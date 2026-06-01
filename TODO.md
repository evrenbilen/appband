# AppBand — Backlog / TODO

Bu dosya AppBand'in yapılacaklar listesidir: epic'ler ve alt görevler, önceliklerine göre
sıralanmış. İçerik, kod tabanı üzerinde yürütülen çok-ajanlı bir inceleme + adversaryal
tamlık kritiği sonucunda üretildi; her madde gerçek kod davranışına dayanıyor.

## Nasıl okunur

- **Öncelik katmanları:** `P0` (şimdi / temel) → `P1` (sonraki / doğruluk) → `P2` (içgörü, performans) → `P3` (büyük bahisler, dağıtım).
- **Efor:** `S` (saatler) · `M` (gün(ler)) · `L` (hafta(lar) / yeniden yazım).
- **Etki:** `high` / `med` / `low`.
- `- [ ]` açık · `- [x]` tamamlandı.
- Parantez içindeki dosyalar dokunulacak ana yerlerdir.

> **Sıralama ilkesi (kritikten):** Ürünün asıl işi — "şu an bağlantımı ne yiyor, uygulama
> bazında?" — bugün hiçbir yerde *canlı ve tam* sunulmuyor; oysa veri (`process_samples`,
> `interface_samples`) zaten tam ve 5–10 sn'de toplanıyor. Bu yüzden **canlı per-app döngüsü**
> ve **dakika çözünürlüğü**, güvenlik üçlüsüyle birlikte P0'da. L-eforlu per-connection yeniden
> yazımı ve rollup tabloları, ihtiyaç kanıtlanana kadar P3'te bekletildi.

---

## P0 — Temel + en yüksek kaldıraç (önce bunlar)

### [x] EPIC P0-A: Yerel yüzeyin güvenlik sıkılaştırması  ·  **TAMAMLANDI** (83 test geçiyor)
Ürünün tüm vaadi yerel gizlilik; ama kimlik-doğrulamasız API tüm ağ geçmişini döndürüyor ve
dashboard public CDN'e gidiyor. Yeni hiçbir hassas endpoint bu kapı inmeden eklenmemeli.
- [x] Host/Origin header doğrulaması → DNS-rebinding ve cross-origin okumayı 403 ile engelle (S, high) (`appband/server.py`, `tests/test_server.py`)
- [x] Chart.js'i `appband/web/vendor/`'a vendor'la + `/static/` üzerinden sun (chart.js@4.4.0, sha256 `0e2326…abff0`) (S, high) (`appband/web/index.html`)
- [x] Sıkı CSP + `X-Content-Type-Options: nosniff` + `Referrer-Policy: no-referrer` header'ları (S, high) (`appband/server.py`)
- [x] `load_config` içinde `bind_host`'u loopback'e kıs (`ipaddress.is_loopback`); non-loopback → uyarı + `127.0.0.1`'e geri dön (S, high) (`appband/config.py`, `tests/test_config.py`)
- [x] DB dosya izinlerini `0600` yap + at-rest şifrelemenin olmadığını dürüstçe belgele (S, med) (`appband/db.py`, README Privacy)

### [x] EPIC P0-B: Canlı "şu an" per-app döngüsü + dakika çözünürlüğü  ·  **TAMAMLANDI** (86 test geçiyor)
Veri zaten tam (`scope=all` → `approximate:false`); backend sadece canlı/ince sunmuyor.
- [x] `/api/current`'a son ~60 sn'de **tam** ilk-N (5) uygulamayı ekle (M, high) (`appband/server.py`)
- [x] `query_timeseries`'e `minute` (60 sn) granülaritesi ekle; dashboard kısa aralıkta (≤1 sa) kullanıyor (M, high) (`appband/db.py`, `appband/server.py`, `appband/web/app.js`)
- [x] Dashboard LIVE paneline canlı top-apps listesi + kapsama chip'i; "Son saat" aralığında dakika-çözünürlüklü grafik (M, high) (`appband/web/app.js`, `index.html`, `style.css`, `locales/*.json`)
- [x] Popover'da tam uygulama kırılımı — `/api/by-process?scope=all` yerine `/api/current.top_apps` kullanıldı (zaten 5 sn'de pollanıyor, canlı için daha doğru, hâlâ tam/exact) (M, high) (`mac-app/Sources/AppBand/NetworkMonitor.swift`, `LivePopover.swift`)
- [x] **Kapsama göstergesi:** `/api/current.coverage` = toplam (interface) vs atfedilen (process) + yüzde; dashboard chip'inde "Ölçülenin %X'i atfedildi" (M, high) (`appband/server.py`, `appband/web/app.js`)

