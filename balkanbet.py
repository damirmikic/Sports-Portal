import json
import requests
from datetime import datetime

BASE_URL = "https://sports-sm-distribution-api.de-2.nsoftcdn.com/api/v1"
TOURNAMENT_ID = 12
COMPANY_UUID = "4f54c6aa-82a9-475d-bf0e-dc02ded89225"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.balkanbet.rs",
    "Referer": "https://www.balkanbet.rs/",
}

LANGUAGE = {
    "default": "sr-Latn",
    "events": "sr-Latn",
    "sport": "sr-Latn",
    "category": "sr-Latn",
    "tournament": "sr-Latn",
    "team": "sr-Latn",
    "market": "sr-Latn",
}

MARKET_1X2_ID = 6
MARKET_BOTH_HALVES_ID = 434
OUTCOME_BOTH_HALVES_ID = 1304
OUTCOME_BOTH_HALVES_NAME = "I1+&II1+"


class BalkanBetClient:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get_matches(self):
        data_format = {
            "default": "object",
            "events": "array",
            "outcomes": "object",
        }

        params = {
            "deliveryPlatformId": 3,
            "dataFormat": json.dumps(data_format, separators=(",", ":")),
            "language": json.dumps(LANGUAGE, separators=(",", ":")),
            "timezone": "Europe/Belgrade",
            "company": "{}",
            "companyUuid": COMPANY_UUID,
            "filter[tournamentId]": TOURNAMENT_ID,
            "filter[from]": datetime.now().replace(microsecond=0).isoformat(),
            "sort": (
                "categoryPosition,categoryName,"
                "tournamentPosition,tournamentName,startsAt"
            ),
            "offerTemplate": "WEB_OVERVIEW",
            "shortProps": 1,
        }

        response = self.session.get(
            f"{BASE_URL}/events",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        events = (payload.get("data") or {}).get("events") or []

        result = []
        for event in events:
            if not isinstance(event, dict):
                continue

            # Potvrđeno iz BalkanBet _mapping:
            # a=id, j=name, n=startsAt, q=rootEventId/display code.
            event_id = event.get("a")
            name = event.get("j")
            starts_at = event.get("n")
            code = event.get("q")

            if event_id is None or not name:
                continue

            home, away = self._split_name(name)

            result.append({
                "id": event_id,
                "code": code,
                "home": home,
                "away": away,
                "name": name,
                "startsAt": starts_at,
            })

        return result

    @staticmethod
    def _split_name(name):
        if " - " in name:
            home, away = name.split(" - ", 1)
            return home.strip(), away.strip()
        return name.strip(), ""

    def get_event(self, event_id):
        data_format = {
            "default": "array",
            "markets": "array",
            "events": "array",
        }

        params = {
            "companyUuid": COMPANY_UUID,
            "id": event_id,
            "language": json.dumps(LANGUAGE, separators=(",", ":")),
            "timezone": "Europe/Belgrade",
            "dataFormat": json.dumps(data_format, separators=(",", ":")),
        }

        response = self.session.get(
            f"{BASE_URL}/events/{event_id}",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        data = payload.get("data")

        # Ovaj endpoint je u browser Preview-u vraćao event direktno u data.
        # Ostavljen je i fallback ako API vrati listu.
        if isinstance(data, list):
            if not data:
                raise ValueError("BalkanBet nije vratio događaj.")
            data = data[0]

        if not isinstance(data, dict):
            raise ValueError("BalkanBet event nije očekivani JSON objekat.")

        return data

    @staticmethod
    def _find_market(event, market_id=None, name=None):
        for market in event.get("markets") or []:
            if not isinstance(market, dict):
                continue

            if market_id is not None and market.get("marketId") == market_id:
                return market

            if name is not None and market.get("name") == name:
                return market

        return None

    @staticmethod
    def _active_odd(outcome):
        if not isinstance(outcome, dict):
            return None

        if outcome.get("active") not in (1, True, None):
            return None

        try:
            return float(outcome["odd"])
        except (KeyError, TypeError, ValueError):
            return None

    def get_markets(self, event_id):
        # Jedan HTTP poziv za oba marketa.
        event = self.get_event(event_id)

        market_1x2 = self._find_market(
            event,
            market_id=MARKET_1X2_ID
        )

        one_x_two = {}
        if market_1x2:
            for outcome in market_1x2.get("outcomes") or []:
                shortcut = str(
                    outcome.get("shortcut")
                    or ""
                ).strip().upper()

                name = str(
                    outcome.get("name")
                    or ""
                ).strip().upper()

                # BalkanBet za nerešeno koristi shortcut "0",
                # dok je naziv outcome-a "X".
                if shortcut == "1" or name == "1":
                    label = "1"
                elif shortcut == "0" or name == "X":
                    label = "X"
                elif shortcut == "2" or name == "2":
                    label = "2"
                else:
                    continue

                odd = self._active_odd(outcome)
                if odd is not None:
                    one_x_two[label] = odd

        market_both = self._find_market(
            event,
            market_id=MARKET_BOTH_HALVES_ID
        )

        both_halves = None
        if market_both:
            for outcome in market_both.get("outcomes") or []:
                if (
                    outcome.get("outcomeId") == OUTCOME_BOTH_HALVES_ID
                    or outcome.get("name") == OUTCOME_BOTH_HALVES_NAME
                ):
                    both_halves = self._active_odd(outcome)
                    break

        return {
            "event": {
                "id": event.get("id"),
                "name": event.get("name"),
                "startsAt": event.get("startsAt"),
                "active": event.get("active"),
            },
            "1X2": one_x_two,
            "1+I&1+II": both_halves,
        }


def get_balkanbet_matches():
    client = BalkanBetClient()
    return [
        {
            "id": match["id"],
            "home": match["home"],
            "away": match["away"],
        }
        for match in client.get_matches()
    ]


if __name__ == "__main__":
    client = BalkanBetClient()

    print("BALKANBET - LIGA SAMPIONA PREMATCH")
    matches = client.get_matches()
    print("Broj meceva:", len(matches))
    print("=" * 80)

    for match in matches:
        print(
            f'{match["id"]} | {match["home"]} - {match["away"]} '
            f'| {match["startsAt"]}'
        )

    psv = next(
        (
            match for match in matches
            if match["home"].lower().startswith("psv")
        ),
        None,
    )

    if psv:
        print()
        print("TEST MARKETA:")
        markets = client.get_markets(psv["id"])
        print("Meč:", psv["home"], "-", psv["away"])
        print("1X2:", markets["1X2"])
        print("1+I&1+II:", markets["1+I&1+II"])
