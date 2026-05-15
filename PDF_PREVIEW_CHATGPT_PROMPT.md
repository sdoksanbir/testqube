# Original-Desktop PDF Önizleme Kodunu Anlama - ChatGPT Prompt

Bu dosya, `original-desktop` projesindeki PDF önizleme / kağıt hazırlama diyaloğunu web uygulamasına taşımak için kullanılacak referans prompt içerir. ChatGPT veya başka bir LLM'e aşağıdaki metni göndererek kod yapısını ve akışını anlayabilirsiniz.

---

## Kopyalanacak Prompt (ChatGPT'ye yapıştırın)

```
Aşağıdaki PyQt5 projesindeki PDF önizleme diyaloğunu analiz et. Özellikle şunları açıkla:

1. **PDFPreviewWidget (PDFPreviewWidget sınıfı)**:
   - Sorular nasıl çiziliyor? (paintEvent, cropped_pixmap, display_width, display_height)
   - PDF üzerinde soruya tıklandığında sol menüde seçim nasıl senkronize ediliyor? (mousePressEvent, dlg.question_list_widget._on_question_clicked)
   - Sorunun büyütülmesi/küçültülmesi (resize) nasıl çalışıyor? (resize handle, bottom_right, mouseMoveEvent, display_scale)
   - Sorular arası boşluk ayarlama (gap adjustment) nasıl yapılıyor? (_get_gap_line_rect, _gap_being_adjusted, custom_gap_after_pt, mouse drag)

2. **QuestionListWidget (sol panel)**:
   - Soru numarası grid yapısı
   - Seçili soru detay kutusu (Boşluk, Boyut, Soru Yerleştir)
   - _on_question_clicked ile preview widget ile senkronizasyon

3. **Bölüm ekle (SectionRange, section_panel)**:
   - SectionRange dataclass alanları
   - Bölüm aralığı (start_idx, end_idx) seçimi
   - Restart numbering, start new page
   - Stil (fill_color, text_color, line_color, font_pt)

4. **Soru yerleştirme (_swap_questions, _insert_question_after, _reorder_questions)**:
   - Yer değiştir (swap) vs altına ekle (insert) farkı
   - Selections listesinde numara güncelleme

5. **Export akışı**:
   - PreviewQuestion'dan Selection'a custom_gap, display_scale aktarımı
   - _reorganize_after_gap_adjustment
   - export_test_pdf çağrısı ve ExportOptions

Proje yolu: original-desktop/src/testmaker/ui/dialogs/pdf_preview_dialog.py (yaklaşık 6500 satır)
```

---

## Kısa Özet (Proje İçinde Kullanım İçin)

- **PDF önizleme**: Original-desktop, PDF'yi iframe yerine canvas üzerinde soru görselleri (QPixmap) olarak çiziyor. Her soru `PreviewQuestion` ile temsil ediliyor; `custom_gap_after_pt`, `display_scale` gibi alanlar var.
- **Tıklama → sol menü seçimi**: `mousePressEvent` içinde soru rect'ine tıklanınca `dlg.question_list_widget._on_question_clicked(q.selection.number)` çağrılıyor.
- **Büyütme/küçültme**: Seçili soruda sağ alt köşede resize handle; sürükleyince `display_scale` güncelleniyor.
- **Boşluk ayarlama**: Her sorunun altında çizgi (gap line); sürüklenince `custom_gap_after_pt` değişiyor.
- **Web sınırı**: Web’de PDF iframe içinde gösterildiği için tıklama, sürükleme ve overlay ekleme mümkün değil. Bu yüzden bu özellikler sol panelden kullanılıyor.
