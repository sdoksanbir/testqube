# pdf_preview_dialog.py
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea, QWidget, QMessageBox, QApplication,
    QSlider, QSpinBox, QSizePolicy, QGridLayout, QCheckBox, QLineEdit, QDialog as QPopupDialog, QComboBox,
    QRadioButton, QButtonGroup, QColorDialog
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer, QMimeData
from PyQt5.QtGui import QPainter, QPixmap, QPen, QBrush, QColor, QFont, QDrag, QPalette, QCursor, QKeyEvent
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import os
import tempfile

from testmaker.models.selection import Selection
from testmaker.services.pdf_exporter import export_test_pdf, ExportOptions, mm_to_pt
import fitz
from testmaker.utils.qimage_utils import qimage_from_fitz_pix


@dataclass
class PreviewQuestion:
    """Önizleme için kırpılmış soru görseli"""
    selection: Selection
    cropped_pixmap: QPixmap  # PDF'den bağımsız kırpılmış görsel
    x: int = 0  # Önizlemede x pozisyonu
    y: int = 0  # Önizlemede y pozisyonu
    display_width: int = 0  # Görüntülenen genişlik
    display_height: int = 0  # Görüntülenen yükseklik
    page_num: int = 0  # Hangi sayfada
    col_num: int = 0  # Hangi sütunda
    display_number: int = 0  # PDF'de görünen numara (bölüm bazlı reset olabilir)
    custom_gap_after_pt: float = None  # Bu sorudan sonraki özel boşluk (pt cinsinden, None ise varsayılan kullanılır)
    custom_gap_before_pt: float = None  # Bu sorudan önceki özel boşluk (pt cinsinden, None ise varsayılan kullanılır)


@dataclass
class SectionRange:
    """Bölüm bilgisi (sıra/pozisyon bazlı). Reorder olsa bile aralık sabit kalır."""
    start_idx: int
    end_idx: int
    title: str
    restart_numbering: bool = False
    start_new_page: bool = False
    fill_color: str = "#FFFFFF"
    text_color: str = "#000000"
    line_color: str = "#000000"
    font_pt: float = 12.0

