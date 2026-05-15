# Güvenli Noktaya Geri Dönme

Bu proje Git ile takip ediliyor. **Güvenli nokta** oluşturuldu:
`Guvenli nokta: arka plan kaldirma ozelligi oncesi`

## Eski Haline Döndürmek İçin

Yaptığınız değişiklikler işe yaramazsa:

```powershell
# Tüm değişiklikleri geri al (güvenli noktaya dön)
git checkout .
git clean -fd
```

Veya sadece belirli dosyaları geri almak için:
```powershell
git checkout -- frontend/src/components/crop/SelectionOverlay.tsx
```

## Commit Geçmişini Görüntüleme

```powershell
git log --oneline
```

İlk commit (f66b813) = Güvenli nokta.
