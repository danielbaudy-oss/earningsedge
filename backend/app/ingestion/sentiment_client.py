"""News API and Reddit API clients for sentiment analysis."""

import httpx
from datetime import date, timedelta
from app.core.config import get_settings

settings = get_settings()


class NewsAPIClient:
    """Client for NewsAPI.org."""

    BASE_URL = "https://newsapi.org/v2"

    def __init__(self):
        self.api_key = settings.news_api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_stock_news(
        self, ticker: str, company_name: str, days_back: int = 7
    ) -> list:
        """Get recent news articles about a stock."""
        from_date = (date.today() - timedelta(days=days_back)).isoformat()
        query = f'"{ticker}" OR "{company_name}"'
        url = f"{self.BASE_URL}/everything"
        params = {
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": 50,
            "apiKey": self.api_key,
        }
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json().get("articles", [])

    async def close(self):
        await self.client.aclose()


class RedditClient:
    """Client for Reddit API (via OAuth). Optional — works without credentials."""

    AUTH_URL = "https://www.reddit.com/api/v1/access_token"
    BASE_URL = "https://oauth.reddit.com"

    def __init__(self):
        self.client_id = settings.reddit_client_id
        self.client_secret = settings.reddit_client_secret
        self.enabled = bool(self.client_id and self.client_secret)
        self.client = httpx.AsyncClient(timeout=30.0)
        self.token = None

    async def _authenticate(self):
        """Get OAuth token from Reddit."""
        auth = (self.client_id, self.client_secret)
        data = {"grant_type": "client_credentials"}
        headers = {"User-Agent": "EarningsEdge/1.0"}
        resp = await self.client.post(
            self.AUTH_URL, auth=auth, data=data, headers=headers
        )
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    async def get_stock_mentions(
        self, ticker: str, subreddits: list[str] = None
    ) -> list:
        """Search Reddit for stock mentions. Returns empty if not configured."""
        if not self.enabled:
            return []

        if not self.token:
            await self._authenticate()

        if subreddits is None:
            subreddits = ["wallstreetbets", "stocks", "investing", "options"]

        all_posts = []
        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "EarningsEdge/1.0",
        }

        for subreddit in subreddits:
            url = f"{self.BASE_URL}/r/{subreddit}/search"
            params = {
                "q": f"${ticker}",
                "sort": "new",
                "t": "week",
                "limit": 25,
            }
            resp = await self.client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                posts = resp.json().get("data", {}).get("children", [])
                all_posts.extend([p["data"] for p in posts])

        return all_posts

    async def close(self):
        await self.client.aclose()
