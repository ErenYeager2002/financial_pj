"""Synthetic repositories only; inventory must not execute project code."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import inventory, python_record, tracked_files

class InventoryTests(unittest.TestCase):
    def test_structure_without_literals_or_execution(self):
        source = """from .service import execute as invoke
raise RuntimeError('must-never-execute')
@router.post('/api/items')
async def create(db):
    invoke('synthetic-sensitive-value')
    db.commit()
"""
        value = python_record('app/routes.py', source)
        self.assertEqual(value['routes'][0]['symbol'], 'create')
        self.assertEqual(value['routes'][0]['path'], '/api/items')
        self.assertEqual(value['side_effect_hints'][0]['callee'], 'db.commit')
        self.assertNotIn('synthetic-sensitive-value', json.dumps(value))
        self.assertNotIn('must-never-execute', json.dumps(value))

    def test_nested_caller_and_syntax_error(self):
        value = python_record('a.py', 'class Service:\n    def save(self, db):\n        db.flush()\n')
        self.assertEqual(value['calls'][0]['caller'], 'Service.save')
        self.assertEqual(python_record('bad.py', 'def (')['parse_error']['line'], 1)

    def test_only_tracked_safe_sources(self):
        with tempfile.TemporaryDirectory(prefix='financial-refactor-inventory-') as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            for name in ['safe.py', 'untracked.py', '.env', 'data/private.py', '.scratch/log.py', 'credential.key']:
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('SENSITIVE = "synthetic-only"\n')
            (root/'linked.py').symlink_to(root/'data/private.py')
            subprocess.run(['git', '-C', str(root), 'add', 'safe.py', '.env', 'data', '.scratch', 'credential.key', 'linked.py'], check=True)
            self.assertEqual(tracked_files(root), ['safe.py'])

if __name__ == '__main__': unittest.main()
