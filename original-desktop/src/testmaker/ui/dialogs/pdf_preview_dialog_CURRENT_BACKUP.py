# pdf_preview_dialog.py
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea, QWidget, QMessageBox, QApplication,
    QSlider, QSpinBox, QSizePolicy, QGridLayout, QCheckBox, QLineEdit, QDialog as QPopupDialog
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer, QMimeData
from PyQt5.QtGui import QPainter, QPixmap, QPen, QBrush, QColor, QFont, QDrag, QPalette, QCursor
from pathlib import Path
from typing import List, Dict
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
    custom_gap_after_pt: float = None  # Bu sorudan sonraki özel boşluk (pt cinsinden, None ise varsayılan kullanılır)
    custom_gap_before_pt: float = None  # Bu sorudan önceki özel boşluk (pt cinsinden, None ise varsayılan kullanılır)


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
        self.setStyleSheet("background-color: #F5F5F5;")  # Açık gri arka plan
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
                
                display_scale = q.selection.display_scale or 1.0
                
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
                number_text = f"{getattr(q.selection, 'number', '?')}."
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
        num_text = f"{getattr(q.selection, 'number', '?')}."
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
                    
                    # Seçili soru için çerçeve
                    if q == self._selected_question:
                        pen = QPen(QColor(255, 0, 0), 3, Qt.SolidLine)
                    else:
                        pen = QPen(QColor(220, 0, 0), 2, Qt.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(img_rect)
                    
                    # Soru numarası (PDF formatında - numara solda, görsel sağda)
                    painter.setFont(QFont("Arial", int(10 * preview_scale), QFont.Bold))
                    painter.setPen(QColor(0, 0, 0))  # Siyah
                    painter.setBrush(Qt.NoBrush)
                    num_text = f"{getattr(q.selection, 'number', '?')}."
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
            max_gap_pt = mm_to_pt(50.0)  # 50 mm -> pt
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
            number_text = f"{getattr(self._selected_question.selection, 'number', '?')}."
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
            new_display_scale = max(0.1, min(5.0, new_display_scale))  # Sınırlama
            
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
        self.current_page = 0
        self.total_pages = 0
        self.zoom_factor = 1.0  # Zoom faktörü
        self.pan_offset = QPoint(0, 0)  # Pan (sürükleme) offset
        self.pan_start_pos = None  # Pan başlangıç pozisyonu
        self.is_panning = False  # Pan yapılıyor mu?
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        
        # Tema uyumlu arka plan
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        if is_dark:
            self.setStyleSheet("background-color: #2B2B2B;")
        else:
            self.setStyleSheet("background-color: #F5F5F5;")
    
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
        self.update()
    
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
        
        # Aspect ratio'yu koruyarak sığdır
        scale_w = available_w / img_w
        scale_h = available_h / img_h
        self.zoom_factor = min(scale_w, scale_h, 1.0)  # Başlangıçta 1.0'dan büyük olmasın
        
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
    
    def mousePressEvent(self, e):
        """Mouse basıldığında - Pan başlat"""
        if e.button() == Qt.LeftButton:
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
            painter.drawText(self.rect(), Qt.AlignCenter, "PDF önizlemesi hazırlanıyor...")
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
            # Ama sınırları kontrol et
            max_offset_x = (img_w - widget_w) // 2 if img_w > widget_w else 0
            max_offset_y = (img_h - widget_h) // 2 if img_h > widget_h else 0
            
            if abs(self.pan_offset.x()) > max_offset_x:
                self.pan_offset.setX(max_offset_x if self.pan_offset.x() > 0 else -max_offset_x)
            if abs(self.pan_offset.y()) > max_offset_y:
                self.pan_offset.setY(max_offset_y if self.pan_offset.y() > 0 else -max_offset_y)
            
            x = center_x + self.pan_offset.x()
            y = center_y + self.pan_offset.y()
        
        painter.drawPixmap(x, y, self.pdf_pixmap)
        
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
        self.setMinimumHeight(350)  # Tüm içerikler net görünsün
        # Maximum yok - içeriğe göre büyüyebilir
        
        # Debounce timer'lar (çok hızlı tepki için - 5ms)
        self.gap_update_timer = QTimer()
        self.gap_update_timer.setSingleShot(True)
        self.gap_update_timer.timeout.connect(self._update_gap_preview)
        
        self.size_update_timer = QTimer()
        self.size_update_timer.setSingleShot(True)
        self.size_update_timer.timeout.connect(self._update_size_preview)
        
        # Sistem temasını algıla
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        
        # Dış border kaldırıldı - sadece gruplar border alacak (modern tasarım)
        self.setStyleSheet("")  # Dış border yok
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)  # Daha fazla padding - okunabilirlik
        layout.setSpacing(12)  # Gruplar arası daha fazla boşluk
        
        # Soru numarası (daha büyük ve belirgin) - Tema uyumlu - Border korunuyor
        num_label = QLabel(f"{selection.number}. SORU")
        num_label.setMinimumHeight(32)
        num_label.setMaximumHeight(32)
        if is_dark:
            num_label.setStyleSheet("""
                font-size: 14px; 
                font-weight: bold; 
                color: #90CAF9;
                padding: 6px;
                background-color: #1E3A5F;
                border: none;
                border-radius: 6px;
            """)
        else:
            num_label.setStyleSheet("""
                font-size: 14px; 
                font-weight: bold; 
                color: #1976D2;
                padding: 6px;
                background-color: #E3F2FD;
                border: none;
                border-radius: 6px;
            """)
        num_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(num_label)
        
        # ========== GRUP 1: BOŞLUK ==========
        # Grup container - BORDER/ÇİZGİLER KALDIRILDI (kullanıcı isteği)
        # İç widget'ların (spinbox/slider) kendi stilleri korunur.
        gap_group_container = QWidget()
        if is_dark:
            gap_group_container.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                }
            """)
        else:
            gap_group_container.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                }
            """)
        
        gap_group_layout = QVBoxLayout(gap_group_container)
        gap_group_layout.setContentsMargins(12, 16, 12, 12)  # Üst padding artırıldı - label kesilmesin
        gap_group_layout.setSpacing(8)
        
        # Grup başlığı - Yeterli yükseklik ve padding ile okunabilir
        gap_label = QLabel("Boşluk")
        gap_label.setMinimumHeight(28)  # Minimum yükseklik - text kesilmesin
        gap_label.setMaximumHeight(28)
        if is_dark:
            gap_label.setStyleSheet("""
                font-size: 12px; 
                color: #B0BEC5; 
                font-weight: bold;
                padding: 4px 0px;
            """)
        else:
            gap_label.setStyleSheet("""
                font-size: 12px; 
                color: #546E7A; 
                font-weight: bold;
                padding: 4px 0px;
            """)
        gap_group_layout.addWidget(gap_label)
        
        # Boşluk kontrolü - Dikey layout (Slider üstte, SpinBox altta)
        gap_control_layout = QVBoxLayout()
        gap_control_layout.setSpacing(2)  # Daha kompakt - sığsın
        gap_control_layout.setContentsMargins(0, 0, 0, 0)  # Dışarıdan margin için
        
        # Slider - Tema uyumlu (tekerlek ile hareket etmez)
        gap_slider = NoWheelSlider(Qt.Horizontal)
        gap_slider.setMinimum(6)
        gap_slider.setMaximum(50)
        gap_slider.setSingleStep(1)
        gap_slider.setPageStep(5)
        gap_slider.setMinimumHeight(22)  # Daha küçük - sığsın
        gap_slider.setMaximumHeight(22)
        if is_dark:
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
        else:
            gap_slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    background-color: #E3E8F0;
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
        gap_spinbox.setMaximum(50)
        gap_spinbox.setSuffix(" mm")
        gap_spinbox.setMinimumHeight(28)  # Biraz büyütüldü - içerik sığsın
        gap_spinbox.setMaximumHeight(28)
        gap_spinbox.setMinimumWidth(80)  # Minimum genişlik - "11 mm" gibi değerler sığsın
        if is_dark:
            gap_spinbox.setStyleSheet("""
                QSpinBox {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: #424242;
                    color: #E0E0E0;
                }
                QSpinBox:focus {
                    border: none;
                    background-color: #4A4A4A;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: #4A4A4A;
                    border: none;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background-color: #616161;
                }
            """)
        else:
            gap_spinbox.setStyleSheet("""
                QSpinBox {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: white;
                    color: #333;
                }
                QSpinBox:focus {
                    border: none;
                    background-color: #FAFAFA;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: #F5F9FF;
                    border: none;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background-color: #E3E8F0;
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
        
        # Bağlantılar - Hızlı tepki için debounce (10ms)
        def on_slider_changed(value):
            gap_spinbox.blockSignals(True)
            gap_spinbox.setValue(value)
            gap_spinbox.blockSignals(False)
            selection.custom_gap_after_pt = mm_to_pt(float(value))
            # Debounce timer'ı başlat (5ms sonra güncelle - çok hızlı tepki)
            self.gap_update_timer.stop()
            self.gap_update_timer.start(5)
        
        def on_spinbox_changed(value):
            gap_slider.blockSignals(True)
            gap_slider.setValue(value)
            gap_slider.blockSignals(False)
            selection.custom_gap_after_pt = mm_to_pt(float(value))
            # Debounce timer'ı başlat (5ms sonra güncelle - çok hızlı tepki)
            self.gap_update_timer.stop()
            self.gap_update_timer.start(5)
        
        gap_slider.valueChanged.connect(on_slider_changed)
        gap_spinbox.valueChanged.connect(on_spinbox_changed)
        
        # Preview güncelleme metodunu kaydet
        self._gap_selection = selection
        self._gap_dialog = dialog
        
        gap_control_layout.addWidget(gap_slider)
        gap_control_layout.addWidget(gap_spinbox_container)
        gap_group_layout.addLayout(gap_control_layout)
        
        # Grup 1'i ana layout'a ekle
        layout.addWidget(gap_group_container)
        
        # ========== GRUP 2: BOYUT ==========
        # Grup container - BORDER/ÇİZGİLER KALDIRILDI (kullanıcı isteği)
        size_group_container = QWidget()
        if is_dark:
            size_group_container.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                }
            """)
        else:
            size_group_container.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                }
            """)
        
        size_group_layout = QVBoxLayout(size_group_container)
        size_group_layout.setContentsMargins(12, 16, 12, 12)  # Üst padding artırıldı - label kesilmesin
        size_group_layout.setSpacing(8)
        
        # Grup başlığı - Yeterli yükseklik ve padding ile okunabilir
        size_label = QLabel("Boyut")
        size_label.setMinimumHeight(28)  # Minimum yükseklik - text kesilmesin
        size_label.setMaximumHeight(28)
        if is_dark:
            size_label.setStyleSheet("""
                font-size: 12px; 
                color: #B0BEC5; 
                font-weight: bold;
                padding: 4px 0px;
            """)
        else:
            size_label.setStyleSheet("""
                font-size: 12px; 
                color: #546E7A; 
                font-weight: bold;
                padding: 4px 0px;
            """)
        size_group_layout.addWidget(size_label)
        
        # Boyut kontrolü - Slider ve SpinBox
        size_control_layout = QVBoxLayout()
        size_control_layout.setSpacing(2)  # Daha kompakt - sığsın
        size_control_layout.setContentsMargins(0, 0, 0, 0)  # Dışarıdan margin için
        
        # Display scale slider (tekerlek ile hareket etmez)
        size_slider = NoWheelSlider(Qt.Horizontal)
        size_slider.setMinimum(50)  # %50
        size_slider.setMaximum(200)  # %200
        size_slider.setSingleStep(5)
        size_slider.setPageStep(10)
        size_slider.setMinimumHeight(22)  # Daha küçük - sığsın
        size_slider.setMaximumHeight(22)
        
        # Mevcut display_scale değerini ayarla
        current_scale = getattr(selection, 'display_scale', 1.0) or 1.0
        size_slider.setValue(int(current_scale * 100))
        
        # Display scale spinbox - Container widget içine al (margin için)
        size_spinbox_container = QWidget()
        size_spinbox_container_layout = QHBoxLayout(size_spinbox_container)
        size_spinbox_container_layout.setContentsMargins(0, 0, 0, 0)  # Margin kaldırıldı - spinbox tam genişlik
        size_spinbox_container_layout.setSpacing(0)
        
        size_spinbox = NoWheelSpinBox()
        size_spinbox.setMinimum(50)
        size_spinbox.setMaximum(200)
        size_spinbox.setSuffix(" %")
        size_spinbox.setMinimumHeight(28)  # Biraz büyütüldü - içerik sığsın
        size_spinbox.setMaximumHeight(28)
        size_spinbox.setMinimumWidth(80)  # Minimum genişlik - "100 %" gibi değerler sığsın
        size_spinbox.setValue(int(current_scale * 100))
        
        size_spinbox_container_layout.addWidget(size_spinbox)
        
        if is_dark:
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
            size_spinbox.setStyleSheet("""
                QSpinBox {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: #424242;
                    color: #E0E0E0;
                }
                QSpinBox:focus {
                    border: none;
                    background-color: #4A4A4A;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: #4A4A4A;
                    border: none;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background-color: #616161;
                }
            """)
        else:
            size_slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    background-color: #E3E8F0;
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
            size_spinbox.setStyleSheet("""
                QSpinBox {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: white;
                    color: #333;
                }
                QSpinBox:focus {
                    border: none;
                    background-color: #FAFAFA;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background-color: #F5F9FF;
                    border: none;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background-color: #E3E8F0;
                }
            """)
        
        # Bağlantılar - Hızlı tepki için debounce (10ms)
        def on_size_slider_changed(value):
            size_spinbox.blockSignals(True)
            size_spinbox.setValue(value)
            size_spinbox.blockSignals(False)
            selection.display_scale = float(value) / 100.0
            # Debounce timer'ı başlat (10ms sonra güncelle)
            self.size_update_timer.stop()
            self.size_update_timer.start(5)
        
        def on_size_spinbox_changed(value):
            size_slider.blockSignals(True)
            size_slider.setValue(value)
            size_slider.blockSignals(False)
            selection.display_scale = float(value) / 100.0
            # Debounce timer'ı başlat (10ms sonra güncelle)
            self.size_update_timer.stop()
            self.size_update_timer.start(5)
        
        size_slider.valueChanged.connect(on_size_slider_changed)
        size_spinbox.valueChanged.connect(on_size_spinbox_changed)
        
        # Preview güncelleme metodunu kaydet
        self._size_selection = selection
        self._size_dialog = dialog
        
        size_control_layout.addWidget(size_slider)
        size_control_layout.addWidget(size_spinbox_container)
        size_group_layout.addLayout(size_control_layout)
        
        # Grup 2'yi ana layout'a ekle
        layout.addWidget(size_group_container)
        
        # ========== GRUP 3: SORU YERLEŞTİR ==========
        # Grup container - BORDER/ÇİZGİLER KALDIRILDI (kullanıcı isteği)
        placement_group_container = QWidget()
        if is_dark:
            placement_group_container.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                }
            """)
        else:
            placement_group_container.setStyleSheet("""
                QWidget {
                    background-color: transparent;
                    border: none;
                    border-radius: 0px;
                }
            """)
        
        placement_group_layout = QVBoxLayout(placement_group_container)
        placement_group_layout.setContentsMargins(12, 16, 12, 12)  # Üst padding artırıldı - label kesilmesin
        placement_group_layout.setSpacing(10)
        
        # Grup başlığı - Yeterli yükseklik ve padding ile okunabilir
        placement_label = QLabel("Soru Yerleştir")
        placement_label.setMinimumHeight(28)  # Minimum yükseklik - text kesilmesin
        placement_label.setMaximumHeight(28)
        if is_dark:
            placement_label.setStyleSheet("""
                font-size: 12px; 
                color: #B0BEC5; 
                font-weight: bold;
                padding: 4px 0px;
            """)
        else:
            placement_label.setStyleSheet("""
                font-size: 12px; 
                color: #546E7A; 
                font-weight: bold;
                padding: 4px 0px;
            """)
        placement_group_layout.addWidget(placement_label)
        
        # 1. satır: Yer değiştir - Label solda, Input sağda
        replace_row = QHBoxLayout()
        replace_row.setSpacing(10)
        
        self.replace_checkbox = QCheckBox()
        self.replace_checkbox.setMaximumHeight(25)
        if is_dark:
            self.replace_checkbox.setStyleSheet("font-size: 10px;")
        else:
            self.replace_checkbox.setStyleSheet("font-size: 10px;")
        
        replace_label = QLabel("Sorusu ile yer değiştir")
        replace_label.setMinimumHeight(28)  # Minimum yükseklik - text görünsün
        replace_label.setMaximumHeight(28)
        if is_dark:
            replace_label.setStyleSheet("""
                font-size: 11px; 
                color: #E0E0E0;
                padding: 4px 0px;
            """)
        else:
            replace_label.setStyleSheet("""
                font-size: 11px; 
                color: #333;
                padding: 4px 0px;
            """)
        
        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Soru numarası")
        self.replace_input.setMinimumHeight(28)
        self.replace_input.setMaximumHeight(28)
        self.replace_input.setEnabled(False)  # Başlangıçta pasif
        if is_dark:
            self.replace_input.setStyleSheet("""
                QLineEdit {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: #424242;
                    color: #E0E0E0;
                }
                QLineEdit:focus {
                    border: none;
                    background-color: #4A4A4A;
                }
                QLineEdit:disabled {
                    background-color: #2B2B2B;
                    border: none;
                    color: #616161;
                }
            """)
        else:
            self.replace_input.setStyleSheet("""
                QLineEdit {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: white;
                    color: #333;
                }
                QLineEdit:focus {
                    border: none;
                    background-color: #FAFAFA;
                }
                QLineEdit:disabled {
                    background-color: #F5F5F5;
                    border: none;
                    color: #BDBDBD;
                }
            """)
        
        replace_row.addWidget(self.replace_checkbox)
        replace_row.addWidget(replace_label)
        replace_row.addStretch()
        replace_row.addWidget(self.replace_input)
        self.replace_input.setMinimumWidth(100)
        self.replace_input.setMaximumWidth(100)
        placement_group_layout.addLayout(replace_row)
        
        # 2. satır: Altına ekle - Label solda, Input sağda
        insert_row = QHBoxLayout()
        insert_row.setSpacing(10)
        
        self.insert_checkbox = QCheckBox()
        self.insert_checkbox.setMaximumHeight(25)
        if is_dark:
            self.insert_checkbox.setStyleSheet("font-size: 10px;")
        else:
            self.insert_checkbox.setStyleSheet("font-size: 10px;")
        
        insert_label = QLabel("Sorusunun altına ekle")
        insert_label.setMinimumHeight(28)  # Minimum yükseklik - text görünsün
        insert_label.setMaximumHeight(28)
        if is_dark:
            insert_label.setStyleSheet("""
                font-size: 11px; 
                color: #E0E0E0;
                padding: 4px 0px;
            """)
        else:
            insert_label.setStyleSheet("""
                font-size: 11px; 
                color: #333;
                padding: 4px 0px;
            """)
        
        self.insert_input = QLineEdit()
        self.insert_input.setPlaceholderText("Soru numarası")
        self.insert_input.setMinimumHeight(28)
        self.insert_input.setMaximumHeight(28)
        self.insert_input.setEnabled(False)  # Başlangıçta pasif
        if is_dark:
            self.insert_input.setStyleSheet("""
                QLineEdit {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: #424242;
                    color: #E0E0E0;
                }
                QLineEdit:focus {
                    border: none;
                    background-color: #4A4A4A;
                }
                QLineEdit:disabled {
                    background-color: #2B2B2B;
                    border: none;
                    color: #616161;
                }
            """)
        else:
            self.insert_input.setStyleSheet("""
                QLineEdit {
                    padding: 6px;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                    background-color: white;
                    color: #333;
                }
                QLineEdit:focus {
                    border: none;
                    background-color: #FAFAFA;
                }
                QLineEdit:disabled {
                    background-color: #F5F5F5;
                    border: none;
                    color: #BDBDBD;
                }
            """)
        
        insert_row.addWidget(self.insert_checkbox)
        insert_row.addWidget(insert_label)
        insert_row.addStretch()
        insert_row.addWidget(self.insert_input)
        self.insert_input.setMinimumWidth(100)
        self.insert_input.setMaximumWidth(100)
        placement_group_layout.addLayout(insert_row)
        
        # Uygula butonu - Grup 3 içinde
        self.apply_button = QPushButton("Uygula")
        self.apply_button.setMinimumHeight(32)
        self.apply_button.setEnabled(False)  # Başlangıçta pasif
        if is_dark:
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
        else:
            self.apply_button.setStyleSheet("""
                QPushButton {
                    font-size: 12px;
                    font-weight: bold;
                    color: #333;
                    background-color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px;
                }
                QPushButton:hover:enabled {
                    background-color: #F5F5F5;
                    border: none;
                }
                QPushButton:enabled {
                    background-color: #E3F2FD;
                    border: none;
                    color: #1976D2;
                }
                QPushButton:disabled {
                    background-color: #F5F5F5;
                    border: none;
                    color: #BDBDBD;
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
        """Mouse basıldığında"""
        if e.button() == Qt.LeftButton:
            self._drag_start_pos = e.pos()
    
    def mouseMoveEvent(self, e):
        """Mouse hareket ettiğinde"""
        if self._drag_start_pos is None:
            return
        if (e.pos() - self._drag_start_pos).manhattanLength() < 10:
            return
        
        # Drag başlat
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(str(self.selection.number))
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(e.pos() - self.rect().topLeft())
        
        self._drag_start_pos = None
        drag.exec_(Qt.MoveAction)
    
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
            # Hızlı tepki için direkt güncelle (timer zaten 10ms)
            self._gap_dialog._update_pdf_preview(question_number=None, preserve_current_page=True)
    
    def _update_size_preview(self):
        """Boyut değişikliğini preview'a uygula - Çok hızlı tepki"""
        if self._size_dialog and self._size_selection:
            # preserve_current_page=True - mevcut sayfada kal, sadece içeriği güncelle
            # Hızlı tepki için direkt güncelle (timer zaten 5ms)
            self._size_dialog._update_pdf_preview(question_number=None, preserve_current_page=True)
    
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
    
    def __init__(self, parent=None, dialog=None):
        super().__init__(parent)
        self.dialog = dialog
        self.selections: List[Selection] = []
        self.setMinimumWidth(350)  # Minimum genişlik, maksimum yok - responsive
        # Size policy: Preferred - içeriğe göre genişleyebilir
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        # Sistem temasını algıla
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        
        if is_dark:
            self.setStyleSheet("""
                QWidget {
                    background-color: #2B2B2B;
                }
            """)
        else:
            self.setStyleSheet("""
                QWidget {
                    background-color: #F5F5F5;
                }
            """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # Başlık (daha modern) - Tema uyumlu - Sadece yazı yüksekliği kadar
        title = QLabel("📋 Sorular ve Ayarlar")
        title.setMaximumHeight(30)  # Sadece yazı yüksekliği kadar
        if is_dark:
            title.setStyleSheet("""
                font-size: 16px; 
                font-weight: bold; 
                color: #64B5F6;
                padding: 4px 8px;
                background-color: #424242;
                border-radius: 8px;
            """)
        else:
            title.setStyleSheet("""
                font-size: 16px; 
                font-weight: bold; 
                color: #1976D2;
                padding: 4px 8px;
                background-color: white;
                border-radius: 8px;
            """)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Soru numaraları grid'i (10 sütun) - Tema uyumlu - Dikdörtgen içinde
        # Genişlik hesaplama: COLUMNS * BUTTON_SIZE + (COLUMNS-1) * SPACING + 2 * PADDING
        grid_width = (self.GRID_COLUMNS * self.BUTTON_SIZE + 
                      (self.GRID_COLUMNS - 1) * self.GRID_SPACING + 
                      2 * self.GRID_PADDING)
        
        self.question_grid_widget = QWidget()
        self.question_grid_widget.setFixedWidth(grid_width)  # Sabit genişlik
        # Yükseklik dinamik - içeriğe göre otomatik hesaplanacak (scroll bar yok)
        self.question_grid_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        if is_dark:
            self.question_grid_widget.setStyleSheet("""
                QWidget {
                    background-color: #424242;
                    border: 2px solid #616161;
                    border-radius: 8px;
                }
            """)
        else:
            self.question_grid_widget.setStyleSheet("""
                QWidget {
                    background-color: white;
                    border: 2px solid #E0E0E0;
                    border-radius: 8px;
                }
            """)
        
        self.question_grid_layout = QGridLayout(self.question_grid_widget)
        self.question_grid_layout.setSpacing(self.GRID_SPACING)  # Satırlar arası boşluk
        self.question_grid_layout.setContentsMargins(
            self.GRID_PADDING, self.GRID_PADDING, 
            self.GRID_PADDING, self.GRID_PADDING
        )  # Padding grid içinde
        self.question_buttons = {}  # {question_number: QPushButton}
        layout.addWidget(self.question_grid_widget)
        
        # Seçili soru detayları (başlangıçta gizli)
        self.selected_question_widget = None
        self.selected_question_number = None
        
        # Soru detayları container (dikdörtgen içinde)
        self.question_details_container = QWidget()
        # Size policy: Minimum yükseklik (içeriğe göre büyüyebilir)
        self.question_details_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        if is_dark:
            self.question_details_container.setStyleSheet("""
                QWidget {
                    background-color: #424242;
                    border: 2px solid #616161;
                    border-radius: 8px;
                }
            """)
        else:
            self.question_details_container.setStyleSheet("""
                QWidget {
                    background-color: white;
                    border: 2px solid #E0E0E0;
                    border-radius: 8px;
                }
            """)
        
        self.question_details_layout = QVBoxLayout(self.question_details_container)
        self.question_details_layout.setContentsMargins(8, 8, 8, 8)  # Padding container içinde
        self.question_details_layout.setSpacing(8)
        
        # Thumbnail container (ayrı kutu, alt kısımda)
        self.thumbnail_container = QWidget()
        self.thumbnail_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        if is_dark:
            self.thumbnail_container.setStyleSheet("""
                QWidget {
                    background-color: #424242;
                    border: 2px solid #616161;
                    border-radius: 8px;
                    padding: 8px;
                }
            """)
        else:
            self.thumbnail_container.setStyleSheet("""
                QWidget {
                    background-color: white;
                    border: 2px solid #E0E0E0;
                    border-radius: 8px;
                    padding: 8px;
                }
            """)
        
        thumbnail_layout = QVBoxLayout(self.thumbnail_container)
        thumbnail_layout.setContentsMargins(8, 8, 8, 8)
        thumbnail_layout.setSpacing(8)
        
        thumbnail_label = QLabel("Soru Görseli:")
        thumbnail_label.setMaximumHeight(20)
        if is_dark:
            thumbnail_label.setStyleSheet("font-size: 10px; color: #E0E0E0; font-weight: bold;")
        else:
            thumbnail_label.setStyleSheet("font-size: 10px; color: #666; font-weight: bold;")
        thumbnail_layout.addWidget(thumbnail_label)
        
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setMinimumHeight(120)  # Biraz daha büyük - görsel net görünsün
        self.thumbnail_label.setMaximumHeight(120)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setText("Soru görseli yükleniyor...")  # Başlangıç metni
        if is_dark:
            self.thumbnail_label.setStyleSheet("""
                QLabel {
                    border: 2px solid #616161;
                    border-radius: 6px;
                    background-color: #2B2B2B;
                    color: #E0E0E0;
                    font-size: 11px;
                }
            """)
        else:
            self.thumbnail_label.setStyleSheet("""
                QLabel {
                    border: 2px solid #E0E0E0;
                    border-radius: 6px;
                    background-color: #FAFAFA;
                    color: #666;
                    font-size: 11px;
                }
            """)
        self.thumbnail_label.setCursor(QCursor(Qt.PointingHandCursor))
        thumbnail_layout.addWidget(self.thumbnail_label)
        
        # Scroll area (daha iyi scroll bar) - Tema uyumlu
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        if is_dark:
            self.scroll.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background-color: transparent;
                }
                QScrollBar:vertical {
                    background-color: #424242;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background-color: #616161;
                    min-height: 30px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #757575;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
            """)
        else:
            self.scroll.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background-color: transparent;
                }
                QScrollBar:vertical {
                    background-color: #E0E0E0;
                    width: 12px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical {
                    background-color: #BDBDBD;
                    min-height: 30px;
                    border-radius: 6px;
                }
                QScrollBar::handle:vertical:hover {
                    background-color: #9E9E9E;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
            """)
        
        # Content widget - içeriğe göre genişleyecek
        class ResponsiveContentWidget(QWidget):
            def sizeHint(self):
                """İçeriğe göre optimal genişlik döndür"""
                hint = super().sizeHint()
                # Minimum genişlik: 350px, maksimum: içeriğe göre
                # En geniş child widget'ın genişliğini bul
                max_width = 350  # Minimum
                for i in range(self.layout().count()):
                    item = self.layout().itemAt(i)
                    if item and item.widget():
                        widget = item.widget()
                        widget_hint = widget.sizeHint()
                        if widget_hint.width() > max_width:
                            max_width = widget_hint.width()
                # Padding ve margin'leri ekle
                margins = self.layout().contentsMargins()
                max_width += margins.left() + margins.right() + 20  # Ekstra padding
                hint.setWidth(max_width)
                return hint
        
        self.content_widget = ResponsiveContentWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(8)  # Daha kompakt
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        # Content widget genişliği içeriğe göre ayarlanacak (responsive)
        # Size policy: Preferred - içeriğe göre genişleyebilir
        self.content_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        
        self.scroll.setWidget(self.content_widget)
        self.scroll.setWidgetResizable(True)  # Widget boyutuna göre scroll
        # Scroll area'nın genişliği içeriğe göre ayarlanacak
        self.scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout.addWidget(self.scroll)
        
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
            
            if is_dark:
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
                        background-color: #1E3A5F;
                        border: 2px solid #64B5F6;
                        color: #64B5F6;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        font-size: 12px;
                        font-weight: bold;
                        color: #333;
                        background-color: white;
                        border: 2px solid #E0E0E0;
                        border-radius: 6px;
                    }
                    QPushButton:hover {
                        background-color: #F5F5F5;
                        border: 2px solid #2196F3;
                    }
                    QPushButton:checked {
                        background-color: #E3F2FD;
                        border: 2px solid #2196F3;
                        color: #2196F3;
                    }
                """)
            
            self.question_grid_layout.addWidget(btn, row, col)
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
        
        # Layout'u güncelle
        self.content_layout.addStretch()
    
    def _on_question_clicked(self, question_number: int):
        """Soru numarası butonuna tıklandığında"""
        # Önceki seçili butonu kaldır
        if self.selected_question_number and self.selected_question_number in self.question_buttons:
            self.question_buttons[self.selected_question_number].setChecked(False)
        
        # Yeni seçili butonu işaretle
        if question_number in self.question_buttons:
            self.question_buttons[question_number].setChecked(True)
        
        self.selected_question_number = question_number
        
        # Seçili soruyu bul
        selected_sel = None
        for sel in self.selections:
            if sel.number == question_number:
                selected_sel = sel
                break
        
        if not selected_sel:
            return
        
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
        
        # Thumbnail'i güncelle (seçilen sorunun görseli)
        self._load_question_thumbnail(selected_sel)
        
        # Container'ları content layout'a ekle (eğer eklenmemişse)
        if self.content_layout.indexOf(self.question_details_container) == -1:
            self.content_layout.addWidget(self.question_details_container)
        if self.content_layout.indexOf(self.thumbnail_container) == -1:
            self.content_layout.addWidget(self.thumbnail_container)
    
    def _load_question_thumbnail(self, selection):
        """Soru görselini yükle (küçük önizleme - thumbnail)"""
        try:
            if not self.dialog or not hasattr(self.dialog, 'pdf_docs'):
                return
            
            if not hasattr(self, 'thumbnail_label') or not self.thumbnail_label:
                return
            
            pdf_key = getattr(selection, "pdf_key", None)
            page_index = int(getattr(selection, "page_index", -1))
            norm = getattr(selection, "norm", None)
            
            if not pdf_key or norm is None:
                self.thumbnail_label.setText("Görsel yok")
                return
            
            doc = self.dialog.pdf_docs.get(str(pdf_key))
            if not doc:
                self.thumbnail_label.setText("PDF bulunamadı")
                return
            
            # PDF'den görseli render et
            import fitz
            page = doc.load_page(page_index)
            rect = fitz.Rect(norm)
            
            # Küçük önizleme için düşük çözünürlük
            zoom = 1.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
            
            # QPixmap'e çevir
            from testmaker.utils.qimage_utils import qimage_from_fitz_pix
            qimg = qimage_from_fitz_pix(pix)
            pixmap = QPixmap.fromImage(qimg)
            
            # Küçük boyuta ölçekle (120px yükseklik - thumbnail label'a sığsın)
            scaled_pixmap = pixmap.scaled(180, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.thumbnail_label.setPixmap(scaled_pixmap)
            self.thumbnail_label.setText("")  # Metni temizle, sadece görsel göster
            
            # Pop-up için tıklama event'i
            self.thumbnail_label.mousePressEvent = lambda e: self._show_question_image_popup(selection)
            
        except Exception as e:
            import traceback
            print(f"Hata: Soru görseli yüklenirken: {e}\n{traceback.format_exc()}")
            if hasattr(self, 'thumbnail_label') and self.thumbnail_label:
                self.thumbnail_label.setText("Yüklenemedi")
    
    def _show_question_image_popup(self, selection):
        """Soru görselini pop-up olarak göster"""
        try:
            if not self.dialog or not hasattr(self.dialog, 'pdf_docs'):
                return
            
            pdf_key = getattr(selection, "pdf_key", None)
            page_index = int(getattr(selection, "page_index", -1))
            norm = getattr(selection, "norm", None)
            
            if not pdf_key or norm is None:
                return
            
            doc = self.dialog.pdf_docs.get(str(pdf_key))
            if not doc:
                return
            
            # Pop-up dialog oluştur
            popup = QPopupDialog(self)
            popup.setWindowTitle(f"Soru {selection.number} - Görsel")
            popup.setModal(True)
            
            layout = QVBoxLayout(popup)
            
            # Görseli yükle
            import fitz
            page = doc.load_page(page_index)
            rect = fitz.Rect(norm)
            
            # Yüksek çözünürlük
            zoom = 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
            
            from testmaker.utils.qimage_utils import qimage_from_fitz_pix
            qimg = qimage_from_fitz_pix(pix)
            pixmap = QPixmap.fromImage(qimg)
            
            # Maksimum boyut (ekranın %80'i)
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry()
            max_width = int(screen_geometry.width() * 0.8)
            max_height = int(screen_geometry.height() * 0.8)
            
            scaled_pixmap = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            image_label = QLabel()
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(image_label)
            
            # Kapat butonu
            close_btn = QPushButton("Kapat")
            close_btn.clicked.connect(popup.close)
            layout.addWidget(close_btn)
            
            popup.resize(scaled_pixmap.width() + 40, scaled_pixmap.height() + 80)
            popup.exec_()
            
        except Exception as e:
            import traceback
            print(f"Hata: Pop-up görsel gösterilirken: {e}\n{traceback.format_exc()}")
        
        # Container'ları content layout'a ekle (eğer eklenmemişse)
        if self.content_layout.indexOf(self.question_details_container) == -1:
            self.content_layout.addWidget(self.question_details_container)
        if self.content_layout.indexOf(self.thumbnail_container) == -1:
            self.content_layout.addWidget(self.thumbnail_container)
        
        # Content widget'ın boyutunu güncelle
        self.content_widget.adjustSize()
        
        # Scroll'u en üste kaydır
        self.scroll.verticalScrollBar().setValue(0)


def pt_to_mm(pt: float) -> float:
    """Points'ten milimetreye dönüştür"""
    return float(pt) * 25.4 / 72.0


