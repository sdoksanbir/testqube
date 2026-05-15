"""
Desktop-style PDF export - adapted from original-desktop/src/testmaker/services/pdf_exporter.py
Preserves layout, header themes, columns, gaps, and answer key.
"""

from __future__ import annotations

import base64
import html
import io
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple

DEBUG_LAYOUT = os.environ.get("DEBUG_PDF_LAYOUT", "").lower() in ("1", "true", "yes")

import fitz
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import getAscentDescent, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.pdfgen import pathobject

from app.core.config import EXPORT_DIR
from app.models.schemas import PdfItem, QuestionItem

# Soru numarası font metrikleri - numara görselin üst kenarı ile top-align için
_NUM_FONT = "Helvetica-Bold"
_NUM_FONT_SIZE = 10.0
_NUM_ASCENT_PT = getAscentDescent(_NUM_FONT, _NUM_FONT_SIZE)[0]  # ~7.18pt
_NUM_TO_IMAGE_GAP_PT = 3.5  # numara sağı ile görsel solu arası (sıkı)
_IMG_COL_RIGHT_PAD_PT = 2.0  # görsel ile sütun sağı arası
_DIVIDER_LINE_WIDTH_PT = 0.9  # yazılı yatay ayırıcı = orta sütun çizgisi (aynı kalınlık)

# Türkçe karakter desteği için Unicode font (bir kez kaydedilir)
_UNICODE_FONT_REGISTERED = False
_UNICODE_FONT = "Helvetica"  # fallback
_UNICODE_ITALIC_NAME: Optional[str] = None
_UNICODE_BOLDITALIC_NAME: Optional[str] = None


def _register_unicode_font() -> str:
    """Türkçe karakterler için Unicode font kaydet. ReportLab Helvetica Latin-1 ile sınırlı."""
    global _UNICODE_FONT_REGISTERED, _UNICODE_FONT, _UNICODE_ITALIC_NAME, _UNICODE_BOLDITALIC_NAME
    if _UNICODE_FONT_REGISTERED:
        return _UNICODE_FONT
    _UNICODE_FONT_REGISTERED = True
    if platform.system() == "Windows":
        root = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts"
        regular = root / "arial.ttf"
        bold = root / "arialbd.ttf"
        italic = root / "ariali.ttf"
        bolditalic = root / "arialbi.ttf"
    elif platform.system() == "Darwin":
        supp = Path("/System/Library/Fonts/Supplemental")
        regular = supp / "Arial.ttf"
        bold = supp / "Arial Bold.ttf"
        italic = supp / "Arial Italic.ttf"
        bolditalic = supp / "Arial Bold Italic.ttf"
    else:
        root = Path("/usr/share/fonts/truetype/dejavu")
        regular = root / "DejaVuSans.ttf"
        bold = root / "DejaVuSans-Bold.ttf"
        italic = root / "DejaVuSans-Oblique.ttf"
        bolditalic = root / "DejaVuSans-BoldOblique.ttf"
    for r, b in [(regular, bold), (regular, None)]:
        if r.exists():
            try:
                pdfmetrics.registerFont(TTFont("UnicodeFont", str(r)))
                if b and b.exists():
                    pdfmetrics.registerFont(TTFont("UnicodeFont-Bold", str(b)))
                _UNICODE_FONT = "UnicodeFont"
                if italic.exists():
                    try:
                        pdfmetrics.registerFont(TTFont("UnicodeFont-Italic", str(italic)))
                        _UNICODE_ITALIC_NAME = "UnicodeFont-Italic"
                    except Exception:
                        pass
                if bolditalic.exists():
                    try:
                        pdfmetrics.registerFont(TTFont("UnicodeFont-BoldItalic", str(bolditalic)))
                        _UNICODE_BOLDITALIC_NAME = "UnicodeFont-BoldItalic"
                    except Exception:
                        pass
                break
            except Exception:
                pass
    return _UNICODE_FONT


def mm_to_pt(mm: float) -> float:
    return float(mm) * 72.0 / 25.4


def pt_to_mm(pt: float) -> float:
    return (pt / 72.0) * 25.4


# Kağıt boyutu preset'leri (mm) - görseldeki ayarlar ile eşleşir
PAPER_PRESETS_MM: Dict[str, Tuple[float, float]] = {
    "A4 (210 x 297 mm)": (210.0, 297.0),
    "10 x 15 cm (4 x 6 in)": (100.0, 150.0),
    "13 x 18 cm (5 x 7 in)": (130.0, 180.0),
    "A6 (105 x 148 mm)": (105.0, 148.0),
    "A5 (148 x 210 mm)": (148.0, 210.0),
    "B5 (182 x 257 mm)": (182.0, 257.0),
    "9 x 13 cm (3.5 x 5 in)": (90.0, 130.0),
    "13 x 20 cm (5 x 8 in)": (130.0, 200.0),
    "20 x 25 cm (8 x 10 in)": (200.0, 250.0),
    "Letter #10 4 1/8 x 9 1/2 in": (104.78, 241.3),
    "Letter DL 110 x 220 mm": (110.0, 220.0),
    "Letter C6 114 x 162 mm": (114.0, 162.0),
    "Letter 8 1/2 x 11 in": (215.9, 279.4),
    "Legal 8 1/2 x 14 in": (215.9, 355.6),
    "A3 (297 x 420 mm)": (297.0, 420.0),
    "A3+ (329 x 483 mm)": (329.0, 483.0),
    "B4 (257 x 364 mm)": (257.0, 364.0),
    "B3 (364 x 515 mm)": (364.0, 515.0),
    # Kısa alias'lar (API geriye uyum)
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "A3": (297.0, 420.0),
    "B4": (257.0, 364.0),
    "B5": (182.0, 257.0),
    "B3": (364.0, 515.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}


def _page_size_pt(opts: "ExportOptions") -> Tuple[float, float]:
    """Sayfa boyutunu pt cinsinden döndür. Preset veya özel boyut (CUSTOM + page_width_mm, page_height_mm)."""
    preset = (opts.page_preset or "").strip()
    w_mm, h_mm = 210.0, 297.0
    if preset.upper() == "CUSTOM" and hasattr(opts, "page_width_mm") and hasattr(opts, "page_height_mm"):
        w_mm = float(getattr(opts, "page_width_mm", 210) or 210)
        h_mm = float(getattr(opts, "page_height_mm", 297) or 297)
    elif preset in PAPER_PRESETS_MM:
        w_mm, h_mm = PAPER_PRESETS_MM[preset]
    else:
        # Kısa isim veya metinden parse et (örn "A4 (210 x 297 mm)")
        for key, dims in PAPER_PRESETS_MM.items():
            if key.startswith(preset) or preset in key:
                w_mm, h_mm = dims
                break
    w_pt, h_pt = mm_to_pt(w_mm), mm_to_pt(h_mm)
    # Yatay (landscape) seçilirse en ve boy değiştir
    ori = (getattr(opts, "orientation", "") or "portrait").strip().lower()
    if ori.startswith("land") or ori == "yatay":
        return h_pt, w_pt
    return w_pt, h_pt


def page_size_pt(opts: "ExportOptions") -> Tuple[float, float]:
    """Public wrapper for _page_size_pt."""
    return _page_size_pt(opts)


# Merkezi layout sabitleri - header/banner yükseklikleri (sütun çizgileri ve contentTop ile senkron)
_FIRST_PAGE_BANNER_H_PT = 22.0  # _draw_header_style3_first_page box_h
_FIRST_PAGE_BANNER_GAP_PT = 2.0  # Banner altı boşluk (1. sayfa)
_OTHER_PAGES_BANNER_BELOW_GAP_PT = 4.0  # Test/deneme 2+ sayfa: banner altı → soru alanı
_OTHER_PAGES_HEADER_H_PT = 4.0  # Diğer sayfalar: içerik üstü (çizgi merkezi _OTHER_PAGES_TOP_RULE_DOWN_PT)
_OTHER_PAGES_TOP_RULE_DOWN_PT = 2.0  # Üst yatay çizgi: iç üstten bu kadar aşağı (sütun çizgisi ile aynı y)
_OTHER_PAGES_HEADER_GAP_PT = 8.0  # Çizgi altı boşluk → soru alanı
_DESC_BOX_GAP_BELOW_PT = 6.0  # Açıklama kutusu altı boşluk
_DESC_BOX_PAD_V_PT = 6.0  # Açıklama kutusu içi üst ve alt boşluk (simetrik)

_WRITTEN_FIELD_KEYS = ("ad_soyad", "numara", "puan", "sinif", "grup")
_WRITTEN_DEFAULT_LABELS_NO_COLON: Dict[str, str] = {
    "ad_soyad": "ADI SOYADI",
    "numara": "NUMARA",
    "puan": "PUAN",
    "sinif": "SINIF",
    "grup": "GRUP",
}

_WRITTEN_TITLE_TO_FIELDS_GAP_PT = 17.0
_WRITTEN_SINIF_TO_RULE_GAP_PT = mm_to_pt(2.0)
_WRITTEN_RULE_TO_CONTENT_GAP_PT = mm_to_pt(2.0)
_WRITTEN_PUAN_BOX_W_PT = 40.0
_WRITTEN_PUAN_BOX_H_PT = 40.0
_WRITTEN_PUAN_BOX_ROUND_R_PT = 4.0
_WRITTEN_FORM_LINE_LEN_PT = 100.0  # etiket sağı çizgi uzunluğu (pt)
_WRITTEN_BOOKLET_FONT_PT = 26.0
_WRITTEN_LABEL_TO_LINE_GAP_PT = 4.0
_WRITTEN_ROW_AFTER_ADI_PT = 8.0
_WRITTEN_LINE_ROW_PT = 11.0
_WRITTEN_CENTER_LETTER_MARGIN_PT = 26.0  # çizgiler ile ortadaki harf arası


def _split_written_title_semantic(title_txt: str) -> Tuple[str, str]:
    """DERSİ öncesi / sonrası (satır kırılımı); genişlik sarmalama ayrı."""
    t = (title_txt or "").strip()[:250]
    if not t:
        return ("YAZILI SINAV", "")
    if " DERSİ " in t:
        idx = t.find(" DERSİ ")
        return ((t[: idx + 7]).strip(), (t[idx + 7 :]).strip())
    idx = t.find("DERSİ")
    if idx != -1:
        return (t[: idx + 5].strip(), t[idx + 5 :].strip())
    return (t, "")


def _wrap_text_to_width(
    text: str,
    max_w: float,
    font_name: str,
    font_size: float,
) -> List[str]:
    words = (text or "").replace("\n", " ").split()
    lines: List[str] = []
    cur = ""
    for w in words:
        if not w:
            continue
        cand = f"{cur} {w}".strip() if cur else w
        if stringWidth(cand, font_name, font_size) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
                cur = ""
            if stringWidth(w, font_name, font_size) <= max_w:
                cur = w
            else:
                chunk = ""
                for ch in w:
                    t2 = chunk + ch
                    if stringWidth(t2, font_name, font_size) <= max_w:
                        chunk = t2
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = ch
                cur = chunk
    if cur:
        lines.append(cur)
    return lines


def _written_title_lines_resolved(opts: "ExportOptions") -> List[str]:
    page_w, _ = _page_size_pt(opts)
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    max_w = max(100.0, page_w - ml - mr - 8.0)
    title_txt = (
        (getattr(opts, "written_paper_title", None) or getattr(opts, "test_title", None) or "YAZILI SINAV").strip()
    )[:250]
    utf = _register_unicode_font()
    bold_name = f"{utf}-Bold" if f"{utf}-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"
    l1, l2 = _split_written_title_semantic(title_txt)
    lines: List[str] = []
    for part in (l1, l2):
        p = (part or "").strip()
        if not p:
            continue
        lines.extend(_wrap_text_to_width(p, max_w, bold_name, 10.0))
    if not lines:
        lines = ["YAZILI SINAV"]
    return lines[:8]


def _normalize_written_field_lines(opts: "ExportOptions") -> Dict[str, List[str]]:
    raw = getattr(opts, "written_paper_field_lines", None)
    if not isinstance(raw, dict):
        raw = {}
    out: Dict[str, List[str]] = {}
    for k in _WRITTEN_FIELD_KEYS:
        vals = raw.get(k)
        if not isinstance(vals, list):
            vals = []
        out[k] = [str(v).strip()[:120] for v in vals if str(v).strip()][:10]
    return out


def _written_labels_flat(opts: "ExportOptions") -> Dict[str, str]:
    raw = getattr(opts, "written_paper_field_labels", None)
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return {
            str(k): ("" if v is None else str(v)).strip()[:80]
            for k, v in raw.items()
        }
    return {}


def _written_field_label_core(opts: "ExportOptions", key: str) -> str:
    custom = (_written_labels_flat(opts).get(key) or "").strip()[:80]
    if custom:
        return custom
    return _WRITTEN_DEFAULT_LABELS_NO_COLON.get(key, key.replace("_", " ").upper())


def _written_field_label_pdf_left(opts: "ExportOptions", key: str) -> str:
    base = _written_field_label_core(opts, key)
    if base.endswith(":"):
        return base
    return f"{base}:"


def _written_field_label_pdf_puan(opts: "ExportOptions") -> str:
    return _written_field_label_core(opts, "puan")


def _written_field_hidden(opts: "ExportOptions", key: str) -> bool:
    raw = getattr(opts, "written_paper_field_hidden", None)
    if not isinstance(raw, dict):
        return False
    v = raw.get(key)
    if v is True:
        return True
    if v is False or v is None:
        return False
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("", "0", "false", "no", "off"):
            return False
        if s in ("1", "true", "yes", "on"):
            return True
    return bool(v)


def _written_n_rows_visible(opts: "ExportOptions", fields: Dict[str, List[str]], key: str) -> int:
    if _written_field_hidden(opts, key):
        return 0
    vals = fields.get(key) or []
    if not vals:
        return 1
    return max(1, min(10, len(vals)))


def _written_header_body_block_pt(
    opts: "ExportOptions", fields: Dict[str, List[str]]
) -> Tuple[int, int, int, float]:
    n_ad = _written_n_rows_visible(opts, fields, "ad_soyad")
    n_num = _written_n_rows_visible(opts, fields, "numara")
    n_sin = _written_n_rows_visible(opts, fields, "sinif")
    gap = _WRITTEN_ROW_AFTER_ADI_PT
    lh = _WRITTEN_LINE_ROW_PT
    body = 0.0
    if n_ad:
        body += float(n_ad) * lh
        if n_num or n_sin:
            body += gap
    if n_num:
        body += float(n_num) * lh
        if n_sin:
            body += gap
    if n_sin:
        body += float(n_sin) * lh
    return n_ad, n_num, n_sin, body


def _written_title_block_height_pt(opts: "ExportOptions") -> float:
    """Sarmalanmış başlık satır sayısı × 11 pt (_draw_written_paper_header ile aynı)."""
    return float(len(_written_title_lines_resolved(opts))) * 11.0


def _written_field_block_metrics(opts: "ExportOptions") -> Tuple[float, float]:
    """(block_body, block_low) — alan satırları yüksekliği ve PUAN ile dikey rezerv."""
    fields = _normalize_written_field_lines(opts)
    _, _, _, block_body = _written_header_body_block_pt(opts, fields)
    if _written_field_hidden(opts, "puan"):
        block_low = max(block_body, block_body / 2.0)
    else:
        block_low = max(block_body, block_body / 2.0 + _WRITTEN_PUAN_BOX_H_PT / 2.0)
    return block_body, block_low


def written_paper_rule_down_from_inner_top_pt(opts: "ExportOptions") -> float:
    """Üst iç kenardan yatay ayırıcı çizgi merkezine (pt, aşağı doğru)."""
    title_h = _written_title_block_height_pt(opts)
    _, block_low = _written_field_block_metrics(opts)
    return (
        title_h
        + _WRITTEN_TITLE_TO_FIELDS_GAP_PT
        + block_low
        + _WRITTEN_SINIF_TO_RULE_GAP_PT
        + _DIVIDER_LINE_WIDTH_PT / 2.0
    )


def written_paper_header_total_height_pt(opts: "ExportOptions") -> float:
    """Yazılı üst blok — ilk soru y_top ile uyumlu (çizgi + 2 mm + çizgi kalınlığı + 2 mm + tampon)."""
    title_h = _written_title_block_height_pt(opts)
    _, block_low = _written_field_block_metrics(opts)
    return (
        title_h
        + _WRITTEN_TITLE_TO_FIELDS_GAP_PT
        + block_low
        + _WRITTEN_SINIF_TO_RULE_GAP_PT
        + _DIVIDER_LINE_WIDTH_PT
        + _WRITTEN_RULE_TO_CONTENT_GAP_PT
    )


def _written_booklet_letter(opts: "ExportOptions") -> str:
    grp = (getattr(opts, "group", None) or "").strip()
    if not grp or grp == "Grup Yok":
        return ""
    if "Grup B" in grp or "B)" in grp:
        return "B"
    if "Grup C" in grp or "C)" in grp:
        return "C"
    if "Grup A" in grp or "A)" in grp:
        return "A"
    return ""


def _compute_layout_geometry(opts: "ExportOptions") -> Dict:
    """
    Merkezi layout geometrisi - preview ve export aynı değerleri kullanır.
    A4 landscape 3 sütun dahil tüm modlar için tutarlı hesaplama.

    Returns:
        {
            "page_w": float, "page_h": float,
            "ml": float, "mr": float, "mt": float, "mb": float,
            "usable_width": float, "usable_height": float (per column),
            "column_count": int, "column_gap": float, "column_width": float,
            "column_x": [x0, x1, ...],
            "content_top_first": float, "content_top_other": float,
            "content_bottom": float,
            "orientation": str,
        }
    """
    page_w, page_h = _page_size_pt(opts)
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)
    mb = mm_to_pt(opts.margin_bottom_mm)
    ori = (getattr(opts, "orientation", "") or "portrait").strip().lower()
    is_landscape = ori.startswith("land") or ori == "yatay"

    usable_width = page_w - ml - mr
    cols = max(1, min(6, int(opts.columns or 1)))
    col_gap = mm_to_pt(opts.column_gap_mm)
    if cols > 1:
        total_gap = (cols - 1) * col_gap
        col_w = (usable_width - total_gap) / cols
    else:
        col_w = usable_width

    column_x = [ml + i * (col_w + col_gap) for i in range(cols)]

    footer_top = mb + mm_to_pt(opts.footer_top_offset_mm)
    content_bottom = footer_top

    if getattr(opts, "written_paper_header", False):
        content_top_first = page_h - mt - written_paper_header_total_height_pt(opts)
    elif opts.include_description:
        box_h = _get_description_box_height_pt(opts)
        content_top_first = (
            page_h
            - mt
            - _FIRST_PAGE_BANNER_H_PT
            - _FIRST_PAGE_BANNER_GAP_PT
            - box_h
            - _DESC_BOX_GAP_BELOW_PT
        )
    else:
        content_top_first = page_h - mt - _FIRST_PAGE_BANNER_H_PT - _FIRST_PAGE_BANNER_GAP_PT

    # Test / deneme: 2+ sayfada da üstte aynı banner → içerik üstü = 1. sayfa (açıklama yok)
    if getattr(opts, "written_paper_header", False):
        content_top_other = (
            page_h - mt - _OTHER_PAGES_HEADER_H_PT - _OTHER_PAGES_HEADER_GAP_PT
        )
    else:
        content_top_other = (
            page_h - mt - _FIRST_PAGE_BANNER_H_PT - _OTHER_PAGES_BANNER_BELOW_GAP_PT
        )
    usable_height_first = content_top_first - content_bottom
    usable_height_other = content_top_other - content_bottom

    if DEBUG_LAYOUT:
        print(
            f"[LAYOUT] geometry: preset={opts.page_preset} orientation={ori} "
            f"page={page_w:.0f}x{page_h:.0f}pt "
            f"usable_w={usable_width:.0f} cols={cols} col_gap={col_gap:.1f} "
            f"col_w={col_w:.1f} col_x={[f'{x:.0f}' for x in column_x]} "
            f"content_top_1st={content_top_first:.0f} content_top_other={content_top_other:.0f} "
            f"content_bottom={content_bottom:.0f} usable_h_1st={usable_height_first:.0f}"
        )

    return {
        "page_w": page_w,
        "page_h": page_h,
        "ml": ml,
        "mr": mr,
        "mt": mt,
        "mb": mb,
        "usable_width": usable_width,
        "content_top_first": content_top_first,
        "content_top_other": content_top_other,
        "content_bottom": content_bottom,
        "usable_height_first": usable_height_first,
        "usable_height_other": usable_height_other,
        "column_count": cols,
        "column_gap": col_gap,
        "column_width": col_w,
        "column_x": column_x,
        "footer_top": footer_top,
        "orientation": "landscape" if is_landscape else "portrait",
    }


