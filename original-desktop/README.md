# Tesqube Builder

Bu proje PyQt5 + PyMuPDF (fitz) ile PDF'lerden soru görselleri kırpıp test oluşturmayı hedefler.

## Çalıştırma (en kolay)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python main.py
```

## Dizin

- `src/testmaker/ui/windows` : ana pencere + PDF görüntüleyici
- `src/testmaker/ui/widgets` : Qt widget'ları
- `src/testmaker/ui/dialogs` : diyaloglar
- `src/testmaker/models` : veri modelleri
- `src/testmaker/utils` : yardımcılar
- `src/testmaker/services` : ileride eklenecek servisler (PDF export, taslak, vb.)
- `resources` : ikon/font gibi statik dosyalar
