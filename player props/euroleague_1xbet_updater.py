"""Refresh canonical 1xBet EuroLeague player points."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from central_roster import canonical_fixture, resolve_player


for _proxy_var in (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
):
    os.environ.pop(_proxy_var, None)

HTTP = requests.Session()
HTTP.trust_env = False
BASE = "https://1xbet.rs/service-api/main-line-feed/v3"
DB = Path(__file__).with_name("basketball_player_points.db")
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://1xbet.rs/sp/line/basketball/139460-euroleague",
}


def get_json(path, params):
    last_error = None
    for attempt in range(3):
        try:
            response = HTTP.get(BASE + path, params=params, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.6)
    raise last_error


def player_points_group(detail):
    return next(
        (
            event_group
            for event_group in detail.get("eventGroups", [])
            if event_group.get("groupId") == 850
        ),
        None,
    )


def player_points_detail(main_detail, detail_params):
    """Find the player market without relying on one volatile subgame type."""
    if player_points_group(main_detail):
        return main_detail

    subgames = main_detail.get("subGamesForMainGame", [])
    subgames = sorted(
        subgames,
        key=lambda item: (
            0 if item.get("gameTypeId") == 52 else 1 if item.get("gameTypeId") is None else 2
        ),
    )

    # The current feed usually embeds every subgame's market groups directly
    # in the main response.  This also survives changes or omissions of the
    # old gameTypeId=52 marker.
    for subgame in subgames:
        if player_points_group(subgame):
            return subgame

    checked = set()
    for subgame in subgames:
        if subgame.get("eventGroups"):
            continue
        subgame_id = subgame.get("id")
        if not subgame_id or subgame_id in checked:
            continue
        checked.add(subgame_id)
        params = dict(detail_params)
        params["gameId"] = subgame_id
        try:
            candidate = get_json("/gameEvents", params)
        except (requests.RequestException, ValueError, AttributeError):
            continue
        if player_points_group(candidate):
            return candidate
    return None


def fetch():
    params = {
        "cfView": 3,
        "count": 40,
        "fcountry": 168,
        "gr": 1039,
        "grMode": 4,
        "lng": "sp",
        "ref": 321,
        "selectedMs": "2.3.139460",
    }
    games = get_json("/games1x2", params)
    if not isinstance(games, list):
        raise RuntimeError("1xBet lista utakmica nije u očekivanom formatu")

    rows = []
    unresolved = set()
    target_games = 0
    successful_details = 0
    market_games = 0

    for game in games:
        if str((game.get("liga") or {}).get("id")) != "139460":
            continue
        game_id = game.get("id")
        raw_home = (game.get("opponent1") or {}).get("fullName")
        raw_away = (game.get("opponent2") or {}).get("fullName")
        if not game_id or not raw_home or not raw_away:
            continue

        target_games += 1
        teams = canonical_fixture(raw_home, raw_away, league="EuroLeague")
        if not teams:
            unresolved.add((f"{raw_home} - {raw_away}", "NEPOZNATA UTAKMICA"))
            continue
        match = f"{teams[0]} - {teams[1]}"

        detail_params = {
            "cfView": 3,
            "countEvents": 250,
            "fcountry": 168,
            "gameId": game_id,
            "gr": 1039,
            "grMode": 4,
            "lng": "sp",
            "marketType": 1,
            "ref": 321,
        }
        try:
            main_detail = get_json("/gameEvents", detail_params)
            successful_details += 1
            detail = player_points_detail(main_detail, detail_params)
        except (requests.RequestException, ValueError, AttributeError):
            continue
        if not detail:
            continue

        group = player_points_group(detail)
        if not group:
            continue
        market_games += 1
        # Player markets live in a subgame, but the subgame does not carry
        # the fixture kickoff. Always take the time from the main event,
        # with the list response as a fallback.
        start_ts = main_detail.get("startTs") or game.get("startTs")
        if start_ts is None:
            continue

        quotes = {}
        for side in group.get("events", []):
            for event in side:
                player = event.get("player") or {}
                raw_player = player.get("name")
                line = event.get("parameter")
                odd = event.get("cf")
                quote_type = event.get("type")
                if raw_player is None or line is None or odd is None:
                    continue
                if quote_type not in (1806, 1807):
                    continue

                resolved = resolve_player(
                    raw_player,
                    league="EuroLeague",
                    allowed_teams=teams,
                )
                if not resolved:
                    unresolved.add((match, raw_player))
                    continue
                team, standard_player = resolved
                key = (team, standard_player, float(line))
                quote = quotes.setdefault(key, {})
                quote["over_odd" if quote_type == 1807 else "under_odd"] = float(odd)

        for (team, standard_player, line), quote in quotes.items():
            if "under_odd" not in quote or "over_odd" not in quote:
                continue
            rows.append(
                (
                    "Euroleague",
                    match,
                    start_ts,
                    team,
                    standard_player,
                    "1xBet",
                    line,
                    quote["under_odd"],
                    quote["over_odd"],
                    datetime.now(timezone.utc).isoformat(),
                )
            )

    if not target_games:
        raise RuntimeError("1xBet nije vratio nijednu ciljnu EuroLeague utakmicu")
    if not successful_details:
        raise RuntimeError("1xBet detalji nisu preuzeti; postojeći podaci nisu menjani")
    if not market_games or not rows:
        raise RuntimeError(
            "1xBet nije vratio nijednu kompletnu ponudu igrača; "
            "poslednji ispravni podaci ostaju sačuvani"
        )
    invalid_rows = [
        row for row in rows
        if not row[1] or row[2] is None or not row[3] or not row[4]
        or row[7] is None or row[8] is None
    ]
    if invalid_rows:
        raise RuntimeError(
            f"1xBet je vratio {len(invalid_rows)} neispravnih redova; "
            "postojeći podaci ostaju sačuvani"
        )
    if unresolved:
        print("1xBet nepovezano:")
        for match, player in sorted(unresolved):
            print(f"  {match} | {player}")
    return rows


def update():
    rows = fetch()
    if not rows:
        raise RuntimeError("Prazan 1xBet rezultat ne sme zameniti postojeće podatke")
    with sqlite3.connect(DB) as connection:
        connection.execute(
            "create table if not exists player_points_odds("
            "league TEXT, match_name TEXT, starts_at TEXT, team TEXT, player TEXT, "
            "bookmaker TEXT, line REAL, under_odd REAL, over_odd REAL, fetched_at TEXT, "
            "primary key(match_name,team,player,bookmaker,line))"
        )
        connection.execute(
            "delete from player_points_odds "
            "where league='Euroleague' and bookmaker='1xBet'"
        )
        connection.executemany(
            "insert into player_points_odds values(?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


if __name__ == "__main__":
    print(f"1xBet Euroleague rows saved: {update()}")
