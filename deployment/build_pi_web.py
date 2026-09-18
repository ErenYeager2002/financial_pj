"""Build only reviewed Pi web overlays on the recorded published source baseline."""
from pathlib import Path
import hashlib
import io
import os
import json
import subprocess
import tarfile

source = Path(__file__).resolve().parents[1]
root = source.parents[2]
baseline = root / 'publications/platform-sync-20260917'
manifest_path = source / 'deployment/pi-web-build-manifest.json'
manifest = json.loads(manifest_path.read_text())
assert subprocess.check_output(['git', '-C', str(baseline), 'rev-parse', 'HEAD'], text=True).strip() == manifest['baseline_commit']
assert not subprocess.check_output(['git', '-C', str(baseline), 'status', '--porcelain', '--', 'web/src', 'web/public']).strip()
overlays = list(manifest['overlays'])
manifest['overlays'] = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in overlays}
manifest_path.write_text(json.dumps(manifest, indent=2))
dockerfile = (source / 'deployment/Dockerfile.pi-web').read_bytes()
archive = io.BytesIO()
with tarfile.open(fileobj=archive, mode='w') as context:
    item = tarfile.TarInfo('Dockerfile'); item.size = len(dockerfile)
    context.addfile(item, io.BytesIO(dockerfile))
    for folder in ['web/src', 'web/public']:
        for path in (baseline / folder).rglob('*'):
            if path.is_file() and str(path.relative_to(baseline)) not in overlays:
                context.add(path, arcname=str(path.relative_to(baseline)))
    for name in overlays + ['web/package.json', 'web/pnpm-lock.yaml', 'web/pnpm-workspace.yaml', 'web/.npmrc']:
        context.add(source / name, arcname=name)
print('Building scoped Pi web image', flush=True)
result = subprocess.run(['docker', 'build', '-t', os.environ.get('PI_WEB_IMAGE', 'financial-platform-isolated-next:pi-workspace-20260917'), '-'], input=archive.getvalue(), capture_output=True)
if result.returncode:
    print(result.stderr.decode(errors='replace')[-6000:])
    raise SystemExit(result.returncode)
print('Pi web production build and TypeScript checks passed', flush=True)
