import requests

BASE_URL = "https://www.soccerbet.rs/restapi/offer/sr"
MOBILE_VERSION = "3.3.4"
LOCALE = "sr"
SPORT = "S"
CL_LEAGUE_ID = "2519992"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.soccerbet.rs/",
}

EVENT_PARAMS = {
    "annex": "0",
    "getChildrenLeagueCategories": "true",
    "mobileVersion": MOBILE_VERSION,
    "locale": LOCALE,
}

LEAGUE_PARAMS = {
    "annex": 0,
    "mobileVersion": MOBILE_VERSION,
    "locale": LOCALE,
}

# Potvrđeni SoccerBet tip-type kodovi.
TT_1 = "1"
TT_X = "2"
TT_2 = "3"
TT_GOAL_BOTH_HALVES = "363"   # I1+&II1+


class SoccerBetClient:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # --------------------------------------------------------
    # PREMATCH DISCOVERY CELE LIGE
    # --------------------------------------------------------
    def get_league(self, league_id=CL_LEAGUE_ID):
        url = f"{BASE_URL}/sport/{SPORT}/league/{league_id}/mob"
        response = self.session.get(
            url,
            params=LEAGUE_PARAMS,
            timeout=self.timeout
        )
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("SoccerBet liga nije očekivani JSON objekat.")

        return data

    def get_matches(self, league_id=CL_LEAGUE_ID):
        data = self.get_league(league_id)
        matches = data.get("esMatches") or []

        result = []

        for match in matches:
            if not isinstance(match, dict):
                continue

            event_id = match.get("id")
            home = match.get("home")
            away = match.get("away")

            if event_id is None or not home or not away:
                continue

            result.append({
                "id": event_id,
                "matchCode": match.get("matchCode"),
                "home": home,
                "away": away,
                "kickOffTime": match.get("kickOffTime"),
            })

        return result

    # --------------------------------------------------------
    # DETALJI JEDNOG PREMATCH MEČA
    # --------------------------------------------------------
    def get_event(self, event_id):
        url = f"{BASE_URL}/match/{event_id}"

        response = self.session.get(
            url,
            params=EVENT_PARAMS,
            timeout=self.timeout
        )
        response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("SoccerBet meč nije očekivani JSON objekat.")

        return data

    @staticmethod
    def _odd_from_tt(event, tt):
        betmap = event.get("betMap") or {}
        group = betmap.get(str(tt))

        if not isinstance(group, dict):
            return None

        item = group.get("NULL")

        if not isinstance(item, dict):
            values = [
                value
                for value in group.values()
                if isinstance(value, dict)
            ]

            if len(values) != 1:
                return None

            item = values[0]

        # U = aktivna/pre-match kvota u SoccerBet odgovoru.
        if item.get("s") != "U":
            return None

        try:
            return float(item["ov"])
        except (KeyError, TypeError, ValueError):
            return None

    def get_1x2(self, event_id):
        event = self.get_event(event_id)

        return {
            "1": self._odd_from_tt(event, TT_1),
            "X": self._odd_from_tt(event, TT_X),
            "2": self._odd_from_tt(event, TT_2),
        }

    def get_both_halves_goal(self, event_id):
        event = self.get_event(event_id)
        return self._odd_from_tt(event, TT_GOAL_BOTH_HALVES)

    def get_markets(self, event_id):
        # Samo jedan HTTP poziv po meču za oba marketa.
        event = self.get_event(event_id)

        return {
            "event": {
                "id": event.get("id"),
                "home": event.get("home"),
                "away": event.get("away"),
                "league": event.get("leagueName"),
                "live": event.get("live"),
                "status": event.get("status"),
            },
            "1X2": {
                "1": self._odd_from_tt(event, TT_1),
                "X": self._odd_from_tt(event, TT_X),
                "2": self._odd_from_tt(event, TT_2),
            },
            "1+I&1+II": self._odd_from_tt(
                event,
                TT_GOAL_BOTH_HALVES
            ),
        }


def get_soccerbet_matches():
    client = SoccerBetClient()

    return [
        {
            "id": match["id"],
            "home": match["home"],
            "away": match["away"],
        }
        for match in client.get_matches()
    ]


if __name__ == "__main__":
    client = SoccerBetClient()

    print("SOCCERBET - LIGA SAMPIONA PREMATCH")
    matches = client.get_matches()

    print("Broj meceva:", len(matches))
    print("=" * 80)

    for match in matches:
        print(
            f'{match["id"]} | sifra {match["matchCode"]} | '
            f'{match["home"]} - {match["away"]}'
        )

    # Ako je PSV još PREMATCH, testiraj i oba marketa.
    for match in matches:
        if match["home"].lower().startswith("psv"):
            print()
            print("TEST MARKETA:")
            markets = client.get_markets(match["id"])
            print("Meč:", markets["event"]["home"], "-", markets["event"]["away"])
            print("1X2:", markets["1X2"])
            print("1+I&1+II:", markets["1+I&1+II"])
            break