class PDFPreviewDialog(QDialog):
    """PDF ön izleme ve düzenleme dialog'u - YENİ TASARIM: Sol panel + PDF render"""
    
    def __init__(self, parent, selections: List[Selection], export_options: ExportOptions, pdf_docs: dict, render_dpi: float = 72.0):
        super().__init__(parent)
        self.setWindowTitle("PDF Ön İzleme ve Düzenleme")
        self.setModal(True)
        
        # MADDE 5: Ekran yüksekliği kadar aç
        from PyQt5.QtWidgets import QApplication, QDesktopWidget
        screen = QApplication.primaryScreen()
        screen_geometry = screen.geometry()
        screen_height = screen_geometry.height()
        screen_width = screen_geometry.width()
        
        # Dialog boyutunu ekran yüksekliğinin %90'ı kadar yap, genişlik de uygun şekilde
        dialog_height = int(screen_height * 0.9)
        dialog_width = min(int(screen_width * 0.85), 1800)  # Maksimum 1800px genişlik
        self.resize(dialog_width, dialog_height)
        
        self.selections = selections
        self.export_options = export_options
        self.pdf_docs = pdf_docs
        self.render_dpi = render_dpi  # PDF render DPI'si (standart 72 DPI)
        self.temp_pdf_path = None  # Geçici PDF dosyası yolu
        
        layout = QVBoxLayout(self)
        
        # Başlık
        title = QLabel("PDF Önizleme ve Boşluk Ayarları")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Ana içerik: Sol panel + Sağ panel (PDF render)
        main_split = QHBoxLayout()
        main_split.setSpacing(10)
        
        # SOL PANEL: Soru listesi ve boşluk ayarları
        self.question_list_widget = QuestionListWidget(parent=self, dialog=self)
        self.question_list_widget.set_selections(selections)
        main_split.addWidget(self.question_list_widget)
        
        # SAĞ PANEL: PDF render preview
        right_panel_layout = QVBoxLayout()
        
        pdf_preview_scroll = QScrollArea()
        pdf_preview_scroll.setWidgetResizable(True)
        pdf_preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # Sağda scrollbar
        pdf_preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # Altta scrollbar
        self.pdf_render_widget = PDFRenderPreviewWidget(self)
        pdf_preview_scroll.setWidget(self.pdf_render_widget)
        right_panel_layout.addWidget(pdf_preview_scroll, stretch=1)
        
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
        
        right_panel_widget = QWidget()
        right_panel_widget.setLayout(right_panel_layout)
        main_split.addWidget(right_panel_widget, stretch=1)
        
        layout.addLayout(main_split)
        
        # Cevap anahtarı (alt taraf) - Tema uyumlu
        self.answer_key_label = QLabel("Cevap Anahtarı: ")
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128
        if is_dark:
            self.answer_key_label.setStyleSheet("""
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                background-color: #4A4A2A;
                color: #FFE082;
                border-radius: 5px;
            """)
        else:
            self.answer_key_label.setStyleSheet("""
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                background-color: #FFF9C4;
                color: #333;
                border-radius: 5px;
            """)
        layout.addWidget(self.answer_key_label)
        
        # Alt bar: Sayfa navigasyonu ve butonlar
        bottom_layout = QHBoxLayout()
        
        # Sayfa navigasyonu
        self.btn_prev_page = QPushButton("⟨ Önceki Sayfa")
        self.btn_prev_page.setStyleSheet("font-size: 12px; padding: 5px 10px;")
        self.btn_prev_page.clicked.connect(self.prev_page)
        bottom_layout.addWidget(self.btn_prev_page)
        
        self.lbl_page_info = QLabel("Sayfa 1 / 1")
        self.lbl_page_info.setStyleSheet("font-size: 12px; padding: 5px;")
        bottom_layout.addWidget(self.lbl_page_info)
        
        self.btn_next_page = QPushButton("Sonraki Sayfa ⟩")
        self.btn_next_page.setStyleSheet("font-size: 12px; padding: 5px 10px;")
        self.btn_next_page.clicked.connect(self.next_page)
        bottom_layout.addWidget(self.btn_next_page)
        
        bottom_layout.addStretch()
        
        # MADDE 4: Ayarları Sıfırla butonu
        btn_reset = QPushButton("Ayarları Sıfırla")
        btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        btn_reset.clicked.connect(self.reset_all_settings)
        bottom_layout.addWidget(btn_reset)
        
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
    
    
    def _update_pdf_preview(self, question_number: int = None, preserve_current_page: bool = True):
        """PDF export'u geçici dosyaya kaydet ve render et
        
        Args:
            question_number: Hangi sorunun sayfasını açacağız (None ise mevcut sayfa korunur)
            preserve_current_page: True ise mevcut sayfada kal (sadece içeriği güncelle)
        """
        try:
            import tempfile
            import os
            
            # Geçici PDF dosyası oluştur
            if self.temp_pdf_path is None:
                temp_dir = tempfile.gettempdir()
                self.temp_pdf_path = os.path.join(temp_dir, f"testmaker_preview_{os.getpid()}.pdf")
            
            # PDF export'u geçici dosyaya kaydet
            temp_path = Path(self.temp_pdf_path)
            export_test_pdf(
                selections=self.selections,
                out_path=temp_path,
                opts=self.export_options,
                pdf_docs=self.pdf_docs
            )
            
            # PDF'i PyMuPDF ile aç
            doc = fitz.open(str(temp_path))
            if doc.page_count == 0:
                self.pdf_render_widget.set_pdf_pixmap(None, 0, fit_to_window=True, preserve_page=False)
                doc.close()
                return
            
            # Hangi sayfayı açacağız?
            # preserve_current_page True ise mevcut sayfayı koru
            if preserve_current_page:
                page_index = self.pdf_render_widget.current_page
                # Sayfa sayısı değişmiş olabilir, sınırları kontrol et
                if page_index >= doc.page_count:
                    page_index = doc.page_count - 1
                if page_index < 0:
                    page_index = 0
            elif question_number is not None:
                # Bu sorunun hangi sayfada olduğunu bul
                found_page = self._find_question_page(question_number)
                if found_page is not None and 0 <= found_page < doc.page_count:
                    page_index = found_page
                else:
                    # Bulunamadı veya geçersiz, mevcut sayfayı koru
                    page_index = self.pdf_render_widget.current_page
                    if page_index >= doc.page_count:
                        page_index = doc.page_count - 1
                    if page_index < 0:
                        page_index = 0
            else:
                # Mevcut sayfayı koru
                page_index = self.pdf_render_widget.current_page
                if page_index >= doc.page_count:
                    page_index = doc.page_count - 1
                if page_index < 0:
                    page_index = 0
            
            # Sayfayı render et (yüksek kalite için DPI kullan)
            page = doc.load_page(page_index)
            # Render DPI: Yüksek kalite için 4x zoom (~288 DPI)
            render_scale = 4.0  # 4x zoom (yüksek kalite)
            mat = fitz.Matrix(render_scale, render_scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # QPixmap'e çevir
            from testmaker.utils.qimage_utils import qimage_from_fitz_pix
            qimg = qimage_from_fitz_pix(pix)
            pdf_pixmap = QPixmap.fromImage(qimg)
            
            # Widget'a gönder
            # İlk yükleme mi kontrol et (original_pixmap None ise ilk yükleme)
            is_first_load = (self.pdf_render_widget.original_pixmap is None or 
                           self.pdf_render_widget.original_pixmap.isNull())
            
            # İlk yüklemede fit_to_window=True, sonraki güncellemelerde False (zoom korunur)
            # preserve_page: İlk yüklemede False, güncellemelerde True (mevcut sayfayı koru)
            self.pdf_render_widget.set_pdf_pixmap(
                pdf_pixmap, 
                doc.page_count, 
                fit_to_window=is_first_load,  # İlk yüklemede pencereye sığdır, sonra zoom'u koru
                preserve_page=preserve_current_page and not is_first_load   # Güncellemelerde mevcut sayfayı koru
            )
            self.pdf_render_widget.current_page = page_index
            
            # Sayfa bilgisini güncelle
            self._update_page_info()
            
            # Cevap anahtarını güncelle
            self._update_answer_key(page_index)
            
            doc.close()
            
        except Exception as e:
            import traceback
            print(f"Hata: PDF preview güncellenirken: {e}\n{traceback.format_exc()}")
            self.pdf_render_widget.set_pdf_pixmap(None, 0, fit_to_window=False, preserve_page=False)
    
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
            
            # Sol panel'i yenile
            self.question_list_widget.set_selections(self.selections)
            
            # PDF preview'ı yenile
            self._update_pdf_preview(question_number=dragged_sel.number)
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
            
            # Yerlerini değiştir
            self.selections[idx1], self.selections[idx2] = self.selections[idx2], self.selections[idx1]
            
            # Numaraları yeniden sırala (1, 2, 3, ...)
            for idx, sel in enumerate(self.selections, start=1):
                sel.number = idx
            
            # Sol panel'i yenile (grid ve detaylar güncellenecek)
            self.question_list_widget.set_selections(self.selections)
            
            # PDF preview'ı yenile
            self._update_pdf_preview(preserve_current_page=True)
            
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
            
            # Sol panel'i yenile (grid ve detaylar güncellenecek)
            self.question_list_widget.set_selections(self.selections)
            
            # PDF preview'ı yenile
            self._update_pdf_preview(preserve_current_page=True)
            
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Soru eklenirken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")
    
    def _update_answer_key(self, page_index: int):
        """Cevap anahtarını güncelle (sadece o sayfadaki sorular için)"""
        try:
            # Bu sayfadaki soruları bul
            from testmaker.services.pdf_exporter import compute_layout
            
            # Tüm soruların layout'unu hesapla
            question_dimensions = []
            for idx, sel in enumerate(self.selections):
                pdf_key = getattr(sel, "pdf_key", None)
                page_idx = int(getattr(sel, "page_index", -1))
                norm = getattr(sel, "norm", None)
                
                if pdf_key and norm is not None:
                    doc = self.pdf_docs.get(str(pdf_key))
                    if doc:
                        page = doc.load_page(page_idx)
                        rect = fitz.Rect(norm)
                        zoom = self.export_options.zoom
                        dpi = 72.0
                        img_w_px = rect.width * zoom * dpi / 72.0
                        img_h_px = rect.height * zoom * dpi / 72.0
                    else:
                        img_w_px = 500
                        img_h_px = 300
                else:
                    img_w_px = 500
                    img_h_px = 300
                
                custom_gap_after_pt = getattr(sel, 'custom_gap_after_pt', None)
                display_scale = getattr(sel, 'display_scale', 1.0)
                question_dimensions.append((idx, img_w_px, img_h_px, custom_gap_after_pt, display_scale))
            
            render_dpi = getattr(self, 'render_dpi', 72.0)
            zoom = render_dpi / 72.0
            layout_result = compute_layout(
                question_dimensions=question_dimensions,
                opts=self.export_options,
                zoom=zoom,
                render_dpi=render_dpi,
                selections=self.selections,  # Soru numaralarını almak için
            )
            
            # Bu sayfadaki soruları bul (page_index + 1 çünkü page_num 1'den başlar)
            page_num = page_index + 1
            page_questions = []
            for layout in layout_result.question_layouts:
                if layout.page_num == page_num:
                    question_idx = layout.question_index
                    if 0 <= question_idx < len(self.selections):
                        sel = self.selections[question_idx]
                        answer = getattr(sel, 'answer', '').strip().upper() or '?'
                        page_questions.append((sel.number, answer))
            
            # Cevap anahtarını formatla
            if page_questions:
                answer_text = "Cevap Anahtarı: " + " | ".join([f"{num}. {ans}" for num, ans in page_questions])
            else:
                answer_text = "Cevap Anahtarı: (Bu sayfada soru yok)"
            
            self.answer_key_label.setText(answer_text)
        except Exception as e:
            import traceback
            print(f"Hata: Cevap anahtarı güncellenirken: {e}\n{traceback.format_exc()}")
            self.answer_key_label.setText("Cevap Anahtarı: (Hata)")
    
    def _find_question_page(self, question_number: int) -> int:
        """Bir sorunun hangi sayfada olduğunu bul (0-indexed)"""
        try:
            from testmaker.services.pdf_exporter import compute_layout
            
            # Tüm soruların boyutlarını hesapla (PDF export ile aynı mantık)
            question_dimensions = []
            question_index_map = {}  # {question_number: index_in_selections}
            
            for idx, sel in enumerate(self.selections):
                question_index_map[sel.number] = idx
                
                # PDF'den görsel boyutlarını tahmin et (norm'dan)
                pdf_key = getattr(sel, "pdf_key", None)
                page_index = int(getattr(sel, "page_index", -1))
                norm = getattr(sel, "norm", None)
                
                if pdf_key and norm is not None:
                    doc = self.pdf_docs.get(str(pdf_key))
                    if doc:
                        page = doc.load_page(page_index)
                        rect = fitz.Rect(norm)
                        # Görsel boyutlarını hesapla (piksel cinsinden)
                        # Zoom ile çarp (export_test_pdf ile aynı mantık)
                        zoom = self.export_options.zoom
                        # Norm rect'in genişliği ve yüksekliği PDF koordinatlarında
                        # Bunu piksel'e çevirmek için DPI kullan
                        dpi = 72.0  # Varsayılan DPI
                        img_w_px = rect.width * zoom * dpi / 72.0
                        img_h_px = rect.height * zoom * dpi / 72.0
                    else:
                        img_w_px = 500
                        img_h_px = 300
                else:
                    img_w_px = 500
                    img_h_px = 300
                
                custom_gap_after_pt = getattr(sel, 'custom_gap_after_pt', None)
                display_scale = getattr(sel, 'display_scale', 1.0)
                question_dimensions.append((idx, img_w_px, img_h_px, custom_gap_after_pt, display_scale))
            
            # Soru numarasına göre index bul
            if question_number not in question_index_map:
                return 0  # Bulunamadı, ilk sayfayı döndür
            
            question_index = question_index_map[question_number]
            
            # Layout hesapla (tüm sorular için)
            render_dpi = getattr(self, 'render_dpi', 72.0)
            zoom = render_dpi / 72.0
            layout_result = compute_layout(
                question_dimensions=question_dimensions,
                opts=self.export_options,
                zoom=zoom,
                render_dpi=render_dpi,
                selections=self.selections,  # Soru numaralarını almak için
            )
            
            # Sorunun sayfa numarasını bul
            for layout in layout_result.question_layouts:
                if layout.question_index == question_index:
                    page_num = layout.page_num
                    page_index = page_num - 1  # 0-indexed'e çevir
                    print(f"DEBUG: Soru {question_number} (index {question_index}) sayfa {page_num} (0-indexed: {page_index})")
                    return page_index
            
            print(f"UYARI: Soru {question_number} için layout bulunamadı")
            return 0
        except Exception as e:
            import traceback
            print(f"Hata: Soru sayfası bulunurken: {e}\n{traceback.format_exc()}")
            return 0
    
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
                display_scale = q.selection.display_scale or 1.0
                
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
                
                display_scale = q.selection.display_scale or 1.0
                
                # PDF export mantığı: ÖNCE px -> pt, SONRA display_scale, SONRA text_scale
                img_w_pt = (orig_w_px / zoom) * display_scale
                img_h_pt = (orig_h_px / zoom) * display_scale
                
                # Sonra text_scale uygula
                draw_w_pt = img_w_pt * text_scale
                draw_h_pt = img_h_pt * text_scale
                
                # Numara genişliği
                number_text = f"{q.selection.number}."
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
                    display_scale = q.selection.display_scale or 1.0
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
                        
                        display_scale = q.selection.display_scale or 1.0
                        img_w_pt = (orig_w_px / zoom) * display_scale
                        img_h_pt = (orig_h_px / zoom) * display_scale
                        draw_w_pt = img_w_pt * text_scale
                        draw_h_pt = img_h_pt * text_scale
                        
                        number_text = f"{getattr(q.selection, 'number', '?')}."
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
                                        
                                        display_scale = q.selection.display_scale or 1.0
                                        img_w_pt = (orig_w_px / zoom) * display_scale
                                        img_h_pt = (orig_h_px / zoom) * display_scale
                                        draw_w_pt = img_w_pt * text_scale
                                        draw_h_pt = img_h_pt * text_scale
                                        
                                        number_text = f"{getattr(q.selection, 'number', '?')}."
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
                
                display_scale = q.selection.display_scale or 1.0
                img_w_pt = (orig_w_px / zoom) * display_scale
                img_h_pt = (orig_h_px / zoom) * display_scale
                draw_w_pt = img_w_pt * text_scale
                draw_h_pt = img_h_pt * text_scale
                
                number_text = f"{getattr(q.selection, 'number', '?')}."
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
                
                # fit_to_window=False - zoom'u koru, sadece sayfa içeriğini güncelle
                self.pdf_render_widget.set_pdf_pixmap(
                    pdf_pixmap, 
                    doc.page_count, 
                    fit_to_window=False,  # Zoom'u koru
                    preserve_page=False   # Sayfa değişiyor, ama zoom korunuyor
                )
                self.pdf_render_widget.current_page = page_index
                
                # Cevap anahtarını güncelle
                self._update_answer_key(page_index)
            
            doc.close()
        except Exception as e:
            print(f"Hata: PDF sayfası yüklenirken: {e}")
    
    def _update_page_info(self):
        """Sayfa bilgisini güncelle"""
        current = self.pdf_render_widget.current_page + 1
        total = self.pdf_render_widget.total_pages
        self.lbl_page_info.setText(f"Sayfa {current} / {total}")
        
        # Butonları aktif/pasif yap
        self.btn_prev_page.setEnabled(current > 1)
        self.btn_next_page.setEnabled(current < total)
    
    def save_pdf(self):
        """PDF'yi kaydet"""
        from PyQt5.QtWidgets import QFileDialog
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "PDF Kaydet",
            "test.pdf",
            "PDF Files (*.pdf)"
        )
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
            QMessageBox.information(self, "Başarılı", f"PDF kaydedildi:\n{out_path}")
            # Dialog'u kapatma, kullanıcı isterse kendisi kapatabilir
        except Exception as e:
            import traceback
            error_msg = f"PDF kaydedilemedi:\n{str(e)}\n\n{traceback.format_exc()}"
            print(f"ERROR: {error_msg}")
            QMessageBox.critical(self, "Hata", error_msg)
