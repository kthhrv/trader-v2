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
