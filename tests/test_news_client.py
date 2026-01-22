import pytest
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
        <item>
            <title>Old News</title>
            <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
        </item>
    </channel>
    </rss>"""

    httpx_mock.add_response(
        url="https://news.google.com/rss/search?q=FTSE%20100%20when%3A24h&hl=en-GB&gl=GB&ceid=GB:en",
        status_code=200,
        content=rss_content.encode("utf-8"),
    )

    client = NewsClient()
    summary = await client.fetch_news("FTSE 100", source="google")

    assert "FTSE 100 Rises" in summary
    assert "Old News" not in summary  # Should be filtered by 24h cutoff


@pytest.mark.asyncio
async def test_fetch_news_yahoo_success(httpx_mock):
    rss_content = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
    <channel>
        <item>
            <title>S&amp;P 500 Earnings</title>
            <pubDate>Wed, 21 Jan 2026 12:00:00 GMT</pubDate>
        </item>
    </channel>
    </rss>"""

    # Check mapping logic: "S&P 500" -> "^GSPC"
    httpx_mock.add_response(
        url="https://finance.yahoo.com/rss/headline?s=%5EGSPC",
        status_code=200,
        content=rss_content.encode("utf-8"),
    )

    client = NewsClient()
    summary = await client.fetch_news("S&P 500", source="yahoo")

    assert "Yahoo Finance (^GSPC)" in summary
    assert "S&P 500 Earnings" in summary


@pytest.mark.asyncio
async def test_fetch_news_empty(httpx_mock):
    httpx_mock.add_response(status_code=200, content=b"")

    client = NewsClient()
    summary = await client.fetch_news("Unknown")
    assert "No recent news found" in summary
