# -*- coding: utf-8 -*-
"""
pdfOCR_local — PDF·이미지(jpg/png/bmp/tif/gif/webp)를 페이지별 이미지로 다뤄
OneOCR(윈도우 캡처 도구 엔진)로 텍스트를 추출하고, 각 페이지의 QR도 검출·디코딩한다.
두 가지 출력 모드를 PDF·이미지 파일 우클릭 메뉴로 제공한다.
  - 텍스트로 변환:        같은 이름의 .txt 저장 (QR은 [QR n] 줄로 추가)
  - 검색 가능한 PDF로 변환: 이미지 위에 투명 텍스트를 얹어 드래그·검색 가능한
                          이름_OCR.pdf 저장 (QR 내용은 QR 위치에 투명 텍스트)

QR은 zxing-cpp로 페이지당 여러 개까지 검출하며, OCR 엔진과 무관하게 동작한다.

사용법:
    python pdfocr_local.py               # 우클릭 컨텍스트 메뉴 등록 (설치)
    python pdfocr_local.py --uninstall   # 컨텍스트 메뉴 제거
    python pdfocr_local.py --txt <파일>  # txt로 저장 (기본)
    python pdfocr_local.py --pdf <파일>  # 검색 가능한 PDF로 저장
"""
import os
import shutil
import sys
import time
import traceback

# 콘솔 코드페이지(cp949 등)에 없는 문자가 출력에 섞여도 죽지 않게 한다
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass

# 우클릭 메뉴를 .pdf와 이미지(perceived type=image: jpg/png/bmp/tif/gif/webp)에 등록
MENU_SCOPES = (
    r"Software\Classes\SystemFileAssociations\.pdf\shell",
    r"Software\Classes\SystemFileAssociations\image\shell",
)
MENU_VERBS = (
    ("pdfOCR_local_txt", "텍스트로 변환(pdfOCR_local)", "--txt"),
    ("pdfOCR_local_pdf", "검색 가능한 PDF로 변환(pdfOCR_local)", "--pdf"),
)
MENU_LEGACY = r"Software\Classes\SystemFileAssociations\.pdf\shell\pdfOCR_local"  # 구버전 단일 메뉴
SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif", ".webp")
RENDER_DPI = 200          # 페이지 렌더링 해상도 (OCR 품질/속도 균형)
MAX_SIDE = 4000           # OCR 입력 이미지 한 변 최대 픽셀 (초과 시 축소)
MIN_SIDE = 50             # OneOCR 엔진이 거부하는 최소 변 길이 (미만이면 확대)
ENGINE_MAX = 10000        # OneOCR 엔진이 거부하는 최대 변 길이
JPEG_QUALITY = 88         # 검색 가능한 PDF에 넣을 페이지 이미지 압축 품질
MUTEX_NAME = "Local\\pdfOCR_local_engine"  # 동시 변환 1개로 제한 (다중 선택 대비)
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "oneocr")
ENGINE_FILES = ("oneocr.dll", "oneocr.onemodel", "onnxruntime.dll")

SCRIPT_PATH = os.path.abspath(__file__)
PROJECT_DIR = os.path.dirname(SCRIPT_PATH)
VENV_PYTHON = os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe")


def _copy_engine_file(src, dst_dir):
    """엔진 파일 복사. WindowsApps 원본의 읽기 전용 속성이 따라오지 않게 푼다."""
    import stat
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.isfile(dst):
        os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)
    shutil.copy2(src, dst)
    os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)


