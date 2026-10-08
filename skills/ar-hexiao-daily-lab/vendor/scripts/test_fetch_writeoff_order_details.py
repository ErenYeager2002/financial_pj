import unittest
from unittest.mock import Mock,patch
import fetch_zhiyun as Z

class WriteoffOrderDetails(unittest.TestCase):
    def test_exact_order_full_details_returned(self):
        c=Mock();c.search_rows.return_value=[{'rowid':'source'}]
        details=dict(so='SO_TARGET',deliver=123,deliver_local=123,delivery_date='2026-05-21',currency='CNY')
        with patch.object(Z,'extract_related_orders',return_value=[dict(so='SO_OTHER'),details]):
            self.assertEqual(Z.lookup_order_details(c,'ws',[], 'SO_TARGET'),details)
        c.search_rows.assert_called_once_with('ws','SO_TARGET')
    def test_conflicting_details_never_choose_first(self):
        with patch.object(Z,'extract_related_orders',return_value=[dict(so='SO_TARGET',delivery_date='2026-05-21'),dict(so='SO_TARGET',delivery_date='2026-05-22')]):
            with self.assertRaises(Z.FetchError):Z.lookup_order_details(Mock(),'ws',[],'SO_TARGET')
    def test_missing_order_stays_missing(self):
        with patch.object(Z,'extract_related_orders',return_value=[]):
            self.assertIsNone(Z.lookup_order_details(Mock(),'ws',[],'SO_TARGET'))
    def test_identical_duplicate_details_are_not_conflicting(self):
        d=dict(so='SO_TARGET',delivery_date='2026-05-21')
        with patch.object(Z,'extract_related_orders',return_value=[d,dict(d)]):
            self.assertEqual(Z.lookup_order_details(Mock(),'ws',[],'SO_TARGET'),d)
if __name__=='__main__':unittest.main()
