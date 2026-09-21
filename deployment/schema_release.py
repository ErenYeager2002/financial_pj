"""Immutable, finance-only configuration plan for a reviewed schema release."""
from dataclasses import dataclass
import hashlib
import json
import re

import yaml

from maintenance_flow import DeploymentFailure

SCHEMA_SERVICES = ("api", "worker-standard", "worker-task-discovery")


@dataclass(frozen=True)
class SchemaRelease:
    original_sha256: str
    compose_text: str
    image_id: str
    expected_revision: str
    target_revision: str
    agent_image_id: str | None = None

    @classmethod
    def prepare(cls, original: str, image_id: str, expected: str, target: str, *, agent_image_id: str | None = None):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise DeploymentFailure("Schema release requires a resolved local image digest")
        if not re.fullmatch(r"[a-zA-Z0-9_]{1,32}", expected) or not re.fullmatch(r"[a-zA-Z0-9_]{1,32}", target) or target in {"head", "heads", "base", "none"}:
            raise DeploymentFailure("Schema release requires exact reviewed revisions")
        if agent_image_id is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", agent_image_id):
            raise DeploymentFailure("Agent release requires a resolved local image digest")
        selected = dict.fromkeys(SCHEMA_SERVICES, image_id)
        if agent_image_id is not None:
            selected["worker-agent"] = agent_image_id
        document = yaml.safe_load(original)
        if not isinstance(document, dict) or document.get("name") != "financial-platform-isolated":
            raise DeploymentFailure("Schema release deployment identity mismatch")
        services = document.get("services", {})
        if not all(isinstance(services.get(name), dict) for name in selected):
            raise DeploymentFailure("Schema release service set is incomplete")
        candidate = original
        for name, selected_image in selected.items():
            pattern = re.compile(r"(?m)(^  " + re.escape(name) + r":\s*\n)(.*?)(?=^  [A-Za-z0-9_-]+:|^\S|\Z)", re.S)
            matches = list(pattern.finditer(candidate))
            if len(matches) != 1:
                raise DeploymentFailure("Schema release requires explicit service blocks")
            match = matches[0]
            block, count = re.subn(r"(?m)^    image:[^\n]*$", "    image: " + selected_image, match.group(2))
            if count != 1:
                raise DeploymentFailure("Schema release requires one explicit image per service")
            candidate = candidate[:match.start(2)] + block + candidate[match.end(2):]
        changed = yaml.safe_load(candidate)
        for name, service in services.items():
            expected_service = dict(service)
            if name in selected:
                expected_service["image"] = selected[name]
            if changed["services"].get(name) != expected_service:
                raise DeploymentFailure("Schema release changed an unrelated service setting")
        return cls(hashlib.sha256(original.encode()).hexdigest(), candidate, image_id, expected, target, agent_image_id)

    def overlay_text(self):
        # A one-off migration uses the new API image without publishing config yet.
        return json.dumps({"services": {"api": {"image": self.image_id}}}) + "\n"

    def migration_arguments(self):
        return ["-m", "app.infrastructure.database.cli", "--dialect", "postgresql",
                "--host", "postgres", "--port", "5432", "--database", "financial",
                "--expected-revision", self.expected_revision, "--target-revision", self.target_revision]
