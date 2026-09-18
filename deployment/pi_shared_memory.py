"""Owner-scoped cross-conversation memory; SQLite transactions serialize writers."""
import hashlib,json,os,re,sqlite3,sys,time
from pathlib import Path

def operate(body, root=Path('/context')):
    root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'memory.sqlite3',timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, session TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL)')
        action=body.get('action','recall')
        if action=='remember':
            text=body.get('text','');session=os.environ.get('PI_PLATFORM_SESSION_ID','')
            if not isinstance(text,str) or not text.strip() or len(text)>8000:raise ValueError('Memory text must contain 1..8000 characters')
            if re.search(r'(?i)(password|passwd|api[_ -]?key|secret|bearer|access[_ -]?token|密码|口令|密钥|验证码)\s*[:=：]|sk-[a-zA-Z0-9_-]{16,}|-----BEGIN.*PRIVATE KEY',text):raise ValueError('Do not store credentials in shared memory')
            identity=hashlib.sha256((session+'\0'+str(body.get('key',text))).encode()).hexdigest()
            with db:db.execute('INSERT OR IGNORE INTO memories VALUES (?,?,?,?)',(identity,session,text,time.time()))
            return {'saved':True}
        if action not in {'recall','search'}:raise ValueError('Unknown memory action')
        query=body.get('query','')
        if not isinstance(query,str) or len(query)>200:raise ValueError('Invalid query')
        rows=db.execute('SELECT session,text,created FROM memories WHERE instr(lower(text),lower(?))>0 ORDER BY created DESC LIMIT 20',(query,)).fetchall()
        remaining=24000;out=[]
        for session,text,created in rows:
            if len(text)>remaining:break
            out.append({'session':session,'memory':text,'created':created});remaining-=len(text)
        return {'memories':out,'scope':'current account and department only'}
    finally:db.close()

if __name__=='__main__':
    try:print(json.dumps(operate(json.loads(sys.argv[1])),ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)[:180]}));sys.exit(1)
