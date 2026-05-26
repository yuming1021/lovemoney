import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, timedelta


# ==========================================
# 基本設定
# ==========================================
st.set_page_config(layout="wide", page_title="AI 股票智慧系統", page_icon="📈")

tz_tw = timezone(timedelta(hours=8))


def get_tw_time():
    return datetime.now(tz_tw).strftime("%H:%M:%S")


def get_tw_datetime():
    return datetime.now(tz_tw)


def is_tw_market_open(now=None):
    """判斷台股一般盤中時間：週一到週五 09:00～13:30。"""
    now = now or get_tw_datetime()

    if now.weekday() >= 5:
        return False, "目前為週末，非台股一般盤中時間。"

    market_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now.replace(hour=13, minute=30, second=0, microsecond=0)

    if now < market_start:
        return False, "目前尚未開盤，全市場自動監控暫停。"

    if now > market_end:
        return False, "目前已收盤，全市場自動監控暫停。"

    return True, "目前為台股一般盤中時間。"


def browser_auto_refresh(seconds, key):
    """
    非阻塞式自動刷新：不用 while True、time.sleep。
    這樣 Streamlit Cloud 與手機版不會被卡住，側邊欄模式也能正常切換。
    """
    seconds = int(seconds)
    components.html(
        f"""
        <script>
            const timer_{key} = setTimeout(function() {{
                window.parent.location.reload();
            }}, {seconds * 1000});
        </script>
        """,
        height=0,
    )


# ==========================================
# 0. 網頁切換：支援 /?code=2330 深度分析跳轉
# ==========================================
MODE_OPTIONS = [
    "🤖 全市場自動監控推薦",
    "🔍 個股自主搜尋分析",
]

if "app_mode" not in st.session_state or st.session_state.app_mode not in MODE_OPTIONS:
    st.session_state.app_mode = "🤖 全市場自動監控推薦"

query_params = st.query_params
url_code = query_params.get("code")

if url_code:
    st.session_state.app_mode = "🔍 個股自主搜尋分析"
    st.session_state.jump_to_code = str(url_code)
    st.query_params.clear()
    st.rerun()


# ==========================================
# 核心功能一：動態獲取真實市場名單
# ==========================================
@st.cache_data(ttl=3600)
def get_real_market_symbols():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    fallback = [
        {"code": "2330", "name": "台積電", "yahoo_symbol": "2330.TW", "display_name": "2330 台積電", "volume_shares": 10000000},
        {"code": "2317", "name": "鴻海", "yahoo_symbol": "2317.TW", "display_name": "2317 鴻海", "volume_shares": 10000000},
        {"code": "0050", "name": "元大台灣50", "yahoo_symbol": "0050.TW", "display_name": "0050 元大台灣50", "volume_shares": 10000000},
    ]

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)

        if res.status_code != 200:
            return fallback

        data = res.json()
        stocks_pool = []

        for item in data:
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()

            # 台股普通股與 ETF 都保留
            if (len(code) == 4 and code.isdigit()) or code.startswith("00"):
                vol_str = str(item.get("TradeVolume", "0")).replace(",", "")
                volume_shares = int(vol_str) if vol_str.isdigit() else 0

                stocks_pool.append({
                    "code": code,
                    "name": name,
                    "yahoo_symbol": f"{code}.TW",
                    "display_name": f"{code} {name}",
                    "volume_shares": volume_shares
                })

        return stocks_pool if stocks_pool else fallback

    except Exception:
        return fallback


all_market_stocks = get_real_market_symbols()


def find_stock_by_code(code):
    code = str(code)
    return next((s for s in all_market_stocks if s["code"] == code), None)


def get_prediction_short(star_count):
    if star_count >= 4:
        return "🔥 飆股成型"
    if star_count == 3:
        return "📈 趨勢轉強"
    if star_count == 2:
        return "➖ 震盪打底"
    if star_count == 1:
        return "📉 格局偏弱"
    return "🚨 極度弱勢"


