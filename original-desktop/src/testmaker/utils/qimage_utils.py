# pdf_viewer/utils/qimage_utils.py
from PyQt5.QtGui import QImage

def qimage_from_fitz_pix(pix):
    fmt = QImage.Format_RGB888 if pix.n < 4 else QImage.Format_RGBA8888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)