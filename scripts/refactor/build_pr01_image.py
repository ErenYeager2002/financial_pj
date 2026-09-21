"""Build a finance-only PR-01 image from a pinned, already-local runtime image.

Send only explicit source paths to Docker; never include .env or business data.
No running service is changed. This transitional image preserves runtime
libraries while PR-01 separates startup checks from schema migration.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = "deployment/Dockerfile.refactor-pr01"
SOURCES = (
    DOCKERFILE, "backend/app/auth_service.py", "backend/app/database.py",
    "backend/app/main.py", "backend/app/worker.py", "backend/app/task_discovery_worker.py",
    "backend/app/infrastructure", "backend/alembic",
)


def build_context(profile="release"):
    sources = SOURCES if profile == "release" else ("deployment/Dockerfile.refactor-pr01-rollback", "backend/app/database.py", "backend/app/infrastructure", "backend/alembic")
    files = []
    for relative in sources:
        path = ROOT / relative
        candidates = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                raise RuntimeError("Build source must be a regular file")
            if not candidate.resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError("Build source escaped repository")
            files.append(candidate)
    buffer = io.BytesIO()
    hashes = {}
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            entry = tarfile.TarInfo(relative)
            entry.size = len(data)
            entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(data))
            hashes[relative] = hashlib.sha256(data).hexdigest()
    return buffer.getvalue(), hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--profile", choices=("release", "rollback"), default="release")
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.base_image):
        parser.error("base-image must be an exact local digest")
    if not re.fullmatch(r"financial-platform-isolated-backend:refactor-pr01-[a-zA-Z0-9_.-]+", args.tag):
        parser.error("tag must be a dedicated finance PR-01 tag")
    subprocess.run(["docker", "image", "inspect", args.base_image], stdout=subprocess.DEVNULL, check=True)
    base_tag = "financial-platform-isolated-backend:refactor-pr01-base-" + args.base_image.split(":", 1)[1]
    subprocess.run(["docker", "tag", args.base_image, base_tag], check=True)
    resolved = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", base_tag], text=True).strip()
    if resolved != args.base_image:
        raise RuntimeError("Pinned local base image changed")
    context, hashes = build_context(args.profile)
    dockerfile = DOCKERFILE if args.profile == "release" else "deployment/Dockerfile.refactor-pr01-rollback"
    subprocess.run(["docker", "build", "--pull=false", "--network=none", "--build-arg", "BASE_IMAGE="+base_tag,
        "-f", dockerfile, "-t", args.tag, "-"], input=context, check=True)
    image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", args.tag], text=True).strip()
    print(json.dumps({"profile": args.profile, "base_image": args.base_image, "image_id": image, "source_hashes": hashes}, sort_keys=True))


if __name__ == "__main__":
    main()
