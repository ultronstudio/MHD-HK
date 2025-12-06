import json
import os
import sys
import time
import datetime
import pygame
import tkinter as tk
from tkinter import messagebox

# --- KONFIGURACE BAREV A ROZMĚRŮ ---
W, H = 1280, 720
BG_COLOR = (255, 255, 255)      # Bílé pozadí
HEADER_LINE_COLOR = (200, 0, 0) # Červená linka nahoře
TIME_BG_COLOR = (220, 20, 20)   # Červený box pro čas
YELLOW_BAR_COLOR = (240, 210, 0)# Žlutý pruh dole
TEXT_BLACK = (0, 0, 0)
TEXT_WHITE = (255, 255, 255)
ROUTE_RED = (200, 0, 0)         # Červená barva trasy

# --- SEMAFOR BARVY ---
# --- CESTY K SOUBORŮM ---
AUDIO_DIR = "audio"
SYS_AUDIO_DIR = os.path.join(AUDIO_DIR, "sys")
STOPS_AUDIO_DIR = os.path.join(AUDIO_DIR, "stops")

# --- SIMULACE PODLE ČASU ---
# Nepočítáme vzdálenost a rychlost, ale jedeme podle
# jízdní doby mezi zastávkami (v minutách v JSON souborech).

DOOR_TIME = 8.0           # doba otevřených dveří (s)
LAYOVER_TIME = 10.0       # pauza na konečné (s)
TIME_SCALE = 8.0          # 1 reálná sekunda = 8 s simulovaného času

# jak dlouho před příjezdem se má hlásit
NEXT_STOP_ANNOUNCE_BEFORE_SEC = 60.0    # "příští zastávka"
CURRENT_STOP_ANNOUNCE_BEFORE_SEC = 10.0 # aktuální zastávka

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LINES_DIR = os.path.join(BASE_DIR, "lines")


