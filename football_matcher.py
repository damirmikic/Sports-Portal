# football_matcher.py
# TEST svih 8 kladionica / 17 liga
# SoccerBet je referenca. Skripta NE dira app.py.

from __future__ import annotations

import json
import re
import time
import uuid
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone

import requests

from meridian import MeridianClient

LEAGUES = {
    "Premier League":       {"SoccerBet":"2516076","MerkurXtip":"2313707","Meridian":"80","Superbet":"106","MaxBet":"152506","Mozzart":"4187","BalkanBet":"33","King":"26"},
    "Championship":         {"SoccerBet":"2515993","MerkurXtip":"2313706","Meridian":"122","Superbet":"27","MaxBet":"119606","Mozzart":"4054","BalkanBet":"36","King":"58"},
    "LaLiga":               {"SoccerBet":"2516061","MerkurXtip":"2313715","Meridian":"92","Superbet":"98","MaxBet":"117709","Mozzart":"4161","BalkanBet":"15","King":"18"},
    "LaLiga 2":             {"SoccerBet":"2515946","MerkurXtip":"2313721","Meridian":"93","Superbet":"191","MaxBet":"117710","Mozzart":"4023","BalkanBet":"135","King":"88"},
    "Serie A":              {"SoccerBet":"2516000","MerkurXtip":"2313717","Meridian":"95","Superbet":"104","MaxBet":"117689","Mozzart":"4460","BalkanBet":"51","King":"91","365":"2222590"},
    "Serie B":              {"SoccerBet":"2515982","MerkurXtip":"2313856","Meridian":"96","Superbet":"244","MaxBet":"117690","Mozzart":"4377","BalkanBet":"132","King":"27"},
    "Bundesliga":           {"SoccerBet":"2515986","MerkurXtip":"2313709","Meridian":"107","Superbet":"245","MaxBet":"117683","Mozzart":"4143","BalkanBet":"87","King":"53"},
    "2. Bundesliga":        {"SoccerBet":"2515981","MerkurXtip":"2313854","Meridian":"108","Superbet":"50","MaxBet":"132231","Mozzart":"4184","BalkanBet":"114","King":"141"},
    "Ligue 1":              {"SoccerBet":"2515968","MerkurXtip":"2313703","Meridian":"87","Superbet":"100","MaxBet":"117827","Mozzart":"4472","BalkanBet":"84","King":"62"},
    "Eredivisie":           {"SoccerBet":"2516075","MerkurXtip":"2313899","Meridian":"125","Superbet":"256","MaxBet":"117808","Mozzart":"3881","BalkanBet":"93","King":"118"},
    "Jupiler Pro League":   {"SoccerBet":"2515984","MerkurXtip":"2313730","Meridian":"132","Superbet":"324","MaxBet":"152565","Mozzart":"4211","BalkanBet":"96","King":"51"},
    "Primeira Liga":        {"SoccerBet":"2515943","MerkurXtip":"2322844","Meridian":"103","Superbet":"142","MaxBet":"132736","Mozzart":"3960","BalkanBet":"516","King":"90"},
    "Turkish Super Lig":    {"SoccerBet":"2515970","MerkurXtip":"2313865","Meridian":"113","Superbet":"323","MaxBet":"119607","Mozzart":"4129","BalkanBet":"129","King":"2"},
    "Austrian Bundesliga":  {"SoccerBet":"2518487","MerkurXtip":"2313857","Meridian":"115","Superbet":"413","MaxBet":"117681","Mozzart":"4215","BalkanBet":"117","King":"87"},
    "Swiss Super League":   {"SoccerBet":"2516009","MerkurXtip":"2313864","Meridian":"135","Superbet":"492","MaxBet":"132232","Mozzart":"4004","BalkanBet":"453","King":"68"},
    "HNL":                  {"SoccerBet":"2516112","MerkurXtip":"2313849","Meridian":"120","Superbet":"362","MaxBet":"152568","Mozzart":"4365","BalkanBet":"330","King":"158"},
    "Serbian Super Liga":   {"SoccerBet":"2517235","MerkurXtip":"2314082","Meridian":"91","Superbet":"1014","MaxBet":"152561","Mozzart":"4181","BalkanBet":"438","King":"185"},
    "UEFA Europa League": {"SoccerBet":"2520043","MerkurXtip":"2313710","Meridian":"86","Superbet":"688","MaxBet":"136867","Mozzart":"3626","BalkanBet":"1470","King":"85"},
    "UEFA Nations League": {"Meridian":"96123","Mozzart":"5137,12127","King":"528","MerkurXtip":"2325577,2331882,2330299,2331906","BalkanBet":"29179","MaxBet":"152788,152790,152789,152791","SoccerBet":"2529486,2529525,2529485,2529539","Superbet":"32375,32376,32377,32378,32379,32380,32381,32382,32374,32383,32384,32385,32386,32387","365":"2251499,2251500,2251498,2251497"},
}

