import requests
import time
import uuid


class MozzartClient:
    BASE_URL = "https://www.mozzartbet.com/betting/match"

    def __init__(self):
        self.session = requests.Session()

        unique_id = (
            f"{int(time.time() * 1000)}-"
            f"{uuid.uuid4().hex[:8]}"
        )

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": (
                "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7"
            ),
            "Content-Type": "application/json",
            "Origin": "https://www.mozzartbet.com",
            "Referer": (
                "https://www.mozzartbet.com/sr/kladjenje/"
                "sport/1/match/1017276?date=today"
            ),
            "Medium": "PREMATCH_MOBILE",
            "X-Unique-Id": unique_id,
            "Sec-CH-UA": (
                '"Chromium";v="152", '
                '"Not?A_Brand";v="24", '
                '"Google Chrome";v="152"'
            ),
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })

    def get_event(self, event_id):
        url = f"{self.BASE_URL}/{event_id}"

        payload = {
            "subgameIds": [],
            "subgames": [],
            "participantId": "",
            "matchTypeId": 0,
            "onlyBindableGames": False,
        }

        r = self.session.post(
            url,
            json=payload,
            timeout=20
        )

        print("STATUS:", r.status_code)

        if r.status_code != 200:
            print("RESPONSE:")
            print(r.text[:1000])

        r.raise_for_status()

        return r.json()

    def get_markets(self, event_id):
        event = self.get_event(event_id)

        match = event.get("match", {})

        return match.get("oddsGroup", [])

    def find_markets(self, event_id, search_text):
        markets = self.get_markets(event_id)

        search_text = search_text.lower()

        return [
            market
            for market in markets
            if search_text in str(
                market.get("groupName", "")
            ).lower()
        ]

    def market_odds(self, market):
        result = []

        for odd in market.get("odds", []):
            result.append({
                "name": odd.get(
                    "subgame",
                    {}
                ).get("name"),
                "price": odd.get("value"),
                "status": odd.get("oddStatus"),
            })

        return result


if __name__ == "__main__":
    client = MozzartClient()

    event_id = 1017276

    event = client.get_event(event_id)

    match = event.get("match", {})

    print(
        "EVENT:",
        match.get("home"),
        "-",
        match.get("visitor")
    )

    markets = client.get_markets(event_id)

    print("UKUPNO MARKETA:", len(markets))

    print("\nPRVIH 10 MARKETA:")

    for market in markets[:10]:
        print(
            market.get("groupName")
        )