class PDFPreviewWidget(QWidget):
    """Sadece görselleri gösteren ön izleme widget'ı - PDF arka plan yok"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.questions: List[PreviewQuestion] = []  # Kırpılmış sorular
        self.current_page = 0  # Hangi sayfa gösteriliyor
        self.pages: List[List[PreviewQuestion]] = []  # Sorular sayfalara ayrılmış
        self.export_options: ExportOptions = None  # Export seçenekleri (layout için gerekli)
        self.render_dpi: float = 72.0  # PDF render DPI'si (standart 72 DPI)
        
        # Seçili soru ve işlem durumu (sadece resize için)
        self._selected_question: PreviewQuestion = None
        self._resize_handle = None
        self._is_resizing = False
        self.drag_start: QPoint = None
        self.initial_rect: QRect = None
        self.initial_width = 0
        self.initial_height = 0
        self._handle_size = 10
        
        # Boşluk ayarlama (gap adjustment) durumu
        self._gap_being_adjusted: PreviewQuestion = None  # Hangi sorunun altındaki/üstündeki boşluk ayarlanıyor
        self._gap_being_adjusted_is_top: bool = False  # Üst boşluk mu ayarlanıyor?
        self._is_adjusting_gap = False  # Boşluk ayarlama modunda mı?
        self._gap_adjust_start_y = 0  # Boşluk ayarlama başlangıç y pozisyonu
        self._gap_adjust_initial_pt = 0.0  # Başlangıçtaki boşluk değeri (pt)
        self._hovered_gap_question: PreviewQuestion = None  # Hover yapılan boşluk çizgisi
        self._hovered_gap_is_top: bool = False  # Hover yapılan çizgi üstte mi?
        self._gap_being_adjusted_is_top: bool = False # Ayarlanan çizgi üstte mi altta mı
        self.reorganize_timer = QTimer(self) # Debouncing için timer
        self.reorganize_timer.setSingleShot(True)  # Tek seferlik timer
        self.reorganize_timer.timeout.connect(self._reorganize_after_gap_adjustment)
        
        self.setMouseTracking(True)
        self.setMinimumSize(1200, 800)
        self.setStyleSheet("background-color: #F0F0F0;")  # Çok açık gri arka plan - sabit renk
        self._last_width = 0  # Son widget genişliği (layout'u gereksiz yenilememek için)
    
    def _get_preview_scale(self) -> float:
        """
        Önizleme ölçeğini hesapla: pt'den px'e dönüşüm (ekran DPI'sına göre)
        1 pt = 1/72 inch
        1 px = 1/DPI inch (logical DPI)
        1 pt = DPI / 72 px
        PDF export ile aynı ölçekte göstermek için zoom faktörü 1.0 (zoom yok)
        """
        try:
            screen = QApplication.primaryScreen()
            logical_dpi = screen.logicalDotsPerInch()
            pt_to_px_ratio = logical_dpi / 72.0
            preview_zoom = 1.0  # PDF export ile aynı ölçekte göstermek için zoom yok
            return pt_to_px_ratio * preview_zoom
        except Exception:
            # Hata durumunda varsayılan değer (96 DPI varsayarak)
            return (96.0 / 72.0) * 1.0  # ≈ 1.333
    
    def set_questions(self, questions: List[PreviewQuestion], pages: List[List[PreviewQuestion]]):
        """Soruları ve sayfa organizasyonunu ayarla"""
        print(f"DEBUG: set_questions çağrıldı - {len(questions)} soru, {len(pages)} sayfa")
        self.questions = list(questions)  # Kopya al
        self.pages = list(pages)  # Kopya al
        self.current_page = 0 if pages else 0
        print(f"DEBUG: export_options var mı? {self.export_options is not None}")
        if self.export_options:
            print("DEBUG: Layout yapılıyor...")
            self._layout_all_pages()
            print(f"DEBUG: Layout tamamlandı - {len(self.pages)} sayfa işlendi")
        else:
            print("DEBUG: export_options yok, layout yapılmıyor")
        # Widget'ı zorla güncelle
        self.update()
        self.repaint()
    
    def set_export_options(self, export_options: ExportOptions):
        """Export options'ı ayarla (layout için gerekli)"""
        print(f"DEBUG: set_export_options çağrıldı - pages var mı? {bool(self.pages)}")
        self.export_options = export_options
        if self.pages:  # Eğer sorular zaten yüklendiyse layout'u güncelle
            print("DEBUG: Pages var, layout yapılıyor...")
            self._layout_all_pages()
            self.update()
        else:
            print("DEBUG: Pages yok, layout yapılmıyor")
    
    def resizeEvent(self, e):
        """Widget boyutu değiştiğinde layout'u yeniden hesapla"""
        super().resizeEvent(e)
        # Widget genişliği değiştiyse layout'u yeniden hesapla (page_x widget genişliğine bağlı)
        if self.width() != self._last_width:
            self._last_width = self.width()
            if self.export_options and self.pages:
                # Layout'u yeniden hesapla (page_x değişmiş olabilir)
                self._layout_all_pages()
                self.update()
    
    def _layout_all_pages(self):
        """Tüm sayfadaki soruları PDF export mantığına göre düzenle"""
        try:
            if not self.export_options or not self.pages:
                return
            
            # Her sayfa için layout yap
            for page_idx, page_questions in enumerate(self.pages):
                if not page_questions:
                    continue
                
                self._layout_single_page(page_idx, page_questions)
        except Exception as e:
            import traceback
            print(f"Hata: _layout_all_pages sırasında: {e}\n{traceback.format_exc()}")
    
    def _layout_single_page(self, page_idx: int, page_questions: List[PreviewQuestion]):
        """Tek bir sayfadaki soruları PDF export mantığına göre düzenle"""
        try:
            print(f"DEBUG: _layout_single_page çağrıldı - Sayfa {page_idx + 1}, {len(page_questions)} soru")
            print(f"  Soru numaraları (sırayla): {[q.selection.number for q in page_questions]}")
            
            if not page_questions:
                print("DEBUG: Sayfa boş, layout yapılmıyor")
                return
            
            from testmaker.services.pdf_exporter import mm_to_pt
            
            # Export options'dan bilgileri al (PDF ile AYNI)
            page_w_pt, page_h_pt = self.export_options.page_size_pt()
            ml_pt, mr_pt, mt_pt, mb_pt = self.export_options.margins_pt()
            col_gap_pt = self.export_options.column_gap_pt()
            question_gap_pt = self.export_options.question_gap_pt()
            cols = max(1, min(6, int(self.export_options.columns or 1)))
            # Render DPI'yi kullan: zoom = render_dpi / 72.0 (PDF export ile aynı mantık)
            # PDF export'ta: opts.zoom kullanılıyor, ama aslında render_dpi / 72.0 olmalı
            # Ön izlemede: render_dpi'yi direkt kullanacağız
            render_dpi = getattr(self, 'render_dpi', 72.0) if hasattr(self, 'render_dpi') else 72.0
            zoom = render_dpi / 72.0  # PDF export ile AYNI: render_dpi / 72.0
            text_scale = 10.0 / 12.0  # Export'taki text scale
            
            print(f"DEBUG: Layout parametreleri - page_w={page_w_pt}, page_h={page_h_pt}, cols={cols}, zoom={zoom}")
            
            # Sütun hesaplamaları (PDF export ile TAM AYNI)
            x_line_center = page_w_pt / 2.0
            header_right_edge = page_w_pt - mr_pt
            
            if cols > 1:
                left_space = x_line_center - ml_pt
                right_space = header_right_edge - x_line_center
                left_columns_count = (cols + 1) // 2
                right_columns_count = cols - left_columns_count
                
                if left_columns_count > 1:
                    left_col_w = (left_space - (left_columns_count - 1) * col_gap_pt) / left_columns_count
                else:
                    left_col_w = left_space
                
                if right_columns_count > 1:
                    right_col_w = (right_space - (right_columns_count - 1) * col_gap_pt) / right_columns_count
                else:
                    right_col_w = right_space
                
                col_w_pt = min(left_col_w, right_col_w)
            else:
                col_w_pt = x_line_center - ml_pt
            
            # Önizleme ölçeği: pt'den px'e dönüşüm (ekran DPI'sına göre)
            preview_scale = self._get_preview_scale()
            
            page_w_px = int(page_w_pt * preview_scale)
            page_h_px = int(page_h_pt * preview_scale)
            ml_px = int(ml_pt * preview_scale)
            mr_px = int(mr_pt * preview_scale)
            mt_px = int(mt_pt * preview_scale)
            mb_px = int(mb_pt * preview_scale)
            col_gap_px = int(col_gap_pt * preview_scale)
            question_gap_px = int(question_gap_pt * preview_scale)
            col_w_px = col_w_pt * preview_scale
            
            # Sayfa başlangıç pozisyonu (widget içinde) - paintEvent ile AYNI hesaplama
            # paintEvent'te: page_x = max(10, (widget_width - page_w_px) // 2)
            # Burada da aynı hesaplamayı yapmalıyız ki layout ile çizim uyumlu olsun
            widget_width = self.width() if self.width() > 0 else 800  # Fallback değer
            page_x = max(10, (widget_width - page_w_px) // 2)  # Ortala, minimum 10px margin (paintEvent ile AYNI)
            page_y = 40
            
            # Header yüksekliği - PDF export ile TAM AYNI hesaplama
            # PDF export'ta _draw_header fonksiyonu:
            # İlk sayfada: header_height = 60pt, inner_padding = 8pt, inner_height = 28pt, desc_y offset = 8pt, desc height = 14pt, final gap = 8pt
            # Toplam: 60 + 8 + 28 + 8 + 14 + 8 = 126pt (ama PDF'de y_start = page_h - mt - 66pt, bu header + margin sonrası boşluk)
            # Aslında: header (60pt) + padding (8pt) + inner (28pt) + desc offset (8pt) + desc (14pt) + final gap (8pt) = 126pt
            # Ancak PDF'de y_start = desc_y - 8.0 = inner_y_bottom - 8.0 - 8.0 = ... = y - 60 - 8 - 28 - 8 - 8 = y - 112
            # Ve y = page_h - mt, yani y_start = page_h - mt - 112... hayır bekle, tekrar hesaplayalım:
            # y = page_h - mt (başlangıç)
            # header_y_top = y, header_y_bottom = y - 60
            # inner_y_top = y - 8, inner_y_bottom = y - 8 - 28 = y - 36
            # desc_y = y - 36 - 8 = y - 44
            # desc_y -= 14 (desc height) -> desc_y = y - 58
            # y = desc_y - 8 = y - 58 - 8 = y - 66
            # Yani: y_start = page_h - mt - 66
            # Qt'de: y_start_px = page_y + mt_px + 66pt * preview_scale
            
            if page_idx == 0:
                header_effective_height_pt = 84.0  # İlk sayfa: PDF export ile TAM AYNI (header + içerik + 8pt boşluk)
            else:
                # Diğer sayfalar: header_height (40pt) + headerBottomGapPt (default 10mm = ~28.35pt)
                header_bottom_gap_pt = self.export_options.header_bottom_gap_pt()
                header_effective_height_pt = 40.0 + header_bottom_gap_pt
            
            header_effective_height_px = int(header_effective_height_pt * preview_scale)
            # Qt koordinat sistemi: Header'dan sonra başla (üstten mesafe)
            # PDF'de: y_start = page_h - mt - header_effective_height (PDF koordinat sisteminde yukarıdan aşağıya)
            # Qt'de: y_start_px = page_y + mt_px + header_effective_height_px (Qt koordinat sisteminde yukarıdan aşağıya)
            y_start_px = page_y + mt_px + header_effective_height_px
            
            # Sütun X pozisyonlarını hesapla (PDF export mantığı ile aynı)
            def get_column_x(col_index: int) -> int:
                """PDF export'taki get_column_x ile aynı mantık"""
                if cols == 1:
                    return int(page_x + ml_px)
                if col_index < left_columns_count:
                    return int(page_x + ml_px + col_index * (col_w_px + col_gap_px))
                else:
                    right_col_index = col_index - left_columns_count
                    reduced_gap = col_gap_px * 0.5
                    return int(page_x + (page_w_px // 2) + reduced_gap + right_col_index * (col_w_px + reduced_gap))
            
            # Soruları PDF export mantığına göre yerleştir (export'taki gibi tek tek)
            # IMPORTANT: Use q.col_num from organization, don't recalculate column assignments
            # Track Y positions per column
            y_by_col = {}  # {col_idx: y_px}
            
            print(f"DEBUG: Layout başlangıcı - y_start={y_start_px}, col_w={col_w_px}")
            
            for idx, q in enumerate(page_questions):
                # Use column number from organization (already set by _organize_into_pages_pdf_export_logic)
                col_idx = getattr(q, 'col_num', 0)  # Default to 0 if not set
                x_col_px = get_column_x(col_idx)
                
                # Initialize Y position for this column if not set
                if col_idx not in y_by_col:
                    y_by_col[col_idx] = int(y_start_px)
                y_px = y_by_col[col_idx]
                
                # Soru boyutunu PDF export mantığına göre hesapla (AYNI)
                orig_w_px = q.cropped_pixmap.width()
                orig_h_px = q.cropped_pixmap.height()
                
                print(f"DEBUG: Soru {idx + 1} - orijinal boyut: {orig_w_px}x{orig_h_px}")
                
                # ÖNEMLİ: Soruları ASLA atlama! Geçersiz boyutlu sorular için minimum boyutlar kullan
                if orig_w_px <= 0:
                    orig_w_px = 100  # Minimum genişlik
                    print(f"DEBUG: Soru {idx + 1} (numara {q.selection.number}) geçersiz genişlik, minimum 100px kullanılıyor")
                if orig_h_px <= 0:
                    orig_h_px = 100  # Minimum yükseklik
                    print(f"DEBUG: Soru {idx + 1} (numara {q.selection.number}) geçersiz yükseklik, minimum 100px kullanılıyor")
                
                raw_display_scale = getattr(q.selection, "display_scale", None)
                display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                
                # PDF export mantığı: ÖNCE px -> pt, SONRA display_scale, SONRA text_scale
                # Export'ta: img_w_pt = img_w_px / zoom * display_scale, sonra draw_w = img_w_pt * text_scale
                img_w_pt = (orig_w_px / zoom) * display_scale
                img_h_pt = (orig_h_px / zoom) * display_scale
                
                # Sonra text_scale uygula (PDF export'taki gibi - 10/12 = 0.833)
                draw_w_pt = img_w_pt * text_scale
                draw_h_pt = img_h_pt * text_scale
                
                # Numara genişliği (export'taki gibi - 10pt font)
                # Export'ta: number_width = stringWidth(number_text, font_name, font_size)
                # Yaklaşık: "1." = ~6pt, "10." = ~18pt, "100." = ~30pt
                number_text = f"{getattr(q, 'display_number', getattr(q.selection, 'number', '?'))}."
                # Yaklaşık genişlik hesabı (10pt font için): her karakter ~6pt
                number_width_pt = max(6.0, len(number_text) * 6.0)  # Minimum 6pt
                number_gap_pt = 4.0
                right_padding_pt = 4.0
                available_width_pt = col_w_pt - number_width_pt - number_gap_pt - right_padding_pt
                
                # Debug: available_width kontrolü
                print(f"DEBUG: col_w_pt={col_w_pt:.1f}, number_width={number_width_pt:.1f}, gap={number_gap_pt}, padding={right_padding_pt}, available={available_width_pt:.1f}")
                
                # Görsel genişliğine sığdır (export mantığı - TAM OLARAK AYNI)
                if draw_w_pt > available_width_pt:
                    scale = available_width_pt / draw_w_pt
                    draw_w_pt = available_width_pt
                    draw_h_pt = draw_h_pt * scale
                
                # Görsel boyutları px'e çevir (preview_scale uygula)
                img_w_px = int(draw_w_pt * preview_scale)
                img_h_px = int(draw_h_pt * preview_scale)
                
                # Numara yüksekliği - PDF export ile aynı hesaplama
                # PDF export'ta: font_size_num = 10.0, text_height = font_ascent_num + font_descent_num
                # Roboto-Bold 10pt için tipik: ascent ~700-800, descent ~200
                # Toplam: (700+200)/1000 * 10 = 9pt veya (800+200)/1000 * 10 = 10pt
                # Güvenli değer: 10.0pt (PDF export'taki gerçek değere yakın)
                box_h_pt = 10.0
                box_h_px = int(box_h_pt * preview_scale)
                
                # Özel boşluk varsa onu kullan, yoksa varsayılan boşluğu kullan
                actual_gap_pt = q.custom_gap_after_pt if q.custom_gap_after_pt is not None else question_gap_pt
                actual_gap_px = int(actual_gap_pt * preview_scale)
                
                # Gerekli yükseklik (export mantığı ile aynı) - ÜST BOŞLUK DAHİL DEĞİL
                needed_pt = max(box_h_pt, draw_h_pt) + actual_gap_pt
                if self.export_options.spaced and self.export_options.draw_separators:
                    needed_pt += 14.0
                needed_px = int(needed_pt * preview_scale)
                
                # ÜST BOŞLUK: Bir önceki sorunun alt boşluğu (aynı sütunda)
                # PDF export mantığında y pozisyonu zaten bir önceki sorudan sonra geliyor
                # Bu yüzden üst boşluk otomatik olarak uygulanmış olmalı
                # Ancak layout'ta görsel pozisyonunu ayarlamak için üst boşluğu hesaplayalım
                gap_before_pt = 0.0  # Varsayılan: üst boşluk yok (sütun başı)
                
                # Bir önceki soruyu bul (aynı sütunda, bu sayfada)
                prev_q = None
                if idx > 0:
                    # Bir önceki soru (sayfa questions listesindeki sıraya göre)
                    prev_q_candidate = page_questions[idx - 1]
                    # Eğer bir önceki sorunun col_num'ı varsa ve aynı sütunda ise kullan
                    if hasattr(prev_q_candidate, 'col_num') and prev_q_candidate.col_num == col_idx:
                        prev_q = prev_q_candidate
                    # Eğer col_num yoksa (henüz ayarlanmamış), sadece ilk sütun için kontrol et
                    elif (not hasattr(prev_q_candidate, 'col_num') or prev_q_candidate.col_num == 0) and col_idx == 0:
                        prev_q = prev_q_candidate
                
                if prev_q:
                    # Bir önceki sorunun alt boşluğunu kullan (bu sorunun üstündeki boşluk = iki soru arası boşluk)
                    gap_before_pt = prev_q.custom_gap_after_pt if prev_q.custom_gap_after_pt is not None else question_gap_pt
                
                gap_before_px = int(gap_before_pt * preview_scale)
                
                # Sayfaya sığıyor mu? (Qt koordinat sistemi: y artar aşağı iner)
                # PDF export mantığında üst boşluk kontrol sırasında kullanılmaz, sadece yerleştirme sırasında
                # Ama layout'ta görsel pozisyonunu doğru ayarlamak için kontrol edelim
                # Soru + üst boşluk + alt boşluk hepsini toplamalıyız
                max_y = page_y + page_h_px - mb_px
                total_needed_px = max(box_h_px, img_h_px) + gap_before_px + actual_gap_px
                if self.export_options.spaced and self.export_options.draw_separators:
                    total_needed_px += int(14.0 * preview_scale)
                
                # NOTE: Column assignments come from _organize_into_pages_pdf_export_logic
                # We should NOT recalculate column assignments here - just use q.col_num
                # If question doesn't fit, it's a layout error (should not happen if organization is correct)
                if (y_px + total_needed_px) > max_y:
                    print(f"DEBUG: UYARI: Soru {idx + 1} (numara {q.selection.number}) sığmıyor (y={y_px}, needed={total_needed_px}, max_y={max_y})")
                    print(f"  -> Bu durum olmamalı (sayfalar zaten _organize_into_pages_pdf_export_logic ile ayrıldı)")
                    print(f"  -> Soru yerleştirilmeye devam ediliyor (overlap olabilir ama soru kaybolmaz)")
                
                # Üst boşluğu y pozisyonuna ekle (görsel yerleştirme için)
                # PDF export'ta y pozisyonu zaten bir önceki sorudan sonra geliyor, bu yüzden üst boşluk otomatik olarak uygulanmış
                # Ama layout'ta görsel pozisyonunu doğru ayarlamak için üst boşluğu ekliyoruz
                y_px = int(y_px + gap_before_px)
                
                # Pozisyon (numara + görsel yan yana - PDF'deki gibi)
                number_gap_px = int(number_gap_pt * preview_scale)
                number_width_px = int(number_width_pt * preview_scale)
                
                # Görsel pozisyonu (numara solda, görsel sağda - PDF export'taki gibi)
                # PDF export'ta: y_top görselin ve numaranın üst kenarı, y_img_bottom = y_top - draw_h (görselin alt kenarı)
                # Qt'de: drawPixmap(topLeft, pixmap) - topLeft görselin ÜST sol köşesi
                # Yani img_y görselin ÜST kenarı olmalı (numara ile üst hizalı)
                
                # Numara ve görselin üst kenarları hizalı (PDF export mantığı)
                img_x = int(x_col_px + number_width_px + number_gap_px)
                img_y = int(y_px)  # Görselin üst kenarı (numara ile aynı y seviyesi)
                
                q.x = img_x
                q.y = img_y
                q.display_width = int(img_w_px)
                q.display_height = int(img_h_px)
                q.page_num = page_idx
                q.col_num = col_idx
                
                print(f"DEBUG: Soru {idx + 1} yerleştirildi - x={q.x}, y={q.y}, w={q.display_width}, h={q.display_height}, col={col_idx}")
                print(f"  -> display_scale={display_scale:.2f}, draw_w_pt={draw_w_pt:.1f}, available={available_width_pt:.1f}, col_w={col_w_pt:.1f}")
                print(f"  -> orig_pixmap={orig_w_px}x{orig_h_px}, final_px={img_w_px}x{img_h_px}")
                print(f"  -> gap_before={gap_before_pt:.2f}pt ({gap_before_pt * 0.352778:.1f}mm), gap_after={actual_gap_pt:.2f}pt ({actual_gap_pt * 0.352778:.1f}mm)")
                
                # Y pozisyonunu güncelle (sorunun tamamı için - Qt koordinat sistemi: y artar aşağı iner)
                # PDF export'ta: y = y_top - max(box_h, draw_h) - gap (y azalır, yukarı çıkar - PDF koordinat sistemi)
                # Qt'de: y = y + max(box_h, draw_h) + gap (y artar, aşağı iner - Qt koordinat sistemi)
                # max(box_h_px, img_h_px) çünkü numara ve görsel aynı satırda, hangisi yüksekse ona göre
                y_px = int(y_px + max(box_h_px, img_h_px) + actual_gap_px)

                # Persist advanced Y for this column so the next question in the same column
                # does NOT start at the same Y (prevents overlap)
                y_by_col[col_idx] = y_px

                # Optional separator (export mantığı)
                if self.export_options.spaced and self.export_options.draw_separators:
                    y_px = int(y_px + 14)
                    y_by_col[col_idx] = y_px

            
            print(f"DEBUG: _layout_single_page tamamlandı - {len(page_questions)} soru yerleştirildi")
        except Exception as e:
            import traceback
            print(f"Hata: _layout_single_page sırasında: {e}\n{traceback.format_exc()}")
    
    def _crop_question_image(self, sel: Selection, pdf_docs: dict) -> QPixmap:
        """PDF'den soru görselini kırp (PDF bağımsız) - Yüksek kalite"""
        try:
            # Taslaktan yüklenen (PDF'e bağlı olmayan) sorular: embedded PNG varsa onu kullan.
            embedded_png = getattr(sel, 'embedded_png', None)
            if embedded_png:
                try:
                    pm = QPixmap()
                    # bytes -> QPixmap
                    if pm.loadFromData(embedded_png, "PNG"):
                        return pm
                except Exception:
                    pass

            if not sel or not sel.pdf_key:
                return QPixmap()
                
            doc = pdf_docs.get(sel.pdf_key)
            if not doc:
                return QPixmap()
            
            if sel.page_index < 0 or sel.page_index >= len(doc):
                return QPixmap()
            
            page = doc.load_page(sel.page_index)
            # Render DPI'yi kullan: zoom = render_dpi / 72.0 (PDF export ile aynı)
            render_dpi = getattr(self, 'render_dpi', 72.0)
            zoom = render_dpi / 72.0  # PDF export ile AYNI mantık
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pm = QPixmap.fromImage(qimage_from_fitz_pix(pix))
            
            # Norm koordinatlarından kırp
            if not sel.norm or len(sel.norm) < 4:
                return QPixmap()
                
            fx, fy, fw, fh = sel.norm
            r = QRect(int(fx * pm.width()), int(fy * pm.height()),
                      int(fw * pm.width()), int(fh * pm.height()))
            r = r.intersected(QRect(0, 0, pm.width(), pm.height()))
            
            if r.width() > 0 and r.height() > 0:
                return pm.copy(r)
            return QPixmap()
        except Exception as e:
            import traceback
            print(f"Hata: Görsel kırpılırken: {e}\n{traceback.format_exc()}")
            return QPixmap()
    
    def _get_handles(self, r_screen: QRect):
        """Sadece sağ alt köşe tutamacı"""
        handles = {}
        half = self._handle_size // 2
        handles["bottom_right"] = QRect(r_screen.right() - half, r_screen.bottom() - half, 
                                        self._handle_size, self._handle_size)
        return handles
    
    def _get_image_rect(self, q: PreviewQuestion):
        """Görselin ekrandaki dikdörtgenini döndür (PDF layout'una göre)"""
        return QRect(int(q.x), int(q.y), int(q.display_width), int(q.display_height))
    
    def _get_gap_line_rect(self, q: PreviewQuestion, is_top: bool = False) -> QRect:
        """Soru altındaki veya üstündeki boşluk çizgisinin dikdörtgenini döndür"""
        if not self.export_options:
            return QRect()
        
        img_rect = self._get_image_rect(q)
        if img_rect.width() <= 0 or img_rect.height() <= 0:
            return QRect()
        
        # Numara genişliği dahil çizgiyi çiz
        num_text = f"{getattr(q, 'display_number', getattr(q.selection, 'number', '?'))}."
        preview_scale = self._get_preview_scale()
        number_width_px = int(len(num_text) * 6.0 * preview_scale)
        number_gap_px = int(4.0 * preview_scale)
        
        # Çizgi genişliği: numara + gap + görsel genişliği
        line_left = img_rect.left() - number_width_px - number_gap_px
        line_right = img_rect.right()
        line_width = line_right - line_left
        
        # Çizgi yüksekliği: 10px (hover için yeterli alan, daha modern görünüm için)
        line_height = 10
        if is_top:
            # Üst çizgi: görselin üst kenarından başla
            line_y = img_rect.top() - line_height
        else:
            # Alt çizgi: görselin alt kenarından başla
            line_y = img_rect.bottom()
        
        return QRect(int(line_left), int(line_y), int(line_width), int(line_height))
    
    def _draw_modern_gap_line(self, painter: QPainter, gap_line_rect: QRect, q: PreviewQuestion, is_top: bool, is_active: bool):
        """Modern görünümlü boşluk çizgisi çiz"""
        if gap_line_rect.width() <= 0 or gap_line_rect.height() <= 0:
            return
        
        line_y = gap_line_rect.top() + gap_line_rect.height() // 2
        center_x = gap_line_rect.left() + gap_line_rect.width() // 2
        
        if is_active:
            # Aktif durumda (hover veya ayarlama) - modern mavi gradient çizgi
            # Gradient arka plan
            from PyQt5.QtGui import QLinearGradient, QGradient
            gradient = QLinearGradient(gap_line_rect.left(), line_y - 4, gap_line_rect.left(), line_y + 4)
            gradient.setColorAt(0, QColor(100, 180, 255, 180))
            gradient.setColorAt(1, QColor(50, 150, 255, 200))
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(gap_line_rect, 5, 5)
            
            # Ana çizgi (kalın, mavi)
            painter.setPen(QPen(QColor(50, 150, 255), 3, Qt.SolidLine))
            painter.drawLine(gap_line_rect.left() + 5, line_y, gap_line_rect.right() - 5, line_y)
            
            # Handle (ortada, modern rounded pill şekli)
            handle_width = 40
            handle_height = 8
            handle_rect = QRect(
                int(center_x - handle_width // 2),
                int(line_y - handle_height // 2),
                handle_width,
                handle_height
            )
            # Handle gradient
            handle_gradient = QLinearGradient(handle_rect.left(), handle_rect.top(), handle_rect.left(), handle_rect.bottom())
            handle_gradient.setColorAt(0, QColor(50, 150, 255))
            handle_gradient.setColorAt(1, QColor(30, 120, 220))
            painter.setBrush(QBrush(handle_gradient))
            painter.setPen(QPen(QColor(20, 100, 200), 1.5))
            painter.drawRoundedRect(handle_rect, 4, 4)
            
            # Shadow efekti (handle için)
            shadow_rect = handle_rect.translated(0, 1)
            painter.setBrush(QBrush(QColor(0, 0, 0, 30)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(shadow_rect, 4, 4)
            
            # Boşluk değeri (çizginin ALTINDA - modern badge stili)
            # NOT: Artık her zaman alt boşluğu gösteriyoruz (is_top parametresi artık sadece çizgi pozisyonu için)
            # Üst çizgi bir önceki sorunun alt boşluğunu gösterir, alt çizgi bu sorunun alt boşluğunu gösterir
            if q.custom_gap_after_pt is not None:
                gap_mm = q.custom_gap_after_pt * 0.352778  # pt -> mm
                gap_text = f"{gap_mm:.1f} mm"
            else:
                default_gap_pt = self.export_options.question_gap_pt() if self.export_options else 12.0
                gap_mm = default_gap_pt * 0.352778
                gap_text = f"{gap_mm:.1f} mm"
            
            # Badge arka planı (çizginin altında)
            text_font = QFont("Arial", 8, QFont.Bold)
            painter.setFont(text_font)
            text_metrics = painter.fontMetrics()
            text_width = text_metrics.width(gap_text)
            text_height = text_metrics.height()
            badge_padding = 4
            badge_rect = QRect(
                int(center_x - (text_width // 2) - badge_padding),
                int(line_y + handle_height // 2 + 5),  # Çizginin altında
                text_width + badge_padding * 2,
                text_height + badge_padding
            )
            
            # Badge gradient
            badge_gradient = QLinearGradient(badge_rect.left(), badge_rect.top(), badge_rect.left(), badge_rect.bottom())
            badge_gradient.setColorAt(0, QColor(50, 150, 255, 240))
            badge_gradient.setColorAt(1, QColor(30, 120, 220, 240))
            painter.setBrush(QBrush(badge_gradient))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawRoundedRect(badge_rect, 6, 6)
            
            # Badge metni
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(badge_rect, Qt.AlignCenter, gap_text)
            
        else:
            # Pasif durumda (normal) - ince, şeffaf gri çizgi
            # Hafif arka plan
            painter.setBrush(QBrush(QColor(220, 220, 220, 80)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(gap_line_rect, 3, 3)
            
            # Ana çizgi (ince, kesikli)
            painter.setPen(QPen(QColor(180, 180, 180), 1.5, Qt.DashLine))
            painter.drawLine(gap_line_rect.left() + 10, line_y, gap_line_rect.right() - 10, line_y)
            
            # Küçük handle (ortada, daha az belirgin)
            handle_rect = QRect(
                int(center_x - 12),
                int(line_y - 2),
                24,
                4
            )
            painter.setBrush(QBrush(QColor(200, 200, 200, 150)))
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawRoundedRect(handle_rect, 2, 2)
    
    def paintEvent(self, e):
        """PDF layout'unu ve görselleri çiz"""
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            
            # Sayfa boyutlarını hesapla
            if not self.export_options:
                return
            
            from testmaker.services.pdf_exporter import mm_to_pt
            page_w_pt, page_h_pt = self.export_options.page_size_pt()
            ml_pt, mr_pt, mt_pt, mb_pt = self.export_options.margins_pt()
            question_gap_pt = self.export_options.question_gap_pt()  # Sorular arası boşluk (pt)
            
            # Önizleme ölçeği: pt'den px'e dönüşüm (ekran DPI'sına göre) - layout ile AYNI
            preview_scale = self._get_preview_scale()
            
            page_w_px = int(page_w_pt * preview_scale)
            page_h_px = int(page_h_pt * preview_scale)
            ml_px = int(ml_pt * preview_scale)
            mr_px = int(mr_pt * preview_scale)
            mt_px = int(mt_pt * preview_scale)
            mb_px = int(mb_pt * preview_scale)
            
            # Sayfa bilgisi
            total_pages = len(self.pages) if self.pages else 1
            page_info = f"Sayfa {self.current_page + 1} / {total_pages}"
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            painter.setPen(QColor(100, 100, 100))
            painter.drawText(10, 20, page_info)
            
            # PDF sayfa arka planı (beyaz kutu) - ORTALANMIŞ
            # Widget genişliğine göre sayfayı ortala
            widget_width = self.width()
            widget_height = self.height()
            page_x = max(10, (widget_width - page_w_px) // 2)  # Ortala, minimum 10px margin
            page_y = 40
            page_rect = QRect(page_x, page_y, page_w_px, page_h_px)
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(200, 200, 200), 1))
            painter.drawRect(page_rect)
            
            # Header çiz (PDF export ile TAM AYNI tasarım)
            # Turuncu renk (#FFA500 = RGB(255, 165, 0) = RGB(1.0, 0.647, 0.0))
            orange_color = QColor(255, 165, 0)
            orange_r, orange_g, orange_b = 1.0, 0.647, 0.0
            
            # Header yüksekliği (sütun çizgisi için gerekli)
            header_height_px = 0
            
            if self.current_page == 0:
                # İLK SAYFA: PDF export ile TAM AYNI (dinamik header yüksekliği)
                header_x_left_px = page_x + ml_px
                header_x_right_px = page_x + page_w_px - mr_px
                header_width_px = header_x_right_px - header_x_left_px
                header_radius_px = int(8.0 * preview_scale)
                
                # PDF koordinat sisteminde: y = page_h - mt (başlangıç)
                # Qt koordinat sisteminde: header_y_top_px = page_y + mt_px
                header_y_top_px = page_y + mt_px
                
                # İç turuncu dolu box (TEST ADI için) - ORTADA
                inner_padding_pt = 8.0
                inner_height_pt = 28.0
                inner_padding_px = int(inner_padding_pt * preview_scale)
                inner_height_px = int(inner_height_pt * preview_scale)
                # PDF'de: inner_y_top = y - inner_padding (y - 8)
                # Qt'de: inner_y_top_px = header_y_top_px + inner_padding_px
                inner_y_top_px = header_y_top_px + inner_padding_px
                inner_y_bottom_px = inner_y_top_px + inner_height_px
                
                # TEST ADI kutusu ortada olacak - genişliği yazıya göre ayarla
                test_title = (self.export_options.test_title.strip() or "TEST")
                font_size_title_pt = 14.0
                font_size_title_px = int(font_size_title_pt * preview_scale)
                painter.setFont(QFont("Arial", font_size_title_px, QFont.Bold))
                font_metrics_title = painter.fontMetrics()
                title_width_px = font_metrics_title.width(test_title)
                padding_pt = 16.0  # PDF export'ta: title_width + 16.0
                padding_px = int(padding_pt * preview_scale)
                inner_box_width_px = title_width_px + padding_px
                
                # Kutu ortada olacak
                inner_x_left_px = header_x_left_px + (header_width_px - inner_box_width_px) // 2
                inner_radius_px = int(6.0 * preview_scale)
                
                # Açıklama metni için yükseklik hesapla (PDF export ile aynı)
                font_size_desc_pt = 10.0
                font_size_desc_px = int(font_size_desc_pt * preview_scale)
                painter.setFont(QFont("Arial", font_size_desc_px, QFont.Bold))
                font_metrics_desc = painter.fontMetrics()
                font_height_desc_px = font_metrics_desc.height()  # Font yüksekliği
                font_ascent_desc_px = font_metrics_desc.ascent()
                
                # Açıklama metni
                meta = []
                if self.export_options.school_name.strip():
                    meta.append(self.export_options.school_name.strip())
                if self.export_options.branch_name.strip():
                    meta.append(f"Şube: {self.export_options.branch_name.strip()}")
                if self.export_options.teacher_name.strip():
                    meta.append(f"Öğretmen: {self.export_options.teacher_name.strip()}")
                
                if meta:
                    desc_text = " | ".join(meta)
                else:
                    desc_text = "TEST İLE İLGİLİ AÇIKLAMA"
                
                # Açıklama metninin genişliği ve yüksekliği (PDF export ile aynı mantık)
                desc_available_width_px = header_width_px - 2 * inner_padding_px
                desc_text_width_px = font_metrics_desc.width(desc_text)
                
                # Metin kaç satır olacak?
                desc_lines = max(1, int(desc_text_width_px / desc_available_width_px) + 1) if desc_available_width_px > 0 else 1
                desc_height_pt = max(mm_to_pt(10.0), desc_lines * (font_size_desc_pt * 1.2))  # Minimum 10mm, satır arası 1.2x
                desc_height_px = int(desc_height_pt * preview_scale)
                
                # Header yüksekliğini hesapla (PDF export ile TAM AYNI - dinamik)
                # header_height = inner_padding + inner_height + 4.0 + 1.0 + 8.0 + desc_height + 4.0
                header_height_pt = (inner_padding_pt + inner_height_pt + 4.0 + 1.0 +  # Çizgi kalınlığı dahil
                                   8.0 + desc_height_pt + 4.0)  # Çizgi-açıklama arası boşluk (8pt) + desc_height + alt boşluk
                header_height_px = int(header_height_pt * preview_scale)
                
                # PDF'de: header_y_bottom = header_y_top - header_height
                # Qt'de: header_y_bottom_px = header_y_top_px + header_height_px
                header_y_bottom_px = header_y_top_px + header_height_px
                
                # ÖNCE dış turuncu çerçeve çiz (ARKADA KALACAK) - PDF export ile aynı
                header_rect = QRect(header_x_left_px, header_y_top_px, header_width_px, header_height_px)
                painter.setBrush(QBrush(QColor(255, 255, 255)))  # Beyaz iç
                painter.setPen(QPen(orange_color, int(1.5 * preview_scale)))  # Turuncu çerçeve
                painter.drawRoundedRect(header_rect, header_radius_px, header_radius_px)
                
                # SONRA içeriği çiz (ÖNDE GÖRÜNECEK) - PDF export ile aynı
                # İç turuncu dolu box (TEST ADI için)
                inner_rect = QRect(inner_x_left_px, inner_y_top_px, inner_box_width_px, inner_height_px)
                painter.setBrush(QBrush(orange_color))  # Turuncu dolu
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(inner_rect, inner_radius_px, inner_radius_px)
                
                # TEST ADI yazısı (beyaz, kalın)
                painter.setPen(QColor(255, 255, 255))  # Beyaz
                painter.setFont(QFont("Arial", font_size_title_px, QFont.Bold))
                painter.drawText(inner_rect, Qt.AlignCenter | Qt.AlignVCenter, test_title)
                
                # Test açıklaması ile başlık arası çizgi (TEST ADI kutusunun altında, turuncu, kalın)
                # PDF'de: line_y = inner_y_bottom - 4.0 (PDF koordinat sisteminde yukarı)
                # Qt'de: line_y_px = inner_y_bottom_px + 4pt (inner box'tan 4pt aşağı)
                line_y_px = inner_y_bottom_px + int(4.0 * preview_scale)
                painter.setPen(QPen(orange_color, int(1.0 * preview_scale)))  # Turuncu, kalın
                painter.drawLine(header_x_left_px, line_y_px, header_x_right_px, line_y_px)
                
                # Açıklama alanı (çizgiden sonra, altında, sol tarafta)
                # PDF'de: desc_y_top = line_y - 8.0 (çizgiden 8pt aşağı)
                # Qt'de: desc_y_top_px = line_y_px + 8pt (çizgiden 8pt aşağı)
                desc_y_top_px = line_y_px + int(8.0 * preview_scale)
                desc_y_bottom_px = desc_y_top_px + desc_height_px
                desc_y_baseline_px = desc_y_top_px + font_ascent_desc_px  # İlk satırın baseline pozisyonu
                
                painter.setPen(QColor(0, 0, 0))  # Siyah
                painter.setFont(QFont("Arial", font_size_desc_px, QFont.Bold))
                desc_x_px = header_x_left_px + inner_padding_px
                painter.drawText(desc_x_px, desc_y_baseline_px, desc_text)
            else:
                # DİĞER SAYFALAR: Banner (yuvarlatılmış dikdörtgen) - PDF export ile aynı
                header_height_pt = 40.0  # pt
                header_height_px = int(header_height_pt * preview_scale)
                header_y_top_px = page_y + mt_px
                header_y_bottom_px = header_y_top_px + header_height_px
                
                # Banner genişliği (kenarlardan 10pt içeride)
                banner_margin_pt = 10.0
                banner_margin_px = int(banner_margin_pt * preview_scale)
                header_x_left_px = page_x + ml_px + banner_margin_px
                header_x_right_px = page_x + page_w_px - mr_px - banner_margin_px
                header_width_px = header_x_right_px - header_x_left_px
                header_radius_px = int(8.0 * preview_scale)
                
                # Dış turuncu çerçeve (sadece stroke, içi beyaz)
                header_rect = QRect(header_x_left_px, header_y_top_px, header_width_px, header_height_px)
                painter.setBrush(QBrush(QColor(255, 255, 255)))  # Beyaz iç
                painter.setPen(QPen(orange_color, int(1.5 * preview_scale)))  # Turuncu çerçeve
                painter.drawRoundedRect(header_rect, header_radius_px, header_radius_px)
                
                # Sol tarafta: Test başlığı (turuncu renk, bold, 12pt)
                test_title = (self.export_options.test_title.strip() or "TEST")
                painter.setPen(orange_color)  # Turuncu
                font_size_title_pt = 12.0
                font_size_title_px = int(font_size_title_pt * preview_scale)
                painter.setFont(QFont("Arial", font_size_title_px, QFont.Bold))
                font_metrics_title = painter.fontMetrics()
                title_y_px = header_y_top_px + (header_height_px // 2) - (font_metrics_title.height() // 2) + font_metrics_title.ascent()
                title_x_px = header_x_left_px + int(8.0 * preview_scale)
                painter.drawText(title_x_px, title_y_px, test_title)
                
                # Sağ tarafta: Okul adı (turuncu renk, normal, 10pt)
                if self.export_options.school_name.strip():
                    school_text = self.export_options.school_name.strip()
                    painter.setPen(orange_color)  # Turuncu
                    font_size_school_pt = 10.0
                    font_size_school_px = int(font_size_school_pt * preview_scale)
                    painter.setFont(QFont("Arial", font_size_school_px, QFont.Normal))
                    font_metrics_school = painter.fontMetrics()
                    school_width_px = font_metrics_school.width(school_text)
                    school_y_px = header_y_top_px + (header_height_px // 2) - (font_metrics_school.height() // 2) + font_metrics_school.ascent()
                    school_x_px = header_x_right_px - school_width_px - int(8.0 * preview_scale)
                    painter.drawText(school_x_px, school_y_px, school_text)
            
            # Footer yüksekliği (PDF export ile aynı)
            footer_y_top_pt = mb_pt + 35.0  # Footer'ın üst çizgisi (pt)
            footer_y_bottom_pt = mb_pt + 15.0  # Footer'ın alt çizgisi (pt)
            footer_y_top_px = int(footer_y_top_pt * preview_scale)
            footer_y_bottom_px = int(footer_y_bottom_pt * preview_scale)
            
            # Sütun çizgisi (2+ sütun varsa) - Footer bölgesinde çizilmemeli, turuncu renk
            cols = int(self.export_options.columns or 1)
            if cols > 1:
                line_x = int(page_x + page_w_px // 2)
                # Header yüksekliği (ilk sayfa için dinamik, diğer sayfalar için 40pt)
                # header_height_px zaten yukarıda hesaplandı
                header_h_px = header_height_px
                y_start_line = page_y + mt_px + header_h_px  # Header'dan sonra başla
                # Footer'ın üst çizgisine kadar çiz (footer bölgesinde çizilmemeli)
                y_end_line = page_y + page_h_px - footer_y_top_px  # Footer'ın üst çizgisine kadar
                # Turuncu renk ve kalın çizgi (PDF export ile aynı)
                painter.setPen(QPen(orange_color, int(1.0 * preview_scale)))
                painter.drawLine(line_x, y_start_line, line_x, y_end_line)
            
            # Mevcut sayfadaki soruları PDF layout'una göre çiz
            if self.pages and self.current_page < len(self.pages):
                page_questions = self.pages[self.current_page]
                if page_questions:
                    print(f"DEBUG: paintEvent - Sayfa {self.current_page + 1}, {len(page_questions)} soru var")
                else:
                    print(f"DEBUG: paintEvent - Sayfa {self.current_page + 1}, soru yok!")
                
                for idx, q in enumerate(page_questions):
                    try:
                        # Görselin pozisyonunu kontrol et
                        if q.x == 0 and q.y == 0 and q.display_width == 0 and q.display_height == 0:
                            # Henüz layout yapılmamış - layout'u zorla yap
                            print(f"DEBUG: Soru {q.selection.number} henüz layout yapılmamış - layout zorlanıyor...")
                            # Bu soruyu içeren sayfayı yeniden layout yap
                            if self.export_options:
                                self._layout_single_page(self.current_page, page_questions)
                            continue
                        
                        img_rect = self._get_image_rect(q)
                        if img_rect.width() <= 0 or img_rect.height() <= 0:
                            print(f"DEBUG: Soru {idx + 1} boyut hatası (w={img_rect.width()}, h={img_rect.height()})")
                            continue
                        
                        # Görsel pixmap'in null olup olmadığını kontrol et
                        if q.cropped_pixmap.isNull():
                            print(f"DEBUG: Soru {idx + 1} pixmap null!")
                            continue
                        
                        print(f"DEBUG: Soru {idx + 1} çiziliyor - x={q.x}, y={q.y}, w={q.display_width}, h={q.display_height}, pixmap w={q.cropped_pixmap.width()}, h={q.cropped_pixmap.height()}")
                        
                        # Görseli çiz (yüksek kalite ile boyutlandırılmış)
                        scaled_pixmap = q.cropped_pixmap.scaled(
                            img_rect.width(), img_rect.height(),
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )
                        painter.drawPixmap(img_rect.topLeft(), scaled_pixmap)
                    except Exception as ex:
                        print(f"Hata: Soru {idx + 1} çizilirken: {ex}")
                        import traceback
                        traceback.print_exc()
                        continue
                    
                    # Seçili soru için kırmızı kesikli çerçeve
                    if q == self._selected_question:
                        pen = QPen(QColor(255, 0, 0), max(2, int(2 * preview_scale)), Qt.SolidLine)
                        painter.setPen(pen)
                        painter.setBrush(Qt.NoBrush)
                        painter.drawRect(img_rect.adjusted(-1, -1, 1, 1))
                    
                    # Soru numarası (PDF formatında - numara solda, görsel sağda)
                    painter.setFont(QFont("Arial", int(10 * preview_scale), QFont.Bold))
                    painter.setPen(QColor(0, 0, 0))  # Siyah
                    painter.setBrush(Qt.NoBrush)
                    num_text = f"{getattr(q, 'display_number', getattr(q.selection, 'number', '?'))}."
                    # Numara görselin solunda (PDF'deki gibi)
                    number_width_px = int(len(num_text) * 6.0 * preview_scale)
                    number_gap_px = int(4.0 * preview_scale)
                    num_rect = QRect(img_rect.left() - number_width_px - number_gap_px, img_rect.top(), 
                                   number_width_px, int(12.0 * preview_scale))
                    painter.drawText(num_rect, Qt.AlignVCenter | Qt.AlignRight, num_text)
                    
                    # Sadece sağ alt köşe tutamacı (seçili ise)
                    if q == self._selected_question:
                        handles = self._get_handles(img_rect)
                        painter.setBrush(QBrush(QColor(220, 0, 0)))
                        painter.setPen(QPen(QColor(255, 255, 255), 2))
                        for handle_rect in handles.values():
                            painter.drawRect(handle_rect)
                    
                    # NOT: Üst boşluk çizgisi kaldırıldı (performans nedeniyle)
                    # Sadece alt boşluk çizgisi gösteriliyor
                    
                    # ALT BOŞLUK ÇİZGİSİ (sorunun altında) - Her zaman göster (tek soru olsa bile)
                    gap_line_rect_bottom = self._get_gap_line_rect(q, is_top=False)
                    if gap_line_rect_bottom.width() > 0 and gap_line_rect_bottom.height() > 0:
                        is_hovered_bottom = (q == self._hovered_gap_question and not self._hovered_gap_is_top)
                        is_adjusted_bottom = (q == self._gap_being_adjusted and not self._gap_being_adjusted_is_top)
                        is_active_bottom = is_hovered_bottom or is_adjusted_bottom
                        
                        self._draw_modern_gap_line(painter, gap_line_rect_bottom, q, is_top=False, is_active=is_active_bottom)
            
            # Footer çiz (cevap anahtarları ve sayfa numarası) - PDF export ile aynı
            # Footer pozisyonları (pt'den px'e çevir)
            footer_y_center_pt = (footer_y_bottom_pt + footer_y_top_pt) / 2.0  # İki çizgi arası orta nokta (pt)
            footer_y_center_px = int(footer_y_center_pt * preview_scale)
            
            # Qt koordinat sistemi: y=0 üstte, y artar aşağı iner
            # PDF'de footer_y_bottom = mb + 15.0 (sayfanın altından 15pt yukarı)
            # Qt'de: footer_y_bottom_qt = page_y + page_h_px - footer_y_bottom_px (sayfanın altından yukarı)
            footer_y_bottom_qt = page_y + page_h_px - footer_y_bottom_px
            footer_y_top_qt = page_y + page_h_px - footer_y_top_px
            footer_y_center_qt = page_y + page_h_px - footer_y_center_px
            
            # Üst çizgi (tüm sayfa genişliğinde)
            painter.setPen(QPen(orange_color, int(0.5 * preview_scale)))
            painter.drawLine(page_x + ml_px, footer_y_top_qt, page_x + page_w_px - mr_px, footer_y_top_qt)
            
            # Cevap anahtarları (mevcut sayfadaki soruların cevapları)
            if self.pages and self.current_page < len(self.pages):
                page_questions = self.pages[self.current_page]
                if page_questions:
                    # Bu sayfadaki soruların cevaplarını topla
                    answers_list = []
                    for q in page_questions:
                        num = getattr(q.selection, 'number', None)
                        ans = (getattr(q.selection, 'answer', '') or '').strip().upper()
                        if num is not None:
                            answers_list.append((num, ans))
                    
                    # Cevap anahtarlarını çiz (sola yaslanmış, turuncu renk)
                    if answers_list:
                        # Cevap anahtarlarını sırala
                        sorted_answers = sorted(answers_list, key=lambda t: t[0])
                        answer_texts = []
                        for num, ans in sorted_answers:
                            # Cevap varsa göster, yoksa "?" göster
                            if ans and ans.strip():
                                answer_texts.append(f"{num}. {ans}")
                            else:
                                answer_texts.append(f"{num}. ?")
                        
                        answer_text = "  ".join(answer_texts)
                        painter.setFont(QFont("Arial", int(9 * preview_scale)))
                        painter.setPen(orange_color)
                        # Dikey ortalama için font metrikleri kullan
                        font_metrics = painter.fontMetrics()
                        text_height = font_metrics.height()
                        answer_x = page_x + ml_px  # Sola yaslanmış
                        answer_y = footer_y_center_qt + text_height / 2.0 - font_metrics.descent()
                        painter.drawText(int(answer_x), int(answer_y), answer_text)
            
            # Alt çizgi (tüm sayfa genişliğinde)
            painter.setPen(QPen(orange_color, int(0.5 * preview_scale)))
            painter.drawLine(page_x + ml_px, footer_y_bottom_qt, page_x + page_w_px - mr_px, footer_y_bottom_qt)
            
            # Sayfa numarası (yuvarlak içinde, iki çizgi arasında, TAM ORTADA)
            footer_space_pt = footer_y_top_pt - footer_y_bottom_pt  # 20.0 pt
            max_circle_radius_pt = footer_space_pt / 2.0 - 2.0  # 2.0 pt güvenlik payı
            circle_radius_pt = min(12.0, max_circle_radius_pt)  # Maksimum 12.0 pt ama çizgi aralığına sığmalı
            circle_radius_px = int(circle_radius_pt * preview_scale)
            
            page_num_text = str(self.current_page + 1)
            painter.setFont(QFont("Arial", int(10 * preview_scale), QFont.Bold))
            font_metrics = painter.fontMetrics()
            page_num_width_px = font_metrics.width(page_num_text)
            
            # Yuvarlak sayfanın ortasında olacak (x ekseninde)
            circle_x = page_x + (ml_px + page_w_px - mr_px) / 2.0  # Tam orta
            circle_y = footer_y_center_qt  # İki çizgi arasında ortala
            
            # Yuvarlak çiz (turuncu çizgi rengi ile)
            painter.setPen(QPen(orange_color, int(1.0 * preview_scale)))
            painter.setBrush(QBrush(QColor(255, 255, 255)))  # Beyaz iç
            painter.drawEllipse(int(circle_x - circle_radius_px), int(circle_y - circle_radius_px),
                               int(circle_radius_px * 2), int(circle_radius_px * 2))
            
            # Sayfa numarası yazısı
            painter.setPen(QColor(0, 0, 0))  # Siyah yazı
            text_x = circle_x - page_num_width_px / 2.0
            text_y = circle_y + font_metrics.ascent() / 2.0 - font_metrics.descent()
            painter.drawText(int(text_x), int(text_y), page_num_text)
            
            # Widget boyutunu içeriğe göre ayarla (scroll için)
            total_height = page_y + page_h_px + 20
            total_width = page_x + page_w_px + 20
            self.setMinimumSize(total_width, total_height)
            if self.width() < total_width or self.height() < total_height:
                self.resize(max(self.width(), total_width), max(self.height(), total_height))
        except Exception as ex:
            import traceback
            print(f"Hata: paintEvent sırasında: {ex}\n{traceback.format_exc()}")
    
    def mousePressEvent(self, e):
        """Mouse basıldığında"""
        try:
            pos = e.pos()
            self._selected_question = None
            self._resize_handle = None
            self._is_resizing = False
            self._is_adjusting_gap = False
            self._gap_being_adjusted = None
            
            if not self.pages or self.current_page >= len(self.pages):
                # Boş alan - seçimi kaldır ama hata verme
                self._selected_question = None
                self.update()
                return
            
            page_questions = self.pages[self.current_page]
            if not page_questions:
                # Sayfa boş - seçimi kaldır ama hata verme
                self._selected_question = None
                self.update()
                return
            
            # Önce tutamaçları kontrol et (resize için)
            for q in reversed(page_questions):
                try:
                    img_rect = self._get_image_rect(q)
                    if img_rect.width() <= 0 or img_rect.height() <= 0:
                        continue
                    handles = self._get_handles(img_rect)
                    
                    for handle_name, handle_rect in handles.items():
                        if handle_rect.contains(pos):
                            self._selected_question = q
                            # Sol menüde ilgili soruyu aktif yap
                            try:
                                dlg = self.window()
                                if dlg and hasattr(dlg, "question_list_widget") and dlg.question_list_widget:
                                    dlg.question_list_widget.last_modified_question = q.selection.number
                                    dlg.question_list_widget._on_question_clicked(int(q.selection.number))
                            except Exception:
                                pass
                            self._resize_handle = handle_name
                            self._is_resizing = True
                            self._is_adjusting_gap = False  # Resize modunda gap ayarlama kapalı
                            self.drag_start = pos
                            self.initial_rect = QRect(img_rect)
                            self.initial_width = q.display_width
                            self.initial_height = q.display_height
                            self.update()
                            return
                except Exception as ex:
                    print(f"Hata: Tutamac kontrolü sırasında: {ex}")
                    continue
            
            # İKİNCİ: Boşluk çizgilerini kontrol et (gap adjustment için) - hem üst hem alt
            # ÖNEMLİ: Üst çizgi bir önceki sorunun alt boşluğunu ayarlar
            # Boşluk çizgisini kontrol et (sadece alt çizgi - üst çizgi kaldırıldı performans için)
            for q in reversed(page_questions):
                try:
                    # Sadece alt çizgiyi kontrol et
                    gap_line_rect_bottom = self._get_gap_line_rect(q, is_top=False)
                    if gap_line_rect_bottom.width() > 0 and gap_line_rect_bottom.height() > 0 and gap_line_rect_bottom.contains(pos):
                        # Alt çizgi: Bu sorunun alt boşluğunu ayarla
                        self._gap_being_adjusted = q
                        self._gap_being_adjusted_is_top = False
                        self._is_adjusting_gap = True
                        self._is_resizing = False  # Gap ayarlama modunda resize kapalı
                        self._gap_adjust_start_y = pos.y()
                        
                        # Mevcut alt boşluk değerini al (pt cinsinden)
                        preview_scale = self._get_preview_scale()
                        if q.custom_gap_after_pt is not None:
                            self._gap_adjust_initial_pt = q.custom_gap_after_pt
                        else:
                            # Varsayılan boşluğu kullan
                            question_gap_pt = self.export_options.question_gap_pt() if self.export_options else 12.0
                            self._gap_adjust_initial_pt = question_gap_pt
                        
                        self.setCursor(Qt.SizeVerCursor)  # Dikey resize cursor
                        self.update()
                        return
                except Exception as ex:
                    print(f"Hata: Boşluk çizgisi kontrolü sırasında: {ex}")
                    continue
            
            # ÜÇÜNCÜ: Görselin içini kontrol et (seçim için - resize başlatmaz)
            for q in reversed(page_questions):
                try:
                    img_rect = self._get_image_rect(q)
                    if img_rect.width() <= 0 or img_rect.height() <= 0:
                        continue
                    if img_rect.contains(pos):
                        self._selected_question = q
                        # Sol menüde ilgili soruyu aktif yap
                        try:
                            dlg = self.window()
                            if dlg and hasattr(dlg, "question_list_widget") and dlg.question_list_widget:
                                dlg.question_list_widget.last_modified_question = q.selection.number
                                dlg.question_list_widget._on_question_clicked(int(q.selection.number))
                        except Exception:
                            pass
                        self._is_resizing = False
                        self._is_adjusting_gap = False
                        self._resize_handle = None
                        self.update()
                        return
                except Exception as ex:
                    print(f"Hata: Görsel kontrolü sırasında: {ex}")
                    continue
            
            # Hiçbir şeye basılmadıysa seçimi kaldır
            self._selected_question = None
            self._is_resizing = False
            self._resize_handle = None
        except Exception as ex:
            import traceback
            print(f"Hata: mousePressEvent sırasında: {ex}\n{traceback.format_exc()}")
            # Hata olsa bile seçimi kaldır ve devam et
            self._selected_question = None
            self.update()
    
    def mouseMoveEvent(self, e):
        """Mouse hareket ettiğinde"""
        pos = e.pos()
        
        # BOŞLUK AYARLAMA işlemi devam ediyorsa
        if self._is_adjusting_gap and self._gap_being_adjusted:
            if not self.export_options:
                return
            
            # Mouse hareketi ile boşluğu ayarla
            delta_y = pos.y() - self._gap_adjust_start_y  # Piksel cinsinden fark
            
            # Piksel farkını pt'ye çevir (preview_scale kullanarak)
            preview_scale = self._get_preview_scale()
            delta_pt = delta_y / preview_scale  # Piksel -> pt
            
            # Yeni boşluk değeri = başlangıç + değişim
            # NOT: Artık her zaman alt boşluğu ayarlıyoruz (üst çizgi bir önceki sorunun alt boşluğunu ayarlar)
            # Alt boşluk: yukarı sürükleyince boşluk azalır, aşağı sürükleyince artar
            new_gap_pt = self._gap_adjust_initial_pt + delta_pt
            
            # Minimum ve maksimum sınırlar (10 mm ile 50 mm arası)
            from testmaker.services.pdf_exporter import mm_to_pt
            min_gap_pt = mm_to_pt(10.0)  # 10 mm -> pt
            max_gap_pt = mm_to_pt(100.0)  # 100 mm -> pt
            new_gap_pt = max(min_gap_pt, min(max_gap_pt, new_gap_pt))
            
            # Boşluğu güncelle (her zaman alt boşluk)
            self._gap_being_adjusted.custom_gap_after_pt = new_gap_pt
            
            # Anlık görsel güncelleme (sadece mevcut sayfayı yeniden çiz)
            self.update()
            
            # Tüm soruları yeniden organize et (sayfa sonu kontrolleri, yeni sayfaya taşıma vs.)
            # Anlık güncelleme için direkt çağır (timer gecikmesi olmadan)
            # Timer sadece çok hızlı değişikliklerde performans için kullanılabilir
            if hasattr(self, 'reorganize_timer') and self.reorganize_timer:
                self.reorganize_timer.stop()
                # Çok kısa bir gecikme ile çağır (10ms - neredeyse anlık)
                self.reorganize_timer.start(10)
            else:
                # Timer yoksa hemen yap (fallback)
                self._reorganize_after_gap_adjustment()
            return
        
        # RESIZE işlemi devam ediyorsa, resize yap ve return
        if self._is_resizing and self._selected_question:
            # Resize işlemini devam ettir
            pass
        else:
            # Resize/gap işlemi yoksa cursor güncelle
            cursor_set = False
            hovered_gap = None
            
            if self.pages and self.current_page < len(self.pages):
                page_questions = self.pages[self.current_page]
                if page_questions:
                    # Boşluk çizgisini kontrol et (hover efekti için) - sadece alt çizgi (üst çizgi kaldırıldı performans için)
                    for q in reversed(page_questions):
                        try:
                            # Alt çizgiyi kontrol et (bu sorunun alt boşluğunu gösterir)
                            gap_line_rect_bottom = self._get_gap_line_rect(q, is_top=False)
                            if gap_line_rect_bottom.width() > 0 and gap_line_rect_bottom.height() > 0 and gap_line_rect_bottom.contains(pos):
                                hovered_gap = q
                                self._hovered_gap_is_top = False
                                self.setCursor(Qt.SizeVerCursor)
                                cursor_set = True
                                break
                        except Exception:
                            continue
                    
                    # Boşluk çizgisi yoksa diğer kontrolleri yap
                    if not cursor_set:
                        for q in reversed(page_questions):
                            try:
                                img_rect = self._get_image_rect(q)
                                if img_rect.width() <= 0 or img_rect.height() <= 0:
                                    continue
                                
                                # Önce görselin içini kontrol et
                                if img_rect.contains(pos):
                                    self.setCursor(Qt.PointingHandCursor)
                                    cursor_set = True
                                    break
                                
                                # Sonra tutamaçları kontrol et
                                handles = self._get_handles(img_rect)
                                for handle_name, handle_rect in handles.items():
                                    if handle_rect.contains(pos):
                                        if handle_name == "bottom_right":
                                            self.setCursor(Qt.SizeFDiagCursor)
                                        else:
                                            self.setCursor(Qt.SizeAllCursor)
                                        cursor_set = True
                                        break
                                
                                if cursor_set:
                                    break
                            except Exception:
                                continue
            
            # Hover edilen boşluk çizgisini güncelle (görsel güncelleme için)
            if hovered_gap != self._hovered_gap_question:
                self._hovered_gap_question = hovered_gap
                self.update()
            
            if not cursor_set:
                self.setCursor(Qt.ArrowCursor)
                if self._hovered_gap_question:
                    self._hovered_gap_question = None
                    self._hovered_gap_is_top = False
                    self.update()
            
            # Resize işlemi yoksa burada bitir
            return
        
        # Resize işlemi devam ediyorsa buraya gelir
        if not self._selected_question:
            return
            
        if not self._is_resizing:
            return
            
        if not self.export_options:
            return
        
        # Sadece sağ alt köşeden resize
        if self._resize_handle == "bottom_right":
            # Sol üst köşe sabit (x, y değişmez)
            left = self._selected_question.x
            top = self._selected_question.y
            
            # Yeni sağ alt köşe pozisyonu
            new_right = max(left + 50, pos.x())  # Minimum 50px genişlik
            new_bottom = max(top + 50, pos.y())  # Minimum 50px yükseklik
            
            # Yeni boyutlar (px cinsinden - ön izlemede görüntülenen boyut)
            # Bu boyut, PDF'deki FINAL boyutun px karşılığıdır (available_width kontrolünden SONRA)
            new_width_px = new_right - left
            new_height_px = new_bottom - top
            
            # Orijinal kırpılmış görsel boyutları (piksel)
            orig_w_px = self._selected_question.cropped_pixmap.width()
            orig_h_px = self._selected_question.cropped_pixmap.height()
            
            if orig_w_px <= 0 or orig_h_px <= 0:
                return
            
            # PDF export mantığı ile AYNI parametreler
            from testmaker.services.pdf_exporter import mm_to_pt
            # Önizleme ölçeği: pt'den px'e dönüşüm (ekran DPI'sına göre) - layout ile AYNI
            preview_scale = self._get_preview_scale()
            
            # Render DPI'yi kullan: zoom = render_dpi / 72.0 (PDF export ile aynı mantık)
            render_dpi = getattr(self, 'render_dpi', 72.0)
            zoom = render_dpi / 72.0  # PDF export ile AYNI: render_dpi / 72.0
            text_scale = 10.0 / 12.0  # PDF export'taki scale_factor (0.833)
            
            # Seçili sorunun hangi sayfa ve sütunda olduğunu bul
            page_idx = self._selected_question.page_num
            col_idx = self._selected_question.col_num
            
            # Sütun genişliğini hesapla (PDF export mantığı ile aynı)
            page_w_pt, page_h_pt = self.export_options.page_size_pt()
            ml_pt, mr_pt, mt_pt, mb_pt = self.export_options.margins_pt()
            col_gap_pt = self.export_options.column_gap_pt()
            cols = max(1, min(6, int(self.export_options.columns or 1)))
            
            x_line_center = page_w_pt / 2.0
            header_right_edge = page_w_pt - mr_pt
            
            if cols > 1:
                left_space = x_line_center - ml_pt
                right_space = header_right_edge - x_line_center
                left_columns_count = (cols + 1) // 2
                right_columns_count = cols - left_columns_count
                
                if left_columns_count > 1:
                    left_col_w = (left_space - (left_columns_count - 1) * col_gap_pt) / left_columns_count
                else:
                    left_col_w = left_space
                
                if right_columns_count > 1:
                    right_col_w = (right_space - (right_columns_count - 1) * col_gap_pt) / right_columns_count
                else:
                    right_col_w = right_space
                
                col_w_pt = min(left_col_w, right_col_w)
            else:
                col_w_pt = x_line_center - ml_pt
            
            # Numara genişliği (PDF export ile aynı)
            number_text = f"{getattr(self._selected_question, 'display_number', getattr(self._selected_question.selection, 'number', '?'))}."
            number_width_pt = max(6.0, len(number_text) * 6.0)  # Minimum 6pt
            number_gap_pt = 4.0
            right_padding_pt = 4.0
            available_width_pt = col_w_pt - number_width_pt - number_gap_pt - right_padding_pt
            
            # Ön izlemede görüntülenen boyut (px) PDF'deki FINAL boyutun px karşılığıdır
            # PDF'deki final boyut: draw_w_pt_final (available_width kontrolünden SONRA)
            # draw_w_pt_final = min(draw_w_pt_before, available_width_pt)
            # draw_w_pt_before = (orig_w_px / zoom) * display_scale * text_scale
            
            # Ön izlemede: new_width_px = draw_w_pt_final * preview_scale
            # Yani: draw_w_pt_final = new_width_px / preview_scale
            draw_w_pt_final = new_width_px / preview_scale
            draw_h_pt_final = new_height_px / preview_scale
            
            # draw_w_pt_final, available_width_pt ile sınırlanmış olabilir
            # display_scale hesaplarken, draw_w_pt_final'den geriye doğru hesaplamalıyız
            # draw_w_pt_before >= draw_w_pt_final olmalı (available_width kontrolü uygulanabilir)
            # draw_w_pt_before = (orig_w_px / zoom) * display_scale * text_scale
            # Eğer draw_w_pt_final < available_width_pt ise, sınırlama yok:
            #   draw_w_pt_before = draw_w_pt_final
            #   display_scale = draw_w_pt_final / ((orig_w_px / zoom) * text_scale)
            # Eğer draw_w_pt_final = available_width_pt ise, sınırlama var:
            #   draw_w_pt_before >= available_width_pt olmalı
            #   display_scale >= available_width_pt / ((orig_w_px / zoom) * text_scale)
            
            # Basit yaklaşım: draw_w_pt_final'den display_scale hesapla
            # Eğer bu değer available_width'ı geçerse, layout'ta otomatik olarak sınırlanacak
            img_w_pt_base = orig_w_px / zoom
            img_h_pt_base = orig_h_px / zoom
            
            # display_scale hesapla (available_width kontrolü ÖNCESİ değerden)
            # draw_w_pt_final = min(draw_w_pt_before, available_width_pt)
            # Eğer draw_w_pt_final = available_width_pt ise, draw_w_pt_before >= available_width_pt olmalı
            # En azından draw_w_pt_final kadar büyük olmalı
            # display_scale hesaplarken draw_w_pt_final'den başla, ama available_width'ı da dikkate al
            
            # Genişlik için display_scale hesapla
            if draw_w_pt_final >= available_width_pt:
                # Sınırlanmış durumda - available_width'ı geçebilir ama layout'ta sınırlanacak
                # Minimum display_scale: available_width için gerekli olan
                min_display_scale_w = available_width_pt / (img_w_pt_base * text_scale) if img_w_pt_base > 0 else 1.0
                # İstenen display_scale: draw_w_pt_final için gerekli olan
                desired_display_scale_w = draw_w_pt_final / (img_w_pt_base * text_scale) if img_w_pt_base > 0 else 1.0
                # İstenen değeri kullan, layout'ta sınırlanacak
                display_scale_w = desired_display_scale_w
            else:
                # Sınırlanmamış durumda
                display_scale_w = draw_w_pt_final / (img_w_pt_base * text_scale) if img_w_pt_base > 0 else 1.0
            
            # Yükseklik için display_scale hesapla (genişlikle uyumlu olmalı)
            display_scale_h = draw_h_pt_final / (img_h_pt_base * text_scale) if img_h_pt_base > 0 else 1.0
            
            # En-boy oranını korumak için genişlikten hesaplanan değeri kullan
            # (Yükseklik, genişlik sınırlamasına göre otomatik ayarlanacak)
            new_display_scale = display_scale_w
            # Boyutlandırma aralığı: %0 .. %200  => 0.0 .. 2.0
            new_display_scale = max(0.0, min(2.0, new_display_scale))  # Sınırlama
            
            # Display scale güncelle
            self._selected_question.selection.display_scale = new_display_scale
                
            # Layout'u hemen güncelle (sadece görsel için, reorganize sonra yapılacak)
            self._layout_all_pages()
            self.update()
    
    def _reorganize_after_gap_adjustment(self):
        """Boşluk ayarlama sonrası tüm soruları yeniden organize et (sayfa sonu kontrolü, yeni sayfaya taşıma)"""
        try:
            if not self.questions:
                return
            
            # Dialog'dan parent'a eriş
            dialog = self.parent()
            if not hasattr(dialog, '_organize_into_pages_pdf_export_logic'):
                # Eğer parent dialog değilse, sadece layout yap
                self._layout_all_pages()
                self.update()
                return
            
            # Tüm soruları mevcut sırasına göre al (custom_gap değerleri korunarak)
            # questions listesi zaten doğru sırada, custom_gap değerleri zaten güncellenmiş
            all_questions = list(self.questions)  # Kopya al (sırayı ve custom_gap değerlerini koru)
            
            # Number'ları 1'den başlayarak güncelle
            for idx, q in enumerate(all_questions, start=1):
                q.selection.number = idx
                # Pozisyonları sıfırla - yeniden hesaplanacak
                q.x = 0
                q.y = 0
                q.display_width = 0
                q.display_height = 0
                q.page_num = 0
                q.col_num = 0
            
            # Soruları yeniden sayfalara ayır (otomatik yerleştirme - sayfa sonu kontrolleri ile)
            # Bu fonksiyon custom_gap değerlerini kullanarak soruları yerleştirir
            # Sayfa sonu kontrolleri yapılır, gerekirse yeni sayfaya taşınır
            new_pages = dialog._organize_into_pages_pdf_export_logic(all_questions)
            
            # Yeni sayfa yapısını güncelle
            self.pages = new_pages
            
            # self.questions listesini de güncelle (sayfa yapısındaki sıraya göre)
            # Tüm sayfalardaki soruları sırayla al (reorganize sonrası yeni sıraya göre)
            reorganized_questions = []
            for page_questions in new_pages:
                reorganized_questions.extend(page_questions)
            
            # self.questions'ı güncelle (reorganize sonrası yeni sıraya göre)
            # Eğer soru sayısı değişmediyse (normal durum), self.questions'ı güncelle
            if len(reorganized_questions) == len(all_questions):
                self.questions = reorganized_questions
                print(f"DEBUG: _reorganize_after_gap_adjustment - self.questions güncellendi: {len(self.questions)} soru")
            else:
                print(f"DEBUG: _reorganize_after_gap_adjustment - UYARI: Soru sayısı değişti! Eski: {len(all_questions)}, Yeni: {len(reorganized_questions)}")
                # Soru sayısı değiştiyse de güncelle (bazı sorular filtrelenmiş olabilir)
                self.questions = reorganized_questions
            
            # Debug: Sayfa yapısını kontrol et
            print(f"DEBUG: _reorganize_after_gap_adjustment - {len(new_pages)} sayfa oluşturuldu, {len(reorganized_questions)} soru")
            for page_idx, page_questions in enumerate(new_pages):
                print(f"  Sayfa {page_idx + 1}: {len(page_questions)} soru - numaralar: {[q.selection.number for q in page_questions]}")
            
            # Boşluk ayarlanan sorunun yeni sayfasını bul ve oraya geç
            if self._gap_being_adjusted:
                for page_idx, page_questions in enumerate(self.pages):
                    if self._gap_being_adjusted in page_questions:
                        self.current_page = page_idx
                        break
            
            # Layout'u yeniden hesapla - TÜM sayfalar için (sadece current_page değil)
            # Bu işlem sayfa sonu kontrolleri, yeni sayfaya taşıma, üst margin kontrolleri vs. yapacak
            print(f"DEBUG: _reorganize_after_gap_adjustment - Layout hesaplanıyor, {len(self.pages)} sayfa var")
            self._layout_all_pages()
            
            # ÖNEMLİ: PreviewQuestion'lardaki custom_gap değerlerini Selection objelerine kopyala
            # Bu, PDF export'un doğru değerleri görmesini sağlar
            dialog = self.parent()
            if hasattr(dialog, 'selections'):
                gap_after_map = {}  # {selection.number: custom_gap_after_pt}
                gap_before_map = {}  # {selection.number: custom_gap_before_pt}
                
                for q in self.questions:
                    sel_number = q.selection.number
                    if q.custom_gap_after_pt is not None:
                        gap_after_map[sel_number] = q.custom_gap_after_pt
                    if q.custom_gap_before_pt is not None:
                        gap_before_map[sel_number] = q.custom_gap_before_pt
                
                # Dialog'daki Selection objelerine custom_gap değerlerini kopyala
                for sel in dialog.selections:
                    sel_number = sel.number
                    if sel_number in gap_after_map:
                        sel.custom_gap_after_pt = gap_after_map[sel_number]
                    elif sel_number in [q.selection.number for q in self.questions]:
                        # Eğer soru listede varsa ama gap_after_map'te yoksa, None yap (varsayılan kullanılsın)
                        sel.custom_gap_after_pt = None
                    
                    if sel_number in gap_before_map:
                        sel.custom_gap_before_pt = gap_before_map[sel_number]
                    elif sel_number in [q.selection.number for q in self.questions]:
                        sel.custom_gap_before_pt = None
                
                print(f"DEBUG: _reorganize_after_gap_adjustment - {len(gap_after_map)} gap_after, {len(gap_before_map)} gap_before değeri Selection objelerine kopyalandı")
            
            self.update()
            
            # Zorla repaint
            self.repaint()
            
            # ÖNEMLİ: PreviewQuestion'daki custom_gap değerlerini Selection objelerine kopyala
            # Böylece PDF export'ta kullanılabilir
            # Selection objeleri MainWindow'daki Selection objelerinin referansları olduğu için
            # Bu değişiklikler otomatik olarak MainWindow'a yansır
            for q in self.questions:
                if q.custom_gap_after_pt is not None:
                    # Direkt olarak Selection objesine yaz (referans olduğu için MainWindow'a yansır)
                    q.selection.custom_gap_after_pt = q.custom_gap_after_pt
                    print(f"DEBUG: _reorganize_after_gap_adjustment - Soru {q.selection.number}'a custom_gap_after_pt={q.custom_gap_after_pt:.2f} yazıldı")
                if q.custom_gap_before_pt is not None:
                    # Direkt olarak Selection objesine yaz (referans olduğu için MainWindow'a yansır)
                    q.selection.custom_gap_before_pt = q.custom_gap_before_pt
                    print(f"DEBUG: _reorganize_after_gap_adjustment - Soru {q.selection.number}'a custom_gap_before_pt={q.custom_gap_before_pt:.2f} yazıldı")
            
            # Dialog içindeki Selection listesindeki tüm Selection'lara da yaz (ekstra güvence için)
            dialog = self.parent()
            if hasattr(dialog, 'selections'):
                for sel in dialog.selections:
                    # PreviewQuestion'dan custom_gap değerini bul
                    for q in self.questions:
                        if q.selection.number == sel.number:
                            if q.custom_gap_after_pt is not None:
                                sel.custom_gap_after_pt = q.custom_gap_after_pt
                            if q.custom_gap_before_pt is not None:
                                sel.custom_gap_before_pt = q.custom_gap_before_pt
                            break
            
            # Sayfa bilgisini güncelle
            if hasattr(dialog, '_update_page_info'):
                dialog._update_page_info()
        except Exception as e:
            import traceback
            print(f"Hata: Boşluk ayarlama sonrası yeniden organize etme sırasında: {e}\n{traceback.format_exc()}")
            # Hata durumunda sadece layout yap
            self._layout_all_pages()
            self.update()
    
    def _reorganize_after_resize(self):
        """Resize sonrası tüm soruları yeniden organize et (otomatik yerleştirme)"""
        try:
            if not self.questions:
                return
            
            # Dialog'dan parent'a eriş
            dialog = self.parent()
            if not hasattr(dialog, '_organize_into_pages_pdf_export_logic'):
                # Eğer parent dialog değilse, sadece layout yap
                self._layout_all_pages()
                return
            
            # Tüm soruları mevcut sırasına göre al (number'a göre değil, questions listesindeki sıraya göre)
            # questions listesi zaten doğru sırada, sadece number'ları 1'den başlayarak güncelle
            all_questions = list(self.questions)  # Kopya al (sırayı koru)
            
            # Number'ları 1'den başlayarak güncelle (eğer zaten güncellenmemişse)
            for idx, q in enumerate(all_questions, start=1):
                q.selection.number = idx
                # Pozisyonları sıfırla - yeniden hesaplanacak
                q.x = 0
                q.y = 0
                q.display_width = 0
                q.display_height = 0
                q.page_num = 0
                q.col_num = 0
            
            # Soruları yeniden sayfalara ayır (otomatik yerleştirme)
            # Bu fonksiyon questions listesindeki sıraya göre işler
            new_pages = dialog._organize_into_pages_pdf_export_logic(all_questions)
            
            # Yeni sayfa yapısını güncelle
            self.pages = new_pages
            
            # Debug: Sayfa yapısını kontrol et
            print(f"DEBUG: _reorganize_after_resize - {len(new_pages)} sayfa oluşturuldu")
            for page_idx, page_questions in enumerate(new_pages):
                print(f"  Sayfa {page_idx + 1}: {len(page_questions)} soru - numaralar: {[q.selection.number for q in page_questions]}")
            
            # Seçili sorunun yeni sayfasını bul ve oraya geç
            if self._selected_question:
                for page_idx, page_questions in enumerate(self.pages):
                    if self._selected_question in page_questions:
                        self.current_page = page_idx
                        break
            
            # Layout'u yeniden hesapla - TÜM sayfalar için (sadece current_page değil)
            print(f"DEBUG: _reorganize_after_resize - Layout hesaplanıyor, {len(self.pages)} sayfa var")
            self._layout_all_pages()
            
            # Widget'ı güncelle - bu paintEvent'i tetikleyecek
            print(f"DEBUG: _reorganize_after_resize - Widget güncelleniyor")
            self.update()
            
            # Zorla repaint
            self.repaint()
            
            # Sayfa bilgisini güncelle
            if hasattr(dialog, '_update_page_info'):
                dialog._update_page_info()
        except Exception as e:
            import traceback
            print(f"Hata: Yeniden organize etme sırasında: {e}\n{traceback.format_exc()}")
            # Hata durumunda sadece layout yap
            self._layout_all_pages()
            self.update()
    
    def mouseReleaseEvent(self, e):
        """Mouse bırakıldığında"""
        # Boşluk ayarlama işlemini tamamla
        if self._is_adjusting_gap:
            # Boşluk ayarlama tamamlandı - son reorganize (timer ile yapılıyor ama mouse release'de timer'ı durdurup hemen yapalım)
            self._is_adjusting_gap = False
            adjusted_question = self._gap_being_adjusted
            self._gap_being_adjusted = None
            self.setCursor(Qt.ArrowCursor)
            
            # Timer'ı durdur ve hemen reorganize et (mouse release'de final)
            if hasattr(self, 'reorganize_timer'):
                self.reorganize_timer.stop()
            if adjusted_question:
                # Boşluğu son kez kontrol et ve güncelle (hemen yap)
                self._reorganize_after_gap_adjustment()
        # Resize işlemini tamamla
        elif self._is_resizing:
            # Resize tamamlandı - tüm soruları yeniden organize et
            self._is_resizing = False
            self._reorganize_after_resize()
        else:
            # Sadece seçim yapıldıysa görseli güncelle
            self.update()
    
    def go_to_page(self, page_index: int):
        """Belirtilen sayfaya git"""
        if 0 <= page_index < len(self.pages):
            self.current_page = page_index
            self._selected_question = None
            self.update()


class QuestionSorterWidget(QWidget):
    """Yatay soru sıralayıcı widget (Seçenek 4)"""
    
    def __init__(self, parent=None, dialog=None):
        super().__init__(parent)
        self.dialog = dialog  # Dialog referansı (parent üzerinden erişim yerine)
        self.questions: List[PreviewQuestion] = []
        self._dragged_index = None
        self._drag_start_pos = None
        self._drag_offset = QPoint(0, 0)
        self._hover_index = None
        self.setMinimumHeight(120)
        self.setMaximumHeight(120)
        self.setStyleSheet("background-color: #E0E0E0;")
        self.setMouseTracking(True)
    
    def set_questions(self, questions: List[PreviewQuestion]):
        """Soruları ayarla"""
        print(f"DEBUG: QuestionSorterWidget.set_questions çağrıldı - {len(questions)} soru")
        self.questions = list(questions) if questions else []  # Kopya al
        # Widget genişliğini ayarla
        if self.questions:
            margin = 5
            item_width = 100
            total_width = margin + len(self.questions) * (item_width + 10)
            self.setMinimumWidth(total_width)
            print(f"DEBUG: QuestionSorterWidget genişliği ayarlandı: {total_width}")
        self.update()
    
    def get_questions(self) -> List[PreviewQuestion]:
        """Sıralanmış soruları döndür"""
        return self.questions
    
    def mousePressEvent(self, e):
        """Mouse basıldığında"""
        if e.button() == Qt.LeftButton:
            # Hangi soruya tıklandı?
            idx = self._get_question_at_pos(e.pos())
            if idx is not None:
                self._dragged_index = idx
                self._drag_start_pos = e.pos()
                # Sorunun merkezinden offset
                item_rect = self._get_question_rect(idx)
                self._drag_offset = e.pos() - item_rect.center()
                self.update()
    
    def mouseMoveEvent(self, e):
        """Mouse hareket ettiğinde"""
        if self._dragged_index is not None:
            # Sürükleniyor - pozisyonu güncelle
            self._drag_start_pos = e.pos()
            self.update()
        else:
            # Hover efekti
            old_hover = self._hover_index
            self._hover_index = self._get_question_at_pos(e.pos())
            if old_hover != self._hover_index:
                self.update()
    
    def mouseReleaseEvent(self, e):
        """Mouse bırakıldığında"""
        if self._dragged_index is not None and self._drag_start_pos:
            # Hedef pozisyonu bul
            target_idx = self._get_question_at_pos(e.pos())
            
            if target_idx is not None and target_idx != self._dragged_index:
                # Soruyu taşı
                dragged_q = self.questions.pop(self._dragged_index)
                # Hedef indeksi güncelle
                if self._dragged_index < target_idx:
                    target_idx -= 1
                self.questions.insert(target_idx, dragged_q)
                
                # Numaraları güncelle
                for idx, q in enumerate(self.questions, start=1):
                    q.selection.number = idx
                
                # Dialog'a bildir
                print(f"DEBUG: QuestionSorterWidget - soru taşındı: {self._dragged_index} -> {target_idx}")
                if self.dialog and hasattr(self.dialog, 'on_questions_reordered'):
                    print(f"DEBUG: QuestionSorterWidget - on_questions_reordered çağrılıyor")
                    self.dialog.on_questions_reordered()
                else:
                    print(f"DEBUG: QuestionSorterWidget - UYARI: dialog bulunamadı veya on_questions_reordered yok (dialog={self.dialog})")
            
            self._dragged_index = None
            self._drag_start_pos = None
            self._drag_offset = QPoint(0, 0)
            self.update()
    
    def _get_question_at_pos(self, pos: QPoint) -> int:
        """Pozisyondaki soru indeksini bul"""
        margin = 5
        item_height = self.height() - 2 * margin
        item_width = 100
        
        x = margin
        for idx in range(len(self.questions)):
            if x <= pos.x() < x + item_width:
                return idx
            x += item_width + 10  # Gap
        return None
    
    def _get_question_rect(self, idx: int) -> QRect:
        """Soru için dikdörtgen pozisyonu"""
        margin = 5
        item_height = self.height() - 2 * margin
        item_width = 100
        item_y = margin
        
        item_x = margin + idx * (item_width + 10)  # Gap
        return QRect(item_x, item_y, item_width, item_height)
    
    def paintEvent(self, e):
        """Widget çizimi"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if not self.questions:
            painter.setPen(QColor(100, 100, 100))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(self.rect(), Qt.AlignCenter, f"Sorular yükleniyor... (0 soru)")
            print(f"DEBUG: QuestionSorterWidget paintEvent - sorular boş!")
            return
        
        print(f"DEBUG: QuestionSorterWidget paintEvent - {len(self.questions)} soru çiziliyor")
        
        margin = 5
        item_height = self.height() - 2 * margin
        item_width = 100
        
        for idx, q in enumerate(self.questions):
            if idx == self._dragged_index:
                continue  # Sürüklenen soru sonra çizilecek
            
            item_rect = self._get_question_rect(idx)
            
            # Arka plan
            if idx == self._hover_index:
                painter.setBrush(QBrush(QColor(200, 200, 255)))
            else:
                painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(150, 150, 150), 2))
            painter.drawRoundedRect(item_rect, 5, 5)
            
            # Küçük önizleme görseli
            if not q.cropped_pixmap.isNull():
                preview_pixmap = q.cropped_pixmap.scaled(
                    item_width - 20, item_height - 30,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                preview_x = item_rect.x() + (item_rect.width() - preview_pixmap.width()) // 2
                preview_y = item_rect.y() + 5
                painter.drawPixmap(preview_x, preview_y, preview_pixmap)
            
            # Soru numarası
            num_text = f"{q.selection.number}."
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.setPen(QColor(0, 0, 0))
            text_rect = QRect(item_rect.x(), item_rect.bottom() - 20, item_rect.width(), 20)
            painter.drawText(text_rect, Qt.AlignCenter, num_text)
        
        # Sürüklenen soru (en üstte, opak)
        if self._dragged_index is not None and self._drag_start_pos:
            q = self.questions[self._dragged_index]
            item_rect = self._get_question_rect(self._dragged_index)
            
            # Mouse pozisyonuna göre konum
            drag_rect = QRect(
                self._drag_start_pos.x() - self._drag_offset.x() - item_rect.width() // 2,
                self._drag_start_pos.y() - self._drag_offset.y() - item_rect.height() // 2,
                item_rect.width(),
                item_rect.height()
            )
            
            painter.setOpacity(0.8)
            painter.setBrush(QBrush(QColor(150, 200, 255)))
            painter.setPen(QPen(QColor(50, 100, 200), 3))
            painter.drawRoundedRect(drag_rect, 5, 5)
            
            # Görsel
            if not q.cropped_pixmap.isNull():
                preview_pixmap = q.cropped_pixmap.scaled(
                    drag_rect.width() - 20, drag_rect.height() - 30,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                preview_x = drag_rect.x() + (drag_rect.width() - preview_pixmap.width()) // 2
                preview_y = drag_rect.y() + 5
                painter.drawPixmap(preview_x, preview_y, preview_pixmap)
            
            # Numara
            num_text = f"{q.selection.number}."
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.setPen(QColor(0, 0, 0))
            text_rect = QRect(drag_rect.x(), drag_rect.bottom() - 20, drag_rect.width(), 20)
            painter.drawText(text_rect, Qt.AlignCenter, num_text)
            painter.setOpacity(1.0)
        
        # Widget genişliğini ayarla (scroll için)
        if self.questions:
            total_width = margin + len(self.questions) * (item_width + 10)
            self.setMinimumWidth(total_width)
            if self.width() < total_width:
                self.resize(total_width, self.height())


class PDFRenderPreviewWidget(QWidget):
    """PDF export'un render edilmiş görselini gösteren widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_pixmap: QPixmap = None
        self.original_pixmap: QPixmap = None  # Orijinal boyut
        self.status_text: str = "PDF önizlemesi hazırlanıyor..."
        self.current_page = 0
        self.total_pages = 0
        self.zoom_factor = 1.0  # Zoom faktörü
        self.pan_offset = QPoint(0, 0)  # Pan (sürükleme) offset
        self.pan_start_pos = None  # Pan başlangıç pozisyonu
        self.is_panning = False  # Pan yapılıyor mu?
        # Question hit-testing / selection (on rendered PDF page)
        self._question_rects_pt: Dict[int, Tuple[float, float, float, float]] = {}  # {qnum: (x0,y0,x1,y1)} in pt
        self._render_scale: float = 4.0  # must match PDFPreviewDialog render_scale
        self._selected_question_number: Optional[int] = None
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        
        # Koyu mod arka plan
        self.setStyleSheet("background-color: #424242;")

    def set_status(self, text: str) -> None:
        self.status_text = text or ""
        self.update()

    def set_question_rects(self, rects_pt: Dict[int, Tuple[float, float, float, float]], *, render_scale: float) -> None:
        """Set question rectangles for current page, in page-point coordinates."""
        self._question_rects_pt = dict(rects_pt or {})
        try:
            self._render_scale = float(render_scale)
        except Exception:
            self._render_scale = 4.0
        self.update()

    def set_render_scale(self, render_scale: float) -> None:
        """Update render scale (pt -> px), keeping current rects."""
        try:
            self._render_scale = float(render_scale)
        except Exception:
            self._render_scale = 4.0
        self.update()

    def set_selected_question_number(self, qnum: Optional[int]) -> None:
        try:
            self._selected_question_number = (int(qnum) if qnum is not None else None)
        except Exception:
            self._selected_question_number = None
        self.update()

    def _hit_test_question(self, pos: QPoint) -> Optional[int]:
        """Return question number if click hits a question image area."""
        try:
            if not self.pdf_pixmap or self.pdf_pixmap.isNull():
                return None

            widget_w = self.width()
            widget_h = self.height()
            img_w = self.pdf_pixmap.width()
            img_h = self.pdf_pixmap.height()

            center_x = (widget_w - img_w) // 2
            center_y = (widget_h - img_h) // 2

            x = center_x + self.pan_offset.x()
            y = center_y + self.pan_offset.y()

            px = float(pos.x() - x)
            py = float(pos.y() - y)
            if px < 0 or py < 0 or px > img_w or py > img_h:
                return None

            # Convert displayed px -> original render px -> page pt
            z = float(self.zoom_factor) if float(self.zoom_factor) > 0 else 1.0
            base_px_x = px / z
            base_px_y = py / z
            rs = float(self._render_scale) if float(self._render_scale) > 0 else 4.0
            pt_x = base_px_x / rs
            pt_y = base_px_y / rs

            hit_num: Optional[int] = None
            hit_area: Optional[float] = None
            for qnum, (rx0, ry0, rx1, ry1) in (self._question_rects_pt or {}).items():
                if rx0 <= pt_x <= rx1 and ry0 <= pt_y <= ry1:
                    area = float((rx1 - rx0) * (ry1 - ry0))
                    if hit_area is None or area < hit_area:
                        hit_area = area
                        hit_num = int(qnum)
            return hit_num
        except Exception:
            return None
    
    def set_pdf_pixmap(self, pixmap: QPixmap, total_pages: int = 1, fit_to_window: bool = False, preserve_page: bool = False):
        """PDF görselini ayarla
        
        Args:
            pixmap: PDF sayfasının pixmap'i
            total_pages: Toplam sayfa sayısı
            fit_to_window: True ise pencereye sığdır (sadece ilk yüklemede veya zoom yapıldığında)
            preserve_page: True ise mevcut sayfayı koru (sadece içeriği güncelle)
        """
        self.original_pixmap = pixmap
        self.total_pages = total_pages
        
        # Sayfa korunuyorsa mevcut sayfayı koru, yoksa 0'a dön
        if not preserve_page:
            self.current_page = 0
            self.pan_offset = QPoint(0, 0)  # Pan offset'i sıfırla
        
        if pixmap:
            # Sadece fit_to_window True ise pencereye sığdır (zoom yapılmadıysa)
            if fit_to_window:
                self._fit_to_window()
            else:
                # Sadece zoom'u uygula (mevcut zoom_factor'ü koru)
                self._apply_zoom()
        else:
            self.pdf_pixmap = None

        # Sayfa değiştiğinde/ilk yüklemede PDF'in üst kısmını göster
        if not preserve_page:
            self._scroll_to_top()
        self.update()

    def _scroll_to_top(self) -> None:
        """Pan offset'i ayarla: PDF'in üst kısmı görünsün."""
        try:
            if not self.pdf_pixmap or self.pdf_pixmap.isNull():
                return
            img_h = self.pdf_pixmap.height()
            widget_h = self.height()
            if img_h <= 0 or widget_h <= 0:
                return
            if img_h > widget_h:
                # Pozitif y offset: görseli aşağı kaydır -> üst kısmı görünür
                max_offset_y = (img_h - widget_h) // 2
                self.pan_offset = QPoint(self.pan_offset.x(), int(max_offset_y))
            else:
                self.pan_offset = QPoint(self.pan_offset.x(), 0)
        except Exception:
            pass
    
    def _fit_to_window(self):
        """PDF'i pencereye sığdır"""
        if not self.original_pixmap or self.original_pixmap.isNull():
            return
        
        # Parent widget'ın boyutunu al (QScrollArea)
        parent = self.parent()
        scroll_area = None
        while parent:
            if isinstance(parent, QScrollArea):
                scroll_area = parent
                break
            parent = parent.parent()
        
        if scroll_area:
            available_w = scroll_area.viewport().width() - 40
            available_h = scroll_area.viewport().height() - 40
        else:
            # Fallback: widget'ın kendi boyutu
            available_w = self.width() - 40
            available_h = self.height() - 40
        
        if available_w <= 0 or available_h <= 0:
            self.zoom_factor = 1.0
            self._apply_zoom()
            return
        
        img_w = self.original_pixmap.width()
        img_h = self.original_pixmap.height()
        
        if img_w <= 0 or img_h <= 0:
            self.zoom_factor = 1.0
            self._apply_zoom()
            return
        
        # Aspect ratio'yu koruyarak sayfayı pencereye TAM sığdır
        scale_w = available_w / img_w
        scale_h = available_h / img_h
        # Pencere sayfadan büyükse büyütmeye de izin ver (kullanıcı "tam sığdır" istiyor)
        base_scale = min(scale_w, scale_h)
        self.zoom_factor = base_scale
        
        # Zoom'u uygula
        self._apply_zoom()
    
    def _apply_zoom(self):
        """Zoom faktörünü uygula"""
        if not self.original_pixmap or self.original_pixmap.isNull():
            return
        
        img_w = self.original_pixmap.width()
        img_h = self.original_pixmap.height()
        
        new_w = int(img_w * self.zoom_factor)
        new_h = int(img_h * self.zoom_factor)
        
        self.pdf_pixmap = self.original_pixmap.scaled(
            new_w, new_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.update()
    
    def zoom_in(self):
        """Yakınlaştır"""
        old_zoom = self.zoom_factor
        self.zoom_factor = min(self.zoom_factor * 1.2, 3.0)  # Maksimum 3x
        # Zoom değiştiğinde pan offset'i koru (görsel merkezde kalır)
        if old_zoom > 0:
            zoom_ratio = self.zoom_factor / old_zoom
            self.pan_offset = QPoint(
                int(self.pan_offset.x() * zoom_ratio),
                int(self.pan_offset.y() * zoom_ratio)
            )
        self._apply_zoom()
    
    def zoom_out(self):
        """Uzaklaştır"""
        old_zoom = self.zoom_factor
        self.zoom_factor = max(self.zoom_factor / 1.2, 0.3)  # Minimum 0.3x
        # Zoom değiştiğinde pan offset'i koru
        if old_zoom > 0:
            zoom_ratio = self.zoom_factor / old_zoom
            self.pan_offset = QPoint(
                int(self.pan_offset.x() * zoom_ratio),
                int(self.pan_offset.y() * zoom_ratio)
            )
        # Eğer zoom 1.0 veya daha küçükse pan offset'i sıfırla
        if self.zoom_factor <= 1.0:
            self.pan_offset = QPoint(0, 0)
        self._apply_zoom()
    
    def zoom_fit(self):
        """Pencereye sığdır"""
        self.pan_offset = QPoint(0, 0)  # Pan offset'i sıfırla
        self._fit_to_window()

    def focus_question(self, qnum: int) -> None:
        """Seçilen sorunun bulunduğu bölgeyi ekranda görünür yap.

        - Zoom'u değiştirmez (zoom_factor korunur)
        - Pan offset'i ayarlayarak soruyu merkeze yaklaştırır
        """
        try:
            if qnum is None:
                return
            rect_pt = (self._question_rects_pt or {}).get(int(qnum))
            if not rect_pt:
                return
            if not self.pdf_pixmap or self.pdf_pixmap.isNull():
                return

            rx0, ry0, rx1, ry1 = rect_pt
            # rect center in displayed-pixmap coordinates
            rs = float(self._render_scale) if float(self._render_scale) > 0 else 4.0
            z = float(self.zoom_factor) if float(self.zoom_factor) > 0 else 1.0
            cx = ((float(rx0) + float(rx1)) / 2.0) * rs * z
            cy = ((float(ry0) + float(ry1)) / 2.0) * rs * z

            widget_w = max(1, int(self.width()))
            widget_h = max(1, int(self.height()))
            img_w = int(self.pdf_pixmap.width())
            img_h = int(self.pdf_pixmap.height())
            if img_w <= 0 or img_h <= 0:
                return

            # draw origin for image
            center_x = (widget_w - img_w) // 2
            center_y = (widget_h - img_h) // 2

            # We want: (center_x + pan_x + cx) ~= widget_w/2  => pan_x ~= img_w/2 - cx
            target_pan_x = (img_w / 2.0) - float(cx)
            target_pan_y = (img_h / 2.0) - float(cy)

            self.pan_offset = QPoint(int(target_pan_x), int(target_pan_y))
            self.update()
        except Exception:
            return
    
    def mousePressEvent(self, e):
        """Mouse basıldığında - Pan başlat"""
        if e.button() == Qt.LeftButton:
            # If user clicked on a question area, select it and sync left panel
            hit = self._hit_test_question(e.pos())
            if hit is not None:
                self.set_selected_question_number(int(hit))
                try:
                    dlg = self.window()
                    if dlg and hasattr(dlg, "question_list_widget") and dlg.question_list_widget:
                        dlg.question_list_widget.last_modified_question = int(hit)
                        dlg.question_list_widget._on_question_clicked(int(hit))
                except Exception:
                    pass
            # Zoom yapılmışsa pan yapılabilir, yoksa normal davranış
            if self.zoom_factor > 1.0:
                self.is_panning = True
                self.pan_start_pos = e.pos()
                self.setCursor(QCursor(Qt.ClosedHandCursor))
            else:
                # Zoom yapılmamışsa da pan yapılabilir (zoom 1.0 olsa bile)
                self.is_panning = True
                self.pan_start_pos = e.pos()
                self.setCursor(QCursor(Qt.ClosedHandCursor))
    
    def mouseMoveEvent(self, e):
        """Mouse hareket ettiğinde - Pan yap"""
        if self.is_panning and self.pan_start_pos:
            delta = e.pos() - self.pan_start_pos
            self.pan_offset += delta
            self.pan_start_pos = e.pos()
            self.update()
        else:
            # Her zaman pan yapılabilir (zoom fark etmez)
            self.setCursor(QCursor(Qt.OpenHandCursor))
    
    def mouseReleaseEvent(self, e):
        """Mouse bırakıldığında - Pan bitir"""
        if e.button() == Qt.LeftButton:
            self.is_panning = False
            self.pan_start_pos = None
            if self.zoom_factor > 1.0:
                self.setCursor(QCursor(Qt.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
    
    def wheelEvent(self, e):
        """Mouse tekerleği ile zoom in/out"""
        # Tekerlek ile zoom (Ctrl gerekmez, direkt zoom)
        delta = e.angleDelta().y()
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        e.accept()  # Event'i kabul et, parent'a iletme
    
    def paintEvent(self, e):
        """PDF görselini çiz"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        if not self.pdf_pixmap or self.pdf_pixmap.isNull():
            # Tema uyumlu metin rengi
            palette = self.palette()
            is_dark = palette.color(QPalette.Window).lightness() < 128
            text_color = QColor(200, 200, 200) if is_dark else QColor(100, 100, 100)
            painter.setPen(text_color)
            painter.setFont(QFont("Arial", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, self.status_text or "PDF önizlemesi hazırlanıyor...")
            return
        
        # Görseli çiz (pan offset ile)
        widget_w = self.width()
        widget_h = self.height()
        img_w = self.pdf_pixmap.width()
        img_h = self.pdf_pixmap.height()
        
        # Merkez pozisyonu
        center_x = (widget_w - img_w) // 2
        center_y = (widget_h - img_h) // 2
        
        # Pan offset'i ekle (sadece zoom > 1.0 ise)
        if self.zoom_factor > 1.0:
            x = center_x + self.pan_offset.x()
            y = center_y + self.pan_offset.y()
            
            # Sınırları kontrol et (görsel widget dışına taşmasın)
            max_offset_x = (img_w - widget_w) // 2 if img_w > widget_w else 0
            max_offset_y = (img_h - widget_h) // 2 if img_h > widget_h else 0
            
            if abs(self.pan_offset.x()) > max_offset_x:
                self.pan_offset.setX(max_offset_x if self.pan_offset.x() > 0 else -max_offset_x)
            if abs(self.pan_offset.y()) > max_offset_y:
                self.pan_offset.setY(max_offset_y if self.pan_offset.y() > 0 else -max_offset_y)
            
            x = center_x + self.pan_offset.x()
            y = center_y + self.pan_offset.y()
        else:
            # Zoom 1.0 veya daha küçükse de pan yapılabilir (görseli hareket ettirmek için)
            # Ama sınırları kontrol et - negatif y değerleri için de çalışmalı (üst kısmı göstermek için)
            max_offset_x = (img_w - widget_w) // 2 if img_w > widget_w else 0
            max_offset_y = (img_h - widget_h) // 2 if img_h > widget_h else 0
            
            if abs(self.pan_offset.x()) > max_offset_x:
                self.pan_offset.setX(max_offset_x if self.pan_offset.x() > 0 else -max_offset_x)
            # Pozitif ve negatif y değerleri için sınır kontrolü (üst kısmı göstermek için pozitif kullanılıyor)
            if self.pan_offset.y() > max_offset_y:
                self.pan_offset.setY(max_offset_y)
            elif self.pan_offset.y() < -max_offset_y:
                self.pan_offset.setY(-max_offset_y)
            
            x = center_x + self.pan_offset.x()
            y = center_y + self.pan_offset.y()
        
        painter.drawPixmap(x, y, self.pdf_pixmap)

        # Selected question highlight (red dashed rectangle)
        if self._selected_question_number is not None:
            rect_pt = (self._question_rects_pt or {}).get(int(self._selected_question_number))
            if rect_pt:
                rx0, ry0, rx1, ry1 = rect_pt
                rs = float(self._render_scale) if float(self._render_scale) > 0 else 4.0
                z = float(self.zoom_factor) if float(self.zoom_factor) > 0 else 1.0
                px0 = (float(rx0) * rs) * z
                py0 = (float(ry0) * rs) * z
                px1 = (float(rx1) * rs) * z
                py1 = (float(ry1) * rs) * z
                r = QRect(int(x + px0), int(y + py0), int(px1 - px0), int(py1 - py0))
                pen = QPen(QColor(255, 0, 0), 2, Qt.SolidLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(r.adjusted(-1, -1, 1, 1))
        
        # Sayfa bilgisi - Tema uyumlu
        if self.total_pages > 1:
            page_info = f"Sayfa {self.current_page + 1} / {self.total_pages}"
            painter.setFont(QFont("Arial", 12, QFont.Bold))
            palette = self.palette()
            is_dark = palette.color(QPalette.Window).lightness() < 128
            text_color = QColor(200, 200, 200) if is_dark else QColor(100, 100, 100)
            painter.setPen(text_color)
            painter.drawText(10, 20, page_info)


class NoWheelSlider(QSlider):
    """Mouse tekerleği ile hareket etmeyen slider"""
    
    def wheelEvent(self, e):
        """Tekerlek event'ini ignore et - sadece scrollbar'da kullanılsın"""
        e.ignore()


class NoWheelSpinBox(QSpinBox):
    """Mouse tekerleği ile hareket etmeyen spinbox"""
    
    def wheelEvent(self, e):
        """Tekerlek event'ini ignore et - sadece scrollbar'da kullanılsın"""
        e.ignore()


class DraggableQuestionItem(QWidget):
    """Sürükle-bırak yapılabilen soru öğesi - Karanlık/Aydınlık mod uyumlu"""
    
    def __init__(self, parent=None, selection=None, dialog=None):
        super().__init__(parent)
        self.selection = selection
        self.dialog = dialog
        self._drag_start_pos = None
        self.setAcceptDrops(True)
        # Minimum yükseklik - tüm içerikler sığsın (başlık + 2x label + 2x slider + 2x spinbox + yerleştirme kontrolleri + spacing'ler)
        # Hesaplama: Başlık(32) + Boşluk label(20) + Boşluk slider(22) + Boşluk spinbox(28) + 
        #            Boyut label(20) + Boyut slider(22) + Boyut spinbox(28) + 
        #            Yerleştirme label(20) + 2x checkbox row(28*2=56) + Uygula butonu(32) +
        #            spacing'ler(4*10=40) + padding'ler(8*2=16) = ~320px
        self.setMinimumHeight(500)  # Yükseklik artırıldı - iç scroll olmasın
        # Maximum yok - içeriğe göre büyüyebilir
        
        # Debounce timer'lar (çok hızlı tepki için - 5ms)
        self.gap_update_timer = QTimer()
        self.gap_update_timer.setSingleShot(True)
        self.gap_update_timer.timeout.connect(self._update_gap_preview)
        
        self.size_update_timer = QTimer()
        self.size_update_timer.setSingleShot(True)
        self.size_update_timer.timeout.connect(self._update_size_preview)
        
        # Her zaman koyu mod
        is_dark = True
        
        # Dış border kaldırıldı - sadece gruplar border alacak (modern tasarım)
        self.setStyleSheet("")  # Dış border yok
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)  # Daha fazla padding - okunabilirlik
        layout.setSpacing(12)  # Gruplar arası daha fazla boşluk
        
        # Soru numarası (daha büyük ve belirgin) - Sabit renk - tema değişikliğinden etkilenmez
        num_label = QLabel(f"{selection.number}. SORU")
        num_label.setMinimumHeight(32)
        num_label.setMaximumHeight(32)
        num_label.setStyleSheet("""
            font-size: 14px; 
            font-weight: bold; 
            color: #90CAF9;
            padding: 6px;
            background-color: #1E3A5F;
            border: none;
            border-radius: 6px;
        """)
        num_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(num_label)
        
        # ========== GRUP 1: BOŞLUK ==========
        # Grup container - soru yerleştir bölümü ile aynı arka plan
        gap_group_container = QWidget()
        # Sabit renk - tema değişikliğinden etkilenmez
        border_color = "#616161"
        gap_group_container.setStyleSheet(f"""
            QWidget {{
                background-color: {border_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        
        gap_group_layout = QVBoxLayout(gap_group_container)
        gap_group_layout.setContentsMargins(12, 16, 12, 12)  # Üst padding artırıldı - label kesilmesin
        gap_group_layout.setSpacing(8)
        
        # Grup başlığı - Yeterli yükseklik ve padding ile okunabilir
        gap_label = QLabel("Boşluk")
        gap_label.setMinimumHeight(32)  # Yükseklik artırıldı - alt çizgi için
        gap_label.setMaximumHeight(32)
        # Sabit renk - tema değişikliğinden etkilenmez
        gap_label.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        gap_group_layout.addWidget(gap_label)
        
        # Boşluk kontrolü - Yatay layout (Slider ve SpinBox yan yana)
        gap_control_layout = QHBoxLayout()
        gap_control_layout.setSpacing(10)  # Slider ve spinbox arası boşluk
        gap_control_layout.setContentsMargins(0, 0, 0, 0)  # Dışarıdan margin için
        
        # Slider - Tema uyumlu (tekerlek ile hareket etmez)
        gap_slider = NoWheelSlider(Qt.Horizontal)
        gap_slider.setMinimum(6)
        gap_slider.setMaximum(100)
        gap_slider.setSingleStep(1)
        gap_slider.setPageStep(5)
        gap_slider.setMinimumHeight(22)  # Daha küçük - sığsın
        gap_slider.setMaximumHeight(22)
        # Sabit renk - tema değişikliğinden etkilenmez
        gap_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #4A4A4A;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #90CAF9;
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background-color: #BBDEFB;
            }
        """)
        
        # SpinBox (elle girilebilir) - Tema uyumlu - Tam genişlik (tekerlek ile hareket etmez)
        # Spinbox'ı container widget içine al (margin için)
        gap_spinbox_container = QWidget()
        gap_spinbox_container_layout = QHBoxLayout(gap_spinbox_container)
        gap_spinbox_container_layout.setContentsMargins(0, 0, 0, 0)  # Margin kaldırıldı - spinbox tam genişlik
        gap_spinbox_container_layout.setSpacing(0)
        
        gap_spinbox = NoWheelSpinBox()
        gap_spinbox.setMinimum(6)
        gap_spinbox.setMaximum(100)
        gap_spinbox.setSuffix(" mm")
        gap_spinbox.setMinimumHeight(28)  # Biraz büyütüldü - içerik sığsın
        gap_spinbox.setMaximumHeight(28)
        gap_spinbox.setMinimumWidth(48)  # Minimum genişlik %60'a düşürüldü (80 * 0.6 = 48)
        # SpinBox her zaman beyaz arka plan, siyah yazı
        gap_spinbox.setStyleSheet("""
            QSpinBox {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QSpinBox:focus {
                border: none;
                background-color: #FAFAFA;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #000000;
                border: none;
                color: #000000;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #333333;
            }
            QSpinBox::up-arrow, QSpinBox::down-arrow {
                width: 8px;
                height: 8px;
            }
            QSpinBox::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 6px solid #000000;
            }
            QSpinBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #000000;
            }
        """)
        
        gap_spinbox_container_layout.addWidget(gap_spinbox)
        
        # Mevcut değeri ayarla
        from testmaker.services.pdf_exporter import mm_to_pt
        current_gap_pt = getattr(selection, 'custom_gap_after_pt', None)
        if current_gap_pt is None:
            if dialog and hasattr(dialog, 'export_options'):
                default_gap_pt = dialog.export_options.question_gap_pt()
            else:
                default_gap_pt = mm_to_pt(6.0)
            current_gap_mm = pt_to_mm(default_gap_pt)
        else:
            current_gap_mm = pt_to_mm(current_gap_pt)
        
        gap_slider.setValue(int(current_gap_mm))
        gap_spinbox.setValue(int(current_gap_mm))
        
        # Bağlantılar - Sadece değeri güncelle, preview'ı güncelleme (Uygula butonuna basılınca güncellenecek)
        def on_gap_slider_changed(value):
            gap_spinbox.blockSignals(True)
            gap_spinbox.setValue(value)
            gap_spinbox.blockSignals(False)
            selection.custom_gap_after_pt = mm_to_pt(float(value))
            # En son işlem yapılan soruyu işaretle (sadece o aktif kalacak)
            if dialog and hasattr(dialog, 'question_list_widget'):
                for btn_num, btn in dialog.question_list_widget.question_buttons.items():
                    btn.setChecked(False)
                dialog.question_list_widget.last_modified_question = selection.number
                if selection.number in dialog.question_list_widget.question_buttons:
                    dialog.question_list_widget.question_buttons[selection.number].setChecked(True)

        def on_gap_spinbox_changed(value):
            gap_slider.blockSignals(True)
            gap_slider.setValue(value)
            gap_slider.blockSignals(False)
            selection.custom_gap_after_pt = mm_to_pt(float(value))
            # En son işlem yapılan soruyu işaretle (sadece o aktif kalacak)
            if dialog and hasattr(dialog, 'question_list_widget'):
                for btn_num, btn in dialog.question_list_widget.question_buttons.items():
                    btn.setChecked(False)
                dialog.question_list_widget.last_modified_question = selection.number
                if selection.number in dialog.question_list_widget.question_buttons:
                    dialog.question_list_widget.question_buttons[selection.number].setChecked(True)

        gap_slider.valueChanged.connect(on_gap_slider_changed)
        gap_spinbox.valueChanged.connect(on_gap_spinbox_changed)

        # Uygula butonu - Boşluk değişikliğini preview'a uygula
        def _on_gap_apply():
            try:
                if self._gap_dialog:
                    self._gap_dialog._update_pdf_preview(
                        question_number=None,
                        preserve_current_page=True,
                        render_scale=3.0,
                        build_hit_test=True,
                        show_status=False,
                    )
            except Exception:
                pass

        gap_apply_btn = QPushButton("Uygula")
        gap_apply_btn.setMinimumHeight(28)
        gap_apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        gap_apply_btn.clicked.connect(_on_gap_apply)

        # Uygula butonunu gap_control_layout'a ekle
        gap_control_layout.addWidget(gap_apply_btn, 0)

        # Preview güncelleme metodunu kaydet
        self._gap_selection = selection
        self._gap_dialog = dialog
        
        gap_control_layout.addWidget(gap_slider, 1)  # Slider genişleyebilir
        gap_control_layout.addWidget(gap_spinbox_container, 0)  # Spinbox sabit genişlik
        gap_group_layout.addLayout(gap_control_layout)
        
        # Grup 1'i ana layout'a ekle
        layout.addWidget(gap_group_container)
        
        # ========== GRUP 2: BOYUT ==========
        # Grup container - boşluk bölümü ile aynı arka plan
        size_group_container = QWidget()
        # Sabit renk - tema değişikliğinden etkilenmez
        border_color = "#616161"
        size_group_container.setStyleSheet(f"""
            QWidget {{
                background-color: {border_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        
        size_group_layout = QVBoxLayout(size_group_container)
        size_group_layout.setContentsMargins(12, 16, 12, 12)  # Üst padding artırıldı - label kesilmesin
        size_group_layout.setSpacing(8)
        
        # Grup başlığı - Yeterli yükseklik ve padding ile okunabilir
        size_label = QLabel("Boyut")
        size_label.setMinimumHeight(32)  # Yükseklik artırıldı - alt çizgi için
        size_label.setMaximumHeight(32)
        # Sabit renk - tema değişikliğinden etkilenmez
        size_label.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        size_group_layout.addWidget(size_label)
        
        # Boyut kontrolü - Slider ve SpinBox yan yana
        size_control_layout = QHBoxLayout()
        size_control_layout.setSpacing(10)  # Slider ve spinbox arası boşluk
        size_control_layout.setContentsMargins(0, 0, 0, 0)  # Dışarıdan margin için
        
        # Display scale slider (tekerlek ile hareket etmez)
        size_slider = NoWheelSlider(Qt.Horizontal)
        size_slider.setMinimum(0)  # %0
        size_slider.setMaximum(200)  # %200
        size_slider.setSingleStep(5)
        size_slider.setPageStep(10)
        size_slider.setMinimumHeight(22)  # Daha küçük - sığsın
        size_slider.setMaximumHeight(22)
        
        # Mevcut display_scale değerini ayarla
        raw_current_scale = getattr(selection, 'display_scale', None)
        current_scale = 1.0 if raw_current_scale is None else float(raw_current_scale)
        current_scale = max(0.0, min(2.0, current_scale))
        size_slider.setValue(int(current_scale * 100))
        
        # Display scale spinbox - Container widget içine al (margin için)
        size_spinbox_container = QWidget()
        size_spinbox_container_layout = QHBoxLayout(size_spinbox_container)
        size_spinbox_container_layout.setContentsMargins(0, 0, 0, 0)  # Margin kaldırıldı - spinbox tam genişlik
        size_spinbox_container_layout.setSpacing(0)
        
        size_spinbox = NoWheelSpinBox()
        size_spinbox.setMinimum(0)
        size_spinbox.setMaximum(200)
        size_spinbox.setSuffix(" %")
        size_spinbox.setMinimumHeight(28)  # Biraz büyütüldü - içerik sığsın
        size_spinbox.setMaximumHeight(28)
        size_spinbox.setMinimumWidth(48)  # Minimum genişlik %60'a düşürüldü (80 * 0.6 = 48)
        size_spinbox.setValue(int(current_scale * 100))
        
        size_spinbox_container_layout.addWidget(size_spinbox)
        
        # Sabit renk - tema değişikliğinden etkilenmez
        size_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #4A4A4A;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #90CAF9;
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background-color: #BBDEFB;
            }
        """)
        # SpinBox her zaman beyaz arka plan, siyah yazı
        size_spinbox.setStyleSheet("""
            QSpinBox {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QSpinBox:focus {
                border: none;
                background-color: #FAFAFA;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #000000;
                border: none;
                color: #000000;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #333333;
            }
            QSpinBox::up-arrow, QSpinBox::down-arrow {
                width: 8px;
                height: 8px;
            }
            QSpinBox::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 6px solid #000000;
            }
            QSpinBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #000000;
            }
        """)
        
        # Bağlantılar - Sadece değeri güncelle, preview'ı güncelleme
        def on_size_slider_changed(value):
            size_spinbox.blockSignals(True)
            size_spinbox.setValue(value)
            size_spinbox.blockSignals(False)
            # Sadece değeri güncelle, preview'ı güncelleme (Uygula butonuna basılınca güncellenecek)
            selection.display_scale = float(value) / 100.0
        
        def on_size_spinbox_changed(value):
            size_slider.blockSignals(True)
            size_slider.setValue(value)
            size_slider.blockSignals(False)
            # Sadece değeri güncelle, preview'ı güncelleme (Uygula butonuna basılınca güncellenecek)
            selection.display_scale = float(value) / 100.0
        
        size_slider.valueChanged.connect(on_size_slider_changed)
        size_spinbox.valueChanged.connect(on_size_spinbox_changed)

        # Uygula butonu - Boyut değişikliğini preview'a uygula
        def _on_size_apply():
            try:
                if self._size_dialog:
                    self._size_dialog._update_pdf_preview(
                        question_number=None,
                        preserve_current_page=True,
                        render_scale=3.0,
                        build_hit_test=True,
                        show_status=False,
                    )
            except Exception:
                pass
        
        size_apply_btn = QPushButton("Uygula")
        size_apply_btn.setMinimumHeight(28)
        size_apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 12px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
        """)
        size_apply_btn.clicked.connect(_on_size_apply)
        
        # Uygula butonunu size_control_layout'a ekle
        size_control_layout.addWidget(size_apply_btn, 0)
        
        # Preview güncelleme metodunu kaydet
        self._size_selection = selection
        self._size_dialog = dialog
        
        size_control_layout.addWidget(size_slider, 1)  # Slider genişleyebilir
        size_control_layout.addWidget(size_spinbox_container, 0)  # Spinbox sabit genişlik
        size_group_layout.addLayout(size_control_layout)
        
        # Grup 2'yi ana layout'a ekle
        layout.addWidget(size_group_container)
        
        # ========== GRUP 3: SORU YERLEŞTİR ==========
        # Grup container - boşluk bölümü ile aynı arka plan
        placement_group_container = QWidget()
        # Sabit renk - tema değişikliğinden etkilenmez
        border_color = "#616161"
        placement_group_container.setStyleSheet(f"""
            QWidget {{
                background-color: {border_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        
        placement_group_layout = QVBoxLayout(placement_group_container)
        placement_group_layout.setContentsMargins(12, 16, 12, 12)  # Üst padding artırıldı - label kesilmesin
        placement_group_layout.setSpacing(10)
        
        # Grup başlığı - Yeterli yükseklik ve padding ile okunabilir
        placement_label = QLabel("Soru Yerleştir")
        placement_label.setMinimumHeight(32)  # Yükseklik artırıldı - alt çizgi için
        placement_label.setMaximumHeight(32)
        # Boşluk ve Boyut başlıkları ile aynı stil - mavi renk, altı çizili
        placement_label.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        placement_group_layout.addWidget(placement_label)
        
        # 1. satır: Yer değiştir - Checkbox, Input, Label yan yana
        replace_row = QHBoxLayout()
        replace_row.setSpacing(5)  # 5px boşluk
        
        self.replace_checkbox = QCheckBox()
        self.replace_checkbox.setMaximumHeight(25)
        # Checkbox her zaman beyaz arka plan, siyah yazı
        self.replace_checkbox.setStyleSheet("""
            font-size: 10px;
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #CCCCCC;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border: 1px solid #2196F3;
            }
        """)
        
        replace_label = QLabel("sorusu ile yer değiştir")
        replace_label.setMinimumHeight(28)  # Minimum yükseklik - text görünsün
        replace_label.setMaximumHeight(28)
        # Sabit renk - tema değişikliğinden etkilenmez
        replace_label.setStyleSheet("""
            font-size: 13px; 
            color: #E0E0E0;
            padding: 4px 0px;
        """)
        
        self.replace_input = QLineEdit()
        # Placeholder kaldırıldı
        self.replace_input.setMinimumHeight(26)  # Daha kompakt
        self.replace_input.setMaximumHeight(26)
        self.replace_input.setEnabled(False)  # Başlangıçta pasif
        # Input her zaman beyaz arka plan, siyah yazı
        self.replace_input.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QLineEdit:focus {
                border: none;
                background-color: #FAFAFA;
            }
            QLineEdit:disabled {
                background-color: #F5F5F5;
                border: none;
                color: #999999;
            }
        """)
        
        replace_row.addWidget(self.replace_checkbox, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        replace_row.addWidget(self.replace_input, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        replace_row.addWidget(replace_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        replace_row.setAlignment(Qt.AlignLeft)  # Tüm satırı sola yasla
        self.replace_input.setFixedWidth(30)  # 2 rakam sığacak kadar küçük (30px)
        self.replace_input.setFixedHeight(26)  # Kompakt yükseklik
        placement_group_layout.addLayout(replace_row)
        # Satırlar arası boşluk
        placement_group_layout.addSpacing(8)
        
        # 2. satır: Altına ekle - Checkbox, Input, Label yan yana
        insert_row = QHBoxLayout()
        insert_row.setSpacing(5)  # 5px boşluk
        
        self.insert_checkbox = QCheckBox()
        self.insert_checkbox.setMaximumHeight(25)
        # Checkbox her zaman beyaz arka plan, siyah yazı
        self.insert_checkbox.setStyleSheet("""
            font-size: 10px;
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #CCCCCC;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border: 1px solid #2196F3;
            }
        """)
        
        insert_label = QLabel("sorusunun altına ekle")
        insert_label.setMinimumHeight(28)  # Minimum yükseklik - text görünsün
        insert_label.setMaximumHeight(28)
        # Sabit renk - tema değişikliğinden etkilenmez
        insert_label.setStyleSheet("""
            font-size: 13px; 
            color: #E0E0E0;
            padding: 4px 0px;
        """)
        
        self.insert_input = QLineEdit()
        # Placeholder kaldırıldı
        self.insert_input.setMinimumHeight(26)  # Daha kompakt
        self.insert_input.setMaximumHeight(26)
        self.insert_input.setEnabled(False)  # Başlangıçta pasif
        # Input her zaman beyaz arka plan, siyah yazı
        self.insert_input.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QLineEdit:focus {
                border: none;
                background-color: #FAFAFA;
            }
            QLineEdit:disabled {
                background-color: #F5F5F5;
                border: none;
                color: #999999;
            }
        """)
        
        insert_row.addWidget(self.insert_checkbox, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        insert_row.addWidget(self.insert_input, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        insert_row.addWidget(insert_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        insert_row.setAlignment(Qt.AlignLeft)  # Tüm satırı sola yasla
        self.insert_input.setFixedWidth(30)  # 2 rakam sığacak kadar küçük (30px)
        self.insert_input.setFixedHeight(26)  # Kompakt yükseklik
        placement_group_layout.addLayout(insert_row)
        # Satırlar arası boşluk
        placement_group_layout.addSpacing(12)
        
        # Uygula butonu - Grup 3 içinde
        self.apply_button = QPushButton("Uygula")
        self.apply_button.setMinimumHeight(32)
        self.apply_button.setEnabled(False)  # Başlangıçta pasif
        # Sabit renk - tema değişikliğinden etkilenmez
        self.apply_button.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                font-weight: bold;
                color: #E0E0E0;
                background-color: #424242;
                border: none;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover:enabled {
                background-color: #515151;
                border: none;
            }
            QPushButton:enabled {
                background-color: #1E3A5F;
                border: none;
                color: #90CAF9;
            }
            QPushButton:disabled {
                background-color: #2B2B2B;
                border: none;
                color: #616161;
            }
        """)
        
        placement_group_layout.addWidget(self.apply_button)
        
        # Grup 3'ü ana layout'a ekle
        layout.addWidget(placement_group_container)

        # Checkbox'lar birbirini dışlayacak ve input enable/disable mantığı
        def on_replace_checkbox_changed(state):
            if state == Qt.Checked:
                self.insert_checkbox.setChecked(False)
                # Sadece 1. satır input aktif
                self.replace_input.setEnabled(True)
                self.insert_input.setEnabled(False)
            else:
                # Checkbox işaretli değilse input pasif
                self.replace_input.setEnabled(False)
            self._update_apply_button_state()
        
        def on_insert_checkbox_changed(state):
            if state == Qt.Checked:
                self.replace_checkbox.setChecked(False)
                # Sadece 2. satır input aktif
                self.insert_input.setEnabled(True)
                self.replace_input.setEnabled(False)
            else:
                # Checkbox işaretli değilse input pasif
                self.insert_input.setEnabled(False)
            self._update_apply_button_state()
        
        self.replace_checkbox.stateChanged.connect(on_replace_checkbox_changed)
        self.insert_checkbox.stateChanged.connect(on_insert_checkbox_changed)
        
        # Uygula butonu tıklama
        self.apply_button.clicked.connect(self._on_apply_placement)
    
    def mousePressEvent(self, e):
        """Mouse basıldığında - Sürükle bırak iptal edildi"""
        pass  # Sürükle bırak özelliği iptal edildi
    
    def mouseMoveEvent(self, e):
        """Mouse hareket ettiğinde - Sürükle bırak iptal edildi"""
        pass  # Sürükle bırak özelliği iptal edildi
    
    def dragEnterEvent(self, e):
        """Drag başladığında"""
        if e.mimeData().hasText():
            e.accept()
        else:
            e.ignore()
    
    def dropEvent(self, e):
        """Drop yapıldığında"""
        if e.mimeData().hasText():
            dragged_number = int(e.mimeData().text())
            if dragged_number != self.selection.number and self.dialog:
                # Soruları yeniden sırala
                self.dialog._reorder_questions(dragged_number, self.selection.number)
            e.accept()
        else:
            e.ignore()
    
    def _update_gap_preview(self):
        """Boşluk değişikliğini preview'a uygula - Çok hızlı tepki"""
        if self._gap_dialog and self._gap_selection:
            # preserve_current_page=True - mevcut sayfada kal, sadece içeriği güncelle
            # B modu: sürüklerken düşük kalite render (hızlı)
            self._gap_dialog._update_pdf_preview(
                question_number=None,
                preserve_current_page=True,
                render_scale=1.6,
                build_hit_test=False,
                show_status=False,
            )
    
    def _update_size_preview(self):
        """Boyut değişikliğini preview'a uygula - Çok hızlı tepki"""
        if self._size_dialog and self._size_selection:
            # preserve_current_page=True - mevcut sayfada kal, sadece içeriği güncelle
            # B modu: sürüklerken düşük kalite render (hızlı)
            self._size_dialog._update_pdf_preview(
                question_number=None,
                preserve_current_page=True,
                render_scale=1.6,
                build_hit_test=False,
                show_status=False,
            )
    
    def _update_apply_button_state(self):
        """Uygula butonunun durumunu güncelle"""
        # En az bir checkbox seçili olmalı
        has_selection = self.replace_checkbox.isChecked() or self.insert_checkbox.isChecked()
        self.apply_button.setEnabled(has_selection)
    
    def _on_apply_placement(self):
        """Uygula butonuna tıklandığında"""
        if not self.dialog or not self.selection:
            return
        
        try:
            if self.replace_checkbox.isChecked():
                # Yer değiştir
                target_number_str = self.replace_input.text().strip()
                if not target_number_str:
                    QMessageBox.warning(self, "Uyarı", "Lütfen bir soru numarası girin.")
                    return
                
                try:
                    target_number = int(target_number_str)
                except ValueError:
                    QMessageBox.warning(self, "Uyarı", "Geçerli bir soru numarası girin.")
                    return
                
                # Mevcut soru ile hedef sorunun yerini değiştir
                self.dialog._swap_questions(self.selection.number, target_number)
                # En son işlem yapılan soruyu işaretle (sadece o aktif kalacak)
                if self.dialog and hasattr(self.dialog, 'question_list_widget'):
                    # Tüm butonları pasif yap
                    for btn_num, btn in self.dialog.question_list_widget.question_buttons.items():
                        btn.setChecked(False)
                    # Mevcut soruyu en son işlem yapılan olarak işaretle
                    self.dialog.question_list_widget.last_modified_question = self.selection.number
                    # Grid'de aktif yap (sadece bu soru)
                    if self.selection.number in self.dialog.question_list_widget.question_buttons:
                        self.dialog.question_list_widget.question_buttons[self.selection.number].setChecked(True)
                
            elif self.insert_checkbox.isChecked():
                # Altına ekle
                target_number_str = self.insert_input.text().strip()
                if not target_number_str:
                    QMessageBox.warning(self, "Uyarı", "Lütfen bir soru numarası girin.")
                    return
                
                try:
                    target_number = int(target_number_str)
                except ValueError:
                    QMessageBox.warning(self, "Uyarı", "Geçerli bir soru numarası girin.")
                    return
                
                # Hedef sorudan sonrasına mevcut soruyu ekle
                self.dialog._insert_question_after(self.selection.number, target_number)
                # En son işlem yapılan soruyu işaretle (sadece o aktif kalacak)
                if self.dialog and hasattr(self.dialog, 'question_list_widget'):
                    # Tüm butonları pasif yap
                    for btn_num, btn in self.dialog.question_list_widget.question_buttons.items():
                        btn.setChecked(False)
                    # Mevcut soruyu en son işlem yapılan olarak işaretle
                    self.dialog.question_list_widget.last_modified_question = self.selection.number
                    # Grid'de aktif yap (sadece bu soru)
                    if self.selection.number in self.dialog.question_list_widget.question_buttons:
                        self.dialog.question_list_widget.question_buttons[self.selection.number].setChecked(True)
            
            # Checkbox'ları sıfırla
            self.replace_checkbox.setChecked(False)
            self.insert_checkbox.setChecked(False)
            self.replace_input.clear()
            self.insert_input.clear()
            
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Soru yerleştirme sırasında hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")


class QuestionListWidget(QWidget):
    """Sol panel: Soru listesi ve boşluk ayarları - Modern tasarım - Karanlık/Aydınlık mod uyumlu"""
    
    # Grid widget sabit değerleri - tek bir yerde tanımlı
    GRID_COLUMNS = 10  # Sabit 10 sütun
    BUTTON_SIZE = 35  # Buton boyutu (px)
    GRID_SPACING = 8  # Satırlar arası boşluk (px)
    GRID_PADDING = 8  # Container padding (px) - üst/alt/sol/sağ
    ROW_HEIGHT = BUTTON_SIZE  # Satır yüksekliği = buton boyutu
    # Bu panelde scrollbar kullanılmayacak (yatay kayma olmasın)
    SCROLL_GUTTER = 0
    SIDE_PAD = 10  # sol/sağ padding aynı olsun
    
    def __init__(self, parent=None, dialog=None):
        super().__init__(parent)
        self.dialog = dialog
        self.selections: List[Selection] = []
        # En son işlem yapılan soruyu takip et (sadece o aktif kalacak)
        self.last_modified_question = None  # En son işlem yapılan soru numarası
        # Genişlik hesaplama - Grid'e göre minimum genişlik (overlap olmasın)
        grid_width = (self.GRID_COLUMNS * self.BUTTON_SIZE + 
                      (self.GRID_COLUMNS - 1) * self.GRID_SPACING + 
                      2 * self.GRID_PADDING)
        # Panel biraz daha geniş olsun (kayma olmasın)
        grid_width = int(grid_width) + 70
        # Sol panel minimum genişliği: grid + simetrik padding
        panel_min_width = int(grid_width) + (2 * int(self.SIDE_PAD)) + 10
        self.setMinimumWidth(panel_min_width)
        # Size policy: Minimum genişlik, Preferred yükseklik (içeriğe göre büyüyebilir)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        
        # Koyu renkte dikdörtgen içine al, köşeleri yuvarlatılmış - arka plandan ayırt edilebilir
        self.setStyleSheet("""
            QWidget {
                background-color: #4A4A4A;
                border: 2px solid #616161;
                border-radius: 12px;
            }
        """)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(int(self.SIDE_PAD), 12, int(self.SIDE_PAD), 12)
        self.main_layout.setSpacing(15)
        # Y ekseninde üste hizala - dağıtma yok
        self.main_layout.setAlignment(Qt.AlignTop)
        
        # Sol paneldeki widget'ları içine alan container - arka plan pencereden bir tık daha açık gri
        self.content_container = QWidget()
        self.content_container.setStyleSheet("""
            QWidget {
                background-color: #353535;
                border: none;
                border-radius: 12px;
            }
        """)
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(int(self.SIDE_PAD), 12, int(self.SIDE_PAD), 12)
        self.content_layout.setSpacing(15)
        self.content_layout.setAlignment(Qt.AlignTop)
        
        # Soru numaraları grid'i (10 sütun) - Genişlik hesaplama önce yapılmalı
        # Genişlik hesaplama: COLUMNS * BUTTON_SIZE + (COLUMNS-1) * SPACING + 2 * PADDING
        grid_width = (self.GRID_COLUMNS * self.BUTTON_SIZE + 
                      (self.GRID_COLUMNS - 1) * self.GRID_SPACING + 
                      2 * self.GRID_PADDING)
        grid_width = int(grid_width) + 70
        
        # Başlık - Modern header tasarımı (grid_width ile aynı genişlikte)
        title = QLabel("📋 Sorular ve Ayarlar")
        title.setFixedWidth(grid_width)  # Altındaki widget'lar ile aynı genişlik
        title.setMinimumHeight(40)  # Daha yüksek header
        title.setMaximumHeight(40)
        # Modern header - pastel, okunabilir
        title.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: #90CAF9;
            padding: 10px 16px;
            background-color: #1E3A5F;
            border: none;
            border-radius: 10px;
        """)
        title.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(title, alignment=Qt.AlignHCenter | Qt.AlignTop)  # Yatay ortalama, dikey üst

        # Bölüm ekle butonu (sağ panel popup)
        self.section_btn_open = QPushButton("BÖLÜM EKLE")
        self.section_btn_open.setFixedWidth(grid_width)
        self.section_btn_open.setMinimumHeight(34)
        self.section_btn_open.setDefault(False)  # ENTER tuşu ile tetiklenmesin
        self.section_btn_open.setAutoDefault(False)  # ENTER tuşu ile tetiklenmesin
        self.section_btn_open.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: #FFFFFF;
                border: 1px solid #FF9800;
                border-radius: 8px;
                padding: 8px 10px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #FFB74D;
                border: 1px solid #FFB74D;
                color: #FFFFFF;
            }
        """)
        # Varsayılan olarak en alta ekle; seçili soru detay kutusu eklenince altına taşınacak
        self.content_layout.addWidget(self.section_btn_open, alignment=Qt.AlignHCenter | Qt.AlignTop)
        
        self.question_grid_widget = QWidget()
        self.question_grid_widget.setFixedWidth(grid_width)  # Grid genişliği (10 sütun tam sığsın)
        # Yükseklik dinamik - içeriğe göre otomatik hesaplanacak (scroll bar yok)
        self.question_grid_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        
        # Her zaman koyu mod
        self.question_grid_widget.setStyleSheet("""
            QWidget {
                background-color: #424242;
                border: 2px solid #616161;
                border-radius: 8px;
            }
        """)
        
        self.question_grid_layout = QGridLayout(self.question_grid_widget)
        self.question_grid_layout.setSpacing(self.GRID_SPACING)  # Satırlar arası boşluk (8px)
        self.question_grid_layout.setContentsMargins(
            self.GRID_PADDING, self.GRID_PADDING, 
            self.GRID_PADDING, self.GRID_PADDING
        )  # Padding grid içinde (8px)
        # Grid içindeki kutuları sol-üstten hizala - overlap olmasın
        self.question_grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # Grid spacing ve margins düzgün - kutular üst üste binmez
        self.question_buttons = {}  # {question_number: QPushButton}
        self.content_layout.addWidget(self.question_grid_widget, alignment=Qt.AlignHCenter | Qt.AlignTop)  # Yatay ortalama, dikey üst
        
        # Seçili soru detayları (başlangıçta gizli)
        self.selected_question_widget = None
        self.selected_question_number = None
        
        # Soru detayları container (dikdörtgen içinde) - Grid widget ile aynı genişlik
        self.question_details_container = QWidget()
        # Grid widget ile aynı genişlik (grid_width - tüm widgetlar aynı genişlikte)
        self.question_details_container.setFixedWidth(grid_width)
        # Size policy: Fixed genişlik, Preferred yükseklik (içeriğe göre büyüyebilir ama expand etmesin)
        self.question_details_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        # Minimum yükseklik yok - sadece içeriğe göre (sizeHint kadar)
        # Maximum yükseklik yok - içeriğe göre büyüyebilir ama stretch olmasın
        # Her zaman koyu mod
        self.question_details_container.setStyleSheet("""
            QWidget {
                background-color: #424242;
                border: 2px solid #616161;
                border-radius: 8px;
            }
        """)
        
        self.question_details_layout = QVBoxLayout(self.question_details_container)
        self.question_details_layout.setContentsMargins(8, 8, 8, 8)  # Padding container içinde
        self.question_details_layout.setSpacing(8)
        
        # Scroll area KALDIRILDI - direkt widget'ları layout'a ekliyoruz
        # İç scroll olmasın, ana pencere scroll'u kullanılsın
        
        # Content container'ı ana layout'a ekle
        self.main_layout.addWidget(self.content_container, alignment=Qt.AlignHCenter | Qt.AlignTop)
        
        # Soru kontrolleri (dinamik olarak eklenecek)
        self.question_controls = {}  # {selection_number: DraggableQuestionItem}
    
    def set_selections(self, selections: List[Selection]):
        """Soruları ayarla ve kontrolleri oluştur"""
        self.selections = selections
        
        # Grid'i temizle
        while self.question_grid_layout.count():
            item = self.question_grid_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
        self.question_buttons.clear()
        
        # Soru numaraları grid'ini oluştur (10 sütun sabit)
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        
        for idx, sel in enumerate(selections):
            row = idx // self.GRID_COLUMNS  # 10 sütun sabit
            col = idx % self.GRID_COLUMNS
            
            # Soru numarası butonu (kare içinde)
            btn = QPushButton(str(sel.number))
            btn.setMinimumSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
            btn.setMaximumSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
            btn.setCheckable(True)  # Tıklanabilir, seçili durumu gösterir
            btn.clicked.connect(lambda checked, num=sel.number: self._on_question_clicked(num))
            
            # Sabit renk - tema değişikliğinden etkilenmez
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 12px;
                    font-weight: bold;
                    color: #E0E0E0;
                    background-color: #424242;
                    border: 2px solid #616161;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #515151;
                    border: 2px solid #64B5F6;
                }
                QPushButton:checked {
                    background-color: #FF6B35;
                    border: 2px solid #FF6B35;
                    color: #FFFFFF;
                }
            """)
            
            self.question_grid_layout.addWidget(btn, row, col, alignment=Qt.AlignLeft | Qt.AlignTop)
            self.question_buttons[sel.number] = btn
        
        # Grid widget'ın yüksekliğini satır sayısına göre dinamik olarak ayarla
        # Formül: container_height = (row_count * ROW_HEIGHT) + ((row_count - 1) * SPACING) + (2 * PADDING)
        # Scroll bar kullanılmayacak - yükseklik otomatik artmalı
        num_rows = (len(selections) + self.GRID_COLUMNS - 1) // self.GRID_COLUMNS  # Yukarı yuvarla
        
        if num_rows > 0:
            # Container yüksekliği = satır sayısı * satır yüksekliği + satırlar arası spacing + padding
            container_height = (num_rows * self.ROW_HEIGHT + 
                               (num_rows - 1) * self.GRID_SPACING + 
                               2 * self.GRID_PADDING)
            self.question_grid_widget.setFixedHeight(container_height)  # Sabit yükseklik (scroll bar yok)
        else:
            # Boş grid için minimum yükseklik
            self.question_grid_widget.setFixedHeight(2 * self.GRID_PADDING)
        
        # Eski kontrolleri tamamen temizle
        while self.question_details_layout.count():
            item = self.question_details_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                widget.deleteLater()
            elif item.spacerItem():
                self.question_details_layout.removeItem(item)
        
        self.question_controls.clear()
        
        # İlk soruyu varsayılan olarak seç
        if selections:
            self._on_question_clicked(selections[0].number)
        
        # En son işlem yapılan soruyu aktif yap (sadece o aktif kalacak)
        if self.last_modified_question and self.last_modified_question in self.question_buttons:
            self.question_buttons[self.last_modified_question].setChecked(True)
        
        # Alt stretch ekle (dikey ortalama için) - Container eklendikten sonra
        # Container _on_question_clicked'de eklenecek, sonra alt stretch eklenecek
    
    def _on_question_clicked(self, question_number: int):
        """Soru numarası butonuna tıklandığında"""
        # Önce tüm butonları pasif yap
        for btn in self.question_buttons.values():
            btn.setChecked(False)
        
        # Sadece tıklanan soruyu aktif yap (turuncu renkte görünecek)
        if question_number in self.question_buttons:
            self.question_buttons[question_number].setChecked(True)
        
        self.selected_question_number = question_number

        # Sağdaki PDF önizlemede bu sorunun bulunduğu sayfayı aç (internal sync çağrılarında kapatılabilir)
        if not getattr(self.dialog, "_suppress_question_nav", False):
            try:
                if self.dialog and hasattr(self.dialog, "_find_question_page") and hasattr(self.dialog, "_load_pdf_page"):
                    page_idx = int(self.dialog._find_question_page(int(question_number)))
                    self.dialog._load_pdf_page(page_idx)
                    if hasattr(self.dialog, "_update_page_info"):
                        self.dialog._update_page_info()
                    # Seçili soruyu sağda highlight et
                    try:
                        if hasattr(self.dialog, "pdf_render_widget") and self.dialog.pdf_render_widget:
                            self.dialog.pdf_render_widget.set_selected_question_number(int(question_number))
                            # Zoom'u değiştirmeden, sorunun bulunduğu bölgeye odaklan
                            self.dialog.pdf_render_widget.focus_question(int(question_number))
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Seçili soruyu bul
        selected_sel = None
        for sel in self.selections:
            if sel.number == question_number:
                selected_sel = sel
                break
        
        if not selected_sel:
            return

        # Sağ paneldeki "BÖLÜM BİLGİLERİ" panelini seçili soruya göre doldur
        try:
            if self.dialog and hasattr(self.dialog, "_sync_section_panel_for_selected_question"):
                self.dialog._sync_section_panel_for_selected_question()
        except Exception:
            pass
        
        # Eski detay widget'ını kaldır
        if self.selected_question_widget:
            self.question_details_layout.removeWidget(self.selected_question_widget)
            self.selected_question_widget.setParent(None)
            self.selected_question_widget.deleteLater()
        
        # Yeni detay widget'ını oluştur (DraggableQuestionItem kullan)
        self.selected_question_widget = DraggableQuestionItem(
            parent=self.question_details_container, 
            selection=selected_sel, 
            dialog=self.dialog
        )
        self.question_details_layout.addWidget(self.selected_question_widget)
        self.question_controls[selected_sel.number] = self.selected_question_widget
        
        # Container'ı content_layout'a ekle (scroll area yok) - Yatay ortalama
        # Stretch faktörü 0 - dikey expand etmesin
        if self.content_layout.indexOf(self.question_details_container) == -1:
            # Container'ı ekle - stretch=0 (expand etmesin), dikey üst hizalı
            self.content_layout.addWidget(self.question_details_container, alignment=Qt.AlignHCenter | Qt.AlignTop, stretch=0)

        # "BÖLÜM EKLE" butonu soru detay kutusunun altına gelsin
        try:
            if hasattr(self, "section_btn_open") and self.section_btn_open:
                self.content_layout.removeWidget(self.section_btn_open)
                self.content_layout.addWidget(self.section_btn_open, alignment=Qt.AlignHCenter | Qt.AlignTop)
        except Exception:
            pass


def pt_to_mm(pt: float) -> float:
    """Points'ten milimetreye dönüştür"""
    return float(pt) * 25.4 / 72.0


class PDFPreviewDialog(QDialog):
    """PDF ön izleme ve düzenleme dialog'u - YENİ TASARIM: Sol panel + PDF render"""
    
    def __init__(self, parent, selections: List[Selection], export_options: ExportOptions, pdf_docs: dict, render_dpi: float = 72.0):
        super().__init__(parent)
        self.setWindowTitle("PDF Ön İzleme ve Düzenleme")
        # Modal kalsın, ancak pencereyi gerçek bir Window olarak aç (Windows'ta tam ekran sorununu çözer)
        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)

        # Window flags: gerçek pencere (tam ekran/maximize için)
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowMinMaxButtonsHint |
            Qt.WindowCloseButtonHint
        )

        # ShowEvent'te maximize edeceğiz (init içinde maximize bazı Windows/Qt kombinasyonlarında boşa düşebiliyor)
        self._did_maximize = False
        
        self.selections = selections
        self.export_options = export_options
        self.pdf_docs = pdf_docs
        self.render_dpi = render_dpi  # PDF render DPI'si (standart 72 DPI)
        self.temp_pdf_path = None  # Geçici PDF dosyası yolu
        self._question_page_map: Dict[int, int] = {}  # {question_number: page_index}
        self._suppress_question_nav: bool = False
        self._suppress_page_goto: bool = False

        # Sections: store as fixed position ranges (so reordering questions won't move sections)
        self.section_ranges: List[SectionRange] = []
        try:
            num_to_idx = {int(getattr(s, "number", 0) or 0): i for i, s in enumerate(self.selections or [])}
            for i, s in enumerate(self.selections or []):
                try:
                    if not bool(getattr(s, "section_enabled", False)):
                        continue
                    title = (getattr(s, "section_title", "") or "").strip()
                    if not title:
                        continue
                    end_num = getattr(s, "section_end_number", None)
                    end_num = int(end_num) if end_num is not None else int(getattr(s, "number", i + 1) or (i + 1))
                    end_i = int(num_to_idx.get(int(end_num), int(i)))
                    self.section_ranges.append(
                        SectionRange(
                            start_idx=int(i),
                            end_idx=int(end_i),
                            title=title,
                            restart_numbering=bool(getattr(s, "section_restart_numbering", False)),
                            start_new_page=bool(getattr(s, "section_start_new_page", False)),
                            fill_color=str(getattr(s, "section_fill_color", "#FFFFFF") or "#FFFFFF"),
                            text_color=str(getattr(s, "section_text_color", "#000000") or "#000000"),
                            line_color=str(getattr(s, "section_line_color", "#000000") or "#000000"),
                            font_pt=float(getattr(s, "section_font_pt", 12.0) or 12.0),
                        )
                    )
                except Exception:
                    continue
        except Exception:
            self.section_ranges = []
        # Normalize selection fields from ranges (position-based)
        self._apply_section_ranges_to_selections()
        self._section_popup: Optional[QDialog] = None
        self._editing_section = None  # Track which section is being edited
        
        layout = QVBoxLayout(self)
        
        # Ana dialog arka planı koyu renk
        self.setStyleSheet("""
            QDialog {
                background-color: #2B2B2B;
            }
        """)
        
        # Ana içerik: Sol panel + Orta PDF preview (sağ panel popup)
        main_split = QHBoxLayout()
        main_split.setSpacing(6)
        
        # SOL PANEL: Soru listesi ve boşluk ayarları - Daha küçük stretch (PDF preview daha büyük)
        self.question_list_widget = QuestionListWidget(parent=self, dialog=self)
        self.question_list_widget.set_selections(selections)
        try:
            if hasattr(self.question_list_widget, "section_btn_open"):
                self.question_list_widget.section_btn_open.clicked.connect(self._open_section_popup)
        except Exception:
            pass
        # Sol panelde scrollbar olmasın
        try:
            self.question_list_widget.setFixedWidth(int(self.question_list_widget.minimumWidth()))
        except Exception:
            pass
        main_split.addWidget(self.question_list_widget, stretch=0)
        
        # ORTA PANEL: PDF render preview
        right_panel_layout = QVBoxLayout()
        
        pdf_preview_scroll = QScrollArea()
        pdf_preview_scroll.setWidgetResizable(True)
        pdf_preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # Sağda scrollbar
        pdf_preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # Altta scrollbar
        # Sağ panel arka planı koyu tonlarda, köşeler yumuşatılmış
        pdf_preview_scroll.setStyleSheet("""
            QScrollArea {
                background-color: #424242;
                border: none;
                border-radius: 12px;
            }
        """)
        self.pdf_render_widget = PDFRenderPreviewWidget(self)
        pdf_preview_scroll.setWidget(self.pdf_render_widget)
        right_panel_layout.addWidget(pdf_preview_scroll, stretch=1)

        # ===== SAĞ PANEL: BÖLÜM BİLGİLERİ =====
        self.section_panel = QWidget()
        self.section_panel.setObjectName("sectionPanel")
        try:
            self.section_panel.setFixedWidth(int(self.question_list_widget.minimumWidth()))
        except Exception:
            self.section_panel.setFixedWidth(360)
        self.section_panel.setStyleSheet("""
            QWidget#sectionPanel {
                background-color: #4A4A4A;
                border: 2px solid #616161;
                border-radius: 12px;
            }
        """)
        section_outer_layout = QVBoxLayout(self.section_panel)
        section_outer_layout.setContentsMargins(12, 12, 12, 12)
        section_outer_layout.setSpacing(12)
        section_outer_layout.setAlignment(Qt.AlignTop)

        section_inner = QWidget()
        section_inner.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }
        """)
        section_inner_layout = QVBoxLayout(section_inner)
        section_inner_layout.setContentsMargins(12, 12, 12, 12)
        section_inner_layout.setSpacing(12)
        section_inner_layout.setAlignment(Qt.AlignTop)
        self.section_inner_layout = section_inner_layout  # Layout referansını sakla (checkbox eklemek için)

        header = QLabel("📌 BÖLÜM BİLGİLERİ")
        header.setMinimumHeight(40)
        header.setMaximumHeight(40)
        header.setStyleSheet("""
            font-size: 16px; 
            font-weight: bold; 
            color: #90CAF9;
            padding: 10px 16px;
            background-color: #1E3A5F;
            border: none;
            border-radius: 10px;
        """)
        header.setAlignment(Qt.AlignCenter)
        section_inner_layout.addWidget(header)

        # Mode selection radio buttons (başlangıçta görünür)
        self.mode_radio_container = QWidget()
        self.mode_radio_layout = QHBoxLayout(self.mode_radio_container)
        self.mode_radio_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_radio_layout.setSpacing(12)
        
        self.section_mode_group = QButtonGroup(self)
        self.section_mode_group.setExclusive(True)
        
        self.rb_new_section = QRadioButton("Yeni bölüm ekle")
        self.rb_edit_section = QRadioButton("Düzenle")
        
        for rb in (self.rb_new_section, self.rb_edit_section):
            rb.setMinimumHeight(28)
            rb.setMaximumHeight(28)
            rb.setStyleSheet("""
                QRadioButton {
                    color: #E0E0E0;
                    font-size: 13px;
                }
                QRadioButton::indicator {
                    width: 18px;
                    height: 18px;
                    border-radius: 9px;
                    border: 2px solid #CCCCCC;
                    background-color: white;
                }
                QRadioButton::indicator:checked {
                    background-color: #2196F3;
                    border: 2px solid #2196F3;
                }
            """)
            self.section_mode_group.addButton(rb)
            self.mode_radio_layout.addWidget(rb)
        
        self.rb_new_section.setChecked(True)
        self.rb_edit_section.setVisible(False)  # Başlangıçta "Düzenle" görünmez
        self.mode_radio_container.setVisible(True)  # Başlangıçta görünür
        section_inner_layout.addWidget(self.mode_radio_container)


        # Bölüm adı (Bölüm aralığının üstünde)
        self.section_title_edit = QLineEdit()
        self.section_title_edit.setPlaceholderText("Bölüm adı giriniz")
        self.section_title_edit.setMinimumHeight(28)
        self.section_title_edit.setMaximumHeight(28)
        self.section_title_edit.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QLineEdit:disabled {
                background-color: #F5F5F5;
                color: #999999;
            }
        """)
        section_inner_layout.addWidget(self.section_title_edit)

        # Bölüm aralığı
        range_box = QWidget()
        range_box.setObjectName("sectionRangeBox")
        range_box.setStyleSheet("""
            QWidget#sectionRangeBox {
                background-color: #616161;
                border: 1px solid #616161;
                border-radius: 8px;
            }
        """)
        range_layout = QVBoxLayout(range_box)
        range_layout.setContentsMargins(12, 12, 12, 12)
        range_layout.setSpacing(8)

        range_title = QLabel("Bölüm aralığı")
        range_title.setMinimumHeight(32)
        range_title.setMaximumHeight(32)
        range_title.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        range_layout.addWidget(range_title)

        self.section_start_cb = QComboBox()
        self.section_end_cb = QComboBox()
        for cb in (self.section_start_cb, self.section_end_cb):
            cb.setMinimumHeight(28)
            cb.setStyleSheet("""
                QComboBox {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: white;
                    color: #000000;
                }
                QComboBox:disabled {
                    background-color: #F5F5F5;
                    color: #999999;
                }
            """)

        start_row = QHBoxLayout()
        start_row.setSpacing(8)
        lbl_start = QLabel("Başlangıç:")
        lbl_start.setStyleSheet("color:#E0E0E0; font-size: 12px;")
        lbl_start.setFixedWidth(80)
        start_row.addWidget(lbl_start, 0)
        start_row.addWidget(self.section_start_cb, 1)
        range_layout.addLayout(start_row)

        end_row = QHBoxLayout()
        end_row.setSpacing(8)
        lbl_end = QLabel("Bitiş:")
        lbl_end.setStyleSheet("color:#E0E0E0; font-size: 12px;")
        lbl_end.setFixedWidth(80)
        end_row.addWidget(lbl_end, 0)
        end_row.addWidget(self.section_end_cb, 1)
        range_layout.addLayout(end_row)
        section_inner_layout.addWidget(range_box)

        # Numara davranışı (kutulu)
        num_box = QWidget()
        num_box.setObjectName("sectionNumBox")
        num_box.setStyleSheet("""
            QWidget#sectionNumBox {
                background-color: #616161;
                border: 1px solid #616161;
                border-radius: 8px;
            }
        """)
        num_layout = QVBoxLayout(num_box)
        num_layout.setContentsMargins(12, 12, 12, 12)
        num_layout.setSpacing(8)

        num_title = QLabel("Soru Numaraları")
        num_title.setMinimumHeight(32)
        num_title.setMaximumHeight(32)
        num_title.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        num_layout.addWidget(num_title)

        self.section_rb_continue = QRadioButton("Soru numarasını sırası ile devam et")
        self.section_rb_restart = QRadioButton("Soru numarasını 1'den başlat")
        for rb in (self.section_rb_continue, self.section_rb_restart):
            rb.setMinimumHeight(28)
            rb.setMaximumHeight(28)
            rb.setStyleSheet("color:#E0E0E0; font-size: 12px;")
            num_layout.addWidget(rb, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        section_inner_layout.addWidget(num_box)

        self.section_num_group = QButtonGroup(self)
        self.section_num_group.setExclusive(True)
        self.section_num_group.addButton(self.section_rb_continue)
        self.section_num_group.addButton(self.section_rb_restart)
        self.section_rb_continue.setChecked(True)

        self.section_new_page_cb = QCheckBox("Soruları yeni sayfadan başlat")
        self.section_new_page_cb.setMinimumHeight(28)
        self.section_new_page_cb.setMaximumHeight(28)
        self.section_new_page_cb.setStyleSheet("""
            font-size: 13px;
            color: #E0E0E0;
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #CCCCCC;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
                border: 1px solid #2196F3;
            }
        """)
        section_inner_layout.addWidget(self.section_new_page_cb, alignment=Qt.AlignLeft | Qt.AlignVCenter)

        # Stil ayarları
        style_box = QWidget()
        style_box.setObjectName("sectionStyleBox")
        style_box.setStyleSheet("""
            QWidget#sectionStyleBox {
                background-color: #616161;
                border: 1px solid #616161;
                border-radius: 8px;
            }
        """)
        style_layout = QVBoxLayout(style_box)
        style_layout.setContentsMargins(12, 12, 12, 12)
        style_layout.setSpacing(8)

        style_title = QLabel("Stil")
        style_title.setMinimumHeight(32)
        style_title.setMaximumHeight(32)
        style_title.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        style_layout.addWidget(style_title)

        style_row1 = QHBoxLayout()
        style_row1.setSpacing(8)
        lbl_fill = QLabel("Dolgu:")
        lbl_text = QLabel("Yazı:")
        lbl_line = QLabel("Çizgi:")
        for lab in (lbl_fill, lbl_text):
            lab.setStyleSheet("color:#E0E0E0; font-size: 12px;")
        lbl_line.setStyleSheet("color:#E0E0E0; font-size: 12px;")

        self.section_fill_btn = QPushButton(" ")
        self.section_text_btn = QPushButton(" ")
        self.section_line_btn = QPushButton(" ")
        for btn in (self.section_fill_btn, self.section_text_btn):
            btn.setFixedSize(44, 24)
            btn.setStyleSheet("background-color:#FFFFFF; border: 1px solid #CCCCCC; border-radius: 4px;")
        self.section_line_btn.setFixedSize(44, 24)
        self.section_line_btn.setStyleSheet("background-color:#000000; border: 1px solid #CCCCCC; border-radius: 4px;")

        style_row1.addWidget(lbl_fill, 0)
        style_row1.addWidget(self.section_fill_btn, 0)
        style_row1.addSpacing(10)
        style_row1.addWidget(lbl_text, 0)
        style_row1.addWidget(self.section_text_btn, 0)
        style_row1.addSpacing(10)
        style_row1.addWidget(lbl_line, 0)
        style_row1.addWidget(self.section_line_btn, 0)
        style_row1.addSpacing(12)
        lbl_size = QLabel("Yazı boyutu:")
        lbl_size.setStyleSheet("color:#E0E0E0; font-size: 12px;")
        self.section_font_size = QSpinBox()
        self.section_font_size.setRange(8, 24)
        self.section_font_size.setValue(12)
        self.section_font_size.setMinimumHeight(28)
        self.section_font_size.setStyleSheet("""
            QSpinBox {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QSpinBox:disabled {
                background-color: #F5F5F5;
                color: #999999;
            }
        """)
        style_row1.addWidget(lbl_size, 0)
        style_row1.addWidget(self.section_font_size, 0)
        style_row1.addStretch()
        style_layout.addLayout(style_row1)
        section_inner_layout.addWidget(style_box)

        # Bölüm listesi (ayrılmış bölümler)
        sections_box = QWidget()
        sections_box.setObjectName("sectionsListBox")
        sections_box.setStyleSheet("""
            QWidget#sectionsListBox {
                background-color: #616161;
                border: 1px solid #616161;
                border-radius: 8px;
            }
        """)
        sections_layout = QVBoxLayout(sections_box)
        sections_layout.setContentsMargins(12, 12, 12, 12)
        sections_layout.setSpacing(8)

        sections_title = QLabel("Bölümler")
        sections_title.setMinimumHeight(32)
        sections_title.setMaximumHeight(32)
        sections_title.setStyleSheet("""
            font-size: 15px; 
            color: #90CAF9; 
            font-weight: bold;
            padding: 4px 0px;
            border-bottom: 2px solid #90CAF9;
        """)
        sections_layout.addWidget(sections_title)

        self.sections_list_container = QWidget()
        self.sections_list_v = QVBoxLayout(self.sections_list_container)
        self.sections_list_v.setContentsMargins(0, 0, 0, 0)
        self.sections_list_v.setSpacing(6)
        sections_layout.addWidget(self.sections_list_container)

        # Apply, Bölümlerden ÖNCE
        self.section_apply_btn = QPushButton("Uygula")
        self.section_apply_btn.setMinimumHeight(34)
        self.section_apply_btn.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                font-weight: bold;
                color: #90CAF9;
                background-color: #1E3A5F;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover:enabled {
                background-color: #24456F;
            }
            QPushButton:disabled {
                background-color: #2B2B2B;
                color: #616161;
            }
        """)
        section_inner_layout.addWidget(self.section_apply_btn)

        section_inner_layout.addWidget(sections_box)
        section_inner_layout.addStretch()

        section_outer_layout.addWidget(section_inner)

        # ===== Bölüm paneli: veri bağlama (Uygula'ya basmadan preview güncellenmez) =====
        self._section_fill_hex = "#FFFFFF"
        self._section_text_hex = "#000000"
        self._section_line_hex = "#000000"

        def _set_color_btn(btn: QPushButton, hex_color: str) -> None:
            hc = (hex_color or "#FFFFFF").strip() or "#FFFFFF"
            btn.setStyleSheet(f"background-color:{hc}; border: 1px solid #CCCCCC; border-radius: 4px;")

        def _refresh_section_range_options() -> None:
            try:
                self.section_start_cb.blockSignals(True)
                self.section_end_cb.blockSignals(True)
                self.section_start_cb.clear()
                self.section_end_cb.clear()
                # Placeholder
                self.section_start_cb.addItem("Seç", None)
                self.section_end_cb.addItem("Seç", None)
                for idx, s in enumerate(self.selections or []):
                    try:
                        n = int(getattr(s, "number", idx + 1) or (idx + 1))
                    except Exception:
                        n = idx + 1
                    self.section_start_cb.addItem(f"Soru {n}", int(idx))
                    self.section_end_cb.addItem(f"Soru {n}", int(idx))
            finally:
                try:
                    self.section_start_cb.blockSignals(False)
                    self.section_end_cb.blockSignals(False)
                except Exception:
                    pass

        def _reset_section_form() -> None:
            """Formu boş hale getir (yeni bölüm ekleme için)"""
            try:
                self._editing_section = None
                # Mode radio'ları sıfırla - "Yeni bölüm ekle" seçili, "Düzenle" görünmez
                self.rb_new_section.setChecked(True)
                self.rb_edit_section.setVisible(False)  # "Düzenle" radio butonu gizli
                self.mode_radio_container.setVisible(True)
                # Form alanlarını sıfırla
                self.section_start_cb.setCurrentIndex(0)
                self.section_end_cb.setCurrentIndex(0)
                self.section_title_edit.setText("")
                self.section_rb_continue.setChecked(True)
                self.section_new_page_cb.setChecked(False)
                self._section_fill_hex = "#FFFFFF"
                self._section_text_hex = "#000000"
                self._section_line_hex = "#000000"
                _set_color_btn(self.section_fill_btn, self._section_fill_hex)
                _set_color_btn(self.section_text_btn, self._section_text_hex)
                _set_color_btn(self.section_line_btn, self._section_line_hex)
                self.section_font_size.setValue(12)
                # Yeni bölüm ekle modunda form aktif
                _set_section_panel_enabled(True)
                _update_section_apply_enabled()
            except Exception:
                pass

        def _set_section_panel_enabled(enabled: bool) -> None:
            # Yeni bölüm ekle modunda checkbox görünmez ama form aktif olmalı
            if self.rb_new_section.isChecked():
                enabled = True
            
            enabled = bool(enabled)
            for w in (
                self.section_start_cb,
                self.section_end_cb,
                self.section_title_edit,
                self.section_rb_continue,
                self.section_rb_restart,
                self.section_new_page_cb,
                self.section_fill_btn,
                self.section_text_btn,
                self.section_line_btn,
                self.section_font_size,
            ):
                try:
                    w.setEnabled(enabled)
                except Exception:
                    pass
            # Apply: only enabled when editing/creating is active
            try:
                self.section_apply_btn.setEnabled(enabled)
            except Exception:
                pass
            # When disabled, keep placeholder visible
            if not enabled:
                try:
                    self.section_title_edit.setText("")
                    self.section_title_edit.setPlaceholderText("Bölüm adı giriniz")
                except Exception:
                    pass

        def _update_section_apply_enabled() -> None:
            try:
                # Form her zaman aktif (checkbox kaldırıldı)
                enabled = True
                
                if not enabled:
                    self.section_apply_btn.setEnabled(False)
                    return
                si = self.section_start_cb.currentData()
                ei = self.section_end_cb.currentData()
                title = (self.section_title_edit.text() or "").strip()
                ok = (si is not None) and (ei is not None) and bool(title)
                self.section_apply_btn.setEnabled(bool(ok))
            except Exception:
                try:
                    self.section_apply_btn.setEnabled(False)
                except Exception:
                    pass

        def _get_selected_question_number() -> Optional[int]:
            try:
                return int(getattr(self.question_list_widget, "selected_question_number", None))
            except Exception:
                return None

        def _find_index_by_number(n: int) -> Optional[int]:
            try:
                nn = int(n)
            except Exception:
                return None
            for i, s in enumerate(self.selections or []):
                try:
                    if int(getattr(s, "number", -1)) == nn:
                        return int(i)
                except Exception:
                    continue
            return None

        def _sync_section_panel_for_selected_question() -> None:
            qn = _get_selected_question_number()
            if qn is None:
                _set_section_panel_enabled(False)
                return
            idx_sel = _find_index_by_number(int(qn))
            if idx_sel is None:
                _set_section_panel_enabled(False)
                return

            # Default: show "Seç" (new section)
            try:
                self.section_start_cb.setCurrentIndex(0)
                self.section_end_cb.setCurrentIndex(0)
            except Exception:
                pass
            self.section_title_edit.setText("")
            self.section_rb_continue.setChecked(True)
            self.section_new_page_cb.setChecked(False)
            self._section_fill_hex = "#FFFFFF"
            self._section_text_hex = "#000000"
            self._section_line_hex = "#000000"
            _set_color_btn(self.section_fill_btn, self._section_fill_hex)
            _set_color_btn(self.section_text_btn, self._section_text_hex)
            _set_color_btn(self.section_line_btn, self._section_line_hex)
            self.section_font_size.setValue(12)

            # If selected question is a section start, load that range
            match = None
            for r in (self.section_ranges or []):
                try:
                    if int(getattr(r, "start_idx", -1)) == int(idx_sel):
                        match = r
                        break
                except Exception:
                    continue
            if match is None:
                _set_section_panel_enabled(False)
                _update_section_apply_enabled()
                return

            _set_section_panel_enabled(True)
            _update_section_apply_enabled()
            try:
                s_idx = int(getattr(match, "start_idx", 0))
                e_idx = int(getattr(match, "end_idx", s_idx))
                si = self.section_start_cb.findData(int(s_idx))
                ei = self.section_end_cb.findData(int(e_idx))
                if si >= 0:
                    self.section_start_cb.setCurrentIndex(si)
                if ei >= 0:
                    self.section_end_cb.setCurrentIndex(ei)
            except Exception:
                pass
            self.section_title_edit.setText((getattr(match, "title", "") or ""))
            if bool(getattr(match, "restart_numbering", False)):
                self.section_rb_restart.setChecked(True)
            else:
                self.section_rb_continue.setChecked(True)
            self.section_new_page_cb.setChecked(bool(getattr(match, "start_new_page", False)))
            self._section_fill_hex = (getattr(match, "fill_color", None) or "#FFFFFF")
            self._section_text_hex = (getattr(match, "text_color", None) or "#000000")
            self._section_line_hex = (getattr(match, "line_color", None) or "#000000")
            _set_color_btn(self.section_fill_btn, self._section_fill_hex)
            _set_color_btn(self.section_text_btn, self._section_text_hex)
            _set_color_btn(self.section_line_btn, self._section_line_hex)
            try:
                self.section_font_size.setValue(int(float(getattr(match, "font_pt", 12.0) or 12.0)))
            except Exception:
                self.section_font_size.setValue(12)

        def _pick_color(initial_hex: str) -> Optional[str]:
            try:
                col = QColorDialog.getColor(QColor(initial_hex), self, "Renk Seç")
                if col and col.isValid():
                    return col.name().upper()
            except Exception:
                pass
            return None

        def _on_pick_fill():
            newc = _pick_color(self._section_fill_hex)
            if newc:
                self._section_fill_hex = newc
                _set_color_btn(self.section_fill_btn, newc)

        def _on_pick_text():
            newc = _pick_color(self._section_text_hex)
            if newc:
                self._section_text_hex = newc
                _set_color_btn(self.section_text_btn, newc)

        def _apply_section_panel():
            # Read range
            try:
                start_idx = self.section_start_cb.currentData()
                start_idx = int(start_idx) if start_idx is not None else None
            except Exception:
                start_idx = None
            try:
                end_idx = self.section_end_cb.currentData()
                end_idx = int(end_idx) if end_idx is not None else None
            except Exception:
                end_idx = None
            if start_idx is None or end_idx is None:
                return
            if end_idx < start_idx:
                start_idx, end_idx = end_idx, start_idx

            # Form her zaman aktif (checkbox kaldırıldı)
            enabled = True
            title = (self.section_title_edit.text() or "").strip()
            restart = bool(self.section_rb_restart.isChecked())
            new_page = bool(self.section_new_page_cb.isChecked())
            font_pt = float(self.section_font_size.value())
            fill_hex = str(self._section_fill_hex or "#FFFFFF")
            text_hex = str(self._section_text_hex or "#000000")
            line_hex = str(self._section_line_hex or "#000000")

            if enabled and title:
                # NOT: Bölüm içinde soru numarasını 1'den başlatma artık serbest.
                # PDF'de görünen numaralandırma bölüm bazlı (local) yapılabildiği için,
                # global çakışma uyarısı vermiyoruz.

                # Eğer düzenleme modundaysa, eski bölümü listeden çıkar
                # Otomatik düzenleme mantığı kaldırıldı - sadece açıkça "Düzenle" butonuna basıldığında düzenleme yapılır
                editing_old_start = None
                editing_old_end = None
                is_editing = (self._editing_section is not None)
                if is_editing:
                    try:
                        editing_old_start = int(getattr(self._editing_section, "start_idx", -1))
                        editing_old_end = int(getattr(self._editing_section, "end_idx", -1))
                        # Eski bölümü listeden kaldır
                        self.section_ranges = [x for x in (self.section_ranges or []) if x is not self._editing_section]
                    except Exception:
                        is_editing = False

                # Çakışma kontrolü: düzenleme modunda ve aralık değişmediyse atla
                # (sadece renk/dolgu değiştiriliyorsa çakışma kontrolü yok)
                skip_overlap_check = (is_editing and editing_old_start is not None and editing_old_end is not None 
                                     and editing_old_start == start_idx and editing_old_end == end_idx)

                if not skip_overlap_check:
                    # Overlap check: do NOT delete existing sections; block and warn instead
                    overlaps: List[int] = []
                    for r in (self.section_ranges or []):
                        try:
                            s_i = int(getattr(r, "start_idx", 0))
                            e_i = int(getattr(r, "end_idx", s_i))
                            if e_i < s_i:
                                s_i, e_i = e_i, s_i
                            o_s = max(int(s_i), int(start_idx))
                            o_e = min(int(e_i), int(end_idx))
                            if o_s <= o_e:
                                overlaps.extend(list(range(o_s, o_e + 1)))
                        except Exception:
                            continue
                    
                    # Eğer düzenleme modundaysa ve yeni aralık eski aralığı kapsıyorsa veya eşitse,
                    # eski aralık içindeki çakışmaları filtrele (aynı bölümün kendi soruları)
                    # Çünkü kullanıcı sadece bölümü genişletiyor, bu durumda kendi sorularıyla çakışma uyarısı vermemeli
                    if is_editing and editing_old_start is not None and editing_old_end is not None:
                        # Yeni aralık eski aralığı kapsıyorsa (genişletme) veya tam tersi (daraltma)
                        old_range = set(range(int(editing_old_start), int(editing_old_end) + 1))
                        new_range = set(range(int(start_idx), int(end_idx) + 1))
                        # Eğer yeni aralık eski aralığı içeriyorsa veya eski aralık yeni aralığı içeriyorsa
                        # (yani birbirleriyle çakışan aralıklar), eski aralık içindeki çakışmaları görmezden gel
                        if old_range.issubset(new_range) or new_range.issubset(old_range) or old_range == new_range:
                            # Aynı bölümün kendi sorularıyla çakışmayı filtrele
                            overlaps = [i for i in overlaps if i not in old_range]
                    
                    if overlaps:
                        try:
                            overlaps = sorted(set(int(i) for i in overlaps))
                            qnums = []
                            for i in overlaps:
                                if 0 <= int(i) < len(self.selections or []):
                                    qnums.append(int(getattr(self.selections[int(i)], "number", int(i) + 1) or (int(i) + 1)))
                            qnums = sorted(set(qnums))
                            QMessageBox.warning(
                                self,
                                "Uyarı",
                                "Yeni bölüm aralığı mevcut bir bölüm ile çakışıyor.\n"
                                f"Çakışan sorular: {', '.join(map(str, qnums))}\n"
                                "Lütfen başka bir aralık seçin."
                            )
                        except Exception:
                            QMessageBox.warning(self, "Uyarı", "Yeni bölüm aralığı mevcut bir bölüm ile çakışıyor. Lütfen başka bir aralık seçin.")
                        # Çakışma varsa eski bölümü geri ekle (eğer düzenliyorsak)
                        if is_editing and self._editing_section is not None:
                            try:
                                if self._editing_section not in (self.section_ranges or []):
                                    self.section_ranges.append(self._editing_section)
                            except Exception:
                                pass
                        return
                
                # Yeni bölümü ekle (veya güncellenmiş olarak ekle)
                self.section_ranges.append(
                    SectionRange(
                        start_idx=int(start_idx),
                        end_idx=int(end_idx),
                        title=title,
                        restart_numbering=bool(restart),
                        start_new_page=bool(new_page),
                        fill_color=fill_hex,
                        text_color=text_hex,
                        line_color=line_hex,
                        font_pt=float(font_pt),
                    )
                )

            # Apply ranges onto selections (position-based)
            self._apply_section_ranges_to_selections()

            # Update preview only now
            self._update_pdf_preview(preserve_current_page=True)
            # Reset UI: checkbox off after creating/updating
            # Formu tamamen temizle (yeni bölüm ekleme için hazır hale getir)
            if hasattr(self, '_reset_section_form'):
                self._reset_section_form()
            else:
                try:
                    self.section_start_cb.setCurrentIndex(0)
                    self.section_end_cb.setCurrentIndex(0)
                    self.section_title_edit.setText("")
                    self._editing_section = None
                except Exception:
                    pass
            _refresh_sections_list()

        def _clear_sections_list_widgets():
            try:
                while self.sections_list_v.count():
                    item = self.sections_list_v.takeAt(0)
                    w = item.widget()
                    if w is not None:
                        w.setParent(None)
                        w.deleteLater()
            except Exception:
                pass

        def _refresh_sections_list():
            _clear_sections_list_widgets()
            try:
                sections = list(self.section_ranges or [])
                if not sections:
                    lbl = QLabel("Henüz bölüm oluşturulmamıştır")
                    lbl.setStyleSheet("color:#E0E0E0; font-size: 12px; padding: 6px; border: none;")
                    self.sections_list_v.addWidget(lbl)
                    return

                sections.sort(key=lambda r: int(getattr(r, "start_idx", 0)))
                for r in sections:
                    try:
                        s_i = int(getattr(r, "start_idx", 0))
                        e_i = int(getattr(r, "end_idx", s_i))
                        if e_i < s_i:
                            s_i, e_i = e_i, s_i
                        if s_i < 0:
                            s_i = 0
                        if e_i >= len(self.selections or []):
                            e_i = max(0, len(self.selections or []) - 1)
                        start_n = int(getattr(self.selections[s_i], "number", s_i + 1) or (s_i + 1))
                        end_n = int(getattr(self.selections[e_i], "number", e_i + 1) or (e_i + 1))
                        title = (getattr(r, "title", "") or "").strip()
                        if not title:
                            continue
                    except Exception:
                        continue

                    row = QWidget()
                    row_l = QHBoxLayout(row)
                    row_l.setContentsMargins(0, 0, 0, 0)
                    row_l.setSpacing(8)

                    btn = QPushButton(f"{title} (Soru {start_n} - {end_n})")
                    btn.setStyleSheet("""
                        QPushButton {
                            text-align: left;
                            padding: 8px 10px;
                            border-radius: 6px;
                            background-color: #2B2B2B;
                            color: #E0E0E0;
                            border: 1px solid #616161;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            background-color: #333333;
                            border: 1px solid #90CAF9;
                            color: #90CAF9;
                        }
                    """)

                    btn_edit = QPushButton("Düzenle")
                    btn_edit.setFixedWidth(60)
                    btn_edit.setStyleSheet("""
                        QPushButton {
                            background-color: #2196F3;
                            color: white;
                            border: none;
                            border-radius: 6px;
                            padding: 8px;
                            font-weight: bold;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            background-color: #1976D2;
                        }
                    """)

                    btn_del = QPushButton("Sil")
                    btn_del.setFixedWidth(50)
                    btn_del.setStyleSheet("""
                        QPushButton {
                            background-color: #F44336;
                            color: white;
                            border: none;
                            border-radius: 6px;
                            padding: 8px;
                            font-weight: bold;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            background-color: #D32F2F;
                        }
                    """)

                    def _load_section(_=False, rr=r):
                        try:
                            # Düzenleme moduna geç: hangi bölüm düzenleniyor
                            self._editing_section = rr
                            # Mode radio butonlarını göster ve "Düzenle" seçili yap
                            self.rb_edit_section.setVisible(True)  # "Düzenle" radio butonu görünür
                            self.mode_radio_container.setVisible(True)
                            self.rb_edit_section.setChecked(True)
                            self.rb_new_section.setChecked(False)  # "Yeni bölüm ekle" seçili değil
                            si = self.section_start_cb.findData(int(getattr(rr, "start_idx", 0)))
                            ei = self.section_end_cb.findData(int(getattr(rr, "end_idx", getattr(rr, "start_idx", 0))))
                            if si >= 0:
                                self.section_start_cb.setCurrentIndex(si)
                            if ei >= 0:
                                self.section_end_cb.setCurrentIndex(ei)
                            self.section_title_edit.setText((getattr(rr, "title", "") or ""))
                            if bool(getattr(rr, "restart_numbering", False)):
                                self.section_rb_restart.setChecked(True)
                            else:
                                self.section_rb_continue.setChecked(True)
                            self.section_new_page_cb.setChecked(bool(getattr(rr, "start_new_page", False)))
                            self._section_fill_hex = (getattr(rr, "fill_color", None) or "#FFFFFF")
                            self._section_text_hex = (getattr(rr, "text_color", None) or "#000000")
                            self._section_line_hex = (getattr(rr, "line_color", None) or "#000000")
                            _set_color_btn(self.section_fill_btn, self._section_fill_hex)
                            _set_color_btn(self.section_text_btn, self._section_text_hex)
                            _set_color_btn(self.section_line_btn, self._section_line_hex)
                            self.section_font_size.setValue(int(float(getattr(rr, "font_pt", 12.0) or 12.0)))
                            _set_section_panel_enabled(True)
                        except Exception:
                            pass

                    def _delete_section(_=False, rr=r):
                        try:
                            self.section_ranges = [x for x in (self.section_ranges or []) if x is not rr]
                        except Exception:
                            try:
                                self.section_ranges = [x for x in (self.section_ranges or []) if getattr(x, "start_idx", None) != getattr(rr, "start_idx", None)]
                            except Exception:
                                pass
                        self._apply_section_ranges_to_selections()
                        _refresh_section_range_options()
                        _refresh_sections_list()
                        self._update_pdf_preview(preserve_current_page=True)
                        try:
                            _set_section_panel_enabled(False)
                        except Exception:
                            pass

                    btn.clicked.connect(_load_section)
                    btn_edit.clicked.connect(_load_section)
                    btn_del.clicked.connect(_delete_section)
                    row_l.addWidget(btn, 1)
                    row_l.addWidget(btn_edit, 0)
                    row_l.addWidget(btn_del, 0)
                    self.sections_list_v.addWidget(row)
            except Exception:
                pass
            self.sections_list_v.addStretch()

        self.section_fill_btn.clicked.connect(_on_pick_fill)
        self.section_text_btn.clicked.connect(_on_pick_text)
        def _on_pick_line():
            newc = _pick_color(self._section_line_hex)
            if newc:
                self._section_line_hex = newc
                _set_color_btn(self.section_line_btn, newc)
        self.section_line_btn.clicked.connect(_on_pick_line)
        
        # Mode radio butonları için event handler
        def _on_new_section_radio_clicked():
            """Yeni bölüm ekle radio butonuna tıklandığında formu sıfırla"""
            if self.rb_new_section.isChecked():
                # "Düzenle" radio butonu görünmez yap
                self.rb_edit_section.setVisible(False)
                _reset_section_form()
        
        def _on_edit_section_radio_clicked():
            """Düzenle radio butonuna tıklandığında"""
            if self.rb_edit_section.isChecked():
                # Düzenle modunda form aktif
                if self._editing_section is not None:
                    _set_section_panel_enabled(True)
        
        self.rb_new_section.toggled.connect(lambda checked: _on_new_section_radio_clicked() if checked else None)
        self.rb_edit_section.toggled.connect(lambda checked: _on_edit_section_radio_clicked() if checked else None)
        
        self.section_apply_btn.clicked.connect(_apply_section_panel)
        self.section_start_cb.currentIndexChanged.connect(lambda _i: _update_section_apply_enabled())
        self.section_end_cb.currentIndexChanged.connect(lambda _i: _update_section_apply_enabled())
        self.section_title_edit.textChanged.connect(lambda _t: _update_section_apply_enabled())

        _refresh_section_range_options()
        _refresh_sections_list()
        _set_color_btn(self.section_fill_btn, self._section_fill_hex)
        _set_color_btn(self.section_text_btn, self._section_text_hex)
        _set_color_btn(self.section_line_btn, self._section_line_hex)
        # Başlangıçta yeni bölüm ekle modu aktif, form aktif, "Düzenle" görünmez
        self.rb_new_section.setChecked(True)
        self.rb_edit_section.setVisible(False)
        _set_section_panel_enabled(True)
        _update_section_apply_enabled()
        self._sync_section_panel_for_selected_question = _sync_section_panel_for_selected_question
        self._reset_section_form = _reset_section_form
        
        # Zoom kontrolleri
        zoom_layout = QHBoxLayout()
        zoom_layout.addStretch()
        
        btn_zoom_out = QPushButton("🔍-")
        btn_zoom_out.setToolTip("Uzaklaştır")
        btn_zoom_out.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #333;
                padding: 8px 12px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #BDBDBD;
            }
        """)
        btn_zoom_out.clicked.connect(self.pdf_render_widget.zoom_out)
        zoom_layout.addWidget(btn_zoom_out)
        
        btn_zoom_fit = QPushButton("⛶")
        btn_zoom_fit.setToolTip("Pencereye Sığdır")
        btn_zoom_fit.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #333;
                padding: 8px 12px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #BDBDBD;
            }
        """)
        btn_zoom_fit.clicked.connect(self.pdf_render_widget.zoom_fit)
        zoom_layout.addWidget(btn_zoom_fit)
        
        btn_zoom_in = QPushButton("🔍+")
        btn_zoom_in.setToolTip("Yakınlaştır")
        btn_zoom_in.setStyleSheet("""
            QPushButton {
                background-color: #E0E0E0;
                color: #333;
                padding: 8px 12px;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #BDBDBD;
            }
        """)
        btn_zoom_in.clicked.connect(self.pdf_render_widget.zoom_in)
        zoom_layout.addWidget(btn_zoom_in)
        
        zoom_layout.addStretch()
        right_panel_layout.addLayout(zoom_layout)
        
        center_panel_widget = QWidget()
        center_panel_widget.setLayout(right_panel_layout)
        # Orta panel widget arka planı koyu tonlarda, köşeler yumuşatılmış
        center_panel_widget.setStyleSheet("""
            QWidget {
                background-color: #424242;
                border: none;
                border-radius: 12px;
            }
        """)
        main_split.addWidget(center_panel_widget, stretch=3)  # PDF preview daha büyük (stretch 3)

        # Sağ panel ana ekranda yok: "Bölüm ekle" ile popup açılacak
        self.section_panel.hide()
        
        layout.addLayout(main_split)
        
        # Cevap anahtarı KALDIRILDI
        
        # Alt bar: Sayfa navigasyonu ve butonlar
        bottom_layout = QHBoxLayout()
        
        # Sayfa navigasyonu - Canlı renkler, PDF kaydet/iptal butonları ile aynı yükseklik
        self.btn_prev_page = QPushButton("⟨ Önceki Sayfa")
        self.btn_prev_page.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover:enabled {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
                color: #757575;
            }
        """)
        self.btn_prev_page.clicked.connect(self.prev_page)
        bottom_layout.addWidget(self.btn_prev_page)
        
        self.lbl_page_info = QLabel("Sayfa 1 / 1")
        self.lbl_page_info.setStyleSheet("font-size: 12px; padding: 5px; color: #E0E0E0;")
        bottom_layout.addWidget(self.lbl_page_info)
        
        self.btn_next_page = QPushButton("Sonraki Sayfa ⟩")
        self.btn_next_page.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover:enabled {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
                color: #757575;
            }
        """)
        self.btn_next_page.clicked.connect(self.next_page)
        bottom_layout.addWidget(self.btn_next_page)

        # Sayfa seçici (istenen sayfaya git) - "Sonraki Sayfa" butonundan sonra
        self.lbl_goto = QLabel("Sayfa:")
        self.lbl_goto.setStyleSheet("font-size: 12px; padding: 5px; color: #E0E0E0;")
        bottom_layout.addWidget(self.lbl_goto)

        self.cb_goto_page = QComboBox()
        self.cb_goto_page.setMinimumWidth(140)
        self.cb_goto_page.setStyleSheet("""
            QComboBox {
                padding: 6px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                background-color: white;
                color: #000000;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
        """)
        bottom_layout.addWidget(self.cb_goto_page)

        def _on_goto_changed(idx: int):
            if self._suppress_page_goto:
                return
            if idx < 0:
                return
            self._load_pdf_page(int(idx))
            self._update_page_info()

        self.cb_goto_page.currentIndexChanged.connect(_on_goto_changed)
        
        bottom_layout.addStretch()
        
        # Ayarları Sıfırla butonu KALDIRILDI
        
        # Butonlar
        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("PDF'yi Kaydet")
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        btn_save.clicked.connect(self.save_pdf)
        bottom_layout.addWidget(btn_save)
        
        layout.addLayout(bottom_layout)
        
        # Önizlemeyi hazırla
        self._update_pdf_preview()
    
    def showEvent(self, event):
        """İlk açılışta pencereyi gerçekten maximize et (Windows/Qt kombinasyonlarında init içinde showMaximized çalışmayabilir)."""
        try:
            super().showEvent(event)
        except Exception:
            pass
        if getattr(self, '_did_maximize', False):
            return
        self._did_maximize = True
        try:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
            self.showMaximized()
        except Exception:
            pass

    def closeEvent(self, event):
        """Dialog kapatıldığında geçici PDF dosyasını temizle"""
        try:
            if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
                try:
                    os.remove(self.temp_pdf_path)
                except Exception:
                    pass
        except Exception:
            pass
        super().closeEvent(event)
    
    def reset_all_settings(self):
        """Tüm boşluk ayarlarını sıfırla ve preview'ı yenile"""
        try:
            from PyQt5.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self,
                "Ayarları Sıfırla",
                "Tüm boşluk ayarları sıfırlanacak ve ilk duruma dönecek. Devam etmek istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Tüm custom_gap değerlerini None yap
                for sel in self.selections:
                    sel.custom_gap_after_pt = None
                    sel.custom_gap_before_pt = None
                
                # Sol panel'i yenile
                self.question_list_widget.set_selections(self.selections)
                
                # PDF preview'ı yenile - ilk yükleme değil, mevcut sayfayı koru
                self._update_pdf_preview(preserve_current_page=True)
                
                # İlk sayfaya dön
                self.pdf_render_widget.current_page = 0
                self._update_page_info()
                
                QMessageBox.information(self, "Başarılı", "Tüm ayarlar sıfırlandı.")
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Ayarlar sıfırlanırken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")
    
    
    def _update_pdf_preview(
        self,
        question_number: int = None,
        preserve_current_page: bool = True,
        *,
        render_scale: float = 3.0,
        build_hit_test: bool = True,
        show_status: bool = True,
    ):
        """PDF export'u geçici dosyaya kaydet ve render et (senkron)."""
        try:
            # UI status
            if show_status and hasattr(self, "pdf_render_widget") and self.pdf_render_widget:
                self.pdf_render_widget.set_status("PDF önizlemesi hazırlanıyor...")

            # Temp PDF path
            if self.temp_pdf_path is None:
                temp_dir = tempfile.gettempdir()
                self.temp_pdf_path = os.path.join(temp_dir, f"tesqube_preview_{os.getpid()}.pdf")

            temp_path = Path(self.temp_pdf_path)
            export_test_pdf(
                selections=self.selections,
                out_path=temp_path,
                opts=self.export_options,
                pdf_docs=self.pdf_docs,
            )

            doc = fitz.open(str(temp_path))
            try:
                if int(doc.page_count) <= 0:
                    self.pdf_render_widget.set_pdf_pixmap(None, 0, fit_to_window=False, preserve_page=False)
                    self.pdf_render_widget.set_status("Bitti")
                    return

                if not hasattr(self, "_question_page_map") or self._question_page_map is None:
                    self._question_page_map = {}

                # Choose page
                if preserve_current_page:
                    page_index = int(self.pdf_render_widget.current_page)
                elif question_number is not None:
                    qn = int(question_number)
                    found_page = self._question_page_map.get(qn)
                    if found_page is None or not (0 <= int(found_page) < int(doc.page_count)):
                        token = f"TMID:{qn}"
                        found_page = None
                        for p_idx in range(int(doc.page_count)):
                            try:
                                page_i = doc.load_page(p_idx)
                                hits = page_i.search_for(token) or []
                                if hits:
                                    found_page = int(p_idx)
                                    break
                            except Exception:
                                continue
                        if found_page is not None:
                            self._question_page_map[qn] = int(found_page)
                    if found_page is not None and 0 <= int(found_page) < int(doc.page_count):
                        page_index = int(found_page)
                    else:
                        page_index = int(self.pdf_render_widget.current_page)
                else:
                    page_index = int(self.pdf_render_widget.current_page)

                if page_index >= int(doc.page_count):
                    page_index = int(doc.page_count) - 1
                if page_index < 0:
                    page_index = 0

                # Render
                page = doc.load_page(int(page_index))
                try:
                    rs = float(render_scale or 3.0)
                except Exception:
                    rs = 3.0
                rs = max(1.2, min(4.0, float(rs)))
                mat = fitz.Matrix(rs, rs)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                qimg = qimage_from_fitz_pix(pix)
                pdf_pixmap = QPixmap.fromImage(qimg)

                # Lightweight mode may skip rebuilding hit-test map; keep scale in sync so highlight doesn't drift
                try:
                    if self.pdf_render_widget:
                        self.pdf_render_widget.set_render_scale(rs)
                except Exception:
                    pass

                # Build rects for click-select
                if build_hit_test:
                    rects_pt: Dict[int, Tuple[float, float, float, float]] = {}
                    try:
                        img_rects: List[fitz.Rect] = []
                        for img in page.get_images(full=True):
                            xref = img[0]
                            try:
                                for r in page.get_image_rects(xref):
                                    img_rects.append(r)
                            except Exception:
                                continue

                        words = page.get_text("words") or []
                        num_words: List[Tuple[int, float, float, float, float]] = []
                        for w in words:
                            try:
                                x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], str(w[4])
                            except Exception:
                                continue
                            t = (txt or "").strip()
                            if t.startswith("TMID:") and t[5:].isdigit():
                                try:
                                    num = int(t[5:])
                                except Exception:
                                    continue
                                num_words.append((num, float(x0), float(y0), float(x1), float(y1)))

                        for num, nx0, ny0, nx1, ny1 in num_words:
                            best_r = None
                            best_dx = None
                            n_h = max(1e-6, (ny1 - ny0))
                            for r in img_rects:
                                if float(r.x0) < float(nx1):
                                    continue
                                overlap = min(float(r.y1), float(ny1)) - max(float(r.y0), float(ny0))
                                if overlap <= 0 or overlap < 0.25 * n_h:
                                    continue
                                dx = float(r.x0) - float(nx1)
                                if best_dx is None or dx < best_dx:
                                    best_dx = dx
                                    best_r = r
                            if best_r is None:
                                continue
                            rects_pt[int(num)] = (float(best_r.x0), float(best_r.y0), float(best_r.x1), float(best_r.y1))
                    except Exception:
                        rects_pt = {}

                    try:
                        if self.pdf_render_widget:
                            self.pdf_render_widget.set_question_rects(rects_pt, render_scale=rs)
                    except Exception:
                        pass

                # Mevcut zoom + pan'ı koru (soru seçimi / yer değiştirme sırasında görünüm zıplamasın)
                current_zoom = getattr(self.pdf_render_widget, 'zoom_factor', 1.0)
                current_pan = getattr(self.pdf_render_widget, 'pan_offset', QPoint(0, 0))
                
                is_first_load = (self.pdf_render_widget.original_pixmap is None or self.pdf_render_widget.original_pixmap.isNull())
                if is_first_load:
                    self.pdf_render_widget.set_pdf_pixmap(pdf_pixmap, doc.page_count, fit_to_window=False, preserve_page=False)
                    self.pdf_render_widget.zoom_factor = 0.4
                    self.pdf_render_widget._apply_zoom()
                else:
                    self.pdf_render_widget.set_pdf_pixmap(pdf_pixmap, doc.page_count, fit_to_window=False, preserve_page=preserve_current_page)
                    # Zoom + pan'ı geri yükle (soru seçimi/taşıma sırasında görünüm sabit kalsın)
                    self.pdf_render_widget.zoom_factor = current_zoom
                    try:
                        self.pdf_render_widget._apply_zoom()
                    except Exception:
                        pass
                    try:
                        self.pdf_render_widget.pan_offset = current_pan
                    except Exception:
                        pass

                self.pdf_render_widget.current_page = int(page_index)
                # Not: Sayfa değişse bile kullanıcı zoom/pan ile nereye bakıyorsa aynı görünümde kalsın.
                self._update_page_info()
                if show_status and self.pdf_render_widget:
                    self.pdf_render_widget.set_status("Bitti")
            finally:
                try:
                    doc.close()
                except Exception:
                    pass
        except Exception as e:
            import traceback
            print(f"Hata: PDF preview güncellenirken: {e}\n{traceback.format_exc()}")
            try:
                self.pdf_render_widget.set_pdf_pixmap(None, 0, fit_to_window=False, preserve_page=False)
                self.pdf_render_widget.set_status("PDF önizleme hatası")
            except Exception:
                pass

    def _apply_section_ranges_to_selections(self) -> None:
        """Apply section_ranges onto selections by current order (indices)."""
        try:
            # Clear all section markers first
            for s in (self.selections or []):
                try:
                    s.section_enabled = False
                    s.section_title = ""
                    s.section_restart_numbering = False
                    s.section_start_new_page = False
                    s.section_end_number = None
                    s.section_fill_color = "#FFFFFF"
                    s.section_text_color = "#000000"
                    s.section_line_color = "#000000"
                    s.section_font_pt = 12.0
                except Exception:
                    pass

            if not self.section_ranges:
                return

            n_sel = len(self.selections or [])
            ranges = list(self.section_ranges or [])
            ranges.sort(key=lambda r: int(getattr(r, "start_idx", 0)))

            for r in ranges:
                try:
                    start_i = int(getattr(r, "start_idx", 0))
                    end_i = int(getattr(r, "end_idx", start_i))
                    if start_i < 0:
                        start_i = 0
                    if end_i < start_i:
                        start_i, end_i = end_i, start_i
                    if start_i >= n_sel:
                        continue
                    if end_i >= n_sel:
                        end_i = n_sel - 1

                    title = (getattr(r, "title", "") or "").strip()
                    if not title:
                        continue

                    start_sel = self.selections[start_i]
                    end_sel = self.selections[end_i]
                    start_sel.section_enabled = True
                    start_sel.section_title = title
                    start_sel.section_restart_numbering = bool(getattr(r, "restart_numbering", False))
                    start_sel.section_start_new_page = bool(getattr(r, "start_new_page", False))
                    start_sel.section_end_number = int(getattr(end_sel, "number", end_i + 1) or (end_i + 1))
                    start_sel.section_fill_color = str(getattr(r, "fill_color", "#FFFFFF") or "#FFFFFF")
                    start_sel.section_text_color = str(getattr(r, "text_color", "#000000") or "#000000")
                    start_sel.section_line_color = str(getattr(r, "line_color", "#000000") or "#000000")
                    try:
                        start_sel.section_font_pt = float(getattr(r, "font_pt", 12.0) or 12.0)
                    except Exception:
                        start_sel.section_font_pt = 12.0
                except Exception:
                    continue
        except Exception:
            pass

    def _open_section_popup(self) -> None:
        """Open 'BÖLÜM BİLGİLERİ' as a popup dialog."""
        try:
            if self._section_popup is not None:
                try:
                    self._section_popup.raise_()
                    self._section_popup.activateWindow()
                    # Formu temizle (yeni bölüm ekleme için)
                    if hasattr(self, '_reset_section_form'):
                        self._reset_section_form()
                except Exception:
                    pass
                return

            # Formu temizle (yeni bölüm ekleme için)
            if hasattr(self, '_reset_section_form'):
                self._reset_section_form()

            # "Yeni bölüm ekle" seçili, "Düzenle" görünmez
            self.rb_new_section.setChecked(True)
            self.rb_edit_section.setVisible(False)

            dlg = QDialog(self)
            dlg.setWindowTitle("Bölüm Bilgileri")
            dlg.setModal(True)
            dlg.setStyleSheet("background-color:#2B2B2B;")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.setSpacing(10)

            # Re-parent section panel into popup
            self.section_panel.setParent(dlg)
            self.section_panel.show()
            lay.addWidget(self.section_panel)

            def _on_finished(_res):
                try:
                    # Re-parent back to main dialog, keep hidden
                    self.section_panel.setParent(self)
                    self.section_panel.hide()
                except Exception:
                    pass
                self._section_popup = None

            dlg.finished.connect(_on_finished)
            self._section_popup = dlg
            dlg.setSizeGripEnabled(True)
            # Dialog boyutu içeriğe göre ayarla
            panel_hint = self.section_panel.sizeHint()
            dlg.resize(panel_hint.width() + 40, panel_hint.height() + 40)
            dlg.exec_()
        except Exception:
            self._section_popup = None

    def _sync_active_question_highlight(self, question_number: Optional[int]) -> None:
        """Keep left panel active state and right preview highlight in sync."""
        try:
            if question_number is None:
                return
            qn = int(question_number)
        except Exception:
            return

        try:
            if hasattr(self, "question_list_widget") and self.question_list_widget:
                self.question_list_widget.last_modified_question = qn
                self._suppress_question_nav = True
                try:
                    self.question_list_widget._on_question_clicked(qn)
                finally:
                    self._suppress_question_nav = False
        except Exception:
            pass

        try:
            if hasattr(self, "pdf_render_widget") and self.pdf_render_widget:
                self.pdf_render_widget.set_selected_question_number(qn)
        except Exception:
            pass
    
    def _reorder_questions(self, dragged_number: int, target_number: int):
        """Soruları yeniden sırala (sürükle-bırak)"""
        try:
            # İndeksleri bul
            dragged_idx = None
            target_idx = None
            for idx, sel in enumerate(self.selections):
                if sel.number == dragged_number:
                    dragged_idx = idx
                if sel.number == target_number:
                    target_idx = idx
            
            if dragged_idx is None or target_idx is None:
                return
            
            # Soruyu taşı
            dragged_sel = self.selections.pop(dragged_idx)
            if dragged_idx < target_idx:
                target_idx -= 1
            self.selections.insert(target_idx, dragged_sel)
            
            # Numaraları güncelle
            for idx, sel in enumerate(self.selections, start=1):
                sel.number = idx
            # Bölüm aralıklarını sabit pozisyona göre tekrar uygula
            self._apply_section_ranges_to_selections()
            
            # Sol panel'i yenile
            self.question_list_widget.set_selections(self.selections)
            try:
                if hasattr(self, "_sync_section_panel_for_selected_question"):
                    self._sync_section_panel_for_selected_question()
            except Exception:
                pass
            # Aktif soruyu (taşınan) yeni numarasıyla seç ve sağda highlight et
            self._sync_active_question_highlight(dragged_sel.number)
            
            # PDF preview'ı yenile
            # Taşınan soru hangi sayfaya gittiyse o sayfayı aç
            self._update_pdf_preview(question_number=dragged_sel.number, preserve_current_page=False)
        except Exception as e:
            import traceback
            print(f"Hata: Sorular yeniden sıralanırken: {e}\n{traceback.format_exc()}")
    
    def _swap_questions(self, question1_number: int, question2_number: int):
        """İki sorunun yerini değiştir"""
        try:
            # İndeksleri bul
            idx1 = None
            idx2 = None
            for idx, sel in enumerate(self.selections):
                if sel.number == question1_number:
                    idx1 = idx
                if sel.number == question2_number:
                    idx2 = idx
            
            if idx1 is None or idx2 is None:
                QMessageBox.warning(self, "Uyarı", f"Soru {question1_number} veya {question2_number} bulunamadı.")
                return
            
            # Yer değiştirilen (işlemi başlatan) soru objesini sakla
            moved_sel = self.selections[idx1]
            self.selections[idx1], self.selections[idx2] = self.selections[idx2], self.selections[idx1]
            
            # Numaraları yeniden sırala (1, 2, 3, ...)
            for idx, sel in enumerate(self.selections, start=1):
                sel.number = idx
            self._apply_section_ranges_to_selections()
            
            # Sol panel'i yenile (grid ve detaylar güncellenecek)
            self.question_list_widget.set_selections(self.selections)
            try:
                if hasattr(self, "_sync_section_panel_for_selected_question"):
                    self._sync_section_panel_for_selected_question()
            except Exception:
                pass
            # Aktif soru olarak işlemi başlatanı koru (yeni numarasıyla)
            try:
                self._sync_active_question_highlight(getattr(moved_sel, "number", None))
            except Exception:
                pass
            
            # PDF preview'ı yenile
            # İşlemi başlatan soru hangi sayfaya gittiyse o sayfayı aç
            self._update_pdf_preview(question_number=getattr(moved_sel, "number", None), preserve_current_page=False)
            
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Sorular yer değiştirilirken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")
    
    def _insert_question_after(self, question_number: int, target_number: int):
        """Bir soruyu başka bir sorunun altına ekle"""
        try:
            # İndeksleri bul
            question_idx = None
            target_idx = None
            for idx, sel in enumerate(self.selections):
                if sel.number == question_number:
                    question_idx = idx
                if sel.number == target_number:
                    target_idx = idx
            
            if question_idx is None or target_idx is None:
                QMessageBox.warning(self, "Uyarı", f"Soru {question_number} veya {target_number} bulunamadı.")
                return
            
            # Soruyu çıkar
            question_sel = self.selections.pop(question_idx)
            
            # Hedef sorudan sonrasına ekle
            if question_idx < target_idx:
                # Soru hedef sorudan önceydi, indeks değişti
                insert_idx = target_idx
            else:
                # Soru hedef sorudan sonraydı
                insert_idx = target_idx + 1
            
            self.selections.insert(insert_idx, question_sel)
            
            # Numaraları yeniden sırala (1, 2, 3, ...)
            for idx, sel in enumerate(self.selections, start=1):
                sel.number = idx
            self._apply_section_ranges_to_selections()
            
            # Sol panel'i yenile (grid ve detaylar güncellenecek)
            self.question_list_widget.set_selections(self.selections)
            try:
                if hasattr(self, "_sync_section_panel_for_selected_question"):
                    self._sync_section_panel_for_selected_question()
            except Exception:
                pass
            # Aktif soruyu (taşınan) yeni numarasıyla seç ve sağda highlight et
            self._sync_active_question_highlight(question_sel.number)
            
            # PDF preview'ı yenile
            # Taşınan soru hangi sayfaya gittiyse o sayfayı aç
            self._update_pdf_preview(question_number=question_sel.number, preserve_current_page=False)
            
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Soru eklenirken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")
    
    def _update_answer_key(self, page_index: int):
        """Cevap anahtarı kaldırıldı - metod boş bırakıldı"""
        pass
    
    def _find_question_page(self, question_number: int) -> int:
        """Bir sorunun hangi sayfada olduğunu bul (0-indexed). Kaynak: export edilen temp PDF."""
        try:
            qn = int(question_number)
        except Exception:
            return 0

        # Use cached map if available
        if qn in (self._question_page_map or {}):
            return int(self._question_page_map.get(qn, 0))

        # Fallback: fast per-question lookup from current temp PDF (no full scan)
        try:
            if self.temp_pdf_path and os.path.exists(self.temp_pdf_path):
                doc = fitz.open(self.temp_pdf_path)
                try:
                    token = f"TMID:{qn}"
                    found = None
                    for p_idx in range(int(doc.page_count)):
                        try:
                            page = doc.load_page(p_idx)
                            hits = page.search_for(token) or []
                            if hits:
                                found = int(p_idx)
                                break
                        except Exception:
                            continue
                    if self._question_page_map is None:
                        self._question_page_map = {}
                    if found is not None:
                        self._question_page_map[int(qn)] = int(found)
                finally:
                    doc.close()
                return int((self._question_page_map or {}).get(qn, 0))
        except Exception:
            pass
        return 0

    def _build_question_page_map_from_doc(self, doc: fitz.Document) -> Dict[int, int]:
        """Scan exported PDF and map question number -> page index."""
        page_map: Dict[int, int] = {}
        try:
            for p_idx in range(int(doc.page_count)):
                try:
                    page = doc.load_page(p_idx)
                    img_rects: List[fitz.Rect] = []
                    for img in page.get_images(full=True):
                        xref = img[0]
                        try:
                            img_rects.extend(page.get_image_rects(xref) or [])
                        except Exception:
                            continue

                    words = page.get_text("words") or []
                    num_words: List[Tuple[int, float, float, float, float]] = []
                    for w in words:
                        try:
                            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], str(w[4])
                        except Exception:
                            continue
                        t = (txt or "").strip()
                        if t.startswith("TMID:") and t[5:].isdigit():
                            try:
                                num = int(t[5:])
                            except Exception:
                                continue
                            num_words.append((num, float(x0), float(y0), float(x1), float(y1)))

                    # Prefer numbers that can be matched to an image on the right
                    for num, nx0, ny0, nx1, ny1 in num_words:
                        best_r = None
                        best_dx = None
                        n_h = max(1e-6, (ny1 - ny0))
                        for r in img_rects:
                            if float(r.x0) < float(nx1):
                                continue
                            overlap = min(float(r.y1), float(ny1)) - max(float(r.y0), float(ny0))
                            if overlap <= 0 or overlap < 0.25 * n_h:
                                continue
                            dx = float(r.x0) - float(nx1)
                            if best_dx is None or dx < best_dx:
                                best_dx = dx
                                best_r = r
                        if best_r is not None:
                            page_map.setdefault(int(num), int(p_idx))

                    # Fallback: if no matches, still record seen numbers
                    if not img_rects:
                        for num, *_ in num_words:
                            page_map.setdefault(int(num), int(p_idx))
                except Exception:
                    continue
        except Exception:
            pass
        return page_map
    
    def _prepare_preview(self):
        """Eski preview metodunu koru (geriye dönük uyumluluk için)"""
        # Yeni tasarımda kullanılmıyor, ama eski kod hala referans edebilir
        self._update_pdf_preview()
    
    def _organize_into_pages_pdf_export_logic(self, questions: List[PreviewQuestion]) -> List[List[PreviewQuestion]]:
        """
        Ortak layout fonksiyonunu kullanarak soruları sayfalara ayır.
        PDF export ile aynı mantığı kullanır (compute_layout).
        """
        try:
            from testmaker.services.pdf_exporter import compute_layout
            
            if not self.export_options or not questions:
                return [[q] for q in questions] if questions else [[]]
            
            # Soruları 1'den başlayarak numaralandır
            for idx, q in enumerate(questions):
                q.selection.number = idx + 1

            # PDF'de görünen numaraları (display_number) hesapla.
            # Bölüm başlangıcında 'restart numbering' seçildiyse 1'den başlat.
            display_counter = 1
            for q in questions:
                try:
                    sec_title = (getattr(q.selection, "section_title", "") or "").strip()
                    sec_enabled = bool(getattr(q.selection, "section_enabled", False)) and bool(sec_title)
                    sec_restart = bool(getattr(q.selection, "section_restart_numbering", False))
                    if sec_enabled and sec_restart:
                        display_counter = 1
                except Exception:
                    pass
                try:
                    q.display_number = int(display_counter)
                except Exception:
                    q.display_number = display_counter
                display_counter += 1
            
            # Render DPI'yi kullan: zoom = render_dpi / 72.0
            render_dpi = getattr(self, 'render_dpi', 72.0)
            zoom = render_dpi / 72.0
            
            # Soru boyutlarını hesapla (preview'daki cropped_pixmap'ten)
            question_dimensions = []
            for q_idx, q in enumerate(questions):
                orig_w_px = q.cropped_pixmap.width()
                orig_h_px = q.cropped_pixmap.height()
                
                # Geçersiz boyutlar için minimum değerler
                if orig_w_px <= 0:
                    orig_w_px = 100
                if orig_h_px <= 0:
                    orig_h_px = 100
                
                # Custom gap ve display_scale
                custom_gap_after_pt = q.custom_gap_after_pt
                raw_display_scale = getattr(q.selection, "display_scale", None)
                display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                
                question_dimensions.append((q_idx, orig_w_px, orig_h_px, custom_gap_after_pt, display_scale))
            
            # Ortak layout fonksiyonunu kullan
            layout_result = compute_layout(
                question_dimensions=question_dimensions,
                opts=self.export_options,
                zoom=zoom,
                render_dpi=render_dpi,
                selections=self.selections,  # Soru numaralarını almak için
            )
            
            # Layout sonuçlarını PreviewQuestion formatına dönüştür
            # Önce layout bilgilerini question_index'e göre sırala
            layout_by_index = {layout.question_index: layout for layout in layout_result.question_layouts}
            
            # Sayfalara göre grupla
            pages: List[List[PreviewQuestion]] = []
            for page_indices in layout_result.pages:
                page_questions = []
                for question_index in page_indices:
                    if question_index < len(questions):
                        q = questions[question_index]
                        layout = layout_by_index.get(question_index)
                        if layout:
                            # Layout bilgilerini PreviewQuestion'a kaydet
                            q.col_num = layout.col_idx
                            q.page_num = layout.page_num - 1  # Preview'da 0'dan başlar
                        page_questions.append(q)
                pages.append(page_questions)
            
            # Eğer hiç sayfa yoksa boş sayfa ekle
            if not pages:
                pages = [[]]
            
            return pages
            
            # Alt sınır: Footer'ın üst çizgisi (PDF export ile aynı)
            footer_y_top_pt = mb_pt + 35.0  # Footer'ın üst çizgisi
            # Sorular footer'ın üst çizgisinin en az 2mm üstünde olmalı
            min_gap_above_footer_pt = mm_to_pt(2.0)  # En az 2mm
            effective_bottom_pt = footer_y_top_pt + min_gap_above_footer_pt
            
            # Sütun altında kalan boşluk kuralları (son soru ile footer arası)
            min_bottom_gap_pt = mm_to_pt(3.0)   # Minimum 3mm
            max_bottom_gap_pt = mm_to_pt(30.0)  # Maksimum 30mm
            
            # Sütun genişliği hesaplama (soldan sağa eşit sütunlar)
            content_width_pt = page_w_pt - ml_pt - mr_pt
            if cols > 1:
                # Sütunlar arası boşluklar: (cols - 1) adet
                total_gap_width = (cols - 1) * col_gap_pt
                col_w_pt = (content_width_pt - total_gap_width) / cols
            else:
                col_w_pt = content_width_pt
            
            # Sütun X pozisyonlarını hesapla (soldan sağa)
            column_x_positions = []
            for col_idx in range(cols):
                x_pos = ml_pt + col_idx * (col_w_pt + col_gap_pt)
                column_x_positions.append(x_pos)
            
            # Header yüksekliği - PDF export ile aynı hesaplama
            def calculate_y_start(page_num: int) -> float:
                """PDF export'taki _draw_header ile aynı y başlangıç değerini hesapla"""
                if page_num == 0:  # İlk sayfa
                    return page_h_pt - mt_pt - 84.0  # PDF export ile uyumlu
                else:
                    # Diğer sayfalarda: header_y_bottom = page_h - mt - 40.0
                    # contentStartY = header_y_bottom - headerBottomGapPt
                    header_bottom_gap_pt = self.export_options.header_bottom_gap_pt()
                    return page_h_pt - mt_pt - 40.0 - header_bottom_gap_pt
            
            # YENİ ALGORİTMA: Soldan sağa sütunlar, yukarıdan aşağıya sorular
            page_num = 0
            col_idx = 0  # En soldaki sütundan başla (0)
            y = calculate_y_start(0)  # İlk sayfa başlangıç pozisyonu
            
            # Her sütun için son sorunun alt kenarını takip et
            prev_bottom_by_col = {}  # {col_idx: y_bottom} - Her sütun için son sorunun alt kenarı (PDF koordinat sisteminde)
            
            def new_page():
                """Yeni sayfa oluştur, 1. sütundan başla"""
                nonlocal page_num, col_idx, y, prev_bottom_by_col
                if current_page:
                    pages.append(current_page[:])
                current_page.clear()
                page_num += 1
                col_idx = 0  # Yeni sayfada 1. sütundan başla
                y = calculate_y_start(page_num)
                prev_bottom_by_col.clear()  # Yeni sayfa başı, tüm sütunlar için alt kenar bilgisi yok
            
            def next_column():
                """Bir sonraki sütuna geç, eğer sütun yoksa yeni sayfa"""
                nonlocal col_idx, y, prev_bottom_by_col, page_num
                col_idx += 1
                if col_idx >= cols:
                    # Tüm sütunlar doldu, yeni sayfa
                    new_page()
                else:
                    # Bir sonraki sütuna geç
                    # Eğer bu sütunda bir önceki soru varsa onun altından başla, yoksa yukarıdan başla
                    if col_idx in prev_bottom_by_col:
                        y = prev_bottom_by_col[col_idx]  # Bir önceki sorunun altından başla
                    else:
                        y = calculate_y_start(page_num)  # Sütun başı, yukarıdan başla
            
            # Soruları sırayla yerleştir (1'den başlayarak numaralandırılmış)
            for q_idx, q in enumerate(questions):
                # Soru boyutunu hesapla (PDF export mantığı ile aynı)
                orig_w_px = q.cropped_pixmap.width()
                orig_h_px = q.cropped_pixmap.height()
                
                # ÖNEMLİ: Soruları ASLA atlama! Geçersiz boyutlu sorular için minimum boyutlar kullan
                if orig_w_px <= 0:
                    orig_w_px = 100
                if orig_h_px <= 0:
                    orig_h_px = 100
                
                raw_display_scale = getattr(q.selection, "display_scale", None)
                display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                
                # PDF export mantığı: ÖNCE px -> pt, SONRA display_scale, SONRA text_scale
                img_w_pt = (orig_w_px / zoom) * display_scale
                img_h_pt = (orig_h_px / zoom) * display_scale
                
                # Sonra text_scale uygula
                draw_w_pt = img_w_pt * text_scale
                draw_h_pt = img_h_pt * text_scale
                
                # Numara genişliği
                number_text = f"{getattr(q, 'display_number', q.selection.number)}."
                number_width_pt = max(6.0, len(number_text) * 6.0)
                number_gap_pt = 4.0
                right_padding_pt = 4.0
                available_width_pt = col_w_pt - number_width_pt - number_gap_pt - right_padding_pt
                
                # Görsel genişliğine sığdır
                if draw_w_pt > available_width_pt:
                    scale_factor = available_width_pt / draw_w_pt
                    draw_w_pt = available_width_pt
                    draw_h_pt = draw_h_pt * scale_factor
                
                # Numara yüksekliği - PDF export ile aynı hesaplama (gerçek font yüksekliği)
                # PDF export'ta: font_ascent_num + font_descent_num
                # font_size_num = 10.0
                # Yaklaşık olarak: font_ascent ~700/1000 * 10 = 7pt, font_descent ~200/1000 * 10 = 2pt
                # Toplam: ~9-10pt, ama güvenli olması için 12pt kullanılıyor gibi görünüyor
                # PDF export'ta gerçek font yüksekliği hesaplanıyor, bu yüzden aynısını yapalım
                # Şimdilik yaklaşık değer: 10pt font için ~10pt yükseklik
                # Ama PDF export'taki gibi tam hesaplama yapmak için font metriklerini kullanmalıyız
                # Qt'de font metrikleri farklı, bu yüzden PDF export ile aynı yaklaşık değeri kullanalım
                # PDF export'ta: text_height = font_ascent_num + font_descent_num
                # Roboto-Bold 10pt için yaklaşık: ascent ~700, descent ~200 -> (700+200)/1000 * 10 = 9pt
                # Ama güvenli olması için 10pt kullanıyoruz
                box_h_pt = 10.0  # PDF export'taki gerçek font yüksekliğine yakın değer (12.0 yerine)
                
                # Boşluk hesaplama: Özel boşluk varsa clamp et, yoksa varsayılan
                if q.custom_gap_after_pt is not None:
                    actual_gap_after_pt = clamp_gap_pt(q.custom_gap_after_pt, question_gap_pt)
                else:
                    actual_gap_after_pt = clamp_gap_pt(None, question_gap_pt)
                
                # Gerekli yükseklik
                needed_pt = max(box_h_pt, draw_h_pt) + actual_gap_after_pt
                if self.export_options.spaced and self.export_options.draw_separators:
                    needed_pt += 14.0
                
                # YENİ ALGORİTMA: Mevcut sütunda sığıyor mu kontrol et
                # ÖNCE: Eğer bu sütunda bir önceki soru varsa, y pozisyonunu onun altından başlat
                if col_idx in prev_bottom_by_col:
                    # Bu sütunda bir önceki soru var, y pozisyonunu onun altından başlat
                    prev_bottom = prev_bottom_by_col[col_idx]
                    y = prev_bottom  # Bir önceki sorunun altından başla
                
                # ŞİMDİ: Mevcut sütunda sığıyor mu kontrol et
                # Alt sınır: footer'ın üst çizgisi (effective_bottom_pt)
                # ÖNEMLİ: Soru yerleştirilmeden önce sığma kontrolü yapılmalı
                # Soru yüksekliği: max(box_h_pt, draw_h_pt)
                # Gerekli alan: soru yüksekliği + boşluk
                question_height_pt = max(box_h_pt, draw_h_pt)
                required_space_pt = question_height_pt + actual_gap_after_pt
                if self.export_options.spaced and self.export_options.draw_separators:
                    required_space_pt += 14.0
                
                # Soru sığıyor mu? (y - required_space_pt >= effective_bottom_pt)
                # ÖNEMLİ: next_column() çağrıldıktan sonra y pozisyonunu tekrar kontrol et
                while (y - required_space_pt) < effective_bottom_pt:
                    # Mevcut sütuna sığmıyor, bir sonraki sütuna geç
                    next_column()
                    # next_column() sonrası y pozisyonunu tekrar kontrol et
                    # Eğer bu sütunda bir önceki soru varsa onun altından başla
                    if col_idx in prev_bottom_by_col:
                        y = prev_bottom_by_col[col_idx]
                    # Eğer hala sığmıyorsa döngü devam eder (yeni sayfaya geçilir)
                
                # y_top: Yeni sorunun üst kenarı (PDF koordinat sisteminde)
                y_top = y
                
                # Soruyu sayfaya ekle
                current_page.append(q)
                q.col_num = col_idx  # Sütun numarasını kaydet
                
                # Y pozisyonunu güncelle (soru yerleştirildikten sonra)
                y_bottom = y_top - question_height_pt - actual_gap_after_pt
                
                # Optional separator (eğer varsa, y_bottom'dan çıkar)
                separator_height_pt = 0.0
                if self.export_options.spaced and self.export_options.draw_separators:
                    separator_height_pt = 14.0
                    y_bottom -= separator_height_pt
                
                # ÖNEMLİ: Alt sınır kontrolü - soru footer'ın üst çizgisinin altına geçmemeli
                # Yukarıdaki while döngüsü bunu önlemeli, ama yine de kesin kontrol yapalım
                if y_bottom < effective_bottom_pt:
                    print(f"DEBUG: UYARI: Soru {q_idx + 1} (numara {q.selection.number}) footer sınırını geçiyor! (y_bottom={y_bottom:.1f}, effective_bottom={effective_bottom_pt:.1f})")
                    # Soruyu footer sınırının üstüne yerleştir
                    y_bottom = effective_bottom_pt
                    y_top = y_bottom + question_height_pt + actual_gap_after_pt + separator_height_pt
                    # Y pozisyonunu güncelle
                    y = y_bottom
                    # UYARI: Bu durumda soru çok büyük olabilir, bir sonraki soru için kontrol et
                
                y = y_bottom  # Bir sonraki soru için başlangıç pozisyonu
                
                # Bu sorunun alt kenarını kaydet (bir sonraki soru için çakışma kontrolü için)
                prev_bottom_by_col[col_idx] = y_bottom
                
                # ÖNEMLİ: Bir sonraki soru için aynı sütunda devam et (yukarıdan aşağıya)
                # Sütun değiştirme sadece soru sığmadığında yapılır (while döngüsünde zaten yapılıyor)
                # Burada sütun değiştirmiyoruz, bir sonraki soru aynı sütunda devam edecek
            
            # Son sayfayı ekle
            if current_page:
                pages.append(current_page)
            
            # Eğer hiç sayfa yoksa boş sayfa ekle
            if not pages:
                pages = [[]]
            
            # ÖNEMLİ: Tüm soruların yerleştirildiğini kontrol et (ASLA soru kaybetme)
            total_q_in_pages = sum(len(page) for page in pages)
            if total_q_in_pages != len(questions):
                print(f"UYARI: Tüm sorular yerleştirilmedi! Giriş: {len(questions)} soru, Yerleştirilen: {total_q_in_pages} soru")
                # Eksik soruları son sayfaya ekle
                placed_questions = set()
                for page in pages:
                    for q in page:
                        placed_questions.add(id(q))
                missing_questions = [q for q in questions if id(q) not in placed_questions]
                if missing_questions:
                    if pages:
                        pages[-1].extend(missing_questions)
                    else:
                        pages.append(missing_questions)
            
            print(f"DEBUG: _organize_into_pages_pdf_export_logic tamamlandı - {len(pages)} sayfa, toplam {total_q_in_pages} soru")
            
            # Sütun içinde boşlukları eşit dağıt (her sütun için ayrı ayrı)
            # Bu işlem sadece görsel düzenleme için, yerleştirme zaten yapıldı
            pages = self._distribute_gaps_evenly_in_columns(
                pages, page_w_pt, page_h_pt, ml_pt, mr_pt, mt_pt, mb_pt,
                col_w_pt, cols, zoom, text_scale, question_gap_pt, render_dpi
            )
            
            return pages
        except Exception as e:
            import traceback
            print(f"Hata: Sayfalara ayırma sırasında hata: {e}\n{traceback.format_exc()}")
            # Hata durumunda her soruyu ayrı sayfaya koy
            return [[q] for q in questions] if questions else [[]]
    
    def _distribute_gaps_evenly_in_columns(self, pages: List[List[PreviewQuestion]], 
                                          page_w_pt: float, page_h_pt: float,
                                          ml_pt: float, mr_pt: float, mt_pt: float, mb_pt: float,
                                          col_w_pt: float, cols: int, zoom: float, text_scale: float,
                                          question_gap_pt: float, render_dpi: float) -> List[List[PreviewQuestion]]:
        """
        Her sütun için boşlukları eşit dağıt (6mm-50mm arası).
        Ayrıca, son soru ile footer arasındaki boşluğu kontrol et (3-30mm arası olmalı).
        Bu fonksiyon sadece görsel düzenleme için, asıl yerleştirme _organize_into_pages_pdf_export_logic'de yapıldı.
        """
        from testmaker.services.pdf_exporter import mm_to_pt, clamp_gap_pt, MIN_GAP_PT, MAX_GAP_PT
        
        footer_y_top_pt = mb_pt + 35.0  # Footer'ın üst çizgisi
        min_gap_above_footer_pt = mm_to_pt(2.0)  # En az 2mm üstünde
        effective_bottom_pt = footer_y_top_pt + min_gap_above_footer_pt
        
        # Sütun altında kalan boşluk kuralları (son soru ile footer arası)
        min_bottom_gap_pt = mm_to_pt(3.0)   # Minimum 3mm
        max_bottom_gap_pt = mm_to_pt(30.0)  # Maksimum 30mm
        
        def calculate_y_start(page_num: int) -> float:
            if page_num == 0:
                return page_h_pt - mt_pt - 84.0
            else:
                header_bottom_gap_pt = self.export_options.header_bottom_gap_pt()
                return page_h_pt - mt_pt - 40.0 - header_bottom_gap_pt
        
        # Her sayfa için, her sütun için boşlukları eşit dağıt
        for page_idx, page_questions in enumerate(pages):
            if not page_questions:
                continue
            
            # Sayfadaki soruları sütunlara göre grupla (sırayı koruyarak)
            questions_by_col = {}  # {col_idx: [questions]}
            for q in page_questions:
                col_idx = getattr(q, 'col_num', 0)
                if col_idx not in questions_by_col:
                    questions_by_col[col_idx] = []
                questions_by_col[col_idx].append(q)
            
            # Her sütundaki soruları y pozisyonuna göre sırala (yukarıdan aşağıya)
            # Not: Bu fonksiyon sadece boşlukları ayarlıyor, sorular zaten yerleştirilmiş
            
            # Her sütun için boşlukları eşit dağıt ve son soru ile footer arasındaki boşluğu kontrol et
            for col_idx, col_questions in questions_by_col.items():
                if len(col_questions) == 0:
                    continue
                
                # Soru yüksekliklerini hesapla
                question_heights = []
                gaps_after = []  # Mevcut boşluklar
                for q in col_questions:
                    orig_w_px = max(100, q.cropped_pixmap.width())
                    orig_h_px = max(100, q.cropped_pixmap.height())
                    raw_display_scale = getattr(q.selection, "display_scale", None)
                    display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                    img_h_pt = (orig_h_px / zoom) * display_scale
                    draw_h_pt = img_h_pt * text_scale
                    box_h_pt = 10.0  # PDF export ile aynı (gerçek font yüksekliği)
                    question_heights.append(max(box_h_pt, draw_h_pt))
                    # Mevcut boşluk
                    if q.custom_gap_after_pt is not None:
                        gaps_after.append(clamp_gap_pt(q.custom_gap_after_pt, question_gap_pt))
                    else:
                        gaps_after.append(clamp_gap_pt(None, question_gap_pt))
                
                # Kullanılabilir alan
                y_start = calculate_y_start(page_idx)
                available_height = y_start - effective_bottom_pt  # effective_bottom_pt kullan (2mm üstünde)
                
                # Toplam soru yüksekliği + mevcut boşluklar
                total_question_height = sum(question_heights)
                total_current_gaps = sum(gaps_after[:-1]) if len(gaps_after) > 1 else 0  # Son soru hariç
                total_used_height = total_question_height + total_current_gaps
                
                # Son soru ile footer arasındaki mevcut boşluk
                current_bottom_gap_pt = available_height - total_used_height
                
                # Eğer son soru ile footer arasındaki boşluk 3-30mm arası değilse, düzenle
                if current_bottom_gap_pt < min_bottom_gap_pt:
                    # Boşluk çok az, sorular arası boşlukları azalt ve son soru ile footer arasına ekle
                    needed_additional = min_bottom_gap_pt - current_bottom_gap_pt
                    if len(col_questions) > 1:
                        # Sorular arası boşluklardan al (eşit dağıt)
                        reduction_per_gap = needed_additional / (len(col_questions) - 1)
                        for i, q in enumerate(col_questions[:-1]):  # Son soru hariç
                            if q.custom_gap_after_pt is not None:
                                q.custom_gap_after_pt = max(MIN_GAP_PT, q.custom_gap_after_pt - reduction_per_gap)
                            else:
                                q.custom_gap_after_pt = max(MIN_GAP_PT, question_gap_pt - reduction_per_gap)
                elif current_bottom_gap_pt > max_bottom_gap_pt:
                    # Boşluk çok fazla, sorular arası boşlukları artır
                    excess = current_bottom_gap_pt - max_bottom_gap_pt
                    if len(col_questions) > 1:
                        # Fazlalığı sorular arası boşluklara ekle (eşit dağıt)
                        addition_per_gap = excess / (len(col_questions) - 1)
                        for i, q in enumerate(col_questions[:-1]):  # Son soru hariç
                            if q.custom_gap_after_pt is not None:
                                q.custom_gap_after_pt = min(MAX_GAP_PT, q.custom_gap_after_pt + addition_per_gap)
                            else:
                                q.custom_gap_after_pt = min(MAX_GAP_PT, question_gap_pt + addition_per_gap)
                
                # Eğer tek soru varsa, sadece son soru ile footer arasındaki boşluğu kontrol et
                if len(col_questions) == 1:
                    # Tek soru için, footer ile arasındaki boşluk 3-30mm arası olmalı
                    single_q_height = question_heights[0]
                    single_bottom_gap = available_height - single_q_height
                    if single_bottom_gap < min_bottom_gap_pt or single_bottom_gap > max_bottom_gap_pt:
                        # Tek soru için boşluk uygun değil, ama bu fonksiyon sadece boşlukları ayarlıyor
                        # Soruları yeniden yerleştirmek için _organize_into_pages_pdf_export_logic çağrılmalı
                        print(f"DEBUG: UYARI: Tek soru için footer boşluğu uygun değil: {single_bottom_gap/mm_to_pt(1.0):.1f}mm")
                    continue
                
                # Çoklu soru için eşit dağıtım yap (son soru ile footer arasındaki boşluk zaten ayarlandı)
                # Şimdi sorular arası boşlukları eşit dağıt
                total_question_height = sum(question_heights)
                # Son soru ile footer arasındaki boşluk için alan ayır (3-30mm arası)
                target_bottom_gap_pt = (min_bottom_gap_pt + max_bottom_gap_pt) / 2.0  # Ortalama: 16.5mm
                remaining_for_gaps = available_height - total_question_height - target_bottom_gap_pt
                
                if remaining_for_gaps > 0 and len(col_questions) > 1:
                    num_gaps = len(col_questions) - 1
                    gap_per_question = remaining_for_gaps / num_gaps
                    
                    # Her soru için boşluk hesapla (clamp ile)
                    for i, q in enumerate(col_questions[:-1]):  # Son soru hariç
                        if q.custom_gap_after_pt is None:
                            # Varsayılan boşluk + eşit dağıtım
                            gap = question_gap_pt + gap_per_question
                            q.custom_gap_after_pt = clamp_gap_pt(gap, question_gap_pt)
                        else:
                            # Mevcut boşluğu koru ama eşit dağıtıma göre ayarla
                            gap = q.custom_gap_after_pt + gap_per_question
                            q.custom_gap_after_pt = clamp_gap_pt(gap, question_gap_pt)
        
        return pages
    
    def _optimize_all_pages_comprehensive(self, pages: List[List[PreviewQuestion]], all_questions: List[PreviewQuestion],
                                           page_w_pt: float, page_h_pt: float, ml_pt: float, mr_pt: float, mt_pt: float, mb_pt: float,
                                           col_w_pt: float, col_gap_pt: float, cols: int, zoom: float, text_scale: float,
                                           left_columns_count: int, x_line_center: float, calculate_y_start, question_gap_pt: float,
                                           render_dpi: float) -> List[List[PreviewQuestion]]:
        """
        TÜM SAYFALAR İÇİN kapsamlı optimizasyon: 
        - Her sayfa için sonraki sayfanın sorularını geri çek
        - Sayfalar arası çakışma kontrolü yap
        - İteratif olarak optimize et (birden fazla iterasyon)
        """
        try:
            if len(pages) <= 1:
                return pages  # Tek sayfa varsa optimizasyon yapmaya gerek yok
            
            print(f"DEBUG: TÜM SAYFALAR kapsamlı optimizasyon başladı - {len(pages)} sayfa")
            
            # Tüm soruları sırayla al (sayfa yapısındaki sıraya göre)
            all_questions_ordered = []
            for page in pages:
                all_questions_ordered.extend(page)
            
            if not all_questions_ordered:
                return pages
            
            # Tüm soruları yeniden yerleştir (çakışma kontrolü ile) - tek seferlik
            # Bu işlem tüm soruları sırayla yerleştirir ve sayfalar arası çakışmaları düzeltir
            optimized_pages = self._reorganize_all_questions_dynamic(
                all_questions_ordered, page_w_pt, page_h_pt, ml_pt, mr_pt, mt_pt, mb_pt,
                col_w_pt, col_gap_pt, cols, zoom, text_scale,
                left_columns_count, x_line_center, calculate_y_start, question_gap_pt
            )
            
            print(f"DEBUG: TÜM SAYFALAR kapsamlı optimizasyon tamamlandı - {len(optimized_pages)} sayfa (önceki: {len(pages)})")
            return optimized_pages if optimized_pages else pages
            
            # Birden fazla iterasyon yap (tüm sayfalar optimize olana kadar)
            max_iterations = 5  # Maksimum iterasyon sayısı
            for iteration in range(max_iterations):
                changed = False  # Bu iterasyonda değişiklik oldu mu?
                
                # Geri optimizasyon: Son sayfadan başla, geriye doğru git
                for page_idx in range(len(pages_copy) - 1, -1, -1):
                    current_page = pages_copy[page_idx]
                    if not current_page:
                        continue
                    
                    # Bu sayfanın her sütununda kalan boş alanı hesapla
                    y_start = calculate_y_start(page_idx)
                    col_final_ys = {}  # Her sütun için son y pozisyonu {col_idx: y}
                    
                    # Bu sayfadaki soruları yerleştir ve her sütunun son y pozisyonunu hesapla
                    for q in current_page:
                        # Soru boyutunu hesapla (PDF export mantığı ile aynı)
                        orig_w_px = q.cropped_pixmap.width()
                        orig_h_px = q.cropped_pixmap.height()
                        
                        if orig_w_px <= 0 or orig_h_px <= 0:
                            continue
                        
                        raw_display_scale = getattr(q.selection, "display_scale", None)
                        display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                        img_w_pt = (orig_w_px / zoom) * display_scale
                        img_h_pt = (orig_h_px / zoom) * display_scale
                        draw_w_pt = img_w_pt * text_scale
                        draw_h_pt = img_h_pt * text_scale
                        
                        number_text = f"{getattr(q, 'display_number', getattr(q.selection, 'number', '?'))}."
                        number_width_pt = max(6.0, len(number_text) * 6.0)
                        available_width_pt = col_w_pt - number_width_pt - 4.0 - 4.0
                        
                        if draw_w_pt > available_width_pt:
                            scale_factor = available_width_pt / draw_w_pt
                            draw_w_pt = available_width_pt
                            draw_h_pt = draw_h_pt * scale_factor
                        
                        box_h_pt = 10.0  # PDF export ile aynı (gerçek font yüksekliği)
                        actual_gap_pt = q.custom_gap_after_pt if q.custom_gap_after_pt is not None else question_gap_pt
                        needed_pt = max(box_h_pt, draw_h_pt) + actual_gap_pt
                        if self.export_options.spaced and self.export_options.draw_separators:
                            needed_pt += 14.0
                        
                        # Bu sorunun sütununu bul
                        col_idx = getattr(q, 'col_num', 0) if hasattr(q, 'col_num') else 0
                        if col_idx not in col_final_ys:
                            col_final_ys[col_idx] = y_start
                        
                        # Y pozisyonunu güncelle (PDF koordinat sisteminde y azalır)
                        col_final_ys[col_idx] = col_final_ys[col_idx] - needed_pt
                    
                    # Sonraki sayfanın sorularını bu sayfaya taşı
                    if page_idx < len(pages_copy) - 1:
                        next_page = pages_copy[page_idx + 1]
                        if next_page:
                            # Her sütun için kalan boş alanı hesapla
                            for col_idx in range(cols):
                                col_final_y = col_final_ys.get(col_idx, y_start)
                                remaining_space = col_final_y - mb_pt
                                
                                if remaining_space > 20.0:  # Minimum 20pt boş alan varsa
                                    # Sonraki sayfanın bu sütuna sığabilecek sorularını bul
                                    moved_questions = []
                                    space_used = 0.0
                                    
                                    for q in next_page:
                                        # Bu soru aynı sütunda mı? (veya sırayla yerleştirilebilir mi?)
                                        q_col_idx = getattr(q, 'col_num', 0) if hasattr(q, 'col_num') else 0
                                        # Şu an için tüm soruları kontrol et (sonra sütun bazlı optimize edilebilir)
                                        
                                        # Soru boyutunu hesapla
                                        orig_w_px = q.cropped_pixmap.width()
                                        orig_h_px = q.cropped_pixmap.height()
                                        
                                        if orig_w_px <= 0 or orig_h_px <= 0:
                                            continue
                                        
                                        raw_display_scale = getattr(q.selection, "display_scale", None)
                                        display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                                        img_w_pt = (orig_w_px / zoom) * display_scale
                                        img_h_pt = (orig_h_px / zoom) * display_scale
                                        draw_w_pt = img_w_pt * text_scale
                                        draw_h_pt = img_h_pt * text_scale
                                        
                                        number_text = f"{getattr(q, 'display_number', getattr(q.selection, 'number', '?'))}."
                                        number_width_pt = max(6.0, len(number_text) * 6.0)
                                        available_width_pt = col_w_pt - number_width_pt - 4.0 - 4.0
                                        
                                        if draw_w_pt > available_width_pt:
                                            scale_factor = available_width_pt / draw_w_pt
                                            draw_w_pt = available_width_pt
                                            draw_h_pt = draw_h_pt * scale_factor
                                        
                                        box_h_pt = 10.0  # PDF export ile aynı (gerçek font yüksekliği)
                                        actual_gap_pt = q.custom_gap_after_pt if q.custom_gap_after_pt is not None else question_gap_pt
                                        needed_pt = max(box_h_pt, draw_h_pt) + actual_gap_pt
                                        if self.export_options.spaced and self.export_options.draw_separators:
                                            needed_pt += 14.0
                                        
                                        # Bu soru kalan alana sığıyor mu?
                                        if space_used + needed_pt <= remaining_space:
                                            moved_questions.append(q)
                                            space_used += needed_pt
                                        else:
                                            break  # Sığmıyorsa dur
                                    
                                    # Taşınan soruları bu sayfaya ekle ve sonraki sayfadan çıkar
                                    if moved_questions:
                                        # Sadece ilk sütun için (veya sırayla) taşı
                                        if col_idx == 0 or len(moved_questions) == 1:
                                            for q in moved_questions:
                                                if q in next_page:
                                                    next_page.remove(q)
                                                    current_page.append(q)
                                                    changed = True
                                            print(f"DEBUG: İterasyon {iteration + 1}, Sayfa {page_idx + 1} - {len(moved_questions)} soru sonraki sayfadan taşındı")
                                            break  # Bir iterasyonda sadece bir sütun için taşı
                
                # Eğer bu iterasyonda değişiklik olmadıysa dur
                if not changed:
                    print(f"DEBUG: İterasyon {iteration + 1} - Değişiklik yok, optimizasyon tamamlandı")
                    break
                
                # Boş sayfaları temizle
                pages_copy = [page for page in pages_copy if page]
            
            # Son kontrol: Boş sayfaları temizle
            optimized_pages = [page for page in pages_copy if page]
            
            print(f"DEBUG: TÜM SAYFALAR kapsamlı optimizasyon tamamlandı - {len(optimized_pages)} sayfa (önceki: {len(pages)})")
            return optimized_pages if optimized_pages else pages
            
        except Exception as e:
            import traceback
            print(f"Hata: TÜM SAYFALAR kapsamlı optimizasyon sırasında: {e}\n{traceback.format_exc()}")
            return pages  # Hata durumunda orijinal sayfaları döndür
    
    def _reorganize_all_questions_dynamic(self, questions: List[PreviewQuestion],
                                           page_w_pt: float, page_h_pt: float, ml_pt: float, mr_pt: float, mt_pt: float, mb_pt: float,
                                           col_w_pt: float, col_gap_pt: float, cols: int, zoom: float, text_scale: float,
                                           left_columns_count: int, x_line_center: float, calculate_y_start, question_gap_pt: float) -> List[List[PreviewQuestion]]:
        """
        TÜM soruları dinamik olarak yeniden yerleştir:
        - Her soru için bir önceki sayfadaki son sorularla çakışma kontrolü yap
        - Çakışma varsa, soruyu bir önceki sayfaya taşı veya yeni sayfaya geç
        - Tüm sayfalar için iteratif optimizasyon yap
        """
        try:
            pages = []
            current_page = []
            page_num = 0
            y = calculate_y_start(0)
            col_idx = 0
            prev_q_by_col = {}  # {col_idx: prev_q} - Mevcut sayfa için
            prev_bottom_by_col = {}  # {col_idx: y_bottom} - Mevcut sayfa için
            prev_page_bottom_by_col = {}  # {(page_idx, col_idx): y_bottom} - Önceki sayfalar için
            
            def new_page():
                nonlocal y, col_idx, page_num, prev_q_by_col, prev_bottom_by_col, prev_page_bottom_by_col
                if current_page:
                    # Mevcut sayfanın son sütunlarının alt kenarını kaydet
                    for c_idx in range(cols):
                        if c_idx in prev_bottom_by_col:
                            prev_page_bottom_by_col[(page_num, c_idx)] = prev_bottom_by_col[c_idx]
                            print(f"DEBUG: Sayfa {page_num + 1}, sütun {c_idx} son alt kenarı kaydedildi: {prev_bottom_by_col[c_idx]:.1f}")
                    pages.append(current_page[:])
                current_page.clear()
                page_num += 1
                y = calculate_y_start(page_num)
                col_idx = 0
                prev_q_by_col.clear()
                prev_bottom_by_col.clear()
            
            def next_column():
                nonlocal col_idx, y, prev_q_by_col, prev_bottom_by_col
                col_idx += 1
                if col_idx >= cols:
                    new_page()
                else:
                    y = calculate_y_start(page_num)
                    if col_idx in prev_q_by_col:
                        del prev_q_by_col[col_idx]
                    if col_idx in prev_bottom_by_col:
                        del prev_bottom_by_col[col_idx]
            
            # Tüm soruları sırayla yerleştir
            for q_idx, q in enumerate(questions):
                # Soru boyutunu hesapla
                orig_w_px = q.cropped_pixmap.width()
                orig_h_px = q.cropped_pixmap.height()
                
                if orig_w_px <= 0 or orig_h_px <= 0:
                    continue
                
                raw_display_scale = getattr(q.selection, "display_scale", None)
                display_scale = 1.0 if raw_display_scale is None else float(raw_display_scale)
                img_w_pt = (orig_w_px / zoom) * display_scale
                img_h_pt = (orig_h_px / zoom) * display_scale
                draw_w_pt = img_w_pt * text_scale
                draw_h_pt = img_h_pt * text_scale
                
                number_text = f"{getattr(q, 'display_number', getattr(q.selection, 'number', '?'))}."
                number_width_pt = max(6.0, len(number_text) * 6.0)
                available_width_pt = col_w_pt - number_width_pt - 4.0 - 4.0
                
                if draw_w_pt > available_width_pt:
                    scale_factor = available_width_pt / draw_w_pt
                    draw_w_pt = available_width_pt
                    draw_h_pt = draw_h_pt * scale_factor
                
                box_h_pt = 10.0  # PDF export ile aynı (gerçek font yüksekliği)
                # Boşluk değerini 10-50mm aralığında sınırla
                from testmaker.services.pdf_exporter import mm_to_pt
                min_gap_pt = mm_to_pt(10.0)  # 10 mm
                max_gap_pt = mm_to_pt(50.0)  # 50 mm
                raw_gap_after_pt = q.custom_gap_after_pt if q.custom_gap_after_pt is not None else question_gap_pt
                actual_gap_after_pt = max(min_gap_pt, min(max_gap_pt, raw_gap_after_pt))
                # Eğer kullanıcı manuel olarak ayarlamışsa, değeri güncelle
                if q.custom_gap_after_pt is not None:
                    q.custom_gap_after_pt = actual_gap_after_pt
                # Sorunun yüksekliği (boşluk olmadan - sadece soru içeriği)
                question_height_pt = max(box_h_pt, draw_h_pt)
                # Gerekli toplam yükseklik (soru + boşluk)
                needed_pt = question_height_pt + actual_gap_after_pt
                if self.export_options.spaced and self.export_options.draw_separators:
                    needed_pt += 14.0
                
                # ÖNEMLİ: Sayfaya sığıyor mu? + Bir önceki sayfadaki sorularla çakışma kontrolü
                y_top = y  # Yeni sorunun üst kenarı
                
                # YENİ ALGORİTMA: Önce bir önceki sütuna sığıp sığmadığını kontrol et (boşluğu gözardı ederek)
                # Eğer sorunun yüksekliği (boşluk olmadan) bir önceki sütuna sığıyorsa, oraya taşı
                placed = False
                if col_idx > 0:  # İlk sütun değilse
                    prev_col_idx = col_idx - 1
                    if prev_col_idx in prev_bottom_by_col:
                        prev_col_bottom = prev_bottom_by_col[prev_col_idx]
                        # Sorunun yüksekliği (boşluk olmadan) bir önceki sütuna sığıyor mu?
                        available_in_prev_col = prev_col_bottom - mb_pt
                        if available_in_prev_col >= question_height_pt:
                            # Soru bir önceki sütuna sığıyor - oraya taşı (boşluğu gözardı et)
                            print(f"DEBUG: Soru {q.selection.number} bir önceki sütuna taşınıyor (yükseklik: {question_height_pt:.1f}, mevcut alan: {available_in_prev_col:.1f})")
                            col_idx = prev_col_idx
                            y_top = prev_col_bottom
                            y = y_top
                            placed = True
                
                # Eğer bir önceki sütuna taşınmadıysa, bir önceki sayfaya bak
                if not placed and page_num > 0:  # İlk sayfa değilse
                    prev_page_col_key = (page_num - 1, col_idx)
                    if prev_page_col_key in prev_page_bottom_by_col:
                        prev_page_bottom = prev_page_bottom_by_col[prev_page_col_key]
                        # Yeni sorunun üst kenarı bir önceki sayfanın son sorunun alt kenarından küçük olmalı
                        if y_top >= prev_page_bottom:
                            print(f"DEBUG: ÇAKIŞMA: Soru {q.selection.number} önceki sayfanın son sorularıyla çakışıyor! (y_top={y_top:.1f}, prev_bottom={prev_page_bottom:.1f})")
                            # Çakışma varsa, önce bir önceki sayfaya taşımayı dene
                            # Bir önceki sayfada bu sütunda yer var mı? (sadece soru yüksekliğini kontrol et)
                            if page_num - 1 < len(pages):
                                prev_page = pages[page_num - 1]
                                # Bir önceki sayfanın bu sütunundaki son sorunun alt kenarından sonraki alanı kontrol et
                                available_on_prev_page = prev_page_bottom - mb_pt
                                # Sadece soru yüksekliğini kontrol et (boşluğu gözardı et)
                                if available_on_prev_page >= question_height_pt:
                                    # Bir önceki sayfaya taşı (boşluğu gözardı et)
                                    print(f"DEBUG: Soru {q.selection.number} bir önceki sayfaya taşınıyor (yükseklik: {question_height_pt:.1f}, mevcut alan: {available_on_prev_page:.1f})...")
                                    prev_page.append(q)
                                    # Bir önceki sayfadaki son sorunun alt kenarını güncelle (soru yüksekliği + boşluk)
                                    new_bottom = prev_page_bottom - needed_pt
                                    prev_bottom_by_col[col_idx] = new_bottom
                                    prev_page_bottom_by_col[(page_num - 1, col_idx)] = new_bottom
                                    # Mevcut sayfadan çıkar (zaten eklenmedi)
                                    page_num = len(pages) - 1  # Bir önceki sayfa
                                    current_page = prev_page
                                    y_top = prev_page_bottom
                                    y = y_top
                                    placed = True
                                else:
                                    # Bir önceki sayfaya sığmıyor, yeni sayfada yerleştir ama çakışmayı düzelt
                                    y_top = prev_page_bottom - 0.1
                                    y = y_top
                                    print(f"DEBUG: Çakışma düzeltildi - y_top={y_top:.1f}")
                            else:
                                # Bir önceki sayfa yok, yeni sayfada yerleştir ama çakışmayı düzelt
                                y_top = prev_page_bottom - 0.1
                                y = y_top
                                print(f"DEBUG: Çakışma düzeltildi - y_top={y_top:.1f}")
                
                # Eğer hala yerleştirilmediyse, mevcut sütunda bir önceki soruyla çakışma kontrolü yap
                if not placed:
                    # Sayfaya sığıyor mu? (normal kontrol)
                    if (y_top - needed_pt) < mb_pt:
                        # Sütun değiştir veya yeni sayfa oluştur
                        if col_idx < cols - 1:
                            next_column()
                            y_top = y
                            if (y_top - needed_pt) < mb_pt:
                                new_page()
                                y_top = y
                        else:
                            new_page()
                            y_top = y
                    
                    # AYNI SAYFADA bir önceki soruyla çakışma kontrolü
                    if col_idx in prev_bottom_by_col:
                        prev_bottom = prev_bottom_by_col[col_idx]
                        if y_top >= prev_bottom:
                            print(f"DEBUG: ÇAKIŞMA: Soru {q.selection.number} aynı sayfadaki bir önceki soruyla çakışıyor! (y_top={y_top:.1f}, prev_bottom={prev_bottom:.1f})")
                            # Çakışma varsa, bir önceki sütuna taşımayı dene (boşluğu gözardı ederek)
                            if col_idx > 0:
                                prev_col_idx = col_idx - 1
                                if prev_col_idx in prev_bottom_by_col:
                                    prev_col_bottom = prev_bottom_by_col[prev_col_idx]
                                    available_in_prev_col = prev_col_bottom - mb_pt
                                    if available_in_prev_col >= question_height_pt:
                                        # Bir önceki sütuna taşı
                                        print(f"DEBUG: Soru {q.selection.number} bir önceki sütuna taşınıyor (çakışma nedeniyle)")
                                        col_idx = prev_col_idx
                                        y_top = prev_col_bottom
                                        y = y_top
                                    else:
                                        # Bir önceki sütuna sığmıyor, çakışmayı düzelt
                                        y_top = prev_bottom - 0.1
                                        y = y_top
                                        print(f"DEBUG: Aynı sayfa içi çakışma düzeltildi - y_top={y_top:.1f}")
                                else:
                                    # Bir önceki sütunda soru yok, taşı
                                    col_idx = prev_col_idx
                                    y_top = calculate_y_start(page_num)
                                    y = y_top
                            else:
                                # İlk sütun, çakışmayı düzelt
                                y_top = prev_bottom - 0.1
                                y = y_top
                                print(f"DEBUG: Aynı sayfa içi çakışma düzeltildi - y_top={y_top:.1f}")
                            
                            # Eğer bu düzeltme sonrası sayfaya sığmıyorsa, sütun/sayfa değiştir
                            if (y_top - needed_pt) < mb_pt:
                                if col_idx < cols - 1:
                                    next_column()
                                    y_top = y
                                else:
                                    new_page()
                                    y_top = y
                
                # Soruyu sayfaya ekle
                current_page.append(q)
                q.col_num = col_idx
                
                # Y pozisyonunu güncelle
                y_bottom = y_top - max(box_h_pt, draw_h_pt) - actual_gap_after_pt
                if self.export_options.spaced and self.export_options.draw_separators:
                    y_bottom -= 14.0
                
                if y_bottom < mb_pt:
                    y_bottom = mb_pt
                
                y = y_bottom
                prev_bottom_by_col[col_idx] = y_bottom
                prev_q_by_col[col_idx] = q
                
                print(f"DEBUG: Soru {q.selection.number} yerleştirildi - sayfa {page_num + 1}, sütun {col_idx}, y_bottom={y_bottom:.1f}")
            
            # Son sayfayı ekle
            if current_page:
                pages.append(current_page)
            
            if not pages:
                pages = [[]]
            
            return pages
            
        except Exception as e:
            import traceback
            print(f"Hata: _reorganize_all_questions_dynamic sırasında: {e}\n{traceback.format_exc()}")
            return [[q] for q in questions] if questions else [[]]
    
    def prev_page(self):
        """Önceki sayfaya git"""
        if self.pdf_render_widget.current_page > 0:
            self._load_pdf_page(self.pdf_render_widget.current_page - 1)
            self._update_page_info()
    
    def next_page(self):
        """Sonraki sayfaya git"""
        if self.pdf_render_widget.current_page < self.pdf_render_widget.total_pages - 1:
            self._load_pdf_page(self.pdf_render_widget.current_page + 1)
            self._update_page_info()
    
    def _load_pdf_page(self, page_index: int):
        """PDF'den belirli bir sayfayı yükle ve göster"""
        try:
            if self.temp_pdf_path is None or not os.path.exists(self.temp_pdf_path):
                return
            
            doc = fitz.open(self.temp_pdf_path)
            if 0 <= page_index < doc.page_count:
                page = doc.load_page(page_index)
                render_scale = 4.0  # Yüksek kalite
                mat = fitz.Matrix(render_scale, render_scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                from testmaker.utils.qimage_utils import qimage_from_fitz_pix
                qimg = qimage_from_fitz_pix(pix)
                pdf_pixmap = QPixmap.fromImage(qimg)

                # Update question hit-test rects for THIS page (so highlight doesn't "stick" across pages)
                rects_pt: Dict[int, Tuple[float, float, float, float]] = {}
                try:
                    img_rects: List[fitz.Rect] = []
                    for img in page.get_images(full=True):
                        xref = img[0]
                        try:
                            for r in page.get_image_rects(xref):
                                img_rects.append(r)
                        except Exception:
                            continue

                    words = page.get_text("words") or []
                    num_words: List[Tuple[int, float, float, float, float]] = []
                    for w in words:
                        try:
                            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], str(w[4])
                        except Exception:
                            continue
                        t = (txt or "").strip()
                        if t.startswith("TMID:") and t[5:].isdigit():
                            try:
                                num = int(t[5:])
                            except Exception:
                                continue
                            num_words.append((num, float(x0), float(y0), float(x1), float(y1)))

                    for num, nx0, ny0, nx1, ny1 in num_words:
                        best_r = None
                        best_dx = None
                        n_h = max(1e-6, (ny1 - ny0))
                        for r in img_rects:
                            if float(r.x0) < float(nx1):
                                continue
                            overlap = min(float(r.y1), float(ny1)) - max(float(r.y0), float(ny0))
                            if overlap <= 0:
                                continue
                            if overlap < 0.25 * n_h:
                                continue
                            dx = float(r.x0) - float(nx1)
                            if best_dx is None or dx < best_dx:
                                best_dx = dx
                                best_r = r
                        if best_r is None:
                            continue
                        rects_pt[int(num)] = (float(best_r.x0), float(best_r.y0), float(best_r.x1), float(best_r.y1))
                except Exception:
                    rects_pt = {}
                
                # fit_to_window=False - zoom'u koru, sadece sayfa içeriğini güncelle
                self.pdf_render_widget.set_pdf_pixmap(
                    pdf_pixmap, 
                    doc.page_count, 
                    fit_to_window=False,  # Zoom'u koru
                    preserve_page=False   # Sayfa değişiyor, ama zoom korunuyor
                )
                self.pdf_render_widget.current_page = page_index

                # Apply new rects; keep selection globally (highlight will only appear
                # if the selected question exists on this page).
                try:
                    self.pdf_render_widget.set_question_rects(rects_pt, render_scale=render_scale)
                except Exception:
                    pass
                
                # Cevap anahtarını güncelle
                self._update_answer_key(page_index)
            
            doc.close()
        except Exception as e:
            print(f"Hata: PDF sayfası yüklenirken: {e}")
    
    def showEvent(self, event):
        super().showEvent(event)
        try:
            if not getattr(self, '_did_maximize', False):
                self._did_maximize = True
                # Gerçek tam ekran/maximize
                self.setWindowState(self.windowState() | Qt.WindowMaximized)
        except Exception:
            pass

    def _update_page_info(self):
        """Sayfa bilgisini güncelle"""
        current = self.pdf_render_widget.current_page + 1
        total = self.pdf_render_widget.total_pages
        self.lbl_page_info.setText(f"Sayfa {current} / {total}")

        # Sayfa seçici (dropdown) güncelle
        try:
            self._suppress_page_goto = True
            self.cb_goto_page.blockSignals(True)
            self.cb_goto_page.clear()
            t = max(1, int(total) if total else 1)
            for i in range(t):
                self.cb_goto_page.addItem(f"Sayfa {i+1}", i)
            cur_idx = max(0, min(int(current) - 1, t - 1))
            self.cb_goto_page.setCurrentIndex(cur_idx)
        finally:
            self.cb_goto_page.blockSignals(False)
            self._suppress_page_goto = False
        
        # Butonları aktif/pasif yap
        self.btn_prev_page.setEnabled(current > 1)
        self.btn_next_page.setEnabled(current < total)
    
    def save_pdf(self):
        """PDF'yi kaydet"""
        from PyQt5.QtWidgets import QFileDialog
        import re
        from datetime import datetime

        def _safe_filename(name: str) -> str:
            name = (name or "").strip() or "test"
            # Replace path separators and other problematic characters
            name = re.sub(r'[<>:"/\\\\|?*]+', "_", name)
            name = re.sub(r"\s+", "_", name)
            name = re.sub(r"_+", "_", name).strip("_")
            return name or "test"

        # Önerilen dosya adı: TestAdı_GG-AA-YYYY_HH-MM-SS.pdf (benzersiz)
        title = _safe_filename(getattr(self.export_options, "test_title", "") if self.export_options else "test")
        ts = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
        suggested = f"{title}_{ts}.pdf"

        # Native dialog bazen OS diline göre İngilizce görünebilir.
        # Türkçe buton/etiket için non-native QFileDialog kullan.
        dlg = QFileDialog(self, "PDF Kaydet", suggested, "PDF Dosyaları (*.pdf)")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        dlg.setDefaultSuffix("pdf")
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        try:
            dlg.setLabelText(QFileDialog.Accept, "Kaydet")
            dlg.setLabelText(QFileDialog.Reject, "İptal")
            dlg.setLabelText(QFileDialog.FileName, "Dosya adı:")
            dlg.setLabelText(QFileDialog.LookIn, "Konum:")
            dlg.setLabelText(QFileDialog.FileType, "Dosya türü:")
        except Exception:
            pass

        if dlg.exec_() != QFileDialog.Accepted:
            return
        files = dlg.selectedFiles() or []
        out_path = files[0] if files else ""
        if not out_path:
            return
        
        try:
            from pathlib import Path
            # Yeni tasarımda: custom_gap değerleri zaten self.selections içindeki Selection objelerine kaydediliyor
            # Sadece MainWindow'daki Selection objelerine de aktarılması gerekiyor
            
            # Gap değerlerini topla (MainWindow'a aktarmak için)
            gap_after_map = {}  # {selection.number: custom_gap_after_pt}
            gap_before_map = {}  # {selection.number: custom_gap_before_pt}
            
            for sel in self.selections:
                sel_number = sel.number
                gap_after_map[sel_number] = getattr(sel, 'custom_gap_after_pt', None)
                gap_before_map[sel_number] = getattr(sel, 'custom_gap_before_pt', None)
                
                if gap_after_map[sel_number] is not None:
                    print(f"DEBUG: save_pdf - Soru {sel_number} için custom_gap_after_pt={gap_after_map[sel_number]:.2f}pt kaydedildi")
                if gap_before_map[sel_number] is not None:
                        print(f"DEBUG: save_pdf - Selection {sel_number} güncellendi: custom_gap_before_pt={sel.custom_gap_before_pt:.2f}pt")
            
            # Export'tan önce bir kez daha kontrol et
            print(f"DEBUG: save_pdf - Export öncesi kontrol: {len(self.selections)} Selection objesi")
            for sel in self.selections:
                gap_after = getattr(sel, 'custom_gap_after_pt', None)
                gap_before = getattr(sel, 'custom_gap_before_pt', None)
                print(f"  Soru {sel.number}: gap_after={gap_after}, gap_before={gap_before}")
            
            # ÖNEMLİ: MainWindow'daki Selection objelerine de custom_gap değerlerini kopyala
            # Bu, dialog kapandıktan sonra MainWindow'dan PDF export yapılırsa doğru değerleri görmesini sağlar
            parent = self.parent()
            if parent and hasattr(parent, 'scroll_layout'):
                # MainWindow'daki Selection objelerini bul ve güncelle
                for i in range(parent.scroll_layout.count()):
                    w = parent.scroll_layout.itemAt(i).widget()
                    if hasattr(w, "selection_data") and w.selection_data:
                        sel = w.selection_data
                        sel_number = sel.number
                        if sel_number in gap_after_map:
                            sel.custom_gap_after_pt = gap_after_map[sel_number]
                            print(f"DEBUG: save_pdf - MainWindow Selection {sel_number} güncellendi: gap_after={sel.custom_gap_after_pt}")
                        if sel_number in gap_before_map:
                            sel.custom_gap_before_pt = gap_before_map[sel_number]
                            print(f"DEBUG: save_pdf - MainWindow Selection {sel_number} güncellendi: gap_before={sel.custom_gap_before_pt}")
            
            export_test_pdf(self.selections, Path(out_path), self.export_options, pdf_docs=self.pdf_docs)

            # Türkçe "Tamam" butonlu bilgilendirme
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Başarılı")
            msg.setText(f"PDF kaydedildi:\n{out_path}")
            btn_ok = msg.addButton("Tamam", QMessageBox.AcceptRole)
            msg.setDefaultButton(btn_ok)
            msg.exec_()
            # Dialog'u kapatma, kullanıcı isterse kendisi kapatabilir
        except Exception as e:
            import traceback
            error_msg = f"PDF kaydedilemedi:\n{str(e)}\n\n{traceback.format_exc()}"
            print(f"ERROR: {error_msg}")
            QMessageBox.critical(self, "Hata", error_msg)
    
    def keyPressEvent(self, event: QKeyEvent):
        """ENTER tuşu ile bölüm ekle penceresinin açılmasını engelle"""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            # ENTER tuşunu yakala ama işleme, böylece bölüm ekle butonu tetiklenmez
            event.ignore()
            return
        super().keyPressEvent(event)