"""Verify this distribution without accessing financial data or the network."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'SHA256SUMS.json').read_text(encoding='utf-8'))
errors=[]
for name,wanted in manifest.items():
 p=root/name
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=wanted:errors.append(name)
if errors:raise SystemExit('Package verification failed: '+', '.join(errors))
print('Package verified: '+str(len(manifest))+' files')
