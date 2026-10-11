"""Unsaved editor drafts are local plugin files, separate from saved OCR results."""
import os
import shutil
from pathlib import Path
import threading
import uuid
from cando_http import HTTPError

def add_draft_routes(server):
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local')))/'app.cando.desktop'/'outputs'/'pdf-ocr'/'.drafts'/uuid.uuid4().hex
    records={};originals={};lock=threading.RLock()
    def item(identifier):
        if identifier not in records:raise HTTPError(404,'Draft not found.')
        return records[identifier]
    def write(record,text):
        base.mkdir(parents=True,exist_ok=True)
        target=Path(record['path']);temporary=target.with_suffix('.tmp')
        temporary.write_text(text,encoding='utf-8')
        temporary.replace(target)
        record['bytes']=target.stat().st_size
    @server.route('GET','/draft')
    def get(request):
        with lock:return dict(item(request.query.get('id',[''])[0]))
    @server.route('POST','/draft')
    def create(request):
        value=request.json();source=Path(value.get('path',''))
        if not source.is_absolute() or not source.is_file():raise HTTPError(400,'Draft source file is missing.')
        with lock:
            key=str(source.resolve())
            if key in originals:return dict(records[originals[key]])
            identifier=uuid.uuid4().hex
            record={'id':identifier,'path':str(base/(identifier+'.txt')),'originalPath':key,'name':source.name,'dirty':False,'version':0}
            write(record,source.read_text(encoding='utf-8-sig'))
            records[identifier]=record;originals[key]=identifier
            return dict(record)
    @server.route('POST','/draft/edit')
    def edit(request):
        value=request.json();text=value.get('text');sequence=value.get('sequence')
        if not isinstance(text,str) or type(sequence) is not int:raise HTTPError(400,'Invalid draft edit.')
        with lock:
            record=item(value.get('id'))
            if sequence>record['version']:
                write(record,text);record.update(version=sequence,dirty=True)
            return dict(record)
    @server.route('POST','/draft/saved')
    def saved(request):
        value=request.json()
        with lock:
            record=item(value.get('id'))
            if value.get('version')==record['version']:record['dirty']=False
            return dict(record)
    @server.route('POST','/draft/snapshot')
    def snapshot(request):
        value=request.json()
        with lock:
            record=item(value.get('id'))
            if value.get('version')!=record['version']:raise HTTPError(409,'The draft changed. Try saving again.')
            target=base/(uuid.uuid4().hex+'-save.txt')
            shutil.copyfile(record['path'],target)
            return {'path':str(target),'version':record['version']}
