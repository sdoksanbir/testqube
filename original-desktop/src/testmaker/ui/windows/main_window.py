import fitz
from pathlib import Path
import re
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGridLayout,
    QTabWidget, QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QSizePolicy, QMessageBox, QScrollArea, QDialog, QSlider, QButtonGroup, QFileDialog, QSpinBox, QDoubleSpinBox,
    QColorDialog, QTextEdit, QToolBar, QPlainTextEdit, QGroupBox, QRadioButton,)
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
from testmaker.ui.dialogs.theme_select_dialog import ThemeSelectDialog
from dataclasses import replace



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tesqube Builder")
        # showMaximized() app.py'de çağrılıyor

        self.thumb_count = 0
        self.question_answers = {}
        self.viewer = None

        # Export settings (advanced page setup)
        self.export_settings = ExportOptions()
        self.export_settings.columns = 2
        self.export_settings.question_gap_spaced_mm = 15.0  # Varsayılan boşluk
        # Tema / başlık tasarımı varsayılanları
        self.export_settings.header_style_id = "style1"
        self.export_settings.theme_color = "#1E88E5"  # canlı mavi (varsayılan)
        self.export_settings.use_description_box = False
        # Cevap anahtarı varsayılanları
        self.export_settings.answer_key_enabled = False
        self.export_settings.answer_key_mode = "per_page"  # per_page | separate_page | end_of_test

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
        main_widget.setStyleSheet("background-color: #2C2C2C;")
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("background-color: #2C2C2C;")

        # Sol panel
        self.left_panel = QTabWidget()
        self.left_panel.setTabPosition(QTabWidget.North)
        # Sekmeleri sola yaslamak için (genişliğe yayılmasın)
        self.left_panel.tabBar().setExpanding(False)
        self.left_panel.setStyleSheet("""
            QTabWidget::pane {
                background-color: #3F3F3F;
                border: none;
            }
        """)
        self.left_panel.tabBar().setStyleSheet("""
            QTabBar::tab {
                background: #5B8BAE; color: white;
                padding: 2px 4px; font-size:14px; font-weight:bold;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                margin:2px; min-width:100px; max-width:120px; height:30px;
            }
            QTabBar::tab:selected { background: #FF9800; color: white;}
            QTabBar::tab:hover { background: #FFB74D; color: white;}
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
        inner_widget.setStyleSheet("background-color:#F0F0F0;border:none;")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = FlowLayout(self.scroll_content, spacing=20)
        self.scroll_content.setLayout(self.scroll_layout)
        self.scroll_area.setWidget(self.scroll_content)
        inner_layout.addWidget(self.scroll_area)

        # Butonlar - görseldeki renklere göre
        btn_layout = QHBoxLayout()
        buttons = [
            # Şimdilik devre dışı: ileride soru bankası entegrasyonu yapılacak
            ("Soru Bankasından Seçin", "#D0D0D0", "#404040"),
            ("Kırpma Aracı", "#CBA2DA", "#FFFFFF"),
            ("Soru Editörü", "#98CADD", "#FFFFFF"),
            # Kaydet butonu ayrı renkte olsun
            ("Taslağı Kaydet", "#F4A261", "#FFFFFF"),
            ("Taslağı Geri Yükle", "#87E29F", "#FFFFFF")
        ]
        for text, color, text_color in buttons:
            btn = QPushButton(text)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    color: {text_color};
                    border-radius: 8px;
                    padding: 12px;
                    font-weight: bold;
                    font-size: 14px;
                    border: 1px solid {color};
                }}
                QPushButton:hover {{
                    background-color: {color};
                    color: {text_color};
                    border: 2px solid {color};
                    opacity: 0.9;
                }}
            """)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if text == "Kırpma Aracı":
                btn.clicked.connect(self.open_crop_tool)
            elif text == "Soru Bankasından Seçin":
                # Şimdilik kapalı
                btn.setEnabled(False)
            elif text == "Soru Editörü":
                btn.clicked.connect(self.open_question_editor)
            elif text == "Taslağı Geri Yükle":
                btn.clicked.connect(self.load_draft)
            elif text == "Taslağı Kaydet":
                btn.clicked.connect(self.save_current_draft)
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
        tab.setStyleSheet("background-color: #3F3F3F;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        style_input = """
            padding: 8px 12px;
            height: 32px;
            border-radius: 8px;
            border: 1px solid #E0E0E0;
            font-size: 14px;
            background-color: #FFFFFF;
            color: #000000;
        """
        style_input += """
            QLineEdit {
                background-color: #FFFFFF;
                color: #000000;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 2px solid #6DCF92;
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
        
        # İki checkbox'ı tek bir dikdörtgen grup içinde
        checkbox_container = QWidget()
        checkbox_container.setStyleSheet("""
            border: 2px solid white;
            border-radius: 8px;
            background-color: #4A5568;
            padding-left: 10px;
            padding-right: 10px;
            padding-top: 6px;
            padding-bottom: 6px;
        """)
        checkbox_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        checkbox_layout = QVBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(10, 6, 10, 6)
        checkbox_layout.setSpacing(0)
        
        self.cb_description = QCheckBox("Test ile ilgili açıklama ekle")
        self.cb_description.setStyleSheet("""
            font-size: 16px;
            min-height: 32px;
            padding-top: 0px;
            padding-bottom: 0px;
            margin-top: 0px;
            margin-bottom: 0px;
            background-color: transparent;
            border: none;
            color: white;
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                background-color: #FFFFFF;
                border: 2px solid #FFFFFF;
                border-radius: 6px;
            }
            QCheckBox::indicator:checked {
                background-color: #90CAF9; /* pastel mavi */
                border: 2px solid #90CAF9;
            }
        """)
        checkbox_layout.addWidget(self.cb_description)
        self.cb_description.setFocusPolicy(Qt.StrongFocus)
        self.cb_description.clicked.connect(lambda: self.cb_description.setFocus(Qt.MouseFocusReason))
        
        # Checkbox işaretlendiğinde dialog aç
        def open_description_dialog(checked):
            if checked:
                self._open_test_description_dialog()
            # Odak checkbox'ta kalsın (input'a geri zıplamasın)
            self.cb_description.setFocus(Qt.MouseFocusReason)
        self.cb_description.toggled.connect(open_description_dialog)
        
        self.cb_spacing = QCheckBox("Sorular arasına boşluk ekle")
        self.cb_spacing.setStyleSheet("""
            font-size: 16px;
            min-height: 32px;
            padding-top: 0px;
            padding-bottom: 0px;
            margin-top: 0px;
            margin-bottom: 0px;
            background-color: transparent;
            border: none;
            color: white;
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                background-color: #FFFFFF;
                border: 2px solid #FFFFFF;
                border-radius: 6px;
            }
            QCheckBox::indicator:checked {
                background-color: #90CAF9; /* pastel mavi */
                border: 2px solid #90CAF9;
            }
        """)
        checkbox_layout.addWidget(self.cb_spacing)
        self.cb_spacing.clicked.connect(self.on_spacing_clicked)
        self.cb_spacing.setFocusPolicy(Qt.StrongFocus)
        self.cb_spacing.clicked.connect(lambda: self.cb_spacing.setFocus(Qt.MouseFocusReason))
        
        self.cb_answer_key = QCheckBox("Teste cevap anahtarı ekle")
        self.cb_answer_key.setStyleSheet("""
            font-size: 16px;
            min-height: 32px;
            padding-top: 0px;
            padding-bottom: 0px;
            margin-top: 0px;
            margin-bottom: 0px;
            background-color: transparent;
            border: none;
            color: white;
            QCheckBox::indicator {
                width: 24px;
                height: 24px;
                background-color: #FFFFFF;
                border: 2px solid #FFFFFF;
                border-radius: 6px;
            }
            QCheckBox::indicator:checked {
                background-color: #90CAF9; /* pastel mavi */
                border: 2px solid #90CAF9;
            }
        """)
        checkbox_layout.addWidget(self.cb_answer_key)
        self.cb_answer_key.setFocusPolicy(Qt.StrongFocus)
        self.cb_answer_key.clicked.connect(lambda: self.cb_answer_key.setFocus(Qt.MouseFocusReason))
        self.cb_answer_key.toggled.connect(self._on_answer_key_toggled)

        # "Teste cevap anahtarı ekle" altına: Çizgi üzerine yazı ekle (Ayarlar'daki seçenek ile aynı)
        self.cb_center_line_text = QCheckBox("Çizgi üzerine yazı ekle")
        self.cb_center_line_text.setStyleSheet(self.cb_answer_key.styleSheet())
        checkbox_layout.addWidget(self.cb_center_line_text)
        self.cb_center_line_text.setFocusPolicy(Qt.StrongFocus)
        self.cb_center_line_text.clicked.connect(lambda: self.cb_center_line_text.setFocus(Qt.MouseFocusReason))

        # Inline input / düzenle butonu KALDIRILDI -> direk checkbox seçilince modern popup açılacak

        def _ensure_center_line_defaults():
            # Renk her zaman tema rengi olsun
            self.other_settings['center_line_text_color'] = getattr(self.export_settings, 'theme_color', '#1E88E5')
            if 'center_line_bold' not in self.other_settings:
                self.other_settings['center_line_bold'] = False

        # İlk durum: ayarlardan oku
        _cl_enabled = bool(self.other_settings.get('center_line_enabled', False))
        self.cb_center_line_text.setChecked(_cl_enabled)
        if _cl_enabled:
            _ensure_center_line_defaults()

        def _on_center_line_toggled(checked: bool):
            self.other_settings['center_line_enabled'] = bool(checked)
            if checked:
                _ensure_center_line_defaults()
                # Açılır pencereyi otomatik aç (GUARD: dialog içinde hata olursa uygulama kapanmasın)
                def _safe_open():
                    # Hata mesajı göstermeden direkt dialog'u açmayı dene
                    # Eğer hata olursa sessizce geç, dialog içinde zaten hata yakalanıyor
                    self._open_center_line_text_dialog()

                try:
                    from PyQt5.QtCore import QTimer
                    QTimer.singleShot(0, _safe_open)
                except Exception:
                    _safe_open()
                try:
                    self.cb_center_line_text.setFocus(Qt.MouseFocusReason)
                except Exception:
                    pass

        self.cb_center_line_text.toggled.connect(_on_center_line_toggled)

        layout.addWidget(checkbox_container)

        # Tema seçimi
        self.btn_theme_select = QPushButton("Tema Seç")
        self.btn_theme_select.setStyleSheet(
            "QPushButton{background-color:#FF9800;color:white;padding:10px;border-radius:6px;font-weight:bold;font-size:14px;} "
            "QPushButton:hover{background-color:#FFB74D;color:white;border:2px solid #FF9800;}"
        )
        self.btn_theme_select.clicked.connect(self.open_theme_select_dialog)
        layout.addWidget(self.btn_theme_select)

        self.btn_prepare = QPushButton("Kağıdı Hazırla")
        self.btn_prepare.setStyleSheet(
            "QPushButton{background-color:#5B8BAE;color:white;padding:10px;border-radius:6px;font-weight:bold;font-size:14px;} QPushButton:hover{background-color:#6BA0C4;color:white;border:2px solid #5B8BAE;}")
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

    def open_theme_select_dialog(self):
        """Tema / Başlık tasarımı seçimi popup'ını aç."""
        use_desc = bool(self.cb_description.isChecked()) if hasattr(self, "cb_description") else False
        dlg = ThemeSelectDialog(
            parent=self,
            current_style_id=getattr(self.export_settings, "header_style_id", "style1"),
            current_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
            use_description_box=use_desc,
        )
        if dlg.exec_() == QDialog.Accepted:
            choice = dlg.result_choice()
            self.export_settings.header_style_id = choice.header_style_id
            self.export_settings.theme_color = choice.theme_color
            self.export_settings.use_description_box = use_desc

    def _on_answer_key_toggled(self, checked: bool):
        """Cevap anahtarı seçimi: checkbox açılınca mod seçtir."""
        if not checked:
            self.export_settings.answer_key_enabled = False
            return

        mode = self._open_answer_key_mode_dialog()
        if not mode:
            # cancel -> revert checkbox
            self.cb_answer_key.blockSignals(True)
            try:
                self.cb_answer_key.setChecked(False)
            finally:
                self.cb_answer_key.blockSignals(False)
            self.export_settings.answer_key_enabled = False
            return

        self.export_settings.answer_key_enabled = True
        self.export_settings.answer_key_mode = mode

    def _open_answer_key_mode_dialog(self) -> str:
        dlg = QDialog(self)
        dlg.setWindowTitle("Cevap Anahtarı Seçenekleri")
        dlg.setModal(True)
        
        theme_col = getattr(self.export_settings, "theme_color", "#1E88E5")
        # Koyu tema - diğer dialog'larla uyumlu
        dlg.setStyleSheet(f"""
            QDialog {{
                background: #2C2C2C;
                border-radius: 14px;
            }}
            QLabel {{
                color: #EDEDED;
                font-size: 13px;
            }}
            QRadioButton {{
                font-size: 13px;
                color: #EDEDED;
                padding: 6px 8px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QGroupBox {{
                border: none;
            }}
        """)
        dlg.setMinimumWidth(420)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Cevap anahtarı nereye eklensin?")
        title.setStyleSheet("color:#EDEDED; font-size:15px; font-weight:700;")
        root.addWidget(title)

        grp = QGroupBox()
        grp.setStyleSheet("QGroupBox{border: none;}")
        v = QVBoxLayout(grp)
        v.setSpacing(8)

        rb_per_page = QRadioButton("Her sayfanın altına ekle")
        rb_separate = QRadioButton("Ayrı sayfaya ekle")
        rb_end = QRadioButton("Testin sonuna ekle")
        for rb in (rb_per_page, rb_separate, rb_end):
            v.addWidget(rb)

        current = getattr(self.export_settings, "answer_key_mode", "per_page") or "per_page"
        if current == "separate_page":
            rb_separate.setChecked(True)
        elif current == "end_of_test":
            rb_end.setChecked(True)
        else:
            rb_per_page.setChecked(True)

        root.addWidget(grp)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton("İPTAL")
        btn_ok = QPushButton("UYGULA")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: #3A3A3A;
                color: #EDEDED;
                border: none;
                border-radius: 10px;
                font-weight: 800;
                padding: 10px 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: #4A4A4A;
            }}
        """)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme_col};
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 800;
                padding: 10px 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {theme_col};
                opacity: 0.9;
            }}
        """)
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        if dlg.exec_() != QDialog.Accepted:
            return ""

        if rb_separate.isChecked():
            return "separate_page"
        if rb_end.isChecked():
            return "end_of_test"
        return "per_page"

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
        # Taslak DB'den gelen seçimlerde PDF olmayabilir. Bu durumda embedded_png kullanılır.
        has_embedded = bool(getattr(selection, 'embedded_png', None))
        if (not has_embedded) and (not self.viewer or not getattr(self.viewer, 'pdf_docs', None)):
            return
        
        self.thumb_count += 1
        question_widget = DraggableQuestion(selection_data=selection)
        question_widget.thumb_number_label.setText(f"{self.thumb_count}. Soru")

        question_widget.question_deleted.connect(self.remove_question)
        question_widget.preview_requested.connect(self.show_question_preview)

        cropped = None
        if has_embedded:
            try:
                pm = QPixmap()
                pm.loadFromData(selection.embedded_png, "PNG")
                cropped = pm
            except Exception:
                cropped = None
        else:
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

        if cropped is None:
            return

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
        try:
            dialog = QuestionPreviewDialog(self, selection_data)
            dialog.exec_()
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Önizleme Hatası", f"Soru önizleme açılamadı:\n{e}\n\n{traceback.format_exc()}")

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

        # PDF'e bağımlı olmayan taslaklarda (embedded_png) PDF açma zorunluluğu yok.
        all_embedded = all(bool(getattr(s, 'embedded_png', None)) for s in selections)
        if (not all_embedded) and (not self.viewer or not getattr(self.viewer, 'pdf_docs', None)):
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
            test_description=(self.test_description or "").strip() if (hasattr(self, "cb_description") and self.cb_description and self.cb_description.isChecked()) else "",
            header_style_id=getattr(self.export_settings, "header_style_id", "style3"),
            theme_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
            use_description_box=bool(self.cb_description.isChecked()) if hasattr(self, "cb_description") else False,
            answer_key_enabled=bool(self.cb_answer_key.isChecked()) if hasattr(self, "cb_answer_key") else False,
            answer_key_mode=getattr(self.export_settings, "answer_key_mode", "per_page"),
            # Tema seçimi: tüm çizgiler tema rengi ile aynı olsun
            line_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
            spaced=self.cb_spacing.isChecked(),
            question_gap_spaced_mm=self.export_settings.question_gap_spaced_mm if self.cb_spacing.isChecked() else self.export_settings.question_gap_mm,
            smart_layout=False,
            watermark_enabled=bool(self.other_settings.get('watermark_enabled', False)) if hasattr(self, 'other_settings') else (self.chk_watermark.isChecked() if hasattr(self, 'chk_watermark') else False),
            watermark_mode=self.other_settings.get('watermark_mode', 'text'),
            watermark_text=self.other_settings.get('watermark_text', ''),
            watermark_text_opacity_pct=int(self.other_settings.get('watermark_text_opacity', 20)),
            watermark_text_size_pct=int(self.other_settings.get('watermark_text_size', 90)),
            watermark_text_angle_deg=int(self.other_settings.get('watermark_text_angle', 45)),
            watermark_text_color=self.other_settings.get('watermark_text_color', getattr(self.export_settings, 'theme_color', '#AECBFA')),
            watermark_image_path=self.other_settings.get('watermark_image_path', ''),
            watermark_image_opacity_pct=int(self.other_settings.get('watermark_image_opacity', 15)),
            watermark_image_size_pct=int(self.other_settings.get('watermark_image_size', 50)),
            center_line_enabled=self.other_settings.get('center_line_enabled', False),
            center_line_text=self.other_settings.get('center_line_text', ''),
            center_line_bold=self.other_settings.get('center_line_bold', False),
            center_line_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
            center_line_text_direction=self.other_settings.get('center_line_text_direction', 'up'),
            # Font normalization (hidden from UI): always ON, fixed to 11pt
            normalize_question_font=True,
            target_question_font_pt=11.0,
        )
        
        # Ön izleme dialog'unu aç (render_dpi'yi de geç)
        pdf_docs = self.viewer.pdf_docs if (self.viewer and getattr(self.viewer, 'pdf_docs', None)) else {}
        render_dpi = self.viewer.render_dpi if self.viewer else 300.0
        preview_dialog = PDFPreviewDialog(self, selections, opts, pdf_docs, render_dpi=render_dpi)
        # Dialog showEvent içinde tam ekran açılacak
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
        
        # Seçimleri gömülü PNG olarak kaydedeceğiz (PDF'lere bağımlılık kalksın).
        # Dosya yolu seç
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Taslağı Kaydet",
            "taslak.db",
            "Taslak Dosyaları (*.db *.tmd);;JSON (eski) (*.json);;Tüm Dosyalar (*.*)"
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
                # UI durumları (taslak geri yüklenince checkbox'lar da aynı gelsin)
                'ui_spacing_enabled': bool(self.cb_spacing.isChecked()) if hasattr(self, 'cb_spacing') else False,
                'ui_description_enabled': bool(self.cb_description.isChecked()) if hasattr(self, 'cb_description') else False,
                'ui_answer_key_enabled': bool(self.cb_answer_key.isChecked()) if hasattr(self, 'cb_answer_key') else False,
            }

            # Export ayarlarını "gerçek" (UI'dan okunmuş) haliyle kaydet.
            # Not: self.export_settings.__dict__ tek başına yeterli değil; çünkü test açıklaması ve checkbox'lar
            # export anında build_export_options ile birleştiriliyor.
            effective_opts = build_export_options(
                self.export_settings,
                test_title=self.input_test_name.text().strip() or "TEST",
                school_name=self.input_school.text().strip(),
                branch_name="",
                teacher_name="",
                test_description=(self.test_description or "").strip() if (hasattr(self, "cb_description") and self.cb_description and self.cb_description.isChecked()) else "",
                header_style_id=getattr(self.export_settings, "header_style_id", "style3"),
                theme_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
                use_description_box=bool(self.cb_description.isChecked()) if hasattr(self, "cb_description") else False,
                answer_key_enabled=bool(self.cb_answer_key.isChecked()) if hasattr(self, "cb_answer_key") else False,
                answer_key_mode=getattr(self.export_settings, "answer_key_mode", "per_page"),
                line_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
                spaced=bool(self.cb_spacing.isChecked()) if hasattr(self, "cb_spacing") else False,
                question_gap_spaced_mm=(self.export_settings.question_gap_spaced_mm if (hasattr(self, "cb_spacing") and self.cb_spacing.isChecked()) else self.export_settings.question_gap_mm),
                smart_layout=False,
            watermark_enabled=bool(self.other_settings.get('watermark_enabled', False)) if hasattr(self, 'other_settings') else (self.chk_watermark.isChecked() if hasattr(self, 'chk_watermark') else False),
            watermark_mode=self.other_settings.get('watermark_mode', 'text'),
            watermark_text=self.other_settings.get('watermark_text', ''),
            watermark_text_opacity_pct=int(self.other_settings.get('watermark_text_opacity', 20)),
            watermark_text_size_pct=int(self.other_settings.get('watermark_text_size', 90)),
            watermark_text_angle_deg=int(self.other_settings.get('watermark_text_angle', 45)),
            watermark_text_color=self.other_settings.get('watermark_text_color', getattr(self.export_settings, 'theme_color', '#AECBFA')),
            watermark_image_path=self.other_settings.get('watermark_image_path', ''),
            watermark_image_opacity_pct=int(self.other_settings.get('watermark_image_opacity', 15)),
            watermark_image_size_pct=int(self.other_settings.get('watermark_image_size', 50)),
                center_line_enabled=self.other_settings.get('center_line_enabled', False),
                center_line_text=self.other_settings.get('center_line_text', ''),
                center_line_bold=self.other_settings.get('center_line_bold', False),
                center_line_color=getattr(self.export_settings, "theme_color", "#AECBFA"),
                center_line_text_direction=self.other_settings.get('center_line_text_direction', 'up'),
                normalize_question_font=True,
                target_question_font_pt=11.0,
            )
            
            # PDF'ten kırpıp embedded_png alanına yaz
            # Not: Halihazırda embedded olan sorular varsa (taslaktan yüklenmiş), onları aynen koru.
            for sel in selections:
                if getattr(sel, 'embedded_png', None):
                    continue
                if not self.viewer or not getattr(self.viewer, 'pdf_docs', None):
                    # PDF yoksa embedded üretilemez; ama bu durumda zaten yukarıda soru eklemeden gelmez.
                    continue
                doc = self.viewer.pdf_docs.get(sel.pdf_key)
                if not doc:
                    continue
                try:
                    page = doc.load_page(sel.page_index)
                    zoom = float(getattr(self.viewer, 'render_dpi', 300) or 300) / 72.0
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))

                    fx, fy, fw, fh = sel.norm
                    r = QRect(int(fx * pm.width()), int(fy * pm.height()),
                              int(fw * pm.width()), int(fh * pm.height()))
                    r = r.intersected(QRect(0, 0, pm.width(), pm.height()))
                    if r.width() <= 0 or r.height() <= 0:
                        continue
                    cropped = pm.copy(r)

                    # Pixmap -> PNG bytes
                    from PyQt5.QtCore import QBuffer, QByteArray
                    ba = QByteArray()
                    buf = QBuffer(ba)
                    buf.open(QBuffer.WriteOnly)
                    cropped.save(buf, "PNG")
                    buf.close()
                    sel.embedded_png = bytes(ba)
                    sel.embedded_w_px = int(cropped.width())
                    sel.embedded_h_px = int(cropped.height())
                except Exception:
                    continue

            draft = Draft(
                selections=selections,
                export_settings=effective_opts.__dict__ if hasattr(effective_opts, '__dict__') else {},
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
            "Taslak Dosyaları (*.db *.tmd *.json);;Tüm Dosyalar (*.*)"
        )
        if not path:
            return
        
        try:
            draft = load_draft(Path(path))
            
            # DB taslaklarında sorular gömülü olduğundan PDF açma zorunluluğu yok.
            all_embedded = all(bool(getattr(s, 'embedded_png', None)) for s in draft.selections)
            if (not all_embedded):
                # Legacy JSON veya eksik embedded içerik -> PDF'ler gerekli
                if not self.viewer or not getattr(self.viewer, 'pdf_docs', None):
                    QMessageBox.warning(
                        self,
                        "PDF Gerekli",
                        "Bu taslak PDF'lere bağlı. Yüklemek için önce Kırpma Aracı'ndan PDF'leri açın."
                    )
                    return

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
            if self.viewer:
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

                # UI checkbox durumlarını geri yükle
                try:
                    if hasattr(self, 'cb_spacing') and 'ui_spacing_enabled' in draft.test_info:
                        self.cb_spacing.blockSignals(True)
                        self.cb_spacing.setChecked(bool(draft.test_info.get('ui_spacing_enabled')))
                        self.cb_spacing.blockSignals(False)
                    if hasattr(self, 'cb_description') and 'ui_description_enabled' in draft.test_info:
                        self.cb_description.blockSignals(True)
                        self.cb_description.setChecked(bool(draft.test_info.get('ui_description_enabled')))
                        self.cb_description.blockSignals(False)
                    if hasattr(self, 'cb_answer_key') and 'ui_answer_key_enabled' in draft.test_info:
                        self.cb_answer_key.blockSignals(True)
                        self.cb_answer_key.setChecked(bool(draft.test_info.get('ui_answer_key_enabled')))
                        self.cb_answer_key.blockSignals(False)
                except Exception:
                    pass
            
            # Export ayarlarını yükle
            if draft.export_settings:
                for key, value in draft.export_settings.items():
                    if hasattr(self.export_settings, key):
                        setattr(self.export_settings, key, value)

                # Test açıklaması export_settings içinde geliyorsa UI state'e de yaz
                try:
                    if 'test_description' in draft.export_settings:
                        self.test_description = draft.export_settings.get('test_description') or ''
                except Exception:
                    pass

                
                # Kağıt boyutu UI'ını export_settings'ten senkronla
                try:
                    preset = (getattr(self.export_settings, 'page_preset', 'A4') or 'A4').upper().strip()
                    # UI hedef text
                    def _find_item_text(prefix: str, items):
                        for it in items:
                            if it.upper().startswith(prefix):
                                return it
                        return None

                    # Combo item listesi (mevcut combodan okuyalım)
                    combos = []
                    if hasattr(self, 'cmb_paper') and self.cmb_paper is not None:
                        combos.append(self.cmb_paper)

                    if preset == 'CUSTOM':
                        for cmb in combos:
                            cmb.blockSignals(True)
                            cmb.setCurrentText('Özel (mm)')
                            cmb.blockSignals(False)
                        if hasattr(self, 'spin_w_mm') and self.spin_w_mm is not None:
                            self.spin_w_mm.setValue(int(getattr(self.export_settings, 'page_width_mm', 210) or 210))
                        if hasattr(self, 'spin_h_mm') and self.spin_h_mm is not None:
                            self.spin_h_mm.setValue(int(getattr(self.export_settings, 'page_height_mm', 297) or 297))
                    else:
                        for cmb in combos:
                            items = [cmb.itemText(i) for i in range(cmb.count())]
                            tgt = _find_item_text(preset, items)
                            if tgt:
                                cmb.blockSignals(True)
                                cmb.setCurrentText(tgt)
                                cmb.blockSignals(False)

                    # export_settings'i advanced UI'dan bir kez daha uygula (margins/orientation vs. etkilenmesin)
                    if hasattr(self, '_apply_export_settings_from_advanced') and hasattr(self, 'cmb_paper') and self.cmb_paper is not None:
                        try:
                            self._apply_export_settings_from_advanced()
                        except Exception:
                            pass
                except Exception:
                    pass

                # Checkbox'lar export_settings içinden de gelebilir (json/db fark etmez)
                try:
                    if hasattr(self, 'cb_spacing') and 'spaced' in draft.export_settings:
                        self.cb_spacing.blockSignals(True)
                        self.cb_spacing.setChecked(bool(draft.export_settings.get('spaced')))
                        self.cb_spacing.blockSignals(False)
                    if hasattr(self, 'cb_description') and 'use_description_box' in draft.export_settings:
                        self.cb_description.blockSignals(True)
                        self.cb_description.setChecked(bool(draft.export_settings.get('use_description_box')))
                        self.cb_description.blockSignals(False)
                    if hasattr(self, 'cb_answer_key') and 'answer_key_enabled' in draft.export_settings:
                        self.cb_answer_key.blockSignals(True)
                        self.cb_answer_key.setChecked(bool(draft.export_settings.get('answer_key_enabled')))
                        self.cb_answer_key.blockSignals(False)
                except Exception:
                    pass
            
            # Diğer ayarları yükle
            if draft.other_settings:
                self.other_settings.update(draft.other_settings)

            # UI: Çizgi üzerine yazı ekle (Test Kağıdı sekmesi)
            try:
                if hasattr(self, 'cb_center_line_text'):
                    cl_enabled = bool(self.other_settings.get('center_line_enabled', False))
                    self.cb_center_line_text.blockSignals(True)
                    self.cb_center_line_text.setChecked(cl_enabled)
                    self.cb_center_line_text.blockSignals(False)
            except Exception:
                pass
            
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
        # Odak checkbox'ta kalsın (input'a geri zıplamasın)
        try:
            self.cb_spacing.setFocus(Qt.MouseFocusReason)
        except Exception:
            pass

    def show_about(self):
        """Hakkında dialogunu gösterir."""
        QMessageBox.about(
            self,
            "Hakkında",
            "<h2>Tesqube Builder</h2>"
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
        tab.setStyleSheet("background-color: #3F3F3F;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Gelişmiş Ayarlar")
        title.setStyleSheet("font-weight:800; font-size:16px;")
        layout.addWidget(title)

        # Filigran
        self.chk_watermark = QCheckBox("Filigran ekle")
        layout.addWidget(self.chk_watermark)

        # Checkbox seçilince popup aç
        def _on_watermark_toggled(state: int):
            enabled = self.chk_watermark.isChecked()
            self.other_settings['watermark_enabled'] = bool(enabled)
            if enabled:
                try:
                    from PyQt5.QtCore import QTimer
                    QTimer.singleShot(0, self._open_watermark_dialog)
                except Exception:
                    self._open_watermark_dialog()

        self.chk_watermark.stateChanged.connect(_on_watermark_toggled)

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
        self.cmb_paper.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        layout.addWidget(self.cmb_paper)

        # Custom size mm
        custom_size_widget = QWidget()
        custom_row = QHBoxLayout(custom_size_widget)
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.setSpacing(8)

        self.spin_w_mm = QSpinBox()
        self.spin_w_mm.setRange(50, 2000)
        self.spin_w_mm.setValue(210)
        self.spin_w_mm.setSuffix(" mm")
        self.spin_w_mm.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        self.spin_h_mm = QSpinBox()
        self.spin_h_mm.setRange(50, 2000)
        self.spin_h_mm.setValue(297)
        self.spin_h_mm.setSuffix(" mm")
        self.spin_h_mm.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        custom_row.addWidget(QLabel("Genişlik:"))
        custom_row.addWidget(self.spin_w_mm)
        custom_row.addWidget(QLabel("Yükseklik:"))
        custom_row.addWidget(self.spin_h_mm)
        layout.addWidget(custom_size_widget)
        self._custom_size_widget = custom_size_widget

        # Orientation
        layout.addWidget(QLabel("Yönlendirme"))
        self.cmb_orientation = QComboBox()
        self.cmb_orientation.addItems(["Dikey", "Yatay"])
        self.cmb_orientation.setStyleSheet("background-color: #FFFFFF; color: #000000;")
        layout.addWidget(self.cmb_orientation)

        # Columns
        layout.addWidget(QLabel("Sütun sayısı"))
        self.cmb_columns = QComboBox()
        self.cmb_columns.addItems([str(i) for i in range(1, 7)])
        self.cmb_columns.setCurrentText("2")
        self.cmb_columns.setStyleSheet("background-color: #FFFFFF; color: #000000;")
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
        self.cmb_margin_preset.setStyleSheet("background-color: #FFFFFF; color: #000000;")
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
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle("Çizgi Üzeri Yazı")
            dlg.setModal(True)

            # Modern görünüm (renk her zaman tema rengi, renk seçimi yok)
            theme_col = getattr(self.export_settings, "theme_color", "#1E88E5")
            dlg.setMinimumWidth(460)
            dlg.setStyleSheet(f"""
            QDialog {{
                background: #2C2C2C;
                border-radius: 14px;
            }}
            QLabel {{
                color: #EDEDED;
                font-size: 13px;
            }}
            QLineEdit {{
                background: #FFFFFF;
                border: 1px solid #555555;
                border-radius: 10px;
                padding: 4px 8px;
                font-size: 14px;
                color: #000000;
                min-height: 34px;
            }}
            QLineEdit:focus {{
                border: 1px solid {theme_col};
            }}
        """)

            v = QVBoxLayout(dlg)
            v.setContentsMargins(18, 18, 18, 18)
            v.setSpacing(14)

            # Input alanı
            input_txt = QLineEdit(self.other_settings.get("center_line_text", ""))
            v.addWidget(input_txt)

            # state
            state = {
                "bold": self.other_settings.get("center_line_bold", False),
            }

            # Tamam ve İptal butonları yan yana - Kalın butonu solda
            button_row = QHBoxLayout()
            button_row.setSpacing(10)
            
            # Kalın butonu - sola yasla
            btn_b = QPushButton("Kalın")
            btn_b.setCheckable(True)
            btn_b.setChecked(state["bold"])
            btn_b.setFixedSize(80, 35)
            btn_b.setCursor(Qt.PointingHandCursor)
            btn_b.setStyleSheet(f"""
                QPushButton {{
                    font-weight: 800;
                    font-size: 14px;
                    border: 1px solid #E5E7EB;
                    border-radius: 10px;
                    background-color: #F3F4F6;
                    color: #111;
                }}
                QPushButton:checked {{
                    /* aktif olduğu belli olsun: tema renginden farklı bir renk */
                    background-color: #22C55E;
                    border: 1px solid #22C55E;
                    color: white;
                }}
                QPushButton:hover {{
                    background-color: #E5E7EB;
                }}
            """)
            
            def toggle_b():
                state["bold"] = btn_b.isChecked()
            btn_b.toggled.connect(toggle_b)
            
            button_row.addWidget(btn_b, 0)  # Kalın butonu sola
            button_row.addStretch(1)  # Boşluk ekle
            
            # Tamam ve İptal butonları - sağa yasla
            btn_ok = QPushButton("Tamam")
            btn_ok.setFixedSize(80, 35)
            btn_ok.setStyleSheet(f"""
                QPushButton {{
                    background-color: {theme_col};
                    color: white;
                    border: none;
                    border-radius: 10px;
                    font-weight: 700;
                    font-size: 14px;
                    padding: 6px 14px;
                }}
                QPushButton:hover {{
                    background-color: {theme_col};
                }}
            """)
            
            btn_cancel = QPushButton("İptal")
            btn_cancel.setFixedSize(80, 35)
            btn_cancel.setStyleSheet("""
                QPushButton {
                    background-color: #E5E7EB;
                    color: #111;
                    border: none;
                    border-radius: 10px;
                    font-weight: 700;
                    font-size: 14px;
                    padding: 6px 14px;
                }
                QPushButton:hover {
                    background-color: #D1D5DB;
                }
            """)
            
            button_row.addWidget(btn_ok)
            button_row.addWidget(btn_cancel)
            v.addLayout(button_row)

            def apply():
                self.other_settings["center_line_text"] = input_txt.text().strip()
                self.other_settings["center_line_bold"] = state["bold"]
                # Renk her zaman tema rengi
                self.other_settings["center_line_text_color"] = theme_col
                dlg.accept()

            btn_ok.clicked.connect(apply)
            btn_cancel.clicked.connect(dlg.reject)
            
            # Enter tuşu ile de kaydet
            input_txt.returnPressed.connect(apply)
            
            dlg.exec_()
        except Exception as e:
            # Hata oluşursa sessizce geç ve varsayılan değerleri kullan
            import traceback
            traceback.print_exc()
            # Dialog açılamazsa en azından varsayılan değerleri ayarla
            if 'center_line_text' not in self.other_settings:
                self.other_settings['center_line_text'] = ''
            if 'center_line_bold' not in self.other_settings:
                self.other_settings['center_line_bold'] = False
            if 'center_line_text_color' not in self.other_settings:
                self.other_settings['center_line_text_color'] = getattr(self.export_settings, "theme_color", "#1E88E5")

    
    def _open_watermark_dialog(self):
        """Filigran ayarları popup (metin veya görsel)."""
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QRadioButton,
            QPushButton, QSlider, QFileDialog, QWidget, QColorDialog, QMessageBox
        )
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor

        theme_col = getattr(self.export_settings, "theme_color", "#1E88E5")

        # defaults
        ws = self.other_settings
        ws.setdefault('watermark_enabled', bool(getattr(self, 'chk_watermark', None) and self.chk_watermark.isChecked()))
        ws.setdefault('watermark_mode', 'text')  # text | image
        ws.setdefault('watermark_text', '')
        ws.setdefault('watermark_text_opacity', 20)   # percent
        ws.setdefault('watermark_text_size', 90)      # percent
        ws.setdefault('watermark_text_angle', 45)     # degrees
        ws.setdefault('watermark_text_color', theme_col)
        ws.setdefault('watermark_image_path', '')
        ws.setdefault('watermark_image_opacity', 15)  # percent
        ws.setdefault('watermark_image_size', 50)     # percent

        dlg = QDialog(self)
        dlg.setWindowTitle("FİLİGRAN EKLE")
        dlg.setModal(True)
        dlg.setMinimumWidth(520)

        dlg.setStyleSheet(f"""
            QDialog {{
                background: #2C2C2C;
            }}
            QWidget#HeaderBar {{
                background: #1F1F1F;
                border-radius: 10px;
            }}
            QLabel {{
                color: #EDEDED;
                font-size: 13px;
            }}
            QLabel#DialogTitle {{
                color: #EDEDED;
                font-weight: 900;
                font-size: 15px;
                letter-spacing: 0.5px;
                padding: 8px 10px;
                background: #1F1F1F;
                border-radius: 10px;
            }}
            QRadioButton {{
                font-size: 13px;
                color: #EDEDED;
                padding: 6px 8px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
            QWidget#Panel {{
                background: #232323;
                border: 1px solid #3A3A3A;
                border-radius: 12px;
            }}
            QLineEdit {{
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 10px 12px;
                font-size: 14px;
                color: #111;
                min-height: 36px;
            }}
            QLineEdit:focus {{
                border: 2px solid {theme_col};
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: #5A5A5A;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: {theme_col};
            }}
            QPushButton#Primary {{
                background-color: {theme_col};
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 800;
                padding: 10px 18px;
            }}
            QPushButton#Primary:hover {{
                background-color: {theme_col};
            }}
            QPushButton#Secondary {{
                background-color: #3A3A3A;
                color: #EDEDED;
                border: none;
                border-radius: 10px;
                font-weight: 800;
                padding: 10px 18px;
            }}
            QPushButton#Secondary:hover {{
                background-color: #4A4A4A;
            }}
            QPushButton#PickButton {{
                background-color: {theme_col};
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 800;
                padding: 6px 12px;
            }}
            QPushButton#PickButton:hover {{
                background-color: {theme_col};
                opacity: 0.9;
            }}
        """)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # Title
        title = QLabel("FİLİGRAN EKLE")
        title.setObjectName("DialogTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        # Divider
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet("background:#3A3A3A;")
        root.addWidget(div)

        # Mode radios (başlık barı içinde) - QButtonGroup ile birbirini dışlamalı
        rb_text = QRadioButton("Metin Filigranı")
        rb_img = QRadioButton("Görsel Filigran")
        radio_group = QButtonGroup(dlg)
        radio_group.addButton(rb_text, 0)
        radio_group.addButton(rb_img, 1)
        
        # Varsayılan seçimi ayarla
        current_mode = ws.get('watermark_mode', 'text')
        if current_mode == 'image':
            rb_img.setChecked(True)
        else:
            rb_text.setChecked(True)

        header_text = QWidget(); header_text.setObjectName("HeaderBar")
        htl = QHBoxLayout(header_text)
        htl.setContentsMargins(10, 6, 10, 6)
        htl.addWidget(rb_text)
        root.addWidget(header_text)

        # Text panel
        text_panel = QWidget(); text_panel.setObjectName("Panel")
        tv = QVBoxLayout(text_panel)
        tv.setContentsMargins(14, 12, 14, 12)
        tv.setSpacing(10)

        txt_input = QLineEdit(ws.get('watermark_text',''))
        txt_input.setPlaceholderText("Basılı filigran için yazı belirleyin")
        tv.addWidget(txt_input)

        def slider_row(label_left: str, slider: QSlider, value_label: QLabel):
            row = QHBoxLayout()
            row.setContentsMargins(0,0,0,0)
            row.setSpacing(10)
            l = QLabel(label_left)
            l.setFixedWidth(90)
            row.addWidget(l)
            row.addWidget(slider, 1)
            row.addWidget(value_label)
            w = QWidget(); w.setLayout(row)
            return w

        # Opacity
        op_slider = QSlider(Qt.Horizontal)
        op_slider.setRange(1, 100)
        op_slider.setValue(int(ws.get('watermark_text_opacity',20)))
        op_val = QLabel(f"%{op_slider.value()}")
        op_slider.valueChanged.connect(lambda v: op_val.setText(f"%{v}"))
        tv.addWidget(slider_row("Opaklık:", op_slider, op_val))

        # Size - maksimum 150% yap (100% çok büyük)
        sz_slider = QSlider(Qt.Horizontal)
        sz_slider.setRange(10, 150)
        sz_slider.setValue(int(ws.get('watermark_text_size',90)))
        sz_val = QLabel(f"%{sz_slider.value()}")
        sz_slider.valueChanged.connect(lambda v: sz_val.setText(f"%{v}"))
        tv.addWidget(slider_row("Büyüklük:", sz_slider, sz_val))

        # Angle
        ang_slider = QSlider(Qt.Horizontal)
        ang_slider.setRange(-90, 90)
        ang_slider.setValue(int(ws.get('watermark_text_angle',45)))
        ang_val = QLabel(f"{ang_slider.value()}°")
        ang_slider.valueChanged.connect(lambda v: ang_val.setText(f"{v}°"))
        tv.addWidget(slider_row("Açı:", ang_slider, ang_val))

        # Color
        color_row = QHBoxLayout(); color_row.setContentsMargins(0,0,0,0); color_row.setSpacing(10)
        color_row.addWidget(QLabel("Renk:"), 0)
        btn_color = QPushButton("")
        btn_color.setFixedSize(26, 18)
        btn_color.setStyleSheet(f"background:{ws.get('watermark_text_color', theme_col)}; border:1px solid #111; border-radius:2px;")

        def pick_color():
            col = QColor(ws.get('watermark_text_color', theme_col))
            chosen = QColorDialog.getColor(col, dlg, "Renk Seç")
            if chosen.isValid():
                ws['watermark_text_color'] = chosen.name()
                btn_color.setStyleSheet(f"background:{chosen.name()}; border:1px solid #111; border-radius:2px;")

        btn_color.clicked.connect(pick_color)
        color_row.addWidget(btn_color, 0)
        color_row.addStretch(1)
        cw = QWidget(); cw.setLayout(color_row)
        tv.addWidget(cw)

        root.addWidget(text_panel)

        # Image radio
        header_img = QWidget(); header_img.setObjectName("HeaderBar")
        hil = QHBoxLayout(header_img)
        hil.setContentsMargins(10, 6, 10, 6)
        hil.addWidget(rb_img)
        root.addWidget(header_img)

        img_panel = QWidget(); img_panel.setObjectName("Panel")
        iv = QVBoxLayout(img_panel)
        iv.setContentsMargins(14, 12, 14, 12)
        iv.setSpacing(10)

        # image picker row
        pick_row = QHBoxLayout(); pick_row.setContentsMargins(0,0,0,0); pick_row.setSpacing(10)
        img_path_lbl = QLabel(ws.get('watermark_image_path','') or "")
        img_path_lbl.setStyleSheet("color:#BDBDBD; font-size:12px;")
        img_path_lbl.setWordWrap(True)
        btn_pick = QPushButton("Görsel Seç")
        btn_pick.setObjectName("PickButton")
        # Butonu içeriğe göre boyutlandır (sizeHint kullan)
        btn_pick.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        def pick_image():
            fp, _ = QFileDialog.getOpenFileName(dlg, "Filigran Görseli Seç", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
            if fp:
                ws['watermark_image_path'] = fp
                img_path_lbl.setText(fp)

        btn_pick.clicked.connect(pick_image)
        pick_row.addWidget(btn_pick, 0)
        pick_row.addWidget(img_path_lbl, 1)
        pw = QWidget(); pw.setLayout(pick_row)
        iv.addWidget(pw)

        # Image opacity
        iop_slider = QSlider(Qt.Horizontal)
        iop_slider.setRange(1, 100)
        iop_slider.setValue(int(ws.get('watermark_image_opacity',15)))
        iop_val = QLabel(f"%{iop_slider.value()}")
        iop_slider.valueChanged.connect(lambda v: iop_val.setText(f"%{v}"))
        iv.addWidget(slider_row("Opaklık:", iop_slider, iop_val))

        # Image size - maksimum 150% yap
        isz_slider = QSlider(Qt.Horizontal)
        isz_slider.setRange(10, 150)
        isz_slider.setValue(int(ws.get('watermark_image_size',50)))
        isz_val = QLabel(f"%{isz_slider.value()}")
        isz_slider.valueChanged.connect(lambda v: isz_val.setText(f"%{v}"))
        iv.addWidget(slider_row("Büyüklük:", isz_slider, isz_val))

        root.addWidget(img_panel)

        def refresh_panels():
            is_text = rb_text.isChecked()
            text_panel.setEnabled(is_text)
            img_panel.setEnabled(not is_text)

        rb_text.toggled.connect(refresh_panels)
        rb_img.toggled.connect(refresh_panels)
        refresh_panels()

        # Buttons
        btn_row = QHBoxLayout(); btn_row.setContentsMargins(0,0,0,0); btn_row.setSpacing(10)
        btn_row.addStretch(1)
        btn_ok = QPushButton("TAMAM"); btn_ok.setObjectName("Primary")
        btn_cancel = QPushButton("İPTAL"); btn_cancel.setObjectName("Secondary")
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        root.addLayout(btn_row)

        def apply_and_close():
            # determine mode
            mode = 'text' if rb_text.isChecked() else 'image'
            ws['watermark_mode'] = mode
            ws['watermark_text'] = (txt_input.text() or '').strip()
            ws['watermark_text_opacity'] = int(op_slider.value())
            ws['watermark_text_size'] = int(sz_slider.value())
            ws['watermark_text_angle'] = int(ang_slider.value())
            ws.setdefault('watermark_text_color', theme_col)
            ws['watermark_image_opacity'] = int(iop_slider.value())
            ws['watermark_image_size'] = int(isz_slider.value())

            if mode == 'text':
                if not ws['watermark_text']:
                    QMessageBox.warning(dlg, "Uyarı", "Metin filigranı için bir yazı girin.")
                    return
            else:
                if not (ws.get('watermark_image_path') or '').strip():
                    QMessageBox.warning(dlg, "Uyarı", "Görsel filigran için bir görsel seçin.")
                    return

            dlg.accept()

        def cancel():
            dlg.reject()

        btn_ok.clicked.connect(apply_and_close)
        btn_cancel.clicked.connect(cancel)

        res = dlg.exec_()
        if res != QDialog.Accepted:
            # iptal olursa kapat / devre dışı bırak
            try:
                self.chk_watermark.blockSignals(True)
                self.chk_watermark.setChecked(False)
            finally:
                self.chk_watermark.blockSignals(False)
            ws['watermark_enabled'] = False
        else:
            ws['watermark_enabled'] = True

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
                .ql-editor {{
                    font-size: 9pt;
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

        theme_col = getattr(self.export_settings, "theme_color", "#1E88E5")
        btn_ok = QPushButton("Tamam")
        btn_ok.setFixedSize(80, 35)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme_col};
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 700;
                font-size: 14px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {theme_col};
                opacity: 0.9;
            }}
        """)

        btn_cancel = QPushButton("İptal")
        btn_cancel.setFixedSize(80, 35)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 700;
                font-size: 14px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #C82333;
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

        theme_col = getattr(self.export_settings, "theme_color", "#1E88E5")
        btn_ok = QPushButton("Tamam")
        btn_ok.setFixedSize(80, 35)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme_col};
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 700;
                font-size: 14px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {theme_col};
                opacity: 0.9;
            }}
        """)

        btn_cancel = QPushButton("İptal")
        btn_cancel.setFixedSize(80, 35)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: 700;
                font-size: 14px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #C82333;
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

        # Taslak DB'den gelen sorular PDF'e bağlı olmayabilir.
        if getattr(self.selection_data, 'embedded_png', None):
            pm = QPixmap()
            pm.loadFromData(self.selection_data.embedded_png, "PNG")
            self.original_pixmap = pm
        else:
            parent_viewer = getattr(self.parent(), 'viewer', None)
            pdf_docs = getattr(parent_viewer, 'pdf_docs', {}) if parent_viewer else {}
            doc = pdf_docs.get(self.selection_data.pdf_key)
            if not doc:
                return
            page = doc.load_page(self.selection_data.page_index)
            zoom = getattr(parent_viewer, 'render_dpi', 300.0) / 72.0
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