@dataclass
class ExportOptions:
    """Desktop ExportOptions subset - enough for layout parity."""
    test_title: str = "TEST"
    school_name: str = ""
    theme_color: str = "#AECBFA"
    header_style_id: str = "style3"
    answer_key_enabled: bool = True
    answer_key_mode: str = "per_page"  # per_page | separate_page | end_of_test
    columns: int = 2
    column_gap_mm: float = 8.0
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 15.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0
    question_gap_mm: float = 35.0  # preferred spacing (mm)
    question_gap_min_mm: float = 12.0  # minimum spacing when compacting (mm)
    auto_compact_spacing: bool = True  # try reducing spacing before next column
    zoom: float = 6.0  # 432 DPI (72*6) - yüksek yazdırma kalitesi
    page_preset: str = "A4"
    page_width_mm: float = 210.0  # CUSTOM preset için
    page_height_mm: float = 297.0  # CUSTOM preset için
    orientation: str = "portrait"  # portrait/dikey | landscape/yatay
    # Boşluklar (mm) - pt yerine mm ile tanımlı
    footer_top_offset_mm: float = 12.35  # alt kenardan footer üst çizgisine (~35pt)
    footer_bottom_offset_mm: float = 5.28  # alt kenardan footer alt çizgisine (~15pt)
    footer_content_gap_mm: float = 5.28  # içerik tabanı ile footer üst çizgisi arası (~15pt)
    column_bottom_min_mm: float = 6.0  # son soru ile içerik tabanı arası min boşluk
    header_reserved_mm: float = 13.0  # üstten header için ayrılan alan (ilk sayfa ~36pt)
    include_description: bool = False  # Test ile ilgili açıklama ekle (banner altında kutu)
    test_description: str = ""  # Açıklama metni (tek sütun geriye uyum)
    description_column_count: int = 1  # Sütun sayısı (1–3)
    description_texts: List[str] = field(default_factory=list)  # Sütun bazlı metinler (HTML)
    description_column_dividers: bool = False  # 2+ sütunda kutuda dikey ayırıcı çizgiler
    # Çizgi üzerine yazı (sütun ayırıcı çizginin ortasında)
    center_line_enabled: bool = False
    center_line_text: str = ""
    center_line_bold: bool = False
    center_line_italic: bool = False
    center_line_color: str = ""  # Boşsa theme_color kullanılır
    center_line_text_direction: str = "up"  # up | down
    # Filigran
    watermark_enabled: bool = False
    watermark_mode: str = "text"
    watermark_text: str = ""
    watermark_text_opacity_pct: int = 20
    watermark_text_size_pct: int = 90
    watermark_text_angle_deg: int = 45
    watermark_text_color: str = "#000000"
    watermark_image_base64: Optional[str] = None
    watermark_image_opacity_pct: int = 15
    watermark_image_size_pct: int = 50
    # Yazılı Kağıdı
    written_paper_header: bool = False
    written_paper_title: Optional[str] = None
    exam_type: Optional[str] = None
    # False: yaprak test kağıdı — "Diğer sayfaya geçiniz" / "TEST BİTTİ" footer yazıları yok
    footer_nav_page_turn_texts: bool = True
    class_section: Optional[str] = None
    group: Optional[str] = None
    teacher_names: List[Dict[str, str]] = field(default_factory=list)
    # Yazılı son sayfa: okul müdürü adı soyadı (imza bloğu sağ alt)
    principal_name: Optional[str] = None
    # Yazılı başlık altı alan satırları (modal EKLE ile); anahtarlar: ad_soyad, numara, puan, sinif, grup
    written_paper_field_lines: Optional[Dict[str, List[str]]] = None
    written_paper_field_hidden: Optional[Dict[str, bool]] = None
    written_paper_field_labels: Optional[Dict[str, str]] = None


# Cevap Anahtarı layout - Canvas preview (answerKeyLayout.ts) ile senkron
_ANSWER_KEY_HEADER_PT = 14.0
_ANSWER_KEY_ROW_PT = 14.0
_ANSWER_KEY_TITLE_FONT_PT = 11.0
_ANSWER_KEY_CELL_FONT_PT = 9.0
_ANSWER_KEY_BORDER_PT = 0.8
_ANSWER_KEY_GRID_PT = 0.3
_ANSWER_KEY_BOTTOM_PAD_PT = 2.0


def _answer_key_table_height(
    items: List[Tuple[int, str]], entries_per_row: int
) -> float:
    """Tablo yüksekliğini hesapla (pt)."""
    col_count = max(1, int(entries_per_row or 1))
    rows = (len(items) + col_count - 1) // col_count
    return (
        _ANSWER_KEY_HEADER_PT
        + rows * _ANSWER_KEY_ROW_PT
        + _ANSWER_KEY_BOTTOM_PAD_PT
    )


def _answer_key_next_chunk(
    max_h: float,
    items: List[Tuple[int, str]],
    entries_per_row: int,
) -> Tuple[float, List[Tuple[int, str]], List[Tuple[int, str]]]:
    """
    Cevap anahtarı tablosunda bir sonraki parça: (kullanılan yükseklik+5pt, chunk, kalan).
    max_h'ye sığmıyorsa (0.0, [], items) döner — ayrı sayfaya geçilir.
    """
    col_count = max(1, int(entries_per_row or 1))
    header_h = _ANSWER_KEY_HEADER_PT
    row_h = _ANSWER_KEY_ROW_PT
    available = max(0.0, max_h - header_h - _ANSWER_KEY_BOTTOM_PAD_PT)
    max_rows = max(1, int(available // row_h)) if available > row_h else 0
    if max_rows <= 0 or not items:
        return 0.0, [], list(items)
    capacity = max_rows * col_count
    chunk = items[:capacity]
    remaining = items[capacity:]
    rows = (len(chunk) + col_count - 1) // col_count
    table_h = header_h + rows * row_h + _ANSWER_KEY_BOTTOM_PAD_PT
    table_h = min(table_h, max_h)
    return table_h + 5.0, chunk, remaining


def _draw_answer_key_table(
    canvas_obj,
    opts: ExportOptions,
    *,
    x: float,
    y_top: float,
    w: float,
    max_h: float,
    items: List[Tuple[int, str]],
    entries_per_row: int,
    title_text: str = "CEVAP ANAHTARI",
    title_font_pt: float = 11.0,
) -> Tuple[float, List[Tuple[int, str]]]:
    """
    Cevap anahtarı tablosu. Eşit sütun/satır, tam ortalanmış içerik.
    Preview ve PDF export aynı layout mantığını kullanır.
    Returns (used_height, remaining_items).
    """
    theme = _hex_to_rgb01(opts.theme_color)
    stroke = theme
    bg = (1.0, 1.0, 1.0)
    bg_header = (
        min(1.0, theme[0] * 0.25 + 0.75),
        min(1.0, theme[1] * 0.25 + 0.75),
        min(1.0, theme[2] * 0.25 + 0.75),
    )

    col_count = max(1, int(entries_per_row or 1))
    header_h = _ANSWER_KEY_HEADER_PT
    row_h = _ANSWER_KEY_ROW_PT

    _, chunk, remaining = _answer_key_next_chunk(max_h, items, entries_per_row)
    if not chunk:
        return 0.0, items
    rows = (len(chunk) + col_count - 1) // col_count

    table_w = max(1.0, w)
    cell_w = table_w / col_count
    table_x = x
    table_h = header_h + rows * row_h + _ANSWER_KEY_BOTTOM_PAD_PT
    table_h = min(table_h, max_h)
    y_bottom = y_top - table_h

    utf_font = _register_unicode_font()
    title_font = (
        f"{utf_font}-Bold"
        if f"{utf_font}-Bold" in pdfmetrics.getRegisteredFontNames()
        else _get_font_name(bold=True)
    )
    cell_font = (
        utf_font if utf_font != "Helvetica" else _get_font_name(bold=False)
    )
    cell_font_bold = (
        f"{utf_font}-Bold"
        if f"{utf_font}-Bold" in pdfmetrics.getRegisteredFontNames()
        else _get_font_name(bold=True)
    )
    tf = max(9.0, min(16.0, float(title_font_pt or _ANSWER_KEY_TITLE_FONT_PT)))
    cf = _ANSWER_KEY_CELL_FONT_PT

    canvas_obj.saveState()
    try:
        canvas_obj.setFillColorRGB(*bg)
        canvas_obj.rect(table_x, y_bottom, table_w, table_h, fill=1, stroke=0)

        canvas_obj.setFillColorRGB(*bg_header)
        canvas_obj.rect(
            table_x, y_top - header_h, table_w, header_h, fill=1, stroke=0
        )

        canvas_obj.setLineWidth(_ANSWER_KEY_BORDER_PT)
        canvas_obj.setStrokeColorRGB(*stroke)
        canvas_obj.rect(table_x, y_bottom, table_w, table_h, fill=0, stroke=1)

        tt = (
            (title_text or "CEVAP ANAHTARI")
            .strip()
            .upper()
            or "CEVAP ANAHTARI"
        )
        canvas_obj.setFont(title_font, tf)
        canvas_obj.setFillColorRGB(*theme)
        title_center_y = y_top - header_h / 2.0
        asc, desc = getAscentDescent(title_font, tf)
        title_baseline = title_center_y - (asc + desc) / 2.0
        canvas_obj.drawCentredString(
            table_x + table_w / 2.0, title_baseline, tt[:50]
        )

        canvas_obj.setFont(cell_font_bold, cf)
        canvas_obj.setFillColorRGB(0, 0, 0)
        asc, desc = getAscentDescent(cell_font_bold, cf)

        for c_i in range(col_count):
            cell_center_x = table_x + (c_i + 0.5) * cell_w
            for r_i in range(rows):
                idx = r_i * col_count + c_i
                if idx >= len(chunk):
                    break
                num, ans = chunk[idx]
                ans = (ans or "").strip().upper() or "?"
                cell_center_y = y_top - header_h - (r_i + 0.5) * row_h
                y_baseline = cell_center_y - (asc + desc) / 2.0
                text = f"{num}. {ans}"
                canvas_obj.drawCentredString(cell_center_x, y_baseline, text)

        canvas_obj.setStrokeColorRGB(*stroke)
        canvas_obj.setLineWidth(_ANSWER_KEY_GRID_PT)
        for c_i in range(1, col_count):
            line_x = table_x + c_i * cell_w
            canvas_obj.line(line_x, y_bottom, line_x, y_top - header_h)
        for r_i in range(1, rows + 1):
            yy = y_top - header_h - r_i * row_h
            canvas_obj.line(table_x, yy, table_x + table_w, yy)
    finally:
        canvas_obj.restoreState()

    return table_h + 5.0, remaining


def _get_font_name(bold: bool = False, italic: bool = False) -> str:
    """ReportLab font adı - kalın ve italik kombinasyonu."""
    if bold and italic:
        return "Helvetica-BoldOblique"
    if bold:
        return "Helvetica-Bold"
    if italic:
        return "Helvetica-Oblique"
    return "Helvetica"


def _hex_to_rgb01(hex_color: str, fallback: Tuple[float, float, float] = (0.68, 0.80, 0.98)) -> Tuple[float, float, float]:
    s = (hex_color or "").strip().lstrip("#")
    if len(s) != 6:
        return fallback
    try:
        return (
            int(s[0:2], 16) / 255.0,
            int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0,
        )
    except Exception:
        return fallback


def _remove_background_from_png(png_bytes: bytes) -> bytes:
    """Make near-white/light pixels fully transparent."""
    img = Image.open(io.BytesIO(png_bytes))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    pixels = img.load()
    w, h = img.size
    threshold = 220
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if (r + g + b) / 3 >= threshold:
                pixels[x, y] = (r, g, b, 0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_crop(
    pdf_path: Path,
    page_number: int,
    norm_x: float,
    norm_y: float,
    norm_w: float,
    norm_h: float,
    zoom: float = 6.0,
    remove_background: bool = False,
) -> Tuple[bytes, int, int]:
    """Render cropped region as PNG. norm_* are 0..1. Returns (png_bytes, width_px, height_px)."""
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_number - 1)
        rect = page.rect
        x_pt = norm_x * rect.width
        y_pt = norm_y * rect.height
        w_pt = norm_w * rect.width
        h_pt = norm_h * rect.height
        clip = fitz.Rect(x_pt, y_pt, x_pt + w_pt, y_pt + h_pt)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        png_bytes = pix.tobytes("png")
    if remove_background:
        png_bytes = _remove_background_from_png(png_bytes)
    return png_bytes, pix.width, pix.height


def _png_base64_to_bytes_and_size(b64: str) -> Tuple[bytes, int, int]:
    """Decode base64 PNG, return (bytes, width_px, height_px)."""
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw))
    return raw, img.width, img.height


def _make_round_rect_left_path(x: float, y: float, w: float, h: float, r: float) -> pathobject.PDFPathObject:
    """Sol üst köşesi yuvarlatılmış, alt köşeler sivri (ReportLab: y yukarı, üst=y+h)."""
    k = 0.5522847498
    p = pathobject.PDFPathObject()
    if r <= 0:
        p.rect(x, y, w, h)
        return p
    p.moveTo(x + r, y + h)
    p.lineTo(x + w, y + h)
    p.lineTo(x + w, y)
    p.lineTo(x, y)
    p.lineTo(x, y + h - r)
    p.curveTo(x, y + h - r * k, x + r * k, y + h, x + r, y + h)
    p.close()
    return p


def _round_rect_left_only(c: canvas.Canvas, x: float, y: float, w: float, h: float, r: float) -> None:
    """Sadece sol üst ve sol alt köşeleri yuvarlatılmış dikdörtgen (ReportLab y yukarı)."""
    if r <= 0:
        c.rect(x, y, w, h)
        return
    p = _make_round_rect_left_path(x, y, w, h, r)
    c.drawPath(p, stroke=1, fill=0)


def _draw_premium_pattern(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    theme: Tuple[float, float, float],
    pad: float = 2.0,
    slope: int = 1,
    clip_path: Optional[pathobject.PDFPathObject] = None,
) -> None:
    """Nokta ve çizgi deseni - premium hava. clip_path verilirse desen sadece o alanda çizilir."""
    c.saveState()
    if clip_path is not None:
        c.clipPath(clip_path, stroke=0, fill=0)
    c.setStrokeColorRGB(*theme)
    c.setFillColorRGB(*theme)
    c.setLineWidth(0.2)
    try:
        # Baskıda okunur olsun (önceden ~0.4 çok soluk kalıyordu)
        c.setFillAlpha(0.72)
        c.setStrokeAlpha(0.72)
    except Exception:
        pass
    ix, iy = x + pad, y + pad
    iw, ih = w - 2 * pad, h - 2 * pad
    dot_r = 0.48
    step = 3.35
    px = ix
    while px < ix + iw:
        py = iy
        while py < iy + ih:
            c.circle(px, py, dot_r, stroke=0, fill=1)
            py += step
        px += step
    try:
        c.setFillAlpha(1.0)
        c.setStrokeAlpha(1.0)
    except Exception:
        pass
    c.restoreState()


def _make_round_rect_right_path(x: float, y: float, w: float, h: float, r: float) -> pathobject.PDFPathObject:
    """Sağ üst köşesi yuvarlatılmış, alt köşeler sivri (ReportLab: y yukarı, üst=y+h)."""
    k = 0.5522847498
    p = pathobject.PDFPathObject()
    if r <= 0:
        p.rect(x, y, w, h)
        return p
    p.moveTo(x, y + h)
    p.lineTo(x + w - r, y + h)
    p.curveTo(x + w - r * k, y + h, x + w, y + h - r * (1 - k), x + w, y + h - r)
    p.lineTo(x + w, y)
    p.lineTo(x, y)
    p.lineTo(x, y + h)
    p.close()
    return p


def _round_rect_right_only(c: canvas.Canvas, x: float, y: float, w: float, h: float, r: float) -> None:
    """Sadece sağ üst ve sağ alt köşeleri yuvarlatılmış dikdörtgen."""
    if r <= 0:
        c.rect(x, y, w, h)
        return
    p = _make_round_rect_right_path(x, y, w, h, r)
    c.drawPath(p, stroke=1, fill=0)


def _make_round_top_corners_rect_path(
    x0: float, y0: float, w: float, h: float, r: float
) -> pathobject.PDFPathObject:
    """
    Alt kenar sivri, yalnızca üst-sol ve üst-sağ köşeler yuvarlatılmış dikdörtgen.
    (x0,y0) sol-alt, y yukarı doğru (ReportLab).
    """
    k = 0.5522847498
    p = pathobject.PDFPathObject()
    if r <= 0:
        p.rect(x0, y0, w, h)
        return p
    r = min(r, w / 2.0 - 0.5, h / 2.0 - 0.5)
    if r <= 0:
        p.rect(x0, y0, w, h)
        return p
    x1, y1 = x0 + w, y0 + h
    p.moveTo(x0, y0)
    p.lineTo(x1, y0)
    p.lineTo(x1, y1 - r)
    p.curveTo(x1, y1 - r + k * r, x1 - r + k * r, y1, x1 - r, y1)
    p.lineTo(x0 + r, y1)
    p.curveTo(x0 + r - k * r, y1, x0, y1 - r + k * r, x0, y1 - r)
    p.lineTo(x0, y0)
    p.close()
    return p


