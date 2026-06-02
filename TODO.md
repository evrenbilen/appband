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

### [~] EPIC P1-C: Dashboard doğruluğu + dürüstlüğü  ·  **çoğu yapıldı** (135 test + 12 e2e geçiyor; 2 madde açık)
- [x] Ölü SSID filtresini bağla + `session_id` index'leri (backend `5601749`, frontend `48c39e4`) — `ssid`/`link_type` param, JOIN sessions, e2e doğruladı (M, high)
- [x] Yaklaşıklık rozetini görünür yap + "Nasıl okunur?" tooltip (By Domain hep, By App scope≠all) — `9679029` (S, high)
- [x] Kullanılmayan `/api/sessions`'tan "Oturum Geçmişi" görünümü — `58fa5e8` (ağ/başlangıç/süre/IP + canlı oturuma "Active" rozeti; e2e) (M, med)
- [x] 4 sabit ön-ayar dışında özel tarih-aralığı seçici — `41302b5` (yerel-geceyarısı sınır matematiği; e2e tek-gün=86400s) (M, med)
- [x] By App / By Domain için CSV dışa-aktarma (client-side blob, upload yok, CSP-güvenli) — `f563c4a` (S, med)
- [ ] Bilgi-mimarisi: tam yüzeyleri öne çıkar; by-domain'i ikincil yap (M, high) — **AÇIK**: kullanıcı-yüzü yeniden-düzen kararı, ekran-başı onayı bekliyor (`appband/web/index.html`, `app.js`)
- [ ] By App / By Domain listelerine client-side arama + "tümünü göster" (15'lik tavan) (M, med) — **AÇIK**: panel etkileşim-modeli kararı (grafik mi tablo mu, arama UX'i), ekran-başı onayı bekliyor (`appband/web/app.js`, `index.html`)

---

## P2 — İçgörü + performans + veri doğruluğu

### [~] EPIC P2-A: İçgörü + sayaçlı-ağ uyarıları (bildirim katmanı = menü çubuğu app'i)  ·  **metered uyarısı yapıldı**
- [x] iphone-hotspot/usb-tether geçişinde sayaçlı-ağ uyarısı — `38994be` (+ banner sunumu `5342957`, UNUserNotificationCenterDelegate) (S, high)
- [ ] Sürekli yüksek-throughput canlı uyarısı ("hotspot'unu bir şey hızla tüketiyor") (M, med) (`NetworkMonitor.swift`)
- [ ] Veri-kullanım bütçesi: `/api/budget` değerlendirme endpoint'i + macOS UserNotifications (L, high — `interface_samples` tam) (`appband/server.py`, mac-app)
- [ ] "Ben uyurken internete ne konuştu?" gece/uzakta raporu (M, med) (`appband/server.py`, mac-app)
- [ ] Günlük/haftalık özet digest'i (`/api/summary` + bildirim + dashboard kartı) (M, med)
- [ ] Öğrenilmiş (process, host) allowlist'ine karşı beklenmedik-hedef uyarısı (L, med)
- [ ] Process-başına anomali tespiti: kendi yuvarlanan baseline'ına göre "aniden konuşkan" (L, med)

### [~] EPIC P2-B: Retention ölçeğinde sorgu performansı  ·  **index + pragma yapıldı** (3 madde deferli)
- [ ] `connections`'ı yazma-anında dedup et: `UNIQUE(...)` + `INSERT OR IGNORE` (M, high) — **DEFERLENDİ**: by-domain/by-process paylaşım-oranını değiştirme riski + canlı toplama yazma-yolunu değiştirir, gözetimsiz doğrulanamaz (`appband/collector.py`, `appband/db.py`)
- [x] Composite index `connections(process_name, ts)` + `process_samples(process_name, ts)` — `e7c7f97` (+ mevcut `idx_proc_name_ts`) (S, high)
- [x] `connections(session_id)` + `dns_cache(resolved_at)` index'leri — `5601749` + `9c08c33` (EXPLAIN: purge artık SEARCH USING INDEX) (S, med)
- [x] SQLite PRAGMA'lar (`mmap_size`, `cache_size`, `temp_store=MEMORY`, `synchronous=NORMAL`) — `86a59ec` (`apply_perf_pragmas`, WAL-güvenli) (S, med)
- [ ] Pahalı endpoint'ler için kısa-TTL in-process response cache (S, med) — **DEFERLENDİ**: threaded server'da cache invalidation karmaşıklığı, ölçülmüş ihtiyaç yok (`appband/server.py`)
- [ ] API pagination/limit koruması + zaman-penceresi tavanı (S, med) — **DEFERLENDİ**: localhost-only + tek kullanıcı + Host/Origin kapısı → gerçek istismar yüzeyi yok; dashboard zaten limit/aralık veriyor (`appband/server.py`)

