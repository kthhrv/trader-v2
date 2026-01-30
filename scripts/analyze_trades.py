import asyncio
import argparse
import sys
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload
from sqlmodel import select
from dotenv import load_dotenv
import os

# Add project root
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))


async def analyze(env: str, limit: int):
    # Local import to avoid E402 while respecting sys.path update
    from app.database.models import TradeExecution

    # Load Config
    env_file = project_root / f".env.{env}"
    if not env_file.exists():
        print(f"Error: {env_file} not found.")
        return

    load_dotenv(env_file)

    # DB Config (Manual Override for Host Access)
    # Assumes we are running this ON the host or tunneling to it?
    # Actually, for local dev accessing remote DB, we usually need SSH tunnel or exposed port.
    # The previous scripts worked because they hardcoded 192.168.0.191.
    # Let's keep that pattern for now or respect env if set.

    user = os.getenv("POSTGRES_USER", "trader")
    password = os.getenv("POSTGRES_PASSWORD", "agnostic")
    host = os.getenv("POSTGRES_HOST", "192.168.0.191")  # Default to prod IP
    port = os.getenv("POSTGRES_PORT", "5432")

    # Map env to the actual DB names used on the host
    db_name = "trader_demo" if env == "demo" else "trader_live"

    db_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"

    print(f"Connecting to {db_url}...")

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore

    try:
        async with async_session() as session:
            stmt = (
                select(TradeExecution)
                .options(selectinload(TradeExecution.signal))  # type: ignore
                .order_by(TradeExecution.fill_time.desc())  # type: ignore
                .limit(limit)
            )
            result = await session.execute(stmt)
            executions = result.scalars().all()

            if executions:
                print(f"\n--- Trade History ({env.upper()} - Last {limit}) ---")
                print(
                    f"{'Time (UTC)':<20} | {'Symbol':<20} | {'Dir':<4} | {'PnL':<8} | {'Status'}"
                )
                print("-" * 75)
                for ex in executions:
                    ts = ex.fill_time.strftime("%Y-%m-%d %H:%M")
                    symbol = ex.signal.symbol if ex.signal else "Unknown"
                    pnl = f"{ex.pnl:.2f}" if ex.pnl is not None else "Open"

                    # Highlight Wins/Losses
                    status = ex.outcome_status

                    print(
                        f"{ts:<20} | {symbol:<20} | {ex.direction:<4} | {pnl:<8} | {status}"
                    )

                    if ex.signal:
                        # Wrap reasoning logic or just print start
                        reason = ex.signal.reasoning.replace("\n", " ")[:120]
                        print(f"  Reason: {reason}...")

                        # Show Trigger Source if available (New Feature!)
                        trigger = getattr(ex.signal, "trigger_source", "N/A")
                        print(f"  Source: {trigger}")

                    print("-" * 75)
            else:
                print(f"No trades found in {env} DB.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyze recent trades from the database."
    )
    parser.add_argument(
        "--env",
        type=str,
        default="demo",
        choices=["demo", "live"],
        help="Environment to query",
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of trades to show"
    )

    args = parser.parse_args()
    asyncio.run(analyze(args.env, args.limit))
