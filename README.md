# CardToPLC — Kart Okuyucu → Siemens S7 PLC Köprüsü

Seri porttan (COM) gelen barkod/kart okuyucu verisini, Siemens S7 PLC'nin (S7-1200/1500/300) Data Block offset'ine **S7 STRING** olarak yazan hafif Windows masaüstü uygulaması.

> Tek `.exe`, Python gerekmez, sistem tepsisinde arka planda çalışır.

---

## Özellikler

- **Sistem tepsisi (tray)** — uygulama arka planda çalışır, konsol penceresi açmaz
- **Canlı kart okuma** — COM porttan gelen byte'ları 50 ms idle-gap yöntemiyle paket olarak alır (Enter göndermesine gerek yok)
- **Sürekli PLC yazma** — kart varken değeri, kart çekilince boş STRING yazar (~20 Hz)
- **Otomatik yeniden bağlanma** — COM port veya PLC koparsa sessizce tekrar dener
- **Manuel gönder** — kart olmadan istediğin değeri PLC'ye yaz (test/debug)
- **COM Aç/Kapa** — tek tıkla seri bağlantıyı durdur/başlat
- **Tek tıkla kurulum** — `install.bat` ile Windows başlangıcına ekler, masaüstü kısayolu oluşturur

---

## Ekran Görüntüsü

```
┌─────────────────────────────────────┐
│  Kart → PLC  |  Config              │
├──────────────┬──────────────────────┤
│ [Ayarlar]    │ [Manuel Gönder]      │
│              │                      │
│ COM Port  ▼⟳│ DB offset'e elle     │
│ Baudrate     │ değer gönder         │
│ PLC IP       │                      │
│ Rack / Slot  │ [Gönder]             │
│ Data Block   │ [Boş gönder]         │
│ String Offset│ [Canlıya dön]        │
│ String Length│                      │
│              │                      │
│ [Kaydet]     │                      │
│ [COM: AÇIK]  │                      │
│              │                      │
│ ┌──────────┐ │                      │
│ │ 1234567  │ │ ← okunan kart        │
│ └──────────┘ │                      │
├──────────────┴──────────────────────┤
│ Seri: COM3 @ 19200                  │
│ PLC durumu: 192.168.0.1 (bağlı)    │
└─────────────────────────────────────┘
```

---

## Config Alanları

| Alan | Açıklama | Örnek |
|------|----------|-------|
| COM Port | Kart okuyucunun bağlı olduğu port | `COM3` |
| Baudrate | Seri iletişim hızı | `9600`, `19200` |
| PLC IP | PLC'nin ağ adresi | `192.168.0.1` |
| Rack | S7-1200/1500 → `0`, S7-300 → `0` | `0` |
| Slot | S7-1200/1500 → `1`, S7-300 → `2` | `1` |
| Data Block | Yazılacak DB numarası | `84` |
| String Offset | DB içindeki STRING başlangıç byte offset'i | `758` |
| String Length | TIA'da tanımlı `String[N]` değeri | `10` |
| Boş süre (sn) | Son kartten bu süre geçince PLC'ye `""` yazar | `0.4` |
| Yazma aralığı (sn) | PLC'ye yazma frekansı | `0.05` |

**Kaydet** → `config.json`'a yazar ve anında yeni ayarlarla yeniden bağlanır.

---

## Kurulum (Python'suz PC)

### 1. EXE'yi derle (geliştirici makinesinde, bir kez)

Python 3.9+ kurulu olmalı:

```bat
build.bat
```

Çıktı: `dist\CardToPLC.exe`

### 2. Hedef PC'ye kur

`CardToPLC.exe`, `install.bat`, `uninstall.bat` dosyalarını aynı klasöre koy, ardından:

```bat
install.bat
```

Bu script:
- Exe'yi `%LOCALAPPDATA%\CardToPLC\` klasörüne kopyalar
- Windows başlangıcına (Startup) ekler
- Masaüstü kısayolu oluşturur
- Uygulamayı hemen çalıştırır

Kaldırmak için:

```bat
uninstall.bat
```

> Yönetici hakkı gerektirmez — kullanıcı klasörüne kurar.

---

## Geliştirici Olarak Çalıştırma

```bash
pip install -r requirements.txt
python card_to_plc.py
```

---

## Teknik Notlar

### S7 STRING Formatı

TIA Portal'da DB değişkenini `String[N]` olarak tanımla. Uygulama bu adrese şunu yazar:

```
byte 0  = maksimum uzunluk (N)
byte 1  = aktif karakter sayısı
byte 2+ = ASCII karakterler
```

`String Length` alanını TIA'daki `N` ile aynı gir.

> **Önemli:** PLC DB'de **"Optimized block access"** kapalı olmalı (klasik/absolute erişim).  
> TIA Portal → DB → Properties → "Optimized block access" tikini kaldır.

### Kart Okuma Yöntemi (Idle-Gap)

Okuyucu Enter göndermediği için sabit uzunluk veya satır sonu beklenemez.  
Gelen byte'lar biriktirilerek seri hat **50 ms sessiz kalınca** paket tamamlanmış sayılır ve tüm tampon tek değer olarak işlenir.  
Bu süreyi değiştirmek için: `IDLE_GAP_MS = 50` (kodun başı).

### python-snap7 ve DLL

`python-snap7 >= 3.0` tamamen saf Python'dur — `snap7.dll` **gerekmez**.  
Eski sürüm kuruluysa:

```bash
pip install --upgrade "python-snap7>=3.0"
```

---

## Bağımlılıklar

| Paket | Amaç |
|-------|------|
| `pyserial` | COM port iletişimi |
| `python-snap7` | Siemens S7 PLC yazma (S7comm) |
| `pystray` | Sistem tepsisi ikonu |
| `Pillow` | Tepsi ikonu görseli |
| `pyinstaller` | Tek exe derleme |

---

## Lisans

MIT
