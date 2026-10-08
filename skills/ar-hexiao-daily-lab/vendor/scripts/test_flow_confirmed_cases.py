"""Synthetic regressions for source-confirmed flow registration."""
import datetime as dt
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import openpyxl
import flow_ledger as L
import flow_monthly as M
import flow_source_receipts as S


class ConfirmedFlowCases(unittest.TestCase):
    def test_flow_match_uses_net_arrival_only(self):
        row = {'date': dt.date(2026, 9, 2), 'amount': 105,
               'formula_orig_amount': None, 'payer': '测试甲',
               'company_name': '测试甲', 'remitter': ''}
        flow = L.FlowLedger([row])
        self.assertEqual(flow.match('2026-09-02', 100, customer='测试甲', fee=5)['hits'], 0)
        row['amount'] = 100
        self.assertEqual(flow.match('2026-09-02', 100, customer='测试甲', fee=5)['hits'], 1)

    def test_confirmed_name_mapping_still_requires_arrival_date(self):
        row = {'date': dt.date(2026, 9, 11), 'amount': 124117.50,
               'formula_orig_amount': None, 'payer': '中国人民解放军95851部队保障部',
               'company_name': '中国人民解放军95851部队保障部', 'remitter': ''}
        flow = L.FlowLedger([row])
        flow._load_name_map_sheet([['到账名称', '系统客户名称'], ['中国人民解放军95851部队保障部', '中国人民解放军32068部队']], '已确认映射')
        self.assertEqual(flow.match('2026-09-14', 124117.50,
                                    customer='中国人民解放军32068部队')['hits'], 0)
        row['date'] = dt.date(2026, 9, 14)
        hit = flow.match('2026-09-14', 124117.50,
                         customer='中国人民解放军32068部队')
        self.assertEqual((hit['hits'], hit['matched_by']), (1, '三键(中英文对照)'))

    def test_current_posting_is_found_before_ambiguous_old_carries(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'flow.xlsx'
            book = openpyxl.Workbook()
            ws = book.active
            ws.title = '明细'
            ws.append(['日期', '公司名称', '金额', '收款形式', '单号', '预收', '是否更新应收款'])
            ws.append([dt.date(2026, 2, 6), '测试甲', 157.70, '冲预收', 'SXSOOLD', '157.7-157.7=0', '是'])
            ws.append([dt.date(2026, 9, 8), '测试甲', 140.41, '冲预收', 'SXSO1', '5068.19-140.41=4927.78', '是'])
            book.save(path)
            book.close()
            rec = {'ar': 'AR1', 'so': 'SO1', 'sod': 'SOD1',
                   'shoukuan_date': '2024-10-23', 'hexiao_date': '2026-09-08',
                   'arrival_total': 13288.09, 'amount_orig': 140.41,
                   'currency': '人民币CNY', 'customer': '测试甲',
                   'all_sods': ['SOD1'],
                   'flow_carry_evidence': {'known_sos': ['SOOLD'], 'opening_limit': 13288.09}}
            L.annotate_records([rec], L.FlowLedger.from_paths([path]))
            self.assertEqual((rec['flow_hits'], rec['flow_row_no'], rec['flow_matched_by']),
                             (1, 3, '已登记核销行'))

    def test_existing_posting_with_wrong_arithmetic_is_located_but_not_auto(self):
        row = {'date': dt.date(2026, 9, 8), 'amount': 140.41,
               'payer': '测试甲', 'form': '冲预收', 'order_cell': 'SXSO1',
               'prepayment': '还剩：5068.19-140.41=4928.78'}
        flow = L.FlowLedger([row])
        hit = flow.match_existing_posting({'hexiao_date': '2026-09-08',
                                           'so': 'SO1', 'customer': '测试甲',
                                           'amount_orig': 140.41})
        self.assertEqual((hit['hits'], hit['matched_by']),
                         (1, '已登记SO但预收未通过算术校验'))

    def test_narrated_credit_balance_is_checked_arithmetically(self):
        parsed = M.parsed_balance(
            'SOX 131.12算预付还剩：97651.78+131.12=97782.9-68,962.21=28820.69-0.42=28820.27')
        self.assertEqual(parsed['opening'], Decimal('97782.90'))
        self.assertEqual(parsed['deductions'], [Decimal('68962.21'), Decimal('0.42')])
        self.assertEqual(parsed['remaining'], Decimal('28820.27'))
        with self.assertRaises(ValueError):
            M.parsed_balance('SOX 131.12算预付还剩：97651.78+131.12=97782.9-68,962.21=28820.68')

    def test_confirmed_carry_can_use_parent_company_name(self):
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(['日期', '公司名称', '金额', '收款形式', '单号', '预收', '是否更新应收款'])
        ws.append([dt.date(2026, 8, 17), '测试甲陕西分公司', 5423.87,
                   '汇款', 'JZ转9月', None, None])
        ws.append([dt.date(2026, 9, 14), '测试甲', 5423.87,
                   '冲预收', 'JZSO1', '还剩：3571.33', '是'])
        cols = {'日期': 1, '公司名称': 2, '金额': 3, '收款形式': 4,
                '单号': 5, '预收': 6, '是否更新应收款': 7}
        entry = {'key': 'source|1', 'date': '2026-09-14', 'so': 'SO1', 'amount': '1852.54'}
        item = {'row_no': 2, 'monthly_date': '2026-09-14',
                'monthly_entries': [entry],
                'monthly_receipt_history': {'basis': 'current_source_reconcile',
                                            'date': '2026-09-14', 'opening': '5423.87',
                                            'entries': [entry], 'known_sos': ['SO1']}}
        chain = M.adopt_chain(ws, cols, item)
        self.assertEqual([month['row'] for month in chain['months']], [2, 3])
        self.assertEqual(chain['months'][1]['entries'], [entry])
        self.assertEqual(chain['months'][1]['remaining'], '3571.33')

    def test_existing_current_deduction_adopts_source_without_subtracting_twice(self):
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(['日期', '公司名称', '金额', '收款形式', '单号', '预收', '是否更新应收款'])
        ws.append([dt.date(2026, 9, 8), '测试甲', 140.41, '冲预收',
                   'SXSO1', '5068.19-140.41=4927.78', '是'])
        cols = {'日期': 1, '公司名称': 2, '金额': 3, '收款形式': 4,
                '单号': 5, '预收': 6, '是否更新应收款': 7}
        entry = {'key': 'source|1', 'date': '2026-09-08', 'so': 'SO1', 'amount': '140.41'}
        history = {'basis': 'current_source_reconcile', 'date': '2026-09-08',
                   'opening': '140.41', 'entries': [entry], 'known_sos': ['SO1']}
        month = M.legacy_month(ws, 2, cols, history)
        self.assertEqual(month['entries'], [entry])
        self.assertEqual(month['remaining'], '4927.78')
        self.assertEqual(month['legacy_sos'], [])

    def test_multiple_visible_sos_require_amount_tie(self):
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(['日期', '公司名称', '金额', '收款形式', '单号', '预收', '是否更新应收款'])
        ws.append([dt.date(2026, 9, 14), '测试甲', 97651.78, '冲预收',
                   'SO2 131.12\n追加：SO1（0.42）',
                   'SO2 131.12算预付还剩：97651.78+131.12=97782.9-68,962.21=28820.69-0.42=28820.27', '是'])
        cols = {'日期': 1, '公司名称': 2, '金额': 3, '收款形式': 4,
                '单号': 5, '预收': 6, '是否更新应收款': 7}
        entry = {'key': 'source|1', 'date': '2026-09-14', 'so': 'SO1', 'amount': '0.42'}
        history = {'basis': 'current_source_reconcile', 'date': '2026-09-14',
                   'opening': '97651.78', 'entries': [entry], 'known_sos': ['SO1']}
        month = M.legacy_month(ws, 2, cols, history)
        self.assertEqual(month['remaining'], '28820.27')
        self.assertEqual([e for e in month['entries'] if e['key'].startswith('source|')], [entry])
        self.assertEqual(sum((M.money(e['amount']) for e in month['entries']), Decimal(0)), Decimal('68962.63'))

    def test_single_foreign_receipt_uses_net_amount_after_fee(self):
        item = {'ar': 'AR1', 'matched_by': '三键(原币公式)',
                'identity': {'amount': 61831, 'formula_orig_amount': 8833,
                             'formula_rate': 7},
                'receipt_net_orig': 8833, 'receipt_total_orig': 8844,
                'receipt_fee_orig': 11,
                'source_receipts': [{'ar': 'AR1', 'so': 'SO1', 'date': '2026-09-02',
                                     'amount': 63526.05, 'amount_orig': 8844,
                                     'currency': '美元USD', 'basis': 'current_source_so_receipt',
                                     'event': ['2026-09-02', 'HX1', 'R1']}]}
        entries = S.allocations(item, dt.date(2026, 9, 2))
        self.assertEqual([entry['amount'] for entry in entries], ['61831'])


if __name__ == '__main__':
    unittest.main()
