"""Offline finance frontend release build from pinned local dependency/runtime images."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = "deployment/Dockerfile.refactor-pr03-web"
FILES = (DOCKERFILE, "web/package.json", "web/pnpm-lock.yaml", "web/pnpm-workspace.yaml", "web/.npmrc", "web/next.config.ts", "web/tsconfig.json", "web/postcss.config.js")
DIRECTORIES = ("web/src", "web/public", "web/tests")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builder",required=True)
    parser.add_argument("--runtime",required=True)
    parser.add_argument("--tag",required=True)
    args=parser.parse_args()
    if not all(re.fullmatch(r"sha256:[0-9a-f]{64}",v) for v in (args.builder,args.runtime)):
        parser.error("exact local image digests required")
    if not re.fullmatch(r"financial-platform-isolated-next:refactor-pr03-[a-zA-Z0-9_.-]+",args.tag):
        parser.error("dedicated finance frontend tag required")
    sources=[ROOT/name for name in FILES]
    for name in DIRECTORIES:
        sources.extend(p for p in sorted((ROOT/name).rglob("*")) if not p.is_dir())
    hashes={}
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode="w") as archive:
        for path in sources:
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
                raise RuntimeError("Invalid frontend source path")
            relative=path.relative_to(ROOT).as_posix()
            if any(p.startswith(".env") or p in {"node_modules", ".next", ".git", "__pycache__"} for p in path.relative_to(ROOT).parts):
                raise RuntimeError("Forbidden build source")
            data=path.read_bytes()
            if relative=="web/.npmrc" and any(token in data.lower() for token in (b"_auth",b"password",b"token")):
                raise RuntimeError("Credential-like package configuration rejected")
            hashes[relative]=hashlib.sha256(data).hexdigest()
            entry=tarfile.TarInfo(relative);entry.size=len(data);entry.mode=0o644
            archive.addfile(entry,io.BytesIO(data))
        source_digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
        record={"stage":"PR-03","source_digest":source_digest,"source_hashes":hashes,"builder_image":args.builder,"runtime_image":args.runtime}
        data=(json.dumps(record,sort_keys=True)+"\n").encode()
        entry=tarfile.TarInfo("refactor-build.json");entry.size=len(data);entry.mode=0o644
        archive.addfile(entry,io.BytesIO(data))
    tags={}
    for kind,image in (("builder",args.builder),("runtime",args.runtime)):
        tag="financial-platform-isolated-next:refactor-pr03-"+kind+"-"+image.split(":")[1]
        subprocess.run(["docker","tag",image,tag],check=True)
        resolved=subprocess.check_output(["docker","image","inspect","--format","{{.Id}}",tag],text=True).strip()
        if resolved!=image:raise RuntimeError("Pinned image changed")
        tags[kind]=tag
    subprocess.run(["docker","build","--pull=false","--network=none","--build-arg","BUILDER_IMAGE="+tags["builder"],"--build-arg","RUNTIME_IMAGE="+tags["runtime"],"-f",DOCKERFILE,"-t",args.tag,"-"],input=buffer.getvalue(),check=True)
    record["image_id"]=subprocess.check_output(["docker","image","inspect","--format","{{.Id}}",args.tag],text=True).strip()
    (ROOT/"docs/refactor/reports/PR-03-web-image.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps({k:v for k,v in record.items() if k!="source_hashes"}))


if __name__=="__main__":main()
