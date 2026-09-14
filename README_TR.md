# Global Bollinger — EODHD Python / Colab / Netlify

Bu paket araştırma ve günlük statik rapor üretimi içindir. Otomatik alım satım emri göndermez.
EODHD All-In-One aboneliği kullanılır; erişim ve tüm 47 enstrümanın kapsandığı iddia edilmez.

## Colab

1. Paketi Colab'a yükleyip açın. `Colab_Run.ipynb` dosyasını Colab'da açabilirsiniz.
2. Colab Secrets bölümüne `EODHD_API_TOKEN` ekleyin ve notebook erişimini açın.
3. Kurulum hücrelerini çalıştırın. `python bb_eodhd.py --init` config ve registry oluşturur.
4. `python bb_eodhd.py --catalog` EODHD'nin gerçek kataloglarını private/catalog.json'a yazar.
5. `universe.json` içindeki kesin eşleşmeyen kayıtları katalogdan doğrulayın.
6. `python bb_eodhd.py` analiz ve netlify_site.zip üretir. Bu ZIP yalnızca yayın dosyaları içerir.

## Kesin sembol eşlemesi

30 cash endeks için yalnızca INDX kataloğunda tekil, tam ad/alias eşleşmesi otomatik kabul edilir.
Sembol tahmini, fuzzy match, Yahoo veya ETF proxy yoktur. Provider adları zamanla değişebileceğinden
ilk çalıştırmada UNRESOLVED kayıtları normaldir. Katalog özel klasörde saklanır, sitede yayımlanmaz.
Her çözümlenmemiş satırın provider_symbol, provider_name ve instrument_type alanlarını gerçek
katalog kaydından doldurun. Örnek şema (örnek metinleri gerçek sembol olarak kullanmayın):

    "provider_symbol": "KATALOGDAKI_KOD.BORSA",
    "provider_name": "Katalogdaki tam ad",
    "instrument_type": "Cash Index / Spot Metal / Futures Reference",
    "volume_verified": false

17 emtia ve metal slotu kayıtlıdır; spot/vadeli tercihinin kullanıcı adına otomatik yapılmaması için
başlangıçta eşleştirilmez. COMM/FOREX EOD OHLC erişimi olmayan ürünü bu sürüm başka endpoint veya
sağlayıcıyla ikame etmez. Farklı payload kullanan Commodities API için ayrı adapter gerekir.
Dolayısıyla bu paket, doğrulanmış 47/47 coverage teslimatı değildir.

## Günlük otomasyon

Paketin kaynaklarını **özel bir GitHub reposuna**, `.github/workflows/daily.yml` dahil yükleyin.
Actions secrets:

- EODHD_API_TOKEN
- NETLIFY_AUTH_TOKEN
- NETLIFY_SITE_ID (hedef projenin ID'si)

Python GitHub Actions'ta çalıştığından EODHD token'ını yalnızca Netlify'a eklemek yeterli değildir.
Workflow günlük 01:00 UTC / 04:00 İstanbul hedefiyle çalışır. Zamanlama gecikebilir; Actions
etkin olmalı ve varsayılan branch üzerinde workflow bulunmalıdır. Önce Run workflow ile deneyin.
Her seriden yalnızca dün UTC ve öncesinin barları istenir; current-day provisional bar kullanılmaz.
Başarılı ilk çalıştırmadan ve yayın erişimi/lisans kontrolünden sonra repository variable
`PUBLISH_APPROVED=true` ayarlayın. Bu değişken açıkken workflow belirtilen mevcut Netlify sitesini
günceller. Bu teslimatta herhangi bir hesapta otomasyon veya deploy yapılmamıştır.

Cache private/cache altında tutulur; Actions cache kaybolursa tam geçmiş tekrar indirilir.
Son 10 takvim günü yeniden çekilerek yakın geçmiş düzeltmeleri birleştirilir. Daha eski provider
düzeltmeleri için periyodik tam yenileme gerekir. Hata durumda mevcut Netlify yayını değiştirilmez.
Kısmi coverage durumunda yalnızca güncel, doğrulanmış seriler hesaplanır; diğerleri Audit'tedir.
Tüm seriler başarısızsa yayın engellenir. Eski sitedeki build-age uyarısı 36 saatten sonra görünür.
7 günlük yaş eşiği gerçek borsa takvimi değildir: uzun resmi tatillerde manuel inceleme gerektirir.
Eksik gözlemler doldurulmaz. Kapsama başlangıcı, OHLC tutarlılığı, pozitif fiyat ve >%35 hareket kontrolü
uygulanır. Tam exchange-calendar gap audit henüz uygulanmamıştır.

## Backtest değişiklikleri

- Bollinger 55 SMA / 1 std varsayılanı korunur. Aynı yön tekrar kırılımları yeni sinyal sayılmaz.
- İlk geçerli rejim sinyali kabul edilir; orijinal Pine barssince başlangıç NA sorunu düzeltilmiştir.
- Sinyal kapanışta, giriş sonraki açılışta; pozisyon riski **önceki bar ATR** ile hesaplanır.
- Stop-gap açılışta, diğer stoplar aktif stop seviyesinde ve olumsuz slippage ile gerçekleşir.
- Aynı bar hedef/stop temasında stop önce varsayılır. Hedef gap iyileşmesi verilmez.
- Trailing stop kapanış bazlıdır ve yalnızca sonraki bardan itibaren geçerlidir.
- Brüt/net P&L ve giriş/çıkış komisyonu mutabakatı test edilir.
- İlk OOS gününün sermaye değişimi performansa dahildir.
- Sortino tüm gözlemlerde risk-free hedefinin altındaki sapmalarla hesaplanır.
- Trend filtresi varsayılan açık; RSI/ADX isteğe bağlı. Gerçek hacim yoksa volume_filter açmayın.
- optimize=false varsayılandır. Açılırsa 9 BB adayı yalnızca training bölümünde seçilir;
  minimum 10 training işlemi yoksa varsayılan korunur. Bu walk-forward veya ileri optimizasyon değildir.
- OOS bağımsız hesaplar kullanır; bunlar ortak sermayeli bir portföy değildir.
- EGARCH son volatilitesi tüm mevcut geçmişten hesaplanır, geçmiş alım/satım sinyalinde kullanılmaz.
- VWAP yalnızca kullanıcı gerçek hacim semantiğini onayladığında ve son 55 hacim pozitifse sunulur.

Cash endeks doğrudan alınıp satılamaz. Sonuçlar yerel fiyat birimleriyle referans-seri simülasyonudur;
USD performansı, futures kontrat P&L'si veya gerçekleştirilebilir yatırım getirisi diye sunulamaz.
Kontrat çarpanı, roll maliyeti, FX dönüşümü, short borrow, carry/faiz ve piyasa etkisi dahil değildir.
Pozisyon risk yüzdesi gap/slippage halinde kayıp garantisi değildir.

## Doğrulama

    pip install -r requirements.txt
    python -m unittest -v test_engine

Unit test fixture'ları yapaydır, yalnızca test içindir; hiçbirinin production veri akışına yolu yoktur.
EODHD hesabıyla uçtan uca veri testi ve Netlify deploy testi kullanıcı credentials'ı olmadan yapılmamıştır.

## Kaynaklar

- https://eodhd.com/financial-apis/exchanges-api-list-of-tickers-and-trading-hours
- https://eodhd.com/financial-apis/api-for-historical-data-and-volumes
- https://docs.netlify.com/api-and-cli-guides/api-guides/get-started-with-api/
