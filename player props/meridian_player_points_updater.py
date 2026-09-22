"""Refresh canonical Meridian EuroLeague player-point markets.

Meridian exposes the league event list separately from the player markets:
the list gives every event id, ``/events/{id}`` exposes the game-group id,
and ``/events/{id}/markets?gameGroupId=...`` contains the player lines.
Only rows resolved through the central roster are written to the shared DB.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

from central_roster import canonical_fixture, resolve_player


DB = Path(__file__).with_name("basketball_player_points.db")
API = "https://online.meridianbet.com/betshop/api"
LEAGUE_ID = 208
BOOKMAKER = "Meridian"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://meridianbet.rs",
    "Referer": "https://meridianbet.rs/",
    "User-Agent": "Mozilla/5.0",
}
SESSION = requests.Session()
SESSION.trust_env = False


def _headers():
    headers = dict(HEADERS)
    token = os.getenv("MERIDIAN_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_json(path, params=None):
    response = SESSION.get(
        API + path,
        params=params or {},
        headers=_headers(),
        timeout=30,
    )
    if response.status_code == 401:
        raise RuntimeError(
            "Meridian API traži pristupni token. Postavi MERIDIAN_ACCESS_TOKEN "
            "iz aktivne sesije meridianbet.rs."
        )
    response.raise_for_status()
    data = response.json()
    if data.get("errorCode"):
        raise RuntimeError(f"Meridian API greška: {data.get('errorCode')}")
    return data


def _text(value):
    return " ".join(str(value or "").split()).strip()


def _league_events(data):
    payload = data.get("payload") or {}
    for league in payload.get("leagues") or []:
        if str(league.get("leagueId")) != str(LEAGUE_ID):
            continue
        yield from league.get("events") or []


def _player_group_id(detail):
    payload = detail.get("payload") or {}
    for group in payload.get("activeGameGroups") or []:
        name = _text(group.get("name")).lower()
        if "poeni" in name and "igra" in name:
            return group.get("id")
    return None


def _player_market(payload):
    """Return the over/under player market from a markets response."""
    candidates = []
    for group in payload if isinstance(payload, list) else []:
        name = _text(group.get("marketName")).lower()
        if group.get("marketType") != "PLAYER_MARKET":
            continue
        # The first group has an exact line and Manje/Više prices.  The plus
        # ladder is intentionally ignored because it is not a single line.
        if "ukupno poena" in name or "ukupno poeni" in name:
            candidates.append(group)
    if not candidates:
        return None
    return candidates[0]


def parse_player_rows(event_header, market_response, league="EuroLeague"):
    """Parse one event's player market into DB rows and unresolved names."""
    rivals = event_header.get("rivals") or []
    if len(rivals) != 2:
        return [], {("NEPOZNATA UTAKMICA", "")}
    teams = canonical_fixture(rivals[0], rivals[1], league=league)
    if not teams:
        return [], {(f"{rivals[0]} - {rivals[1]}", "NEPOZNATA UTAKMICA")}
    match = f"{teams[0]} - {teams[1]}"
    start_ms = event_header.get("startTime")
    starts_at = (
        datetime.fromtimestamp(float(start_ms) / 1000, tz=timezone.utc).isoformat()
        if start_ms is not None
        else None
    )
    market = _player_market((market_response.get("payload") if isinstance(market_response, dict) else None))
    if not market:
        return [], set()

    rows = []
    unresolved = set()
    fetched_at = datetime.now(timezone.utc).isoformat()
    for quote in market.get("markets") or []:
        raw_player = _text(quote.get("name"))
        line = quote.get("overUnder")
        selections = quote.get("selections") or []
        if not raw_player or line is None:
            continue
        odds = {}
        for selection in selections:
            if selection.get("state") != "ACTIVE":
                continue
            label = _text(selection.get("name")).lower()
            price = selection.get("price")
            if price is None:
                continue
            if label in {"manje", "under"}:
                odds["under"] = float(price)
            elif label in {"više", "vise", "over"}:
                odds["over"] = float(price)
        if "under" not in odds or "over" not in odds:
            continue
        resolved = resolve_player(raw_player, league=league, allowed_teams=teams)
        if not resolved:
            unresolved.add((match, raw_player))
            continue
        team, standard_player = resolved
        rows.append(
            (
                "Euroleague",
                match,
                starts_at,
                team,
                standard_player,
                BOOKMAKER,
                float(line),
                odds["under"],
                odds["over"],
                fetched_at,
            )
        )
    return rows, unresolved


def fetch():
    listing = get_json(
        "/v1/offer/sport/55/league",
        {"time": "ALL", "leagues": LEAGUE_ID, "page": 0},
    )
    events = list(_league_events(listing))
    if not events:
        raise RuntimeError("Meridian nije vratio nijednu EuroLeague utakmicu")

    rows = []
    unresolved = set()
    market_events = 0
    for event in events:
        header = event.get("header") or {}
        event_id = header.get("eventId")
        if not event_id:
            continue
        detail = get_json(f"/v2/events/{event_id}")
        group_id = _player_group_id(detail)
        if not group_id:
            continue
        market_response = get_json(
            f"/v2/events/{event_id}/markets",
            {"gameGroupId": group_id},
        )
        event_rows, event_unresolved = parse_player_rows(header, market_response)
        if event_rows:
            market_events += 1
            rows.extend(event_rows)
        unresolved.update(event_unresolved)

    if not market_events or not rows:
        raise RuntimeError(
            "Meridian nije vratio nijednu kompletnu ponudu poena igrača; "
            "postojeći Meridian podaci ostaju sačuvani"
        )
    if unresolved:
        print("Meridian nepovezano:")
        for match, player in sorted(unresolved):
            print(f"  {match} | {player}")
    return rows


def update():
    rows = fetch()
    with sqlite3.connect(DB) as connection:
        connection.execute(
            "delete from player_points_odds "
            "where league='Euroleague' and bookmaker=?",
            (BOOKMAKER,),
        )
        connection.executemany(
            "insert into player_points_odds values(?,?,?,?,?,?,?,?,?,?)", rows
        )
    return len(rows)


if __name__ == "__main__":
    print(f"Meridian Euroleague rows saved: {update()}")