BOOKS = ["Meridian","Superbet","MaxBet","Mozzart","SoccerBet","BalkanBet","King","MerkurXtip","365"]

ALIASES = {
    "man utd":"manchester united", "man united":"manchester united",
    "man city":"manchester city", "nottm forest":"nottingham forest",
    "nottingham":"nottingham forest", "spurs":"tottenham",
    "wolves":"wolverhampton", "inter milan":"inter", "internazionale":"inter",
    "psg":"paris saint germain", "athletic bilbao":"athletic club",
    "atletico madrid":"atletico", "bayern munich":"bayern",
    "borussia monchengladbach":"monchengladbach",
    "west bromwich albion":"west brom", "west bromwich":"west brom",
    "west bromwich alb":"west brom", "w bromwich":"west brom", "wba":"west brom",
    "queens park rangers":"qpr", "queens park":"qpr",
    "imt novi beograd":"imt",
    "crvena zvezda":"red star belgrade", "fk crvena zvezda":"red star belgrade", "crvena zvezda beograd":"red star belgrade", "red star":"red star belgrade",
    # Dodatne varijante imena klubova iz testa svih 8 kladionica
    "coventry city":"coventry",
    "leeds united":"leeds",
    "bolton wanderers":"bolton",
    "cardiff city":"cardiff",
    "derby county":"derby",
    "birmingham city":"birmingham",
    "preston north end":"preston",
    "lincoln city":"lincoln",
    "atl madrid":"atletico",
    "atletico de madrid":"atletico",
    "sporting gijon":"gijon",
    "sporting de gijon":"gijon",
    "cd eldense":"eldense",
    "c elta vigo b":"celta vigo b",
    "rc celta b":"celta vigo b",
    "celta b":"celta vigo b",
    "sd eibar":"eibar",
    "vfl bochum":"bochum",
    "spvgg greuther furth":"greuther furth",
    "vfl osnabruck":"osnabruck",
    "hertha bsc":"hertha berlin",
    "stade rennais":"rennes",
    "rennes fc":"rennes",
    "olympique marseille":"marseille",
    "olympique de marseille":"marseille",
    "lille osc":"lille",
    "estac troyes":"troyes",
    "stade brestois":"brest",
    "stade brestois 29":"brest",
    "paris sg":"paris saint germain",
    "fc twente":"twente",
    "ado den haag":"den haag",
    "pec zwolle":"zwolle",
    "oud heverlee leuven":"leuven",
    "oh leuven":"leuven",
    "cercle brugge ksv":"cercle brugge",
    "union saint gilloise":"royale union sg",
    "union st gilloise":"royale union sg",
    "royale union saint gilloise":"royale union sg",
    "krc genk":"genk",
    "kaa gent":"gent",
    "zulte waregem":"waregem",
    "sporting charleroi":"charleroi",
    "nacional madeira":"nacional",
    "cd nacional":"nacional",
    "fc alverca":"alverca",
    "sporting braga":"braga",
    "sc braga":"braga",
    "estoril praia":"estoril",
    "gd estoril praia":"estoril",
    "amed sk":"amedspor",
    "amed sfk":"amedspor",
    "istanbul basaksehir":"basaksehir",
    "basaksehir fk":"basaksehir",
    "sk sturm graz":"sturm graz",
    "lask linz":"lask",
    "fk partizan belgrade":"partizan",
    "partizan belgrade":"partizan",
    "fk vojvodina":"vojvodina",
    "imt beograd":"imt",
    "fk imt":"imt",


    # Poslednjih 6 neuparenih iz kompletnog testa
    "club nacional de football":"nacional",
    "cd nacional madeira":"nacional",
    "nacional da madeira":"nacional",
    "fc alverca sad":"alverca",
    "alverca sad":"alverca",
    "real sporting de gijon":"gijon",
    "real sporting gijon":"gijon",
    "sporting gijon":"gijon",
    "cd eldense":"eldense",
    "royale union saint gilloise":"royale union sg",
    "royale union st gilloise":"royale union sg",
    "union saint gilloise":"royale union sg",
    "union st gilloise":"royale union sg",
    "lommel sk":"lommel",
    "hnk gorica":"gorica",
    "nk varazdin":"varazdin",
    "imt novi beograd":"imt",
    "fk imt beograd":"imt",
    "fk imt novi beograd":"imt",
    "fk crvena zvezda":"crvena zvezda",
    "red star belgrade":"crvena zvezda",


    # Tacni MaxBet nazivi sa sajta
    "st gilloise":"royale union sg",
    "lommel sk":"lommel",
    "c zvezda":"red star belgrade", "czvezda":"red star belgrade", "c zvezda beograd":"red star belgrade",

    # UEFA Europa League - varijante naziva klubova
    "rsc anderlecht":"anderlecht",
    "olympique lyonnais":"lyon",
    "olympique lyon":"lyon",
    "ol lyon":"lyon",
    "celtic glasgow":"celtic",
    "ferencvarosi tc":"ferencvaros",
    "ferencvaros tc":"ferencvaros",
    "olympiacos piraeus":"olympiacos",
    "olympiakos piraeus":"olympiacos",
    "olympiakos":"olympiacos",
    "jagiellonia bialystok":"jagiellonia",
    "omonia nicosia":"omonia",
    "ac omonia nicosia":"omonia",
    "rc celta de vigo":"celta vigo",
    "celta de vigo":"celta vigo",

    # Dodatna mapiranja za meceve koji su u novoj proveri imali prazne kvote
    "rapid vienna":"rapid wien", "rapid wien":"rapid wien",
    "wsg tirol":"tirol", "wsG tirol":"tirol", "red bull salzburg":"salzburg",
    "fc salzburg":"salzburg", "rb salzburg":"salzburg", "sturm graz":"sturm graz",
    "newcastle united":"newcastle", "hull city":"hull",
    "bristol city":"bristol city", "watford fc":"watford",
    "millwall fc":"millwall", "west ham united":"west ham",
    "birmingham city":"birmingham", "middlesbrough fc":"middlesbrough",
    "lincoln city":"lincoln", "swansea city":"swansea",
    "as monaco":"monaco", "rc lens":"lens", "racing club de lens":"lens",
    "aj auxerre":"auxerre", "stade brestois 29":"brest",
    "as roma":"roma", "roma fc":"roma", "inter milan":"inter",
    "fc internazionale":"inter",
    "ajax amsterdam":"ajax", "ajax fc":"ajax",
    "willem ii tilburg":"willem ii", "excelsior rotterdam":"excelsior",
    "psv eindhoven":"psv",
    "fc twente":"twente",
    "zeljeznicar pancevo":"zeleznicar pancevo", "zeleznicar pancevo":"zeleznicar pancevo",
    "fk zeleznicar pancevo":"zeleznicar pancevo",
    "radnicki nis":"radnicki nis", "fk radnicki nis":"radnicki nis",
    "ath bilbao":"athletic club", "athletic bilbao":"athletic club",
    "athletic club bilbao":"athletic club", "deportivo alaves":"alaves",
    "deportivo la coruna":"deportivo a coruna", "rc deportivo":"deportivo a coruna",
    "real betis":"betis", "real betis balompie":"betis",
    "r sociedad b":"real sociedad b", "real sociedad ii":"real sociedad b",
    "real sociedad b":"real sociedad b",
    "ud almeria":"almeria", "union deportiva almeria":"almeria",
    "c elta vigo b":"celta vigo b", "rc celta b":"celta vigo b",
    "celta vigo b":"celta vigo b",
    "amedspor":"amedspor", "amed sk":"amedspor", "amed sfk":"amedspor",
    "amed spor":"amedspor", "besiktas jk":"besiktas",
    "besiktas jimnastik kulubu":"besiktas",

    # Dodatne varijante za poslednje preostale neuparene mece
    "bristol c":"bristol city", "bristol city fc":"bristol city",
    "watford fc":"watford", "watford football club":"watford",
    "millwall fc":"millwall", "millwall football club":"millwall",
    "west ham utd":"west ham", "west ham united fc":"west ham",
    "birmingham fc":"birmingham", "birmingham city fc":"birmingham",
    "boro":"middlesbrough", "middlesbrough fc":"middlesbrough",
    "lincoln fc":"lincoln", "lincoln city fc":"lincoln",
    "swansea fc":"swansea", "swansea city fc":"swansea",
    "gil vicente fc":"gil vicente", "gil vicente de barcelos":"gil vicente",
    "maritimo madeira":"maritimo", "cs maritimo":"maritimo", "maritimo fc":"maritimo",
    "zeljeznicar pancevo":"zeleznicar pancevo", "fk zeljeznicar pancevo":"zeleznicar pancevo",
    "zeleznicar pancevo fk":"zeleznicar pancevo",
    "deportivo la coruna":"deportivo a coruna", "deportivo de la coruna":"deportivo a coruna",
    "rc deportivo de la coruna":"deportivo a coruna",
    "real betis balompie":"betis", "real betis balompie s.a.d.":"betis",
    "amed sfk":"amedspor", "amed spor kulubu":"amedspor",
    "besiktas jk":"besiktas", "besiktas jimnastik kulubu":"besiktas",
    "goztepe sk":"goztepe", "goztepe izmir":"goztepe",
    "caykur rizespor":"rizespor", "caykur rizespor kulubu":"rizespor",
    "rizespor kulubu":"rizespor", "caykur rizespor fk":"rizespor",

    # Meridian / BalkanBet varijante iz poslednje provere
    "gil vicente barcelos":"gil vicente",
    "maritimo madeira":"maritimo",
    "rc deportivo de a coruna":"deportivo a coruna",
    "real betis seville":"betis",
    "amed sportif faaliyetler":"amedspor",
    "amed sportif activiteler":"amedspor",
    "besiktas istanbul":"besiktas",
    "besiktas jk":"besiktas",
    "amed":"amedspor",
}