def _draw_other_page_test_banner(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
) -> Tuple[float, float]:
    """
    Diğer sayfalar (test/deneme): üst köşeleri yuvarlak çerçeve, içi noktalı tema deseni;
    sol test adı / sağ kurum adı — metinlerin arkası beyaz dikdörtgen (çerçevesiz).
    """
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)
    theme = _hex_to_rgb01(opts.theme_color)
    box_h = 22.0
    gap = _OTHER_PAGES_BANNER_BELOW_GAP_PT
    r_corner = 5.0
    inner_box_y = page_h - mt - box_h
    inner_h = box_h
    content_w = page_w - ml - mr
    pad_x = 8.0
    text_pad_w = 4.0
    text_pad_v = 3.0

    p_banner = _make_round_top_corners_rect_path(ml, inner_box_y, content_w, inner_h, r_corner)
    _draw_premium_pattern(
        c,
        ml,
        inner_box_y,
        content_w,
        inner_h,
        theme,
        pad=2.0,
        slope=1,
        clip_path=p_banner,
    )
    c.saveState()
    c.setLineWidth(1.0)
    c.setStrokeColorRGB(*theme)
    c.drawPath(p_banner, stroke=1, fill=0)
    c.restoreState()

    utf = _register_unicode_font()
    bold_name = "Helvetica-Bold" if utf == "Helvetica" else f"{utf}-Bold"
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        bold_name = utf if utf != "Helvetica" else "Helvetica-Bold"

    title_txt = ((opts.test_title or "TEST").strip() or "TEST")[:80]
    school_txt = ((getattr(opts, "school_name", "") or "").strip())[:80]
    half = max(30.0, content_w / 2.0 - 10.0)
    while title_txt and stringWidth(title_txt, bold_name, 10) > half - pad_x:
        title_txt = title_txt[:-1]
    while school_txt and stringWidth(school_txt, bold_name, 10) > half - pad_x:
        school_txt = school_txt[:-1]

    asc, des = getAscentDescent(bold_name, 10.0)
    # ReportLab: descent çoğu fontta negatif; metin dikey merkezi = baseline + (asc+des)/2
    y_banner_mid = inner_box_y + inner_h / 2.0
    y_text = y_banner_mid - (asc + des) / 2.0
    y_band_bot = y_text + des - text_pad_v
    band_h = asc - des + 2.0 * text_pad_v

    c.setFillColorRGB(1, 1, 1)
    tw_title = stringWidth(title_txt, bold_name, 10)
    c.rect(
        ml + pad_x - text_pad_w,
        y_band_bot,
        tw_title + 2.0 * text_pad_w,
        band_h,
        stroke=0,
        fill=1,
    )
    if school_txt:
        sw = stringWidth(school_txt, bold_name, 10)
        c.rect(
            page_w - mr - pad_x - sw - text_pad_w,
            y_band_bot,
            sw + 2.0 * text_pad_w,
            band_h,
            stroke=0,
            fill=1,
        )

    c.setFont(bold_name, 10)
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.drawString(ml + pad_x, y_text, title_txt)
    if school_txt:
        sw = stringWidth(school_txt, bold_name, 10)
        c.drawString(page_w - mr - pad_x - sw, y_text, school_txt)

    return inner_box_y, gap


def _style3_paint_three_box_banner(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
) -> Tuple[float, float]:
    """
    Test/deneme tema bandı (3 kutu). ReportLab Y alttan.
    Dönüş: (inner_box_y, gap_pt) — inner_box_y banner dikdörtgeninin alt kenarı.
    """
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)
    theme = _hex_to_rgb01(opts.theme_color)
    box_h = 22.0
    content_w = page_w - ml - mr
    gap = 2.0
    left_w = content_w * 0.35
    mid_w = content_w * 0.30
    right_w = content_w - left_w - mid_w - 2 * gap
    x_left = ml
    x_mid = ml + left_w + gap
    x_right = ml + left_w + mid_w + 2 * gap
    inner_box_y = page_h - mt - box_h
    inner_h = box_h
    r = 6.0
    c.saveState()
    c.setLineWidth(1.0)
    c.setStrokeColorRGB(*theme)

    _draw_premium_pattern(
        c, x_left, inner_box_y, left_w, inner_h, theme,
        pad=2.0, slope=1, clip_path=_make_round_rect_left_path(x_left, inner_box_y, left_w, inner_h, r)
    )
    _round_rect_left_only(c, x_left, inner_box_y, left_w, inner_h, r)

    c.setFillColorRGB(*theme)
    c.rect(x_mid, inner_box_y, mid_w, inner_h, stroke=1, fill=1)

    _draw_premium_pattern(
        c, x_right, inner_box_y, right_w, inner_h, theme,
        pad=2.0, slope=-1, clip_path=_make_round_rect_right_path(x_right, inner_box_y, right_w, inner_h, r)
    )
    _round_rect_right_only(c, x_right, inner_box_y, right_w, inner_h, r)

    c.setFillColorRGB(1, 1, 1)
    utf = _register_unicode_font()
    bold_name = "Helvetica-Bold" if utf == "Helvetica" else f"{utf}-Bold"
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        bold_name = utf if utf != "Helvetica" else "Helvetica-Bold"
    c.setFont(bold_name, 12)
    c.drawCentredString(x_mid + mid_w / 2, inner_box_y + inner_h / 2 - 4, (opts.test_title or "TEST")[:40])
    c.restoreState()
    return inner_box_y, gap


def _test_footer_band_y(opts: ExportOptions, mb: float) -> Tuple[float, float, float]:
    y_top = mb + mm_to_pt(opts.footer_top_offset_mm)
    y_bot = mb + mm_to_pt(opts.footer_bottom_offset_mm)
    return y_top, y_bot, (y_top + y_bot) / 2.0


def _draw_written_paper_footer_simple(
    c: canvas.Canvas,
    *,
    ml: float,
    mr: float,
    page_w: float,
    footer_top: float,
    footer_font: str,
    show_answers: bool,
    answers: List[Tuple[int, str]],
) -> None:
    """Yazılı kağıdı: tek çizgi + isteğe bağlı cevaplar (değişmez)."""
    c.saveState()
    c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
    c.setStrokeColorRGB(0, 0, 0)
    c.line(ml, footer_top, page_w - mr, footer_top)
    if show_answers and answers:
        c.setFont(footer_font, 9)
        c.setFillColorRGB(0, 0, 0)
        txt = "  ".join(f"{n}. {a or '?'}" for n, a in sorted(answers, key=lambda t: t[0]))
        c.drawString(ml, footer_top + 8.0, txt[:120])
    c.restoreState()


def _draw_test_paper_footer_double(
    c: canvas.Canvas,
    *,
    ml: float,
    mr: float,
    page_w: float,
    mb: float,
    opts: ExportOptions,
    theme: Tuple[float, float, float],
    footer_font: str,
    page_no: int,
    show_answers: bool,
    answers: List[Tuple[int, str]],
    last_question_page_num: Optional[int] = None,
) -> None:
    """Test/deneme: çift çizgi; ortada daire içi sayfa no; solda cevap anahtarı (daireye taşmaz)."""
    y_top, y_bot, y_mid = _test_footer_band_y(opts, mb)
    cx = (ml + page_w - mr) / 2.0
    band = y_top - y_bot
    max_r = max(4.0, band / 2.0 - 2.0)
    circle_r = min(11.0, max_r)

    c.saveState()
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(*theme)
    c.line(ml, y_top, page_w - mr, y_top)
    c.restoreState()

    utf = _register_unicode_font()
    bold_pg = (
        f"{utf}-Bold"
        if f"{utf}-Bold" in pdfmetrics.getRegisteredFontNames()
        else "Helvetica-Bold"
    )

    if show_answers and answers:
        sorted_ans = sorted(answers, key=lambda t: t[0])
        full_ans = "  ".join(f"{n}. {(a or '?').strip()}" for n, a in sorted_ans)
        left_limit = cx - circle_r - 10.0
        avail = max(20.0, left_limit - ml)
        c.saveState()
        c.setFont(footer_font, 9)
        c.setFillColorRGB(*theme)
        ans_show = full_ans
        while ans_show and stringWidth(ans_show, footer_font, 9) > avail:
            ans_show = ans_show[:-1]
        if len(ans_show) < len(full_ans) and ans_show:
            ell = "…"
            while ans_show and stringWidth(ans_show + ell, footer_font, 9) > avail:
                ans_show = ans_show[:-1]
            ans_show = (ans_show + ell).strip()
        try:
            fo9 = pdfmetrics.getFont(footer_font)
            asc9 = (fo9.face.ascent / 1000.0) * 9.0
        except Exception:
            asc9 = 6.5
        if ans_show:
            c.drawString(ml, y_mid - asc9 / 2.0, ans_show[:200])
        c.restoreState()

    c.saveState()
    c.setLineWidth(0.4)
    c.setStrokeColorRGB(*theme)
    c.line(ml, y_bot, page_w - mr, y_bot)
    c.restoreState()

    pg_txt = str(int(page_no))
    # Daire içi güvenli kutu (çapın ~%72’si); hem genişlik hem yükseklik
    chord = 2.0 * circle_r * 0.72
    fs = 10.0
    while fs >= 5.0:
        tw = stringWidth(pg_txt, bold_pg, fs)
        asc, des = getAscentDescent(bold_pg, fs)
        th = asc - des
        if tw <= chord and th <= chord:
            break
        fs -= 0.5
    c.saveState()
    c.setLineWidth(0.8)
    c.setStrokeColorRGB(*theme)
    c.setFillColorRGB(1, 1, 1)
    c.circle(cx, y_mid, circle_r, fill=1, stroke=1)
    c.setFillColorRGB(*theme)
    c.setFont(bold_pg, fs)
    asc, des = getAscentDescent(bold_pg, fs)
    # descent çoğu fontta negatif; görsel merkez y_mid → taban çizgisi
    ty = y_mid - (asc + des) / 2.0
    c.drawCentredString(cx, ty, pg_txt)
    c.restoreState()

    show_nav = bool(getattr(opts, "footer_nav_page_turn_texts", True))
    if (
        show_nav
        and last_question_page_num is not None
        and int(last_question_page_num) >= 1
    ):
        nav_bold = (
            f"{footer_font}-Bold"
            if f"{footer_font}-Bold" in pdfmetrics.getRegisteredFontNames()
            else "Helvetica-Bold"
        )
        c.saveState()
        c.setFillColorRGB(0, 0, 0)
        rx = page_w - mr
        fs_nav = 8.0
        c.setFont(nav_bold, fs_nav)
        asc_n, des_n = getAscentDescent(nav_bold, fs_nav)
        line_h = asc_n - des_n
        lead = fs_nav * 1.2
        lq = int(last_question_page_num)
        pn = int(page_no)
        if pn < lq:
            ty_n = y_mid - (asc_n + des_n) / 2.0
            c.drawRightString(rx, ty_n, "Diğer sayfaya geçiniz.")
        elif pn == lq:
            y_hi = y_mid + (line_h + lead) / 2.0 - des_n
            y_lo = y_hi - lead - line_h
            c.drawRightString(rx, y_hi, "TEST BİTTİ.")
            c.drawRightString(rx, y_lo, "CEVAPLARINIZI KONTROL EDİNİZ.")
        c.restoreState()


def _draw_header_style3_first_page(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
) -> float:
    """İlk sayfa: 3 kutu yan yana; isteğe bağlı açıklama kutusu."""
    inner_box_y, gap = _style3_paint_three_box_banner(c, page_w, page_h, opts)
    if opts.include_description:
        return _draw_description_box(c, page_w, page_h, inner_box_y, opts, banner_gap_pt=gap)
    return inner_box_y - gap


def _html_to_plain(txt: str) -> str:
    """HTML etiketlerini kaldır, düz metin döndür."""
    if not txt or not isinstance(txt, str):
        return ""
    import re
    t = re.sub(r"<[^>]+>", " ", txt)
    t = html.unescape(t)
    return " ".join(t.split()).strip()


def _html_to_lines(txt: str) -> List[str]:
    """HTML'den satır listesi - <br>, </p>, <p>, </li> satır sonu. <li> bullet (•) ekler."""
    if not txt or not isinstance(txt, str):
        return []
    import re
    t = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    t = re.sub(r"</p>", "\n", t, flags=re.I)
    t = re.sub(r"<p(?:\s[^>]*)?>", "\n", t, flags=re.I)
    t = re.sub(r"<li(?:\s[^>]*)?>", "\n• ", t, flags=re.I)
    t = re.sub(r"</li>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    lines = [" ".join(s.split()).strip() for s in t.split("\n") if " ".join(s.split()).strip()]
    return lines if lines else [""]


def _get_description_box_height_pt(opts: ExportOptions) -> float:
    """Açıklama kutusu yüksekliği (pt) - satır sayısına göre."""
    if not opts.include_description:
        return 0.0
    col_count = max(1, min(3, opts.description_column_count or 1))
    texts_raw = opts.description_texts or []
    if col_count == 1 and not texts_raw and opts.test_description:
        lines_per_col = [len(_html_to_lines(opts.test_description or ""))]
    else:
        texts_in = texts_raw[:col_count] if texts_raw else [""]
        while len(texts_in) < col_count:
            texts_in.append("")
        lines_per_col = [len(_html_to_lines(t or "")) for t in texts_in]
    max_lines = max(lines_per_col) if lines_per_col else 1
    if max_lines < 1:
        max_lines = 1
    line_h = 10.0  # 8pt font için uyumlu satır aralığı
    return _DESC_BOX_PAD_V_PT * 2 + max_lines * line_h


def _draw_description_box(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    banner_bottom_y: float,
    opts: ExportOptions,
    *,
    banner_gap_pt: float = 2.0,
) -> float:
    """Banner altında Açıklama kutusu. Yükseklik satır sayısına göre, sütunlar eşit bölünür."""
    if not opts.include_description:
        return banner_bottom_y
    col_count = max(1, min(3, opts.description_column_count or 1))
    texts_raw = opts.description_texts or []
    if col_count == 1 and not texts_raw and opts.test_description:
        lines_per_col: List[List[str]] = [_html_to_lines(opts.test_description or "")]
    else:
        texts_in = (texts_raw[:col_count] if texts_raw else [""])
        while len(texts_in) < col_count:
            texts_in.append("")
        lines_per_col = [_html_to_lines(t or "") for t in texts_in]
    for i in range(len(lines_per_col)):
        if not lines_per_col[i]:
            lines_per_col[i] = [""]
    max_lines = max(len(ll) for ll in lines_per_col)
    line_h = 10.0  # 8pt font için uyumlu
    pad_top = _DESC_BOX_PAD_V_PT
    pad_bottom = _DESC_BOX_PAD_V_PT
    box_h = pad_top + max_lines * line_h + pad_bottom
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    theme = _hex_to_rgb01(opts.theme_color)
    r = 6.0
    content_w = page_w - ml - mr
    box_y = banner_bottom_y - banner_gap_pt - box_h
    col_w = content_w / col_count
    c.saveState()
    c.setLineWidth(1.0)
    c.setStrokeColorRGB(*theme)
    c.setFillColorRGB(1, 1, 1)
    k = 0.5522847498
    p = pathobject.PDFPathObject()
    p.moveTo(ml + r, box_y)
    p.lineTo(ml + content_w - r, box_y)
    p.curveTo(ml + content_w - r * k, box_y, ml + content_w, box_y + r * (1 - k), ml + content_w, box_y + r)
    p.lineTo(ml + content_w, box_y + box_h)
    p.lineTo(ml, box_y + box_h)
    p.lineTo(ml, box_y + r)
    p.curveTo(ml, box_y + r * k, ml + r * k, box_y, ml + r, box_y)
    p.close()
    c.drawPath(p, stroke=1, fill=1)
    utf = _register_unicode_font()
    pad_x = 6.0
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.setFont(utf, 8)
    try:
        from reportlab.pdfbase.pdfmetrics import getFont
        font_obj = getFont(utf)
        ascent = float(getattr(getattr(font_obj, "face", None), "ascent", 800))
        descent = float(getattr(getattr(font_obj, "face", None), "descent", -200))
        text_offset = (ascent + descent) / 2000.0 * 8.0
    except Exception:
        text_offset = 3.0
    for col_idx in range(col_count):
        x_left = ml + col_idx * col_w
        lines = lines_per_col[col_idx]
        c.saveState()
        clip_p = pathobject.PDFPathObject()
        clip_p.rect(x_left + pad_x, box_y, col_w - 2 * pad_x, box_h)
        c.clipPath(clip_p, stroke=0, fill=0)
        for line_idx, line_txt in enumerate(lines):
            y_line = box_y + box_h - pad_top - (line_idx + 0.5) * line_h - text_offset
            txt = (line_txt or "").strip()[:120]
            if not txt:
                continue
            if col_count == 1 and col_idx == 0:
                if line_idx == 0:
                    c.drawString(ml + pad_x, y_line, "AÇIKLAMA")
                    c.drawString(ml + pad_x + 55.0, y_line, txt)
                else:
                    c.drawString(ml + pad_x + 55.0, y_line, txt)
            else:
                c.drawString(x_left + pad_x, y_line, txt)
        c.restoreState()
    if (
        col_count > 1
        and bool(getattr(opts, "description_column_dividers", False))
    ):
        c.saveState()
        c.setStrokeColorRGB(*theme)
        c.setLineWidth(0.55)
        y_bot = box_y
        y_top = box_y + box_h
        for b in range(1, col_count):
            x_div = ml + b * col_w
            c.line(x_div, y_bot, x_div, y_top)
        c.restoreState()
    c.restoreState()
    return box_y - 6.0


def _draw_header_style3_other_pages(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
) -> float:
    """Yazılı: ince üst çizgi. Test/deneme: her sayfada aynı 3’lü tema bandı (açıklama kutusu yok)."""
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)
    written = bool(getattr(opts, "written_paper_header", False))
    if not written:
        inner_box_y, gap = _draw_other_page_test_banner(c, page_w, page_h, opts)
        return inner_box_y - gap
    line_y = page_h - mt - _OTHER_PAGES_TOP_RULE_DOWN_PT
    c.saveState()
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
    c.line(ml, line_y, page_w - mr, line_y)
    c.restoreState()
    return page_h - mt - _OTHER_PAGES_HEADER_H_PT - _OTHER_PAGES_HEADER_GAP_PT


def _draw_header_style3(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
    is_first_page: bool = True,
) -> float:
    """Style3 header - sayfa numarasına göre ilk/diğer stil."""
    if is_first_page:
        return _draw_header_style3_first_page(c, page_w, page_h, opts)
    return _draw_header_style3_other_pages(c, page_w, page_h, opts)


