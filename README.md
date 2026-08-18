# Yargı Kararı Bulucu

Türkiye'deki kamuya açık resmî karar kaynaklarında arama yapmayı kolaylaştıran Streamlit uygulaması.

## Kaynaklar
- Yargıtay Karar Arama
- Danıştay Karar Arama
- UYAP Emsal Karar Arama
- Anayasa Mahkemesi Kararlar Bilgi Bankası

## Kurulum

Komut İstemi / PowerShell:

```bash
pip install -r requirements.txt
streamlit run yargi_karari_bulucu.py
```

## Kullanım örnekleri

- `işçinin WhatsApp yazışması nedeniyle fesih`
- Tam ifade: `feshin son çare olması ilkesi`
- Mevzuat: `4857 18`
- Daire: `9. Hukuk Dairesi`
- Esas No: `2023/1234`
- Karar No: `2024/5678`

## Not
Uygulama arama sonuçlarını yalnızca resmî yargı alan adlarıyla sınırlar.
Resmî sitelerin erişim biçimleri değişebileceği için "karar metnini getir" özelliği
her sonuçta çalışmayabilir. Hukuki doğrulama için sonuçtaki resmî karar bağlantısı esas alınmalıdır.
