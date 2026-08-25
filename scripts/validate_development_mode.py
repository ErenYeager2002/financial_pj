from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = PROJECT_ROOT / "deploy" / "development" / "compose.yaml"
LAN_COMPOSE_PATH = PROJECT_ROOT / "deploy" / "development" / "compose.lan.yaml"
PRODUCTION_COMPOSE_PATH = PROJECT_ROOT / "deploy" / "production" / "compose.yaml"
DEV_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "dev.ps1"
DEV_STOP_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "dev-stop.ps1"


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!override", _construct_override)


def _command_text(service: dict[str, Any]) -> str:
    command = service.get("command", "")
    if isinstance(command, list):
        return " ".join(str(item) for item in command)
    return str(command)


def _environment(service: dict[str, Any]) -> dict[str, str]:
    value = service.get("environment", {})
    if not isinstance(value, dict):
        raise TypeError("service environment must use mapping form")
    return {str(key): str(item) for key, item in value.items()}


def validate() -> None:
    required_files = [
        COMPOSE_PATH,
        LAN_COMPOSE_PATH,
        PRODUCTION_COMPOSE_PATH,
        DEV_SCRIPT_PATH,
        DEV_STOP_SCRIPT_PATH,
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required_files if not path.is_file()]
    if missing:
        raise AssertionError(f"missing development mode files: {', '.join(missing)}")

    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    if compose.get("name") != "financial-platform-dev":
        raise AssertionError("development Compose must use an isolated project name")

    services = compose.get("services", {})
    required_services = {
        "postgres",
        "migrate",
        "egress-proxy",
        "api",
        "worker-python",
        "worker-http",
        "worker-workflow",
        "worker-task-discovery",
        "next",
    }
    missing_services = sorted(required_services - set(services))
    if missing_services:
        raise AssertionError(f"missing development services: {', '.join(missing_services)}")

    api = services["api"]
    next_service = services["next"]
    if "--reload" not in _command_text(api):
        raise AssertionError("development API must enable uvicorn reload")
    if "pnpm dev" not in _command_text(next_service):
        raise AssertionError("development frontend must use pnpm dev")

    for worker_name in (
        "worker-python",
        "worker-http",
        "worker-workflow",
        "worker-task-discovery",
    ):
        if services[worker_name].get("profiles") != ["tasks"]:
            raise AssertionError(f"{worker_name} must be opt-in through the tasks profile")
        worker_command = _command_text(services[worker_name])
        if "watchfiles" in worker_command:
            raise AssertionError(
                f"{worker_name} must not hot-reload while a task may be running"
            )
        expected_module = (
            "python -m app.task_discovery_worker"
            if worker_name == "worker-task-discovery"
            else "python -m app.worker"
        )
        if expected_module not in worker_command:
            raise AssertionError(f"{worker_name} must run the stable platform Worker directly")
    if services["egress-proxy"].get("profiles") != ["tasks"]:
        raise AssertionError("egress-proxy must be opt-in through the tasks profile")
    if "pnpm exec tsc -p tsconfig.json --watch" not in _command_text(next_service):
        raise AssertionError("agent runtime must rebuild incrementally while development is running")

    backend_environment = compose.get("x-backend-environment", {})
    if str(backend_environment.get("FINANCIAL_ENV")) != "development":
        raise AssertionError("development backend must set FINANCIAL_ENV=development")
    if str(backend_environment.get("FINANCIAL_AUTH_MODE")) != "${FINANCIAL_AUTH_MODE:-clerk}":
        raise AssertionError("development backend must expose the selected authentication mode")
    for key in (
        "FINANCIAL_CLERK_ISSUER",
        "FINANCIAL_CLERK_AUTHORIZED_PARTIES",
        "FINANCIAL_DEV_CLERK_AUTO_PROVISION_ADMIN",
    ):
        if key not in backend_environment:
            raise AssertionError(f"development backend is missing {key}")
    next_environment = _environment(next_service)
    for key in (
        "CLERK_SECRET_KEY",
        "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        "FINANCIAL_AUTH_MODE",
        "FINANCIAL_SESSION_COOKIE",
    ):
        if key not in next_environment:
            raise AssertionError(f"development frontend is missing {key}")
    if str(backend_environment.get("FINANCIAL_SESSION_COOKIE_SECURE")).lower() != "false":
        raise AssertionError("localhost development must use a non-secure session cookie")
    execution_flag = str(backend_environment.get("FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED", ""))
    if not execution_flag.endswith(":-false}"):
        raise AssertionError("real AR reconciliation execution must be disabled by default")
    discovery_flag = str(backend_environment.get("FINANCIAL_TASK_DISCOVERY_ENABLED", ""))
    if not discovery_flag.endswith(":-false}"):
        raise AssertionError("real task discovery must be disabled by default")

    for service_name, service in services.items():
        for port in service.get("ports", []):
            if not str(port).startswith("127.0.0.1:"):
                raise AssertionError(f"{service_name} exposes a non-loopback development port")

    lan_compose = yaml.load(LAN_COMPOSE_PATH.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    lan_services = lan_compose.get("services", {})
    lan_api_ports = [str(item) for item in lan_services.get("api", {}).get("ports", [])]
    lan_next_ports = [str(item) for item in lan_services.get("next", {}).get("ports", [])]
    if "0.0.0.0:8000:8000" not in lan_api_ports:
        raise AssertionError("LAN Compose must expose the API on port 8000")
    if "0.0.0.0:3000:3000" not in lan_next_ports:
        raise AssertionError("LAN Compose must expose the frontend on port 3000")
    lan_text = LAN_COMPOSE_PATH.read_text(encoding="utf-8")
    if "FINANCIAL_LAN_ORIGIN:?" not in lan_text:
        raise AssertionError("LAN Compose must require an explicit LAN origin")
    for local_origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        if local_origin not in lan_text:
            raise AssertionError(f"LAN Compose must preserve the local origin {local_origin}")

    backend_volumes = compose.get("x-backend", {}).get("volumes", [])
    joined_volumes = "\n".join(str(item) for item in backend_volumes)
    if "data/development" not in joined_volumes:
        raise AssertionError("development platform files must use data/development")
    if "FINANCIAL_DATA_DIR" in joined_volumes:
        raise AssertionError("development mode must not mount the production data directory")
    production_text = PRODUCTION_COMPOSE_PATH.read_text(encoding="utf-8")
    if "pnpm dev" in production_text or "--reload" in production_text:
        raise AssertionError("production Compose must not enable development reload behavior")

    dev_script = DEV_SCRIPT_PATH.read_text(encoding="utf-8")
    stop_script = DEV_STOP_SCRIPT_PATH.read_text(encoding="utf-8")
    for marker in (
        "ValidateOnly",
        "RestartWorkers",
        "ResetFrontendCache",
        "financial-platform-dev_next-cache",
        'ValidateSet("Core", "Tasks")',
        '"--profile", "tasks"',
        "--force-recreate",
        "deploy\\development\\compose.yaml",
        "-Lan",
        "LanInterfaceAlias",
        "compose.lan.yaml",
    ):
        if marker not in dev_script:
            raise AssertionError(f"scripts/dev.ps1 is missing {marker}")
    if "RemoveData" not in stop_script:
        raise AssertionError("scripts/dev-stop.ps1 must preserve data unless explicitly requested")


def main() -> int:
    try:
        validate()
    except (AssertionError, OSError, yaml.YAMLError) as exc:
        print(f"development mode configuration: invalid: {exc}")
        return 1
    print("development mode configuration: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
