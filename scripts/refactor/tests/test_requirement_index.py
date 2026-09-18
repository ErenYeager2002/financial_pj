import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from index_requirements import index

class RequirementIndexTests(unittest.TestCase):
    def test_all_named_gates_are_indexed(self):
        guide=Path(__file__).resolve().parents[3]/'docs/refactor/execution-guide.md'
        ids={x['id'] for x in index(guide.read_text(encoding='utf-8-sig'))}
        expected={f'PR-{i:02d}' for i in range(22)}
        for prefix,count in [('T',90),('I',30),('G',16)]: expected.update(f'{prefix}{i:02d}' for i in range(1,count+1))
        self.assertFalse(expected-ids, sorted(expected-ids))
    def test_index_never_marks_implementation_passed(self):
        rows=index('## Phase\n1. Must validate\n| T01 | required |\n')
        self.assertEqual(len(rows),2)
        self.assertTrue(all(x['status']=='unverified' and x['evidence']==[] for x in rows))
