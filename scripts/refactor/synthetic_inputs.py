"""Deterministic, fabricated workbook inputs; no database or network imports."""
from datetime import date
from pathlib import Path
import hashlib
import json
from openpyxl import Workbook
from verify_isolation import contained_path, verify

LEDGER_HEADERS = ['部门','销售人员','客户名称','单号','新智云单号','应收金额','计提金额','回款明细','是否结账（是/否）','收款时间','收款方式(支/汇/现)','实收金额','差异']

def workbook(path, title, headers, rows):
    wb=Workbook();ws=wb.active;ws.title=title;ws.append(headers)
    for row in rows: ws.append(row)
    wb.save(path);wb.close()

def create(root, env):
    verify(env)
    root=contained_path(str(root),Path(env['REFACTOR_TEST_ROOT']).resolve())
    root.mkdir(parents=True,exist_ok=False)
    ledgers={}
    for year in (2025,2026):
        so=f'SO{str(year)[2:]}010001';sod=f'SOD{str(year)[2:]}010001'
        target=root/f'{year}-ledger.xlsx'
        workbook(target,'明细',LEDGER_HEADERS,[['合成部门','合成人员','合成客户','SYNTHETIC',so,100,None,None,None,None,None,sod,None]])
        ledgers[str(year)]=target.name
    workbook(root/'flow.xlsx','流水',['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'],[[date(2026,7,27),'合成客户',200,'汇款','WX',200,None]])
    dates=['2026-07-31','2026-08-01']
    for year,day in zip((2025,2026),dates):
        export=root/day/'01_智云导出';export.mkdir(parents=True)
        so=f'SO{str(year)[2:]}010001';sod=f'SOD{str(year)[2:]}010001'
        workbook(export/'回款记录_synthetic.xlsx','回款',['回款记录ID','核销日期','到账日期','到账金额/原币','到账金额/本币','手续费/原币','原币币种','回款类型','核销状态','开票客户'],[['ARTEST0001',day,'2026-07-27',200,200,0,'人民币CNY','预存回款','核销成功','合成客户']])
        workbook(export/'订单交付_synthetic.xlsx','订单',['回款记录ID','SO','订单已核销金额','交付额/原币','汇率','订单名称'],[['ARTEST0001',so,100,100,1,'合成项目']])
        workbook(export/'核销明细_synthetic.xlsx','核销',['核销记录NUM','rowid','回款记录NUM','核销日期','本次核销金额','本次核销金额/本币','币种','汇率','SO','订单名称','是否已撤销'],[[f'HXTEST{year}',f'ROWTEST{year}','ARTEST0001',day,100,100,'人民币CNY',1,so,'合成项目','否']])
        workbook(export/'订单明细_synthetic.xlsx','明细',['SO','SOD','交付额/原币'],[[so,sod,100]])
    manifest={'synthetic':True,'ledger_years':ledgers,'flow':'flow.xlsx','dates':dates,'expected':{'current_writeoff_per_date':100,'original_receipt':200,'balances':[100,0],'publication_on_verification_failure':False},'sha256':{str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(root.rglob('*.xlsx'))}}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest
