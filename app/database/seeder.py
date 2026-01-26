import asyncio
import random
from datetime import datetime, timedelta, timezone
from app.database.session import async_session_maker, init_db
from app.database.models import TradeSignal, TradeExecution, HistoricalCandle
from app.core.markets import MARKET_CONFIGS


async def seed_data():
    print("Initializing Database...")
    await init_db()

    print("Generating Sample Data...")
    async with async_session_maker() as session:
        # Clear existing data? Maybe not, let's append.

        markets = list(MARKET_CONFIGS.keys())
        strategies = ["Market Open", "Mean Reversion", "Trend Following", "Breakout"]
        outcomes = ["WIN", "LOSS", "BREAKEVEN"]

        start_time = datetime.now(timezone.utc) - timedelta(days=7)

        for i in range(50):
            market_key = random.choice(markets)
            config = MARKET_CONFIGS[market_key]
            strategy = random.choice(strategies)

            # Time progression
            trade_time = start_time + timedelta(hours=i * 3 + random.randint(0, 2))

            # Price simulation
            base_price = (
                7000
                if "ftse" in market_key
                else (15000 if "dax" in market_key else 4000)
            )
            entry = base_price + random.uniform(-50, 50)
            direction = random.choice(["BUY", "SELL"])

            # Signal
            signal = TradeSignal(
                timestamp=trade_time,
                symbol=config["epic"],
                strategy_name=strategy,
                signal_decision=direction,
                confidence=random.choice(["HIGH", "MEDIUM"]),
                reasoning=f"Sample AI analysis for {market_key}. {random.choice(['Bullish divergence detected.', 'Resistance breakout imminent.', 'Oversold RSI condition.'])}",
                entry_price=entry,
                stop_loss=entry - 20 if direction == "BUY" else entry + 20,
                take_profit=entry + 40 if direction == "BUY" else entry - 40,
                position_size=1.0,
                atr_at_generation=15.0,
            )
            session.add(signal)
            await session.flush()  # get signal.id

            # Execution (80% chance of execution)
            if random.random() < 0.8:
                outcome = random.choice(outcomes)
                pnl = 0.0
                exit_price = entry

                if outcome == "WIN":
                    pnl = random.uniform(50, 150)
                    exit_price = entry + 30 if direction == "BUY" else entry - 30
                elif outcome == "LOSS":
                    pnl = random.uniform(-50, -20)
                    exit_price = entry - 15 if direction == "BUY" else entry + 15

                execution = TradeExecution(
                    signal_id=signal.id,
                    deal_id=f"DEAL_{int(trade_time.timestamp())}_{i}",
                    direction=direction,
                    fill_price=entry,
                    fill_time=trade_time + timedelta(minutes=1),
                    size=1.0,
                    initial_stop_loss=signal.stop_loss,
                    current_stop_loss=signal.stop_loss,
                    exit_price=exit_price,
                    exit_time=trade_time + timedelta(minutes=random.randint(15, 120)),
                    pnl=pnl,
                    outcome_status=outcome,
                )
                session.add(execution)
                await session.flush()  # Ensure ID if needed

                # Generate Synthetic Candles for this trade
                # From 30 mins before entry to exit + 30 mins
                candle_start = trade_time - timedelta(minutes=30)
                assert execution.exit_time is not None
                candle_end = execution.exit_time + timedelta(minutes=30)

                curr_time = candle_start
                curr_price = entry  # Start simulation near entry

                while curr_time <= candle_end:
                    # Random walk
                    change = random.uniform(-5, 5)
                    curr_price += change

                    # Generate OHLC
                    open_p = curr_price
                    close_p = curr_price + random.uniform(-2, 2)
                    high_p = max(open_p, close_p) + random.uniform(0, 3)
                    low_p = min(open_p, close_p) - random.uniform(0, 3)

                    hc = HistoricalCandle(
                        symbol=config["epic"],
                        resolution="MINUTE",
                        timestamp=curr_time,
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=random.randint(50, 500),
                    )
                    session.add(hc)
                    curr_time += timedelta(minutes=1)

        await session.commit()
        print("Successfully seeded 50 sample trades.")


if __name__ == "__main__":
    asyncio.run(seed_data())
