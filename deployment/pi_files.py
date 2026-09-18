"""Descriptor-based file transfer for one manager-authenticated Pi session."""
import base64
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from uuid import UUID, uuid4

CHUNK = 1024 * 1024


def private_directory(path):
    if path.is_symlink(): raise ValueError('Unsafe directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != 0 or not stat.S_ISDIR(info.st_mode): raise ValueError('Invalid directory ownership')
    return path


def inputs(session_root):
    path = private_directory(session_root / 'inputs')
    path.chmod(0o755)
    return path


def open_beneath(root, path='', directory=False):
    if not isinstance(path, str) or path.startswith('/') or '\\' in path or '\x00' in path:
        raise ValueError('Invalid file path')
    parts = path.split('/') if path else []
    if any(p in {'','.', '..'} for p in parts): raise ValueError('Invalid path component')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(parts) - 1 or directory: flags |= os.O_DIRECTORY
            next_fd = os.open(part, flags, dir_fd=fd); os.close(fd); fd = next_fd
        info = os.fstat(fd)
        if directory and not stat.S_ISDIR(info.st_mode): raise ValueError('Not a directory')
        if not directory and not stat.S_ISREG(info.st_mode): raise ValueError('Not a regular file')
        return fd
    except BaseException:
        os.close(fd); raise


def version(info):
    return hashlib.sha256(f'{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}'.encode()).hexdigest()


def metadata(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value)); temporary.chmod(0o600); os.replace(temporary,path)


def operate(session_root, body):
    action = body.get('action')
    source = body.get('source', 'workspace')
    if source not in {'workspace','inputs'}: raise ValueError('Invalid file source')
    if action in {'list','read','stat'}:
        root = inputs(session_root) if source == 'inputs' else session_root / 'workspace'
        if not root.exists() and action == 'list': return {'entries':[], 'path':body.get('path',''), 'next_offset':None}
        path = body.get('path','')
        fd = open_beneath(root, path, directory=action=='list')
        try:
            if action == 'list':
                names = sorted(os.listdir(fd)); offset = max(0,int(body.get('offset',0))); entries=[]
                for name in names[offset:offset+200]:
                    try: info=os.stat(name,dir_fd=fd,follow_symlinks=False)
                    except FileNotFoundError: continue
                    if stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode):
                        entries.append({'name':name,'kind':'directory' if stat.S_ISDIR(info.st_mode) else 'file','size':info.st_size})
                return {'entries':entries,'path':path,'next_offset':offset+200 if len(names)>offset+200 else None}
            info=os.fstat(fd); fingerprint=version(info)
            if body.get('version') and body['version']!=fingerprint: raise ValueError('File changed during download')
            result={'size':info.st_size,'version':fingerprint,'name':Path(path).name}
            if action=='read':
                offset=max(0,int(body.get('offset',0)));os.lseek(fd,offset,os.SEEK_SET);data=os.read(fd,CHUNK)
                if version(os.fstat(fd))!=fingerprint: raise ValueError('File changed during download')
                result.update(data=base64.b64encode(data).decode(),next=offset+len(data))
            return result
        finally: os.close(fd)
    staging=private_directory(session_root/'uploads')
    if action=='upload_begin':
        name=body.get('name');size=body.get('size')
        if not isinstance(name,str) or not name or name in {'.','..'} or any(c in name for c in '/\\\x00\r\n') or len(name.encode())>240:
            raise ValueError('Invalid file name')
        if not isinstance(size,int) or not 0<=size<=32*1024**3: raise ValueError('Invalid upload size')
        upload_id=str(uuid4());folder=staging/upload_id;folder.mkdir(mode=0o700)
        metadata(folder/'meta.json',{'name':name,'size':size})
        (folder/'data').touch(mode=0o600)
        return {'upload_id':upload_id,'next':0}
    upload_id=str(UUID(body.get('upload_id')));folder=staging/upload_id
    if action=='upload_abort':
        if folder.exists(): shutil.rmtree(folder)
        return {'aborted':True}
    if action not in {'upload_chunk','upload_commit'}: raise ValueError('Invalid file operation')
    info=json.loads((folder/'meta.json').read_text());data_path=folder/'data'
    if action=='upload_chunk':
        data=base64.b64decode(body.get('data',''),validate=True);offset=body.get('offset')
        if len(data)>CHUNK or not isinstance(offset,int) or offset!=data_path.stat().st_size or offset+len(data)>info['size']:
            raise ValueError('Upload offset or chunk size mismatch')
        with data_path.open('ab') as stream: stream.write(data)
        return {'upload_id':upload_id,'next':offset+len(data)}
    if data_path.stat().st_size!=info['size']: raise ValueError('Upload incomplete')
    digest=hashlib.sha256()
    with data_path.open('rb') as stream:
        while chunk:=stream.read(CHUNK): digest.update(chunk)
    destination=inputs(session_root)/upload_id;destination.mkdir(mode=0o755);destination.chmod(0o755)
    target=destination/info['name'];data_path.chmod(0o444);os.replace(data_path,target)
    result={'path':upload_id+'/'+info['name'],'agent_path':'/inputs/'+upload_id+'/'+info['name'],'name':info['name'],'size':info['size'],'sha256':digest.hexdigest()}
    shutil.rmtree(folder)
    return result
