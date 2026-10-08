import base64,hashlib,json,tempfile,unittest
from pathlib import Path
import complete_execution as E,rescan_holds as H

class CurrentCompletion(unittest.TestCase):
    def test_old_audits_preserved_without_becoming_new_execution_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Path(tmp);folder=ws/'03_台账';folder.mkdir()
            names=('父回款顺序分配台账.json','跑批台账.json')
            original={name:b'invalid legacy data' for name in names}
            for name,raw in original.items():(folder/name).write_bytes(raw)
            H.save_ledger(H.ledger_path(ws),[])
            checked=ws/'checked.json';checked.write_text(json.dumps({'hexiao_date':'2026-08-20','write':[],'skip':[]}))
            publication={'schema_version':'ar-publication-v1','reconciliation_date':'2026-08-20',
                'material_set_id':'material','files':[{'file_id':'file'}],'written':0,'material_version':1,'workflow_id':'workflow'}
            result=json.loads(E.build(ws,checked,publication,'abc').read_text())
            self.assertEqual(result['json_ledgers'][names[0]]['parents'],{})
            self.assertEqual(set(result['json_ledgers'][names[1]]['runs']),{'2026-08-20'})
            for name,raw in original.items():
                archived=result['historical_audit_files'][name]
                self.assertEqual(base64.b64decode(archived['base64']),raw)
                self.assertEqual(archived['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual((folder/name).read_bytes(),raw)
            self.assertEqual(json.loads(E.build(ws,checked,publication,'abc').read_text())['json_ledgers'][names[0]],result['json_ledgers'][names[0]])

if __name__=='__main__':unittest.main()
