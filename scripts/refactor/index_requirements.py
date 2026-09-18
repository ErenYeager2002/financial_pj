"""Index specification clauses; never infer acceptance from generated files."""
import hashlib
import json
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[2]

def index(text):
    entries = []
    section = 'preamble'
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith('#'): section = line.lstrip('# ').strip()
        match = re.match(r'\|\s*(?:\*\*)?((?:PR-\d{2})|(?:[TGI]\d{2}))(?:\*\*)?\s*\|', line)
        if match:
            entries.append({'id':match.group(1), 'source_line':line_number, 'section':section, 'requirement':line, 'status':'unverified', 'evidence':[]})
        elif re.match(r'^\d+\. ', line):
            entries.append({'id':f'clause-L{line_number}', 'source_line':line_number, 'section':section, 'requirement':line, 'status':'unverified', 'evidence':[]})
    return entries

if __name__ == '__main__':
    guide = ROOT/'docs/refactor/execution-guide.md'
    raw = guide.read_bytes()
    result = {'schema_version':'requirement-index-v1', 'spec_sha256':hashlib.sha256(raw).hexdigest(), 'coverage':'Numbered clauses and PR/T/G/I table rows; prose requirements still require manual audit.', 'entries':index(raw.decode('utf-8-sig'))}
    target = ROOT/'docs/refactor/reports/requirement-index.json'
    if target.exists():
        previous = json.loads(target.read_text())
        if any(x.get('status') != 'unverified' or x.get('evidence') for x in previous.get('entries', [])):
            raise SystemExit('Refusing to overwrite annotated acceptance evidence')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'indexed_clauses':len(result['entries']), 'status':'unverified'}))