### [x] EPIC P0-C: CI + sürüm tek-kaynak  ·  **TAMAMLANDI** (90 test + build geçiyor)
- [x] GitHub Actions CI: macOS'ta `unittest` + `swift build` + Playwright e2e (S, high) (`.github/workflows/ci.yml`)
- [x] Tek-kaynak `appband.__version__` → build.sh Info.plist'e enjekte ediyor + README testle doğrulanıyor + `/api/version` endpoint'i (S, high) (`appband/__init__.py`, `mac-app/build.sh`, `appband/server.py`, `tests/test_version.py`)
- [x] About kutusundaki sabit `0.1.3` → `CFBundleShortVersionString` okuyor (S, low — doğrulanmış bug) (`mac-app/Sources/AppBand/AppBandApp.swift`)
- [x] Güncellemede backend yeniden kopyalanıyor: `installIfNeeded` `.version` marker'ı ile sürüm karşılaştırıyor (M, high) (`mac-app/Sources/AppBand/BackendInstaller.swift`)

---

## P1 — Güvenilirlik + çekirdek UX doğruluğu

### [~] EPIC P1-A: İki daemon'un kendini-iyileştirmesi  ·  **8/10 yapıldı** (109 test geçiyor)
- [x] DB bozulması tespiti (`PRAGMA quick_check`) + karantina-ve-yeniden-oluştur → launchd crash döngüsünü kır (M, high) (`appband/db.py`) — `12d2e3f` (+ `ef0025e` locked-DB) (+ tie-break `d8fabdc`)
- [x] Heartbeat tablosu + `/api/health` (IPC'siz tek liveness kanalı; eksik-poller tespiti) (M, high) — `246faf4` (+ `f70f621`)
- [x] Günlük `VACUUM` + saatlik `wal_checkpoint(TRUNCATE)` (busy uyarısı dahil) (M, med) — `40ca3c4` (+ `36e76b5`)
- [x] `RotatingFileHandler`'a geç (her iki daemon, 5MB×3) (S, med) — `95979d0`
- [ ] **DEFERLENDİ** Thread supervisor: ölen poller'ı yeniden başlat (M, med) — güvenli birim-testi için collector main()'in refactor'u gerekiyor; per-tick try/except zaten geçici hataları yutuyor, thread'ler yalnızca nadir scaffolding hatasında ölür. P2'ye taşındı. (`appband/collector.py`)
- [x] Açıkta kalan oturumları başlangıçta kapat (30-gün retention sızıntısı) (M, med) — `aa83342`
- [x] `_run`: araç-eksik (FileNotFoundError) ↔ timeout ayrımı, tek-sefer logla (collector + session_watcher) (M, med) — `43a8e96` (+ `36e76b5`)
- [ ] **DEFERLENDİ** Collector öz-metrikleri (düşen tick, izlenen anahtar, DNS kuyruk derinliği) (M, med) — değerli ama P1-B/P1-C kullanıcı-yüzü kurtarmadan düşük öncelikli. P2'ye taşındı.
- [x] **(bonus)** Server: istemci kopması (BrokenPipe/ConnectionReset) sessiz ele alınıyor — `115ee0f` (e2e doğruladı: 0 traceback)

### [x] EPIC P1-B: Mac uygulaması — hata görünürlüğü, kurtarma, kalıcılık  ·  **TAMAMLANDI** (build geçiyor; Swift, unittest yok)
- [x] Yutulan `BackendInstaller` hatasını NSAlert ile göster (S, high) — `9e19bcf`
- [x] "connecting" vs "offline" ayrımı (3-durum) + tek-tık **Restart Services** (`launchctl kickstart -k`) (M, high) — `9e19bcf`
- [x] SMAppService ile "Girişte Başlat" toggle'ı (M, med) — `3c47cd1`
- [x] Uygulama-içi Uninstall akışı (NSAlert + suppression-checkbox → `uninstall.sh --purge`) (M, med) — `3c47cd1`
- [x] 1Hz başlık timer'ı → Combine sink (`$menuBarTitle`) (S, low — idle güç) — `3c47cd1`

### [ ] EPIC P1-C: Dashboard doğruluğu + dürüstlüğü
- [ ] Ölü SSID filtresini bağla (`state.ssid` hiçbir fetch'e eklenmiyor) **+ `process_samples`/`connections` için `session_id` index'i** (M, high) (`appband/web/app.js`, `appband/server.py`, `appband/db.py`, `tests/test_server.py`)
- [ ] Yaklaşıklık rozetini görünür yap + "Nasıl okunur?" FAQ popover'ı (CSS/i18n zaten var, kullanılmıyor) (S, high) (`appband/web/index.html`, `app.js`, `style.css`)
- [ ] Bilgi-mimarisi: tam yüzeyleri (toplam, uygulama, ağ) öne çıkar; tek yaklaşık panel olan by-domain'i ikincil + etiketli yap (M, high) (`appband/web/index.html`, `app.js`)
- [ ] Kullanılmayan `/api/sessions`'tan "Ziyaret edilen ağlar" görünümü (M, med) (`appband/web/index.html`, `app.js`, `locales/*.json`)
- [ ] By App / By Domain listelerine client-side arama + "tümünü göster" (15'lik tavan) (M, med) (`appband/web/app.js`, `index.html`, `style.css`)
- [ ] 4 sabit ön-ayar dışında özel tarih-aralığı seçici (her endpoint zaten `from/to` alıyor) (M, med) (`appband/web/index.html`, `app.js`)
- [ ] By App / By Domain / By Network için CSV dışa-aktarma (client-side, upload yok) (S, med) (`appband/web/app.js`)

---

## P2 — İçgörü + performans + veri doğruluğu

### [ ] EPIC P2-A: İçgörü + sayaçlı-ağ uyarıları (bildirim katmanı = menü çubuğu app'i)
- [ ] iphone-hotspot/usb-tether geçişinde sayaçlı-ağ uyarısı (S, high — en düşük efor, hotspot senaryosu) (`NetworkMonitor.swift`)
- [ ] Sürekli yüksek-throughput canlı uyarısı ("hotspot'unu bir şey hızla tüketiyor") (M, med) (`NetworkMonitor.swift`)
- [ ] Veri-kullanım bütçesi: `/api/budget` değerlendirme endpoint'i + macOS UserNotifications (L, high — `interface_samples` tam) (`appband/server.py`, mac-app)
- [ ] "Ben uyurken internete ne konuştu?" gece/uzakta raporu (M, med) (`appband/server.py`, mac-app)
- [ ] Günlük/haftalık özet digest'i (`/api/summary` + bildirim + dashboard kartı) (M, med)
- [ ] Öğrenilmiş (process, host) allowlist'ine karşı beklenmedik-hedef uyarısı (L, med)
- [ ] Process-başına anomali tespiti: kendi yuvarlanan baseline'ına göre "aniden konuşkan" (L, med)

### [ ] EPIC P2-B: Retention ölçeğinde sorgu performansı
- [ ] `connections`'ı yazma-anında dedup et: `UNIQUE(session, process, ip, port, bucket)` + `INSERT OR IGNORE` (M, high — ~9x fazlalık) (`appband/collector.py`, `appband/db.py`)
- [ ] Composite index: `connections(process_name, ts)` + `process_samples(process_name, ts)` (S, high) (`appband/db.py`)
- [ ] `connections(session_id)` + `dns_cache(resolved_at)` index'leri (purge/DNS taramalarını kapsa) (S, med) (`appband/db.py`)
- [ ] SQLite PRAGMA'lar: `mmap_size`, `cache_size`, `temp_store=MEMORY`, `synchronous=NORMAL` (S, med) (`appband/db.py`, `appband/collector.py`, `appband/server.py`)
- [ ] Pahalı yaklaşık endpoint'ler için kısa-TTL in-process response cache (S, med) (`appband/server.py`)
- [ ] API endpoint'lerine pagination/limit koruması + zaman-penceresi tavanı (S, med) (`appband/server.py`)

### [ ] EPIC P2-C: Veri-modeli doğruluğu (yakalanan-ama-kullanılmayan alanlar)
- [ ] VPN/tunnel oturumlarını tespit + etiketle (`utun/ipsec/ppp` → `ethernet` yanlış) (S, med) (`appband/parsers/network_info.py`, `session_watcher.py`)
- [ ] IPv6 LAN/dışlama sınıflandırmasını düzelt: zone-id (`%en0`) sıyır, bracketless IPv6 ayrıştır (S, med) (`appband/parsers/lsof.py`, `tests/fixtures/lsof_ipv6.txt`)
- [ ] Uyku/uyanma ve offline boşluklarını kaydet (`gaps` tablosu) → "izlemiyorduk" vs "gerçekten 0" (M, med) (`appband/collector.py`, `appband/db.py`, `appband/delta.py`)
- [ ] PID → app bundle id + görünen ad (`plistlib`, stdlib) ile kararlı per-app gruplama (M, med) (`appband/parsers/proc_info.py`, `collector.py`, `db.py`)
- [ ] Port/protokol kırılımı: saklanan ama okunmayan alanlardan `/api/by-port` (S, low) (`appband/server.py`)

### [ ] EPIC P2-D: Test derinliği
- [ ] Yaklaşık by-domain/by-process dağıtım matematiğini bilinen byte değerleriyle test et (M, high) (`tests/test_server_approximation.py`)
- [ ] Parser testlerini `tests/fixtures/`'taki gerçek yakalamalardan sür (30KB lsof hiç parse edilmiyor) (S, med) (`tests/test_parsers_*.py`)
- [ ] `_run` subprocess-failure yolu + `collect_snapshot` happy-path kapsaması (S, med) (`tests/test_collector_smoke.py`, `test_session_watcher.py`)
- [ ] CI'a `shellcheck` + plist-render + `plutil -lint` (S, med) (`.github/workflows/ci.yml`)
- [ ] Locale anahtar-paritesi unittest'i (eksik çeviriyi yakala) (S, low) (`tests/`)
- [ ] Server testlerindeki ResourceWarning'leri sustur + stray `.pytest_cache`'i temizle (S, low) (`tests/test_server.py`)
- [ ] Atıl `netstat` parser'ını ya bağla ya sil (test kapsamasını şişiriyor) (S, low) (`appband/parsers/netstat.py`)

---

## P3 — Büyük bahisler + dağıtım (bilinçli sırala)

### [ ] EPIC P3-A: Gerçek per-connection byte muhasebesi  ·  **ihtiyaç kanıtlanmadan başlama**
> ⚠️ Yaklaşıklığı tamamen kaldırır ama: (1) proje zaten iPhone-hotspot kernel sayaç hatasından
> kaçmak için `nettop -m route` kullanıyor; ham per-socket sayaç tam o riski geri getirir.
> (2) Canlı-tam-app görünümü (P0-B) gerçek senaryonun çoğunu zaten karşılıyor.
- [ ] Önce P0-B'yi çıkar ve kullanıcının host-bazlı byte atıfına ihtiyacını kanıtla
- [ ] `nettop` (`-P` olmadan) per-socket çıktısını parse eden bağlantı-detayı parser'ı + fixture (M, high) (`appband/parsers/nettop.py`)
- [ ] Per-connection `DeltaTracker` + yeni `connection_samples` tablosu (L, high) (`appband/collector.py`, `appband/db.py`)
- [ ] by-domain/by-process'i gerçek byte'lara taşı, `approximate` bayrağını kaldır (L, high) (`appband/server.py`)
- [ ] (Opsiyonel) nettop TCP sağlık sütunları (`rtt_avg`, `re-tx`) → bağlantı-kalitesi sinyali (M, low)

### [ ] EPIC P3-B: 5-dk rollup tabloları  ·  dedup+index+cache yetersiz ölçülürse
- [ ] Önce P2-B'yi ölç; ancak yetersizse rollup'a geç (L, high) (`appband/collector.py`, `appband/db.py`, `appband/server.py`)

### [ ] EPIC P3-C: Release engineering + dağıtım
- [ ] Tag ile tetiklenen release workflow: build + sign + DMG + checksum + `gh release create` (M, high — CI'a bağlı) (`.github/workflows/release.yml`)
- [ ] README'nin vaat ettiği SHA-256 manifestini gerçekten yayınla (S, high) (release workflow)
- [ ] Commit'lenmiş DMG'leri + 26MB scratch image'i sil ve gitignore'la (S, med) (`.gitignore`, `mac-app/`)
- [ ] Notarization plumbing'i env-credential'ların arkasında ekle (ad-hoc fallback bozulmadan) (M, — ücretli Apple hesabı gerekir) (`mac-app/build-dmg.sh`)
- [ ] Homebrew cask (ayrı tap repo, yayınlanmış SHA + Release URL'lerine bağlı) (M, high)
- [ ] GitHub Releases API'sine karşı "güncelleme var" kontrolü (uygulamanın tek dış çağrısı → opt-in + README'de belgele) (M, med) (mac-app)

### [ ] EPIC P3-D: Dokümanlar + onboarding
- [ ] `CHANGELOG.md` (v0.1.0–v0.1.4 tag'lerinden) (S, med)
- [ ] Mimari dokümanı + diyagram → bkz. `docs/ARCHITECTURE.md` (S, med) ✅ *başlatıldı*
- [ ] Dört shell script'e `--help`/usage çıktısı (S, med) (`scripts/*.sh`)
- [ ] Dashboard'a ilk-çalıştırma onboarding overlay'i (P1-C bilgi-mimarisi indikten *sonra*) (M, med) (`appband/web/`)
- [ ] Mac uygulamasının menü/About'unu yerelleştir veya "İngilizce-only" olduğunu belgele (S, low)

---

## Kısıt notları (ihlal değil — incelemede dikkat)

- **Chart.js vendor'lama** ve **mac-app güncelleme kontrolü** "no deps / localhost-only" kurallarını ihlal etmez (kural Python *server* bind'i için; Swift app ayrı). Yine de güncelleme kontrolünü opt-in yap ve README Privacy'de belgele.
- **Şema değişiklikleri additive-only** + her biri `_ensure_column` ile kayıtlı olmalı (migration framework yok; `SCHEMA`'yı değiştirmek mevcut DB'leri güncellemez).
- **Tüm yıkıcı/hassas endpoint'ler** (purge / forget / export / budget) Host/Origin kapısının (P0-A) arkasında olmalı — bu yüzden o kapı birinci.
- **Bildirimler** yalnızca menü çubuğu app'inden gelmeli, başsız LaunchAgent'lardan değil.
