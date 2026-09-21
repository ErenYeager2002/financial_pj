"""Allocation evidence must preserve money and identity across pipeline stages."""
import copy,json,tempfile,unittest
from pathlib import Path
import fallback_allocation_ledger as F

def audit():
    return {'basis':'local','parent_amount':30.,'allocations':[
        {'so':'SO_B','allocated':20.,'allocated_local':20.,'allocated_orig':20.,'delivery':20.,'status':'full'},
        {'so':'SO_A','allocated':10.,'allocated_local':10.,'allocated_orig':10.,'delivery':10.,'status':'full'}],
        'allocated_sos':['SO_B','SO_A'],'partial_sos':[],'zero_sos':[],
        'already_settled_sos':[],'processing_order':{'ar':'AR_TEST','rule':'fixed'},
        'applied_cases':{'AR_TEST|SO_A|D_A':{'so':'SO_A','sod':'D_A','amount_local':10.},
                         'AR_TEST|SO_B|D_B':{'so':'SO_B','sod':'D_B','amount_local':20.}},
        'applied_sos':['SO_A','SO_B']}

def plan(a):return {'hexiao_date':'2026-09-08','parent_fallback_allocations':{'AR_TEST':a},'write':[],'skip':[]}

class AllocationContractTest(unittest.TestCase):
    def setup_workspace(self,root):
        a=audit();F.commit(root,plan(a));return a
    def test_complete_reorder_preflight_commit_and_readback_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.setup_workspace(root);before=copy.deepcopy(F.load(root))
            b=copy.deepcopy(a);b['allocations'].reverse();b['allocated_sos'].reverse()
            F.preflight(root,plan(b))
            self.assertEqual(F.load(root),before)
            F.commit(root,plan(b));actual=F.load(root)['parents']['AR_TEST']
            expected={**F.eligible_entries(plan(b))['AR_TEST'],'ar':'AR_TEST','hexiao_date':'2026-09-08'}
            self.assertEqual(F.readback_payload(actual),F.readback_payload(expected))
            self.assertEqual(actual['allocations'],a['allocations'])
    def test_complete_reorder_commit_without_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=self.setup_workspace(root);b=copy.deepcopy(a)
            b['allocations'].reverse();b['allocated_sos'].reverse()
            F.commit(root,plan(b))
    def test_preflight_rejects_financial_identity_and_unknown_changes_without_writing(self):
        mutations=[lambda a:a['allocations'][0].update(allocated_local=21.),
                   lambda a:a['allocations'][0].update(so='SO_OTHER'),
                   lambda a:a.update(new_financial_semantics=True),
                   lambda a:a['applied_cases'].pop('AR_TEST|SO_A|D_A'),
                   lambda a:a['processing_order'].update(rule='changed')]
        for mutate in mutations:
            with self.subTest(mutation=mutate),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);a=self.setup_workspace(root);path=F.ledger_path(root);before=path.read_bytes()
                b=copy.deepcopy(a);mutate(b)
                with self.assertRaises(ValueError):F.preflight(root,plan(b))
                with self.assertRaises(ValueError):F.commit(root,plan(b))
                self.assertEqual(path.read_bytes(),before)
    def test_duplicate_so_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=audit();a['allocations'].append(copy.deepcopy(a['allocations'][0]))
            with self.assertRaises(ValueError):F.commit(Path(tmp),plan(a))
    def test_partial_order_remains_significant(self):
        a=audit();a['allocations'][0]['status']='partial';a['partial_sos']=['SO_B']
        b=copy.deepcopy(a);b['allocations'].reverse();b['allocated_sos'].reverse()
        self.assertNotEqual(F._stable_payload(a),F._stable_payload(b))
    def test_provenance_strict_readback_but_stable_allocation(self):
        a=audit();b=copy.deepcopy(a);b['current_material_evidence']={'test':'evidence'}
        self.assertEqual(F._stable_payload(a),F._stable_payload(b))
        self.assertNotEqual(F.readback_payload(a),F.readback_payload(b))
    def test_preflight_does_not_create_missing_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);F.preflight(root,plan(audit()))
            self.assertEqual(list(root.iterdir()),[])

if __name__=='__main__':unittest.main()
