# testmaker/widgets/draggable_question.py
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication,
    QGridLayout, QSizePolicy, QButtonGroup
)
from PyQt5.QtCore import Qt, QMimeData, pyqtSignal, QSize
from PyQt5.QtGui import QDrag, QIcon, QPixmap

from testmaker.models.selection import Selection
from testmaker.utils.paths import asset_path


class DraggableQuestion(QWidget):
    reordered_signal = pyqtSignal(list)
    question_deleted = pyqtSignal(object)
    preview_requested = pyqtSignal(object)

    def __init__(self, selection_data: Selection = None):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.selection_data = selection_data

        self.is_dragging = False
        self.set_default_style()

        # Ana layout: Soldaki ayar butonları ve sağdaki ana içerik
        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(5, 5, 5, 5)

        # Sol Taraf: Butonlar için sabit bir alan
        left_button_container = QWidget()
        left_button_container.setFixedWidth(24)  # Butonlar için sabit genişlik
        left_btn_layout = QVBoxLayout(left_button_container)
        left_btn_layout.setContentsMargins(0, 0, 0, 0)
        left_btn_layout.setSpacing(6)

        left_btn_layout.addStretch(1)

        # Silme butonu
        self.btn_delete = QPushButton("X")
        self.btn_delete.setFixedSize(24, 24)
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #E74C3C; color: white; border: none;
                font-weight: bold; font-size: 12px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #C0392B; }
        """)
        self.btn_delete.clicked.connect(lambda: self.question_deleted.emit(self.selection_data))
        self.btn_delete.setVisible(False)
        left_btn_layout.addWidget(self.btn_delete)

        # Önizleme butonu
        self.btn_preview = QPushButton()
        self.btn_preview.setIcon(QIcon(asset_path("search.svg")))
        self.btn_preview.setFixedSize(24, 24)
        self.btn_preview.setStyleSheet("""
            QPushButton {
                border: none; background-color: #5DADE2; border-radius: 4px;
            }
            QPushButton:hover { background-color: #3498DB; }
        """)
        self.btn_preview.clicked.connect(lambda: self.preview_requested.emit(self.selection_data))
        self.btn_preview.setVisible(False)
        left_btn_layout.addWidget(self.btn_preview)

        # Diğer sol butonlar
        self.btn_spacing = QPushButton()
        self.btn_spacing.setFixedSize(24, 24)
        self.btn_spacing.setStyleSheet("""
            QPushButton {
                background-color: #82e0aa; border: 1px solid #748DAE;
                border-radius: 4px; font-weight: bold;
            }
        """)
        self.btn_spacing.setVisible(False)
        left_btn_layout.addWidget(self.btn_spacing)

        self.btn_single_line = QPushButton()
        self.btn_single_line.setFixedSize(24, 24)
        self.btn_single_line.setStyleSheet("""
            QPushButton {
                background-color: #f5b7b1; border: 1px solid #748DAE;
                border-radius: 4px; font-weight: bold;
            }
        """)
        self.btn_single_line.setVisible(False)
        left_btn_layout.addWidget(self.btn_single_line)

        left_btn_layout.addStretch(1)

        main_h_layout.addWidget(left_button_container)

        # Sağ Taraf: Soru numarası, görsel ve şıklar için
        right_content_widget = QWidget()
        self.right_content_layout = QVBoxLayout(right_content_widget)
        self.right_content_layout.setContentsMargins(0, 0, 0, 0)
        self.right_content_layout.setSpacing(5)

        # Soru Numarası - Ortada ve sabit
        self.thumb_number_label = QLabel()
        self.thumb_number_label.setAlignment(Qt.AlignCenter)
        self.thumb_number_label.setStyleSheet("color:#333;font-weight:bold;font-size:14pt; margin-bottom: 4px;")
        self.right_content_layout.addWidget(self.thumb_number_label)

        # Görsel için çerçeve
        image_frame = QWidget()
        image_frame.setStyleSheet("""
            QWidget {
                background-color: white; border: 1px solid #DEDEDE; border-radius: 8px;
            }
        """)
        image_layout = QGridLayout(image_frame)
        image_layout.setContentsMargins(2, 2, 2, 2)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(250, 150)
        self.lbl_thumb.setStyleSheet("border:none;")
        self.lbl_thumb.setAlignment(Qt.AlignTop)
        image_layout.addWidget(self.lbl_thumb, 0, 0, 1, 1, Qt.AlignTop | Qt.AlignHCenter)
        self.right_content_layout.addWidget(image_frame)

        # Şıklar için
        self.btns = {}
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)  # Sadece bir butonun seçili olmasını sağlar
        hbox = QHBoxLayout()
        hbox.setSpacing(8)
        hbox.addStretch(1)
        letters = ["A", "B", "C", "D", "E"]
        for l in letters:
            btn = QPushButton(l)
            btn.setFixedSize(28, 28)
            btn.setCheckable(True) # Butonları işaretlenebilir yap
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid #AF3E3E;
                    border-radius: 14px;
                    background-color: #AF3E3E;
                    font-weight: bold;
                    font-size: 13px;
                    color: white;
                }}
                QPushButton:checked {{
                    border: 1px solid #6F826A;
                    background-color: #6F826A;
                }}
            """)
            hbox.addWidget(btn)
            self.btns[l] = btn
            self.btn_group.addButton(btn) # Butonu gruba ekle

        hbox.addStretch(1)
        self.right_content_layout.addLayout(hbox)
        main_h_layout.addWidget(right_content_widget)

        self.btn_group.buttonClicked.connect(self.on_answer_changed)

        if self.selection_data:
            self.set_answer(self.selection_data.answer)

    def set_default_style(self):
        self.setStyleSheet("""
            DraggableQuestion {
                background-color: #F8F8F8;
                border: 1px solid #DEDEDE;
                border-radius: 12px;
            }
        """)

    def on_answer_changed(self, button):
        self.selection_data.answer = button.text()

    def set_answer(self, answer):
        """
        Seçilen şıkkın butonunu görsel olarak işaretler.
        Diğer butonların işaretini kaldırır.
        """
        for button in self.btn_group.buttons():
            button.setChecked(button.text() == answer)

    def enterEvent(self, event):
        self.btn_preview.setVisible(True)
        self.btn_delete.setVisible(True)
        self.btn_spacing.setVisible(True)
        self.btn_single_line.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.btn_preview.setVisible(False)
        self.btn_delete.setVisible(False)
        self.btn_spacing.setVisible(False)
        self.btn_single_line.setVisible(False)
        super().leaveEvent(event)

    # Drag & drop
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
            self.is_dragging = True
            self.update_style()
            self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            distance = (event.pos() - self.drag_start_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setText("drag_question")
                drag.setMimeData(mime)

                pixmap = self.grab()
                drag.setPixmap(pixmap)
                drag.setHotSpot(event.pos() - self.rect().topLeft())
                drag.exec_(Qt.MoveAction)

    def mouseReleaseEvent(self, event):
        self.is_dragging = False
        self.set_default_style()
        self.unsetCursor()

    def dragEnterEvent(self, event):
        if event.mimeData().text() == "drag_question":
            event.acceptProposedAction()

    def dropEvent(self, event):
        event.acceptProposedAction()
        parent_layout = self.parentWidget().layout()
        dragged_widget = event.source()

        idx_old = parent_layout.indexOf(dragged_widget)
        idx_new = parent_layout.indexOf(self)

        item_to_move = parent_layout.takeAt(idx_old)
        parent_layout.insertItem(idx_new, item_to_move)

        new_sequence_data = []
        for i in range(parent_layout.count()):
            w = parent_layout.itemAt(i).widget()
            if hasattr(w, "thumb_number_label"):
                w.thumb_number = i + 1
                w.thumb_number_label.setText(f"{w.thumb_number}. Soru")
                if w.selection_data:
                    w.selection_data.number = w.thumb_number
                    new_sequence_data.append(w.selection_data)

        self.reordered_signal.emit(new_sequence_data)

    def update_style(self):
        if self.is_dragging:
            self.setStyleSheet("""
                DraggableQuestion {
                    background-color: #EAEAEA;
                    border: 1px solid #C0C0C0;
                    border-radius: 12px;
                }
            """)
        else:
            self.set_default_style()

    def set_thumbnail_image(self, pixmap):
        thumb_width, thumb_height = 250, 150

        # En-boy oranını koruyarak, resmi thumbnail'ın genişliğine tam sığdır
        scaled_pixmap = pixmap.scaledToWidth(
            thumb_width, Qt.SmoothTransformation
        )

        self.lbl_thumb.setPixmap(scaled_pixmap)