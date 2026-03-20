from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from testmaker.models.selection import Selection


class ThumbnailWidget(QWidget):
    def __init__(self, selection: Selection, pixmap: QPixmap, thumb_number: int):
        super().__init__()
        self.selection = selection
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(2, 2, 2, 2)

        # Thumbnail
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setPixmap(pixmap.scaledToWidth(250, Qt.SmoothTransformation))
        self.lbl_thumb.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.layout.addWidget(self.lbl_thumb)

        # Şıklar
        self.btns = {}
        hbox = QHBoxLayout()
        letters = ["A", "B", "C", "D", "E"]
        for l in letters:
            btn = QPushButton(l)
            btn.setFixedSize(28, 28)
            self.btns[l] = btn
            hbox.addWidget(btn)
        self.layout.addLayout(hbox)
