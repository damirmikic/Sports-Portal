import os
import requests
from dotenv import load_dotenv


class MeridianClient:
    BASE_URL = "https://online.meridianbet.com/betshop/api/v2"
    AUTH_URL = "https://auth.meridianbet.com/oauth/token"

    def __init__(self):
        load_dotenv()

        self.access_token = None

        self.refresh_token = os.getenv(
            "MERIDIAN_REFRESH_TOKEN"
        )

        self.basic_auth = os.getenv(
            "MERIDIAN_BASIC_AUTH"
        )

        self.fingerprint = os.getenv(
            "MERIDIAN_FINGERPRINT"
        )

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "sr",
            "Origin": "https://meridianbet.rs",
            "Referer": "https://meridianbet.rs/",
        })

    def save_refresh_token(self):
        env_path = ".env"

        if not os.path.exists(env_path):
            return

        with open(
            env_path,
            "r",
            encoding="utf-8"
        ) as f:
            lines = f.readlines()

        found = False
        new_lines = []

        for line in lines:
            if line.startswith(
                "MERIDIAN_REFRESH_TOKEN="
            ):
                new_lines.append(
                    "MERIDIAN_REFRESH_TOKEN="
                    + self.refresh_token
                    + "\n"
                )
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(
                "MERIDIAN_REFRESH_TOKEN="
                + self.refresh_token
                + "\n"
            )

        with open(
            env_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.writelines(new_lines)

    def refresh(self):
        headers = {
            "Authorization": self.basic_auth,
            "X-Device-Fingerprint": self.fingerprint,
            "Origin": "https://meridianbet.rs",
            "Referer": "https://meridianbet.rs/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": (
                "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7"
            ),
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "locale": "sr",
        }

        r = requests.post(
            self.AUTH_URL,
            headers=headers,
            data=data,
            timeout=20
        )

        if r.status_code != 200:
            print(
                "MERIDIAN REFRESH GREŠKA:",
                r.status_code
            )
            return False

        j = r.json()

        self.access_token = j.get(
            "access_token"
        )

        new_refresh_token = j.get(
            "refresh_token"
        )

        if new_refresh_token:
            self.refresh_token = (
                new_refresh_token
            )

            self.save_refresh_token()

        return bool(self.access_token)

    def _auth_headers(self):
        if not self.access_token:
            if not self.refresh():
                raise RuntimeError(
                    "Meridian login nije uspeo."
                )

        return {
            "Authorization": (
                "Bearer "
                + self.access_token
            ),
            "X-Device-Fingerprint": (
                self.fingerprint
            ),
        }

    def get_event(self, event_id):
        url = (
            f"{self.BASE_URL}/events/"
            f"{event_id}"
        )

        r = self.session.get(
            url,
            headers=self._auth_headers(),
            timeout=20
        )

        if r.status_code == 401:
            self.access_token = None

            if not self.refresh():
                r.raise_for_status()

            r = self.session.get(
                url,
                headers=self._auth_headers(),
                timeout=20
            )

        r.raise_for_status()

        data = r.json()

        if isinstance(data, dict):
            return data.get(
                "payload",
                data
            )

        return data

    def get_all_markets(self, event_id):
        url = (
            f"{self.BASE_URL}/events/"
            f"{event_id}/markets"
        )

        params = {
            "gameGroupId": "all"
        }

        r = self.session.get(
            url,
            params=params,
            headers=self._auth_headers(),
            timeout=20
        )

        if r.status_code == 401:
            self.access_token = None

            if not self.refresh():
                r.raise_for_status()

            r = self.session.get(
                url,
                params=params,
                headers=self._auth_headers(),
                timeout=20
            )

        r.raise_for_status()

        data = r.json()

        if isinstance(data, dict):
            return data.get(
                "payload",
                []
            )

        return data

    def find_market(
        self,
        event_id,
        market_name
    ):
        markets = self.get_all_markets(
            event_id
        )

        market_name = market_name.lower()

        result = []

        for item in markets:
            name = str(
                item.get(
                    "marketName",
                    ""
                )
            ).lower()

            if market_name in name:
                result.append(item)

        return result


if __name__ == "__main__":
    client = MeridianClient()

    event_id = 19574718

    event = client.get_event(
        event_id
    )

    print(
        "EVENT:",
        event.get(
            "header",
            {}
        )
    )

    markets = client.get_all_markets(
        event_id
    )

    print(
        "UKUPNO MARKET STAVKI:",
        len(markets)
    )

    print("\nDNB:")

    dnb = client.find_market(
        event_id,
        "Draw no bet"
    )

    for item in dnb:
        for market in item.get(
            "markets",
            []
        ):
            for selection in market.get(
                "selections",
                []
            ):
                if selection.get(
                    "state"
                ) == "ACTIVE":
                    print(
                        selection.get("name"),
                        "->",
                        selection.get("price")
                    )