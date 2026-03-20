# selection.py
class Selection:
    def __init__(self, norm_rect, answer, pdf_key, page_index, number=0):
        self.norm = tuple(norm_rect)  # (fx,fy,fw,fh) 0..1
        self.answer = answer
        self.pdf_key = pdf_key
        self.page_index = page_index
        self.number = number
        self.preview_scale = 1.0
        self.display_scale = 1.0  # Ön izlemede görselin boyutunu değiştirmek için
        self.custom_gap_after_pt = None  # Bu sorudan sonraki özel boşluk (pt cinsinden, None ise varsayılan kullanılır)
        self.custom_gap_before_pt = None  # Bu sorudan önceki özel boşluk (pt cinsinden, None ise varsayılan kullanılır)
        # Yeni bölüm (section break) - preview/export için
        self.section_enabled = False
        self.section_title = ""
        self.section_restart_numbering = False  # True ise başlıktan sonra numara 1'den başlar
        self.section_start_new_page = False     # True ise başlık + sonraki sorular yeni sayfadan başlar
        # Bölüm aralığı ve stil seçenekleri (başlangıç soru üstünde başlık)
        self.section_end_number = None  # int or None (None => sadece başlangıç sorusu)
        self.section_fill_color = "#FFFFFF"   # hex
        self.section_text_color = "#000000"   # hex
        self.section_line_color = "#000000"   # hex (stroke)
        self.section_font_pt = 12.0           # default 12pt
        self.viewer = None  # PDFViewer referansı (opsiyonel)

        # --- Taslak (DB) için gömülü görsel desteği ---
        # PDF'lere bağımlı olmadan taslak yüklemek için seçim görselini PNG bytes olarak saklayabiliriz.
        # None ise klasik PDF kırpma yolu kullanılır.
        self.embedded_png = None  # type: bytes | None
        self.embedded_w_px = None
        self.embedded_h_px = None
    
    def __eq__(self, other):
        """İki Selection'ın aynı olup olmadığını kontrol eder."""
        if not isinstance(other, Selection):
            return False
        return (self.norm == other.norm and 
                self.pdf_key == other.pdf_key and 
                self.page_index == other.page_index)
    
    def __hash__(self):
        """Hash için kullanılır."""
        return hash((self.norm, self.pdf_key, self.page_index))