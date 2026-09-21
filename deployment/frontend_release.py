"""Pin the one finance frontend service without changing any other Compose value."""
from dataclasses import dataclass
import hashlib
import re
import yaml
from maintenance_flow import DeploymentFailure


@dataclass(frozen=True)
class FrontendRelease:
    original_sha256: str
    compose_text: str
    image_id: str

    @classmethod
    def prepare(cls, original, image_id):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}",image_id):
            raise DeploymentFailure("Frontend release requires an exact local image digest")
        before=yaml.safe_load(original)
        if not isinstance(before,dict) or before.get("name")!="financial-platform-isolated":
            raise DeploymentFailure("Frontend deployment identity mismatch")
        if not isinstance(before.get("services",{}).get("next"),dict):
            raise DeploymentFailure("Frontend service missing")
        pattern=re.compile(r"(?m)(^  next:\s*\n)(.*?)(?=^  [A-Za-z0-9_-]+:|^\S|\Z)",re.S)
        matches=list(pattern.finditer(original))
        if len(matches)!=1:raise DeploymentFailure("Frontend service block is ambiguous")
        match=matches[0]
        block,count=re.subn(r"(?m)^    image:[^\n]*$","    image: "+image_id,match.group(2))
        if count!=1:raise DeploymentFailure("Frontend image field is ambiguous")
        candidate=original[:match.start(2)]+block+original[match.end(2):]
        before["services"]["next"]["image"]=image_id
        if yaml.safe_load(candidate)!=before:
            raise DeploymentFailure("Frontend release changed unrelated configuration")
        return cls(hashlib.sha256(original.encode()).hexdigest(),candidate,image_id)
