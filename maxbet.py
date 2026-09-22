import requests


class MaxBetClient:
    BASE_URL = "https://www.maxbet.rs/restapi/offer/sr"

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.maxbet.rs/",
            "Origin": "https://www.maxbet.rs",
        })

        self.ttg_lang = None

    def get_ttg_lang(self):
        if self.ttg_lang is not None:
            return self.ttg_lang

        url = (
            f"{self.BASE_URL}/ttg_lang"
            "?mobileVersion=1.21.17&locale=sr"
        )

        r = self.session.get(
            url,
            timeout=20
        )

        r.raise_for_status()

        self.ttg_lang = r.json()

        return self.ttg_lang

    def get_event(self, event_id):
        url = f"{self.BASE_URL}/match/{event_id}"

        r = self.session.get(
            url,
            timeout=20
        )

        r.raise_for_status()

        return r.json()

    def get_market_dictionary(self):
        data = self.get_ttg_lang()

        return data.get(
            "betPickMap",
            {}
        )

    def get_odds_map(self, event_id):
        event = self.get_event(event_id)

        if not isinstance(event, dict):
            return {}

        # MaxBet u odgovoru može imati nekoliko nivoa.
        # Tražimo dict koji izgleda kao mapa:
        # {"1": 1.09, "2": 24.0, "50310": 1.45, ...}

        def find_odds(obj):
            if isinstance(obj, dict):
                numeric_pairs = {}

                for key, value in obj.items():
                    if (
                        isinstance(key, str)
                        and key.isdigit()
                        and isinstance(value, (int, float))
                    ):
                        numeric_pairs[key] = value

                if len(numeric_pairs) > 20:
                    return numeric_pairs

                for value in obj.values():
                    found = find_odds(value)

                    if found:
                        return found

            elif isinstance(obj, list):
                for item in obj:
                    found = find_odds(item)

                    if found:
                        return found

            return {}

        return find_odds(event)

    def describe_odd(self, bet_code):
        markets = self.get_market_dictionary()

        possible_keys = [
            f"{bet_code}_S",
            str(bet_code),
        ]

        for key in possible_keys:
            if key in markets:
                return markets[key]

        return None

    def get_all_odds(self, event_id):
        odds_map = self.get_odds_map(event_id)

        result = []

        for code, price in odds_map.items():
            info = self.describe_odd(code)

            result.append({
                "code": code,
                "price": price,
                "label": info.get("label") if info else None,
                "caption": info.get("caption") if info else None,
                "tipTypeName": info.get("tipTypeName") if info else None,
            })

        return result


if __name__ == "__main__":
    client = MaxBetClient()

    event_id = 24031896

    event = client.get_event(event_id)

    print("EVENT RESPONSE TYPE:", type(event).__name__)

    all_odds = client.get_all_odds(event_id)

    print("UKUPNO KVOTA:", len(all_odds))

    print("\nPRVIH 20:")

    for odd in all_odds[:20]:
        print(
            odd["code"],
            "->",
            odd["price"],
            "|",
            odd["caption"],
            "|",
            odd["label"]
        )