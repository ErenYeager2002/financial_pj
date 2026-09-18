"""Duplicate candidates only: never deletes files or treats similarity as equivalence."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
import io
import tokenize
from itertools import combinations
from pathlib import Path
from inventory import tracked_files

def shingles(raw):
    """Token windows preserve names and literals; formatting/comments are ignored."""
    try:
        tokens = [f"{t.type}:{t.string}" for t in tokenize.generate_tokens(io.StringIO(raw.decode("utf-8-sig")).readline)
                  if t.type not in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}]
    except (UnicodeDecodeError, tokenize.TokenError, IndentationError):
        return set()
    return {hashlib.sha256("\0".join(tokens[i:i+5]).encode()).hexdigest() for i in range(max(0,len(tokens)-4))}


def similarity(left, right):
    return len(left & right) / len(left | right) if left and right else 0.0


def report(root):
    exact, normalized = defaultdict(list), defaultdict(list)
    families = defaultdict(list)
    for name in tracked_files(root):
        if not name.startswith(("skills/", "sources/", "standalone-skills/", "native-skill-overrides/")): continue
        path = root / name
        if path.suffix not in {".py", ".ts", ".tsx", ".js", ".json", ".md", ".yaml"}: continue
        raw = path.read_bytes()
        exact[hashlib.sha256(raw).hexdigest()].append(name)
        if path.suffix == ".py":
            families[path.name].append((name, hashlib.sha256(raw).hexdigest(), shingles(raw)))
            try: normalized[hashlib.sha256(ast.dump(ast.parse(raw.decode("utf-8-sig")), include_attributes=False).encode()).hexdigest()].append(name)
            except (SyntaxError, UnicodeDecodeError): pass
    near = []
    for family in families.values():
        for left,right in combinations(family,2):
            if left[1] == right[1]: continue
            score = similarity(left[2],right[2])
            if score >= 0.8:
                near.append({"paths":[left[0],right[0]], "token_5gram_jaccard":round(score,6), "protected":True, "semantic_equivalence":False})
    return {"near_python_same_basename":near, "near_scope":"Same basename only; token 5-gram Jaccard >= 0.8; renamed files are not covered", "schema_version": "duplicate-candidates-v2", "action": "review_only", "limitations": "AST equivalence excludes formatting only; no semantic equivalence or deletion authorization. Preserve provenance and licenses.", "exact": [{"sha256": h, "paths": p, "protected": True} for h,p in exact.items() if len(p)>1], "python_ast_equivalent": [{"normalized_sha256": h, "paths": p, "protected": True} for h,p in normalized.items() if len(p)>1]}

if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    value=report(args.root);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n");print(json.dumps({k:len(value[k]) for k in ['exact','python_ast_equivalent']}))
