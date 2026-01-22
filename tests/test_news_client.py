import pytest
import re
import time
from unittest.mock import patch, MagicMock
from app.adapters.news_client import NewsClient


@pytest.mark.asyncio
async def test_fetch_news_google_success(httpx_mock):
    rss_content = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
    <channel>
        <title>Google News</title>
        <item>
            <title>FTSE 100 Rises</title>
            <pubDate>Wed, 21 Jan 2026 10:00:00 GMT</pubDate>
        </item>
    </channel>
    </rss>"""

    httpx_mock.add_response(
        method="GET",
        url="https://news.google.com/rss/search?q=FTSE%20100%20when%3A24h&hl=en-GB&gl=GB&ceid=GB:en",
        status_code=200,
        content=rss_content.encode("utf-8"),
    )

    client = NewsClient()
    summary = await client.fetch_news("FTSE 100", source="google")

    assert "FTSE 100 Rises" in summary


@pytest.mark.asyncio
async def test_fetch_news_yahoo_success():
    mock_feed = MagicMock()
    # Use a real struct_time object
    current_struct = time.gmtime()

    # Use a plain dict-like object to avoid MagicMock confusion in get()
    class Entry(dict):
        def __getattr__(self, name):
            return self.get(name)

    mock_entry = Entry(
        {
            "title": "S&P 500 Earnings",
            "published": "Recent",
            "published_parsed": current_struct,
        }
    )

    mock_feed.entries = [mock_entry]

    with patch("app.adapters.news_client.feedparser.parse", return_value=mock_feed):
        client = NewsClient()
        summary = await client.fetch_news("S&P 500", source="yahoo")

        assert "Yahoo Finance (^GSPC)" in summary
        assert "S&P 500 Earnings" in summary


@pytest.mark.asyncio
async def test_fetch_news_empty(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*google.*"),
        status_code=200,
        content=b"<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>",
    )

    with patch("app.adapters.news_client.feedparser.parse") as mock_parse:
        mock_parse.return_value.entries = []
        client = NewsClient()
        summary = await client.fetch_news("Unknown")
        assert "No recent news found" in summary
