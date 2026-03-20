"""
Desktop-style PDF export - adapted from original-desktop/src/testmaker/services/pdf_exporter.py
Preserves layout, header themes, columns, gaps, and answer key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.core.config import EXPORT_DIR
from app.models.schemas import PdfItem, QuestionItem


def mm_to_pt(mm: float) -> float:
    return float(mm) * 72.0 / 25.4


def pt_to_mm(pt: float) -> float:
    return (pt / 72.0) * 25.4


@dataclass
class ExportOptions:
    """Desktop ExportOptions subset - enough for layout parity."""
    test_title: str = "TEST"
    school_name: str = ""
    theme_color: str = "#AECBFA"
    header_style_id: str = "style3"
    answer_key_enabled: bool = True
    columns: int = 2
    column_gap_mm: float = 8.0
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 15.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0
    question_gap_mm: float = 35.0
    zoom: float = 4.0
    page_preset: str = "A4"


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


def _render_crop(
    pdf_path: Path,
    page_number: int,
    norm_x: float,
    norm_y: float,
    norm_w: float,
    norm_h: float,
    zoom: float = 4.0,
) -> Tuple[bytes, int, int]:
    """Render cropped region as PNG. norm_* are 0..1 (desktop parity). Returns (png_bytes, width_px, height_px)."""
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
        return pix.tobytes("png"), pix.width, pix.height


def _draw_header_style3(
    c: canvas.Canvas,
    page_w: float,
    page_h: float,
    opts: ExportOptions,
) -> float:
    """Style3 header: split boxes. Returns y_start for questions."""
    ml = mm_to_pt(opts.margin_left_mm)
    mr = mm_to_pt(opts.margin_right_mm)
    mt = mm_to_pt(opts.margin_top_mm)
    theme = _hex_to_rgb01(opts.theme_color)
    box_h = 18.0
    box_y = page_h - mt - box_h
    content_w = page_w - ml - mr
    gap = 5.0
    left_w = content_w * 0.35
    mid_w = content_w * 0.30
    right_w = content_w - left_w - mid_w - 2 * gap
    x_left = ml
    x_mid = ml + left_w + gap
    x_right = ml + left_w + mid_w + 2 * gap
    c.saveState()
    c.setLineWidth(0.8)
    c.setStrokeColorRGB(*theme)
    c.setFillColorRGB(1, 1, 1)
    c.roundRect(x_left, box_y, left_w, box_h, 6, fill=1, stroke=1)
    c.roundRect(x_mid, box_y, mid_w, box_h, 6, fill=1, stroke=1)
    c.roundRect(x_right, box_y, right_w, box_h, 6, fill=1, stroke=1)
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(x_mid + mid_w / 2, box_y + 5, (opts.test_title or "TEST")[:40])
    c.setFont("Helvetica", 10)
    c.drawCentredString(x_right + right_w / 2, box_y + 5, (opts.school_name or "")[:50])
    c.restoreState()
    return box_y - 10.0


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
    page_w, page_h = A4
    c = canvas.Canvas(str(out_path), pagesize=A4)
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
    footer_top = mb + 35.0
    theme = _hex_to_rgb01(opts.theme_color)
    page_num = 1
    current_top = _draw_header_style3(c, page_w, page_h, opts)
    col_idx = 0
    x_col = ml + col_idx * (col_w + col_gap)
    y = current_top
    prev_bottom: Dict[int, float] = {}
    page_answers: List[Tuple[int, str]] = []

    def next_col():
        nonlocal col_idx, x_col, y, page_num, current_top
        col_idx += 1
        if col_idx >= cols:
            _draw_footer()
            c.showPage()
            page_num += 1
            current_top = _draw_header_style3(c, page_w, page_h, opts)
            col_idx = 0
            x_col = ml
            y = current_top
            prev_bottom.clear()
        else:
            x_col = ml + col_idx * (col_w + col_gap)
            y = prev_bottom.get(col_idx, current_top)

    def _draw_footer():
        c.saveState()
        c.setLineWidth(0.4)
        c.setStrokeColorRGB(*theme)
        c.line(ml, footer_top, page_w - mr, footer_top)
        c.line(ml, mb + 15, page_w - mr, mb + 15)
        if opts.answer_key_enabled and page_answers:
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(*theme)
            txt = "  ".join(f"{n}. {a or '?'}" for n, a in sorted(page_answers, key=lambda t: t[0]))
            c.drawString(ml, (footer_top + mb + 15) / 2 - 4, txt[:120])
        c.setFont("Helvetica-Bold", 10)
        c.setFillColorRGB(0, 0, 0)
        c.drawCentredString((ml + page_w - mr) / 2, (footer_top + mb + 15) / 2 - 4, str(page_num))
        c.restoreState()
        page_answers.clear()

    sorted_q = sorted(questions, key=lambda q: q.order_index)
    for idx, q in enumerate(sorted_q, start=1):
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
            )
        except Exception:
            continue
        img_w_pt = img_w_px / opts.zoom
        img_h_pt = img_h_px / opts.zoom
        text_scale = 10.0 / 12.0
        draw_w = img_w_pt * text_scale
        draw_h = img_h_pt * text_scale
        box_h = 12.0
        num_text = f"{idx}."
        num_w = 20.0
        avail_w = col_w - num_w - 8
        if draw_w > avail_w:
            s = avail_w / draw_w
            draw_w = avail_w
            draw_h *= s
        q_h = max(box_h, draw_h) + gap_pt
        effective_bottom = footer_top + 15
        if col_idx in prev_bottom:
            y = prev_bottom[col_idx]
        while y - q_h < effective_bottom:
            next_col()
            if col_idx in prev_bottom:
                y = prev_bottom[col_idx]
        y_top = y
        c.setFont("Helvetica-Bold", 10)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(x_col, y_top - 10, num_text)
        ans = (q.answer_key or "").strip().upper() or "?"
        page_answers.append((idx, ans))
        import io
        ir = ImageReader(io.BytesIO(png_bytes))
        c.drawImage(ir, x_col + num_w + 4, y_top - draw_h - 12, width=draw_w, height=draw_h, preserveAspectRatio=True)
        y_bottom = y_top - max(box_h, draw_h) - gap_pt
        prev_bottom[col_idx] = y_bottom
        y = y_bottom

    if page_answers:
        _draw_footer()
    c.save()
    return out_path
