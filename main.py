# ==========================================
# MODEL1 PRO API — FINAL PRODUCTION VERSION
# ==========================================

import sys, subprocess, os

# ---------- AUTO INSTALL ---------
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

packages = [
    ("fastapi","fastapi"),
    ("uvicorn","uvicorn"),
    ("pyswisseph","swisseph"),
    ("timezonefinder","timezonefinder"),
    ("pytz","pytz"),
    ("requests","requests")
]

for p, imp in packages:
    try:
        __import__(imp)
    except:
        install(p)

# ---------- IMPORTS ----------
from fastapi import FastAPI
import swisseph as swe
from datetime import datetime
from timezonefinder import TimezoneFinder
import pytz
import requests

# ==========================================
# GOOGLE LOCATION
# ==========================================
def get_lat_lon(place):
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise Exception("GOOGLE_API_KEY missing")

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    res = requests.get(url, params={"address": place, "key": key}, timeout=10)

    data = res.json()
    if data["status"] != "OK":
        raise Exception("Invalid place")

    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]

# ==========================================
# EPHEMERIS
# ==========================================
EPHE_PATH = "./ephe"

def setup_ephe():
    if not os.path.exists(EPHE_PATH):
        os.makedirs(EPHE_PATH)

    files = {
        "sepl_18.se1": "https://www.astro.com/ftp/swisseph/ephe/sepl_18.se1",
        "semo_18.se1": "https://www.astro.com/ftp/swisseph/ephe/semo_18.se1"
    }

    for f,u in files.items():
        p = os.path.join(EPHE_PATH,f)
        if os.path.exists(p):
            continue
        r = requests.get(u)
        with open(p,"wb") as x:
            x.write(r.content)

    swe.set_ephe_path(os.path.abspath(EPHE_PATH))
    swe.calc_ut(swe.julday(2026,1,1), swe.SUN)

setup_ephe()

# ==========================================
# CORE ENGINE
# ==========================================
app = FastAPI()
swe.set_sid_mode(swe.SIDM_LAHIRI)

def deg_diff(a,b):
    d=abs(a-b)%360
    return min(d,360-d)

def get_sign(d): return int(d/30)

lords={0:"Mars",1:"Venus",2:"Mercury",3:"Moon",4:"Sun",5:"Mercury",
       6:"Venus",7:"Mars",8:"Jupiter",9:"Saturn",10:"Saturn",11:"Jupiter"}

def tenth_lord(asc):
    return lords[(get_sign(asc)+9)%12]

# ---------- DASHA ----------
dasha=[("Ketu",7),("Venus",20),("Sun",6),("Moon",10),
       ("Mars",7),("Rahu",18),("Jupiter",16),
       ("Saturn",19),("Mercury",17)]

def build_dasha(moon,birth):
    size=360/27
    idx=int(moon/size)
    bal=1-((moon%size)/size)
    lord,yrs=dasha[idx%9]

    tl=[]; cur=birth
    first=yrs*bal
    tl.append((lord,cur,cur+first))
    cur+=first

    i=(idx+1)%9
    for _ in range(20):
        l,y=dasha[i]
        tl.append((l,cur,cur+y))
        cur+=y
        i=(i+1)%9
    return tl

def get_md(year,tl):
    for md,s,e in tl:
        if s<=year<e:
            return md
    return None

# ---------- TRANSIT ----------
def transit(year,m=6,d=15):
    jd=swe.julday(year,m,d)
    return (
        swe.calc_ut(jd,swe.SATURN)[0][0],
        swe.calc_ut(jd,swe.JUPITER)[0][0],
        swe.calc_ut(jd,swe.MOON)[0][0]
    )

# ---------- MODEL ----------
def evaluate(year,pos,asc,tl):

    md=get_md(year,tl)
    sat,jup,_=transit(year)

    lord=tenth_lord(asc)
    ldeg=pos[lord]

    h10=any(deg_diff(p,ldeg)<8 for p in pos.values())
    dasha_ok=(md==lord or md in ["Saturn","Jupiter"])
    tr=(deg_diff(jup,ldeg)<8 or deg_diff(sat,ldeg)<6)

    score=sum([h10,dasha_ok,tr])

    if score<2:
        return "Stable","⭐"

    if score==2:
        return "Trigger","⭐⭐"

    return "Execution","⭐⭐⭐"

# ---------- MONTH ----------
def months(year,pos,asc):
    ldeg=pos[tenth_lord(asc)]
    ms=[]
    for m in range(1,13):
        _,j,_=transit(year,m,15)
        if deg_diff(j,ldeg)<8:
            ms.append(m)
    return ms

# ==========================================
# API
# ==========================================
@app.get("/predict")
def predict(dob:str,tob:str,place:str):

    lat,lon=get_lat_lon(place)

    tf=TimezoneFinder()
    tz=pytz.timezone(tf.timezone_at(lat=lat,lng=lon))

    dt=datetime.strptime(f"{dob} {tob}","%Y-%m-%d %H:%M")
    dt=tz.localize(dt).astimezone(pytz.utc)

    jd=swe.julday(dt.year,dt.month,dt.day,dt.hour+dt.minute/60)

    names=["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn"]
    ids=[swe.SUN,swe.MOON,swe.MARS,swe.MERCURY,
         swe.JUPITER,swe.VENUS,swe.SATURN]

    pos=dict(zip(names,[swe.calc_ut(jd,i)[0][0] for i in ids]))

    houses,ascmc=swe.houses(jd,lat,lon)
    asc=ascmc[0]

    tl=build_dasha(pos["Moon"],dt.year)

    future={}
    for y in range(2026,2035):
        ev,st=evaluate(y,pos,asc,tl)
        if ev!="Stable":
            future[y]={
                "event":ev,
                "strength":st,
                "months":months(y,pos,asc)
            }

    return {
        "place":place,
        "ascendant":asc,
        "future":future
    }

# ---------- RUN ----------
if __name__=="__main__":
    import uvicorn
   uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("PORT",8000)))