def get_ai_prediction_text(star_count):
    if star_count == 5:
        return (
            "🔥 **型態走勢：極度看漲 (Strong Buy)**\n\n"
            "技術面完整，均線呈現強勢多頭排列，且伴隨量能支撐。"
            "短線動能偏強，但仍要避免追在乖離過大的位置。"
        )
    if star_count == 4:
        return (
            "🚀 **型態走勢：穩健看漲 (Buy)**\n\n"
            "趨勢明顯轉強，長短天期均線提供支撐。"
            "若回測不破月線，仍屬偏多架構。"
        )
    if star_count == 3:
        return (
            "📈 **型態走勢：溫和偏多 (Accumulate)**\n\n"
            "已站上關鍵支撐，但動能尚未完全爆發。"
            "可觀察是否帶量突破前高，或回測均線是否有守。"
        )
    if star_count == 2:
        return (
            "➖ **型態走勢：中性盤整 (Hold)**\n\n"
            "多空勢均力敵，正處於區間震盪階段。"
            "建議等待帶量突破或跌破後再判斷方向。"
        )
    if star_count == 1:
        return (
            "📉 **型態走勢：轉弱疑慮 (Underperform)**\n\n"
            "價格結構偏弱，均線支撐不足。"
            "短線可能仍有回檔壓力，建議降低追價風險。"
        )
    return (
        "🚨 **型態走勢：極度弱勢 (Strong Sell)**\n\n"
        "空頭格局明顯，賣壓偏重。"
        "若沒有重新站回關鍵均線，建議先避開。"
    )


def prepare_chart_data(df_raw):
    """補上均線、量均線與成交量張數。"""
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    df = df_raw.copy().dropna(how="all")

    if len(df) < 50:
        return pd.DataFrame()

    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA10"] = df["Close"].rolling(window=10).mean()
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA50"] = df["Close"].rolling(window=50).mean()
    df["Vol_MA5"] = df["Volume"].rolling(window=5).mean()
    df["Volume_K"] = df["Volume"] / 1000

    return df


def calc_stock_metrics(df_chart):
    """依照你原本的邏輯計算星評、月線進場價、停損價。"""
    if df_chart is None or df_chart.empty or len(df_chart) < 50:
        return None

    current_price = float(df_chart["Close"].iloc[-1])
    today_open = float(df_chart["Open"].iloc[-1])
    today_vol = float(df_chart["Volume"].iloc[-1])

    ma5 = float(df_chart["MA5"].iloc[-1])
    ma10 = float(df_chart["MA10"].iloc[-1])
    ma20 = float(df_chart["MA20"].iloc[-1])
    ma50 = float(df_chart["MA50"].iloc[-1])
    vol_ma5 = float(df_chart["Vol_MA5"].iloc[-1])

    if pd.isna(current_price) or pd.isna(ma20) or pd.isna(ma50) or today_open == 0:
        return None

    price_change = ((current_price - today_open) / today_open) * 100
    bias_ratio = ((current_price - ma20) / ma20) * 100
    actual_volume = int(today_vol / 1000)

    star_count = 0
    if current_price > ma20:
        star_count += 1
    if ma20 > ma50:
        star_count += 1
    if ma5 > ma10:
        star_count += 1
    if current_price > today_open and today_vol > vol_ma5:
        star_count += 1
    if 0 < bias_ratio < 8.0:
        star_count += 1

    return {
        "current_price": current_price,
        "today_open": today_open,
        "actual_volume": actual_volume,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma50": ma50,
        "vol_ma5": vol_ma5,
        "price_change": price_change,
        "bias_ratio": bias_ratio,
        "star_count": star_count,
        "safe_entry": ma20 * 0.99,
        "stop_loss": ma20 * 0.95,
        "prediction_short": get_prediction_short(star_count),
        "prediction_text": get_ai_prediction_text(star_count)
    }


