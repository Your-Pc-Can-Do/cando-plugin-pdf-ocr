"""Plugin-owned preview/save logic."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
if os.environ.get('CANDO_SDK_PATH'):sys.path.insert(0,os.environ['CANDO_SDK_PATH'])
sys.path.insert(0,str(ROOT))
from task_runtime import Context,PluginError
from worker import preview,save_text

def context(inputs,options,directory,locale='en'):
    return Context({'inputs':[str(item) for item in inputs],'options':options,'locale':locale},
                   {'outputs':[],'outputDir':str(directory)},threading.Event(),lambda:None,threading.RLock())

class PreviewAndEditing(unittest.TestCase):
    def test_preview_all_pdf_and_tiff_pages_without_ocr(self):
        import pymupdf
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='cando-ocr-view-') as directory:
            folder=Path(directory);source=folder/'three-pages.pdf'
            with pymupdf.open() as document:
                for number in range(3):document.new_page().insert_text((30,30),f'Synthetic page {number+1}')
                document.save(source)
            image=folder/'two-pages.tiff'
            with Image.new('RGB',(200,300),'red') as first,Image.new('RGB',(300,200),'blue') as second:
                first.save(image,save_all=True,append_images=[second])
            before=hashlib.sha256(source.read_bytes()).digest();ctx=context([source,image],{},folder/'out');preview(ctx)
            metadata=json.loads(Path(ctx.job['outputs'][-1]['path']).read_text(encoding='utf8'))
            self.assertEqual(len(metadata['pages']),5);self.assertEqual(metadata['errors'],[])
            self.assertEqual([p['pageNumber'] for p in metadata['pages']],[1,2,3,1,2])
            self.assertNotIn('ocr_engine',sys.modules);self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),before)
            self.assertTrue(all(Path(output['path']).is_relative_to(folder/'out') for output in ctx.job['outputs']))

    def test_save_unicode_empty_and_long_edits_preserves_existing_result(self):
        with tempfile.TemporaryDirectory(prefix='cando-ocr-save-') as directory:
            texts=['원래 결과\nCanDo','','한글 edit\n'*120000];targets=[]
            for text in texts:
                ctx=context([],{'text':text,'name':'sample'},directory);save_text(ctx)
                target=Path(ctx.job['outputs'][0]['path']);self.assertEqual(target.read_text(encoding='utf-8-sig'),text);targets.append(target)
            self.assertEqual(len(set(targets)),3);self.assertEqual(targets[0].read_text(encoding='utf-8-sig'),texts[0])

    def test_saved_content_is_preserved_in_both_locales(self):
        with tempfile.TemporaryDirectory(prefix='cando-ocr-locale-') as directory:
            for locale in ('en','ko'):
                content='진행 중\nUser text is not translated.';ctx=context([],{'text':content,'name':locale},directory,locale)
                result=save_text(ctx)
                self.assertEqual(Path(ctx.job['outputs'][0]['path']).read_text(encoding='utf-8-sig'),content)
                self.assertIn('Saved your edits' if locale=='en' else '편집한 텍스트',result['summary'])

    def test_bad_name_rejected_and_input_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='cando-ocr-save-') as directory:
            with self.assertRaises(PluginError):save_text(context([],{'text':'private','name':'../escape'},directory))
            self.assertEqual(list(Path(directory).iterdir()),[])
            source=Path(directory)/'sample.txt';source.write_text('Original input',encoding='utf8')
            ctx=context([source],{'text':'New edit','name':'sample'},directory);save_text(ctx)
            self.assertNotEqual(Path(ctx.job['outputs'][0]['path']),source);self.assertEqual(source.read_text(encoding='utf8'),'Original input')

if __name__=='__main__':unittest.main()
