import fitz
from pathlib import Path
import re
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGridLayout,
    QTabWidget, QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QSizePolicy, QMessageBox, QScrollArea, QDialog, QSlider, QButtonGroup, QFileDialog, QSpinBox, QDoubleSpinBox,
    QColorDialog, QTextEdit, QToolBar, QPlainTextEdit,)
from PyQt5.QtCore import Qt, QRect, QSize, QUrl
from PyQt5.QtGui import QPixmap, QIcon, QPainter, QColor, QTextCharFormat, QFont, QTextListFormat, QTextBlockFormat
from testmaker.ui.windows.pdf_viewer import PDFViewer
from testmaker.models.selection import Selection
from testmaker.utils.qimage_utils import qimage_from_fitz_pix
from testmaker.utils.flow_layout import FlowLayout
from testmaker.ui.widgets.draggable_question import DraggableQuestion
from testmaker.services.pdf_exporter import export_test_pdf, ExportOptions, build_export_options
from testmaker.services.draft_store import save_draft, load_draft, Draft
from testmaker.ui.dialogs.pdf_preview_dialog import PDFPreviewDialog
from testmaker.ui.dialogs.question_gap_dialog import QuestionGapDialog
from dataclasses import replace



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Online Test Maker")
        # showMaximized() app.py'de çağrılıyor

        self.thumb_count = 0
        self.question_answers = {}
        self.viewer = None

        # Export settings (advanced page setup)
        self.export_settings = ExportOptions()
        self.export_settings.columns = 2
        self.export_settings.question_gap_spaced_mm = 15.0  # Varsayılan boşluk

        # Other (advanced) settings
        self.other_settings = {
            'center_line_enabled': False,
            'center_line_text': '',
            'center_line_bold': False,
            'center_line_text_color': '#000000',
            'center_line_text_direction': 'up',
        }
        
        # Test açıklaması
        self.test_description = ''

        self._create_menu_bar()
        self._create_main_layout()

    def _create_menu_bar(self):
        menubar = self.menuBar()
        menubar.setStyleSheet("font-size: 14px;")  # Daha okunabilir
        
        # Dosya menüsü
        file_menu = menubar.addMenu("Dosya")
        save_draft_action = file_menu.addAction("Taslağı Kaydet")
        save_draft_action.triggered.connect(self.save_current_draft)
        load_draft_action = file_menu.addAction("Taslağı Yükle")
        load_draft_action.triggered.connect(self.load_draft)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Çıkış")
        exit_action.triggered.connect(self.close)
        
        # Düzenle menüsü
        edit_menu = menubar.addMenu("Düzenle")
        clear_all_action = edit_menu.addAction("Tüm Soruları Temizle")
        clear_all_action.triggered.connect(self.clear_all_questions)
        
        # Hakkında menüsü
        about_menu = menubar.addMenu("Hakkında")
        about_action = about_menu.addAction("Hakkında")
        about_action.triggered.connect(self.show_about)

    def _create_main_layout(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        splitter = QSplitter(Qt.Horizontal)

        # Sol panel
        self.left_panel = QTabWidget()
        self.left_panel.setTabPosition(QTabWidget.North)
        self.left_panel.tabBar().setStyleSheet("""
            QTabBar::tab {
                background: #D6A99D; color:white;
                padding: 2px 4px; font-size:14px; font-weight:bold;
                border-radius:6px; margin:2px; min-width:100px; max-width:120px; height:30px;
            }
            QTabBar::tab:selected { background:#9CAFAA; color:white;}
            QTabBar::tab:hover { background:#D6DAC8;color:#064232;}
        """)
        
        self.left_panel.addTab(self._create_test_paper_tab(), "Test Kağıdı")
        # Diğer tab'lar ileride eklenecek
        # self.left_panel.addTab(QWidget(), "Yaprak Test")
        # self.left_panel.addTab(QWidget(), "Deneme Sınavı")
        # Advanced settings tab - "Ayarlar" yazısı ile
        adv_idx = self.left_panel.addTab(self._create_advanced_settings_tab(), "Ayarlar")
        splitter.addWidget(self.left_panel)

        # Sağ panel
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        self.right_panel.setStyleSheet("background-color:#BBDCE5;border:2px solid #748DAE;border-radius:6px;")

        inner_widget = QWidget()
        inner_layout = QVBoxLayout(inner_widget)
        inner_layout.setContentsMargins(20, 20, 20, 20)
        inner_layout.setSpacing(5)
        inner_widget.setStyleSheet("background-color:#EEEEEE;border:none;")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = FlowLayout(self.scroll_content, spacing=20)
        self.scroll_content.setLayout(self.scroll_layout)
        self.scroll_area.setWidget(self.scroll_content)
        inner_layout.addWidget(self.scroll_area)

        # Butonlar
        btn_layout = QHBoxLayout()
        buttons = [
            ("Cihazdan Seçin", "#f5b7b1"),
            ("Kırpma Aracı", "#d7bde2"),
            ("Soru Editörü", "#a9cce3"),
            ("Taslağı Geri Yükle", "#82e0aa")
        ]
        for text, color in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    color: #1d1d1d;
                    border-radius: 8px;
                    padding: 12px;
                    font-weight: bold;
                    font-size: 14px;
                    border: 1px solid {color};
                }}
                QPushButton:hover {{
                    background-color: white;
                    color: {color};
                    border: 2px solid {color};
                }}
            """)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if text == "Kırpma Aracı":
                btn.clicked.connect(self.open_crop_tool)
            elif text == "Cihazdan Seçin":
                btn.clicked.connect(self.import_from_device)
            elif text == "Soru Editörü":
                btn.clicked.connect(self.open_question_editor)
            elif text == "Taslağı Geri Yükle":
                btn.clicked.connect(self.load_draft)
            btn_layout.addWidget(btn)
        inner_layout.addLayout(btn_layout)

        right_layout.addWidget(inner_widget)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        main_layout.addWidget(splitter)
        self.setCentralWidget(main_widget)

    # Test Kağıdı Tab
    def _create_test_paper_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        style_input = """
            padding: 8px 12px;
            height: 32px;
            border-radius: 8px;
            border: 2px solid #E0E0E0;
            font-size: 14px;
            background-color: #FAFAFA;
            color: #333;
        """
        style_input += """
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #9CAFAA;
                background-color: #FFFFFF;
                outline: none;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #666;
                width: 0;
                height: 0;
            }
        """

        self.input_test_name = QLineEdit()
        self.input_test_name.setPlaceholderText("Test Adı")
        self.input_test_name.setStyleSheet(style_input)
        self.input_test_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.input_test_name)
        
        # Tüm elemanlar arası boşluk (azaltıldı)
        layout.addSpacing(6)
        
        self.input_school = QLineEdit()
        self.input_school.setPlaceholderText("Okul Adı")
        self.input_school.setStyleSheet(style_input)
        self.input_school.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.input_school)
        
        # Tüm elemanlar arası boşluk (azaltıldı)
        layout.addSpacing(6)
        
        # Checkbox ve açıklama
        self.cb_description = QCheckBox("Test ile ilgili açıklama ekle")
        self.cb_description.setStyleSheet("""
            font-size: 17px;
            min-height: 40px;
            padding-top: 0px;
            padding-bottom: 0px;
            margin-top: 0px;
            margin-bottom: 0px;
        """)
        layout.addWidget(self.cb_description, alignment=Qt.AlignLeft)
        
        # Checkbox işaretlendiğinde dialog aç
        def open_description_dialog(checked):
            if checked:
                self._open_test_description_dialog()
        self.cb_description.toggled.connect(open_description_dialog)

        # Checkbox'lar arası boşluk
        layout.addSpacing(0)

        self.cb_spacing = QCheckBox("Sorular arasında boşluk bırak")
        self.cb_spacing.setStyleSheet("""
            font-size: 17px;
            min-height: 40px;
            padding-top: 0px;
            padding-bottom: 0px;
            margin-top: 0px;
            margin-bottom: 0px;
        """)
        self.cb_spacing.clicked.connect(self.on_spacing_clicked)
        layout.addWidget(self.cb_spacing, alignment=Qt.AlignLeft)

        self.btn_prepare = QPushButton("Kağıdı Hazırla")
        self.btn_prepare.setStyleSheet(
            "QPushButton{background-color:#748DAE;color:white;padding:10px;border-radius:6px;font-weight:bold;font-size:14px;} QPushButton:hover{background-color:white;color:#748DAE;border:2px solid #748DAE;}")
        self.btn_prepare.clicked.connect(self.prepare_test_paper)

        layout.addWidget(self.btn_prepare)
        layout.addStretch(1)
        return tab

    # PDFViewer
    def open_crop_tool(self):
        if not self.viewer:
            self.viewer = PDFViewer()
            self.viewer.selection_list_ready.connect(self.display_questions)

        # Tam ekran aç
        self.viewer.showMaximized()
        self.viewer.raise_()
        self.viewer.activateWindow()

    def clear_all_thumbnails(self):
        self.thumb_count = 0
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def display_questions(self, selections: list):
        self.clear_all_thumbnails()
        for sel in selections:
            self.add_thumbnail_from_selection(sel)

    def add_thumbnail_from_selection(self, selection: Selection):
        if not self.viewer or not self.viewer.pdf_docs:
            return
        
        self.thumb_count += 1
        question_widget = DraggableQuestion(selection_data=selection)
        question_widget.thumb_number_label.setText(f"{self.thumb_count}. Soru")

        question_widget.question_deleted.connect(self.remove_question)
        question_widget.preview_requested.connect(self.show_question_preview)

        doc = self.viewer.pdf_docs.get(selection.pdf_key)
        if not doc:
            QMessageBox.warning(
                self,
                "PDF Bulunamadı",
                f"PDF bulunamadı: {selection.pdf_key}\n"
                "Lütfen PDF'leri tekrar açın."
            )
            return
        page = doc.load_page(selection.page_index)
        zoom = self.viewer.render_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

        pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))

        fx, fy, fw, fh = selection.norm
        r = QRect(int(fx * pm.width()), int(fy * pm.height()),
                  int(fw * pm.width()), int(fh * pm.height()))
        r = r.intersected(QRect(0, 0, pm.width(), pm.height()))
        if r.width() <= 0 or r.height() <= 0:
            return
        cropped = pm.copy(r)

        question_widget.set_thumbnail_image(cropped)
        self.scroll_layout.addWidget(question_widget)
        question_widget.reordered_signal.connect(self.update_viewer_sequence)

    def remove_question(self, selection_data):
        if self.viewer:
            try:
                self.viewer.global_sequence.remove(selection_data)
                self.viewer._renumber_global()
                self.viewer._refresh_current_page_selections()
            except ValueError:
                pass

        for i in range(self.scroll_layout.count()):
            widget = self.scroll_layout.itemAt(i).widget()
            if hasattr(widget, 'selection_data') and widget.selection_data == selection_data:
                self.scroll_layout.removeWidget(widget)
                widget.deleteLater()
                break

        self.thumb_count = 0
        new_sequence = []
        for i in range(self.scroll_layout.count()):
            widget = self.scroll_layout.itemAt(i).widget()
            if hasattr(widget, 'selection_data'):
                self.thumb_count += 1
                widget.thumb_number = self.thumb_count
                widget.thumb_number_label.setText(f"{self.thumb_count}. Soru")
                if widget.selection_data:
                    widget.selection_data.number = self.thumb_count
                    new_sequence.append(widget.selection_data)

        if self.viewer:
            self.viewer.update_global_sequence(new_sequence)

    def show_question_preview(self, selection_data):
        from testmaker.ui.dialogs.pdf_preview_dialog import QuestionPreviewDialog
        dialog = QuestionPreviewDialog(self, selection_data)
        dialog.exec_()

    def update_viewer_sequence(self, new_sequence):
        if self.viewer:
            self.viewer.update_global_sequence(new_sequence)

    def prepare_test_paper(self):
        # Seçimleri UI sırasına göre al
        selections = []
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if hasattr(w, "selection_data") and w.selection_data:
                selections.append(w.selection_data)
        
        # Soruları 1'den başlayarak yeniden numaralandır (her "Kağıdı Hazırla" tıklamasında)
        for idx, sel in enumerate(selections, start=1):
            sel.number = idx

        if not selections:
            QMessageBox.information(self, "Bilgi", "Lütfen önce soru ekleyin.")
            return

        # PDF viewer ve dokümanların açık olması gerekiyor
        if not self.viewer or not self.viewer.pdf_docs:
            QMessageBox.warning(
                self,
                "PDF Gerekli",
                "PDF oluşturmak için önce PDF'leri açmanız gerekiyor.\n"
                "Lütfen 'Kırpma Aracı' butonunu kullanarak PDF ekleyin."
            )
            return

        # Export seçenekleri (şimdilik panelden okuduklarımız)
        opts = build_export_options(
            self.export_settings,
            test_title=self.input_test_name.text().strip() or "TEST",
            school_name=self.input_school.text().strip(),
            branch_name="",
            teacher_name="",
            spaced=self.cb_spacing.isChecked(),
            question_gap_spaced_mm=self.export_settings.question_gap_spaced_mm if self.cb_spacing.isChecked() else self.export_settings.question_gap_mm,
            smart_layout=self.chk_smart_layout.isChecked() if hasattr(self, "chk_smart_layout") else False,
            watermark_enabled=self.chk_watermark.isChecked() if hasattr(self, "chk_watermark") else False,
            watermark_text=self.input_watermark.text().strip() if hasattr(self, "input_watermark") else "",
            center_line_enabled=self.other_settings.get('center_line_enabled', False),
            center_line_text=self.other_settings.get('center_line_text', ''),
            center_line_bold=self.other_settings.get('center_line_bold', False),
            center_line_color=self.other_settings.get('center_line_text_color', '#000000'),
            center_line_text_direction=self.other_settings.get('center_line_text_direction', 'up'),
        )
        
        # Ön izleme dialog'unu aç (render_dpi'yi de geç)
        render_dpi = self.viewer.render_dpi if self.viewer else 300.0
        preview_dialog = PDFPreviewDialog(self, selections, opts, self.viewer.pdf_docs, render_dpi=render_dpi)
        result = preview_dialog.exec_()
        
        # Dialog kapandıktan sonra:
        # 1. Soruların yeni sırasını MainWindow'a aktar
        # 2. Soruları 1'den başlayarak yeniden numaralandır
        # 3. Custom gap değerlerini aktar
        
        if preview_dialog and hasattr(preview_dialog, 'selections'):
            # Dialog'daki yeni sıralamayı al (soruların yerleri değişmiş olabilir)
            reordered_selections = preview_dialog.selections
            
            # Soruları 1'den başlayarak yeniden numaralandır
            for idx, sel in enumerate(reordered_selections, start=1):
                sel.number = idx
            
            # MainWindow'daki soruları yeni sıraya göre yeniden düzenle
            # Önce mevcut widget'ları temizle
            self.clear_all_thumbnails()
            self.thumb_count = 0  # Thumb count'ı sıfırla
            
            # Yeni sıraya göre thumbnail'ları yeniden oluştur
            for sel in reordered_selections:
                self.add_thumbnail_from_selection(sel)
            
            # Viewer'daki global_sequence'i de güncelle
            if self.viewer:
                self.viewer.update_global_sequence(reordered_selections)
            
            # Custom gap değerlerini aktar (zaten Selection objelerinde var, ama emin olmak için)
            if hasattr(preview_dialog, 'preview_widget') and hasattr(preview_dialog.preview_widget, 'questions'):
                gap_after_map = {}  # {selection.number: custom_gap_after_pt}
                gap_before_map = {}  # {selection.number: custom_gap_before_pt}
                
                for q in preview_dialog.preview_widget.questions:
                    if q.custom_gap_after_pt is not None:
                        gap_after_map[q.selection.number] = q.custom_gap_after_pt
                    if q.custom_gap_before_pt is not None:
                        gap_before_map[q.selection.number] = q.custom_gap_before_pt
                
                # MainWindow'daki Selection objelerini güncelle
                for sel in reordered_selections:
                    if sel.number in gap_after_map:
                        sel.custom_gap_after_pt = gap_after_map[sel.number]
                    if sel.number in gap_before_map:
                        sel.custom_gap_before_pt = gap_before_map[sel.number]

    def change_answer(self, letter, selection_data: Selection):
        selection_data.answer = letter
        self._refresh_thumbnail(selection_data)

    def edit_selection(self, pixmap):
        QMessageBox.information(self, "Soru Düzenle", "Bu soruyu düzenleme penceresi açılacak.")

    def _refresh_thumbnail(self, selection_data):
        """Verilen selection_data'ya ait thumb'ı günceller ve buton durumunu günceller."""
        if not self.viewer or not self.viewer.pdf_docs:
            return
        
        for i in range(self.scroll_layout.count()):
            widget = self.scroll_layout.itemAt(i).widget()
            if hasattr(widget, 'selection_data') and widget.selection_data == selection_data:
                doc = self.viewer.pdf_docs.get(selection_data.pdf_key)
                if not doc:
                    continue
                page = doc.load_page(selection_data.page_index)
                zoom = self.viewer.render_dpi / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))

                fx, fy, fw, fh = selection_data.norm
                r = QRect(int(fx * pm.width()), int(fy * pm.height()),
                          int(fw * pm.width()), int(fh * pm.height()))
                cropped = pm.copy(r)

                # Resim boyutunu ölçekleme
                scaled_thumb = cropped.scaled(
                    int(cropped.width() * selection_data.preview_scale),
                    int(cropped.height() * selection_data.preview_scale),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                widget.set_thumbnail_image(scaled_thumb)

                # Buton durumunu güncelleme
                widget.set_answer(selection_data.answer)

                break

    # -----------------------------
    # Yeni buton fonksiyonları
    # -----------------------------
    def import_from_device(self):
        """Cihazdan görsel dosyaları seçip soru olarak ekler."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Görsel Dosyaları Seçin",
            "",
            "Görsel Dosyaları (*.png *.jpg *.jpeg *.bmp *.gif);;Tüm Dosyalar (*.*)"
        )
        if not files:
            return
        
        try:
            # Görselleri geçici bir PDF'e dönüştür
            import tempfile
            from PIL import Image
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter, A4
            
            # Geçici PDF dosyası oluştur
            temp_pdf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
            temp_pdf_path = temp_pdf.name
            temp_pdf.close()
            
            # PDF oluştur
            c = canvas.Canvas(temp_pdf_path, pagesize=A4)
            page_w, page_h = A4
            
            for img_path in files:
                try:
                    # Görseli yükle
                    img = Image.open(img_path)
                    img_w, img_h = img.size
                    
                    # Görseli sayfaya sığdır (aspect ratio korunarak)
                    scale_w = page_w / img_w
                    scale_h = page_h / img_h
                    scale = min(scale_w, scale_h) * 0.9  # %90 margin
                    
                    draw_w = img_w * scale
                    draw_h = img_h * scale
                    
                    # Sayfayı ortala
                    x = (page_w - draw_w) / 2.0
                    y = (page_h - draw_h) / 2.0
                    
                    # Görseli PDF'e ekle
                    c.drawImage(img_path, x, y, width=draw_w, height=draw_h, preserveAspectRatio=True)
                    c.showPage()  # Yeni sayfa
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Uyarı",
                        f"Görsel yüklenemedi: {Path(img_path).name}\n{str(e)}"
                    )
                    continue
            
            c.save()
            
            # PDF viewer'ı aç veya oluştur
            if not self.viewer:
                self.viewer = PDFViewer()
                self.viewer.selection_list_ready.connect(self.display_questions)
            
            # PDF'i viewer'a ekle
            try:
                doc = fitz.open(temp_pdf_path)
                key = self.viewer._unique_pdf_key(temp_pdf_path)
                self.viewer.pdf_docs[key] = doc
                self.viewer.cmb_pdf.setEnabled(True)
                self.viewer.cmb_pdf.addItem(key)
                self.viewer.cmb_pdf.setCurrentText(key)
                self.viewer.page.set_selection_enabled(True)
                self.viewer.current_pdf = key
                self.viewer.page_index = 0
                # PDF'i render et
                self.viewer._render_current()
                # PDF genişliğini pencere genişliğine göre zoom hesapla
                if self.viewer.page.pm_orig:
                    pdf_width_px = self.viewer.page.pm_orig.width()
                    viewer_width = self.viewer.width() - 100
                    if pdf_width_px > 0:
                        initial_scale = viewer_width / pdf_width_px
                        self.viewer.page.scale = max(0.2, min(2.0, initial_scale))
                        self.viewer._refresh_current_page_selections()
                self.viewer._update_status()
            except Exception as e:
                import traceback
                QMessageBox.warning(
                    self,
                    "Uyarı",
                    f"PDF viewer'a eklenirken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}"
                )
            
            # Viewer'ı göster
            self.viewer.showMaximized()
            self.viewer.raise_()
            self.viewer.activateWindow()
            
            QMessageBox.information(
                self,
                "Başarılı",
                f"{len(files)} görsel dosyası PDF'e dönüştürüldü ve yüklendi.\n"
                "Şimdi kırpma aracından soruları seçebilirsiniz."
            )
        except ImportError:
            QMessageBox.warning(
                self,
                "Hata",
                "Pillow kütüphanesi gerekli. Lütfen 'pip install Pillow' komutunu çalıştırın."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Hata",
                f"Görseller yüklenirken hata oluştu:\n{str(e)}"
            )

    def open_question_editor(self):
        """Tüm soruları düzenlemek için bir dialog açar."""
        if self.scroll_layout.count() == 0:
            QMessageBox.information(self, "Bilgi", "Düzenlenecek soru yok.")
            return
        
        # İlk soruyu önizleme dialogunda aç
        first_widget = self.scroll_layout.itemAt(0).widget()
        if hasattr(first_widget, 'selection_data') and first_widget.selection_data:
            self.show_question_preview(first_widget.selection_data)
        else:
            QMessageBox.information(self, "Bilgi", "Soru bulunamadı.")

    def save_current_draft(self):
        """Mevcut taslağı kaydeder."""
        # Seçimleri topla
        selections = []
        for i in range(self.scroll_layout.count()):
            w = self.scroll_layout.itemAt(i).widget()
            if hasattr(w, "selection_data") and w.selection_data:
                selections.append(w.selection_data)
        
        if not selections:
            QMessageBox.information(self, "Bilgi", "Kaydedilecek soru yok.")
            return
        
        # Dosya yolu seç
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Taslağı Kaydet",
            "taslak.json",
            "JSON Dosyaları (*.json);;Tüm Dosyalar (*.*)"
        )
        if not path:
            return
        
        try:
            # Test bilgilerini topla
            test_info = {
                'test_name': self.input_test_name.text().strip(),
                'school_name': self.input_school.text().strip(),
                'branch_name': '',
                'group_choice': '',
            }
            
            draft = Draft(
                selections=selections,
                export_settings=self.export_settings.__dict__ if hasattr(self.export_settings, '__dict__') else {},
                other_settings=self.other_settings,
                test_info=test_info,
            )
            save_draft(Path(path), draft)
            QMessageBox.information(self, "Başarılı", f"Taslak kaydedildi:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Taslak kaydedilemedi:\n{str(e)}")

    def load_draft(self):
        """Kaydedilmiş taslağı yükler."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Taslağı Yükle",
            "",
            "JSON Dosyaları (*.json);;Tüm Dosyalar (*.*)"
        )
        if not path:
            return
        
        try:
            draft = load_draft(Path(path))
            
            # PDF viewer'ın açık olması gerekiyor
            if not self.viewer or not self.viewer.pdf_docs:
                reply = QMessageBox.question(
                    self,
                    "PDF Gerekli",
                    "Taslağı yüklemek için önce PDF'leri açmanız gerekiyor.\n"
                    "Kırpma Aracı'nı açıp PDF ekleyin, sonra tekrar deneyin.",
                    QMessageBox.Ok | QMessageBox.Cancel
                )
                return
            
            # Seçimleri kontrol et - PDF'ler hala açık mı?
            missing_pdfs = set()
            for sel in draft.selections:
                if sel.pdf_key not in self.viewer.pdf_docs:
                    missing_pdfs.add(sel.pdf_key)
            
            if missing_pdfs:
                QMessageBox.warning(
                    self,
                    "PDF Eksik",
                    f"Taslaktaki bazı PDF'ler açık değil:\n" + "\n".join(list(missing_pdfs)[:3])
                )
                return
            
            # Mevcut soruları temizle
            self.clear_all_thumbnails()
            
            # Yeni seçimleri ekle
            self.viewer.global_sequence = draft.selections
            self.viewer._renumber_global()
            self.display_questions(draft.selections)
            
            # Test bilgilerini yükle
            if draft.test_info:
                if 'test_name' in draft.test_info:
                    self.input_test_name.setText(draft.test_info.get('test_name', ''))
                if 'school_name' in draft.test_info:
                    self.input_school.setText(draft.test_info.get('school_name', ''))
                # Şube adı ve grup seçimi kaldırıldı - artık kullanılmıyor
            
            # Export ayarlarını yükle
            if draft.export_settings:
                for key, value in draft.export_settings.items():
                    if hasattr(self.export_settings, key):
                        setattr(self.export_settings, key, value)
            
            # Diğer ayarları yükle
            if draft.other_settings:
                self.other_settings.update(draft.other_settings)
            
            QMessageBox.information(self, "Başarılı", f"Taslak yüklendi:\n{path}")
        except FileNotFoundError:
            QMessageBox.warning(self, "Hata", "Taslak dosyası bulunamadı.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Taslak yüklenemedi:\n{str(e)}")

    def clear_all_questions(self):
        """Tüm soruları temizler."""
        if self.scroll_layout.count() == 0:
            return
        
        reply = QMessageBox.question(
            self,
            "Onay",
            "Tüm soruları silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.clear_all_thumbnails()
            if self.viewer:
                self.viewer.global_sequence = []
                self.viewer._renumber_global()

    def on_spacing_clicked(self):
        """Checkbox veya label'a tıklandığında"""
        # MADDE 6: Eğer checkbox işaretleniyorsa (True oluyorsa), önce tüm custom_gap değerlerini sıfırla
        if self.cb_spacing.isChecked():
            # Tüm Selection objelerindeki custom_gap değerlerini None yap
            # Selections'ı scroll_layout'tan topla (prepare_test_paper metodundaki gibi)
            selections = []
            for i in range(self.scroll_layout.count()):
                w = self.scroll_layout.itemAt(i).widget()
                if hasattr(w, "selection_data") and w.selection_data:
                    selections.append(w.selection_data)
            
            for sel in selections:
                sel.custom_gap_after_pt = None
                sel.custom_gap_before_pt = None
            print("DEBUG: on_spacing_clicked - Tüm custom_gap değerleri sıfırlandı")
        
        # Checkbox'ın otomatik durum değişimini önle
        current_state = self.cb_spacing.isChecked()
        self.cb_spacing.blockSignals(True)
        self.cb_spacing.setChecked(not current_state)  # Geçici olarak değiştir
        self.cb_spacing.blockSignals(False)
        
        # Dialog'u aç, kullanıcı boşluk miktarını seçsin
        current_gap = self.export_settings.question_gap_spaced_mm if hasattr(self.export_settings, 'question_gap_spaced_mm') and self.export_settings.question_gap_spaced_mm else 15.0
        dialog = QuestionGapDialog(self, current_gap)
        if dialog.exec_() == QDialog.Accepted:
            new_gap = dialog.get_gap_mm()
            self.export_settings.question_gap_spaced_mm = new_gap
            # Checkbox'ı işaretle (kullanıcı değer seçti)
            self.cb_spacing.setChecked(True)
            print(f"DEBUG: on_spacing_clicked - Yeni boşluk değeri ayarlandı: {new_gap}mm")
        else:
            # Dialog iptal edildiyse checkbox'ı önceki durumuna geri al
            self.cb_spacing.setChecked(current_state)

    def show_about(self):
        """Hakkında dialogunu gösterir."""
        QMessageBox.about(
            self,
            "Hakkında",
            "<h2>Online Test Maker</h2>"
            "<p>PDF'lerden soru seçip test kağıdı oluşturma uygulaması</p>"
            "<p><b>Sürüm:</b> 1.0</p>"
            "<p><b>Geliştirici:</b> Test Maker Team</p>"
            "<p>PyQt5 + PyMuPDF ile geliştirilmiştir.</p>"
        )

    # -----------------------------
    # Advanced Settings (Gear Tab)
    # -----------------------------
    def _gear_icon(self) -> QIcon:
        """Create a simple gear-like icon for the tab."""
        size = 18
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QColor("#555555"))
        p.setBrush(QColor("#888888"))
        # outer circle
        p.drawEllipse(3, 3, size - 6, size - 6)
        # inner circle
        p.setBrush(QColor("#EEEEEE"))
        p.drawEllipse(7, 7, size - 14, size - 14)
        # teeth (simple)
        p.setBrush(QColor("#888888"))
        for i in range(8):
            p.save()
            p.translate(size/2, size/2)
            p.rotate(i * 45)
            p.drawRect(int(size/2 - 2), -1, 3, 2)
            p.restore()
        p.end()
        return QIcon(pm)

    def _make_margin_preview_pixmap(self, w: int, h: int, top_cm: float, bottom_cm: float, left_cm: float, right_cm: float) -> QPixmap:
        """Draw a paper preview with margin lines."""
        pm = QPixmap(w, h)
        pm.fill(QColor("#FFFFFF"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Paper border
        p.setPen(QColor("#444444"))
        p.drawRect(5, 5, w - 10, h - 10)

        # Map cm -> preview pixels (rough)
        # Assume max 5cm each side for visualization
        max_cm = 5.0
        inner_left = 5 + int((left_cm / max_cm) * (w - 10) * 0.25)
        inner_right = (w - 5) - int((right_cm / max_cm) * (w - 10) * 0.25)
        inner_top = 5 + int((top_cm / max_cm) * (h - 10) * 0.25)
        inner_bottom = (h - 5) - int((bottom_cm / max_cm) * (h - 10) * 0.25)

        p.setPen(QColor("#9CAFAA"))
        p.drawRect(inner_left, inner_top, max(1, inner_right - inner_left), max(1, inner_bottom - inner_top))

        p.end()
        return pm

    def _create_advanced_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Gelişmiş Ayarlar")
        title.setStyleSheet("font-weight:800; font-size:16px;")
        layout.addWidget(title)

        # Checkboxes row
        self.chk_smart_layout = QCheckBox("Akıllı soru yerleşimi uygula")
        self.chk_watermark = QCheckBox("Filigran ekle")
        layout.addWidget(self.chk_smart_layout)
        layout.addWidget(self.chk_watermark)

        # Watermark text input (shows when enabled)
        self.input_watermark = QLineEdit()
        self.input_watermark.setPlaceholderText("Filigran metni (örn. OKUL / DENEME)")
        self.input_watermark.setEnabled(False)
        layout.addWidget(self.input_watermark)

        def _toggle_watermark():
            self.input_watermark.setEnabled(self.chk_watermark.isChecked())
        self.chk_watermark.stateChanged.connect(_toggle_watermark)

        # Paper size dropdown
        layout.addWidget(QLabel("Kağıt Boyutu"))
        self.cmb_paper = QComboBox()
        paper_items = [
            "A0 (841 x 1189 mm)",
            "A1 (594 x 841 mm)",
            "A2 (420 x 594 mm)",
            "A3 (297 x 420 mm)",
            "A4 (210 x 297 mm)",
            "A5 (148 x 210 mm)",
            "A6 (105 x 148 mm)",
            "B4 (250 x 353 mm)",
            "B5 (176 x 250 mm)",
            "Letter (215.9 x 279.4 mm)",
            "Legal (215.9 x 355.6 mm)",
            "Tabloid (279.4 x 431.8 mm)",
            "Executive (184.15 x 266.7 mm)",
            "Folio (210 x 330 mm)",
            "Özel (mm)"
        ]
        self.cmb_paper.addItems(paper_items)
        self.cmb_paper.setCurrentText("A4 (210 x 297 mm)")
        layout.addWidget(self.cmb_paper)

        # Custom size mm
        custom_row = QHBoxLayout()
        self.spin_w_mm = QSpinBox()
        self.spin_w_mm.setRange(50, 2000)
        self.spin_w_mm.setValue(210)
        self.spin_w_mm.setSuffix(" mm")
        self.spin_h_mm = QSpinBox()
        self.spin_h_mm.setRange(50, 2000)
        self.spin_h_mm.setValue(297)
        self.spin_h_mm.setSuffix(" mm")
        custom_row.addWidget(QLabel("Genişlik:"))
        custom_row.addWidget(self.spin_w_mm)
        custom_row.addWidget(QLabel("Yükseklik:"))
        custom_row.addWidget(self.spin_h_mm)
        layout.addLayout(custom_row)

        # Orientation
        layout.addWidget(QLabel("Yönlendirme"))
        self.cmb_orientation = QComboBox()
        self.cmb_orientation.addItems(["Dikey", "Yatay"])
        layout.addWidget(self.cmb_orientation)

        # Columns
        layout.addWidget(QLabel("Sütun sayısı"))
        self.cmb_columns = QComboBox()
        self.cmb_columns.addItems([str(i) for i in range(1, 7)])
        self.cmb_columns.setCurrentText("2")
        layout.addWidget(self.cmb_columns)

        # Margins section
        layout.addWidget(QLabel("Kenar boşlukları ayarla:"))

        margins_box = QHBoxLayout()

        self.lbl_margin_preview = QLabel()
        self.lbl_margin_preview.setFixedSize(140, 190)

        # Defaults in cm
        self._m_top_cm = 1.5
        self._m_bottom_cm = 1.5
        self._m_left_cm = 1.5
        self._m_right_cm = 1.5


        margins_box.addWidget(self.lbl_margin_preview)

        # 2x2 "table" without borders
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        self.lbl_margin_top = QLabel(f"Üst  {self._m_top_cm:.1f} cm")
        self.lbl_margin_bottom = QLabel(f"Alt  {self._m_bottom_cm:.1f} cm")
        self.lbl_margin_left = QLabel(f"Sol  {self._m_left_cm:.1f} cm")
        self.lbl_margin_right = QLabel(f"Sağ  {self._m_right_cm:.1f} cm")
        for lab in (self.lbl_margin_top, self.lbl_margin_bottom, self.lbl_margin_left, self.lbl_margin_right):
            lab.setStyleSheet("font-size:13px;")

        grid.addWidget(self.lbl_margin_top, 0, 0)
        grid.addWidget(self.lbl_margin_bottom, 0, 1)
        grid.addWidget(self.lbl_margin_left, 1, 0)
        grid.addWidget(self.lbl_margin_right, 1, 1)

        margins_box.addLayout(grid)

        # Initial preview/labels
        self._refresh_margin_preview()
        layout.addLayout(margins_box)

        # Preset margins dropdown + custom link
        preset_row = QHBoxLayout()
        self.cmb_margin_preset = QComboBox()
        self.cmb_margin_preset.addItems(["Dar", "Normal", "Geniş"])
        self.cmb_margin_preset.setCurrentText("Normal")
        preset_row.addWidget(self.cmb_margin_preset)

        self.lbl_custom_margins = QLabel("Özel kenar boşlukları")
        self.lbl_custom_margins.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.lbl_custom_margins.setOpenExternalLinks(False)
        self.lbl_custom_margins.setStyleSheet("border-bottom: 1px dotted #333; padding-bottom:2px;")
        preset_row.addWidget(self.lbl_custom_margins)
        preset_row.addStretch()
        layout.addLayout(preset_row)

        self.lbl_custom_margins.mousePressEvent = lambda e: self._open_custom_margins_dialog()

        def _apply_preset():
            preset = self.cmb_margin_preset.currentText()
            if preset == "Dar":
                self._set_margins_cm(1.0, 1.0, 1.0, 1.0)
            elif preset == "Normal":
                self._set_margins_cm(1.5, 1.5, 1.5, 1.5)
            elif preset == "Geniş":
                self._set_margins_cm(2.5, 2.5, 2.5, 2.5)
        self.cmb_margin_preset.currentIndexChanged.connect(_apply_preset)

        # Other settings button
        btn_other = QPushButton("-> Diğer ayarları göster")
        btn_other.setStyleSheet("font-size: 14px;")
        btn_other.clicked.connect(self._open_other_settings_dialog)
        layout.addWidget(btn_other)

        layout.addStretch(1)

        # Enable/disable custom mm inputs
        def _update_custom_size_state():
            is_custom = self.cmb_paper.currentText().startswith("Özel")
            self.spin_w_mm.setEnabled(is_custom)
            self.spin_h_mm.setEnabled(is_custom)
            self._apply_export_settings_from_advanced()
        self.cmb_paper.currentIndexChanged.connect(_update_custom_size_state)
        self.spin_w_mm.valueChanged.connect(self._apply_export_settings_from_advanced)
        self.spin_h_mm.valueChanged.connect(self._apply_export_settings_from_advanced)
        self.cmb_orientation.currentIndexChanged.connect(self._apply_export_settings_from_advanced)
        self.cmb_columns.currentIndexChanged.connect(self._apply_export_settings_from_advanced)

        _update_custom_size_state()
        self._apply_export_settings_from_advanced()

        return tab

    def _set_margins_cm(self, top: float, bottom: float, left: float, right: float):
        self._m_top_cm = float(top)
        self._m_bottom_cm = float(bottom)
        self._m_left_cm = float(left)
        self._m_right_cm = float(right)
        self._refresh_margin_preview()
        self._apply_export_settings_from_advanced()

    def _refresh_margin_preview(self):
        pm = self._make_margin_preview_pixmap(
            140, 190, self._m_top_cm, self._m_bottom_cm, self._m_left_cm, self._m_right_cm
        )
        self.lbl_margin_preview.setPixmap(pm)
        self.lbl_margin_top.setText(f"Üst  {self._m_top_cm:.1f} cm")
        self.lbl_margin_bottom.setText(f"Alt  {self._m_bottom_cm:.1f} cm")
        self.lbl_margin_left.setText(f"Sol  {self._m_left_cm:.1f} cm")
        self.lbl_margin_right.setText(f"Sağ  {self._m_right_cm:.1f} cm")

    def _parse_paper_choice(self):
        text = self.cmb_paper.currentText()
        if text.startswith("Özel"):
            return "CUSTOM", float(self.spin_w_mm.value()), float(self.spin_h_mm.value())
        # Example: "A4 (210 x 297 mm)"
        m = re.match(r"^([A-Za-z0-9 ]+)\s*\(([^)]+)\)$", text)
        if not m:
            return "A4", 210.0, 297.0
        name = m.group(1).strip()
        return name.upper().replace(" ", ""), 0.0, 0.0

    def _apply_export_settings_from_advanced(self):
        preset, w_mm, h_mm = self._parse_paper_choice()
        orientation = "landscape" if self.cmb_orientation.currentText() == "Yatay" else "portrait"
        cols = int(self.cmb_columns.currentText())

        # margins in mm from cm
        top_mm = self._m_top_cm * 10.0
        bottom_mm = self._m_bottom_cm * 10.0
        left_mm = self._m_left_cm * 10.0
        right_mm = self._m_right_cm * 10.0

        self.export_settings = replace(
            self.export_settings,
            page_preset=preset,
            page_width_mm=w_mm if preset == "CUSTOM" else self.export_settings.page_width_mm,
            page_height_mm=h_mm if preset == "CUSTOM" else self.export_settings.page_height_mm,
            orientation=orientation,
            columns=cols,
            margin_top_mm=top_mm,
            margin_bottom_mm=bottom_mm,
            margin_left_mm=left_mm,
            margin_right_mm=right_mm,
        )

    def _open_custom_margins_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Özel Kenar Boşlukları")
        dlg.setModal(True)

        root = QHBoxLayout(dlg)
        left = QVBoxLayout()
        right = QVBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(right, 1)

        def mk_spin(label, val):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 10.0)
            sp.setSingleStep(0.1)
            sp.setDecimals(1)
            sp.setValue(val)
            row.addWidget(sp)
            left.addLayout(row)
            return sp

        sp_top = mk_spin("Üst", self._m_top_cm)
        sp_bottom = mk_spin("Alt", self._m_bottom_cm)
        sp_left = mk_spin("Sol", self._m_left_cm)
        sp_right = mk_spin("Sağ", self._m_right_cm)

        prev = QLabel()
        prev.setFixedSize(220, 300)
        right.addWidget(prev)

        def refresh_preview():
            pm = self._make_margin_preview_pixmap(220, 300, sp_top.value(), sp_bottom.value(), sp_left.value(), sp_right.value())
            prev.setPixmap(pm)

        sp_top.valueChanged.connect(refresh_preview)
        sp_bottom.valueChanged.connect(refresh_preview)
        sp_left.valueChanged.connect(refresh_preview)
        sp_right.valueChanged.connect(refresh_preview)
        refresh_preview()

        btns = QHBoxLayout()
        btn_ok = QPushButton("Tamam")
        btn_ok.setStyleSheet("font-size: 14px; font-weight: bold;")
        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("font-size: 14px; font-weight: bold;")
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        left.addLayout(btns)

        btn_cancel.clicked.connect(dlg.reject)

        def apply_and_close():
            self._set_margins_cm(sp_top.value(), sp_bottom.value(), sp_left.value(), sp_right.value())
            self.cmb_margin_preset.setCurrentText("Normal")  # doesn't matter; keep UI stable
            dlg.accept()

        btn_ok.clicked.connect(apply_and_close)

        dlg.exec_()

    def _open_other_settings_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Diğer Ayarlar")
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)

        row = QHBoxLayout()
        chk = QCheckBox()
        chk.setChecked(self.other_settings.get("center_line_enabled", False))
        row.addWidget(chk)

        lbl = QLabel("Çizgi üzerine yazı ekle")
        lbl.setStyleSheet("text-decoration: underline; cursor: pointer;")
        row.addWidget(lbl)
        row.addStretch()
        layout.addLayout(row)

        def open_dialog_and_check():
            # Checkbox'ı seçili yap ve dialog'u aç
            chk.setChecked(True)
            self._open_center_line_text_dialog()
        
        def toggle_and_open(event):
            # Label'a tıklandığında checkbox'ı toggle et ve dialog'u aç
            chk.setChecked(True)
            self._open_center_line_text_dialog()
        
        def checkbox_toggled(checked):
            # Checkbox'a tıklandığında dialog'u aç
            if checked:
                self._open_center_line_text_dialog()
        
        lbl.mousePressEvent = toggle_and_open
        chk.toggled.connect(checkbox_toggled)

        btns = QHBoxLayout()
        btn_ok = QPushButton("Tamam")
        btn_ok.setStyleSheet("font-size: 12px; font-weight: bold;")
        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("font-size: 12px; font-weight: bold;")
        btns.addStretch()
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

        btn_cancel.clicked.connect(dlg.reject)

        def apply():
            self.other_settings["center_line_enabled"] = chk.isChecked()
            dlg.accept()

        btn_ok.clicked.connect(apply)
        dlg.exec_()

    def _open_center_line_text_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Çizgi Üzeri Yazı")
        dlg.setModal(True)

        v = QVBoxLayout(dlg)

        # Input container - butonları input içinde göstermek için
        input_container = QWidget()
        input_container_layout = QHBoxLayout(input_container)
        input_container_layout.setContentsMargins(0, 0, 0, 0)
        input_container_layout.setSpacing(0)
        
        input_txt = QLineEdit(self.other_settings.get("center_line_text", ""))
        input_txt.setStyleSheet("""
            padding: 8px 12px;
            font-size: 14px;
            border: 2px solid #E0E0E0;
            border-right: none;
            border-radius: 4px 0 0 4px;
            background-color: #FAFAFA;
            color: #333;
        """)
        input_container_layout.addWidget(input_txt, 1)  # Input genişleyebilir

        # Butonlar input'un içinde (sağ tarafta)
        btn_b = QPushButton("B")
        btn_b.setCheckable(True)
        btn_b.setChecked(self.other_settings.get("center_line_bold", False))
        btn_b.setFixedSize(40, 35)
        btn_b.setStyleSheet("""
            QPushButton {
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-left: 1px solid #ccc;
                border-right: 1px solid #ccc;
                background-color: #f0f0f0;
            }
            QPushButton:checked {
                background-color: #4CAF50;
                color: white;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)

        btn_c = QPushButton("C")
        btn_c.setFixedSize(40, 35)
        btn_c.setStyleSheet("""
            QPushButton {
                border: none;
                border-left: 1px solid #ccc;
                border-right: 1px solid #ccc;
                border-radius: 0 4px 4px 0;
                background-color: #f0f0f0;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        
        input_container_layout.addWidget(btn_b)
        input_container_layout.addWidget(btn_c)
        
        v.addWidget(input_container)

        # state
        state = {
            "bold": btn_b.isChecked(),
            "color": self.other_settings.get("center_line_text_color", "#000000"),
        }

        def toggle_b():
            state["bold"] = btn_b.isChecked()
        btn_b.toggled.connect(toggle_b)

        def choose_color():
            col = QColorDialog.getColor(QColor(state["color"]), self, "Renk Seç")
            if col.isValid():
                state["color"] = col.name()
        btn_c.clicked.connect(choose_color)

        # Tamam ve İptal butonları yan yana
        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        
        btn_ok = QPushButton("Tamam")
        btn_ok.setFixedSize(80, 35)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        btn_cancel = QPushButton("İptal")
        btn_cancel.setFixedSize(80, 35)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        
        button_row.addWidget(btn_ok)
        button_row.addWidget(btn_cancel)
        v.addLayout(button_row)

        def apply():
            self.other_settings["center_line_text"] = input_txt.text().strip()
            self.other_settings["center_line_bold"] = state["bold"]
            self.other_settings["center_line_text_color"] = state["color"]
            dlg.accept()

        btn_ok.clicked.connect(apply)
        btn_cancel.clicked.connect(dlg.reject)
        
        # Enter tuşu ile de kaydet
        input_txt.returnPressed.connect(apply)
        
        dlg.exec_()

    def _open_test_description_dialog(self):
        """Test açıklaması düzenleme dialog'u - TinyMCE ile"""
        # QWebEngineView kullanmayı dene
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView
            print("✓ QWebEngineView yüklü - Quill.js editörü kullanılıyor")
            self._open_test_description_dialog_web(dlg_parent=self)
        except ImportError as e:
            # QWebEngineView yoksa gelişmiş QTextEdit kullan
            print(f"✗ QWebEngineView yüklü değil - Gelişmiş QTextEdit kullanılıyor")
            print(f"  Hata: {e}")
            print(f"  Yüklemek için: pip install PyQtWebEngine")
            self._open_test_description_dialog_advanced(dlg_parent=self)
    
    def _open_test_description_dialog_web(self, dlg_parent):
        """Quill.js ile web tabanlı editör (API key gerektirmez)"""
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        
        dlg = QDialog(dlg_parent)
        dlg.setWindowTitle("Test Açıklaması (Zengin Metin Editörü)")
        dlg.setModal(True)
        dlg.setMinimumSize(800, 600)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # WebEngineView
        web_view = QWebEngineView()
        
        # Mevcut içeriği HTML'e çevir (eğer HTML değilse)
        initial_content = self.test_description if self.test_description else ""
        # Eğer HTML formatında değilse, düz metin olarak kabul et
        if initial_content and not initial_content.strip().startswith('<'):
            initial_content = initial_content.replace('\n', '<br>')
        
        # Quill.js HTML içeriği (API key gerektirmez)
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <link href="https://cdn.quilljs.com/1.3.6/quill.snow.css" rel="stylesheet">
            <style>
                body {{
                    margin: 0;
                    padding: 10px;
                    font-family: Arial, sans-serif;
                }}
                #editor-container {{
                    height: 400px;
                }}
            </style>
        </head>
        <body>
            <div id="editor-container"></div>
            <script src="https://cdn.quilljs.com/1.3.6/quill.js"></script>
            <script>
                var quill = new Quill('#editor-container', {{
                    theme: 'snow',
                    modules: {{
                        toolbar: [
                            [{{ 'header': [1, 2, 3, false] }}],
                            ['bold', 'italic', 'underline', 'strike'],
                            [{{ 'list': 'ordered'}}, {{ 'list': 'bullet' }}],
                            [{{ 'align': [] }}],
                            ['link', 'image'],
                            ['clean']
                        ]
                    }},
                    placeholder: 'Test açıklamasını buraya yazın...'
                }});
                
                // Mevcut içeriği yükle
                quill.root.innerHTML = `{initial_content}`;
            </script>
        </body>
        </html>
        """
        
        web_view.setHtml(html_content)
        layout.addWidget(web_view)

        # Butonlar
        button_row = QHBoxLayout()
        button_row.addStretch()

        btn_ok = QPushButton("Tamam")
        btn_ok.setFixedSize(80, 35)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        btn_cancel = QPushButton("İptal")
        btn_cancel.setFixedSize(80, 35)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)

        button_row.addWidget(btn_ok)
        button_row.addWidget(btn_cancel)
        layout.addLayout(button_row)

        def apply():
            """Quill.js içeriğini al ve kaydet"""
            def save_content(content):
                self.test_description = content or ''
                dlg.accept()
            
            # Quill.js içeriğini al (HTML formatında)
            js_code = "quill.root.innerHTML;"
            web_view.page().runJavaScript(js_code, save_content)

        def cancel():
            self.cb_description.setChecked(False)
            dlg.reject()

        btn_ok.clicked.connect(apply)
        btn_cancel.clicked.connect(cancel)

        dlg.exec_()
    
    def _open_test_description_dialog_advanced(self, dlg_parent):
        """Gelişmiş QTextEdit editörü (QWebEngineView yoksa)"""
        dlg = QDialog(dlg_parent)
        dlg.setWindowTitle("Test Açıklaması (QTextEdit Editörü)")
        dlg.setModal(True)
        dlg.setMinimumSize(700, 500)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setStyleSheet("""
            QToolBar {
                background-color: #F5F5F5;
                border: 1px solid #E0E0E0;
                border-radius: 4px;
                padding: 4px;
                spacing: 4px;
            }
            QToolButton {
                padding: 4px 8px;
                border: 1px solid #D0D0D0;
                border-radius: 3px;
                background-color: white;
            }
            QToolButton:hover {
                background-color: #E8E8E8;
            }
            QToolButton:pressed {
                background-color: #D0D0D0;
            }
        """)

        # Text editor - HTML modunda çalışacak
        text_editor = QTextEdit()
        if self.test_description:
            text_editor.setHtml(self.test_description)
        else:
            text_editor.setPlainText("")
        text_editor.setStyleSheet("""
            QTextEdit {
                border: 2px solid #E0E0E0;
                border-radius: 4px;
                padding: 8px;
                font-size: 14px;
                background-color: #FFFFFF;
            }
            QTextEdit:focus {
                border: 2px solid #9CAFAA;
            }
        """)

        # Formatlama fonksiyonu
        def apply_format(format_type):
            cursor = text_editor.textCursor()
            
            if format_type == 'bold':
                fmt = QTextCharFormat()
                fmt.setFontWeight(QFont.Bold if not cursor.charFormat().fontWeight() == QFont.Bold else QFont.Normal)
                cursor.mergeCharFormat(fmt)
            elif format_type == 'italic':
                fmt = QTextCharFormat()
                fmt.setFontItalic(not cursor.charFormat().fontItalic())
                cursor.mergeCharFormat(fmt)
            elif format_type == 'underline':
                fmt = QTextCharFormat()
                fmt.setUnderlineStyle(1 if cursor.charFormat().underlineStyle() == 0 else 0)
                cursor.mergeCharFormat(fmt)
            elif format_type == 'bullet':
                # Madde işareti ekle
                cursor.insertText("• ")
            elif format_type == 'align_left':
                fmt = QTextBlockFormat()
                fmt.setAlignment(Qt.AlignLeft)
                cursor.mergeBlockFormat(fmt)
            elif format_type == 'align_center':
                fmt = QTextBlockFormat()
                fmt.setAlignment(Qt.AlignCenter)
                cursor.mergeBlockFormat(fmt)
            elif format_type == 'align_right':
                fmt = QTextBlockFormat()
                fmt.setAlignment(Qt.AlignRight)
                cursor.mergeBlockFormat(fmt)
            
            text_editor.setTextCursor(cursor)

        # Formatlama butonları
        btn_bold = QPushButton("B")
        btn_bold.setCheckable(True)
        btn_bold.setToolTip("Kalın")
        btn_bold.setStyleSheet("font-weight: bold;")
        btn_bold.clicked.connect(lambda: apply_format('bold'))

        btn_italic = QPushButton("I")
        btn_italic.setCheckable(True)
        btn_italic.setToolTip("İtalik")
        btn_italic.setStyleSheet("font-style: italic;")
        btn_italic.clicked.connect(lambda: apply_format('italic'))

        btn_underline = QPushButton("U")
        btn_underline.setCheckable(True)
        btn_underline.setToolTip("Altı Çizili")
        btn_underline.setStyleSheet("text-decoration: underline;")
        btn_underline.clicked.connect(lambda: apply_format('underline'))

        btn_bullet = QPushButton("•")
        btn_bullet.setToolTip("Madde İşareti")
        btn_bullet.clicked.connect(lambda: apply_format('bullet'))

        btn_align_left = QPushButton("◄")
        btn_align_left.setToolTip("Sola Hizala")
        btn_align_left.clicked.connect(lambda: apply_format('align_left'))

        btn_align_center = QPushButton("◄►")
        btn_align_center.setToolTip("Ortala")
        btn_align_center.clicked.connect(lambda: apply_format('align_center'))

        btn_align_right = QPushButton("►")
        btn_align_right.setToolTip("Sağa Hizala")
        btn_align_right.clicked.connect(lambda: apply_format('align_right'))

        toolbar.addWidget(btn_bold)
        toolbar.addWidget(btn_italic)
        toolbar.addWidget(btn_underline)
        toolbar.addSeparator()
        toolbar.addWidget(btn_bullet)
        toolbar.addSeparator()
        toolbar.addWidget(btn_align_left)
        toolbar.addWidget(btn_align_center)
        toolbar.addWidget(btn_align_right)

        layout.addWidget(toolbar)
        layout.addWidget(text_editor)

        # Butonlar
        button_row = QHBoxLayout()
        button_row.addStretch()

        btn_ok = QPushButton("Tamam")
        btn_ok.setFixedSize(80, 35)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        btn_cancel = QPushButton("İptal")
        btn_cancel.setFixedSize(80, 35)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)

        button_row.addWidget(btn_ok)
        button_row.addWidget(btn_cancel)
        layout.addLayout(button_row)

        def apply():
            # HTML formatında kaydet (zengin metin formatını korumak için)
            self.test_description = text_editor.toHtml()
            dlg.accept()

        def cancel():
            # İptal edilirse checkbox'ı kaldır
            self.cb_description.setChecked(False)
            dlg.reject()

        btn_ok.clicked.connect(apply)
        btn_cancel.clicked.connect(cancel)

        dlg.exec_()


class QuestionPreviewDialog(QDialog):
    def __init__(self, parent, selection_data):
        super().__init__(parent)
        self.setWindowTitle("Soru Önizleme")

        self.selection_data = selection_data
        self.original_pixmap = None

        # UI elemanları
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)

        # Resim Alanı
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: white; border: 1px solid #ccc; border-radius: 8px;")

        self.main_layout.addWidget(self.image_label, alignment=Qt.AlignCenter)

        # Şıklar için buton grubu
        self.bottom_layout = QHBoxLayout()
        self.btn_group = QButtonGroup(self)
        self.answers = ["A", "B", "C", "D", "E"]
        for letter in self.answers:
            btn = QPushButton(letter)
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("""
                QPushButton {
                    border: 1px solid #DCCFC0; border-radius: 4px; background-color: #DCCFC0; font-weight: bold; font-size: 14px;
                }
                QPushButton:hover { background-color: #FFCC80; border: 1px solid orange; }
                QPushButton:checked { background-color: orange; border: 1px solid #F57C00; }
            """)
            self.bottom_layout.addWidget(btn)
            self.btn_group.addButton(btn)

        self.bottom_layout.addStretch()
        self.main_layout.addLayout(self.bottom_layout)

        # Sinyal bağlantıları
        self.btn_group.buttonClicked.connect(self.update_answer)

        self._load_selection()

    def _load_selection(self):
        self.setWindowTitle(f"{self.selection_data.number}. Soru Önizleme")

        doc = self.parent().viewer.pdf_docs.get(self.selection_data.pdf_key)
        if not doc: return
        page = doc.load_page(self.selection_data.page_index)
        zoom = self.parent().viewer.render_dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))

        fx, fy, fw, fh = self.selection_data.norm
        r = QRect(int(fx * pm.width()), int(fy * pm.height()),
                  int(fw * pm.width()), int(fh * pm.height()))
        self.original_pixmap = pm.copy(r)

        # Maksimum resim ve pencere boyutunu belirle
        max_width = 600
        max_height = 600

        # Resmin boyutunu kontrol et ve gerektiğinde küçült
        if self.original_pixmap.width() > max_width or self.original_pixmap.height() > max_height:
            scaled_pixmap = self.original_pixmap.scaled(
                QSize(max_width, max_height), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        else:
            scaled_pixmap = self.original_pixmap

        self.image_label.setFixedSize(scaled_pixmap.size())
        self.image_label.setPixmap(scaled_pixmap)

        # Pencere boyutunu, ölçeklenmiş resim boyutuna göre ayarla
        self.resize(scaled_pixmap.width() + 40, scaled_pixmap.height() + 100)

        # Ölçekleme artık sabit olduğu için preview_scale'i buna göre ayarla
        width_ratio = scaled_pixmap.width() / self.original_pixmap.width()
        height_ratio = scaled_pixmap.height() / self.original_pixmap.height()
        self.selection_data.preview_scale = min(width_ratio, height_ratio)

        for btn in self.btn_group.buttons():
            btn.setChecked(btn.text() == self.selection_data.answer)

    def update_answer(self, btn):
        self.selection_data.answer = btn.text()
        self.parent()._refresh_thumbnail(self.selection_data)
