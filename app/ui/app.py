import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import asyncio
import sys
from pathlib import Path

# Fix path to allow importing from root 'app'
# We are in /app/ui/app.py, so we need to go up 2 levels to get to root
root_path = Path(__file__).parent.parent.parent.absolute()
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from datetime import datetime, timedelta, timezone  # noqa: E402

# Import V2 logic
from app.services.scorecard import ScorecardService  # noqa: E402
from app.database.queries import get_recent_trades_joined, get_trade_candles  # noqa: E402
from app.core.markets import MARKET_CONFIGS  # noqa: E402


# Helpers for Async execution within Streamlit
def run_async(coro):
    return asyncio.run(coro)


st.set_page_config(
    page_title="Trader V2 Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- CSS Styling ---
st.markdown(
    """
    <style>
    .main {
        background-color: #0e1117;
    }
    .stMetric {
        background-color: #1e2130;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #3e4150;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Sidebar ---
st.sidebar.title("🛠️ Control Center")

# Heartbeat Check
heartbeat_path = Path("data/heartbeat.txt")
status_color = "🔴"
status_text = "OFFLINE"
if heartbeat_path.exists():
    mtime = datetime.fromtimestamp(heartbeat_path.stat().st_mtime)
    if (datetime.now() - mtime).total_seconds() < 120:
        status_color = "🟢"
        status_text = "RUNNING"

st.sidebar.markdown(f"**System Status:** {status_color} {status_text}")
if heartbeat_path.exists():
    st.sidebar.caption(f"Last Heartbeat: {mtime.strftime('%H:%M:%S')}")

st.sidebar.divider()

st.sidebar.subheader("Quick Actions")
if st.sidebar.button("Run FTSE Analysis", width="stretch"):
    st.sidebar.info("Starting FTSE manual run...")
    # This would ideally call a service or subprocess
    st.sidebar.warning("Action not yet connected to backend process.")

if st.sidebar.button("Refresh Dashboard", type="primary", width="stretch"):
    st.rerun()

# --- Main Dashboard ---
st.title("📈 Trader V2 Performance")

# Fetch Data
with st.spinner("Fetching analytics..."):
    stats = run_async(ScorecardService.get_scorecard_data())
    recent_trades = run_async(get_recent_trades_joined(limit=20))

if not stats:
    st.warning("No trading data found in database. Start trading to see statistics!")
    st.stop()

# --- Row 1: Metrics ---
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Net PnL", f"£{stats['net_pnl']:,.2f}")

with col2:
    wr = stats["win_rate"]
    st.metric("Win Rate", f"{wr:.1f}%", delta=f"{wr - 50:.1f}%" if wr > 0 else None)

with col3:
    pf = stats["profit_factor"]
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    st.metric("Profit Factor", pf_str)

with col4:
    st.metric("Expectancy", f"£{stats['expectancy']:.2f}")

st.divider()

# --- Row 2: Charts & League Table ---
tab1, tab2, tab3 = st.tabs(["📊 Performance", "🕒 Trades", "🗺️ Market Map"])

with tab1:
    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("The Funnel")
        funnel_data = {
            "Stage": ["Sessions", "AI Waits", "Rejects/Skip", "Executed"],
            "Count": [
                stats["total_sessions"],
                stats["ai_waits"],
                stats["rejected"],
                stats["total_trades"],
            ],
        }
        fig = px.funnel(
            funnel_data, x="Count", y="Stage", color_discrete_sequence=["#636EFA"]
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")

    with c2:
        st.subheader("Market League Table")
        if stats["market_stats"]:
            m_df = pd.DataFrame(stats["market_stats"])
            m_df.columns = ["Market", "Trades", "Net PnL", "Win Rate %"]
            st.dataframe(
                m_df.style.background_gradient(subset=["Net PnL"], cmap="RdYlGn"),
                width="stretch",
                hide_index=True,
            )
        else:
            st.write("No market breakdown available.")

with tab2:
    st.subheader("Trade History")
    st.caption("Select a row to view analysis and chart.")

    if recent_trades:
        trade_list = []
        for execution, signal in recent_trades:
            market = signal.symbol if signal else "UNKNOWN"
            decimals = (
                2 if "SPTRD" in market or "SPX" in market or "US500" in market else 1
            )

            exit_val = execution.exit_price
            exit_str = f"{exit_val:.{decimals}f}" if exit_val else "Active"

            trade_list.append(
                {
                    "Time": execution.fill_time.strftime("%Y-%m-%d %H:%M"),
                    "Market": market,
                    "Dir": "⬆️ BUY" if execution.direction == "BUY" else "⬇️ SELL",
                    "Entry": f"{execution.fill_price:.{decimals}f}",
                    "Exit": exit_str,
                    "PnL": execution.pnl or 0.0,
                    "Status": execution.outcome_status,
                    "Strategy": signal.strategy_name if signal else "MANUAL",
                }
            )

        t_df = pd.DataFrame(trade_list)

        # Interactive Table
        event = st.dataframe(
            t_df.style.map(
                lambda x: "color: #00ff00"
                if x == "WIN"
                else ("color: #ff4b4b" if x == "LOSS" else ""),
                subset=["Status"],
            ).format({"PnL": "£{:.2f}"}),
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )

        # Handle Selection
        if event.selection.rows:
            idx = event.selection.rows[0]
            execution, signal = recent_trades[idx]

            st.divider()
            st.markdown(f"### 🔎 Trade Analysis: {execution.deal_id}")

            c1, c2 = st.columns([1, 2])

            with c1:
                st.markdown(
                    f"**Strategy:** {signal.strategy_name if signal else 'MANUAL'}"
                )
                st.markdown(f"**Confidence:** {signal.confidence if signal else 'N/A'}")
                pnl_val = execution.pnl if execution.pnl is not None else 0.0
                st.markdown(f"**PnL:** £{pnl_val:.2f}")

                if signal:
                    with st.expander("AI Reasoning", expanded=True):
                        st.write(signal.reasoning)

            with c2:
                # Fetch Candles
                if signal and signal.symbol:
                    # Window: Entry - 30m to Exit + 30m
                    start_t = execution.fill_time - timedelta(minutes=30)
                    end_t = (
                        execution.exit_time or datetime.now(timezone.utc)
                    ) + timedelta(minutes=30)

                    with st.spinner("Loading Chart..."):
                        candles = run_async(
                            get_trade_candles(signal.symbol, start_t, end_t)
                        )

                    if candles:
                        df_c = pd.DataFrame([c.model_dump() for c in candles])

                        fig = go.Figure(
                            data=[
                                go.Candlestick(
                                    x=df_c["timestamp"],
                                    open=df_c["open"],
                                    high=df_c["high"],
                                    low=df_c["low"],
                                    close=df_c["close"],
                                    name="Price",
                                )
                            ]
                        )

                        # Add Markers
                        fig.add_trace(
                            go.Scatter(
                                x=[execution.fill_time],
                                y=[execution.fill_price],
                                mode="markers",
                                marker=dict(
                                    symbol="triangle-up"
                                    if execution.direction == "BUY"
                                    else "triangle-down",
                                    size=12,
                                    color="blue",
                                ),
                                name="Entry",
                            )
                        )

                        if execution.exit_time and execution.exit_price:
                            fig.add_trace(
                                go.Scatter(
                                    x=[execution.exit_time],
                                    y=[execution.exit_price],
                                    mode="markers",
                                    marker=dict(symbol="x", size=12, color="orange"),
                                    name="Exit",
                                )
                            )

                        # Stop Loss Line (approximate)
                        fig.add_shape(
                            type="line",
                            x0=execution.fill_time,
                            y0=execution.initial_stop_loss,
                            x1=execution.exit_time or end_t,
                            y1=execution.initial_stop_loss,
                            line=dict(color="red", width=2, dash="dash"),
                            name="Initial Stop",
                        )
                        # To hide from legend but keep hover, we use add_trace(go.Scatter(mode='lines'...)) instead of add_shape if we want a legend item.
                        # Wait, add_shape does NOT appear in the legend by default.
                        # If the user sees it in the key, I must have added it as a trace or they are referring to the markers.

                        # Let's check my code. I used `fig.add_shape`. Shapes don't show in the legend.
                        # Perhaps I should add a dummy trace if I WANT it in the legend, or maybe the user sees 'Entry' / 'Exit' / 'Price'.

                        # "SL is include in the key on charts" -> User wants it REMOVED from the key? Or included?
                        # "SL is include in the key on charts" sounds like a statement of fact that might be unwanted?
                        # Or maybe a request "SL is NOT included in the key..."?

                        # Given "SL is include in the key on charts" usually means "It shouldn't be there", or "It is there".
                        # If I look at the previous code:
                        # fig.add_shape(..., name="Initial Stop") -> 'name' property on shape is for hover, not legend.

                        # BUT, maybe I want to make it a trace so it IS in the legend? Or the user implies it IS there and wants it gone?
                        # Since shapes don't appear in the legend, maybe I misunderstood the current state.

                        # Let's assume the user WANTS it in the legend because shapes are invisible in the legend.
                        # To put it in the legend, I must use `add_trace(go.Scatter(...))`.

                        # Let's replace add_shape with add_trace to make it visible in the legend and hoverable.

                        fig.add_trace(
                            go.Scatter(
                                x=[execution.fill_time, execution.exit_time or end_t],
                                y=[
                                    execution.initial_stop_loss,
                                    execution.initial_stop_loss,
                                ],
                                mode="lines",
                                line=dict(color="red", width=2, dash="dash"),
                                name="Initial Stop",
                            )
                        )

                        fig.update_layout(
                            height=500,
                            margin=dict(l=0, r=0, t=30, b=0),
                            xaxis_rangeslider_visible=False,
                        )
                        st.plotly_chart(fig, width="stretch")
                    else:
                        st.warning(
                            f"No candle data found for {signal.symbol} in this period."
                        )
                else:
                    st.warning("Missing symbol info.")

    else:
        st.write("No trades recorded yet.")

with tab3:
    st.subheader("Market Configuration")
    markets = []
    for k, v in MARKET_CONFIGS.items():
        markets.append(
            {
                "Key": k,
                "Name": v["name"],
                "EPIC": v["epic"],
                "Schedule": f"{v['schedule']['hour']:02d}:{v['schedule']['minute']:02d}",
                "Max Spread": v["max_spread"],
            }
        )
    st.table(markets)

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
