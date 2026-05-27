import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, timedelta

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

# =========================================================
# 基本設定
# =========================================================
st.set_page_config(
    page_title="AI 股票智慧系統",
    page_icon="📈",
    layout="wide"
)

TZ_TW = timezone(timedelta(hours=8))

MODE_MARKET = "🤖 台股全市場自動監控"
MODE_TW_SEARCH = "🔍 台股自主搜尋分析"
MODE_US_SEARCH = "🇺🇸 美股自主搜尋分析"
MODE_OPTIONS = [MODE_MARKET, MODE_TW_SEARCH, MODE_US_SEARCH]
MODE_TO_QUERY = {MODE_MARKET: "market", MODE_TW_SEARCH: "tw", MODE_US_SEARCH: "us"}
QUERY_TO_MODE = {v: k for k, v in MODE_TO_QUERY.items()}


def now_tw():
    return datetime.now(TZ_TW)


def get_tw_time_text():
    return now_tw().strftime("%Y-%m-%d %H:%M:%S")


def is_tw_market_open(dt=None):
    """台股一般交易時間：週一～週五 09:00～13:30。此處未判斷國定假日。"""
    dt = dt or now_tw()
    if dt.weekday() >= 5:
        return False, "目前為週末，非台股一般盤中時間。"

    start = dt.replace(hour=9, minute=0, second=0, microsecond=0)
    end = dt.replace(hour=13, minute=30, second=0, microsecond=0)

    if dt < start:
        return False, "目前尚未開盤，全市場自動監控暫停。"
    if dt > end:
        return False, "目前已收盤，全市場自動監控暫停。"
    return True, "目前為台股一般盤中時間。"


def safe_autorefresh(seconds, key):
    """使用 streamlit-autorefresh，不用 while True，也不做整頁 reload。"""
    if not HAS_AUTOREFRESH:
        st.warning("⚠️ requirements.txt 缺少 streamlit-autorefresh，所以自動刷新暫時不可用。")
        return 0
    return st_autorefresh(interval=int(seconds) * 1000, key=key)


def clean_symbol(text):
    return str(text or "").strip().upper().replace(" ", "")


# =========================================================
# 台股清單
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_twse_symbols():
    fallback = [
        {"code": "2330", "name": "台積電", "yahoo_symbol": "2330.TW", "display_name": "2330 台積電", "volume_shares": 10_000_000},
        {"code": "2317", "name": "鴻海", "yahoo_symbol": "2317.TW", "display_name": "2317 鴻海", "volume_shares": 10_000_000},
        {"code": "2454", "name": "聯發科", "yahoo_symbol": "2454.TW", "display_name": "2454 聯發科", "volume_shares": 10_000_000},
        {"code": "0050", "name": "元大台灣50", "yahoo_symbol": "0050.TW", "display_name": "0050 元大台灣50", "volume_shares": 10_000_000},
        {"code": "006208", "name": "富邦台50", "yahoo_symbol": "006208.TW", "display_name": "006208 富邦台50", "volume_shares": 10_000_000},
    ]
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return fallback
        data = res.json()
        output = []
        for item in data:
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            vol_text = str(item.get("TradeVolume", "0")).replace(",", "")
            volume_shares = int(vol_text) if vol_text.isdigit() else 0
            if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                output.append({
                    "code": code,
                    "name": name,
                    "yahoo_symbol": f"{code}.TW",
                    "display_name": f"{code} {name}",
                    "volume_shares": volume_shares,
                })
        return output if output else fallback
    except Exception:
        return fallback


TW_STOCKS = get_twse_symbols()
TW_BY_CODE = {s["code"]: s for s in TW_STOCKS}
TW_DISPLAY_OPTIONS = [s["display_name"] for s in TW_STOCKS]


# =========================================================
# 資料下載與技術分析
# =========================================================
@st.cache_data(ttl=45, show_spinner=False)
def download_history_one(yahoo_symbol, period="6mo"):
    return yf.Ticker(yahoo_symbol).history(period=period, auto_adjust=False)


@st.cache_data(ttl=45, show_spinner=False)
def download_history_candidates(candidates, period="6mo"):
    """依序嘗試多個 Yahoo symbol，回傳第一個有足夠資料的結果。"""
    for symbol in candidates:
        try:
            df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            if df is not None and not df.empty and len(df.dropna(how="all")) >= 50:
                return symbol, df
        except Exception:
            continue
    return candidates[0] if candidates else "", pd.DataFrame()


