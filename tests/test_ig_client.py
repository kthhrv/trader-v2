import pytest
from app.adapters.ig_client import AsyncIGClient, IGAuthenticationError


@pytest.mark.asyncio
async def test_ig_client_authentication_success(httpx_mock):
    # Mock the login response
    httpx_mock.add_response(
        method="POST",
        url="https://demo-api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "fake_cst", "X-SECURITY-TOKEN": "fake_x_security_token"},
        json={"currentAccountId": "D12345", "accountType": "SPREADBET"},
    )

    client = AsyncIGClient()
    await client.authenticate(env_type="DEMO")

    assert "DEMO" in client.auth_tokens
    assert client.auth_tokens["DEMO"]["CST"] == "fake_cst"
    assert client.auth_tokens["DEMO"]["X-SECURITY-TOKEN"] == "fake_x_security_token"

    # Verify session headers were updated
    session = await client._get_session("DEMO")
    assert session.headers["CST"] == "fake_cst"
    assert session.headers["X-SECURITY-TOKEN"] == "fake_x_security_token"

    await client.close()


@pytest.mark.asyncio
async def test_ig_client_authentication_failure(httpx_mock):
    # Mock a failed login
    httpx_mock.add_response(
        method="POST",
        url="https://demo-api.ig.com/gateway/deal/session",
        status_code=401,
        json={"errorCode": "error.security.client-token-invalid"},
    )

    client = AsyncIGClient()
    with pytest.raises(IGAuthenticationError):
        await client.authenticate(env_type="DEMO")

    await client.close()


@pytest.mark.asyncio
async def test_fetch_prices_calls_correct_env(httpx_mock):
    # 1. Mock Auth for LIVE
    httpx_mock.add_response(
        method="POST",
        url="https://api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "live_cst", "X-SECURITY-TOKEN": "live_token"},
        json={"currentAccountId": "L12345", "accountType": "SPREADBET"},
    )

    # 2. Mock Prices call
    httpx_mock.add_response(
        method="GET",
        url="https://api.ig.com/gateway/deal/prices/IX.D.NASDAQ.IFD.IP/MIN/10",
        status_code=200,
        json={
            "prices": [
                {"snapshotTime": "2023-01-01T10:00:00", "openPrice": {"bid": 12000}}
            ]
        },
    )

    client = AsyncIGClient()
    prices = await client.fetch_historical_prices(
        epic="IX.D.NASDAQ.IFD.IP", resolution="MIN", num_points=10, env_type="LIVE"
    )

    assert len(prices["prices"]) == 1
    assert prices["prices"][0]["openPrice"]["bid"] == 12000
    await client.close()


@pytest.mark.asyncio
async def test_activity_window_survives_account_timezone_and_pins_page_size(
    httpx_mock,
):
    """2026-07-22: IG reads the v3 activity endpoint's from/to in the ACCOUNT's
    timezone, not UTC (documented behaviour — `GET /session` supplies
    `timezoneOffset` for exactly this). Naive UTC strings put the upper bound
    an hour in the past whenever the account offset is non-zero, hiding the
    most recent hour.

    Latent since this code was written; it began biting live between 07-08 and
    07-21 when the account offset stopped being 0. Measured impact on this
    (live) arm: `_sync_outcome` retries only ~30s against a ~1h blind window,
    so every close since 2026-07-13 was left `outcome_status='OPEN'` with NULL
    pnl/exit — 0 successful syncs in 7 days of logs.

    Pad both bounds past any real-world offset (max +14:00) rather than
    compensate for a specific one; the caller joins client-side on
    affectedDealId. pageSize goes in with it: this call never pinned one, so it
    sat on IG's v3 default of 50, and a padded window measured 65 rows on the
    sibling account the same day.
    """
    import re
    from datetime import datetime, timedelta, timezone

    httpx_mock.add_response(
        method="POST",
        url="https://demo-api.ig.com/gateway/deal/session",
        status_code=200,
        headers={"CST": "cst", "X-SECURITY-TOKEN": "xst"},
        json={"currentAccountId": "D12345", "accountType": "SPREADBET"},
    )
    client = AsyncIGClient()
    await client.authenticate(env_type="DEMO")

    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*/history/activity.*"),
        status_code=200,
        json={"activities": []},
    )

    # Bracket the call: the client stamps its own `now` in between, so each
    # bound is compared against the end of the bracket that holds for ANY call
    # duration (strftime drops sub-second remainder from `to`; elapsed time
    # walks `frm`).
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    await client.fetch_activity_history(max_span_seconds=3600, env_type="DEMO")
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    [request] = httpx_mock.get_requests(url=re.compile(r".*/history/activity.*"))
    fmt = "%Y-%m-%dT%H:%M:%S"
    frm = datetime.strptime(request.url.params["from"], fmt)
    to = datetime.strptime(request.url.params["to"], fmt)
    truncation = timedelta(seconds=1)

    assert to >= before + timedelta(hours=14) - truncation
    assert frm <= after - timedelta(seconds=3600) - timedelta(hours=14)
    assert request.url.params["pageSize"] == "500"

    await client.close()
