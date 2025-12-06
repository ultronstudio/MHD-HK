import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LINES_DIR = os.path.join(BASE_DIR, "lines")

APP_TITLE = "MHD HK – Bus Simulator"
APP_VERSION = "1.1.0"
APP_AUTHOR = "Petr Vurm"

def load_lines():
    lines = []
    if not os.path.isdir(LINES_DIR):
        return lines

    for filename in os.listdir(LINES_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(LINES_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            line_id = data.get("id") or os.path.splitext(filename)[0]
            desc = data.get("description", "")
            lines.append({
                "id": line_id,
                "description": desc,
                "file": path,
            })
        except Exception as e:
            print(f"Nepodařilo se načíst {filename}: {e}")
    return sorted(lines, key=lambda x: x["id"])


def run_simulator(line_id: str, direction: str):
    """Spustí hlavní simulátor jako nový proces.

    direction: "tam" nebo "zpet" – zatím se nepředává do Pygame okna,
    ale je připravené pro budoucí rozšíření (např. přes argv).
    """
    python_exe = sys.executable or "python"
    cmd = [python_exe, os.path.join(BASE_DIR, "main.py"), line_id, direction]

    try:
        subprocess.Popen(cmd, cwd=BASE_DIR)
    except Exception as e:
        messagebox.showerror("Chyba", f"Simulátor se nepodařilo spustit:\n{e}")


class StartWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(False, False)

        self.lines = load_lines()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_ui()
        # nastav výchozí text směrů dle vybrané linky
        self.update_direction_labels()

    def _build_ui(self):
        # trochu větší okno, aby se vešel celý text linek
        main = ttk.Frame(self, padding=(20, 15, 20, 15))
        main.grid(row=0, column=0, sticky="nsew")

        # Výběr linky
        ttk.Label(main, text="Linka:").grid(row=0, column=0, sticky="w")

        self.line_var = tk.StringVar()
        line_names = [f" {l['id']} | {l['description']}" for l in self.lines] or ["Žádné linky nenalezeny"]
        # širší combobox, aby byl vidět celý text položky
        self.line_combo = ttk.Combobox(main, textvariable=self.line_var, values=line_names, state="readonly", width=55)
        if self.lines:
            self.line_combo.current(0)
        self.line_combo.grid(row=0, column=1, padx=(5, 0), sticky="w")
        # při změně výběru linky aktualizuj text směrů
        self.line_combo.bind("<<ComboboxSelected>>", lambda e: self.update_direction_labels())

        # Směr
        ttk.Label(main, text="Směr:").grid(row=1, column=0, pady=(10, 0), sticky="w")

        self.direction_var = tk.StringVar(value="tam")
        dir_frame = ttk.Frame(main)
        dir_frame.grid(row=1, column=1, padx=(5, 0), pady=(10, 0), sticky="w")

        self.rb_tam = ttk.Radiobutton(dir_frame, text="Směr TAM", variable=self.direction_var, value="tam")
        self.rb_tam.grid(row=0, column=0, sticky="w")
        self.rb_zpet = ttk.Radiobutton(dir_frame, text="Směr ZPĚT", variable=self.direction_var, value="zpet")
        self.rb_zpet.grid(row=1, column=0, sticky="w")

        # Tlačítka
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(15, 0), sticky="e")

        about_btn = ttk.Button(btn_frame, text="O aplikaci", command=self.show_about)
        about_btn.grid(row=0, column=0, padx=(0, 5))

        start_btn = ttk.Button(btn_frame, text="Spustit", command=self.on_start)
        start_btn.grid(row=0, column=1)

    def on_start(self):
        if not self.lines:
            messagebox.showwarning("Žádné linky", "Nebyl nalezen žádný soubor s definicí linky v adresáři 'lines'.")
            return

        idx = self.line_combo.current()
        if idx < 0 or idx >= len(self.lines):
            messagebox.showwarning("Výběr", "Vyberte prosím linku.")
            return

        line = self.lines[idx]
        direction = self.direction_var.get()

        # schovej okno startéru a spusť simulátor blokujícím způsobem
        self.withdraw()
        python_exe = sys.executable or "python"
        cmd = [python_exe, os.path.join(BASE_DIR, "main.py"), line["id"], direction]

        try:
            subprocess.run(cmd, cwd=BASE_DIR)
        except Exception as e:
            messagebox.showerror("Chyba", f"Simulátor se nepodařilo spustit:\n{e}")
        finally:
            # po ukončení simulátoru znovu ukaž start okno
            self.deiconify()

    def update_direction_labels(self):
        """Aktualizuje text radiobuttonů Směr TAM/ZPĚT podle vybrané linky.
        Očekává popis ve formátu "A > B" v JSON "description".
        Pokud formát není k dispozici, ponechá obecné popisky.
        """
        if not self.lines:
            return
        idx = self.line_combo.current()
        if idx < 0 or idx >= len(self.lines):
            return
        desc = self.lines[idx].get("description", "")
        # pokus o rozdělení na A (výchozí) a B (cílová)
        parts = [p.strip() for p in desc.split('>')]
        if len(parts) == 2:
            start_name, end_name = parts
            self.rb_tam.config(text=f"Směr TAM ({end_name})")
            self.rb_zpet.config(text=f"Směr ZPĚT ({start_name})")
        else:
            # fallback – bez detailu
            self.rb_tam.config(text="Směr TAM")
            self.rb_zpet.config(text="Směr ZPĚT")

    def show_about(self):
        text = (
            f"{APP_TITLE}\n"
            f"Verze: {APP_VERSION}\n\n"
            "Autor: Petr Vurm (ultronstudio)\n"
            "Projekt: MHD-HK – simulátor informačního panelu MHD v Hradci Králové.\n\n"
            "Zdrojový kód je licencován pod MIT licencí (viz LICENSE). "
            "Hlasové nahrávky v adresáři 'audio/' nejsou volně licencovány a jejich použití "
            "mimo tento repozitář bez výslovného souhlasu autora je zakázáno."
        )
        messagebox.showinfo("O aplikaci", text)

    def on_close(self):
        self.destroy()

if __name__ == "__main__":
    app = StartWindow()
    app.mainloop()
