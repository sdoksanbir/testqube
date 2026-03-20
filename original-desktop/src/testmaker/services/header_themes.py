from __future__ import annotations

"""
Header theme renderer used by:
- PDF export (ReportLab canvas)
- Theme selection popup previews (QPainter on QPixmap)

We keep the theme layout in mm units and convert to pt (PDF) or px (preview)
with a shared drawing pipeline.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, Tuple
import re


# -------------------------
# Geometry helpers
# -------------------------


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def mm_to_pt(mm: float) -> float:
    return (mm / 25.4) * 72.0


def pt_to_mm(pt: float) -> float:
    return (pt / 72.0) * 25.4


def clamp(v: float, a: float, b: float) -> float:
    return max(a, min(b, v))


def hex_to_rgb01(hex_color: str, fallback: Tuple[float, float, float] = (0.68, 0.80, 0.98)) -> Tuple[float, float, float]:
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


def mix_rgb(a: Tuple[float, float, float], b: Tuple[float, float, float], t: float) -> Tuple[float, float, float]:
    t = clamp(float(t), 0.0, 1.0)
    return (a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t, a[2] * (1 - t) + b[2] * t)


# -------------------------
# Drawing abstraction
# -------------------------


class Drawer(Protocol):
    def rounded_rect(self, r: Rect, radius: float, *, fill: Optional[Tuple[float, float, float]], stroke: Optional[Tuple[float, float, float]], stroke_w: float) -> None: ...
    def rounded_rect_corners(
        self,
        r: Rect,
        *,
        rtl: float,
        rtr: float,
        rbr: float,
        rbl: float,
        fill: Optional[Tuple[float, float, float]],
        stroke: Optional[Tuple[float, float, float]],
        stroke_w: float,
    ) -> None: ...
    def rect(self, r: Rect, *, fill: Optional[Tuple[float, float, float]], stroke: Optional[Tuple[float, float, float]], stroke_w: float) -> None: ...
    def text_center(self, r: Rect, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None: ...
    def text_left(self, x: float, y: float, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None: ...
    def text_right(self, x: float, y: float, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None: ...
    def measure_text_w(self, text: str, font_size: float, bold: bool) -> float: ...


class ReportLabDrawer:
    """Top-left coordinate system (mm) -> ReportLab canvas (pt, bottom-left)."""

    def __init__(self, c, *, page_w_pt: float, page_h_pt: float):
        self._c = c
        self._pw = page_w_pt
        self._ph = page_h_pt

    def _to_pt_rect(self, r: Rect) -> Tuple[float, float, float, float]:
        x_pt = mm_to_pt(r.x)
        w_pt = mm_to_pt(r.w)
        h_pt = mm_to_pt(r.h)
        # r.y is from top; reportlab y from bottom
        y_pt = self._ph - mm_to_pt(r.y) - h_pt
        return x_pt, y_pt, w_pt, h_pt

    def rounded_rect(self, r: Rect, radius: float, *, fill, stroke, stroke_w: float) -> None:
        x, y, w, h = self._to_pt_rect(r)
        rad_pt = mm_to_pt(radius)
        self._c.saveState()
        try:
            if fill is not None:
                self._c.setFillColorRGB(*fill)
            if stroke is not None:
                self._c.setStrokeColorRGB(*stroke)
            self._c.setLineWidth(max(0.0, stroke_w))
            self._c.roundRect(x, y, w, h, rad_pt, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)
        finally:
            self._c.restoreState()

    def _round_rect_path_pt(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        rtl: float,
        rtr: float,
        rbr: float,
        rbl: float,
    ):
        """Per-corner rounded rect path in ReportLab pt coords (x/y bottom-left)."""
        # clamp to half size
        rtl = max(0.0, min(float(rtl), min(w, h) / 2.0))
        rtr = max(0.0, min(float(rtr), min(w, h) / 2.0))
        rbr = max(0.0, min(float(rbr), min(w, h) / 2.0))
        rbl = max(0.0, min(float(rbl), min(w, h) / 2.0))

        p = self._c.beginPath()
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

    def rounded_rect_corners(self, r: Rect, *, rtl: float, rtr: float, rbr: float, rbl: float, fill, stroke, stroke_w: float) -> None:
        x, y, w, h = self._to_pt_rect(r)
        rtl_pt = mm_to_pt(rtl)
        rtr_pt = mm_to_pt(rtr)
        rbr_pt = mm_to_pt(rbr)
        rbl_pt = mm_to_pt(rbl)
        p = self._round_rect_path_pt(x, y, w, h, rtl=rtl_pt, rtr=rtr_pt, rbr=rbr_pt, rbl=rbl_pt)
        self._c.saveState()
        try:
            if fill is not None:
                self._c.setFillColorRGB(*fill)
            if stroke is not None:
                self._c.setStrokeColorRGB(*stroke)
            self._c.setLineWidth(max(0.0, stroke_w))
            self._c.drawPath(p, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)
        finally:
            self._c.restoreState()

    def rect(self, r: Rect, *, fill, stroke, stroke_w: float) -> None:
        x, y, w, h = self._to_pt_rect(r)
        self._c.saveState()
        try:
            if fill is not None:
                self._c.setFillColorRGB(*fill)
            if stroke is not None:
                self._c.setStrokeColorRGB(*stroke)
            self._c.setLineWidth(max(0.0, stroke_w))
            self._c.rect(x, y, w, h, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)
        finally:
            self._c.restoreState()

    def _font_name(self, bold: bool) -> str:
        # Prefer Roboto (Turkish-friendly) if available; fallback to Helvetica
        try:
            from reportlab.pdfbase.pdfmetrics import getFont

            getFont("Roboto-Bold" if bold else "Roboto")
            return "Roboto-Bold" if bold else "Roboto"
        except Exception:
            return "Helvetica-Bold" if bold else "Helvetica"

    def text_center(self, r: Rect, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None:
        x, y, w, h = self._to_pt_rect(r)
        self._c.saveState()
        try:
            self._c.setFillColorRGB(*color)
            self._c.setFont(self._font_name(bold), font_size)
            self._c.drawCentredString(x + w / 2.0, y + (h / 2.0) - (font_size * 0.35), text)
        finally:
            self._c.restoreState()

    def text_left(self, x: float, y: float, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None:
        # x/y are in mm from top-left baseline-ish
        x_pt = mm_to_pt(x)
        y_pt = self._ph - mm_to_pt(y)
        self._c.saveState()
        try:
            self._c.setFillColorRGB(*color)
            self._c.setFont(self._font_name(bold), font_size)
            self._c.drawString(x_pt, y_pt - (font_size * 0.2), text)
        finally:
            self._c.restoreState()

    def text_right(self, x: float, y: float, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None:
        x_pt = mm_to_pt(x)
        y_pt = self._ph - mm_to_pt(y)
        from reportlab.pdfbase.pdfmetrics import stringWidth

        self._c.saveState()
        try:
            self._c.setFillColorRGB(*color)
            self._c.setFont(self._font_name(bold), font_size)
            w = stringWidth(text, self._font_name(bold), font_size)
            self._c.drawString(x_pt - w, y_pt - (font_size * 0.2), text)
        finally:
            self._c.restoreState()

    def measure_text_w(self, text: str, font_size: float, bold: bool) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        return pt_to_mm(stringWidth(text, self._font_name(bold), font_size))


class QPainterDrawer:
    """Top-left coordinate system (mm) -> QPainter (px)."""

    def __init__(self, p, *, mm_to_px_scale: float):
        from PyQt5.QtCore import Qt as _Qt
        self._p = p
        self._s = float(mm_to_px_scale)
        self._Qt = _Qt

    def _to_px_rect(self, r: Rect) -> Tuple[float, float, float, float]:
        return r.x * self._s, r.y * self._s, r.w * self._s, r.h * self._s

    def _qcolor(self, rgb01: Tuple[float, float, float]):
        from PyQt5.QtGui import QColor

        return QColor(int(rgb01[0] * 255), int(rgb01[1] * 255), int(rgb01[2] * 255))

    def rounded_rect(self, r: Rect, radius: float, *, fill, stroke, stroke_w: float) -> None:
        from PyQt5.QtGui import QPen, QBrush
        from PyQt5.QtCore import QRectF
        x, y, w, h = self._to_px_rect(r)
        rad = radius * self._s
        if fill is None:
            self._p.setBrush(QBrush())
        else:
            self._p.setBrush(QBrush(self._qcolor(fill)))
        if stroke is None or stroke_w <= 0:
            self._p.setPen(self._Qt.NoPen)
        else:
            pen = QPen(self._qcolor(stroke))
            pen.setWidthF(max(0.5, stroke_w))
            self._p.setPen(pen)
        self._p.drawRoundedRect(QRectF(x, y, w, h), rad, rad)

    def rounded_rect_corners(self, r: Rect, *, rtl: float, rtr: float, rbr: float, rbl: float, fill, stroke, stroke_w: float) -> None:
        from PyQt5.QtGui import QPen, QBrush, QPainterPath
        from PyQt5.QtCore import QRectF

        x, y, w, h = self._to_px_rect(r)
        rtl_px = max(0.0, float(rtl) * self._s)
        rtr_px = max(0.0, float(rtr) * self._s)
        rbr_px = max(0.0, float(rbr) * self._s)
        rbl_px = max(0.0, float(rbl) * self._s)
        # clamp radii
        max_r = min(w, h) / 2.0
        rtl_px = min(rtl_px, max_r)
        rtr_px = min(rtr_px, max_r)
        rbr_px = min(rbr_px, max_r)
        rbl_px = min(rbl_px, max_r)

        path = QPainterPath()
        # Start at top-left corner
        path.moveTo(x + rtl_px, y)
        # top edge
        path.lineTo(x + w - rtr_px, y)
        if rtr_px:
            path.arcTo(QRectF(x + w - 2 * rtr_px, y, 2 * rtr_px, 2 * rtr_px), 90, -90)
        # right edge
        path.lineTo(x + w, y + h - rbr_px)
        if rbr_px:
            path.arcTo(QRectF(x + w - 2 * rbr_px, y + h - 2 * rbr_px, 2 * rbr_px, 2 * rbr_px), 0, -90)
        # bottom edge
        path.lineTo(x + rbl_px, y + h)
        if rbl_px:
            path.arcTo(QRectF(x, y + h - 2 * rbl_px, 2 * rbl_px, 2 * rbl_px), 270, -90)
        # left edge
        path.lineTo(x, y + rtl_px)
        if rtl_px:
            path.arcTo(QRectF(x, y, 2 * rtl_px, 2 * rtl_px), 180, -90)
        path.closeSubpath()

        if fill is None:
            self._p.setBrush(QBrush())
        else:
            self._p.setBrush(QBrush(self._qcolor(fill)))
        if stroke is None or stroke_w <= 0:
            self._p.setPen(self._Qt.NoPen)
        else:
            pen = QPen(self._qcolor(stroke))
            pen.setWidthF(max(0.5, stroke_w))
            self._p.setPen(pen)
        self._p.drawPath(path)

    def rect(self, r: Rect, *, fill, stroke, stroke_w: float) -> None:
        from PyQt5.QtGui import QPen, QBrush
        from PyQt5.QtCore import QRectF
        x, y, w, h = self._to_px_rect(r)
        if fill is None:
            self._p.setBrush(QBrush())
        else:
            self._p.setBrush(QBrush(self._qcolor(fill)))
        if stroke is None or stroke_w <= 0:
            self._p.setPen(self._Qt.NoPen)
        else:
            pen = QPen(self._qcolor(stroke))
            pen.setWidthF(max(0.5, stroke_w))
            self._p.setPen(pen)
        self._p.drawRect(QRectF(x, y, w, h))

    def _font(self, size_pt: float, bold: bool):
        from PyQt5.QtGui import QFont
        # Prefer a Turkish-friendly font; Qt will fallback if missing
        f = QFont("Roboto")
        f.setPointSizeF(size_pt)
        f.setBold(bool(bold))
        return f

    def text_center(self, r: Rect, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None:
        from PyQt5.QtCore import QRectF
        x, y, w, h = self._to_px_rect(r)
        self._p.setFont(self._font(font_size, bold))
        self._p.setPen(self._qcolor(color))
        self._p.drawText(QRectF(x, y, w, h), int(self._Qt.AlignCenter), text)

    def text_left(self, x: float, y: float, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None:
        self._p.setFont(self._font(font_size, bold))
        self._p.setPen(self._qcolor(color))
        self._p.drawText(int(x * self._s), int(y * self._s), text)

    def text_right(self, x: float, y: float, text: str, font_size: float, bold: bool, color: Tuple[float, float, float]) -> None:
        from PyQt5.QtGui import QFontMetricsF
        self._p.setFont(self._font(font_size, bold))
        self._p.setPen(self._qcolor(color))
        fm = QFontMetricsF(self._p.font())
        w = fm.horizontalAdvance(text)
        self._p.drawText(int(x * self._s - w), int(y * self._s), text)

    def measure_text_w(self, text: str, font_size: float, bold: bool) -> float:
        from PyQt5.QtGui import QFontMetricsF
        f = self._font(font_size, bold)
        fm = QFontMetricsF(f)
        return (fm.horizontalAdvance(text) / self._s)


# -------------------------
# Theme constants (in mm)
# -------------------------


PAGE_MARGIN_LEFT_MM = 12.0
PAGE_MARGIN_RIGHT_MM = 12.0
HEADER_TOP_MM = 10.0
HEADER_HEIGHT_MM = 22.0
HEADER_HEIGHT_DESC_MM = 42.0
RADIUS_MM = 6.0
GAP_MM = 5.0  # 5px-ish, used in PDF as pt converted from mm? We'll treat as mm for consistency.

def _pt_to_mm_safe(pt: float) -> float:
    try:
        return pt_to_mm(float(pt))
    except Exception:
        return 0.0


def _html_to_text_lines(s: str) -> list[str]:
    t = (s or "").strip()
    if not t:
        return []
    if "<" in t and ">" in t:
        t = re.sub(r"(?i)<br\s*/?>", "\n", t)
        t = re.sub(r"(?i)</p\s*>", "\n", t)
        t = re.sub(r"(?i)<li\s*>", "- ", t)
        t = re.sub(r"(?i)</li\s*>", "\n", t)
        t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\r\n?", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return [ln.strip() for ln in t.splitlines() if ln.strip()]


def _wrap_lines_mm(d: Drawer, lines: list[str], *, max_w_mm: float, font_pt: float, bold: bool) -> list[str]:
    out: list[str] = []
    for raw in lines:
        prefix = ""
        body = raw
        if body.startswith("- "):
            prefix = "• "
            body = body[2:].strip()
        words = body.split()
        if not words:
            continue
        cur = ""
        first = True
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            pref = prefix if first else ("  " if prefix else "")
            if d.measure_text_w(pref + cand, font_pt, bold) <= max_w_mm:
                cur = cand
            else:
                if cur:
                    out.append(pref + cur)
                    first = False
                    cur = w
                else:
                    out.append(pref + w)
                    first = False
                    cur = ""
        if cur:
            pref = prefix if first else ("  " if prefix else "")
            out.append(pref + cur)
    return out


def _ellipsize_mm(d: Drawer, text: str, *, max_w_mm: float, font_pt: float, bold: bool) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    if d.measure_text_w(s, font_pt, bold) <= max_w_mm:
        return s
    ell = "…"
    while s and d.measure_text_w(s + ell, font_pt, bold) > max_w_mm:
        s = s[:-1]
    return (s + ell) if s else ell


def _layout_header_boxes(page_w_mm: float, *, theme_style: str, use_desc: bool) -> Tuple[Rect, Rect, Rect, Rect, Optional[Rect]]:
    """
    Returns (base_rect, left_rect, center_rect, right_rect) in mm units.
    For style1/style2 base_rect is used. For style3, base_rect is the top row container.
    """
    left = PAGE_MARGIN_LEFT_MM
    right = page_w_mm - PAGE_MARGIN_RIGHT_MM
    top = HEADER_TOP_MM
    header_h = HEADER_HEIGHT_DESC_MM if use_desc else HEADER_HEIGHT_MM

    base = Rect(left, top, right - left, header_h)

    gap = GAP_MM

    if theme_style == "style1":
        # Base container starts a bit lower
        base2 = Rect(left, top + 6.0, right - left, HEADER_HEIGHT_MM)
        center = Rect(base2.x + base2.w * 0.225, base2.y - 4.0, base2.w * 0.55, 14.0)
        side = Rect(base2.right - 60.0, base2.y + 1.0, 60.0, 12.0)
        return base2, Rect(0, 0, 0, 0), center, side, None

    if theme_style == "style2":
        bar = Rect(left, top + 6.0, right - left, 16.0)
        tag = Rect(left + 2.0, bar.y - 6.0, 45.0, 10.0)
        side = Rect(bar.right - 55.0, bar.y + 2.0, 55.0, 10.0)
        return bar, tag, Rect(0, 0, 0, 0), side, None

    # style3: split header
    box_h = 14.0
    top_row = Rect(left, top + 6.0, right - left, box_h)
    left_w = top_row.w * 0.35
    mid_w = top_row.w * 0.30
    right_w = top_row.w - left_w - mid_w - 2 * gap
    l = Rect(top_row.x, top_row.y, left_w, box_h)
    c = Rect(l.right + gap, top_row.y, mid_w, box_h)
    r = Rect(c.right + gap, top_row.y, right_w, box_h)
    return top_row, l, c, r, None


def draw_theme_header(
    d: Drawer,
    *,
    page_w_mm: float,
    page_h_mm: float,
    style_id: str,
    theme_color: str,
    test_title: str,
    school_name: str,
    teacher_name: str = "",
    use_description_box: bool,
    test_description: str,
) -> float:
    """
    Draws header (and optional description box) using mm-based layout.
    Returns y_start (mm) where questions should start.
    """
    style_id = (style_id or "style3").strip().lower()
    if style_id not in ("style1", "style2", "style3"):
        style_id = "style3"

    theme = hex_to_rgb01(theme_color)
    fill_very_light = mix_rgb(theme, (1.0, 1.0, 1.0), 0.88)
    fill_light = mix_rgb(theme, (1.0, 1.0, 1.0), 0.75)
    fill_title = mix_rgb(theme, (1.0, 1.0, 1.0), 0.72)
    fill_box = (1.0, 1.0, 1.0)
    text_dark = (0.16, 0.16, 0.16)

    radius = RADIUS_MM
    border_w = 1.6  # thin border like screenshot
    gap_mm = _pt_to_mm_safe(5.0)  # 5px-ish
    # Spacing:
    # - title -> description gap should be smaller
    # - header/desc -> questions gap a bit larger (handled by caller)
    gap_after_mm = _pt_to_mm_safe(8.0)
    gap_title_to_desc_mm = _pt_to_mm_safe(3.0)

    base, left_r, center_r, right_r, _ = _layout_header_boxes(page_w_mm, theme_style=style_id, use_desc=use_description_box)

    # Theme 1 (Style1): center title + left/right boxes with sharp inner corners
    if style_id == "style1":
        left = PAGE_MARGIN_LEFT_MM
        right = page_w_mm - PAGE_MARGIN_RIGHT_MM
        content_w = right - left

        # Typography
        title_font_pt = 18.0

        # Box height: text height + increased top/bottom padding (px-ish ≈ pt here)
        pad_y_mm = _pt_to_mm_safe(4.0)
        box_h = _pt_to_mm_safe(title_font_pt * 1.10) + (2.0 * pad_y_mm)
        y = HEADER_TOP_MM

        title_txt = (test_title or "TEST").strip().upper()
        title_pad_x = 8.0
        title_w = max(40.0, d.measure_text_w(title_txt, title_font_pt, True) + 2 * title_pad_x)
        title_w = min(content_w - 2 * gap_mm, title_w)
        title_x = left + (content_w - title_w) / 2.0

        # Side boxes dynamically fill remaining area
        left_w = max(0.0, (title_x - gap_mm) - left)
        right_x = title_x + title_w + gap_mm
        right_w = max(0.0, right - right_x)

        has_desc = bool(use_description_box and (test_description or "").strip())

        # Corner rules:
        # - Inner corners: sharp always
        # - If description exists: bottom outer corners sharp too
        # - Else: outer corners rounded
        if left_w > 0.5:
            rtl = radius
            rtr = 0.0
            rbr = 0.0
            rbl = 0.0 if has_desc else radius
            d.rounded_rect_corners(
                Rect(left, y, left_w, box_h),
                rtl=rtl,
                rtr=rtr,
                rbr=rbr,
                rbl=rbl,
                fill=fill_box,
                stroke=theme,
                stroke_w=border_w,
            )
            # left box: intentionally empty (no text)

        # Center title box: sharp corners (no radius)
        d.rounded_rect_corners(
            Rect(title_x, y, title_w, box_h),
            rtl=0.0,
            rtr=0.0,
            rbr=0.0,
            rbl=0.0,
            fill=fill_title,
            stroke=theme,
            stroke_w=border_w,
        )
        d.text_center(Rect(title_x, y, title_w, box_h), title_txt, font_size=title_font_pt, bold=True, color=text_dark)

        if right_w > 0.5:
            rtl = 0.0
            rtr = radius
            rbr = 0.0 if has_desc else radius
            rbl = 0.0
            d.rounded_rect_corners(
                Rect(right_x, y, right_w, box_h),
                rtl=rtl,
                rtr=rtr,
                rbr=rbr,
                rbl=rbl,
                fill=fill_box,
                stroke=theme,
                stroke_w=border_w,
            )

        y_cursor = y + box_h + (gap_title_to_desc_mm if has_desc else gap_after_mm)

    elif style_id == "style2":
        # Full bar
        d.rounded_rect(base, radius=radius, fill=fill_light, stroke=theme, stroke_w=border_w)
        d.text_center(base, (test_title or "TEST"), font_size=18, bold=True, color=text_dark)

        # Floating tag
        d.rounded_rect(left_r, radius=radius, fill=(1, 1, 1), stroke=theme, stroke_w=border_w)
        d.text_center(left_r, "Sınav / Ders / Tarih", font_size=11, bold=False, color=text_dark)

        # Side info pill
        info = school_name.strip()
        if info:
            d.rounded_rect(right_r, radius=radius, fill=(1, 1, 1), stroke=theme, stroke_w=border_w)
            d.text_center(right_r, info, font_size=11, bold=False, color=text_dark)

        y_cursor = base.bottom + 4.0

    else:
        # Split header
        if left_r.w > 1:
            d.rounded_rect(left_r, radius=radius, fill=fill_light, stroke=theme, stroke_w=border_w)
            d.text_center(left_r, "", font_size=11, bold=False, color=text_dark)
        if center_r.w > 1:
            d.rounded_rect(center_r, radius=radius, fill=fill_light, stroke=theme, stroke_w=border_w)
            d.text_center(center_r, (test_title or "TEST"), font_size=18, bold=True, color=text_dark)
        if right_r.w > 1:
            d.rounded_rect(right_r, radius=radius, fill=fill_light, stroke=theme, stroke_w=border_w)
            info = school_name.strip() or ""
            d.text_center(right_r, info, font_size=11, bold=False, color=text_dark)

        y_cursor = base.bottom + 4.0

    # Description box: shown only if enabled and non-empty
    if use_description_box and (test_description or "").strip():
        desc_font_pt = 9.0  # requested: smaller
        desc_lines = _wrap_lines_mm(
            d,
            _html_to_text_lines(test_description),
            max_w_mm=(page_w_mm - PAGE_MARGIN_LEFT_MM - PAGE_MARGIN_RIGHT_MM) - 12.0,
            font_pt=desc_font_pt,
            bold=False,
        )
        if desc_lines:
            # Max 3 lines; ellipsize last if needed
            max_lines = 3
            max_w_mm = (page_w_mm - PAGE_MARGIN_LEFT_MM - PAGE_MARGIN_RIGHT_MM) - 12.0
            if len(desc_lines) > max_lines:
                desc_lines = desc_lines[:max_lines]
                desc_lines[-1] = _ellipsize_mm(d, desc_lines[-1], max_w_mm=max_w_mm, font_pt=desc_font_pt, bold=False)

            pad_x = 6.0
            pad_y = 3.0
            line_h = _pt_to_mm_safe(desc_font_pt * 1.35)
            desc_h = pad_y * 2 + len(desc_lines) * line_h
            desc_x = PAGE_MARGIN_LEFT_MM
            desc_w = page_w_mm - PAGE_MARGIN_LEFT_MM - PAGE_MARGIN_RIGHT_MM
            desc_y = y_cursor  # already includes gap_after_mm from header

            # Top corners sharp, bottom corners slightly rounded (reduced radius)
            desc_radius = max(1.5, radius * 0.5)
            d.rounded_rect_corners(
                Rect(desc_x, desc_y, desc_w, desc_h),
                rtl=0.0,
                rtr=0.0,
                rbr=desc_radius,
                rbl=desc_radius,
                fill=(1.0, 1.0, 1.0),
                stroke=theme,
                stroke_w=border_w,
            )

            # draw lines
            y_text = desc_y + pad_y + _pt_to_mm_safe(desc_font_pt)
            for ln in desc_lines:
                d.text_left(desc_x + pad_x, y_text, ln, font_size=desc_font_pt, bold=False, color=text_dark)
                y_text += line_h

            y_cursor = desc_y + desc_h + gap_after_mm

    return y_cursor