def norm(s):
    s = str(s or "")
    # Neke kladionice povremeno vrate srpske klubove ćirilicom.
    # Pre normalizacije ih prevedemo u latinicu.
    cyr = str.maketrans({
        "А":"A","Б":"B","В":"V","Г":"G","Д":"D","Ђ":"Dj","Е":"E","Ж":"Z","З":"Z",
        "И":"I","Ј":"J","К":"K","Л":"L","Љ":"Lj","М":"M","Н":"N","Њ":"Nj","О":"O",
        "П":"P","Р":"R","С":"S","Т":"T","Ћ":"C","У":"U","Ф":"F","Х":"H","Ц":"C",
        "Ч":"C","Џ":"Dz","Ш":"S",
        "а":"a","б":"b","в":"v","г":"g","д":"d","ђ":"dj","е":"e","ж":"z","з":"z",
        "и":"i","ј":"j","к":"k","л":"l","љ":"lj","м":"m","н":"n","њ":"nj","о":"o",
        "п":"p","р":"r","с":"s","т":"t","ћ":"c","у":"u","ф":"f","х":"h","ц":"c",
        "ч":"c","џ":"dz","ш":"s"
    })
    s = s.translate(cyr)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\b(fc|cf|ac|afc|ssc|fk|nk|sk|sv|sc|calcio|club)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)

