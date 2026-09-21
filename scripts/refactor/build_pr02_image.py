"""Build the PR-02 finance candidate with a restricted source-only context."""
import argparse
import ast
import json
import re
import subprocess
import build_pr01_image as context_builder

ROOT = context_builder.ROOT
DOCKERFILE = "deployment/Dockerfile.refactor-pr02"
SOURCES = (DOCKERFILE, *(
    "backend/app/" + name for name in (
        "adapters.py", "draft_service.py", "events.py", "main.py",
        "routers/assistant.py", "run_service.py", "worker.py",
    )
))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.base_image):
        parser.error("base-image must be an exact local image ID")
    if not re.fullmatch(r"financial-platform-isolated-backend:refactor-pr02-[a-zA-Z0-9_.-]+", args.tag):
        parser.error("requires dedicated finance PR-02 tag")
    for name in SOURCES:
        if name.endswith(".py"):
            ast.parse((ROOT / name).read_text(encoding="utf-8"))
    subprocess.run(["docker", "image", "inspect", args.base_image], stdout=subprocess.DEVNULL, check=True)
    base_tag = "financial-platform-isolated-backend:refactor-pr02-base-" + args.base_image.split(":")[1]
    subprocess.run(["docker", "tag", args.base_image, base_tag], check=True)
    resolved = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", base_tag], text=True).strip()
    if resolved != args.base_image:
        raise RuntimeError("Pinned local base changed")
    context_builder.SOURCES = SOURCES
    content, hashes = context_builder.build_context()
    subprocess.run(["docker", "build", "--pull=false", "--network=none", "--build-arg", "BASE_IMAGE=" + base_tag,
        "-f", DOCKERFILE, "-t", args.tag, "-"], input=content, check=True)
    image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", args.tag], text=True).strip()
    report = {"stage": "PR-02", "base_image": args.base_image, "image_id": image, "source_hashes": hashes}
    (ROOT / "docs/refactor/reports/PR-02-image.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))

if __name__ == "__main__":
    main()
