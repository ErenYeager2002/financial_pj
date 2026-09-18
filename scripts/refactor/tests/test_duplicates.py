import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from duplicate_report import shingles, similarity

class DuplicateTests(unittest.TestCase):
    def test_format_and_comments_ignored(self):
        a = shingles(b"def f(x):\n return x + 1\n")
        b = shingles(b"# comment\ndef f( x ):\n    return x+1 # tail\n")
        self.assertEqual(similarity(a,b),1)
    def test_changed_amount_is_not_equivalent(self):
        self.assertLess(similarity(shingles(b"def f(x):\n return x + 1\n"),shingles(b"def f(x):\n return x + 100\n")),1)
    def test_empty_not_duplicate(self):
        self.assertEqual(similarity(set(),set()),0)