def ensure_engine_files():
    """OneOCR 엔진 파일을 ~/.config/oneocr 에 준비한다.

    프로젝트 백업본(oneocr_files) → 윈도우 앱 패키지(캡처 도구/Photos) 순으로
    찾는다. 저장소를 갓 클론한 직후에는 백업본이 없으므로(.gitignore 대상)
    앱 패키지에서 자동으로 가져온다.
    """
    missing = [f for f in ENGINE_FILES if not os.path.isfile(os.path.join(CONFIG_DIR, f))]
    if not missing:
        return
    src_dir = CONFIG_DIR
    if all(os.path.isfile(os.path.join(src_dir, f)) for f in ENGINE_FILES):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        for name in missing:
            _copy_engine_file(os.path.join(src_dir, name), CONFIG_DIR)
        return
    print("OneOCR 엔진 파일이 없어 윈도우 앱 패키지에서 가져옵니다...")
    if not restore_engine_files():
        raise FileNotFoundError(
            "OneOCR 엔진 파일을 찾을 수 없습니다.\n"
            "윈도우 캡처 도구(Snipping Tool)나 Photos 앱이 설치되어 있지 않은 것 같습니다.\n"
            f"캡처 도구 폴더에서 {', '.join(ENGINE_FILES)} 를 {src_dir} 에 직접 복사해 주세요."
        )


def find_appx_engine_sources():
    """윈도우 앱 패키지(캡처 도구, Photos)에서 OneOCR 파일 세트가 있는 폴더를 찾는다.

    패키지 폴더명은 버전이 바뀔 때마다 달라지므로 Get-AppxPackage로 런타임에 해석한다.
    dll과 모델은 빌드가 짝을 이루므로 반드시 같은 패키지에서 세트로 가져와야 한다.
    """
    import subprocess

    sources = []
    for pkg, sub in (("Microsoft.ScreenSketch", "SnippingTool"),
                     ("Microsoft.Windows.Photos", "")):
        try:
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-AppxPackage {pkg}).InstallLocation"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            loc = (cp.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if not loc:
            continue
        cand = os.path.join(loc, sub) if sub else loc
        if all(os.path.isfile(os.path.join(cand, f)) for f in ENGINE_FILES):
            sources.append(cand)
    return sources


def restore_engine_files():
    """손상·유실된 OneOCR 엔진 파일을 윈도우 앱 패키지에서 다시 복사한다. 성공 시 True."""
    for src_dir in find_appx_engine_sources():
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            for name in ENGINE_FILES:
                _copy_engine_file(os.path.join(src_dir, name), CONFIG_DIR)
        except OSError:
            continue
        # 프로젝트 백업본도 같이 갱신해 둔다 (실패해도 무시)
        try:
            backup_dir = CONFIG_DIR
            os.makedirs(backup_dir, exist_ok=True)
            for name in ENGINE_FILES:
                _copy_engine_file(os.path.join(src_dir, name), backup_dir)
        except OSError:
            pass
        print(f"OneOCR 엔진 파일을 복구했습니다: {src_dir}")
        return True
    return False


def prepare_image(img):
    """렌더링된 페이지를 OneOCR 입력 규격(한 변 50~10000px)에 맞춘다.

    (보정된 이미지, None, (sx, sy))를 돌려준다. sx·sy는 원본 대비 확대/축소
    배율로, 엔진이 돌려준 좌표를 원본 픽셀 좌표로 되돌릴 때 쓴다.
    맞출 수 없는 극단적 비율이면 (None, 사유, None).
    """
    import math
    from PIL import Image

    ow, oh = img.size
    w, h = ow, oh
    if max(w, h) > MAX_SIDE:
        scale = MAX_SIDE / max(w, h)
        w, h = max(round(w * scale), 1), max(round(h * scale), 1)
    if min(w, h) < MIN_SIDE:
        scale = MIN_SIDE / min(w, h)
        w, h = math.ceil(w * scale), math.ceil(h * scale)
        if max(w, h) > ENGINE_MAX:
            return None, "페이지 비율이 극단적이어서 OCR 불가", None
    if (w, h) != (ow, oh):
        img = img.resize((w, h), Image.Resampling.LANCZOS)
    # oneocr 1.0.12의 recognize_pil은 BGRA 변환이 무변환(no-op) 버그라
    # 엔진에 R/B가 뒤바뀐 채 전달된다. 미리 R/B를 바꿔 실제 BGRA가 가도록 보정.
    r, g, b = img.split()
    return Image.merge("RGB", (b, g, r)), None, (w / ow, h / oh)


