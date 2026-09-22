from flask import Flask, render_template_string, request, jsonify, session, redirect
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import unicodedata
import football_matcher as fm
import users
from euroleague_portal import euroleague_bp
from nfl_portal import nfl_bp
from football_stats_portal import football_stats_bp
from basketball_points_portal import points_bp
import threading
import time
import requests
import json
import sqlite3
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from meridian import MeridianClient
from superbet import SuperbetClient
from maxbet import MaxBetClient
from mozzart import MozzartClient
from soccerbet import SoccerBetClient
from balkanbet import BalkanBetClient
from king import KingClient

app = Flask(__name__)
app.secret_key = "sports-portal-tajni-kljuc-2026"
users.init_db()
app.register_blueprint(euroleague_bp)
app.register_blueprint(nfl_bp)
app.register_blueprint(football_stats_bp)
app.register_blueprint(points_bp)

BOOKS = ["BalkanBet", "King", "MaxBet", "Meridian",
         "MerkurXtip", "Mozzart", "SoccerBet", "Superbet", "365", "1xBet", "Admiral"]
LEAGUE_LABELS = {
    "Austrian Bundesliga": "Austria 1",
    "Jupiler Pro League": "Belgium 1",
    "HNL": "Croatia 1",
    "Premier League": "England 1",
    "Championship": "England 2",
    "Ligue 1": "France 1",
    "Bundesliga": "Germany 1",
    "2. Bundesliga": "Germany 2",
    "Serie A": "Italy 1",
    "Serie B": "Italy 2",
    "Eredivisie": "Netherlands 1",
    "Primeira Liga": "Portugal 1",
    "Serbian Super Liga": "Serbia 1",
    "LaLiga": "Spain 1",
    "LaLiga 2": "Spain 2",
    "Swiss Super League": "Switzerland 1",
    "Turkish Super Lig": "Turkey 1",
    "UEFA Europa League": "Liga Evrope",
    "UEFA Nations League": "UEFA Liga nacija",
    "UEFA Conference League": "Liga Konferencija",
}

LEAGUE_ORDER = sorted(fm.LEAGUES.keys(), key=lambda x: LEAGUE_LABELS[x])
LEAGUES = ["Sve lige"] + LEAGUE_ORDER
FOOTBALL_DB_PATH = Path("C:/Users/dkecm/Desktop/kvote/football_odds.db")

def slugify(text):
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def _first_value(obj, keys):
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if v not in (None, ""):
            return v
    return None