def sim(a,b):
    a,b=norm(a),norm(b)
    if not a or not b: return 0.0
    if a==b: return 1.0
    sa,sb=set(a.split()),set(b.split())
    tok=len(sa&sb)/max(1,len(sa|sb))
    return max(tok, SequenceMatcher(None,a,b).ratio())

def match_score(a,b):
    d=(sim(a["home"],b["home"])+sim(a["away"],b["away"]))/2
    r=(sim(a["home"],b["away"])+sim(a["away"],b["home"]))/2
    return max(d,r*0.92)

def best_match(ref,cands,used,threshold=.70):
    best=None; score=0.0
    for c in cands:
        if str(c["id"]) in used: continue
        s=match_score(ref,c)
        if s>score: best,score=c,s
    if best is not None and score>=threshold:
        return best,score
    return None,score

def split_name(name):
    name=str(name or "").strip()
    for sep in (" - "," vs "," – "," v "):
        if sep in name:
            a,b=name.split(sep,1)
            return a.strip(),b.strip()
    return name,""

def generic_event(obj):
    if not isinstance(obj,dict): return None
    eid=obj.get("id") or obj.get("eventId") or obj.get("matchId")
    home=obj.get("home") or obj.get("homeName") or obj.get("homeTeamName")
    away=obj.get("away") or obj.get("awayName") or obj.get("awayTeamName")
    if isinstance(home,dict): home=home.get("name")
    if isinstance(away,dict): away=away.get("name")
    comps=obj.get("competitors") or obj.get("participants") or []
    if (not home or not away) and isinstance(comps,list) and len(comps)>=2:
        def cn(x):
            return x.get("name") if isinstance(x,dict) else str(x)
        home,away=cn(comps[0]),cn(comps[1])
    if not home or not away:
        name=obj.get("name") or obj.get("eventName") or obj.get("matchName")
        h,a=split_name(name)
        home=home or h; away=away or a
    if eid is None or not home or not away:
        return None
    kickoff = next((obj.get(k) for k in ("kickOffTime", "kickoffTime", "startsAt", "startTime", "start") if obj.get(k) not in (None, "")), None)
    return {"id":str(eid),"home":str(home).strip(),"away":str(away).strip(),"kickoff_ts":kickoff}

