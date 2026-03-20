# question_gap_dialog.py
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QDoubleSpinBox, QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent


class QuestionGapDialog(QDialog):
    """Sorular arası boşluk ayarlama dialog'u"""
    
    def __init__(self, parent=None, current_gap_mm: float = 15.0):
        super().__init__(parent)
        self.setWindowTitle("BOŞLUK MİKTARINI AYARLAYIN")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        self.selected_gap_mm = current_gap_mm
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Başlık
        title = QLabel("Sorular arası boşluk miktarını seçin:")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Dropdown
        self.combo_gap = QComboBox()
        # 15'ten 55'e kadar 5'er 5'er artan değerler
        for mm in range(15, 60, 5):
            self.combo_gap.addItem(f"{mm} milimetre", mm)
        
        # Son eleman: Başka değer belirle
        self.combo_gap.addItem("Başka değer belirle", -1)
        
        # Mevcut değeri seç (eğer listede varsa)
        current_index = 0
        for i in range(self.combo_gap.count()):
            if self.combo_gap.itemData(i) == current_gap_mm:
                current_index = i
                break
        else:
            # Mevcut değer listede yoksa "Başka değer belirle"yi seç
            current_index = self.combo_gap.count() - 1
        
        self.combo_gap.setCurrentIndex(current_index)
        self.combo_gap.currentIndexChanged.connect(self._on_combo_changed)
        
        layout.addWidget(self.combo_gap)
        
        # Butonlar
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("İPTAL")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #333;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid #CCC;
            }
            QPushButton:hover {
                background-color: #D0D0D0;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_ok = QPushButton("TAMAM")
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
        
        # İlk kontrol: Eğer mevcut değer listede yoksa, custom dialog aç
        if current_index == self.combo_gap.count() - 1:
            self._open_custom_dialog()
    
    def _on_combo_changed(self, index):
        """Dropdown değiştiğinde"""
        selected_data = self.combo_gap.itemData(index)
        if selected_data == -1:  # "Başka değer belirle" seçildi
            self._open_custom_dialog()
    
    def _open_custom_dialog(self):
        """Özel değer giriş dialog'unu açar"""
        try:
            custom_dialog = CustomGapDialog(self, self.selected_gap_mm)
            result = custom_dialog.exec_()
            if result == QDialog.Accepted:
                custom_value = custom_dialog.get_value()
                if custom_value is not None:
                    self.selected_gap_mm = custom_value
                    # Dropdown'dan "Başka değer belirle"yi seçili tut
                    # (Değer artık dropdown'da görünmeyecek, ama seçili değer olarak saklanacak)
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Özel değer dialog'u açılırken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")
    
    def get_gap_mm(self) -> float:
        """Seçilen boşluk değerini döndürür (mm cinsinden)"""
        current_index = self.combo_gap.currentIndex()
        selected_data = self.combo_gap.itemData(current_index)
        
        if selected_data == -1:
            # "Başka değer belirle" seçili, custom değeri döndür
            return self.selected_gap_mm
        else:
            # Dropdown'dan seçilen değeri döndür
            return float(selected_data)


class CustomGapDialog(QDialog):
    """Özel boşluk değeri giriş dialog'u"""
    
    def __init__(self, parent=None, current_value: float = 15.0):
        super().__init__(parent)
        self.setWindowTitle("DEĞER GİRİN")
        self.setModal(True)
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Açıklama
        label = QLabel("Boşluk miktarını milimetre cinsinden girin:")
        label.setStyleSheet("font-size: 13px; padding: 5px;")
        layout.addWidget(label)
        
        # Input alanı
        input_layout = QHBoxLayout()
        self.spin_value = QDoubleSpinBox()
        self.spin_value.setRange(0.1, 200.0)  # Minimum 0.1mm, maksimum 200mm
        self.spin_value.setSingleStep(1.0)
        self.spin_value.setDecimals(1)
        self.spin_value.setValue(current_value)
        self.spin_value.setSuffix(" mm")
        self.spin_value.setStyleSheet("""
            QDoubleSpinBox {
                padding: 8px 12px;
                font-size: 14px;
                border: 2px solid #E0E0E0;
                border-radius: 4px;
                background-color: #FAFAFA;
                color: #333;
            }
            QDoubleSpinBox:focus {
                border: 2px solid #9CAFAA;
                background-color: #FFFFFF;
            }
        """)
        input_layout.addWidget(self.spin_value)
        layout.addLayout(input_layout)
        
        # Butonlar
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("İPTAL")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #333;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #CCC;
            }
            QPushButton:hover {
                background-color: #D0D0D0;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_ok = QPushButton("TAMAM")
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        
        layout.addLayout(btn_layout)
        
        # Spinbox'a focus ver
        self.spin_value.setFocus()
    
    def keyPressEvent(self, event: QKeyEvent):
        """Enter tuşu ile dialog'u kabul et"""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            self.accept()
        else:
            super().keyPressEvent(event)
    
    def get_value(self) -> float:
        """Girilen değeri döndürür"""
        return self.spin_value.value()
