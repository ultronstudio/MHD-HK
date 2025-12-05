import pygame
import time
import datetime
import os
import math
import random

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
TL_RED = (255, 0, 0)
TL_ORANGE = (255, 165, 0)
TL_GREEN = (0, 255, 0)
TL_OFF = (50, 0, 0) # Tmavá červená (zhasnuto)

# --- CESTY K SOUBORŮM ---
AUDIO_DIR = "audio"
SYS_AUDIO_DIR = os.path.join(AUDIO_DIR, "sys")
STOPS_AUDIO_DIR = os.path.join(AUDIO_DIR, "stops")

# --- FYZIKA ---
MAX_SPEED_KMH = 50.0 # Ve městě max 50
MAX_SPEED_MS = MAX_SPEED_KMH / 3.6
ACCEL = 1.2
DECEL = 1.5
DOOR_TIME = 8.0 
LAYOVER_TIME = 10.0
NEXT_STOP_ANNOUNCE_DIST = 150.0

# --- DATA LINKY 2 ---
trasa_segmenty = [
    ("Terminál HD", 0, "terminal_hd"),
    ("Hlavní nádraží", 500, "hlavni_nadrazi"),
    ("Gočárova třída", 600, "gocarova"),
    ("Ulrichovo náměstí", 400, "ulrichovo"),
    ("Adalbertinum", 500, "adalbertinum"),
    ("Magistrát města", 400, "magistrat"),
    ("Komenského", 300, "komenskeho"),
    ("Zimní stadion", 600, "zimni_stadion"),
    ("Hotel Garni", 700, "hotel_garni"),
    ("Futurum", 800, "futurum"),
    ("Na Brně", 400, "na_brne"),
    ("Na Plachtě", 500, "na_plachte"),
    ("Zvonička", 600, "zvonicka"),
    ("Nový Hradec Králové", 700, "nhk")
]

# --- DEFINICE PŘEKÁŽEK (SEMAFORY A KRUHÁČE) ---
# Klíč = Globální index zastávky (0-13 = TAM, 14-27 = ZPĚT)
# Hodnota = Typ překážky ('LIGHT', 'ROUNDABOUT')
OBSTACLES = {
    # --- SMĚR TAM (Terminál -> NHK) ---
    2: 'ROUNDABOUT', # Hlavní -> Gočárova (Kruháč u Koruny)
    3: 'LIGHT',      # Gočárova -> Ulrichovo (Semafor)
    4: 'LIGHT',      # Ulrichovo -> Adalbertinum (Semafor za mostem)
    5: 'LIGHT',      # Adalbertinum -> Magistrát (Semafor)
    6: 'LIGHT',      # Magistrát -> Komenského (Semafor u soudu)
    7: 'LIGHT',      # Komenského -> Zimní stadion (Semafor)
    8: 'LIGHT',      # Zimní stadion -> Hotel Garni (Velká křižovatka)
    9: 'LIGHT',      # Hotel Garni -> Futurum (Semafor u Futura)
    10: 'LIGHT',     # Futurum -> Na Brně (Semafor)
    
    # --- SMĚR ZPĚT (NHK -> Terminál) ---
    # Indexy jsou posunuté o 14 (14 = Start NHK, 15 = První zastávka Zvonička...)
    18: 'LIGHT',     # Na Brně -> Futurum (Semafor)
    19: 'LIGHT',     # Futurum -> Hotel Garni (Semafor)
    20: 'LIGHT',     # Hotel Garni -> Zimní stadion (Velká křižovatka)
    21: 'LIGHT',     # Zimní stadion -> Komenského (Semafor)
    22: 'LIGHT',     # Komenského -> Magistrát (Semafor u soudu)
    23: 'LIGHT',     # Magistrát -> Adalbertinum (Semafor)
    24: 'LIGHT',     # Adalbertinum -> Ulrichovo (Semafor před mostem)
    25: 'LIGHT',     # Ulrichovo -> Gočárova (Semafor)
    26: 'ROUNDABOUT' # Gočárova -> Hlavní nádraží (Kruháč u Koruny)
}

