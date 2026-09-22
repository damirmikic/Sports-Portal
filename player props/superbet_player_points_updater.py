"""Refresh canonical Superbet EuroLeague player points."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

from central_roster import canonical_fixture, resolve_player


DB = Path(__file__).with_name("basketball_player_points.db")
EVENTS = "https://production-superbet-offer-rs.freetls.fastly.net/sb-rs/api/v3/sr-Latn-RS/events"
BETBUILDER = "https://production-superbet-bmb.freetls.fastly.net/betbuilder/v2/getBetbuilderMarketsForMatch"
TOURNAMENTS = "11,24,2373,2374,2379,2380,2381,2382,19114,76588"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SESSION = requests.Session()
SESSION.trust_env = False


def split_fixture_name(value):
    text = str(value or "").replace("\ufffd", "\u00b7").strip()
    for separator in (" - ", " \u00b7 ", "\u00b7"):
        if separator in text:
            home, away = text.split(separator, 1)
            if home.strip() and away.strip():
                return home.strip(), away.strip()
    return None


def fetch():
    params = {
        "startDate": "2026-09-21T00:00:00.000Z",
        "endDate": "2027-03-20T00:00:00.000Z",
        "index": "active-prematch",
        "sports": 4,
        "tournaments": TOURNAMENTS,
    }
    response = SESSION.get(EVENTS, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()

    rows = []
    unresolved = set()
    target_events = 0
    successful_details = 0

    for event in data.get("events", []):
        fixture = event.get("fixture") or {}
        raw_match = fixture.get("event_name")
        raw_teams = split_fixture_name(raw_match)
        if not raw_teams or fixture.get("tournament_id") not in (19114, "19114"):
            continue

        teams = canonical_fixture(*raw_teams, league="EuroLeague")
        if not teams:
            unresolved.add((str(raw_match), "NEPOZNATA UTAKMICA"))
            continue
        target_events += 1
        match = f"{teams[0]} - {teams[1]}"

        try:
            detail_response = SESSION.get(
                BETBUILDER,
                params={
                    "match_id": event["event_id"],
                    "lang": "sr-Latn-RS",
                    "target": "SB_RS",
                },
                headers=HEADERS,
                timeout=30,
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            successful_details += 1
        except (requests.RequestException, ValueError):
            continue

        market = next(
            (market for market in detail.get("markets", []) if str(market.get("id")) == "233565"),
            None,
        )
        if not market:
            continue

        grouped = {}
        for odd in market.get("odds", []):
            spec = odd.get("specifiers") or {}
            player, total = spec.get("player"), spec.get("total")
            if not player or total is None or odd.get("status") != "ACTIVE":
                continue
            key = (player, float(total))
            quote = grouped.setdefault(key, {})
            label = (odd.get("name") or "").lower()
            quote["under" if "manje" in label else "over"] = float(odd["price"])

        for (raw_player, line), odds in grouped.items():
            if "under" not in odds or "over" not in odds:
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
            rows.append(
                (
                    "Euroleague",
                    match,
                    fixture.get("utc_date"),
                    team,
                    standard_player,
                    "Superbet",
                    line,
                    odds["under"],
                    odds["over"],
                    datetime.now(timezone.utc).isoformat(),
                )
            )

    if target_events and not successful_details:
        raise RuntimeError("Superbet detalji nisu preuzeti; postojeći podaci nisu menjani")
    if unresolved:
        print("Superbet nepovezano:")
        for match, player in sorted(unresolved):
            print(f"  {match} | {player}")
    return rows


def update():
    rows = fetch()
    with sqlite3.connect(DB) as connection:
        connection.execute(
            "delete from player_points_odds "
            "where league='Euroleague' and bookmaker='Superbet'"
        )
        connection.executemany(
            "insert into player_points_odds values(?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


if __name__ == "__main__":
    print(f"Superbet Euroleague rows saved: {update()}")
