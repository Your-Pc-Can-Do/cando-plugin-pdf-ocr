"""Persistent HTTP backend; OCR processes and editor drafts belong to this plugin."""
import multiprocessing
import sys
from cando_http import Limits
from task_runtime import make_server
from drafts import add_draft_routes
from worker import preview, save_text, text, searchable_pdf

if __name__=='__main__':
    multiprocessing.freeze_support()
    ready_output=sys.stdout;sys.stdout=sys.stderr
    server=make_server({'preview':preview,'save-text':save_text,'text':text,'searchable-pdf':searchable_pdf},slug='pdf-ocr')
    server.limits=Limits(json_bytes=8*1024*1024)
    add_draft_routes(server)
    server.serve(ready_output=ready_output)
