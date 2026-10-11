# PDF & image OCR

Independent plugin for Your PC Can Do (CanDo), using schema 2 and direct HTTP v1. Requires CanDo `>=0.5.8, <0.7.0`.

Select PDFs or images to see their pages in a horizontal preview strip. Extracted text appears in an editable document selector; copy it or save an edited copy. Searchable PDF generation retains the existing rendered-page and transparent-text approach. QR content is included when recognized. Originals and previous results are never overwritten.

The plugin owns its HTML/JS UI, persistent Python backend, processing jobs, progress, cancellation and draft state. The CanDo HTTP SDK supplies authenticated transport and host file/clipboard functions. `ui/config.json` contains tool-specific labels and options owned by this plugin.

## Install and run

1. Add the plugin ZIP in CanDo.
2. Optionally review the source with a connected AI CLI. Then explicitly choose installation; without a review, acknowledge **Install without review**. Installing dependencies may download packages.
3. CanDo prepares its managed Python 3.14 environment using its bundled uv and Python. A separately installed Python or manually registered virtual environment is not required.
4. Open the tool, select files and an action, then run. **Choose output folder** is optional; by default results go to `%LOCALAPPDATA%/app.cando.desktop/outputs/pdf-ocr/<operation-id>`.

Switching tools preserves the backend, current operation, selected files, page previews and acknowledged text edits. The editor shows **Updating the local draft…** while an edit is being sent. Wait for that message to finish before switching away. Immediate navigation or app exit during a pending edit is not guaranteed to retain it. App shutdown stops the backend; draft restoration across app restarts is not provided.

**Save edits** takes a versioned snapshot and writes a new TXT, so subsequent edits cannot change an already requested save. New extraction or input selection replaces the displayed draft selection; save edits first if you need a separate result file. The plugin keeps drafts in its local output directory, separately from original results.

**Cancel job** stops the operation's inference child, including native inference calls, while the persistent backend remains available. Completed result files are retained; unfinished files allocated by the operation are removed. Preview work and extraction may run concurrently.

## Engines and network

OneOCR uses the installed Microsoft Windows Snipping Tool engine and the existing `%USERPROFILE%/.config/oneocr` cache. Microsoft binaries/models are not included in this repository. If OneOCR is unavailable, RapidOCR is used.

RapidOCR is pinned to **3.10.0**, a non-yanked release. The fallback explicitly selects the compatible PP-OCRv4 mobile detector and Korean PP-OCRv5 mobile recognizer; it does not inherit the changed 3.10 default model architecture. The ONNX CPU path was tested with synthetic English text and searchable PDFs. GPU, PyTorch, recognition accuracy across document types and the OneOCR path were not revalidated in this migration.

Processing is local. Python dependency installation uses PyPI; absent RapidOCR models may download from ModelScope. Declared destinations include `pypi.org`, `files.pythonhosted.org`, `www.modelscope.cn` and `*.modelscope.cn`; package/CDN redirects can vary. This disclosure is not a network restriction or a safety guarantee. The tool has no document-upload feature.

## Size and lifecycle behavior

- Plugin HTTP JSON requests default to 8 MiB. Oversized editor requests show an error and are not silently truncated.
- Copy uses a short text host request or a registered UTF-8 file. The Copy button supports up to 1 MiB; larger text can be selected/copied manually or opened from its saved file.
- Long preview reads use host file URLs and Range requests. Tokens are only in Authorization headers on backend requests, never in preview URLs.
- Task state excludes output lists; result metadata is paged. Media refs are released after load, and text/reveal/copy refs after use. Selected input refs remain for tool reentry. A request interrupted during iframe teardown may retain its ref until the backend session ends.

## Development and provenance

Repackage and reinstall the ZIP after source changes. The source directory and installed copy are separate. See `tests/README.md` for synthetic checks.

Repository: `Your-Pc-Can-Do/cando-plugin-pdf-ocr`; contact: `marin6670@gmail.com`.
Processing originated in the user's local `D:\pdfOCR_local` tool, reference commit `5e74372a8308123dca7ef8784bc13e1402db1849`. Context-menu registration is outside this plugin's runtime path. Project source license is not yet selected; dependencies and Microsoft engines retain their own license terms. No engine binary is redistributed here.
