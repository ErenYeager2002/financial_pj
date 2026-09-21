"""Duplicate candidates only: never deletes files or treats similarity as equivalence."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
import io
import tokenize
import subprocess
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



def provenance(name, files):
    """Directory/metadata evidence, not a claim that a source is authoritative."""
    parts = Path(name).parts
    if parts[0] == 'sources' and len(parts) > 4 and parts[2] == 'skills':
        package = '/'.join(parts[:4]); relative = '/'.join(parts[4:]); skill = parts[3]
        role = 'source-tree'
    else:
        package = '/'.join(parts[:2]); relative = '/'.join(parts[2:]); skill = parts[1]
        role = {'skills':'platform-package','standalone-skills':'standalone-package','native-skill-overrides':'native-override'}.get(parts[0],'source-repository-metadata')
    vendor = relative.startswith('vendor/')
    comparison = relative.removeprefix('vendor/')
    evidence = []
    parent = Path(name).parent
    while parent != Path('.'):
        for metadata in ['SOURCE.md','LICENSE','LICENSE.md','NOTICE','VERSION.json','SHA256SUMS.json']:
            candidate = (parent / metadata).as_posix()
            if candidate in files: evidence.append(candidate)
        parent = parent.parent
    return {'path':name,'root':parts[0],'package':package,'skill_id':skill,
            'relative_path':relative,'comparison_relative_path':comparison,
            'role':role,'vendor':vendor,
            'generated_metadata':Path(name).name in {'SHA256SUMS.json'},
            'provenance_evidence':evidence,'authority_verified':False,
            'license_review_required':True,'protected':True}

def report(root):
    exact, normalized = defaultdict(list), defaultdict(list)
    families = defaultdict(list)
    files = tracked_files(root)
    evidence_files = set(subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines())
    metadata = []
    relative_groups = defaultdict(list)
    for name in files:
        if not name.startswith(("skills/", "sources/", "standalone-skills/", "native-skill-overrides/")): continue
        path = root / name
        if path.suffix not in {".py", ".ts", ".tsx", ".js", ".json", ".md", ".yaml"}: continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        item = provenance(name, evidence_files)
        item["sha256"] = digest
        metadata.append(item)
        relative_groups[item["comparison_relative_path"]].append(item)
        exact[digest].append(name)
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
    return {"files":metadata, "relative_path_groups":[{"relative_path":key,"members":members,"same_bytes":len({x["sha256"] for x in members}) == 1,"relationship":"candidate-only; skill identity and provenance need review"} for key,members in sorted(relative_groups.items()) if len(members)>1], "near_python_same_basename":near, "near_scope":"Same basename only; token 5-gram Jaccard >= 0.8; renamed files are not covered", "schema_version": "duplicate-candidates-v3", "action": "review_only", "limitations": "AST equivalence excludes formatting only; no semantic equivalence or deletion authorization. Preserve provenance and licenses.", "exact": [{"sha256": h, "paths": p, "protected": True} for h,p in exact.items() if len(p)>1], "python_ast_equivalent": [{"normalized_sha256": h, "paths": p, "protected": True} for h,p in normalized.items() if len(p)>1]}

if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    value=report(args.root);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n");print(json.dumps({k:len(value[k]) for k in ['exact','python_ast_equivalent']}))
