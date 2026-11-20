# Akademik Altyazı

İşitme engelli öğrenciler için **gerçek zamanlı Türkçe ders altyazısı ve terim açıklama sistemi**.
Öğretim üyesi tarayıcıdan konuşur; öğrenciler oda koduyla katılıp büyük, yüksek kontrastlı
altyazıyı ve derste geçen akademik terimlerin sade tanımlarını (görsel ve Türk İşaret Dili videosuyla) canlı izler.

> Üniversite sosyal sorumluluk projesi.

## Nasıl çalışır?

```
Tarayıcı (konuşmacı)                         Sunucu (Django + Channels / Daphne)
getUserMedia ─► AudioWorklet                 SpeakerConsumer
  48 kHz → 16 kHz mono Int16                   │  Silero VAD (ONNX, torch'suz) → konuşma bölümleri
  320 ms'lik parçalar ── WebSocket ──────────► │  faster-whisper (language="tr", initial_prompt = alan terimleri)
                                               │  zeyrek + rapidfuzz ile terim eşleme → veritabanı
Tarayıcı (öğrenci)  ◄── WebSocket (grup) ──────┘  partial (gri) / final (beyaz) + terim kartları
```

- **Kısmi metin (gri):** konuşma sürerken ~1,2 sn'de bir hızlı (beam=1) çözümleme; isteğe bağlı daha hafif bir modelle (`ASR_PARTIAL_MODEL_SIZE=base`).
- **Kesin metin (beyaz):** ≥600 ms sessizlikte ya da en geç 10 sn'de bölüm kapanır, beam=5 ile çözülür,
  terimler eşlenir, kaydedilir ve tüm öğrencilere gönderilir. Uzun konuşmada kesme noktası son 2 sn'deki en sessiz andan seçilir.
- **Geride kalmama:** CPU yetişemezse kuyrukta bekleyen bölümler tek Whisper çağrısında birleştirilir (≤25 sn);
  Whisper'ın çağrı maliyeti neredeyse sabit olduğundan gecikme birikmez.
- **initial_prompt:** oturumun alanındaki terimler Whisper'a ipucu olarak verilir. Örnek: istem olmadan
  "öz iğnelemeli", alan terimleriyle "özyinelemeli" yazıldı.
- **Terim eşleme:** çekimli biçimler ("algoritma**nın**", "ikili arama ağaç**larında**", "önbelleğ**e**"),
  zeyrek kökleri, takma adlar ("deadlock", "stack") ve tanıma hataları için bulanık eşleme ("algoritimanın").

## Gereksinimler

- Python **3.10 – 3.12** (3.12.7 ile denendi)
- Windows, Linux veya macOS. GPU gerekmez; CPU için `small` + `int8` önerilir.
- İlk çalıştırmada Whisper modeli indirilir (small ≈ 480 MB) — internet gerekir.
- Mikrofon için tarayıcı **güvenli bağlam** ister: `http://localhost` ya da HTTPS (aşağıya bakın).

## Kurulum

Windows (PowerShell):

```powershell
cd Altyazi_project
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

copy .env.example .env             # sonra DJANGO_SECRET_KEY'i değiştirin
python manage.py migrate
python manage.py loaddata bilgisayar_muhendisligi   # örnek sözlük (32 terim)
python manage.py createsuperuser                   # konuşmacı/yönetici hesabı
python manage.py asr_hazirla                       # modelleri önceden indir (önerilir)
```

Linux/macOS: `python3 -m venv venv && source venv/bin/activate`, `.env` için `cp .env.example .env`.

## Çalıştırma

```powershell
python manage.py runserver
```

`daphne` `INSTALLED_APPS`'te olduğundan `runserver` doğrudan ASGI (HTTP + WebSocket) sunucusu açar.
Alternatif: `daphne -b 0.0.0.0 -p 8000 altyazi.asgi:application`

| Sayfa | Adres | Kimler |
|---|---|---|
| Ana sayfa / derse katıl | http://localhost:8000/ | Öğrenci (girişsiz) |
| Öğrenci altyazı ekranı | http://localhost:8000/oda/`KOD`/ | Öğrenci (girişsiz) |
| Konuşmacı paneli | http://localhost:8000/konusmaci/ | Giriş yapmış kullanıcı |
| Terim sözlüğü yönetimi | http://localhost:8000/admin/ | Yönetici |
| Transkript (TXT) | http://localhost:8000/oda/`KOD`/transkript.txt | Herkes |

### Ders akışı

1. Konuşmacı giriş yapar → **Oturumlarım** → başlık ve alan seçip oturum oluşturur.
2. Ekrandaki **oda kodunu** (ör. `K7M2QX`) öğrencilerle paylaşır.
3. **● Başlat** → tarayıcı mikrofon izni ister → altyazı akmaya başlar. **■ Durdur** oturumu bitirir
   (tekrar Başlat ile devam edilebilir; zaman damgaları kaldığı yerden sürer).