def recursive_events(data):
    found=[]; seen=set()
    def walk(x):
        if isinstance(x,dict):
            ev=generic_event(x)
            if ev:
                k=(ev["id"],ev["home"],ev["away"])
                if k not in seen:
                    seen.add(k); found.append(ev)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(data)
    return found

# ---------------- SoccerBet / MerkurXtip / MaxBet ----------------

REST = {
    "SoccerBet": ("https://www.soccerbet.rs/restapi/offer/sr","3.3.4",0,"https://www.soccerbet.rs/"),
    "MerkurXtip":("https://www.merkurxtip.rs/restapi/offer/sr","1.23.17",0,"https://www.merkurxtip.rs/"),
    "MaxBet":    ("https://www.maxbet.rs/restapi/offer/sr","1.21.17",3,"https://www.maxbet.rs/"),
    "365":       ("https://ibet2.365.rs/restapi/offer/sr","2.27.33",0,"https://ibet2.365.rs/"),
}

def rest_matches(book,lid):
    base,mobile,annex,ref=REST[book]
    rows=[]
    for league_id in str(lid).split(","):
        league_id = league_id.strip()
        if not league_id:
            continue
        r=requests.get(
            f"{base}/sport/S/league/{league_id}/mob",
            params={"annex":annex,"mobileVersion":mobile,"locale":"sr"},
            headers={"Accept":"application/json","User-Agent":"Mozilla/5.0","Referer":ref},
            timeout=30
        )
        r.raise_for_status()
        for m in (r.json().get("esMatches") or []):
            if m.get("id") and m.get("home") and m.get("away"):
                rows.append({"id":str(m["id"]),"home":str(m["home"]),"away":str(m["away"]),"kickoff_ts":m.get("kickOffTime")})
    return rows

