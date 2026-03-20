# src/testmaker/services/pdf_exporter.py

from __future__ import annotations

from dataclasses import dataclass, replace, fields
from pathlib import Path
from typing import Dict, List, Optional, Tuple, NamedTuple

import re
import fitz  # PyMuPDF
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from testmaker.utils.paths import fonts_dir
from testmaker.services.header_themes import ReportLabDrawer, draw_theme_header, pt_to_mm, mm_to_pt as _mm_to_pt_theme


# -------------------------
# Layout Data Structures
# -------------------------
@dataclass
class QuestionLayoutInfo:
    """Bir sorunun layout bilgileri (pozisyon, boyut, sütun, sayfa)"""
    question_index: int  # Soru indeksi (selections listesindeki)
    page_num: int  # Sayfa numarası (1'den başlar)
    col_idx: int  # Sütun indeksi (0'dan başlar)
    x_pt: float  # X pozisyonu (pt)
    y_top_pt: float  # Y üst pozisyonu (PDF koordinat sistemi, pt)
    y_bottom_pt: float  # Y alt pozisyonu (PDF koordinat sistemi, pt)
    draw_w_pt: float  # Görsel genişliği (pt)
    draw_h_pt: float  # Görsel yüksekliği (pt)
    box_h_pt: float  # Numara yüksekliği (pt)
    gap_after_pt: float  # Sorudan sonraki boşluk (pt)
    number: int  # Soru numarası


@dataclass
class LayoutResult:
    """Layout hesaplama sonucu"""
    question_layouts: List[QuestionLayoutInfo]  # Tüm soruların layout bilgileri
    pages: List[List[int]]  # Sayfalara göre soru indeksleri [[0,1,2], [3,4,5], ...]


# Türkçe karakterleri destekleyen font yükle
_roboto_font_loaded = False


def _ensure_roboto_font():
    """Roboto fontunu yükle (Türkçe karakterleri destekler)"""
    global _roboto_font_loaded
    if _roboto_font_loaded:
        return

    try:
        roboto_path = fonts_dir() / "roboto" / "static" / "Roboto-Regular.ttf"
        roboto_bold_path = fonts_dir() / "roboto" / "static" / "Roboto-Bold.ttf"

        if roboto_path.exists():
            pdfmetrics.registerFont(TTFont("Roboto", str(roboto_path)))
        if roboto_bold_path.exists():
            pdfmetrics.registerFont(TTFont("Roboto-Bold", str(roboto_bold_path)))

        _roboto_font_loaded = True
    except Exception:
        # Font yüklenemezse varsayılan font kullanılacak
        pass


# -------------------------
# Helpers
# -------------------------
def mm_to_pt(mm: float) -> float:
    # 1 inch = 25.4 mm, 1 pt = 1/72 inch
    return float(mm) * 72.0 / 25.4


def preset_size_mm(preset: str) -> Tuple[float, float]:
    p = (preset or "A4").upper().strip()

    # ISO A series (mm)
    iso_a = {
        "A0": (841.0, 1189.0),
        "A1": (594.0, 841.0),
        "A2": (420.0, 594.0),
        "A3": (297.0, 420.0),
        "A4": (210.0, 297.0),
        "A5": (148.0, 210.0),
        "A6": (105.0, 148.0),
    }
    if p in iso_a:
        return iso_a[p]

    # ISO B series (common)
    iso_b = {
        "B4": (250.0, 353.0),
        "B5": (176.0, 250.0),
    }
    if p in iso_b:
        return iso_b[p]

    # US sizes
    if p in ("LETTER", "US LETTER"):
        return 215.9, 279.4
    if p == "LEGAL":
        return 215.9, 355.6
    if p in ("TABLOID", "LEDGER"):
        return 279.4, 431.8  # 11x17 in
    if p == "EXECUTIVE":
        return 184.15, 266.7
    if p == "FOLIO":
        return 210.0, 330.0

    # fallback
    return 210.0, 297.0


# -------------------------
# Options
# -------------------------
@dataclass
class ExportOptions:
    # Meta
    test_title: str = "TEST"
    school_name: str = ""
    branch_name: str = ""
    teacher_name: str = ""
    # "Test ile ilgili açıklama ekle" içeriği (boşsa kapakta kutu çizilmez)
    test_description: str = ""
    # Header theme selection
    header_style_id: str = "style1"   # "style1" | "style2" | "style3"
    theme_color: str = "#AECBFA"      # pastel theme color
    use_description_box: bool = False
    # Answer key
    answer_key_enabled: bool = False
    answer_key_mode: str = "per_page"  # "per_page" | "separate_page" | "end_of_test"

    # Question font normalization (auto scale per question)
    normalize_question_font: bool = True
    target_question_font_pt: float = 11.0
    normalize_min_scale: float = 0.70
    normalize_max_scale: float = 1.45
    normalize_fallback_observed_pt: float = 12.0

    # Page size
    page_preset: str = "A4"          # A4, A5, LETTER, LEGAL, CUSTOM
    page_width_mm: float = 210.0     # used when CUSTOM
    page_height_mm: float = 297.0    # used when CUSTOM
    orientation: str = "portrait"    # portrait / landscape

    # Advanced
    smart_layout: bool = False
    watermark_enabled: bool = False
    # Watermark
    watermark_mode: str = "text"  # "text" | "image"
    watermark_text: str = ""
    watermark_text_opacity_pct: int = 20
    watermark_text_size_pct: int = 90
    watermark_text_angle_deg: int = 45
    watermark_text_color: str = "#AECBFA"
    watermark_image_path: str = ""
    watermark_image_opacity_pct: int = 15
    watermark_image_size_pct: int = 50
    # Backward-compatible field (used by older UI)
    watermark_opacity: float = 0.12
    center_line_enabled: bool = False
    center_line_text: str = ""
    center_line_bold: bool = False
    center_line_color: str = "#000000"
    center_line_text_direction: str = "up"  # up / down
    line_color: str = "#000000"  # Tüm çizgiler için renk (sütun çizgisi, separator vb.)

    # Layout
    columns: int = 2                # 1..6
    column_gap_mm: float = 8.0      # gap between columns in mm
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 15.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0

    # Spacing
    question_gap_mm: float = 35.0       # normal (varsayılan 35mm)
    question_gap_spaced_mm: float = 35.0
    spaced: bool = False
    draw_separators: bool = False       # optional separator lines when spaced
    header_bottom_gap_mm: float = 10.0  # Gap between header bottom and questions on pages 2+ (default 10mm)

    # Rendering
    zoom: float = 4.0  # Yüksek kalite: 4.0 = ~288 DPI (72 * 4 = 288 DPI)

    def page_size_pt(self) -> Tuple[float, float]:
        if (self.page_preset or "").upper().strip() == "CUSTOM":
            w_mm, h_mm = float(self.page_width_mm), float(self.page_height_mm)
        else:
            w_mm, h_mm = preset_size_mm(self.page_preset)

        w_pt, h_pt = mm_to_pt(w_mm), mm_to_pt(h_mm)

        if (self.orientation or "portrait").lower().startswith("land"):
            return h_pt, w_pt
        return w_pt, h_pt

    def margins_pt(self) -> Tuple[float, float, float, float]:
        return (
            mm_to_pt(self.margin_left_mm),
            mm_to_pt(self.margin_right_mm),
            mm_to_pt(self.margin_top_mm),
            mm_to_pt(self.margin_bottom_mm),
        )

    def column_gap_pt(self) -> float:
        return mm_to_pt(self.column_gap_mm)

    def question_gap_pt(self) -> float:
        return mm_to_pt(self.question_gap_spaced_mm if self.spaced else self.question_gap_mm)
    
    def header_bottom_gap_pt(self) -> float:
        """Convert header bottom gap from mm to pt"""
        return mm_to_pt(self.header_bottom_gap_mm)


# -------------------------
# Gap Clamping Constants
# -------------------------
MIN_GAP_MM = 6.0   # Minimum gap between questions (mm)
MAX_GAP_MM = 50.0  # Maximum gap between questions (mm)
MIN_GAP_PT = mm_to_pt(MIN_GAP_MM)  # ~17.01 pt
MAX_GAP_PT = mm_to_pt(MAX_GAP_MM)  # ~141.73 pt


def clamp_gap_pt(gap_pt: Optional[float], default_gap_pt: float) -> float:
    """
    Clamp gap to MIN_GAP_PT..MAX_GAP_PT range.
    
    Args:
        gap_pt: Custom gap in points (None = use default)
        default_gap_pt: Default gap in points
    
    Returns:
        Clamped gap in points
    """
    if gap_pt is None:
        gap_pt = default_gap_pt
    return max(MIN_GAP_PT, min(gap_pt, MAX_GAP_PT))


# -------------------------
# Internal rendering helpers
# -------------------------
def _safe_clip_from_norm(page: fitz.Page, norm_rect_xywh: Tuple[float, float, float, float]) -> Optional[fitz.Rect]:
    """
    norm_rect = (x, y, w, h) in 0..1 of rendered page.
    Returns a safe clip rect (intersected with page rect) or None.
    """
    pr = page.rect
    fx, fy, fw, fh = norm_rect_xywh

    x0 = fx
    y0 = fy
    x1 = fx + fw
    y1 = fy + fh

    x0, x1 = sorted([x0, x1])
    y0, y1 = sorted([y0, y1])

    # clamp 0..1
    x0 = max(0.0, min(1.0, x0))
    x1 = max(0.0, min(1.0, x1))
    y0 = max(0.0, min(1.0, y0))
    y1 = max(0.0, min(1.0, y1))

    clip = fitz.Rect(
        pr.x0 + x0 * pr.width,
        pr.y0 + y0 * pr.height,
        pr.x0 + x1 * pr.width,
        pr.y0 + y1 * pr.height,
    )

    clip = clip & pr
    if clip.is_empty or clip.width < 2 or clip.height < 2:
        return None
    return clip


def _weighted_median(values_weights: List[Tuple[float, float]], fallback: float) -> float:
    """
    Weighted median for (value, weight) pairs.
    Returns fallback if empty or invalid.
    """
    try:
        vw = [(float(v), float(w)) for (v, w) in values_weights if w and w > 0]
        if not vw:
            return float(fallback)
        vw.sort(key=lambda t: t[0])
        total = sum(w for _, w in vw)
        if total <= 0:
            return float(fallback)
        acc = 0.0
        for v, w in vw:
            acc += w
            if acc >= total / 2.0:
                return float(v)
        return float(vw[-1][0])
    except Exception:
        return float(fallback)