def prepare_indicators(df_raw):
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
    df = df_raw.copy().dropna(how="all")
    if len(df) < 50:
        return pd.DataFrame()

    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA10"] = df["Close"].rolling(10).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["Vol_MA5"] = df["Volume"].rolling(5).mean()
    df["Low5"] = df["Low"].rolling(5).min()
    df["Low10"] = df["Low"].rolling(10).min()
    prev_close = df["Close"].shift(1)
    df["TR"] = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR14"] = df["TR"].rolling(14).mean()
    return df


def get_short_prediction(stars):
    if stars >= 4:
        return "🔥 飆股成型"
    if stars == 3:
        return "📈 趨勢轉強"
    if stars == 2:
        return "➖ 震盪打底"
    if stars == 1:
        return "📉 格局偏弱"
    return "🚨 極度弱勢"


def get_long_prediction(stars):
    if stars == 5:
        return "🔥 **型態走勢：極度看漲**\n\n均線結構與量價動能都偏強，但如果價格離短均太遠，仍不建議無腦追高。"
    if stars == 4:
        return "🚀 **型態走勢：穩健看漲**\n\n趨勢偏多，短中期均線提供支撐。較好的做法是等回測支撐不破再進場。"
    if stars == 3:
        return "📈 **型態走勢：溫和偏多**\n\n價格站上關鍵均線，但動能還沒完全確認。可觀察是否帶量突破或回測有守。"
    if stars == 2:
        return "➖ **型態走勢：中性盤整**\n\n多空尚未明確表態，容易區間震盪。建議等突破或跌破後再決定方向。"
    if stars == 1:
        return "📉 **型態走勢：轉弱疑慮**\n\n價格結構偏弱，支撐不足。短線有回檔壓力，建議降低追價風險。"
    return "🚨 **型態走勢：極度弱勢**\n\n空頭格局偏明顯，若沒有重新站回關鍵均線，建議先避開。"


def calc_metrics(df, volume_divisor):
    if df is None or df.empty or len(df) < 50:
        return None
    latest = df.iloc[-1]
    current_price = float(latest["Close"])
    today_open = float(latest["Open"])
    today_vol = float(latest["Volume"])
    ma5 = float(latest["MA5"])
    ma10 = float(latest["MA10"])
    ma20 = float(latest["MA20"])
    ma50 = float(latest["MA50"])
    vol_ma5 = float(latest["Vol_MA5"])
    low5 = float(latest["Low5"])
    low10 = float(latest["Low10"])
    atr14 = float(latest["ATR14"])

    required = [current_price, today_open, ma5, ma10, ma20, ma50, vol_ma5, low5, low10, atr14]
    if any(pd.isna(x) for x in required) or today_open == 0 or ma20 == 0:
        return None

    price_change = ((current_price - today_open) / today_open) * 100
    bias_ratio = ((current_price - ma20) / ma20) * 100

    stars = 0
    if current_price > ma20:
        stars += 1
    if ma20 > ma50:
        stars += 1
    if ma5 > ma10:
        stars += 1
    if current_price > today_open and today_vol > vol_ma5:
        stars += 1
    if 0 < bias_ratio < 8:
        stars += 1

    entry_price = max(ma10, low5) * 0.995
    stop_loss = low10 * 0.985

    return {
        "current_price": current_price,
        "actual_volume": int(today_vol / volume_divisor),
        "price_change": price_change,
        "bias_ratio": bias_ratio,
        "stars": stars,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "short_prediction": get_short_prediction(stars),
        "long_prediction": get_long_prediction(stars),
    }