def _quad_to_bbox(rect, sx, sy):
    """OneOCR의 4꼭짓점 rect를 (x0,y0,x1,y1) 정렬 사각형으로, 원본 좌표로 환산."""
    xs = (rect["x1"], rect["x2"], rect["x3"], rect["x4"])
    ys = (rect["y1"], rect["y2"], rect["y3"], rect["y4"])
    return (min(xs) / sx, min(ys) / sy, max(xs) / sx, max(ys) / sy)


class OneOcrBackend:
    """1순위: 윈도우 캡처 도구의 OneOCR 엔진 (역공학 바인딩)."""

    name = "OneOCR"

    def __init__(self):
        import oneocr
        self.engine = oneocr.OcrEngine()

    def recognize(self, img):
        """(텍스트, 오류, 줄목록)을 돌려준다.

        줄목록 = [{'text', 'bbox': (x0,y0,x1,y1)}] (입력 img의 픽셀 좌표).
        검색 가능한 PDF의 텍스트 레이어는 '줄' 단위로 심는다 — OneOCR은 한글을
        음절 단위 단어로 쪼개므로(예: '하나은행'→'하 나 은 행') 단어 박스를 따로
        심으면 PDF 추출 시 글자마다 공백이 끼지만, line['text']는 올바른
        띄어쓰기를 담고 있어 줄 단위로 심으면 추출이 깨끗하다.
        오류가 None이 아니면 페이지 실패.
        """
        prepared, skip_reason, scale = prepare_image(img)
        if prepared is None:
            return "", skip_reason, []
        result = self.engine.recognize_pil(prepared)
        sx, sy = scale
        segments = []
        for line in result.get("lines") or []:
            rect, txt = line.get("bounding_rect"), line.get("text")
            if rect and txt:
                segments.append({"text": txt, "bbox": _quad_to_bbox(rect, sx, sy)})
        return (result.get("text") or "").strip(), result.get("error"), segments


