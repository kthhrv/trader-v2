import asyncio
import feedparser
import time
from typing import Optional, List
from urllib.parse import quote
import httpx

from app.core.logger import logger


class NewsClient:
    """
    Async News Fetcher using httpx for requests and feedparser for parsing.
    """

    def __init__(self):
        # Default English Settings
        self.default_base_url = (
            "https://news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en"
        )
        # Yahoo Finance RSS
        self.yahoo_base_url = "https://finance.yahoo.com/rss/headline?s={symbol}"

        # Locale Configurations for Native News
        self.locale_config = {
            "dax": {
                "base_url": "https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de",
                "native_query": "DAX 40 Wirtschaft",
            },
        }

    async def fetch_news(
        self,
        query: str,
        limit: int = 5,
        source: Optional[str] = None,
        market: Optional[str] = None,
    ) -> str:
        """
        Fetches top news headlines asynchronously.
        """
        news_summary = f"--- Top News Headlines for '{query}' ---\n"
        seen_titles = set()
        count = 0
        cutoff_time = time.time() - (24 * 3600)

        source = source.lower() if source else None

        async with httpx.AsyncClient(timeout=10.0) as client:
            fetch_tasks = []
            do_google = source is None or source == "google"
            do_yahoo = source is None or source == "yahoo"

            if do_google:
                fetch_tasks.append(
                    self._fetch_google(client, query, market, cutoff_time)
                )

            if do_yahoo:
                yahoo_symbol = self._get_yahoo_symbol(query)
                if yahoo_symbol:
                    fetch_tasks.append(
                        self._fetch_yahoo(client, yahoo_symbol, cutoff_time)
                    )

            results = await asyncio.gather(*fetch_tasks)

            # Map back to specific processors
            google_res = []
            yahoo_res = []

            res_idx = 0
            if do_google:
                if res_idx < len(results):
                    google_res = results[res_idx]
                    res_idx += 1

            if do_yahoo:
                yahoo_symbol = self._get_yahoo_symbol(query)
                if yahoo_symbol and res_idx < len(results):
                    yahoo_res = results[res_idx]

            # Aggregate Text
            if google_res:
                news_summary += "\nSource: Google News\n"
                for item in google_res:
                    if count >= limit:
                        break
                    if item["title"] not in seen_titles:
                        news_summary += f"{count + 1}. {item['prefix']}[{item['published']}] {item['title']}\n"
                        seen_titles.add(item["title"])
                        count += 1

            if yahoo_res:
                yahoo_symbol = self._get_yahoo_symbol(query)  # Re-get symbol for header
                if yahoo_symbol:
                    news_summary += f"\nSource: Yahoo Finance ({yahoo_symbol})\n"
                    for item in yahoo_res:
                        if count >= limit * 2:
                            break
                        if item["title"] not in seen_titles:
                            news_summary += (
                                f"{count + 1}. [{item['published']}] {item['title']}\n"
                            )
                            seen_titles.add(item["title"])
                            count += 1

        if count == 0:
            return "No recent news found (within last 24h)."

        return news_summary

    async def _fetch_google(
        self,
        client: httpx.AsyncClient,
        query: str,
        market: Optional[str],
        cutoff_time: float,
    ) -> List[dict]:
        results = []
        try:
            google_url_template = self.default_base_url
            search_query = query

            if market and market.lower() in self.locale_config:
                config = self.locale_config[market.lower()]
                google_url_template = config["base_url"]
                search_query = config["native_query"]
                logger.info(f"Switched to Native Query for {market}: '{search_query}'")

            full_query = f"{search_query} when:24h"
            url = google_url_template.format(query=quote(full_query))

            response = await client.get(url)
            response.raise_for_status()

            # Parsing RSS is CPU bound, run in thread
            feed = await asyncio.to_thread(feedparser.parse, response.content)

            if feed.entries:
                # Sort entries
                entries = sorted(
                    feed.entries,
                    key=lambda x: x.get("published_parsed") or 0,
                    reverse=True,
                )

                for entry in entries:
                    pub_struct = entry.get("published_parsed")
                    if pub_struct and time.mktime(pub_struct) < cutoff_time:
                        continue

                    prefix = (
                        "[Native] "
                        if market and market.lower() in self.locale_config
                        else ""
                    )
                    results.append(
                        {
                            "title": entry.title,
                            "published": entry.published
                            if "published" in entry
                            else "Unknown",
                            "prefix": prefix,
                        }
                    )

        except Exception as e:
            logger.error(f"Error fetching Google news: {e}")

        return results

    async def _fetch_yahoo(
        self, client: httpx.AsyncClient, symbol: str, cutoff_time: float
    ) -> List[dict]:
        results = []
        try:
            url = self.yahoo_base_url.format(symbol=symbol)
            # Use feedparser directly (in thread) as it handles Yahoo's quirks better than raw httpx
            feed = await asyncio.to_thread(feedparser.parse, url)

            if feed.entries:
                entries = sorted(
                    feed.entries,
                    key=lambda x: x.get("published_parsed") or 0,
                    reverse=True,
                )

                for entry in entries:
                    pub_struct = entry.get("published_parsed")
                    if pub_struct and time.mktime(pub_struct) < cutoff_time:
                        continue

                    results.append(
                        {
                            "title": entry.title,
                            "published": entry.published
                            if "published" in entry
                            else "Unknown",
                        }
                    )
        except Exception as e:
            logger.error(f"Error fetching Yahoo news: {e}")

        return results

    def _get_yahoo_symbol(self, query: str) -> Optional[str]:
        q = query.lower()
        if "ftse" in q:
            return "^FTSE"
        elif "s&p" in q or "spx" in q or "500" in q:
            return "^GSPC"
        elif "nikkei" in q or "japan" in q:
            return "^N225"
        elif "gbp" in q:
            return "GBPUSD=X"
        elif "eur" in q:
            return "EURUSD=X"
        elif "dax" in q:
            return "^GDAXI"
        elif "nasdaq" in q or "tech" in q:
            return "^NDX"
        elif "asx" in q or "australia" in q:
            return "^AXJO"
        return None