# ---------------- Meridian ----------------

def meridian_matches(lid):
    c=MeridianClient()
    headers=c._auth_headers()
    url="https://online.meridianbet.com/betshop/api/v1/offer/sport/58/league"
    params={"page":0,"time":"ALL","leagues":str(lid)}
    r=c.session.get(url,params=params,headers=headers,timeout=30)
    if r.status_code==401:
        c.access_token=None
        headers=c._auth_headers()
        r=c.session.get(url,params=params,headers=headers,timeout=30)
    r.raise_for_status()
    data=r.json()
    result=[]
    leagues=((data.get("payload") or {}).get("leagues") or [])
    for lg in leagues:
        for e in lg.get("events") or []:
            header=e.get("header") or {}
            rivals=header.get("rivals") or []
            eid=e.get("eventId") or e.get("id") or header.get("eventId") or header.get("id")
            if len(rivals)>=2 and eid is not None:
                def rn(x):
                    if isinstance(x,dict): return x.get("name") or x.get("rivalName") or ""
                    return str(x)
                kickoff = next((e.get(k) for k in ("kickOffTime", "kickoffTime", "startsAt", "startTime", "start") if e.get(k) not in (None, "")), None)
                result.append({"id":str(eid),"home":rn(rivals[0]),"away":rn(rivals[1]),"kickoff_ts":kickoff})
            else:
                ev=generic_event(e)
                if ev: result.append(ev)
    return result

# ---------------- Superbet ----------------


_SUPERBET_ALL_ROWS = None

def _superbet_all_rows():
    global _SUPERBET_ALL_ROWS
    if _SUPERBET_ALL_ROWS is not None:
        return _SUPERBET_ALL_ROWS

    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    api_end = start + timedelta(days=180)
    wanted_end = now + timedelta(days=7)

    tournament_ids = sorted({
        int(part.strip())
        for v in LEAGUES.values() if v.get("Superbet")
        for part in str(v["Superbet"]).split(",") if part.strip()
    })

    params = {
        "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "endDate": api_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "index": "active-prematch",
        "tournaments": ",".join(str(x) for x in tournament_ids),
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://superbet.rs",
        "Referer": "https://superbet.rs/",
        "User-Agent": "Mozilla/5.0",
        "X-Super-Pv": "no_user",
    }

    events = []
    for offset in range(0, len(tournament_ids), 12):
        chunk = tournament_ids[offset:offset + 12]
        chunk_params = dict(params)
        chunk_params["tournaments"] = ",".join(str(x) for x in chunk)
        r = requests.get(
            "https://production-superbet-offer-rs.freetls.fastly.net/sb-rs/api/v3/sr-Latn-RS/events",
            params=chunk_params, headers=headers, timeout=30
        )
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict):
            events.extend(payload.get("events", []) or [])
    rows = []

    for event in events:
        fixture = event.get("fixture") or {}
        tid = fixture.get("tournament_id") or event.get("tournament_id")
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            continue

        raw_date = fixture.get("utc_date")
        dt = None
        if raw_date:
            try:
                dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                pass

        if dt is None:
            millis = event.get("unix_date_millis") or fixture.get("unix_date_millis")
            if millis:
                try:
                    dt = datetime.fromtimestamp(int(millis) / 1000, timezone.utc)
                except Exception:
                    pass

        if dt is None or not (now <= dt <= wanted_end):
            continue

        event_id = event.get("event_id") or event.get("id")
        event_name = fixture.get("event_name") or event.get("name") or ""

        if "·" in event_name:
            home, away = [x.strip() for x in event_name.split("·", 1)]
        elif " - " in event_name:
            home, away = [x.strip() for x in event_name.split(" - ", 1)]
        else:
            continue

        if event_id and home and away:
            rows.append({
                "id": str(event_id),
                "home": home,
                "away": away,
                "tournament_id": tid,
                "kickoff_ts": dt.timestamp() * 1000 if dt else None,
            })

    _SUPERBET_ALL_ROWS = rows
    return rows


