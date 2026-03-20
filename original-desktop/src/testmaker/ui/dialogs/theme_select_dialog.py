from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QPixmap, QFont
from PyQt5.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from testmaker.services.header_themes import QPainterDrawer, draw_theme_header

@dataclass(frozen=True)
class ThemeChoice:
    header_style_id: str  # "style1" | "style2" | "style3"
    theme_color: str      # "#RRGGBB"


def _qcolor(hex_color: str) -> QColor:
    c = QColor(hex_color)
    if not c.isValid():
        c = QColor("#1E88E5")
    return c


class _PreviewCard(QWidget):
    def __init__(self, style_id: str, color_hex: str, show_description: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.style_id = style_id
        self.color_hex = color_hex
        self.show_description = show_description
        self.setFixedSize(280, 90)

    def set_theme(self, color_hex: str, show_description: bool) -> None:
        self.color_hex = color_hex
        self.show_description = show_description
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#2C2C2C"))

        # Scale: A4 width 210mm -> available px width
        pad = 6
        content = self.rect().adjusted(pad, pad, -pad, -pad)
        scale = content.width() / 210.0
        d = QPainterDrawer(p, mm_to_px_scale=scale)

        # draw header on a pseudo page
        draw_theme_header(
            d,
            page_w_mm=210.0,
            page_h_mm=90.0 / scale,
            style_id=self.style_id,
            theme_color=self.color_hex,
            test_title="TEST ADI",
            school_name="OKUL",
            teacher_name="",
            use_description_box=self.show_description,
            test_description="Açıklama...",
        )
        p.end()


class ThemeSelectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        current_style_id: str,
        current_color: str,
        use_description_box: bool,
    ):
        super().__init__(parent)
        self.setWindowTitle("Tema / Başlık Tasarımı Seç")
        self.setModal(True)

        self._use_description_box = bool(use_description_box)
        self._selected_style_id = current_style_id or "style3"
        self._selected_color = current_color or "#1E88E5"

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Styles
        grp_styles = QGroupBox("Başlık Tasarımı")
        styles_layout = QGridLayout(grp_styles)
        styles_layout.setHorizontalSpacing(16)
        styles_layout.setVerticalSpacing(10)

        self._style_group = QButtonGroup(self)
        self._style_group.setExclusive(True)

        styles: List[Tuple[str, str]] = [
            ("style1", "Style 1"),
            ("style2", "Style 2"),
            ("style3", "Style 3"),
        ]

        self._previews: List[_PreviewCard] = []
        for idx, (sid, label) in enumerate(styles):
            col = idx
            rb = QRadioButton(f"{label} ({'Açıklamalı' if self._use_description_box else 'Açıklamasız'})")
            self._style_group.addButton(rb)
            rb.setProperty("style_id", sid)
            if sid == self._selected_style_id:
                rb.setChecked(True)

            preview = _PreviewCard(sid, self._selected_color, self._use_description_box)
            self._previews.append(preview)

            box = QVBoxLayout()
            box.addWidget(preview, alignment=Qt.AlignCenter)
            box.addWidget(rb, alignment=Qt.AlignCenter)
            w = QWidget()
            w.setLayout(box)
            styles_layout.addWidget(w, 0, col)

        root.addWidget(grp_styles)

        # Colors
        grp_colors = QGroupBox("Tema Rengi (Canlı)")
        colors_layout = QHBoxLayout(grp_colors)
        colors_layout.setSpacing(10)

        # Canlı renkler (öncelik: kırmızı, mavi, turuncu, yeşil)
        swatches = ["#E53935", "#1E88E5", "#FB8C00", "#43A047", "#8E24AA"]
        for col in swatches:
            b = QPushButton()
            b.setFixedSize(QSize(34, 24))
            b.setStyleSheet(f"background-color:{col}; border:1px solid #FFFFFF; border-radius:6px;")
            b.clicked.connect(lambda _=False, c=col: self._set_color(c))
            colors_layout.addWidget(b)

        btn_pick = QPushButton("Renk Seç…")
        btn_pick.clicked.connect(self._pick_color)
        colors_layout.addStretch(1)
        colors_layout.addWidget(btn_pick)

        root.addWidget(grp_colors)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("İptal")
        btn_apply = QPushButton("Uygula")
        btn_cancel.clicked.connect(self.reject)
        btn_apply.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_apply)
        root.addLayout(btn_row)

        self._style_group.buttonClicked.connect(self._on_style_changed)

        self._refresh_previews()

    def _on_style_changed(self):
        b = self._style_group.checkedButton()
        if b:
            self._selected_style_id = str(b.property("style_id") or "style3")
        self._refresh_previews()

    def _set_color(self, hex_color: str) -> None:
        self._selected_color = hex_color
        self._refresh_previews()

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(_qcolor(self._selected_color), self, "Tema Rengi Seç")
        if c.isValid():
            self._set_color(c.name().upper())

    def _refresh_previews(self) -> None:
        for pv in self._previews:
            pv.set_theme(self._selected_color, self._use_description_box)

    def result_choice(self) -> ThemeChoice:
        return ThemeChoice(header_style_id=self._selected_style_id, theme_color=self._selected_color)