def _parse_kickoff(value):
    """Vrati unix timestamp početka meča ako ga SoccerBet referenca sadrži."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        x = float(value)
        if x > 10_000_000_000:
            x /= 1000.0
        return x if x > 1_000_000_000 else None
    text = str(value).strip()
    if text.isdigit():
        return _parse_kickoff(float(text))
    try:
        # ISO vreme; ako nema zonu, SoccerBet vreme tretiramo kao lokalno vreme servera.
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.timestamp()
        return dt.timestamp()
    except Exception:
        return None

def _kickoff_from_ref(r):
    direct = _first_value(r, (
        "kickoff_ts", "start_ts", "startTime", "start_time", "startDate", "startDateTime",
        "kickoff", "kickoffTime", "kickOffTime", "eventStart", "eventTime", "dateTime", "date"
    ))
    ts = _parse_kickoff(direct)
    if ts:
        return ts
    for key in ("event", "match", "fixture"):
        nested = r.get(key) if isinstance(r, dict) else None
        if isinstance(nested, dict):
            ts = _parse_kickoff(_first_value(nested, ("startTime","startDate","kickoff","dateTime","date")))
            if ts:
                return ts
    return None

def _logo_from_ref(r, side):
    keys = (
        f"{side}_logo", f"{side}Logo", f"{side}_image", f"{side}Image",
        f"{side}TeamLogo", f"{side}ParticipantLogo"
    )
    return _first_value(r, keys)

def _soccerbet_kickoff_map(league_id):
    """
    football_matcher nam za SoccerBet listing vraća id/home/away,
    ali ne prosleđuje kickOffTime. Zato vreme čitamo direktno iz istog
    SoccerBet league feed-a, jednom po ligi.
    """
    try:
        r = requests.get(
            f"https://www.soccerbet.rs/restapi/offer/sr/sport/S/league/{league_id}/mob",
            params={"annex":0, "mobileVersion":"3.3.4", "locale":"sr"},
            headers={
                "Accept":"application/json",
                "User-Agent":"Mozilla/5.0",
                "Referer":"https://www.soccerbet.rs/"
            },
            timeout=30
        )
        r.raise_for_status()
        data = r.json()
        out = {}
        for m in data.get("esMatches") or []:
            if m.get("id") is not None and m.get("kickOffTime") is not None:
                out[str(m["id"])] = _parse_kickoff(m.get("kickOffTime"))
        return out
    except Exception as e:
        print(f"SoccerBet vreme GRESKA league={league_id}: {e}")
        return {}



_SUPERBET_KICKOFF_MAP = None
_SUPERBET_KICKOFF_LOCK = threading.Lock()

def _load_superbet_kickoff_map():
    """Jednom učitaj tačna vremena iz ISTOG Superbet prematch feed-a koji koristi matcher."""
    global _SUPERBET_KICKOFF_MAP
    if _SUPERBET_KICKOFF_MAP is not None:
        return _SUPERBET_KICKOFF_MAP

    with _SUPERBET_KICKOFF_LOCK:
        if _SUPERBET_KICKOFF_MAP is not None:
            return _SUPERBET_KICKOFF_MAP

        out = {}
        try:
            now = datetime.now(timezone.utc)
            start = now.replace(minute=0, second=0, microsecond=0)
            api_end = start + timedelta(days=180)

            tournament_ids = sorted(int(v["Superbet"]) for v in fm.LEAGUES.values() if v.get("Superbet"))
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

            r = requests.get(
                "https://production-superbet-offer-rs.freetls.fastly.net/sb-rs/api/v3/sr-Latn-RS/events",
                params=params, headers=headers, timeout=30
            )
            r.raise_for_status()
            payload = r.json()
            events = payload.get("events", []) if isinstance(payload, dict) else []

            for event in events:
                fixture = event.get("fixture") or {}
                event_id = event.get("event_id") or event.get("id")
                if event_id is None:
                    continue

                raw_date = fixture.get("utc_date")
                dt = None
                if raw_date:
                    try:
                        dt = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                    except Exception:
                        pass

                if dt is None:
                    millis = event.get("unix_date_millis") or fixture.get("unix_date_millis")
                    if millis:
                        try:
                            dt = datetime.fromtimestamp(int(millis) / 1000, timezone.utc)
                        except Exception:
                            pass

                if dt is not None:
                    out[str(event_id)] = int(dt.timestamp())

        except Exception as e:
            print(f"Superbet kickoff feed GRESKA: {e}")

        _SUPERBET_KICKOFF_MAP = out
        print(f"Rezervna Superbet vremena: {len(out)} (koriste se samo kada primarni izvor nema vreme)")
        return _SUPERBET_KICKOFF_MAP

def _superbet_kickoff_by_id(event_id):
    if not event_id:
        return None
    return _load_superbet_kickoff_map().get(str(event_id))


def _superbet_event_kickoff(event_id):
    if not event_id:
        return None
    try:
        event = SuperbetClient().get_event(event_id)
        if not isinstance(event, dict):
            return None

        # Probaj sam event i najčešće ugnježdene strukture.
        ts = _kickoff_from_ref(event)
        if ts:
            return ts

        fixture = event.get("fixture")
        if isinstance(fixture, dict):
            ts = _kickoff_from_ref(fixture)
            if ts:
                return ts

        # Superbet može koristiti timestamp/start_date varijante.
        candidates = []
        for obj in (event, fixture if isinstance(fixture, dict) else {}):
            for key in (
                "start", "start_date", "startDate", "start_time", "startTime",
                "event_start", "eventStart", "event_time", "eventTime",
                "scheduled", "scheduledAt", "date", "dateTime", "timestamp"
            ):
                if obj.get(key) not in (None, ""):
                    candidates.append(obj.get(key))
        for value in candidates:
            ts = _parse_kickoff(value)
            if ts:
                return ts
    except Exception as e:
        print(f"Superbet vreme GRESKA event={event_id}: {e}")
    return None

def is_started(m, now=None):
    ts = m.get("kickoff_ts")
    return bool(ts and ts <= (now if now is not None else time.time()))

def load_one_league(league_name):
    ids = fm.LEAGUES[league_name]
    fetched = {}

    def get_rows(book):
        if book in fetched:
            return fetched[book]
        lid = ids.get(book)
        if not lid:
            fetched[book] = []
            return []
        try:
            fetched[book] = fm.GETTERS[book](lid)
        except Exception as e:
            print(f"{league_name} | {book} GRESKA: {e}")
            fetched[book] = []
        return fetched[book]

    # Standard leagues: SoccerBet reference when available.
    # UEFA: SoccerBet feed is empty, so prefer Meridian as clean reference,
    # then King / Merkur / MaxBet.
    ref_book = "SoccerBet"
    ref = get_rows("SoccerBet")
    if not ref:
        candidates = ("Meridian", "King", "MerkurXtip", "MaxBet") if league_name.startswith("UEFA ") else ("King","Meridian","MerkurXtip","MaxBet")
        for candidate in candidates:
            rows = get_rows(candidate)
            if rows:
                ref_book = candidate
                ref = rows
                print(f"{league_name}: referenca {candidate} ({len(rows)} mečeva)")
                break

    if not ref:
        print(f"{league_name}: NEMA REFERENTNIH MEČEVA")
        return league_name, []

    # Fetch all available bookmaker league lists.
    for b in BOOKS:
        get_rows(b)

    used = {b: set() for b in BOOKS}
    out = []
    soccerbet_kickoff = _soccerbet_kickoff_map(ids.get("SoccerBet")) if ref_book == "SoccerBet" else {}

    for r in ref:
        ids_by_book = {b: None for b in BOOKS}
        status = {b: False for b in BOOKS}

        # IMPORTANT: reference event ID itself is a valid odds event ID.
        ids_by_book[ref_book] = str(r["id"])
        status[ref_book] = True
        used[ref_book].add(str(r["id"]))

        for book in BOOKS:
            if book == ref_book:
                continue
            rows = fetched.get(book, [])
            if not rows:
                continue
            m, score = fm.best_match(r, rows, used[book])
            if m:
                used[book].add(str(m["id"]))
                ids_by_book[book] = str(m["id"])
                status[book] = True

        # Vreme uzimamo iz već pronađenog Superbet eventa, ako postoji.
        # football_matcher ostaje potpuno netaknut.
        kickoff_ts = None
        superbet_id = ids_by_book.get("Superbet")
        if superbet_id:
            kickoff_ts = _superbet_kickoff_by_id(superbet_id)

        # Za standardne lige, ako je SoccerBet referenca, probaj i njegov feed.
        if kickoff_ts is None and ref_book == "SoccerBet":
            kickoff_ts = soccerbet_kickoff.get(str(r.get("id")))

        out.append({
            "id": slugify(f"{league_name}-{r['home']}-{r['away']}-{r['id']}"),
            "league": league_name,
            "name": f"{r['home']} - {r['away']}",
            "home": r["home"],
            "away": r["away"],
            "kickoff_ts": kickoff_ts,
            "home_logo": _logo_from_ref(r, "home"),
            "away_logo": _logo_from_ref(r, "away"),
            "book_ids": ids_by_book,
            "status": status,
            "matched_count": sum(1 for b in BOOKS if status.get(b)),
        })

    # UEFA diagnostic: show one sample ID map, so failures are visible in CMD.
    if league_name.startswith("UEFA ") and out:
        sample = next((x for x in out if "Milan" in x["name"] and "Benfica" in x["name"]), out[0])
        print(f"{league_name} SAMPLE IDS | {sample['name']} | {sample['book_ids']}")

    return league_name, out

def build_all_matches():
    print("=" * 90)
    print(f"UCITAVAM {len(LEAGUE_ORDER)} LIGA / 8 KLADIONICA")
    print("=" * 90)
    results, errors = {}, []

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(load_one_league, league): league for league in LEAGUE_ORDER}
        for future in as_completed(futures):
            league = futures[future]
            try:
                name, rows = future.result()
                results[name] = rows
                full = sum(1 for x in rows if x["matched_count"] == 8)
                print(f"GOTOVO: {name}: {len(rows)} meceva | svih 8: {full}/{len(rows)}")
            except Exception as e:
                errors.append(f"{league}: {e}")
                results[league] = []
                print(f"GRESKA: {league}: {e}")

    ordered = []
    for league in LEAGUE_ORDER:
        ordered.extend(results.get(league, []))
    print("=" * 90)
    print(f"UKUPNO PREMATCH MECEVA: {len(ordered)}")
    print("=" * 90)
    return ordered, errors

MERIDIAN_LOCK = threading.Lock()

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _norm(v):
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", "", s).lower()

# Svi dogovoreni marketi. Svaki market ima jednu ili dve kolone.
MARKETS = [
    ("1x2", "1X2", ["1","X","2"]),
    ("dnb", "DNB", ["1","2"]),

    ("dc", "Dupla šansa", ["1X","X2"]),
    ("dc2", "Dupla šansa & 2+", ["1X","X2"]),
    ("dc03", "Dupla šansa & 0–3", ["1X","X2"]),

    ("g2", "2+ ukupno", ["DA"]),
    ("g3", "3+ ukupno", ["DA"]),
    ("or2", "2+ I ili 2+ II", ["DA"]),

    ("both", "1+ I & 1+ II", ["DA"]),
    ("h13", "1–3 / 1–3", ["DA"]),
    ("h12", "1–2 / 1–2", ["DA"]),
    ("i1_g2", "1+ I & 2+ ukupno", ["DA"]),
    ("i1_g3", "1+ I & 3+ ukupno", ["DA"]),
    ("h01_02", "0–1 / 0–2", ["DA"]),
    ("h02_02", "0–2 / 0–2", ["DA"]),

    ("fh1", "1+ I poluvreme", ["DA"]),
    ("fh2", "2+ I poluvreme", ["DA"]),
    ("sh1", "1+ II poluvreme", ["DA"]),
    ("sh2", "2+ II poluvreme", ["DA"]),

    ("gg", "GG", ["DA"]),
    ("ggi", "GG I", ["DA"]),

    ("hi1", "Domaćin 1. poluvreme", ["1+","2+"]),
    ("ai1", "Gost 1. poluvreme", ["1+","2+"]),
    ("hi2", "Domaćin 2. poluvreme", ["1+","2+"]),
    ("ai2", "Gost 2. poluvreme", ["1+","2+"]),
    ("hcombo", "Domaćin: 1+ I & 2+ ukupno", ["DA"]),
    ("acombo", "Gost: 1+ I & 2+ ukupno", ["DA"]),
]
MARKET_MAP = {k:(title, cols) for k,title,cols in MARKETS}

# SoccerBet i MerkurXtip koriste istu familiju TT kodova za ove fudbalske tipove.
TT = {
    "1x2": {"1":1, "X":2, "2":3},
    "dnb": {"1":264, "2":265},
    "g1": {"DA":406}, "g2":{"DA":242}, "g3":{"DA":24},
    "fh1":{"DA":207}, "fh2":{"DA":208},
    "sh1":{"DA":213}, "sh2":{"DA":214},
    "both":{"DA":363},
    "h13":{"DA":51568}, "h12":{"DA":51428},
    "h01_02":{"DA":50740}, "h02_02":{"DA":50743},
    "dc":{"1X":7, "X2":9},
    "dc2":{"1X":575, "X2":577},
    "dc03":{"1X":570, "X2":572},
    "gg":{"DA":272}, "ggi":{"DA":291},
    "or2":{"DA":50313},
    "i1_g2":{"DA":50310}, "i1_g3":{"DA":50311},
    "hi1":{"1+":307, "2+":274}, "ai1":{"1+":308, "2+":275},
    "hi2":{"1+":312, "2+":297}, "ai2":{"1+":313, "2+":298},
    "hcombo":{"DA":50690}, "acombo":{"DA":50696},
}

# Standardne skraćenice koje se pojavljuju kod MaxBet/Meridian/Mozzart/BalkanBet.
ALIASES = {
    "1": ("1x2","1"), "x":("1x2","X"), "2":("1x2","2"),
    "w1":("dnb","1"), "w2":("dnb","2"),
    "1+":("g1","DA"), "2+":("g2","DA"), "3+":("g3","DA"),
    "i1+&ii1+":("both","DA"), "1+i&1+ii":("both","DA"),
    "i1-3&ii1-3":("h13","DA"), "i1-2&ii1-2":("h12","DA"),
    "i0-1&ii0-2":("h01_02","DA"), "i0-2&ii0-2":("h02_02","DA"),
    "1x":("dc","1X"), "x2":("dc","X2"),
    "1x&2+":("dc2","1X"), "x2&2+":("dc2","X2"),
    "1x&0-3":("dc03","1X"), "x2&0-3":("dc03","X2"),
    "gg":("gg","DA"), "igg":("ggi","DA"),
    "i2+vii2+":("or2","DA"), "i2+iliii2+":("or2","DA"),
    "i1+&2+":("i1_g2","DA"), "i1+&3+":("i1_g3","DA"),
    "di1+":("hi1","1+"), "di2+":("hi1","2+"),
    "gi1+":("ai1","1+"), "gi2+":("ai1","2+"),
    "dii1+":("hi2","1+"), "dii2+":("hi2","2+"),
    "gii1+":("ai2","1+"), "gii2+":("ai2","2+"),
    "di1+&d2+":("hcombo","DA"), "gi1+&g2+":("acombo","DA"),
}

def empty_markets():
    return {k:{} for k,_,_ in MARKETS}

def put(out, market, col, value):
    v = _num(value)
    if v is not None:
        out.setdefault(market,{})[col] = v

def map_caption(out, caption, price, allow_plain=True):
    n = _norm(caption).replace("–","-")
    hit = ALIASES.get(n)
    if hit:
        # Plain 1/X/2 and 1+/2+/3+ can be ambiguous in non-main groups.
        if not allow_plain and n in ("1","x","2","1+","2+","3+"):
            return
        put(out, hit[0], hit[1], price)

def get_soccerbet_all(event_id):
    c = SoccerBetClient()
    event = c.get_event(event_id)
    out = empty_markets()
    for mk, cols in TT.items():
        for col, code in cols.items():
            put(out, mk, col, c._odd_from_tt(event, code))
    return out

def get_merkur_all(event_id):
    url = f"https://www.merkurxtip.rs/restapi/offer/sr/match/{event_id}"
    r = requests.get(url,
        params={"annex":0,"getChildrenLeagueCategories":"true","mobileVersion":"1.23.17","locale":"sr"},
        headers={"Accept":"application/json, text/plain, */*","User-Agent":"Mozilla/5.0",
                 "Referer":"https://www.merkurxtip.rs/","Origin":"https://www.merkurxtip.rs"},
        timeout=25)
    r.raise_for_status()
    event = r.json()
    out = empty_markets()
    for mk, cols in TT.items():
        for col, code in cols.items():
            put(out, mk, col, _rest_odd(event, code))
    return out

def get_365_all(event_id):
    session = requests.Session()
    session.trust_env = False
    r = session.get(
        f"https://ibet2.365.rs/restapi/offer/sr/match/{event_id}",
        params={"annex": 0, "mobileVersion": "2.27.33", "locale": "sr"},
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                 "Referer": "https://ibet2.365.rs/"}, timeout=25)
    r.raise_for_status()
    event = r.json()
    out = empty_markets()
    for mk, cols in TT.items():
        for col, code in cols.items():
            put(out, mk, col, _rest_odd(event, code))
    return out

def _rest_odd(event, tt):
    root = event.get("odds") or event.get("betMap") or {}
    group = root.get(str(tt))
    direct = _num(group)
    if direct is not None:
        return direct
    if not isinstance(group, dict):
        return None
    item = group.get("NULL")
    if isinstance(item, dict):
        if item.get("s") not in (None,"U"):
            return None
        return _num(item.get("ov") if "ov" in item else item.get("price"))
    vals = [x for x in group.values() if isinstance(x,dict)]
    if len(vals)==1:
        item=vals[0]
        if item.get("s") not in (None,"U"):
            return None
        return _num(item.get("ov") if "ov" in item else item.get("price"))
    return None

def get_balkanbet_all(event_id):
    c = BalkanBetClient()
    event = c.get_event(event_id)
    out = empty_markets()

    for market in event.get("markets") or []:
        mid = market.get("marketId")
        for o in market.get("outcomes") or []:
            if o.get("active") not in (1, True, None):
                continue
            name = str(o.get("name") or o.get("shortcut") or "")
            price = o.get("odd")
            n = _norm(name).replace("–","-")

            # 1X2
            if mid == 6:
                if n == "0": n = "x"
                if n in ("1","x","2"):
                    put(out, "1x2", n.upper() if n=="x" else n, price)
                continue

            # DNB
            if mid == 389:
                if n in ("w1","1"): put(out,"dnb","1",price)
                elif n in ("w2","2"): put(out,"dnb","2",price)
                continue

            # Ukupno golova
            if mid == 443:
                if n == "2+": put(out,"g2","DA",price)
                elif n == "3+": put(out,"g3","DA",price)

            # Golovi prvo poluvreme
            if mid == 428:
                if n in ("i1+","1+"): put(out,"fh1","DA",price)
                elif n in ("i2+","2+"): put(out,"fh2","DA",price)

            # Golovi drugo poluvreme
            if mid == 431:
                if n in ("ii1+","1+"): put(out,"sh1","DA",price)
                elif n in ("ii2+","2+"): put(out,"sh2","DA",price)

            map_caption(out, name, price, allow_plain=False)

    return out


def get_maxbet_all(event_id):
    out = empty_markets()
    odds = MaxBetClient().get_all_odds(event_id)

    TIP_MAP = {
        "KI_1": ("1x2","1"), "KI_X":("1x2","X"), "KI_2":("1x2","2"),
        "G_W1":("dnb","1"), "G_W2":("dnb","2"),
        "G2_PLUS":("g2","DA"), "G3_PLUS":("g3","DA"),
        "G1P1_PLUS":("fh1","DA"), "G1P2_PLUS":("fh2","DA"),
        "G2P1_PLUS":("sh1","DA"), "G2P2_PLUS":("sh2","DA"),
        "P1_PLUS_D1_PLUS":("both","DA"),
        "G1P1_3_G2P1_3":("h13","DA"),
        "G1P1_2_G2P1_2":("h12","DA"),
        "G1P0_1_G2P0_2":("h01_02","DA"),
        "G1P0_2_G2P0_2":("h02_02","DA"),
        "P2_PLUS_ILI_D2_PLUS":("or2","DA"),
        "P1_PLUS_2_PLUS":("i1_g2","DA"),
        "P1_PLUS_3_PLUS":("i1_g3","DA"),
        "DS_1X_2_PLUS":("dc2","1X"), "DS_X2_2_PLUS":("dc2","X2"),
        "DS_1X_0_3":("dc03","1X"), "DS_X2_0_3":("dc03","X2"),
        "G1H1_PLUS":("hi1","1+"), "G1H2_PLUS":("hi1","2+"),
        "G1A1_PLUS":("ai1","1+"), "G1A2_PLUS":("ai1","2+"),
        "DH1_PLUS":("hi2","1+"), "G2H2_PLUS":("hi2","2+"),
        "DA1_PLUS":("ai2","1+"), "G2A2_PLUS":("ai2","2+"),
        "GH1P1_PLUS_GH2_PLUS":("hcombo","DA"),
        "GA1P1_PLUS_GA2_PLUS":("acombo","DA"),
        "GG_1":("ggi","DA"),
    }

    for o in odds:
        caption = str(o.get("caption") or "")
        tip = str(o.get("tipTypeName") or "")
        label = str(o.get("label") or "")
        price = o.get("price")

        if tip in TIP_MAP:
            mk,col = TIP_MAP[tip]
            put(out,mk,col,price)
            continue

        # GG glavni market.
        if _norm(caption) == "gg" and "prvom" not in _norm(label):
            put(out,"gg","DA",price)

        # DC glavni.
        if _norm(caption) == "1x":
            put(out,"dc","1X",price)
        elif _norm(caption) == "x2":
            put(out,"dc","X2",price)

        # Fallback za već potvrđene skraćenice.
        map_caption(out, caption, price, allow_plain=False)

    return out


def get_meridian_all(event_id):
    out = empty_markets()
    with MERIDIAN_LOCK:
        data = MeridianClient().get_all_markets(event_id)

    for item in data:
        tid = str(item.get("gameTemplateId") or "")
        for market in item.get("markets") or []:
            line = str(market.get("overUnder"))
            for s in market.get("selections") or []:
                if s.get("state") != "ACTIVE":
                    continue
                name = str(s.get("name") or "")
                price = s.get("price")
                n = _norm(name)

                if tid=="3999" and n in ("1","x","2"):
                    put(out,"1x2", n.upper() if n=="x" else n, price); continue
                if tid=="4117" and n in ("1","2"):
                    put(out,"dnb",n,price); continue

                if tid=="4004" and n.startswith("vise"):
                    if line=="1.5": put(out,"g2","DA",price)
                    elif line=="2.5": put(out,"g3","DA",price)
                    continue

                # Ukupni golovi po poluvremenima.
                if tid=="4018" and n.startswith("vise"):
                    if line=="0.5": put(out,"fh1","DA",price)
                    elif line=="1.5": put(out,"fh2","DA",price)
                    continue
                if tid=="4043" and n.startswith("vise"):
                    if line=="0.5": put(out,"sh1","DA",price)
                    elif line=="1.5": put(out,"sh2","DA",price)
                    continue

                # Team totals.
                if tid=="4023" and n.startswith("vise"):
                    if line=="0.5": put(out,"hi1","1+",price)
                    elif line=="1.5": put(out,"hi1","2+",price)
                    continue
                if tid=="4026" and n.startswith("vise"):
                    if line=="0.5": put(out,"ai1","1+",price)
                    elif line=="1.5": put(out,"ai1","2+",price)
                    continue
                if tid=="4047" and n.startswith("vise"):
                    if line=="0.5": put(out,"hi2","1+",price)
                    elif line=="1.5": put(out,"hi2","2+",price)
                    continue
                if tid=="4049" and n.startswith("vise"):
                    if line=="0.5": put(out,"ai2","1+",price)
                    elif line=="1.5": put(out,"ai2","2+",price)
                    continue

                # Ostali marketi imaju dovoljno karakteristična imena.
                map_caption(out,name,price,allow_plain=False)

                # Eksplicitni Meridian nazivi.
                nn = _norm(name).replace("–","-")
                if tid=="4021" and nn in ("igg","gg"): put(out,"ggi","DA",price)
                elif tid=="4007" and nn=="gg": put(out,"gg","DA",price)
                elif tid=="4008":
                    if nn=="1x": put(out,"dc","1X",price)
                    elif nn=="x2": put(out,"dc","X2",price)
                elif tid=="4719":
                    if nn=="1x&2+": put(out,"dc2","1X",price)
                    elif nn=="x2&2+": put(out,"dc2","X2",price)
                elif tid=="4721":
                    if nn=="1x&0-3": put(out,"dc03","1X",price)
                    elif nn=="x2&0-3": put(out,"dc03","X2",price)
                elif tid=="4643" and "i1+&ii1+" in nn: put(out,"both","DA",price)
                elif tid=="4646":
                    if nn=="i1-3&ii1-3": put(out,"h13","DA",price)
                    elif nn=="i1-2&ii1-2": put(out,"h12","DA",price)
                    elif nn=="i0-1&ii0-2": put(out,"h01_02","DA",price)
                    elif nn=="i0-2&ii0-2": put(out,"h02_02","DA",price)
                elif tid=="4728" and ("i2+iliii2+" in nn or "i2+vii2+" in nn):
                    put(out,"or2","DA",price)
                elif tid=="5122":
                    if "i1+&2+" in nn: put(out,"i1_g2","DA",price)
                    elif "i1+&3+" in nn: put(out,"i1_g3","DA",price)
                elif tid=="5123":
                    if "di1+&d2+" in nn: put(out,"hcombo","DA",price)
                    elif "gi1+&g2+" in nn: put(out,"acombo","DA",price)

    return out


def get_mozzart_all(event_id):
    out = empty_markets()
    groups = MozzartClient().get_markets(event_id)

    for g in groups:
        gname = _norm(g.get("groupName"))
        for o in g.get("odds") or []:
            if o.get("oddStatus") != "ACTIVE":
                continue
            sg = o.get("subgame") or {}
            name = str(sg.get("name") or "")
            n = _norm(name).replace("–","-")
            price = o.get("value")

            if gname=="konacanishod" and n in ("1","x","2"):
                put(out,"1x2", n.upper() if n=="x" else n, price); continue

            if gname=="duplasansa":
                if n=="1x": put(out,"dc","1X",price)
                elif n=="x2": put(out,"dc","X2",price)
                continue

            if gname=="ukupnogolovanamecu":
                if n=="2+": put(out,"g2","DA",price)
                elif n=="3+": put(out,"g3","DA",price)
                continue

            if gname=="obatimadajugol":
                if n=="gg": put(out,"gg","DA",price)
                elif n=="1gg": put(out,"ggi","DA",price)

            if gname=="ukupnogolovaprvopoluvreme":
                if n=="1+": put(out,"fh1","DA",price)
                elif n=="2+": put(out,"fh2","DA",price)
                continue

            if gname=="ukupnogolovadrugopoluvreme":
                if n=="1+": put(out,"sh1","DA",price)
                elif n=="2+": put(out,"sh2","DA",price)
                continue

            if gname=="tim1goloviprvopoluvreme":
                if n=="1+": put(out,"hi1","1+",price)
                elif n=="2+": put(out,"hi1","2+",price)
                continue
            if gname=="tim2goloviprvopoluvreme":
                if n=="1+": put(out,"ai1","1+",price)
                elif n=="2+": put(out,"ai1","2+",price)
                continue
            if gname=="tim1golovidrugopoluvreme":
                if n=="1+": put(out,"hi2","1+",price)
                elif n=="2+": put(out,"hi2","2+",price)
                continue
            if gname=="tim2golovidrugopoluvreme":
                if n=="1+": put(out,"ai2","1+",price)
                elif n=="2+": put(out,"ai2","2+",price)
                continue

            # Timske kombinacije:
            # domaćin/gost postiže 1+ u I poluvremenu i 2+ ukupno na meču.
            if gname=="tim1dajegol" and n=="i1+&2+":
                put(out,"hcombo","DA",price)
                continue
            if gname=="tim2dajegol" and n=="i1+&2+":
                put(out,"acombo","DA",price)
                continue

            if gname=="brojgolovauprvomidrugompoluvremenu":
                if n=="1+i&1+ii": put(out,"both","DA",price)

            if gname=="duplasansa+golovi":
                if n=="1x&2+": put(out,"dc2","1X",price)
                elif n=="x2&2+": put(out,"dc2","X2",price)
                elif n=="1x&0-3": put(out,"dc03","1X",price)
                elif n=="x2&0-3": put(out,"dc03","X2",price)

            # Potvrđene kompleksne skraćenice.
            map_caption(out,name,price,allow_plain=False)

        # DNB grupa, ako postoji.
        if ("bezneresen" in gname or "drawnobet" in gname):
            active=[o for o in g.get("odds") or [] if o.get("oddStatus")=="ACTIVE"]
            if len(active)>=2:
                put(out,"dnb","1",active[0].get("value"))
                put(out,"dnb","2",active[1].get("value"))

    return out


def get_superbet_all(event_id):
    out=empty_markets()
    c=SuperbetClient(); event=c.get_event(event_id)
    if not event: return out
    for m in event.get("markets") or []:
        mid=str(m.get("id"))
        for o in c.market_odds(m):
            name=str(o.get("name") or "")
            info=str(o.get("info") or "")
            price=o.get("price")
            n=_norm(name)
            if mid=="547" and n in ("1","x","2"):
                put(out,"1x2",n.upper() if n=="x" else n,price)
            elif mid=="555":
                code = None
                # market_odds ne vraća code; redosled/naziv tima: koristimo info tekst.
                if "pobeđuje" in info:
                    if not out["dnb"].get("1"): put(out,"dnb","1",price)
                    else: put(out,"dnb","2",price)
            elif mid=="200734" and n.startswith("vise"):
                if "0.5" in n: put(out,"g1","DA",price)
                elif "1.5" in n: put(out,"g2","DA",price)
                elif "2.5" in n: put(out,"g3","DA",price)
            elif mid=="200735" and n.startswith("vise"):
                if "0.5" in n: put(out,"fh1","DA",price)
                elif "1.5" in n: put(out,"fh2","DA",price)
            elif mid=="200738" and n.startswith("vise"):
                if "0.5" in n: put(out,"sh1","DA",price)
                elif "1.5" in n: put(out,"sh2","DA",price)
            elif mid=="531":
                if n=="1x": put(out,"dc","1X",price)
                elif n=="x2": put(out,"dc","X2",price)
            elif mid=="542":
                mname = _norm(m.get("name"))
                # 2+ ukupno = više od 1.5; 0-3 = manje od 3.5.
                if "(1.5)" in str(m.get("name")):
                    if n=="1x&viseod1.5": put(out,"dc2","1X",price)
                    elif n=="x2&viseod1.5": put(out,"dc2","X2",price)
                elif "(3.5)" in str(m.get("name")):
                    if n=="1x&manjeod3.5": put(out,"dc03","1X",price)
                    elif n=="x2&manjeod3.5": put(out,"dc03","X2",price)
            elif mid=="539" and n=="da": put(out,"gg","DA",price)
            elif mid=="565" and n=="da": put(out,"ggi","DA",price)
            elif mid=="201803":
                if n=="1-3": put(out,"h13","DA",price)
                elif n=="1-2": put(out,"h12","DA",price)
            elif mid=="201505":
                if "vise0.5&vise0.5" in n: put(out,"both","DA",price)
                elif "manje1.5&manje2.5" in n: put(out,"h01_02","DA",price)
                elif "manje2.5&manje2.5" in n: put(out,"h02_02","DA",price)
            elif mid=="201520" and n=="vise1.5ilivise1.5": put(out,"or2","DA",price)
            elif mid=="231389":
                if "vise0.5&vise1.5" in n: put(out,"i1_g2","DA",price)
                elif "vise0.5&vise2.5" in n: put(out,"i1_g3","DA",price)
            elif mid=="231525" and "vise0.5&vise1.5" in n: put(out,"hcombo","DA",price)
            elif mid=="231526" and "vise0.5&vise1.5" in n: put(out,"acombo","DA",price)
            elif mid in ("2529","2531","201506","201507") and n.startswith("vise"):
                target={"2529":"hi1","2531":"ai1","201506":"hi2","201507":"ai2"}[mid]
                if "0.5" in n: put(out,target,"1+",price)
                elif "1.5" in n: put(out,target,"2+",price)
    return out

def get_king_all(event_id):
    out = empty_markets()
    c = KingClient()
    groups = c.get_all_markets(event_id)

    def clean_spec(market):
        raw = (
            market.get("specifier")
            or market.get("specifiers")
            or market.get("specialBetValue")
            or ""
        )
        # King nekad vrati broj/string, a nekad strukturu.
        if isinstance(raw, dict):
            for k in ("total", "value", "line", "handicap"):
                if raw.get(k) is not None:
                    raw = raw.get(k)
                    break
        s = str(raw).strip()
        hit = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", "."))
        return hit.group(0) if hit else s

    for g in groups:
        mid = str(g.get("marketTypeId"))
        markets = g.get("markets") or []

        for market in markets:
            spec = clean_spec(market)
            outcomes = [o for o in (market.get("outcomes") or []) if isinstance(o, dict)]
            vals = []

            for o in outcomes:
                price = (
                    c._odd_value(o)
                    if hasattr(c, "_odd_value")
                    else _num(o.get("odd") or o.get("price") or o.get("value"))
                )
                name = str(o.get("name") or o.get("shortName") or o.get("label") or "")
                vals.append((name, price))
                n = _norm(name)

                # Glavni total: 2+ i 3+.
                if mid == "103" and n == "over":
                    if spec == "1.5":
                        put(out, "g2", "DA", price)
                    elif spec == "2.5":
                        put(out, "g3", "DA", price)

                # Ukupan broj golova u I poluvremenu.
                elif mid == "3" and n == "over":
                    if spec == "0.5":
                        put(out, "fh1", "DA", price)
                    elif spec == "1.5":
                        put(out, "fh2", "DA", price)

                # Ukupan broj golova u II poluvremenu.
                elif mid == "91" and n == "over":
                    if spec == "0.5":
                        put(out, "sh1", "DA", price)
                    elif spec == "1.5":
                        put(out, "sh2", "DA", price)

                # Dupla šansa.
                elif mid == "23":
                    if n == "1x":
                        put(out, "dc", "1X", price)
                    elif n == "x2":
                        put(out, "dc", "X2", price)

                # GG / GG I / gol u oba poluvremena.
                elif mid == "119" and n == "yes":
                    put(out, "gg", "DA", price)
                elif mid == "50852" and n == "yes":
                    put(out, "ggi", "DA", price)
                elif mid == "66" and n == "yes":
                    put(out, "both", "DA", price)

                # Domaćin - I poluvreme timski golovi.
                elif mid == "31" and n == "over":
                    if spec == "0.5":
                        put(out, "hi1", "1+", price)
                    elif spec == "1.5":
                        put(out, "hi1", "2+", price)

                # Gost - I poluvreme timski golovi.
                elif mid == "96" and n == "over":
                    if spec == "0.5":
                        put(out, "ai1", "1+", price)
                    elif spec == "1.5":
                        put(out, "ai1", "2+", price)

                # Domaćin - II poluvreme 1+.
                elif mid == "560" and n == "yes":
                    put(out, "hi2", "1+", price)

                # Gost - II poluvreme 1+.
                elif mid == "659" and n == "yes":
                    put(out, "ai2", "1+", price)

                # Domaćin - II poluvreme 2+.
                # U King katalogu "Or More" je 2 ili više golova.
                elif mid == "600" and n == "ormore":
                    put(out, "hi2", "2+", price)

                # Gost - II poluvreme 2+.
                elif mid == "52040" and n == "ormore":
                    put(out, "ai2", "2+", price)

            # 1X2: King koristi imena timova umesto 1 i 2.
            if mid == "77" and vals:
                if len(vals) >= 1:
                    put(out, "1x2", "1", vals[0][1])
                for nm, pr in vals:
                    if _norm(nm) == "x":
                        put(out, "1x2", "X", pr)
                if len(vals) >= 3:
                    put(out, "1x2", "2", vals[-1][1])

            # DNB: dva outcome-a = domaćin / gost.
            if mid == "360" and len(vals) >= 2:
                put(out, "dnb", "1", vals[0][1])
                put(out, "dnb", "2", vals[-1][1])

    return out

ALL_GETTERS = {
    "BalkanBet":get_balkanbet_all, "King":get_king_all, "MaxBet":get_maxbet_all,
    "Meridian":get_meridian_all, "MerkurXtip":get_merkur_all, "Mozzart":get_mozzart_all,
    "SoccerBet":get_soccerbet_all, "Superbet":get_superbet_all,
    "365":get_365_all,
}

# Fudbalske rute čitaju samo bazu; collectori iznad nisu deo request toka.
def _football_connection():
    return sqlite3.connect(FOOTBALL_DB_PATH.as_uri() + "?mode=ro", uri=True, timeout=5)


def load_matches_from_db():
    with closing(_football_connection()) as con:
        records = con.execute(
            "SELECT match_id, league, home, away, kickoff_ts, book_ids_json, matched_count FROM matches"
        ).fetchall()
    matches = []
    for mid, league, home, away, kickoff, raw_ids, count in records:
        try:
            ids = json.loads(raw_ids or "{}")
        except (TypeError, ValueError):
            ids = {}
        if not isinstance(ids, dict):
            ids = {}
        matches.append({
            "id": mid, "league": league, "name": f"{home} - {away}",
            "home": home, "away": away, "kickoff_ts": kickoff,
            "home_logo": None, "away_logo": None,
            "book_ids": ids, "status": {book: bool(ids.get(book)) for book in BOOKS},
            "matched_count": count or 0,
        })
    return matches


def match_by_id(mid):
    return next((m for m in load_matches_from_db() if m["id"] == mid), None)


def _load_saved_markets(match_ids):
    ids = list(dict.fromkeys(match_ids))
    if not ids:
        return {}
    grouped = {}
    with closing(_football_connection()) as con:
        # Batch-evi ostaju ispod SQLite limita parametara.
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            placeholders = ",".join("?" for _ in batch)
            records = con.execute(
                "SELECT match_id, bookmaker, market_key, selection_key, odd "
                f"FROM current_odds WHERE match_id IN ({placeholders})", batch
            ).fetchall()
            for mid, book, key, selection, odd in records:
                grouped.setdefault(mid, {}).setdefault(book, {}).setdefault(key, {})[selection] = odd
    return {mid: _market_blocks(rows) for mid, rows in grouped.items()}


def load_all_markets(match):
    return _load_saved_markets([match["id"]]).get(match["id"], _market_blocks({}))


def _market_blocks(rows):
    errors = {}
    blocks=[]
    for key,title,cols in MARKETS:
        best={}; worst={}
        for col in cols:
            vals=[rows.get(b,{}).get(key,{}).get(col) for b in BOOKS]
            vals=[v for v in vals if isinstance(v,(int,float))]
            best[col]=max(vals) if vals else None
            worst[col]=min(vals) if len(set(vals))>1 else None
        blocks.append({
            "key":key,"title":title,"cols":cols,
            "rows":[{"book":b,"odds":rows.get(b,{}).get(key,{})} for b in BOOKS],
            "best":best,"worst":worst
        })
    return {"blocks":blocks,"errors":errors}

HTML = r"""
<!doctype html>
<html lang="sr">
<head>
<meta charset="utf-8">
<title>Poređenje kvota - fudbal</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0f1722;color:#f1f5f9;font-family:Arial,sans-serif}
.wrap{max-width:1450px;margin:auto;padding:34px 28px 80px}
h1{margin:0 0 8px;font-size:38px}
.sub{color:#94a3b8;margin-bottom:24px}
.portal-back{position:fixed;top:28px;right:40px;z-index:1001;color:#f4d35e;text-decoration:none;font-weight:bold}

.leagues{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px}
.league{text-decoration:none;color:#cbd5e1;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:9px 12px;font-weight:bold;font-size:14px}
.league:hover{background:#293548}
.league.active{background:#2563eb;border-color:#2563eb;color:white}

.filterbox{background:#131e2b;border:1px solid #2d3a4a;border-radius:12px;padding:14px 16px;margin:0 0 26px}
.filterhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.filtertitle{font-weight:bold;color:#9fb3c8}
.filteractions{display:flex;gap:7px}
.smallbtn{border:1px solid #3a4b60;background:#1b2838;color:#dbe6f2;border-radius:7px;padding:6px 10px;cursor:pointer}
.smallbtn:hover{background:#26364a}
.marketfilters{display:flex;flex-wrap:wrap;gap:7px}
.marketpill{display:flex;align-items:center;gap:6px;border:1px solid #334155;background:#1b2735;color:#cbd5e1;border-radius:8px;padding:7px 10px;font-size:13px;cursor:pointer;user-select:none}
.marketpill input{accent-color:#2563eb}
.marketpill:has(input:checked){background:#1f3e68;border-color:#3b82f6;color:#fff}

.section-title{color:#60a5fa;font-size:23px;font-weight:bold;margin:28px 0 12px}
.card{background:#151f2c;border:1px solid #2d3a4a;border-radius:12px;padding:17px 20px;margin-bottom:10px}
.card:hover{border-color:#48617d}
.top{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
.matchmain{display:flex;align-items:center;gap:10px;min-width:0}
.crest{width:34px;height:34px;border-radius:50%;background:#223247;border:1px solid #3b5069;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:bold;color:#b9cbe0;overflow:hidden;flex:0 0 34px}
.crest img{width:100%;height:100%;object-fit:contain;background:#fff}
.matchtext{min-width:0}
.teams{font-size:20px;font-weight:bold}
.kickoff{color:#f4d35e;font-size:13px;font-weight:bold;margin-top:4px;letter-spacing:.2px}
.count{color:#94a3b8;font-weight:bold}
.quickodds{display:flex;flex-wrap:nowrap;gap:7px;margin-top:12px;overflow-x:auto;overflow-y:hidden;padding:2px 2px 6px;scrollbar-color:#48617d #101a26}
.quickodd{cursor:pointer}
.quickodd.pickselected{border-color:#22c55e;background:#173b35}
.quickodd{min-width:68px;border:1px solid #334155;background:#101a26;border-radius:7px;padding:6px 8px;text-align:center}
.quicklabel{display:block;color:#8196ad;font-size:10px;margin-bottom:2px}
.quickvalue{font-size:14px;font-weight:bold;color:#e7eef7}
.quickvalue.best{color:#62d98b}

.books{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}
.matchzone{cursor:pointer;margin:-17px -20px 0;padding:17px 20px 2px}
.matchzone:hover{background:rgba(72,97,125,.08);border-radius:7px}
.book{padding:5px 8px;border-radius:6px;font-size:13px;border:1px solid #334155;background:#202b38}
.book.missing{color:#ff8a8a;border-color:#66353a;background:#2b1b20}
.hint{color:#7890aa;font-size:12px;margin-top:10px}

.oddsbox{display:none;margin-top:16px;border-top:1px solid #2d3a4a;padding-top:14px}
.oddsbox.open{display:block}
.marketsgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:0 34px}
.market{margin:0 0 24px}
.markettitle{font-weight:bold;color:#f4d35e;margin:0 0 7px;font-size:17px}
table{width:100%;border-collapse:collapse;max-width:720px}
th,td{padding:7px 12px;border-bottom:1px solid #2d3a4a;text-align:center}
th:first-child,td:first-child{text-align:left}
th{color:#9fb3c8}
.best{color:#62d98b;font-weight:bold}
.worst{color:#ff7777;font-weight:bold}
.oddcell{cursor:pointer;border-radius:5px;transition:.12s}
.oddcell:hover{background:#25374a}
.oddcell.pickselected{background:#273f5b;outline:1px solid #5b8fc4}
.dash{color:#7d8da0}
.loading,.empty{color:#94a3b8}
.error{color:#ffb4b4;margin:8px 0}

.ticket{display:none;position:fixed;right:18px;bottom:18px;width:390px;max-height:78vh;overflow:auto;background:#241927;border:1px solid #875f78;border-radius:13px;box-shadow:0 14px 44px rgba(0,0,0,.58);z-index:1000;transition:.18s}
.ticket.show{display:block}
.ticket.collapsed{width:245px;max-height:58px;overflow:hidden}
.ticket.collapsed .ticketbody{display:none}
.tickethead{position:sticky;top:0;background:#342033;padding:14px 16px;border-bottom:1px solid #704b65;display:flex;justify-content:space-between;align-items:center}
.tickettop{font-size:19px;font-weight:bold;color:#ffd166}
.ticketcontrols{display:flex;gap:7px;align-items:center}
.collapsebtn{border:1px solid #8f6884;background:#4a2e46;color:#e9bed3;border-radius:7px;padding:5px 9px;cursor:pointer;font-size:16px;line-height:1}
.ticketbody{padding:12px 16px 16px;background:#241927}
.ticketpick{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid #51384d;padding:9px 0;font-size:13px}
.ticketpickname{line-height:1.4;color:#cbb7c9}
.ticketpickname b{color:#f1d5e2}
.remove{border:0;background:transparent;color:#ff8a8a;cursor:pointer;font-size:18px}
.tickettable{margin-top:12px;width:100%}
.tickettable td,.tickettable th{padding:8px 5px;border-bottom:1px solid #51384d}
.tickettable th{color:#d49ab7;font-weight:bold}
.ticketbook{color:#f1c75b;font-weight:bold}
.ticketodd{color:#7db7ff;font-weight:bold}
.tickettotal{font-weight:bold}
.clearbtn{border:1px solid #704653;background:#3b232c;color:#ffb1bd;border-radius:7px;padding:6px 9px;cursor:pointer}
.ticketnote{font-size:11px;color:#a68ca0;margin-top:8px}

@media(max-width:800px){
 .marketsgrid{grid-template-columns:1fr}
 .wrap{padding:22px 12px 80px}
 .portal-back{top:18px;right:16px}
 .ticket{left:10px;right:10px;width:auto}
}
</style>
</head>
<body>
<a class="portal-back" href="/portal">← Sports Portal</a>
<div class="wrap">
<h1>Poređenje kvota</h1>
<div class="sub">Fudbal · {{league_count}} liga · {{books|length}} kladionica · {{total}} PREMATCH utakmica</div>

<div class="leagues">
{% for league in leagues %}
<a class="league {% if league==selected %}active{% endif %}" href="/?liga={{league|urlencode}}">
{{'Sve lige' if league=='Sve lige' else league_labels[league]}}
</a>
{% endfor %}
</div>

<div class="filterbox">
  <div class="filterhead">
    <div class="filtertitle">Marketi — označi šta želiš da vidiš</div>
    <div class="filteractions">
      <button class="smallbtn" type="button" onclick="selectAllMarkets()">Sve</button>
      <button class="smallbtn" type="button" onclick="clearMarkets()">Očisti</button>
    </div>
  </div>
  <div class="marketfilters">
  {% for key,title,cols in markets %}
    <label class="marketpill">
      <input type="checkbox" class="marketcheck" value="{{key}}" {% if key=='1x2' %}checked{% endif %} onchange="marketFilterChanged()">
      <span>{{title}}</span>
    </label>
  {% endfor %}
  </div>
</div>

<div style="display:flex;gap:10px;align-items:center;margin:-12px 0 24px">
  <button id="leagueLoadBtn" class="smallbtn" type="button" onclick="activateVisibleLeague()">Učitaj sačuvane kvote</button>
  <span id="leagueLoadStatus" style="color:#7f91a5;font-size:12px"></span>
</div>

{% for err in errors %}<div class="error">{{err}}</div>{% endfor %}

{% for league,rows in grouped %}
<div class="section-title">{{league_labels[league]}}</div>
{% for m in rows %}
<div class="card" data-mid="{{m.id}}" data-match-name="{{m.name|e}}" {% if m.kickoff_ts %}data-kickoff="{{m.kickoff_ts}}"{% endif %}>
  <div class="matchzone" onclick="toggleOdds(this.parentElement,'{{m.id}}')">
  <div class="top">
    <div class="matchmain">
      <div class="matchtext">
        <div class="teams">{{m.name}}</div>
        {% if m.time_label %}<div class="kickoff">{{m.time_label}}</div>{% endif %}
      </div>
    </div>
    <div class="count">{{m.matched_count}}/{{books|length}}</div>
  </div>
  <div class="books">
  {% for book in books %}
    <span class="book {% if not m.status.get(book) %}missing{% endif %}">{{book}}{% if not m.status.get(book) %} —{% endif %}</span>
  {% endfor %}
  </div>
  <div class="hint">Klikni za kvote iz označenih marketa</div>
  </div>
  <div class="quickodds" onclick="event.stopPropagation()"></div>
  <div class="oddsbox" onclick="event.stopPropagation()"></div>
</div>
{% endfor %}
{% endfor %}
</div>

<div id="ticket" class="ticket">
  <div class="tickethead">
    <div class="tickettop">Tiket <span id="ticketCount"></span></div>
    <div class="ticketcontrols">
      <button id="collapseBtn" class="collapsebtn" type="button" onclick="toggleTicketCollapse()" title="Skupi/raširi">−</button>
      <button class="clearbtn" type="button" onclick="clearTicket()">Obriši</button>
    </div>
  </div>
  <div class="ticketbody">
    <div id="ticketPicks"></div>
    <table class="tickettable">
      <thead><tr><th>Kladionica</th><th>Ukupna kvota</th></tr></thead>
      <tbody id="ticketRows"></tbody>
    </table>
    <div class="ticketnote">Ako kladionica nema makar jednu izabranu igru, prikazuje se —.</div>
  </div>
</div>

<script>
const BOOKS = {{ books|tojson }};
const marketCache = {};
const selectedPicks = new Map();

function fmt(v){
  if(v===null || v===undefined) return "—";
  return Number(v)<10 ? Number(v).toFixed(2) : Number(v).toFixed(1);
}

const CURRENT_LEAGUE = {{ selected|tojson }};
const LEAGUE_NAMES = {{ leagues|tojson }};
const STORAGE_PICKS = "football_ticket_picks_v2";
const STORAGE_FILTERS = "football_market_filters_v2";
const STORAGE_TICKET_COLLAPSED = "football_ticket_collapsed_v1";

function applyTicketCollapseState(){
  const panel=document.getElementById("ticket");
  let collapsed=false;
  try{ collapsed=localStorage.getItem(STORAGE_TICKET_COLLAPSED)==="1"; }catch(e){}
  panel.classList.toggle("collapsed",collapsed);
  document.getElementById("collapseBtn").textContent = collapsed ? "+" : "−";
}

function toggleTicketCollapse(){
  const panel=document.getElementById("ticket");
  panel.classList.toggle("collapsed");
  const collapsed=panel.classList.contains("collapsed");
  document.getElementById("collapseBtn").textContent = collapsed ? "+" : "−";
  try{ localStorage.setItem(STORAGE_TICKET_COLLAPSED,collapsed?"1":"0"); }catch(e){}
}

async function fetchMatchMarkets(id, force=false){
  if(!force && marketCache[id]) return marketCache[id];
  const r=await fetch("/api/markets/"+encodeURIComponent(id)+(force?"?refresh=1":""));
  const d=await r.json();
  if(!r.ok) throw new Error(d.error||"Greška");
  marketCache[id]=d;
  return d;
}

function saveTicket(){
  try{
    localStorage.setItem(STORAGE_PICKS, JSON.stringify([...selectedPicks.entries()]));
  }catch(e){}
}

function restoreTicket(){
  try{
    const raw=localStorage.getItem(STORAGE_PICKS);
    if(!raw) return;
    const arr=JSON.parse(raw);
    if(Array.isArray(arr)){
      arr.forEach(([k,v])=>selectedPicks.set(k,v));
    }
  }catch(e){}
}

function saveMarketFilters(){
  try{
    const checked=[...document.querySelectorAll(".marketcheck:checked")].map(x=>x.value);
    localStorage.setItem(STORAGE_FILTERS, JSON.stringify(checked));
  }catch(e){}
}

function restoreMarketFilters(){
  try{
    const raw=localStorage.getItem(STORAGE_FILTERS);
    if(!raw) return;
    const wanted=new Set(JSON.parse(raw));
    document.querySelectorAll(".marketcheck").forEach(x=>x.checked=wanted.has(x.value));
  }catch(e){}
}

function quickOddValue(data,key,col){
  const b=(data.blocks||[]).find(x=>x.key===key);
  if(!b) return null;
  const vals=b.rows.map(r=>r.odds ? r.odds[col] : null).filter(v=>v!==null && v!==undefined).map(Number);
  return vals.length ? Math.max(...vals) : null;
}

function renderQuickOdds(card,data){
  if(!card || !data) return;
  const q=card.querySelector(".quickodds");
  if(!q) return;
  const items=[
    ["1","1x2","1"],["X","1x2","X"],["2","1x2","2"],
    ["1X","dc","1X"],["X2","dc","X2"],["2+","g2","DA"],["3+","g3","DA"],
    ["1+ I & 1+ II","both","DA"],["1–3 / 1–3","h13","DA"],["2+ I ili II","or2","DA"],
    ["GG","gg","DA"],["GG I","ggi","DA"],["2+ I","fh2","DA"],
    ["1X&2+","dc2","1X"],["X2&2+","dc2","X2"],["1X&0–3","dc03","1X"],["X2&0–3","dc03","X2"]
  ];
  q.innerHTML=items.map(([label,key,col])=>{
    const v=quickOddValue(data,key,col);
    const pk=pickKey(card.dataset.mid,key,col);
    const selected=selectedPicks.has(pk)?' pickselected':'';
    const matchName=encodeURIComponent(card.dataset.matchName||'');
    const title=encodeURIComponent((data.blocks||[]).find(x=>x.key===key)?.title||label);
    const block=(data.blocks||[]).find(x=>x.key===key);
    const labelText=encodeURIComponent(block?pickLabel(block,col):label);
    return '<div class="quickodd'+selected+'" data-pickkey="'+pk+'" onclick="togglePick(event,\''+card.dataset.mid+'\',\''+key+'\',\''+col+'\',\''+matchName+'\',\''+title+'\',\''+labelText+'\')"><span class="quicklabel">'+label+'</span><span class="quickvalue">'+(v===null?'—':fmt(v))+'</span></div>';
  }).join("");
}

function removeStartedCards(){
  const now=Date.now()/1000;
  document.querySelectorAll('.card[data-kickoff]').forEach(card=>{
    const ts=Number(card.dataset.kickoff||0);
    if(ts>0 && ts<=now) card.remove();
  });
}

async function hydrateCurrentLeagueCache(){
  const names=CURRENT_LEAGUE==="Sve lige" ? LEAGUE_NAMES.filter(x=>x!=="Sve lige") : [CURRENT_LEAGUE];
  await Promise.all(names.map(async league=>{ try{
    const r=await fetch("/api/league-cache?league="+encodeURIComponent(league));
    const d=await r.json();
    if(!r.ok) return;
    Object.entries(d.matches||{}).forEach(([id,data])=>{
      marketCache[id]=data;
      const card=document.querySelector('.card[data-mid="'+CSS.escape(id)+'"]');
      if(card){
        renderQuickOdds(card,data);
        const box=card.querySelector(".oddsbox");
        box.dataset.loaded="1";
        if(box.classList.contains("open")) renderMarkets(box,id,data);
      }
    });
    updateLeagueStatus(d.active, Object.keys(d.matches||{}).length, d.total||0);
  }catch(e){} }));
}

async function hydrateTicketCache(){
  const ids=[...new Set([...selectedPicks.values()].map(p=>p.matchId))];
  if(!ids.length) return;
  try{
    const r=await fetch("/api/cached-matches",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ids})
    });
    const d=await r.json();
    Object.entries(d.matches||{}).forEach(([id,data])=>marketCache[id]=data);
    renderTicket();
  }catch(e){}
}

function updateLeagueStatus(active, cached, total){
  const status=document.getElementById("leagueLoadStatus");
  const btn=document.getElementById("leagueLoadBtn");
  if(!status || !btn) return;

  if(CURRENT_LEAGUE==="Sve lige"){
    status.textContent="Automatsko čitanje sačuvanih kvota za sve lige";
    btn.disabled=false;
    return;
  }

  if(active){
    status.textContent="Automatsko čitanje sačuvanih kvota · "+cached+"/"+total+" mečeva";
    btn.textContent="Osveži prikaz lige";
  }else if(cached>0){
    status.textContent="Sačuvane kvote: "+cached+"/"+total+" mečeva";
  }else{
    status.textContent="";
  }
}

async function activateVisibleLeague(){
  const status=document.getElementById("leagueLoadStatus");
  if(status) status.textContent="Učitavam sačuvane kvote...";

  try{
    if(CURRENT_LEAGUE==="Sve lige"){
      await hydrateCurrentLeagueCache();
      if(status) status.textContent="Sačuvane kvote učitane za sve lige.";
      return;
    }
    const r=await fetch("/api/activate-league",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({league:CURRENT_LEAGUE})
    });
    const d=await r.json();
    if(!r.ok) throw new Error(d.error||"Greška");
    updateLeagueStatus(true,d.cached||0,d.total||0);
    // Preuzmi sačuvane kvote iz baze.
    setTimeout(hydrateCurrentLeagueCache,1500);
  }catch(e){
    if(status) status.textContent=e.message;
  }
}

// Tihi polling čita već sačuvane kvote iz baze.
// Ne pokreće nove zahteve ka kladionicama.
setInterval(()=>{
  hydrateCurrentLeagueCache();
  hydrateTicketCache();
},12000);

function selectedMarkets(){
  return [...document.querySelectorAll(".marketcheck:checked")].map(x=>x.value);
}

function selectAllMarkets(){
  document.querySelectorAll(".marketcheck").forEach(x=>x.checked=true);
  marketFilterChanged();
}

function clearMarkets(){
  document.querySelectorAll(".marketcheck").forEach(x=>x.checked=false);
  marketFilterChanged();
}

function marketFilterChanged(){
  saveMarketFilters();
  document.querySelectorAll(".oddsbox[data-loaded='1']").forEach(box=>{
    const id=box.closest(".card").dataset.mid;
    if(id && marketCache[id]) renderMarkets(box,id,marketCache[id]);
  });
}

function colLabel(block,col){
  if(block.key==="dc2") return col==="1X" ? "1X&2+" : "X2&2+";
  if(block.key==="dc03") return col==="1X" ? "1X&0–3" : "X2&0–3";
  if(block.cols.length===1 && col==="DA") return "";
  return col;
}

function pickLabel(block,col){
  const c=colLabel(block,col);
  return c ? block.title+" · "+c : block.title;
}

function pickKey(matchId,marketKey,col){
  return matchId+"||"+marketKey+"||"+col;
}

function renderMarkets(box,id,d){
  const wanted=selectedMarkets();
  const blocks=d.blocks.filter(b=>wanted.includes(b.key));
  if(!blocks.length){
    box.innerHTML='<div class="empty">Označi bar jedan market iznad.</div>';
    return;
  }

  const matchName=box.closest(".card").dataset.matchName;
  let h='<div class="marketsgrid">';
  for(const b of blocks){
    h+='<div class="market"><div class="markettitle">'+b.title+'</div><table><tr><th>Kladionica</th>';
    for(const c of b.cols) h+='<th>'+colLabel(b,c)+'</th>';
    h+='</tr>';

    for(const row of b.rows){
      h+='<tr><td>'+row.book+'</td>';
      for(const c of b.cols){
        const v=row.odds[c];
        let cl="oddcell";
        if(v!==undefined && v!==null && b.best[c]!==null && Number(v)===Number(b.best[c])) cl+=" best";
        else if(v!==undefined && v!==null && b.worst[c]!==null && Number(v)===Number(b.worst[c])) cl+=" worst";

        const pk=pickKey(id,b.key,c);
        if(selectedPicks.has(pk)) cl+=" pickselected";

        if(v===undefined || v===null){
          h+='<td class="dash">—</td>';
        }else{
          const safeMatch=encodeURIComponent(matchName);
          const safeTitle=encodeURIComponent(b.title);
          const safeLabel=encodeURIComponent(pickLabel(b,c));
          h+='<td class="'+cl+'" data-pickkey="'+pk+'" onclick="togglePick(event,\''+id+'\',\''+b.key+'\',\''+c+'\',\''+safeMatch+'\',\''+safeTitle+'\',\''+safeLabel+'\')">'+fmt(v)+'</td>';
        }
      }
      h+='</tr>';
    }
    h+='</table></div>';
  }
  h+='</div>';
  box.innerHTML=h;
}

async function toggleOdds(card,id){
  const box=card.querySelector(".oddsbox");
  card.dataset.mid=id;

  if(box.classList.contains("open")){
    box.classList.remove("open");
    return;
  }
  box.classList.add("open");

  if(box.dataset.loaded==="1"){
    renderMarkets(box,id,marketCache[id]);
    return;
  }

  box.innerHTML='<div class="loading">Učitavam sačuvane kvote...</div>';
  try{
    const d=await fetchMatchMarkets(id,false);
    box.dataset.loaded="1";
    renderMarkets(box,id,d);
  }catch(e){
    box.innerHTML='<div class="error">'+e.message+'</div>';
  }
}

function togglePick(ev,matchId,marketKey,col,matchNameEnc,titleEnc,labelEnc){
  ev.stopPropagation();
  const key=pickKey(matchId,marketKey,col);
  if(selectedPicks.has(key)){
    selectedPicks.delete(key);
  }else{
    selectedPicks.set(key,{
      matchId, marketKey, col,
      matchName:decodeURIComponent(matchNameEnc),
      marketTitle:decodeURIComponent(titleEnc),
      label:decodeURIComponent(labelEnc)
    });
  }
  saveTicket();
  const card=document.querySelector('.card[data-mid="'+CSS.escape(matchId)+'"]');
  if(card && marketCache[matchId]) renderQuickOdds(card,marketCache[matchId]);
  refreshLoadedMarkets();
  renderTicket();
}

function refreshLoadedMarkets(){
  document.querySelectorAll(".oddsbox[data-loaded='1']").forEach(box=>{
    const id=box.closest(".card").dataset.mid;
    if(id && marketCache[id]) renderMarkets(box,id,marketCache[id]);
  });
}

function removePick(key){
  selectedPicks.delete(key);
  saveTicket();
  refreshLoadedMarkets();
  renderTicket();
}

function clearTicket(){
  selectedPicks.clear();
  saveTicket();
  refreshLoadedMarkets();
  renderTicket();
}

function oddsForPick(book,pick){
  const d=marketCache[pick.matchId];
  if(!d) return null;
  const block=d.blocks.find(b=>b.key===pick.marketKey);
  if(!block) return null;
  const row=block.rows.find(r=>r.book===book);
  if(!row) return null;
  const v=row.odds[pick.col];
  return (v===undefined || v===null) ? null : Number(v);
}

function renderTicket(){
  const panel=document.getElementById("ticket");
  const picks=[...selectedPicks.entries()];
  document.getElementById("ticketCount").textContent=picks.length ? "("+picks.length+")" : "";

  if(!picks.length){
    panel.classList.remove("show");
    return;
  }
  panel.classList.add("show");

  let ph="";
  for(const [key,p] of picks){
    ph+='<div class="ticketpick"><div class="ticketpickname"><b>'+p.matchName+'</b><br>'+p.label+'</div><button class="remove" onclick="removePick(\''+key+'\')">×</button></div>';
  }
  document.getElementById("ticketPicks").innerHTML=ph;

  const totals=BOOKS.map(book=>{
    let product=1, missing=false;
    for(const [,p] of picks){
      const v=oddsForPick(book,p);
      if(v===null){missing=true;break;}
      product*=v;
    }
    return {book,total:missing?null:product};
  });

  totals.sort((a,b)=>{
    if(a.total===null && b.total===null) return a.book.localeCompare(b.book);
    if(a.total===null) return 1;
    if(b.total===null) return -1;
    return b.total-a.total;
  });

  let rh="";
  for(const x of totals){
    rh+='<tr><td class="ticketbook">'+x.book+'</td><td class="tickettotal ticketodd">'+(x.total===null?"—":fmt(x.total))+'</td></tr>';
  }
  document.getElementById("ticketRows").innerHTML=rh;
}

document.addEventListener("DOMContentLoaded", async ()=>{
  restoreMarketFilters();
  restoreTicket();
  applyTicketCollapseState();
  removeStartedCards();
  setInterval(removeStartedCards,15000);
  await hydrateCurrentLeagueCache();
  await hydrateTicketCache();
  marketFilterChanged();
  renderTicket();
});

</script>
</body>
</html>
"""

def _day_letter(ts):
    if not ts:
        return ""
    try:
        # Windows deployments may not ship the IANA zoneinfo database;
        # datetime.fromtimestamp uses the configured local timezone there.
        return datetime.fromtimestamp(float(ts)).strftime("%d.%m. %H:%M")
    except (TypeError, ValueError, OverflowError):
        return ""

@app.route("/")
def home():
    selected=request.args.get("liga","Sve lige")
    if selected not in LEAGUES:selected="Sve lige"
    try:
        matches, errors = load_matches_from_db(), []
    except (sqlite3.Error, OSError):
        app.logger.exception("Football database read failed")
        matches, errors = [], ["Baza fudbalskih podataka trenutno nije dostupna."]
    grouped=[]
    for league in LEAGUE_ORDER:
        if selected!="Sve lige" and league!=selected:continue
        rows=[m for m in matches if m["league"]==league and not is_started(m)]
        rows.sort(key=lambda m: (m.get("kickoff_ts") is None, m.get("kickoff_ts") or 10**20, m.get("name","")))
        for m in rows:
            m["time_label"] = _day_letter(m.get("kickoff_ts"))
        if rows:grouped.append((league,rows))
    return render_template_string(HTML,grouped=grouped,leagues=LEAGUES,selected=selected,
        books=BOOKS,total=sum(1 for m in matches if not is_started(m)),errors=errors,league_labels=LEAGUE_LABELS,
        markets=MARKETS,league_count=len(LEAGUE_ORDER))


def _football_db_error():
    app.logger.exception("Football database read failed")
    return jsonify({"error": "Baza fudbalskih podataka trenutno nije dostupna."}), 503


@app.route("/api/activate-league", methods=["POST"])
def api_activate_league():
    payload = request.get_json(silent=True) or {}
    league = payload.get("league")
    if league not in LEAGUE_ORDER:
        return jsonify({"error":"Izaberi jednu konkretnu ligu."}),400
    try:
        mids = [m["id"] for m in load_matches_from_db() if m["league"] == league and not is_started(m)]
        saved = _load_saved_markets(mids)
    except (sqlite3.Error, OSError):
        return _football_db_error()
    return jsonify({"ok": True, "league": league, "active": True,
                    "cached": len(saved), "total": len(mids)})


@app.route("/api/league-cache")
def api_league_cache():
    league = request.args.get("league")
    if league not in LEAGUE_ORDER:
        return jsonify({"matches":{}, "active":False, "total":0})
    try:
        mids = [m["id"] for m in load_matches_from_db() if m["league"] == league and not is_started(m)]
        saved = _load_saved_markets(mids)
    except (sqlite3.Error, OSError):
        return _football_db_error()
    return jsonify({"matches": saved, "active": True, "total": len(mids)})


@app.route("/api/cached-matches", methods=["POST"])
def api_cached_matches():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    if not isinstance(ids, list):
        ids = []
    try:
        saved = _load_saved_markets([str(mid) for mid in ids[:100]])
    except (sqlite3.Error, OSError):
        return _football_db_error()
    return jsonify({"matches": saved})


@app.route("/api/markets/<match_id>")
def api_markets(match_id):
    try:
        m = match_by_id(match_id)
        if not m:
            return jsonify({"error":"Meč nije pronađen"}),404
        if is_started(m):
            return jsonify({"error":"Meč je već počeo i uklonjen je iz PREMATCH ponude."}),410
        # I običan zahtev i refresh=1 čitaju poslednje sačuvane kvote.
        data = load_all_markets(m)
    except (sqlite3.Error, OSError):
        return _football_db_error()
    return jsonify(data)

@app.route("/portal")
def portal():
    username = session.get("username")
    is_premium = session.get("is_premium", False)
    html = """
    <!DOCTYPE html>
    <html lang="sr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sports Portal</title>
        <style>
            body {
                margin: 0;
                background: #0f1115;
                color: white;
                font-family: Arial, sans-serif;
            }

            .header {
                padding: 25px 40px;
                background: #171a21;
                border-bottom: 1px solid #292e38;
                font-size: 26px;
                font-weight: bold;
            }

            .container {
                max-width: 1550px;
                margin: 50px auto;
                padding: 0 20px;
            }

            h1 {
                font-size: 42px;
                margin-bottom: 10px;
            }

            .subtitle {
                color: #aeb4c0;
                font-size: 18px;
                margin-bottom: 40px;
            }

            .cards {
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                gap: 20px;
                align-items: stretch;
            }

            .portal-back {
                position: fixed;
                top: 28px;
                right: 40px;
                z-index: 10;
                color: #f1ca45;
                text-decoration: none;
                font-weight: bold;
            }

            .card {
                background: #191d25;
                border: 1px solid #2b303a;
                border-radius: 12px;
                padding: 26px;
                min-height: 330px;
                display: flex;
                flex-direction: column;
            }

            .card h2 {
                margin-top: 0;
            }

            .card p {
                color: #aeb4c0;
                line-height: 1.5;
            }

            .button {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 190px;
                min-height: 52px;
                margin-top: auto;
                align-self: flex-start;
                padding: 10px 16px;
                background: #2563eb;
                color: white;
                text-decoration: none;
                border-radius: 7px;
                text-align: center;
            }

            .premium {
                border-color: #7c5cff;
            }

            @media (max-width: 1250px) {
                .cards { grid-template-columns: repeat(3, minmax(250px, 1fr)); }
            }

            @media (max-width: 760px) {
                .cards { grid-template-columns: 1fr; }
                .card { min-height: 280px; }
            }
        </style>
    </head>

    <body>
            <div class="header">SPORTS PORTAL</div>

        <div style="padding: 15px 40px; background: #13161c; color: #aeb4c0;">
            Prijavljen kao: {username}<br>
            Premium status: {premium_status}<br>
            <a href="/logout" style="display: inline-block; margin-top: 10px; color: #ffffff; background: #333943; padding: 8px 14px; border-radius: 6px; text-decoration: none;">Odjavi se</a>
        </div>
        <div class="container">
            <h1>Sports Portal</h1>

            <div class="subtitle">
                Kvote, fudbalska i košarkaška statistika i premium sportski podaci na jednom mestu.
            </div>

            <div class="cards">

                <div class="card">
                    <h2>⚽ Kvote</h2>
                    <p>
                        Poređenje kvota više kladionica na jednom mestu.
                    </p>
                    <a class="button" href="/">Otvori kvote</a>
                </div>

                <div class="card">
                    <h2>⚽ Fudbal statistika</h2>
                    <p>
                        Statistika utakmica, timova i liga.
                    </p>
                    <a class="button" href="/football-stats/">Otvori statistiku</a>
                </div>

                <div class="card">
                    <h2>🏀 Poeni igrača</h2>
                    <p>Poeni igrača, granice i kvote.</p>
                    <a class="button" href="/player-points">Otvori poene igrača</a>
                </div>

                <div class="card">
                    <h2>🏀 Igrači statistika</h2>
                    <p>Istorija over/under učinka igrača.</p>
                    <a class="button" href="/basketball">Otvori statistiku</a>
                </div>

                <div class="card premium">
                    <h2>⭐ Premium</h2>
                    <p>Full pristup svim sadržajima.</p>
                    <a class="button" href="/premium">Saznaj više</a>
                </div>

            </div>
        </div>
    </body>
    </html>
    """

    return html.replace("{username}", username or "Gost").replace(
    "{premium_status}",
    "Premium" if is_premium else "Besplatan korisnik"
)

@app.route("/register", methods=["GET", "POST"])
def register():
    username = request.form.get("username")
    email = request.form.get("email")
    password = request.form.get("password")

    if request.method == "POST":
        result, message = users.register_user(username, email, password)
        return f"<h1>{message}</h1>"

    return """
<!DOCTYPE html>
<html lang="sr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Registracija</title>

    <style>
        body {
            margin: 0;
            background: #0f1115;
            color: white;
            font-family: Arial, sans-serif;
        }

        .header {
            padding: 25px 40px;
            background: #171a21;
            border-bottom: 1px solid #292e38;
            font-size: 26px;
            font-weight: bold;
        }

        .container {
            max-width: 450px;
            margin: 60px auto;
            padding: 35px;
            background: #191d25;
            border: 1px solid #2b303a;
            border-radius: 12px;
        }

        h1 {
            margin-top: 0;
            text-align: center;
        }

        label {
            display: block;
            margin-top: 20px;
            margin-bottom: 7px;
        }

        input {
            width: 100%;
            box-sizing: border-box;
            padding: 12px;
            background: #0f1115;
            color: white;
            border: 1px solid #363c47;
            border-radius: 7px;
        }

        button {
            width: 100%;
            margin-top: 25px;
            padding: 13px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 7px;
            cursor: pointer;
            font-size: 16px;
        }
    </style>
</head>

<body>

<div class="header">SPORTS PORTAL</div>

<div class="container">

    <h1>Registracija</h1>

    <form method="POST">

        <label>Korisničko ime:</label>
        <input type="text" name="username" required>

        <label>Email:</label>
        <input type="email" name="email" required>

        <label>Lozinka:</label>
        <input type="password" name="password" required>

        <button type="submit">Registruj se</button>

    </form>

</div>

</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = users.login_user(email, password)

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["is_premium"] = users.is_user_premium(user["id"])
            return redirect("/portal")

        return "<h1>Pogrešan email ili lozinka.</h1>"
    return """
<!DOCTYPE html>
<html lang="sr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Prijava</title>

    <style>
        body {
            margin: 0;
            background: #0f1115;
            color: white;
            font-family: Arial, sans-serif;
        }

        .header {
            padding: 25px 40px;
            background: #171a21;
            border-bottom: 1px solid #292e38;
            font-size: 26px;
            font-weight: bold;
        }

        .container {
            max-width: 450px;
            margin: 60px auto;
            padding: 35px;
            background: #191d25;
            border: 1px solid #2b303a;
            border-radius: 12px;
        }

        h1 {
            margin-top: 0;
            text-align: center;
        }

        label {
            display: block;
            margin-top: 20px;
            margin-bottom: 7px;
        }

        input {
            width: 100%;
            box-sizing: border-box;
            padding: 12px;
            background: #0f1115;
            color: white;
            border: 1px solid #363c47;
            border-radius: 7px;
        }

        button {
            width: 100%;
            margin-top: 25px;
            padding: 13px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 7px;
            cursor: pointer;
            font-size: 16px;
        }
    </style>
</head>

<body>

<div class="header">SPORTS PORTAL</div>

<div class="container">

    <h1>Prijava</h1>

    <form method="POST">

        <label>Email:</label>
        <input type="email" name="email" required>

        <label>Lozinka:</label>
        <input type="password" name="password" required>

        <button type="submit">Prijavi se</button>

    </form>

</div>

</body>
</html>
"""

@app.route("/premium")
def premium():
    return """
    <!DOCTYPE html>
    <html lang="sr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Premium</title>
        <style>
            body {
                margin: 0;
                background: #0f1115;
                color: white;
                font-family: Arial, sans-serif;
            }

            .header {
                padding: 25px 40px;
                background: #171a21;
                border-bottom: 1px solid #292e38;
                font-size: 26px;
                font-weight: bold;
            }

            .container {
                max-width: 900px;
                margin: 60px auto;
                padding: 0 20px;
                text-align: center;
            }

            h1 {
                font-size: 42px;
                margin-bottom: 15px;
            }

            .subtitle {
                color: #aeb4c0;
                font-size: 18px;
                margin-bottom: 45px;
            }

            .features {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 20px;
                text-align: left;
            }

            .feature {
                background: #191d25;
                border: 1px solid #2b303a;
                border-radius: 12px;
                padding: 25px;
            }

            .feature h2 {
                margin-top: 0;
            }

            .feature p {
                color: #aeb4c0;
                line-height: 1.5;
            }

            .price {
                margin-top: 45px;
                font-size: 32px;
                font-weight: bold;
            }
            .plans {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 20px;
                margin-top: 45px;
            }

            .plan {
                background: #191d25;
                border: 1px solid #2b303a;
                border-radius: 12px;
                padding: 25px;
            }

            .plan h2 {
                margin-top: 0;
            }

            .plan-price {
                font-size: 30px;
                font-weight: bold;
                margin: 20px 0;
            }

            .plan p {
                color: #aeb4c0;
            }

            .button {
                display: inline-block;
                margin-top: 20px;
                padding: 13px 25px;
                background: #7c5cff;
                color: white;
                text-decoration: none;
                border-radius: 7px;
            }
        </style>
    </head>

    <body>
        <div class="header">SPORTS PORTAL</div>
        <a href="/portal" style="position:fixed;top:28px;right:40px;z-index:10;color:#f1ca45;text-decoration:none;font-weight:bold">← Sports Portal</a>

        <div class="container">
            <h1>⭐ Premium</h1>

            <div class="subtitle">
                Otključaj napredne sportske podatke i dodatne funkcije.
            </div>

            <div class="features">

                <div class="feature">
                    <h2>📊 Napredne kvote</h2>
                    <p>
                        Više liga, dodatna tržišta i napredne mogućnosti poređenja.
                    </p>
                </div>

                <div class="feature">
                    <h2>⚽ Napredna statistika</h2>
                    <p>
                        Detaljniji podaci o ekipama, utakmicama i igračima.
                    </p>
                </div>

                <div class="feature">
                    <h2>🏆 Premium sadržaj</h2>
                    <p>
                        Dodatne analize i funkcije dostupne samo Premium korisnicima.
                    </p>
                </div>

            </div>

            <div class="plans">

    <div class="plan">
        <h2>1 mesec</h2>
        <div class="plan-price">600 RSD</div>
        <p>Premium pristup za 1 mesec.</p>
        <a class="button" href="/premium/1">Izaberi</a>
    </div>

    <div class="plan">
        <h2>3 meseca</h2>
        <div class="plan-price">1.500 RSD</div>
        <p>Premium pristup za 3 meseca.</p>
        <a class="button" href="/premium/3">Izaberi</a>
    </div>

    <div class="plan">
        <h2>6 meseci</h2>
        <div class="plan-price">2.500 RSD</div>
        <p>Premium pristup za 6 meseci.</p>
        <a class="button" href="/premium/6">Izaberi</a>
    </div>

</div>

        </div>
    </body>
    </html>
    """
@app.route("/premium/1")
def premium_one_month():
    return """
    <!DOCTYPE html>
    <html lang="sr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Premium</title>
    </head>
    <body>
        <h1>Izabran paket: 1 mesec</h1>
        <h2>600 RSD</h2>
        <p>Plaćanje će uskoro biti dostupno.</p>
        <a href="/premium">Nazad na Premium</a>
    </body>
    </html>
    """
@app.route("/premium/3")
def premium_three_months():
    return """
    <!DOCTYPE html>
    <html lang="sr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Premium</title>
    </head>
    <body>
        <h1>Izabran paket: 3 meseca</h1>
        <h2>1.500 RSD</h2>
        <p>Plaćanje će uskoro biti dostupno.</p>
        <a href="/premium">Nazad na Premium</a>
    </body>
    </html>
    """
@app.route("/premium/6")
def premium_six_months():
    return """
    <!DOCTYPE html>
    <html lang="sr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Premium</title>
    </head>
    <body>
        <h1>Izabran paket: 6 meseci</h1>
        <h2>2.500 RSD</h2>
        <p>Plaćanje će uskoro biti dostupno.</p>
        <a href="/premium">Nazad na Premium</a>
    </body>
    </html>
    """
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

if __name__=="__main__":
    app.run(host="127.0.0.1",port=5003,debug=False,threaded=True)
