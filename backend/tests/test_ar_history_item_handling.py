import copy
from types import SimpleNamespace
from app.ar_material_history import history_differences
from app.ar_history_guard import guard_decisions


def row(amount='100.00', day='2026-09-09', method='汇', so='SO1', n=10):
    return dict(row=n, so=so, sod='SOD1', amount=amount, date=day, method=method)


def test_blank_receipt_is_missing_not_global_conflict():
    changes = history_differences([row()], [row('0.00', '', '')], 2026)
    assert changes[0]['status'] == 'missing'
    assert changes[0]['current_rows'][0]['row'] == 10


def test_changed_date_or_method_is_conflict():
    for current in [row(day='2026-08-27'), row(method='冲预收'), row('0.00', '', '汇')]:
        assert history_differences([row()], [current], 2026)[0]['status'] == 'conflict'


def test_existing_other_receipt_is_not_mistaken_for_conflict():
    assert history_differences([row(),row('200.00')], [row()], 2026)[0]['status'] == 'missing'


def test_row_reordering_and_duplicates_preserve_counts():
    assert history_differences([row()], [row(n=30)], 2026) == []
    assert history_differences([row(),row()], [row()], 2026)[0]['count'] == 1


def test_history_differences_annotate_without_overruling_current_decisions():
    changes = history_differences([row(),row(so='SO2')], [row(method='冲预收'),row('0.00','','',so='SO2')], 2026)
    result = {'auto':[dict(so=so,ledger_year=2026,bucket='auto',five_cols={'amount':100}, row_operation={'x':1}) for so in ['SO1','SO2','SO3']], 'hold':[], 'exception':[]}
    fake = SimpleNamespace(_dist=lambda rows:{}, build_ar_summary=lambda rows:[])
    guard_decisions(result,changes,fake)
    assert [r['so'] for r in result['auto']] == ['SO1','SO2','SO3']
    assert result['auto'][0]['material_history_conflicts']
    assert result['auto'][0]['five_cols']=={'amount':100}
    assert not result['hold']
    before=copy.deepcopy(result);guard_decisions(result,changes,fake);assert result==before


def test_year_scope_is_preserved():
    changes=history_differences([row()],[row(method='冲预收')],2025)
    result={'auto':[dict(so='SO1',ledger_year=2026,bucket='auto')], 'hold':[], 'exception':[]}
    guard_decisions(result,changes,SimpleNamespace(_dist=lambda r:{},build_ar_summary=lambda r:[]))
    assert len(result['auto'])==1


def test_real_classifier_dependency_guard_keeps_unrelated_orders():
    import sys
    import importlib
    sys.path.insert(0, '/app/skills/ar-hexiao-daily-lab/vendor/scripts')
    classifier = importlib.import_module('classify_hexiao')
    changes=history_differences([row()],[row(method='冲预收')],2026)
    records=[dict(case_id='AR'+str(i)+'|'+so,ar='AR'+str(i),so=so,sod='SOD1',ledger_year=2026,bucket='auto',code='OK',reason='',five_cols={'x':1}) for i,so in enumerate(['SO1','SO2','SO3'])]
    for r in records[:2]: r['fallback_batch_cases']=[x['case_id'] for x in records[:2]]
    result={'auto':records,'hold':[],'exception':[]}
    guard_decisions(result,changes,classifier)
    assert [r['so'] for r in result['auto']]==['SO1','SO2','SO3']
    assert not result['hold']


def test_report_contains_exact_rows_and_preserves_existing_sheets():
    import tempfile,json
    from pathlib import Path
    import openpyxl
    from app.ar_history_guard import append_history_report
    with tempfile.TemporaryDirectory() as folder:
        workspace=Path(folder);out=workspace/'04_产出';out.mkdir()
        path=out/'核销日清_20260909.xlsx'
        book=openpyxl.Workbook();book.active.title='核销明细';book.active['A1']='既有内容';book.save(path);book.close()
        (out/'最终核销结果_20260909.json').write_text(json.dumps({'counts':{'total':1}}))
        differences=history_differences([row()],[row(method='冲预收')],2026)
        append_history_report(workspace,'20260909',differences)
        book=openpyxl.load_workbook(path)
        assert book['核销明细']['A1'].value=='既有内容'
        assert book['历史材料差异']['F2'].value=='10'
        assert book['历史材料差异']['D2'].value=='历史值与当前表不同，以本次核销判定为准'
        book.close()