def load_line_definition(line_id: str):
    """Načte definici linky z JSON souboru v adresáři 'lines'."""
    filename = f"{line_id}.json"
    path = os.path.join(LINES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    stops_raw = data.get("stops", [])
    trasa_segmenty = []
    for s in stops_raw:
        # distance nyní znamená čas příjezdu od začátku trasy v minutách
        trasa_segmenty.append((s.get("name", ""), s.get("distance", 0), s.get("audio", "")))
    return data, trasa_segmenty

class BusSimulatorSimpleLine:
    def __init__(self, line_id: str = "2", direction: str = "tam"):
        print("--- INICIALIZACE SIMULÁTORU ---")
        pygame.init()
        try: 
            pygame.mixer.init()
            pygame.mixer.set_num_channels(8)
            print("🔊 Zvukový systém: OK")
        except: 
            print("❌ Zvukový systém: CHYBA (Audio nebude hrát)")

        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        
        # --- FONTY ---
        self.font_line = pygame.font.SysFont('Arial', 70, bold=True)
        self.font_dest = pygame.font.SysFont('Arial', 65, bold=True)
        self.font_time = pygame.font.SysFont('Arial', 60, bold=True)
        self.font_stop_list = pygame.font.SysFont('Arial', 50, bold=True) 
        self.font_footer = pygame.font.SysFont('Arial', 55, bold=True)
        self.font_dp = pygame.font.SysFont('Times New Roman', 50, bold=True, italic=True)

        self.stops = []
        self.smer_tam = (direction == "tam")
        self.line_id = line_id

        # Načtení definice linky z JSON
        try:
            line_data, self.trasa_segmenty = load_line_definition(line_id)
            desc = line_data.get("description", "")
            self.desc = desc
            # cílová stanice = poslední zastávka v aktuálním směru
            if self.trasa_segmenty:
                if self.smer_tam:
                    self.dest_name = self.trasa_segmenty[-1][0].upper()
                else:
                    self.dest_name = self.trasa_segmenty[0][0].upper()
            else:
                self.dest_name = ""  # fallback, přepíše se v prebuild_route

            dir_text = "TAM" if self.smer_tam else "ZPĚT"
            caption = f"{line_id} | {desc} (směr: {dir_text})" if desc else f"Linka {line_id} (směr: {dir_text})"
        except Exception as e:
            print(f"Chyba při načítání definice linky {line_id}: {e}")
            self.trasa_segmenty = []
            self.dest_name = ""
            self.desc = ""
            caption = "MHD HK - Bus Simulator"

        pygame.display.set_caption(caption)

        self.prebuild_route()

        # Stav vozu
        # bus_abs_pos = čas od začátku směru v sekundách simulovaného času
        self.bus_abs_pos = 0.0
        self.speed = 0.0  # ponecháno jen pro debug, fakticky se nepoužívá
        self.stop_index = 0     
        self.gui_stop_index = 0 
        
        # Stavy: DRIVING, BRAKING, STOPPED, DOORS_OPEN, DOORS_CLOSED, LAYOVER
        # Výchozí: zastávka s dveřmi zavřenými, ihned přejdeme na otevření dveří se zvukem
        # aby byl slyšet startovní nástup.
        self.state = "STOPPED" 
        self.timer = 0.0
        # Ihned po startu přejdi do DOORS_OPEN (otevření se zvukem)
        self.current_wait_limit = 0.0
        self.debug_timer = 0.0 
        
        # Audio fronta
        self.audio_queue_timer = 0.0
        self.audio_to_play = None
        self.audio_playlist = [] 
        
        # Hlášení
        self.next_stop_announced = False 
        self.current_stop_announced = False 
        self.leg_start_pos = 0.0
        # Úvodní sekvence na první zastávce: zavřeno -> otevřít (se zvukem) -> zavřít (se zvukem) -> rozjezd
        self.startup_sequence_done = False

    def prebuild_route(self):
        self.stops = []
        current_dist = 0.0
        
        if self.smer_tam:
            zdroj = self.trasa_segmenty
        else:
            zdroj = self.trasa_segmenty[::-1]

        if self.smer_tam:
            for name, minute_mark, fname in zdroj:
                current_dist = minute_mark * 60.0
                self.stops.append({"nazev": name, "dist": current_dist, "file": fname})
        else:
            # pro směr zpět použij časovou osu obráceně
            times = [x[1] * 60.0 for x in zdroj]
            names = [x[0] for x in zdroj]
            files = [x[2] for x in zdroj]
            total_time = times[-1] if times else 0.0
            for name, t, fname in zip(names, times, files):
                self.stops.append({"nazev": name, "dist": total_time - t, "file": fname})

    def play_sound(self, category, filename):
        if not pygame.mixer.get_init(): return 0.0
        base_path = SYS_AUDIO_DIR if category == 'sys' else STOPS_AUDIO_DIR
        path_mp3 = os.path.join(base_path, f"{filename}.mp3")
        path_wav = os.path.join(base_path, f"{filename}.wav")
        target_path = path_mp3 if os.path.exists(path_mp3) else (path_wav if os.path.exists(path_wav) else None)
        
        if target_path:
            try:
                sound = pygame.mixer.Sound(target_path)
                length = sound.get_length()
                sound.play()
                return length
            except: return 0.0
        return 0.0

    def check_current_stop_announcement(self, time_to_go):
        if not self.current_stop_announced and time_to_go <= CURRENT_STOP_ANNOUNCE_BEFORE_SEC:
            self.current_stop_announced = True
            self.gui_stop_index = self.stop_index
            print(f"📢 [INFO] 25m do cíle -> Hlásím aktuální zastávku.")
            self.audio_playlist.append(('sys', 'gong'))
            self.audio_playlist.append(('stops', self.stops[self.stop_index]['file']))
            if self.stop_index == len(self.stops) - 1:
                self.audio_playlist.append(('sys', 'konecna'))

    def update_physics(self, dt):
        # Audio fronta
        if self.audio_queue_timer > 0: self.audio_queue_timer -= dt
        if self.audio_queue_timer <= 0 and self.audio_playlist:
            cat, file = self.audio_playlist.pop(0)
            duration = self.play_sound(cat, file)
            self.audio_queue_timer = duration + 0.2

        if self.stop_index >= len(self.stops):
            if self.state != "LAYOVER": self.state = "LAYOVER"
            return

        target_time = self.stops[self.stop_index]["dist"]  # v sekundách
        time_to_go = target_time - self.bus_abs_pos

        # --- LOGIKA JÍZDY PODLE ČASU ---

        if self.state == "DRIVING":
            sim_dt = dt * TIME_SCALE

            leg_total_time = target_time - self.leg_start_pos
            time_traveled = self.bus_abs_pos - self.leg_start_pos

            # Hlášení příští zastávky: spouštět dříve (v polovině úseku),
            # aby se nehlásilo těsně před příjezdem.
            if not self.next_stop_announced and leg_total_time > 0:
                # spustíme hlášení, jakmile projedeme polovinu času úseku
                if time_traveled >= (leg_total_time * 0.5):
                    self.next_stop_announced = True
                    self.gui_stop_index = self.stop_index
                    self.audio_playlist.append(('sys', 'gong'))
                    self.audio_playlist.append(('sys', 'pristi_zastavka'))
                    self.audio_playlist.append(('stops', self.stops[self.stop_index]['file']))
                    print(f"📢 [INFO] Průjezd poloviny úseku ({time_traveled:.1f}/{leg_total_time:.1f}s) - hlásím příští zastávku.")

            self.check_current_stop_announcement(time_to_go)

            self.bus_abs_pos += sim_dt

            if self.bus_abs_pos >= target_time:
                self.bus_abs_pos = target_time
                self.state = "STOPPED"
                self.timer = 0
                self.current_wait_limit = 1.0

        # --- STANDARDNÍ STAVY ZASTÁVKY ---
        elif self.state == "BRAKING":
            # v časové verzi slouží jako rychlý dojezd
            sim_dt = dt * TIME_SCALE
            self.bus_abs_pos += sim_dt
            if self.bus_abs_pos >= target_time:
                self.bus_abs_pos = target_time
                self.state = "STOPPED"
                self.timer = 0
                self.current_wait_limit = 1.0

        elif self.state == "STOPPED":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                self.state = "DOORS_OPEN"
                self.timer = 0
                # otevření dveří se zvukem, čas stejně jako zavření
                audio_len = self.play_sound('sys', 'bus_door')
                self.current_wait_limit = audio_len + 2.0

        elif self.state == "DOORS_OPEN":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                # běžné chování: zavřít dveře a připravit čas na zavření
                self.state = "DOORS_CLOSED"
                self.timer = 0
                audio_len = self.play_sound('sys', 'buzzer')
                self.current_wait_limit = audio_len + 2.0

        elif self.state == "DOORS_CLOSED":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                # Pokud jsme na konečné, otočit jízdní řád po zavření dveří,
                # připravit trasu pro opačný směr a POTÉ otevřít dveře pro nástup.
                if self.stop_index == len(self.stops) - 1:
                    try:
                        # přepnout směr a připravit novou trasu
                        self.smer_tam = not self.smer_tam
                        self.prebuild_route()
                        self.bus_abs_pos = 0.0
                        self.stop_index = 0
                        self.gui_stop_index = 0
                        # aktualizuj titulek a cílovou stanici
                        try:
                            if self.trasa_segmenty:
                                if self.smer_tam:
                                    self.dest_name = self.trasa_segmenty[-1][0].upper()
                                else:
                                    self.dest_name = self.trasa_segmenty[0][0].upper()
                            dir_text = "TAM" if self.smer_tam else "ZPĚT"
                            caption = f"{self.line_id} | {getattr(self, 'desc', '')} (směr: {dir_text})" if getattr(self, 'desc', '') else f"Linka {self.line_id} (směr: {dir_text})"
                            try:
                                pygame.display.set_caption(caption)
                            except Exception:
                                pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # Otevřít dveře pro nástup v novém směru
                    audio_len = self.play_sound('sys', 'bus_door')
                    self.current_wait_limit = audio_len + 2.0
                    self.timer = 0
                    self.state = "DOORS_OPEN"
                else:
                    # pokračovat na další zastávku
                    self.stop_index += 1
                    self.state = "DRIVING"
                    self.next_stop_announced = False
                    self.current_stop_announced = False
                    self.leg_start_pos = self.bus_abs_pos
                    self.timer = 0

    def get_time_string(self):
        now = datetime.datetime.now()
        colon = ":" if (time.time() % 1) > 0.5 else " "
        return f"{now.strftime('%H')}{colon}{now.strftime('%M')}"

    def draw_straight_route(self):
        footer_y = H - 120
        line_x = 120
        line_bottom = footer_y + 60 
        line_top = 160

        pygame.draw.line(self.screen, ROUTE_RED, (line_x, line_bottom), (line_x, line_top), 10)
        arrow_tip = (line_x, line_top - 20)
        arrow_left = (line_x - 15, line_top + 10)
        arrow_right = (line_x + 15, line_top + 10)
        pygame.draw.polygon(self.screen, ROUTE_RED, [arrow_tip, arrow_left, arrow_right])

        # Aktuální zastávka
        ellipse_w, ellipse_h = 70, 44
        pygame.draw.ellipse(self.screen, TEXT_BLACK, 
                            (line_x - ellipse_w//2, line_bottom - ellipse_h//2 - 10, ellipse_w, ellipse_h))

        stops_to_show = 4
        start_y = line_bottom - 110
        spacing_y = 100

        for i in range(stops_to_show):
            view_idx = self.gui_stop_index + 1 + i
            if view_idx < len(self.stops):
                stop = self.stops[view_idx]
                current_y = start_y - (i * spacing_y)
                if current_y < 150: break

                e_w, e_h = 50, 30
                pygame.draw.ellipse(self.screen, TEXT_BLACK, 
                                    (line_x - e_w//2, current_y - e_h//2, e_w, e_h))
                lbl = self.font_stop_list.render(stop["nazev"], True, TEXT_BLACK)
                self.screen.blit(lbl, (line_x + 50, current_y - lbl.get_height()//2))

    def draw(self):
        self.screen.fill(BG_COLOR)

        lbl_num = self.font_line.render(self.line_id, True, TEXT_BLACK)
        self.screen.blit(lbl_num, (30, 15))
        
        arrow_poly = [(110, 35), (110, 75), (150, 55)]
        pygame.draw.polygon(self.screen, ROUTE_RED, arrow_poly)

        lbl_dest = self.font_dest.render(self.dest_name, True, TEXT_BLACK)
        self.screen.blit(lbl_dest, (170, 20))

        pygame.draw.line(self.screen, HEADER_LINE_COLOR, (0, 100), (W, 100), 5)

        time_box_w, time_box_h = 200, 80
        pygame.draw.rect(self.screen, TIME_BG_COLOR, (W - time_box_w, 100, time_box_w, time_box_h))
        lbl_time = self.font_time.render(self.get_time_string(), True, TEXT_WHITE)
        self.screen.blit(lbl_time, (W - time_box_w + (time_box_w - lbl_time.get_width())//2, 100 + (time_box_h - lbl_time.get_height())//2))

        footer_height = 120
        footer_y = H - footer_height
        pygame.draw.rect(self.screen, YELLOW_BAR_COLOR, (0, footer_y, W, footer_height))

        if self.gui_stop_index < len(self.stops):
            current_stop_name = self.stops[self.gui_stop_index]["nazev"]
        else:
            current_stop_name = "KONEČNÁ"
        
        lbl_footer = self.font_footer.render(current_stop_name, True, TEXT_BLACK)
        self.screen.blit(lbl_footer, (190, footer_y + (footer_height - lbl_footer.get_height())//2))

        self.draw_straight_route()

        # Debug
        state_display = self.state
        if state_display == "WAITING_FOR_LIGHT": state_display = "ČEKÁM NA SEMAFOR"
        if state_display == "YIELDING": state_display = "PŘEDNOST (KRUHÁČ)"
        
        lbl_debug = pygame.font.SysFont('Consolas', 15).render(f"t={int(self.bus_abs_pos)} s | {state_display}", True, (150,150,150))
        self.screen.blit(lbl_debug, (W-300, H-20))

    def run(self):
        print("--- START SIMULACE ---")
        running = True
        root = None
        while running:
            dt = self.clock.tick(60) / 1000.0 
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    # potvrzení ukončení simulace
                    if root is None:
                        root = tk.Tk()
                        root.withdraw()
                    if messagebox.askyesno("Ukončit simulaci", "Opravdu chcete ukončit simulaci linky?"):
                        running = False
            self.update_physics(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()
        if root is not None:
            root.destroy()
        print("--- KONEC SIMULACE ---")

if __name__ == "__main__":
    # Případ, kdy je main.py spuštěn přímo (např. ze start.py nebo z příkazové řádky).
    # Lze předat ID linky a směr přes argumenty, jinak se použije výchozí linka 2, směr TAM.
    line_id = "2"
    direction = "tam"

    if len(sys.argv) >= 2:
        line_id = sys.argv[1]
    if len(sys.argv) >= 3:
        direction = sys.argv[2]

    app = BusSimulatorSimpleLine(line_id=line_id, direction=direction)
    app.run()