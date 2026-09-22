# euroleague_portal.py
# EuroLeague Player Stats modul za glavni Sports Portal.

from flask import Blueprint, render_template_string, jsonify, request, redirect
from collections import defaultdict
from pathlib import Path
import sqlite3
import re

euroleague_bp = Blueprint("euroleague", __name__)

# Baza ostaje u postojecem Player Props projektu.
DB_FILE = Path(r"C:\Users\dkecm\Desktop\player props\euroleague_stats.db")

MARKETS = [
    ("PTS", "PTS"), ("REB", "REB"), ("AST", "AST"), ("3PM", "3PM"),
    ("PR", "P+R"), ("PA", "P+A"), ("RA", "R+A"), ("PRA", "PRA"), ("PIR", "PIR"),
]

BASKETBALL_LEAGUES = [
    ("nba", "NBA"),
    ("euroleague", "EuroLeague"),
    ("eurocup", "EuroCup"),
    ("aba", "ABA"),
    ("acb", "ACB"),
    ("super-lig", "Super Lig"),
    ("lega-a", "Lega A"),
    ("bbl", "BBL"),
]

# Ovi redosledi su deo pripreme interfejsa dok se ne preuzmu statistike liga.
PLACEHOLDER_TEAMS = {
    "nba": [
        "Atlanta", "Boston", "Brooklyn", "Charlotte", "Chicago", "Cleveland",
        "Dallas", "Denver", "Detroit", "Golden State", "Houston", "Indiana",
        "LA Clippers", "LA Lakers", "Memphis", "Miami", "Milwaukee", "Minnesota",
        "New Orleans", "NY Knicks", "Oklahoma", "Orlando", "Philadelphia", "Phoenix",
        "Portland", "Sacramento", "San Antonio", "Toronto", "Utah", "Washington",
    ],
    "aba": [
        "Borac", "Bosna", "Budućnost", "Cedevita Olimpija", "Cibona", "Cluj-Napoca",
        "Crvena Zvezda", "Dubai", "FMP", "Igokea", "Ilirija", "Krka", "Mega",
        "Partizan", "SC Derby", "Široki", "Slovan", "Spartak", "Vienna", "Zadar",
    ],
}

TEAM_DISPLAY = {
    "Anadolu Efes Istanbul": "Anadolu Efes",
    "AS Monaco": "Monaco",
    "Crvena Zvezda Meridianbet Belgrade": "Crvena Zvezda",
    "Dubai Basketball": "Dubai",
    "EA7 Emporio Armani Milan": "Milano",
    "FC Barcelona": "Barcelona",
    "FC Bayern Munich": "Bayern",
    "Fenerbahce Beko Istanbul": "Fenerbahce",
    "Hapoel IBI Tel Aviv": "Hapoel TA",
    "Kosner Baskonia Vitoria-Gasteiz": "Baskonia",
    "LDLC ASVEL Villeurbanne": "ASVEL",
    "Maccabi Rapyd Tel Aviv": "Maccabi TA",
    "Olympiacos Piraeus": "Olympiacos",
    "Panathinaikos AKTOR Athens": "Panathinaikos",
    "Paris Basketball": "Paris",
    "Partizan Mozzart Bet Belgrade": "Partizan",
    "Real Madrid": "Real Madrid",
    "Valencia Basket": "Valencia",
    "Virtus Bologna": "Virtus",
    "Zalgiris Kaunas": "Zalgiris",
    "Besiktas": "Besiktas",
    # Alternate names used by bookmaker feeds; these resolve to the
    # canonical names shown in the statistics section.
    "Dubai": "Dubai",
    "Dubai Basketball": "Dubai",
    "Real Madrid Baloncesto": "Real Madrid",
    "Saski Baskonia": "Baskonia",
    "Saski Baskonia Vitoria-Gasteiz": "Baskonia",
    "Kosner Baskonia": "Baskonia",
    "Olympiacos SFP Pireus": "Olympiacos",
    "Olympiacos Piraeus": "Olympiacos",
}


def canonical_team_name(name):
    """Return the single team name used across stats and bookmaker feeds."""
    value = " ".join(str(name or "").split())
    return TEAM_DISPLAY.get(value, value)
BAD_TEAMS = {"LOCAL", "ROAD"}

def _connect():
    return sqlite3.connect(str(DB_FILE))