class RapidOcrBackend:
    """백업: RapidOCR + PP-OCRv5 한국어 인식 모델 (ONNX Runtime, 완전 로컬).

    검출은 기본 ch_PP-OCRv4_det 사용 — 실측에서 multi(v3)·v5 det보다
    한국어 문서를 라인 단위로 훨씬 안정적으로 잡는다.

    실행 장치: DirectML(DX12 GPU — NVIDIA/AMD/인텔 모두 해당)이 가능하고
    문서가 길면 GPU, 아니면 CPU. 이 PC(Iris Xe) 실측: CPU 3.2초/페이지,
    DirectML 1.65초/페이지 — 단 첫 실행 셰이더 컴파일 ~30초 때문에
    약 20페이지부터 GPU가 이득. PDFOCR_RAPIDOCR_DEVICE=cpu|gpu 로 강제 가능.
    """

    DML_MIN_PAGES = 20

    def __init__(self, page_count=None):
        use_dml = self._should_use_dml(page_count)
        try:
            self.engine = self._build(use_dml)
        except Exception:
            if not use_dml:
                raise
            self.engine = self._build(False)  # GPU 초기화 실패 시 CPU로
            use_dml = False
        self.name = f"RapidOCR (PP-OCRv5 korean, {'DirectML GPU' if use_dml else 'CPU'})"

    @staticmethod
    def _build(use_dml):
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangRec, OCRVersion, ModelType
        return RapidOCR(params={
            "Det.ocr_version": OCRVersion.PPOCRV4,
            "Det.model_type": ModelType.MOBILE,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.KOREAN,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            # 중국어 학습 방향 분류기가 정상 한국어 줄을 180° 회전으로 오판해
            # 인식을 망가뜨리는 것을 실측으로 확인 — 비활성화
            "Global.use_cls": False,
            "Global.log_level": "warning",
            "EngineConfig.onnxruntime.use_dml": use_dml,
        })

    @classmethod
    def _should_use_dml(cls, page_count):
        forced = os.environ.get("PDFOCR_RAPIDOCR_DEVICE", "").lower()
        if forced == "cpu":
            return False
        try:
            import onnxruntime as ort
            available = "DmlExecutionProvider" in ort.get_available_providers()
        except ImportError:
            available = False
        if forced in ("gpu", "dml"):
            return available
        # 자동: DML 가능 + 실제 GPU 존재 + 워밍업 비용을 상쇄할 만큼 긴 문서
        return (available
                and page_count is not None and page_count >= cls.DML_MIN_PAGES
                and cls._has_real_gpu())

    @staticmethod
    def _has_real_gpu():
        """가상/원격 디스플레이 어댑터만 있는 환경(VM, RDP)에서는 DML이 WARP
        소프트웨어 렌더러로 떨어져 CPU보다 느릴 수 있으므로 실제 GPU를 확인한다."""
        import re
        import subprocess
        try:
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return False
        fake = re.compile(r"Microsoft Basic|Remote|Virtual|VMware|VBox|Hyper-V", re.I)
        return any(name.strip() and not fake.search(name)
                   for name in (cp.stdout or "").splitlines())

    def recognize(self, img):
        """(텍스트, 오류, 줄목록)을 돌려준다.

        RapidOCR의 검출 단위는 줄(영역)이라 bbox도 줄 단위다 — 검색 가능한 PDF에
        그대로 줄 단위로 심으면 된다. 좌표는 입력 img의 픽셀 좌표로 환산한다.
        """
        import numpy as np
        ow, oh = img.size
        sx = sy = 1.0
        if max(ow, oh) > MAX_SIDE:
            from PIL import Image
            scale = MAX_SIDE / max(ow, oh)
            nw, nh = max(round(ow * scale), 1), max(round(oh * scale), 1)
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
            sx, sy = nw / ow, nh / oh
        bgr = np.asarray(img)[:, :, ::-1]  # RapidOCR은 cv2 관례(BGR) 입력
        result = self.engine(bgr)
        txts = result.txts or []
        segments = []
        if result.boxes is not None:
            for box, txt in zip(result.boxes, txts):
                if not txt:
                    continue
                arr = np.asarray(box)
                xs, ys = arr[:, 0], arr[:, 1]
                segments.append({"text": txt, "bbox": (
                    float(xs.min()) / sx, float(ys.min()) / sy,
                    float(xs.max()) / sx, float(ys.max()) / sy)})
        return "\n".join(txts).strip(), None, segments


def load_engine(page_count=None):
    """OneOCR → 엔진 파일 자동 복구 후 재시도 → RapidOCR 순으로 폴백한다.

    PDFOCR_FORCE_ENGINE=rapidocr 환경 변수로 백업 엔진을 강제할 수 있다(테스트·비교용).
    page_count는 RapidOCR의 CPU/GPU 자동 선택에 쓰인다.
    """
    if os.environ.get("PDFOCR_FORCE_ENGINE", "").lower() == "rapidocr":
        print("PDFOCR_FORCE_ENGINE=rapidocr — 백업 엔진을 강제 사용합니다.")
        return RapidOcrBackend(page_count)

    try:
        ensure_engine_files()
        return OneOcrBackend()
    except Exception as e:
        print(f"OneOCR 로딩 실패: {e}")

    print("윈도우 앱 패키지에서 엔진 파일 복구를 시도합니다...")
    if restore_engine_files():
        try:
            return OneOcrBackend()
        except Exception as e:
            print(f"복구 후에도 OneOCR 로딩 실패: {e}")

    print("백업 엔진 RapidOCR(PP-OCRv5 한국어)로 전환합니다.")
    return RapidOcrBackend(page_count)


