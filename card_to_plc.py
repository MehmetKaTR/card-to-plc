# -*- coding: utf-8 -*-
"""
Card -> Siemens S7 PLC
======================
Tek uygulama. Sistem tepsisinde (sağ alt, görev çubuğu) arka planda çalışır.
Seri porttan (COM) kart okuyucudan gelen her satırı (\\r\\n ile biten) okur,
config'te tanımlı Siemens PLC'nin DB offset'ine S7 STRING olarak yazar.

Tepsi (tray) ikonuna çift tıklayınca / sağ tık > "Aç" ile config penceresi açılır.
Pencereyi kapatınca uygulama KAPANMAZ, arka planda okumaya devam eder.
Tamamen kapatmak için tepsi ikonu > "Çıkış".

Ayarlar config.json dosyasına kaydedilir (exe'nin yanında).
"""

import os
import sys
import json
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import serial
import serial.tools.list_ports
import snap7

from PIL import Image, ImageDraw
import pystray


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------
def app_dir():
    """exe (PyInstaller) ya da .py yanındaki klasör."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(app_dir(), "config.json")

# Seri hat bu kadar ms sessiz kalınca "paket tamamlandı" sayılır (referans: 50 ms).
# Okuyucu Enter göndermiyor; kart burst halinde gelir, susunca okuma tamamlanır.
IDLE_GAP_MS = 50

# PLC'ye yazma temposu (saniye). 0.05 = saniyede ~20 kez, durmadan yaz.
WRITE_INTERVAL = 0.05

# Bu süre kadar yeni kart paketi gelmezse "kart yok" sayılır ve PLC'ye BOŞ yazılır.
CLEAR_TIMEOUT = 0.4

DEFAULT_CONFIG = {
    "com_port": "COM1",
    "baudrate": 19200,
    "plc_ip": "192.168.0.1",
    "rack": 0,
    "slot": 1,
    "db_number": 84,
    "string_offset": 758,
    "string_length": 10,
    "clear_timeout": 0.4,
    "write_interval": 0.05,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def build_s7_string(value, max_length):
    """
    Siemens S7 STRING formatı:
      byte0 = maksimum uzunluk
      byte1 = güncel (aktif) uzunluk
      byte2.. = ASCII karakterler
    Toplam = max_length + 2 byte.
    """
    value = value[:max_length]
    data = bytearray(max_length + 2)
    data[0] = max_length
    data[1] = len(value)
    data[2:2 + len(value)] = value.encode("ascii", errors="ignore")
    return data


# ----------------------------------------------------------------------------
# Arka plan işçisi: seri okuma + PLC'ye yazma
# ----------------------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, get_config, ui_queue):
        super().__init__(daemon=True)
        self.get_config = get_config        # güncel config'i döndüren fonksiyon
        self.ui = ui_queue                  # UI'ye mesaj kuyruğu
        self._stop = threading.Event()
        self._restart = threading.Event()   # config değişince yeniden bağlan
        self._enabled = threading.Event()   # COM bağlantısı aç/kapa
        self._enabled.set()                 # başlangıçta açık
        self.ser = None
        self.plc = None
        self._plc_ok = None                 # son PLC durumu (spam'i önlemek için)
        self._plc_shown_value = None        # statüde gösterilen son değer
        self._manual = None                 # manuel override (None = kapalı)

    # --- dış kontrol ---
    def stop(self):
        self._stop.set()

    def send_manual(self, value):
        # Elle değer gönder: kart okunana / "Canlıya dön"e basılana kadar yazılır.
        self._manual = value

    def clear_manual(self):
        self._manual = None                 # canlı (kart) moduna dön

    def restart(self):
        self._restart.set()

    def enable(self):
        self._enabled.set()

    def disable(self):
        self._enabled.clear()

    def is_enabled(self):
        return self._enabled.is_set()

    # --- UI bildirimleri ---
    def log(self, text):
        self.ui.put(("log", text))

    def set_card(self, text):
        self.ui.put(("card", text))

    def set_plc_status(self, ok, text):
        self.ui.put(("plc", (ok, text)))

    def set_serial_status(self, ok, text):
        self.ui.put(("serial", (ok, text)))

    # --- bağlantılar ---
    def _open_serial(self, cfg):
        self._close_serial()
        try:
            self.ser = serial.Serial(
                port=cfg["com_port"],
                baudrate=int(cfg["baudrate"]),
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.02,
            )
            # KRİTİK: bazı okuyucular DTR/RTS açık olmadan veri göndermez.
            try:
                self.ser.dtr = True
                self.ser.rts = True
            except Exception:
                pass
            self.set_serial_status(True, "Seri: %s @ %s" % (cfg["com_port"], cfg["baudrate"]))
            self.log("Seri port açıldı: %s" % cfg["com_port"])
            return True
        except Exception as e:
            self.ser = None
            self.set_serial_status(False, "Seri HATA: %s" % e)
            return False

    def _close_serial(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _open_plc(self, cfg):
        self._close_plc()
        try:
            self.plc = snap7.client.Client()
            self.plc.connect(cfg["plc_ip"], int(cfg["rack"]), int(cfg["slot"]))
            if self.plc.get_connected():
                self.set_plc_status(True, "PLC bağlı: %s" % cfg["plc_ip"])
                self.log("PLC bağlandı: %s" % cfg["plc_ip"])
                return True
            self.set_plc_status(False, "PLC bağlanamadı")
            return False
        except Exception as e:
            self.plc = None
            self.set_plc_status(False, "PLC HATA: %s" % e)
            return False

    def _close_plc(self):
        if self.plc is not None:
            try:
                self.plc.disconnect()
            except Exception:
                pass
            self.plc = None

    def _write_plc(self, cfg, value):
        try:
            # get_connected() her yazışta aktif soket kontrolü yapıp yavaşlatır;
            # onun yerine doğrudan yaz, kopukluğu exception ile yakala.
            if self.plc is None:
                if not self._open_plc(cfg):
                    return False
            data = build_s7_string(value, int(cfg["string_length"]))
            self.plc.db_write(int(cfg["db_number"]), int(cfg["string_offset"]), data)
            # Saniyede ~20 yazım olduğu için durumu yalnızca DEĞİŞİNCE bildir
            if self._plc_ok is not True or self._plc_shown_value != value:
                self.set_plc_status(True, "PLC bağlı: %s (yazılıyor: %s)" % (cfg["plc_ip"], value))
                self._plc_ok = True
                self._plc_shown_value = value
            return True
        except Exception as e:
            if self._plc_ok is not False:
                self.set_plc_status(False, "PLC yazma HATA: %s" % e)
                self._plc_ok = False
            self._close_plc()
            return False

    # --- ana döngü ---
    def run(self):
        cfg = self.get_config()
        if self._enabled.is_set():
            self._open_serial(cfg)
        self._open_plc(cfg)
        buf = b""
        last_data = time.time()       # son byte zamanı (idle-gap için)
        current_value = ""            # son okunan kart değeri ("" = kart yok)
        last_value_time = 0.0         # son geçerli paket zamanı
        last_write = 0.0              # son PLC yazma zamanı
        displayed = None              # ekranda gösterilen son değer

        while not self._stop.is_set():
            # config değişti -> ANINDA yeniden bağlan (COM/IP hemen etkin)
            if self._restart.is_set():
                self._restart.clear()
                cfg = self.get_config()
                self.log("Ayarlar değişti, yeniden bağlanılıyor...")
                if self._enabled.is_set():
                    self._open_serial(cfg)
                else:
                    self._close_serial()
                self._open_plc(cfg)
                buf = b""

            # COM bağlantısı kapalıysa (Aç/Kapa butonu) okuma yapma
            if not self._enabled.is_set():
                if self.ser is not None:
                    self._close_serial()
                    self.set_serial_status(False, "Bağlantı KAPALI")
                time.sleep(0.2)
                continue

            # Açık ama port kapalıysa aç
            if self.ser is None:
                if not self._open_serial(cfg):
                    time.sleep(2)
                    continue

            # --- 1) Seri porttan gelen byte'ları biriktir (referans yöntemi) ---
            try:
                n = self.ser.in_waiting
                chunk = self.ser.read(n if n > 0 else 1)
            except Exception as e:
                self.set_serial_status(False, "Seri okuma HATA: %s" % e)
                self._close_serial()
                time.sleep(1)
                continue

            if chunk:
                buf += chunk
                last_data = time.time()

            # --- 2) Seri hat 50 ms sessiz kalınca paket TAMAM -> son değeri güncelle
            # (Sabit uzunlukla kesmiyoruz; burst bitince tüm tampon bir okumadır.)
            if buf and (time.time() - last_data) * 1000.0 > IDLE_GAP_MS:
                value = buf.decode("ascii", errors="ignore").strip("\r\n\t \x00")
                buf = b""
                if value:
                    current_value = value
                    last_value_time = time.time()
                    self._manual = None   # gerçek kart, manuel override'ı iptal eder

            # --- 3) PLC'ye DURMADAN yaz: kart varsa değeri, yoksa BOŞ (sil + yaz) ---
            now = time.time()
            try:
                write_iv = float(cfg.get("write_interval", WRITE_INTERVAL))
            except (ValueError, TypeError):
                write_iv = WRITE_INTERVAL
            if (now - last_write) >= write_iv:
                try:
                    clear_to = float(cfg.get("clear_timeout", CLEAR_TIMEOUT))
                except (ValueError, TypeError):
                    clear_to = CLEAR_TIMEOUT
                if self._manual is not None:
                    live = self._manual        # manuel override (2. sekme)
                elif current_value and (now - last_value_time) <= clear_to:
                    live = current_value
                else:
                    live = ""                 # kart çekildi / veri yok -> sıfırla
                    current_value = ""
                if live != displayed:         # ekranı canlı güncelle (boşsa temizle)
                    self.set_card(live)
                    displayed = live
                self._write_plc(cfg, live)    # boş değer = sıfır uzunluklu STRING
                last_write = now

        self._close_serial()
        self._close_plc()


# ----------------------------------------------------------------------------
# Config penceresi (Tkinter)
# ----------------------------------------------------------------------------
class ConfigWindow:
    def __init__(self):
        self.config = load_config()
        self.ui_queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("Kart -> PLC  |  Config")
        self.root.resizable(False, False)
        self.root.geometry("340x600")

        self.vars = {}
        self._build_form()
        self._build_status()

        # Pencere X ile kapatılınca -> tepsiye gizle (uygulama çalışmaya devam)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        # Worker başlat
        self.worker = Worker(lambda: dict(self.config), self.ui_queue)
        self.worker.start()

        # Tray ikonu
        self.tray = None
        self._start_tray()

        # UI kuyruğunu periyodik kontrol et
        self.root.after(150, self._drain_queue)

    # --- form ---
    def _row(self, parent, label, key, width=18):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text=label, width=14, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(self.config.get(key, "")))
        ttk.Entry(frame, textvariable=var, width=width).pack(side="left", fill="x", expand=True)
        self.vars[key] = var

    def _com_row(self, parent):
        """COM port'u yazmak yerine PC'deki portlardan seçtir."""
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        ttk.Label(frame, text="COM Port", width=14, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(self.config.get("com_port", "")))
        self.com_combo = ttk.Combobox(frame, textvariable=var, width=11, state="readonly")
        self.com_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(frame, text="⟳", width=3, command=self._refresh_ports).pack(side="left", padx=(4, 0))
        self.vars["com_port"] = var
        self._refresh_ports()

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        cur = self.vars["com_port"].get()
        # Kayıtlı port şu an takılı değilse bile listede kalsın
        if cur and cur not in ports:
            ports = ports + [cur]
        self.com_combo["values"] = ports
        if not self.vars["com_port"].get() and ports:
            self.vars["com_port"].set(ports[0])

    def _build_form(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True)

        # ---- Sekme 1: Ayarlar ----
        pad = ttk.Frame(nb, padding=10)
        nb.add(pad, text="Ayarlar")

        ttk.Label(pad, text="Bağlantı Ayarları", font=("Segoe UI", 10, "bold")).pack(anchor="w")

        self._com_row(pad)
        self._row(pad, "Baudrate", "baudrate")
        self._row(pad, "PLC IP", "plc_ip")
        self._row(pad, "Rack", "rack")
        self._row(pad, "Slot", "slot")
        self._row(pad, "Data Block", "db_number")
        self._row(pad, "String Offset", "string_offset")
        self._row(pad, "String Length", "string_length")
        self._row(pad, "Boş süre (sn)", "clear_timeout")
        self._row(pad, "Yazma aralığı (sn)", "write_interval")

        ttk.Button(pad, text="Kaydet", command=self.on_save).pack(fill="x", pady=(8, 4))

        self.conn_btn = ttk.Button(pad, text="COM Bağlantısı: AÇIK (Kapat)",
                                   command=self.toggle_conn)
        self.conn_btn.pack(fill="x", pady=(0, 6))

        ttk.Label(pad, text="Okunan Kart (canlı)", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.card_box = tk.Text(pad, height=3, width=36, state="disabled",
                                bg="#111", fg="#0f0", font=("Consolas", 11))
        self.card_box.pack(fill="x", pady=(2, 6))

        self._pad = pad

        # ---- Sekme 2: Manuel Gönder ----
        tab2 = ttk.Frame(nb, padding=10)
        nb.add(tab2, text="Manuel Gönder")
        self._build_manual_tab(tab2)

    def _build_manual_tab(self, parent):
        ttk.Label(parent, text="DB string offset'e elle değer gönder",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(parent, text="(Ayarlar sekmesindeki DB / String Offset'e yazılır)",
                  foreground="#888").pack(anchor="w", pady=(0, 8))

        self.manual_var = tk.StringVar()
        ent = ttk.Entry(parent, textvariable=self.manual_var, width=30,
                        font=("Consolas", 11))
        ent.pack(fill="x", pady=2)
        ent.bind("<Return>", lambda e: self.on_manual_send())

        ttk.Button(parent, text="Gönder", command=self.on_manual_send).pack(fill="x", pady=(6, 3))
        ttk.Button(parent, text="Boş gönder (sıfırla)",
                   command=self.on_manual_clear_value).pack(fill="x", pady=3)
        ttk.Button(parent, text="Canlıya dön (kart okumaya)",
                   command=self.on_manual_release).pack(fill="x", pady=3)

        self.manual_info = ttk.Label(parent, text="", foreground="#1a7", wraplength=290,
                                     justify="left")
        self.manual_info.pack(anchor="w", pady=(8, 0))
        ttk.Label(parent,
                  text="Gönderilen değer, kart okunana veya 'Canlıya dön'e basılana "
                       "kadar PLC'ye yazılır.",
                  foreground="#888", wraplength=290, justify="left").pack(anchor="w", pady=(10, 0))

    def _build_status(self):
        bar = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        bar.pack(side="bottom", fill="x")
        self.serial_lbl = ttk.Label(bar, text="Seri: -", foreground="#888")
        self.serial_lbl.pack(anchor="w")
        self.plc_lbl = ttk.Label(bar, text="PLC durumu: -", foreground="#888")
        self.plc_lbl.pack(anchor="w")

    # --- kaydet ---
    def on_save(self):
        try:
            new_cfg = {
                "com_port": self.vars["com_port"].get().strip(),
                "baudrate": int(self.vars["baudrate"].get()),
                "plc_ip": self.vars["plc_ip"].get().strip(),
                "rack": int(self.vars["rack"].get()),
                "slot": int(self.vars["slot"].get()),
                "db_number": int(self.vars["db_number"].get()),
                "string_offset": int(self.vars["string_offset"].get()),
                "string_length": int(self.vars["string_length"].get()),
                "clear_timeout": float(self.vars["clear_timeout"].get().replace(",", ".")),
                "write_interval": float(self.vars["write_interval"].get().replace(",", ".")),
            }
        except ValueError:
            messagebox.showerror("Hata", "Sayısal alanlara (baudrate, rack, slot, DB, offset, length, boş süre, yazma aralığı) geçerli sayı girin.")
            return
        self.config = new_cfg
        save_config(new_cfg)
        self.worker.restart()  # yeni ayarlarla ANINDA yeniden bağlan
        messagebox.showinfo("Kaydedildi", "Ayarlar kaydedildi ve uygulandı.")

    # --- manuel gönder (2. sekme) ---
    def on_manual_send(self):
        val = self.manual_var.get()
        self.worker.send_manual(val)
        self.manual_info.config(text="Gönderiliyor: '%s'" % val, foreground="#1a7")

    def on_manual_clear_value(self):
        self.worker.send_manual("")   # PLC'ye boş yaz (sıfırla)
        self.manual_info.config(text="Boş (sıfır) gönderiliyor.", foreground="#1a7")

    def on_manual_release(self):
        self.worker.clear_manual()    # canlı kart moduna dön
        self.manual_info.config(text="Canlı moda dönüldü (kart okuma).", foreground="#888")

    # --- COM bağlantısı aç/kapa ---
    def toggle_conn(self):
        if self.worker.is_enabled():
            self.worker.disable()
            self.conn_btn.config(text="COM Bağlantısı: KAPALI (Aç)")
        else:
            self.worker.enable()
            self.conn_btn.config(text="COM Bağlantısı: AÇIK (Kapat)")

    # --- canlı kart kutusu ---
    def _set_card_text(self, text):
        self.card_box.config(state="normal")
        self.card_box.delete("1.0", "end")   # her yeni kartta sıfırla
        self.card_box.insert("1.0", text)
        self.card_box.config(state="disabled")

    # --- UI kuyruğu ---
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "card":
                    self._set_card_text(payload)
                elif kind == "plc":
                    ok, text = payload
                    self.plc_lbl.config(text="PLC durumu: " + text,
                                        foreground="#1a7" if ok else "#c33")
                elif kind == "serial":
                    ok, text = payload
                    self.serial_lbl.config(text=text,
                                           foreground="#1a7" if ok else "#c33")
                elif kind == "log":
                    pass  # istenirse log dosyasına yazılabilir
        except queue.Empty:
            pass
        self.root.after(150, self._drain_queue)

    # --- tepsi (tray) ---
    def _make_icon_image(self):
        img = Image.new("RGB", (64, 64), "#1f6feb")
        d = ImageDraw.Draw(img)
        d.rectangle([14, 22, 50, 42], outline="white", width=3)  # kart simgesi
        d.line([18, 48, 46, 48], fill="white", width=3)
        return img

    def _start_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Aç (Config)", self._tray_open, default=True),
            pystray.MenuItem("Çıkış", self._tray_quit),
        )
        self.tray = pystray.Icon("card2plc", self._make_icon_image(),
                                 "Kart -> PLC (çalışıyor)", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _tray_open(self, icon=None, item=None):
        self.root.after(0, self.show_window)

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self.quit_app)

    # --- pencere göster/gizle ---
    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        self.root.withdraw()  # tepsiye gizle, uygulama çalışmaya devam eder

    def quit_app(self):
        try:
            self.worker.stop()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        # Açılışta gizli başla (sadece tepsi) — istenirse show_window ile aç
        self.root.after(300, self.hide_window)
        self.root.mainloop()


if __name__ == "__main__":
    ConfigWindow().run()
