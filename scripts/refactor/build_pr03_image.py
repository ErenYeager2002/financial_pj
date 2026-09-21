"""Build the PR-03 finance candidate with a restricted source-only context."""
import argparse
import ast
import json
import re
import subprocess
import build_pr01_image as context_builder

ROOT = context_builder.ROOT
DOCKERFILE = "deployment/Dockerfile.refactor-pr03"
SOURCES = (DOCKERFILE, "backend/app", "backend/alembic")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--stage", choices=["PR-03","PR-04"], default="PR-03")
    args = parser.parse_args()
    stage_slug = args.stage.lower().replace("-", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.base_image):
        parser.error("base-image must be an exact local image ID")
    if not re.fullmatch(rf"financial-platform-isolated-backend:refactor-{stage_slug}-[a-zA-Z0-9_.-]+", args.tag):
        parser.error("requires dedicated finance PR-03 tag")
    for relative in SOURCES:
        path = ROOT / relative
        for candidate in path.rglob("*.py") if path.is_dir() else [path]:
            if candidate.suffix == ".py":
                ast.parse(candidate.read_text(encoding="utf-8"))
    subprocess.run(["docker", "image", "inspect", args.base_image], stdout=subprocess.DEVNULL, check=True)
    base_tag = "financial-platform-isolated-backend:refactor-pr03-base-" + args.base_image.split(":")[1]
    subprocess.run(["docker", "tag", args.base_image, base_tag], check=True)
    resolved = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", base_tag], text=True).strip()
    if resolved != args.base_image:
        raise RuntimeError("Pinned local base changed")
    context_builder.SOURCES = SOURCES
    content, hashes = context_builder.build_context()
    subprocess.run(["docker", "build", "--pull=false", "--network=none", "--build-arg", "BASE_IMAGE=" + base_tag,
        "-f", DOCKERFILE, "-t", args.tag, "-"], input=content, check=True)
    image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", args.tag], text=True).strip()
    report = {"stage": args.stage, "base_image": args.base_image, "image_id": image, "source_hashes": hashes}
    (ROOT / f"docs/refactor/reports/{args.stage}-image.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
