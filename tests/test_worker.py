"""Synthetic direct HTTP OCR, output, draft and cancellation regression checks."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
def descendants(parent):
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];kernel.Process32NextW.argtypes=kernel.Process32FirstW.argtypes
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateToolhelp32Snapshot(2,0);entry=Entry();entry.dwSize=ctypes.sizeof(entry);parents={}
    try:
        ok=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID]=entry.th32ParentProcessID;ok=kernel.Process32NextW(handle,ctypes.byref(entry))
    finally:kernel.CloseHandle(handle)
    found=set();frontier={parent}
    while frontier:
        frontier={pid for pid,ppid in parents.items() if ppid in frontier and pid not in found};found.update(frontier)
    return found

class DirectHTTP(unittest.TestCase):
    def setUp(self):
        sdk=os.environ.get('CANDO_SDK_PATH')
        if not sdk:self.skipTest('Set CANDO_SDK_PATH to the client sdk/python directory')
        self.temp=tempfile.TemporaryDirectory(prefix='cando-ocr-http-');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.token=secrets.token_hex(24)
        env=dict(os.environ,CANDO_PORT='0',CANDO_TOKEN=self.token,LOCALAPPDATA=str(self.folder),PYTHONDONTWRITEBYTECODE='1',PDFOCR_FORCE_ENGINE='rapidocr',PDFOCR_RAPIDOCR_DEVICE='cpu',HTTP_PROXY='http://127.0.0.1:9',HTTPS_PROXY='http://127.0.0.1:9',NO_PROXY='127.0.0.1,localhost')
        code="import sys,runpy;sys.path[:0]=[sys.argv[1],sys.argv[2]];runpy.run_path(sys.argv[2]+'/main.py',run_name='__main__')"
        self.log=(self.folder/'stderr.log').open('w',encoding='utf8')
        self.process=subprocess.Popen([sys.executable,'-I','-u','-B','-X','utf8','-c',code,sdk,str(ROOT)],stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf8',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        line=self.process.stdout.readline();self.assertTrue(line,'No ready line');self.base='http://127.0.0.1:'+str(json.loads(line)['port']);self.addCleanup(self.stop)
    def stop(self):
        try:self.call('/.cando/shutdown',{})
        except Exception:pass
        try:self.process.wait(5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.process.stdout.close();self.log.close()
    def call(self,path,data=None):
        request=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)
    def outputs(self,job):
        rows=[];offset=0
        while offset is not None:
            page=self.call('/outputs?id='+job['id']+'&offset='+str(offset));rows.extend(page['outputs']);offset=page['nextOffset']
        return rows
    def wait(self,job):
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            result=next(x for x in self.call('/state')['jobs'] if x['id']==job['id'])
            if result['status']!='running':result['outputs']=self.outputs(result);return result
            time.sleep(.03)
        self.fail('Task did not complete')
    def source(self,pages=1):
        from PIL import Image,ImageDraw,ImageFont
        import pymupdf
        source=self.folder/'synthetic.png'
        with Image.new('RGB',(900,250),'white') as image:
            ImageDraw.Draw(image).text((35,70),'CanDo LOCAL 12345',fill='black',font=ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf',52));image.save(source)
        if pages>1:
            target=self.folder/'synthetic.pdf'
            with pymupdf.open() as document:
                for _ in range(pages):document.new_page(width=900,height=250).insert_image(pymupdf.Rect(0,0,900,250),filename=source)
                document.save(target)
            return target
        return source
    def start(self,action,source=None,**extras):
        return self.call('/start',dict(action=action,inputs=[] if source is None else [str(source)],options=extras.pop('options',{}),**extras))
    def test_real_rapidocr_text_searchable_pdf_preserve_original(self):
        import pymupdf
        source=self.source();before=hashlib.sha256(source.read_bytes()).digest()
        for action in ('text','searchable-pdf'):
            result=self.wait(self.start(action,source,outputDir=str(self.folder/'chosen')));self.assertEqual(result['status'],'completed',result)
            target=Path(result['outputs'][0]['path']);self.assertEqual(target.parent,self.folder/'chosen')
            if action=='text':text=target.read_text(encoding='utf-8-sig')
            else:
                with pymupdf.open(target) as document:text=''.join(page.get_text() for page in document)
            self.assertIn('CanDo LOCAL 12345',text)
        self.assertEqual(before,hashlib.sha256(source.read_bytes()).digest())
    def test_preview_pages_and_paginated_state(self):
        result=self.wait(self.start('preview',self.source(3)));self.assertEqual(result['status'],'completed',result)
        metadata=json.loads(Path(result['outputs'][-1]['path']).read_text(encoding='utf8'));self.assertEqual(len(metadata['pages']),3)
        self.assertFalse(metadata['errors']);self.assertNotIn('outputs',self.call('/state')['jobs'][0])
    def test_cancel_stops_inference_child_and_server_can_run_again(self):
        baseline=descendants(self.process.pid);job=self.start('text',self.source(12));deadline=time.monotonic()+5
        spawned=set()
        while time.monotonic()<deadline:
            spawned=descendants(self.process.pid)-baseline
            if spawned:break
            time.sleep(.02)
        self.assertTrue(spawned,'Inference child was not observed')
        started=time.monotonic();self.call('/cancel',{'id':job['id']});result=self.wait(job)
        self.assertEqual(result['status'],'cancelled',result);self.assertLess(time.monotonic()-started,1.5)
        self.assertFalse(descendants(self.process.pid)&spawned);self.assertEqual(list(Path(result['outputDir']).glob('*')),[])
        self.assertEqual(self.wait(self.start('preview',self.source()))['status'],'completed')
    def test_unsaved_draft_ordering_save_and_view_restore(self):
        source=self.folder/'text.txt';source.write_text('Original text',encoding='utf8');draft=self.call('/draft',{'path':str(source)})
        latest='CanDo Unicode \uD55C\uAE00\n'*14000
        self.call('/draft/edit',{'id':draft['id'],'text':latest,'sequence':2})
        self.call('/draft/edit',{'id':draft['id'],'text':'stale edit','sequence':1})
        record=self.call('/draft?id='+draft['id']);self.assertTrue(record['dirty']);self.assertEqual(Path(record['path']).read_text(encoding='utf8'),latest)
        view={'files':[],'draftIds':[draft['id']],'selectedDraft':0};self.call('/view',view);self.assertEqual(self.call('/view'),view)
        snapshot=self.call('/draft/snapshot',{'id':draft['id'],'version':2})
        self.call('/draft/edit',{'id':draft['id'],'text':'New edit while the previous snapshot saves','sequence':3})
        result=self.wait(self.start('save-text',options={'draftPath':snapshot['path'],'name':'local-edit'}));self.assertEqual(result['status'],'completed',result)
        self.assertEqual(Path(result['outputs'][0]['path']).read_text(encoding='utf-8-sig'),latest)
        self.call('/draft/saved',{'id':draft['id'],'version':1});self.assertTrue(self.call('/draft?id='+draft['id'])['dirty'])
        self.call('/draft/saved',{'id':draft['id'],'version':2});self.assertTrue(self.call('/draft?id='+draft['id'])['dirty'])
        self.call('/draft/saved',{'id':draft['id'],'version':3});self.assertFalse(self.call('/draft?id='+draft['id'])['dirty'])
        self.assertEqual(source.read_text(encoding='utf8'),'Original text')

if __name__=='__main__':unittest.main()
