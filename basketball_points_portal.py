from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

from flask import Blueprint, render_template_string, request
from euroleague_portal import TEAM_DISPLAY, canonical_team_name


points_bp = Blueprint("points", __name__)
DB = Path(r"C:\Users\dkecm\Desktop\player props\basketball_player_points.db")
LEAGUES = [
    ("nba", "NBA"), ("euroleague", "EuroLeague"), ("eurocup", "EuroCup"),
    ("aba", "ABA"), ("acb", "ACB"), ("superlig", "Super Lig"),
    ("legaa", "Lega A"), ("bbl", "BBL"),
]

PAGE = """<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#0d1219;color:#eef2ff;font:16px Arial,sans-serif}.wrap{max-width:1800px;margin:30px auto 70px;padding:0 30px}.top{display:flex;justify-content:space-between;align-items:center;gap:24px}h1{margin:0 0 8px;font-size:34px}.subtitle,.empty{color:#9cafc8}a{color:#f5d14c;text-decoration:none;font-weight:bold}.portal-link{white-space:nowrap}.box,details{background:#161e29;border:1px solid #2d3a4b;border-radius:14px;padding:20px;margin-top:22px}.tabs{display:flex;gap:10px;flex-wrap:wrap}.tab{display:inline-block;padding:10px 16px;border:1px solid #334155;border-radius:8px;color:#dbe7f7}.tab.on{background:#f5d14c;border-color:#f5d14c;color:#101722}summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:20px;font-size:23px;font-weight:bold}summary::-webkit-details-marker{display:none}summary small{display:block;margin-top:6px;color:#9cafc8;font-size:17px;font-weight:normal}.open,.team{color:#f5d14c}.open{white-space:nowrap}.team{margin-top:28px;font-size:20px;font-weight:bold}.quote-head,.quote-row{display:grid;grid-template-columns:22% 110px 150px 110px 22%;gap:10px;align-items:center;text-align:center;justify-content:start}.quote-head{padding:16px 18px 10px;color:#9cafc8;font-size:14px;font-weight:bold}.player-card{margin-top:12px;padding:18px;border:1px solid #334155;border-radius:12px;background:#111821}.player-name{display:grid;grid-template-columns:22% 110px 150px 110px 22%;gap:10px;margin-bottom:14px;font-size:24px;font-weight:800}.player-name span{grid-column:3;text-align:center}.quote-row{padding:13px 0;border-top:1px solid #2d3a4b}.bookmaker{justify-self:center;padding:7px 13px;border:1px solid #445a75;border-radius:8px;background:#253b56;color:#b8cbe3;font-weight:bold}.odd{justify-self:center;min-width:72px;padding:8px 10px;border:1px solid #40516a;border-radius:8px;text-align:center;font-size:16px}.line{justify-self:center;min-width:150px;padding:9px 20px;border:1px solid #f5d14c;border-radius:10px;background:#f5d14c;color:#111827;text-align:center;font-size:22px;font-weight:800}@media(max-width:700px){.wrap{padding:0 16px}.top{align-items:flex-start;flex-direction:column}.quote-head,.quote-row{grid-template-columns:1fr 60px 80px 60px 1fr;gap:8px}.player-name{grid-template-columns:1fr 60px 80px 60px 1fr;gap:8px;font-size:22px}.line{min-width:0;padding:8px}.quote-head{font-size:11px;padding-left:0;padding-right:0}.bookmaker{padding:6px 5px;font-size:12px}.player-card{padding:13px}}</style>
<main class="wrap"><header class="top"><div><h1>Igrači statistika</h1><div class="subtitle">Liga → meč → ekipa → igrač → UNDER · granica · OVER</div></div><a class="portal-link" href="/portal">← Sports Portal</a></header><section class="box"><div class="tabs">{% for code,name in leagues %}<a class="tab {% if code == league %}on{% endif %}" href="/player-points?league={{code}}">{{name}}</a>{% endfor %}</div></section>{% if matches %}{% for match in matches %}<details class="match"><summary><span>{{match.name}}<small>{{match.time}}</small></span><span class="open">Otvori ›</span></summary>{% for team in match.teams %}{% if team.players %}<section><div class="team">POENI IGRAČA · {{team.name}}</div><div class="quote-head"><span>Kladionica</span><span>UNDER</span><span>GRANICA</span><span>OVER</span><span>Kladionica</span></div>{% for player in team.players %}<article class="player-card"><div class="player-name"><span>{{player.name}}</span></div>{% for quote in player.quotes %}<div class="quote-row"><span class="bookmaker">{{quote.bookmaker}}</span><span class="odd">{{"%.2f"|format(quote.under)}}</span><span class="line">{{quote.line}}</span><span class="odd">{{"%.2f"|format(quote.over)}}</span><span class="bookmaker">{{quote.bookmaker}}</span></div>{% endfor %}</article>{% endfor %}</section>{% endif %}{% endfor %}</details>{% endfor %}{% else %}<section class="box empty">Za ovu ligu još nema učitanih ponuda.</section>{% endif %}</main>"""


