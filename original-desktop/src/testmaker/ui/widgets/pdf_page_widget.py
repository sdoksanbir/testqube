from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.QtGui import (
    QPainter, QPixmap, QPen, QBrush, QFont, QPainterPath, QFontMetrics, QColor
)
from PyQt5.QtCore import Qt, QRect, QPoint, QSize, QRectF, pyqtSignal


class PDFPageWidget(QWidget):
    """
    Sadece çizim ve tıklama işlerini yapar.
    Seçim ekleme/silme için parent'tan callback bekler:
      - on_request_new_selection(norm_rect)
      - on_request_delete_selection(selection)
      - on_request_edit_selection(selection)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm_orig: QPixmap = None
        self.pm_scaled: QPixmap = None
        self.scale: float = 1.0
        self.selections = []  # sadece bu sayfaya ait Selection objeleri
        self.drag_start: QPoint = None
        self.drag_rect_screen: QRect = None
        self._handle_size = 8  # px
        self._button_height = 24  # px
        self._selected_selection = None
        self._handle_hover = None
        self._button_hover = None
        self._resize_handle = None
        self._is_dragging = False
        self._is_resizing = False
        self.selection_enabled = False
        self.initial_rect: QRect = None  # Taşıma ve yeniden boyutlandırma için başlangıç kutusu

        self.setMouseTracking(True)

        self.on_request_new_selection = None
        self.on_request_delete_selection = None
        self.on_request_edit_selection = None

    def set_selection_enabled(self, enabled):
        self.selection_enabled = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    # --- koordinatlar ---
    def norm_to_orig_rect(self, norm_rect) -> QRect:
        fx, fy, fw, fh = norm_rect
        if not self.pm_orig:
            return QRect()
        w = self.pm_orig.width()
        h = self.pm_orig.height()
        return QRect(int(fx * w), int(fy * h), int(fw * w), int(fh * h))

    def orig_to_screen_rect(self, r: QRect) -> QRect:
        s = self.scale
        return QRect(int(r.x() * s), int(r.y() * s), int(r.width() * s), int(r.height() * s))

    def screen_to_norm_rect(self, r: QRect):
        if not self.pm_orig:
            return (0, 0, 0, 0)
        s = self.scale
        ox = r.x() / s
        oy = r.y() / s
        ow = r.width() / s
        oh = r.height() / s
        w, h = self.pm_orig.width(), self.pm_orig.height()
        fx = max(0.0, min(1.0, ox / w))
        fy = max(0.0, min(1.0, oy / h))
        fw = max(0.0, min(1.0, ow / w))
        fh = max(0.0, min(1.0, oh / h))
        return (fx, fy, fw, fh)

    # --- sayfa & zoom ---
    def set_page_pixmap(self, pm: QPixmap):
        self.pm_orig = pm
        self.apply_scale(self.scale, repaint_only=False)

    def apply_scale(self, new_scale: float, repaint_only=False):
        if not self.pm_orig:
            return
        self.scale = max(0.1, float(new_scale))
        if not repaint_only:
            sw = max(1, int(self.pm_orig.width() * self.scale))
            sh = max(1, int(self.pm_orig.height() * self.scale))
            self.pm_scaled = self.pm_orig.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.setFixedSize(self.pm_scaled.size())
        if self.drag_rect_screen:
            norm = self.screen_to_norm_rect(self.drag_rect_screen)
            self.drag_rect_screen = self.orig_to_screen_rect(self.norm_to_orig_rect(norm))
        self.update()

    def _get_handles(self, r_screen: QRect):
        """Dikdörtgenin köşelerinde ve kenarlarında tutamaçlar oluşturur"""
        handles = {}
        half = self._handle_size // 2

        # Köşeler
        handles["top_left"] = QRect(r_screen.left() - half, r_screen.top() - half, self._handle_size, self._handle_size)
        handles["top_right"] = QRect(r_screen.right() - half, r_screen.top() - half, self._handle_size,
                                     self._handle_size)
        handles["bottom_left"] = QRect(r_screen.left() - half, r_screen.bottom() - half, self._handle_size,
                                       self._handle_size)
        handles["bottom_right"] = QRect(r_screen.right() - half, r_screen.bottom() - half, self._handle_size,
                                        self._handle_size)

        # Kenarlar
        handles["top"] = QRect(r_screen.center().x() - half, r_screen.top() - half, self._handle_size,
                               self._handle_size)
        handles["bottom"] = QRect(r_screen.center().x() - half, r_screen.bottom() - half, self._handle_size,
                                  self._handle_size)
        handles["left"] = QRect(r_screen.left() - half, r_screen.center().y() - half, self._handle_size,
                                self._handle_size)
        handles["right"] = QRect(r_screen.right() - half, r_screen.center().y() - half, self._handle_size,
                                 self._handle_size)

        return handles

    def _get_buttons(self, r_screen: QRect):
        buttons = {}
        metrics = QFontMetrics(QFont("Arial", 12, QFont.Bold))
        padding = 8

        text_edit = "Düzenle"
        w_edit = metrics.horizontalAdvance(text_edit) + 2 * padding
        h_edit = self._button_height
        x_edit = r_screen.right() - w_edit * 2 - 4
        y_edit = r_screen.top() - h_edit - 2
        buttons["edit"] = QRect(x_edit, y_edit, w_edit, h_edit)

        text_del = "Soru Sil"
        w_del = metrics.horizontalAdvance(text_del) + 2 * padding
        h_del = self._button_height
        x_del = r_screen.right() - w_del
        y_del = r_screen.top() - h_del - 2
        buttons["delete"] = QRect(x_del, y_del, w_del, h_del)

        return buttons

    # --- mouse ---
    def mousePressEvent(self, e):
        if not self.pm_scaled or not self.selection_enabled:
            return

        pos = e.pos()
        self._selected_selection = None
        self._resize_handle = None
        self._is_dragging = False
        self._is_resizing = False

        # Önce butonları kontrol et
        for sel in list(self.selections):
            r_screen = self.orig_to_screen_rect(self.norm_to_orig_rect(sel.norm))
            buttons = self._get_buttons(r_screen)

            if buttons["delete"].contains(pos):
                if self.on_request_delete_selection:
                    self.on_request_delete_selection(sel)
                return
            if buttons["edit"].contains(pos):
                if self.on_request_edit_selection:
                    self.on_request_edit_selection(sel)
                return

        # Sonra tutamaçları kontrol et
        for sel in list(self.selections):
            r_screen = self.orig_to_screen_rect(self.norm_to_orig_rect(sel.norm))
            handles = self._get_handles(r_screen)

            for handle_name, handle_rect in handles.items():
                if handle_rect.contains(pos):
                    self._selected_selection = sel
                    self._resize_handle = handle_name
                    self._is_resizing = True
                    self.drag_start = pos
                    self.initial_rect = QRect(r_screen)
                    return

        # En son kutunun içini kontrol et
        for sel in list(self.selections):
            r_screen = self.orig_to_screen_rect(self.norm_to_orig_rect(sel.norm))
            if r_screen.contains(pos):
                self._selected_selection = sel
                self._is_dragging = True
                self.drag_start = pos
                self.initial_rect = QRect(r_screen)
                return

        # Hiçbir şeye basılmadıysa yeni bir seçim başlat
        if e.button() == Qt.LeftButton and self.selection_enabled:
            self.drag_start = e.pos()
            self.drag_rect_screen = QRect(self.drag_start, self.drag_start)
            self.update()

    def mouseMoveEvent(self, e):
        pos = e.pos()

        # Sürükleme veya boyutlandırma işlemi başlamadıysa
        if not (self._is_resizing or self._is_dragging):
            cursor_set = False
            # İmleci tutamaçların üzerine geldiğinde değiştir
            for sel in list(self.selections):
                r_screen = self.orig_to_screen_rect(self.norm_to_orig_rect(sel.norm))
                buttons = self._get_buttons(r_screen)
                if buttons["delete"].contains(pos) or buttons["edit"].contains(pos):
                    self.setCursor(Qt.PointingHandCursor)
                    cursor_set = True
                    break

                handles = self._get_handles(r_screen)
                for handle_name, handle_rect in handles.items():
                    if handle_rect.contains(pos):
                        if handle_name in ["top_left", "bottom_right"]:
                            self.setCursor(Qt.SizeFDiagCursor)
                        elif handle_name in ["top_right", "bottom_left"]:
                            self.setCursor(Qt.SizeBDiagCursor)
                        elif handle_name in ["top", "bottom"]:
                            self.setCursor(Qt.SizeVerCursor)
                        elif handle_name in ["left", "right"]:
                            self.setCursor(Qt.SizeHorCursor)
                        cursor_set = True
                        break
                if cursor_set:
                    break

                if r_screen.contains(pos):
                    self.setCursor(Qt.SizeAllCursor)
                    cursor_set = True
                    break

            if not cursor_set:
                self.setCursor(Qt.CrossCursor if self.selection_enabled else Qt.ArrowCursor)

            # Yeni seçim dikdörtgenini çiz
            if self.drag_start and self.selection_enabled:
                self.drag_rect_screen = QRect(self.drag_start, e.pos()).normalized()
                self.update()
            return

        # Buradan sonrası sadece sürükleme veya yeniden boyutlandırma işlemi başladığında çalışır
        if self._is_resizing and self._selected_selection:
            delta = pos - self.drag_start
            new_rect = QRect(self.initial_rect)

            if "top" in self._resize_handle:
                new_rect.setTop(self.initial_rect.top() + delta.y())
            if "bottom" in self._resize_handle:
                new_rect.setBottom(self.initial_rect.bottom() + delta.y())
            if "left" in self._resize_handle:
                new_rect.setLeft(self.initial_rect.left() + delta.x())
            if "right" in self._resize_handle:
                new_rect.setRight(self.initial_rect.right() + delta.x())

            if new_rect.width() > 10 and new_rect.height() > 10:
                self._selected_selection.norm = self.screen_to_norm_rect(new_rect.normalized())

            self.update()
            return

        if self._is_dragging and self._selected_selection:
            delta = pos - self.drag_start
            new_rect = QRect(self.initial_rect)
            new_rect.translate(delta)
            self._selected_selection.norm = self.screen_to_norm_rect(new_rect)
            self.update()
            return

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag_start and self.selection_enabled and not self._is_dragging and not self._is_resizing:
            rect_screen = QRect(self.drag_start, e.pos()).normalized()
            self.drag_start = None
            self.drag_rect_screen = None
            if rect_screen.width() >= 4 and rect_screen.height() >= 4:
                norm = self.screen_to_norm_rect(rect_screen)
                if self.on_request_new_selection:
                    self.on_request_new_selection(norm)
            self.update()

        self._is_dragging = False
        self._is_resizing = False
        self._selected_selection = None
        self._resize_handle = None
        self.drag_start = None

        if self.selection_enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    # --- çizim ---
    def _draw_rounded_rect(self, painter, rect, radius=4):
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.drawPath(path)

    def paintEvent(self, e):
        if not self.pm_scaled:
            return
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pm_scaled)

        if self.drag_rect_screen and self.selection_enabled:
            p.setBrush(QBrush(QColor(0, 0, 0, 100)))
            p.setPen(Qt.NoPen)
            p.drawRect(0, 0, self.width(), self.drag_rect_screen.top())
            p.drawRect(0, self.drag_rect_screen.top(), self.drag_rect_screen.left(),
                       self.drag_rect_screen.height())
            p.drawRect(self.drag_rect_screen.right(), self.drag_rect_screen.top(),
                       self.width() - self.drag_rect_screen.right(), self.drag_rect_screen.height())
            p.drawRect(0, self.drag_rect_screen.bottom(), self.width(),
                       self.height() - self.drag_rect_screen.bottom())

        selection_pen = QPen(QColor(220, 0, 0), 3, Qt.SolidLine)
        label_font = QFont("Arial", 13, QFont.Bold)
        p.setFont(label_font)

        for sel in self.selections:
            r_screen = self.orig_to_screen_rect(self.norm_to_orig_rect(sel.norm))
            if r_screen.width() <= 0 or r_screen.height() <= 0:
                continue

            p.setBrush(Qt.NoBrush)
            p.setPen(selection_pen)
            p.drawRect(r_screen)

            handles = self._get_handles(r_screen)
            p.setBrush(QBrush(QColor(220, 0, 0)))
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for handle_rect in handles.values():
                p.drawRect(handle_rect)

            buttons = self._get_buttons(r_screen)
            radius = 4

            metrics = p.fontMetrics()
            pad = 8
            text1 = f"Soru {getattr(sel, 'number', '?')}"
            w1 = metrics.horizontalAdvance(text1) + 2 * pad
            h1 = self._button_height
            rect1 = QRect(r_screen.left(), r_screen.top() - h1 - 2, w1, h1)

            p.setBrush(QBrush(QColor(239, 83, 80)))
            p.setPen(Qt.white)
            self._draw_rounded_rect(p, rect1, radius)
            p.drawText(rect1, Qt.AlignCenter, text1)

            answer_text = "Cevap: "
            if sel.answer is None or sel.answer == "?":
                answer_text += "?"
                color_bg = QColor(158, 158, 158)
            else:
                answer_text += str(sel.answer)
                color_bg = QColor(102, 187, 106)

            w2 = metrics.horizontalAdvance(answer_text) + 2 * pad
            h2 = self._button_height
            rect2 = QRect(r_screen.left(), r_screen.bottom() + 2, w2, h2)

            p.setBrush(QBrush(color_bg))
            p.setPen(Qt.white)
            self._draw_rounded_rect(p, rect2, radius)
            p.drawText(rect2, Qt.AlignCenter, answer_text)

            btn_font = QFont("Arial", 13, QFont.Bold)
            p.setFont(btn_font)
            metrics = QFontMetrics(btn_font)
            btn_padding = 6

            del_text = "Soru Sil"
            del_width = metrics.horizontalAdvance(del_text) + btn_padding * 2
            del_height = self._button_height
            del_rect = QRect(r_screen.right() - del_width,
                             r_screen.top() - del_height - 2,
                             del_width,
                             del_height)

            edit_text = "Düzenle"
            edit_width = metrics.horizontalAdvance(edit_text) + btn_padding * 2
            edit_height = self._button_height
            edit_rect = QRect(del_rect.left() - 4 - edit_width,
                              r_screen.top() - edit_height - 2,
                              edit_width,
                              edit_height)

            p.setBrush(QBrush(QColor(158, 158, 158)))
            p.setPen(Qt.white)
            self._draw_rounded_rect(p, edit_rect, radius)
            p.drawText(edit_rect, Qt.AlignCenter, edit_text)

            p.setBrush(QBrush(QColor(66, 165, 245)))
            p.setPen(Qt.white)
            self._draw_rounded_rect(p, del_rect, radius)
            p.drawText(del_rect, Qt.AlignCenter, del_text)