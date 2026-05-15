# PDF Yerleşim Motoru İyileştirmesi - Rapor

## BUG FIX (21.03.2025): Her sütuna sadece 1 soru hatası

**Root cause:** Algoritma soru sığdığı anda hemen `flush_column` + `next_column` yapıyordu. Bu yüzden her sütuna tek soru yerleşiyordu.

**Fix:** Sığdığında flush yapma; sadece `i += 1` ve döngüde devam et. Yalnızca overflow olduğunda (yeni soru eklenince sığmıyorsa) flush + next_column yap.

---

## 1. Current Placement Problem

**Mevcut sorun:** Sistem sorular arası boşluğu sabit uygulayıp, sütuna sığmayan soruyu doğrudan sonraki sütuna taşıyordu:
- Her soru altında sabit boşluk (örn. 30 mm)
- `y - (soru_yüksekliği + boşluk) < effective_bottom` ise → hemen `next column`
- Boşluk azaltılarak sığma denenmiyordu
- Bu da gereksiz beyaz alan ve erken kolon taşmasına yol açıyordu

## 2. Root Cause

**Kök neden:**
- `backend/app/services/desktop_export.py` içinde layout mantığı sabit spacing + overflow → next column şeklindeydi
- `gap_after_q` her zaman preferred/custom değeri kullanıyordu
- Compaction (sıkıştırma) denenmiyordu
- `compute_layout_from_payload` ve `export_from_payload` aynı sabit mantığı kullanıyordu

## 3. New Layout Strategy

**Yeni strateji:** "min / preferred / applied" spacing modeli:

- **preferredSpacingMm** (tercih edilen): Kullanıcının seçtiği boşluk
- **minSpacingMm** (minimum): Sıkıştırma alt sınırı, okunabilirlik için korunur
- **appliedSpacingMm**: Yerleşim sırasında hesaplanan gerçek uygulanan boşluk

**Algoritma:**
1. Önce preferred spacing ile yerleştirmeyi dene
2. Sığmazsa: sütundaki tüm soruların boşluklarını `min..preferred` aralığında eşit şekilde azalt
3. Hâlâ sığmazsa: önceki soruları mevcut sütuna yerleştir, yeni soruyu sonraki sütuna taşı
4. Minimum boşluk her zaman korunur (sıfırlanmaz)

## 4. How Spacing Optimization Works

1. **Column buffer:** Sorular sırayla bir sütun buffer’ına eklenir
2. **Fit check:** `gap_budget = available_height - total_block_height` (n soru için n boşluk)
3. **Preferred fit:** `gap_budget >= n * preferred` ise → preferred kullanılır
4. **Compaction:** `gap_budget >= n * min_gap` ise → `applied = gap_budget / n` (uniform dağıtım, `[min, preferred]` sınırları içinde)
5. ** overflow:** `gap_budget < n * min_gap` ise → son soru buffer’dan çıkarılır, öncekiler yerleştirilir, yeni sütuna geçilir

**Tek soru sığmıyorsa:** Minimum boşlukla yerleştirilir (tek soru için tek boşluk).

## 5. Files Changed

| Dosya | Değişiklik |
|-------|------------|
| `backend/app/services/desktop_export.py` | ExportOptions: `question_gap_min_mm`, `auto_compact_spacing` eklendi. `_compute_layout_entries_flexible`, `_prepare_question_data_for_layout`, `_run_layout` eklendi. `export_from_payload` ve `compute_layout_from_payload` yeni layout motorunu kullanacak şekilde güncellendi. |
| `backend/app/models/schemas.py` | ExportWithQuestionsRequest: `question_gap_min_mm`, `auto_compact_spacing` alanları eklendi |
| `backend/app/services/export_service.py` | Layout/export çağrılarına `question_gap_min_mm`, `auto_compact_spacing` parametreleri eklendi |
| `backend/app/api/routes/exports.py` | Layout ve export endpoint’lerine yeni parametreler aktarıldı |
| `frontend/src/store/editorStore.ts` | `questionGapMinMm`, `autoCompactSpacing` state ve setter’ları eklendi. `applyDraftPayload` bu alanları destekliyor |
| `frontend/src/api/client.ts` | Layout ve export payload tiplerine `question_gap_min_mm`, `auto_compact_spacing` eklendi |
| `frontend/src/components/modals/PdfPreviewModal.tsx` | fetchLayout ve handleSavePdf için yeni parametreler kullanılıyor |
| `frontend/src/components/modals/QuestionGapModal.tsx` | Minimum boşluk seçimi ve "Otomatik sıkıştırma" checkbox’ı eklendi |
| `frontend/src/components/forms/OptionsPanel.tsx` | QuestionGapModal’a `currentMinGapMm`, `currentAutoCompact` ve yeni `onConfirm` imzası geçiriliyor |
| `frontend/src/components/modals/SaveDraftModal.tsx` | Taslak kaydında `questionGapMinMm`, `autoCompactSpacing` saklanıyor |

## 6. Preview/Export Consistency

- `compute_layout_from_payload` ve `export_from_payload` aynı layout motorunu (`_prepare_question_data_for_layout` → `_run_layout` → `_compute_layout_entries_flexible`) kullanıyor
- Export, layout çıktısındaki `x_pt`, `y_top_pt`, `block_h`, `applied_gap_pt` değerlerini doğrudan kullanıyor
- Önizleme ve PDF çıktısı birebir aynı yerleşimi verir

## 7. Validation Steps

1. **İki sütun:** Tercih edilen boşlukla sığmayan sorular, sıkıştırma ile aynı sütunda kalmalı
2. **Minimum boşluk:** Hiçbir boşluk `minSpacingMm` altına düşmemeli
3. **Gereksiz taşma:** Soru yalnızca gerçekten sığmıyorsa sonraki sütuna geçmeli
4. **Preview vs export:** PDF önizleme ve export aynı sayfa / sütun düzenini göstermeli
5. **Deterministik:** Aynı girdi her zaman aynı layout’u vermeli
6. **Manuel mod:** `auto_compact_spacing: false` ile eski sabit spacing davranışı korunmalı

## 8. Remaining Limitations

- **Column balancing:** Şu an sütunlar sırayla dolduruluyor; sütun yüksekliklerini dengeleyen global optimizasyon yok
- **Çok uzun sorular:** Tek bir soru sütun yüksekliğinden uzunsa minimum boşlukla yerleştirilir (taşma görmezden gelinir)
- **export_desktop_style:** Hâlâ eski sabit layout mantığını kullanıyor; sadece `export_from_payload` (web export) yeni motoru kullanıyor

## Kullanım

- **Tercih edilen boşluk:** "Sorular arasına boşluk ekle" → Seçenekler → Boşluk miktarı
- **Minimum boşluk:** Aynı modaldaki "Minimum boşluk (sıkıştırma sınırı)" dropdown’ı (6–20 mm)
- **Otomatik sıkıştırma:** "Otomatik sıkıştırma (sığdırmak için boşlukları azalt)" checkbox’ı