def season_label(code):
    m = re.fullmatch(r"E(\d{4})", str(code or ""))
    if not m:
        return str(code)
    y = int(m.group(1))
    return f"{y}/{str(y + 1)[-2:]}"

def available_seasons():
    if not DB_FILE.exists():
        return []
    with _connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT season FROM player_games "
            "WHERE COALESCE(TRIM(season),'')<>'' ORDER BY season DESC"
        ).fetchall()]

def rosters(season):
    with _connect() as conn:
        rows = conn.execute("""
            SELECT pg.player, pg.team, g.game_date
            FROM player_games pg
            LEFT JOIN games g
              ON pg.season=g.season AND pg.game_code=g.game_code
            WHERE pg.season=?
              AND COALESCE(TRIM(pg.player),'')<>''
              AND COALESCE(TRIM(pg.team),'')<>''
            ORDER BY g.game_date ASC, pg.game_code ASC
        """, (season,)).fetchall()

    latest = {}
    for player, team, _ in rows:
        team = str(team or "").strip()
        if team and team.upper() not in BAD_TEAMS:
            latest[player] = team

    out = defaultdict(list)
    for player, team in latest.items():
        out[team].append(player)
    return {
        team: sorted(players, key=str.lower)
        for team, players in sorted(
            out.items(), key=lambda x: TEAM_DISPLAY.get(x[0], x[0]).lower()
        )
    }

def _value(row, market):
    pts, reb, ast, three_pm, pir = row
    return {
        "PTS": pts, "REB": reb, "AST": ast, "3PM": three_pm,
        "PR": pts + reb, "PA": pts + ast, "RA": reb + ast,
        "PRA": pts + reb + ast, "PIR": pir,
    }[market]

def player_stats(player, market, line, season):
    if market not in {x[0] for x in MARKETS}:
        return None, "Nepoznat market."

    with _connect() as conn:
        rows = conn.execute("""
            SELECT pg.pts, pg.reb, pg.ast, pg.three_pm, pg.valuation
            FROM player_games pg
            LEFT JOIN games g
              ON pg.season=g.season AND pg.game_code=g.game_code
            WHERE pg.season=? AND pg.player=?
            ORDER BY g.game_date DESC, pg.game_code DESC
        """, (season, player)).fetchall()

    if not rows:
        return None, "Nema statistike za izabranog igrača i sezonu."

    vals = [_value(tuple(0 if v is None else v for v in row), market) for row in rows]

    def calc(values):
        over = sum(v > line for v in values)
        under = sum(v < line for v in values)
        games = len(values)
        return {
            "games": games, "over": over, "under": under,
            "over_pct": round(over * 100 / games, 1) if games else 0,
            "under_pct": round(under * 100 / games, 1) if games else 0,
        }

    return {
        "ok": True, "player": player, "market": market, "line": line,
        "season_code": season, "season_label": season_label(season),
        "l5": calc(vals[:5]),
        "l10": calc(vals[:10]),
        "season": calc(vals),
    }, None

