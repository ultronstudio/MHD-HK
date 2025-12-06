import json
import os
import sys
import time
import datetime
import pygame
import tkinter as tk
from tkinter import messagebox
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
# --- CESTY K SOUBORŮM ---
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# audio umístěné relativně v projektu nebo v extrahované složce _MEIPASS
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
SYS_AUDIO_DIR = os.path.join(AUDIO_DIR, "sys")
STOPS_AUDIO_DIR = os.path.join(AUDIO_DIR, "stops")

# --- SIMULACE PODLE ČASU ---
# Nepočítáme vzdálenost a rychlost, ale jedeme podle
# jízdní doby mezi zastávkami (v minutách v JSON souborech).

DOOR_TIME = 8.0           # doba otevřených dveří (s)
LAYOVER_TIME = 10.0       # pauza na konečné (s)
TIME_SCALE = 1.0          # 1 reálná sekunda = 1 s simulovaného času (reálný čas)

# jak dlouho před příjezdem se má hlásit
NEXT_STOP_ANNOUNCE_BEFORE_SEC = 60.0    # "příští zastávka"
CURRENT_STOP_ANNOUNCE_BEFORE_SEC = 10.0 # aktuální zastávka

# Náhodné poruchy troleje (volitelné)
ENABLE_RANDOM_BREAKS = False
TROLLEY_BREAK_PROB_PER_LEG = 0.03
TROLLEY_REPAIR_MIN_SEC = 20.0
TROLLEY_REPAIR_MAX_SEC = 60.0
TROLLEY_BREAK_REASONS = ["porucha_trolej", "strom_na_vedeni", "nehoda_automobil", "porucha_vozu"]