PAGE += """<style>.player-name span{justify-self:center;width:max-content;white-space:nowrap}</style><script>(function(){
const key="sportsPortalOpenMatches";
function save(){const ids=[...document.querySelectorAll("details.match[open]")].map((x,i)=>x.dataset.matchId||String(i));localStorage.setItem(key,JSON.stringify(ids));}
function restore(){const ids=new Set(JSON.parse(localStorage.getItem(key)||"[]"));document.querySelectorAll("details.match").forEach((x,i)=>{if(ids.has(x.dataset.matchId||String(i)))x.open=true;});}
document.querySelectorAll("details.match").forEach((x,i)=>{x.dataset.matchId=String(i);x.addEventListener("toggle",save);});restore();setInterval(function(){save();window.location.reload();},60000);})();</script>"""


def player_display_name(raw_name):
    """Convert source form 'I.Watson Boye (Ulm)' to 'Watson Boye I.'."""
    name = raw_name.split("(", 1)[0].strip()
    # Remove roster suffixes such as IV so equivalent bookmaker names merge.
    name = re.sub(r"\b(?:II|III|IV|V)\b", "", name)
    name = " ".join(name.split())
    # Keep known source naming variants stable in the public display.
    special_names = {
        "hadji omar badio e": "Badio B.",
        "hadji omar badio": "Badio B.",
        "el hadji omar badio": "Badio B.",
        "brancou badio": "Badio B.",
        "wright m": "Wright M.",
    }
    normalized = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    normalized = " ".join(normalized.split())
    if normalized in special_names:
        return special_names[normalized]
    if "," in name:
        surname, given = (part.strip() for part in name.split(",", 1))
        if surname and given:
            return f"{surname} {given[0].upper()}."
    match = re.match(r"^([^.\s]+\.)(?:\s*)?(.*)$", name)
    if match and match.group(2):
        return f"{match.group(2)} {match.group(1)}"
    parts = name.split()
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-zÀ-ž]\.?", parts[-1]):
        return f"{parts[-1].rstrip('.')}. {parts[0][0].upper()}."
    if len(parts) >= 2:
        return f"{' '.join(parts[1:])} {parts[0][0].upper()}."
    return name


def main_line(rows):
    """Choose one main line only; alternates remain hidden."""
    usable = [row for row in rows if row[3] is not None and row[4] is not None]
    return min(usable, key=lambda row: (0 if 1.70 <= row[3] <= 2.00 and 1.70 <= row[4] <= 2.00 else 1, abs(row[3] - 1.85) + abs(row[4] - 1.85), -row[2]))


