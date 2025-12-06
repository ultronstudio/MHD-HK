import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# Nahrávání / audio processing
try:
    import sounddevice as sd
    import numpy as np
except Exception as e:
    sd = None
    np = None

# Pro export do MP3 použijeme pydub (vyžaduje ffmpeg v PATH)
try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None
try:
    import simpleaudio as sa
except Exception:
    sa = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
SYS_AUDIO_DIR = os.path.join(AUDIO_DIR, "sys")
STOPS_AUDIO_DIR = os.path.join(AUDIO_DIR, "stops")
LINES_DIR = os.path.join(BASE_DIR, "lines")

APP_TITLE = "MHD HK – Recorder"
LOG_PATH = os.path.join(BASE_DIR, "record.log")

def _log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

# Globální bezpečnostní háčky proti pádu
def _global_excepthook(exctype, value, tb):
    try:
        _log(f"GLOBAL: {exctype.__name__}: {value}")
        messagebox.showerror("Neočekávaná chyba", f"{exctype.__name__}: {value}")
    except Exception:
        pass
sys.excepthook = _global_excepthook

def _thread_excepthook(args):
    try:
        _log(f"THREAD: {args.exc_type.__name__}: {args.exc_value}")
        messagebox.showerror("Chyba ve vlákně", f"{args.exc_type.__name__}: {args.exc_value}")
    except Exception:
        pass
try:
    threading.excepthook = _thread_excepthook
except Exception:
    pass

