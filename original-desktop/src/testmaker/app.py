import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from testmaker.ui.windows.main_window import MainWindow


def main() -> int:
    # QWebEngineView için gerekli attribute'u set et (QApplication oluşturulmadan ÖNCE)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    
    app = QApplication(sys.argv)
    
    # Sabit renk şeması - sistem temasından bağımsız
    # NOT: f-string kullanmıyoruz; QSS içindeki { } karakterleri f-string'i bozar.
    app.setStyleSheet("""
    QWidget {
        background-color: #2C2C2C;
        color: #FFFFFF;
    }
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
        color: #000000;
        background-color: #FFFFFF;
        selection-color: #FFFFFF;
        selection-background-color: #6DCF92;
        font-size: 14px;
        padding: 8px 12px;
        border: 1px solid #E0E0E0;
        border-radius: 8px;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {
        border: 2px solid #6DCF92;
        background-color: #FFFFFF;
        outline: none;
    }
    QComboBox::drop-down {
        border: none;
        width: 30px;
        background-color: transparent;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 6px solid #666;
        width: 0;
        height: 0;
    }
    QComboBox QAbstractItemView {
        color: #000000;
        background-color: #FFFFFF;
        font-size: 14px;
        border: 2px solid #E0E0E0;
        border-radius: 6px;
        selection-background-color: #6DCF92;
        selection-color: #FFFFFF;
        padding: 4px;
    }
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        border: none;
        background-color: #F5F5F5;
        width: 20px;
    }
    QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
        background-color: #E0E0E0;
    }
    QCheckBox {
        font-size: 15px;
        spacing: 8px;
        color: #FFFFFF;
    }
    QCheckBox::indicator {
        background-color: #FFFFFF;
        border: 1px solid #FFFFFF;
        border-radius: 6px;
    }
    QCheckBox::indicator:checked {
        background-color: #90CAF9; /* pastel mavi */
        border: 1px solid #90CAF9;
    }
    QCheckBox::indicator:unchecked {
        background-color: #FFFFFF;
        border: 1px solid #FFFFFF;
    }
    QLabel {
        font-size: 15px;
        color: #FFFFFF;
    }
    """)
    window = MainWindow()
    window.showMaximized()  # Tam ekran aç
    return app.exec_()