### [~] EPIC P2-C: Veri-modeli doğruluğu (yakalanan-ama-kullanılmayan alanlar)  ·  **4/5 yapıldı** (1 deferli)
- [x] VPN/tunnel oturumlarını `vpn` etiketle (`utun/ipsec/ppp`) — `03d4c99` (S, med)
- [x] IPv6 zone-id (`%en0`) sıyır + bracketless IPv6 ayrıştır — `3a3b8e6` + `b76b429` (S, med)
- [x] Uyku/uyanma boşluklarını kaydet (`gaps`) + `/api/gaps` + timeseries banner — `a56f227` + `ca911fd` + `4acef15` (M, med)
- [ ] PID → app bundle id + görünen ad (`plistlib`) ile kararlı per-app gruplama (M, med) — **DEFERLENDİ**: yeni parser + yazma-yolu + şema sütunu; eşleştirme heuristiği gerçek process verisi gerektirir, gözetimsiz doğrulanamaz (`appband/parsers/proc_info.py`, `collector.py`, `db.py`)
- [x] Port/protokol kırılımı `/api/by-port` + dashboard paneli — `30ef393` + panel `027871a` (S, low)

### [x] EPIC P2-D: Test derinliği  ·  **TAMAMLANDI**
- [x] Yaklaşık by-domain/by-process dağıtım matematiğini bilinen byte değerleriyle test — `9d35275` + `519cdc0` (+ rounding fix & çok-bucket koruma testi `14c2452`) (M, high)
- [x] Parser testlerini gerçek fixture'lardan sür (30KB `lsof_i.txt` dahil) — `f5bd151` + `5b32703` (nettop/route/ipconfig/ifconfig) (S, med)
- [x] `_run` subprocess-failure yolu + `collect_snapshot` happy-path — `6efd4bf` (+ mevcut `_run` missing/transient kapsaması) (S, med)
- [x] CI'a `shellcheck` + `plutil -lint` — `a4a0c05` (lokal doğrulandı: scriptler temiz, template'ler OK) (S, med)
- [x] Locale anahtar-paritesi unittest'i — `5b32703` (`tests/test_locales.py`) (S, low)
- [x] Server testlerindeki ResourceWarning'leri sustur (socket + HTTPError) — `519cdc0` (`-W error::ResourceWarning` temiz) (S, low)
- [x] Atıl `netstat` parser'ını sil (gerçekte kullanılmıyordu) — `fb5a4bd` (S, low)

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

### [~] EPIC P3-C: Release engineering + dağıtım  ·  **otomasyon yapıldı** (yalnız GitHub'da tag'de çalışır)
- [x] Tag ile tetiklenen release workflow: build + DMG + SHA-256 + `gh release create` — `3cbf58f` (M, high)
- [x] SHA-256 manifestini yayınla — `3cbf58f` (release workflow üretir; `v*` tag'de) (S, high)
- [x] Commit'lenmiş DMG'leri + scratch image'i sil ve gitignore'la — zaten temiz: `*.dmg`/`.build/`/`AppBand.app/` gitignore'lu, 1MB üzeri izlenen dosya yok (yalnız niyetli README/DMG PNG'leri) (S, med)
- [ ] Notarization plumbing'i env-credential'ların arkasında ekle (ad-hoc fallback bozulmadan) (M, — ücretli Apple hesabı gerekir) (`mac-app/build-dmg.sh`)
- [ ] Homebrew cask (ayrı tap repo, yayınlanmış SHA + Release URL'lerine bağlı) (M, high)
- [ ] GitHub Releases API'sine karşı "güncelleme var" kontrolü (uygulamanın tek dış çağrısı → opt-in + README'de belgele) (M, med) (mac-app)

### [~] EPIC P3-D: Dokümanlar + onboarding  ·  **3/5 yapıldı**
- [x] `CHANGELOG.md` (v0.1.0–v0.1.4 + Unreleased) — `b2acd73` + `9aa663a` (S, med)
- [x] Mimari dokümanı → `docs/ARCHITECTURE.md` — `6df48c9` (S, med)
- [x] Dört shell script'e `--help`/usage çıktısı — `5419049` (yan-etkiden önce çıkar; lokal doğrulandı) (S, med)
- [ ] Dashboard'a ilk-çalıştırma onboarding overlay'i (M, med) — **AÇIK**: P1-C bilgi-mimarisi indikten sonra (`appband/web/`)
- [ ] Mac uygulamasının menü/About'unu yerelleştir veya "İngilizce-only" olduğunu belgele (S, low) — **AÇIK**

---

## Kısıt notları (ihlal değil — incelemede dikkat)

- **Chart.js vendor'lama** ve **mac-app güncelleme kontrolü** "no deps / localhost-only" kurallarını ihlal etmez (kural Python *server* bind'i için; Swift app ayrı). Yine de güncelleme kontrolünü opt-in yap ve README Privacy'de belgele.
- **Şema değişiklikleri additive-only** + her biri `_ensure_column` ile kayıtlı olmalı (migration framework yok; `SCHEMA`'yı değiştirmek mevcut DB'leri güncellemez).
- **Tüm yıkıcı/hassas endpoint'ler** (purge / forget / export / budget) Host/Origin kapısının (P0-A) arkasında olmalı — bu yüzden o kapı birinci.
- **Bildirimler** yalnızca menü çubuğu app'inden gelmeli, başsız LaunchAgent'lardan değil.