def _draw_written_paper_header(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
) -> float:
    """
    Yazılı sınav başlığı: ortada 1–2 satır başlık; kısa boşluk; sol ADI SOYADI / NUMARA
    çizgileri etiketin sağında; kitapçık harfi sayfa ortasında; sağda PUAN + kutu (blok ortasında).
    Blok altında tam genişlikte çizgi.
    """
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)

    utf = _register_unicode_font()
    bold_name = f"{utf}-Bold" if f"{utf}-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"

    title_lines = _written_title_lines_resolved(opts)
    title_line_h = 11.0
    y_line1 = page_h - mt - title_line_h
    c.saveState()
    c.setFont(bold_name, 10)
    c.setFillColorRGB(0, 0, 0)
    for ti, ln in enumerate(title_lines):
        c.drawCentredString(page_w / 2.0, y_line1 - 2 - ti * title_line_h, (ln or "")[:220])
    c.restoreState()
    title_h = title_line_h * float(len(title_lines))

    y_fields = page_h - mt - title_h - _WRITTEN_TITLE_TO_FIELDS_GAP_PT

    cx = page_w / 2.0
    x_left = ml

    fields = _normalize_written_field_lines(opts)
    n_ad, n_num, n_sin, block_body = _written_header_body_block_pt(opts, fields)

    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)

    adi_lbl = _written_field_label_pdf_left(opts, "ad_soyad")
    num_lbl = _written_field_label_pdf_left(opts, "numara")
    sin_lbl = _written_field_label_pdf_left(opts, "sinif")
    c.setFont(bold_name, 8)
    w_adi = float(stringWidth(adi_lbl, bold_name, 8))
    w_num = float(stringWidth(num_lbl, bold_name, 8))
    w_sin = float(stringWidth(sin_lbl, bold_name, 8))
    w_lbl_slot = max(w_adi, w_num, w_sin)
    x_lbl_right = x_left + w_lbl_slot
    x_line0 = x_lbl_right + _WRITTEN_LABEL_TO_LINE_GAP_PT
    x_line_end = min(x_line0 + _WRITTEN_FORM_LINE_LEN_PT, cx - _WRITTEN_CENTER_LETTER_MARGIN_PT)

    yr = y_fields
    if n_ad > 0:
        for j in range(n_ad):
            yrow = yr - j * _WRITTEN_LINE_ROW_PT
            if j == 0:
                c.setFont(bold_name, 8)
                c.drawRightString(x_lbl_right, yrow, adi_lbl)
            c.setFont(utf, 8)
            c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
            _, desc = getAscentDescent(utf, 8)
            c.line(x_line0, yrow + float(desc) + 1.0, x_line_end, yrow + float(desc) + 1.0)
        yr -= n_ad * _WRITTEN_LINE_ROW_PT
        if n_num or n_sin:
            yr -= _WRITTEN_ROW_AFTER_ADI_PT
    if n_num > 0:
        y_num = yr
        for j in range(n_num):
            yrow = y_num - j * _WRITTEN_LINE_ROW_PT
            if j == 0:
                c.setFont(bold_name, 8)
                c.drawRightString(x_lbl_right, yrow, num_lbl)
            c.setFont(utf, 8)
            c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
            _, desc = getAscentDescent(utf, 8)
            c.line(x_line0, yrow + float(desc) + 1.0, x_line_end, yrow + float(desc) + 1.0)
        yr -= n_num * _WRITTEN_LINE_ROW_PT
        if n_sin:
            yr -= _WRITTEN_ROW_AFTER_ADI_PT
    if n_sin > 0:
        y_sin = yr
        for j in range(n_sin):
            yrow = y_sin - j * _WRITTEN_LINE_ROW_PT
            if j == 0:
                c.setFont(bold_name, 8)
                c.drawRightString(x_lbl_right, yrow, sin_lbl)
            c.setFont(utf, 8)
            c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
            _, desc = getAscentDescent(utf, 8)
            c.line(x_line0, yrow + float(desc) + 1.0, x_line_end, yrow + float(desc) + 1.0)

    y_mid = y_fields - block_body / 2.0

    booklet = _written_booklet_letter(opts)
    if booklet:
        c.setFont(bold_name, _WRITTEN_BOOKLET_FONT_PT)
        _, bd = getAscentDescent(bold_name, _WRITTEN_BOOKLET_FONT_PT)
        c.drawCentredString(cx, y_mid + float(bd) * 0.25, booklet)

    y_rule = page_h - mt - written_paper_rule_down_from_inner_top_pt(opts)

    if not _written_field_hidden(opts, "puan"):
        box_w = _WRITTEN_PUAN_BOX_W_PT
        box_h = _WRITTEN_PUAN_BOX_H_PT
        box_left = page_w - mr - box_w
        box_bottom = y_mid - box_h / 2.0

        c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
        c.roundRect(
            box_left,
            box_bottom,
            box_w,
            box_h,
            _WRITTEN_PUAN_BOX_ROUND_R_PT,
            stroke=1,
            fill=0,
        )

        c.setFont(bold_name, 8)
        puan_y = box_bottom + box_h + _WRITTEN_LABEL_TO_LINE_GAP_PT
        c.drawCentredString(
            box_left + box_w / 2.0, puan_y, _written_field_label_pdf_puan(opts)[:40]
        )

    c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
    c.setStrokeColorRGB(0, 0, 0)
    c.line(ml, y_rule, page_w - mr, y_rule)

    return y_rule - _DIVIDER_LINE_WIDTH_PT / 2.0 - _WRITTEN_RULE_TO_CONTENT_GAP_PT


def _draw_written_teacher_signatures_right_column(
    c: canvas.Canvas,
    _y_top: float,
    y_bottom: float,
    x0: float,
    block_w: float,
    teachers: List[Dict],
    utf: str,
    bold_name: str,
) -> None:
    """
    Yazılı kağıdı son sayfa sağ sütun: Başarılar + ADI SOYADI | İMZA başlıkları,
    her öğretmen için solda ad-soyad (ve unvan), sağda düz imza çizgisi.

    Dikeyde sütunun altına sabitlenir (footer üstü); sol sütundaki soru yüksekliğine göre
    ortalanmaz. _y_top şimdilik API uyumu için (gelecekte tavan olarak kullanılabilir).
    """
    inner_l = x0 + 4.0
    inner_r = x0 + block_w - 4.0
    mid_split = inner_l + (inner_r - inner_l) * 0.42
    sig_l = mid_split + 6.0
    sig_r = inner_r - 1.0

    rows: List[Tuple[str, str, float]] = []
    for t in teachers:
        name = (t.get("name") or "").strip() or ""
        title = (t.get("title") or "").strip() or ""
        row_h = 20.0 if title else 14.0
        rows.append((name, title, row_h))

    if not rows:
        return

    # Alttan yukarı: blok footer üstüne sabit (sağ sütunun altı); y_top = üst tavan (taşma önleme)
    y_last_name = y_bottom + 14.0
    extra = sum(rows[i][2] + 5.0 for i in range(1, len(rows)))
    y_first_teacher = y_last_name + extra
    # Dikey: Başarılar → başlık satırı (18) + çizgi (5) → öğretmen (12) = 35 pt
    y = y_first_teacher + 35.0

    c.setFillColorRGB(0, 0, 0)

    c.setFont(bold_name, 11)
    c.drawCentredString((inner_l + inner_r) / 2.0, y, "BAŞARILAR")
    y -= 18.0

    c.setFont(bold_name, 7)
    name_hdr_cx = (inner_l + mid_split) / 2.0
    sig_hdr_cx = (sig_l + sig_r) / 2.0
    c.drawCentredString(name_hdr_cx, y, "ADI SOYADI")
    c.drawCentredString(sig_hdr_cx, y, "İMZA")

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
    header_line_y = y - 5.0
    c.line(inner_l, header_line_y, inner_r, header_line_y)
    y = header_line_y - 12.0

    for name, title, row_h in rows:
        c.setFont(bold_name, 7)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(inner_l, y, (name or "—")[:32])

        if title:
            c.setFont(utf, 6)
            c.setFillColorRGB(0.35, 0.35, 0.35)
            c.drawString(inner_l, y - 8.0, title[:38])
            c.setFillColorRGB(0, 0, 0)
            _, desc_t = getAscentDescent(utf, 6)
            line_y = (y - 8.0) + float(desc_t)
        else:
            _, desc_n = getAscentDescent(bold_name, 7)
            line_y = y + float(desc_n)

        c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
        c.line(sig_l, line_y, sig_r, line_y)

        y -= row_h + 5.0


def _written_signature_upper(s: str) -> str:
    return (s or "").strip().upper()


def _pack_teacher_names_into_rows(
    names: List[str],
    content_w: float,
    name_fs: float,
    font_bold: str,
    gap_x: float,
    min_cell: float,
    max_cell: float,
) -> List[List[Tuple[str, float]]]:
    """Yan yana satırlar; sığmayınca yeni satır (flex-wrap benzeri)."""
    rows: List[List[Tuple[str, float]]] = []
    if not names:
        return rows
    row: List[Tuple[str, float]] = []
    row_w = 0.0
    for name in names:
        tw = float(stringWidth(name, font_bold, name_fs))
        cell_w = max(min_cell, min(max_cell, tw + 14.0))
        need = cell_w if not row else gap_x + cell_w
        if row and row_w + need > content_w + 0.5:
            rows.append(row)
            row = []
            row_w = 0.0
        row.append((name, cell_w))
        row_w += need
    if row:
        rows.append(row)
    return rows


def _draw_written_last_page_signature_block(
    c: canvas.Canvas,
    page_w: float,
    y_top: float,
    y_bottom: float,
    opts: ExportOptions,
) -> None:
    """
    Yazılı kağıdı son soru sayfası: tam genişlikte imza alanı.
    Üstte 'Hazırlayan Öğretmenler', öğretmen adları yan yana satır kırarak (branş yok),
    altta sağda Okul Müdürü + ad soyad + İmza.
    y_top: imza bandının üst sınırı (sorulara yakın, büyük y); y_bottom: alt sınır (küçük y).
    """
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    content_w = page_w - ml - mr
    teachers = getattr(opts, "teacher_names", None) or []
    names: List[str] = []
    for t in teachers:
        if not isinstance(t, dict):
            continue
        n = (t.get("name") or "").strip()
        if n:
            names.append(_written_signature_upper(n))
    principal = _written_signature_upper(
        str(getattr(opts, "principal_name", None) or "")
    )
    if not names and not principal:
        return

    utf = _register_unicode_font()
    bold = (
        f"{utf}-Bold"
        if f"{utf}-Bold" in pdfmetrics.getRegisteredFontNames()
        else "Helvetica-Bold"
    )

    title_fs = 10.0
    name_fs = 8.0
    label_fs = 7.0
    role_fs = 9.0
    gap_x = 9.0
    min_cell = 68.0
    max_cell = 132.0
    row_gap = 10.0
    sig_line_h = 14.0
    title_gap = 10.0
    pr_block_w = 128.0

    rows = _pack_teacher_names_into_rows(
        names, content_w, name_fs, bold, gap_x, min_cell, max_cell
    )

    def _cell_block_h() -> float:
        return name_fs + 5.0 + label_fs + sig_line_h + 6.0

    def _teach_h() -> float:
        if not rows:
            return 0.0
        cb = _cell_block_h()
        return title_fs + 6.0 + title_gap + len(rows) * cb + (len(rows) - 1) * row_gap

    def _pr_h() -> float:
        if not principal:
            return 0.0
        return role_fs + 8.0 + name_fs + 6.0 + label_fs + sig_line_h + 10.0

    gap_mid = 16.0 if (rows and principal) else 0.0
    total_h = _teach_h() + gap_mid + _pr_h()

    avail = max(0.0, y_top - y_bottom)
    if total_h > avail > 1.0:
        sc = min(1.0, (avail / total_h) * 0.96)
        title_fs = max(8.0, title_fs * sc)
        name_fs = max(6.0, name_fs * sc)
        label_fs = max(5.5, label_fs * sc)
        role_fs = max(7.0, role_fs * sc)
        row_gap *= sc
        gap_x *= sc
        gap_mid *= sc
        rows = _pack_teacher_names_into_rows(
            names, content_w, name_fs, bold, gap_x, min_cell * sc, max_cell
        )
        total_h = _teach_h() + gap_mid + _pr_h()

    # Yukarıdan aşağı: y azalır
    y = y_top - 8.0

    if rows:
        c.setFillColorRGB(0, 0, 0)
        c.setFont(bold, title_fs)
        asc_t, des_t = getAscentDescent(bold, title_fs)
        c.drawCentredString(ml + content_w / 2.0, y, "HAZIRLAYAN ÖĞRETMENLER")
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.55)
        c.line(ml, y - asc_t - 3.0, page_w - mr, y - asc_t - 3.0)
        y = y - asc_t - title_gap - 4.0
        cb = _cell_block_h()

        for row in rows:
            total_rw = sum(w for _, w in row) + gap_x * (len(row) - 1)
            x_start = ml + max(0.0, (content_w - total_rw) / 2.0)
            x_cur = x_start
            base_y = y
            for name, cell_w in row:
                tw = float(stringWidth(name, bold, name_fs))
                c.setFont(bold, name_fs)
                asc_n, des_n = getAscentDescent(bold, name_fs)
                nx = x_cur + max(0.0, (cell_w - tw) / 2.0)
                c.drawString(nx, base_y, name[:44])
                c.setFont(utf, label_fs)
                asc_l, des_l = getAscentDescent(utf, label_fs)
                lab_y = base_y - asc_n + des_n - 4.0
                c.drawCentredString(x_cur + cell_w / 2.0, lab_y, "İmza")
                sig_y = lab_y - asc_l + des_l - 5.0
                c.setStrokeColorRGB(0, 0, 0)
                c.setLineWidth(0.4)
                c.line(x_cur + 3.0, sig_y, x_cur + cell_w - 3.0, sig_y)
                x_cur += cell_w + gap_x
            y = base_y - cb - row_gap

    if principal:
        y -= gap_mid if rows else 0.0
        x_r = page_w - mr
        x_l_pr = x_r - pr_block_w
        c.setFillColorRGB(0, 0, 0)
        c.setFont(bold, role_fs)
        asc_r, des_r = getAscentDescent(bold, role_fs)
        c.drawRightString(x_r, y, "OKUL MÜDÜRÜ")
        y2 = y - asc_r + des_r - 8.0
        c.setFont(bold, name_fs)
        asc_n, des_n = getAscentDescent(bold, name_fs)
        c.drawRightString(x_r, y2, principal[:48])
        y3 = y2 - asc_n + des_n - 6.0
        c.setFont(utf, label_fs)
        asc_l, des_l = getAscentDescent(utf, label_fs)
        c.drawRightString(x_r, y3, "İmza")
        line_y = y3 - asc_l + des_l - 4.0
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.45)
        c.line(x_l_pr, line_y, x_r, line_y)


def _draw_teacher_signatures_block(
    c: canvas.Canvas,
    page_w: float,
    y_top: float,
    y_bottom: float,
    opts: ExportOptions,
    col_w: Optional[float] = None,
    col_gap: Optional[float] = None,
    cols: Optional[int] = None,
) -> None:
    """
    Öğretmen adları ve imza satırları.
    col_w, col_gap, cols verilirse: sadece son sayfanın SAĞ SÜTUNUNUN en altına çizilir (sütuna sığacak font).
    Verilmezse: eski davranış (tüm genişlik).
    Yazılı kağıdı (written_paper_header): sağ sütunda Başarılar + ADI SOYADI / İMZA + çizgili imza alanı.
    """
    teachers = getattr(opts, "teacher_names", None) or []
    teachers = [t for t in teachers if isinstance(t, dict)]
    if not teachers:
        return

    ml = mm_to_pt(opts.margin_left_mm)
    utf = _register_unicode_font()
    bold_name = f"{utf}-Bold" if f"{utf}-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"

    # Sağ sütun içinde mi çizeceğiz?
    use_right_column = (
        col_w is not None and col_gap is not None and cols is not None and cols >= 1
    )
    if use_right_column:
        x0 = ml + (cols - 1) * (col_w + col_gap)
        block_w = max(40.0, col_w - 12.0)  # sütun genişliğine sığ
        if getattr(opts, "written_paper_header", False):
            _draw_written_last_page_signature_block(
                c, page_w, y_top, y_bottom, opts
            )
            return
        name_pt = 7
        title_pt = 6
        name_h = 7.0
        title_h = 6.0
        line_h = 10.0
        block_h = name_h + title_h + line_h + 4.0
        block_gap = 6.0
    else:
        x0 = ml + 8.0
        block_w = 80.0
        name_pt = 9
        title_pt = 8
        name_h = 10.0
        title_h = 8.0
        block_h = name_h + title_h + 14.0 + 8.0
        block_gap = 6.0

    n_blocks = len(teachers)
    if use_right_column:
        # Sağ sütunda alt alta diz (yaprak test / yazılı olmayan)
        start_y = y_top - 8.0
    else:
        content_w = page_w - ml - mm_to_pt(opts.margin_right_mm)
        n_cols = max(1, int(content_w / (block_w + 16.0)))
        start_y = y_top - 12.0

    for idx, t in enumerate(teachers):
        name = (t.get("name") or "").strip() or ""
        title = (t.get("title") or "").strip() or ""

        if use_right_column:
            row = idx
            x = x0 + 6.0
            y = start_y - row * (block_h + block_gap)
        else:
            col = idx % n_cols
            row = idx // n_cols
            x = x0 + col * (block_w + 16.0)
            y = start_y - row * (block_h + 6.0)

        if y < y_bottom:
            break

        c.setFont(bold_name, name_pt)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(x, y, name[:35])
        c.setFont(utf, title_pt)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.drawString(x, y - name_h, title[:35])

        line_y = y - name_h - 4.0
        c.setStrokeColorRGB(0.5, 0.5, 0.5)
        c.setLineWidth(0.4)
        c.line(x, line_y, x + block_w, line_y)


def _column_divider_line_geometry(
    page_w: float,
    page_h: float,
    opts: ExportOptions,
    is_first_page: bool,
) -> Tuple[List[float], float]:
    """Sütun ayırıcı dikey çizgilerin x listesi ve üst uç y (PDF, y yukarı). cols<2 ise xs=[]."""
    cols = max(1, min(6, opts.columns))
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)
    col_gap = mm_to_pt(opts.column_gap_mm)
    content_w = page_w - ml - mr
    col_w = (content_w - (cols - 1) * col_gap) / cols if cols > 1 else content_w
    xs = [
        ml + (i + 1) * col_w + (i + 0.5) * col_gap
        for i in range(max(0, cols - 1))
    ]
    written = bool(getattr(opts, "written_paper_header", False))
    if is_first_page:
        if written:
            y_start = page_h - mt - written_paper_rule_down_from_inner_top_pt(opts)
        elif opts.include_description:
            box_h = _get_description_box_height_pt(opts)
            total_h = 22.0 + 2.0 + box_h
            y_start = page_h - mt - total_h
        else:
            y_start = page_h - mt - 22.0
    else:
        if written:
            y_start = page_h - mt - _OTHER_PAGES_TOP_RULE_DOWN_PT
        else:
            y_start = page_h - mt - _FIRST_PAGE_BANNER_H_PT
    return xs, y_start


