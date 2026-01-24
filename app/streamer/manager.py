import asyncio
import json
from pathlib import Path
from typing import Optional
import redis.asyncio as redis

from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient
from app.core.markets import MARKET_CONFIGS
from app.streamer.candle_builder import CandleBuilder


class StreamManager:
    """
    Manages the 24/7 IG Lightstreamer connection via Node.js sidecar.
    Aggregates candles and publishes ticks to Redis.
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.ig_client = AsyncIGClient.get_instance()
        self.process: Optional[asyncio.subprocess.Process] = None
        self.script_path = (
            Path(__file__).parent.parent.parent
            / "app"
            / "adapters"
            / "js"
            / "stream_service.js"
        )
        self.candle_builder = CandleBuilder()

    async def start(self):
        """
        Main loop: Authenticates, starts Node process, reads stream.
        """
        while True:
            try:
                await self._run_session()
            except asyncio.CancelledError:
                logger.info("StreamManager stopping...")
                await self._stop_process()
                break
            except Exception as e:
                logger.error(f"StreamManager crashed: {e}. Restarting in 5s...")
                await self._stop_process()
                await asyncio.sleep(5)

    async def _run_session(self):
        # 1. Authenticate (Get Tokens)
        env = (
            settings.DATA_ACCOUNT_ENV
        )  # Use the dedicated Data account (Live preferred)
        logger.info(f"StreamManager authenticating with {env}...")

        await self.ig_client.authenticate(env)
        tokens = self.ig_client.auth_tokens.get(env)
        if not tokens:
            raise Exception("Authentication failed (No tokens)")

        # 2. Prepare Epics
        epics = [config["epic"] for config in MARKET_CONFIGS.values()]
        epics_str = ",".join(epics)
        logger.info(f"Subscribing to {len(epics)} markets: {epics_str}")

        # 3. Spawn Node Process
        # Note: The JS script takes a single epic usually. We might need to update the JS script
        # to handle multiple epics OR spawn multiple processes.
        # Checking streamer.py: It passes ONE epic to the command.
        # "node stream_service.js CST XST ACCOUNT EPIC URL"

        # CRITICAL: The current JS script only supports ONE epic per process.
        # To support 6 markets, we either:
        # A) Modify JS to accept a list.
        # B) Spawn 6 Node processes (Heavy).
        # C) Update JS to subscribe to multiple items (Lightstreamer supports this).

        # For Phase 1, I will implement a loop that spawns a process PER market.
        # This is inefficient but safest without rewriting the JS adapter immediately.
        # WAIT: 'market-streamer' is a single service. Running 6 subprocesses is fine.

        tasks = []
        for epic in epics:
            tasks.append(self._stream_market(epic, tokens, env))

        await asyncio.gather(*tasks)

    async def _stream_market(self, epic: str, tokens: dict, env: str):
        """
        Manages a single Node process for one market with automatic retries.
        """
        while True:
            try:
                await self._run_market_process(epic, tokens, env)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in stream task for {epic}: {e}")

            logger.info(f"Restarting stream for {epic} in 10s...")
            await asyncio.sleep(10)

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
                if "[NODE_STREAM_INFO]" in line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    if data.get("type") == "price_update":
                        await self.redis.publish("market_data", json.dumps(data))
                        if data.get("bid"):
                            await self.candle_builder.on_tick(epic, float(data["bid"]))
                except json.JSONDecodeError:
                    pass

        stdout_task = asyncio.create_task(read_stdout(process.stdout))

        # Await either task or the process itself
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

    async def _stop_process(self):
        # Todo: Kill all subprocesses
        pass
