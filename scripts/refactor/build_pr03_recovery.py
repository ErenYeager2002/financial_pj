"""Build a distinct, explicitly degraded finance recovery image from a verified core."""
import argparse
import json
import re
import subprocess
import build_pr01_image as context_builder

ROOT = context_builder.ROOT
DOCKERFILE = "deployment/Dockerfile.refactor-pr03-recovery"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--stage", choices=["PR-03","PR-04"], default="PR-03")
    args = parser.parse_args()
    stage_slug = args.stage.lower().replace("-", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.base_image):
        parser.error("requires an exact already-verified candidate digest")
    if not re.fullmatch(rf"financial-platform-isolated-backend:refactor-{stage_slug}-recovery-[a-zA-Z0-9_.-]+", args.tag):
        parser.error("requires a dedicated recovery tag")
    base = "financial-platform-isolated-backend:refactor-pr03-recovery-base-" + args.base_image.split(":")[1]
    subprocess.run(["docker", "tag", args.base_image, base], check=True)
    resolved = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", base], text=True).strip()
    if resolved != args.base_image:
        raise RuntimeError("Recovery base changed")
    context_builder.SOURCES = (DOCKERFILE,)
    context, hashes = context_builder.build_context()
    subprocess.run(["docker", "build", "--pull=false", "--network=none", "--build-arg", "BASE_IMAGE=" + base,
        "-f", DOCKERFILE, "-t", args.tag, "-"], input=context, check=True)
    image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", args.tag], text=True).strip()
    if image == args.base_image:
        raise RuntimeError("Recovery image must have a distinct enforced policy")
    report = {"image_id":image, "base_candidate":args.base_image, "mode":"replay-only",
        "schema_revision":"f4b5c6d7e8f9", "source_hashes":hashes,
        "limitation":f"Shared {args.stage} safety core, including execution authorization. Blocks unbound ordinary submissions; not old-code rollback or full service restoration."}
    (ROOT / f"docs/refactor/reports/{args.stage}-recovery-image.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
