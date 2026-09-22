import requests
import json


class SuperbetClient:
    BASE_URL = (
        "https://production-superbet-offer-rs.freetls.fastly.net"
        "/sb-rs/api/v3/subscription/sr-Latn-RS/events"
    )

    def get_event(self, event_id):
        url = f"{self.BASE_URL}?events={event_id}"

        r = requests.get(
            url,
            stream=True,
            timeout=(10, 30)
        )

        r.raise_for_status()

        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue

            if line.startswith("data:"):
                data = json.loads(line[5:])

                if data:
                    return data[0]

        return None

    def get_markets(self, event_id):
        event = self.get_event(event_id)

        if not event:
            return []

        return event.get("markets", [])

    def find_markets(self, event, search_text):
        search_text = search_text.lower()

        return [
            market
            for market in event.get("markets", [])
            if search_text in market.get("name", "").lower()
        ]

    def find_market_exact(self, event, market_name):
        market_name = market_name.lower()

        for market in event.get("markets", []):
            if market.get("name", "").lower() == market_name:
                return market

        return None

    def market_odds(self, market):
        result = []

        for odd in market.get("odds", []):
            if odd.get("status") != 1:
                continue

            if not odd.get("display", True):
                continue

            result.append({
                "name": odd.get("metadata", {}).get("name"),
                "price": odd.get("price"),
                "info": odd.get("metadata", {}).get("info"),
            })

        return result


if __name__ == "__main__":
    client = SuperbetClient()

    event_id = 14738949

    event = client.get_event(event_id)

    print("EVENT:", event["fixture"]["event_name"])
    print("UKUPNO MARKETA:", len(event.get("markets", [])))

    print("\nDNB:")

    market = client.find_market_exact(
        event,
        "Winner DNB"
    )

    if market:
        for odd in client.market_odds(market):
            print(
                odd["name"],
                "->",
                odd["price"]
            )