class BusSimulatorSimpleLine:
    def __init__(self):
        print("--- INICIALIZACE SIMULÁTORU ---")
        pygame.init()
        try: 
            pygame.mixer.init()
            pygame.mixer.set_num_channels(8)
            print("🔊 Zvukový systém: OK")
        except: 
            print("❌ Zvukový systém: CHYBA (Audio nebude hrát)")

        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("MHD HK - Real Traffic Mode")
        self.clock = pygame.time.Clock()
        
        # --- FONTY ---
        self.font_line = pygame.font.SysFont('Arial', 70, bold=True)
        self.font_dest = pygame.font.SysFont('Arial', 65, bold=True)
        self.font_time = pygame.font.SysFont('Arial', 60, bold=True)
        self.font_stop_list = pygame.font.SysFont('Arial', 50, bold=True) 
        self.font_footer = pygame.font.SysFont('Arial', 55, bold=True)
        self.font_dp = pygame.font.SysFont('Times New Roman', 50, bold=True, italic=True)

        self.stops = []
        self.smer_tam = True
        self.prebuild_route()

        # Stav vozu
        self.bus_abs_pos = 0.0
        self.speed = 0.0
        self.stop_index = 0     
        self.gui_stop_index = 0 
        
        # Stavy: DRIVING, BRAKING, STOPPED, DOORS_OPEN, DOORS_CLOSED, LAYOVER
        # Nové stavy pro dopravu: WAITING_FOR_LIGHT, YIELDING (kruháč)
        self.state = "STOPPED" 
        self.timer = 0.0
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

        # --- LOGIKA SEMAFORŮ ---
        # 0=Červená, 1=Červená+Oranžová, 2=Zelená, 3=Oranžová
        self.tl_state = 0 
        self.tl_timer = 0.0
        self.obstacle_processed = False # Abychom na jedné křižovatce nestáli 2x
        self.show_traffic_light = False # Viditelnost semaforu

    def prebuild_route(self):
        self.stops = []
        current_dist = 0.0
        
        if self.smer_tam:
            zdroj = trasa_segmenty
            self.dest_name = "NOVÝ HRADEC KRÁLOVÉ"
        else:
            zdroj = trasa_segmenty[::-1]
            self.dest_name = "TERMINÁL HD"

        if self.smer_tam:
            for name, dist_seg, fname in zdroj:
                current_dist += dist_seg
                self.stops.append({"nazev": name, "dist": current_dist, "file": fname})
        else:
            names = [x[0] for x in zdroj]
            files = [x[2] for x in zdroj]
            dists = [x[1] for x in zdroj][1:] + [0]
            for i, name in enumerate(names):
                self.stops.append({"nazev": name, "dist": current_dist, "file": files[i]})
                current_dist += dists[i]

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

    def check_current_stop_announcement(self, dist_rem):
        if not self.current_stop_announced and dist_rem <= 25.0:
            self.current_stop_announced = True
            self.gui_stop_index = self.stop_index
            print(f"📢 [INFO] 25m do cíle -> Hlásím aktuální zastávku.")
            self.audio_playlist.append(('sys', 'gong'))
            self.audio_playlist.append(('stops', self.stops[self.stop_index]['file']))
            if self.stop_index == len(self.stops) - 1:
                self.audio_playlist.append(('sys', 'konecna'))

    def update_traffic_lights(self, dt):
        """Simuluje cyklus semaforu (zrychleně)."""
        self.tl_timer += dt
        # Cyklus: Červená (4s) -> Červ+Oranž (1s) -> Zelená (4s) -> Oranžová (1.5s)
        if self.tl_state == 0 and self.tl_timer > 4.0: # Red -> RedOrange
            self.tl_state = 1
            self.tl_timer = 0
        elif self.tl_state == 1 and self.tl_timer > 1.0: # RedOrange -> Green
            self.tl_state = 2
            self.tl_timer = 0
        elif self.tl_state == 2 and self.tl_timer > 4.0: # Green -> Orange
            self.tl_state = 3
            self.tl_timer = 0
        elif self.tl_state == 3 and self.tl_timer > 1.5: # Orange -> Red
            self.tl_state = 0
            self.tl_timer = 0

    def get_global_stop_index(self):
        """Vrátí globální index (0-27) pro detekci překážek"""
        if self.smer_tam:
            return self.stop_index
        else:
            # Zpáteční cesta: index 0 je NHK (což je globálně 13/14), posouváme
            return 14 + self.stop_index

    def update_physics(self, dt):
        # Aktualizace semaforů na pozadí
        self.update_traffic_lights(dt)

        # Audio fronta
        if self.audio_queue_timer > 0: self.audio_queue_timer -= dt
        if self.audio_queue_timer <= 0 and self.audio_playlist:
            cat, file = self.audio_playlist.pop(0)
            duration = self.play_sound(cat, file)
            self.audio_queue_timer = duration + 0.2

        if self.stop_index >= len(self.stops):
            if self.state != "LAYOVER": self.state = "LAYOVER"
            return
            
        target_dist = self.stops[self.stop_index]["dist"]
        dist_to_go = target_dist - self.bus_abs_pos

        # --- LOGIKA VIDITELNOSTI SEMAFORU ---
        global_idx = self.get_global_stop_index()
        obstacle_type = OBSTACLES.get(global_idx)
        
        self.show_traffic_light = False
        if obstacle_type == 'LIGHT':
            # Zobrazit pokud:
            # 1. Jsme před křižovatkou (cca 300m) a ještě jsme ji neprojeli
            # 2. NEBO pokud na ní právě čekáme
            if (dist_to_go < 300.0 and not self.obstacle_processed) or self.state == "WAITING_FOR_LIGHT":
                self.show_traffic_light = True

        # --- LOGIKA JÍZDY A DOPRAVY ---
        
        if self.state == "DRIVING":
            # 1. Hlášení příští zastávky (polovina)
            leg_total_dist = target_dist - self.leg_start_pos
            dist_traveled = self.bus_abs_pos - self.leg_start_pos
            if not self.next_stop_announced and dist_traveled >= NEXT_STOP_ANNOUNCE_DIST:
                 self.next_stop_announced = True
                 self.gui_stop_index = self.stop_index
                 self.audio_playlist.append(('sys', 'gong'))
                 self.audio_playlist.append(('sys', 'pristi_zastavka'))
                 self.audio_playlist.append(('stops', self.stops[self.stop_index]['file']))

            self.check_current_stop_announcement(dist_to_go)

            # 2. Detekce PŘEKÁŽEK (Semafor/Kruháč)
            if obstacle_type and not self.obstacle_processed and dist_to_go < 150.0 and dist_to_go > 40.0:
                if obstacle_type == 'LIGHT':
                    # Brzdíme do křižovatky
                    if self.speed > 0: self.speed -= DECEL * dt
                    # Pokud je červená/oranžová a jsme pomalí, zastavíme
                    if self.tl_state != 2 and self.speed < 2.0:
                        self.state = "WAITING_FOR_LIGHT"
                        self.speed = 0
                        print("🚦 [DOPRAVA] Červená! Čekám na semaforu.")
                elif obstacle_type == 'ROUNDABOUT':
                    # Brzdíme pro přednost
                    if self.speed > 3.0: # Zpomal na ~10 km/h
                        self.speed -= DECEL * dt
                    else:
                        self.state = "YIELDING"
                        self.timer = 0
                        print("arrows [DOPRAVA] Kruhový objezd - dávám přednost.")

            # 3. Standardní jízda/brzdění do zastávky
            elif dist_to_go <= ((self.speed**2)/(2*DECEL)) + 5.0:
                self.state = "BRAKING"
                print(f"🛑 [STAV] Brzdím do zastávky.")
            elif self.speed < MAX_SPEED_MS:
                self.speed += ACCEL * dt
            
            # Aplikace pohybu
            if self.state == "DRIVING": # Pokud jsme se nepřepnuli
                self.bus_abs_pos += self.speed * dt

        # --- NOVÉ STAVY PRO DOPRAVU ---
        elif self.state == "WAITING_FOR_LIGHT":
            # Čekáme na zelenou (stav 2)
            if self.tl_state == 2: # Zelená
                self.state = "DRIVING"
                self.obstacle_processed = True # Křižovatka projeta
                print("🟢 [DOPRAVA] Zelená! Jedeme.")

        elif self.state == "YIELDING":
            # Čekáme chvilku na kruháči
            self.timer += dt
            if self.timer > 2.0: # 2 sekundy dáváme přednost
                self.state = "DRIVING"
                self.obstacle_processed = True
                print("↪️ [DOPRAVA] Kruháč volný, jedeme.")

        # --- STANDARDNÍ STAVY ZASTÁVKY ---
        elif self.state == "BRAKING":
            self.check_current_stop_announcement(dist_to_go)
            if dist_to_go > 0.5 and self.speed < 1.0: self.speed = 1.0 
            elif self.speed > 0.1: self.speed -= DECEL * dt
            else: self.speed = 0
            self.bus_abs_pos += self.speed * dt
            
            if dist_to_go <= 0.5:
                self.bus_abs_pos = target_dist
                self.speed = 0
                self.state = "STOPPED"
                self.timer = 0
                self.current_wait_limit = 1.0

        elif self.state == "STOPPED":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                self.state = "DOORS_OPEN"
                self.timer = 0
                self.current_wait_limit = DOOR_TIME 

        elif self.state == "DOORS_OPEN":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                self.state = "DOORS_CLOSED"
                self.timer = 0
                audio_len = self.play_sound('sys', 'buzzer')
                self.current_wait_limit = audio_len + 2.0

        elif self.state == "DOORS_CLOSED":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                if self.stop_index == len(self.stops) - 1: 
                    self.state = "LAYOVER"
                else:
                    self.stop_index += 1
                    self.state = "DRIVING"
                    self.next_stop_announced = False
                    self.current_stop_announced = False
                    self.leg_start_pos = self.bus_abs_pos
                    self.obstacle_processed = False # Reset překážky pro nový úsek
                self.timer = 0

        elif self.state == "LAYOVER":
            self.timer += dt
            if self.timer > LAYOVER_TIME:
                self.smer_tam = not self.smer_tam
                self.prebuild_route()
                self.bus_abs_pos = 0.0
                self.stop_index = 1
                self.gui_stop_index = 0 
                self.state = "DRIVING"
                self.timer = 0
                self.next_stop_announced = False
                self.current_stop_announced = False
                self.leg_start_pos = 0.0
                self.obstacle_processed = False

    def get_time_string(self):
        now = datetime.datetime.now()
        colon = ":" if (time.time() % 1) > 0.5 else " "
        return f"{now.strftime('%H')}{colon}{now.strftime('%M')}"

    def draw_traffic_light(self):
        """Vykreslí semafor pod časem."""
        # Box semaforu
        box_w, box_h = 60, 140
        box_x = W - 150
        box_y = 200 # Pod časem
        
        pygame.draw.rect(self.screen, (30, 30, 30), (box_x, box_y, box_w, box_h), 0, 10)
        
        # Barvy podle stavu
        # 0=R, 1=R+O, 2=G, 3=O
        c_red = TL_RED if self.tl_state in [0, 1] else TL_OFF
        c_orange = TL_ORANGE if self.tl_state in [1, 3] else TL_OFF
        c_green = TL_GREEN if self.tl_state == 2 else TL_OFF
        
        # Žárovky
        radius = 18
        pygame.draw.circle(self.screen, c_red, (box_x + box_w//2, box_y + 25), radius)
        pygame.draw.circle(self.screen, c_orange, (box_x + box_w//2, box_y + 70), radius)
        pygame.draw.circle(self.screen, c_green, (box_x + box_w//2, box_y + 115), radius)

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

        lbl_num = self.font_line.render("2", True, TEXT_BLACK)
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

        # --- VYKRESLENÍ SEMAFORU (JEN KDYŽ JE TŘEBA) ---
        if self.show_traffic_light:
            self.draw_traffic_light()

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
        
        lbl_debug = pygame.font.SysFont('Consolas', 15).render(f"{int(self.speed*3.6)} km/h | {state_display}", True, (150,150,150))
        self.screen.blit(lbl_debug, (W-300, H-20))

    def run(self):
        print("--- START SIMULACE ---")
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0 
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    pass # Fullscreen logic removed for simplicity in this snippet
            self.update_physics(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()
        print("--- KONEC SIMULACE ---")

if __name__ == "__main__":
    app = BusSimulatorSimpleLine()
    app.run()