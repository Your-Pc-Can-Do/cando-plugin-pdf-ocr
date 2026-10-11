# Synthetic verification

Use a Python 3.14 environment containing this plugin's updated requirements and cached RapidOCR models. Point it at the client's HTTP SDK:

```powershell
$env:CANDO_SDK_PATH = 'C:\path\your-pc-can-do\sdk\python'
& 'C:\path\managed-env\Scripts\python.exe' -I -B -X utf8 -m unittest discover -s tests -v
```

`test_worker.py` launches the actual persistent HTTP backend and checks RapidOCR 3.10.0 text/searchable PDF output, multi-page previews, output pagination, versioned drafts, cancellation of the inference child and subsequent operation reuse. It forces ONNX CPU, uses generated files and points model-download proxies at an unavailable loopback port so existing cached models are required. `test_preview_edit.py` checks plugin-owned preview/save logic, Unicode/empty/long edits, locale handling and preservation of original files.

Run the real browser/SDK integration with the client development dependencies and Edge available:

```powershell
$env:CANDO_CLIENT_DIR = 'C:\path\your-pc-can-do'
$env:CANDO_OCR_PYTHON = 'C:\path\managed-env\Scripts\python.exe'
node tests/check-ui.mjs
```

The browser test uses an opaque iframe and the real HTTP SDK/backend. It creates a synthetic three-page PDF, decodes page previews, extracts real text, saves edits, restores an acknowledged unsaved draft in a new iframe, checks both UI languages and verifies fileRef cleanup. Native file dialogs, file registration/preview serving, clipboard and Explorer are host mocks; the user's clipboard is never changed.

Set `CANDO_TEST_OUTPUT_DIR` to a fresh evidence directory; otherwise the harness writes to the client's `.test-data/stage4-ocr` directory. Browser checks do not establish native CanDo/WebView2 dialogs, Windows Sandbox installation, GPU/PyTorch operation, OneOCR behavior or OCR accuracy beyond the synthetic test. No microphone is used.
