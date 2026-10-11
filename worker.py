from task_runtime import PluginError
from ocr_session import OCRSession
import io
import json



def tr(ctx, en, ko):
    return ko if getattr(ctx, 'locale', 'en') == 'ko' else en



def preview(ctx):
    """Render pages without loading OCR or sending the source outside this PC."""
    from PIL import Image, ImageOps
    import pymupdf
    if not ctx.inputs:
        raise PluginError(tr(ctx, 'Choose a PDF or image.', 'PDF 또는 이미지를 선택해 주세요.'))
    metadata = {'pages': [], 'errors': []}
    for source_index, source in enumerate(ctx.inputs):
        ctx.check_cancelled()
        def save_page(image, number, count):
            ctx.check_cancelled()
            target = ctx.output_path(f'preview-{source_index + 1:03d}-{number:05d}.jpg')
            try:
                image.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                image.convert('RGB').save(target, 'JPEG', quality=82)
                ctx.add_output(target)
                metadata['pages'].append(dict(sourceIndex=source_index, sourceName=source.name,
                                             pageNumber=number, pageCount=count, path=str(target)))
            except Exception:
                target.unlink(missing_ok=True)
                raise
            ctx.progress((source_index + number / count) / len(ctx.inputs),
                         tr(ctx, f'{source.name} · Preview {number}/{count}', f'{source.name} · {number}/{count}쪽 미리보기'))
        try:
            if source.suffix.lower() == '.pdf':
                with pymupdf.open(source) as document:
                    if document.needs_pass:
                        raise PluginError(tr(ctx, 'Choose an unlocked PDF.', '암호를 해제한 PDF를 선택해 주세요.'))
                    for number, page in enumerate(document, 1):
                        scale = min(1.5, 1000 / max(page.rect.width, page.rect.height))
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
                        with Image.frombytes('RGB', (pix.width, pix.height), pix.samples) as image:
                            save_page(image, number, document.page_count)
            else:
                with Image.open(source) as original:
                    count = getattr(original, 'n_frames', 1)
                    for index in range(count):
                        original.seek(index)
                        with ImageOps.exif_transpose(original).convert('RGB') as image:
                            save_page(image, index + 1, count)
        except Exception as exc:
            ctx.check_cancelled()
            metadata['errors'].append({'sourceName': source.name, 'message': str(exc)[:300]})
    target = ctx.output_path('metadata.json')
    target.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    ctx.add_output(target)
    return ctx.result(tr(ctx, f"Created {len(metadata['pages'])} page previews.", f"{len(metadata['pages'])}쪽 미리보기를 만들었습니다."))


def save_text(ctx):
    content = ctx.options.get('text')
    if 'draftPath' in ctx.options:
        from pathlib import Path
        content=Path(ctx.options['draftPath']).read_text(encoding='utf-8-sig')
    if not isinstance(content, str):
        raise PluginError(tr(ctx, 'Text is required to save.', '저장할 텍스트가 필요합니다.'))
    name = ctx.options.get('name', 'OCR')
    if not isinstance(name, str) or len(name) > 160:
        raise PluginError(tr(ctx, 'Check the text file name.', '텍스트 파일 이름을 확인해 주세요.'))
    # The plugin reserves a unique output filename.
    target = ctx.output_path(name + '_edited.txt')
    try:
        target.write_text(content, encoding='utf-8-sig')
        ctx.add_output(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return ctx.result(tr(ctx, 'Saved your edits as a new file in the CanDo output folder.', '편집한 텍스트를 CanDo 결과 폴더에 새 파일로 저장했습니다.'))

def process(ctx, as_pdf):
    try:
        import pymupdf
        import ocr_engine as engine
    except ImportError as exc:
        raise PluginError(tr(ctx, 'The OCR dependencies could not be loaded. Prepare this plugin environment in CanDo.', 'OCR 의존성을 불러오지 못했습니다. CanDo에서 플러그인 환경을 준비해 주세요.')) from exc
    if not ctx.inputs:
        raise PluginError(tr(ctx, 'Choose a PDF or image.', 'PDF 또는 이미지를 선택해 주세요.'))
    failed = 0
    for file_index, source in enumerate(ctx.inputs):
        ctx.check_cancelled()
        total, pages = engine.load_source(str(source))
        target = None
        document = None
        text_file = None
        backend = None
        try:
            ctx.progress(file_index / len(ctx.inputs), tr(ctx, 'Preparing OCR engine…', 'OCR 엔진 준비 중…'))
            backend = OCRSession(ctx,total)
            target = ctx.output_path(source.stem + ('_OCR.pdf' if as_pdf else '.txt'))
            if as_pdf:
                document = pymupdf.open()
                font = engine._load_text_font()
            else:
                text_file = target.open('w', encoding='utf-8-sig')
                text_file.write(tr(ctx, f'[OCR engine: {backend.name}]\n\n', f'[OCR 엔진: {backend.name}]\n\n'))
            for page_number, img, ppp in pages:
                try:
                    ctx.check_cancelled()
                    text, error, segments = backend.recognize(img)
                    ctx.check_cancelled()
                    qrs = engine.detect_qr(img)
                    if error:
                        failed += 1
                        text = tr(ctx, f'[OCR failed: {error}]', f'[OCR 실패: {error}]')
                    if as_pdf:
                        page = document.new_page(width=img.width * ppp, height=img.height * ppp)
                        buffer = io.BytesIO()
                        img.save(buffer, format='JPEG', quality=engine.JPEG_QUALITY)
                        page.insert_image(page.rect, stream=buffer.getvalue())
                        engine._draw_text_layer(page, segments + qrs, font, ppp)
                    else:
                        text_file.write(tr(ctx, f'===== Page {page_number} / {total} =====\n{text}\n', f'===== 페이지 {page_number} / {total} =====\n{text}\n'))
                        for j, qr in enumerate(qrs, 1):
                            text_file.write(f'[QR {j}] {qr["text"]}\n')
                        text_file.write('\n')
                    ctx.progress((file_index + page_number / total) / len(ctx.inputs), tr(ctx, f'{source.name} · Page {page_number}/{total} · {backend.name}', f'{source.name} · {page_number}/{total}쪽 · {backend.name}'))
                finally:
                    img.close()
            if as_pdf:
                document.subset_fonts()
                document.save(target, garbage=4, deflate=True)
            else:
                text_file.close()
            ctx.add_output(target)
        except Exception:
            if text_file:
                text_file.close()
            if target:
                target.unlink(missing_ok=True)
            raise
        finally:
            if backend:
                backend.close()
            pages.close()
            if document:
                document.close()
            if text_file:
                text_file.close()
    warning = tr(ctx, f' Warning: OCR failed on {failed} pages. Check the source images or failure markers.', f' 주의: {failed}쪽에서 OCR에 실패했습니다. 원본 이미지 또는 실패 표시를 확인해 주세요.') if failed else ''
    return ctx.result(tr(ctx, f'Saved {len(ctx.inputs)} documents.', f'{len(ctx.inputs)}개 문서를 저장했습니다.') + warning)

def text(ctx):
    return process(ctx, False)

def searchable_pdf(ctx):
    return process(ctx, True)
