"""Canonical team and player names backed by the shared roster table."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path


DB = Path(__file__).with_name("basketball_player_points.db")
_INITIAL = re.compile(r"^[a-z]{1,2}$")
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Names used by feeds that differ from the short names in the central roster.
# These are deliberately tied to a canonical team, so a team string can never
# make a player eligible for both sides of a fixture.
_TEAM_FEED_ALIASES = {
    "Olympiacos": ("Olympiakos Piraeus", "BC Olympiakos Piraeus"),
    "Milano": ("Olimpia Milano",),
    "Crvena Zvezda": ("KK Crvena Zvezda Meridianbet", "KK Crvena Zvezda Meridianbet Belgrade"),
    "Zalgiris": ("BC Zalgiris Kaunas",),
    "Partizan": ("KK Partizan Belgrade",),
}


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _name_norm(value):
    tokens = [token for token in norm(value).split() if token not in _SUFFIXES]
    return " ".join(tokens)


def _team_aliases(standard, alternate):
    values = [standard]
    values.extend(part.strip() for part in str(alternate or "").split(","))
    values.extend(_TEAM_FEED_ALIASES.get(standard, ()))
    return [value for value in values if value]


def load(league=None):
    query = (
        "select league,standard_team,alternate_team,standard_player,"
        "alternate_player from player_roster"
    )
    with sqlite3.connect(DB) as connection:
        rows = connection.execute(query).fetchall()
    if league:
        league_key = norm(league).replace(" ", "")
        rows = [row for row in rows if norm(row[0]).replace(" ", "") == league_key]
    return rows


def canonical_team(raw_team, league="EuroLeague"):
    """Return the roster team for a bookmaker team name, or None."""
    raw_key = norm(raw_team)
    if not raw_key:
        return None

    scored = {}
    for _, standard, alternate, _, _ in load(league):
        score = 0
        for alias in _team_aliases(standard, alternate):
            alias_key = norm(alias)
            if not alias_key:
                continue
            if raw_key == alias_key:
                score = max(score, 100)
            elif len(alias_key) >= 4 and (alias_key in raw_key or raw_key in alias_key):
                score = max(score, 70 + min(len(alias_key), len(raw_key)))
        if score:
            scored[standard] = max(score, scored.get(standard, 0))

    if not scored:
        return None
    best = max(scored.values())
    winners = [team for team, score in scored.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def _surname_key(standard_player):
    tokens = _name_norm(standard_player).split()
    while tokens and _INITIAL.fullmatch(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def resolve_player(raw_player, league="EuroLeague", allowed_teams=None):
    """Resolve a bookmaker player to the canonical roster player and team.

    A canonical surname is accepted only when it identifies one player among
    the two teams in the fixture. Ambiguous matches are rejected, never guessed.
    """
    player_key = _name_norm(raw_player)
    if not player_key:
        return None

    allowed = None
    if allowed_teams is not None:
        allowed = {canonical_team(team, league) or str(team).strip() for team in allowed_teams}
        allowed.discard("")
        allowed.discard(None)

    candidates = {}
    player_tokens = player_key.split()
    for _, team, _, standard, alternate in load(league):
        if allowed is not None and team not in allowed:
            continue

        standard_key = _name_norm(standard)
        alternate_key = _name_norm(alternate)
        surname = _surname_key(standard)
        surname_tokens = surname.split()
        score = 0

        if alternate_key and player_key == alternate_key:
            score = 120
        elif standard_key and player_key == standard_key:
            score = 115
        elif alternate_key and set(alternate_key.split()) == set(player_tokens):
            score = 110
        elif surname and surname in player_key:
            score = 80 + len(surname_tokens)
        elif surname_tokens and all(token in player_tokens for token in surname_tokens):
            score = 75 + len(surname_tokens)

        if score:
            key = (team, standard)
            candidates[key] = max(score, candidates.get(key, 0))

    if not candidates:
        return None
    best = max(candidates.values())
    winners = [key for key, score in candidates.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def canonical_fixture(home, away, league="EuroLeague"):
    home_team = canonical_team(home, league)
    away_team = canonical_team(away, league)
    if not home_team or not away_team or home_team == away_team:
        return None
    return home_team, away_team


def team_match(raw, standard, alternate):
    raw_key = norm(raw)
    return any(
        alias_key and (raw_key == alias_key or alias_key in raw_key or raw_key in alias_key)
        for alias_key in (norm(value) for value in _team_aliases(standard, alternate))
    )


def resolve(raw_player, raw_team=None, league="EuroLeague"):
    allowed = [raw_team] if raw_team else None
    return resolve_player(raw_player, league=league, allowed_teams=allowed)
