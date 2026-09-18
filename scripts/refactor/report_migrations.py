"""Read migration metadata without importing migration modules or opening a DB."""
import ast
from pathlib import Path
from inventory import tracked_files, call_name
from report_maps import table
ROOT=Path(__file__).resolve().parents[2]

def scan(root):
    result=[]
    for name in tracked_files(root):
        if not name.startswith('backend/alembic/versions/') or not name.endswith('.py'): continue
        tree=ast.parse((root/name).read_text(encoding='utf-8-sig'))
        metadata={}
        for node in tree.body:
            key=None; value=None
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                key=node.targets[0].id;value=node.value
            elif isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name):
                key=node.target.id;value=node.value
            if key in {'revision','down_revision'}:
                try: metadata[key]=ast.literal_eval(value)
                except (ValueError,TypeError): metadata[key]='<dynamic>'
        operations=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                callee=call_name(node.func)
                if callee.startswith('op.'):
                    operations.append(f'{callee}:{node.lineno}')
        result.append([name,metadata.get('revision','missing'),metadata.get('down_revision'),', '.join(operations)])
    return result

if __name__=='__main__':
    rows=scan(ROOT)
    (ROOT/'docs/refactor/migration-ledger.md').write_text('# Migration baseline ledger\n\nStatic metadata only. No production migration or downgrade has been run by this refactor. Multiple heads, upgrade correctness and legacy SQLite equivalence still require isolated PR-01 tests. Raw SQL bodies are not copied into this report.\n\n'+table(['Path','Revision','Parent','Alembic operations and lines'],rows))
    print(f'Indexed {len(rows)} migration files')
