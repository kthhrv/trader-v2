import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import reflex as rx
import plotly.graph_objects as go
import pandas as pd
import redis.asyncio as redis
from dotenv import load_dotenv

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

# Load environment variables
load_dotenv(project_root / ".env")

# fmt: off
from app.services.scorecard import ScorecardService  # noqa: E402
from app.database.queries import get_recent_signals_with_executions, delete_signal_record, get_trade_candles  # noqa: E402
from app.core.markets import MARKET_CONFIGS  # noqa: E402
from app.core.config import settings  # noqa: E402
# fmt: on


class State(rx.State):
    """The app state."""

    # Metrics
    net_pnl_str: str = "£0.00"
    win_rate_str: str = "0.0%"
    profit_factor_str: str = "0.00"
    expectancy_str: str = "£0.00"
    pnl_color: str = "gray"

    # Bot Status
    bot_status: str = "Checking..."
    bot_status_color: str = "gray"
    last_heartbeat: str = ""

    # Tables
    activity_log: List[Dict[str, Any]] = []
    market_stats: List[Dict[str, Any]] = []
    funnel_data: List[Dict[str, Any]] = []

    # Selection & Details
    selected_trade: Dict[str, Any] = {}
    has_selection: bool = False

    # Confirmation Dialog
    confirmation_open: bool = False
    item_to_delete: int = 0

    # Raw Candle Data (Serializable)
    raw_candles: List[Dict[str, Any]] = []

    is_loading: bool = False

    @rx.var
    def chart_figure(self) -> go.Figure:
        """Computed var to build the Plotly figure from raw candle data."""
        if not self.raw_candles or not self.has_selection:
            # Return a blank figure to avoid errors
            return go.Figure()

        item = self.selected_trade

        try:
            df = pd.DataFrame(self.raw_candles)
            if df.empty:
                return go.Figure()

            df["timestamp"] = pd.to_datetime(df["timestamp"])
            # Ensure numeric columns
            for col in ["open", "high", "low", "close"]:
                df[col] = df[col].astype(float)

            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)

            # --- Indicators ---
            # SMA 10
            df["sma_10"] = df["close"].rolling(window=10).mean()

            # Bollinger Bands (20, 2)
            sma_20 = df["close"].rolling(window=20).mean()
            std_20 = df["close"].rolling(window=20).std()
            upper_bb = sma_20 + (std_20 * 2)
            lower_bb = sma_20 - (std_20 * 2)

            # ATR (14) - 1.5x Bands
            upper_atr = None
            lower_atr = None
            try:
                df.ta.atr(length=14, append=True)
                atr_col = [c for c in df.columns if "ATR" in c]
                if atr_col:
                    atr = df[atr_col[0]]
                    upper_atr = sma_20 + (atr * 1.5)
                    lower_atr = sma_20 - (atr * 1.5)
            except Exception as e:
                print(f"ATR Calc error: {e}")

            # --- Plotting ---
            fig = go.Figure(
                data=[
                    go.Candlestick(
                        x=df.index,
                        open=df["open"],
                        high=df["high"],
                        low=df["low"],
                        close=df["close"],
                        name=item["market"],
                    )
                ]
            )

            # Add Trend (SMA 10)
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["sma_10"],
                    mode="lines",
                    name="Trend (SMA 10)",
                    line=dict(color="yellow", width=1.5),
                )
            )

            # Add BB
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=upper_bb,
                    line=dict(color="rgba(255, 255, 255, 0.3)", width=1, dash="dash"),
                    name="Upper BB",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=lower_bb,
                    line=dict(color="rgba(255, 255, 255, 0.3)", width=1, dash="dash"),
                    fill="tonexty",
                    fillcolor="rgba(255, 255, 255, 0.05)",
                    name="Lower BB",
                )
            )

            # Add ATR
            if upper_atr is not None:
                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=upper_atr,
                        line=dict(color="cyan", width=1, dash="dot"),
                        name="Upper ATR (1.5x)",
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=lower_atr,
                        line=dict(color="cyan", width=1, dash="dot"),
                        name="Lower ATR (1.5x)",
                    )
                )

            # --- Horizontal Lines (Entry, SL) ---
            entry_price = item.get("fill_price")
            sl_price = item.get("sl")

            if entry_price:
                fig.add_hline(
                    y=entry_price,
                    line_dash="dash",
                    line_color="green",
                    annotation_text="Entry",
                )

            if sl_price:
                fig.add_hline(
                    y=sl_price,
                    line_dash="dot",
                    line_color="darkorange",
                    annotation_text="Init SL",
                )

            # Trailing Stop Trigger (1.5R)
            if entry_price and sl_price:
                risk = abs(entry_price - sl_price)
                direction = item.get("dir")  # "BUY" or "SELL"
                trigger_price = 0
                if direction == "BUY":
                    trigger_price = entry_price + (1.5 * risk)
                elif direction == "SELL":
                    trigger_price = entry_price - (1.5 * risk)

                if trigger_price > 0:
                    fig.add_hline(
                        y=trigger_price,
                        line_dash="dot",
                        line_color="cyan",
                        annotation_text="Trail (1.5R)",
                    )

            # --- Markers for Entry/Exit Time ---
            fill_time = item.get("fill_time")
            if fill_time:
                ft_dt = datetime.fromisoformat(fill_time)
                fig.add_vline(x=ft_dt, line_dash="dot", line_color="green")

            exit_time = item.get("exit_time")
            if exit_time:
                et_dt = datetime.fromisoformat(exit_time)
                fig.add_vline(x=et_dt, line_dash="dot", line_color="red")

            # Add Entry Marker (Triangle)
            if fill_time and entry_price:
                fig.add_trace(
                    go.Scatter(
                        x=[datetime.fromisoformat(fill_time)],
                        y=[entry_price],
                        mode="markers",
                        marker=dict(
                            symbol="triangle-up"
                            if item.get("dir") == "BUY"
                            else "triangle-down",
                            size=12,
                            color="blue",
                        ),
                        name="Entry Marker",
                    )
                )

            # Add Exit Marker (X)
            if exit_time and item.get("exit_price"):
                fig.add_trace(
                    go.Scatter(
                        x=[datetime.fromisoformat(exit_time)],
                        y=[item["exit_price"]],
                        mode="markers",
                        marker=dict(symbol="x", size=12, color="orange"),
                        name="Exit Marker",
                    )
                )

            fig.update_layout(
                template="plotly_dark",
                height=400,
                margin=dict(l=20, r=20, t=20, b=100),
                xaxis_rangeslider_visible=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.2,
                    xanchor="center",
                    x=0.5,
                ),
            )
            return fig

        except Exception as e:
            print(f"Error building graph: {e}")
            return go.Figure()

    async def check_heartbeat(self):
        """Checks the Redis heartbeat key for bot status."""
        try:
            r = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            content = await r.get("health:app:last_seen")
            await r.aclose()

            if content:
                last_hb = datetime.fromisoformat(content)
                # Normalize to aware UTC if naive
                if not last_hb.tzinfo:
                    last_hb = last_hb.replace(tzinfo=timezone.utc)

                now = datetime.now(timezone.utc)
                self.last_heartbeat = last_hb.strftime("%H:%M:%S")

                if (now - last_hb).total_seconds() < 120:
                    self.bot_status = "ONLINE"
                    self.bot_status_color = "green"
                else:
                    self.bot_status = "OFFLINE"
                    self.bot_status_color = "red"
            else:
                self.bot_status = "NO SIGNAL"
                self.bot_status_color = "gray"
        except Exception as e:
            print(f"Heartbeat check failed: {e}")
            self.bot_status = "ERROR"
            self.bot_status_color = "red"

    async def load_data(self):
        self.is_loading = True

        # Update Heartbeat
        await self.check_heartbeat()

        stats = await ScorecardService.get_scorecard_data()
        if stats:
            pnl = stats.get("net_pnl", 0.0)
            self.net_pnl_str = f"£{pnl:,.2f}"
            self.pnl_color = "green" if pnl >= 0 else "red"
            self.win_rate_str = f"{stats.get('win_rate', 0.0):.1f}%"
            pf = stats.get("profit_factor", 0.0)
            self.profit_factor_str = "∞" if pf == float("inf") else f"{pf:.2f}"
            self.expectancy_str = f"£{stats.get('expectancy', 0.0):.2f}"

            # Process Market Stats for UI
            raw_market_stats = stats.get("market_stats", [])
            processed_market_stats = []
            for m in raw_market_stats:
                m_copy = m.copy()
                m_copy["Net_PnL_Str"] = f"£{m['Net_PnL']:,.2f}"
                m_copy["Win_Rate_Str"] = f"{m['Win_Rate']:.1f}%"
                m_copy["Net_PnL_Color"] = (
                    "green"
                    if m["Net_PnL"] > 0
                    else ("red" if m["Net_PnL"] < 0 else "gray")
                )
                processed_market_stats.append(m_copy)
            self.market_stats = processed_market_stats

            self.funnel_data = [
                {
                    "name": "Sessions",
                    "value": stats.get("total_sessions", 0),
                    "fill": "#8884d8",
                },
                {
                    "name": "AI Waits",
                    "value": stats.get("ai_waits", 0),
                    "fill": "#83a6ed",
                },
                {
                    "name": "Rejects/Skip",
                    "value": stats.get("rejected", 0),
                    "fill": "#8dd1e1",
                },
                {
                    "name": "Executed",
                    "value": stats.get("total_trades", 0),
                    "fill": "#82ca9d",
                },
            ]

        raw_activity = await get_recent_signals_with_executions(limit=50)
        processed_log = []
        for signal, execution in raw_activity:
            market = signal.symbol
            decimals = 2 if any(x in market for x in ["SPX", "US500", "SPTRD"]) else 1

            item = {
                "id": signal.id,
                "market": market,
                "strategy": signal.strategy_name,
                "confidence": signal.confidence,
                "reasoning": signal.reasoning,
                "symbol": market,
                "signal_time": signal.timestamp.isoformat(),
            }

            if execution:
                item.update(
                    {
                        "time": execution.fill_time.strftime("%Y-%m-%d %H:%M"),
                        "dir": execution.direction,
                        "entry": f"{execution.fill_price:.{decimals}f}",
                        "exit": f"{execution.exit_price:.{decimals}f}"
                        if execution.exit_price
                        else "Active",
                        "pnl": f"£{execution.pnl or 0.0:.2f}",
                        "status": execution.outcome_status,
                        "fill_time": execution.fill_time.isoformat(),
                        "exit_time": execution.exit_time.isoformat()
                        if execution.exit_time
                        else None,
                        "fill_price": execution.fill_price,
                        "exit_price": execution.exit_price,
                        "sl": execution.initial_stop_loss,
                    }
                )
            else:
                item.update(
                    {
                        "time": signal.timestamp.strftime("%Y-%m-%d %H:%M"),
                        "dir": signal.signal_decision
                        if signal.signal_decision != "WAIT"
                        else "-",
                        "entry": f"{signal.entry_price:.{decimals}f}"
                        if signal.entry_price
                        else "-",
                        "exit": "-",
                        "pnl": "£0.00",
                        "status": "WAIT"
                        if signal.signal_decision == "WAIT"
                        else "SKIPPED",
                        "fill_time": signal.timestamp.isoformat(),
                        "fill_price": signal.entry_price,
                        "exit_time": None,
                        "exit_price": None,
                    }
                )
            processed_log.append(item)

        self.activity_log = processed_log
        self.is_loading = False

    async def select_trade(self, item: Any):
        """Sets the selected trade and fetches candle data."""
        self.selected_trade = item
        self.has_selection = True

        # Fetch Candle Data
        symbol = item["market"]
        fill_time_str = item.get("fill_time") or item.get("signal_time")
        if not fill_time_str:
            self.raw_candles = []
            return

        start_t = datetime.fromisoformat(fill_time_str) - timedelta(minutes=30)

        exit_time_str = item.get("exit_time")
        if exit_time_str:
            end_t = datetime.fromisoformat(exit_time_str) + timedelta(minutes=30)
        else:
            end_t = datetime.fromisoformat(fill_time_str) + timedelta(minutes=60)

        candles = await get_trade_candles(symbol, start_t, end_t)

        # Store candles as simple dicts
        self.raw_candles = [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
            }
            for c in candles
        ]

    def set_has_selection(self, val: bool):
        self.has_selection = val

    def set_confirmation_open(self, val: bool):
        self.confirmation_open = val

    def ask_delete(self, id: Any):
        """Opens confirmation dialog."""
        self.item_to_delete = id
        self.confirmation_open = True

    def cancel_delete(self):
        """Closes confirmation dialog."""
        self.confirmation_open = False

    async def confirm_delete(self):
        """Performs deletion."""
        await delete_signal_record(self.item_to_delete)
        if self.selected_trade.get("id") == self.item_to_delete:
            self.has_selection = False
        self.confirmation_open = False
        await self.load_data()


