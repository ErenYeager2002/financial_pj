"""Render exhaustive static evidence tables; no runtime or ownership inference."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs/refactor'

def table(headers, rows):
    def clean(value): return str(value).replace('|', '\\|').replace('\n', ' ')
    return '| ' + ' | '.join(headers) + ' |\n|' + '|'.join('---' for _ in headers) + '|\n' + ''.join('| ' + ' | '.join(clean(x) for x in row) + ' |\n' for row in rows)

def main():
    source = json.loads((DOCS/'reports/source-inventory.json').read_text())
    ts = json.loads((DOCS/'reports/typescript-inventory.json').read_text())
    files = source['files']
    intro = f"Baseline `{source['commit']}`. Static AST evidence only; dynamic dispatch, imported aliases and runtime reachability require targeted verification.\n\n"
    routes = [(x['path'], y['line'], y['method'], y['path'], y['symbol']) for x in files for y in x.get('routes', [])]
    calls = [(x['path'], y['line'], y['caller'], y['callee']) for x in files for y in x.get('calls', [])]
    effects = [(x['path'], y['line'], y['caller'], y['callee'], 'unclassified; verify use-case commit owner') for x in files for y in x.get('side_effect_hints', []) if y['callee'].rsplit('.',1)[-1] in {'commit','rollback','flush'}]
    imports = [(x['path'], y['line'], y['module'], ', '.join(y.get('names', []))) for x in files for y in x.get('imports', [])]
    (DOCS/'reports/python-call-sites.md').write_text('# Python call sites\n\n'+intro+table(['File','Line','Caller scope','Callee expression'], calls))
    (DOCS/'execution-paths.md').write_text('# Execution entrypoints\n\n'+intro+'Every decorator route is listed below, including test fixtures. This is not a complete runtime call graph. See [call sites](reports/python-call-sites.md) for caller scopes. Router prefixes, registration, worker loops, Pi and Native runtime traces remain to be annotated before PR-00 acceptance.\n\n'+table(['File','Line','Verb','Decorator path','Handler'],routes)+'\n## Frontend entries\n\n'+table(['File','Route entry','BFF'],[(x['path'], x.get('route'),x.get('bff')) for x in ts['files'] if x.get('route') or x.get('bff')]))
    (DOCS/'transaction-boundaries.md').write_text('# Transaction boundary candidates\n\n'+intro+'This lists commit/rollback/flush expressions, not confirmed transaction ownership. Test doubles and unrelated methods can share these names. Classify API use cases, worker claims, checkpoints, heartbeat and implicit helpers before PR-02; no automatic rewrite is justified by this list.\n\n'+table(['File','Line','Caller scope','Expression','Classification'],effects))
    (DOCS/'dependency-map.md').write_text('# Dependency evidence\n\n'+intro+'Python imports below retain relative module syntax. TypeScript imports, dynamic imports, hooks and query-key AST locations are in reports/typescript-inventory.json. Dependency resolution and cycle classification are pending; imports do not prove runtime calls.\n\n'+table(['File','Line','Module','Imported names'],imports))
    (DOCS/'source-map.md').write_text('# Source map\n\n'+intro+'Tracked baseline source is indexed by path, symbol and exact line span in [source-inventory.json](reports/source-inventory.json). [source-inventory.md](reports/source-inventory.md) is the file index. TypeScript symbols use the compiler AST report. Untracked code, environment files, runtime data and symlinks are intentionally excluded.\n\nThe refactor worktree is separate from the deployed release. Changes in the deployed non-Git tree are not automatically copied here; they require provenance and compatibility review. Generated/vendor flags are conservative hints, not permission to modify or delete.\n')
    print(json.dumps({'routes':len(routes),'calls':len(calls),'transaction_candidates':len(effects),'imports':len(imports)}))

if __name__ == '__main__': main()
