import requests

BASE_URL = "https://danteprod.phoenix365-prod.com/partner-api/sportsbook/public/v2"
SPORT_ID = "1"
REGION_ID = "1050"
TOURNAMENT_ID = "94"
CL_TOURNAMENT_ID = "94"
UEFA_REGION_ID = "1050"
FOOTBALL_SPORT_ID = "1"

# King market IDs discovered from the public prematch feed
MARKET_1X2 = "77"
MARKET_GOAL_BOTH_HALVES = "66"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://king.rs/",
    "Origin": "https://king.rs",
}


class KingClient:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get_cl_matches(self):
        url = f"{BASE_URL}/listing/tournaments-with-events"
        params = {
            "sportId": SPORT_ID,
            "sportService": "PREMATCH",
            "offset": 0,
            "limit": 48,
            "regionId": REGION_ID,
            "tournamentId": TOURNAMENT_ID,
        }
        r = self.session.get(url, params=params, timeout=15)
        r.raise_for_status()
        payload = r.json()

        tournaments = payload.get("tournaments") or payload.get("data", {}).get("tournaments") or []
        matches = []

        for tournament in tournaments:
            if str(tournament.get("tournamentId")) != TOURNAMENT_ID:
                continue

            for event in tournament.get("events", []):
                event_id = event.get("eventId") or event.get("id")
                if not event_id:
                    continue

                # King listing može imati različita polja za naziv/učesnike.
                home = ""
                away = ""

                competitors = event.get("competitors") or event.get("participants") or []
                if isinstance(competitors, list) and len(competitors) >= 2:
                    def cname(x):
                        if not isinstance(x, dict):
                            return str(x)
                        return (
                            x.get("name")
                            or x.get("competitorName")
                            or x.get("participantName")
                            or x.get("shortName")
                            or ""
                        )
                    home = cname(competitors[0])
                    away = cname(competitors[1])

                if not home or not away:
                    home = (
                        event.get("homeName")
                        or event.get("homeTeamName")
                        or event.get("homeCompetitorName")
                        or ""
                    )
                    away = (
                        event.get("awayName")
                        or event.get("awayTeamName")
                        or event.get("awayCompetitorName")
                        or ""
                    )

                # Ako listing nema imena, pokušaj da ih izvučemo iz event name polja.
                if not home or not away:
                    name = event.get("name") or event.get("eventName") or ""
                    for sep in (" - ", " vs ", " v "):
                        if sep in name:
                            left, right = name.split(sep, 1)
                            home = home or left.strip()
                            away = away or right.strip()
                            break

                matches.append({
                    "id": str(event_id),
                    "home": home.strip() if isinstance(home, str) else str(home),
                    "away": away.strip() if isinstance(away, str) else str(away),
                    "start": event.get("startTime") or event.get("startsAt") or event.get("startDate") or "",
                    "_raw": event,
                })

        return matches

    def get_markets_page(self, event_id, offset=0, limit=500):
        url = f"{BASE_URL}/event/{event_id}/markets"
        params = {"offset": offset, "limit": limit}

        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _market_groups(payload):
        """
        King /markets response is normally:
        {"data": [ {marketTypeId, marketTypeName, markets:[...]}, ... ]}

        Keep this tolerant in case the wrapper changes slightly.
        """
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        data = payload.get("data")
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ("markets", "items", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value

        for key in ("markets", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        return []

    def get_all_markets(self, event_id):
        """
        First try one large request. If King caps the page size, continue
        with pagination without making one request per market.
        """
        first = self.get_markets_page(event_id, offset=0, limit=500)
        groups = self._market_groups(first)

        # If we received plenty of groups, this is normally the full event.
        # The fallback below is mainly for APIs that silently cap limit.
        if len(groups) >= 100:
            return groups

        # Probe the next page. If empty, first page was complete.
        second = self.get_markets_page(event_id, offset=len(groups), limit=500)
        more = self._market_groups(second)
        if not more:
            return groups

        seen = set()
        combined = []

        def add(items):
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = (
                    str(item.get("marketTypeId", "")),
                    str(item.get("id", "")),
                    str(item.get("marketTypeName", "")),
                )
                if key not in seen:
                    seen.add(key)
                    combined.append(item)

        add(groups)
        add(more)

        offset = len(groups) + len(more)
        while more:
            page = self.get_markets_page(event_id, offset=offset, limit=500)
            more = self._market_groups(page)
            if not more:
                break
            before = len(combined)
            add(more)
            if len(combined) == before:
                break
            offset += len(more)

        return combined

    @staticmethod
    def _outcomes_from_group(group):
        outcomes = []

        # /markets groups usually contain a list named "markets".
        for market in group.get("markets", []) if isinstance(group, dict) else []:
            if not isinstance(market, dict):
                continue
            if str(market.get("marketStatus", "ACTIVE")).upper() not in ("ACTIVE", "OPEN"):
                continue
            for outcome in market.get("outcomes", []):
                if isinstance(outcome, dict):
                    outcomes.append(outcome)

        # Be tolerant if outcomes are directly on the group.
        if isinstance(group, dict):
            for outcome in group.get("outcomes", []):
                if isinstance(outcome, dict):
                    outcomes.append(outcome)

        return outcomes

    @staticmethod
    def _odd_value(outcome):
        for key in ("odd", "odds", "price", "value"):
            value = outcome.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.replace(",", "."))
                except ValueError:
                    pass
            if isinstance(value, dict):
                for subkey in ("decimal", "value", "odd"):
                    v = value.get(subkey)
                    if isinstance(v, (int, float)):
                        return float(v)
                    if isinstance(v, str):
                        try:
                            return float(v.replace(",", "."))
                        except ValueError:
                            pass
        return None

    @staticmethod
    def _label(outcome):
        values = [
            outcome.get("name"),
            outcome.get("shortName"),
            outcome.get("shortcut"),
            outcome.get("label"),
        ]
        return " ".join(str(v) for v in values if v is not None).strip().upper()

    def find_group(self, groups, market_type_id):
        for group in groups:
            if str(group.get("marketTypeId")) == str(market_type_id):
                return group
        return None

    def get_1x2_from_groups(self, groups):
        group = self.find_group(groups, MARKET_1X2)
        if not group:
            return {}

        result = {}
        outcomes = self._outcomes_from_group(group)

        for outcome in outcomes:
            label = self._label(outcome)
            odd = self._odd_value(outcome)
            if odd is None:
                continue

            if label in ("1", "HOME", "HOME WIN") or label.startswith("1 "):
                result["1"] = odd
            elif label in ("X", "DRAW") or " DRAW" in f" {label}":
                result["X"] = odd
            elif label in ("2", "AWAY", "AWAY WIN") or label.startswith("2 "):
                result["2"] = odd

        # Fallback: Winner 3-way is conventionally home/draw/away in order.
        if len(result) < 3 and len(outcomes) >= 3:
            vals = [self._odd_value(x) for x in outcomes[:3]]
            if all(v is not None for v in vals):
                result = {"1": vals[0], "X": vals[1], "2": vals[2]}

        return result

    def get_both_halves_goal_from_groups(self, groups):
        group = self.find_group(groups, MARKET_GOAL_BOTH_HALVES)
        if not group:
            return None

        outcomes = self._outcomes_from_group(group)

        # We need YES: at least one goal in first half AND at least one in second.
        for outcome in outcomes:
            label = self._label(outcome)
            if label in ("YES", "DA", "Y") or " YES" in f" {label}":
                return self._odd_value(outcome)

        # Fallback for a two-outcome Yes/No market: print diagnostics rather
        # than silently assuming the wrong side.
        return None

    def get_markets(self, event_id):
        groups = self.get_all_markets(event_id)
        return {
            "1x2": self.get_1x2_from_groups(groups),
            "both_halves_goal": self.get_both_halves_goal_from_groups(groups),
            "market_groups": groups,
        }


def _event_name(event):
    for key in ("name", "eventName", "sportName"):
        value = event.get(key)
        if isinstance(value, str) and " - " in value:
            return value

    home = (
        event.get("homeTeamName")
        or event.get("homeName")
        or event.get("home")
        or ""
    )
    away = (
        event.get("awayTeamName")
        or event.get("awayName")
        or event.get("away")
        or ""
    )
    return f"{home} - {away}".strip(" -")


def get_king_matches():
    client = KingClient()
    matches = client.get_cl_matches()
    return [{"id": m["id"], "home": m["home"], "away": m["away"]} for m in matches]


if __name__ == "__main__":
    client = KingClient()
    matches = client.get_cl_matches()

    print("KING - LIGA SAMPIONA PREMATCH")
    print("Broj meceva:", len(matches))
    print("=" * 100)
    for m in matches:
        print(f'{m["id"]} | {m["home"]} - {m["away"]} | {m.get("start", "")}')

    if matches:
        test = matches[0]
        print("\nTEST MARKETA:")
        print("Mec:", f'{test["home"]} - {test["away"]}')
        print("Event ID:", test["id"])
        result = client.get_markets(test["id"])
        print("Broj market grupa:", result.get("market_group_count"))
        print("Pronadjen 1X2 (77):", bool(result.get("1x2")))
        print("Pronadjen gol u oba poluvremena (66):", result.get("both_halves_goal") is not None)
        print("1X2:", result.get("1x2"))
        print("1+I&1+II:", result.get("both_halves_goal"))
