import asyncio
import json
from pathlib import Path
from typing import List
import redis.asyncio as redis

from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.adapters.notification import HomeAssistantNotifier
from app.core.markets import MARKET_CONFIGS
from app.streamer.candle_builder import CandleBuilder

# Backoff constants
INITIAL_BACKOFF_S = 10
MAX_BACKOFF_S = 300  # 5 minutes cap


class StreamManager:
    """
    Manages the 24/7 IG Lightstreamer connection via Node.js sidecar.
    Aggregates candles and publishes ticks to Redis.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.ig_client = AsyncIGClient.get_instance()
        self.script_path = (
            Path(__file__).parent.parent.parent
            / "app"
            / "adapters"
            / "js"
            / "stream_service.js"
        )
        self.candle_builder = CandleBuilder()
        self._notifier = HomeAssistantNotifier()
        self._alerted_cap: set[str] = set()
        self._processes: List[asyncio.subprocess.Process] = []

    async def start(self):
        """
        Main loop: Authenticates, starts Node process, reads stream.
        """
        while True:
            try:
                await self._run_session()
            except asyncio.CancelledError:
                logger.info("StreamManager stopping...")
                await self._stop_processes()
                break
            except Exception as e:
                logger.error(f"StreamManager crashed: {e}. Restarting in 5s...")
                await self._stop_processes()
                await asyncio.sleep(5)

    async def _ensure_authenticated(self, env: str) -> dict:
        """Authenticate if not already. Returns cached tokens."""
        await self.ig_client.authenticate(env)
        tokens = self.ig_client.auth_tokens.get(env)
        if not tokens:
            raise Exception("Authentication failed (No tokens)")
        return tokens

    async def _force_reauth(self, env: str) -> dict:
        """Invalidate cached tokens and re-authenticate."""
        if env in self.ig_client.auth_tokens:
            del self.ig_client.auth_tokens[env]
        logger.info(f"Forcing re-authentication for {env}...")
        return await self._ensure_authenticated(env)

    async def _run_session(self):
        env = settings.DATA_ACCOUNT_ENV
        logger.info(f"StreamManager authenticating with {env}...")

        await self._ensure_authenticated(env)

        epics = [config["epic"] for config in MARKET_CONFIGS.values()]
        logger.info(
            f"Subscribing to {len(epics)} markets: {','.join(epics)}"
        )

        tasks = []
        for epic in epics:
            tasks.append(self._stream_market(epic, env))

        await asyncio.gather(*tasks)

    async def _stream_market(self, epic: str, env: str):
        """
        Manages a single Node process for one market with exponential backoff retries.
        Re-authenticates only after consecutive fast failures (likely stale tokens).
        Backoff resets after a process runs successfully for > 60s.
        """
        backoff = INITIAL_BACKOFF_S
        consecutive_fast_failures = 0

        while True:
            start_time = asyncio.get_event_loop().time()
            try:
                # Re-auth after 3 consecutive fast failures (likely stale tokens)
                if consecutive_fast_failures >= 3:
                    tokens = await self._force_reauth(env)
                    consecutive_fast_failures = 0
                else:
                    tokens = await self._ensure_authenticated(env)
                await self._run_market_process(epic, tokens, env)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in stream task for {epic}: {e}")

            # Reset backoff if the process ran for a meaningful duration
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > 60:
                backoff = INITIAL_BACKOFF_S
                consecutive_fast_failures = 0
                self._alerted_cap.discard(epic)
            else:
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                consecutive_fast_failures += 1

                if backoff >= MAX_BACKOFF_S and epic not in self._alerted_cap:
                    self._alerted_cap.add(epic)
                    await self._notifier.send_notification(
                        title="Streamer: Max Backoff Reached",
                        message=f"{epic} has failed repeatedly and hit the {MAX_BACKOFF_S}s backoff cap. Possible IG outage.",
                        priority="high",
                    )

            logger.info(f"Restarting stream for {epic} in {backoff}s...")
            await asyncio.sleep(backoff)

    async def _run_market_process(self, epic: str, tokens: dict, env: str):
        cst = tokens["CST"]
        xst = tokens["X-SECURITY-TOKEN"]

        creds = (
            settings._get_live_credentials()
            if env == "LIVE"
            else settings._get_demo_credentials()
        )
        account_id = creds["acc_id"]
        base_url = (
            "https://apd.marketdatasystems.com"
            if env == "LIVE"
            else "https://demo-apd.marketdatasystems.com"
        )

        cmd = ["node", str(self.script_path), cst, xst, account_id, epic, base_url]

        logger.info(f"Spawning stream for {epic}...")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.script_path.parent),
        )
        self._processes.append(process)

        # Start stderr reader task
        async def log_stderr(stderr):
            while True:
                line = await stderr.readline()
                if not line:
                    break
                logger.error(f"[Node Error {epic}] {line.decode().strip()}")

        stderr_task = asyncio.create_task(log_stderr(process.stderr))

        async def read_stdout(stdout):
            while True:
                line = await stdout.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                if not line_str:
                    continue
                await self._process_stream_line(line_str, epic)

        stdout_task = asyncio.create_task(read_stdout(process.stdout))

        try:
            return_code = await process.wait()
            logger.warning(f"Node process for {epic} exited with code {return_code}")
        finally:
            stderr_task.cancel()
            stdout_task.cancel()
            try:
                process.terminate()
            except Exception:
                pass
            if process in self._processes:
                self._processes.remove(process)

    async def _process_stream_line(self, line_str: str, epic: str):
        if "[NODE_STREAM_INFO]" in line_str:
            return
        try:
            data = json.loads(line_str)
            if data.get("type") == "price_update":
                bid = float(data.get("bid", 0))
                offer = float(data.get("offer", 0))

                # Sanity Check: Filter out unrealistic values (e.g. overflow/sentinels)
                # Max reasonable price for indices/forex is < 1,000,000
                # Min reasonable price is > 0
                if not (0 < bid < 1_000_000) or not (0 < offer < 1_000_000):
                    logger.warning(
                        f"Ignored insane price for {epic}: Bid={bid}, Offer={offer}"
                    )
                    return

                await self.redis.publish("market_data", json.dumps(data))
                if data.get("bid"):
                    await self.candle_builder.on_tick(epic, bid)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Failed to parse stream line: {e}")

    async def _stop_processes(self):
        for process in self._processes:
            try:
                process.terminate()
            except Exception:
                pass
        self._processes.clear()
