import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.core.logger import logger
from app.adapters.ig_client import AsyncIGClient


class StreamerService:
    """
    Manages the Node.js sidecar for Lightstreamer connection.
    Yields real-time price and trade updates.
    """

    def __init__(self, ig_client: AsyncIGClient):
        self.ig_client = ig_client
        self.process: Optional[asyncio.subprocess.Process] = None
        self.script_path = (
            Path(__file__).parent.parent / "adapters" / "js" / "stream_service.js"
        )

    async def stream(self, epic: str) -> AsyncGenerator[dict, None]:
        """
        Starts the stream for a specific epic and yields updates.
        """
        if self.process:
            logger.warning("Stream already running. Restarting...")
            await self.stop()

        # 1. Get Tokens
        # We need to access the client's internal auth tokens.
        # Since AsyncIGClient manages sessions per env, we assume the relevant one (TRADING/DEMO) is active.
        env = settings.TRADING_ACCOUNT_ENV
        if env not in self.ig_client.auth_tokens:
            await self.ig_client.authenticate(env)

        tokens = self.ig_client.auth_tokens[env]
        cst = tokens["CST"]
        xst = tokens["X-SECURITY-TOKEN"]

        # Get Account ID from Settings (Client doesn't store it explicitly in auth_tokens dict yet)
        creds = (
            settings._get_live_credentials()
            if env == "LIVE"
            else settings._get_demo_credentials()
        )
        account_id = creds["acc_id"]

        # 2. Spawn Node Process
        cmd = [
            "node",
            str(self.script_path),
            cst,
            xst,
            account_id,
            epic,
            "https://apd.marketdatasystems.com"
            if env == "LIVE"
            else "https://demo-apd.marketdatasystems.com",
        ]

        logger.info(f"Starting Streamer: {' '.join(cmd)}")

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.script_path.parent),  # Run in JS dir for node_modules
        )

        # 3. Read Loop
        try:
            if self.process.stdout:
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break

                    line_str = line.decode().strip()

                    if not line_str:
                        continue

                    # Log Node Info/Errors
                    if "[NODE_STREAM_INFO]" in line_str:
                        logger.info(f"[Streamer] {line_str}")
                        continue
                    if "[NODE_STREAM_ERROR]" in line_str:
                        logger.error(f"[Streamer] {line_str}")
                        continue

                    # Parse JSON Data
                    try:
                        data = json.loads(line_str)
                        yield data
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            logger.info("Streamer cancelled.")
        finally:
            await self.stop()

    async def stop(self):
        """
        Terminates the subprocess.
        """
        if self.process:
            logger.info("Stopping Streamer...")
            try:
                self.process.terminate()
                await self.process.wait()
            except ProcessLookupError:
                pass
            self.process = None
