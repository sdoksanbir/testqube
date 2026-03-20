# answer_dialog.py
from PyQt5.QtWidgets import QDialog, QLabel, QPushButton, QGridLayout
from PyQt5.QtCore import Qt

class AnswerDialog(QDialog):
    def __init__(self, current_answer=None, parent=None, is_first_selection=False):
        super().__init__(parent)
        self.setWindowTitle("Doğru Cevap Seç")
        self.setModal(True)
        self.choice = None
        self.buttons = {}
        self.is_first_selection = is_first_selection

        layout = QGridLayout(self)
        layout.setSpacing(10)  # Genel boşluk
        layout.setHorizontalSpacing(15)  # Şıklar arası yatay boşluk

        # "Doğru şıkkı seçiniz:" yazısı kaldırıldı

        letters = ["A", "B", "C", "D", "E"]
        for i, l in enumerate(letters):
            b = QPushButton(l)
            b.setCheckable(True)
            b.setFixedSize(44, 44)
            b.setProperty("role", "choice")
            b.clicked.connect(lambda checked, letter=l: self._choose(letter))
            layout.addWidget(b, 0, i)
            self.buttons[l] = b

        # Şıklar ile "Cevap yok" butonu arasına boşluk için boş bir satır ekle
        layout.setRowMinimumHeight(1, 15)  # 15px boşluk

        cancel_btn = QPushButton("Cevap yok")
        cancel_btn.setObjectName("cancel")
        cancel_btn.setCheckable(True)  # Checkable yap ki turuncu olabilsin
        cancel_btn.clicked.connect(self._no_answer)
        cancel_btn.setFixedHeight(36)
        layout.addWidget(cancel_btn, 2, 0, 1, 5)
        self.cancel_btn = cancel_btn  # Referansı sakla

        self.setStyleSheet("""
        QDialog { background: #ffffff; }
        QPushButton[role="choice"] {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #ffffff, stop:1 #f6f6f6);
            border: 1px solid #d0c6be;
            border-radius: 8px;
            color: #222;
            font-weight: 700;
            font-size: 16px;
        }
        QPushButton[role="choice"]:hover {
            background: #fbfbfb;
        }
        QPushButton[role="choice"]:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #ffb36b, stop:1 #ff8a00);
            color: white;
            border: 1px solid #e07a00;
        }
        QPushButton#cancel {
            background: #A8D5E2;
            border: 1px solid #7EC8E3;
            border-radius: 6px;
            padding: 6px 8px;
            color: #2C3E50;
            font-weight: 600;
            font-size: 14px;
        }
        QPushButton#cancel:hover {
            background: #7EC8E3;
            border: 1px solid #5BA3C1;
        }
        QPushButton#cancel:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #ffb36b, stop:1 #ff8a00);
            border: 1px solid #e07a00;
            color: white;
        }
        """)

        if current_answer is not None and current_answer in self.buttons:
            self._set_checked(current_answer)
        elif current_answer is None:
            # Tüm şıkları pasif yap
            for btn in self.buttons.values():
                btn.setChecked(False)
            # İlk seçimde "Cevap yok" turuncu olmasın (MAB-VI rengi kalsın)
            # Yeniden düzenlemede (is_first_selection=False) ve cevap yoksa turuncu olsun
            if not self.is_first_selection:
                self.cancel_btn.setChecked(True)

    def _set_checked(self, letter):
        # Tüm şıkları pasif yap
        for l, btn in self.buttons.items():
            btn.setChecked(l == letter)
        # "Cevap yok" butonunu pasif yap
        self.cancel_btn.setChecked(False)

    def _choose(self, letter):
        self.choice = letter
        self._set_checked(letter)
        self.accept()

    def _no_answer(self):
        self.choice = None
        # Tüm şıkları pasif yap
        for btn in self.buttons.values():
            btn.setChecked(False)
        # "Cevap yok" butonunu aktif yap
        self.cancel_btn.setChecked(True)
        self.accept()