def superbet_matches(lid):
    wanted = {str(x).strip() for x in str(lid).split(",") if str(x).strip()}
    return [
        {
            "id": x["id"],
            "home": x["home"],
            "away": x["away"],
            "kickoff_ts": x.get("kickoff_ts"),
        }
        for x in _superbet_all_rows()
        if str(x["tournament_id"]) in wanted
    ]

# ---------------- Mozzart ----------------

def mozzart_matches(cid):
    competition_ids = [int(value) for value in str(cid).split(",") if value.strip()]
    unique_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/153.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://www.mozzartbet.com",
        "Referer": "https://www.mozzartbet.com/",
        "Medium": "PREMATCH_MOBILE",
        "X-Unique-Id": unique_id,
    }
    payload = {
        "date": "all_days",
        "sort": "bycompetition",
        "currentPage": 0,
        "pageSize": 100,
        "sportId": 1,
        "competitionIds": competition_ids,
        "matchTypeId": 0,
        "search": "",
    }

    r = requests.post(
        "https://www.mozzartbet.com/betting/matches",
        json=payload, headers=headers, timeout=30
    )
    r.raise_for_status()
    items = (r.json().get("items") or [])

    rows = []
    for match in items:
        event_id = match.get("id")
        home_obj = match.get("home") or {}
        away_obj = match.get("visitor") or {}
        home = home_obj.get("name") if isinstance(home_obj, dict) else str(home_obj or "")
        away = away_obj.get("name") if isinstance(away_obj, dict) else str(away_obj or "")

        if event_id and home and away:
            rows.append({
                "id": str(event_id),
                "home": home,
                "away": away,
            })

    return rows

# ---------------- BalkanBet ----------------

def balkan_matches(tid):
    data_format={"default":"object","events":"array","outcomes":"object"}
    language={"default":"sr-Latn","events":"sr-Latn","sport":"sr-Latn","category":"sr-Latn","tournament":"sr-Latn","team":"sr-Latn","market":"sr-Latn"}
    params={
        "deliveryPlatformId":3,
        "dataFormat":json.dumps(data_format,separators=(",",":")),
        "language":json.dumps(language,separators=(",",":")),
        "timezone":"Europe/Belgrade","company":"{}",
        "companyUuid":"4f54c6aa-82a9-475d-bf0e-dc02ded89225",
        "filter[tournamentId]":str(tid),
        "filter[from]":datetime.now().replace(microsecond=0).isoformat(),
        "sort":"categoryPosition,categoryName,tournamentPosition,tournamentName,startsAt",
        "offerTemplate":"WEB_OVERVIEW","shortProps":1,
    }
    r=requests.get(
        "https://sports-sm-distribution-api.de-2.nsoftcdn.com/api/v1/events",
        params=params,
        headers={"Accept":"application/json","User-Agent":"Mozilla/5.0","Origin":"https://www.balkanbet.rs","Referer":"https://www.balkanbet.rs/"},
        timeout=30
    )
    r.raise_for_status()
    events=((r.json().get("data") or {}).get("events") or [])
    out=[]
    for e in events:
        if not e.get("a") or not e.get("j"): continue
        h,a=split_name(e.get("j"))
        if h and a: out.append({"id":str(e["a"]),"home":h,"away":a})
    return out

# ---------------- King ----------------


_KING_ALL_TOURNAMENTS = None