def _draw_center_line_text(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
    *,
    footer_top: float,
    is_first_page: bool,
) -> None:
    """Sütun ayırıcı çizgilerinin ortasında dikey metin (beyaz zemin, çizgiyi kapatır)."""
    if bool(getattr(opts, "written_paper_header", False)):
        return
    if not bool(getattr(opts, "center_line_enabled", False)):
        return
    txt = (getattr(opts, "center_line_text", "") or "").strip()
    if not txt:
        return
    xs, y_start = _column_divider_line_geometry(page_w, page_h, opts, is_first_page)
    if not xs:
        return
    cl_hex = (getattr(opts, "center_line_color", "") or "").strip()
    rgb = _hex_to_rgb01(cl_hex if cl_hex else opts.theme_color)
    font_size = 9.0
    bold = bool(getattr(opts, "center_line_bold", False))
    italic = bool(getattr(opts, "center_line_italic", False))
    utf = _register_unicode_font()
    if utf != "Helvetica":
        if bold and italic and f"{utf}-BoldOblique" in pdfmetrics.getRegisteredFontNames():
            font_name = f"{utf}-BoldOblique"
        elif bold and f"{utf}-Bold" in pdfmetrics.getRegisteredFontNames():
            font_name = f"{utf}-Bold"
        elif italic and f"{utf}-Oblique" in pdfmetrics.getRegisteredFontNames():
            font_name = f"{utf}-Oblique"
        else:
            font_name = utf
    elif bold and italic:
        font_name = "Helvetica-BoldOblique"
    elif bold:
        font_name = "Helvetica-Bold"
    elif italic:
        font_name = "Helvetica-Oblique"
    else:
        font_name = "Helvetica"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        font_name = "Helvetica-Bold" if bold else "Helvetica"

    try:
        asc, des = getAscentDescent(font_name, font_size)
    except Exception:
        asc, des = 7.2, -2.2
    band_h = asc - des
    txt_w = stringWidth(txt, font_name, font_size)
    direction = (getattr(opts, "center_line_text_direction", "up") or "up").lower().strip()
    rotation = 90 if direction == "up" else -90
    page_y_center = (y_start + footer_top) / 2.0
    baseline_y = -(asc + des) / 2.0

    for x_line_center in xs:
        c.saveState()
        try:
            c.setFont(font_name, font_size)
            c.translate(x_line_center, page_y_center)
            c.rotate(rotation)
            pad = 2.0
            c.setFillColorRGB(1, 1, 1)
            c.rect(
                -txt_w / 2.0 - pad,
                -band_h / 2.0 - pad,
                txt_w + 2 * pad,
                band_h + 2 * pad,
                fill=1,
                stroke=0,
            )
            c.setFillColorRGB(*rgb)
            c.drawCentredString(0, baseline_y, txt)
        finally:
            c.restoreState()


def _draw_column_divider(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
    footer_top: float,
    is_first_page: bool = True,
) -> None:
    """Sütun ayırıcı çizgiler - üst banner alt çizgisinden footer üst çizgisine kadar (2–6 sütun)."""
    cols = max(1, min(6, opts.columns))
    if cols < 2:
        return
    written = bool(getattr(opts, "written_paper_header", False))
    theme = _hex_to_rgb01(opts.theme_color)
    line_positions, y_start = _column_divider_line_geometry(page_w, page_h, opts, is_first_page)
    c.saveState()
    if written:
        c.setStrokeColorRGB(0, 0, 0)
    else:
        c.setStrokeColorRGB(*theme)
    c.setLineWidth(_DIVIDER_LINE_WIDTH_PT)
    for line_x in line_positions:
        c.line(line_x, y_start, line_x, footer_top)
    c.restoreState()


def _draw_watermark(
    c: canvas.Canvas, page_w: float, page_h: float, opts: ExportOptions
) -> None:
    """Filigran çiz (metin veya görsel) - sayfa ortasında, tüm içeriğin üstünde."""
    if not getattr(opts, "watermark_enabled", False):
        return
    mode = (getattr(opts, "watermark_mode", "text") or "text").strip().lower()
    try:
        if mode == "image":
            img_b64 = (getattr(opts, "watermark_image_base64", "") or "").strip()
            if not img_b64:
                return
            raw = base64.b64decode(img_b64)
            op_pct = float(getattr(opts, "watermark_image_opacity_pct", 15.0))
            op = max(0.0, min(1.0, op_pct / 100.0))
            size_pct = float(getattr(opts, "watermark_image_size_pct", 50.0))
            size_factor = max(0.05, min(2.0, size_pct / 100.0))
            target_w = page_w * 0.70 * size_factor
            img = Image.open(io.BytesIO(raw))
            img = img.convert("RGBA")
            r, g, b, a = img.split()
            a = a.point(lambda v: int(v * op))
            img = Image.merge("RGBA", (r, g, b, a))
            ratio = img.height / float(img.width) if img.width else 1.0
            target_h = target_w * ratio
            x = (page_w - target_w) / 2.0
            y = (page_h - target_h) / 2.0
            c.saveState()
            c.drawImage(
                ImageReader(img),
                x, y,
                width=target_w, height=target_h,
                mask="auto", preserveAspectRatio=True, anchor="c"
            )
            c.restoreState()
            return
        txt = (getattr(opts, "watermark_text", "") or "").strip()
        if not txt:
            return
        op_pct = float(getattr(opts, "watermark_text_opacity_pct", 20.0))
        alpha = max(0.0, min(1.0, op_pct / 100.0))
        size_pct = float(getattr(opts, "watermark_text_size_pct", 90.0))
        size_factor = max(0.10, min(2.50, size_pct / 100.0))
        ang = float(getattr(opts, "watermark_text_angle_deg", 45.0))  # ReportLab: pozitif = CCW
        col = getattr(opts, "watermark_text_color", "#000000")
        theme = _hex_to_rgb01(col)
        base = min(page_w, page_h) * 0.12
        font_size = max(10.0, base * size_factor)
        utf_font = _register_unicode_font()
        font_name = (
            f"{utf_font}-Bold"
            if f"{utf_font}-Bold" in pdfmetrics.getRegisteredFontNames()
            else "Helvetica-Bold"
        )
        c.saveState()
        try:
            if hasattr(c, "setFillAlpha"):
                c.setFillAlpha(alpha)
            c.translate(page_w / 2.0, page_h / 2.0)
            c.rotate(ang)
            c.setFillColorRGB(*theme)
            c.setFont(font_name, font_size)
            c.drawCentredString(0, 0, txt)
        except Exception:
            pass
        finally:
            c.restoreState()
    except Exception:
        pass


def _compute_layout_entries_flexible(
    question_data: List[Dict],
    opts: ExportOptions,
    page_w: float,
    page_h: float,
    ml: float,
    mr: float,
    mb: float,
    col_gap: float,
    col_w: float,
    cols: int,
) -> List[Dict]:
    """
    Flexible layout: pack as many questions per column as fit.
    Column-bottom: boşluk footer üst çizgisine göre ölçülür (alt çizgi değil).
    Uses central layout geometry - contentTop matches actual header/banner heights.
    """
    geom = _compute_layout_geometry(opts)
    content_floor = geom["content_bottom"]
    content_top_first = geom["content_top_first"]
    content_top_other = geom["content_top_other"]

    min_gap_pt = mm_to_pt(opts.question_gap_min_mm)
    preferred_gap_pt = mm_to_pt(opts.question_gap_mm)
    column_bottom_min_pt = mm_to_pt(opts.column_bottom_min_mm)

    def col_top_for_page(_p: int) -> float:
        return content_top_first if _p == 0 else content_top_other

    def get_col_x(c: int) -> float:
        col_x_list = geom["column_x"]
        return col_x_list[c] if c < len(col_x_list) else ml + c * (col_w + col_gap)

    result: List[Dict] = []
    page_num = 1
    col_idx = 0
    col_top = col_top_for_page(0)
    col_buffer: List[Dict] = []
    available_height = col_top - content_floor

    def flush_column(applied_gaps: List[float]) -> None:
        nonlocal col_top, available_height
        y = col_top
        for j, qu in enumerate(col_buffer):
            block_h = qu["block_h"]
            gap = applied_gaps[j] if j < len(applied_gaps) else preferred_gap_pt
            x_pt = get_col_x(col_idx)
            entry = {
                **{k: v for k, v in qu.items() if k not in ("block_h", "preferred_gap_pt", "min_gap_pt")},
                "page_num": page_num,
                "col_idx": col_idx,
                "x_pt": x_pt,
                "y_top_pt": y,
                "block_h": block_h,
                "applied_gap_pt": gap,
            }
            result.append(entry)
            if DEBUG_LAYOUT:
                print(
                    f"[LAYOUT] placed q{entry.get('idx','?')} page={page_num} col={col_idx} "
                    f"y_top={y:.0f} x={x_pt:.0f} block_h={block_h:.0f}"
                )
            y -= block_h + gap
        col_buffer.clear()

    def next_column() -> None:
        nonlocal col_idx, page_num, col_top, available_height
        col_idx += 1
        if col_idx >= cols:
            page_num += 1
            col_idx = 0
        col_top = col_top_for_page(page_num - 1)
        available_height = col_top - content_floor

    def _compute_applied_for_buffer(buf: List[Dict]) -> List[float]:
        """Mevcut buffer için applied_gaps hesapla."""
        n_b = len(buf)
        if n_b == 0:
            return []
        total_b = sum(x["block_h"] for x in buf)
        gap_budget_b = available_height - total_b
        if n_b == 1:
            return [max(column_bottom_min_pt, gap_budget_b)]
        total_inter_b = sum(buf[j]["preferred_gap_pt"] for j in range(n_b - 1))
        if total_inter_b + column_bottom_min_pt <= gap_budget_b:
            bottom_b = gap_budget_b - total_inter_b
            return [buf[j]["preferred_gap_pt"] for j in range(n_b - 1)] + [bottom_b]
        rest_b = gap_budget_b - column_bottom_min_pt
        per_b = rest_b / (n_b - 1)
        applied_inter_b = [
            max(min_gap_pt, min(buf[j]["preferred_gap_pt"], per_b))
            for j in range(n_b - 1)
        ]
        bottom_b = gap_budget_b - sum(applied_inter_b)
        return applied_inter_b + [max(column_bottom_min_pt, bottom_b)]

    i = 0
    while i < len(question_data):
        q = question_data[i]
        block_h = q["block_h"]
        preferred = q.get("preferred_gap_pt", preferred_gap_pt)
        if col_buffer and q.get("section") and q["section"].get("start_new_page"):
            applied_force = _compute_applied_for_buffer(col_buffer)
            flush_column(applied_force)
            next_column()
        col_buffer.append({
            **q,
            "block_h": block_h,
            "preferred_gap_pt": preferred,
            "min_gap_pt": min_gap_pt,
        })

        n = len(col_buffer)
        total_block = sum(x["block_h"] for x in col_buffer)
        gap_budget = available_height - total_block
        gap_needed = (n - 1) * min_gap_pt + column_bottom_min_pt if n >= 1 else 0

        if DEBUG_LAYOUT:
            q_idx = col_buffer[-1].get("idx", i + 1)
            fit = gap_budget >= gap_needed
            reason = "fit" if fit else "overflow"
            print(
                f"[LAYOUT] q{q_idx} col={col_idx} page={page_num} n={n} {reason} "
                f"block_h={block_h:.1f} total_block={total_block:.1f} "
                f"available={available_height:.1f} gap_budget={gap_budget:.1f} "
                f"gap_needed={gap_needed:.1f} -> "
                f"{'stay' if fit else 'next_col/page'}"
            )

        if opts.auto_compact_spacing:
            if gap_budget >= gap_needed:
                if n == 1:
                    applied = [max(column_bottom_min_pt, gap_budget)]
                    i += 1
                    continue
                total_inter = sum(col_buffer[j]["preferred_gap_pt"] for j in range(n - 1))
                if total_inter + column_bottom_min_pt <= gap_budget:
                    bottom = gap_budget - total_inter
                    applied = [
                        col_buffer[j]["preferred_gap_pt"] for j in range(n - 1)
                    ] + [bottom]
                    i += 1
                    continue
                else:
                    if DEBUG_LAYOUT:
                        print(f"  -> OVERFLOW: preferred gap doesn't fit, move to next col")
                    col_buffer.pop()
                    if len(col_buffer) == 0:
                        next_column()
                        continue
                    n_prev = len(col_buffer)
                    total_prev = sum(x["block_h"] for x in col_buffer)
                    gap_budget_prev = available_height - total_prev
                    if n_prev == 1:
                        applied = [max(column_bottom_min_pt, gap_budget_prev)]
                    else:
                        total_inter_prev = sum(col_buffer[j]["preferred_gap_pt"] for j in range(n_prev - 1))
                        if total_inter_prev + column_bottom_min_pt <= gap_budget_prev:
                            bottom = gap_budget_prev - total_inter_prev
                            applied = [
                                col_buffer[j]["preferred_gap_pt"] for j in range(n_prev - 1)
                            ] + [bottom]
                        else:
                            rest = gap_budget_prev - column_bottom_min_pt
                            per = rest / (n_prev - 1)
                            applied_inter = [
                                max(min_gap_pt, min(col_buffer[j]["preferred_gap_pt"], per))
                                for j in range(n_prev - 1)
                            ]
                            bottom = gap_budget_prev - sum(applied_inter)
                            applied = applied_inter + [max(column_bottom_min_pt, bottom)]
                    flush_column(applied)
                    next_column()
                    continue
            elif n == 1:
                if DEBUG_LAYOUT:
                    print(f"  -> OVERFLOW single q: block_h={block_h:.1f} > available, next_col")
                applied = [max(column_bottom_min_pt, gap_budget)]
                flush_column(applied)
                next_column()
                i += 1
            else:
                col_buffer.pop()
                if DEBUG_LAYOUT:
                    print(f"  -> OVERFLOW n={n}: gap_budget={gap_budget:.1f} < gap_needed={gap_needed:.1f}, flush prev, next_col")
                if len(col_buffer) == 0:
                    next_column()
                    continue
                n_prev = len(col_buffer)
                total_prev = sum(x["block_h"] for x in col_buffer)
                gap_budget_prev = available_height - total_prev
                gap_needed_prev = (n_prev - 1) * min_gap_pt + column_bottom_min_pt
                if gap_budget_prev >= gap_needed_prev:
                    if n_prev == 1:
                        applied = [max(column_bottom_min_pt, gap_budget_prev)]
                    else:
                        total_inter = sum(col_buffer[j]["preferred_gap_pt"] for j in range(n_prev - 1))
                        if total_inter + column_bottom_min_pt <= gap_budget_prev:
                            bottom = gap_budget_prev - total_inter
                            applied = [
                                col_buffer[j]["preferred_gap_pt"] for j in range(n_prev - 1)
                            ] + [bottom]
                        else:
                            rest = gap_budget_prev - column_bottom_min_pt
                            per = rest / (n_prev - 1)
                            applied_inter = [
                                max(min_gap_pt, min(col_buffer[j]["preferred_gap_pt"], per))
                                for j in range(n_prev - 1)
                            ]
                            bottom = gap_budget_prev - sum(applied_inter)
                            applied = applied_inter + [max(column_bottom_min_pt, bottom)]
                    flush_column(applied)
                    next_column()
                else:
                    col_buffer.pop()
                    next_column()
        else:
            total_preferred = (
                total_block
                + sum(col_buffer[j].get("preferred_gap_pt", preferred_gap_pt) for j in range(n - 1))
                + column_bottom_min_pt
            ) if n >= 1 else total_block
            if total_preferred <= available_height:
                i += 1
                continue
            else:
                col_buffer.pop()
                if len(col_buffer) > 0:
                    n_prev = len(col_buffer)
                    gap_budget_prev = available_height - sum(x["block_h"] for x in col_buffer)
                    if n_prev == 1:
                        applied = [max(column_bottom_min_pt, gap_budget_prev)]
                    else:
                        inter_list = [x.get("preferred_gap_pt", preferred_gap_pt) for x in col_buffer[:-1]]
                        total_inter = sum(inter_list)
                        bottom = gap_budget_prev - total_inter
                        applied = inter_list + [max(column_bottom_min_pt, bottom)]
                    flush_column(applied)
                    next_column()
                else:
                    next_column()
                    i += 1

    if col_buffer:
        n = len(col_buffer)
        total_block = sum(x["block_h"] for x in col_buffer)
        gap_budget = available_height - total_block
        gap_needed = (n - 1) * min_gap_pt + column_bottom_min_pt if n >= 1 else 0
        if gap_budget >= gap_needed and opts.auto_compact_spacing:
            if n == 1:
                applied = [max(column_bottom_min_pt, gap_budget)]
            else:
                total_inter = sum(x.get("preferred_gap_pt", preferred_gap_pt) for x in col_buffer[:-1])
                if total_inter + column_bottom_min_pt <= gap_budget:
                    bottom = gap_budget - total_inter
                    applied = [
                        x.get("preferred_gap_pt", preferred_gap_pt) for x in col_buffer[:-1]
                    ] + [bottom]
                else:
                    rest = gap_budget - column_bottom_min_pt
                    per = rest / (n - 1)
                    applied_inter = [
                        max(min_gap_pt, min(x.get("preferred_gap_pt", preferred_gap_pt), per))
                        for x in col_buffer[:-1]
                    ]
                    bottom = gap_budget - sum(applied_inter)
                    applied = applied_inter + [max(column_bottom_min_pt, bottom)]
        else:
            if n == 1:
                applied = [max(column_bottom_min_pt, gap_budget)]
            else:
                inter_list = [x.get("preferred_gap_pt", preferred_gap_pt) for x in col_buffer[:-1]]
                total_inter = sum(inter_list)
                bottom = gap_budget - total_inter
                applied = inter_list + [max(column_bottom_min_pt, bottom)]
        flush_column(applied)

    return result


def _get_section_for_index(idx: int, sections: List[Dict]) -> Optional[Dict]:
    """Soru indeksi (0-based) bir bölümün başlangıcı mı? Eşleşen section döner."""
    for s in sections or []:
        if int(s.get("start_idx", -1)) == idx:
            return s
    return None


def _is_explanation_dict(q: Dict) -> bool:
    return str(q.get("content_type") or "question").strip().lower() == "explanation"


def _question_number_slot_width_pt_for_items(
    sorted_q: List[Dict],
    sections: Optional[List[Dict]],
) -> float:
    """Yalnızca numaralanan (question) öğelerin 'n.' genişliğinin maksimumu; bölüm reset dahil."""
    default_w = stringWidth("9.", _NUM_FONT, _NUM_FONT_SIZE)
    display_counter = 1
    max_w = default_w
    for pos, q in enumerate(sorted_q):
        sec = _get_section_for_index(pos, sections or [])
        if sec and sec.get("restart_numbering"):
            display_counter = 1
        if _is_explanation_dict(q):
            continue
        max_w = max(max_w, stringWidth(f"{display_counter}.", _NUM_FONT, _NUM_FONT_SIZE))
        display_counter += 1
    return max_w