# ==========================================
# 共用個股分析畫面：原本分析功能保留
# ==========================================
def render_single_stock_analysis(selected_stock_info):
    st.write("---")
    st.subheader(
        f"📊 【{selected_stock_info['code']} {selected_stock_info['name']}】 "
        f"量價與綜合評鑑"
    )

    try:
        ticker = yf.Ticker(selected_stock_info["yahoo_symbol"])
        df_raw = ticker.history(period="6mo")
        df_chart = prepare_chart_data(df_raw)

        if df_chart.empty:
            st.error("此標的目前無足夠歷史交易數據可供分析。")
            return

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.75, 0.25]
        )

        fig.add_trace(
            go.Candlestick(
                x=df_chart.index,
                open=df_chart["Open"],
                high=df_chart["High"],
                low=df_chart["Low"],
                close=df_chart["Close"],
                name="日K線",
                increasing_line_color="red",
                increasing_fillcolor="red",
                decreasing_line_color="green",
                decreasing_fillcolor="green"
            ),
            row=1,
            col=1
        )

        fig.add_trace(
            go.Scatter(x=df_chart.index, y=df_chart["MA5"], mode="lines", name="5日線", line=dict(color="pink", width=1.5)),
            row=1,
            col=1
        )
        fig.add_trace(
            go.Scatter(x=df_chart.index, y=df_chart["MA10"], mode="lines", name="10日線", line=dict(color="cyan", width=1.5)),
            row=1,
            col=1
        )
        fig.add_trace(
            go.Scatter(x=df_chart.index, y=df_chart["MA20"], mode="lines", name="20日線", line=dict(color="orange", width=2)),
            row=1,
            col=1
        )

        vol_colors = [
            "red" if row["Close"] >= row["Open"] else "green"
            for _, row in df_chart.iterrows()
        ]
        fig.add_trace(
            go.Bar(x=df_chart.index, y=df_chart["Volume_K"], marker_color=vol_colors, name="實際成交量(張)"),
            row=2,
            col=1
        )

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=500,
            margin=dict(l=10, r=10, t=10, b=10),
            hovermode="x unified"
        )

        st.plotly_chart(fig, use_container_width=True)

        metrics = calc_stock_metrics(df_chart)
        if metrics is None:
            st.error("此標的資料不足，無法計算技術評鑑。")
            return

        col_data, col_ai = st.columns([1, 1])

        with col_data:
            st.write("### 🗃️ 盤中真實數據")
            st.info(f"**📈 實際總成交量：** {metrics['actual_volume']:,} 張")
            st.metric(label="目前最新報價", value=f"${round(metrics['current_price'], 2)}")
            st.metric(label="📥 建議安全進場價(月線)", value=f"${round(metrics['safe_entry'], 2)}")
            st.metric(label="🚨 建議果斷停損價(破月線)", value=f"${round(metrics['stop_loss'], 2)}")
            st.caption(f"🕒 最新同步時間: {get_tw_time()}")

        with col_ai:
            st.write("### 📐 綜合技術評鑑")
            star_count = metrics["star_count"]
            st.subheader(f"推薦星評：{'⭐' * star_count if star_count > 0 else '💀 (0星)'}")

            if star_count >= 4:
                st.success(metrics["prediction_text"])
            elif star_count == 3:
                st.info(metrics["prediction_text"])
            elif star_count == 2:
                st.warning(metrics["prediction_text"])
            else:
                st.error(metrics["prediction_text"])

    except Exception as e:
        st.error(f"分析過程中發生錯誤: {e}")


# ==========================================
# 全市場掃描引擎
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def scan_whole_market(min_volume, min_stars):
    active_pool = [
        s for s in all_market_stocks
        if s["volume_shares"] > (min_volume * 1000)
    ]

    recommended_list = []

    if active_pool:
        try:
            tickers_list = [s["yahoo_symbol"] for s in active_pool]
            bulk_data = yf.download(
                tickers_list,
                period="3mo",
                group_by="ticker",
                progress=False,
                auto_adjust=False
            )

            for stock in active_pool:
                symbol = stock["yahoo_symbol"]

                try:
                    if isinstance(bulk_data.columns, pd.MultiIndex):
                        if symbol not in bulk_data.columns.levels[0]:
                            continue
                        df_daily = bulk_data[symbol].dropna(how="all")
                    else:
                        df_daily = bulk_data.dropna(how="all")

                    df_chart = prepare_chart_data(df_daily)
                    if df_chart.empty:
                        continue

                    metrics = calc_stock_metrics(df_chart)
                    if metrics is None:
                        continue

                    if metrics["star_count"] >= min_stars:
                        recommended_list.append({
                            "代號": stock["code"],
                            "名稱": stock["name"],
                            "當前現價": round(metrics["current_price"], 2),
                            "今日漲跌": f"{metrics['price_change']:+.2f}%",
                            "成交量(張)": f"{metrics['actual_volume']:,}",
                            "技術星評": "⭐" * metrics["star_count"],
                            "型態短評": metrics["prediction_short"],
                            "乖離率": f"{metrics['bias_ratio']:+.2f}%",
                            "深度分析": f"/?code={stock['code']}",
                            "score_raw": metrics["star_count"]
                        })

                except Exception:
                    continue

        except Exception:
            pass

    if recommended_list:
        df_picks = pd.DataFrame(recommended_list)
        return (
            df_picks.sort_values(by="score_raw", ascending=False)
            .drop(columns=["score_raw"]),
            get_tw_time()
        )

    return pd.DataFrame(), get_tw_time()