def load_source(path):
    """PDF/이미지 파일을 열어 (총 페이지 수, 페이지 생성기)를 돌려준다.

    생성기는 (index, PIL.RGB, ppp)를 순서대로 yield한다. ppp(points per pixel)는
    픽셀 좌표를 PDF 포인트로 환산하는 계수로, 검색 가능한 PDF 좌표 매핑에 쓰인다.
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"파일이 없습니다: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _load_pdf_source(path)
    if ext in SUPPORTED_IMAGE_EXTS:
        return _load_image_source(path)
    raise RuntimeError(f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'}")


def _load_pdf_source(path):
    import pymupdf
    from PIL import Image

    print(f"PDF 열기: {path}")
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise RuntimeError("암호로 보호된 PDF입니다. 암호 해제 후 다시 시도해 주세요.")
    if doc.page_count == 0:
        raise RuntimeError("페이지가 없는 PDF입니다 (파일이 손상되었을 수 있습니다).")
    zoom = RENDER_DPI / 72.0

    def gen():
        try:
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom),
                                      colorspace=pymupdf.csRGB, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                yield i, img, 72.0 / RENDER_DPI
        finally:
            doc.close()

    return doc.page_count, gen()


def _load_image_source(path):
    from PIL import Image, ImageSequence

    print(f"이미지 열기: {path}")
    im = Image.open(path)
    frames = [f.convert("RGB") for f in ImageSequence.Iterator(im)]  # 다중 프레임 TIFF 등 대응
    dpi = im.info.get("dpi", (96, 96))
    d = dpi[0] if isinstance(dpi, (tuple, list)) else dpi
    ppp = 72.0 / (d if d and d > 1 else 96)

    def gen():
        for i, frame in enumerate(frames, start=1):
            yield i, frame, ppp

    return len(frames), gen()


def detect_qr(img):
    """페이지 이미지에서 QR을 검출·디코딩한다 (엔진 무관, zxing-cpp 사용).

    반환: [{'text': str, 'bbox': (x0,y0,x1,y1)}] (입력 img의 픽셀 좌표).
    한 페이지에 여러 개여도 모두 반환. zxing이 없거나 오류면 [](기능 비활성)로
    OCR 본체에 영향을 주지 않는다. zxing은 해상도에 강건해 200 DPI에서도 검출된다.
    """
    try:
        import zxingcpp
    except ImportError:
        return []
    import numpy as np
    gray = np.asarray(img.convert("L"))
    try:
        results = zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode)
    except Exception:
        return []
    out = []
    for r in results:
        if not r.text:
            continue
        p = r.position
        xs = (p.top_left.x, p.top_right.x, p.bottom_right.x, p.bottom_left.x)
        ys = (p.top_left.y, p.top_right.y, p.bottom_right.y, p.bottom_left.y)
        out.append({"text": r.text, "bbox": (min(xs), min(ys), max(xs), max(ys))})
    return out


def _load_text_font():
    """투명 텍스트 레이어용 폰트 — 한글+영문+숫자를 모두 인코딩할 수 있어야 한다."""
    import pymupdf
    for path in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
                 r"C:\Windows\Fonts\batang.ttc"):
        if os.path.isfile(path):
            return pymupdf.Font(fontfile=path)
    return pymupdf.Font("korea")  # 폴백: 내장 CJK 폰트


def _draw_text_layer(page, segments, font, ppp):
    """줄 박스(입력 픽셀 좌표)에 맞춰 투명 텍스트를 줄 단위로 얹는다(render_mode=3).

    ppp = points per pixel(픽셀→포인트 환산 계수). 줄 단위로 심으므로 PDF 추출 시
    줄 안에서 불필요한 공백이 끼지 않는다.
    """
    import pymupdf
    tw = pymupdf.TextWriter(page.rect)
    placed = 0
    for seg in segments:
        x0, y0, x1, y1 = (c * ppp for c in seg["bbox"])
        bw, bh = x1 - x0, y1 - y0
        if bw <= 0 or bh <= 0:
            continue
        fs = bh * 0.92
        tl = font.text_length(seg["text"], fontsize=fs)
        if tl <= 0:
            continue
        fs *= bw / tl  # 글자 폭을 줄 박스 폭에 맞춰 드래그 정렬을 정확히
        tw.append(pymupdf.Point(x0, y1 - bh * 0.18), seg["text"], font=font, fontsize=fs)
        placed += 1
    if placed:
        tw.write_text(page, render_mode=3)
    return placed
