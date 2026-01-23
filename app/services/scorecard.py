import pandas as pd
from typing import Optional, Dict
from app.database.queries import get_all_trades, get_all_signals


class ScorecardService:
    @staticmethod
    async def get_scorecard_data() -> Optional[Dict]:
        """
        Calculates performance metrics and returns them as a dictionary.
        """
        signals = await get_all_signals()
        trades = await get_all_trades()

        if not signals:
            return None

        # --- 1. The Funnel ---
        total_sessions = len(signals)
        ai_waits = sum(1 for s in signals if s.signal_decision == "WAIT")

        # In V2, we don't strictly record "REJECTED_SAFETY" in the DB yet,
        # but we can infer executed vs total.
        # Executed Count
        executed_ids = {t[0].signal_id for t in trades if t[0].signal_id is not None}
        total_trades = len(trades)

        # Inferred Rejects (BUY/SELL signals that have no execution)
        rejected = sum(
            1
            for s in signals
            if s.signal_decision in ["BUY", "SELL"] and s.id not in executed_ids
        )

        stats = {
            "total_sessions": total_sessions,
            "ai_waits": ai_waits,
            "rejected": rejected,
            "total_trades": total_trades,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "market_stats": [],
            "conf_stats": [],
        }

        if not trades:
            return stats

        # Build DataFrame for Performance Stats
        records = []
        for execution, signal in trades:
            # Fallback for manual trades
            symbol = signal.symbol if signal else "UNKNOWN"
            strategy = signal.strategy_name if signal else "MANUAL"
            conf = signal.confidence if signal else "N/A"

            records.append(
                {
                    "pnl": execution.pnl or 0.0,
                    "outcome": execution.outcome_status,
                    "market": symbol,
                    "confidence": conf,
                    "strategy": strategy,
                }
            )

        df = pd.DataFrame(records)

        # Only closed trades matter for PnL
        closed_df = df[df["outcome"].isin(["WIN", "LOSS", "BREAKEVEN"])].copy()

        if not closed_df.empty:
            wins = closed_df[closed_df["pnl"] > 0]
            losses = closed_df[closed_df["pnl"] <= 0]

            stats["net_pnl"] = closed_df["pnl"].sum()
            stats["win_rate"] = len(wins) / len(closed_df) * 100

            gross_win = wins["pnl"].sum()
            gross_loss = abs(losses["pnl"].sum())
            stats["profit_factor"] = (
                gross_win / gross_loss if gross_loss > 0 else float("inf")
            )

            avg_win = wins["pnl"].mean() if not wins.empty else 0
            avg_loss = losses["pnl"].mean() if not losses.empty else 0
            stats["expectancy"] = (len(wins) / len(closed_df) * avg_win) + (
                len(losses) / len(closed_df) * avg_loss
            )

            # Market Breakdown
            m_stats = (
                closed_df.groupby("market")
                .agg(
                    Trades=("pnl", "count"),
                    Net_PnL=("pnl", "sum"),
                    Win_Rate=("pnl", lambda x: (x > 0).mean() * 100),
                )
                .sort_values(by="Net_PnL", ascending=False)
                .reset_index()
            )
            stats["market_stats"] = m_stats.to_dict("records")

            # AI Confidence Audit
            closed_df["confidence"] = closed_df["confidence"].astype(str).str.upper()
            c_stats = (
                closed_df.groupby("confidence")
                .agg(
                    Trades=("pnl", "count"),
                    Win_Rate=("pnl", lambda x: (x > 0).mean() * 100),
                    Avg_PnL=("pnl", "mean"),
                )
                .reset_index()
            )
            stats["conf_stats"] = c_stats.to_dict("records")

        return stats

    @staticmethod
    def generate_report(stats: Optional[Dict]):
        """
        Prints the beautiful ASCII scorecard.
        """
        if not stats:
            print("No data available.")
            return

        GREEN = "\033[92m"
        RED = "\033[91m"
        BLUE = "\033[94m"
        YELLOW = "\033[93m"
        RESET = "\033[0m"
        BOLD = "\033[1m"

        def color_pnl(val):
            if val > 0:
                return f"{GREEN}£{val:+.2f}{RESET}"
            if val < 0:
                return f"{RED}£{val:+.2f}{RESET}"
            return f"£{val:.2f}"

        print(f"\n{BOLD}{'=' * 60}")
        print(f"{'TRADER V2 SCORECARD':^60}")
        print(f"{'=' * 60}{RESET}")

        # --- 1. The Funnel ---
        print(f"\n{BLUE}[ THE FUNNEL ]{RESET}")
        ts = stats["total_sessions"]
        if ts > 0:
            print(f"Total Sessions:      {ts}")
            print(
                f"  > AI Waits:        {stats['ai_waits']} ({stats['ai_waits'] / ts * 100:.1f}%)"
            )
            print(
                f"  > Rejected/Skip:   {stats['rejected']} ({stats['rejected'] / ts * 100:.1f}%)"
            )
            print(
                f"Total Trades Taken:  {stats['total_trades']} (Conv: {stats['total_trades'] / ts * 100:.1f}%)"
            )
        else:
            print("No sessions recorded.")

        # --- 2. Performance ---
        print(f"\n{BLUE}[ PERFORMANCE ]{RESET}")
        print(f"Net PnL:             {color_pnl(stats['net_pnl'])}")

        wr_color = GREEN if stats["win_rate"] > 50 else RED
        print(f"Win Rate:            {wr_color}{stats['win_rate']:.1f}%{RESET}")

        pf_color = (
            GREEN
            if stats["profit_factor"] > 1.5
            else (YELLOW if stats["profit_factor"] > 1.0 else RED)
        )
        pf_str = (
            "Inf"
            if stats["profit_factor"] == float("inf")
            else f"{stats['profit_factor']:.2f}"
        )
        print(f"Profit Factor:       {pf_color}{pf_str}{RESET}")
        print(f"Expectancy:          {color_pnl(stats['expectancy'])} per trade")

        # --- 3. Market Breakdown ---
        if stats["market_stats"]:
            print(f"\n{BLUE}[ MARKET LEAGUE TABLE ]{RESET}")
            # Manual ASCII Table for beauty
            print(f"{'Market':<15} | {'Trades':<6} | {'Win Rate':<8} | {'Net PnL':<10}")
            print("-" * 48)
            for row in stats["market_stats"]:
                wr = f"{row['Win_Rate']:.1f}%"
                pnl = color_pnl(row["Net_PnL"])
                print(f"{row['market']:<15} | {row['Trades']:<6} | {wr:<8} | {pnl:<10}")

        # --- 4. Confidence Audit ---
        if stats["conf_stats"]:
            print(f"\n{BLUE}[ AI CONFIDENCE AUDIT ]{RESET}")
            print(
                f"{'Confidence':<12} | {'Trades':<6} | {'Win Rate':<8} | {'Avg PnL':<10}"
            )
            print("-" * 48)
            for row in stats["conf_stats"]:
                wr = f"{row['Win_Rate']:.1f}%"
                pnl = color_pnl(row["Avg_PnL"])
                print(
                    f"{row['confidence']:<12} | {row['Trades']:<6} | {wr:<8} | {pnl:<10}"
                )

        print(f"\n{BOLD}{'=' * 60}{RESET}\n")