# ==========================================
# 側邊欄多功能導航選單
# ==========================================
with st.sidebar:
    st.header("👑 AI 股票智慧系統")
    st.radio(
        "請選擇功能模式：",
        MODE_OPTIONS,
        key="app_mode"
    )
    st.write("---")


# ==========================================
# 模式 A：全市場自動監控推薦
# ==========================================
if st.session_state.app_mode == "🤖 市場 AI 推薦":
    st.title("🌐 市場 AI 推薦")

    market_open, market_msg = is_tw_market_open()

    with st.sidebar:
        st.subheader("📊 篩選嚴格度設定")
        min_volume = st.number_input(
            "最低成交量門檻 (張)",
            min_value=1000,
            max_value=50000,
            value=3000,
            step=1000
        )
        min_stars = st.slider(
            "最低綜合技術星級",
            min_value=1,
            max_value=5,
            value=3
        )
        refresh_rate = st.slider(
            "盤中自動重新掃描間隔 (秒)",
            min_value=30,
            max_value=120,
            value=60
        )

    st.caption(f"🕒 台灣時間：{get_tw_datetime().strftime('%Y-%m-%d %H:%M:%S')}")

    status_placeholder = st.empty()
    table_placeholder = st.empty()

    if not market_open:
        status_placeholder.warning(
            f"⏸️ {market_msg}\n\n"
            "全市場自動監控只在台股一般盤中時間提供；"
            "你仍然可以切到左側「🔍 個股自主搜尋分析」繼續搜尋與查看原本分析。"
        )
        with table_placeholder.container():
            st.info(
                "非盤中時間不執行全市場自動掃描，避免 Streamlit Cloud 一直重跑或手機卡住。\n\n"
                "請使用左側「🔍 個股自主搜尋分析」繼續搜尋個股與查看 K 線分析。"
            )
    else:
        status_placeholder.info("⚡ 雲端引擎正在同步最新盤中資料...")
        df_picks, update_time = scan_whole_market(min_volume, min_stars)

        if not df_picks.empty:
            with table_placeholder.container():
                st.success(f"🎉 **最新精選強勢標的：** (台灣時間: {update_time})")
                st.dataframe(
                    df_picks,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "深度分析": st.column_config.LinkColumn(
                            "🔍 深度分析",
                            display_text="👉 點我分析"
                        )
                    }
                )
        else:
            with table_placeholder.container():
                st.warning(f"⚠️ 目前市場沒有符合條件的標的。(台灣時間: {update_time})")

        status_placeholder.success(
            f"✅ 數據同步完成！系統會在 {refresh_rate} 秒後自動刷新，但不會用 while True 卡住頁面。"
        )
        browser_auto_refresh(refresh_rate, key="market_auto_refresh")


# ==========================================
# 模式 B：個股自主搜尋分析
# ==========================================
elif st.session_state.app_mode == "🔍 個股搜尋分析":
    st.title("🔎 個股搜尋與量價分析")

    with st.sidebar:
        st.subheader("🔄 個股即時盯盤設定")
        auto_refresh_search = st.checkbox("開啟個股無縫自動刷新", value=False)

        if auto_refresh_search:
            search_refresh_rate = st.slider(
                "個股刷新間隔 (秒)",
                min_value=15,
                max_value=60,
                value=30
            )

    if all_market_stocks:
        search_options = [s["display_name"] for s in all_market_stocks]

        default_idx = 0
        if "jump_to_code" in st.session_state and st.session_state.jump_to_code:
            for i, s in enumerate(all_market_stocks):
                if s["code"] == st.session_state.jump_to_code:
                    default_idx = i
                    break
            st.session_state.jump_to_code = None

        user_select = st.selectbox(
            "👉 請選擇或輸入您想查詢的標的 (支援搜尋 ETF)：",
            search_options,
            index=default_idx
        )

        selected_stock_info = next(
            (s for s in all_market_stocks if s["display_name"] == user_select),
            None
        )

        if selected_stock_info:
            render_single_stock_analysis(selected_stock_info)

            if auto_refresh_search:
                st.info(
                    f"⏱️ 系統將在 {search_refresh_rate} 秒後自動為您更新 "
                    f"{selected_stock_info['name']} 的真實報價與成交量..."
                )
                browser_auto_refresh(search_refresh_rate, key="search_auto_refresh")
            else:
                st.caption("⏸️ 自動刷新已暫停。勾選左側「開啟個股無縫自動刷新」即可啟動即時盯盤。")
    else:
        st.error("目前無法取得市場清單，請稍後再試。")