HTML = r"""
<!doctype html>
<html lang="sr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Igrači statistika · Sports Portal</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0f1114;color:#e8edf2;font-family:Arial,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:28px}
.top{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}
h1{margin:0 0 5px;font-size:30px}.sub{color:#909aa6}.back{color:#f1ca45;text-decoration:none;font-weight:700}
.panel{background:#171a1f;border:1px solid #2c323a;border-radius:12px;padding:18px;margin-bottom:18px}
.label{font-size:11px;color:#929da9;text-transform:uppercase;margin-bottom:9px}
.tabs{display:flex;gap:8px;flex-wrap:wrap}
.tab{display:inline-block;border:1px solid #343b45;background:#1b1f25;color:#dce3ea;border-radius:8px;padding:9px 13px;cursor:pointer;font-weight:700;text-decoration:none}
.tab:hover{background:#222831}.tab.active{background:#f1ca45;color:#111;border-color:#f1ca45}.tab.placeholder{cursor:default}
.players{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.player-btn{border:1px solid #343b45;background:#121519;color:#e8edf2;border-radius:8px;padding:11px 12px;cursor:pointer;text-align:left;font-weight:650}
.player-btn:hover{background:#20252c}.player-btn.active{border-color:#f1ca45;color:#f1ca45}
.controls{display:flex;gap:18px;align-items:flex-end;flex-wrap:wrap}.market-wrap{flex:1;min-width:500px}.line-wrap,.season-wrap{width:180px}
select{width:100%;background:#121519;color:#fff;border:1px solid #3a424d;border-radius:8px;padding:10px 12px;font-size:16px;font-weight:700}
.stats-head{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:14px}
.stats-player{font-size:23px;font-weight:800}.stats-market{color:#f1ca45;font-size:17px;font-weight:800}
table{width:100%;border-collapse:collapse}th,td{padding:13px 15px;border-bottom:1px solid #292f36;text-align:center}
th{font-size:11px;color:#929da9;text-transform:uppercase}th:first-child,td:first-child{text-align:left}
.pct{font-size:18px;font-weight:800}.empty{color:#8d98a4;padding:12px 0}.error{color:#ffb347}
@media(max-width:800px){.wrap{padding:12px}.market-wrap{min-width:100%}.line-wrap,.season-wrap{width:100%}.top{align-items:flex-start;flex-direction:column}.players{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="wrap">
 <div class="top"><div><h1>Igrači statistika</h1><div class="sub">Liga → tim → igrač → market → granica</div></div><a class="back" href="/portal">← Sports Portal</a></div>

 <div class="panel"><div class="label">Liga</div><div class="tabs" id="leagueTabs">
 {% for code,label in leagues %}<a class="tab {% if code==selected_league %}active{% endif %}" href="/basketball?league={{code}}">{{label}}</a>{% endfor %}
 </div></div>

 {% if has_data %}
 <div class="panel"><div class="season-wrap"><div class="label">Sezona</div>
  <select id="seasonSelect" onchange="changeSeason()">
   {% for code,label in seasons %}<option value="{{code}}" {% if code==selected_season %}selected{% endif %}>{{label}}</option>{% endfor %}
 </select>
 </div></div>

 <div class="panel"><div class="label">Timovi</div><div class="tabs" id="teamTabs">
 {% for team in teams %}<button class="tab" data-team="{{team}}" onclick="selectTeam(this)">{{team_display.get(team,team)}}</button>{% endfor %}
 </div></div>

 <div class="panel"><div class="label">Igrači</div><div class="players" id="players"><div class="empty">Izaberi tim.</div></div></div>

 <div class="panel"><div class="controls"><div class="market-wrap"><div class="label">Market</div><div class="tabs" id="marketTabs">
 {% for code,label in markets %}<button class="tab {% if code=='PTS' %}active{% endif %}" data-market="{{code}}" onclick="selectMarket(this)">{{label}}</button>{% endfor %}
 </div></div><div class="line-wrap"><div class="label">Granica</div><select id="lineSelect" onchange="loadStats()">
 {% for line in lines %}<option value="{{line}}" {% if line==18.5 %}selected{% endif %}>{{line}}</option>{% endfor %}
 </select></div></div></div>

 <div class="panel" id="statsPanel"><div class="empty">Izaberi tim i igrača da vidiš statistiku.</div></div>
 {% else %}
 <div class="panel"><div class="label">Timovi</div>
  {% if placeholder_teams %}<div class="tabs">{% for team in placeholder_teams %}<span class="tab placeholder">{{team}}</span>{% endfor %}</div>{% endif %}
  <div class="empty">Igrači i statistike za {{selected_league_label}} pojaviće se ovde čim preuzmemo podatke za tu ligu.</div>
 </div>
 {% endif %}
</div>
<script>
let selectedTeam=null,selectedPlayer=null,selectedMarket='PTS',selectedSeason='{{selected_season}}';
function changeSeason(){window.location.href='/basketball?league=euroleague&season='+encodeURIComponent(document.getElementById('seasonSelect').value)}
async function selectTeam(btn){
 document.querySelectorAll('#teamTabs .tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');
 selectedTeam=btn.dataset.team;selectedPlayer=null;document.getElementById('statsPanel').innerHTML='<div class="empty">Izaberi igrača.</div>';
 const box=document.getElementById('players');box.innerHTML='<div class="empty">Učitavam igrače...</div>';
 try{const r=await fetch('/api/euroleague/players?team='+encodeURIComponent(selectedTeam)+'&season='+encodeURIComponent(selectedSeason));
 const d=await r.json();if(!r.ok)throw new Error(d.error||'Greška');box.innerHTML='';
 d.players.forEach(name=>{const b=document.createElement('button');b.className='player-btn';b.textContent=name;b.onclick=()=>selectPlayer(b,name);box.appendChild(b)})}
 catch(e){box.innerHTML='<div class="error">'+e.message+'</div>'}
}
function selectPlayer(btn,name){document.querySelectorAll('.player-btn').forEach(x=>x.classList.remove('active'));btn.classList.add('active');selectedPlayer=name;loadStats()}
function selectMarket(btn){document.querySelectorAll('#marketTabs .tab').forEach(x=>x.classList.remove('active'));btn.classList.add('active');selectedMarket=btn.dataset.market;loadStats()}
async function loadStats(){
 if(!selectedPlayer)return;const line=document.getElementById('lineSelect').value,panel=document.getElementById('statsPanel');panel.innerHTML='<div class="empty">Računam statistiku...</div>';
 try{const u='/api/euroleague/stats?player='+encodeURIComponent(selectedPlayer)+'&market='+encodeURIComponent(selectedMarket)+'&line='+encodeURIComponent(line)+'&season='+encodeURIComponent(selectedSeason);
 const r=await fetch(u),d=await r.json();if(!r.ok)throw new Error(d.error||'Greška');
 const labels=[['season','SEZONA'],['l5','L5'],['l10','L10']];let rows='';
 labels.forEach(([k,l])=>{const s=d[k];rows+=`<tr><td><b>${l}</b></td><td>${s.over}/${s.games} &nbsp; <span class="pct">${s.over_pct}%</span></td><td>${s.under}/${s.games} &nbsp; <span class="pct">${s.under_pct}%</span></td></tr>`});
 panel.innerHTML=`<div class="stats-head"><div class="stats-player">${esc(d.player)}</div><div class="stats-market">${esc(d.market)} &nbsp; | &nbsp; Granica ${d.line}</div></div><table><thead><tr><th>Period</th><th>OVER</th><th>UNDER</th></tr></thead><tbody>${rows}</tbody></table>`}
 catch(e){panel.innerHTML='<div class="error">'+e.message+'</div>'}
}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML}
</script>
</body></html>
"""