def metric_card(
    title: str, value: str, subtext: Optional[str] = None, color: str = "blue"
):
    return rx.card(
        rx.vstack(
            rx.text(title, font_size="sm", color="gray.400"),
            rx.text(value, font_size="2xl", font_weight="bold"),
            rx.cond(subtext, rx.text(subtext, font_size="xs", color=f"{color}.400")),
            align_items="start",
            spacing="1",
        ),
        variant="surface",
        width="100%",
        background_color="rgba(30, 33, 48, 0.5)",
    )


def market_map():
    # Convert MARKET_CONFIGS dict to list for table
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Key"),
                rx.table.column_header_cell("Name"),
                rx.table.column_header_cell("Schedule"),
                rx.table.column_header_cell("Max Spread"),
            )
        ),
        rx.table.body(
            *[
                rx.table.row(
                    rx.table.cell(k),
                    rx.table.cell(v["name"]),
                    rx.table.cell(
                        f"{v['schedule']['hour']:02d}:{v['schedule']['minute']:02d}"
                    ),
                    rx.table.cell(str(v["max_spread"])),
                )
                for k, v in MARKET_CONFIGS.items()
            ]
        ),
        variant="surface",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            # Header
            rx.hstack(
                rx.heading("📈 Trader V2", size="6"),
                # Bot Status Badge
                rx.badge(
                    rx.hstack(
                        rx.icon("activity", size=16),
                        rx.text(State.bot_status),
                        rx.cond(
                            State.bot_status == "ONLINE",
                            rx.text(State.last_heartbeat, font_size="xs", opacity=0.7),
                        ),
                    ),
                    color_scheme=State.bot_status_color,
                    variant="surface",
                    size="3",
                    padding_x="3",
                ),
                rx.spacer(),
                rx.button("Refresh", on_click=State.load_data, variant="soft"),
                width="100%",
                padding_y="4",
                align_items="center",
                spacing="4",
            ),
            rx.grid(
                metric_card("Net PnL", State.net_pnl_str, color=State.pnl_color),
                metric_card("Win Rate", State.win_rate_str, "Target: 50%"),
                metric_card("Profit Factor", State.profit_factor_str, "Target: >1.5"),
                metric_card("Expectancy", State.expectancy_str, "Per Trade"),
                columns="4",
                spacing="4",
                width="100%",
            ),
            rx.divider(margin_y="6"),
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Performance", value="perf"),
                    rx.tabs.trigger("Activity Log", value="log"),
                    rx.tabs.trigger("Market Map", value="map"),
                ),
                rx.tabs.content(
                    rx.vstack(
                        rx.heading("Funnel Analysis", size="4", margin_top="4"),
                        rx.recharts.bar_chart(
                            rx.recharts.bar(
                                data_key="value",
                                stroke="#8884d8",
                                fill="#8884d8",
                                label=True,
                            ),
                            rx.recharts.x_axis(data_key="name"),
                            rx.recharts.y_axis(),
                            data=State.funnel_data,
                            height=300,
                            width="100%",
                        ),
                        rx.heading("Market League Table", size="4", margin_top="4"),
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("Market"),
                                    rx.table.column_header_cell("Trades"),
                                    rx.table.column_header_cell("Net PnL"),
                                    rx.table.column_header_cell("Win Rate"),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.market_stats,
                                    lambda item: rx.table.row(
                                        rx.table.cell(
                                            item["market"], font_weight="bold"
                                        ),
                                        rx.table.cell(item["Trades"]),
                                        rx.table.cell(
                                            item["Net_PnL_Str"],
                                            color=item["Net_PnL_Color"],
                                            font_weight="bold",
                                        ),
                                        rx.table.cell(item["Win_Rate_Str"]),
                                    ),
                                )
                            ),
                            variant="surface",
                            width="100%",
                        ),
                    ),
                    value="perf",
                ),
                rx.tabs.content(
                    rx.vstack(
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("Time"),
                                    rx.table.column_header_cell("Market"),
                                    rx.table.column_header_cell("Dir"),
                                    rx.table.column_header_cell("Entry"),
                                    rx.table.column_header_cell("PnL"),
                                    rx.table.column_header_cell("Status"),
                                    rx.table.column_header_cell("Actions"),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.activity_log,
                                    lambda item: rx.table.row(
                                        rx.table.cell(item["time"]),
                                        rx.table.cell(item["market"]),
                                        rx.table.cell(item["dir"]),
                                        rx.table.cell(item["entry"]),
                                        rx.table.cell(item["pnl"]),
                                        rx.table.cell(item["status"]),
                                        rx.table.cell(
                                            rx.hstack(
                                                rx.button(
                                                    "👁️",
                                                    on_click=lambda: State.select_trade(
                                                        item
                                                    ),  # type: ignore
                                                    variant="ghost",
                                                    size="1",
                                                ),
                                                rx.button(
                                                    "🗑️",
                                                    on_click=lambda: State.ask_delete(
                                                        item["id"]
                                                    ),  # type: ignore
                                                    variant="ghost",
                                                    color_scheme="ruby",
                                                    size="1",
                                                ),
                                            )
                                        ),
                                    ),
                                )
                            ),
                            width="100%",
                        ),
                        # Trade Details Modal
                        rx.dialog.root(
                            rx.dialog.content(
                                rx.dialog.title(
                                    f"🔎 Details: {State.selected_trade['market']}"
                                ),
                                rx.vstack(
                                    rx.text(
                                        f"Strategy: {State.selected_trade['strategy']}",
                                        font_weight="bold",
                                    ),
                                    rx.text(
                                        f"Confidence: {State.selected_trade['confidence']}"
                                    ),
                                    rx.text(f"PnL: {State.selected_trade['pnl']}"),
                                    rx.text(
                                        "AI Reasoning:",
                                        font_size="sm",
                                        color="gray.400",
                                    ),
                                    rx.scroll_area(
                                        rx.text(
                                            State.selected_trade["reasoning"],
                                            font_size="sm",
                                        ),
                                        height="200px",
                                        type="always",
                                        scrollbars="vertical",
                                        style={
                                            "background": "rgba(0,0,0,0.2)",
                                            "padding": "10px",
                                            "border_radius": "5px",
                                        },
                                    ),
                                    rx.divider(),
                                    rx.plotly(
                                        data=State.chart_figure,
                                        height="400px",
                                        width="100%",
                                    ),
                                    width="100%",
                                    spacing="4",
                                ),
                                rx.flex(
                                    rx.dialog.close(
                                        rx.button(
                                            "Close", variant="soft", color_scheme="gray"
                                        ),
                                    ),
                                    justify="end",
                                    margin_top="4",
                                ),
                                max_width="1000px",
                            ),
                            open=State.has_selection,
                            on_open_change=State.set_has_selection,
                        ),
                        # Delete Confirmation Alert
                        rx.alert_dialog.root(
                            rx.alert_dialog.content(
                                rx.alert_dialog.title("Confirm Deletion"),
                                rx.alert_dialog.description(
                                    "Are you sure you want to delete this record? This action cannot be undone."
                                ),
                                rx.flex(
                                    rx.alert_dialog.cancel(
                                        rx.button(
                                            "Cancel",
                                            on_click=State.cancel_delete,
                                            variant="soft",
                                            color_scheme="gray",
                                        ),
                                    ),
                                    rx.alert_dialog.action(
                                        rx.button(
                                            "Delete",
                                            on_click=State.confirm_delete,
                                            variant="solid",
                                            color_scheme="ruby",
                                        ),
                                    ),
                                    spacing="3",
                                    justify="end",
                                    margin_top="4",
                                ),
                            ),
                            open=State.confirmation_open,
                            on_open_change=State.set_confirmation_open,
                        ),
                        width="100%",
                    ),
                    value="log",
                ),
                rx.tabs.content(
                    rx.vstack(
                        rx.heading("Market Configuration", size="4", margin_top="4"),
                        market_map(),
                    ),
                    value="map",
                ),
                default_value="perf",
                width="100%",
            ),
            width="100%",
            max_width="1200px",
            padding="4",
        ),
        on_mount=State.load_data,
    )


app = rx.App(theme=rx.theme(appearance="dark", accent_color="blue", radius="large"))
app.add_page(index, title="Trader V2 Dashboard")
