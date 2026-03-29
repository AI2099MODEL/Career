# ==========================================
# MODEL1 API — FINAL STABLE VERSION
# ==========================================

import sys
import subprocess
import os

# ==========================================
# AUTO INSTALL
# ==========================================
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

packages = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("pyswisseph", "swisseph"),
    ("timezonefinder", "timezonefinder"),
    ("pytz", "pytz"),
    ("requests", "requests"),
    ("geopy", "geopy")
]

for pkg, module in packages:
    try:
        __import__(module)
    except ImportError:
        print(f"Installing {pkg}...")
        install(pkg)

# ==========================================
# IMPORTS
# ==========================================
from fastapi import FastAPI
import swisseph as swe
from datetime import datetime
from timezonefinder import TimezoneFinder
import pytz
import requests
from geopy.geocoders import Nominatim

# ==========================================
# FREE LOCATION (NO API KEY)
# ==========================================
geolocator = Nominatim(user_agent="astro_engine")

def get_lat_lon(place):
    location = geolocator.geocode(place)
    if location is None:
        raise Exception(f"Location not found: {place}")
    return location.latitude, location.longitude

# ==========================================
# EPHEMERIS SETUP
# ==========================================
EPHE_PATH = "./ephe"

def setup_ephemeris():
    if not os.path.exists(EPHE_PATH):
        os.makedirs(EPHE_PATH)

    files = {
        "sepl_18.se1": "https://www.astro.com/ftp/swisseph/ephe/sepl_18.se1",
        "semo_18.se1": "https://www.astro.com/ftp/swisseph/ephe/semo_18.se1"
    }

    for fname, url in files.items():
        path = os.path.join(EPHE_PATH, fname)

        if os.path.exists(path):
            print(f"{fname} exists, skipping...")
            continue

        print(f"Downloading {fname}...")
        r = requests.get(url, timeout=30)

        if r.status_code == 200:
            with open(path, "wb") as f:
                f.write(r.content)
            print(f"{fname} downloaded")
        else:
            raise Exception(f"Failed to download {fname}")

    swe.set_ephe_path(os.path.abspath(EPHE_PATH))

    # Test ephemeris
    swe.calc_ut(swe.julday(2026, 1, 1), swe.SUN)
    print("✅ Ephemeris ready")

setup_ephemeris()

# ==========================================
# APP INIT
# ==========================================
app = FastAPI()
swe.set_sid_mode(swe.SIDM_LAHIRI)

# ==========================================
# HELPERS
# ==========================================
def deg_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)

def get_sign(d):
    return int(d / 30)

sign_lords = {
    0: "Mars", 1: "Venus", 2: "Mercury", 3: "Moon", 4: "Sun", 5: "Mercury",
    6: "Venus", 7: "Mars", 8: "Jupiter", 9: "Saturn", 10: "Saturn", 11: "Jupiter"
}

def get_10th_lord(asc):
    return sign_lords[(get_sign(asc) + 9) % 12]

# ==========================================
# DASHA ENGINE
# ==========================================
dasha_seq = [
    ("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10),
    ("Mars", 7), ("Rahu", 18), ("Jupiter", 16),
    ("Saturn", 19), ("Mercury", 17)
]

def build_dasha(moon_deg, birth_year):
    nak = 360 / 27
    idx = int(moon_deg / nak)
    balance = 1 - ((moon_deg % nak) / nak)

    lord, yrs = dasha_seq[idx % 9]

    tl = []
    cur = birth_year

    first = yrs * balance
    tl.append((lord, cur, cur + first))
    cur += first

    i = (idx % 9 + 1) % 9

    for _ in range(20):
        l, y = dasha_seq[i]
        tl.append((l, cur, cur + y))
        cur += y
        i = (i + 1) % 9

    return tl

def get_md_ad(year, tl):
    for md, s, e in tl:
        if s <= year < e:
            md_len = e - s
            a_s = s
            for l, y in dasha_seq:
                a_e = a_s + md_len * (y / 120)
                if a_s <= year < a_e:
                    return md, l
                a_s = a_e
    return None, None

# ==========================================
# TRANSITS
# ==========================================
def transit(year):
    jd = swe.julday(year, 6, 15)
    sat = swe.calc_ut(jd, swe.SATURN)[0][0]
    jup = swe.calc_ut(jd, swe.JUPITER)[0][0]
    return sat, jup

# ==========================================
# MODEL LOGIC
# ==========================================
def model1(year, pos_map, asc, tl):
    md, ad = get_md_ad(year, tl)
    sat, jup = transit(year)

    lord = get_10th_lord(asc)
    lord_deg = pos_map[lord]

    h10 = any(deg_diff(p, lord_deg) < 8 for p in pos_map.values())
    dasha_ok = md == lord or ad == lord or md in ["Saturn", "Jupiter"]
    tr_ok = deg_diff(jup, lord_deg) < 8 or deg_diff(sat, lord_deg) < 6

    score = sum([h10, dasha_ok, tr_ok])

    if score < 2:
        return "Stable", "⭐"
    elif score == 2:
        return "Trigger", "⭐⭐"
    else:
        return "Execution", "⭐⭐⭐"

# ==========================================
# MONTH DETECTION
# ==========================================
def get_months(year, pos_map, asc):
    lord = get_10th_lord(asc)
    ldeg = pos_map[lord]

    active = []
    for m in range(1, 13):
        jd = swe.julday(year, m, 15)
        jup = swe.calc_ut(jd, swe.JUPITER)[0][0]

        if deg_diff(jup, ldeg) < 8:
            active.append(m)

    return active

# ==========================================
# API
# ==========================================
@app.get("/")
def home():
    return {"status": "API running"}

@app.get("/predict")
def predict(dob: str, tob: str, place: str):
    try:
        lat, lon = get_lat_lon(place)

        tf = TimezoneFinder()
        tz_name = tf.timezone_at(lat=lat, lng=lon) or "UTC"
        tz = pytz.timezone(tz_name)

        dt = datetime.strptime(f"{dob} {tob}", "%Y-%m-%d %H:%M")
        dt = tz.localize(dt).astimezone(pytz.utc)

        jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60)

        planets = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
        ids = [
            swe.SUN, swe.MOON, swe.MARS, swe.MERCURY,
            swe.JUPITER, swe.VENUS, swe.SATURN
        ]

        pos = [swe.calc_ut(jd, i)[0][0] for i in ids]
        pos_map = dict(zip(planets, pos))

        houses, ascmc = swe.houses(jd, lat, lon)
        asc = ascmc[0]

        tl = build_dasha(pos_map["Moon"], dt.year)

        future = {}
        for y in range(2026, 2035):
            ev, st = model1(y, pos_map, asc, tl)

            if ev != "Stable":
                future[y] = {
                    "event": ev,
                    "strength": st,
                    "months": get_months(y, pos_map, asc)
                }

        return {
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "ascendant_degree": asc,
            "future": future
        }

    except Exception as e:
        return {"error": str(e)}

# ==========================================
# RUN SERVER
# ==========================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)