def _apply_display_numbers_to_layout_entries(layout_entries: List[Dict]) -> None:
    display_counter = 1
    for entry in layout_entries:
        sec = entry.get("section")
        if sec and sec.get("restart_numbering"):
            display_counter = 1
        if str(entry.get("content_type") or "question").strip().lower() == "explanation":
            entry["display_number"] = None
        else:
            entry["display_number"] = display_counter
            display_counter += 1


def _display_numbers_for_sorted_question_count(n: int, sections: Optional[List[Dict]]) -> List[int]:
    nums: List[int] = []
    counter = 1
    for idx in range(n):
        sec = _get_section_for_index(idx, sections or [])
        if sec and sec.get("restart_numbering"):
            counter = 1
        nums.append(counter)
        counter += 1
    return nums


def _question_number_slot_width_pt(n: int, sections: Optional[List[Dict]]) -> float:
    """Sütunda numaralar dikey hizalı kalsın diye 1..n görünen numaraların max 'd.' genişliği."""
    nums = _display_numbers_for_sorted_question_count(n, sections)
    if not nums:
        return stringWidth("9.", _NUM_FONT, _NUM_FONT_SIZE)
    return max(stringWidth(f"{d}.", _NUM_FONT, _NUM_FONT_SIZE) for d in nums)


def _question_number_slot_width_from_layout_entries(layout_entries: List[Dict]) -> float:
    if not layout_entries:
        return stringWidth("9.", _NUM_FONT, _NUM_FONT_SIZE)
    m = 0.0
    for e in layout_entries:
        raw = e.get("display_number")
        if raw is None:
            continue
        d = int(raw)
        m = max(m, stringWidth(f"{d}.", _NUM_FONT, _NUM_FONT_SIZE))
    return m if m > 0 else stringWidth("9.", _NUM_FONT, _NUM_FONT_SIZE)


def _number_draw_left_pt(x_col: float, num_text: str, slot_w: float) -> float:
    """Numarayı slot içinde sağa yasla; kısa '2.' ile görsel arasında boşluk kalmaz."""
    tw = stringWidth(num_text, _NUM_FONT, _NUM_FONT_SIZE)
    return x_col + max(0.0, slot_w - tw)


_EXPL_CAP_FONT_PT = 9.0
_EXPL_CAP_PAD_PT = 2.0
_EXPL_CAP_GAP_PT = 5.0


def _expl_norm_align(v: Any) -> str:
    s = str(v or "left").strip().lower()
    return s if s in ("left", "center", "right") else "left"


def _expl_norm_placement(v: Any) -> str:
    s = str(v or "above").strip().lower()
    return s if s in ("above", "below", "left", "right") else "above"


def _expl_norm_side_flow(v: Any) -> str:
    s = str(v or "horizontal").strip().lower()
    return s if s in ("horizontal", "vertical_up") else "horizontal"


def _expl_lead_from_size(size: float) -> float:
    return max(size * 1.22, size + 1.0)


def _expl_resolve_font_name(utf: str, bold: bool, italic: bool) -> str:
    if utf == "Helvetica":
        if bold and italic:
            return "Helvetica-BoldOblique"
        if bold:
            return "Helvetica-Bold"
        if italic:
            return "Helvetica-Oblique"
        return "Helvetica"
    try:
        names = list(pdfmetrics.getRegisteredFontNames())
    except Exception:
        names = []
    if bold and italic and _UNICODE_BOLDITALIC_NAME and _UNICODE_BOLDITALIC_NAME in names:
        return _UNICODE_BOLDITALIC_NAME
    if bold and "UnicodeFont-Bold" in names:
        return "UnicodeFont-Bold"
    if italic and _UNICODE_ITALIC_NAME and _UNICODE_ITALIC_NAME in names:
        return _UNICODE_ITALIC_NAME
    return utf


def _expl_caption_color_rgb(hex_color: Any) -> Tuple[float, float, float]:
    h = str(hex_color or "").strip()
    if not h.startswith("#") or len(h) < 4:
        h = "#0f172a"
    return _hex_to_rgb01(h, (0.059, 0.09, 0.102))


def _expl_normalize_hex_for_preview(hex_color: Any) -> str:
    h = str(hex_color or "").strip()
    if len(h) == 7 and h.startswith("#"):
        return h
    return "#0f172a"


def _expl_truncate_string_to_width(s: str, font_name: str, font_size: float, max_w: float) -> str:
    s = s or ""
    if max_w <= 1.0:
        return ""
    while s:
        try:
            w = float(stringWidth(s, font_name, font_size))
        except Exception:
            w = len(s) * font_size * 0.48
        if w <= max_w:
            break
        s = s[:-1]
    return s


