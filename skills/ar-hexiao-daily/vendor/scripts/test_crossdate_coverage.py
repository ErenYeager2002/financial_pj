import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import classify_hexiao as C
import build_task_reports as R

class CrossDateCoverage(unittest.TestCase):
    def test_filtered_writeoffs_cannot_hide_source_order(self):
        p = {"ar": "AR_TEST", "orders": [{"so": "SO_A"}, {"so": "SO_B"}],
             "writeoffs": {"SO_A": 10},
             "_source_order_keys_by_date": {"2026-08-29": ["AR_TEST|SO_A", "AR_TEST|SO_B"]},
             "hexiao_date": dt.date(2026, 8, 29)}
        with self.assertRaises(C.CoverageError):
            C.source_coverage([p], [{"ar": "AR_TEST", "so": "SO_A"}])

    def test_range_audit_finds_shifted_order_missing_from_earlier_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            earlier = {"auto": [], "hold": [], "exception": []}
            later = {"auto": [{"ar": "AR_TEST", "so": "SO_B"}],
                     "source_coverage": {"source_order_keys_by_date": {
                         "2026-08-29": ["AR_TEST|SO_A"], "2026-08-30": ["AR_TEST|SO_B"]}}}
            # Raw shifted rows can include a revoked record absent from audited sources.
            later["shifted_detail_dates"] = {"2026-08-29": {"order_keys": ["AR_TEST|SO_REVOKED"]}}
            for stamp, value in [("20260829", earlier), ("20260830", later)]:
                (out / f"判定结果_{stamp}.json").write_text(json.dumps(value))
            days = [dt.date(2026,8,29),dt.date(2026,8,30)]
            self.assertEqual(R.source_coverage_issues(out, days), [("2026-08-29", "AR_TEST", "SO_A")])
            earlier["hold"] = [{"ar": "AR_TEST", "so": "SO_A"}]
            (out / "判定结果_20260829.json").write_text(json.dumps(earlier))
            self.assertEqual(R.source_coverage_issues(out, days), [])
            self.assertEqual(R.source_coverage_issues(out, days[1:]), [])

if __name__ == "__main__": unittest.main()