def _estimate_font_pt_from_text_dict(
    dct: dict,
    *,
    fallback_pt: float,
    min_spans: int,
) -> Tuple[float, bool]:
    """
    Estimate median font size from a PyMuPDF get_text('dict') payload.
    Returns (pt, ok). Applies IQR filtering + practical 6..30pt clamp.
    """
    vw: List[Tuple[float, float]] = []
    sizes_unweighted: List[float] = []
    try:
        for b in dct.get("blocks", []) or []:
            for ln in b.get("lines", []) or []:
                for sp in ln.get("spans", []) or []:
                    size = sp.get("size", None)
                    txt = (sp.get("text", "") or "").strip()
                    if not txt:
                        continue
                    # Very short spans are often noise (single punctuation, etc.)
                    if len(txt) < 2:
                        continue
                    try:
                        size_f = float(size)
                    except Exception:
                        continue
                    if size_f < 4.0 or size_f > 60.0:
                        continue
                    w = float(len(txt))
                    vw.append((size_f, w))
                    sizes_unweighted.append(size_f)

        if len(vw) < int(min_spans or 0):
            return float(fallback_pt), False

        # Robust outlier filtering (IQR) + practical clamp 6..30pt
        try:
            srt = sorted(sizes_unweighted)
            q1 = srt[int(0.25 * (len(srt) - 1))]
            q3 = srt[int(0.75 * (len(srt) - 1))]
            iqr = max(0.01, q3 - q1)
            # More aggressive than classic 1.5*IQR to reduce header/footer skew
            lo = max(6.0, q1 - 1.0 * iqr)
            hi = min(30.0, q3 + 1.0 * iqr)
            vw_f = [(v, w) for (v, w) in vw if lo <= float(v) <= hi]
            if len(vw_f) >= int(min_spans or 0):
                vw = vw_f
        except Exception:
            pass

        # Prefer dominant font size (weighted mode) to avoid header/footer affecting medians.
        try:
            bins: Dict[float, float] = {}
            for v, w in vw:
                b = round(float(v) * 2.0) / 2.0  # 0.5pt bins
                bins[b] = bins.get(b, 0.0) + float(w)
            if bins:
                best_bin = max(bins.items(), key=lambda t: t[1])[0]
                tol = 0.75
                vw_near = [(v, w) for (v, w) in vw if abs(float(v) - float(best_bin)) <= tol]
                if len(vw_near) >= int(min_spans or 0):
                    return _weighted_median(vw_near, fallback_pt), True
        except Exception:
            pass

        return _weighted_median(vw, fallback_pt), True
    except Exception:
        return float(fallback_pt), False


def _estimate_font_pt_in_clip(
    doc: fitz.Document,
    page_index: int,
    norm_xywh: Tuple[float, float, float, float],
    *,
    fallback_pt: float,
) -> Tuple[float, bool]:
    """
    Estimate the typical font size (pt) inside the selection clip using PDF text spans.
    Uses a weighted median of span sizes; weights by (trimmed text length).
    """
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return float(fallback_pt), False
        page = doc.load_page(page_index)
        clip = _safe_clip_from_norm(page, norm_xywh)
        if clip is None:
            return float(fallback_pt), False

        dct = page.get_text("dict", clip=clip)
        return _estimate_font_pt_from_text_dict(dct, fallback_pt=fallback_pt, min_spans=8)
    except Exception:
        return float(fallback_pt), False


def _estimate_font_pt_from_raster_png(png_bytes: bytes, *, zoom: float, fallback_pt: float) -> float:
    """
    For scanned/image PDFs where text isn't extractable, estimate a "font pt" proxy
    from the typical connected-component height in the raster image.
    """
    try:
        import numpy as np
        import cv2

        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return float(fallback_pt)

        # Binarize (text -> white)
        img_blur = cv2.GaussianBlur(img, (3, 3), 0)
        _, th = cv2.threshold(img_blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Remove small noise
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)

        cnts, _hier = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return float(fallback_pt)

        h_list: List[float] = []
        H, W = img.shape[:2]
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            area = w * h
            if area < 20:
                continue
            if h < 6 or h > max(12, int(H * 0.25)):
                continue
            if w < 2:
                continue
            if (w / max(1.0, float(h))) > 15.0:
                continue
            h_list.append(float(h))

        if not h_list:
            return float(fallback_pt)

        # "Only letter height": pick the dominant height band (mode) from mid-range heights.
        # This avoids dots/noise (very small) and merged/ascender-heavy components (very tall).
        h_arr = np.array(h_list, dtype=np.float32)
        h_arr.sort()
        n = int(h_arr.shape[0])
        if n >= 12:
            lo_idx = int(0.30 * n)
            hi_idx = int(0.85 * n)
            if hi_idx <= lo_idx:
                lo_idx, hi_idx = 0, n
            h_mid = h_arr[lo_idx:hi_idx]
        else:
            h_mid = h_arr

        # Histogram with 1px bins to find dominant letter-height band
        h_int = np.clip(np.rint(h_mid).astype(np.int32), 1, 10000)
        uniq, cnt = np.unique(h_int, return_counts=True)
        mode_h = int(uniq[int(np.argmax(cnt))])
        # Use median of heights near the mode (±1px)
        near = h_mid[(np.abs(h_mid - float(mode_h)) <= 1.0)]
        if near.size >= 3:
            med_h_px = float(np.median(near))
        else:
            med_h_px = float(np.median(h_mid))
        if zoom <= 0:
            return float(fallback_pt)

        # Convert pixel height to pt-ish: px ≈ pt * zoom (since DPI=72*zoom).
        # We intentionally DO NOT apply an "em factor" here; we want a direct optical height proxy.
        observed_pt = (med_h_px / float(zoom))
        # Empirical calibration: connected-component heights tend to slightly overestimate
        # the "pt-equivalent" on typical scanned question PDFs. This factor brings the
        # optical method closer to the selectable-text method (≈ +10% scale).
        observed_pt = observed_pt / 1.10
        if observed_pt < 4.0 or observed_pt > 60.0:
            return float(fallback_pt)
        return float(observed_pt)
    except Exception:
        return float(fallback_pt)


def _render_selection_png_bytes(
    doc: fitz.Document,
    page_index: int,
    norm_xywh: Tuple[float, float, float, float],
    zoom: float,
) -> Optional[Tuple[bytes, int, int]]:
    if page_index < 0 or page_index >= doc.page_count:
        return None

    page = doc.load_page(page_index)
    clip = _safe_clip_from_norm(page, norm_xywh)
    if clip is None:
        return None

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    return pix.tobytes("png"), pix.width, pix.height


