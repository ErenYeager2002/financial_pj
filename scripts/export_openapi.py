from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_OUTPUT = PROJECT_ROOT / "contracts" / "financial-platform.openapi.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app


def rendered_openapi() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="导出财务平台稳定 OpenAPI 契约")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查目标文件是否与当前 FastAPI 契约一致，不写文件。",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    rendered = rendered_openapi()
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print(f"OpenAPI 契约需要重新生成：{output}", file=sys.stderr)
            return 1
        print(f"OpenAPI 契约一致：{output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"OpenAPI 契约已生成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
