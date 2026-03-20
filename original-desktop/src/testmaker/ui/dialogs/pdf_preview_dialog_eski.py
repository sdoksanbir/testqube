# pdf_preview_dialog.py
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea, QWidget, QMessageBox, QApplication
)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer
from PyQt5.QtGui import QPainter, QPixmap, QPen, QBrush, QColor, QFont
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

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
        self.render_dpi: float = 300.0  # PDF render DPI'si (default 300, widget'a aktarılacak)
        
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
            render_dpi = getattr(self, 'render_dpi', 300.0) if hasattr(self, 'render_dpi') else 300.0
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
                
                # Numara yüksekliği (10pt font)
                box_h_pt = 12.0
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
                
                # Optional separator (export mantığı)
                if self.export_options.spaced and self.export_options.draw_separators:
                    y_px = int(y_px + 14)
            
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
            render_dpi = getattr(self, 'render_dpi', 300.0)
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
            # Debouncing: Timer'ı durdur ve yeniden başlat (200ms gecikme ile - performans için)
            if hasattr(self, 'reorganize_timer') and self.reorganize_timer:
                self.reorganize_timer.stop()
                self.reorganize_timer.start(200)  # 200ms gecikme
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
            render_dpi = getattr(self, 'render_dpi', 300.0)
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