def draw_stock_chart(df, volume_unit, volume_divisor):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="日K線",
            increasing_line_color="red", increasing_fillcolor="red",
            decreasing_line_color="green", decreasing_fillcolor="green",
        ),
        row=1, col=1,
    )
    fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], mode="lines", name="5日線", line=dict(color="pink", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA10"], mode="lines", name="10日線", line=dict(color="cyan", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], mode="lines", name="20日線", line=dict(color="orange", width=1.8)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA50"], mode="lines", name="50日線", line=dict(color="gray", width=1.2)), row=1, col=1)
    colors = ["red" if c >= o else "green" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"] / volume_divisor, name=f"成交量({volume_unit})", marker_color=colors), row=2, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False, height=540, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def render_analysis(stock_info, volume_unit, volume_divisor, currency, subtitle, candidates=None):
    st.write("---")
    st.subheader(f"📊 【{stock_info['code']} {stock_info['name']}】{subtitle}")

    try:
        if candidates:
            used_symbol, raw = download_history_candidates(candidates, period="6mo")
            st.caption(f"資料來源代號：{used_symbol}")
        else:
            used_symbol = stock_info["yahoo_symbol"]
            raw = download_history_one(used_symbol, period="6mo")
            st.caption(f"資料來源代號：{used_symbol}")

        df = prepare_indicators(raw)
        if df.empty:
            st.error("這個標的目前沒有足夠的歷史資料，無法分析。請確認代號是否正確，或換一個標的。")
            return

        draw_stock_chart(df, volume_unit, volume_divisor)
        metrics = calc_metrics(df, volume_divisor)
        if metrics is None:
            st.error("資料不足，無法計算技術評鑑。")
            return

        col_left, col_right = st.columns([1, 1])
        with col_left:
            st.write("### 🗃️ 最新資料面板")
            st.info(f"**📈 成交量：** {metrics['actual_volume']:,} {volume_unit}")
            st.metric("目前最新報價", f"{currency}{metrics['current_price']:.2f}", f"{metrics['price_change']:+.2f}%")
            st.metric("📥 建議短線進場價", f"{currency}{metrics['entry_price']:.2f}", help="公式：max(10日線, 近5日低點) × 0.995。")
            st.metric("🚨 建議短線停損價", f"{currency}{metrics['stop_loss']:.2f}", help="公式：近10日低點 × 0.985。")
            st.caption(f"🕒 最新同步時間：{get_tw_time_text()}（台灣時間）")

        with col_right:
            st.write("### 📐 綜合技術評鑑")
            stars = metrics["stars"]
            st.subheader(f"推薦星評：{'⭐' * stars if stars > 0 else '💀 0星'}")
            st.write(f"**乖離率：** {metrics['bias_ratio']:+.2f}%")
            st.write(f"**型態短評：** {metrics['short_prediction']}")
            if stars >= 4:
                st.success(metrics["long_prediction"])
            elif stars == 3:
                st.info(metrics["long_prediction"])
            elif stars == 2:
                st.warning(metrics["long_prediction"])
            else:
                st.error(metrics["long_prediction"])
    except Exception as e:
        st.error(f"分析失敗：{e}")


# =========================================================
# 台股全市場掃描
# =========================================================
@st.cache_data(ttl=20, show_spinner=False)
def scan_tw_market(min_volume_lots, min_stars, refresh_count):
    # refresh_count 放進參數，是為了自動刷新時真的重新抓資料，不被 cache 永遠吃掉。
    active_pool = [s for s in TW_STOCKS if s["volume_shares"] >= min_volume_lots * 1000]
    result = []
    if not active_pool:
        return pd.DataFrame(), get_tw_time_text()

    try:
        symbols = [s["yahoo_symbol"] for s in active_pool]
        bulk = yf.download(symbols, period="3mo", group_by="ticker", progress=False, auto_adjust=False, threads=True)
        for stock in active_pool:
            try:
                symbol = stock["yahoo_symbol"]
                if isinstance(bulk.columns, pd.MultiIndex):
                    if symbol not in bulk.columns.get_level_values(0):
                        continue
                    raw = bulk[symbol].dropna(how="all")
                else:
                    raw = bulk.dropna(how="all")
                df = prepare_indicators(raw)
                metrics = calc_metrics(df, volume_divisor=1000)
                if metrics is None or metrics["stars"] < min_stars:
                    continue
                result.append({
                    "代號": stock["code"],
                    "名稱": stock["name"],
                    "當前現價": round(metrics["current_price"], 2),
                    "今日漲跌": f"{metrics['price_change']:+.2f}%",
                    "成交量(張)": f"{metrics['actual_volume']:,}",
                    "技術星評": "⭐" * metrics["stars"],
                    "型態短評": metrics["short_prediction"],
                    "乖離率": f"{metrics['bias_ratio']:+.2f}%",
                    "深度分析": f"/?mode=tw&tw={stock['code']}",
                    "score": metrics["stars"],
                })
            except Exception:
                continue
    except Exception:
        return pd.DataFrame(), get_tw_time_text()

    if not result:
        return pd.DataFrame(), get_tw_time_text()
    return pd.DataFrame(result).sort_values("score", ascending=False).drop(columns=["score"]), get_tw_time_text()


# =========================================================
# URL / Session 初始化
# =========================================================
mode_query = st.query_params.get("mode")
if "app_mode" not in st.session_state:
    st.session_state.app_mode = QUERY_TO_MODE.get(mode_query, MODE_MARKET)

# 深度連結：/?mode=tw&tw=2330 或 /?mode=us&us=NVDA
if st.query_params.get("tw"):
    st.session_state.app_mode = MODE_TW_SEARCH
if st.query_params.get("us"):
    st.session_state.app_mode = MODE_US_SEARCH


# =========================================================
# 側邊欄
# =========================================================
with st.sidebar:
    st.header("👑 AI 股票智慧系統")
    current_index = MODE_OPTIONS.index(st.session_state.app_mode) if st.session_state.app_mode in MODE_OPTIONS else 0
    selected_mode = st.radio("請選擇功能模式：", MODE_OPTIONS, index=current_index, key="mode_radio")
    if selected_mode != st.session_state.app_mode:
        st.session_state.app_mode = selected_mode
        st.query_params["mode"] = MODE_TO_QUERY[selected_mode]
        if selected_mode != MODE_TW_SEARCH and "tw" in st.query_params:
            del st.query_params["tw"]
        if selected_mode != MODE_US_SEARCH and "us" in st.query_params:
            del st.query_params["us"]
        st.rerun()
    st.write("---")
    st.caption("本系統為技術分析輔助工具，不構成投資建議。")


# =========================================================
# 頁面 A：台股全市場自動監控
# =========================================================
if st.session_state.app_mode == MODE_MARKET:
    st.title("🌐 台股全市場 AI 自動監控")
    st.caption(f"🕒 台灣時間：{get_tw_time_text()}")

    market_open, msg = is_tw_market_open()
    with st.sidebar:
        st.subheader("📊 掃描條件")
        min_volume = st.number_input("最低成交量門檻（張）", min_value=1000, max_value=50000, value=3000, step=1000)
        min_stars = st.slider("最低綜合技術星級", min_value=1, max_value=5, value=3)
        refresh_seconds = st.slider("盤中自動刷新秒數", min_value=30, max_value=180, value=60, step=10)
        manual_refresh = st.button("🔄 立即重新掃描")

    refresh_count = 0
    if market_open:
        refresh_count = safe_autorefresh(refresh_seconds, key="market_refresh")

    if manual_refresh:
        scan_tw_market.clear()
        download_history_one.clear()
        download_history_candidates.clear()
        refresh_count += 999999

    if not market_open:
        st.warning(f"⏸️ {msg}\n\n非盤中時間不提供台股全市場自動掃描，避免雲端一直重跑造成網站卡住。")
        st.info("你仍然可以使用左側的「台股自主搜尋分析」與「美股自主搜尋分析」。")
    else:
        st.info(f"⚡ 正在掃描符合條件的台股標的……目前刷新次數：{refresh_count}")
        picks, update_time = scan_tw_market(min_volume, min_stars, refresh_count)
        if picks.empty:
            st.warning(f"目前沒有符合條件的標的。（更新時間：{update_time}）")
        else:
            st.success(f"🎉 最新精選強勢標的（更新時間：{update_time}）")
            st.dataframe(
                picks,
                use_container_width=True,
                hide_index=True,
                column_config={"深度分析": st.column_config.LinkColumn("🔍 深度分析", display_text="👉 點我分析")},
            )
        st.caption(f"盤中每 {refresh_seconds} 秒自動刷新一次；此版不使用 while True，也不做整頁 reload。")


# =========================================================
# 頁面 B：台股自主搜尋
# =========================================================
elif st.session_state.app_mode == MODE_TW_SEARCH:
    st.title("🔍 台股自主搜尋與量價分析")
    with st.sidebar:
        st.subheader("🔄 台股自動刷新")
        tw_auto = st.checkbox("開啟台股自動刷新", value=False)
        tw_refresh = st.slider("台股刷新秒數", min_value=15, max_value=120, value=30, step=5) if tw_auto else 30
        if st.button("🔄 重新抓取此台股"):
            download_history_one.clear()
            download_history_candidates.clear()

    if tw_auto:
        safe_autorefresh(tw_refresh, key="tw_search_refresh")

    default_tw = clean_symbol(st.query_params.get("tw", "2330")) or "2330"
    tw_input = st.text_input(
        "👉 直接輸入台股代號，上市/上櫃都可嘗試，例如 2330、2317、2454、006208、6488：",
        value=default_tw,
        placeholder="輸入台股代號",
    )
    tw_code = clean_symbol(tw_input)
    if tw_code and st.query_params.get("tw") != tw_code:
        st.query_params["mode"] = "tw"
        st.query_params["tw"] = tw_code

    matched = TW_BY_CODE.get(tw_code)
    if matched:
        stock = matched
        candidates = [matched["yahoo_symbol"]]
    else:
        # 不在上市清單中時，自動嘗試上市 .TW 與上櫃 .TWO。
        stock = {"code": tw_code, "name": tw_code, "yahoo_symbol": f"{tw_code}.TW"}
        candidates = [f"{tw_code}.TW", f"{tw_code}.TWO"]
        st.caption("此代號不在目前上市清單內，系統會依序嘗試 Yahoo Finance 的 .TW 與 .TWO。")

    if not tw_code:
        st.warning("請先輸入台股代號。")
    else:
        render_analysis(stock, volume_unit="張", volume_divisor=1000, currency="NT$", subtitle="台股量價與綜合評鑑", candidates=candidates)
        st.caption("台股搜尋不受盤中時間限制，任何時間都能查歷史資料。")


# =========================================================
# 頁面 C：美股自主搜尋
# =========================================================
elif st.session_state.app_mode == MODE_US_SEARCH:
    st.title("🇺🇸 美股自主搜尋與量價分析")
    with st.sidebar:
        st.subheader("🔄 美股自動刷新")
        us_auto = st.checkbox("開啟美股自動刷新", value=False)
        us_refresh = st.slider("美股刷新秒數", min_value=15, max_value=120, value=30, step=5) if us_auto else 30
        if st.button("🔄 重新抓取此美股"):
            download_history_one.clear()
            download_history_candidates.clear()

    if us_auto:
        safe_autorefresh(us_refresh, key="us_search_refresh")

    st.info("美股不再限制固定清單；能不能查到取決於 Yahoo Finance / yfinance 是否有該代號資料。")
    quick_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN", "GOOGL", "META", "PLTR", "ARM", "CEG", "PANW", "ONDS", "SMR", "OKLO", "SOFI", "RKLB", "IONQ", "SPY", "QQQ", "VOO", "TQQQ", "SOXL"]

    default_us = clean_symbol(st.query_params.get("us", "NVDA")) or "NVDA"
    col1, col2 = st.columns([2, 1])
    with col1:
        us_input = st.text_input("👉 輸入任意美股 / ETF 代號：", value=default_us, placeholder="例如 ONDS、SMR、OKLO、SOFI、RKLB、NVDA、QQQ")
    with col2:
        quick_pick = st.selectbox("常用快速選擇：", ["不使用"] + quick_symbols)

    us_symbol = clean_symbol(quick_pick if quick_pick != "不使用" else us_input)
    if us_symbol and st.query_params.get("us") != us_symbol:
        st.query_params["mode"] = "us"
        st.query_params["us"] = us_symbol

    if not us_symbol:
        st.warning("請先輸入美股代號。")
    else:
        stock = {"code": us_symbol, "name": us_symbol, "yahoo_symbol": us_symbol}
        render_analysis(stock, volume_unit="股", volume_divisor=1, currency="US$", subtitle="美股量價與綜合評鑑", candidates=[us_symbol])
        st.caption("可自由輸入美股/ETF 代號；但打錯、下市、資料不足或 Yahoo Finance 無資料時會無法分析。")

else:
    st.error("未知功能模式，請重新整理頁面。")