def _expl_fit_lines_to_box(
    lines: List[str],
    font_name: str,
    font_size: float,
    leading: float,
    max_h: float,
    max_line_w: float,
) -> List[str]:
    pad = _EXPL_CAP_PAD_PT * 2
    avail_h = max(leading, max_h - pad)
    max_lines = max(1, int(avail_h // leading))
    out: List[str] = []
    for line in lines:
        if len(out) >= max_lines:
            break
        cur = line if line is not None else ""
        cur = str(cur)
        while cur:
            try:
                sw = float(stringWidth(cur, font_name, font_size))
            except Exception:
                sw = len(cur) * font_size * 0.48
            if sw <= max_line_w:
                break
            cur = cur[:-1]
        out.append(cur)
    if not out:
        out = [""]
    return out[:max_lines]


def _expl_wrap_lines(text: str, font_name: str, font_size: float, max_w: float) -> List[str]:
    if max_w <= 2.0:
        return [t for t in (text or "").split("\n")] if text else []
    raw = (text or "").replace("\r\n", "\n")
    if not raw.strip():
        return []
    out: List[str] = []
    for para in raw.split("\n"):
        p = para.strip()
        if not p:
            out.append("")
            continue
        words = p.split()
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip() if cur else w
            try:
                tw = float(stringWidth(trial, font_name, font_size))
            except Exception:
                tw = len(trial) * font_size * 0.48
            if tw <= max_w:
                cur = trial
            else:
                if cur:
                    out.append(cur)
                cur = w
        if cur:
            out.append(cur)
    return out if out else [""]


def _expl_lines_max_width(lines: List[str], font_name: str, font_size: float) -> float:
    m = 1.0
    for line in lines:
        s = line if line else " "
        try:
            m = max(m, float(stringWidth(s, font_name, font_size)))
        except Exception:
            m = max(m, len(s) * font_size * 0.48)
    return m


def _expl_caption_block_height(num_lines: int, font_size: float, leading: float) -> float:
    n = max(int(num_lines), 1)
    return _EXPL_CAP_PAD_PT + max(font_size, n * leading) + _EXPL_CAP_PAD_PT


def _expl_one_char_side_pad_pt(font_name: str, font_size: float) -> float:
    """Yazı kadar kutu: sağ/sol iç boşluk ≈ bir karakter genişliği."""
    for ch in ("O", "M", "W", "İ", "ı"):
        try:
            return float(stringWidth(ch, font_name, font_size))
        except Exception:
            continue
    return max(2.0, font_size * 0.55)


def _expl_tight_box_side_inset_pt(font_name: str, font_size: float) -> float:
    """Sıkı kutu: dar sol/sağ iç boşluk (≈0.28 karakter, min 0.45 pt)."""
    one = _expl_one_char_side_pad_pt(font_name, font_size)
    return max(0.45, one * 0.28)


def _build_expl_caption_spec(q: Dict, inner_w: float, draw_w: float, draw_h: float) -> Optional[Dict[str, Any]]:
    if str(q.get("content_type") or "question").strip().lower() != "explanation":
        return None
    if not bool(q.get("explanation_caption_enabled")):
        return None
    raw = (q.get("explanation_caption_text") or "").strip()
    if not raw:
        return None
    align = _expl_norm_align(q.get("explanation_caption_align"))
    place = _expl_norm_placement(q.get("explanation_caption_placement"))
    side_flow = _expl_norm_side_flow(q.get("explanation_caption_side_flow"))
    bold = bool(q.get("explanation_caption_bold"))
    italic = bool(q.get("explanation_caption_italic"))
    color_hex = _expl_normalize_hex_for_preview(q.get("explanation_caption_color"))
    box_enabled = bool(q.get("explanation_caption_box_enabled"))
    box_tight = str(q.get("explanation_caption_box_width") or "full").strip().lower() == "tight"
    box_hex = str(q.get("explanation_caption_box_color") or "#f1f5f9").strip()
    if not box_hex.startswith("#") or len(box_hex) < 4:
        box_hex = "#f1f5f9"
    box_fill_rgb = _hex_to_rgb01(box_hex, (0.945, 0.961, 0.976))
    box_rounded = str(q.get("explanation_caption_box_corner") or "rounded").strip().lower() != "sharp"
    try:
        size = float(q.get("explanation_caption_font_pt") or _EXPL_CAP_FONT_PT)
    except (TypeError, ValueError):
        size = _EXPL_CAP_FONT_PT
    size = max(6.0, min(16.0, size))
    lead = _expl_lead_from_size(size)
    gap = _EXPL_CAP_GAP_PT
    utf = _register_unicode_font()
    font = _expl_resolve_font_name(utf, bold, italic)
    rgb = _expl_caption_color_rgb(color_hex)
    tw_box = max(20.0, inner_w - 2 * _EXPL_CAP_PAD_PT)
    line_max = max(8.0, tw_box - 2 * _EXPL_CAP_PAD_PT)

    def spec_base(
        lines: List[str],
        mode: str,
        block_h: float,
        caption_h: float,
        text_col_w: float = 0.0,
        *,
        side_vertical: bool = False,
        vertical_text: str = "",
    ) -> Dict[str, Any]:
        return {
            "mode": mode,
            "lines": lines,
            "font": font,
            "size": size,
            "leading": lead,
            "align": align,
            "block_h": float(block_h),
            "caption_h": float(caption_h),
            "text_col_w": float(text_col_w),
            "color_rgb": rgb,
            "color_hex": color_hex,
            "bold": bold,
            "italic": italic,
            "side_vertical": bool(side_vertical),
            "vertical_text": vertical_text or "",
            "box_enabled": box_enabled,
            "box_tight": box_tight,
            "box_fill_rgb": box_fill_rgb,
            "box_rounded": box_rounded,
            "box_hex": box_hex if box_enabled else "",
        }

    if place in ("above", "below"):
        lines = _expl_wrap_lines(raw, font, size, tw_box)
        lines = _expl_fit_lines_to_box(lines, font, size, lead, draw_h, line_max)
        n = max(len(lines), 1)
        ch = _expl_caption_block_height(n, size, lead)
        if place == "above":
            bh = ch + gap + draw_h
        else:
            bh = draw_h + gap + ch
        return spec_base(lines, place, bh, ch)

    if place == "left":
        max_side = max(50.0, inner_w * 0.44)
        wrap_w = max(10.0, max_side - 2 * _EXPL_CAP_PAD_PT)
        if side_flow == "vertical_up":
            one = " ".join((raw.replace("\r\n", "\n").replace("\n", " ").split()))
            vmax = max(8.0, draw_h - 2 * _EXPL_CAP_PAD_PT)
            vtext = _expl_truncate_string_to_width(one, font, size, vmax)
            text_w = min(max_side, size + 2 * _EXPL_CAP_PAD_PT + 1.0)
            need_v = text_w + gap + draw_w
            if need_v <= inner_w + 0.5 and vtext.strip():
                ch = max(draw_h, size + 2 * _EXPL_CAP_PAD_PT)
                bh = max(ch, draw_h)
                return spec_base([], "left_right", bh, ch, text_w, side_vertical=True, vertical_text=vtext)
        lines_side = _expl_wrap_lines(raw, font, size, wrap_w)
        lines_side = _expl_fit_lines_to_box(lines_side, font, size, lead, draw_h, wrap_w)
        text_w = min(max_side, _expl_lines_max_width(lines_side, font, size) + 2 * _EXPL_CAP_PAD_PT)
        need = text_w + gap + draw_w
        if need <= inner_w + 0.5:
            n = max(len(lines_side), 1)
            ch = _expl_caption_block_height(n, size, lead)
            bh = max(ch, draw_h)
            return spec_base(lines_side, "left_right", bh, ch, text_w)
        lines_full = _expl_wrap_lines(raw, font, size, tw_box)
        lines_full = _expl_fit_lines_to_box(lines_full, font, size, lead, draw_h, line_max)
        n = max(len(lines_full), 1)
        ch = _expl_caption_block_height(n, size, lead)
        bh = ch + gap + draw_h
        return spec_base(lines_full, "stacked_top", bh, ch)

    if place == "right":
        max_side = max(50.0, inner_w * 0.44)
        wrap_w = max(10.0, max_side - 2 * _EXPL_CAP_PAD_PT)
        if side_flow == "vertical_up":
            one = " ".join((raw.replace("\r\n", "\n").replace("\n", " ").split()))
            vmax = max(8.0, draw_h - 2 * _EXPL_CAP_PAD_PT)
            vtext = _expl_truncate_string_to_width(one, font, size, vmax)
            text_w = min(max_side, size + 2 * _EXPL_CAP_PAD_PT + 1.0)
            need = draw_w + gap + text_w
            if need <= inner_w + 0.5 and vtext.strip():
                ch = max(draw_h, size + 2 * _EXPL_CAP_PAD_PT)
                bh = max(ch, draw_h)
                return spec_base([], "right_left", bh, ch, text_w, side_vertical=True, vertical_text=vtext)
        lines_side = _expl_wrap_lines(raw, font, size, wrap_w)
        lines_side = _expl_fit_lines_to_box(lines_side, font, size, lead, draw_h, wrap_w)
        text_w = min(max_side, _expl_lines_max_width(lines_side, font, size) + 2 * _EXPL_CAP_PAD_PT)
        need = draw_w + gap + text_w
        if need <= inner_w + 0.5:
            n = max(len(lines_side), 1)
            ch = _expl_caption_block_height(n, size, lead)
            bh = max(ch, draw_h)
            return spec_base(lines_side, "right_left", bh, ch, text_w)
        lines_full = _expl_wrap_lines(raw, font, size, tw_box)
        lines_full = _expl_fit_lines_to_box(lines_full, font, size, lead, draw_h, line_max)
        n = max(len(lines_full), 1)
        ch = _expl_caption_block_height(n, size, lead)
        bh = draw_h + gap + ch
        return spec_base(lines_full, "stacked_bottom", bh, ch)

    return None


def _draw_expl_caption_lines(
    c: canvas.Canvas,
    lines: List[str],
    font_name: str,
    font_size: float,
    leading: float,
    align: str,
    x_left: float,
    box_w: float,
    y_top_box: float,
    fill_rgb: Tuple[float, float, float],
    caption_block_h: float,
    *,
    box_enabled: bool = False,
    box_fill_rgb: Optional[Tuple[float, float, float]] = None,
    box_rounded: bool = True,
    box_tight: bool = False,
) -> None:
    if not lines:
        return
    ch = float(caption_block_h)
    n = len(lines)
    try:
        ascent = float(getAscentDescent(font_name, font_size)[0])
        descent = float(getAscentDescent(font_name, font_size)[1])
    except Exception:
        ascent = font_size * 0.8
        descent = font_size * 0.2

    draw_x = x_left
    draw_w = box_w
    if box_enabled and box_fill_rgb is not None:
        y_bl = y_top_box - ch
        if box_tight:
            mx = 0.0
            for line in lines:
                s = line if line is not None else " "
                try:
                    mx = max(mx, float(stringWidth(s, font_name, font_size)))
                except Exception:
                    mx = max(mx, len(s) * font_size * 0.48)
            inset = _expl_tight_box_side_inset_pt(font_name, font_size)
            inner = mx + 2.0 * inset + _EXPL_CAP_PAD_PT
            tight_w = min(box_w, inner)
            if align == "center":
                draw_x = x_left + (box_w - tight_w) / 2.0
            elif align == "right":
                draw_x = x_left + box_w - tight_w
            else:
                draw_x = x_left
            draw_w = tight_w
        c.saveState()
        c.setFillColorRGB(box_fill_rgb[0], box_fill_rgb[1], box_fill_rgb[2])
        if box_rounded:
            rad = min(6.0, max(2.0, ch * 0.18), max(2.0, draw_w * 0.035))
            c.roundRect(draw_x, y_bl, draw_w, ch, rad, fill=1, stroke=0)
        else:
            c.rect(draw_x, y_bl, draw_w, ch, fill=1, stroke=0)
        c.restoreState()

    # Dikey: metin bloğunu caption alanı yüksekliği (ch) içinde ortala (kutu açık/kapalı).
    text_h = (n - 1) * leading + ascent + descent
    excess = max(0.0, ch - text_h)
    y = y_top_box - excess / 2.0 - ascent
    if box_enabled:
        area_left = draw_x
        area_w = draw_w
    else:
        area_left = x_left
        area_w = box_w

    c.setFont(font_name, font_size)
    c.setFillColorRGB(fill_rgb[0], fill_rgb[1], fill_rgb[2])
    for line in lines:
        s = line if line is not None else " "
        try:
            lw = float(stringWidth(s, font_name, font_size))
        except Exception:
            lw = len(s) * font_size * 0.5
        if box_enabled:
            lx = area_left + max(0.0, (area_w - lw) / 2.0)
        elif align == "center":
            lx = x_left + max(0.0, (box_w - lw) / 2.0)
        elif align == "right":
            lx = x_left + max(0.0, box_w - lw)
        else:
            lx = x_left
        c.drawString(lx, y, s)
        y -= leading


def _draw_expl_caption_vertical(
    c: canvas.Canvas,
    text: str,
    font_name: str,
    font_size: float,
    fill_rgb: Tuple[float, float, float],
    x_left: float,
    box_w: float,
    draw_y_top: float,
    draw_h: float,
    is_left_column: bool,
) -> None:
    s = (text or "").strip()
    if not s:
        return
    try:
        tw = float(stringWidth(s, font_name, font_size))
    except Exception:
        tw = len(s) * font_size * 0.5
    px = x_left + box_w / 2.0
    py = draw_y_top - draw_h / 2.0
    c.saveState()
    c.setFillColorRGB(fill_rgb[0], fill_rgb[1], fill_rgb[2])
    c.setFont(font_name, font_size)
    c.translate(px, py)
    c.rotate(90.0 if is_left_column else -90.0)
    adj = -tw / 2.0
    try:
        descent = float(getAscentDescent(font_name, font_size)[1])
    except Exception:
        descent = font_size * 0.2
    c.drawString(adj, -descent * 0.35, s)
    c.restoreState()


def _draw_explanation_content_block(
    c: canvas.Canvas,
    entry: Dict,
    x_pt: float,
    num_w: float,
    draw_y_top: float,
    inner_w: float,
) -> None:
    """Açıklama + isteğe bağlı metin + görsel."""
    expl = entry.get("expl_caption")
    x0 = x_pt + num_w + _NUM_TO_IMAGE_GAP_PT
    draw_w = float(entry["draw_w"])
    draw_h = float(entry["draw_h"])
    ir = ImageReader(io.BytesIO(entry["png_bytes"]))
    gap = _EXPL_CAP_GAP_PT

    if not expl:
        c.drawImage(
            ir, x0, draw_y_top - draw_h, width=draw_w, height=draw_h, mask="auto"
        )
        return

    mode = expl["mode"]
    lines = expl["lines"]
    font = expl["font"]
    size = expl["size"]
    lead = expl["leading"]
    align = expl["align"]
    ch = float(expl["caption_h"])
    rgb = expl.get("color_rgb") or (0.0, 0.0, 0.0)
    side_v = bool(expl.get("side_vertical"))
    vtext = str(expl.get("vertical_text") or "")
    box_on = bool(expl.get("box_enabled"))
    box_fill = expl.get("box_fill_rgb") if box_on else None
    box_rnd = bool(expl.get("box_rounded", True))
    box_tight = bool(expl.get("box_tight"))

    def _cap_lines(x_l: float, bw: float, y_top: float) -> None:
        _draw_expl_caption_lines(
            c, lines, font, size, lead, align, x_l, bw, y_top, rgb, ch,
            box_enabled=box_on,
            box_fill_rgb=box_fill if isinstance(box_fill, tuple) else None,
            box_rounded=box_rnd,
            box_tight=box_tight,
        )

    if mode == "above":
        _cap_lines(x0, inner_w, draw_y_top)
        img_y_bl = draw_y_top - ch - gap - draw_h
        c.drawImage(ir, x0, img_y_bl, width=draw_w, height=draw_h, mask="auto")
    elif mode == "below":
        img_y_bl = draw_y_top - draw_h
        c.drawImage(ir, x0, img_y_bl, width=draw_w, height=draw_h, mask="auto")
        text_top = draw_y_top - draw_h - gap
        _cap_lines(x0, inner_w, text_top)
    elif mode == "left_right":
        tw = float(expl["text_col_w"])
        if side_v:
            _draw_expl_caption_vertical(c, vtext, font, size, rgb, x0, tw, draw_y_top, draw_h, True)
        else:
            _cap_lines(x0, tw, draw_y_top)
        ix = x0 + tw + gap
        c.drawImage(ir, ix, draw_y_top - draw_h, width=draw_w, height=draw_h, mask="auto")
    elif mode == "right_left":
        tw = float(expl["text_col_w"])
        c.drawImage(ir, x0, draw_y_top - draw_h, width=draw_w, height=draw_h, mask="auto")
        tx0 = x0 + draw_w + gap
        if side_v:
            _draw_expl_caption_vertical(c, vtext, font, size, rgb, tx0, tw, draw_y_top, draw_h, False)
        else:
            _cap_lines(tx0, tw, draw_y_top)
    elif mode == "stacked_top":
        _cap_lines(x0, inner_w, draw_y_top)
        img_y_bl = draw_y_top - ch - gap - draw_h
        c.drawImage(ir, x0, img_y_bl, width=draw_w, height=draw_h, mask="auto")
    elif mode == "stacked_bottom":
        img_y_bl = draw_y_top - draw_h
        c.drawImage(ir, x0, img_y_bl, width=draw_w, height=draw_h, mask="auto")
        text_top = draw_y_top - draw_h - gap
        _cap_lines(x0, inner_w, text_top)
    else:
        c.drawImage(ir, x0, draw_y_top - draw_h, width=draw_w, height=draw_h, mask="auto")


def _prepare_question_data_for_layout(
    questions: List[Dict],
    pdf_map: Dict[str, "PdfItem"],
    opts: ExportOptions,
    col_w: float,
    sections: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Load question images and compute block dimensions. Returns list for layout algorithm."""
    box_h = 12.0
    sorted_q = sorted(questions, key=lambda q: q.get("order_index", 0))
    num_w = _question_number_slot_width_pt_for_items(sorted_q, sections)
    text_scale = 10.0 / 12.0
    result: List[Dict] = []

    for idx, q in enumerate(sorted_q, start=1):
        png_bytes = None
        img_w_px = 0
        img_h_px = 0

        if q.get("image_base64"):
            try:
                raw_b64 = str(q["image_base64"])
                if "base64," in raw_b64:
                    raw_b64 = raw_b64.split("base64,", 1)[1]
                png_bytes, img_w_px, img_h_px = _png_base64_to_bytes_and_size(raw_b64)
            except Exception:
                continue
        else:
            item = pdf_map.get(q.get("pdf_id", ""))
            if not item:
                continue
            try:
                crop = q.get("crop", {})
                png_bytes, img_w_px, img_h_px = _render_crop(
                    Path(item.path),
                    q.get("page_number", 1),
                    crop.get("x", 0),
                    crop.get("y", 0),
                    crop.get("width", 1),
                    crop.get("height", 1),
                    opts.zoom,
                    remove_background=q.get("remove_background", False),
                )
            except Exception:
                continue

        display_scale = float(q.get("display_scale") or 1.0)
        custom_gap = q.get("custom_gap_mm")
        preferred_gap_pt_q = mm_to_pt(custom_gap if custom_gap is not None else opts.question_gap_mm)

        img_w_pt = (img_w_px / opts.zoom) * display_scale
        img_h_pt = (img_h_px / opts.zoom) * display_scale
        draw_w = img_w_pt * text_scale
        draw_h = img_h_pt * text_scale

        avail_w = col_w - num_w - _NUM_TO_IMAGE_GAP_PT - _IMG_COL_RIGHT_PAD_PT
        if draw_w > avail_w and avail_w > 0:
            s = avail_w / draw_w
            draw_w = avail_w
            draw_h *= s

        content_inner_w = max(20.0, avail_w)
        expl_spec = _build_expl_caption_spec(q, content_inner_w, draw_w, draw_h)
        if expl_spec:
            block_h = max(box_h, float(expl_spec["block_h"]))
        else:
            block_h = max(box_h, draw_h)

        sec = _get_section_for_index(idx - 1, sections or [])
        sec_gap = 8.0
        sec_box_h = 0.0
        if sec:
            font_pt = max(8.0, min(24.0, float(sec.get("font_pt", 12.0) or 12.0)))
            sec_box_h = font_pt + 8.0  # İçeriğe sıkı yükseklik (font + minimal padding)
            block_h += sec_box_h + sec_gap

        entry: Dict = {
            "order_index": idx - 1,
            "idx": idx,
            "block_h": block_h,
            "preferred_gap_pt": preferred_gap_pt_q,
            "png_bytes": png_bytes,
            "img_w_px": img_w_px,
            "img_h_px": img_h_px,
            "draw_w": draw_w,
            "draw_h": draw_h,
            "answer_key": (q.get("answer_key") or "").strip().upper() or "?",
            "crop": q.get("crop", {}),
            "content_type": str(q.get("content_type") or "question").strip().lower(),
            "content_inner_w": content_inner_w,
            "expl_caption": expl_spec,
        }
        if sec:
            entry["section"] = {
                "title": (sec.get("title") or "").strip() or "Bölüm",
                "fill_color": str(sec.get("fill_color", "#FFFFFF") or "#FFFFFF"),
                "text_color": str(sec.get("text_color", "#000000") or "#000000"),
                "line_color": str(sec.get("line_color", "#000000") or "#000000"),
                "font_pt": float(sec.get("font_pt", 12.0) or 12.0),
                "restart_numbering": bool(sec.get("restart_numbering", False)),
                "start_new_page": bool(sec.get("start_new_page", False)),
                "box_h": sec_box_h,
                "gap_after": sec_gap,
            }
        result.append(entry)
    return result


def _run_layout(
    question_data: List[Dict],
    opts: ExportOptions,
) -> List[Dict]:
    """Run flexible layout. question_data from _prepare_question_data_for_layout."""
    page_w, page_h = _page_size_pt(opts)
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mb = mm_to_pt(opts.margin_bottom_mm)
    col_gap = mm_to_pt(opts.column_gap_mm)
    cols = max(1, min(6, opts.columns))
    content_w = page_w - ml - mr
    col_w = (content_w - (cols - 1) * col_gap) / cols if cols > 1 else content_w

    return _compute_layout_entries_flexible(
        question_data,
        opts,
        page_w, page_h, ml, mr, mb, col_gap, col_w, cols,
    )


def export_desktop_style(
    questions: List[QuestionItem],
    pdf_items: List[PdfItem],
    opts: ExportOptions,
    out_name: str = "exported_test.pdf",
) -> Path:
    """Export questions using desktop-style layout."""
    pdf_map = {p.id: p for p in pdf_items}
    out_path = EXPORT_DIR / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = _page_size_pt(opts)
    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mb = mm_to_pt(opts.margin_bottom_mm)
    col_gap = mm_to_pt(opts.column_gap_mm)
    gap_pt = mm_to_pt(opts.question_gap_mm)
    cols = max(1, min(6, opts.columns))
    content_w = page_w - ml - mr
    if cols > 1:
        col_w = (content_w - (cols - 1) * col_gap) / cols
    else:
        col_w = content_w
    footer_top = mb + mm_to_pt(opts.footer_top_offset_mm)
    theme = _hex_to_rgb01(opts.theme_color)
    page_num = 1
    current_top = _draw_header_style3(c, page_w, page_h, opts, is_first_page=True)
    _draw_column_divider(c, page_w, page_h, opts, footer_top, is_first_page=True)
    col_idx = 0
    x_col = ml + col_idx * (col_w + col_gap)
    y = current_top
    prev_bottom: Dict[int, float] = {}
    page_answers: List[Tuple[int, str]] = []

    def next_col():
        nonlocal col_idx, x_col, y, page_num, current_top
        col_idx += 1
        if col_idx >= cols:
            _draw_center_line_text(
                c,
                page_w,
                page_h,
                opts,
                footer_top=footer_top,
                is_first_page=(page_num == 1),
            )
            _draw_footer()
            _draw_watermark(c, page_w, page_h, opts)
            c.showPage()
            page_num += 1
            current_top = _draw_header_style3(c, page_w, page_h, opts, is_first_page=False)
            _draw_column_divider(c, page_w, page_h, opts, footer_top, is_first_page=False)
            col_idx = 0
            x_col = ml
            y = current_top
            prev_bottom.clear()
        else:
            x_col = ml + col_idx * (col_w + col_gap)
            y = prev_bottom.get(col_idx, current_top)

    _footer_utf = _register_unicode_font()
    _footer_font = _footer_utf if _footer_utf != "Helvetica" else "Helvetica"
    _ak_mode = (getattr(opts, "answer_key_mode", "per_page") or "per_page").strip().lower()
    _show_footer_answers = bool(opts.answer_key_enabled) and _ak_mode == "per_page"

    def _draw_footer():
        written = bool(getattr(opts, "written_paper_header", False))
        if written:
            _draw_written_paper_footer_simple(
                c,
                ml=ml,
                mr=mr,
                page_w=page_w,
                footer_top=footer_top,
                footer_font=_footer_font,
                show_answers=_show_footer_answers and bool(page_answers),
                answers=list(page_answers),
            )
        else:
            _draw_test_paper_footer_double(
                c,
                ml=ml,
                mr=mr,
                page_w=page_w,
                mb=mb,
                opts=opts,
                theme=theme,
                footer_font=_footer_font,
                page_no=page_num,
                show_answers=_show_footer_answers,
                answers=list(page_answers),
            )
        page_answers.clear()

    sorted_q = sorted(questions, key=lambda q: q.order_index)
    qdicts: List[Dict] = []
    for q in sorted_q:
        if hasattr(q, "model_dump"):
            qdicts.append(q.model_dump())
        elif isinstance(q, dict):
            qdicts.append(q)
        else:
            qdicts.append(
                {
                    "content_type": str(getattr(q, "content_type", None) or "question").lower(),
                }
            )
    num_w = _question_number_slot_width_pt_for_items(qdicts, None)
    display_counter = 1
    for q in sorted_q:
        item = pdf_map.get(q.pdf_id)
        if not item:
            continue
        pdf_path = Path(item.path)
        try:
            png_bytes, img_w_px, img_h_px = _render_crop(
                pdf_path,
                q.page_number,
                q.crop.x,
                q.crop.y,
                q.crop.width,
                q.crop.height,
                opts.zoom,
                remove_background=getattr(q, "remove_background", False),
            )
        except Exception:
            continue
        img_w_pt = img_w_px / opts.zoom
        img_h_pt = img_h_px / opts.zoom
        text_scale = 10.0 / 12.0
        draw_w = img_w_pt * text_scale
        draw_h = img_h_pt * text_scale
        box_h = 12.0
        ctype = str(getattr(q, "content_type", None) or "question").strip().lower()
        is_expl = ctype == "explanation"
        num_text: Optional[str] = None
        disp_idx: Optional[int] = None
        if not is_expl:
            disp_idx = display_counter
            num_text = f"{display_counter}."
            display_counter += 1
        avail_w = col_w - num_w - _NUM_TO_IMAGE_GAP_PT - _IMG_COL_RIGHT_PAD_PT
        if draw_w > avail_w:
            s = avail_w / draw_w
            draw_w = avail_w
            draw_h *= s
        q_h = max(box_h, draw_h) + gap_pt
        content_floor = footer_top  # Footer üst çizgisine göre, alt çizgi değil
        if col_idx in prev_bottom:
            y = prev_bottom[col_idx]
        while y - q_h < content_floor:
            next_col()
            if col_idx in prev_bottom:
                y = prev_bottom[col_idx]
        y_top = y
        c.setFont(_NUM_FONT, _NUM_FONT_SIZE)
        c.setFillColorRGB(0, 0, 0)
        if num_text:
            c.drawString(
                _number_draw_left_pt(x_col, num_text, num_w),
                y_top - _NUM_ASCENT_PT,
                num_text,
            )
        ans = (q.answer_key or "").strip().upper() or "?"
        if disp_idx is not None:
            page_answers.append((disp_idx, ans))
        ir = ImageReader(io.BytesIO(png_bytes))
        # ReportLab drawImage varsayılan anchor 'sw' (sol alt). Görselin ÜST kenarı y_top'ta olmalı.
        c.drawImage(
            ir, x_col + num_w + _NUM_TO_IMAGE_GAP_PT, y_top - draw_h,
            width=draw_w, height=draw_h,
            mask="auto",
        )
        y_bottom = y_top - max(box_h, draw_h) - gap_pt
        prev_bottom[col_idx] = y_bottom
        y = y_bottom

    if page_answers:
        _draw_center_line_text(
            c,
            page_w,
            page_h,
            opts,
            footer_top=footer_top,
            is_first_page=(page_num == 1),
        )
        _draw_footer()
        _draw_watermark(c, page_w, page_h, opts)
    c.save()
    return out_path


def export_from_payload(
    questions: List[Dict],
    pdf_items: List[PdfItem],
    opts: ExportOptions,
    out_name: str = "exported_test.pdf",
    sections: Optional[List[Dict]] = None,
    layout_y_top_overrides: Optional[Any] = None,
) -> Path:
    """Export from payload - uses flexible layout (preferred/min spacing, compaction)."""
    pdf_map = {p.id: p for p in pdf_items}
    out_path = EXPORT_DIR / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = _page_size_pt(opts)
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mb = mm_to_pt(opts.margin_bottom_mm)
    col_gap = mm_to_pt(opts.column_gap_mm)
    cols = max(1, min(6, opts.columns))
    content_w = page_w - ml - mr
    col_w = (content_w - (cols - 1) * col_gap) / cols if cols > 1 else content_w

    question_data = _prepare_question_data_for_layout(
        questions, pdf_map, opts, col_w, sections=sections or []
    )
    if not question_data:
        raise ValueError(
            "Hiçbir soru işlenemedi. "
            "Yerel PDF kullandıysanız soruların image_base64 değeri olmalı. "
            "Sunucuya yüklenmiş PDF kullandıysanız soruların pdf_id değeri sunucudaki PDF ile eşleşmeli."
        )
    layout_entries = _run_layout(question_data, opts)
    _apply_y_top_overrides_to_layout_entries(layout_entries, layout_y_top_overrides)

    _apply_display_numbers_to_layout_entries(layout_entries)

    num_w = _question_number_slot_width_from_layout_entries(layout_entries)

    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))
    theme = _hex_to_rgb01(opts.theme_color)
    footer_top = mb + mm_to_pt(opts.footer_top_offset_mm)

    mode = (getattr(opts, "answer_key_mode", "per_page") or "per_page").strip().lower()
    show_footer_answers = bool(opts.answer_key_enabled) and (mode == "per_page")

    effective_bottom = footer_top + mm_to_pt(2.0)
    last_q_page = max(int(e["page_num"]) for e in layout_entries)
    footer_nav_last_question_page: Optional[int] = None
    if not bool(getattr(opts, "written_paper_header", False)):
        footer_nav_last_question_page = last_q_page

    utf_font = _register_unicode_font()
    footer_font = utf_font if utf_font != "Helvetica" else "Helvetica"

    def _draw_footer(_pg_num: int, answers: List[Tuple[int, str]], show_answers: bool = True) -> None:
        written = bool(getattr(opts, "written_paper_header", False))
        if written:
            _draw_written_paper_footer_simple(
                c,
                ml=ml,
                mr=mr,
                page_w=page_w,
                footer_top=footer_top,
                footer_font=footer_font,
                show_answers=show_answers and bool(answers),
                answers=answers,
            )
            return
        _draw_test_paper_footer_double(
            c,
            ml=ml,
            mr=mr,
            page_w=page_w,
            mb=mb,
            opts=opts,
            theme=theme,
            footer_font=footer_font,
            page_no=_pg_num,
            show_answers=show_answers,
            answers=answers,
            last_question_page_num=footer_nav_last_question_page,
        )

    current_page = 0
    page_answers: List[Tuple[int, str]] = []
    answer_key: List[Tuple[int, str]] = []
    answer_key_groups: List[Tuple[str, List[Tuple[int, str]]]] = []
    _ak_title = "Genel"
    _ak_entries: List[Tuple[int, str]] = []

    for entry in layout_entries:
        if entry["page_num"] != current_page:
            if current_page > 0:
                _draw_center_line_text(
                    c,
                    page_w,
                    page_h,
                    opts,
                    footer_top=footer_top,
                    is_first_page=(current_page == 1),
                )
                _draw_footer(current_page, page_answers, show_footer_answers)
                _draw_watermark(c, page_w, page_h, opts)
                c.showPage()
                page_answers.clear()
            current_page = entry["page_num"]
            if getattr(opts, "written_paper_header", False) and current_page == 1:
                _draw_written_paper_header(c, page_w, page_h, opts)
            else:
                _draw_header_style3(c, page_w, page_h, opts, is_first_page=(current_page == 1))
            _draw_column_divider(c, page_w, page_h, opts, footer_top, is_first_page=(current_page == 1))

        x_pt = entry["x_pt"]
        y_top = entry["y_top_pt"]
        sec = entry.get("section")
        draw_y_top = y_top
        if sec:
            sec_box_h = sec.get("box_h", 22.0)
            sec_gap = sec.get("gap_after", 8.0)
            box_w_sec = col_w
            y_top_sec = y_top
            y_bottom_sec = y_top_sec - sec_box_h
            fill_rgb = _hex_to_rgb01(sec.get("fill_color", "#FFFFFF"), (1.0, 1.0, 1.0))
            text_rgb = _hex_to_rgb01(sec.get("text_color", "#000000"), (0.0, 0.0, 0.0))
            stroke_rgb = _hex_to_rgb01(
                sec.get("line_color") or opts.theme_color,
                (0.0, 0.0, 0.0),
            )
            c.saveState()
            c.setLineWidth(0.8)
            c.setStrokeColorRGB(*stroke_rgb)
            c.setFillColorRGB(*fill_rgb)
            c.roundRect(x_pt, y_bottom_sec, box_w_sec, sec_box_h, 8.0, fill=1, stroke=1)
            c.setFillColorRGB(*text_rgb)
            sec_font_pt = max(8.0, min(24.0, float(sec.get("font_pt", 12.0))))
            utf_font = _register_unicode_font()
            bold_sec = "Helvetica-Bold" if utf_font == "Helvetica" else f"{utf_font}-Bold"
            if bold_sec not in pdfmetrics.getRegisteredFontNames():
                bold_sec = utf_font if utf_font != "Helvetica" else _NUM_FONT
            c.setFont(bold_sec, sec_font_pt)
            sec_title = (sec.get("title") or "").strip() or "Bölüm"
            box_center_y = y_bottom_sec + sec_box_h / 2.0
            try:
                from reportlab.pdfbase.pdfmetrics import stringWidth, getFont
                text_w = float(stringWidth(sec_title, bold_sec, sec_font_pt))
                font_obj = getFont(bold_sec)
                ascent = float(getattr(getattr(font_obj, "face", None), "ascent", 800))
                descent = float(getattr(getattr(font_obj, "face", None), "descent", -200))
                ascent_pt = (ascent / 1000.0) * sec_font_pt
                descent_pt = (descent / 1000.0) * sec_font_pt
                text_center_offset = (ascent_pt + descent_pt) / 2.0
                y_baseline = box_center_y - text_center_offset
                x_text = x_pt + max(0.0, (box_w_sec - text_w) / 2.0)
                c.drawString(x_text, y_baseline, sec_title)
            except Exception:
                y_baseline = box_center_y - sec_font_pt * 0.35
                c.drawCentredString(x_pt + box_w_sec / 2.0, y_baseline, sec_title)
            c.restoreState()
            draw_y_top = y_bottom_sec - sec_gap

        disp_num = entry.get("display_number")
        ans_key = entry["answer_key"]
        c.setFont(_NUM_FONT, _NUM_FONT_SIZE)
        c.setFillColorRGB(0, 0, 0)
        if disp_num is not None:
            num_text = f"{int(disp_num)}."
            c.drawString(
                _number_draw_left_pt(x_pt, num_text, num_w),
                draw_y_top - _NUM_ASCENT_PT,
                num_text,
            )
        sec_cur = entry.get("section")
        group_title = "Genel"
        if sec_cur:
            group_title = (sec_cur.get("title") or "").strip() or "Bölüm"
        if group_title != _ak_title:
            if _ak_entries:
                answer_key_groups.append((_ak_title, list(_ak_entries)))
                _ak_entries = []
            _ak_title = group_title
        if disp_num is not None:
            page_answers.append((int(disp_num), ans_key))
            answer_key.append((int(disp_num), ans_key))
            _ak_entries.append((int(disp_num), ans_key))
        inner_w = float(
            entry.get(
                "content_inner_w",
                col_w - num_w - _NUM_TO_IMAGE_GAP_PT - _IMG_COL_RIGHT_PAD_PT,
            )
        )
        if str(entry.get("content_type") or "question") == "explanation":
            _draw_explanation_content_block(c, entry, x_pt, num_w, draw_y_top, inner_w)
        else:
            ir = ImageReader(io.BytesIO(entry["png_bytes"]))
            c.drawImage(
                ir,
                x_pt + num_w + _NUM_TO_IMAGE_GAP_PT,
                draw_y_top - entry["draw_h"],
                width=entry["draw_w"],
                height=entry["draw_h"],
                mask="auto",
            )

    if _ak_entries:
        answer_key_groups.append((_ak_title, list(_ak_entries)))

    if page_answers:
        # Öğretmen / imza bloğu: döngü bittiğinde yalnızca son soru sayfası için (page_answers temizlenmeden kalan)
        teachers = getattr(opts, "teacher_names", None) or []
        if teachers and isinstance(teachers, list) and len(teachers) > 0:
            last_entries = [e for e in layout_entries if e["page_num"] == current_page]
            last_y = (
                min(e["y_top_pt"] - e.get("block_h", 0) for e in last_entries)
                if last_entries else footer_top
            )
            teacher_y_bottom = mb + mm_to_pt(opts.footer_top_offset_mm) + 25.0
            _draw_teacher_signatures_block(
                c, page_w, last_y - 12.0, teacher_y_bottom, opts,
                col_w=col_w, col_gap=col_gap, cols=cols,
            )
        _draw_center_line_text(
            c,
            page_w,
            page_h,
            opts,
            footer_top=footer_top,
            is_first_page=(current_page == 1),
        )
        _draw_footer(current_page, page_answers, show_footer_answers)
        _draw_watermark(c, page_w, page_h, opts)

    has_sections = any(
        ((t or "").strip() and (t or "").strip().lower() != "genel")
        for t, _ in (answer_key_groups or [])
    )
    groups_to_draw: List[Tuple[str, List[Tuple[int, str]]]] = []
    if has_sections and answer_key_groups:
        groups_to_draw = list(answer_key_groups)
    else:
        groups_to_draw = [("Cevap Anahtarı", list(answer_key))] if answer_key else []

    if opts.answer_key_enabled and mode == "end_of_test" and groups_to_draw:
        last_entries = [e for e in layout_entries if e["page_num"] == current_page]
        last_y = min(e["y_top_pt"] - e.get("block_h", 0) for e in last_entries) if last_entries else footer_top
        x0 = ml + (cols - 1) * (col_w + col_gap) if cols > 1 else ml
        w0 = col_w
        max_h_avail = max(0.0, last_y - 8.0 - effective_bottom)
        for g_title, g_items in groups_to_draw:
            remaining = list(g_items or [])
            if not remaining:
                continue
            title = (g_title or "").strip() or "Cevap Anahtarı"
            title_pt = 12.0 if (has_sections and title.lower() != "genel") else 11.0
            y0_bottom = effective_bottom
            while remaining:
                avail = max(0.0, max_h_avail - _ANSWER_KEY_HEADER_PT - _ANSWER_KEY_BOTTOM_PAD_PT)
                max_rows = max(1, int(avail // _ANSWER_KEY_ROW_PT)) if avail > _ANSWER_KEY_ROW_PT else 0
                if max_rows <= 0:
                    break
                capacity = max_rows * 2
                chunk = remaining[:capacity]
                if not chunk:
                    break
                table_h = _answer_key_table_height(chunk, 2)
                y0 = y0_bottom + table_h
                used, remaining2 = _draw_answer_key_table(
                    c, opts,
                    x=x0, y_top=y0, w=w0,
                    max_h=max_h_avail,
                    items=remaining, entries_per_row=2,
                    title_text=title, title_font_pt=title_pt,
                )
                if used <= 0.0:
                    break
                remaining = remaining2
                y0_bottom += used + 8.0
                max_h_avail = max(0.0, last_y - 8.0 - y0_bottom)

    if opts.answer_key_enabled and mode == "separate_page" and groups_to_draw:
        w0 = col_w
        x0 = ml + (page_w - ml - mr - w0) / 2.0
        y0 = page_h - mm_to_pt(opts.margin_top_mm) - mm_to_pt(opts.header_reserved_mm) - 8.0

        def new_answer_page() -> float:
            nonlocal current_page
            current_page += 1
            c.showPage()
            # Cevap anahtarı sayfasında banner/header yok
            mt = mm_to_pt(opts.margin_top_mm)
            top = page_h - mt - 10.0
            _draw_footer(current_page, [], False)
            return top - 8.0

        y0 = new_answer_page()
        for g_title, g_items in groups_to_draw:
            remaining = list(g_items or [])
            if not remaining:
                continue
            title = (g_title or "").strip() or "Cevap Anahtarı"
            title_pt = 12.0 if (has_sections and title.lower() != "genel") else 11.0
            while remaining:
                used, remaining2 = _draw_answer_key_table(
                    c, opts,
                    x=x0, y_top=y0, w=w0,
                    max_h=max(0.0, y0 - effective_bottom),
                    items=remaining, entries_per_row=4,
                    title_text=title, title_font_pt=title_pt,
                )
                if used <= 0.0:
                    _draw_watermark(c, page_w, page_h, opts)
                    y0 = new_answer_page()
                    continue
                y0 -= used + 10.0
                remaining = remaining2
        _draw_watermark(c, page_w, page_h, opts)

    c.save()
    return out_path


def _coerce_y_top_override_map(overrides: Optional[Any]) -> Dict[int, float]:
    if not overrides:
        return {}
    out: Dict[int, float] = {}
    for o in overrides:
        if o is None:
            continue
        if hasattr(o, "order_index") and hasattr(o, "y_top_pt"):
            oi = int(o.order_index)
            yt = float(o.y_top_pt)
        elif isinstance(o, dict):
            raw_oi = o.get("order_index")
            raw_yt = o.get("y_top_pt")
            if raw_oi is None or raw_yt is None:
                continue
            oi = int(raw_oi)
            yt = float(raw_yt)
        else:
            continue
        out[oi] = yt
    return out


def _preview_finalize_expl_caption(cap_preview: Dict[str, Any], expl: Dict[str, Any]) -> None:
    """Sıkı kutu: canvas arka planı metin + karakter payı kadar daraltılır."""
    lines = cap_preview.get("lines") or []
    if not lines or not expl.get("box_enabled") or not expl.get("box_tight"):
        cap_preview.pop("box_bg_x_pt", None)
        cap_preview.pop("box_bg_w_pt", None)
        return
    font = expl["font"]
    fs = float(expl["size"])
    alg = str(cap_preview.get("align") or "left")
    x_left = float(cap_preview["x_pt"])
    full_w = float(cap_preview["w_pt"])
    mx = 0.0
    for line in lines:
        s = line if line is not None else " "
        try:
            mx = max(mx, float(stringWidth(s, font, fs)))
        except Exception:
            mx = max(mx, len(s) * fs * 0.48)
    inset = _expl_tight_box_side_inset_pt(font, fs)
    tight_w = min(full_w, mx + 2.0 * inset + _EXPL_CAP_PAD_PT)
    if alg == "center":
        bx = x_left + (full_w - tight_w) / 2.0
    elif alg == "right":
        bx = x_left + full_w - tight_w
    else:
        bx = x_left
    cap_preview["box_bg_x_pt"] = bx
    cap_preview["box_bg_w_pt"] = tight_w


def _preview_expl_for_canvas(
    entry: Dict,
    draw_y_top: float,
    x_col: float,
    num_w: float,
    inner_w: float,
) -> Tuple[float, float, Optional[Dict[str, Any]]]:
    """Önizleme: görsel sol üst (x, y_top) ve isteğe bağlı açıklama metin kutusu."""
    x0 = x_col + num_w + _NUM_TO_IMAGE_GAP_PT
    expl = entry.get("expl_caption")
    dw = float(entry["draw_w"])
    dh = float(entry["draw_h"])
    gap = _EXPL_CAP_GAP_PT
    if not expl:
        return x0, draw_y_top, None
    mode = expl["mode"]
    ch = float(expl["caption_h"])
    lines = expl["lines"]
    align = expl["align"]
    fs = float(expl["size"])
    ld = float(expl["leading"])
    color_hex = str(expl.get("color_hex") or "#0f172a")
    bold = bool(expl.get("bold"))
    italic = bool(expl.get("italic"))
    side_v = bool(expl.get("side_vertical"))
    vtext = str(expl.get("vertical_text") or "")
    box_en = bool(expl.get("box_enabled"))
    box_hex = str(expl.get("box_hex") or "#f1f5f9")
    box_rnd = bool(expl.get("box_rounded", True))
    box_tight_flag = bool(expl.get("box_tight"))
    cap_preview: Dict[str, Any] = {
        "lines": lines,
        "align": align,
        "font_pt": fs,
        "leading_pt": ld,
        "color_hex": color_hex,
        "bold": bold,
        "italic": italic,
        "single_line": "",
        "rotate_deg": 0,
        "pivot_x_pt": 0.0,
        "pivot_y_pt": 0.0,
        "box_enabled": box_en,
        "box_fill_hex": box_hex if box_en else "",
        "box_rounded": box_rnd,
        "box_tight": box_tight_flag,
    }
    if mode == "above":
        cap_preview.update({"x_pt": x0, "y_top_pt": draw_y_top, "w_pt": inner_w, "h_pt": ch})
        _preview_finalize_expl_caption(cap_preview, expl)
        return x0, draw_y_top - ch - gap, cap_preview
    if mode == "below":
        cap_preview.update(
            {"x_pt": x0, "y_top_pt": draw_y_top - dh - gap, "w_pt": inner_w, "h_pt": ch}
        )
        _preview_finalize_expl_caption(cap_preview, expl)
        return x0, draw_y_top, cap_preview
    if mode == "left_right":
        tw = float(expl["text_col_w"])
        if side_v and vtext.strip():
            px = x0 + tw / 2.0
            py = draw_y_top - dh / 2.0
            cap_preview["lines"] = []
            cap_preview["single_line"] = vtext
            cap_preview["rotate_deg"] = 90
            cap_preview["pivot_x_pt"] = px
            cap_preview["pivot_y_pt"] = py
            cap_preview.update({"x_pt": x0, "y_top_pt": draw_y_top, "w_pt": tw, "h_pt": dh})
        else:
            cap_preview.update({"x_pt": x0, "y_top_pt": draw_y_top, "w_pt": tw, "h_pt": ch})
        _preview_finalize_expl_caption(cap_preview, expl)
        return x0 + tw + gap, draw_y_top, cap_preview
    if mode == "right_left":
        tw = float(expl["text_col_w"])
        tx0 = x0 + dw + gap
        if side_v and vtext.strip():
            px = tx0 + tw / 2.0
            py = draw_y_top - dh / 2.0
            cap_preview["lines"] = []
            cap_preview["single_line"] = vtext
            cap_preview["rotate_deg"] = -90
            cap_preview["pivot_x_pt"] = px
            cap_preview["pivot_y_pt"] = py
            cap_preview.update({"x_pt": tx0, "y_top_pt": draw_y_top, "w_pt": tw, "h_pt": dh})
        else:
            cap_preview.update(
                {"x_pt": tx0, "y_top_pt": draw_y_top, "w_pt": tw, "h_pt": ch}
            )
        _preview_finalize_expl_caption(cap_preview, expl)
        return x0, draw_y_top, cap_preview
    if mode == "stacked_top":
        cap_preview.update({"x_pt": x0, "y_top_pt": draw_y_top, "w_pt": inner_w, "h_pt": ch})
        _preview_finalize_expl_caption(cap_preview, expl)
        return x0, draw_y_top - ch - gap, cap_preview
    if mode == "stacked_bottom":
        cap_preview.update(
            {"x_pt": x0, "y_top_pt": draw_y_top - dh - gap, "w_pt": inner_w, "h_pt": ch}
        )
        _preview_finalize_expl_caption(cap_preview, expl)
        return x0, draw_y_top, cap_preview
    return x0, draw_y_top, None


def _apply_y_top_overrides_to_layout_entries(
    layout_entries: List[Dict],
    overrides: Optional[Any],
) -> None:
    m = _coerce_y_top_override_map(overrides)
    if not m:
        return
    for e in layout_entries:
        oi = e.get("order_index")
        if oi in m:
            e["y_top_pt"] = float(m[oi])


def compute_layout_from_payload(
    questions: List[Dict],
    pdf_items: List[PdfItem],
    opts: ExportOptions,
    sections: Optional[List[Dict]] = None,
    layout_y_top_overrides: Optional[Any] = None,
) -> List[Dict]:
    """Compute question positions using flexible layout. Returns layout items for preview."""
    pdf_map = {p.id: p for p in pdf_items}
    page_w, page_h = _page_size_pt(opts)
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    col_gap = mm_to_pt(opts.column_gap_mm)
    cols = max(1, min(6, opts.columns))
    content_w = page_w - ml - mr
    col_w = (content_w - (cols - 1) * col_gap) / cols if cols > 1 else content_w

    question_data = _prepare_question_data_for_layout(
        questions, pdf_map, opts, col_w, sections=sections or []
    )
    if not question_data:
        raise ValueError(
            "Hiçbir soru işlenemedi. "
            "Yerel PDF kullandıysanız soruların image_base64 değeri olmalı. "
            "Sunucuya yüklenmiş PDF kullandıysanız soruların pdf_id değeri sunucudaki PDF ile eşleşmeli."
        )
    layout_entries = _run_layout(question_data, opts)
    _apply_y_top_overrides_to_layout_entries(layout_entries, layout_y_top_overrides)

    _apply_display_numbers_to_layout_entries(layout_entries)

    num_w = _question_number_slot_width_from_layout_entries(layout_entries)

    result: List[Dict] = []

    for entry in layout_entries:
        img_b64 = base64.b64encode(entry["png_bytes"]).decode("ascii")
        y_top = entry["y_top_pt"]
        sec = entry.get("section")
        draw_y_top = float(y_top)
        if sec:
            sec_box_h = sec.get("box_h", 22.0)
            sec_gap = sec.get("gap_after", 8.0)
            y_bottom_sec = y_top - sec_box_h
            draw_y_top = y_bottom_sec - sec_gap
        inner_w = float(
            entry.get(
                "content_inner_w",
                col_w - num_w - _NUM_TO_IMAGE_GAP_PT - _IMG_COL_RIGHT_PAD_PT,
            )
        )
        x_col = float(entry["x_pt"])
        if str(entry.get("content_type") or "question") == "explanation":
            img_x, img_y_top, cap_prev = _preview_expl_for_canvas(
                entry, draw_y_top, x_col, num_w, inner_w
            )
        else:
            img_x = x_col + num_w + _NUM_TO_IMAGE_GAP_PT
            img_y_top = draw_y_top
            cap_prev = None
        result.append({
            "order_index": entry["order_index"],
            "page_num": entry["page_num"],
            "x_pt": x_col,
            "y_top_pt": float(y_top),
            "w_pt": float(col_w),
            "h_pt": float(entry["block_h"]),
            "num_slot_w_pt": float(num_w),
            "img_x_pt": float(img_x),
            "img_y_top_pt": float(img_y_top),
            "img_w_pt": float(entry["draw_w"]),
            "img_h_pt": float(entry["draw_h"]),
            "image_base64": img_b64,
            "answer_key": entry["answer_key"],
            "applied_gap_pt": float(entry.get("applied_gap_pt", 0)),
            "section": entry.get("section"),
            "display_number": entry.get("display_number"),
            "content_type": entry.get("content_type") or "question",
            "explanation_caption": cap_prev,
        })
    return result