def belgrade_time(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # The portal runs on the user's Belgrade-configured Windows computer.
    return stamp.astimezone().strftime("%d.%m. · %H:%M")


def canonical_start(value):
    """Different feeds write the same UTC time with different millisecond text."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().replace('.', '', 1).isdigit()):
        value = float(value)
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value).astimezone(timezone.utc).isoformat()
    value = str(value).strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def display_team_name(match, source_team):
    """Unify bookmaker abbreviations under the actual BBL fixture team name."""
    match = normalize_match_name(match)
    if " - " not in match:
        return canonical_team_name(source_team)
    home, away = match.split(" - ", 1)
    canonical_home = canonical_team_name(home)
    canonical_away = canonical_team_name(away)
    source_team = canonical_team_name(source_team)
    if not source_team:
        # An unresolved bookmaker team must never be guessed as the home team.
        return ""
    if source_team == canonical_home or source_team.split()[0] == canonical_home.split()[0]:
        return canonical_home
    if source_team == canonical_away or source_team.split()[0] == canonical_away.split()[0]:
        return canonical_away
    return source_team


def display_match_name(match):
    """Use the same canonical club names in match cards and player rows."""
    normalized = normalize_match_name(match)
    parts = normalized.split(" - ", 1)
    if len(parts) != 2:
        return str(match)
    return " - ".join(canonical_team_name(part) for part in parts)


def normalize_match_name(match):
    """Normalize bookmaker separators before team matching."""
    value = str(match or "").strip()
    if " - " not in value:
        # Some feeds serialize the separator as a middle-dot or replacement
        # character. These preserve spaces inside multi-word team names.
        value = value.replace("\u00b7", " - ").replace("\ufffd", " - ")
    if " - " not in value and "-" in value:
        value = value.replace("-", " - ", 1)
    return value


def canonical_match_name(match):
    """Use canonical club names so bookmaker variants share one fixture."""
    normalized = normalize_match_name(match)
    if " - " not in normalized:
        return normalized
    home, away = normalized.split(" - ", 1)
    return f"{canonical_team_name(home)} - {canonical_team_name(away)}"


def bbl_matches(league="bbl"):
    with sqlite3.connect(DB) as connection:
        rows = connection.execute("SELECT match_name, starts_at, team, player, bookmaker, line, under_odd, over_odd FROM player_points_odds WHERE league = ?", ("BBL" if league == "bbl" else "Euroleague",)).fetchall()
    grouped = {}
    for match, starts_at, team, player, bookmaker, line, under, over in rows:
        match = canonical_match_name(match)
        starts_at = canonical_start(starts_at)
        grouped.setdefault((match, starts_at, team, player, bookmaker), []).append((player, bookmaker, line, under, over))
    matches = {}
    for (match, starts_at, team, player, bookmaker), options in grouped.items():
        if not starts_at:
            # A malformed bookmaker row must not take down the whole page.
            # The updater will replace it after obtaining the fixture time.
            continue
        selected = main_line(options)
        team = display_team_name(match, team)
        # EuroLeague importers store the exact canonical roster name.  Do not
        # manufacture another display name from bookmaker text.
        player_name = str(player).strip() if league == "euroleague" else player_display_name(player)
        player_data = matches.setdefault((match, starts_at), {}).setdefault(team, {}).setdefault(player_name, {"name": player_name, "quotes": []})
        player_data["quotes"].append({"bookmaker": bookmaker, "line": selected[2], "under": selected[3], "over": selected[4]})
    result = []
    for (match, starts_at), teams in matches.items():
        match = normalize_match_name(match)
        if " - " not in match:
            continue
        home, away = (canonical_team_name(part) for part in match.split(" - ", 1))
        ordered = []
        for team_name in (home, away):
            players = list(teams.get(team_name, {}).values())
            for player in players:
                player["quotes"].sort(key=lambda quote: quote["bookmaker"])
            players.sort(key=lambda player: -max(quote["line"] for quote in player["quotes"]))
            ordered.append({"name": team_name, "players": players})
        result.append({"name": display_match_name(match), "time": belgrade_time(starts_at), "teams": ordered})
    return sorted(result, key=lambda match: match["time"])


@points_bp.route("/player-points")
def page():
    league = request.args.get("league", "bbl")
    matches = bbl_matches(league) if league in ("bbl", "euroleague") and DB.exists() else []
    return render_template_string(PAGE, leagues=LEAGUES, league=league, matches=matches)