def _png_size_from_bytes(png: bytes) -> Optional[Tuple[int, int]]:
    """Get PNG (w,h) without extra deps.

    PNG IHDR chunk stores width/height in bytes 16..23 (big-endian).
    """
    try:
        if not png or len(png) < 24:
            return None
        # PNG signature
        if png[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w = int.from_bytes(png[16:20], "big")
        h = int.from_bytes(png[20:24], "big")
        if w <= 0 or h <= 0:
            return None
        return w, h
    except Exception:
        return None


def _render_selection_from_embedded(sel) -> Optional[Tuple[bytes, int, int]]:
    png = getattr(sel, "embedded_png", None)
    if not png:
        return None
    w = getattr(sel, "embedded_w_px", None)
    h = getattr(sel, "embedded_h_px", None)
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        return png, w, h
    sz = _png_size_from_bytes(png)
    if sz:
        return png, sz[0], sz[1]
    return None


def _get_font_name(bold: bool = False) -> str:
    """Roboto fontunu kullan, yoksa varsayılan fonta dön"""
    try:
        from reportlab.pdfbase.pdfmetrics import getFont
        if getFont('Roboto-Bold' if bold else 'Roboto'):
            return 'Roboto-Bold' if bold else 'Roboto'
    except Exception:
        pass
    return 'Helvetica-Bold' if bold else 'Helvetica'


def _draw_watermark_and_centerline(c: canvas.Canvas, page_w: float, page_h: float, opts: ExportOptions) -> None:
    """Draw optional watermark (text or image) and (optionally) center-line text.

    Watermark settings are provided in ExportOptions:
      - watermark_enabled
      - watermark_mode: 'text' or 'image'
      - text: watermark_text, watermark_text_opacity_pct, watermark_text_size_pct, watermark_text_angle_deg, watermark_text_color
      - image: watermark_image_path, watermark_image_opacity_pct, watermark_image_size_pct
    """
    if not getattr(opts, 'watermark_enabled', False):
        # Center line is handled elsewhere in this project
        return

    mode = (getattr(opts, 'watermark_mode', 'text') or 'text').strip().lower()

    def _hex_to_rgb(col: str):
        col = (col or '').strip()
        if col.startswith('#'):
            col = col[1:]
        if len(col) == 3:
            col = ''.join(ch*2 for ch in col)
        if len(col) != 6:
            return (0, 0, 0)
        try:
            r = int(col[0:2], 16)
            g = int(col[2:4], 16)
            b = int(col[4:6], 16)
            return (r, g, b)
        except Exception:
            return (0, 0, 0)

    try:
        if mode == 'image':
            img_path = (getattr(opts, 'watermark_image_path', '') or '').strip()
            if not img_path:
                return

            # Apply opacity by converting to RGBA and multiplying alpha
            try:
                from PIL import Image
                from reportlab.lib.utils import ImageReader

                op_pct = float(getattr(opts, 'watermark_image_opacity_pct', 15.0))
                op = max(0.0, min(1.0, op_pct / 100.0))

                im = Image.open(img_path)
                im = im.convert('RGBA')
                r, g, b, a = im.split()
                # Multiply existing alpha
                a = a.point(lambda v: int(v * op))
                im = Image.merge('RGBA', (r, g, b, a))

                # Scale relative to page
                size_pct = float(getattr(opts, 'watermark_image_size_pct', 50.0))
                size_factor = max(0.05, min(2.0, size_pct / 100.0))

                # Target width ~ 70% of page at 100%
                target_w = page_w * 0.70 * size_factor
                ratio = im.height / float(im.width) if im.width else 1.0
                target_h = target_w * ratio

                # Center
                x = (page_w - target_w) / 2.0
                y = (page_h - target_h) / 2.0

                c.saveState()
                c.drawImage(ImageReader(im), x, y, width=target_w, height=target_h, mask='auto', preserveAspectRatio=True, anchor='c')
                c.restoreState()
                return
            except ImportError:
                # PIL not available: draw without opacity control
                from reportlab.lib.utils import ImageReader
                size_pct = float(getattr(opts, 'watermark_image_size_pct', 50.0))
                size_factor = max(0.05, min(2.0, size_pct / 100.0))
                target_w = page_w * 0.70 * size_factor
                # keep aspect ratio using ImageReader size
                ir = ImageReader(img_path)
                iw, ih = ir.getSize()
                ratio = ih / float(iw) if iw else 1.0
                target_h = target_w * ratio
                x = (page_w - target_w) / 2.0
                y = (page_h - target_h) / 2.0
                c.saveState()
                c.drawImage(ir, x, y, width=target_w, height=target_h, mask='auto', preserveAspectRatio=True, anchor='c')
                c.restoreState()
                return

        # Text watermark
        txt = (getattr(opts, 'watermark_text', '') or '').strip()
        if not txt:
            return

        op_pct = float(getattr(opts, 'watermark_text_opacity_pct', 20.0))
        alpha = max(0.0, min(1.0, op_pct / 100.0))

        size_pct = float(getattr(opts, 'watermark_text_size_pct', 90.0))
        size_factor = max(0.10, min(2.50, size_pct / 100.0))

        ang = float(getattr(opts, 'watermark_text_angle_deg', 45.0))
        col = getattr(opts, 'watermark_text_color', getattr(opts, 'theme_color', '#AECBFA'))
        r, g, b = _hex_to_rgb(col)

        base = min(page_w, page_h) * 0.12
        font_size = max(10.0, base * size_factor)

        # Yazı genişliği ve yüksekliği hesapla
        from reportlab.pdfbase.pdfmetrics import stringWidth, getFont
        txt_w = stringWidth(txt, _get_font_name(bold=True), font_size)
        font_obj = getFont(_get_font_name(bold=True))
        ascent = getattr(getattr(font_obj, "face", None), "ascent", 700)
        descent = getattr(getattr(font_obj, "face", None), "descent", -200)
        txt_h = ((ascent - descent) / 1000.0) * font_size

        c.saveState()
        try:
            # Opacity ayarla (sadece yazı için, arka plan yok)
            if hasattr(c, 'setFillAlpha'):
                c.setFillAlpha(alpha)
            
            # Transform matrisini ayarla
            c.translate(page_w / 2.0, page_h / 2.0)
            c.rotate(ang)
            
            # Sadece metin rengini çiz (arka plan yok)
            c.setFillColorRGB(r/255.0, g/255.0, b/255.0)
            c.setFont(_get_font_name(bold=True), font_size)
            c.drawCentredString(0, 0, txt)
        except Exception:
            pass
        finally:
            c.restoreState()

    except Exception:
        # Fail-safe: watermark should never crash export
        pass

FIRST_PAGE_HEADER_HEIGHT_PT = 84.0
FIRST_PAGE_TOP_ROW_HEIGHT_PT = 34.0
OTHER_PAGES_HEADER_HEIGHT_PT = 40.0


def _round_rect_path(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    rtl: float = 0.0,
    rtr: float = 0.0,
    rbr: float = 0.0,
    rbl: float = 0.0,
):
    """Create a path for a per-corner rounded rectangle (ReportLab)."""
    rtl = max(0.0, min(rtl, min(w, h) / 2.0))
    rtr = max(0.0, min(rtr, min(w, h) / 2.0))
    rbr = max(0.0, min(rbr, min(w, h) / 2.0))
    rbl = max(0.0, min(rbl, min(w, h) / 2.0))

    p = c.beginPath()

    # start bottom-left
    p.moveTo(x + rbl, y)
    p.lineTo(x + w - rbr, y)
    if rbr:
        p.arcTo(x + w - 2 * rbr, y, x + w, y + 2 * rbr, startAng=270, extent=90)
    p.lineTo(x + w, y + h - rtr)
    if rtr:
        p.arcTo(x + w - 2 * rtr, y + h - 2 * rtr, x + w, y + h, startAng=0, extent=90)
    p.lineTo(x + rtl, y + h)
    if rtl:
        p.arcTo(x, y + h - 2 * rtl, x + 2 * rtl, y + h, startAng=90, extent=90)
    p.lineTo(x, y + rbl)
    if rbl:
        p.arcTo(x, y, x + 2 * rbl, y + 2 * rbl, startAng=180, extent=90)
    p.close()
    return p


def _draw_round_rect_custom(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    rtl: float,
    rtr: float,
    rbr: float,
    rbl: float,
    *,
    fill: int,
    stroke: int,
):
    p = _round_rect_path(c, x, y, w, h, rtl=rtl, rtr=rtr, rbr=rbr, rbl=rbl)
    c.drawPath(p, fill=fill, stroke=stroke)


def _hex_to_rgb01(hex_color: str, fallback: Tuple[float, float, float] = (0.68, 0.80, 0.98)) -> Tuple[float, float, float]:
    s = (hex_color or "").strip().lstrip("#")
    if len(s) != 6:
        return fallback
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
        return (r, g, b)
    except Exception:
        return fallback


def _mix_rgb(a: Tuple[float, float, float], b: Tuple[float, float, float], t: float) -> Tuple[float, float, float]:
    """Linear mix: a*(1-t) + b*t, clamped."""
    t = max(0.0, min(1.0, float(t)))
    return (a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t, a[2] * (1 - t) + b[2] * t)


def draw_first_page_header(c: canvas.Canvas, page_w: float, page_h: float, opts: ExportOptions) -> float:
    """
    Page 1 (cover): custom header layout.
    Returns the y coordinate where questions should start.

    NOTE: We intentionally keep the reserved height equal to `FIRST_PAGE_HEADER_HEIGHT_PT`
    so pagination/margins logic remains stable.
    """
    # Use unified theme renderer (same as popup preview)
    drawer = ReportLabDrawer(c, page_w_pt=page_w, page_h_pt=page_h)
    page_w_mm = pt_to_mm(page_w)
    page_h_mm = pt_to_mm(page_h)
    y_cursor_mm = draw_theme_header(
        drawer,
        page_w_mm=page_w_mm,
        page_h_mm=page_h_mm,
        style_id=getattr(opts, "header_style_id", "style3"),
        theme_color=getattr(opts, "theme_color", "#AECBFA"),
        test_title=(opts.test_title or "TEST"),
        school_name=(opts.school_name or ""),
        teacher_name=(opts.teacher_name or ""),
        use_description_box=bool(getattr(opts, "use_description_box", False)),
        test_description=(opts.test_description or ""),
    )
    # Convert top-based mm cursor to reportlab y (pt from bottom)
    return page_h - _mm_to_pt_theme(y_cursor_mm)


def draw_other_pages_header(c: canvas.Canvas, page_w: float, page_h: float, opts: ExportOptions, page_index: int) -> float:
    """
    Page 2+ (standard): compact header with symmetric left/right boxes.
    Returns the y coordinate where questions should start.
    """
    """
    User rule: other pages header is a single rounded rectangle.
    - Left: Test Adı
    - Right: Okul Adı
    - Questions start 5px-ish below the header
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth, getFont

    ml, mr, mt, _mb = opts.margins_pt()
    y_top = page_h - mt

    # Theme stroke color for all lines
    outline = _hex_to_rgb01(getattr(opts, "theme_color", "#AECBFA"), fallback=(0.65, 0.65, 0.65))
    text_dark = (0.15, 0.15, 0.15)

    box_x = ml
    box_w = page_w - ml - mr
    box_h = 24.0
    box_r = 8.0
    box_y = y_top - box_h

    left_text = (opts.test_title or "TEST").strip()
    right_text = (opts.school_name or "").strip()

    pad_x = 8.0
    half_w = (box_w / 2.0) - (2 * pad_x)

    c.saveState()
    try:
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(*outline)
        c.setLineWidth(0.8)
        c.roundRect(box_x, box_y, box_w, box_h, box_r, fill=0, stroke=1)

        # Left: bold
        c.setFillColorRGB(*text_dark)
        font_left = _get_font_name(bold=True)
        font_right = _get_font_name(bold=False)
        font_size = 10

        c.setFont(font_left, font_size)
        fobj = getFont(font_left)
        ascent = (fobj.face.ascent / 1000.0) * font_size

        if stringWidth(left_text, font_left, font_size) > half_w:
            while left_text and stringWidth(left_text + "…", font_left, font_size) > half_w:
                left_text = left_text[:-1]
            left_text = (left_text + "…") if left_text else ""
        c.drawString(box_x + pad_x, box_y + (box_h / 2.0) - (ascent / 2.0), left_text)

        if right_text:
            c.setFont(font_right, font_size)
            fobj2 = getFont(font_right)
            ascent2 = (fobj2.face.ascent / 1000.0) * font_size
            if stringWidth(right_text, font_right, font_size) > half_w:
                while right_text and stringWidth(right_text + "…", font_right, font_size) > half_w:
                    right_text = right_text[:-1]
                right_text = (right_text + "…") if right_text else ""
            c.drawRightString(box_x + box_w - pad_x, box_y + (box_h / 2.0) - (ascent2 / 2.0), right_text)
    finally:
        c.restoreState()

    # Slightly increased gap between header and questions
    return box_y - 8.0


def _draw_header(c: canvas.Canvas, page_w: float, page_h: float, opts: ExportOptions, page_num: int = 1) -> float:
    """
    Header dispatcher.
    - page_index == 0: first page header (cover)
    - page_index > 0: other pages header
    """
    page_index = max(0, int(page_num) - 1)
    if page_index == 0:
        return draw_first_page_header(c, page_w, page_h, opts)
    return draw_other_pages_header(c, page_w, page_h, opts, page_index)


def _apply_page_decorations(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
    y_start: float,
) -> None:
    """Optional watermark and other page-level decorations."""
    # Filigran buradan kaldırıldı - her sayfanın SONUNDA çizilecek (sorular, bölüm başlıkları, footer'dan sonra)
    # Böylece filigran her şeyin üstünde görünecek
    # Center line is handled by the column renderer
    return



def build_export_options(base: ExportOptions, **overrides) -> ExportOptions:
    """Robust builder: filters unknown keys so UI mismatches won't crash."""
    allowed = {f.name for f in fields(ExportOptions)}
    clean = {k: v for k, v in overrides.items() if k in allowed}
    return replace(base, **clean)


def compute_question_dimensions(
    img_w_px: float,
    img_h_px: float,
    zoom: float,
    display_scale: float = 1.0,
    text_scale: float = 10.0 / 12.0,
    col_w_pt: float = None,
    number_width_pt: float = None,
    number_gap_pt: float = 4.0,
    right_padding_pt: float = 4.0,
) -> Tuple[float, float, float]:
    """
    Soru boyutlarını hesapla (PDF export ve preview için ortak).
    
    Returns:
        (draw_w_pt, draw_h_pt, box_h_pt): Görsel genişliği, yüksekliği ve numara yüksekliği (pt)
    """
    # px -> pt conversion
    img_w_pt = img_w_px / float(zoom)
    img_h_pt = img_h_px / float(zoom)
    
    # display_scale uygula
    img_w_pt *= display_scale
    img_h_pt *= display_scale
    
    # text_scale uygula (10/12 = 0.833)
    draw_w_pt = img_w_pt * text_scale
    draw_h_pt = img_h_pt * text_scale
    
    # Numara yüksekliği (gerçek font yüksekliği ~10pt)
    box_h_pt = 10.0
    
    # Eğer sütun genişliği verilmişse, görseli sığdır
    if col_w_pt is not None and number_width_pt is not None:
        available_width = col_w_pt - number_width_pt - number_gap_pt - right_padding_pt
        if draw_w_pt > available_width:
            scale = available_width / draw_w_pt
            draw_w_pt = available_width
            draw_h_pt = draw_h_pt * scale
    
    return draw_w_pt, draw_h_pt, box_h_pt


def compute_layout(
    question_dimensions: List[Tuple[int, float, float, Optional[float], Optional[float]]],
    # (question_index, img_w_px, img_h_px, custom_gap_after_pt, display_scale)
    opts: ExportOptions,
    zoom: float = 1.0,
    render_dpi: float = 72.0,
    selections: Optional[List] = None,  # Selections listesi - soru numaralarını almak için
) -> LayoutResult:
    """
    Ortak layout hesaplama fonksiyonu (PDF export ve preview için).
    
    Args:
        question_dimensions: [(question_index, img_w_px, img_h_px, custom_gap_after_pt), ...]
        opts: ExportOptions
        zoom: Render zoom (render_dpi / 72.0)
        render_dpi: Render DPI (default 72.0)
    
    Returns:
        LayoutResult: Layout hesaplama sonucu
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth, getFont
    
    page_w_pt, page_h_pt = opts.page_size_pt()
    ml_pt, mr_pt, mt_pt, mb_pt = opts.margins_pt()
    col_gap_pt = opts.column_gap_pt()
    default_gap_after_q = opts.question_gap_pt()
    cols = max(1, min(6, int(opts.columns or 1)))
    text_scale = 10.0 / 12.0
    
    # Footer sınırları
    footer_y_top_pt = mb_pt + 35.0
    min_gap_above_footer_pt = mm_to_pt(2.0)
    effective_bottom_pt = footer_y_top_pt + min_gap_above_footer_pt
    
    # Sütun genişliği
    content_w_pt = page_w_pt - ml_pt - mr_pt
    if cols > 1:
        total_gap_width = (cols - 1) * col_gap_pt
        col_w_pt = (content_w_pt - total_gap_width) / cols
    else:
        col_w_pt = content_w_pt
    
    # Header yüksekliği hesaplama
    def calculate_y_start(page_num: int) -> float:
        if page_num == 0:
            return page_h_pt - mt_pt - 84.0
        else:
            header_bottom_gap_pt = opts.header_bottom_gap_pt()
            return page_h_pt - mt_pt - 40.0 - header_bottom_gap_pt
    
    # Sütun X pozisyonları
    def get_column_x(col_index: int) -> float:
        return ml_pt + col_index * (col_w_pt + col_gap_pt)
    
    # Layout hesaplama
    question_layouts: List[QuestionLayoutInfo] = []
    pages: List[List[int]] = []
    current_page_indices: List[int] = []
    
    page_num = 0
    col_idx = 0
    y = calculate_y_start(0)
    prev_bottom_by_col: Dict[int, float] = {}
    
    def new_page():
        nonlocal page_num, col_idx, y, prev_bottom_by_col
        if current_page_indices:
            pages.append(current_page_indices[:])
        current_page_indices.clear()
        page_num += 1
        col_idx = 0
        y = calculate_y_start(page_num)
        prev_bottom_by_col.clear()
    
    def next_column():
        nonlocal col_idx, y, prev_bottom_by_col, page_num
        col_idx += 1
        if col_idx >= cols:
            new_page()
        else:
            if col_idx in prev_bottom_by_col:
                y = prev_bottom_by_col[col_idx]
            else:
                y = calculate_y_start(page_num)
    
    # Font metrikleri (numara genişliği için)
    _ensure_roboto_font()
    font_name_num = _get_font_name(bold=True)
    font_size_num = 10.0
    font_obj_num = getFont(font_name_num)
    font_ascent_num = (font_obj_num.face.ascent / 1000.0) * font_size_num
    font_descent_num = abs(font_obj_num.face.descent / 1000.0) * font_size_num
    text_height = font_ascent_num + font_descent_num
    box_h_pt = text_height
    
    # Her soru için layout hesapla
    for q_idx, dim_tuple in enumerate(question_dimensions):
        # Destructure: (question_index, img_w_px, img_h_px, custom_gap_after_pt, display_scale)
        if len(dim_tuple) == 4:
            question_index, img_w_px, img_h_px, custom_gap_after_pt = dim_tuple
            display_scale = 1.0
        else:
            question_index, img_w_px, img_h_px, custom_gap_after_pt, display_scale = dim_tuple
        
        # Soru numarasını al: selections varsa sel.number kullan, yoksa q_idx + 1
        if selections and 0 <= question_index < len(selections):
            number = int(getattr(selections[question_index], "number", q_idx + 1) or (q_idx + 1))
        else:
            number = q_idx + 1  # Fallback: Soru numarası 1'den başlar
        
        # Soru boyutlarını hesapla
        number_text = f"{display_number}."
        number_width_pt = stringWidth(number_text, font_name_num, font_size_num)
        
        draw_w_pt, draw_h_pt, _ = compute_question_dimensions(
            img_w_px, img_h_px, zoom, display_scale, text_scale,
            col_w_pt, number_width_pt
        )
        
        # Boşluk hesaplama
        gap_after_q = clamp_gap_pt(custom_gap_after_pt, default_gap_after_q)
        
        # Soru yüksekliği
        question_height_pt = max(box_h_pt, draw_h_pt)
        required_space_pt = question_height_pt + gap_after_q
        if opts.spaced and opts.draw_separators:
            required_space_pt += 14.0
        
        # Mevcut sütunda bir önceki soru varsa y pozisyonunu onun altından başlat
        if col_idx in prev_bottom_by_col:
            y = prev_bottom_by_col[col_idx]
        
        # Sığma kontrolü
        while (y - required_space_pt) < effective_bottom_pt:
            next_column()
            if col_idx in prev_bottom_by_col:
                y = prev_bottom_by_col[col_idx]
        
        # Pozisyonları hesapla
        y_top_pt = y
        x_pt = get_column_x(col_idx)
        
        # Y alt pozisyonu
        y_bottom_pt = y_top_pt - question_height_pt - gap_after_q
        if opts.spaced and opts.draw_separators:
            y_bottom_pt -= 14.0
        
        # Alt sınır kontrolü
        if y_bottom_pt < effective_bottom_pt:
            y_bottom_pt = effective_bottom_pt
            y_top_pt = y_bottom_pt + question_height_pt + gap_after_q
            if opts.spaced and opts.draw_separators:
                y_top_pt += 14.0
        
        # Layout bilgisini kaydet
        layout_info = QuestionLayoutInfo(
            question_index=question_index,
            page_num=page_num,
            col_idx=col_idx,
            x_pt=x_pt,
            y_top_pt=y_top_pt,
            y_bottom_pt=y_bottom_pt,
            draw_w_pt=draw_w_pt,
            draw_h_pt=draw_h_pt,
            box_h_pt=box_h_pt,
            gap_after_pt=gap_after_q,
            number=number,
        )
        question_layouts.append(layout_info)
        current_page_indices.append(question_index)
        
        # Bir sonraki soru için y pozisyonunu güncelle
        y = y_bottom_pt
        prev_bottom_by_col[col_idx] = y_bottom_pt
    
    # Son sayfayı ekle
    if current_page_indices:
        pages.append(current_page_indices)
    
    return LayoutResult(question_layouts=question_layouts, pages=pages)


def _draw_center_line_text(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
    x_positions: Optional[List[float]] = None,
) -> None:
    """
    Dikey yazıyı SAYFANIN TAM ORTASINDAKİ DİKEY ÇİZGİNİN ÜSTÜNE bindirir.
    - Çizgi arkada kalır
    - Yazı önde görünür ve çizgiyi KAPATIR (Word gibi)
    """
    if not (opts.center_line_enabled and (opts.center_line_text or "").strip()):
        return

    from reportlab.pdfbase.pdfmetrics import getFont, stringWidth

    if not x_positions:
        x_positions = [page_w / 2.0]
    page_y_center = page_h / 2.0

    txt = opts.center_line_text.strip()

    color = (opts.center_line_color or "#000000").lstrip("#")
    if len(color) == 6:
        r = int(color[0:2], 16) / 255.0
        g = int(color[2:4], 16) / 255.0
        b = int(color[4:6], 16) / 255.0
    else:
        r, g, b = 0, 0, 0

    _ensure_roboto_font()
    font_name = _get_font_name(bold=opts.center_line_bold)
    font_size = 9

    # Font yüksekliği (pt) -> dikey yazıda çizgi ile "üst üste" binmesi için X düzeltmesi gerekir
    font_obj = getFont(font_name)
    # face.ascent/descent 1000-em biriminde olur (ReportLab)
    ascent = getattr(getattr(font_obj, "face", None), "ascent", 700)
    descent = getattr(getattr(font_obj, "face", None), "descent", -200)
    font_h = ((ascent - descent) / 1000.0) * font_size

    # Yazı uzunluğu (rotate sonrası x ekseninde kalacak)
    txt_w = stringWidth(txt, font_name, font_size)

    direction = (opts.center_line_text_direction or "up").lower().strip()
    rotation = 90 if direction == "up" else -90

    for x_line_center in x_positions:
        c.saveState()
        try:
            c.setFont(font_name, font_size)
            # ✅ Kritik: X'e font yüksekliğinin çeyreğini ekleyerek görsel merkez çizgiye oturur
            c.translate(x_line_center + (font_h / 4.0), page_y_center)
            c.rotate(rotation)

            # ✅ Yazı çizgiyi kapatsın diye beyaz arkaplan şeridi (Word "metin kutusu" gibi)
            pad = 2.0
            c.setFillColorRGB(1, 1, 1)
            c.rect(-txt_w / 2.0 - pad, -font_h / 2.0 - pad, txt_w + 2 * pad, font_h + 2 * pad, fill=1, stroke=0)

            # Yazı rengi
            c.setFillColorRGB(r, g, b)
            c.drawCentredString(0, 0, txt)
        finally:
            c.restoreState()


def export_test_pdf(
    selections: List[object],
    out_path: Path,
    opts: ExportOptions,
    pdf_docs: Optional[Dict[str, fitz.Document]] = None,
) -> None:
    """
    selections: Selection-like objects (pdf_key, page_index, norm, number, answer)
    pdf_docs: mapping (pdf_key -> open fitz.Document). REQUIRED.
    """
    if pdf_docs is None:
        raise RuntimeError("pdf_docs verilmedi. Export için açık PDF dokümanları gerekli.")

    # Font yükleme işlemini başta yap
    _ensure_roboto_font()

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    page_w, page_h = opts.page_size_pt()
    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))
    # Filigranı başta çizme - her sayfanın sonunda çizilecek (en üstte görünmesi için)

    ml, mr, mt, mb = opts.margins_pt()
    col_gap = opts.column_gap_pt()
    default_gap_after_q = opts.question_gap_pt()  # Varsayılan boşluk (her soru için custom yoksa kullanılacak)

    # columns clamp
    cols = int(opts.columns or 1)
    if cols < 1:
        cols = 1
    if cols > 6:
        cols = 6

    content_w = page_w - ml - mr
    # YENİ MANTIK: Soldan sağa eşit sütunlar (preview ile aynı)
    if cols > 1:
        # Sütunlar arası boşluklar: (cols - 1) adet
        total_gap_width = (cols - 1) * col_gap
        col_w = (content_w - total_gap_width) / cols
    else:
        col_w = content_w
    
    # Sütun ayırıcı çizgiler (cols-1 adet, gap ortasında)
    x_lines: List[float] = []
    if cols > 1:
        for i in range(cols - 1):
            x_lines.append(ml + (i + 1) * col_w + i * col_gap + (col_gap / 2.0))

    # Sayfa numarası takibi
    page_num = 1
    
    # Header
    y_start = _draw_header(c, page_w, page_h, opts, page_num)
    _apply_page_decorations(c, page_w, page_h, opts, y_start)

    # Normalization params (target 11pt, clamp 0.8..1.35)
    normalize_enabled = bool(getattr(opts, "normalize_question_font", True))
    target_pt_global = float(getattr(opts, "target_question_font_pt", 11.0) or 11.0)
    min_s_global = float(getattr(opts, "normalize_min_scale", 0.70) or 0.70)
    max_s_global = float(getattr(opts, "normalize_max_scale", 1.45) or 1.45)
    fallback_observed_global = float(getattr(opts, "normalize_fallback_observed_pt", 12.0) or 12.0)
    base_zoom_global = float(opts.zoom)

    # IMPORTANT: From this point on, normalization must be independent per-question.
    # User can resize questions individually and it must not affect others.
    # So we disable any global coupling (global_k, median width bump, etc.).
    normalize_link_questions = bool(getattr(opts, "normalize_link_questions", False))

    # Cache observed font (pt proxy) + clip sizes for normalization/global fit
    # key: (pdf_key, page_index, norm_xywh) -> (observed_pt, has_pdf_text, clip_w_pt, clip_h_pt)
    _norm_cache: Dict[Tuple[str, int, Tuple[float, float, float, float]], Tuple[float, bool, float, float]] = {}
    # Cache page-level selectable text detection + page median
    # key: (pdf_key, page_index) -> (page_has_text, page_median_pt)
    _page_text_cache: Dict[Tuple[str, int], Tuple[bool, float]] = {}

    # -----------------------------
    # Global factor to keep widths consistent across questions
    # Some questions get downscaled later to fit column width (draw_w > available_width).
    # That creates visible font-size differences. We compute a global k<=1 so that after
    # normalization, ALL questions fit in the column width without per-question extra downscale.
    # -----------------------------
    global_k = 1.0
    target_width_after_pt = 0.0  # typical (median) width after normalization
    # Debug/reference: highlight the question that drives the strongest height scaling.
    # We define "reference" as the question with the largest unclamped height-based scale (s_i).
    ref_question_num: Optional[int] = None
    ref_question_score: float = -1.0
    if normalize_enabled and normalize_link_questions:
        try:
            from reportlab.pdfbase.pdfmetrics import stringWidth

            # Worst-case number width based on max question number
            max_num = 1
            for sel in selections:
                try:
                    n = int(getattr(sel, "number", 0) or 0)
                    if n > max_num:
                        max_num = n
                except Exception:
                    pass

            font_name_num = _get_font_name(bold=True)
            font_size_num = 10.0
            max_number_text = f"{max_num}."
            number_width_max = stringWidth(max_number_text, font_name_num, font_size_num)

            number_gap = 4.0
            right_padding = 4.0
            available_width_max = col_w - number_width_max - number_gap - right_padding
            if available_width_max <= 1:
                available_width_max = col_w * 0.85

            ratios: List[float] = []
            width_after_list: List[float] = []
            for sel in selections:
                pdf_key_i = getattr(sel, "pdf_key", None)
                page_index_i = int(getattr(sel, "page_index", -1))
                norm_i = getattr(sel, "norm", None)
                if not pdf_key_i or norm_i is None:
                    continue
                doc_i = pdf_docs.get(str(pdf_key_i))
                if doc_i is None:
                    continue

                display_scale_i = float(getattr(sel, "display_scale", 1.0) or 1.0)
                cache_key = (str(pdf_key_i), page_index_i, tuple(norm_i))

                if cache_key in _norm_cache:
                    observed_pt_i, _has_text_i, clip_w_pt_i, _clip_h_pt_i = _norm_cache[cache_key]
                else:
                    observed_pt_i = float(fallback_observed_global)
                    has_text_i = False
                    clip_w_pt_i, clip_h_pt_i = 0.0, 0.0
                    try:
                        # 1) Page-level selectable-text detection
                        page_key_i = (str(pdf_key_i), int(page_index_i))
                        if page_key_i in _page_text_cache:
                            page_has_text_i, page_median_i = _page_text_cache[page_key_i]
                        else:
                            page_has_text_i, page_median_i = False, float(fallback_observed_global)
                            try:
                                page_obj_i = doc_i.load_page(page_index_i)
                                dct_page_i = page_obj_i.get_text("dict")
                                page_median_i, ok_page_i = _estimate_font_pt_from_text_dict(
                                    dct_page_i, fallback_pt=fallback_observed_global, min_spans=20
                                )
                                page_has_text_i = bool(ok_page_i)
                            except Exception:
                                page_has_text_i, page_median_i = False, float(fallback_observed_global)
                            _page_text_cache[page_key_i] = (bool(page_has_text_i), float(page_median_i))

                        # 2) If page is selectable-text, prefer clip median; fallback to page median
                        if page_has_text_i:
                            observed_pt_pdf_i, ok_clip_i = _estimate_font_pt_in_clip(
                                doc_i, page_index_i, norm_i, fallback_pt=float(page_median_i)
                            )
                            observed_pt_i = float(observed_pt_pdf_i) if ok_clip_i else float(page_median_i)
                            has_text_i = True

                        # 3) Always render once to get a reliable clip width (and raster proxy if needed)
                        rendered_base_i = _render_selection_from_embedded(sel_i) or _render_selection_png_bytes(doc_i, page_index_i, norm_i, base_zoom_global)
                        if rendered_base_i:
                            png_base_i, wpx_i, hpx_i = rendered_base_i
                            clip_w_pt_i = float(wpx_i) / float(base_zoom_global)
                            clip_h_pt_i = float(hpx_i) / float(base_zoom_global)
                            if not has_text_i:
                                observed_pt_i = float(
                                    _estimate_font_pt_from_raster_png(
                                        png_base_i, zoom=base_zoom_global, fallback_pt=fallback_observed_global
                                    )
                                )
                        else:
                            # Fallback: best-effort from page geometry
                            page_i = doc_i.load_page(page_index_i)
                            clip_i = _safe_clip_from_norm(page_i, norm_i)
                            if clip_i is not None:
                                clip_w_pt_i, clip_h_pt_i = float(clip_i.width), float(clip_i.height)
                    except Exception:
                        pass

                    _norm_cache[cache_key] = (float(observed_pt_i), bool(has_text_i), float(clip_w_pt_i), float(clip_h_pt_i))

                if clip_w_pt_i <= 1:
                    continue

                s_i = (target_pt_global / observed_pt_i) if (observed_pt_i and observed_pt_i > 0) else 1.0
                s_i = max(min_s_global, min(max_s_global, float(s_i)))
                try:
                    num_i = int(getattr(sel, "number", 0) or 0)
                    if num_i > 0 and float(s_i) > float(ref_question_score):
                        ref_question_score = float(s_i)
                        ref_question_num = int(num_i)
                except Exception:
                    pass

                max_scale_w_i = float(available_width_max) / float(clip_w_pt_i * max(display_scale_i, 1e-6))
                if max_scale_w_i <= 0:
                    continue
                ratios.append(max_scale_w_i / s_i)

                # Track typical post-normalization widths (clipped to column availability)
                w_after = float(clip_w_pt_i) * float(display_scale_i) * float(s_i)
                w_after = min(float(available_width_max), max(0.0, w_after))
                if w_after > 1.0:
                    width_after_list.append(w_after)

            if ratios:
                global_k = max(0.1, min(1.0, min(ratios)))
            if width_after_list:
                width_after_list.sort()
                mid = len(width_after_list) // 2
                if len(width_after_list) % 2 == 1:
                    target_width_after_pt = float(width_after_list[mid])
                else:
                    target_width_after_pt = float((width_after_list[mid - 1] + width_after_list[mid]) / 2.0)
        except Exception:
            global_k = 1.0
            target_width_after_pt = 0.0

    # Çizgi rengi: tema rengi (tüm çizgiler için)
    line_r, line_g, line_b = _hex_to_rgb01(getattr(opts, "theme_color", getattr(opts, "line_color", "#000000")))
    
    # ÖNCE ÇİZGİYİ ÇİZ (ARKADA KALACAK) - Footer bölgesinde çizilmemeli
    if cols > 1 and x_lines:
        c.saveState()
        try:
            c.setLineWidth(0.7)
            c.setStrokeColorRGB(line_r, line_g, line_b)
            footer_y_top = mb + 35.0  # Footer'ın üst çizgisi
            # Çizgi üstteki kutuya / açıklama kutusuna kadar uzasın:
            # y_start soruların başladığı yer; +5pt header/desc alt kenarına yaklaştırır.
            y_line_end = y_start + 5.0
            for x in x_lines:
                c.line(x, footer_y_top, x, y_line_end)
        finally:
            c.restoreState()

    # SONRA YAZIYI ÇİZ (ÖNDE) - çizgiyi kapatır
    _draw_center_line_text(c, page_w, page_h, opts, x_positions=x_lines)

    # YENİ MANTIK: Soldan sağa sütunlar (preview ile aynı)
    # Sütun X pozisyonlarını hesapla (soldan sağa)
    def get_column_x(col_index: int) -> float:
        """Sütun indeksine göre X konumunu hesapla (soldan sağa)"""
        return ml + col_index * (col_w + col_gap)
    
    col_idx = 0  # En soldaki sütundan başla (0)
    x_col = get_column_x(0)
    y = y_start
    
    # Her sütun için son sorunun alt kenarını takip et
    prev_bottom_by_col = {}  # {col_idx: y_bottom} - Her sütun için son sorunun alt kenarı

    answer_key: List[Tuple[int, str]] = []
    # Her sayfa için cevap anahtarı takibi: {page_num: [(question_num, answer), ...]}
    page_answers: Dict[int, List[Tuple[int, str]]] = {}
    current_page_answers: List[Tuple[int, str]] = []  # Mevcut sayfadaki cevaplar (sadece çizilen sorular için)
    
    # Varsayılan boşluk (her soru için custom boşluk yoksa kullanılacak)
    default_gap_after_q = opts.question_gap_pt()

    def draw_page_footer(canvas_obj, p_num: int, answers_list: List[Tuple[int, str]], *, show_answers: bool):
        """Sayfa altına cevap anahtarlarını ve sayfa numarasını çiz"""
        # Çizgi rengi: tema rengi
        line_r, line_g, line_b = _hex_to_rgb01(getattr(opts, "theme_color", getattr(opts, "line_color", "#000000")))
        
        # Alt margin'dan başla (iki çizgi arası mesafe küçültüldü)
        footer_y_bottom = mb + 15.0  # Alt çizgi pozisyonu
        footer_y_top = mb + 35.0  # Üst çizgi pozisyonu
        footer_y_center = (footer_y_bottom + footer_y_top) / 2.0  # İki çizgi arası orta nokta
        
        # İki çizgi arası cevap anahtarları
        # Üst çizgi (tüm sayfa genişliğinde, sütun çizgisinden bağımsız)
        canvas_obj.saveState()
        canvas_obj.setLineWidth(0.4)
        canvas_obj.setStrokeColorRGB(line_r, line_g, line_b)
        canvas_obj.line(ml, footer_y_top, page_w - mr, footer_y_top)
        canvas_obj.restoreState()
        
        # Cevap anahtarları (footer) sadece per_page modunda çizilir
        if show_answers:
            canvas_obj.saveState()
            try:
                canvas_obj.setFont(_get_font_name(bold=False), 9)
                canvas_obj.setFillColorRGB(line_r, line_g, line_b)

                # Cevap anahtarlarını sırala
                sorted_answers = sorted(list(answers_list or []), key=lambda t: t[0])
                answer_texts = []
                for num, ans in sorted_answers:
                    if ans and ans.strip():
                        answer_texts.append(f"{num}. {ans}")
                    else:
                        answer_texts.append(f"{num}. ?")

                answer_text = "  ".join(answer_texts) if answer_texts else ""
                from reportlab.pdfbase.pdfmetrics import getFont

                font_obj = getFont(_get_font_name(bold=False))
                font_ascent = (font_obj.face.ascent / 1000.0) * 9
                answer_x = ml
                answer_y = footer_y_center - font_ascent / 2.0
                if answer_text:
                    canvas_obj.drawString(answer_x, answer_y, answer_text)
            finally:
                canvas_obj.restoreState()
        
        # Alt çizgi (tüm sayfa genişliğinde, sütun çizgisinden bağımsız)
        canvas_obj.saveState()
        canvas_obj.setLineWidth(0.4)
        canvas_obj.setStrokeColorRGB(line_r, line_g, line_b)
        canvas_obj.line(ml, footer_y_bottom, page_w - mr, footer_y_bottom)
        canvas_obj.restoreState()
        
        # Sayfa numarası (yuvarlak içinde, iki çizgi arasında, TAM ORTADA)
        # Çizgi aralığı: footer_y_top - footer_y_bottom = 35.0 - 15.0 = 20.0 pt
        # Daire yarıçapı çizgi aralığına sığmalı (20.0 pt / 2 = 10.0 pt maksimum)
        footer_space = footer_y_top - footer_y_bottom  # 20.0 pt
        max_circle_radius = footer_space / 2.0 - 2.0  # 2.0 pt güvenlik payı
        circle_radius = min(12.0, max_circle_radius)  # Maksimum 12.0 pt ama çizgi aralığına sığmalı
        
        page_num_text = str(p_num)
        canvas_obj.saveState()
        canvas_obj.setFont(_get_font_name(bold=True), 10)
        from reportlab.pdfbase.pdfmetrics import stringWidth, getFont
        page_num_width = stringWidth(page_num_text, _get_font_name(bold=True), 10)
        # Yuvarlak sayfanın ortasında olacak (x ekseninde)
        circle_x = (ml + page_w - mr) / 2.0  # Tam orta
        circle_y = footer_y_center  # İki çizgi arasında ortala
        
        # Yuvarlak çiz (turuncu çizgi rengi ile)
        canvas_obj.setLineWidth(0.8)
        canvas_obj.setStrokeColorRGB(line_r, line_g, line_b)
        canvas_obj.setFillColorRGB(1, 1, 1)  # Beyaz iç
        canvas_obj.circle(circle_x, circle_y, circle_radius, fill=1, stroke=1)
        
        # Sayfa numarası yazısı
        canvas_obj.setFillColorRGB(0, 0, 0)
        font_obj = getFont(_get_font_name(bold=True))
        font_ascent = (font_obj.face.ascent / 1000.0) * 10
        text_x = circle_x - page_num_width / 2.0
        text_y = circle_y - font_ascent / 2.0
        canvas_obj.drawString(text_x, text_y, page_num_text)
        canvas_obj.restoreState()
    
    def _draw_answer_key_table(
        canvas_obj,
        *,
        x: float,
        y_top: float,
        w: float,
        max_h: float,
        items: List[Tuple[int, str]],
        entries_per_row: int,
        title_text: str = "Cevap Anahtarı",
        title_font_pt: float = 11.0,
    ) -> Tuple[float, List[Tuple[int, str]]]:
        """
        Draw a compact answer key table.
        Returns (used_height, remaining_items).
        Coordinates: y_top is top edge in pt.
        """
        # theme color
        line_r, line_g, line_b = _hex_to_rgb01(getattr(opts, "theme_color", getattr(opts, "line_color", "#000000")))
        stroke = (line_r, line_g, line_b)
        bg = (1, 1, 1)
        bg_header = (min(1.0, line_r * 0.25 + 0.75), min(1.0, line_g * 0.25 + 0.75), min(1.0, line_b * 0.25 + 0.75))

        entries_per_row = max(1, int(entries_per_row or 1))
        cell_h = 14.0
        header_h = 18.0
        pad = 6.0

        # how many rows fit?
        available = max(0.0, max_h - header_h - pad)
        max_rows = max(1, int(available // cell_h)) if available > cell_h else 0
        if max_rows <= 0 or not items:
            return 0.0, items

        capacity = max_rows * entries_per_row
        chunk = items[:capacity]
        remaining = items[capacity:]

        rows = (len(chunk) + entries_per_row - 1) // entries_per_row
        table_h = header_h + rows * cell_h + pad
        table_h = min(table_h, max_h)
        y_bottom = y_top - table_h

        canvas_obj.saveState()
        try:
            canvas_obj.setLineWidth(0.8)
            canvas_obj.setStrokeColorRGB(*stroke)
            canvas_obj.setFillColorRGB(*bg)
            canvas_obj.roundRect(x, y_bottom, w, table_h, 8.0, fill=1, stroke=1)

            # header strip
            canvas_obj.setFillColorRGB(*bg_header)
            canvas_obj.roundRect(x, y_top - header_h, w, header_h, 8.0, fill=1, stroke=0)
            canvas_obj.setFillColorRGB(0, 0, 0)
            tt = (title_text or "Cevap Anahtarı").strip() or "Cevap Anahtarı"
            tf = float(title_font_pt or 11.0)
            tf = max(9.0, min(16.0, tf))
            canvas_obj.setFont(_get_font_name(bold=True), tf)
            canvas_obj.drawString(x + 10.0, y_top - 13.0, tt)

            # grid text
            canvas_obj.setFont(_get_font_name(bold=False), 9)
            col_w = w / entries_per_row
            y_cursor = y_top - header_h - 4.0
            idx = 0
            for r_i in range(rows):
                y_row_top = y_cursor - r_i * cell_h
                for c_i in range(entries_per_row):
                    if idx >= len(chunk):
                        break
                    num, ans = chunk[idx]
                    ans = (ans or "").strip().upper() or "?"
                    cell_x = x + c_i * col_w
                    # light separators
                    canvas_obj.setStrokeColorRGB(*stroke)
                    canvas_obj.setLineWidth(0.3)
                    canvas_obj.line(cell_x, y_row_top - cell_h, cell_x + col_w, y_row_top - cell_h)

                    text = f"{num}. {ans}"
                    canvas_obj.setFillColorRGB(0, 0, 0)
                    canvas_obj.drawString(cell_x + 6.0, y_row_top - 10.0, text)
                    idx += 1
            # vertical separators
            canvas_obj.setStrokeColorRGB(*stroke)
            canvas_obj.setLineWidth(0.3)
            for c_i in range(1, entries_per_row):
                xx = x + c_i * col_w
                canvas_obj.line(xx, y_bottom, xx, y_top - header_h)
        finally:
            canvas_obj.restoreState()

        return table_h + 5.0, remaining  # + small gap below

    def new_page():
        nonlocal y, col_idx, x_col, y_start, page_num, current_page_answers, prev_bottom_by_col
        # Mevcut sayfanın cevaplarını kaydet ve footer'ını çiz (yeni sayfaya geçmeden önce)
        if current_page_answers:
            page_answers[page_num] = list(current_page_answers)
        show_footer_answers = bool(getattr(opts, "answer_key_enabled", False)) and (getattr(opts, "answer_key_mode", "per_page") == "per_page")
        draw_page_footer(c, page_num, list(current_page_answers), show_answers=show_footer_answers)
        
        # ÖNEMLİ: Filigranı EN SON çiz - tüm içerikten (sorular, bölüm başlıkları, footer, çizgi, yazı) sonra
        # Böylece filigran her şeyin üstünde görünecek
        _draw_watermark_and_centerline(c, page_w, page_h, opts)
        
        current_page_answers.clear()  # Yeni sayfa için sıfırla
        
        page_num += 1
        c.showPage()
        y_start = _draw_header(c, page_w, page_h, opts, page_num)
        _apply_page_decorations(c, page_w, page_h, opts, y_start)

        # Çizgi (her sayfada) - Footer bölgesinde çizilmemeli
        if cols > 1 and x_lines:
            c.saveState()
            try:
                c.setLineWidth(0.7)
                c.setStrokeColorRGB(line_r, line_g, line_b)
                # Footer bölgesini atla (footer_y_top'a kadar çiz)
                footer_y_top = mb + 35.0  # Footer'ın üst çizgisi
                # Çizgi üstteki kutuya / açıklama kutusuna kadar uzasın
                y_line_end = y_start + 5.0
                for x in x_lines:
                    c.line(x, footer_y_top, x, y_line_end)
            finally:
                c.restoreState()

        # Yazı (her sayfada)
        _draw_center_line_text(c, page_w, page_h, opts, x_positions=x_lines)

        # YENİ MANTIK: Yeni sayfada 1. sütundan başla
        col_idx = 0
        x_col = get_column_x(0)
        y = y_start
        prev_bottom_by_col.clear()  # Yeni sayfa başı, tüm sütunlar için alt kenar bilgisi yok

    def next_column():
        nonlocal col_idx, x_col, y, prev_bottom_by_col
        col_idx += 1
        if col_idx >= cols:
            # Tüm sütunlar doldu, yeni sayfa
            new_page()
        else:
            # Bir sonraki sütuna geç
            x_col = get_column_x(col_idx)
            # Eğer bu sütunda bir önceki soru varsa onun altından başla, yoksa yukarıdan başla
            if col_idx in prev_bottom_by_col:
                y = prev_bottom_by_col[col_idx]  # Bir önceki sorunun altından başla
            else:
                y = y_start  # Sütun başı, yukarıdan başla

    q_fallback = 0
    # Display numbering in the PDF (can be reset by section headers).
    display_counter = 1
    # Answer key grouping by sections (used for separate_page / end_of_test)
    answer_key_groups: List[Tuple[str, List[Tuple[int, str]]]] = []
    _ak_group_title: str = "Genel"
    _ak_group_entries: List[Tuple[int, str]] = []
    _ak_active_end: Optional[int] = None
    for sel in selections:
        q_fallback += 1
        internal_id = int(getattr(sel, "number", q_fallback) or q_fallback)  # stable unique id
        sec_title = (getattr(sel, "section_title", "") or "").strip()
        sec_enabled = bool(getattr(sel, "section_enabled", False)) and bool(sec_title)
        sec_restart = bool(getattr(sel, "section_restart_numbering", False))
        try:
            sec_end = getattr(sel, "section_end_number", None)
            sec_end = int(sec_end) if sec_end is not None else int(internal_id)
        except Exception:
            sec_end = int(internal_id)

        # If section requests numbering restart, apply before numbering this question.
        if sec_enabled and sec_restart:
            display_counter = 1

        display_number = int(display_counter)
        display_counter += 1
        ans = (getattr(sel, "answer", "") or "").strip().upper()
        # Cevap anahtarına ekle (PDF'de görünen numara ile)
        answer_key.append((display_number, ans))
        # Group answer keys by sections (except per-page footer, handled separately)
        try:
            if sec_enabled:
                # flush previous group
                if _ak_group_entries:
                    answer_key_groups.append((_ak_group_title, list(_ak_group_entries)))
                _ak_group_title = sec_title
                _ak_group_entries = []
                _ak_active_end = int(sec_end)
            _ak_group_entries.append((int(display_number), str(ans)))
            if _ak_active_end is not None and int(internal_id) >= int(_ak_active_end):
                # section ends here; flush and go back to "Genel"
                answer_key_groups.append((_ak_group_title, list(_ak_group_entries)))
                _ak_group_title = "Genel"
                _ak_group_entries = []
                _ak_active_end = None
        except Exception:
            pass
        # NOT: current_page_answers'a ekleme yapılmıyor - sadece soru çizildiğinde ekleniyor

        pdf_key = getattr(sel, "pdf_key", None)
        page_index = int(getattr(sel, "page_index", -1))
        norm = getattr(sel, "norm", None)
        if not pdf_key or norm is None:
            continue

        # Seçim "embedded" bir taslaktan geliyorsa artık PDF dokümanına bağımlı olmamalı.
        # Bu durumda görsel sel.embedded_png içinden çizilir.
        is_embedded = str(pdf_key) == "__EMBEDDED__"
        doc = None if is_embedded else pdf_docs.get(str(pdf_key))
        if (not is_embedded) and doc is None:
            raise FileNotFoundError(f"PDF doc bulunamadı (pdf_key): {pdf_key}")

        # display_scale varsa uygula (görselin boyutunu değiştirmek için)
        display_scale = getattr(sel, 'display_scale', 1.0)
        
        # Custom boşluk varsa onu kullan, yoksa varsayılan boşluğu kullan
        custom_gap_pt = getattr(sel, 'custom_gap_after_pt', None)
        gap_after_q = custom_gap_pt if custom_gap_pt is not None else default_gap_after_q

        # -----------------------------
        # Column width constraint (apply during scaling, not after draw)
        # -----------------------------
        from reportlab.pdfbase.pdfmetrics import stringWidth, getFont
        number_text = f"{display_number}."
        font_name_num = _get_font_name(bold=True)
        font_size_num = 10.0
        number_width = float(stringWidth(number_text, font_name_num, font_size_num))
        # Numara ile görsel arası boşluk
        number_gap = 4.0
        right_padding = 4.0  # sağ taraftan güvenlik payı
        available_width = col_w - number_width - number_gap - right_padding
        if available_width <= 1:
            available_width = col_w * 0.85

        # -----------------------------
        # Per-question font normalization (target 11pt)
        # -----------------------------
        normalize = normalize_enabled
        observed_pt = fallback_observed_global
        s = 1.0

        base_zoom = base_zoom_global
        cached_base_png: Optional[bytes] = None
        has_pdf_text = False
        clip_w_pt_for_fit = 0.0

        # First try PDF text-based measurement
        if normalize:
            cache_key = (str(pdf_key), int(page_index), tuple(norm))
            if cache_key in _norm_cache:
                observed_pt, has_pdf_text, _clip_w_pt, _clip_h_pt = _norm_cache[cache_key]
                clip_w_pt_for_fit = float(_clip_w_pt or 0.0)
            else:
                # Page-level selectable-text detection (hybrid rule)
                page_key = (str(pdf_key), int(page_index))
                if page_key in _page_text_cache:
                    page_has_text, page_median = _page_text_cache[page_key]
                else:
                    page_has_text, page_median = False, float(fallback_observed_global)
                    try:
                        page_obj = doc.load_page(page_index)
                        dct_page = page_obj.get_text("dict")
                        page_median, ok_page = _estimate_font_pt_from_text_dict(
                            dct_page, fallback_pt=fallback_observed_global, min_spans=20
                        )
                        page_has_text = bool(ok_page)
                    except Exception:
                        page_has_text, page_median = False, float(fallback_observed_global)
                    _page_text_cache[page_key] = (bool(page_has_text), float(page_median))

                if page_has_text:
                    obs_clip, ok_clip = _estimate_font_pt_in_clip(
                        doc, page_index, norm, fallback_pt=float(page_median)
                    )
                    has_pdf_text = True
                    observed_pt = float(obs_clip) if ok_clip else float(page_median)
                else:
                    has_pdf_text = False
                    # Scanned/image PDF: render once at base zoom and estimate from raster
                    rendered_base = _render_selection_from_embedded(sel) or _render_selection_png_bytes(doc, page_index, norm, base_zoom)
                    if rendered_base:
                        png_base, wpx, hpx = rendered_base
                        cached_base_png = png_base
                        observed_pt = _estimate_font_pt_from_raster_png(
                            png_base, zoom=base_zoom, fallback_pt=fallback_observed_global
                        )
                        # Use raster clip width for fit (more reliable)
                        clip_w_pt_for_fit = float(wpx) / float(base_zoom)
                    else:
                        observed_pt = fallback_observed_global
                # cache clip size too (best-effort)
                try:
                    page_i = doc.load_page(page_index)
                    clip_i = _safe_clip_from_norm(page_i, norm)
                    if clip_i is None:
                        clip_w_pt_i, clip_h_pt_i = 0.0, 0.0
                    else:
                        clip_w_pt_i, clip_h_pt_i = float(clip_i.width), float(clip_i.height)
                except Exception:
                    clip_w_pt_i, clip_h_pt_i = 0.0, 0.0
                if clip_w_pt_for_fit <= 0.0:
                    clip_w_pt_for_fit = float(clip_w_pt_i or 0.0)
                _norm_cache[cache_key] = (float(observed_pt), bool(has_pdf_text), float(clip_w_pt_i), float(clip_h_pt_i))

            # Scale to target point size (default 11pt)
            if observed_pt and observed_pt > 0:
                s = float(target_pt_global) / float(observed_pt)
            s = max(min_s_global, min(max_s_global, float(s)))
            # Global coupling is optional; default OFF.
            if normalize_link_questions:
                s = float(s) * float(global_k)
                # global_k can push s below min clamp; re-clamp
                s = max(float(min_s_global), min(float(max_s_global), float(s)))

            # Enforce width limit here so we don't do a second "fit" later (which would break equalization)
            if clip_w_pt_for_fit > 1e-6 and available_width > 1e-6:
                s_max_w = float(available_width) / float(clip_w_pt_for_fit * max(float(display_scale), 1e-6))
                if s_max_w > 0:
                    s = min(float(s), float(s_max_w))

            # NOTE: Median-width "bump up small scans" is global coupling.
            # It is disabled by default so manual per-question resizing doesn't affect others.
            if normalize_link_questions and (not has_pdf_text) and target_width_after_pt > 1.0 and clip_w_pt_for_fit > 1e-6:
                current_w = float(clip_w_pt_for_fit) * float(display_scale) * float(s)
                if current_w > 1e-6 and current_w < (0.90 * float(target_width_after_pt)):
                    desired = float(target_width_after_pt)
                    bump = desired / current_w
                    s_bumped = float(s) * float(bump)
                    s_bumped = min(float(max_s_global), max(float(min_s_global), float(s_bumped)))
                    if clip_w_pt_for_fit > 1e-6 and available_width > 1e-6:
                        s_max_w2 = float(available_width) / float(clip_w_pt_for_fit * max(float(display_scale), 1e-6))
                        if s_max_w2 > 0:
                            s_bumped = min(float(s_bumped), float(s_max_w2))
                    s = float(s_bumped)

        # Render zoom: if we are scaling up, render higher resolution to avoid blur.
        render_zoom = base_zoom * (s if (normalize and s > 1.0) else 1.0)

        # Reuse base render if it matches (avoid double render for scanned PDFs when s<=1)
        if cached_base_png is not None and abs(float(render_zoom) - float(base_zoom)) < 1e-6:
            # We don't have original px dims here; re-render to get dims (cheap-ish), but keep
            # bytes reuse isn't helpful without dims. Fall back to normal path.
            rendered = _render_selection_from_embedded(sel) or _render_selection_png_bytes(doc, page_index, norm, render_zoom)
        else:
            rendered = _render_selection_from_embedded(sel) or _render_selection_png_bytes(doc, page_index, norm, render_zoom)
        if not rendered:
            continue
        png_bytes, img_w_px, img_h_px = rendered

        # px -> pt approximation: pt ~= px / zoom
        img_w_pt = img_w_px / float(render_zoom)
        img_h_pt = img_h_px / float(render_zoom)
        
        # display_scale'ı görselin boyutuna uygula
        img_w_pt *= display_scale
        img_h_pt *= display_scale

        # Apply normalization scale to physical draw size (aspect ratio preserved by using same factor)
        draw_w = img_w_pt * (s if normalize else 1.0)
        draw_h = img_h_pt * (s if normalize else 1.0)
        
        # -----------------------------
        # Number label (boxed) + image (side-by-side)
        # İSTENEN: Numara kutusunun ÜST KENARI ile görselin ÜST KENARI aynı hizaya gelsin.
        # Not: ReportLab'de drawString y=baseline, drawImage ise y=bottom-left (anchor paramı
        # bazı sürümlerde yok/ignore edilebiliyor). Bu yüzden "y_top" (satır üst kenarı)
        # üzerinden her şeyi güvenli şekilde hesaplıyoruz.
        # -----------------------------
        # Numara font ayarları
        c.setFont(font_name_num, font_size_num)

        # Numara ölçüleri (kutu yok, sadece yazı)
        font_obj_num = getFont(font_name_num)
        font_ascent_num = (font_obj_num.face.ascent / 1000.0) * font_size_num
        font_descent_num = abs(font_obj_num.face.descent / 1000.0) * font_size_num
        text_height = font_ascent_num + font_descent_num
        box_w = number_width  # Kutu yok, sadece yazı genişliği
        box_h = text_height   # Kutu yok, sadece yazı yüksekliği

        # Güvenlik: teorik olarak buraya düşmemeli (ölçek yukarıda width-limit ile sınırlandı)
        if draw_w > available_width and available_width > 1e-6:
            scale = available_width / draw_w
            draw_w = available_width
            draw_h = draw_h * scale

        # Footer yüksekliği: İki çizgi arası alan (35pt - 15pt = 20pt) + alt margin
        footer_y_top = mb + 35.0
        footer_y_bottom = mb + 15.0
        # Sorular footer'ın üst çizgisinin en az 2mm üstünde olmalı
        min_gap_above_footer_pt = mm_to_pt(2.0)  # En az 2mm
        effective_bottom = footer_y_top + min_gap_above_footer_pt
        
        # Custom boşluk varsa clamp et
        gap_after_q = clamp_gap_pt(custom_gap_pt, default_gap_after_q)

        # Bölüm başlığı yeni sayfadan başlayacaksa, header+ilk soru için sayfa değiştir
        sec_new_page = bool(getattr(sel, "section_start_new_page", False))
        if sec_enabled and sec_new_page:
            new_page()
        
        # YENİ MANTIK: ÖNCE eğer bu sütunda bir önceki soru varsa, y pozisyonunu onun altından başlat
        if col_idx in prev_bottom_by_col:
            # Bu sütunda bir önceki soru var, y pozisyonunu onun altından başlat
            y = prev_bottom_by_col[col_idx]
        
        # ŞİMDİ: Mevcut sütunda sığıyor mu kontrol et
        # Soru yüksekliği (boşluk olmadan)
        question_height = max(box_h, draw_h)
        required_space = question_height + gap_after_q
        if opts.spaced and opts.draw_separators:
            required_space += 14.0
        # Bölüm başlığı bu sorunun ÜSTÜNE basılacaksa gerekli alanı ekle
        sec_gap_after = 8.0
        sec_font_pt = 12.0
        sec_box_h = 0.0
        if sec_enabled:
            try:
                sec_font_pt = float(getattr(sel, "section_font_pt", 12.0) or 12.0)
            except Exception:
                sec_font_pt = 12.0
            sec_font_pt = max(8.0, min(24.0, float(sec_font_pt)))
            sec_box_h = float(sec_font_pt) + 14.0
            required_space += float(sec_box_h) + float(sec_gap_after)
        
        # Soru sığıyor mu? (y - required_space >= effective_bottom)
        while (y - required_space) < effective_bottom:
            # Mevcut sütuna sığmıyor, bir sonraki sütuna geç
            next_column()
            # Yeni sütunda bir önceki soru var mı kontrol et
            if col_idx in prev_bottom_by_col:
                y = prev_bottom_by_col[col_idx]  # Bir önceki sorunun altından başla

        # Bölüm başlığı (bu sorunun üstüne)
        if sec_enabled and sec_box_h > 0.0:
            try:
                fill_rgb = _hex_to_rgb01(getattr(sel, "section_fill_color", "#FFFFFF"), fallback=(1.0, 1.0, 1.0))
                text_rgb = _hex_to_rgb01(getattr(sel, "section_text_color", "#000000"), fallback=(0.0, 0.0, 0.0))
                stroke_rgb = _hex_to_rgb01(getattr(sel, "section_line_color", None) or getattr(opts, "theme_color", getattr(opts, "line_color", "#000000")),
                                           fallback=(line_r, line_g, line_b))
                box_w_sec = float(col_w)
                y_top_sec = float(y)
                y_bottom_sec = y_top_sec - float(sec_box_h)

                c.saveState()
                try:
                    c.setLineWidth(0.8)
                    c.setStrokeColorRGB(*stroke_rgb)
                    c.setFillColorRGB(*fill_rgb)
                    c.roundRect(x_col, y_bottom_sec, box_w_sec, float(sec_box_h), 8.0, fill=1, stroke=1)
                    c.setFillColorRGB(*text_rgb)
                    font_name_sec = _get_font_name(bold=True)
                    c.setFont(font_name_sec, float(sec_font_pt))
                    # Center text
                    try:
                        text_w = float(stringWidth(sec_title, font_name_sec, float(sec_font_pt)))
                        font_obj = getFont(font_name_sec)
                        ascent = float(getattr(getattr(font_obj, "face", None), "ascent", 800))
                        descent = float(getattr(getattr(font_obj, "face", None), "descent", -200))
                        ascent_pt = (ascent / 1000.0) * float(sec_font_pt)
                        descent_pt = (descent / 1000.0) * float(sec_font_pt)  # negative
                        text_h = ascent_pt - descent_pt
                        x_text = float(x_col) + max(0.0, (box_w_sec - text_w) / 2.0)
                        y_baseline = float(y_bottom_sec) + max(0.0, (float(sec_box_h) - text_h) / 2.0) - descent_pt
                        c.drawString(x_text, y_baseline, sec_title)
                    except Exception:
                        x_center = float(x_col) + float(box_w_sec) / 2.0
                        y_baseline = float(y_bottom_sec) + (float(sec_box_h) - float(sec_font_pt)) / 2.0 + float(sec_font_pt) * 0.25
                        c.drawCentredString(x_center, y_baseline, sec_title)
                finally:
                    c.restoreState()

                # advance y below header
                y = float(y_bottom_sec) - float(sec_gap_after)
                prev_bottom_by_col[col_idx] = y
            except Exception:
                pass

        # --- Draw: number text (top-aligned with image) ---
        # Satırın üst kenarı
        y_top = y

        # Numara yazısı: üst kenarı y_top ile hizalı
        # ReportLab'de drawString y=baseline, bu yüzden baseline = y_top - font_ascent_num
        c.saveState()
        c.setFillColorRGB(0, 0, 0)  # siyah yazı (kutu yok)
        y_text_baseline = y_top - font_ascent_num
        c.setFont(font_name_num, font_size_num)
        c.drawString(x_col, y_text_baseline, number_text)
        # Hidden stable id (used for preview hit-testing even if numbering resets)
        try:
            c.setFont(_get_font_name(bold=False), 1.0)
            c.setFillColorRGB(1, 1, 1)  # white on white
            c.drawString(x_col, y_text_baseline - 1.0, f"TMID:{internal_id}")
        except Exception:
            pass
        c.restoreState()
        
        # Avoid disk IO: draw image from memory (much faster)
        from reportlab.lib.utils import ImageReader
        import io
        img_reader = ImageReader(io.BytesIO(png_bytes))

        # --- Draw image ---
        # ReportLab'de drawImage y=bottom-left. Biz y_top (üst) ile hizalamak için bottom'u hesaplıyoruz.
        x_img = x_col + box_w + number_gap
        y_img_bottom = y_top - draw_h
        c.drawImage(
            img_reader,
            x_img,
            y_img_bottom,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
        )

        # Debug: draw a red rectangle around the reference question
        if ref_question_num is not None and int(internal_id) == int(ref_question_num):
            c.saveState()
            try:
                c.setLineWidth(2.0)
                c.setStrokeColorRGB(1.0, 0.0, 0.0)
                rect_x = x_col
                rect_y = y_top - max(box_h, draw_h)
                rect_w = box_w + number_gap + draw_w
                rect_h = max(box_h, draw_h)
                c.rect(rect_x, rect_y, rect_w, rect_h, fill=0, stroke=1)
            finally:
                c.restoreState()
        
        # Y koordinatını güncelle - kutu ve görselden hangisi daha yüksekse ona göre
        y_bottom = y_top - max(box_h, draw_h) - gap_after_q
        
        # Optional separator (eğer varsa, y_bottom'dan çıkar)
        separator_height = 0.0
        if opts.spaced and opts.draw_separators:
            separator_height = 14.0
            y_bottom -= separator_height
            # Separator çiz
            c.saveState()
            c.setLineWidth(0.4)
            c.setStrokeColorRGB(line_r, line_g, line_b)  # Ayarlanabilir çizgi rengi
            c.line(x_col, y_bottom, x_col + col_w, y_bottom)
            c.restoreState()
        
        # ÖNEMLİ: Alt sınır kontrolü - soru footer'ın üst çizgisinin altına geçmemeli
        if y_bottom < effective_bottom:
            y_bottom = effective_bottom
            y_top = y_bottom + max(box_h, draw_h) + gap_after_q + separator_height
        
        y = y_bottom  # Bir sonraki soru için başlangıç pozisyonu
        
        # Bu sorunun alt kenarını kaydet (bir sonraki soru için çakışma kontrolü için)
        prev_bottom_by_col[col_idx] = y_bottom
        
        # Bu soruyu mevcut sayfanın cevap anahtarına ekle (sadece çizilen sorular için)
        current_page_answers.append((display_number, ans))
        
        # ÖNEMLİ: Bir sonraki soru için aynı sütunda devam et (yukarıdan aşağıya)
        # Sütun değiştirme sadece soru sığmadığında yapılır (while döngüsünde zaten yapılıyor)

    # Flush remaining answer-key group (section/general)
    if _ak_group_entries:
        try:
            answer_key_groups.append((_ak_group_title, list(_ak_group_entries)))
        except Exception:
            pass

    # Son sayfanın cevaplarını kaydet
    if current_page_answers:
        page_answers[page_num] = list(current_page_answers)
    
    # Mod seçimi
    show_footer_answers = bool(getattr(opts, "answer_key_enabled", False)) and (getattr(opts, "answer_key_mode", "per_page") == "per_page")
    mode = (getattr(opts, "answer_key_mode", "per_page") or "per_page").strip().lower()

    # Testin sonuna ekle: son sorunun altına (sütun içinde) tablo ekle
    if bool(getattr(opts, "answer_key_enabled", False)) and mode == "end_of_test":
        # Footer'ın üst çizgisinin en az 2mm üstünde olmalı
        footer_y_top = mb + 35.0
        min_gap_above_footer_pt = mm_to_pt(2.0)
        effective_bottom = footer_y_top + min_gap_above_footer_pt
        has_sections = False
        try:
            has_sections = any(((t or "").strip() and (t or "").strip().lower() != "genel") for t, _ in (answer_key_groups or []))
        except Exception:
            has_sections = False

        groups_to_draw: List[Tuple[str, List[Tuple[int, str]]]] = []
        if has_sections and answer_key_groups:
            groups_to_draw = list(answer_key_groups)
        else:
            groups_to_draw = [("Cevap Anahtarı", list(answer_key))]

        for g_title, g_items in groups_to_draw:
            remaining = list(g_items or [])
            if not remaining:
                continue
            title = (g_title or "").strip() or "Cevap Anahtarı"
            title_pt = 12.0 if (has_sections and title.lower() != "genel") else 11.0
            while remaining:
                used, remaining2 = _draw_answer_key_table(
                    c,
                    x=x_col,
                    y_top=y,
                    w=col_w,
                    max_h=max(0.0, y - effective_bottom),
                    items=remaining,
                    entries_per_row=2,
                    title_text=title,
                    title_font_pt=title_pt,
                )
                if used <= 0.0:
                    next_column()
                    continue
                y -= used + 8.0
                remaining = remaining2

    # Son sayfanın footer'ını çiz (cevap anahtarı per_page modunda ise göster)
    if page_num > 0:
        last_page_answers = page_answers.get(page_num, [])
        draw_page_footer(c, page_num, last_page_answers, show_answers=show_footer_answers)
        # Son sayfanın filigranını en üste çiz (tüm içerikten sonra)
        _draw_watermark_and_centerline(c, page_w, page_h, opts)

    # Ayrı sayfaya ekle: test bittikten sonra cevap anahtarı sayfası (tablo)
    if bool(getattr(opts, "answer_key_enabled", False)) and mode == "separate_page":
        has_sections = False
        try:
            has_sections = any(((t or "").strip() and (t or "").strip().lower() != "genel") for t, _ in (answer_key_groups or []))
        except Exception:
            has_sections = False

        groups_to_draw: List[Tuple[str, List[Tuple[int, str]]]] = []
        if has_sections and answer_key_groups:
            groups_to_draw = list(answer_key_groups)
        else:
            groups_to_draw = [("Cevap Anahtarı", list(answer_key))]

        footer_y_top = mb + 35.0
        min_gap_above_footer_pt = mm_to_pt(2.0)
        effective_bottom = footer_y_top + min_gap_above_footer_pt
        x0 = ml
        w0 = page_w - ml - mr

        def new_answer_page() -> float:
            nonlocal page_num
            # Önceki sayfanın filigranını en üste çiz (varsa, yeni sayfaya geçmeden önce)
            if page_num > 0:
                _draw_watermark_and_centerline(c, page_w, page_h, opts)
            page_num += 1
            c.showPage()
            y_start_ans = _draw_header(c, page_w, page_h, opts, page_num)
            _apply_page_decorations(c, page_w, page_h, opts, y_start_ans)
            draw_page_footer(c, page_num, [], show_answers=False)
            # Bu sayfanın filigranını en üste çiz (tüm içerikten sonra)
            _draw_watermark_and_centerline(c, page_w, page_h, opts)
            return float(y_start_ans)

        y0 = new_answer_page()
        for g_title, g_items in groups_to_draw:
            remaining = list(g_items or [])
            if not remaining:
                continue
            title = (g_title or "").strip() or "Cevap Anahtarı"
            title_pt = 12.0 if (has_sections and title.lower() != "genel") else 11.0
            while remaining:
                used, remaining2 = _draw_answer_key_table(
                    c,
                    x=x0,
                    y_top=y0,
                    w=w0,
                    max_h=max(0.0, y0 - effective_bottom),
                    items=remaining,
                    entries_per_row=4,
                    title_text=title,
                    title_font_pt=title_pt,
                )
                if used <= 0.0:
                    y0 = new_answer_page()
                    continue
                y0 -= used + 10.0
                remaining = remaining2
        
        # Son cevap anahtarı sayfasının filigranını en üste çiz
        if page_num > 0:
            _draw_watermark_and_centerline(c, page_w, page_h, opts)

    # PDF'yi kaydet
    c.save()

    # No temp file cleanup needed (in-memory images)
