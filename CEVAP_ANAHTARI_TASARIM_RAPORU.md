# Cevap Anahtarı Tasarım Raporu

## 1. Root Cause

Cevap anahtarının profesyonel görünmemesinin temel nedenleri:

- **İçerik-bazlı hücre genişliği**: `minCellW` / `min_cell_w` her hücrenin metin genişliğine göre hesaplanıyordu; en geniş içerik tüm sütunları etkiliyordu
- **Farklı layout mantığı**: Preview (Canvas) ve PDF export ayrı algoritmalarla çizim yapıyordu
- **Ölçü tutarsızlığı**: pt/px dönüşümleri, padding ve satır yükseklikleri iki tarafta farklıydı
- **Merkezleme hataları**: ReportLab’de `drawCentredString` baseline kullanıyordu; dikey merkez için doğru baseline hesaplanmıyordu

## 2. What Was Wrong in the Old Answer Key Layout

| Sorun | Eski Durum |
|-------|------------|
| Sütun genişlikleri | `min_cell_w = max(...)` ile içeriğe göre; sütunlar eşit değildi |
| Satır yükseklikleri | `pad_v` vb. ekstra padding ile tutarsız görünüm |
| Hücre içeriği | Canvas’ta `cellCenterX - totalW/2` ile yatay, `textBaseline: middle` ile dikey; ReportLab’de baseline hatası |
| Başlık | Farklı font/pozisyon, “Cevap Anahtarı” küçük harfle |
| Preview vs Export | Ayrı hesaplama, farklı sonuçlar |

## 3. New Grid System

Ortak layout sistemi:

- **`frontend/src/utils/answerKeyLayout.ts`**: Merkezi layout hesapları
- **`computeAnswerKeyLayout()`**: `totalWidthPx`, `columnCount`, `scale` ile tek kaynaktan hesaplama

Sabit ölçüler (pt):

- `HEADER_HEIGHT_PT`: 14  
- `ROW_HEIGHT_PT`: 14  
- `CELL_FONT_PT`: 9  
- `TITLE_FONT_PT`: 11  
- `BORDER_WIDTH_PT`: 0.8  
- `GRID_LINE_WIDTH_PT`: 0.3  

## 4. How Equal Row Heights and Equal Column Widths Were Ensured

1. **Eşit sütun genişliği**  
   - `tableWidth = totalWidth` (tam genişlik)  
   - `cellWidth = tableWidth / columnCount`  
   - İçerik genişliği hesaba katılmıyor.

2. **Eşit satır yüksekliği**  
   - Tüm satırlar için `ROW_HEIGHT_PT = 14`  
   - `rowCount = ceil(items.length / columnCount)`  
   - `tableHeight = headerHeight + rowCount * rowHeight + TABLE_BOTTOM_PADDING_PT`

## 5. How Content Centering Was Fixed

1. **Canvas (Preview)**  
   - `ctx.textAlign = "center"`  
   - `ctx.textBaseline = "middle"`  
   - `ctx.fillText(text, cellCenterX, cellCenterY)`  
   - `cellCenterX = tableX + (c + 0.5) * cellWidth`  
   - `cellCenterY = tableYTop + headerHeight + (r + 0.5) * rowHeight`  

2. **ReportLab (PDF Export)**  
   - `drawCentredString(cell_center_x, y_baseline, text)`  
   - `y_baseline = cell_center_y - (asc + desc) / 2`  
   - `getAscentDescent()` ile font metrikleri kullanılıyor  

## 6. How Preview/Export Consistency Was Ensured

1. **Ortak layout parametreleri**  
   - Frontend: `ANSWER_KEY_LAYOUT` sabitleri  
   - Backend: `_ANSWER_KEY_*` sabitleriyle aynı değerler  

2. **Aynı grid mantığı**  
   - İkisi de `tableWidth = availableWidth`, `cellWidth = tableWidth / columns`  
   - İkisi de sabit `rowHeight` kullanıyor  

3. **Tek metin formatı**  
   - `"${num}. ${ans}"`  
   - Başlık: `"CEVAP ANAHTARI"` (büyük harf)

## 7. Files Changed

| Dosya | Değişiklik |
|-------|------------|
| `frontend/src/utils/answerKeyLayout.ts` | **Yeni** – Layout config ve `computeAnswerKeyLayout()` |
| `frontend/src/components/pdf/CanvasPdfPreview.tsx` | `drawAnswerKeyTable` yeniden yazıldı, ortak layout kullanılıyor |
| `backend/app/services/desktop_export.py` | `_draw_answer_key_table` yeniden yazıldı, aynı layout sabitleri |

## 8. Validation Steps

1. **Eşit sütunlar**  
   - Tablo genişliği `columnCount` ile bölünüyor; tüm sütunlar aynı genişlikte.

2. **Eşit satırlar**  
   - Her satır `ROW_HEIGHT_PT` kadar; ek padding yok.

3. **İçerik hizalama**  
   - Canvas: `textAlign: center`, `textBaseline: middle`  
   - ReportLab: `drawCentredString` + doğru `y_baseline`  

4. **Başlık**  
   - Tek satır, tablo genişliğinde, ortalanmış, büyük harf.

5. **Preview vs PDF**  
   - Aynı layout sabitleri ve hesaplama mantığı kullanıldığı için görünüm uyumlu.

6. **Farklı soru sayıları**  
   - `rowCount = ceil(n/cols)` ile dinamik satır sayısı; oranlar korunuyor.
