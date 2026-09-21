import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from duplicate_report import shingles, similarity, provenance

class DuplicateTests(unittest.TestCase):
    def test_format_and_comments_ignored(self):
        a = shingles(b"def f(x):\n return x + 1\n")
        b = shingles(b"# comment\ndef f( x ):\n    return x+1 # tail\n")
        self.assertEqual(similarity(a,b),1)
    def test_changed_amount_is_not_equivalent(self):
        self.assertLess(similarity(shingles(b"def f(x):\n return x + 1\n"),shingles(b"def f(x):\n return x + 100\n")),1)
    def test_empty_not_duplicate(self):
        self.assertEqual(similarity(set(),set()),0)

    def test_vendor_mapping_preserves_distinct_package_identity(self):
        name='skills/ar-hexiao-daily-lab/vendor/scripts/apply_all.py'
        facts=provenance(name,{'skills/ar-hexiao-daily-lab/VERSION.json'})
        self.assertTrue(facts['vendor'])
        self.assertEqual(facts['comparison_relative_path'],'scripts/apply_all.py')
        self.assertEqual(facts['skill_id'],'ar-hexiao-daily-lab')
        self.assertFalse(facts['authority_verified'])
        self.assertEqual(facts['provenance_evidence'],['skills/ar-hexiao-daily-lab/VERSION.json'])

    def test_source_root_and_license_are_evidence_not_authority(self):
        facts=provenance('sources/finance-skills/skills/ar-hexiao-daily/scripts/apply_all.py',{'sources/finance-skills/LICENSE','sources/finance-skills/SOURCE.md'})
        self.assertEqual(facts['relative_path'],'scripts/apply_all.py')
        self.assertEqual(facts['role'],'source-tree')
        self.assertEqual(len(facts['provenance_evidence']),2)
        self.assertTrue(facts['protected'])
