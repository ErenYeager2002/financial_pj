from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from compress import compress_pdf, CompressionError


def main():
    if sys.platform == "linux":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    item = request["files"]["pdf_file"]
    if not isinstance(item, dict):
        raise CompressionError("请上传一份 PDF。")
    output = Path(request["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    stem = Path(item["name"].replace("\\", "/")).stem
    name = stem.encode("utf-8")[:200].decode("utf-8", errors="ignore") + "_压缩.pdf"
    target = output / name
    def progress(message):
        print(json.dumps({"type":"progress", "message":message, "state":"running"},ensure_ascii=False),flush=True)
    details = compress_pdf(Path(item["local_path"]), target, progress)
    result = {"status":"success", "summary":{k:v for k,v in details.items() if k!="warnings"},
              "output_files":[{"name":name,"path":str(target.resolve())}], "warnings":details["warnings"]}
    Path(args.result).write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")

if __name__ == "__main__":
    try:
        main()
    except CompressionError as exc:
        raise SystemExit(str(exc))