class PDFPreviewDialog(QDialog):
    """PDF ön izleme ve düzenleme dialog'u"""
    
    def __init__(self, parent, selections: List[Selection], export_options: ExportOptions, pdf_docs: dict, render_dpi: float = 300.0):
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
        self.render_dpi = render_dpi  # PDF render DPI'si (300, 150, 600, vb. - kullanıcı değiştirebilir)
        
        layout = QVBoxLayout(self)
        
        # Başlık
        title = QLabel("Soruların sırasını değiştirmek için üstteki küçük kutuları sürükleyin")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Yatay soru sıralayıcı (Seçenek 4)
        self.sorter_widget = QuestionSorterWidget(parent=None, dialog=self)  # Dialog referansını ver
        self.sorter_widget.setMinimumHeight(120)
        self.sorter_widget.setMaximumHeight(120)
        self.sorter_widget.setMinimumWidth(400)  # Başlangıç genişliği
        self.sorter_widget.resize(400, 120)  # Başlangıç boyutu
        
        sorter_scroll = QScrollArea()
        sorter_scroll.setWidgetResizable(False)  # Manuel genişlik kontrolü için
        sorter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sorter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sorter_scroll.setWidget(self.sorter_widget)
        sorter_scroll.setMinimumHeight(130)
        sorter_scroll.setMaximumHeight(130)
        layout.addWidget(sorter_scroll)
        
        # Alt başlık
        subtitle = QLabel("Soruların büyüklüğünü düzenleyin (Sol üst köşe sabit, sağ alt köşeden büyütün/küçültün)")
        subtitle.setStyleSheet("font-size: 12px; padding: 5px;")
        layout.addWidget(subtitle)
        
        # Scroll area ile ön izleme widget'ı
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)  # Widget boyutunu manuel ayarlayacağız
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_widget = PDFPreviewWidget(self)
        scroll.setWidget(self.preview_widget)
        layout.addWidget(scroll)
        
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
        btn_cancel.setStyleSheet("font-size: 14px; font-weight: bold;")
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
        self._prepare_preview()
    
    def reset_all_settings(self):
        """MADDE 4: Tüm boşluk ayarlarını sıfırla ve preview'ı yenile"""
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
                for q in self.preview_widget.questions:
                    q.custom_gap_after_pt = None
                    q.custom_gap_before_pt = None
                    # Selection objesine de yaz
                    q.selection.custom_gap_after_pt = None
                    q.selection.custom_gap_before_pt = None
                
                # Dialog'daki Selection objelerine de yaz
                for sel in self.selections:
                    sel.custom_gap_after_pt = None
                    sel.custom_gap_before_pt = None
                
                # Preview'ı yenile
                self._prepare_preview()
                
                # İlk sayfaya dön
                self.preview_widget.current_page = 0
                self._update_page_info()
                
                QMessageBox.information(self, "Başarılı", "Tüm ayarlar sıfırlandı.")
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Hata", f"Ayarlar sıfırlanırken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}")
    
    def on_questions_reordered(self):
        """Soru sırası değiştiğinde çağrılır (Seçenek 4)"""
        try:
            print(f"DEBUG: ========== on_questions_reordered çağrıldı ==========")
            
            # Sorter widget'tan güncel sıralamayı al
            reordered_questions = self.sorter_widget.get_questions()
            print(f"DEBUG: Yeni sıralama - {len(reordered_questions)} soru:")
            for idx, q in enumerate(reordered_questions, start=1):
                print(f"  {idx}. Soru numarası: {q.selection.number}, pixmap: {q.cropped_pixmap.width()}x{q.cropped_pixmap.height()}")
            
            # ÖNEMLİ: self.selections listesini de güncelle (PDF export için)
            # PreviewQuestion objelerinden Selection objelerini al ve yeni sıraya göre düzenle
            self.selections = [q.selection for q in reordered_questions]
            print(f"DEBUG: self.selections güncellendi - {len(self.selections)} seçim")
            
            # Numaraları güncelle
            for idx, q in enumerate(reordered_questions, start=1):
                q.selection.number = idx
            
            # Pozisyonları sıfırla (yeniden layout için)
            for q in reordered_questions:
                q.x = 0
                q.y = 0
                q.display_width = 0
                q.display_height = 0
                q.page_num = 0
                q.col_num = 0
            
            # Soruları yeniden sayfalara ayır
            new_pages = self._organize_into_pages_pdf_export_logic(reordered_questions)
            print(f"DEBUG: Yeni sayfa yapısı oluşturuldu - {len(new_pages)} sayfa")
            
            # Preview widget'a güncel sırayı ve sayfaları aktar (set_questions kullan)
            # Bu metod layout'u da otomatik hesaplayacak
            self.preview_widget.set_questions(list(reordered_questions), new_pages)
            
            # ÖNEMLİ: Sorter widget'a da güncel sırayı aktar (yeniden düzenlenmiş sıraya göre)
            # new_pages'ten tüm soruları sırayla al
            all_reorganized_questions = []
            for page in new_pages:
                all_reorganized_questions.extend(page)
            self.sorter_widget.set_questions(all_reorganized_questions)
            
            # İlk sayfaya dön (yeniden düzenlendi)
            self.preview_widget.current_page = 0
            
            # Widget'ı zorla güncelle
            self.preview_widget.update()
            self.preview_widget.repaint()
            
            # Sayfa bilgisini güncelle
            self._update_page_info()
            
            print(f"DEBUG: on_questions_reordered tamamlandı - preview güncellendi ({len(reordered_questions)} soru, {len(new_pages)} sayfa)")
        except Exception as e:
            import traceback
            print(f"Hata: Soru sırası güncellenirken: {e}\n{traceback.format_exc()}")
    
    def _prepare_preview(self):
        """Görselleri kırp ve sayfalara ayır - PDF export mantığını kullan"""
        try:
            print(f"DEBUG: _prepare_preview başladı - {len(self.selections)} seçim var")
            
            # 1. Görselleri kırp
            questions = []
            for idx, sel in enumerate(self.selections):
                try:
                    print(f"DEBUG: Soru {idx + 1} kırpılıyor...")
                    cropped = self.preview_widget._crop_question_image(sel, self.pdf_docs)
                    if not cropped.isNull():
                        print(f"DEBUG: Soru {idx + 1} kırpıldı - boyut: {cropped.width()}x{cropped.height()}")
                        # Selection'daki custom_gap değerlerini PreviewQuestion'a kopyala
                        custom_gap_after = getattr(sel, 'custom_gap_after_pt', None)
                        custom_gap_before = getattr(sel, 'custom_gap_before_pt', None)
                        q = PreviewQuestion(
                            selection=sel, 
                            cropped_pixmap=cropped,
                            custom_gap_after_pt=custom_gap_after,
                            custom_gap_before_pt=custom_gap_before
                        )
                        questions.append(q)
                    else:
                        print(f"DEBUG: Soru {idx + 1} kırpılamadı (pixmap null)")
                except Exception as e:
                    print(f"Hata: Soru {idx + 1} kırpılırken hata oluştu: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            print(f"DEBUG: {len(questions)} soru başarıyla kırpıldı")
            
            if not questions:
                QMessageBox.warning(self, "Hata", "Hiçbir soru görseli yüklenemedi.")
                return
            
            # 2. Soruları PDF export mantığını simüle ederek sayfalara ayır
            print("DEBUG: Sorular sayfalara ayrılıyor...")
            pages = self._organize_into_pages_pdf_export_logic(questions)
            
            print(f"DEBUG: {len(pages)} sayfa oluşturuldu")
            if not pages:
                QMessageBox.warning(self, "Hata", "Sorular sayfalara ayrılamadı.")
                return
            
            # 3. Widget'a gönder (render_dpi'yi de aktar)
            print("DEBUG: Widget'a gönderiliyor...")
            self.preview_widget.render_dpi = self.render_dpi  # Render DPI'yi widget'a aktar
            self.preview_widget.set_questions(questions, pages)
            self.preview_widget.set_export_options(self.export_options)
            
            # 4. Sorter widget'a soruları gönder (Seçenek 4)
            print(f"DEBUG: Sorter widget'a {len(questions)} soru gönderiliyor...")
            self.sorter_widget.set_questions(questions)
            
            self._update_page_info()
            print("DEBUG: _prepare_preview tamamlandı")
        except Exception as e:
            import traceback
            error_msg = f"Önizleme hazırlanırken hata oluştu:\n{str(e)}\n\n{traceback.format_exc()}"
            QMessageBox.critical(self, "Kritik Hata", error_msg)
            print(error_msg)
    
    def _organize_into_pages_pdf_export_logic(self, questions: List[PreviewQuestion]) -> List[List[PreviewQuestion]]:
        """PDF export mantığını TAM OLARAK simüle ederek soruları sayfalara ayır"""
        try:
            from testmaker.services.pdf_exporter import mm_to_pt
            
            if not self.export_options or not questions:
                return [[q] for q in questions] if questions else [[]]
            
            pages = []
            current_page = []
            
            # PDF export mantığını simüle et - TAM OLARAK AYNI
            page_w_pt, page_h_pt = self.export_options.page_size_pt()
            ml_pt, mr_pt, mt_pt, mb_pt = self.export_options.margins_pt()
            col_gap_pt = self.export_options.column_gap_pt()
            question_gap_pt = self.export_options.question_gap_pt()
            cols = max(1, min(6, int(self.export_options.columns or 1)))
            # Render DPI'yi kullan: zoom = render_dpi / 72.0 (PDF export ile aynı mantık)
            render_dpi = getattr(self, 'render_dpi', 300.0)
            zoom = render_dpi / 72.0  # PDF export ile AYNI: render_dpi / 72.0
            text_scale = 10.0 / 12.0
            
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
            
            # Header yüksekliği - PDF export ile TAM AYNI hesaplama
            # PDF export'ta _draw_header fonksiyonu:
            # İlk sayfada:
            #   y = page_h - mt (başlangıç)
            #   header_height = 60pt
            #   inner_padding = 8pt
            #   inner_height = 28pt
            #   inner_y_bottom = y - 8 - 28 = y - 36
            #   desc_y = inner_y_bottom - 8 = y - 44
            #   desc_y -= 14 (açıklama yüksekliği)
            #   y = desc_y - 8 = y - 44 - 14 - 8 = y - 66
            #   Yani: y = page_h - mt - 66
            # Diğer sayfalarda:
            #   y = page_h - mt (başlangıç)
            #   y -= 20 (okul adından sonra boşluk)
            #   Yani: y = page_h - mt - 20
            def calculate_y_start(page_num: int) -> float:
                """PDF export'taki _draw_header ile aynı y başlangıç değerini hesapla"""
                if page_num == 0:  # İlk sayfa
                    # PDF export'ta: y = page_h - mt (başlangıç)
                    # inner_padding = 8, inner_height = 28
                    # inner_y_bottom = y - 8 - 28 = y - 36
                    # line_y = inner_y_bottom - 4 = y - 40
                    # desc_y_top = line_y - 8 = y - 48
                    # desc_height = max(10mm, ...) ≈ 28pt (minimum)
                    # desc_y_bottom = desc_y_top - desc_height = y - 48 - 28 = y - 76
                    # y = desc_y_bottom - 8.0 = y - 76 - 8 = y - 84
                    # Yani: y_start = page_h - mt - 84 (8pt boşluk ile)
                    # Ama kod basitleştirilmiş: 66 + header'dan sonra boşluk (8pt) = 74
                    # Gerçekte: header yüksekliği dinamik, ama yaklaşık 76pt + 8pt = 84pt
                    return page_h_pt - mt_pt - 84.0  # PDF export ile uyumlu (8pt boşluk)
                else:
                    # Diğer sayfalarda: header_y_bottom = page_h - mt - 40.0 (banner height)
                    # contentStartY = header_y_bottom - headerBottomGapPt (default 10mm = ~28.35pt)
                    header_bottom_gap_pt = self.export_options.header_bottom_gap_pt()
                    return page_h_pt - mt_pt - 40.0 - header_bottom_gap_pt
            
            # Sütun sayılarını hesapla
            left_columns_count = (cols + 1) // 2
            right_columns_count = cols - left_columns_count
            
            # Yükseklik ve pozisyon takibi (PDF export mantığı ile aynı)
            # Her sütun için son sorunun alt kenarını takip et (çakışma kontrolü için)
            prev_bottom_by_col = {}  # {col_idx: y_bottom} - Her sütun için son sorunun alt kenarı (PDF koordinat sisteminde)
            page_num = 0
            def new_page():
                nonlocal y, col_idx, x_col, page_num, prev_q_by_col, prev_bottom_by_col
                if current_page:
                    pages.append(current_page[:])
                current_page.clear()
                page_num += 1
                y = calculate_y_start(page_num)
                col_idx = 0
                if cols > 1:
                    x_col = ml_pt if col_idx < left_columns_count else x_line_center + col_gap_pt * 0.5
                else:
                    x_col = ml_pt
                # Yeni sayfa başı, tüm sütunlar için bir önceki soru yok
                prev_q_by_col.clear()
                prev_bottom_by_col.clear()  # Yeni sayfa başı, tüm sütunlar için alt kenar bilgisi yok
            
            def next_column():
                nonlocal col_idx, x_col, y, prev_q_by_col, prev_bottom_by_col
                col_idx += 1
                if col_idx >= cols:
                    new_page()
                else:
                    if cols > 1:
                        if col_idx < left_columns_count:
                            x_col = ml_pt + col_idx * (col_w_pt + col_gap_pt)
                        else:
                            right_col_index = col_idx - left_columns_count
                            reduced_gap = col_gap_pt * 0.5
                            x_col = x_line_center + reduced_gap + right_col_index * (col_w_pt + reduced_gap)
                    else:
                        x_col = ml_pt
                    y = calculate_y_start(page_num)
                    # Yeni sütun başı, bu sütun için bir önceki soru yok
                    if col_idx in prev_q_by_col:
                        del prev_q_by_col[col_idx]
                    if col_idx in prev_bottom_by_col:
                        del prev_bottom_by_col[col_idx]  # Yeni sütun başı, alt kenar bilgisi yok
            
            # İlk sayfa - PDF export ile AYNI y başlangıç pozisyonu
            y = calculate_y_start(0)
            col_idx = 0
            if cols > 1:
                if col_idx < left_columns_count:
                    x_col = ml_pt
                else:
                    right_col_index = col_idx - left_columns_count
                    reduced_gap = col_gap_pt * 0.5
                    x_col = x_line_center + reduced_gap + right_col_index * (col_w_pt + reduced_gap)
            else:
                x_col = ml_pt
            
            # Soruları tek tek işle (PDF export mantığı ile aynı)
            # Her sütun için bir önceki soruyu takip et
            prev_q_by_col = {}  # {col_idx: prev_q}
            # Her sayfa için son sütunların alt kenarını takip et (sayfalar arası çakışma kontrolü için)
            last_bottom_by_page_col = {}  # {(page_idx, col_idx): y_bottom} - Her sayfa için son sütunların alt kenarı
            
            for q_idx, q in enumerate(questions):
                # Soru boyutunu hesapla (PDF export mantığı ile aynı)
                orig_w_px = q.cropped_pixmap.width()
                orig_h_px = q.cropped_pixmap.height()
                
                # ÖNEMLİ: Soruları ASLA atlama! Geçersiz boyutlu sorular için minimum boyutlar kullan
                if orig_w_px <= 0:
                    orig_w_px = 100  # Minimum genişlik
                    print(f"DEBUG: Soru {q_idx + 1} (numara {q.selection.number}) geçersiz genişlik, minimum 100px kullanılıyor")
                if orig_h_px <= 0:
                    orig_h_px = 100  # Minimum yükseklik
                    print(f"DEBUG: Soru {q_idx + 1} (numara {q.selection.number}) geçersiz yükseklik, minimum 100px kullanılıyor")
                
                display_scale = q.selection.display_scale or 1.0
                
                # PDF export mantığı: ÖNCE px -> pt, SONRA display_scale, SONRA text_scale
                # Export'ta: img_w_pt = img_w_px / zoom * display_scale, sonra draw_w = img_w_pt * text_scale
                img_w_pt = (orig_w_px / zoom) * display_scale
                img_h_pt = (orig_h_px / zoom) * display_scale
                
                # Sonra text_scale uygula (PDF export'taki gibi - 10/12 = 0.833)
                draw_w_pt = img_w_pt * text_scale
                draw_h_pt = img_h_pt * text_scale
                
                # Numara genişliği (10pt font - export'taki gibi)
                number_text = f"{getattr(q.selection, 'number', '?')}."
                number_width_pt = max(6.0, len(number_text) * 6.0)  # Minimum 6pt, yaklaşık
                number_gap_pt = 4.0
                right_padding_pt = 4.0
                available_width_pt = col_w_pt - number_width_pt - number_gap_pt - right_padding_pt
                
                # Görsel genişliğine sığdır (export mantığı - TAM OLARAK AYNI)
                # Export'ta: if draw_w > available_width: scale = available_width / draw_w, draw_w = available_width, draw_h = draw_h * scale
                if draw_w_pt > available_width_pt:
                    scale_factor = available_width_pt / draw_w_pt
                    draw_w_pt = available_width_pt
                    draw_h_pt = draw_h_pt * scale_factor
                
                # Numara yüksekliği (10pt font)
                box_h_pt = 12.0
                
                # Özel boşluk varsa onu kullan, yoksa varsayılan boşluğu kullan
                # PDF export'ta her soru için sadece alt boşluk (gap_after) var
                # Üst boşluk bir önceki sorunun alt boşluğu olarak otomatik olarak uygulanıyor
                actual_gap_after_pt = q.custom_gap_after_pt if q.custom_gap_after_pt is not None else question_gap_pt
                
                # Gerekli yükseklik (PDF export mantığı ile TAM AYNI)
                # PDF export'ta: needed = max(box_h, draw_h) + gap_after
                # Üst boşluk kontrol sırasında kullanılmaz, çünkü y pozisyonu zaten bir önceki sorudan sonra geliyor
                needed_pt = max(box_h_pt, draw_h_pt) + actual_gap_after_pt
                if self.export_options.spaced and self.export_options.draw_separators:
                    needed_pt += 14.0
                
                # Debug: Soru bilgileri
                print(f"DEBUG: Soru {q_idx + 1} (numara {q.selection.number}) - y={y:.1f}, needed={needed_pt:.1f}, mb={mb_pt:.1f}, draw_h={draw_h_pt:.1f}, gap_after={actual_gap_after_pt:.1f}")
                print(f"  -> Kontrol: (y - needed) = {y - needed_pt:.1f}, mb = {mb_pt:.1f}, sığıyor mu? {(y - needed_pt) >= mb_pt}")
                
                # Sayfaya sığıyor mu? (PDF export mantığı - TAM AYNI)
                # PDF export'ta: if (y - needed) < mb: next_column()
                # y pozisyonu bir önceki sorudan sonraki pozisyonu gösteriyor (üst boşluk zaten uygulanmış)
                # Önce mevcut sütunda sığıyor mu kontrol et
                if (y - needed_pt) < mb_pt:
                    print(f"DEBUG: Soru {q_idx + 1} (numara {q.selection.number}) mevcut sütuna sığmıyor (y={y:.1f}, needed={needed_pt:.1f}, mb={mb_pt:.1f}), sütun/sayfa değiştiriliyor...")
                    # Önce sütun değiştirmeyi dene
                    if col_idx < cols - 1:
                        # Başka sütun var, sütun değiştir
                        next_column()
                        print(f"DEBUG: Yeni sütun: col_idx={col_idx}, y={y:.1f}")
                        # Yeni sütun başı, bir önceki soru yok (bu sütun için)
                        if col_idx in prev_q_by_col:
                            del prev_q_by_col[col_idx]
                        # Yeni sütunda da sığıyor mu kontrol et
                        if (y - needed_pt) < mb_pt:
                            # Yeni sütunda da sığmıyor, yeni sayfa oluştur
                            print(f"DEBUG: Soru {q_idx + 1} yeni sütunda da sığmıyor, yeni sayfa oluşturuluyor...")
                            # ÖNEMLİ: Bir önceki sayfanın son sütunlarının alt kenarını kaydet (sayfalar arası çakışma kontrolü için)
                            if page_num > 0:  # Yeni sayfa oluşturulmadan önce
                                for c_idx in range(cols):
                                    if (page_num - 1, c_idx) in last_bottom_by_page_col:
                                        # Bir önceki sayfanın bu sütunundaki son sorunun alt kenarı
                                        pass  # Şu an için kaydet, sonra kullanılacak
                            new_page()
                            print(f"DEBUG: Yeni sayfa: page_num={page_num}, y={y:.1f}")
                            # Yeni sayfa başı, tüm sütunlar için bir önceki soru yok
                            prev_q_by_col.clear()
                            prev_bottom_by_col.clear()
                    else:
                        # Başka sütun yok, direkt yeni sayfa oluştur
                        print(f"DEBUG: Soru {q_idx + 1} başka sütun yok, yeni sayfa oluşturuluyor...")
                        # ÖNEMLİ: Bir önceki sayfanın son sütunlarının alt kenarını kaydet
                        if page_num > 0:  # Yeni sayfa oluşturulmadan önce
                            for c_idx in range(cols):
                                if c_idx in prev_bottom_by_col:
                                    last_bottom_by_page_col[(page_num - 1, c_idx)] = prev_bottom_by_col[c_idx]
                                    print(f"DEBUG: Önceki sayfa {page_num - 1}, sütun {c_idx} son alt kenarı kaydedildi: {prev_bottom_by_col[c_idx]:.1f}")
                        new_page()
                        print(f"DEBUG: Yeni sayfa: page_num={page_num}, y={y:.1f}")
                        # Yeni sayfa başı, tüm sütunlar için bir önceki soru yok
                        prev_q_by_col.clear()
                        prev_bottom_by_col.clear()
                    
                    # ÖNEMLİ: Yeni sayfada soru yerleştirilirken, bir önceki sayfanın son sütunlarıyla çakışma kontrolü yap
                    if page_num > 0:  # İlk sayfa değilse
                        prev_page_col_key = (page_num - 1, col_idx)
                        if prev_page_col_key in last_bottom_by_page_col:
                            prev_page_bottom = last_bottom_by_page_col[prev_page_col_key]
                            # Yeni sorunun üst kenarı bir önceki sayfanın son sorunun alt kenarından küçük olmalı
                            if y >= prev_page_bottom:
                                print(f"DEBUG: ÇAKIŞMA: Soru {q_idx + 1} (numara {q.selection.number}) önceki sayfanın son sorularıyla çakışıyor! (y={y:.1f}, prev_bottom={prev_page_bottom:.1f})")
                                # Çakışma varsa, yeni sorunun üst kenarını bir önceki sayfanın son sorunun alt kenarından küçük yap
                                y = prev_page_bottom - 0.1
                                print(f"DEBUG: Sayfalar arası çakışma düzeltildi - y={y:.1f}")
                                # Eğer bu düzeltme sonrası sayfaya sığmıyorsa, sütun değiştir veya sayfa değiştir
                                if (y - needed_pt) < mb_pt:
                                    print(f"DEBUG: Çakışma düzeltmesi sonrası sayfaya sığmıyor, yeni sütuna/sayfaya geçiliyor...")
                                    if col_idx < cols - 1:
                                        next_column()
                                    else:
                                        new_page()
                    
                    # Yeni sayfa/sütunda hala sığmıyorsa sorunu bildir (çok yüksek soru)
                    if (y - needed_pt) < mb_pt:
                        print(f"DEBUG: UYARI: Soru {q_idx + 1} (numara {q.selection.number}) çok yüksek! (needed={needed_pt:.1f}, available={y - mb_pt:.1f})")
                
                # ÖNEMLİ: AYNI SAYFADA bir önceki soruyla çakışma kontrolü (aynı sütunda)
                y_top = y  # Yeni sorunun üst kenarı (PDF koordinat sisteminde)
                if col_idx in prev_bottom_by_col:
                    prev_bottom = prev_bottom_by_col[col_idx]  # Aynı sayfadaki bir önceki sorunun alt kenarı
                    # Çakışma kontrolü: yeni sorunun üst kenarı bir önceki sorunun alt kenarından küçük olmalı
                    if y_top >= prev_bottom:
                        print(f"DEBUG: ÇAKIŞMA: Soru {q_idx + 1} (numara {q.selection.number}) aynı sayfadaki bir önceki soruyla çakışıyor! (y_top={y_top:.1f}, prev_bottom={prev_bottom:.1f})")
                        # Çakışma varsa, yeni sorunun üst kenarını bir önceki sorunun alt kenarından küçük yap
                        y_top = prev_bottom - 0.1
                        y = y_top
                        print(f"DEBUG: Aynı sayfa içi çakışma düzeltildi - y_top={y_top:.1f}")
                        # Eğer bu düzeltme sonrası sayfaya sığmıyorsa, sütun/sayfa değiştir
                        if (y_top - needed_pt) < mb_pt:
                            print(f"DEBUG: Çakışma düzeltmesi sonrası sayfaya sığmıyor, sütun/sayfa değiştiriliyor...")
                            if col_idx < cols - 1:
                                next_column()
                                y_top = y
                            else:
                                new_page()
                                y_top = y
                
                # Soruyu sayfaya ekle
                current_page.append(q)
                q.col_num = col_idx  # Sütun numarasını kaydet
                print(f"DEBUG: Soru {q_idx + 1} sayfaya eklendi - sayfa {page_num + 1}, sütun {col_idx}, y_top={y_top:.1f}")
                
                # Y pozisyonunu güncelle (PDF export mantığı - TAM OLARAK AYNI)
                # PDF export'ta: y = y_top - max(box_h, draw_h) - gap_after_q
                y_bottom = y_top - max(box_h_pt, draw_h_pt) - actual_gap_after_pt
                
                # Alt margin kontrolü: y pozisyonu mb (alt margin) değerinden küçük olmamalı
                if y_bottom < mb_pt:
                    print(f"DEBUG: UYARI: Soru {q_idx + 1} (numara {q.selection.number}) alt margin'ı geçiyor! (y_bottom={y_bottom:.1f}, mb={mb_pt:.1f})")
                    y_bottom = mb_pt
                
                y = y_bottom  # Y pozisyonunu güncelle (bir sonraki soru için başlangıç pozisyonu)
                
                # Optional separator (export mantığı)
                if self.export_options.spaced and self.export_options.draw_separators:
                    y -= 14.0
                
                # Bu sorunun alt kenarını kaydet (bir sonraki soru için çakışma kontrolü için)
                prev_bottom_by_col[col_idx] = y_bottom
                # Bu sayfanın bu sütunundaki son sorunun alt kenarını kaydet (sayfalar arası çakışma kontrolü için)
                last_bottom_by_page_col[(page_num, col_idx)] = y_bottom
                
                print(f"DEBUG: Soru {q_idx + 1} yerleştirildi - y_after={y:.1f}, y_bottom={y_bottom:.1f}")
                print(f"DEBUG: Sayfa {page_num + 1}, sütun {col_idx} son alt kenarı: {y_bottom:.1f}")
                
                # Bir sonraki soru için bu soruyu bir önceki soru olarak kaydet (aynı sütunda)
                prev_q_by_col[col_idx] = q
            
            # Son sayfayı ekle
            if current_page:
                pages.append(current_page)
            
            # Eğer hiç sayfa yoksa boş sayfa ekle
            if not pages:
                pages = [[]]
            
            # Debug: Sayfa yapısını kontrol et
            total_q_in_pages = sum(len(page) for page in pages)
            print(f"DEBUG: _organize_into_pages_pdf_export_logic tamamlandı - {len(pages)} sayfa, toplam {total_q_in_pages} soru (giriş: {len(questions)} soru)")
            for page_idx, page in enumerate(pages):
                if page:
                    print(f"  Sayfa {page_idx + 1}: {len(page)} soru - numaralar: {[q.selection.number for q in page]}")
                else:
                    print(f"  Sayfa {page_idx + 1}: BOŞ")
            
            # ÖNEMLİ: Tüm soruların yerleştirildiğini kontrol et (ASLA soru kaybetme)
            total_q_in_pages = sum(len(page) for page in pages)
            if total_q_in_pages != len(questions):
                print(f"UYARI: Tüm sorular yerleştirilmedi! Giriş: {len(questions)} soru, Yerleştirilen: {total_q_in_pages} soru")
                # Eksik soruları son sayfaya ekle (asla soru kaybetme)
                placed_questions = set()
                for page in pages:
                    for q in page:
                        placed_questions.add(id(q))  # Obje ID'si ile takip
                missing_questions = [q for q in questions if id(q) not in placed_questions]
                if missing_questions:
                    print(f"DEBUG: {len(missing_questions)} eksik soru bulundu, son sayfaya ekleniyor...")
                    if pages:
                        pages[-1].extend(missing_questions)
                    else:
                        pages.append(missing_questions)
            
            return pages
        except Exception as e:
            import traceback
            print(f"Hata: Sayfalara ayırma sırasında hata: {e}\n{traceback.format_exc()}")
            # Hata durumunda her soruyu ayrı sayfaya koy
            return [[q] for q in questions] if questions else [[]]
    
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
                        
                        box_h_pt = 12.0
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
                                        
                                        box_h_pt = 12.0
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
                
                box_h_pt = 12.0
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
        if self.preview_widget.current_page > 0:
            self.preview_widget.go_to_page(self.preview_widget.current_page - 1)
            self._update_page_info()
    
    def next_page(self):
        """Sonraki sayfaya git"""
        if self.preview_widget.current_page < len(self.preview_widget.pages) - 1:
            self.preview_widget.go_to_page(self.preview_widget.current_page + 1)
            self._update_page_info()
    
    def _update_page_info(self):
        """Sayfa bilgisini güncelle"""
        current = self.preview_widget.current_page + 1
        total = len(self.preview_widget.pages)
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
            # ÖNEMLİ: PreviewQuestion'lardaki custom_gap değerlerini Selection objelerine kopyala
            # Bu işlem dialog içindeki Selection objelerini günceller
            # MainWindow'daki Selection objelerine de aktarılacak (accept/reject'te)
            gap_after_map = {}  # {selection.number: custom_gap_after_pt}
            gap_before_map = {}  # {selection.number: custom_gap_before_pt}
            
            # Tüm PreviewQuestion'lardan gap değerlerini topla
            for q in self.preview_widget.questions:
                # Selection objesine direkt referans var, numara ile eşleştir
                sel_number = q.selection.number
                if q.custom_gap_after_pt is not None:
                    gap_after_map[sel_number] = q.custom_gap_after_pt
                    print(f"DEBUG: save_pdf - Soru {sel_number} için custom_gap_after_pt={q.custom_gap_after_pt:.2f}pt kaydedildi")
                else:
                    # None ise, Selection'daki değeri de None yap (varsayılan kullanılsın)
                    gap_after_map[sel_number] = None
                
                if q.custom_gap_before_pt is not None:
                    gap_before_map[sel_number] = q.custom_gap_before_pt
                    print(f"DEBUG: save_pdf - Soru {sel_number} için custom_gap_before_pt={q.custom_gap_before_pt:.2f}pt kaydedildi")
                else:
                    gap_before_map[sel_number] = None
            
            # Dialog içindeki Selection objelerine custom_gap değerlerini kopyala
            # ÖNEMLİ: Selection objelerinin numaralarına göre eşleştir
            for sel in self.selections:
                sel_number = sel.number
                if sel_number in gap_after_map:
                    sel.custom_gap_after_pt = gap_after_map[sel_number]
                    if gap_after_map[sel_number] is not None:
                        print(f"DEBUG: save_pdf - Selection {sel_number} güncellendi: custom_gap_after_pt={sel.custom_gap_after_pt:.2f}pt")
                    else:
                        print(f"DEBUG: save_pdf - Selection {sel_number} güncellendi: custom_gap_after_pt=None (varsayılan kullanılacak)")
                
                if sel_number in gap_before_map:
                    sel.custom_gap_before_pt = gap_before_map[sel_number]
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
