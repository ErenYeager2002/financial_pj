import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import openpyxl
import flow_monthly as M
import flow_current_carry as C


class CurrentCarry(unittest.TestCase):
    def entry(self,so,amount,day):
        return {'key':'source|'+json.dumps(['AR_TEST',so,day,['HX'+so,'R'+so]]),'case_id':'AR_TEST|'+so,'so':so,'amount':str(amount),'date':day}

    def fixture(self,path,stored):
        wb=openpyxl.Workbook();ws=wb.active;ws.title='流水'
        ws.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        ws.append([dt.date(2026,7,1),'合成客户',1000,'汇款','WXSO1 400 转8月','1000-400=600','是'])
        ws.append([dt.date(2026,8,29),'合成客户',600,'冲预收','WXSO3 100','600-100=500','是'])
        chain=M.adopt_chain(ws,M.columns(ws),{'row_no':2})
        ws.append([dt.date(2026,8,11),'合成客户',500,'冲预收','WXSO1 300 SO2 200 追加：SO3 100','600-500=100-100=0','是'])
        wb.save(path);wb.close()
        if stored:M.save_state(path,{'schema':M.SCHEMA,'receipts':{'AR_TEST':chain}})

    def item(self,late=False):
        entries=[self.entry('SO1',300,'2026-08-11'),self.entry('SO2',200,'2026-08-11')]
        if late:entries.append(self.entry('SO3',100,'2026-08-29'))
        history={'basis':'current_source_reconcile','fetched_history':True,'date':entries[-1]['date'],'opening':'600','entries':entries,'known_sos':[e['so'] for e in entries]}
        return {'ar':'AR_TEST','sheet':'流水','row_no':2,'monthly_date':entries[-1]['date'],
                'monthly_receipt_history':{'periods':{'2026-08':history}},
                'monthly_entries':entries[-1:] if late else entries,
                'so_outcomes':[{'so':e['so'],'completed':True} for e in entries]}

    def test_existing_current_prefix_and_future_tail_no_double_deduction(self):
        for stored in (False,True):
            with self.subTest(stored=stored),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.fixture(p,stored)
                wb=openpyxl.load_workbook(p);old_partial=[c.value for c in wb.active[3]];wb.close()
                for late in (False,True,True):
                    changes=M.write_file(p,out,[self.item(late)])
                    if changes:p.write_bytes(out.read_bytes())
                    wb=openpyxl.load_workbook(p);ws=wb.active
                    self.assertEqual([c.value for c in ws[3]],old_partial)
                    self.assertEqual(M.parsed_balance(ws['F4'].value)['remaining'],0)
                    self.assertEqual(ws.max_row,4);wb.close()
                    self.assertTrue(all(not c['核销事项'] for c in changes))
                before=p.read_bytes();self.assertEqual(M.write_file(p,out,[self.item(True)]),[]);self.assertEqual(p.read_bytes(),before)

    def test_missing_or_conflicting_evidence_still_ambiguous(self):
        def duplicate(ws):ws.append([c.value for c in ws[4]])
        edits=[lambda ws: setattr(ws['E4'],'value','WXSO1 301 SO2 199 追加：SO3 100'),
               lambda ws:setattr(ws['F4'],'value','600-500=99-99=0'),
               lambda ws:setattr(ws['E3'],'value','WXSO9 100'),
               lambda ws:setattr(ws['A3'],'value',dt.date(2026,8,1)),
               duplicate]
        for edit in edits:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'flow.xlsx';self.fixture(p,False)
                wb=openpyxl.load_workbook(p);edit(wb.active)
                candidates=list(range(3,wb.active.max_row+1))
                self.assertIsNone(C.choose(wb.active,M.columns(wb.active),candidates,self.item(),600));wb.close()

    def test_future_source_and_missing_source_are_not_current_proof(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'flow.xlsx';self.fixture(p,False);wb=openpyxl.load_workbook(p);ws=wb.active;cols=M.columns(ws)
            facts=C.row_facts(ws,cols,4,600);hist=self.item()['monthly_receipt_history']['periods']['2026-08']
            for mutate in [lambda h:h.update(fetched_history=False),lambda h:h['entries'].pop(),lambda h:h['entries'][0].update(date='2026-08-29'),lambda h:h['entries'].append(copy.deepcopy(h['entries'][0]))]:
                h=copy.deepcopy(hist);mutate(h);self.assertIsNone(C.source_prefix(facts,h))
            original=copy.deepcopy(hist);self.assertIsNotNone(C.source_prefix(facts,hist));self.assertEqual(hist,original)
            ws['E4']='WXSO3 100 SO2 200 SO1 300'
            self.assertIsNotNone(C.source_prefix(C.row_facts(ws,cols,4,600),hist));wb.close()

    def test_current_cumulative_row_cannot_steal_another_parent(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.fixture(p,True)
            state=M.load_state(p);wb=openpyxl.load_workbook(p);ws=wb.active
            other=M.legacy_month(ws,4,M.columns(ws));wb.close()
            state['receipts']['AR_OTHER']={'sheet':'流水','months':[other]};M.save_state(p,state)
            before=p.read_bytes()
            with self.assertRaisesRegex(ValueError,'另一笔到账'):
                M.write_file(p,out,[self.item()])
            self.assertEqual(p.read_bytes(),before);self.assertFalse(out.exists())

    def test_current_proof_does_not_require_saved_metadata_or_text_order(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'flow.xlsx';self.fixture(p,False)
            wb=openpyxl.load_workbook(p);ws=wb.active
            ws['E4']='WXSO3 100 SO2 200 SO1 300'
            for late in (False,True):
                chain=M.adopt_chain(ws,M.columns(ws),self.item(late))
                self.assertEqual(chain['months'][-1]['row'],4)
                keys={e['key'] for e in chain['months'][-1]['entries']}
                self.assertTrue({e['key'] for e in self.item(late)['monthly_entries']}<=keys)
                self.assertEqual(chain['months'][-1]['remaining'],'0')
            wb.close()

    def test_expanded_equation_retains_legacy_period_amount(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.fixture(p,False)
            wb=openpyxl.load_workbook(p);ws=wb.active
            ws['F4']='600-300-200-100=0';wb.save(p);wb.close()
            for late in (False,True):
                wb=openpyxl.load_workbook(p);ws=wb.active
                chain=M.adopt_chain(ws,M.columns(ws),self.item(late));wb.close()
                self.assertEqual(chain['months'][-1]['row'],4)
                self.assertEqual(chain['months'][-1]['start'],'600')
                self.assertEqual(chain['months'][-1]['remaining'],'0')
                changes=M.write_file(p,out,[self.item(late)])
                self.assertTrue(all(not c['核销事项'] for c in changes))
                if changes:p.write_bytes(out.read_bytes())