def safe_action(fn):
    # Dekorátor: zachytí výjimky z UI akcí
    def _wrap(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception as e:
            _log(f"SAFE_ACTION ERROR in {getattr(fn, '__name__', 'unknown')}: {e}")
            try:
                messagebox.showerror("Chyba", f"Operace selhala:\n{e}")
            except Exception:
                pass
    return _wrap

class Recorder:
    def __init__(self, samplerate=44100, channels=1):
        self.samplerate = samplerate
        self.channels = channels
        self._recording = False
        self._frames = []
        self._stream = None

    def _detect_samplerate(self):
        # Pokus se získat nativní samplerate zařízení, aby nedošlo ke zkreslení
        try:
            if sd is not None:
                if sd.default.samplerate:
                    return int(sd.default.samplerate)
                dev = sd.query_devices(kind='input')
                sr = dev.get('default_samplerate') or dev.get('default_sample_rate')
                if sr:
                    return int(sr)
        except Exception:
            pass
        return self.samplerate

    def start(self):
        if sd is None or np is None:
            raise RuntimeError("Chybí knihovna sounddevice nebo numpy. Nainstalujte je: pip install sounddevice numpy")
        self._frames = []
        self._recording = True
        # Nastav samplerate podle zařízení, aby se předešlo zpomalenému/robotickému zvuku
        effective_sr = self._detect_samplerate()
        self.samplerate = effective_sr
        self._stream = sd.InputStream(samplerate=self.samplerate, channels=self.channels, dtype='float32', callback=self._callback)
        self._stream.start()

    def _callback(self, indata, frames, time, status):
        if status:
            # Můžeme zalogovat, ale nepanikařit
            pass
        if self._recording:
            self._frames.append(indata.copy())

    def stop(self):
        if not self._recording:
            return None
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._frames:
            return None
        data = np.concatenate(self._frames, axis=0)
        # Pokud by zařízení poskytovalo více kanálů, sjednoť na požadovaný počet
        if data.ndim == 2 and self.channels == 1:
            # převod na mono průměrováním, aby nedošlo k fázovým artefaktům
            data = data.mean(axis=1)
        return data  # numpy array float32 [-1,1]

class RecordWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(False, False)

        # Stav
        self.category_var = tk.StringVar(value="sys")
        self.filename_var = tk.StringVar(value="")
        self.volume_var = tk.IntVar(value=100)  # 0-200 %

        self.recorder = Recorder()
        self.preview_data = None  # numpy float32
        self.preview_segment = None  # pydub.AudioSegment
        self.is_playing = False
        self.play_thread = None
        self.silence_threshold_var = tk.IntVar(value=3)  # % z max amplitudy
        self.play_pos_ms = 0
        self.play_duration_ms = 0
        self._play_start_monotonic = None
        self._recording_timer = None
        self._play_stream = None
        self._play_index = 0
        self._playback_obj = None
        self._last_stop_time = 0.0
        self._shutting_down_playback = False
        self._shutting_down_playback = False

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=(20, 15, 20, 15))
        main.grid(row=0, column=0, sticky="nsew")

        # Kategorie
        ttk.Label(main, text="Kategorie:").grid(row=0, column=0, sticky="w")
        cat_frame = ttk.Frame(main)
        cat_frame.grid(row=0, column=1, sticky="w")
        self.radio_sys = ttk.Radiobutton(cat_frame, text="System (sys)", variable=self.category_var, value="sys")
        self.radio_sys.grid(row=0, column=0, sticky="w")
        self.radio_stops = ttk.Radiobutton(cat_frame, text="Zastávky (stops)", variable=self.category_var, value="stops")
        self.radio_stops.grid(row=0, column=1, sticky="w")

        # Název souboru (automaticky ze zastávek v lines/*.json)
        ttk.Label(main, text="Zastávka / soubor:").grid(row=1, column=0, pady=(10, 0), sticky="w")
        self.filename_combo = ttk.Combobox(main, textvariable=self.filename_var, width=40, state="readonly")
        self.filename_combo.grid(row=1, column=1, pady=(10, 0), sticky="w")
        # Bezpečně zachytit výběr, pouze aktualizovat label/info
        try:
            self.filename_combo.bind("<<ComboboxSelected>>", lambda e: self._on_filename_selected())
        except Exception:
            pass
        ttk.Button(main, text="↻ Načíst", command=self._load_stop_names).grid(row=1, column=2, pady=(10, 0), sticky="w")

        # Hlasitost
        ttk.Label(main, text="Hlasitost:").grid(row=2, column=0, pady=(10, 0), sticky="w")
        vol_frame = ttk.Frame(main)
        vol_frame.grid(row=2, column=1, pady=(10, 0), sticky="w")
        # Nejprve vytvoř štítek, aby existoval při prvním přenastavení
        self.vol_label = ttk.Label(vol_frame, text="100 %")
        self.vol_label.grid(row=0, column=1, padx=(10, 0))
        # Vytvoř Scale bez command, nastav počáteční hodnotu, pak připoj command
        vol_scale = ttk.Scale(vol_frame, from_=0, to=200, orient="horizontal")
        vol_scale.set(self.volume_var.get())
        vol_scale.configure(command=lambda v: self._on_volume_change(v))
        vol_scale.grid(row=0, column=0, sticky="ew")

        # Ovládání nahrávání
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=(15, 0), sticky="w")
        self.btn_rec = ttk.Button(btn_frame, text="● Nahrávat", command=self.on_record)
        self.btn_rec.grid(row=0, column=0, padx=(0, 5))
        self.btn_stop = ttk.Button(btn_frame, text="■ Stop", command=self.on_stop)
        self.btn_stop.grid(row=0, column=1, padx=(0, 5))
        self.btn_preview = ttk.Button(btn_frame, text="▶ Náhled", command=self.on_preview)
        self.btn_preview.grid(row=0, column=2, padx=(0, 5))
        self.btn_clear = ttk.Button(btn_frame, text="✖ Smazat náhled", command=self.on_clear_preview)
        self.btn_clear.grid(row=0, column=3, padx=(0, 5))

        # Waveform + ořez ticha
        wf_frame = ttk.LabelFrame(main, text="Waveform")
        wf_frame.grid(row=4, column=0, columnspan=3, pady=(15, 0), sticky="ew")
        self.waveform_canvas = tk.Canvas(wf_frame, width=600, height=120, bg="#f7f7f7", highlightthickness=1, highlightbackground="#ccc")
        self.waveform_canvas.grid(row=0, column=0, columnspan=3, padx=5, pady=5)
        # Časová informace a playhead
        info_frame = ttk.Frame(wf_frame)
        info_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=5)
        self.time_label = ttk.Label(info_frame, text="00:00 / 00:00")
        self.time_label.grid(row=0, column=0, sticky="w")
        # Playhead je vykreslován v _draw_waveform/_update_playhead
        ttk.Label(wf_frame, text="Prahová hodnota ticha (%):").grid(row=2, column=0, sticky="w", padx=5)
        thr_scale = ttk.Scale(wf_frame, from_=0, to=20, orient="horizontal")
        thr_scale.set(self.silence_threshold_var.get())
        thr_scale.grid(row=2, column=1, sticky="ew", padx=5)
        self.thr_label = ttk.Label(wf_frame, text=f"{self.silence_threshold_var.get()} %")
        self.thr_label.grid(row=2, column=2, sticky="w")
        thr_scale.configure(command=lambda v: self._on_threshold_change(v))
        self.btn_trim_silence = ttk.Button(wf_frame, text="✂ Osekat ticho", command=self.on_trim_silence)
        self.btn_trim_silence.grid(row=3, column=2, sticky="e", padx=5, pady=(5, 5))

        # Export
        export_frame = ttk.Frame(main)
        export_frame.grid(row=5, column=0, columnspan=3, pady=(15, 0), sticky="e")
        self.btn_export = ttk.Button(export_frame, text="Exportovat MP3", command=self.on_export)
        self.btn_export.grid(row=0, column=0)

        # Info
        self.info_label = ttk.Label(main, text="Připraveno", foreground="#666")
        self.info_label.grid(row=6, column=0, columnspan=3, pady=(10, 0), sticky="w")
        # Načti seznam zastávek při startu
        try:
            self._load_stop_names()
        except Exception:
            pass

    def _on_volume_change(self, v):
        try:
            val = int(float(v))
        except Exception:
            val = self.volume_var.get()
        val = max(0, min(200, val))
        self.volume_var.set(val)
        self.vol_label.config(text=f"{val} %")
        # Aktualizuj waveform podle vizuální hlasitosti
        self._draw_waveform()

    @safe_action
    def on_record(self):
        if sd is None:
            messagebox.showerror("Chybí závislosti", "Knihovna sounddevice není dostupná. Nainstalujte: pip install sounddevice")
            return
        # Pokud už nahráváme, ignoruj opakované kliknutí
        if getattr(self.recorder, "_recording", False):
            self.info_label.config(text="Už nahrávám…")
            return
        try:
            self.info_label.config(text="Nahrávám…")
            self.recorder.start()
            _log("Record started")
            # živý update vizuálu při nahrávání
            self._schedule_recording_update()
            # během nahrávání povolit pouze Stop
            try:
                self.btn_rec.state(["disabled"])
                self.btn_preview.state(["disabled"])
                self.btn_clear.state(["disabled"])
                self.btn_export.state(["disabled"])
                # Stop povolit
                self.btn_stop.state(["!disabled"])
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Nahrávání", f"Nelze zahájit nahrávání:\n{e}")

    @safe_action
    def on_stop(self):
        try:
            import time as _time
            now = _time.monotonic()
            # debounce: ignoruj rychlé opakování Stop
            if now - getattr(self, '_last_stop_time', 0) < 0.25:
                _log("Stop ignored due to debounce")
                return
            self._last_stop_time = now
            # zastavit případné přehrávání (idempotentně)
            if self._play_stream is not None:
                try:
                    self._play_stream.stop()
                except Exception:
                    pass
                try:
                    self._play_stream.close()
                except Exception:
                    pass
                self._play_stream = None
            self.is_playing = False
            self.play_pos_ms = 0
            # zrušit playhead timer přirozeně v _update_playhead
            self._draw_waveform()

            # zastavit nahrávací timer bezpečně
            if self._recording_timer is not None:
                try:
                    self.after_cancel(self._recording_timer)
                except Exception:
                    pass
                self._recording_timer = None

            # zastavit nahrávání (idempotentně)
            data = self.recorder.stop()
            _log("Record stopped")
            if data is None:
                self.info_label.config(text="Bez dat – zkuste znovu.")
                return
            self.preview_data = data  # numpy float32 [-1,1]
            self.preview_segment = None
            self.info_label.config(text=f"Nahrávka připravena. Délka: {len(data)/self.recorder.samplerate:.2f} s")
            self._draw_waveform()
            # live update už zrušen výše
            # znovu povolit tlačítka po ukončení nahrávání
            try:
                self.btn_rec.state(["!disabled"])
                self.btn_preview.state(["!disabled"])
                self.btn_clear.state(["!disabled"])
                self.btn_export.state(["!disabled"])
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Stop", f"Chyba při ukončení nahrávání:\n{e}")

    def _numpy_to_segment(self, data):
        # očekává float32 [-1,1]
        if AudioSegment is None:
            raise RuntimeError("Chybí pydub. Nainstalujte: pip install pydub (a mít ffmpeg v PATH)")
        # Převod na 16-bit PCM
        audio = (data * 32767).astype(np.int16)
        seg = AudioSegment(
            audio.tobytes(),
            frame_rate=self.recorder.samplerate,
            sample_width=2,
            channels=self.recorder.channels,
        )
        return seg

    @safe_action
    def on_preview(self):
        if self.preview_data is None:
            messagebox.showinfo("Náhled", "Nejprve něco nahrajte.")
            return
        if self.is_playing:
            self.info_label.config(text="Přehrávání už běží…")
            return
        try:
            # Bezpečné přehrávání přes simpleaudio (pokud dostupné), jinak pydub.playback
            if self.preview_data is None or (hasattr(self.preview_data, 'size') and self.preview_data.size == 0):
                messagebox.showinfo("Náhled", "Žádná data k přehrání.")
                return
            # Připrav segment
            seg = self.preview_segment or self._numpy_to_segment(self.preview_data)
            vol = self.volume_var.get()
            if vol == 0:
                seg_adj = seg - 120
            else:
                gain_db = 20.0 * (np.log10(vol/100.0)) if np is not None else 0.0
                seg_adj = seg + gain_db

            def _play_with_simpleaudio():
                try:
                    raw = seg_adj.raw_data
                    channels = seg_adj.channels
                    sampwidth = seg_adj.sample_width
                    fr = seg_adj.frame_rate
                    play_obj = sa.play_buffer(raw, channels, sampwidth, fr)
                    self._playback_obj = play_obj
                    self.is_playing = True
                    try:
                        self.btn_preview.state(["disabled"])
                    except Exception:
                        pass
                    _log("Preview (simpleaudio) started")
                    play_obj.wait_done()
                except Exception as e:
                    _log(f"simpleaudio playback error: {e}")
                finally:
                    self._playback_obj = None
                    self.is_playing = False
                    try:
                        # znovu povolit všechna ovládací tlačítka a volby
                        self.btn_preview.state(["!disabled"])
                        self.btn_rec.state(["!disabled"])
                        self.btn_clear.state(["!disabled"])
                        self.btn_export.state(["!disabled"])
                        try:
                            self.radio_sys.config(state='normal')
                            self.radio_stops.config(state='normal')
                            self.filename_combo.config(state='readonly')
                        except Exception:
                            pass
                    except Exception:
                        pass

            def _play_with_pydub():
                try:
                    from pydub.playback import play
                    self.is_playing = True
                    try:
                        self.btn_preview.state(["disabled"])
                    except Exception:
                        pass
                    _log("Preview (pydub) started")
                    play(seg_adj)
                except Exception as e:
                    _log(f"pydub playback error: {e}")
                finally:
                    self.is_playing = False
                    try:
                        self.btn_preview.state(["!disabled"])
                        self.btn_rec.state(["!disabled"])
                        self.btn_clear.state(["!disabled"])
                        self.btn_export.state(["!disabled"])
                        try:
                            self.radio_sys.config(state='normal')
                            self.radio_stops.config(state='normal')
                            self.filename_combo.config(state='readonly')
                        except Exception:
                            pass
                    except Exception:
                        pass

            # lock controls during playback
            try:
                self.radio_sys.config(state='disabled')
                self.radio_stops.config(state='disabled')
                self.filename_combo.config(state='disabled')
            except Exception:
                pass

            if sa is not None:
                self.play_thread = threading.Thread(target=_play_with_simpleaudio, daemon=True)
            else:
                self.play_thread = threading.Thread(target=_play_with_pydub, daemon=True)
            self.play_thread.start()
            self.info_label.config(text="Přehrávám náhled…")
        except Exception as e:
            _log(f"Preview error: {e}")
            messagebox.showerror("Náhled", f"Chyba náhledu:\n{e}")

    @safe_action
    def on_clear_preview(self):
        self.preview_data = None
        self.preview_segment = None
        self.info_label.config(text="Náhled smazán. Připraveno.")
        # Smazat waveform
        try:
            self.waveform_canvas.delete("all")
        except Exception:
            pass
        # Po smazání náhledu povolit ovládací prvky
        try:
            self.btn_rec.state(["!disabled"])
            self.btn_preview.state(["!disabled"])
            self.btn_clear.state(["!disabled"])
            self.btn_export.state(["!disabled"])
            try:
                self.radio_sys.config(state='normal')
                self.radio_stops.config(state='normal')
                self.filename_combo.config(state='readonly')
            except Exception:
                pass
        except Exception:
            pass

    @safe_action
    def on_export(self):
        if self.preview_data is None:
            messagebox.showinfo("Export", "Nejprve něco nahrajte a případně si to pusťte v náhledu.")
            return
        name = self.filename_var.get().strip()
        if not name:
            messagebox.showwarning("Zastávka", "Vyberte zastávku / název souboru")
            return
        category = self.category_var.get()
        if category == "sys":
            out_dir = SYS_AUDIO_DIR
        else:
            out_dir = STOPS_AUDIO_DIR
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{name}.mp3")
        # Kontrola existence souboru
        if os.path.exists(out_path):
            if not messagebox.askyesno("Soubor existuje", f"Soubor {name}.mp3 už existuje. Chcete ho přepsat?"):
                self.info_label.config(text="Export zrušen – soubor existuje.")
                return
        try:
            seg = self.preview_segment or self._numpy_to_segment(self.preview_data)
            # hlasitost (0 % = úplné ztišení)
            vol = self.volume_var.get()
            if vol == 0:
                seg_adj = seg - 120
            else:
                gain_db = 20.0 * (np.log10(vol/100.0)) if np is not None else 0.0
                seg_adj = seg + gain_db
            # export do MP3
            if AudioSegment is None:
                raise RuntimeError("Chybí pydub, pro export MP3 nainstalujte: pip install pydub a mějte ffmpeg v PATH")
            seg_adj.export(out_path, format="mp3")
            self.info_label.config(text=f"Exportováno: {out_path}")
            messagebox.showinfo("Export", f"Uloženo do:\n{out_path}")
            # Po exportu zajistit, že UI je odemčeno
            try:
                self.btn_rec.state(["!disabled"])
                self.btn_preview.state(["!disabled"])
                self.btn_clear.state(["!disabled"])
                self.btn_export.state(["!disabled"])
                try:
                    self.radio_sys.config(state='normal')
                    self.radio_stops.config(state='normal')
                    self.filename_combo.config(state='readonly')
                except Exception:
                    pass
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Export", f"Export se nezdařil:\n{e}")
            try:
                # i při chybě se snažíme UI odemknout
                self.btn_rec.state(["!disabled"])
                self.btn_preview.state(["!disabled"])
                self.btn_clear.state(["!disabled"])
                self.btn_export.state(["!disabled"])
                try:
                    self.radio_sys.config(state='normal')
                    self.radio_stops.config(state='normal')
                    self.filename_combo.config(state='readonly')
                except Exception:
                    pass
            except Exception:
                pass

    def _load_stop_names(self):
        # Načti unikátní audio klíče ze všech JSON v adresáři lines
        names = set()
        try:
            for fname in os.listdir(LINES_DIR):
                if not fname.lower().endswith(".json"):
                    continue
                fpath = os.path.join(LINES_DIR, fname)
                try:
                    import json
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for stop in data.get("stops", []):
                        a = stop.get("audio")
                        if isinstance(a, str):
                            a = a.strip()
                            if a:
                                names.add(a)
                except Exception:
                    # ignoruj nevalidní JSON
                    continue
        except Exception:
            names = set()
        sorted_names = sorted(names, key=lambda x: x.lower())
        # naplnit combobox
        try:
            self.filename_combo["values"] = sorted_names
            if sorted_names and not self.filename_var.get():
                self.filename_var.set(sorted_names[0])
        except Exception:
            pass

    def _on_filename_selected(self):
        # Bezpečný handler pro změnu výběru v comboboxu
        try:
            name = self.filename_var.get().strip()
            if name:
                self.info_label.config(text=f"Vybráno: {name}")
            else:
                self.info_label.config(text="Vyberte zastávku")
        except Exception:
            # Neprovádět žádné akce, jen ignorovat chybu
            pass

    def _on_threshold_change(self, v):
        try:
            val = int(float(v))
        except Exception:
            val = self.silence_threshold_var.get()
        val = max(0, min(20, val))
        self.silence_threshold_var.set(val)
        self.thr_label.config(text=f"{val} %")

    def _draw_waveform(self):
        # Jednoduché vykreslení waveformu na Canvas
        if self.preview_data is None or np is None:
            return
        w = int(self.waveform_canvas.cget("width"))
        h = int(self.waveform_canvas.cget("height"))
        self.waveform_canvas.delete("all")
        self.waveform_canvas.create_line(0, h//2, w, h//2, fill="#ddd")
        data = self.preview_data
        # Vizuální zesílení dle hlasitosti slideru (lineární faktor)
        vis_gain = max(0.0, float(self.volume_var.get()) / 100.0)
        # downsample pro rychlé vykreslení
        samples = data.shape[0]
        if samples <= 0:
            return
        step = max(1, samples // w)
        # vytvoř páry (x, y)
        points = []
        for i in range(0, samples, step):
            x = i // step
            # podpora víc kanálů => vezmi první kanál
            sample = float(data[i]) if data.ndim == 1 else float(data[i, 0])
            sample *= vis_gain
            y = h//2 - int(sample * (h//2 - 4))
            points.append((x, y))
        # nakresli polyline
        for i in range(1, len(points)):
            x1, y1 = points[i-1]
            x2, y2 = points[i]
            self.waveform_canvas.create_line(x1, y1, x2, y2, fill="#2c7be5")
        # Playhead
        if self.play_duration_ms > 0 and self.is_playing:
            pos_px = min(w-1, int((self.play_pos_ms / self.play_duration_ms) * w))
            self.waveform_canvas.create_line(pos_px, 0, pos_px, h, fill="#e83e8c")
        # Časový text
        total_sec = samples / self.recorder.samplerate
        cur_sec = (self.play_pos_ms/1000.0) if self.is_playing else total_sec
        def fmt(s):
            m = int(s//60)
            ss = int(s%60)
            return f"{m:02d}:{ss:02d}"
        self.time_label.config(text=f"{fmt(cur_sec)} / {fmt(total_sec)}")

    def _update_playhead(self):
        # aktualizace playheadu podle stream pozice
        if not self.is_playing:
            # ukončení: dočistit tlačítko a stream
            try:
                self.btn_preview.state(["!disabled"])  # znovu povolit
            except Exception:
                pass
            try:
                preview_len = self.preview_data.shape[0] if self.preview_data is not None else 0
            except Exception:
                preview_len = 0
            if self._play_stream is not None and self._play_index >= preview_len:
                try:
                    self._shutting_down_playback = True
                    self._play_stream.stop()
                    import time as _t
                    _t.sleep(0.05)
                    self._play_stream.close()
                except Exception:
                    pass
                self._play_stream = None
                self._shutting_down_playback = False
            return
        # Pokud právě vypínáme playback, neredrawuj (stabilita)
        if not self._shutting_down_playback:
            try:
                self._draw_waveform()
            except Exception as e:
                _log(f"Draw waveform error: {e}")
        if self.play_pos_ms < self.play_duration_ms:
            self.after(50, self._update_playhead)
        else:
            # konec přehrávání
            self.is_playing = False
            try:
                self.btn_preview.state(["!disabled"])  # znovu povolit
            except Exception:
                pass
            if self._play_stream is not None:
                try:
                    self._shutting_down_playback = True
                    self._play_stream.stop()
                    import time as _t
                    _t.sleep(0.05)
                    self._play_stream.close()
                except Exception:
                    pass
                self._play_stream = None
                self._shutting_down_playback = False

    @safe_action
    def on_trim_silence(self):
        # Ořízne ticho z počátku a konce podle prahu
        if self.preview_data is None or np is None:
            messagebox.showinfo("Ořez ticha", "Nejprve něco nahrajte.")
            return
        try:
            # Bezpečně ukonči přehrávání před ořezem
            if self.is_playing or self._play_stream is not None:
                try:
                    if self._play_stream is not None:
                        try:
                            self._play_stream.stop()
                        except Exception:
                            pass
                        try:
                            self._play_stream.close()
                        except Exception:
                            pass
                        self._play_stream = None
                    self.is_playing = False
                    self.play_pos_ms = 0
                except Exception:
                    pass

            data = self.preview_data
            thr_pct = self.silence_threshold_var.get() / 100.0
            # Ošetři NaN/Inf a prázdná data
            try:
                max_amp = float(np.max(np.abs(data)))
            except Exception:
                max_amp = 0.0
            if not np.isfinite(max_amp):
                max_amp = 0.0
            max_amp = max(1e-6, max_amp)
            threshold = thr_pct * max_amp
            # najdi první index > threshold
            idx_start = 0
            try:
                while idx_start < len(data) and abs(float(data[idx_start] if data.ndim == 1 else data[idx_start, 0])) <= threshold:
                    idx_start += 1
            except Exception:
                idx_start = 0
            # najdi poslední index > threshold
            idx_end = len(data) - 1
            try:
                while idx_end > idx_start and abs(float(data[idx_end] if data.ndim == 1 else data[idx_end, 0])) <= threshold:
                    idx_end -= 1
            except Exception:
                idx_end = len(data) - 1
            if idx_end <= idx_start:
                messagebox.showinfo("Ořez ticha", "Celá nahrávka je tichá podle zvoleného prahu.")
                return
            trimmed = data[idx_start:idx_end+1]
            if trimmed is None or (hasattr(trimmed, 'size') and trimmed.size == 0):
                messagebox.showinfo("Ořez ticha", "Po ořezu nezbyla žádná nahrávka.")
                return
            self.preview_data = trimmed
            self.preview_segment = None  # re-generovat při dalším přehrání/exportu
            self.info_label.config(text=f"Oříznuto ticho. Nová délka: {len(trimmed)/self.recorder.samplerate:.2f} s")
            self._draw_waveform()
        except Exception as e:
            messagebox.showerror("Ořez ticha", f"Nepodařilo se oříznout ticho:\n{e}")

    def _schedule_recording_update(self):
        # periodicky překreslí waveform podle aktuálně nahraných dat
        try:
            if self._recording_timer is not None:
                self.after_cancel(self._recording_timer)
        except Exception:
            pass
        def _tick():
            if self.recorder._recording and self.recorder._frames:
                try:
                    # sloučit jen poslední část pro výkon
                    last = self.recorder._frames[-1]
                    if isinstance(last, np.ndarray):
                        # ukázat celková data pro lepší kontext
                        try:
                            data = np.concatenate(self.recorder._frames, axis=0)
                            self.preview_data = data
                            self.preview_segment = None
                        except Exception:
                            pass
                    self._draw_waveform()
                except Exception:
                    pass
            if self.recorder._recording:
                self._recording_timer = self.after(100, _tick)
            else:
                self._recording_timer = None
        self._recording_timer = self.after(100, _tick)

if __name__ == "__main__":
    app = RecordWindow()
    app.mainloop()
