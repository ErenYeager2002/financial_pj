"""Regression cases distilled from the 2026-08-20 and 2026-08-30 batch evidence."""
import copy
import json
import unittest

import current_receipt_group as G

import baseline_receipts as BR
import classify_hexiao as C
import validate_plan as V


class AugustReceiptRegressions(unittest.TestCase):
    def ledger(self, rows):
        by_so = {}
        by_sod = {}
        for ref, row in rows.items():
            by_so.setdefault(row['so'], []).append(ref)
            by_sod.setdefault(row['sod'], []).append(ref)
        return C.LedgerIndex(synthetic={'so': by_so, 'sod': by_sod, 'rows': rows})

    def test_partial_historical_group_is_proved_without_rewriting_future_payment(self):
        so, sod, posting = 'SO_PARTIAL', 'SOD_PARTIAL', '2026-08-20'
        source = [
            ('AR_A', '2026-06-17', 38774.30),
            ('AR_B', '2026-06-17', 22800.00),
            ('AR_C', '2026-05-28', 40500.00),
            ('AR_D', '2026-06-30', 42322.50),
            ('AR_E', '2026-06-30', 24300.00),
            ('AR_F', '2026-06-30', 20250.00),
            ('AR_G', '2026-06-30', 21600.00),
            ('AR_H', '2026-06-30', 52650.00),
        ]
        rows = {
            2: dict(so=so, sod=sod, yingshou=10125.00, huikuan=10125.00,
                    jiezhang='是', shoukuan_time='2026-09-15', shoukuan_way='汇', jiti=None, chayi=None),
            3: dict(so=so, sod=sod, yingshou=7478.20, huikuan=None,
                    jiezhang='否', shoukuan_time=None, shoukuan_way=None, jiti=None, chayi=None),
        }
        records = []
        cumulative = 0
        for ref, (ar, arrival, amount) in enumerate(source, 4):
            cumulative = round(cumulative + amount, 2)
            rows[ref] = dict(so=so, sod=sod, yingshou=amount, huikuan=amount,
                             jiezhang='是', shoukuan_time=arrival,
                             shoukuan_way='汇', jiti=None, chayi=None)
            records.append(dict(ar=ar, so=so, sod=sod, amount_local=amount,
                                amount_orig=amount, deliver_local=280800.00,
                                deliver_orig=280800.00, so_delivery_local=280800.00,
                                sod_delivery_local={sod: 280800.00}, all_sods=[sod],
                                cumulative_received_local=cumulative, currency='CNY',
                                shoukuan_date=arrival, hexiao_date=posting, status='正常',
                                writeoff_sequence_key=[posting, 'HX_' + ar, 'DETAIL_' + ar]))
        ledger = self.ledger(rows)
        ledger.baseline_receipt_state = {BR.group_key(so, sod): {
            'baseline_receivable': 280800.00, 'scope_only': True, 'events': {},
            'ordinary_events': {'future_event': {'signature': [10125.00, '2026-09-15', '汇']}},
        }}
        plan = C.classify_records(records, ledger, {})
        self.assertEqual(plan['counts'], {'auto': 8, 'hold': 0, 'exception': 0, 'total': 8},
                         [(r.get('ar'), r.get('code')) for r in plan['hold']])
        current = {int(ref): row for ref, row in BR.ledger_rows(ledger, so, sod).items()}
        checked = V.validate(plan, current)
        self.assertEqual(checked['counts'], {'write': 0, 'skip': 8, 'conflict': 0})
        serialized = json.loads(json.dumps(plan, default=str))
        self.assertEqual(V.validate(serialized, current)['counts'], checked['counts'])
        self.assertTrue(all(item.get('current_workbook_receipts') for item in checked['skip']))
        self.assertTrue(all(not item.get('row_operation') and not item.get('so_accrual_backfills') for item in checked['skip']))
        self.assertEqual(sum(r['回款明细'] or 0 for r in current.values()), 273321.80)

    def test_partial_group_rejects_incomplete_or_ambiguous_evidence(self):
        so, sod = 'SO_GUARD', 'SOD_GUARD'
        rows = {
            2: dict(so=so, sod=sod, yingshou=20, huikuan=20, jiezhang='是',
                    shoukuan_time='2026-06-01', shoukuan_way='汇', jiti=None, chayi=None),
            3: dict(so=so, sod=sod, yingshou=30, huikuan=30, jiezhang='是',
                    shoukuan_time='2026-06-02', shoukuan_way='汇', jiti=None, chayi=None),
            4: dict(so=so, sod=sod, yingshou=10, huikuan=10, jiezhang='是',
                    shoukuan_time='2026-09-01', shoukuan_way='汇', jiti=None, chayi=None),
            5: dict(so=so, sod=sod, yingshou=40, huikuan=None, jiezhang='否',
                    shoukuan_time=None, shoukuan_way=None, jiti=None, chayi=None),
        }
        records = [dict(ar='AR_' + str(i), so=so, sod=sod, amount_local=amount,
                        amount_orig=amount, deliver_local=100, deliver_orig=100,
                        all_sods=[sod], cumulative_received_local=cumulative,
                        currency='CNY', shoukuan_date=day,
                        hexiao_date='2026-08-20', status='正常',
                        writeoff_sequence_key=['2026-08-20', 'HX_' + str(i)])
                   for i, (amount, cumulative, day) in enumerate([
                       (20, 20, '2026-06-01'), (30, 50, '2026-06-02')], 1)]
        journal = {'baseline_receivable': 100, 'scope_only': True, 'events': {},
                   'ordinary_events': {'future': {'signature': [10, '2026-09-01', '汇']}}}
        before = BR.ledger_rows(self.ledger(rows), so, sod)
        proof = G.build_partial_existing(records, before, journal)
        self.assertIsNotNone(proof)
        self.assertEqual(proof['before_rows'], proof['after_rows'])
        self.assertIsNone(G.build_partial_existing(records[:1], before, journal))
        self.assertIsNone(G.build_partial_existing(records, before, {**journal, 'ordinary_events': {}}))
        changed = copy.deepcopy(records)
        changed[1]['cumulative_received_local'] = 49
        self.assertIsNone(G.build_partial_existing(changed, before, journal))
        changed = copy.deepcopy(before)
        changed['5']['是否结账'] = '是'
        self.assertIsNone(G.build_partial_existing(records, changed, journal))
        changed_records = copy.deepcopy(records)
        changed_rows = copy.deepcopy(before)
        changed_records[1].update(amount_local=20, amount_orig=20,
                                  cumulative_received_local=40,
                                  shoukuan_date='2026-06-01')
        changed_rows['3'].update(应收金额=20, 回款明细=20, 收款时间='2026-06-01')
        changed_rows['5']['应收金额'] = 50
        self.assertIsNone(G.build_partial_existing(changed_records, changed_rows, journal))

    def test_registered_paid_rows_with_unpaid_siblings_do_not_release_accrual(self):
        so, ar, posting = 'SO_SPLIT', 'AR_SPLIT', '2026-08-30'
        sods = ['SOD_FIRST', 'SOD_SECOND']
        rows = {}
        records = []
        for index, sod in enumerate(sods):
            ref = 2 + index * 2
            rows[ref] = dict(so=so, sod=sod, yingshou=519.90, huikuan=None,
                             jiezhang='否', shoukuan_time=None, shoukuan_way=None,
                             jiti=None, chayi=None)
            rows[ref + 1] = dict(so=so, sod=sod, yingshou=3698.10, huikuan=3698.10,
                                 jiezhang='是', shoukuan_time='2026-08-28',
                                 shoukuan_way='汇', jiti=None, chayi=None)
            records.append(dict(ar=ar, so=so, sod=sod, amount_local=3698.10,
                                amount_orig=3698.10, deliver_local=4218.00,
                                deliver_orig=4218.00, so_delivery_local=8436.00,
                                sod_delivery_local={s: 4218.00 for s in sods},
                                all_sods=sods, cumulative_received_local=3698.10,
                                currency='CNY', shoukuan_date='2026-08-28',
                                hexiao_date=posting, status='正常',
                                writeoff_sequence_key=[posting, 'HX_' + sod, 'DETAIL_' + sod]))
        ledger = self.ledger(rows)
        ledger.baseline_receipt_state = {
            BR.group_key(so, rec['sod']): {
                'baseline_receivable': 4218.00, 'scope_only': True, 'events': {},
                'ordinary_events': {BR.event_key(rec): {
                    'signature': [3698.10, '2026-08-28', '汇']}},
            } for rec in records
        }
        plan = C.classify_records(records, ledger, {})
        self.assertEqual(plan['counts']['auto'], 2, plan)
        for item in plan['auto']:
            self.assertEqual(item['code'], 'OK_CURRENT_WORKBOOK_RECEIPT_PRESENT')
            self.assertFalse(item.get('so_accrual_backfills'))
            self.assertFalse(item['so_accrual_audit']['all_settled'])
        current = {}
        for sod in sods:
            current.update({int(ref): row for ref, row in BR.ledger_rows(ledger, so, sod).items()})
        checked = V.validate(plan, current)
        self.assertEqual(checked['counts'], {'write': 0, 'skip': 2, 'conflict': 0})


if __name__ == '__main__':
    unittest.main()
