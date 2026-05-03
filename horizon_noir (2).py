#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║     H O R I Z O N   N O I R  —  Année 2178                     ║
║     Simulateur Galactique + RPG Spatial                         ║
║     Compatible Windows / macOS / Linux                          ║
╚══════════════════════════════════════════════════════════════════╝

Dépendances : pip install pygame numpy
Lancement   : python horizon_noir.py
"""

# ── Imports & compatibilité tous OS ───────────────────────────────
import os, sys, math, random, time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from enum import Enum

# Pilotes silencieux pour serveurs/CI (SDL tente audio/video réel sur bureau)
if "--headless" in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import numpy as np

# ── Constantes ────────────────────────────────────────────────────
W, H        = 1280, 800
FPS         = 60
G           = 6.674e-11
DT_PHYS     = 55000        # secondes simulées / frame physique
SAMPLE_RATE = 44100
FONT_MONO   = "Courier New,Courier,monospace"   # fallback automatique

# ── Palette ───────────────────────────────────────────────────────
C = dict(
    bg         = (  3,  5, 18),
    ui_bg      = (  5,  8, 28),
    ui_border  = ( 30, 60,120),
    gold       = (255,200, 50),
    orange     = (255,140, 20),
    cyan       = ( 60,200,255),
    purple     = (160, 40,240),
    green      = ( 50,220,100),
    red        = (220, 50, 50),
    gray       = (140,140,150),
    white      = (240,240,255),
    dim        = (100,110,130),
    horizon    = ( 80,  0,160),
    warn       = (255,100,  0),
    info       = ( 80,180,255),
)

# ══════════════════════════════════════════════════════════════════
#  SYNTHÈSE AUDIO  (numpy, pas de fichier externe)
# ══════════════════════════════════════════════════════════════════

def _adsr(n, atk=0.08, dec=0.15, sus=0.7, rel=0.2):
    env = np.ones(n, dtype=np.float32)
    a = max(1, int(atk * n)); d = max(1, int(dec * n)); r = max(1, int(rel * n))
    env[:a]    = np.linspace(0, 1, a)
    env[a:a+d] = np.linspace(1, sus, d)
    if r < n:   env[-r:] = np.linspace(env[-r-1], 0, r)
    return env

def synth(freq, dur, vol=0.3, wave='sine', atk=0.08, dec=0.15):
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, False, dtype=np.float32)
    if   wave == 'sine':     w = np.sin(2*np.pi*freq*t)
    elif wave == 'tri':      w = 2*np.abs(2*(t*freq - np.floor(t*freq+0.5))) - 1
    elif wave == 'saw':      w = 2*(t*freq - np.floor(t*freq+0.5))
    elif wave == 'square':   w = np.sign(np.sin(2*np.pi*freq*t)).astype(np.float32)
    elif wave == 'noise':    w = np.random.uniform(-1,1,n).astype(np.float32)
    else:                    w = np.sin(2*np.pi*freq*t)
    w *= _adsr(n, atk, dec) * vol
    return np.clip(w, -1, 1)

def pad(freq, dur=3.5, vol=0.12):
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, False, dtype=np.float32)
    w  = np.sin(2*np.pi*freq*t)
    w += np.sin(2*np.pi*freq*1.259*t) * 0.55   # tierce mineure
    w += np.sin(2*np.pi*freq*1.498*t) * 0.40   # quinte
    w += np.sin(2*np.pi*freq*2.0  *t) * 0.18   # octave
    lfo = 0.82 + 0.18*np.sin(2*np.pi*0.25*t)
    env = _adsr(n, 0.35, 0.25, 0.75, 0.35)
    w = np.clip(w * lfo * env * vol, -1, 1)
    return w

def noise_burst(dur=0.5, vol=0.55, lo=3, smooth=4):
    n = int(SAMPLE_RATE * dur)
    w = np.random.uniform(-1,1,n).astype(np.float32)
    for _ in range(smooth):
        k = [0.25,0.5,0.25]
        w = np.convolve(w, k, 'same').astype(np.float32)
    t = np.linspace(0, dur, n, False, dtype=np.float32)
    env = np.exp(-lo * t / dur)
    return np.clip(w * env * vol, -1, 1)

def _to_sound(arr):
    s = (arr * 32767).astype(np.int16)
    try:
        return pygame.sndarray.make_sound(s)
    except Exception:
        return None

def _mix(*arrays):
    n = max(len(a) for a in arrays)
    out = np.zeros(n, dtype=np.float32)
    for a in arrays:
        out[:len(a)] += a
    return np.clip(out, -1, 1)

def build_sounds():
    sr = SAMPLE_RATE
    sounds = {}
    try:
        # Pads ambiants — séquence harmonique sombre
        roots = [98.0, 110.0, 123.47, 130.81, 146.83, 164.81]
        for i, r in enumerate(roots):
            sounds[f'pad_{i}'] = _to_sound(pad(r, 4.0, 0.11))

        # FX
        sounds['place_planet']    = _to_sound(synth(392, 0.5, 0.4, 'tri',  0.04, 0.2))
        sounds['place_star']      = _to_sound(synth(587, 0.6, 0.4, 'sine', 0.03, 0.2))
        sounds['place_bh']        = _to_sound(synth(55,  1.0, 0.5, 'saw',  0.02, 0.3))
        sounds['place_asteroid']  = _to_sound(synth(220, 0.3, 0.35,'square',0.03,0.15))
        sounds['collision']       = _to_sound(noise_burst(0.7, 0.65, 4, 5))
        sounds['whoosh']          = _to_sound(_mix(
            synth(800, 0.4, 0.25, 'noise', 0.01, 0.5),
            synth(200, 0.4, 0.15, 'sine',  0.01, 0.6)))
        sounds['scan']            = _to_sound(_mix(
            synth(1200,0.3, 0.3,'sine',0.01,0.1),
            synth(1600,0.3, 0.2,'sine',0.05,0.15)))
        sounds['alert']           = _to_sound(_mix(
            synth(440, 0.15,0.5,'square',0.01,0.05),
            synth(440, 0.15,0.5,'square',0.01,0.05)))
        sounds['repair']          = _to_sound(synth(660, 0.4, 0.35,'tri',0.02,0.2))
        sounds['horizon_hum']     = _to_sound(_mix(
            pad(40, 3.0, 0.18), synth(60, 3.0, 0.08,'sine',0.3,0.2)))
        sounds['victory']         = _to_sound(_mix(
            synth(523.25,0.4,0.45,'sine',0.02,0.3),
            synth(659.25,0.4,0.35,'tri', 0.02,0.3),
            synth(783.99,0.4,0.30,'sine',0.02,0.3),
            synth(1046.5,0.6,0.40,'sine',0.02,0.3)))
        sounds['game_over']       = _to_sound(_mix(
            synth(220,0.5,0.4,'sine',0.01,0.4),
            synth(185,0.8,0.3,'sine',0.01,0.5)))
        sounds['hyperdrive']      = _to_sound(_mix(
            synth(110,0.8,0.3,'saw',0.01,0.3),
            synth(220,0.6,0.2,'sine',0.05,0.4),
            noise_burst(0.8,0.2,2,6)))
        sounds['narrative']       = _to_sound(synth(330, 0.3, 0.3,'tri',0.02,0.2))
    except Exception as e:
        print(f"[Audio] Avertissement : {e}")
    return sounds

# ══════════════════════════════════════════════════════════════════
#  MOTEUR AUDIO
# ══════════════════════════════════════════════════════════════════

class AudioEngine:
    def __init__(self, sounds):
        self.sounds     = sounds
        self.pad_seq    = [f'pad_{i}' for i in range(6)]
        random.shuffle(self.pad_seq)
        self.pad_idx    = 0
        self.pad_timer  = 0
        self.pad_int    = 190   # frames entre accords
        self.hum_ch     = pygame.mixer.Channel(0) if pygame.mixer.get_init() else None
        self.hum_on     = False
        self.master_vol = 0.8
        self._ok        = bool(pygame.mixer.get_init())

    def _play(self, name, vol_mul=1.0):
        if not self._ok: return
        snd = self.sounds.get(name)
        if not snd: return
        ch = pygame.mixer.find_channel()
        if ch:
            ch.set_volume(self.master_vol * vol_mul)
            ch.play(snd)

    def play(self, name, vol=1.0):
        self._play(name, vol)

    def update(self, has_horizon: bool):
        if not self._ok: return
        self.pad_timer += 1
        if self.pad_timer >= self.pad_int:
            self.pad_timer = 0
            k = self.pad_seq[self.pad_idx % len(self.pad_seq)]
            self.pad_idx += 1
            ch = pygame.mixer.find_channel()
            if ch:
                ch.set_volume(self.master_vol * 0.65)
                if self.sounds.get(k): ch.play(self.sounds[k])

        if self.hum_ch:
            snd = self.sounds.get('horizon_hum')
            if has_horizon and not self.hum_on and snd:
                self.hum_ch.play(snd, loops=-1, fade_ms=2000)
                self.hum_on = True
            elif not has_horizon and self.hum_on:
                self.hum_ch.fadeout(1500)
                self.hum_on = False

# ══════════════════════════════════════════════════════════════════
#  TYPES D'OBJETS
# ══════════════════════════════════════════════════════════════════

class ObjType(Enum):
    STAR        = "star"
    PLANET      = "planet"
    BLACK_HOLE  = "black_hole"
    ASTEROID    = "asteroid"
    STATION     = "station"
    WORMHOLE    = "wormhole"
    ANOMALY     = "anomaly"
    SHIP        = "ship"

# ══════════════════════════════════════════════════════════════════
#  CORPS CÉLESTE
# ══════════════════════════════════════════════════════════════════

@dataclass
class Body:
    x: float; y: float
    vx: float = 0.0; vy: float = 0.0
    mass: float = 1e24
    otype: ObjType = ObjType.PLANET
    name: str = ""
    radius: float = 10
    color: tuple = (100,150,255)
    alive: bool = True
    trail: list = field(default_factory=list)
    trail_max: int = 200
    age: float = 0.0
    rotation: float = 0.0
    birth: float = 0.0          # 0→1 animation
    scannable: bool = False
    scanned: bool = False
    data_reward: int = 0
    colony_hp: int = 0          # >0 = colonie
    colony_name: str = ""
    faction: str = ""           # OSS / Indep / Horizon

    def update(self):
        self.age += DT_PHYS
        rot_speed = {ObjType.STAR:0.002, ObjType.PLANET:0.008,
                     ObjType.BLACK_HOLE:0.001, ObjType.ASTEROID:0.025,
                     ObjType.STATION:0.005, ObjType.WORMHOLE:0.015,
                     ObjType.ANOMALY:0.003, ObjType.SHIP:0.01}
        self.rotation = (self.rotation + rot_speed.get(self.otype, 0.007)) % (2*math.pi)
        if self.birth < 1.0: self.birth = min(1.0, self.birth + 0.045)
        self.trail.append((self.x, self.y))
        if len(self.trail) > self.trail_max: self.trail.pop(0)

# ══════════════════════════════════════════════════════════════════
#  VAISSEAU JOUEUR
# ══════════════════════════════════════════════════════════════════

@dataclass
class Ship:
    x: float = 0.0; y: float = 0.0
    vx: float = 0.0; vy: float = 0.0
    hull: int = 100;  hull_max: int = 100
    shield: int = 80; shield_max: int = 80
    energy: float = 100.0; energy_max: int = 100
    fuel: float = 100.0; fuel_max: float = 100.0
    data: int = 0
    credits: int = 500
    # Modules
    has_scanner: bool = True
    has_hyperdrive: bool = False
    has_ai: bool = False
    has_weapons: bool = False
    scanner_range: float = 300.0
    # Niveaux amelioration
    hull_level: int = 0
    shield_level: int = 0
    engine_level: int = 0
    scanner_level: int = 0
    # Distribution energie
    eng_engine: int = 34
    eng_shield: int = 33
    eng_sensor: int = 33
    # Pannes
    engine_broken: bool = False
    scanner_broken: bool = False
    shield_broken: bool = False
    # Hyperdrive
    hyperdrive_charge: float = 0.0
    hyperdrive_cooldown: int = 0
    # Stats
    missions_done: int = 0
    colonies_saved: int = 0
    colonies_abandoned: int = 0
    total_scans: int = 0
    jumps_done: int = 0
    log: list = None

    def __post_init__(self):
        if self.log is None:
            self.log = []

    def add_log(self, msg):
        self.log.append(msg)
        if len(self.log) > 25: self.log.pop(0)

    def regen(self):
        if not self.shield_broken:
            rate = self.eng_shield / 100.0 * 0.08
            self.shield = min(self.shield_max, self.shield + rate)
        if self.energy < self.energy_max:
            self.energy = min(self.energy_max, self.energy + 0.12)

    def take_damage(self, dmg):
        if self.shield > 0 and not self.shield_broken:
            absorbed = min(self.shield, dmg)
            self.shield -= absorbed; dmg -= absorbed
        self.hull = max(0, self.hull - dmg)

    @property
    def alive(self): return self.hull > 0

    @property
    def speed_mult(self):
        base = self.eng_engine / 34.0 if not self.engine_broken else 0.3
        return base * (1.0 + self.engine_level * 0.25)

    @property
    def effective_scanner_range(self):
        return self.scanner_range * (1.0 + self.scanner_level * 0.5)

# ══════════════════════════════════════════════════════════════════
#  NARRATIF — QUÊTES & DIALOGUES
# ══════════════════════════════════════════════════════════════════

@dataclass
class NarrativeEvent:
    title: str
    lines: List[str]
    choices: List[Tuple[str, str]]   # (label, outcome_key)
    icon: str = "📡"

STORY_EVENTS = {
    "intro": NarrativeEvent(
        "BRIEFING OSS — Année 2178",
        [
            "Pilote, bienvenue à bord du Khronos.",
            "L'Horizon Noir s'étend à une vitesse alarmante.",
            "Trois colonies ont disparu en 72 heures.",
            "Votre mission : scanner les anomalies,",
            "contacter les colonies en danger,",
            "et trouver l'origine du phénomène.",
            "Bonne chance. L'OSS compte sur vous.",
        ],
        [("Accepter la mission", "mission_start")],
        "🛰️"
    ),
    "colony_nova": NarrativeEvent(
        "CONTACT — Colonie Nova Kepler",
        [
            "Signal faible reçu de Nova Kepler.",
            "«Ici le Gouverneur Yara Chen.",
            " L'Horizon Noir coupe nos communications.",
            " Nos systèmes de vie tombent en panne.",
            " Nous avons besoin de votre aide immédiatement.»",
            "Votre scanner détecte une instabilité croissante.",
        ],
        [
            ("Dévier vers Nova Kepler (+30 crédits, +1 colonie)", "save_nova"),
            ("Continuer la mission principale", "ignore_nova"),
        ],
        "🏘️"
    ),
    "wormhole_found": NarrativeEvent(
        "ANOMALIE DÉTECTÉE — Trou de Ver",
        [
            "Votre IA détecte une signature gravitationnelle.",
            "Un trou de ver instable vient d'apparaître.",
            "Destination inconnue. Probabilité de survie : 67%.",
            "Mais il pourrait mener à l'origine de l'Horizon.",
        ],
        [
            ("Traverser le trou de ver (risqué)", "enter_wormhole"),
            ("Scanner depuis une distance sûre", "scan_wormhole"),
        ],
        "🌀"
    ),
    "faction_horizon": NarrativeEvent(
        "TRANSMISSION CRYPTÉE",
        [
            "«Pilote... Vous approchez de la vérité.»",
            "«L'Horizon Noir n'est pas une anomalie.»",
            "«C'est une arme. Construite par l'OSS.»",
            "«Rejoignez-nous. Nous pouvons l'arrêter.»",
            "Signal perdu.",
        ],
        [
            ("Faire confiance à l'OSS", "trust_oss"),
            ("Enquêter sur cette faction", "investigate_faction"),
            ("Rester neutre", "stay_neutral"),
        ],
        "⚠️"
    ),
    "origin_found": NarrativeEvent(
        "DECOUVERTE — Source de l'Horizon Noir",
        [
            "Scanner maximal. Donnees compilees.",
            "L'Horizon Noir est un generateur de singularites",
            "place en orbite du trou noir Erebus-9.",
            "Il amplifie la gravite a l'echelle interstellaire.",
            "Trois options. Une seule chance.",
        ],
        [
            ("Detruire le generateur (Fin : Paix)", "destroy_gen"),
            ("Capturer le generateur (Fin : Controle)", "capture_gen"),
            ("Sacrifier le Khronos pour l'absorber (Fin : Sacrifice)", "sacrifice_gen"),
        ],
        "SOURCE"
    ),
    "ending_peace": NarrativeEvent(
        "FIN : LA PAIX DES ETOILES",
        [
            "Le generateur Erebus-9 est detruit.",
            "L'Horizon Noir se dissipe en 72 heures.",
            "Les routes interstellaires rouvrent une a une.",
            "Nova Kepler, Veridian, Glacius... toutes survivent.",
            "L'OSS vous recompense : Amiral de la Flotte Civile.",
            "Dans vos journaux de bord, une derniere entree :",
            "  'Nous sommes les gardiens des etoiles.'",
        ],
        [("Nouvelle partie", "restart")],
        "VICTOIRE"
    ),
    "ending_control": NarrativeEvent(
        "FIN : LE MAITRE DES ETOILES",
        [
            "Vous controlez maintenant l'Horizon Noir.",
            "L'OSS tente de negocier. Les factions s'inclinent.",
            "Vous pouvez ouvrir ou fermer les routes a volonte.",
            "Pouvoir absolu. Solitude absolue.",
            "Dans cent ans, les historiens debattront encore :",
            "  Etes-vous un sauveur ou un tyran ?",
        ],
        [("Nouvelle partie", "restart")],
        "POUVOIR"
    ),
    "ending_sacrifice": NarrativeEvent(
        "FIN : LE SACRIFICE DU KHRONOS",
        [
            "Vous guidez le Khronos dans le coeur de l'anomalie.",
            "A l'interieur, le silence. Puis la lumiere.",
            "Votre vaisseau absorbe le generateur.",
            "L'Horizon Noir implose. Vous disparaissez avec lui.",
            "Mais les colonies survivent. Toutes.",
            "  'Pilote Khronos — Disparu en service. Jamais oublie.'",
        ],
        [("Nouvelle partie", "restart")],
        "SACRIFICE"
    ),
    "storm_event": NarrativeEvent(
        "ALERTE — Tempete Solaire Classe X",
        [
            "Eruption coronale de Solaris Prime detectee.",
            "Intensite : Classe X — Categorie maximale.",
            "Toutes les communications sont perturbees.",
            "Vos boucliers sont sollicites au maximum.",
            "Que faites-vous ?",
        ],
        [
            ("Activer boucliers maximum (-20 energie)", "storm_shield"),
            ("Chercher abri derriere une planete", "storm_hide"),
            ("Continuer la mission, ignorer la tempete", "storm_ignore"),
        ],
        "TEMPETE"
    ),
    "station_contact": NarrativeEvent(
        "CONTACT — Station OSS Aleph",
        [
            "Transmission de la Commandante Reyes, OSS Aleph.",
            "'Pilote, nous avons decode les donnees de l'Horizon.",
            " Le phenomene est amplifie par 3 relais orbitaux.",
            " Si vous detruisez les relais, l'intensite baisse.",
            " Mais les relais sont proteges par des champs de force.'",
            "Coordonnees transmises. Mission disponible.",
        ],
        [
            ("Accepter la mission relais (+100 cr.)", "accept_relay_mission"),
            ("Demander plus d'informations d'abord", "ask_relay_info"),
        ],
        "OSS"
    ),
    "veridian_contact": NarrativeEvent(
        "SIGNAL — Colonie Veridian",
        [
            "Transmission d'urgence de Veridian.",
            "'Ici le Docteur Amara Singh.",
            " Nous avons trouve quelque chose dans les mines.",
            " Des cristaux qui resonent avec l'Horizon Noir.",
            " Ils pourraient etre la cle pour l'inverser.",
            " Mais des pirates independants ont encercle la colonie.'",
        ],
        [
            ("Intervenir militairement contre les pirates", "fight_pirates"),
            ("Negocier avec les pirates (500 cr.)", "bribe_pirates"),
            ("Recuperer les cristaux discritement", "stealth_crystals"),
        ],
        "CRISTAUX"
    ),
    "oss_betrayal": NarrativeEvent(
        "REVELATION — Les Archives Classifiees",
        [
            "Votre IA a pirate les archives de l'OSS Aleph.",
            "Classification : ULTRA SECRET — Projet Erebus.",
            "'Annee 2171 : Le generateur Erebus-9 est operationnel.'",
            "'Cible : les systemes independants non allies a l'OSS.'",
            "'L'Horizon Noir est notre arme de dernier recours.'",
            "L'OSS a cree l'Horizon Noir. Ils ont menti depuis le debut.",
            "Vous etes seul. A vous de decider.",
        ],
        [
            ("Denoncer l'OSS publiquement", "expose_oss"),
            ("Utiliser cette info pour negocier", "blackmail_oss"),
            ("Detruire le generateur quand meme", "destroy_anyway"),
        ],
        "SECRET"
    ),
    "glacius_falling": NarrativeEvent(
        "URGENCE — Colonie Glacius en chute libre",
        [
            "Alerte critique : Glacius.",
            "L'Horizon Noir a desactive leurs generateurs de chaleur.",
            "Temperature : -180 degres et en baisse.",
            "12 000 habitants. Autonomie : 6 heures.",
            "Votre carburant est limite. Si vous allez a Glacius,",
            "vous ne pourrez peut-etre pas atteindre la Source.",
        ],
        [
            ("Foncer vers Glacius, sauver les habitants", "save_glacius"),
            ("Continuer vers la Source, sacrifier Glacius", "abandon_glacius"),
        ],
        "URGENCE"
    ),
}

# ── Événements additionnels (missions secondaires) ────────────────
SIDE_MISSIONS = [
    {   "name": "Relique Ancienne",
        "desc": "Un signal precede de 500 ans vient d'etre detecte.",
        "reward": 150, "data": 60,
        "outcome": "Une sonde pre-humaine. Son origine : inconnue.",
    },
    {   "name": "Flotte Fantome",
        "desc": "5 vaisseaux deriverent sans equipage vers le trou de ver.",
        "reward": 200, "data": 40,
        "outcome": "Les logs montrent qu'ils ont traverse l'Horizon.",
    },
    {   "name": "Cartographie Sombre",
        "desc": "Cartographier le bord de l'Horizon Noir.",
        "reward": 80,  "data": 100,
        "outcome": "L'Horizon n'est pas aleatoire. Il a une forme.",
    },
]

# ══════════════════════════════════════════════════════════════════
#  PARTICULES
# ══════════════════════════════════════════════════════════════════

class Particles:
    __slots__ = ['px','py','pvx','pvy','plife','pmax','pr','pg','pb','psize','_n','_cap']
    def __init__(self, cap=2000):
        self._cap = cap; self._n = 0
        self.px   = np.zeros(cap, np.float32); self.py   = np.zeros(cap, np.float32)
        self.pvx  = np.zeros(cap, np.float32); self.pvy  = np.zeros(cap, np.float32)
        self.plife= np.zeros(cap, np.float32); self.pmax = np.zeros(cap, np.float32)
        self.pr   = np.zeros(cap, np.uint8);   self.pg   = np.zeros(cap, np.uint8)
        self.pb   = np.zeros(cap, np.uint8);   self.psize= np.zeros(cap, np.float32)

    def emit(self, x, y, color, count=20, spd=(500,6000), sz=(1,4), life=(20000,90000)):
        for _ in range(min(count, self._cap - self._n)):
            i = self._n; self._n += 1
            a = random.uniform(0, math.pi*2); s = random.uniform(*spd)
            self.px[i]=x; self.py[i]=y
            self.pvx[i]=math.cos(a)*s; self.pvy[i]=math.sin(a)*s
            l = random.uniform(*life)
            self.plife[i]=l; self.pmax[i]=l
            self.pr[i]=color[0]; self.pg[i]=color[1]; self.pb[i]=color[2]
            self.psize[i]=random.uniform(*sz)

    def emit_ring(self, x, y, color, count=30, radius=40, speed=1500):
        for i in range(min(count, self._cap - self._n)):
            idx = self._n; self._n += 1
            a = i * math.pi*2/count
            self.px[idx]=x+math.cos(a)*radius; self.py[idx]=y+math.sin(a)*radius
            self.pvx[idx]=math.cos(a)*speed; self.pvy[idx]=math.sin(a)*speed
            l = random.uniform(40000,110000)
            self.plife[idx]=l; self.pmax[idx]=l
            self.pr[idx]=color[0]; self.pg[idx]=color[1]; self.pb[idx]=color[2]
            self.psize[idx]=random.uniform(1,3)

    def update(self):
        if self._n == 0: return
        n = self._n
        self.px[:n]   += self.pvx[:n] * DT_PHYS * 7e-6
        self.py[:n]   += self.pvy[:n] * DT_PHYS * 7e-6
        self.plife[:n] -= DT_PHYS * 0.9
        # Compactage
        alive = self.plife[:n] > 0
        if not np.all(alive):
            for attr in ['px','py','pvx','pvy','plife','pmax','pr','pg','pb','psize']:
                arr = getattr(self, attr); arr[:n][~alive]
                vals = arr[:n][alive]
                arr[:len(vals)] = vals
            self._n = int(alive.sum())

    def draw(self, surface, wtsc, zoom):
        if self._n == 0: return
        n = self._n
        for i in range(n):
            sx, sy = wtsc(self.px[i], self.py[i])
            if 0 <= sx < W and 0 <= sy < H:
                t = self.plife[i] / self.pmax[i]
                sz = max(1, int(self.psize[i] * t))
                c = (int(self.pr[i]*t), int(self.pg[i]*t), int(self.pb[i]*t))
                if sz <= 1:
                    try: surface.set_at((sx,sy), c)
                    except: pass
                else:
                    pygame.draw.circle(surface, c, (sx,sy), sz)

# ══════════════════════════════════════════════════════════════════
#  RENDERER
# ══════════════════════════════════════════════════════════════════

class Renderer:
    def __init__(self):
        self._gc: Dict[tuple, pygame.Surface] = {}

    def _glow_surf(self, r: int, color: tuple) -> pygame.Surface:
        key = (r, color)
        if key not in self._gc:
            s = pygame.Surface((r*2+2, r*2+2), pygame.SRCALPHA)
            for rr in range(r, 1, -3):
                t = rr / r; a = int(80 * t * t)
                c = tuple(min(255, int(cc*(0.3+0.7*t))) for cc in color)
                pygame.draw.circle(s, (*c, a), (r+1, r+1), rr)
            self._gc[key] = s
        return self._gc[key]

    def glow(self, surf, cx, cy, r, color):
        g = self._glow_surf(max(2,r), color)
        surf.blit(g, (cx - r - 1, cy - r - 1))

    def trail(self, surf, body, wtsc):
        n = len(body.trail)
        if n < 3: return
        tick = pygame.time.get_ticks() / 1000.0
        for i in range(1, n):
            f = i / n
            pulse = 0.55 + 0.45 * math.sin(tick*2 + f*5)
            c = tuple(int(cc * f * pulse) for cc in body.color)
            w = max(1, int(f * 2.2))
            p1 = wtsc(*body.trail[i-1]); p2 = wtsc(*body.trail[i])
            if (0<=p1[0]<W and 0<=p1[1]<H and 0<=p2[0]<W and 0<=p2[1]<H):
                pygame.draw.line(surf, c, p1, p2, w)

    def birth_fx(self, surf, body, sx, sy, sr):
        if body.birth >= 1.0: return
        t = body.birth; wr = int(sr * 5 * (1-t))
        if wr < 2: return
        ws = pygame.Surface((wr*2+4, wr*2+4), pygame.SRCALPHA)
        a = int(220 * t)
        pygame.draw.circle(ws, (*body.color, a), (wr+2,wr+2), wr, max(1, int(3*(1-t)+1)))
        surf.blit(ws, (sx-wr-2, sy-wr-2))

    def star(self, surf, body, sx, sy, sr):
        tick = pygame.time.get_ticks() / 1000.0
        # Rayons
        for i in range(12):
            angle = body.rotation + i * math.pi / 6 + math.sin(tick + i) * 0.04
            inner = sr * 1.05
            outer = sr * (2.1 + 0.45 * math.sin(tick*1.4 + i*0.9))
            x1 = sx + math.cos(angle)*inner; y1 = sy + math.sin(angle)*inner
            x2 = sx + math.cos(angle)*outer; y2 = sy + math.sin(angle)*outer
            rc = tuple(min(255, int(c*0.88)) for c in body.color)
            for lw, la in [(3,20),(2,55),(1,130)]:
                pygame.draw.line(surf, (*rc,la), (int(x1),int(y1)), (int(x2),int(y2)), lw)
        # Glow
        self.glow(surf, sx, sy, int(sr*(2.4+0.3*math.sin(tick*1.1))), body.color)
        # Corps
        for r in range(sr, 0, -2):
            f = r/sr; c = tuple(min(255,int(cc*(0.55+0.45*(1-f*0.25)))) for cc in body.color)
            pygame.draw.circle(surf, c, (sx,sy), r)
        # Taches solaires
        if sr > 7:
            for k in range(3):
                sa = body.rotation*2 + k*2.1
                spx = sx + int(math.cos(sa)*sr*0.28); spy = sy + int(math.sin(sa)*sr*0.28)
                dc = tuple(max(0,c-70) for c in body.color)
                pygame.draw.circle(surf, dc, (spx,spy), max(2, sr//5))
        # Highlight
        hc = tuple(min(255,c+120) for c in body.color)
        pygame.draw.circle(surf, (*hc,190), (sx-sr//3,sy-sr//3), max(2,sr//4))

    def planet(self, surf, body, sx, sy, sr):
        # Atmosphère
        for layer in range(4):
            lr = sr + (4-layer)*max(2,sr//2)
            atmo = pygame.Surface((lr*2,lr*2), pygame.SRCALPHA)
            for r in range(lr,sr,-2):
                ta = 1-(r-sr)/(lr-sr+1); a = int(18*ta*ta)
                pygame.draw.circle(atmo, (*body.color,a), (lr,lr), r)
            surf.blit(atmo, (sx-lr,sy-lr))
        # Corps
        for r in range(sr,0,-1):
            f = r/sr; c = tuple(min(255,int(cc*(0.38+0.62*f))) for cc in body.color)
            pygame.draw.circle(surf, c, (sx,sy), r)
        # Bandes
        dc = tuple(max(0,c-45) for c in body.color)
        lc = tuple(min(255,c+38) for c in body.color)
        for band in range(3):
            by = sy - sr + (band+1)*sr*2//4; bh = max(2,sr//5)
            bs = pygame.Surface((sr*2, bh*2), pygame.SRCALPHA)
            bc2 = dc if band%2==0 else lc
            pygame.draw.ellipse(bs, (*bc2,70), (0,bh//2,sr*2,bh))
            surf.blit(bs, (sx-sr, by-bh))
        # Calotte polaire
        if sr >= 8:
            pygame.draw.ellipse(surf,(200,220,255,140),(sx-sr//2,sy-sr+1,sr,sr//3))
        # Anneau optionnel
        if sum(body.color)%3==0 and sr >= 7:
            rs = pygame.Surface((sr*5,sr*3), pygame.SRCALPHA)
            rc2 = tuple(min(255,c+30) for c in body.color)
            pygame.draw.ellipse(rs,(*rc2,75),(0,sr,sr*5,sr),2)
            surf.blit(rs,(sx-sr*5//2,sy-sr*3//2))
        # Highlight
        hc = tuple(min(255,c+110) for c in body.color)
        pygame.draw.circle(surf,(*hc,170),(sx-sr//3,sy-sr//3),max(2,sr//3))

    def black_hole(self, surf, body, sx, sy, sr):
        tick = pygame.time.get_ticks() / 1000.0
        # Warp halo
        wr = sr*6; ws = pygame.Surface((wr*2,wr*2), pygame.SRCALPHA)
        for r in range(wr,sr*2,-4):
            tw = max(0, 1-(r-sr*2)/(wr-sr*2)); a=int(55*tw*tw)
            pygame.draw.circle(ws,(int(70*tw),0,int(110*tw),a),(wr,wr),r)
        surf.blit(ws,(sx-wr,sy-wr))
        # Disque d'accrétion
        ring_cols=[(255,150,25),(255,90,190),(90,170,255),(190,45,255),(255,210,90)]
        for ri in range(5):
            ra=sr*(1.9+ri*0.65); rb=sr*(0.45+ri*0.16)
            rang=tick*(38-ri*6)+ri*0.5; rc2=ring_cols[ri]; ral=115-ri*18
            rsurf=pygame.Surface((int(ra*2)+8,int(rb*2)+8),pygame.SRCALPHA)
            for lw,la in [(4,ral//3),(2,ral//2),(1,ral)]:
                pygame.draw.ellipse(rsurf,(*rc2,la),(2,int(rb)+2,int(ra*2),int(rb*2)),lw)
            rot=pygame.transform.rotate(rsurf,rang)
            surf.blit(rot,(sx-rot.get_width()//2,sy-rot.get_height()//2))
        # Halo violet pulsant
        pulse=1+0.14*math.sin(tick*3); hr=int(sr*2.6*pulse)
        hs=pygame.Surface((hr*2,hr*2),pygame.SRCALPHA)
        for r in range(hr,sr,-3):
            th=1-(r-sr)/(hr-sr+1); a=int(48*th*th)
            pygame.draw.circle(hs,(115,0,195,a),(hr,hr),r)
        surf.blit(hs,(sx-hr,sy-hr))
        # Horizon sphère noire
        pygame.draw.circle(surf,(0,0,0),(sx,sy),sr+1)
        sc=(int(38*(0.5+0.5*math.sin(tick*5))),0,int(75*(0.5+0.5*math.sin(tick*3))))
        pygame.draw.circle(surf,sc,(sx,sy),sr,2)
        # Jets polaires
        for sign in [1,-1]:
            jl = max(0, int(sr*(3.5+1.8*math.sin(tick*2))))
            for step in range(0, jl, 2):
                jx = sx + random.randint(-2,2); jy = sy+sign*step
                if 0<=jx<W and 0<=jy<H:
                    surf.set_at((jx,jy),(90,40,230))

    def asteroid(self, surf, body, sx, sy, sr):
        rng = random.Random(hash(body.name)); pts = []
        for i in range(7):
            a = body.rotation + i*math.pi*2/7; r=sr*rng.uniform(0.62,1.32)
            pts.append((int(sx+math.cos(a)*r),int(sy+math.sin(a)*r)))
        if len(pts)>2:
            pygame.draw.polygon(surf,body.color,pts)
            lc = tuple(min(255,c+55) for c in body.color)
            pygame.draw.polygon(surf,lc,pts,1)
            if sr>4:
                dc = tuple(max(0,c-55) for c in body.color)
                pygame.draw.circle(surf,dc,(sx+sr//4,sy-sr//4),max(1,sr//3))

    def station(self, surf, body, sx, sy, sr):
        tick = pygame.time.get_ticks()/1000.0
        # Corps central hexagonal
        pts=[]
        for i in range(6):
            a=body.rotation+i*math.pi/3
            pts.append((int(sx+math.cos(a)*sr),int(sy+math.sin(a)*sr)))
        pygame.draw.polygon(surf,(60,80,120),pts)
        pygame.draw.polygon(surf,body.color,pts,2)
        # Panneaux solaires
        for arm in range(3):
            a=body.rotation+arm*math.pi*2/3
            ax=sx+int(math.cos(a)*sr*2); ay=sy+int(math.sin(a)*sr*2)
            pygame.draw.line(surf,(100,120,180),(sx,sy),(ax,ay),2)
            panel_surf=pygame.Surface((sr,sr//2+2),pygame.SRCALPHA)
            pygame.draw.rect(panel_surf,(30,100,180,160),(0,0,sr,sr//2))
            panel_rot=pygame.transform.rotate(panel_surf,math.degrees(-a))
            surf.blit(panel_rot,(ax-panel_rot.get_width()//2,ay-panel_rot.get_height()//2))
        # Lumière clignotante
        if int(tick*2)%2==0:
            pygame.draw.circle(surf,(255,80,80),(sx+sr//2,sy-sr//2),3)

    def wormhole(self, surf, body, sx, sy, sr):
        tick = pygame.time.get_ticks()/1000.0
        for ring in range(6):
            r = int(sr*(1+ring*0.55))
            a_val = int(90-ring*13)
            t_col = ring/5.0
            c = (int(180*(1-t_col)+40*t_col), int(60*t_col), int(255*t_col))
            ws2=pygame.Surface((r*2,r*2),pygame.SRCALPHA)
            pygame.draw.circle(ws2,(*c,a_val),(r,r),r,max(1,3-ring//2))
            angle_off=tick*(1+ring*0.3)*(1 if ring%2==0 else -1)
            rot=pygame.transform.rotate(ws2,math.degrees(angle_off))
            surf.blit(rot,(sx-rot.get_width()//2,sy-rot.get_height()//2))
        pulse=0.5+0.5*math.sin(tick*4)
        c_inner=(int(80+120*pulse),int(20+80*pulse),int(200+55*pulse))
        pygame.draw.circle(surf,c_inner,(sx,sy),max(3,sr//2))

    def anomaly(self, surf, body, sx, sy, sr):
        """Anomalie Horizon Noir."""
        tick = pygame.time.get_ticks()/1000.0
        # Halo sombre pulsant
        pulse=1+0.2*math.sin(tick*2.5)
        for r in range(int(sr*3*pulse),sr,-4):
            t_r=1-(r-sr)/(sr*3*pulse-sr+1); a=int(70*t_r*t_r)
            c=(int(60*t_r),0,int(80*t_r))
            hs=pygame.Surface((r*2,r*2),pygame.SRCALPHA)
            pygame.draw.circle(hs,(*c,a),(r,r),r)
            surf.blit(hs,(sx-r,sy-r))
        # Tentacules chaotiques
        for arm in range(8):
            base_a=body.rotation+arm*math.pi/4
            length=sr*(2+math.sin(tick*3+arm))
            pts=[(sx,sy)]
            for step in range(1,6):
                f=step/5; wobble=math.sin(tick*4+arm*1.3+step)*0.4
                a=base_a+wobble
                pts.append((int(sx+math.cos(a)*length*f),int(sy+math.sin(a)*length*f)))
            for j in range(len(pts)-1):
                alpha_l=int(150*(1-j/5))
                pygame.draw.line(surf,(80,0,120),(pts[j][0],pts[j][1]),(pts[j+1][0],pts[j+1][1]),2)
        pygame.draw.circle(surf,(20,0,40),(sx,sy),sr)
        pygame.draw.circle(surf,(100,0,150),(sx,sy),sr,2)

    def draw_body(self, surf, body, sx, sy, sr):
        self.birth_fx(surf, body, sx, sy, sr)
        self.trail(surf, body, lambda wx,wy: (
            int((wx-self._cam_x)*self._zoom+W/2),
            int((wy-self._cam_y)*self._zoom+H/2)))
        d = { ObjType.STAR:       self.star,
              ObjType.PLANET:     self.planet,
              ObjType.BLACK_HOLE: self.black_hole,
              ObjType.ASTEROID:   self.asteroid,
              ObjType.STATION:    self.station,
              ObjType.WORMHOLE:   self.wormhole,
              ObjType.ANOMALY:    self.anomaly }
        fn = d.get(body.otype)
        if fn: fn(surf, body, sx, sy, sr)

    def set_camera(self, cx, cy, zoom):
        self._cam_x=cx; self._cam_y=cy; self._zoom=zoom

rdr = Renderer()

# ══════════════════════════════════════════════════════════════════
#  FOND — NÉBULEUSE + ÉTOILES
# ══════════════════════════════════════════════════════════════════

class Background:
    def __init__(self):
        self.nebula = self._make_nebula()
        self.stars  = self._make_stars()

    def _make_nebula(self):
        s = pygame.Surface((W,H), pygame.SRCALPHA)
        palette = [(20,0,60),(0,25,75),(55,0,38),(0,45,48),(38,18,0),(50,0,80)]
        for base in palette:
            for _ in range(random.randint(3,7)):
                cx=random.randint(0,W); cy=random.randint(0,H)
                r=random.randint(70,260)
                c=tuple(max(0,min(255,cc+random.randint(-25,55))) for cc in base)
                for rr in range(r,0,-9):
                    a=int(22*(1-rr/r)); pygame.draw.circle(s,(*c,a),(cx,cy),rr)
        return s

    def _make_stars(self):
        tints={'w':(0,0,20),'b':(-40,-40,30),'y':(20,20,-40),'r':(30,-30,-30)}
        stars=[]
        for _ in range(450):
            tint=random.choice(list(tints.keys()))
            off=tints[tint]; b=random.randint(55,245)
            c=tuple(max(0,min(255,b+o)) for o in off)
            stars.append({'x':random.randint(0,W),'y':random.randint(0,H),
                          'b':b,'c':c,'sz':random.choice([1,1,1,2,2,3]),
                          'tw':random.uniform(0,math.pi*2),
                          'tws':random.uniform(0.006,0.038)})
        return stars

    def draw(self, surf):
        surf.fill(C['bg'])
        surf.blit(self.nebula,(0,0))
        tick=pygame.time.get_ticks()/1000.0
        for s in self.stars:
            s['tw']+=s['tws']
            f=0.55+0.45*math.sin(s['tw'])
            c=tuple(min(255,int(cc*f)) for cc in s['c'])
            sz=s['sz']
            if sz==1:
                try: surf.set_at((s['x'],s['y']),c)
                except: pass
            elif sz==2:
                pygame.draw.circle(surf,c,(s['x'],s['y']),1)
            else:
                cx2,cy2=s['x'],s['y']
                pygame.draw.circle(surf,c,(cx2,cy2),2)
                for dx2,dy2 in[(-5,0),(5,0),(0,-5),(0,5)]:
                    nx,ny=cx2+dx2,cy2+dy2
                    if 0<=nx<W and 0<=ny<H:
                        try: surf.set_at((nx,ny),tuple(cc//4 for cc in c))
                        except: pass

bg_obj = None  # Initialisé après pygame.init()

# ══════════════════════════════════════════════════════════════════
#  FONT HELPER
# ══════════════════════════════════════════════════════════════════

def load_font(size, bold=False):
    for name in ["Courier New","Courier","DejaVu Sans Mono","monospace",None]:
        try:
            if name: f=pygame.font.SysFont(name,size,bold=bold)
            else:    f=pygame.font.Font(None,size+4)
            return f
        except: continue
    return pygame.font.Font(None,size+4)

# ══════════════════════════════════════════════════════════════════
#  UI HELPERS
# ══════════════════════════════════════════════════════════════════

def draw_panel(surf, rect, title="", border_col=None, alpha=200):
    if border_col is None: border_col=C['ui_border']
    panel=pygame.Surface((rect[2],rect[3]),pygame.SRCALPHA)
    panel.fill((*C['ui_bg'],alpha))
    surf.blit(panel,(rect[0],rect[1]))
    pygame.draw.rect(surf,border_col,(rect[0],rect[1],rect[2],rect[3]),1)

def draw_bar(surf, x, y, w, h, val, mx, col_full, col_empty=(30,30,40), label=""):
    pygame.draw.rect(surf,col_empty,(x,y,w,h))
    filled=max(0,int(w*val/max(1,mx)))
    pygame.draw.rect(surf,col_full,(x,y,filled,h))
    pygame.draw.rect(surf,(60,80,100),(x,y,w,h),1)

def draw_text(surf, txt, x, y, font, color=None, shadow=False):
    if color is None: color=C['white']
    if shadow:
        s=font.render(txt,True,(0,0,0)); surf.blit(s,(x+1,y+1))
    t=font.render(txt,True,color); surf.blit(t,(x,y))
    return t.get_width()

# ══════════════════════════════════════════════════════════════════
#  JEU PRINCIPAL
# ══════════════════════════════════════════════════════════════════

class HorizonNoir:
    def __init__(self):
        # ── Fonts ──
        self.f_title  = load_font(28,True)
        self.f_big    = load_font(20,True)
        self.f_med    = load_font(15)
        self.f_small  = load_font(12)

        self.bodies: List[Body] = []
        self.parts   = Particles(3000)
        self.ship    = Ship(x=0.0, y=0.0)

        # Caméra
        self.cam_x=0.0; self.cam_y=0.0; self.zoom=0.000001
        self.follow_ship=False

        # Interaction placement
        self.sel_type  = ObjType.PLANET
        self.dragging  = False
        self.drag_start= None; self.drag_pos=None
        self.panning   = False; self.pan_start=None; self.cam_start=None

        # Simulation
        self.paused    = False
        self.sim_time  = 0.0
        self.frame     = 0

        # Messages
        self.msg=""; self.msg_timer=0
        self.msg_sub=""

        # Scénario
        self.story_phase=0          # 0=intro,1=exploration,2=origin,3=ending
        self.active_event: Optional[NarrativeEvent]=None
        self.story_flags: Dict[str,bool]={}
        self.horizon_intensity=0.0  # 0→1 danger croissant
        self.solar_storm_timer=0
        self.breakdown_timer=0
        self.scan_cooldown=0
        self.quests_done=0

        # UI
        self.show_intro=True
        self.show_ship_panel=True
        self.show_narrative=False
        self.show_shop=False
        self.show_quest_log=False
        self.show_minimap=True
        self.game_over=False
        self.game_over_reason=""
        self._shop_rects=[]
        self._choice_rects=[]

        # Pré-génération du système stellaire
        self._generate_system()

    # ── Utilitaires caméra ────────────────────────────────────────
    def wtsc(self,wx,wy):
        return (int((wx-self.cam_x)*self.zoom+W/2),
                int((wy-self.cam_y)*self.zoom+H/2))
    def stow(self,sx,sy):
        return ((sx-W/2)/self.zoom+self.cam_x,
                (sy-H/2)/self.zoom+self.cam_y)

    # ── Génération du système ─────────────────────────────────────
    def _generate_system(self):
        """Crée un système multi-étoiles avec colonies, stations, anomalies."""
        cx=cy=0.0

        # Étoile centrale — Solaris Prime
        self.bodies.append(Body(cx,cy,0,0,mass=2.2e30,otype=ObjType.STAR,
            name="Solaris Prime",radius=28,color=(255,200,55),trail_max=60))

        # Planètes habitées
        planet_data=[
            ("Nova Kepler",  1.4e11, 12000, (80,160,255),  True,  "OSS",   120),
            ("Veridian",     2.5e11, 9500,  (50,210,100),  True,  "Indep", 80),
            ("Durata",       4.0e11, 7200,  (200,150,80),  False, "",      0),
            ("Glacius",      6.5e11, 5800,  (150,200,240), True,  "Indep", 60),
            ("Ignis",        1.1e11, 14000, (255,120,50),  False, "",      0),
        ]
        for name,dist,v_orb,col,colony,faction,hp in planet_data:
            angle=random.uniform(0,math.pi*2)
            px=cx+math.cos(angle)*dist; py=cy+math.sin(angle)*dist
            vx=-math.sin(angle)*v_orb;  vy= math.cos(angle)*v_orb
            b=Body(px,py,vx,vy,mass=6e24,otype=ObjType.PLANET,
                   name=name,radius=11,color=col,trail_max=200,
                   scannable=True,data_reward=random.randint(10,30),
                   birth=0.0)
            if colony:
                b.colony_hp=hp; b.colony_name=name; b.faction=faction
            self.bodies.append(b)

        # Station OSS
        dist_s=3.0e11; angle_s=random.uniform(0,math.pi*2)
        sx2=cx+math.cos(angle_s)*dist_s; sy2=cy+math.sin(angle_s)*dist_s
        vx2=-math.sin(angle_s)*8000;    vy2=math.cos(angle_s)*8000
        self.bodies.append(Body(sx2,sy2,vx2,vy2,mass=1e20,otype=ObjType.STATION,
            name="Station OSS Aleph",radius=14,color=C['cyan'],trail_max=120,
            scannable=True,data_reward=50,faction="OSS",birth=0.0))

        # Astéroïdes
        for i in range(8):
            dist_a=random.uniform(3.2e11,5.0e11); angle_a=random.uniform(0,math.pi*2)
            v_a=random.uniform(5000,9000)
            ax2=cx+math.cos(angle_a)*dist_a; ay2=cy+math.sin(angle_a)*dist_a
            avx=-math.sin(angle_a)*v_a+random.uniform(-1000,1000)
            avy= math.cos(angle_a)*v_a+random.uniform(-1000,1000)
            self.bodies.append(Body(ax2,ay2,avx,avy,mass=1e20,otype=ObjType.ASTEROID,
                name=f"Ast-{i+1}",radius=5,color=C['gray'],trail_max=80,birth=0.0))

        # Trou de ver instable
        dist_w=8.0e11; angle_w=random.uniform(0,math.pi*2)
        wx2=cx+math.cos(angle_w)*dist_w; wy2=cy+math.sin(angle_w)*dist_w
        self.bodies.append(Body(wx2,wy2,0,0,mass=0,otype=ObjType.WORMHOLE,
            name="Trou de Ver Kappa",radius=16,color=(120,40,255),trail_max=30,
            scannable=True,data_reward=80,birth=0.0))

        # Anomalie Horizon Noir (cachée loin)
        dist_h=1.4e12; angle_h=random.uniform(0,math.pi*2)
        hx=cx+math.cos(angle_h)*dist_h; hy=cy+math.sin(angle_h)*dist_h
        self.bodies.append(Body(hx,hy,0,0,mass=0,otype=ObjType.ANOMALY,
            name="Horizon Noir — Source",radius=22,color=C['purple'],trail_max=20,
            scannable=True,data_reward=200,birth=0.0))

        # Position initiale du vaisseau près de la station
        self.ship.x=sx2+5e10; self.ship.y=sy2+5e10
        self.cam_x=self.ship.x; self.cam_y=self.ship.y

    # ── Physique ──────────────────────────────────────────────────
    def _gravity(self):
        alive=[b for b in self.bodies if b.alive and b.mass>0]
        n=len(alive)
        for i in range(n):
            ax=ay=0.0
            for j in range(n):
                if i==j: continue
                dx=alive[j].x-alive[i].x; dy=alive[j].y-alive[i].y
                dist2=dx*dx+dy*dy
                if dist2<1e10: continue
                cd=((alive[i].radius+alive[j].radius)*1e6/self.zoom)**2
                if dist2<cd:
                    self._collide(alive[i],alive[j]); continue
                dist=math.sqrt(dist2); f=G*alive[j].mass/dist2
                ax+=f*dx/dist; ay+=f*dy/dist
            alive[i].vx+=ax*DT_PHYS; alive[i].vy+=ay*DT_PHYS

    def _collide(self,a,b):
        light,heavy=(a,b) if a.mass<=b.mass else (b,a)
        # Les stations et anomalies ne sont pas détruites par collision
        if heavy.otype in(ObjType.STATION,ObjType.ANOMALY,ObjType.WORMHOLE): return
        if light.otype in(ObjType.STATION,ObjType.ANOMALY,ObjType.WORMHOLE): return
        light.alive=False
        self.parts.emit(light.x,light.y,(255,200,50),count=60,spd=(1500,12000),sz=(1,5))
        self.parts.emit_ring(light.x,light.y,light.color,count=40)
        audio_eng.play('collision')
        total=heavy.mass+light.mass*0.1
        heavy.vx=(heavy.mass*heavy.vx+light.mass*light.vx)/total
        heavy.vy=(heavy.mass*heavy.vy+light.mass*light.vy)/total

    # ── Vaisseau ──────────────────────────────────────────────────
    # ── Boutique d'ameliorations ──────────────────────────────────
    UPGRADES = [
        {"id":"hull1",     "name":"Blindage Mk.II",      "cost":200, "desc":"+40 PV max",        "req":None},
        {"id":"hull2",     "name":"Blindage Mk.III",     "cost":400, "desc":"+60 PV max",        "req":"hull1"},
        {"id":"shield1",   "name":"Bouclier Ameliore",   "cost":180, "desc":"+40 bouclier max",  "req":None},
        {"id":"shield2",   "name":"Bouclier Adamantin",  "cost":360, "desc":"+60 bouclier max",  "req":"shield1"},
        {"id":"engine1",   "name":"Propulseur Ionique",  "cost":250, "desc":"Vitesse +25%",      "req":None},
        {"id":"engine2",   "name":"Propulseur Plasma",   "cost":500, "desc":"Vitesse +50%",      "req":"engine1"},
        {"id":"scanner1",  "name":"Scanner Longue Portee","cost":150,"desc":"Portee x1.5",      "req":None},
        {"id":"scanner2",  "name":"Scanner Quantique",   "cost":350, "desc":"Portee x2.5",      "req":"scanner1"},
        {"id":"hyperdrive","name":"Hyperdrive",           "cost":600, "desc":"Saut rapide [H]",  "req":None},
        {"id":"ai",        "name":"IA de Combat",         "cost":450, "desc":"Pannes -50%, auto-rep","req":None},
        {"id":"weapons",   "name":"Armement Defensif",   "cost":350, "desc":"Repousse pirates",  "req":None},
        {"id":"tank",      "name":"Reservoir Etendu",    "cost":200, "desc":"Carburant x2",      "req":None},
    ]

    def buy_upgrade(self, uid):
        upg = next((u for u in self.UPGRADES if u["id"]==uid), None)
        if not upg: return False
        if upg["req"] and upg["req"] not in self.ship_upgrades:
            self.set_msg("Prerequis manquant: "+upg["req"],140,C["warn"]); return False
        if uid in self.ship_upgrades:
            self.set_msg("Amelioration deja installee.",120,C["dim"]); return False
        if self.ship.credits < upg["cost"]:
            self.set_msg(f"Credits insuffisants ({upg['cost']} req.).",140,C["warn"]); return False
        self.ship.credits -= upg["cost"]
        self.ship_upgrades.add(uid)
        self._apply_upgrade(uid)
        self.set_msg(f"[OK] {upg['name']} installe !",180,C["green"])
        audio_eng.play("repair")
        self.ship.add_log(f"Upgrade: {upg['name']}")
        return True

    def _apply_upgrade(self, uid):
        s = self.ship
        if   uid=="hull1":     s.hull_max+=40; s.hull=min(s.hull+40,s.hull_max); s.hull_level=1
        elif uid=="hull2":     s.hull_max+=60; s.hull=min(s.hull+60,s.hull_max); s.hull_level=2
        elif uid=="shield1":   s.shield_max+=40; s.shield=min(s.shield+40,s.shield_max); s.shield_level=1
        elif uid=="shield2":   s.shield_max+=60; s.shield=min(s.shield+60,s.shield_max); s.shield_level=2
        elif uid=="engine1":   s.engine_level=1
        elif uid=="engine2":   s.engine_level=2
        elif uid=="scanner1":  s.scanner_level=1
        elif uid=="scanner2":  s.scanner_level=2
        elif uid=="hyperdrive":s.has_hyperdrive=True
        elif uid=="ai":        s.has_ai=True
        elif uid=="weapons":   s.has_weapons=True
        elif uid=="tank":      s.fuel_max=200.0; s.fuel=min(s.fuel+100,s.fuel_max)

    def hyperdrive_jump(self, tx, ty):
        if not self.ship.has_hyperdrive:
            self.set_msg("Hyperdrive non installe !",120,C["warn"]); return
        if self.ship.hyperdrive_cooldown>0:
            self.set_msg(f"Hyperdrive en recharge ({self.ship.hyperdrive_cooldown//60}s)...",120,C["dim"]); return
        if self.ship.fuel<20:
            self.set_msg("Carburant insuffisant pour le saut !",140,C["warn"]); return
        self.ship.x=tx; self.ship.y=ty
        self.ship.vx=0;  self.ship.vy=0
        self.ship.fuel=max(0,self.ship.fuel-20)
        self.ship.hyperdrive_cooldown=300
        self.ship.jumps_done+=1
        self.cam_x=tx; self.cam_y=ty
        self.parts.emit(tx,ty,C["cyan"],count=80,spd=(2000,12000),sz=(1,5))
        self.parts.emit_ring(tx,ty,(180,80,255),count=60,radius=80,speed=3000)
        audio_eng.play("hyperdrive")
        self.set_msg("Saut hyperdrive reussi !",160,C["cyan"])
        self.ship.add_log(f"Saut vers ({tx:.1e},{ty:.1e})")

    def _update_ship(self):
        keys=pygame.key.get_pressed()
        spd=3e9*self.ship.speed_mult
        moved=False
        if not self.ship.engine_broken:
            if keys[pygame.K_UP]    or keys[pygame.K_w]:
                self.ship.vy -= spd; self.ship.fuel=max(0,self.ship.fuel-0.005); moved=True
            if keys[pygame.K_DOWN]  or keys[pygame.K_s]:
                self.ship.vy += spd; self.ship.fuel=max(0,self.ship.fuel-0.005); moved=True
            if keys[pygame.K_LEFT]  or keys[pygame.K_a]:
                self.ship.vx -= spd; self.ship.fuel=max(0,self.ship.fuel-0.005); moved=True
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                self.ship.vx += spd; self.ship.fuel=max(0,self.ship.fuel-0.005); moved=True
        # Allocation energie clavier
        if keys[pygame.K_e]:
            self.ship.eng_engine=min(100,self.ship.eng_engine+1)
            excess=max(0,self.ship.eng_engine+self.ship.eng_shield+self.ship.eng_sensor-100)
            self.ship.eng_shield=max(0,self.ship.eng_shield-excess)
        elif keys[pygame.K_q] and not (keys[pygame.K_LEFT] or keys[pygame.K_a]):
            self.ship.eng_shield=min(100,self.ship.eng_shield+1)
            excess=max(0,self.ship.eng_engine+self.ship.eng_shield+self.ship.eng_sensor-100)
            self.ship.eng_engine=max(0,self.ship.eng_engine-excess)
        # Hyperdrive cooldown
        if self.ship.hyperdrive_cooldown>0:
            self.ship.hyperdrive_cooldown=max(0,self.ship.hyperdrive_cooldown-1)
        if self.ship.has_hyperdrive and self.ship.hyperdrive_cooldown==0:
            self.ship.hyperdrive_charge=min(1.0,self.ship.hyperdrive_charge+0.002)
        # IA auto-reparation
        if self.ship.has_ai and self.frame%600==0:
            if self.ship.engine_broken or self.ship.scanner_broken or self.ship.shield_broken:
                self.ship.engine_broken=False
                self.ship.scanner_broken=False
                self.ship.shield_broken=False
                self.set_msg("IA : auto-reparation.",140,C["purple"])
                audio_eng.play("repair")
        # Fuel epuise
        if self.ship.fuel<=0 and moved:
            self.ship.engine_broken=True
            if self.frame%120==0:
                self.set_msg("CARBURANT EPUISE — Moteur a l arret !",160,C["red"])
        self.ship.x+=self.ship.vx*DT_PHYS*0.0001
        self.ship.y+=self.ship.vy*DT_PHYS*0.0001
        self.ship.vx*=0.97; self.ship.vy*=0.97
        self.ship.regen()
        if self.follow_ship:
            self.cam_x=self.ship.x; self.cam_y=self.ship.y


    def _scan(self, silent=False):
        if self.scan_cooldown>0 or not self.ship.has_scanner or self.ship.scanner_broken:
            if not silent: self.set_msg("Scanner indisponible !",100,C['warn'])
            return
        self.scan_cooldown = 120 if self.ship.has_ai else 180
        scanned_any=False
        sx,sy=self.ship.x,self.ship.y
        sr=self.ship.effective_scanner_range/self.zoom*1e6
        for b in self.bodies:
            if b.scanned or not b.scannable: continue
            dist=math.hypot(b.x-sx,b.y-sy)
            if dist<sr*1.5e10:
                b.scanned=True
                self.ship.data+=b.data_reward
                self.ship.total_scans+=1
                self.parts.emit(b.x,b.y,C['cyan'],count=30,spd=(500,3000))
                if not silent:
                    self.set_msg(f"Scan: {b.name}  +{b.data_reward} donnees",160,C['cyan'])
                    audio_eng.play('scan')
                scanned_any=True
                self.ship.add_log(f"Scanne: {b.name} (+{b.data_reward}dt)")
                if b.otype==ObjType.WORMHOLE and not self.story_flags.get('wormhole_event'):
                    self.story_flags['wormhole_event']=True
                    self._trigger_event('wormhole_found')
                elif b.otype==ObjType.ANOMALY and not self.story_flags.get('origin_event'):
                    self.story_flags['origin_event']=True
                    self.story_phase=2
                    self._trigger_event('origin_found')
                elif b.otype==ObjType.STATION and not self.story_flags.get('station_scan'):
                    self.story_flags['station_scan']=True
                    self.ship.credits+=25
                    if not silent: self.set_msg(f"Station scannee ! +25 credits.",160,C['cyan'])
        if not scanned_any and not silent:
            self.set_msg("Aucun objet a portee du scanner.",100,C['dim'])

    def _trigger_event(self, key: str):
        ev=STORY_EVENTS.get(key)
        if ev:
            self.active_event=ev; self.show_narrative=True
            audio_eng.play('narrative')

    def _handle_choice(self, choice_key: str):
        self.show_narrative=False
        self._choice_rects=[]
        sf=self.story_flags

        # ── Choix principaux ──────────────────────────────────────
        if   choice_key=="mission_start":
            self.story_phase=1
            self.set_msg("Mission activee. Explorez le systeme !",200,C['green'])

        elif choice_key=="save_nova":
            sf['nova_saved']=True; self.ship.credits+=30; self.ship.colonies_saved+=1
            self.set_msg("+30 credits. Nova Kepler sauvee.",180,C['green'])
            audio_eng.play('repair')
            for b in self.bodies:
                if b.colony_name=="Nova Kepler": b.colony_hp=min(120,b.colony_hp+40)
        elif choice_key=="ignore_nova":
            sf['nova_ignored']=True; self.ship.colonies_abandoned+=1
            self.set_msg("Nova Kepler abandonnee...",160,C['warn'])
            for b in self.bodies:
                if b.colony_name=="Nova Kepler": b.colony_hp=max(0,b.colony_hp-30)

        elif choice_key=="enter_wormhole":
            sf['wormhole_entered']=True
            if random.random()<0.67:
                self.set_msg("Traversee reussie ! +50 donnees.",200,C['cyan'])
                self.ship.data+=50
                if not sf.get('oss_betrayal_event') and self.ship.data>=80:
                    sf['oss_betrayal_event']=True
                    pygame.time.set_timer(pygame.USEREVENT+2,4000)
            else:
                dmg=random.randint(20,40)
                self.ship.take_damage(dmg)
                self.set_msg(f"Instabilite ! -{dmg} coque.",180,C['red'])
                audio_eng.play('alert')
        elif choice_key=="scan_wormhole":
            self.ship.data+=40
            self.set_msg("Scan securise. +40 donnees.",160,C['cyan'])

        elif choice_key in("trust_oss","investigate_faction","stay_neutral"):
            sf['faction_choice']=choice_key
            msgs={"trust_oss":"Vous faites confiance a l'OSS. Pour l'instant.",
                  "investigate_faction":"Vous enquetez sur la faction rebelle. Prudence.",
                  "stay_neutral":"Vous restez neutre. Les deux factions vous surveillent."}
            self.set_msg(msgs[choice_key],200,C['info'])
            # La trahison OSS peut etre revelee plus tard
            if choice_key=="investigate_faction" and not sf.get('oss_betrayal_event'):
                sf['oss_betrayal_event']=True
                pygame.time.set_timer(pygame.USEREVENT+2,5000)

        elif choice_key=="destroy_gen":
            self.story_phase=3; self._trigger_event('ending_peace')
            audio_eng.play('victory')
        elif choice_key=="capture_gen":
            self.story_phase=3; self._trigger_event('ending_control')
            audio_eng.play('victory')
        elif choice_key=="sacrifice_gen":
            self.story_phase=3; self._trigger_event('ending_sacrifice')
            audio_eng.play('victory')

        elif choice_key=="restart":
            self.__init__(); return

        # ── Tempete solaire ───────────────────────────────────────
        elif choice_key=="storm_shield":
            self.ship.energy=max(0,self.ship.energy-20)
            self.ship.shield=min(self.ship.shield_max,self.ship.shield+15)
            self.set_msg("Boucliers max actives. Dommages reduits.",150,C['cyan'])
        elif choice_key=="storm_hide":
            self.set_msg("Vous vous abritez. Tempete evitee.",150,C['green'])
        elif choice_key=="storm_ignore":
            dmg=random.randint(15,30); self.ship.take_damage(dmg)
            self.set_msg(f"Tempete traversee. -{dmg} coque.",150,C['warn'])
            audio_eng.play('alert')

        # ── Mission station ───────────────────────────────────────
        elif choice_key=="accept_relay_mission":
            sf['relay_mission']=True; self.ship.credits+=100
            self.set_msg("+100 credits. Mission relais acceptee.",180,C['gold'])
            audio_eng.play('scan')
        elif choice_key=="ask_relay_info":
            self.set_msg("L'OSS transmet les specs techniques. +20 donnees.",150,C['info'])
            self.ship.data+=20

        # ── Cristaux Veridian ─────────────────────────────────────
        elif choice_key=="fight_pirates":
            dmg=random.randint(10,25); self.ship.take_damage(dmg)
            self.ship.data+=80; self.ship.credits+=60
            self.ship.colonies_saved+=1
            self.set_msg(f"Pirates repousses ! -{dmg} coque. +80 donnees.",200,C['green'])
            audio_eng.play('collision')
            for b in self.bodies:
                if b.colony_name=="Veridian": b.colony_hp=min(80,b.colony_hp+30)
        elif choice_key=="bribe_pirates":
            if self.ship.credits>=500:
                self.ship.credits-=500; self.ship.data+=80; self.ship.colonies_saved+=1
                self.set_msg("Pirates payes. Cristaux recuperes. +80 donnees.",180,C['cyan'])
                for b in self.bodies:
                    if b.colony_name=="Veridian": b.colony_hp=min(80,b.colony_hp+20)
            else:
                self.set_msg("Credits insuffisants ! Les pirates attaquent.",160,C['red'])
                self.ship.take_damage(20); audio_eng.play('alert')
        elif choice_key=="stealth_crystals":
            if random.random()<0.6:
                self.ship.data+=80
                self.set_msg("Mission furtive reussie ! +80 donnees.",180,C['green'])
            else:
                dmg=random.randint(15,30); self.ship.take_damage(dmg)
                self.set_msg(f"Repere ! -{dmg} coque.",160,C['warn'])
                audio_eng.play('alert')

        # ── Trahison OSS ──────────────────────────────────────────
        elif choice_key=="expose_oss":
            sf['oss_exposed']=True
            self.set_msg("Transmission publique envoyee. L'OSS vous traque.",200,C['warn'])
            audio_eng.play('alert')
        elif choice_key=="blackmail_oss":
            sf['oss_blackmail']=True; self.ship.credits+=300
            self.ship.has_hyperdrive=True
            self.set_msg("+300 credits. Hyperdrive debloque. L'OSS coopere... pour l'instant.",220,C['gold'])
            audio_eng.play('hyperdrive')
        elif choice_key=="destroy_anyway":
            sf['destroy_anyway']=True
            self.set_msg("Cap sur la Source. Quoi qu'il en coute.",180,C['cyan'])

        # ── Glacius ───────────────────────────────────────────────
        elif choice_key=="save_glacius":
            self.ship.fuel=max(0,self.ship.fuel-35)
            self.ship.credits+=80; self.ship.colonies_saved+=1
            self.set_msg("Glacius sauvee. -35 carburant. +80 credits.",200,C['green'])
            audio_eng.play('repair')
            for b in self.bodies:
                if b.colony_name=="Glacius": b.colony_hp=60
        elif choice_key=="abandon_glacius":
            self.ship.colonies_abandoned+=1
            self.set_msg("Glacius perdue. Vous accelerez vers la Source.",180,C['warn'])
            for b in self.bodies:
                if b.colony_name=="Glacius": b.colony_hp=0

        # ── Final avec 3e option sacrifice ────────────────────────
        if choice_key in ("destroy_gen","capture_gen","destroy_anyway") and self.story_phase<3:
            pass  # Déjà traité

        # Post-traitement universel
        if sf.get('wormhole_entered') and not sf.get('faction_event_shown') and sf.get('faction_event'):
            sf['faction_event_shown']=True

    # ── Événements scénaristiques dynamiques ──────────────────────
    def _scenario_tick(self):
        self.frame+=1
        # Horizon Noir s'intensifie avec le temps (200 jours pour max)
        self.horizon_intensity=min(1.0, self.sim_time/(86400*200))

        # ── Dommages de l'Horizon aux colonies ────────────────────
        for b in self.bodies:
            if b.colony_hp>0 and b.alive:
                if random.random()<0.0006*self.horizon_intensity:
                    b.colony_hp=max(0,b.colony_hp-1)
                    if b.colony_hp==0:
                        self.set_msg(f"! Colonie {b.colony_name} perdue !",240,C['red'])
                        audio_eng.play('alert')
                        self.parts.emit(b.x,b.y,C['red'],count=50)
                        self.ship.colonies_abandoned+=1

        # ── Tempetes solaires narratives ──────────────────────────
        self.solar_storm_timer=max(0,self.solar_storm_timer-1)
        if self.solar_storm_timer==0 and random.random()<0.0015 and self.story_phase>=1:
            self.solar_storm_timer=random.randint(400,800)
            if not self.story_flags.get('storm_shown'):
                self.story_flags['storm_shown']=True
                self._trigger_event('storm_event')
            else:
                # Tempete simple sans popup
                self.set_msg("! Tempete solaire — Boucliers sollicites !",180,C['warn'])
                audio_eng.play('alert')
                self.ship.take_damage(random.randint(3,10))

        # ── Pannes pres de l'Horizon ──────────────────────────────
        ship_sx,ship_sy=self.wtsc(self.ship.x,self.ship.y)
        near_horizon=False
        for b in self.bodies:
            if b.otype==ObjType.ANOMALY:
                bsx,bsy=self.wtsc(b.x,b.y)
                if math.hypot(ship_sx-bsx,ship_sy-bsy)<420:
                    near_horizon=True
        if near_horizon:
            self.breakdown_timer=max(0,self.breakdown_timer-1)
            if self.breakdown_timer==0 and random.random()<0.004:
                self.breakdown_timer=random.randint(280,650)
                which=random.choice(['engine','scanner','shield'])
                if which=='engine':
                    self.ship.engine_broken=True
                    self.set_msg("! MOTEUR EN PANNE !",220,C['red'])
                elif which=='scanner':
                    self.ship.scanner_broken=True
                    self.set_msg("! SCANNER EN PANNE !",220,C['red'])
                else:
                    self.ship.shield_broken=True
                    self.set_msg("! BOUCLIER EN PANNE !",220,C['red'])
                audio_eng.play('alert')
            # Dommages passifs pres de l'Horizon
            if random.random()<0.001*self.horizon_intensity:
                self.ship.take_damage(1)

        # ── Declenchements narratifs automatiques ─────────────────
        sf=self.story_flags
        t=self.sim_time

        # Phase 1 : contact Nova Kepler apres 5 jours
        if self.story_phase==1 and not sf.get('nova_event') and t>86400*5:
            sf['nova_event']=True; self._trigger_event('colony_nova')

        # Phase 1 : contact station OSS apres 8 jours
        if self.story_phase>=1 and not sf.get('station_event') and t>86400*8:
            sf['station_event']=True; self._trigger_event('station_contact')

        # Phase 1 : Veridian apres 15 jours
        if self.story_phase>=1 and not sf.get('veridian_event') and t>86400*15:
            sf['veridian_event']=True; self._trigger_event('veridian_contact')

        # Faction : quand data>=100 OU wormhole traversee
        if self.story_phase>=1 and not sf.get('faction_event') and self.ship.data>=100:
            sf['faction_event']=True; self._trigger_event('faction_horizon')

        # Trahison OSS : timer USEREVENT+2
        # (deja gere via handle_events)

        # Glacius en danger : quand horizon>=60% et pas encore montre
        if self.story_phase>=1 and not sf.get('glacius_event') and self.horizon_intensity>=0.6:
            sf['glacius_event']=True; self._trigger_event('glacius_falling')

        # Origin event : quand data>=200 et phase 1
        if self.story_phase==1 and not sf.get('origin_auto') and self.ship.data>=200:
            sf['origin_auto']=True; self.story_phase=2
            self._trigger_event('origin_found')

        # Reveal trahison OSS si option choisie
        if not sf.get('oss_betrayal_shown') and sf.get('oss_betrayal_triggered'):
            sf['oss_betrayal_shown']=True; self._trigger_event('oss_betrayal')

        # Fin si toutes colonies perdues
        colonies=[(b.colony_hp,b.colony_name) for b in self.bodies if b.colony_name]
        if colonies and all(hp==0 for hp,_ in colonies) and not self.game_over and self.story_phase<3:
            self.game_over=True
            self.game_over_reason="Toutes les colonies ont ete perdues. L'humanite recule dans ses etoiles."
            audio_eng.play('game_over')

        # Game over si vaisseau detruit
        if not self.ship.alive and not self.game_over:
            self.game_over=True
            self.game_over_reason="Votre vaisseau a ete detruit par l'Horizon Noir."
            audio_eng.play('game_over')

    # ── Ajout d'objet ─────────────────────────────────────────────
    def add_body(self, wx, wy, vx=0.0, vy=0.0):
        cfgs={
            ObjType.PLANET:    dict(mass=6e24,radius=11,
                color=random.choice([(80,160,255),(50,220,100),(0,200,200),(150,100,255)]),
                name=f"Planète-{len(self.bodies)+1}",trail_max=220),
            ObjType.STAR:      dict(mass=2e30,radius=24,
                color=random.choice([(255,200,50),(255,150,30),(255,255,150)]),
                name=f"Étoile-{len(self.bodies)+1}",trail_max=80),
            ObjType.BLACK_HOLE:dict(mass=1e32,radius=19,color=C['purple'],
                name=f"TN-{len(self.bodies)+1}",trail_max=40),
            ObjType.ASTEROID:  dict(mass=1e20,radius=5,
                color=C['gray'],name=f"Ast-{len(self.bodies)+1}",trail_max=100),
            ObjType.STATION:   dict(mass=1e20,radius=14,color=C['cyan'],
                name=f"Station-{len(self.bodies)+1}",trail_max=120),
            ObjType.WORMHOLE:  dict(mass=0,radius=16,color=(120,40,255),
                name=f"Trou de Ver",trail_max=30),
        }
        cfg=cfgs.get(self.sel_type,cfgs[ObjType.PLANET])
        b=Body(wx,wy,vx,vy,otype=self.sel_type,birth=0.0,**cfg)
        self.bodies.append(b)
        self.parts.emit(wx,wy,cfg['color'],count=40,spd=(1000,8000))
        self.parts.emit_ring(wx,wy,cfg['color'],count=30)
        sm={ObjType.PLANET:'place_planet',ObjType.STAR:'place_star',
            ObjType.BLACK_HOLE:'place_bh',ObjType.ASTEROID:'place_asteroid',
            ObjType.STATION:'place_planet',ObjType.WORMHOLE:'place_bh'}
        audio_eng.play(sm.get(self.sel_type,'place_planet'))

    def set_msg(self, msg, frames=180, color=None):
        self.msg=msg; self.msg_timer=frames
        self.msg_color=color if color else C['white']

    # ── UPDATE ────────────────────────────────────────────────────
    def update(self):
        if self.paused or self.game_over or self.show_narrative or self.show_intro: return
        self.sim_time+=DT_PHYS
        self._gravity()
        for b in self.bodies:
            if b.alive:
                b.x+=b.vx*DT_PHYS; b.y+=b.vy*DT_PHYS; b.update()
        self.bodies=[b for b in self.bodies if b.alive or b.otype in
                     (ObjType.STATION,ObjType.WORMHOLE,ObjType.ANOMALY)]
        self.parts.update()
        self._update_ship()
        self._update_hyperdrive()
        self._ai_tick()
        self._scenario_tick()
        audio_eng.update(any(b.otype==ObjType.ANOMALY for b in self.bodies))
        if self.scan_cooldown>0: self.scan_cooldown-=1
        if self.msg_timer>0:     self.msg_timer-=1

    # ══════════════════════════════════════════════════════════════
    #  RENDU
    # ══════════════════════════════════════════════════════════════

    def _draw_ship(self, surf):
        sx,sy=self.wtsc(self.ship.x,self.ship.y)
        if 0<=sx<W and 0<=sy<H:
            tick=pygame.time.get_ticks()/1000.0
            # Triangle directionnel
            heading=math.atan2(self.ship.vy,self.ship.vx) if (self.ship.vx or self.ship.vy) else 0
            pts=[]
            for ang_off,dist in [(0,14),(2.4,7),(math.pi,9),(3.88,7)]:
                a=heading+ang_off
                pts.append((int(sx+math.cos(a)*dist),int(sy+math.sin(a)*dist)))
            col=C['cyan'] if not self.ship.engine_broken else C['warn']
            pygame.draw.polygon(surf,col,pts[:3])
            pygame.draw.polygon(surf,tuple(min(255,c+60) for c in col),pts[:3],1)
            # Trainée moteur
            trail_a=heading+math.pi
            for i in range(1,6):
                tx=sx+int(math.cos(trail_a)*i*4)+random.randint(-1,1)
                ty=sy+int(math.sin(trail_a)*i*4)+random.randint(-1,1)
                r=max(1,5-i); a=int(160-i*28)
                tc=(255,int(120-i*15),0)
                if 0<=tx<W and 0<=ty<H:
                    pygame.draw.circle(surf,tc,(tx,ty),r)
            # Bouclier visuel
            if self.ship.shield>0 and not self.ship.shield_broken:
                sa=int(30*self.ship.shield/self.ship.shield_max)
                ss=pygame.Surface((32,32),pygame.SRCALPHA)
                pygame.draw.circle(ss,(80,160,255,sa),(16,16),14)
                surf.blit(ss,(sx-16,sy-16))
            # Scanner range
            if self.ship.has_scanner and not self.ship.scanner_broken and self.scan_cooldown<20:
                scan_px=int(self.ship.scanner_range)
                ss=pygame.Surface((scan_px*2,scan_px*2),pygame.SRCALPHA)
                pygame.draw.circle(ss,(0,180,255,15),(scan_px,scan_px),scan_px)
                pygame.draw.circle(ss,(0,180,255,40),(scan_px,scan_px),scan_px,1)
                surf.blit(ss,(sx-scan_px,sy-scan_px))

    def _draw_bodies(self, surf):
        rdr.set_camera(self.cam_x,self.cam_y,self.zoom)
        for body in self.bodies:
            sx,sy=self.wtsc(body.x,body.y)
            sr=max(3,int(body.radius*self.zoom*1e6))
            if -sr*4<=sx<W+sr*4 and -sr*4<=sy<H+sr*4:
                rdr.draw_body(surf,body,sx,sy,sr)
                # Label
                if sr>5:
                    lbl=self.f_small.render(body.name,True,(180,200,230))
                    surf.blit(lbl,(sx+sr+3,sy-7))
                # Indicateur colonie
                if body.colony_hp>0:
                    bar_w=max(20,sr*2); bar_h=4
                    bx=sx-bar_w//2; by=sy-sr-10
                    draw_bar(surf,bx,by,bar_w,bar_h,body.colony_hp,
                             120,(50,220,100),(120,30,30))
                    faction_col={'OSS':C['cyan'],'Indep':C['green']}.get(body.faction,C['gray'])
                    ft=self.f_small.render(body.faction,True,faction_col)
                    surf.blit(ft,(sx-ft.get_width()//2,by-12))
                # Étoile scannée
                if body.scanned:
                    pygame.draw.circle(surf,C['cyan'],(sx+sr+2,sy-sr-2),3)

    def _draw_ui_left(self, surf):
        """Panneau latéral gauche."""
        tick=pygame.time.get_ticks()/1000.0
        pw=230; draw_panel(surf,(0,0,pw,H))
        y=10

        # Titre animé
        tc=(int(190+65*math.sin(tick*0.9)),int(160+60*math.sin(tick*0.9+1.2)),55)
        t=self.f_title.render("HORIZON NOIR",True,tc); surf.blit(t,(10,y)); y+=36

        # Séparateur lumineux
        for px in range(5,pw-5,2):
            a=int(90+50*math.sin(tick*2+px*0.07))
            pygame.draw.line(surf,(50,90,180,a),(px,y),(px,y)); y+=1
        y+=6

        # ── Vaisseau ──
        draw_text(surf,"[ VAISSEAU ]",10,y,self.f_small,C['dim']); y+=14
        draw_bar(surf,10,y,pw-20,7,self.ship.hull,self.ship.hull_max,(50,220,80))
        surf.blit(self.f_small.render(f"Coque {int(self.ship.hull)}/{self.ship.hull_max}",True,C['green']),(10,y-1))
        y+=10
        draw_bar(surf,10,y,pw-20,7,self.ship.shield,self.ship.shield_max,(60,140,255))
        surf.blit(self.f_small.render(f"Bouclier {int(self.ship.shield)}/{self.ship.shield_max}",True,C['cyan']),(10,y-1))
        y+=10
        draw_bar(surf,10,y,pw-20,7,self.ship.fuel,self.ship.fuel_max,(255,180,50))
        surf.blit(self.f_small.render(f"Carburant {int(self.ship.fuel)}%",True,C['gold']),(10,y-1))
        y+=14

        # Pannes
        broken=[]
        if self.ship.engine_broken:  broken.append("⚠ MOTEUR")
        if self.ship.scanner_broken: broken.append("⚠ SCANNER")
        if self.ship.shield_broken:  broken.append("⚠ BOUCLIER")
        for br in broken:
            draw_text(surf,br,10,y,self.f_small,C['red']); y+=13

        # Modules
        mods=[("Scanner","✓" if self.ship.has_scanner else "✗",C['cyan'] if self.ship.has_scanner else C['dim']),
              ("Hyperdrive","✓" if self.ship.has_hyperdrive else "✗",C['green'] if self.ship.has_hyperdrive else C['dim']),
              ("IA","✓" if self.ship.has_ai else "✗",C['purple'] if self.ship.has_ai else C['dim'])]
        for mname,mval,mc in mods:
            surf.blit(self.f_small.render(f"{mname}: {mval}",True,mc),(10,y)); y+=13
        y+=4

        # ── Allocation énergie ──
        draw_text(surf,"[ ÉNERGIE ]",10,y,self.f_small,C['dim']); y+=14
        for label,val in [("Moteurs",self.ship.eng_engine),("Boucliers",self.ship.eng_shield),("Capteurs",self.ship.eng_sensor)]:
            c=(100,200,100) if val>50 else (200,200,80) if val>25 else (200,80,80)
            draw_bar(surf,10,y,pw-20,6,val,100,c)
            surf.blit(self.f_small.render(f"{label}: {val}%",True,c),(10,y-1)); y+=10
        y+=4

        # ── Stats mission ──
        draw_text(surf,"[ MISSION ]",10,y,self.f_small,C['dim']); y+=14
        stats=[
            (f"Données: {self.ship.data}",     C['cyan']),
            (f"Crédits: {self.ship.credits}",  C['gold']),
            (f"Colonies sauvées: {self.ship.colonies_saved}",C['green']),
            (f"Phase: {self.story_phase}/3",    C['info']),
        ]
        for s,c in stats:
            draw_text(surf,s,10,y,self.f_small,c); y+=13
        y+=4

        # ── Horizon Noir ──
        draw_text(surf,"[ HORIZON NOIR ]",10,y,self.f_small,C['dim']); y+=14
        hi_col=(int(100+155*self.horizon_intensity),int(50*(1-self.horizon_intensity)),int(200*(1-self.horizon_intensity)))
        draw_bar(surf,10,y,pw-20,8,self.horizon_intensity,1.0,hi_col,(20,10,30))
        surf.blit(self.f_small.render(f"Intensité: {int(self.horizon_intensity*100)}%",True,hi_col),(10,y-1))
        y+=14

        # ── Contrôles ──
        pygame.draw.line(surf,C['ui_border'],(5,y),(pw-5,y)); y+=6
        ctrls=[("ZQSD/Flèches","Pilote vaisseau"),(f"F","Scanner [{max(0,self.scan_cooldown)} cd]"),
               ("R","Réparer (coût: 50cr)"),("T","Follow vaisseau"),
               ("1-6","Objet à placer"),("Clic D+drag","Vélocité"),
               ("N","Événement narrative"),("P/ESPACE","Pause"),("ESC","Quitter")]
        for k,v in ctrls:
            kw=self.f_small.render(k,True,C['gold']); surf.blit(kw,(8,y))
            surf.blit(self.f_small.render(v,True,C['dim']),(8+kw.get_width()+4,y)); y+=13

    def _draw_placement_bar(self, surf):
        """Barre de sélection d'objet en bas."""
        items=[
            (ObjType.PLANET,   "1-Planète",    (80,160,255)),
            (ObjType.BLACK_HOLE,"2-Trou Noir", C['purple']),
            (ObjType.STAR,     "3-Étoile",     C['gold']),
            (ObjType.ASTEROID, "4-Astéroïde",  C['gray']),
            (ObjType.STATION,  "5-Station",    C['cyan']),
            (ObjType.WORMHOLE, "6-Trou de Ver",(120,40,255)),
        ]
        bw=140; bh=34; bx=238; by=H-bh-4
        draw_panel(surf,(bx-4,by-4,(bw+6)*len(items)+8,bh+8))
        tick=pygame.time.get_ticks()/1000.0
        for i,(ot,lbl,col) in enumerate(items):
            x=bx+i*(bw+6); active=self.sel_type==ot
            if active:
                pulse=int(60+30*math.sin(tick*4))
                bg=pygame.Surface((bw,bh),pygame.SRCALPHA)
                bg.fill((*col,pulse)); surf.blit(bg,(x,by))
                pygame.draw.rect(surf,col,(x,by,bw,bh),2)
            tc2=col if active else tuple(cc//2 for cc in col)
            surf.blit(self.f_small.render(lbl,True,tc2),(x+4,by+10))

    def _draw_message(self, surf):
        if not self.msg or self.msg_timer<=0: return
        af=min(1.0,self.msg_timer/35)
        ms=self.f_big.render(self.msg,True,getattr(self,'msg_color',C['white']))
        mw=ms.get_width()+28; mx=W//2-mw//2; my=26
        mb=pygame.Surface((mw,34),pygame.SRCALPHA); mb.fill((0,0,0,int(185*af)))
        mc=getattr(self,'msg_color',C['white'])
        pygame.draw.rect(mb,(*mc,int(200*af)),(0,0,mw,34),2)
        surf.blit(mb,(mx,my)); surf.blit(ms,(mx+14,my+6))

    def _draw_narrative(self, surf):
        """Popup narratif plein écran partiel."""
        if not self.active_event: return
        ev=self.active_event
        tick=pygame.time.get_ticks()/1000.0
        pw=700; ph=400; px=W//2-pw//2; py=H//2-ph//2
        ov=pygame.Surface((W,H),pygame.SRCALPHA); ov.fill((0,0,20,170)); surf.blit(ov,(0,0))
        draw_panel(surf,(px,py,pw,ph),(0,0,0,0),C['gold'],230)
        # Titre avec icône
        title=f"{ev.icon}  {ev.title}"
        tc=(int(200+55*math.sin(tick*0.9)),int(170+50*math.sin(tick*0.9+1.2)),55)
        surf.blit(self.f_big.render(title,True,tc),(px+16,py+14))
        pygame.draw.line(surf,C['gold'],(px+10,py+44),(px+pw-10,py+44),1)
        # Texte
        ty=py+56
        for line in ev.lines:
            surf.blit(self.f_med.render(line,True,C['white']),(px+16,ty)); ty+=22
        # Choix
        ty=max(ty+10,py+ph-len(ev.choices)*38-10)
        for i,(lbl,key) in enumerate(ev.choices):
            bx2=px+16; by2=ty+i*38; bw2=pw-32; bh2=32
            mx2,my2=pygame.mouse.get_pos()
            hover=(bx2<=mx2<bx2+bw2 and by2<=my2<by2+bh2)
            bg2=pygame.Surface((bw2,bh2),pygame.SRCALPHA)
            bg2.fill(C['gold']+(60 if hover else 25,))
            surf.blit(bg2,(bx2,by2))
            pygame.draw.rect(surf,C['gold'],(bx2,by2,bw2,bh2),1)
            col2=C['white'] if hover else C['dim']
            surf.blit(self.f_med.render(lbl,True,col2),(bx2+10,by2+7))
            # Stocker zones pour clic
            if not hasattr(self,'_choice_rects'): self._choice_rects=[]
            if len(self._choice_rects)<=i: self._choice_rects.append(None)
            self._choice_rects[i]=(bx2,by2,bw2,bh2,key)

    def _draw_game_over(self, surf):
        ov=pygame.Surface((W,H),pygame.SRCALPHA); ov.fill((0,0,0,200)); surf.blit(ov,(0,0))
        tick=pygame.time.get_ticks()/1000.0
        tc=(int(200+55*abs(math.sin(tick*1.5))),30,30)
        t1=self.f_title.render("GAME OVER",True,tc)
        surf.blit(t1,(W//2-t1.get_width()//2,H//2-80))
        t2=self.f_med.render(self.game_over_reason,True,C['white'])
        surf.blit(t2,(W//2-t2.get_width()//2,H//2-30))
        t3=self.f_med.render("Appuyez sur ESPACE pour recommencer.",True,C['dim'])
        surf.blit(t3,(W//2-t3.get_width()//2,H//2+20))

    def _draw_intro(self, surf):
        tick=pygame.time.get_ticks()/1000.0
        ov=pygame.Surface((W,H),pygame.SRCALPHA)
        for iy in range(H):
            a=int(195+30*math.sin(iy*0.01+tick)); pygame.draw.line(ov,(0,0,12,a),(0,iy),(W,iy))
        surf.blit(ov,(0,0))
        cy=H//2

        tc=(int(190+65*math.sin(tick*0.8)),int(155+65*math.sin(tick*0.8+1.3)),55)
        t1=self.f_title.render("H O R I Z O N   N O I R",True,tc)
        surf.blit(t1,(W//2-t1.get_width()//2,cy-170))

        t2=self.f_med.render("Année 2178 — Simulateur Galactique & RPG Spatial",True,C['cyan'])
        surf.blit(t2,(W//2-t2.get_width()//2,cy-118))

        pygame.draw.line(surf,C['gold'],(W//2-280,cy-90),(W//2+280,cy-90),1)

        story_lines=[
            "L'Horizon Noir dévore les colonies une à une.",
            "Vous êtes le pilote Khronos, recruté par l'OSS.",
            "Explorez, scannez, survivez. Décidez du destin de l'humanité.",
        ]
        for i,line in enumerate(story_lines):
            t=self.f_med.render(line,True,C['white'])
            surf.blit(t,(W//2-t.get_width()//2,cy-62+i*24))

        controls=[("ZQSD / Flèches","Piloter le vaisseau"),
                  ("F","Scanner les objets proches"),
                  ("R","Réparer (50 crédits)"),
                  ("1-6","Choisir type d'objet à placer"),
                  ("Clic gauche","Placer un objet"),
                  ("Clic droit + glisser","Donner une vélocité"),
                  ("N","Ouvrir un événement narratif"),
                  ("T","Suivre / lâcher le vaisseau"),]
        for i,(k,v) in enumerate(controls):
            x=W//2-220; y=cy+10+i*20
            kw=self.f_small.render(k,True,C['gold']); surf.blit(kw,(x,y))
            surf.blit(self.f_small.render(v,True,C['dim']),(x+kw.get_width()+8,y))

        pulse=abs(math.sin(tick*2.2))
        sc=(int(80+175*pulse),int(190+65*pulse),int(80+60*pulse))
        st=self.f_big.render("[ CLIQUEZ OU APPUYEZ POUR COMMENCER ]",True,sc)
        halo=pygame.Surface((st.get_width()+36,38),pygame.SRCALPHA)
        halo.fill((0,int(55*pulse),0,int(55*pulse)))
        stx=W//2-st.get_width()//2
        surf.blit(halo,(stx-18,cy+186)); surf.blit(st,(stx,cy+192))

    def _draw_drag_arrow(self, surf):
        if not self.dragging or not self.drag_start or not self.drag_pos: return
        dx=self.drag_pos[0]-self.drag_start[0]; dy=self.drag_pos[1]-self.drag_start[1]
        spd=math.hypot(dx,dy)
        for lw,la in [(5,35),(3,75),(1,190)]:
            pygame.draw.line(surf,(*C['gold'],la),self.drag_start,self.drag_pos,lw)
        if spd>10:
            ang=math.atan2(dy,dx)
            for side in[0.42,-0.42]:
                ax2=self.drag_pos[0]+math.cos(ang+math.pi+side)*13
                ay2=self.drag_pos[1]+math.sin(ang+math.pi+side)*13
                pygame.draw.line(surf,C['gold'],self.drag_pos,(int(ax2),int(ay2)),2)
        vt=self.f_small.render(f"v ≈ {spd*52:.0f} m/s",True,C['gold'])
        surf.blit(vt,(self.drag_pos[0]+11,self.drag_pos[1]-14))

    # ══ BOUTIQUE & UPGRADES ══════════════════════════════════════

    SHOP_ITEMS = [
        ("hull_1",    "Blindage Lv.1",   200, 0,   "Coque +30 PV",     "upgrade_hull"),
        ("hull_2",    "Blindage Lv.2",   400, 20,  "Coque +30 PV max", "upgrade_hull"),
        ("shield_1",  "Bouclier Lv.1",   180, 0,   "Bouclier +20",     "upgrade_shield"),
        ("shield_2",  "Bouclier Lv.2",   360, 20,  "Bouclier +20 max", "upgrade_shield"),
        ("engine_1",  "Reacteurs Lv.1",  220, 0,   "Vitesse +25%",     "upgrade_engine"),
        ("engine_2",  "Reacteurs Lv.2",  440, 30,  "Vitesse +25% max", "upgrade_engine"),
        ("scanner_1", "Scanner Lv.1",    150, 10,  "Portee +50%",      "upgrade_scanner"),
        ("scanner_2", "Scanner Lv.2",    300, 20,  "Portee +50% max",  "upgrade_scanner"),
        ("hyperdrive","Hyperdrive",       500, 50,  "Saut [H]",         "buy_hyperdrive"),
        ("ai_module", "Module IA",        600, 80,  "Nav+auto-scan",    "buy_ai"),
        ("weapons",   "Armement",         350, 30,  "Combat pirates",   "buy_weapons"),
        ("fuel_tank", "Reservoir Extra",  120, 0,   "Fuel max +50",     "buy_fuel_tank"),
        ("repair_kit","Kit Reparation",    50, 0,   "Repare tout",      "repair_all"),
        ("refuel",    "Plein Carburant",   80, 0,   "Fuel 100%",        "refuel"),
    ]

    def _can_buy(self, iid):
        s = self.ship; c = s.credits; d = s.data
        if iid=="hull_1":    return s.hull_level<1 and c>=200
        if iid=="hull_2":    return s.hull_level==1 and c>=400 and d>=20
        if iid=="shield_1":  return s.shield_level<1 and c>=180
        if iid=="shield_2":  return s.shield_level==1 and c>=360 and d>=20
        if iid=="engine_1":  return s.engine_level<1 and c>=220
        if iid=="engine_2":  return s.engine_level==1 and c>=440 and d>=30
        if iid=="scanner_1": return s.scanner_level<1 and c>=150 and d>=10
        if iid=="scanner_2": return s.scanner_level==1 and c>=300 and d>=20
        if iid=="hyperdrive":return not s.has_hyperdrive and c>=500 and d>=50
        if iid=="ai_module": return not s.has_ai and c>=600 and d>=80
        if iid=="weapons":   return not s.has_weapons and c>=350 and d>=30
        if iid=="fuel_tank": return s.fuel_max<150 and c>=120
        if iid=="repair_kit":return c>=50
        if iid=="refuel":    return s.fuel<s.fuel_max and c>=80
        return False

    def _already_owned(self, iid):
        s = self.ship
        if iid=="hull_1":    return s.hull_level>=1
        if iid=="hull_2":    return s.hull_level>=2
        if iid=="shield_1":  return s.shield_level>=1
        if iid=="shield_2":  return s.shield_level>=2
        if iid=="engine_1":  return s.engine_level>=1
        if iid=="engine_2":  return s.engine_level>=2
        if iid=="scanner_1": return s.scanner_level>=1
        if iid=="scanner_2": return s.scanner_level>=2
        if iid=="hyperdrive":return s.has_hyperdrive
        if iid=="ai_module": return s.has_ai
        if iid=="weapons":   return s.has_weapons
        if iid=="fuel_tank": return s.fuel_max>=150
        return False

    def buy_upgrade(self, action, cost_cr, cost_data):
        s = self.ship
        s.credits -= cost_cr
        s.data = max(0, s.data - cost_data)
        if action=="upgrade_hull":
            s.hull_level+=1; s.hull_max+=30; s.hull=min(s.hull_max,s.hull+30)
            self.set_msg(f"Blindage Lv.{s.hull_level} installe ! Coque +30",180,C['green'])
        elif action=="upgrade_shield":
            s.shield_level+=1; s.shield_max+=20; s.shield=min(s.shield_max,s.shield+20)
            self.set_msg(f"Bouclier Lv.{s.shield_level} installe ! Bouclier +20",180,C['cyan'])
        elif action=="upgrade_engine":
            s.engine_level+=1
            self.set_msg(f"Reacteurs Lv.{s.engine_level} ! Vitesse +25%",180,C['gold'])
        elif action=="upgrade_scanner":
            s.scanner_level+=1
            self.set_msg(f"Scanner Lv.{s.scanner_level} ! Portee +50%",180,C['cyan'])
        elif action=="buy_hyperdrive":
            s.has_hyperdrive=True
            self.set_msg("Hyperdrive installe ! [H] pour charger et sauter.",200,C['purple'])
        elif action=="buy_ai":
            s.has_ai=True
            self.set_msg("Module IA actif ! Navigation assistee.",180,C['purple'])
        elif action=="buy_weapons":
            s.has_weapons=True
            self.set_msg("Armement installe ! Combat pirates possible.",180,C['warn'])
        elif action=="buy_fuel_tank":
            s.fuel_max=150.0; s.fuel=min(s.fuel+50,s.fuel_max)
            self.set_msg("Reservoir agrandi ! Fuel max 150.",160,C['gold'])
        elif action=="repair_all":
            s.engine_broken=False; s.scanner_broken=False; s.shield_broken=False
            s.hull=min(s.hull_max,s.hull+20)
            self.set_msg("Toutes pannes reparees ! +20 coque.",160,C['green'])
        elif action=="refuel":
            s.fuel=s.fuel_max
            self.set_msg("Plein carburant !",140,C['gold'])
        audio_eng.play('repair')
        s.add_log(f"Achat: {action}")

    # ══ HYPERDRIVE ════════════════════════════════════════════════

    def _update_hyperdrive(self):
        s = self.ship
        if not s.has_hyperdrive: return
        keys = pygame.key.get_pressed()
        if keys[pygame.K_h] and s.hyperdrive_cooldown==0 and s.fuel>10:
            s.hyperdrive_charge = min(100.0, s.hyperdrive_charge+1.5)
            if s.hyperdrive_charge >= 100.0:
                self._hyperdrive_jump()
        else:
            s.hyperdrive_charge = max(0, s.hyperdrive_charge-1.5)
        if s.hyperdrive_cooldown>0: s.hyperdrive_cooldown-=1

    def _hyperdrive_jump(self):
        s = self.ship
        target=None; best=float('inf')
        for b in self.bodies:
            if b.otype in(ObjType.STATION,ObjType.PLANET,ObjType.WORMHOLE,ObjType.ANOMALY):
                d=math.hypot(b.x-s.x,b.y-s.y)
                if 1e9<d<best: best=d; target=b
        if not target:
            s.hyperdrive_charge=0.0
            self.set_msg("Aucune cible de saut.",120,C['dim']); return
        self.parts.emit(s.x,s.y,C['purple'],count=80,spd=(3000,12000))
        self.parts.emit_ring(s.x,s.y,(200,100,255),count=60,radius=80)
        s.x=target.x+random.uniform(-8e10,8e10)
        s.y=target.y+random.uniform(-8e10,8e10)
        s.vx*=0.08; s.vy*=0.08
        s.fuel=max(0,s.fuel-15)
        s.hyperdrive_charge=0.0; s.hyperdrive_cooldown=300; s.jumps_done+=1
        self.cam_x=s.x; self.cam_y=s.y
        self.parts.emit(s.x,s.y,C['purple'],count=60)
        audio_eng.play('hyperdrive')
        self.set_msg(f"Saut vers {target.name} ! -15 fuel.",200,C['purple'])
        s.add_log(f"Saut -> {target.name}")

    # ══ MODULE IA ═════════════════════════════════════════════════

    def _ai_tick(self):
        if not self.ship.has_ai or self.paused: return
        s = self.ship
        if self.frame%200==0 and self.scan_cooldown==0:
            self._scan(silent=True)
        if s.hull<s.hull_max*0.3 and self.frame%120==0:
            self.set_msg("IA: Coque critique ! Reparation recommandee.",120,C['red'])
        if s.hull<s.hull_max*0.4 and not s.shield_broken:
            s.eng_shield=min(60,s.eng_shield+1)
            s.eng_engine=max(20,s.eng_engine-1)
        if s.energy<30:
            s.eng_engine=max(15,s.eng_engine-1)

    # ══ MINIMAP ═══════════════════════════════════════════════════

    def _draw_minimap(self, surf):
        MMW,MMH=200,140; MMX=W-MMW-8; MMY=8
        mm=pygame.Surface((MMW,MMH),pygame.SRCALPHA)
        mm.fill((4,8,24,210))
        pygame.draw.rect(mm,C['ui_border'],(0,0,MMW,MMH),1)
        if self.bodies:
            xs=[b.x for b in self.bodies]; ys=[b.y for b in self.bodies]
            cx0=(min(xs)+max(xs))/2; cy0=(min(ys)+max(ys))/2
            span=max(max(xs)-min(xs),max(ys)-min(ys),1e11)
        else: cx0=cy0=0; span=1e12
        pad=12
        def tmm(wx,wy):
            return (int(MMW/2+(wx-cx0)/span*(MMW-2*pad)),
                    int(MMH/2+(wy-cy0)/span*(MMH-2*pad)))
        tc={ObjType.STAR:C['gold'],ObjType.PLANET:C['cyan'],
            ObjType.BLACK_HOLE:C['purple'],ObjType.ASTEROID:C['gray'],
            ObjType.STATION:(0,220,200),ObjType.WORMHOLE:(140,60,255),
            ObjType.ANOMALY:C['red']}
        for b in self.bodies:
            mx2,my2=tmm(b.x,b.y)
            if 0<=mx2<MMW and 0<=my2<MMH:
                col=tc.get(b.otype,C['white'])
                r=5 if b.otype==ObjType.STAR else(4 if b.otype==ObjType.BLACK_HOLE else 3)
                pygame.draw.circle(mm,col,(mx2,my2),r)
                if b.colony_hp>0:
                    hc2=(0,200,80) if b.colony_hp>40 else(220,80,50)
                    pygame.draw.circle(mm,hc2,(mx2+4,my2-4),2)
        vx2,vy2=tmm(self.ship.x,self.ship.y)
        tick=pygame.time.get_ticks()/1000.0
        if 0<=vx2<MMW and 0<=vy2<MMH:
            bc2=(int(180+75*math.sin(tick*4)),255,180)
            pygame.draw.circle(mm,bc2,(vx2,vy2),3)
        lbl=self.f_small.render("MINIMAP [M]",True,C['dim'])
        mm.blit(lbl,(4,2))
        surf.blit(mm,(MMX,MMY))

    # ══ HUD SUPÉRIEUR ═════════════════════════════════════════════

    def _draw_hud_top(self, surf):
        tick=pygame.time.get_ticks()/1000.0
        HX=235; HW=W-235-215; HH=36
        hud=pygame.Surface((HW,HH),pygame.SRCALPHA)
        hud.fill((4,8,24,195))
        pygame.draw.rect(hud,C['ui_border'],(0,0,HW,HH),1)
        x=10
        days=int(self.sim_time/86400)
        t=self.f_small.render(f"An 2178 — Jour {days:04d}",True,C['gold'])
        hud.blit(t,(x,10)); x+=t.get_width()+14
        pygame.draw.line(hud,C['ui_border'],(x,4),(x,HH-4)); x+=8
        spd=math.hypot(self.ship.vx,self.ship.vy)
        t=self.f_small.render(f"v:{spd/1000:.0f}km/s",True,C['cyan'])
        hud.blit(t,(x,10)); x+=t.get_width()+12
        pygame.draw.line(hud,C['ui_border'],(x,4),(x,HH-4)); x+=8
        t=self.f_small.render(f"Cr:{self.ship.credits}",True,C['gold'])
        hud.blit(t,(x,10)); x+=t.get_width()+8
        t=self.f_small.render(f"Data:{self.ship.data}",True,C['cyan'])
        hud.blit(t,(x,10)); x+=t.get_width()+12
        pygame.draw.line(hud,C['ui_border'],(x,4),(x,HH-4)); x+=8
        phases=["Recrutement","Exploration","Decouverte","Resolution"]
        ph_cols=[C['dim'],C['green'],C['warn'],C['gold']]
        t=self.f_small.render(f"{phases[min(self.story_phase,3)]}",True,ph_cols[min(self.story_phase,3)])
        hud.blit(t,(x,10)); x+=t.get_width()+12
        if self.ship.has_hyperdrive:
            pygame.draw.line(hud,C['ui_border'],(x,4),(x,HH-4)); x+=8
            t=self.f_small.render("HD",True,C['purple'])
            hud.blit(t,(x,4))
            bw=60
            pygame.draw.rect(hud,(30,10,50),(x,18,bw,8))
            fw=int(bw*self.ship.hyperdrive_charge/100)
            hc2=C['purple'] if self.ship.hyperdrive_cooldown==0 else C['dim']
            if fw>0: pygame.draw.rect(hud,hc2,(x,18,fw,8))
            pygame.draw.rect(hud,C['purple'],(x,18,bw,8),1)
            x+=bw+12
        hi=self.horizon_intensity
        if hi>0.1:
            hic=(int(100+155*hi),int(30*(1-hi)),int(180*(1-hi)))
            pulse=0.7+0.3*math.sin(tick*4*hi)
            hc3=tuple(int(c*pulse) for c in hic)
            t=self.f_small.render(f"HORIZON:{int(hi*100)}%",True,hc3)
            hud.blit(t,(HW-t.get_width()-8,10))
        surf.blit(hud,(HX,0))

    # ══ JOURNAL DE QUÊTES ═════════════════════════════════════════

    def _draw_quest_log(self, surf):
        if not self.show_quest_log: return
        QW,QH=420,470; QX=W//2-QW//2; QY=H//2-QH//2
        ov=pygame.Surface((W,H),pygame.SRCALPHA); ov.fill((0,0,0,160)); surf.blit(ov,(0,0))
        pn=pygame.Surface((QW,QH),pygame.SRCALPHA); pn.fill((*C['ui_bg'],240))
        pygame.draw.rect(pn,C['gold'],(0,0,QW,QH),2); surf.blit(pn,(QX,QY))
        y=QY+10
        tt=self.f_big.render("JOURNAL DE BORD",True,C['gold'])
        surf.blit(tt,(QX+QW//2-tt.get_width()//2,y)); y+=30
        pygame.draw.line(surf,C['ui_border'],(QX+8,y),(QX+QW-8,y)); y+=8
        surf.blit(self.f_small.render("[ QUETES ]",True,C['cyan']),(QX+10,y)); y+=16
        for qn,qd,qok in self._get_active_quests():
            col=C['green'] if qok else C['white']
            mk="[V]" if qok else "[ ]"
            surf.blit(self.f_small.render(f"{mk} {qn}",True,col),(QX+12,y)); y+=13
            surf.blit(self.f_small.render(f"    {qd}",True,C['dim']),(QX+12,y)); y+=13
        y+=6; pygame.draw.line(surf,C['ui_border'],(QX+8,y),(QX+QW-8,y)); y+=8
        surf.blit(self.f_small.render("[ JOURNAL ]",True,C['cyan']),(QX+10,y)); y+=14
        for entry in (self.ship.log[-8:] if self.ship.log else ["Aucune entree."]):
            surf.blit(self.f_small.render(entry[:55],True,C['dim']),(QX+12,y)); y+=13
        y+=6; pygame.draw.line(surf,C['ui_border'],(QX+8,y),(QX+QW-8,y)); y+=8
        surf.blit(self.f_small.render("[ STATS ]",True,C['cyan']),(QX+10,y)); y+=14
        s=self.ship
        for lbl2,v in [("Colonies sauvees",s.colonies_saved),("Colonies perdues",s.colonies_abandoned),
                       ("Scans",s.total_scans),("Sauts hyperdrive",s.jumps_done),
                       ("Credits",s.credits),("Donnees",s.data)]:
            surf.blit(self.f_small.render(f"  {lbl2}: {v}",True,C['white']),(QX+12,y)); y+=13
        cl=self.f_small.render("[J] Fermer",True,C['gold'])
        surf.blit(cl,(QX+QW//2-cl.get_width()//2,QY+QH-20))

    def _get_active_quests(self):
        sf=self.story_flags; s=self.ship
        q=[("Scanner l'anomalie","Trouvez la source de l'Horizon Noir",sf.get('origin_event',False)),
           ("Contacter Nova Kepler","Repondre au signal de detresse",sf.get('nova_event',False)),
           ("Enqueter le Trou de Ver","Scanner ou traverser Kappa",sf.get('wormhole_event',False)),
           ("Elucider l'Horizon","Accumuler 200 donnees",s.data>=200)]
        if sf.get('relay_mission'):
            q.append(("Mission relais OSS","Neutraliser les relais orbitaux",sf.get('relay_done',False)))
        if s.has_hyperdrive:
            q.append(("Maitriser l'Hyperdrive","Effectuer 3 sauts",s.jumps_done>=3))
        return q

    # ══ BOUTIQUE UI ═══════════════════════════════════════════════

    def _draw_shop(self, surf):
        if not self.show_shop: return
        SW,SH=580,500; SX=W//2-SW//2; SY=H//2-SH//2
        tick=pygame.time.get_ticks()/1000.0
        ov=pygame.Surface((W,H),pygame.SRCALPHA); ov.fill((0,0,0,170)); surf.blit(ov,(0,0))
        pn=pygame.Surface((SW,SH),pygame.SRCALPHA); pn.fill((*C['ui_bg'],245)); surf.blit(pn,(SX,SY))
        bc2=(int(100+80*math.sin(tick*2)),int(60+40*math.sin(tick*1.5)),int(200+55*math.sin(tick*2.5)))
        pygame.draw.rect(surf,bc2,(SX,SY,SW,SH),2)
        y=SY+12
        tt=self.f_big.render("STATION OSS — BOUTIQUE [B]",True,C['gold'])
        surf.blit(tt,(SX+SW//2-tt.get_width()//2,y)); y+=28
        sb=self.f_small.render(f"Credits: {self.ship.credits}   Donnees: {self.ship.data}",True,C['cyan'])
        surf.blit(sb,(SX+SW//2-sb.get_width()//2,y)); y+=18
        pygame.draw.line(surf,C['ui_border'],(SX+8,y),(SX+SW-8,y)); y+=6
        if not hasattr(self,'_shop_rects'): self._shop_rects=[]
        self._shop_rects=[]
        mx,my=pygame.mouse.get_pos()
        for iid,label,cost_cr,cost_data,desc,action in self.SHOP_ITEMS:
            owned=self._already_owned(iid); can=self._can_buy(iid)
            ih=30; iw=SW-20; hover=(SX+10<=mx<SX+10+iw and y<=my<y+ih)
            bg2=pygame.Surface((iw,ih),pygame.SRCALPHA)
            if owned:   bg2.fill((10,40,10,120))
            elif hover: bg2.fill((20,30,70,200))
            elif can:   bg2.fill((10,20,45,120))
            else:       bg2.fill((25,10,10,80))
            surf.blit(bg2,(SX+10,y))
            pygame.draw.rect(surf,(C['cyan'] if hover else C['ui_border']),(SX+10,y,iw,ih),1)
            col=C['dim'] if owned else(C['green'] if can else (80,80,80))
            mk="[OK]" if owned else("    " if not can else "    ")
            surf.blit(self.f_small.render(f"{mk} {label}",True,col),(SX+16,y+8))
            surf.blit(self.f_small.render(desc,True,C['dim']),(SX+200,y+8))
            pp=[]
            if cost_cr>0:   pp.append(f"{cost_cr}cr")
            if cost_data>0: pp.append(f"{cost_data}dt")
            pstr=" + ".join(pp) if pp else "gratuit"
            surf.blit(self.f_small.render(pstr,True,C['gold'] if can else C['dim']),(SX+SW-110,y+8))
            if not owned:
                self._shop_rects.append((SX+10,y,iw,ih,iid,action,cost_cr,cost_data))
            y+=ih+3
        y+=6
        cl=self.f_small.render("[B] Fermer",True,C['gold'])
        surf.blit(cl,(SX+SW//2-cl.get_width()//2,y))

    
    # ── RENDER PRINCIPAL ─────────────────────────────────────────
    def draw(self, surf):
        bg_obj.draw(surf)
        if self.show_intro:
            self._draw_intro(surf); return

        # Horizon Noir overlay ambiant
        if self.horizon_intensity>0.2:
            hi_ov=pygame.Surface((W,H),pygame.SRCALPHA)
            a=int(40*self.horizon_intensity)
            hi_ov.fill((40,0,60,a)); surf.blit(hi_ov,(0,0))

        self.parts.draw(surf,self.wtsc,self.zoom)
        self._draw_bodies(surf)
        self._draw_ship(surf)
        self._draw_drag_arrow(surf)
        self._draw_hud_top(surf)
        self._draw_ui_left(surf)
        self._draw_placement_bar(surf)
        if self.show_minimap: self._draw_minimap(surf)
        self._draw_message(surf)

        # Overlays modale (ordre important)
        if self.show_shop:       self._draw_shop(surf)
        elif self.show_quest_log:self._draw_quest_log(surf)
        elif self.show_narrative:self._draw_narrative(surf)
        if self.game_over:       self._draw_game_over(surf)
        if self.paused:
            tick=pygame.time.get_ticks()/1000.0
            pc=(int(195+60*math.sin(tick*3)),int(195+60*math.sin(tick*3+1)),100)
            pt=self.f_title.render("  PAUSE  ",True,pc)
            surf.blit(pt,(W//2-pt.get_width()//2,H//2-20))

    # ── EVENTS ────────────────────────────────────────────────────
    def _inject_event(self, event):
        """Process a single pre-fetched event (used by main loop)."""
        # Reuse the same logic as handle_events but for one event
        if event.type == pygame.USEREVENT+1:
            pygame.time.set_timer(pygame.USEREVENT+1,0)
            if not self.story_flags.get('faction_event_shown'):
                self.story_flags['faction_event_shown']=True
                self._trigger_event('faction_horizon')
        if event.type == pygame.USEREVENT+2:
            pygame.time.set_timer(pygame.USEREVENT+2,0)
            if not self.story_flags.get('oss_betrayal_shown'):
                self.story_flags['oss_betrayal_shown']=True
                self._trigger_event('oss_betrayal')
        if self.show_intro:
            if event.type in(pygame.MOUSEBUTTONDOWN,pygame.KEYDOWN):
                self.show_intro=False; audio_eng.play('whoosh'); self._trigger_event('intro')
            return
        if self.game_over:
            if event.type==pygame.KEYDOWN and event.key==pygame.K_SPACE:
                self.__init__()
            return
        if self.show_narrative:
            if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                mx,my=event.pos
                for rect in getattr(self,'_choice_rects',[]):
                    if rect and rect[0]<=mx<rect[0]+rect[2] and rect[1]<=my<rect[1]+rect[3]:
                        self._handle_choice(rect[4]); self._choice_rects=[]; audio_eng.play('whoosh'); break
            return
        self._process_keydown_mouse(event)

    def _process_keydown_mouse(self, event):
        """Handle keyboard/mouse in gameplay (shared by _inject_event)."""
        if event.type==pygame.KEYDOWN:
            k=event.key
            if k==pygame.K_ESCAPE:
                if self.show_shop or self.show_quest_log:
                    self.show_shop=False; self.show_quest_log=False
                # ESC handled by outer loop for menu return
            elif k in(pygame.K_SPACE,pygame.K_p):
                if not self.show_shop and not self.show_quest_log: self.paused=not self.paused
            elif k==pygame.K_1 and not self.show_shop: self.sel_type=ObjType.PLANET;    audio_eng.play('whoosh')
            elif k==pygame.K_2 and not self.show_shop: self.sel_type=ObjType.BLACK_HOLE;audio_eng.play('whoosh')
            elif k==pygame.K_3 and not self.show_shop: self.sel_type=ObjType.STAR;      audio_eng.play('whoosh')
            elif k==pygame.K_4 and not self.show_shop: self.sel_type=ObjType.ASTEROID;  audio_eng.play('whoosh')
            elif k==pygame.K_5 and not self.show_shop: self.sel_type=ObjType.STATION;   audio_eng.play('whoosh')
            elif k==pygame.K_6 and not self.show_shop: self.sel_type=ObjType.WORMHOLE;  audio_eng.play('whoosh')
            elif k==pygame.K_f: self._scan()
            elif k==pygame.K_t: self.follow_ship=not self.follow_ship; audio_eng.play('whoosh')
            elif k==pygame.K_m: self.show_minimap=not self.show_minimap
            elif k==pygame.K_b:
                self.show_shop=not self.show_shop; self.show_quest_log=False
                if self.show_shop: audio_eng.play('whoosh')
            elif k==pygame.K_j:
                self.show_quest_log=not self.show_quest_log; self.show_shop=False
                if self.show_quest_log: audio_eng.play('whoosh')
            elif k==pygame.K_n and not self.show_shop and not self.show_quest_log:
                pending=[('wormhole_found','wormhole_found'),('colony_nova','colony_nova'),
                         ('faction_horizon','faction_horizon'),('station_contact','station_contact')]
                for flg,ev_key in pending:
                    if not self.story_flags.get(flg+'_shown'):
                        self.story_flags[flg+'_shown']=True
                        self._trigger_event(ev_key); audio_eng.play('whoosh'); break
            elif k==pygame.K_LEFTBRACKET:
                self.ship.eng_engine=max(10,self.ship.eng_engine-5)
                self.ship.eng_shield=min(80,self.ship.eng_shield+5)
                self.set_msg("Energie: +boucliers",80,C['cyan'])
            elif k==pygame.K_RIGHTBRACKET:
                self.ship.eng_engine=min(80,self.ship.eng_engine+5)
                self.ship.eng_shield=max(10,self.ship.eng_shield-5)
                self.set_msg("Energie: +moteurs",80,C['gold'])
            elif k==pygame.K_r:
                cost=50
                if self.ship.credits>=cost:
                    self.ship.credits-=cost
                    self.ship.hull=min(self.ship.hull_max,self.ship.hull+25)
                    self.ship.shield=min(self.ship.shield_max,self.ship.shield+20)
                    self.ship.engine_broken=False; self.ship.scanner_broken=False; self.ship.shield_broken=False
                    self.set_msg("Reparation ! +25 coque.",150,C['green']); audio_eng.play('repair')
                    self.ship.add_log("Reparation urgence")
                else: self.set_msg("Credits insuffisants (50).",140,C['warn'])
        elif event.type==pygame.MOUSEBUTTONDOWN:
            if self.show_shop and event.button==1:
                mx,my=event.pos
                for rx,ry,rw,rh,iid,action,cc,cd in getattr(self,'_shop_rects',[]):
                    if rx<=mx<rx+rw and ry<=my<ry+rh:
                        if self._can_buy(iid): self.buy_upgrade(action,cc,cd)
                        else: self.set_msg("Credits ou donnees insuffisants.",120,C['warn'])
                        break
                return
            if self.show_quest_log and event.button==1:
                self.show_quest_log=False; return
            if event.button==1 and not self.show_narrative and not self.show_shop:
                if event.pos[0]>230 and event.pos[1]>36:
                    wx,wy=self.stow(*event.pos); self.add_body(wx,wy)
            elif event.button==3:
                self.dragging=True; self.drag_start=event.pos; self.drag_pos=event.pos
            elif event.button==2:
                self.panning=True; self.pan_start=event.pos; self.cam_start=(self.cam_x,self.cam_y)
            elif event.button==4: self.zoom=min(self.zoom*1.12,0.014)
            elif event.button==5: self.zoom=max(self.zoom/1.12,5e-10)
        elif event.type==pygame.MOUSEBUTTONUP:
            if event.button==3 and self.dragging:
                self.dragging=False
                if self.drag_start and self.drag_pos and self.drag_start[0]>230 and not self.show_shop:
                    dx=self.drag_pos[0]-self.drag_start[0]; dy=self.drag_pos[1]-self.drag_start[1]
                    wx,wy=self.stow(*self.drag_start)
                    self.add_body(wx,wy,dx*52/self.zoom*1e-6,dy*52/self.zoom*1e-6)
                self.drag_start=None; self.drag_pos=None
            elif event.button==2: self.panning=False
        elif event.type==pygame.MOUSEMOTION:
            if self.dragging: self.drag_pos=event.pos
            if self.panning and self.pan_start and self.cam_start and not self.show_shop:
                dx=(event.pos[0]-self.pan_start[0])/self.zoom
                dy=(event.pos[1]-self.pan_start[1])/self.zoom
                self.cam_x=self.cam_start[0]-dx; self.cam_y=self.cam_start[1]-dy

    def handle_events(self):
        for event in pygame.event.get():
            if event.type==pygame.QUIT:
                pygame.quit(); sys.exit()
            self._inject_event(event)

    def _handle_events_old(self):
        for event in pygame.event.get():
            if event.type==pygame.QUIT:
                pygame.quit(); sys.exit()

            if event.type==pygame.QUIT:
                pygame.quit(); sys.exit()

            if event.type==pygame.USEREVENT+1:
                pygame.time.set_timer(pygame.USEREVENT+1,0)
                if not self.story_flags.get('faction_event_shown'):
                    self.story_flags['faction_event_shown']=True
                    self._trigger_event('faction_horizon')

            if event.type==pygame.USEREVENT+2:
                pygame.time.set_timer(pygame.USEREVENT+2,0)
                if not self.story_flags.get('oss_betrayal_shown'):
                    self.story_flags['oss_betrayal_shown']=True
                    self._trigger_event('oss_betrayal')

            # Intro
            if self.show_intro:
                if event.type in(pygame.MOUSEBUTTONDOWN,pygame.KEYDOWN):
                    self.show_intro=False; audio_eng.play('whoosh')
                    self._trigger_event('intro')
                continue

            # Game over
            if self.game_over:
                if event.type==pygame.KEYDOWN and event.key==pygame.K_SPACE:
                    self.__init__()
                continue

            # Narrative
            if self.show_narrative:
                if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                    mx,my=event.pos
                    rects=getattr(self,'_choice_rects',[])
                    for rect in rects:
                        if rect and rect[0]<=mx<rect[0]+rect[2] and rect[1]<=my<rect[1]+rect[3]:
                            self._handle_choice(rect[4])
                            self._choice_rects=[]
                            audio_eng.play('whoosh'); break
                continue

            if event.type==pygame.KEYDOWN:
                k=event.key
                # Fermeture modales avec Echap
                if k==pygame.K_ESCAPE:
                    if self.show_shop or self.show_quest_log:
                        self.show_shop=False; self.show_quest_log=False
                    else: pygame.quit(); sys.exit()
                elif k in(pygame.K_SPACE,pygame.K_p):
                    if not self.show_shop and not self.show_quest_log:
                        self.paused=not self.paused
                # Placement objets (bloqué si modale ouverte)
                elif k==pygame.K_1 and not self.show_shop:
                    self.sel_type=ObjType.PLANET;    audio_eng.play('whoosh')
                elif k==pygame.K_2 and not self.show_shop:
                    self.sel_type=ObjType.BLACK_HOLE;audio_eng.play('whoosh')
                elif k==pygame.K_3 and not self.show_shop:
                    self.sel_type=ObjType.STAR;      audio_eng.play('whoosh')
                elif k==pygame.K_4 and not self.show_shop:
                    self.sel_type=ObjType.ASTEROID;  audio_eng.play('whoosh')
                elif k==pygame.K_5 and not self.show_shop:
                    self.sel_type=ObjType.STATION;   audio_eng.play('whoosh')
                elif k==pygame.K_6 and not self.show_shop:
                    self.sel_type=ObjType.WORMHOLE;  audio_eng.play('whoosh')
                # Actions
                elif k==pygame.K_f: self._scan()
                elif k==pygame.K_t: self.follow_ship=not self.follow_ship; audio_eng.play('whoosh')
                elif k==pygame.K_m: self.show_minimap=not self.show_minimap
                elif k==pygame.K_b:
                    self.show_shop=not self.show_shop
                    self.show_quest_log=False
                    if self.show_shop: audio_eng.play('whoosh')
                elif k==pygame.K_j:
                    self.show_quest_log=not self.show_quest_log
                    self.show_shop=False
                    if self.show_quest_log: audio_eng.play('whoosh')
                elif k==pygame.K_n and not self.show_shop and not self.show_quest_log:
                    pending=[('wormhole_found','wormhole_found'),
                             ('colony_nova','colony_nova'),
                             ('faction_horizon','faction_horizon'),
                             ('station_contact','station_contact')]
                    for flg,ev_key in pending:
                        if not self.story_flags.get(flg+'_shown'):
                            self.story_flags[flg+'_shown']=True
                            self._trigger_event(ev_key); audio_eng.play('whoosh'); break
                # Énergie redistribution : [ ] pour baisser/monter moteurs
                elif k==pygame.K_LEFTBRACKET:
                    self.ship.eng_engine=max(10,self.ship.eng_engine-5)
                    self.ship.eng_shield=min(80,self.ship.eng_shield+5)
                    self.set_msg("Energie: +boucliers",80,C['cyan'])
                elif k==pygame.K_RIGHTBRACKET:
                    self.ship.eng_engine=min(80,self.ship.eng_engine+5)
                    self.ship.eng_shield=max(10,self.ship.eng_shield-5)
                    self.set_msg("Energie: +moteurs",80,C['gold'])
                elif k==pygame.K_r:
                    cost=50
                    if self.ship.credits>=cost:
                        self.ship.credits-=cost
                        self.ship.hull=min(self.ship.hull_max,self.ship.hull+25)
                        self.ship.shield=min(self.ship.shield_max,self.ship.shield+20)
                        self.ship.engine_broken=False; self.ship.scanner_broken=False
                        self.ship.shield_broken=False
                        self.set_msg("Reparation ! +25 coque, +20 bouclier.",150,C['green'])
                        audio_eng.play('repair')
                        self.ship.add_log("Reparation d'urgence")
                    else:
                        self.set_msg("Credits insuffisants (50 requis).",140,C['warn'])

            elif event.type==pygame.MOUSEBUTTONDOWN:
                # Clics dans la boutique
                if self.show_shop and event.button==1:
                    mx2,my2=event.pos
                    for rx,ry,rw,rh,iid,action,cc,cd in getattr(self,'_shop_rects',[]):
                        if rx<=mx2<rx+rw and ry<=my2<ry+rh:
                            if self._can_buy(iid):
                                self.buy_upgrade(action,cc,cd)
                            else:
                                self.set_msg("Credits ou donnees insuffisants.",120,C['warn'])
                            break
                    continue
                # Clics dans le journal (juste fermer)
                if self.show_quest_log and event.button==1:
                    self.show_quest_log=False; continue

                if event.button==1 and not self.show_narrative and not self.show_shop:
                    if event.pos[0]>230 and event.pos[1]>36:
                        wx,wy=self.stow(*event.pos); self.add_body(wx,wy)
                elif event.button==3:
                    self.dragging=True; self.drag_start=event.pos; self.drag_pos=event.pos
                elif event.button==2:
                    self.panning=True; self.pan_start=event.pos; self.cam_start=(self.cam_x,self.cam_y)
                elif event.button==4: self.zoom=min(self.zoom*1.12,0.014)
                elif event.button==5: self.zoom=max(self.zoom/1.12,5e-10)

            elif event.type==pygame.MOUSEBUTTONUP:
                if event.button==3 and self.dragging:
                    self.dragging=False
                    if self.drag_start and self.drag_pos and self.drag_start[0]>230 and not self.show_shop:
                        dx=self.drag_pos[0]-self.drag_start[0]
                        dy=self.drag_pos[1]-self.drag_start[1]
                        wx,wy=self.stow(*self.drag_start)
                        self.add_body(wx,wy,dx*52/self.zoom*1e-6,dy*52/self.zoom*1e-6)
                    self.drag_start=None; self.drag_pos=None
                elif event.button==2: self.panning=False

            elif event.type==pygame.MOUSEMOTION:
                if self.dragging:  self.drag_pos=event.pos
                if self.panning and self.pan_start and self.cam_start and not self.show_shop:
                    dx=(event.pos[0]-self.pan_start[0])/self.zoom
                    dy=(event.pos[1]-self.pan_start[1])/self.zoom
                    self.cam_x=self.cam_start[0]-dx; self.cam_y=self.cam_start[1]-dy

# ══════════════════════════════════════════════════════════════════
#  POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════

def _check_dependencies():
    """Vérifie et installe les dépendances si nécessaire."""
    missing = []
    try: import pygame
    except ImportError: missing.append('pygame')
    try: import numpy
    except ImportError: missing.append('numpy')
    if missing:
        print(f"Dépendances manquantes : {', '.join(missing)}")
        print(f"Installation automatique : pip install {' '.join(missing)}")
        try:
            import subprocess
            subprocess.check_call([sys.executable,'-m','pip','install']+missing,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Installation réussie. Relancez le script.")
        except Exception as e:
            print(f"Erreur : {e}\nInstallez manuellement : pip install {' '.join(missing)}")
        sys.exit(1)

def _init_display(w, h):
    """Initialise l'affichage avec fallback de résolution."""
    # Essayer différentes résolutions si la native échoue
    for ww, hh in [(w,h),(1024,768),(800,600)]:
        try:
            surf = pygame.display.set_mode((ww,hh))
            if ww != w or hh != h:
                print(f"[Info] Résolution réduite à {ww}x{hh}")
            return surf, ww, hh
        except Exception:
            continue
    # Dernier recours : fenêtre quelconque
    pygame.display.init()
    surf = pygame.display.set_mode((800,600),pygame.NOFRAME)
    return surf, 800, 600

def _init_audio():
    """Initialise l'audio avec fallback silencieux."""
    # Ordre de priorité selon l'OS
    if sys.platform == 'win32':
        drivers = ['', 'directsound', 'waveout', 'dummy']
    elif sys.platform == 'darwin':
        drivers = ['', 'coreaudio', 'dummy']
    else:
        drivers = ['', 'pulse', 'alsa', 'oss', 'dummy']

    for drv in drivers:
        try:
            if drv:
                os.environ['SDL_AUDIODRIVER'] = drv
            pygame.mixer.pre_init(SAMPLE_RATE, -16, 1, 512)
            pygame.mixer.init()
            if pygame.mixer.get_init():
                print(f"[Audio] Pilote : {drv or 'auto'}")
                return True
        except Exception:
            pass
    print("[Audio] Son désactivé (aucun pilote disponible)")
    return False

# ══════════════════════════════════════════════════════════════════
#  MENU DE DÉMARRAGE
# ══════════════════════════════════════════════════════════════════

class MainMenu:
    """Menu principal animé avec particules, lore et navigation."""

    MENU_ITEMS = [
        ("NOUVELLE PARTIE",   "new_game"),
        ("CONTINUER",         "continue"),
        ("PARAMETRES",        "settings"),
        ("CREDITS",           "credits_screen"),
        ("QUITTER",           "quit"),
    ]

    LORE_LINES = [
        "Annee 2178. L'horizon se ferme sur les etoiles.",
        "Des colonies disparaissent. Les routes s'eteignent.",
        "L'OSS recrute ses derniers pilotes.",
        "Vous etes le Khronos. Votre mission : survivre.",
        "Et peut-etre... sauver ce qui reste de l'humanite.",
    ]

    CREDITS_TEXT = [
        "HORIZON NOIR",
        "Simulateur Galactique & RPG Spatial",
        "",
        "Moteur physique : Newton N-Corps",
        "Audio : Synthese procedurale numpy",
        "Musique : Drone_cosmique.mp3",
        "",
        "Graphismes : pygame + algorithmes proceduraux",
        "Scenarios : 14 evenements narratifs",
        "Fins : 3 endings distincts",
        "",
        "Compatible Windows / macOS / Linux",
        "Python 3.8+  |  pygame  |  numpy",
        "",
        "[ESC] Retour",
    ]

    def __init__(self, surf, fonts, bg, sounds_ref, has_save=False):
        self.surf        = surf
        self.f_title     = fonts[0]
        self.f_big       = fonts[1]
        self.f_med       = fonts[2]
        self.f_small     = fonts[3]
        self.bg          = bg
        self.sounds      = sounds_ref
        self.has_save    = has_save
        self.selected    = 0
        self.state       = "menu"        # menu | settings | credits_screen
        self.running     = True
        self.action      = None
        self.lore_idx    = 0
        self.lore_timer  = 0
        self.lore_alpha  = 0.0
        self.lore_fade   = "in"
        # Étoiles de fond supplémentaires pour le menu
        self.particles   = []
        self._spawn_menu_particles()
        # Settings
        self.vol_music   = 70
        self.vol_sfx     = 80
        self.resolution  = 0  # index dans RESOLUTIONS
        self.RESOLUTIONS = ["1280x800","1920x1080","1024x768","800x600"]

    def _spawn_menu_particles(self):
        for _ in range(120):
            self.particles.append({
                'x': random.uniform(0, W),
                'y': random.uniform(0, H),
                'vx': random.uniform(-0.3, 0.3),
                'vy': random.uniform(-0.8, -0.1),
                'size': random.uniform(1, 3),
                'color': random.choice([(120,0,220),(0,180,255),(255,200,50),(50,220,100)]),
                'alpha': random.uniform(0.2, 1.0),
                'life': random.uniform(0.4, 1.0),
            })

    def _update_particles(self):
        for p in self.particles:
            p['x'] += p['vx']; p['y'] += p['vy']
            p['alpha'] -= 0.003
            if p['alpha'] <= 0 or p['y'] < -10:
                p['x'] = random.uniform(0, W)
                p['y'] = H + 5
                p['vx'] = random.uniform(-0.3, 0.3)
                p['vy'] = random.uniform(-0.8, -0.1)
                p['alpha'] = random.uniform(0.6, 1.0)
                p['color'] = random.choice([(120,0,220),(0,180,255),(255,200,50),(50,220,100)])

    def _draw_particles(self):
        for p in self.particles:
            a = max(0, min(255, int(p['alpha'] * 180)))
            c = tuple(min(255, int(cc * p['alpha'])) for cc in p['color'])
            sz = max(1, int(p['size']))
            try:
                if sz <= 1: self.surf.set_at((int(p['x']), int(p['y'])), c)
                else: pygame.draw.circle(self.surf, c, (int(p['x']), int(p['y'])), sz)
            except: pass

    def _draw_lore(self, tick):
        """Texte de lore qui défile lentement."""
        self.lore_timer += 1
        if self.lore_fade == "in":
            self.lore_alpha = min(1.0, self.lore_alpha + 0.02)
            if self.lore_alpha >= 1.0: self.lore_fade = "hold"
        elif self.lore_fade == "hold":
            if self.lore_timer > 180: self.lore_fade = "out"
        elif self.lore_fade == "out":
            self.lore_alpha = max(0.0, self.lore_alpha - 0.015)
            if self.lore_alpha <= 0:
                self.lore_idx = (self.lore_idx + 1) % len(self.LORE_LINES)
                self.lore_timer = 0; self.lore_fade = "in"
        a = int(self.lore_alpha * 200)
        line = self.LORE_LINES[self.lore_idx]
        txt = self.f_small.render(line, True, (200, 200, 255))
        s = pygame.Surface((txt.get_width(), txt.get_height()), pygame.SRCALPHA)
        s.blit(txt, (0,0)); s.set_alpha(a)
        self.surf.blit(s, (W//2 - txt.get_width()//2, H - 60))

    def _draw_title_block(self, tick):
        cy = H // 2 - 160
        # Glow derrière le titre
        gw = 700; gh = 80
        gs = pygame.Surface((gw, gh), pygame.SRCALPHA)
        pulse = 0.5 + 0.5 * math.sin(tick * 0.6)
        for r in range(gh//2, 0, -4):
            a = int(50 * (r / (gh//2)) * pulse)
            pygame.draw.ellipse(gs, (80, 0, 150, a), (gw//2-r*4, gh//2-r, r*8, r*2))
        self.surf.blit(gs, (W//2 - gw//2, cy - gh//2))
        # Titre principal
        tc = (int(200 + 55*math.sin(tick*0.7)),
              int(150 + 60*math.sin(tick*0.7 + 1.5)), 55)
        title = self.f_title.render("H O R I Z O N   N O I R", True, tc)
        self.surf.blit(title, (W//2 - title.get_width()//2, cy))
        cy += 46
        # Sous-titre
        sub = self.f_med.render("Simulateur Galactique & RPG Spatial  —  Annee 2178", True, (100, 160, 220))
        self.surf.blit(sub, (W//2 - sub.get_width()//2, cy))
        cy += 28
        # Ligne décorative animée
        lw = 380; lx = W//2 - lw//2
        for px in range(lw):
            f = px / lw
            a = int(180 * math.sin(math.pi * f) * (0.6 + 0.4*math.sin(tick*2 + f*6)))
            col = (int(80+120*f), int(20+80*(1-f)), int(200-100*f))
            try: self.surf.set_at((lx+px, cy), tuple(min(255,c) for c in col))
            except: pass
        return cy + 20

    def _draw_menu_items(self, tick, start_y):
        for i, (label, _) in enumerate(self.MENU_ITEMS):
            if label == "CONTINUER" and not self.has_save:
                col = (50, 50, 60)
                txt = self.f_big.render(label + "  [aucune save]", True, col)
                self.surf.blit(txt, (W//2 - txt.get_width()//2, start_y + i*48))
                continue
            active = (i == self.selected)
            if active:
                pulse = 0.7 + 0.3 * math.sin(tick * 4)
                col = (int(180+75*pulse), int(220+35*pulse), int(80+60*pulse))
                # Fond lumineux
                bw = 400; bh = 40
                bg_s = pygame.Surface((bw, bh), pygame.SRCALPHA)
                for px in range(bw):
                    fa = int(60 * math.sin(math.pi * px/bw) * pulse)
                    pygame.draw.line(bg_s, (100, 200, 80, fa), (px,0),(px,bh))
                self.surf.blit(bg_s, (W//2 - bw//2, start_y + i*48 - 4))
                # Flèches latérales
                arrow_c = tuple(min(255,c) for c in col)
                aw = self.f_big.render(">>", True, arrow_c)
                self.surf.blit(aw, (W//2 - 230, start_y + i*48 + 4))
                self.surf.blit(aw, (W//2 + 200, start_y + i*48 + 4))
            else:
                col = (120, 130, 160)
            txt = self.f_big.render(label, True, col)
            self.surf.blit(txt, (W//2 - txt.get_width()//2, start_y + i*48))

    def _draw_settings(self, tick):
        self.surf.fill((3, 5, 18))
        self.bg.draw(self.surf)
        title = self.f_big.render("PARAMETRES", True, (200,180,50))
        self.surf.blit(title, (W//2 - title.get_width()//2, 80))
        pygame.draw.line(self.surf, (50,80,120), (W//2-200,120),(W//2+200,120))

        items = [
            ("Volume Musique", self.vol_music, "vol_music"),
            ("Volume SFX",     self.vol_sfx,   "vol_sfx"),
        ]
        for i, (label, val, key) in enumerate(items):
            y = 160 + i * 70
            t = self.f_med.render(label, True, (180,190,220))
            self.surf.blit(t, (W//2 - 200, y))
            # Barre
            bw = 300; bh = 16; bx = W//2 - 50; by = y + 5
            pygame.draw.rect(self.surf, (20,25,40), (bx,by,bw,bh))
            fw = int(bw * val / 100)
            pygame.draw.rect(self.surf, (80,180,80), (bx,by,fw,bh))
            pygame.draw.rect(self.surf, (50,80,120), (bx,by,bw,bh), 1)
            vt = self.f_small.render(f"{val}%", True, (200,220,180))
            self.surf.blit(vt, (bx + bw + 10, by))

        t = self.f_med.render("Resolution", True, (180,190,220))
        self.surf.blit(t, (W//2 - 200, 300))
        rt = self.f_med.render(f"< {self.RESOLUTIONS[self.resolution]} >", True, (100,200,255))
        self.surf.blit(rt, (W//2 - 50, 300))

        back = self.f_med.render("[ESC / B] Retour", True, (100,120,160))
        self.surf.blit(back, (W//2 - back.get_width()//2, H - 60))

    def _draw_credits(self, tick):
        self.surf.fill((3,5,18))
        self.bg.draw(self.surf)
        y = 60
        for line in self.CREDITS_TEXT:
            if not line:
                y += 14; continue
            if line in ("HORIZON NOIR",):
                tc = (int(200+55*math.sin(tick*0.8)), 160, 50)
                t = self.f_big.render(line, True, tc)
            elif line.startswith("["):
                t = self.f_small.render(line, True, (100,120,160))
            else:
                t = self.f_small.render(line, True, (160,170,200))
            self.surf.blit(t, (W//2 - t.get_width()//2, y))
            y += t.get_height() + 8

    def handle_event(self, event):
        if self.state == "settings":
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_b):
                    self.state = "menu"
                elif event.key == pygame.K_UP:
                    self.vol_music = min(100, self.vol_music + 5)
                    _set_music_volume(self.vol_music)
                elif event.key == pygame.K_DOWN:
                    self.vol_music = max(0, self.vol_music - 5)
                    _set_music_volume(self.vol_music)
                elif event.key == pygame.K_LEFT:
                    self.resolution = (self.resolution - 1) % len(self.RESOLUTIONS)
                elif event.key == pygame.K_RIGHT:
                    self.resolution = (self.resolution + 1) % len(self.RESOLUTIONS)
            return

        if self.state == "credits_screen":
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,pygame.K_b,pygame.K_RETURN):
                self.state = "menu"
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_UP:
                self.selected = (self.selected - 1) % len(self.MENU_ITEMS)
            elif event.key == pygame.K_DOWN:
                self.selected = (self.selected + 1) % len(self.MENU_ITEMS)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._activate(self.selected)
            elif event.key == pygame.K_ESCAPE:
                self.action = "quit"; self.running = False
        elif event.type == pygame.MOUSEMOTION:
            for i in range(len(self.MENU_ITEMS)):
                item_y = H//2 - 20 + i*48
                if abs(event.pos[1] - item_y) < 22:
                    self.selected = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(len(self.MENU_ITEMS)):
                item_y = H//2 - 20 + i*48
                if abs(event.pos[1] - item_y) < 22:
                    self._activate(i)

    def _activate(self, idx):
        label, action = self.MENU_ITEMS[idx]
        if action == "continue" and not self.has_save:
            return
        if action in ("settings", "credits_screen"):
            self.state = action; return
        if action == "quit":
            self.action = "quit"; self.running = False; return
        self.action = action; self.running = False

    def draw(self, tick):
        if self.state == "settings":
            self._draw_settings(tick); return
        if self.state == "credits_screen":
            self._draw_credits(tick); return
        # Menu principal
        self.bg.draw(self.surf)
        self._update_particles()
        self._draw_particles()
        title_bottom = self._draw_title_block(tick)
        self._draw_menu_items(tick, title_bottom + 10)
        self._draw_lore(tick)
        # Version
        vt = self.f_small.render("v2.0  |  Python + pygame + numpy", True, (50,55,70))
        self.surf.blit(vt, (W - vt.get_width() - 10, H - 20))
        # Touche musique
        mt = self.f_small.render("[M] Musique on/off", True, (50,55,70))
        self.surf.blit(mt, (10, H - 20))

    def run(self, clock):
        while self.running:
            tick = pygame.time.get_ticks() / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.action = "quit"; self.running = False
                self.handle_event(event)
            self.draw(tick)
            pygame.display.flip()
            clock.tick(FPS)
        return self.action


# ── Helpers musique globaux ────────────────────────────────────────

def _music_path():
    """Cherche Drone_cosmique.mp3 / .wav dans plusieurs emplacements."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = os.getcwd()
    candidates = [
        os.path.join(script_dir, "Drone_cosmique.mp3"),
        os.path.join(script_dir, "Drone_cosmique.wav"),
        os.path.join(os.getcwd(), "Drone_cosmique.mp3"),
        os.path.join(os.getcwd(), "Drone_cosmique.wav"),
        "Drone_cosmique.mp3",
        "Drone_cosmique.wav",
    ]
    for p in candidates:
        if os.path.isfile(p): return p
    return None

def _start_music(volume=70):
    """Lance la musique de fond en boucle, silencieux si absent."""
    path = _music_path()
    if not path:
        print("[Musique] Drone_cosmique.mp3 introuvable — mode silence.")
        return False
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(volume / 100.0)
        pygame.mixer.music.play(-1, fade_ms=3000)
        print(f"[Musique] {os.path.basename(path)} en cours.")
        return True
    except Exception as e:
        print(f"[Musique] Erreur : {e}")
        return False

def _set_music_volume(vol):
    try: pygame.mixer.music.set_volume(max(0, min(100, vol)) / 100.0)
    except: pass

def _stop_music(fade_ms=1500):
    try: pygame.mixer.music.fadeout(fade_ms)
    except: pass


def main():
    global bg_obj, audio_eng

    _check_dependencies()

    # ── Compatibilité display/audio ────────────────────────────────
    if sys.platform.startswith('linux'):
        has_display = 'DISPLAY' in os.environ or 'WAYLAND_DISPLAY' in os.environ
        if not has_display:
            os.environ.setdefault('SDL_VIDEODRIVER','offscreen')
    if sys.platform == 'darwin':
        os.environ.setdefault('SDL_VIDEO_MAC_FULLSCREEN_SPACES','0')

    audio_ok = _init_audio()
    if not pygame.get_init(): pygame.init()

    # ── Fenêtre ───────────────────────────────────────────────────
    try:
        surf, _, _ = _init_display(W, H)
    except Exception as e:
        print(f"Erreur affichage : {e}"); sys.exit(1)
    pygame.display.set_caption("HORIZON NOIR — Simulateur Galactique 2178")

    try:
        icon = pygame.Surface((32,32), pygame.SRCALPHA)
        pygame.draw.circle(icon,(120,0,200),(16,16),14)
        pygame.draw.circle(icon,(0,0,0),(16,16),8)
        pygame.draw.circle(icon,(200,100,0),(16,16),14,2)
        pygame.display.set_icon(icon)
    except: pass

    # ── Chargement splash ─────────────────────────────────────────
    clock = pygame.time.Clock()
    f_splash = load_font(18)
    f_splash_big = load_font(26, True)

    def draw_loading(label, progress):
        surf.fill((3,5,18))
        # Étoiles rapides
        for _ in range(80):
            x,y = random.randint(0,W), random.randint(0,H)
            b = random.randint(40,180)
            try: surf.set_at((x,y),(b,b,min(255,b+30)))
            except: pass
        # Logo
        tc = (180,140,50)
        t = f_splash_big.render("HORIZON NOIR", True, tc)
        surf.blit(t, (W//2-t.get_width()//2, H//2-80))
        # Barre
        bw = 400; bh = 12; bx = W//2-bw//2; by = H//2+10
        pygame.draw.rect(surf,(20,25,40),(bx,by,bw,bh))
        pygame.draw.rect(surf,(80,160,80),(bx,by,int(bw*progress),bh))
        pygame.draw.rect(surf,(50,80,120),(bx,by,bw,bh),1)
        t2 = f_splash.render(label, True, (100,120,160))
        surf.blit(t2, (W//2-t2.get_width()//2, by+20))
        pygame.display.flip()
        clock.tick(30)

    draw_loading("Initialisation...", 0.05)
    sounds = build_sounds() if audio_ok else {}
    draw_loading("Sons generes...", 0.40)
    audio_eng = AudioEngine(sounds)
    draw_loading("Moteur audio OK...", 0.55)
    bg_obj = Background()
    draw_loading("Nebuleuse generee...", 0.80)
    music_on = _start_music(70) if audio_ok else False
    draw_loading("Pret !", 1.0)
    pygame.time.wait(400)

    # ── Boucle menu + jeu ─────────────────────────────────────────
    fonts = (load_font(30,True), load_font(22,True), load_font(15), load_font(12))
    saved_game = None

    print("=" * 58)
    print("  HORIZON NOIR — Annee 2178")
    print("  Touches menu : Fleches + Entree | Souris")
    print("  En jeu : ZQSD F R T B J N M 1-6 H P ESC")
    print("=" * 58)

    while True:
        # ── MENU ──────────────────────────────────────────────────
        menu = MainMenu(surf, fonts, bg_obj, sounds,
                        has_save=(saved_game is not None))
        action = menu.run(clock)

        if action == "quit":
            _stop_music(800); pygame.time.wait(900)
            pygame.quit(); sys.exit(0)

        elif action == "new_game":
            _stop_music(2000)
            pygame.time.wait(500)
            game = HorizonNoir()

        elif action == "continue" and saved_game is not None:
            _stop_music(2000)
            pygame.time.wait(500)
            game = saved_game

        else:
            continue   # Cas impossible, retour menu

        # ── GAMEPLAY ──────────────────────────────────────────────
        # Fade-in musique jeu (la même piste, volume légèrement plus bas)
        if music_on:
            try:
                pygame.mixer.music.set_volume(0.45)
                if not pygame.mixer.music.get_busy():
                    path = _music_path()
                    if path:
                        pygame.mixer.music.load(path)
                        pygame.mixer.music.play(-1, fade_ms=2500)
            except: pass

        running = True
        while running:
            try:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        _stop_music(800); pygame.time.wait(900)
                        pygame.quit(); sys.exit(0)

                    # Touche M : toggle musique
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                        music_on = not music_on
                        if music_on:
                            path = _music_path()
                            if path:
                                try:
                                    pygame.mixer.music.load(path)
                                    pygame.mixer.music.play(-1, fade_ms=1000)
                                    pygame.mixer.music.set_volume(0.45)
                                except: pass
                            game.set_msg("Musique activee.", 100, C['dim'])
                        else:
                            _stop_music(800)
                            game.set_msg("Musique desactivee.", 100, C['dim'])

                    # ESC depuis le jeu → retour menu
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        if game.show_shop or game.show_quest_log:
                            game.show_shop = False; game.show_quest_log = False
                        else:
                            saved_game = game
                            _stop_music(1500)
                            running = False; break

                    else:
                        # Injecter l'event dans le jeu
                        pygame.event.post(event) if False else None
                        game._inject_event(event)

                if not running: break
                game.update()
                game.draw(surf)
                pygame.display.flip()
                clock.tick(FPS)

            except KeyboardInterrupt:
                running = False
            except Exception as e:
                print(f"[Erreur] {e}")
                import traceback; traceback.print_exc()
                running = False

if __name__=="__main__":
    main()
