# A4 Yatay 3 Sütun Layout Düzeltme Raporu

## 1. Root Cause

**Ana neden:** PDF kaydetme (handleSavePdf) sırasında `getPaperSizePayload()` orientation parametresi olmadan çağrılıyordu. Bu yüzden kullanıcı "Yatay" seçse bile kaydedilen PDF her zaman dikey (portrait) boyutlarla üretiliyordu.

**İkincil nedenler:**
- İlk sayfa contentTop hesaplaması `header_reserved_mm` (37pt) kullanıyordu; oysa gerçek 3 kutulu banner sadece 22pt + 2pt = 24pt. Bu tutarsızlık layout davranışını etkileyebiliyordu.
- paperSizePayload preset boyutları için her zaman 210x297 kullanıyordu; A3 gibi diğer presetlerde yanlış boyut gönderilirdi.
- CanvasPdfPreview sabit 15mm margin kullanıyordu; kullanıcı özel margin seçse backend layout ile uyumsuzluk oluşuyordu.

## 2. A4 Landscape 3-Column Geometry’de Ne Yanlıştı?

- **Orientation kaybı:** handleSavePdf’te `orientation` geçilmediği için backend portrait varsayıyordu. Sonuç: 595×841pt (dikey) instead of 841×595pt (yatay).
- **Usable width:** Portrait’ta `usable_width ≈ 524pt`, landscape’ta `≈770pt`. Yanlış orientation ile sütunlar dar kalıp üçüncü sütun fiilen kullanılmıyordu.
- **Content top:** İlk sayfa için 24pt (banner + gap) yerine 37pt kullanılması available_height’ı azaltıyordu; bu da daha erken sütun/sayfa geçişine yol açabiliyordu.

## 3. Files Changed

| Dosya | Değişiklik |
|-------|------------|
| `frontend/src/components/modals/PdfPreviewModal.tsx` | handleSavePdf’te `getPaperSizePayload(..., orientation)`; CanvasPdfPreview’e margin ve columnGapMm prop’ları |
| `frontend/src/utils/paperSizePayload.ts` | PAPER_PRESETS_MM import; preset boyutları doğru kullanılıyor |
| `frontend/src/components/pdf/CanvasPdfPreview.tsx` | marginTopMm, marginBottomMm, marginLeftMm, marginRightMm, columnGapMm prop’ları; sabit margin yerine prop’lardan okuma |
| `backend/app/services/desktop_export.py` | `_compute_layout_geometry()` merkezi fonksiyon; `_FIRST_PAGE_BANNER_H_PT`, `_OTHER_PAGES_HEADER_H_PT` sabitleri; col_top_for_page bu geometriye bağlı |

## 4. New Layout Calculation

`_compute_layout_geometry(opts)` artık tek kaynak:

```
usable_width = page_w - ml - mr
column_gap = mm_to_pt(column_gap_mm)
column_width = (usable_width - (cols-1)*column_gap) / cols
column_x[i] = ml + i * (column_width + column_gap)

content_top_first  = page_h - mt - 22 - 2  [banner + gap] veya [banner + gap + desc_box + 6] (açıklama varsa)
content_top_other  = page_h - mt - 24 - 10 [diğer sayfa header + gap]
content_bottom     = footer_top
```

Landscape için `_page_size_pt` width/height swap ediyor (return h_pt, w_pt).

## 5. Header/Banner ile Sütunların Ayrılması

- Sabitler: `_FIRST_PAGE_BANNER_H_PT=22`, `_FIRST_PAGE_BANNER_GAP_PT=2`, `_OTHER_PAGES_HEADER_H_PT=24`, `_OTHER_PAGES_HEADER_GAP_PT=10`.
- İlk sayfa (açıklama yok): `content_top = page_h - mt - 24`.
- İlk sayfa (açıklama var): `content_top = page_h - mt - 22 - 2 - box_h - 6`.
- Diğer sayfalar: `content_top = page_h - mt - 34`.
- Sütun çizgileri bu content alanı içinde; banner sütun layout’unu bozmuyor.

## 6. Preview ve Export Uyumluluğu

- İkisi de aynı `compute_layout_from_payload` / `export_from_payload` → `_run_layout` → `_compute_layout_entries_flexible` zincirini kullanıyor.
- `_compute_layout_entries_flexible` layout için `_compute_layout_geometry()` kullanıyor.
- Preview (`/exports/layout`) ve export (`/exports/from-questions`) aynı opts ile çalışıyor; orientation ve columns her ikisinde de doğru geçiriliyor.
- PdfPreviewModal hem layout hem de kaydetme için `orientation` gönderiyor.

## 7. Validation Steps

1. **A4 portrait + 2 column:** Mevcut davranış bozulmamalı.
2. **A4 landscape + 3 column:**  
   - `page_w_pt ≈ 841`, `page_h_pt ≈ 595`  
   - 3 sütun eşit genişlikte  
   - Sorular 1→2→3 sütunlara akmalı  
   - Üçüncü sütun kullanılmalı
3. **Banner:** Header sütunların üstünde, içeriğe taşmamalı.
4. **Preview vs PDF:** Önizleme ile kaydedilen PDF aynı düzeni göstermeli.
5. **Orientation değişimi:** Dikey↔yatay geçişte cache veya eski layout kalıntısı kalmamalı.

DEBUG için: `DEBUG_PDF_LAYOUT=1` (ortam değişkeni) ile layout log’ları açılır.

## 8. Remaining Risks

- **Gap line çizimi:** 3 sütunda “sol/sağ” sınıflandırması `midX = pageWpt/2` ile yapılıyor; orta sütun davranışı farklı olabilir (sadece görsel debug).
- **Column gap UI:** Şu an column gap frontend’de 8mm sabit; kullanıcı ayarı yok. Backend `column_gap_mm` kullanıyor.
- **WrittenPaperForm:** Kağıt boyutu/orientation ayarları WrittenPaperForm’dan da kullanılıyorsa, oradaki `getPaperSizePayload` çağrılarının orientation geçirdiğinden emin olunmalı.