4. Öğrenciler ana sayfada kodu girer. Sonradan katılan öğrenci o ana kadarki metni ve terimleri de görür.

### Mikrofonsuz demo / test: `demo_stream`

Bir WAV dosyasını **gerçek zamanlı hızda** konuşmacı hattına besler. Sunucu açıkken, ayrı bir terminalde:

```powershell
python manage.py demo_stream K7M2QX demo_audio\ders_ornegi.wav
```

`demo_audio/ders_ornegi.wav`, Windows'un Türkçe "Tolga" sentez sesiyle üretilmiş 31 sn'lik örnek bir ders anlatımıdır
(git'e eklenmez; kendi kaydınızı da kullanabilirsiniz).

Komut, oturum sahibinin adına sunucuya gerçek bir konuşmacı WebSocket'i açar; öğrenci sayfasını açık tutarsanız
altyazıyı ve kartları canlı görürsünüz. Seçenekler:

| Seçenek | Açıklama |
|---|---|
| `--hiz 2` | 2 kat hızlı besle (varsayılan 1 = gerçek zamanlı) |
| `--durdur` | Dosya bitince oturumu "bitti" durumuna al |
| `--url ws://192.168.1.20:8000` | Farklı sunucu adresi (varsayılan `ws://127.0.0.1:8000`) |
| `--yerel` | Sunucu olmadan bu süreçte çalıştır, sonucu terminale yaz (Redis kullanılıyorsa öğrencilere de yayınlar) |

16-bit PCM WAV doğrudan okunur (her örnekleme hızı/kanal sayısı 16 kHz mono'ya çevrilir); mp3/m4a gibi biçimler PyAV ile açılır.

## Ayarlar (`.env`)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ASR_MODEL_SIZE` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` … |
| `ASR_DEVICE` / `ASR_COMPUTE_TYPE` | `cpu` / `int8` | GPU için `cuda` / `float16` |
| `ASR_PARTIALS` | `true` | Kısmi (gri) altyazıyı aç/kapat. Zayıf CPU'da `false` |
| `ASR_PARTIAL_INTERVAL` | `1.2` | Kısmi çözümleme aralığı (sn). CPU yetişemezse otomatik uzar |
| `ASR_PARTIAL_MODEL_SIZE` | `base` (.env.example) | Kısmi metin modeli; boşsa ana model. CPU'da kesin metni geciktirmemek için önerilir |
| `ASR_PROMPT_PREVIOUS` | `false` | Önceki cümleyi de isteme ekle. Kapalı: Whisper istemdeki cümleye benzeyen yeni cümleyi atlayabiliyor |
| `ASR_MAX_SEGMENT_SECONDS` | `10` | Bir bölümün en uzun süresi |
| `ASR_MIN_SILENCE_MS` | `600` | Cümleyi bitirmek için gereken sessizlik |
| `ASR_VAD_THRESHOLD` | `0.5` | Silero VAD konuşma eşiği (gürültülü salonda 0.6) |
| `ASR_VAD_MODEL_PATH` | boş | Boşsa faster-whisper içindeki Silero modeli; arayüzü uymazsa resmi model `models/` altına indirilir |
| `ASR_MODEL_DIR` | boş | Whisper modelinin indirileceği klasör (boşsa Hugging Face önbelleği) |
| `TERM_FUZZY_THRESHOLD` | `88` | Bulanık eşleme eşiği (0–100) |
| `REDIS_URL` | boş | Doluysa Redis kanal katmanı (çok süreç/sunucu için) |

Tüm liste: [.env.example](.env.example)

**Performans notu (ölçülen):** Geliştirme dizüstünde (12 mantıksal çekirdek, GPU yok) `small/int8` bir Whisper
çağrısı bölüm uzunluğundan bağımsız olarak ~4–6 sn, `base` ~1 sn sürdü. Yani beyaz metin, cümle bittikten ~5 sn sonra
görünür; 31 sn'lik örnek ders 36 sn'de, gerçek zamana yetişerek ve 8/8 cümle doğru yazıya döküldü.
Gecikme fazlaysa: `ASR_PARTIALS=false` ya da `ASR_MODEL_SIZE=base` (daha hızlı, daha az doğru).
GPU varsa (`ASR_DEVICE=cuda`, `ASR_COMPUTE_TYPE=float16`) gecikme 1 sn'nin altına iner ve `medium`/`large-v3` kullanılabilir.

## Terim sözlüğü

Yönetim panelinde (**/admin/** → Terim Sözlüğü) alan ve terim eklenir:

- **Terim:** yalın hâliyle yazın ("ikili arama ağacı"). Çekimli biçimler otomatik tanınır.
- **Takma adlar:** JSON liste — `["binary search tree", "BST"]`
- **Sade tanım:** kısa, günlük dille.
- **Görsel:** isteğe bağlı (`media/terms/`).
- **TİD video bağlantısı:** YouTube bağlantısı (gizlilik dostu `youtube-nocookie` ile gömülür) veya doğrudan `.mp4/.webm` adresi.

> Örnek fixture'daki terimlerin görsel ve TİD video alanları **bilerek boş** bırakılmıştır; doğru ve onaylı TİD
> karşılıklarının uzman/işaret dili tercümanı desteğiyle eklenmesi gerekir.

Kendi sözlüğünüzü dışa aktarmak için: `python manage.py dumpdata glossary --indent 2 > sozluk.json`

## Erişilebilirlik

- "Görünüm" menüsü: yazı boyutu (A−/A+, klavyede `+`/`-`), 3 tema (siyah-beyaz, siyah-sarı, açık), satır aralığı,
  yazı tipi, kısmi metni ve terim kartlarını gizleme. Tercihler tarayıcıda saklanır.
- Altyazıdaki terimler vurgulanır; tıklanınca ilgili kart öne gelir.
- `aria-live` bölgeleri, klavye ile tam kullanım, görünür odak çerçevesi, `prefers-reduced-motion` desteği, mobil yerleşim.

## Ağda kullanım (başka cihazlar)

- **Öğrenciler** için HTTP yeterlidir: `.env` → `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.20` ve
  `daphne -b 0.0.0.0 -p 8000 altyazi.asgi:application`, öğrenciler `http://192.168.1.20:8000` adresine girer.
- **Konuşmacı** mikrofonu başka bir cihazdan kullanacaksa HTTPS şarttır (tarayıcı kuralı). Seçenekler:
  sunucuyu konuşmacının bilgisayarında çalıştırmak (localhost), ya da Caddy/nginx ile TLS sonlandırmak
  (`DJANGO_CSRF_TRUSTED_ORIGINS=https://...` ekleyin).

## Üretim / Redis

```powershell
pip install channels-redis   # requirements'ta var
# .env:  REDIS_URL=redis://127.0.0.1:6379/0   DJANGO_DEBUG=false
python manage.py collectstatic
daphne -b 0.0.0.0 -p 8000 altyazi.asgi:application
```

Bellek içi kanal katmanı yalnızca **tek süreçte** çalışır. Birden çok Daphne süreci, ayrı bir ASR sunucusu ya da
`demo_stream --yerel` ile canlı yayın için Redis gerekir. Not: her süreç Whisper modelini kendi belleğine yükler.

## Testler

```powershell
python manage.py test
```

Testler Whisper modeline ihtiyaç duymaz (sahte VAD/transkripsiyon kullanılır): terim eşleme (çekimler, tamlamalar,
yanlış pozitifler), VAD bölümleme (sessizlik, 10 sn sınırı, kesme noktası), ses hattı, görünümler, TXT indirme ve WebSocket tüketicileri.

## Proje yapısı

```
altyazi/        ayarlar, ASGI, URL'ler
asr/            vad.py (Silero ONNX) · segmenter.py · transcriber.py (faster-whisper) · pipeline.py
                management/commands/asr_hazirla.py
glossary/       Domain, Term · matcher.py (zeyrek + rapidfuzz) · admin · fixtures/bilgisayar_muhendisligi.json
lectures/       LectureSession, TranscriptSegment · consumers.py (WebSocket) · views · services
                management/commands/demo_stream.py
static/js/      pcm-worklet.js (AudioWorklet) · speaker.js · student.js · captions.js · a11y.js
templates/      Türkçe arayüz şablonları
```

## Bilinen sınırlamalar

- Otomatik konuşma tanıma hata yapabilir; özellikle gürültülü ortamda ve çok hızlı konuşmada. Yaka mikrofonu önerilir.
- Konuşmacı ayrımı (diarization) yoktur; tek konuşmacı varsayılır.
- Whisper zaman zaman sessizlikte "halüsinasyon" üretebilir; bilinen kalıplar (ör. "Altyazı M.K.") filtrelenir.
- `faster-whisper 1.2.x` PyAV 16+ ile uyumsuzdur; bu yüzden `requirements.txt` `av<16` sabitler
  (Windows'ta bu sürüm kaynaktan derlenebilir ve kurulum birkaç dakika sürebilir). PCM WAV dosyaları PyAV'ye ihtiyaç duymaz.
- Birleştirilmiş bölümler tek satır olarak görünür (geride kalındığında); zaman damgası ilk bölümün başlangıcıdır.