if getattr(sys, 'frozen', False):
    # běží zabalené PyInstaller --onefile
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LINES_DIR = os.path.join(BASE_DIR, "lines")
ICON_PATH = os.path.join(BASE_DIR, "logo.png")


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
        # na Windows nastavíme AppUserModelID, aby se taskbar správně pároval s ikonou
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(u"ultronstudio.mhdhk")
            except Exception:
                pass

        pygame.init()
        # načíst ikonu (logo.png) a nastavit ji pro Pygame okno
        try:
            if os.path.exists(ICON_PATH):
                icon_surf = pygame.image.load(ICON_PATH)
                try:
                    icon_surf = icon_surf.convert_alpha()
                except Exception:
                    try:
                        icon_surf = icon_surf.convert()
                    except Exception:
                        pass
                try:
                    pygame.display.set_icon(icon_surf)
                except Exception:
                    pass
        except Exception:
            pass
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
        # malé písmo pro plánované časy (bude dynamicky zmenšeno, aby se vešlo do oválu)
        self.font_dp = pygame.font.SysFont('Arial', 28, bold=True)

        def _render_text_fit(text, max_w, max_h, font_name='Arial', bold=True, start_size=28):
            # Vrátí surface s textem, který se vejde do max_w x max_h, snižuje velikost písma.
            for size in range(start_size, 8, -1):
                f = pygame.font.SysFont(font_name, size, bold=bold)
                surf = f.render(text, True, TEXT_WHITE)
                if surf.get_width() <= max_w - 6 and surf.get_height() <= max_h - 4:
                    return surf
            # fallback - použij poslední vytvořený
            return pygame.font.SysFont(font_name, 10, bold=bold).render(text, True, TEXT_WHITE)

        # helper uložíme jako atribut instance
        self._render_text_fit = _render_text_fit

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

        # připravit cestu k ikonce pro případné Tk root dialogy
        self._icon_path = ICON_PATH if os.path.exists(ICON_PATH) else None

        self.prebuild_route()

        # plánovaný čas odjezdu z první zastávky (aktuální čas)
        try:
            self.departure_time = datetime.datetime.now()
        except Exception:
            self.departure_time = datetime.datetime.today()
        # spočítat plánované časy příjezdů pro každou zastávku
        try:
            self._compute_schedule_times()
        except Exception:
            pass

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
        # Časy čekání při zastávce (v sekundách)
        # Po zastavení chvíli počkat, pak otevřít dveře
        self.stop_wait_before_open = 1.5
        # Po otevření dveří počkat navíc (audio_len + this)
        self.after_open_extra = 1.0
        # Minimální doba, po kterou budou dveře otevřené (v sekundách)
        # Nastaveno na 15s, aby byl nástup/výstup dostatečně dlouhý na všech zastávkách
        self.door_open_min = 15.0
        # Doba otevření na první zastávce po startu (v sekundách)
        self.first_stop_dwell = 15.0
        # Po zavření dveří čekat ještě krátce před odjezdem
        self.after_close_extra = 1.0
        self.debug_timer = 0.0 
        
        # Audio fronta
        self.audio_queue_timer = 0.0
        self.audio_to_play = None
        self.audio_playlist = [] 
        # Random break scheduling state (pro ENABLE_RANDOM_BREAKS)
        self._scheduled_break = None
        # support multiple scheduled breaks generated at start (abs positions)
        self._scheduled_breaks = []
        self._break_active = False
        # Track breaks per direction so we limit to max 2 in one direction
        self._breaks_done = 0
        self._breaks_direction = None  # which direction had breaks (True=tam, False=zpět)
        self._break_positions = []
        
        # Hlášení
        self.next_stop_announced = False 
        self.current_stop_announced = False 
        self.leg_start_pos = 0.0
        # Úvodní sekvence na první zastávce: zavřeno -> otevřít (se zvukem) -> zavřít (se zvukem) -> rozjezd
        self.startup_sequence_done = False
        # Po inicializaci naplánuj poruchy pro tento směr
        try:
            self._generate_scheduled_breaks()
        except Exception:
            pass

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
            # pro směr zpět: vezmeme původní časovou osu (neobráčenou),
            # zjistíme celkový čas trasy a pro každou zastávku v opačném pořadí
            # spočítáme dist = total_time - (minute_mark * 60).
            orig = self.trasa_segmenty
            if orig:
                total_time = orig[-1][1] * 60.0
            else:
                total_time = 0.0
            for name, minute_mark, fname in zdroj:
                # zde je zdroj už obrácený pořad (od cíle k začátku)
                dist = max(0.0, total_time - (minute_mark * 60.0))
                self.stops.append({"nazev": name, "dist": dist, "file": fname})

    def _generate_scheduled_breaks(self):
        """Generuje 0..2 poruch (absolutní pozice v sekundách od startu směru).
        Poruchy jsou naplánovány pro aktuální trasu (self.stops) a přidány do
        self._scheduled_breaks jako slovníky s klíči: abs_pos, repair_time, reason, triggered.
        """
        self._scheduled_breaks = []
        if not self.stops:
            return
        route_total = self.stops[-1]["dist"]
        # pokud je trasa příliš krátká, žádné poruchy
        if route_total <= 10.0:
            return
        count = random.randint(0, 2)
        vehicle_type = getattr(self, 'vehicle', 'bus')
        # pokud máme dvě poruchy, umístíme je do 2. a 4. čtvrtiny trasy
        if count == 2:
            q2_min, q2_max = 0.25 * route_total, 0.5 * route_total
            q4_min, q4_max = 0.75 * route_total, min(0.95 * route_total, route_total)
            pos1 = random.uniform(q2_min, q2_max)
            pos2 = random.uniform(q4_min, q4_max)
            positions = [pos1, pos2]
        elif count == 1:
            # náhodně vybereme buď 2. nebo 4. čtvrtinu
            if random.choice([True, False]):
                positions = [random.uniform(0.25 * route_total, 0.5 * route_total)]
            else:
                positions = [random.uniform(0.75 * route_total, min(0.95 * route_total, route_total))]
        else:
            positions = []

        for pos in positions:
            repair_t = random.uniform(TROLLEY_REPAIR_MIN_SEC, TROLLEY_REPAIR_MAX_SEC)
            # vyber duvod vhodny pro typ vozidla
            if vehicle_type == 'trolley':
                possible = list(TROLLEY_BREAK_REASONS)
            else:
                possible = [r for r in TROLLEY_BREAK_REASONS if r != 'porucha_trolej']
            reason = random.choice(possible) if possible else 'porucha'
            self._scheduled_breaks.append({'abs_pos': pos, 'repair_time': repair_t, 'reason': reason, 'triggered': False})
        # vždy vypiš info do konzole (i když je seznam prázdný)
        try:
            items = [f"{b['abs_pos']:.1f}s:{b['reason']}" for b in self._scheduled_breaks]
            print(f"[DEBUG] Naplánované poruchy pro linku {self.line_id}: {len(self._scheduled_breaks)} -> {items}")
        except Exception:
            print(f"[DEBUG] Naplánované poruchy pro linku {self.line_id}: {len(self._scheduled_breaks)}")

    def _compute_schedule_times(self):
        """Vypočítá plánované časy příjezdu (`sched_dt` a `sched_str`) pro každou zastávku
        na základě `self.departure_time` a `stop['dist']` (v sekundách).
        """
        if not hasattr(self, 'departure_time') or self.departure_time is None:
            try:
                self.departure_time = datetime.datetime.now()
            except Exception:
                self.departure_time = datetime.datetime.today()
        for s in self.stops:
            try:
                sched_dt = self.departure_time + datetime.timedelta(seconds=float(s.get('dist', 0.0)))
                s['sched_dt'] = sched_dt
                # zobrazovat pouze hodiny a minuty
                s['sched_str'] = sched_dt.strftime('%H:%M')
            except Exception:
                s['sched_dt'] = None
                s['sched_str'] = ''

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

    def _queue_line_delay_announce(self, reason_key: str):
        """Slozi a naplni audio_playlist hlasku ve formatu:
        linka_cislo + cislo_{line_id} + se_zpozdi_z_duvodu + <reason>
        Reason_key se pripadne mapuje na konkretni soubor v audio/sys.
        """
        # mapovani internich klicu na konkretni audio soubory
        reason_map = {
            'porucha_trolej': 'porucha_trolej',
            'strom_na_vedeni': 'strom_na_vedeni',
            'nehoda': 'nehoda_automobil',
            'porucha': 'porucha'
        }
        reason_file = reason_map.get(reason_key, reason_key)

        # pridame poradi, ktere odpovida existujicim souborum v audio/sys
        # 1) "Linka cislo"
        self.audio_playlist.append(('sys', 'linka_cislo'))
        # 2) cislo jako slovo/varianta - preferujeme `cislo_{id}`
        self.audio_playlist.append(('sys', f'cislo_{self.line_id}'))
        # 3) spojovaci fraze
        self.audio_playlist.append(('sys', 'se_zpozdi_z_duvodu'))
        # 4) prave duvod
        self.audio_playlist.append(('sys', reason_file))
        # také loguj textovou podobu hlášení pro ladění
        try:
            print(f"[ANN] linka_cislo cislo_{self.line_id} se_zpozdi_z_duvodu {reason_file}")
        except Exception:
            pass

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
                # spustíme hlášení už v první čtvrtině času úseku
                if time_traveled >= (leg_total_time * 0.25):
                    self.next_stop_announced = True
                    self.gui_stop_index = self.stop_index
                    self.audio_playlist.append(('sys', 'gong'))
                    self.audio_playlist.append(('sys', 'pristi_zastavka'))
                    self.audio_playlist.append(('stops', self.stops[self.stop_index]['file']))
                    print(f"📢 [INFO] Průjezd čtvrtiny úseku ({time_traveled:.1f}/{leg_total_time:.1f}s) - hlásím příští zastávku.")
            # Zkontroluj naplánované poruchy vytvořené při startu/otočení směru.
            try:
                if self._scheduled_breaks and not self._break_active:
                    for br in self._scheduled_breaks:
                        if br.get('triggered'):
                            continue
                        if self.bus_abs_pos >= br.get('abs_pos', 0.0):
                            br['triggered'] = True
                            self._break_active = True
                            self.state = 'BROKEN'
                            self.timer = 0.0
                            self.repair_timer = br.get('repair_time', 10.0)
                            self.break_reason = br.get('reason', 'porucha')
                            # upozorni cestující: složená hláška
                            self.audio_playlist.append(('sys', 'gong'))
                            self._queue_line_delay_announce(self.break_reason)
                            # zaznamenej pozici poruchy a pocet poruch v tomto smeru
                            try:
                                abs_pos = float(br.get('abs_pos', 0.0))
                                self._break_positions.append(abs_pos)
                                self._breaks_done += 1
                                if self._breaks_direction is None:
                                    self._breaks_direction = self.smer_tam
                            except Exception:
                                pass
                            print(f"[DEBUG] Line {self.line_id} BROKEN: reason={self.break_reason}, repair={self.repair_timer:.1f}s, abs_pos={abs_pos:.1f}")
                            break
            except Exception:
                pass
            
            # (logování přesunuto do místa, kde se hlášení skutečně spouští)

            self.check_current_stop_announcement(time_to_go)

            self.bus_abs_pos += sim_dt

            if self.bus_abs_pos >= target_time:
                self.bus_abs_pos = target_time
                self.state = "STOPPED"
                self.timer = 0
                # krátké čekání na úplné zastavení před otevřením dveří
                self.current_wait_limit = getattr(self, 'stop_wait_before_open', 1.5)

        # --- STANDARDNÍ STAVY ZASTÁVKY ---
        elif self.state == "BRAKING":
            # v časové verzi slouží jako rychlý dojezd
            sim_dt = dt * TIME_SCALE
            self.bus_abs_pos += sim_dt
            if self.bus_abs_pos >= target_time:
                self.bus_abs_pos = target_time
                self.state = "STOPPED"
                self.timer = 0
                # krátké čekání na úplné zastavení před otevřením dveří
                self.current_wait_limit = getattr(self, 'stop_wait_before_open', 1.5)

        elif self.state == "BROKEN":
            # Vozidlo je v poruše: čekáme na dokončení opravy (repair_timer nastavován při přechodu do BROKEN)
            self.timer += dt
            if self.timer >= getattr(self, 'repair_timer', 0.0):
                # oprava hotova -> pokračovat v jízdě
                self._break_active = False
                self.timer = 0.0
                # po oprave jedeme dal (neotevirame dveře automaticky)
                self.state = "DRIVING"
                # resetuj oznaceni hlasek pro aktualni usek
                self.next_stop_announced = False
                self.current_stop_announced = False
            
        elif self.state == "STOPPED":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                # otevřít dveře po čekání na zastavení
                self.state = "DOORS_OPEN"
                self.timer = 0
                audio_len = self.play_sound('sys', 'bus_door')
                # zajisti minimalni dobu otevreni pro nastup
                wait_time = audio_len + getattr(self, 'after_open_extra', 1.0)
                min_open = getattr(self, 'door_open_min', 4.0)
                # pokud jsme na PRVNÍ zastávce po startu, necháme delší otevření
                if getattr(self, 'stop_index', 0) == 0 and not getattr(self, 'startup_sequence_done', False):
                    min_open = max(min_open, getattr(self, 'first_stop_dwell', 15.0))
                    # označíme, že úvodní sekvence proběhla
                    try:
                        self.startup_sequence_done = True
                    except Exception:
                        pass
                self.current_wait_limit = max(wait_time, min_open)

        elif self.state == "DOORS_OPEN":
            self.timer += dt
            if self.timer > self.current_wait_limit:
                # běžné chování: zavřít dveře a připravit čas na zavření
                self.state = "DOORS_CLOSED"
                self.timer = 0
                # spustit zvuk zavírání/pípnutí a čekat než dveře budou zavřené
                audio_len = self.play_sound('sys', 'buzzer')
                self.current_wait_limit = audio_len + getattr(self, 'after_close_extra', 0.5)

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
                        # reset poruch pro novy smer a naplanuj nove
                        self._breaks_done = 0
                        self._break_positions = []
                        self._breaks_direction = None
                        try:
                            self._generate_scheduled_breaks()
                        except Exception:
                            pass
                        # aktualizuj plánovaný čas odjezdu a přepočítej časy
                        try:
                            self.departure_time = datetime.datetime.now()
                        except Exception:
                            self.departure_time = datetime.datetime.today()
                        try:
                            self._compute_schedule_times()
                        except Exception:
                            pass
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
        # vycentrovat hlavní ovál přesně na osu
        pygame.draw.ellipse(self.screen, TEXT_BLACK, 
                    (line_x - ellipse_w//2, line_bottom - ellipse_h//2, ellipse_w, ellipse_h))

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
                # ovál vykreslíme tak, aby byl vycentrován na linii
                oval_rect = (line_x - e_w//2, current_y - e_h//2, e_w, e_h)
                pygame.draw.ellipse(self.screen, TEXT_BLACK, oval_rect)

                # název zastávky zarovnaný na pevnou pozici (vpravo od osy), oříznutí dlouhých názvů
                name = stop.get("nazev", "")
                # pevná levá pozice pro začátek názvů
                label_x = line_x + (ellipse_w // 2) + 20
                # maximální šířka pro štítek
                max_label_w = max(40, W - label_x - 20)
                lbl = self.font_stop_list.render(name, True, TEXT_BLACK)
                if lbl.get_width() > max_label_w:
                    # jednoduché oříznutí s elipsou — zkus odhadnout počet znaků
                    approx_chars = max(3, int(len(name) * (max_label_w / lbl.get_width())) - 1)
                    short = name[:approx_chars].rstrip()
                    # doplň tečku pokud se ještě nevejde
                    while self.font_stop_list.render(short + '…', True, TEXT_BLACK).get_width() > max_label_w and len(short) > 3:
                        short = short[:-1]
                    short = short + '…'
                    lbl = self.font_stop_list.render(short, True, TEXT_BLACK)
                self.screen.blit(lbl, (label_x, current_y - lbl.get_height()//2))

                # vykresli plánovaný čas příjezdu VEDLE oválu (brand barva, stejny font jako jmena)
                sched = stop.get('sched_str', '')
                if sched:
                    # použijeme stejný font jako pro seznam zastávek, barva brand (ROUTE_RED)
                    try:
                        # menší font pro plánované časy
                        lbl_time = self.font_dp.render(sched, True, ROUTE_RED)
                        # umístit vlevo od oválu s malou mezerou
                        left_x = line_x - (e_w // 2) - 10 - lbl_time.get_width()
                        self.screen.blit(lbl_time, (left_x, current_y - lbl_time.get_height()//2))
                    except Exception:
                        # fallback: jednoduché renderování menším fontem bíle uvnitř oválu
                        max_w, max_h = e_w, e_h
                        surf_time = self._render_text_fit(sched, max_w, max_h, font_name='Arial', bold=True, start_size=28)
                        oval_cx = line_x
                        oval_cy = current_y
                        self.screen.blit(surf_time, (oval_cx - surf_time.get_width()//2, oval_cy - surf_time.get_height()//2))

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
                        # pokud máme logo, nastav ho jako ikonu okna dialogu
                        try:
                            if self._icon_path and os.path.exists(self._icon_path):
                                img = tk.PhotoImage(master=root, file=self._icon_path)
                                root.iconphoto(False, img)
                                root._icon_image = img
                        except Exception:
                            pass
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