import os
import fitz
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QPushButton, QComboBox, QScrollArea, QSlider,
    QSpinBox, QWidget, QHBoxLayout, QVBoxLayout, QMessageBox, QFileDialog, QDialog
)
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage

from testmaker.ui.widgets.pdf_page_widget import PDFPageWidget
from testmaker.models.selection import Selection
from testmaker.ui.dialogs.answer_dialog import AnswerDialog
from testmaker.utils.qimage_utils import qimage_from_fitz_pix


class PDFViewer(QMainWindow):
    selection_list_ready = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tesqube Builder — Çoklu PDF & Numaralandırma")
        # Başlangıçta tam ekran açılacak (open_crop_tool'da showMaximized çağrılıyor)
        # PDF yüklendiğinde genişlik PDF genişliğine göre ayarlanacak
        self.setGeometry(100, 60, 1280, 900)

        # state
        self.pdf_docs = {}
        self.current_pdf = None
        self.page_index = 0
        self.render_dpi = 300
        self.global_sequence = []
        self.pdf_page_indices = {}
        self.pdf_zoom_settings = {}  # Her PDF için ayrı zoom ayarı

        # Üst bar
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("PDF:"))
        self.cmb_pdf = QComboBox()
        self.cmb_pdf.setEnabled(False)
        self.cmb_pdf.currentIndexChanged.connect(self._combo_pdf_changed)
        top_layout.addWidget(self.cmb_pdf, 2)

        self.btn_add_pdf = QPushButton("PDF Ekle")
        self.btn_add_pdf.setStyleSheet("""
            QPushButton {
                background-color: #9CAFAA;
                color: white;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 15px;
                border: none;
            }
            QPushButton:hover {
                background-color: #7A9A8A;
            }
            QPushButton:pressed {
                background-color: #6A8A7A;
            }
        """)
        self.btn_add_pdf.clicked.connect(self.add_pdf)
        top_layout.addWidget(self.btn_add_pdf)

        self.btn_list_questions = QPushButton("Soruları Listele")
        self.btn_list_questions.setStyleSheet("""
            QPushButton {
                background-color: #D6A99D;
                color: white;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 15px;
                border: none;
            }
            QPushButton:hover {
                background-color: #C6998D;
            }
            QPushButton:pressed {
                background-color: #B6897D;
            }
        """)
        self.btn_list_questions.clicked.connect(self.show_question_list)
        top_layout.addWidget(self.btn_list_questions)

        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("DPI:"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 600)
        self.spin_dpi.setValue(300)  # render_dpi ile eşleştir
        self.spin_dpi.valueChanged.connect(self.change_dpi)
        top_layout.addWidget(self.spin_dpi)
        top_layout.addStretch(1)

        # Orta alan
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.page = PDFPageWidget()
        self.scroll.setWidget(self.page)

        # Callbacks
        self.page.on_request_new_selection = self._handle_new_selection
        self.page.on_request_delete_selection = self._handle_delete_selection
        self.page.on_request_edit_selection = self._handle_edit_selection

        # Alt bar
        self.btn_prev = QPushButton("⟨ Önceki")
        self.btn_prev.setStyleSheet("""
            QPushButton {
                background-color: #748DAE;
                color: white;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 15px;
                border: none;
            }
            QPushButton:hover {
                background-color: #5A6D8E;
            }
            QPushButton:pressed {
                background-color: #4A5D7E;
            }
            QPushButton:disabled {
                background-color: #CCCCCC;
                color: #888888;
            }
        """)
        self.btn_prev.clicked.connect(lambda: self.go_to_page(self.page_index - 1))
        self.btn_next = QPushButton("Sonraki ⟩")
        self.btn_next.setStyleSheet("""
            QPushButton {
                background-color: #748DAE;
                color: white;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 15px;
                border: none;
            }
            QPushButton:hover {
                background-color: #5A6D8E;
            }
            QPushButton:pressed {
                background-color: #4A5D7E;
            }
            QPushButton:disabled {
                background-color: #CCCCCC;
                color: #888888;
            }
        """)
        self.btn_next.clicked.connect(lambda: self.go_to_page(self.page_index + 1))

        self.cmb_page = QComboBox()
        self.cmb_page.setEnabled(False)
        self.cmb_page.currentIndexChanged.connect(self._combo_page_changed)

        self.btn_save_all = QPushButton("Seçimleri Kaydet (Tüm PDF'ler)")
        self.btn_save_all.setStyleSheet("""
            QPushButton {
                background-color: #82e0aa;
                color: #1d1d1d;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: bold;
                font-size: 15px;
                border: 2px solid #82e0aa;
            }
            QPushButton:hover {
                background-color: white;
                color: #82e0aa;
                border: 2px solid #82e0aa;
            }
            QPushButton:pressed {
                background-color: #72d09a;
            }
        """)
        self.btn_save_all.clicked.connect(self.save_all_selections)

        self.lbl_zoom = QLabel("Zoom:")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(10)
        self.slider.setMaximum(400)
        self.slider.setValue(100)
        self.slider.setFixedWidth(160)
        self.slider.valueChanged.connect(self.on_zoom_changed)

        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.btn_next)
        bottom.addSpacing(10)
        bottom.addWidget(QLabel("Sayfa:"))
        bottom.addWidget(self.cmb_page)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_save_all)
        bottom.addSpacing(20)
        bottom.addWidget(self.lbl_zoom)
        bottom.addWidget(self.slider)

        # Ana düzen
        main_layout = QVBoxLayout()
        top_widget = QWidget();
        top_widget.setLayout(top_layout)
        main_layout.addWidget(top_widget)
        main_layout.addWidget(self.scroll, 1)
        bottom_widget = QWidget();
        bottom_widget.setLayout(bottom)
        main_layout.addWidget(bottom_widget)

        wrap = QWidget();
        wrap.setLayout(main_layout)
        self.setCentralWidget(wrap)

        self.status = self.statusBar()
        self._update_status()

    # ---------- helpers ----------
    def _update_status(self):
        if self.current_pdf:
            doc = self.pdf_docs[self.current_pdf]
            self.status.showMessage(
                f"PDF: {self.current_pdf} | Sayfa {self.page_index + 1}/{len(doc)} | "
                f"DPI: {self.render_dpi} | Zoom: {int(self.page.scale * 100)}% | "
                f"Toplam Soru: {len(self.global_sequence)}"
            )
        else:
            self.status.showMessage("PDF ekleyin.")

    def _unique_pdf_key(self, path):
        base = os.path.basename(path)
        key = base
        i = 2
        while key in self.pdf_docs:
            name, ext = os.path.splitext(base)
            key = f"{name} ({i}){ext}"
            i += 1
        return key

    # ---------- PDF işlemleri ----------
    def add_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF Ekle", "", "PDF Files (*.pdf)")
        if not path:
            return
        try:
            doc = fitz.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"PDF açılamadı:\n{e}")
            return
        key = self._unique_pdf_key(path)
        self.pdf_docs[key] = doc

        self.cmb_pdf.setEnabled(True)
        self.cmb_pdf.addItem(key)
        self.cmb_pdf.setCurrentText(key)
        self.page.set_selection_enabled(True)
        
        # current_pdf'i ayarla (render için gerekli)
        self.current_pdf = key
        self.page_index = 0
        
        # Önce PDF'i render et (pm_orig'yi almak için)
        self._render_current()
        
        # PDF genişliğini pencere genişliğine göre zoom hesapla ve ayarla
        if self.page.pm_orig:
            # Render edilmiş PDF'in genişliğini al
            pdf_width_px = self.page.pm_orig.width()
            
            # Pencere genişliğini al
            window_width = self.width()
            
            # ScrollArea için alan bırak (scrollbar + margin)
            available_width = window_width - 240
            
            # PDF genişliğini pencere genişliğine sığdıracak zoom hesapla
            if pdf_width_px > 0:
                calculated_zoom_percent = int((available_width / pdf_width_px) * 100)
                # Zoom sınırları içinde tut (10% - 400%)
                calculated_zoom_percent = max(10, min(400, calculated_zoom_percent))
            else:
                calculated_zoom_percent = 100
            
            # Bu PDF için zoom ayarını kaydet
            self.pdf_zoom_settings[key] = calculated_zoom_percent
            
            # Slider'ı ve sayfayı güncelle
            self.slider.setValue(calculated_zoom_percent)
            self.page.apply_scale(calculated_zoom_percent / 100.0)
        
        self._refresh_current_page_selections()
        self._update_status()

    def change_dpi(self, dpi):
        self.render_dpi = dpi
        if self.current_pdf:
            self._render_current()
            self._update_status()

    def _combo_pdf_changed(self, idx):
        if idx < 0 or idx >= self.cmb_pdf.count(): return
        key = self.cmb_pdf.itemText(idx)
        if not key: return

        self.current_pdf = key
        self.page_index = self.pdf_page_indices.get(key, 0)
        self._populate_page_combo()
        
        # Önce render et (pm_orig'yi almak için)
        self._render_current()
        
        # Eğer bu PDF için zoom ayarı yoksa, pencere genişliğine göre hesapla
        if key not in self.pdf_zoom_settings:
            if self.page.pm_orig:
                # Render edilmiş PDF'in genişliğini al
                pdf_width_px = self.page.pm_orig.width()
                
                # Pencere genişliğini al
                window_width = self.width()
                
                # ScrollArea için alan bırak
                available_width = window_width - 240
                
                # PDF genişliğini pencere genişliğine sığdıracak zoom hesapla
                if pdf_width_px > 0:
                    calculated_zoom_percent = int((available_width / pdf_width_px) * 100)
                    calculated_zoom_percent = max(10, min(400, calculated_zoom_percent))
                    self.pdf_zoom_settings[key] = calculated_zoom_percent
                else:
                    self.pdf_zoom_settings[key] = 100
        
        # Bu PDF'in zoom ayarını yükle ve uygula
        zoom_value = self.pdf_zoom_settings.get(key, 100)
        self.slider.setValue(zoom_value)
        self.page.apply_scale(zoom_value / 100.0)
        
        self._refresh_current_page_selections()
        self._update_status()
        self.page.set_selection_enabled(True)

    def _populate_page_combo(self):
        self.cmb_page.blockSignals(True)
        self.cmb_page.clear()
        if self.current_pdf:
            n = len(self.pdf_docs[self.current_pdf])
            for i in range(n):
                self.cmb_page.addItem(str(i + 1))
            self.cmb_page.setEnabled(True)
            self.cmb_page.setCurrentIndex(self.page_index)
        else:
            self.cmb_page.setEnabled(False)
        self.cmb_page.blockSignals(False)

    def _combo_page_changed(self, idx):
        if not self.current_pdf: return
        if idx != self.page_index:
            self.go_to_page(idx)

    def _render_current(self):
        if not self.current_pdf: return
        doc = self.pdf_docs[self.current_pdf]
        page = doc.load_page(self.page_index)
        zoom = self.render_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))
        self.page.set_page_pixmap(pm)
        # Zoom uygulaması render'dan sonra yapılacak

    def _refresh_current_page_selections(self):
        current = []
        for sel in self.global_sequence:
            if sel.pdf_key == self.current_pdf and sel.page_index == self.page_index:
                current.append(sel)
        self.page.selections = current
        self.page.update()

    # ---------- sayfa / zoom ----------
    def go_to_page(self, new_index):
        if not self.current_pdf: return
        doc = self.pdf_docs[self.current_pdf]
        if new_index < 0 or new_index >= len(doc): return

        self.page_index = new_index
        self.pdf_page_indices[self.current_pdf] = new_index

        self._render_current()
        self._refresh_current_page_selections()
        self.cmb_page.blockSignals(True)
        self.cmb_page.setCurrentIndex(self.page_index)
        self.cmb_page.blockSignals(False)
        self._update_status()

    def on_zoom_changed(self, val):
        # Mevcut PDF'in zoom ayarını kaydet
        if self.current_pdf:
            self.pdf_zoom_settings[self.current_pdf] = val
        self.page.apply_scale(val / 100.0)
        self._update_status()

    # ---------- seçim işlemleri ----------
    def _handle_new_selection(self, norm_rect):
        if not self.current_pdf:
            return

        dlg = AnswerDialog(parent=self, is_first_selection=True)
        if dlg.exec_() == QDialog.Accepted:
            ans = dlg.choice

            if not self.page.pm_scaled:
                return

            rect_screen_initial = self.page.orig_to_screen_rect(
                self.page.norm_to_orig_rect(norm_rect)
            )
            cropped_pixmap = self.page.pm_scaled.copy(rect_screen_initial)
            cropped_image_cv2 = self.qpixmap_to_cv2(cropped_pixmap)

            gray = cv2.cvtColor(cropped_image_cv2, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)[1]

            y_coords, x_coords = np.where(thresh > 0)

            if len(y_coords) > 0 and len(x_coords) > 0:
                x_min = np.min(x_coords)
                y_min = np.min(y_coords)
                x_max = np.max(x_coords)
                y_max = np.max(y_coords)

                # Boşluk Ayarları
                padding_horizontal = 10  # Sağ ve sol için 20 piksel boşluk
                padding_vertical = 5  # Üst ve alt için 10 piksel boşluk

                x_min = max(0, x_min - padding_horizontal)
                y_min = max(0, y_min - padding_vertical)
                x_max = min(cropped_image_cv2.shape[1] - 1, x_max + padding_horizontal)
                y_max = min(cropped_image_cv2.shape[0] - 1, y_max + padding_vertical)

                new_rect = QRect(int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min)).normalized()

                final_screen_rect = new_rect.translated(rect_screen_initial.topLeft())
                norm_rect = self.page.screen_to_norm_rect(final_screen_rect)
            else:
                QMessageBox.information(self, "Bilgi",
                                        "Seçim alanında metin veya görsel bulunamadı. Orijinal kutu kullanılacak.")

            sel = Selection(norm_rect, ans, self.current_pdf, self.page_index)
            sel.viewer = self
            self.global_sequence.append(sel)
            self._renumber_global()
            self._refresh_current_page_selections()
            self._update_status()

    def _handle_delete_selection(self, sel: Selection):
        try:
            self.global_sequence.remove(sel)
        except ValueError:
            pass
        self._renumber_global()
        self._refresh_current_page_selections()
        self._update_status()

    def _handle_edit_selection(self, sel: Selection):
        dlg = AnswerDialog(current_answer=sel.answer, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            sel.answer = dlg.choice
            self._refresh_current_page_selections()
            self._update_status()

    def _renumber_global(self):
        for i, sel in enumerate(self.global_sequence, start=1):
            sel.number = i

    def update_global_sequence(self, new_sequence):
        self.global_sequence = new_sequence
        self._renumber_global()
        self._update_status()
        self._refresh_current_page_selections()

    def save_all_selections(self):
        if not self.global_sequence:
            QMessageBox.information(self, "Bilgi", "Kaydedilecek seçim yok.")
            return
        out_dir = "thumbnails"
        os.makedirs(out_dir, exist_ok=True)
        total = 0
        for sel in self.global_sequence:
            doc = self.pdf_docs.get(sel.pdf_key)
            if not doc: continue
            page = doc.load_page(sel.page_index)
            zoom = self.render_dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))

            fx, fy, fw, fh = sel.norm
            r = QRect(int(fx * pm.width()), int(fy * pm.height()),
                      int(fw * pm.width()), int(fh * pm.height()))
            r = r.intersected(QRect(0, 0, pm.width(), pm.height()))
            if r.width() <= 0 or r.height() <= 0:
                continue
            cropped = pm.copy(r)
            safe_pdf = os.path.splitext(os.path.basename(sel.pdf_key))[0].replace(" ", "_")

            ans_str = sel.answer if sel.answer is not None else "no-ans"
            out_path = os.path.join(out_dir,
                                    f"Q{sel.number:03d}_({safe_pdf})_p{sel.page_index + 1}_ans-{ans_str}.png")
            cropped.save(out_path, "PNG")
            total += 1
        QMessageBox.information(self, "Bilgi", f"{total} seçim '{out_dir}/' klasörüne kaydedildi.")

    def show_question_list(self):
        if not self.global_sequence:
            QMessageBox.information(self, "Bilgi", "Henüz seçim yapılmadı.")
            return
        self.selection_list_ready.emit(self.global_sequence)
        self.hide()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def qpixmap_to_cv2(self, qpixmap):
        qimage = qpixmap.toImage()
        if qimage.format() != QImage.Format_RGB32:
            qimage = qimage.convertToFormat(QImage.Format_RGB32)

        width = qimage.width()
        height = qimage.height()
        bytes_per_line = qimage.bytesPerLine()

        ptr = qimage.constBits()
        ptr.setsize(height * bytes_per_line)
        arr = np.array(ptr).reshape(height, width, 4)
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)