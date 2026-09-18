"""Read tracked source without importing it or traversing runtime data."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

EXCLUDED = {".git", ".venv", "node_modules", "data", ".scratch", ".pnpm-store", "__pycache__", "工作区"}
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".cjs", ".mjs", ".css", ".yaml", ".yml", ".toml", ".json", ".ps1", ".sh", ".service", ".mount", ".slice", ".md"}

def tracked_files(root):
    names = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode().split("\0")
    result = []
    for name in names:
        if not name: continue
        path = root / name
        if EXCLUDED.intersection(Path(name).parts) or path.name.startswith(".env") or path.name == "credential.key": continue
        if any(p.is_symlink() for p in [path, *path.parents]) or not path.is_file(): continue
        if root.resolve() not in path.resolve().parents: continue
        if path.suffix not in EXTENSIONS and not path.name.startswith("Dockerfile"): continue
        result.append(name)
    return sorted(result)

def call_name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return call_name(node.value) + "." + node.attr
    return "<dynamic>"

def python_record(path, text):
    record = {"symbols": [], "imports": [], "calls": [], "routes": [], "side_effect_hints": []}
    try: tree = ast.parse(text, filename=path)
    except SyntaxError as error:
        record["parse_error"] = {"line": error.lineno, "kind": type(error).__name__}
        return record
    class Visitor(ast.NodeVisitor):
        scope = []
        def visit_FunctionDef(self, node):
            name = ".".join([*self.scope, node.name])
            record["symbols"].append({"symbol": name, "kind": type(node).__name__, "start": node.lineno, "end": node.end_lineno})
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in {"get", "post", "put", "patch", "delete", "websocket"}:
                    route = decorator.args[0].value if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str) else "<dynamic>"
                    record["routes"].append({"method": decorator.func.attr, "path": route, "symbol": name, "line": node.lineno})
            self.scope.append(node.name); self.generic_visit(node); self.scope.pop()
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_ClassDef(self, node):
            record["symbols"].append({"symbol": ".".join([*self.scope, node.name]), "kind": "ClassDef", "start": node.lineno, "end": node.end_lineno})
            self.scope.append(node.name); self.generic_visit(node); self.scope.pop()
        def visit_Import(self, node):
            record["imports"].extend({"module": a.name, "alias": a.asname, "line": node.lineno} for a in node.names)
        def visit_ImportFrom(self, node):
            record["imports"].append({"module": "." * node.level + (node.module or ""), "names": [a.name for a in node.names], "line": node.lineno})
        def visit_Call(self, node):
            name = call_name(node.func)
            entry = {"caller": ".".join(self.scope) or "<module>", "callee": name, "line": node.lineno}
            record["calls"].append(entry)
            tail = name.rsplit(".", 1)[-1]
            if tail in {"commit", "rollback", "flush", "execute", "Popen", "run", "write_text", "write_bytes", "open", "unlink", "rmtree", "replace", "import_module", "__import__"}:
                record["side_effect_hints"].append(entry)
            self.generic_visit(node)
    Visitor().visit(tree)
    return record

def inventory(root):
    records = []
    for name in tracked_files(root):
        path = root / name
        try: text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError: continue
        item = {"path": name, "language": path.suffix.lstrip("."), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "lines": len(text.splitlines()), "vendor": "vendor" in path.parts or name.startswith("sources/"), "generated": path.name in {"generated.ts", "pnpm-lock.yaml", "SHA256SUMS.json"}, "symbols": [], "imports": [], "side_effect_hints": []}
        if path.suffix == ".py": item.update(python_record(name, text))
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"}: item["typescript_ast"] = "pending_node_scanner"
        records.append(item)
    return {"schema_version": "source-inventory-v1", "commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), "coverage": "tracked source only; static calls are not proof of runtime use", "files": records}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    md = args.output.with_suffix(".md")
    md.write_text("# Tracked source inventory\n\nStatic evidence; no runtime absence inference.\n\n| Path | Lines | Symbols | Effects |\n|---|---:|---:|---:|\n" + "".join(f"| {x['path']} | {x['lines']} | {len(x['symbols'])} | {len(x['side_effect_hints'])} |\n" for x in result["files"]))
    print(json.dumps({"files": len(result["files"]), "parse_errors": sum("parse_error" in x for x in result["files"])}))