@euroleague_bp.route("/euroleague")
def euroleague_legacy_page():
    return redirect("/basketball?league=euroleague", code=302)

@euroleague_bp.route("/basketball")
def basketball_page():
    selected_league = str(request.args.get("league") or "euroleague").strip().lower()
    league_labels = dict(BASKETBALL_LEAGUES)
    if selected_league not in league_labels:
        selected_league = "euroleague"
    if selected_league != "euroleague":
        return render_template_string(
            HTML,
            leagues=BASKETBALL_LEAGUES,
            selected_league=selected_league,
            selected_league_label=league_labels[selected_league],
            has_data=False,
            selected_season="",
            placeholder_teams=PLACEHOLDER_TEAMS.get(selected_league, []),
        )

    seasons = available_seasons()
    if not seasons:
        return "EuroLeague baza nije pronađena ili je prazna.", 500
    requested = str(request.args.get("season") or "").strip()
    selected = requested if requested in seasons else seasons[0]
    r = rosters(selected)
    return render_template_string(
        HTML, teams=list(r.keys()), team_display=TEAM_DISPLAY, markets=MARKETS,
        lines=[x + 0.5 for x in range(71)],
        seasons=[(x, season_label(x)) for x in seasons], selected_season=selected,
        leagues=BASKETBALL_LEAGUES, selected_league="euroleague",
        selected_league_label="EuroLeague", has_data=True,
        placeholder_teams=[],
    )

@euroleague_bp.route("/api/euroleague/players")
def euroleague_players():
    team = str(request.args.get("team") or "").strip()
    season = str(request.args.get("season") or "").strip()
    r = rosters(season)
    if team not in r:
        return jsonify({"error":"Tim nije pronađen.","players":[]}),404
    return jsonify({"team":team,"players":r[team]})

@euroleague_bp.route("/api/euroleague/stats")
def euroleague_stats_api():
    player = str(request.args.get("player") or "").strip()
    market = str(request.args.get("market") or "PTS").strip().upper()
    season = str(request.args.get("season") or "").strip()
    try:
        line = float(request.args.get("line","18.5"))
    except (TypeError,ValueError):
        return jsonify({"error":"Neispravna granica."}),400
    result,error = player_stats(player,market,line,season)
    if error:
        return jsonify({"error":error}),404
    return jsonify(result)