def _king_all_tournaments():
    global _KING_ALL_TOURNAMENTS
    if _KING_ALL_TOURNAMENTS is not None:
        return _KING_ALL_TOURNAMENTS

    r = requests.get(
        "https://danteprod.phoenix365-prod.com/partner-api/sportsbook/public/v2/listing/tournaments-with-events",
        params={"sportId": 1, "sportService": "PREMATCH", "offset": 0, "limit": 500},
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/153.0.0.0 Safari/537.36",
            "Referer": "https://king.rs/",
            "Origin": "https://king.rs",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _KING_ALL_TOURNAMENTS = (
        data.get("tournaments")
        or (data.get("data") or {}).get("tournaments")
        or []
    )
    return _KING_ALL_TOURNAMENTS

def king_matches(tid):
    out = []
    for t in _king_all_tournaments():
        if str(t.get("tournamentId") or t.get("id")) != str(tid):
            continue
        for e in t.get("events") or []:
            ev = generic_event(e)
            if ev:
                out.append(ev)
    return out

GETTERS={
    "SoccerBet": lambda lid: rest_matches("SoccerBet",lid),
    "MerkurXtip":lambda lid: rest_matches("MerkurXtip",lid),
    "MaxBet":lambda lid: rest_matches("MaxBet",lid),
    "365":lambda lid: rest_matches("365",lid),
    "Meridian":meridian_matches,
    "Superbet":superbet_matches,
    "Mozzart":mozzart_matches,
    "BalkanBet":balkan_matches,
    "King":king_matches,
}

def main():
    print("="*140)
    print("FOOTBALL MATCHER - 8 KLADIONICA / 17 LIGA")
    print("SoccerBet = referenca")
    print("="*140)

    grand={b:[0,0] for b in BOOKS if b!="SoccerBet"}

    for league,ids in LEAGUES.items():
        print("\n"+"="*140)
        print(league)
        print("="*140)

        try:
            ref=GETTERS["SoccerBet"](ids["SoccerBet"])
        except Exception as e:
            print("SoccerBet GRESKA:",repr(e))
            continue

        print(f"SoccerBet: {len(ref)} meceva")

        all_books={}
        for book in BOOKS:
            if book=="SoccerBet": continue
            try:
                rows=GETTERS[book](ids[book])
                all_books[book]=rows
                print(f"{book}: {len(rows)}")
            except Exception as e:
                all_books[book]=[]
                print(f"{book}: GRESKA {type(e).__name__}: {e}")

        used={b:set() for b in all_books}
        matched={b:0 for b in all_books}

        for r in ref:
            misses=[]
            for book,cands in all_books.items():
                m,s=best_match(r,cands,used[book])
                if m:
                    used[book].add(str(m["id"]))
                    matched[book]+=1
                else:
                    misses.append(f"{book}({s:.2f})")
            if misses:
                print(f'  -- {r["home"]} - {r["away"]} | ' + ", ".join(misses))

        print("REZIME:")
        for book in all_books:
            print(f"  {book:<12} {matched[book]}/{len(ref)}")
            grand[book][0]+=matched[book]
            grand[book][1]+=len(ref)

    print("\n"+"="*140)
    print("UKUPNO SVE LIGE")
    print("="*140)
    for book,(ok,total) in grand.items():
        print(f"{book:<12} {ok}/{total}")

if __name__=="__main__":
    targets = [
        ("Serie B", "Empoli", "Arezzo"),
        ("Turkish Super Lig", "Besiktas", "Erzurumspor"),
    ]
    print("=" * 100)
    print("KING DIJAGNOSTIKA")
    print("=" * 100)
    for league_name, home, away in targets:
        lid = LEAGUES[league_name]["King"]
        cands = king_matches(lid)
        ref = {"id": "ref", "home": home, "away": away}
        ranked = sorted(
            [(match_score(ref, c), c) for c in cands],
            key=lambda x: x[0],
            reverse=True
        )
        print(f"\n{league_name}: {home} - {away}")
        print(f"King ima {len(cands)} meceva u ligi")
        for score, c in ranked[:8]:
            print(f"  {score:.3f} | {c['home']} - {c['away']} | id={c['id']}")
