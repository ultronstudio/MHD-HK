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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
SYS_AUDIO_DIR = os.path.join(AUDIO_DIR, "sys")
STOPS_AUDIO_DIR = os.path.join(AUDIO_DIR, "stops")

APP_TITLE = "MHD HK – Recorder"

class Recorder:
    def __init__(self, samplerate=44100, channels=1):
        self.samplerate = samplerate
        self.channels = channels
        self._recording = False
        self._frames = []
        self._stream = None

    def start(self):
        if sd is None or np is None:
            raise RuntimeError("Chybí knihovna sounddevice nebo numpy. Nainstalujte je: pip install sounddevice numpy")
        self._frames = []
        self._recording = True
        self._stream = sd.InputStream(samplerate=self.samplerate, channels=self.channels, callback=self._callback)
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

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=(20, 15, 20, 15))
        main.grid(row=0, column=0, sticky="nsew")

        # Kategorie
        ttk.Label(main, text="Kategorie:").grid(row=0, column=0, sticky="w")
        cat_frame = ttk.Frame(main)
        cat_frame.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(cat_frame, text="System (sys)", variable=self.category_var, value="sys").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(cat_frame, text="Zastávky (stops)", variable=self.category_var, value="stops").grid(row=0, column=1, sticky="w")

        # Název souboru
        ttk.Label(main, text="Název souboru:").grid(row=1, column=0, pady=(10, 0), sticky="w")
        entry = ttk.Entry(main, textvariable=self.filename_var, width=40)
        entry.grid(row=1, column=1, pady=(10, 0), sticky="w")
        ttk.Label(main, text="(bez .mp3)").grid(row=1, column=2, pady=(10, 0), sticky="w")

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

    def on_record(self):
        if sd is None:
            messagebox.showerror("Chybí závislosti", "Knihovna sounddevice není dostupná. Nainstalujte: pip install sounddevice")
            return
        try:
            self.info_label.config(text="Nahrávám…")
            self.recorder.start()
            # živý update vizuálu při nahrávání
            self._schedule_recording_update()
        except Exception as e:
            messagebox.showerror("Nahrávání", f"Nelze zahájit nahrávání:\n{e}")

    def on_stop(self):
        try:
            # zastavit případné přehrávání
            if self._play_stream is not None:
                try:
                    self._play_stream.stop()
                    self._play_stream.close()
                except Exception:
                    pass
                self._play_stream = None
                self.is_playing = False
                self.play_pos_ms = 0
                self._draw_waveform()
            data = self.recorder.stop()
            if data is None:
                self.info_label.config(text="Bez dat – zkuste znovu.")
                return
            self.preview_data = data  # numpy float32 [-1,1]
            self.preview_segment = None
            self.info_label.config(text=f"Nahrávka připravena. Délka: {len(data)/self.recorder.samplerate:.2f} s")
            self._draw_waveform()
            # zrušit live update při nahrávání
            if self._recording_timer is not None:
                try:
                    self.after_cancel(self._recording_timer)
                except Exception:
                    pass
                self._recording_timer = None
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

    def on_preview(self):
        if self.preview_data is None:
            messagebox.showinfo("Náhled", "Nejprve něco nahrajte.")
            return
        if self.is_playing:
            self.info_label.config(text="Přehrávání už běží…")
            return
        try:
            # Přehrávání přes sounddevice pro možnost živé změny hlasitosti a zastavení
            if sd is None:
                messagebox.showerror("Náhled", "Chybí sounddevice pro přehrávání.")
                return
            data = self.preview_data
            self._play_index = 0
            frames_total = data.shape[0]
            self.play_duration_ms = int((frames_total / self.recorder.samplerate) * 1000)
            self.play_pos_ms = 0
            import time as _time
            self._play_start_monotonic = _time.monotonic()

            def _out_callback(outdata, frames, time, status):
                if status:
                    pass
                start = self._play_index
                end = min(start + frames, frames_total)
                # zkopírovat data a aplikovat aktuální hlasitost
                chunk = data[start:end]
                # zajistit tvar (frames, channels)
                if self.recorder.channels == 1 and chunk.ndim == 1:
                    chunk = chunk.reshape(-1, 1)
                # hlasitost
                vol = self.volume_var.get()
                if vol == 0:
                    outdata[:end-start, :] = 0
                else:
                    gain = float(vol) / 100.0
                    out = chunk * gain
                    # ořez na [-1,1]
                    out = np.clip(out, -1.0, 1.0)
                    outdata[:end-start, :] = out
                # doplnit zbytek nulami, pokud jsme na konci
                if end - start < frames:
                    outdata[end-start:, :] = 0
                self._play_index = end
                # update pozice pro playhead
                self.play_pos_ms = int((self._play_index / self.recorder.samplerate) * 1000)

            self._play_stream = sd.OutputStream(
                samplerate=self.recorder.samplerate,
                channels=self.recorder.channels,
                callback=_out_callback,
                dtype='float32'
            )
            self._play_stream.start()
            self.is_playing = True
            self.btn_preview.state(["disabled"])  # během přehrávání
            self._update_playhead()
            self.info_label.config(text="Přehrávám náhled…")
        except Exception as e:
            messagebox.showerror("Náhled", f"Chyba náhledu:\n{e}")

    def on_clear_preview(self):
        self.preview_data = None
        self.preview_segment = None
        self.info_label.config(text="Náhled smazán. Připraveno.")
        # Smazat waveform
        try:
            self.waveform_canvas.delete("all")
        except Exception:
            pass

    def on_export(self):
        if self.preview_data is None:
            messagebox.showinfo("Export", "Nejprve něco nahrajte a případně si to pusťte v náhledu.")
            return
        name = self.filename_var.get().strip()
        if not name:
            messagebox.showwarning("Název souboru", "Zadejte název souboru (bez .mp3)")
            return
        category = self.category_var.get()
        if category == "sys":
            out_dir = SYS_AUDIO_DIR
        else:
            out_dir = STOPS_AUDIO_DIR
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{name}.mp3")
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
        except Exception as e:
            messagebox.showerror("Export", f"Export se nezdařil:\n{e}")

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
            if self._play_stream is not None and self._play_index >= self.preview_data.shape[0]:
                try:
                    self._play_stream.stop()
                    self._play_stream.close()
                except Exception:
                    pass
                self._play_stream = None
            return
        self._draw_waveform()
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
                    self._play_stream.stop()
                    self._play_stream.close()
                except Exception:
                    pass
                self._play_stream = None

    def on_trim_silence(self):
        # Ořízne ticho z počátku a konce podle prahu
        if self.preview_data is None or np is None:
            messagebox.showinfo("Ořez ticha", "Nejprve něco nahrajte.")
            return
        try:
            data = self.preview_data
            thr_pct = self.silence_threshold_var.get() / 100.0
            max_amp = max(1e-6, float(np.max(np.abs(data))))
            threshold = thr_pct * max_amp
            # najdi první index > threshold
            idx_start = 0
            while idx_start < len(data) and abs(data[idx_start]) <= threshold:
                idx_start += 1
            # najdi poslední index > threshold
            idx_end = len(data) - 1
            while idx_end > idx_start and abs(data[idx_end]) <= threshold:
                idx_end -= 1
            if idx_end <= idx_start:
                messagebox.showinfo("Ořez ticha", "Celá nahrávka je tichá podle zvoleného prahu.")
                return
            trimmed = data[idx_start:idx_end+1]
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
