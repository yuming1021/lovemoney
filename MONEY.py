import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, timedelta

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

st.set_page_config(page_title="AI 股票智慧系統", page_icon="📈", layout="wide")

TZ_TW = timezone(timedelta(hours=8))
MODE_MARKET = "🤖 台股全市場自動推薦"
MODE_TW_SEARCH = "🔍 台股自主搜尋分析"
MODE_US_SEARCH = "🇺🇸 美股自主搜尋分析"
MODES = [MODE_MARKET, MODE_TW_SEARCH, MODE_US_SEARCH]
MODE_MAP = {"market": MODE_MARKET, "tw": MODE_TW_SEARCH, "us": MODE_US_SEARCH}
MODE_QUERY = {v: k for k, v in MODE_MAP.items()}


def now_tw():
    return datetime.now(TZ_TW)


def tw_time_text():
    return now_tw().strftime("%Y-%m-%d %H:%M:%S")


def is_tw_market_open():
    dt = now_tw()
    if dt.weekday() >= 5:
        return False
    start = dt.replace(hour=9, minute=0, second=0, microsecond=0)
    end = dt.replace(hour=13, minute=30, second=0, microsecond=0)
    return start <= dt <= end


def clean_code(value):
    return str(value or "").strip().replace(" ", "").upper()


def only_digits(value):
    text = str(value or "").strip()
    return "".join(ch for ch in text if ch.isdigit())


def autorefresh(seconds, key):
    if st_autorefresh is None:
        return 0
    return st_autorefresh(interval=int(seconds) * 1000, key=key)


# =========================================================
# 台股清單：上市 + 上櫃
# =========================================================
@st.cache_data(ttl=900, show_spinner=False)
def get_twse_symbols():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    fallback = [
        {"code": "2330", "name": "台積電", "yahoo_symbol": "2330.TW", "display_name": "2330 台積電", "volume_shares": 0, "market": "上市"},
        {"code": "2317", "name": "鴻海", "yahoo_symbol": "2317.TW", "display_name": "2317 鴻海", "volume_shares": 0, "market": "上市"},
        {"code": "2454", "name": "聯發科", "yahoo_symbol": "2454.TW", "display_name": "2454 聯發科", "volume_shares": 0, "market": "上市"},
        {"code": "0050", "name": "元大台灣50", "yahoo_symbol": "0050.TW", "display_name": "0050 元大台灣50", "volume_shares": 0, "market": "上市"},
        {"code": "006208", "name": "富邦台50", "yahoo_symbol": "006208.TW", "display_name": "006208 富邦台50", "volume_shares": 0, "market": "上市"},
    ]
    try:
        res = requests.get(url, headers=headers, timeout=12)
        if res.status_code != 200:
            return fallback
        data = res.json()
        stocks = []
        for item in data:
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            vol_text = str(item.get("TradeVolume", "0")).replace(",", "")
            volume_shares = int(vol_text) if vol_text.isdigit() else 0
            if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                stocks.append({
                    "code": code,
                    "name": name,
                    "yahoo_symbol": f"{code}.TW",
                    "display_name": f"{code} {name}",
                    "volume_shares": volume_shares,
                    "market": "上市",
                })
        return stocks if stocks else fallback
    except Exception:
        return fallback


def pick_value(item, names, default=""):
    for name in names:
        value = item.get(name)
        if value not in [None, ""]:
            return value
    return default


@st.cache_data(ttl=900, show_spinner=False)
def get_tpex_symbols():
    urls = [
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code != 200:
                continue
            data = res.json()
            stocks = []
            for item in data:
                code = str(pick_value(item, ["SecuritiesCompanyCode", "SecuritiesCode", "Code", "證券代號", "股票代號", "代號"], "")).strip()
                name = str(pick_value(item, ["CompanyName", "SecuritiesCompanyName", "Name", "證券名稱", "股票名稱", "名稱"], "")).strip()
                vol_text = str(pick_value(item, ["TradingVolume", "TradeVolume", "成交股數", "成交量"], "0")).replace(",", "")
                try:
                    volume_shares = int(float(vol_text))
                except Exception:
                    volume_shares = 0
                if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                    stocks.append({
                        "code": code,
                        "name": name or code,
                        "yahoo_symbol": f"{code}.TWO",
                        "display_name": f"{code} {name or code}",
                        "volume_shares": volume_shares,
                        "market": "上櫃",
                    })
            if stocks:
                return stocks
        except Exception:
            continue
    return []


TWSE_STOCKS = get_twse_symbols()
TPEX_STOCKS = get_tpex_symbols()
_twse_codes = {s["code"] for s in TWSE_STOCKS}
TW_STOCKS = TWSE_STOCKS + [s for s in TPEX_STOCKS if s["code"] not in _twse_codes]
TW_BY_CODE = {s["code"]: s for s in TW_STOCKS}
TW_OPTIONS = [s["display_name"] for s in TW_STOCKS]
TW_BY_DISPLAY = {s["display_name"]: s for s in TW_STOCKS}


# =========================================================
# 技術分析
# =========================================================
@st.cache_data(ttl=45, show_spinner=False)
def get_history(symbol, period="6mo"):
    return yf.Ticker(symbol).history(period=period, auto_adjust=False)


@st.cache_data(ttl=45, show_spinner=False)
def get_first_valid_history(symbols, period="6mo"):
    for symbol in symbols:
        try:
            df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            if df is not None and not df.empty and len(df.dropna(how="all")) >= 50:
                return symbol, df
        except Exception:
            pass
    return symbols[0] if symbols else "", pd.DataFrame()


def add_indicators(raw):
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.copy().dropna(how="all")
    if len(df) < 50:
        return pd.DataFrame()
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA10"] = df["Close"].rolling(10).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["Vol_MA5"] = df["Volume"].rolling(5).mean()
    df["Low5"] = df["Low"].rolling(5).min()
    df["Low10"] = df["Low"].rolling(10).min()
    return df


def short_comment(stars):
    if stars >= 4:
        return "🔥 飆股成型"
    if stars == 3:
        return "📈 趨勢轉強"
    if stars == 2:
        return "➖ 震盪打底"
    if stars == 1:
        return "📉 格局偏弱"
    return "🚨 極度弱勢"


def long_comment(stars):
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
    need = ["Open", "Close", "Volume", "MA5", "MA10", "MA20", "MA50", "Vol_MA5", "Low5", "Low10"]
    if any(col not in df.columns or pd.isna(latest[col]) for col in need):
        return None

    open_price = float(latest["Open"])
    close_price = float(latest["Close"])
    volume = float(latest["Volume"])
    ma5 = float(latest["MA5"])
    ma10 = float(latest["MA10"])
    ma20 = float(latest["MA20"])
    ma50 = float(latest["MA50"])
    vol_ma5 = float(latest["Vol_MA5"])
    low5 = float(latest["Low5"])
    low10 = float(latest["Low10"])
    if open_price == 0 or ma20 == 0:
        return None

    price_change = (close_price - open_price) / open_price * 100
    bias_ratio = (close_price - ma20) / ma20 * 100

    stars = 0
    if close_price > ma20:
        stars += 1
    if ma20 > ma50:
        stars += 1
    if ma5 > ma10:
        stars += 1
    if close_price > open_price and volume > vol_ma5:
        stars += 1
    if 0 < bias_ratio < 8:
        stars += 1

    return {
        "current_price": close_price,
        "actual_volume": int(volume / volume_divisor),
        "price_change": price_change,
        "bias_ratio": bias_ratio,
        "stars": stars,
        "entry_price": max(ma10, low5) * 0.995,
        "stop_loss": low10 * 0.985,
        "short_prediction": short_comment(stars),
        "long_prediction": long_comment(stars),
    }


def draw_chart(df, volume_unit, volume_divisor):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="日K線",
        increasing_line_color="red", increasing_fillcolor="red",
        decreasing_line_color="green", decreasing_fillcolor="green",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], mode="lines", name="5日線", line=dict(color="pink", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA10"], mode="lines", name="10日線", line=dict(color="cyan", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], mode="lines", name="20日線", line=dict(color="orange", width=1.8)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA50"], mode="lines", name="50日線", line=dict(color="gray", width=1.2)), row=1, col=1)
    bar_colors = ["red" if c >= o else "green" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"] / volume_divisor, marker_color=bar_colors, name=f"成交量({volume_unit})"), row=2, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False, height=540, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def render_analysis(stock, candidates, volume_unit, volume_divisor, currency):
    used_symbol, raw = get_first_valid_history(candidates, period="6mo")
    df = add_indicators(raw)
    if df.empty:
        st.error("查不到足夠資料，請確認代號是否正確。")
        return

    st.subheader(f"📊 {stock['code']} {stock['name']}")
    draw_chart(df, volume_unit, volume_divisor)
    metrics = calc_metrics(df, volume_divisor)
    if metrics is None:
        st.error("資料不足，無法計算技術評鑑。")
        return

    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.write("### 🗃️ 最新資料面板")
        st.info(f"**成交量：** {metrics['actual_volume']:,} {volume_unit}")
        st.metric("目前最新報價", f"{currency}{metrics['current_price']:.2f}", f"{metrics['price_change']:+.2f}%")
        st.metric("📥 建議短線進場價", f"{currency}{metrics['entry_price']:.2f}")
        st.metric("🚨 建議短線停損價", f"{currency}{metrics['stop_loss']:.2f}")

    with col_right:
        stars = metrics["stars"]
        st.write("### 📐 綜合技術評鑑")
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


# =========================================================
# 全市場掃描
# =========================================================
def extract_from_bulk(bulk, symbol):
    if bulk is None or bulk.empty:
        return pd.DataFrame()
    if isinstance(bulk.columns, pd.MultiIndex):
        if symbol not in list(bulk.columns.get_level_values(0).unique()):
            return pd.DataFrame()
        return bulk[symbol].dropna(how="all")
    return bulk.dropna(how="all")


def scan_market(min_volume_lots, min_stars, market_scope, batch_size):
    if market_scope == "上市":
        base_pool = TWSE_STOCKS
    elif market_scope == "上櫃":
        base_pool = TPEX_STOCKS
    else:
        base_pool = TW_STOCKS

    pool = [s for s in base_pool if int(s.get("volume_shares", 0)) >= int(min_volume_lots) * 1000]
    pool = sorted(pool, key=lambda x: int(x.get("volume_shares", 0)), reverse=True)
    total = len(pool)
    rows = []

    if total == 0:
        return pd.DataFrame(), 0, 0

    progress = st.progress(0, text=f"掃描中：0 / {total}")
    scanned = 0

    for start in range(0, total, batch_size):
        batch = pool[start:start + batch_size]
        symbols = [s["yahoo_symbol"] for s in batch]
        try:
            bulk = yf.download(
                symbols,
                period="3mo",
                group_by="ticker",
                progress=False,
                auto_adjust=False,
                threads=True,
                timeout=20,
            )
        except Exception:
            bulk = pd.DataFrame()

        for stock in batch:
            scanned += 1
            try:
                raw = extract_from_bulk(bulk, stock["yahoo_symbol"])
                df = add_indicators(raw)
                metrics = calc_metrics(df, volume_divisor=1000)
                if metrics is None or metrics["stars"] < min_stars:
                    continue
                rows.append({
                    "市場": stock["market"],
                    "代號": stock["code"],
                    "名稱": stock["name"],
                    "當前現價": round(metrics["current_price"], 2),
                    "今日漲跌": f"{metrics['price_change']:+.2f}%",
                    "成交量(張)": metrics["actual_volume"],
                    "技術星評": "⭐" * metrics["stars"],
                    "型態短評": metrics["short_prediction"],
                    "乖離率": f"{metrics['bias_ratio']:+.2f}%",
                    "深度分析": f"/?mode=tw&tw={stock['code']}",
                    "score": metrics["stars"],
                })
            except Exception:
                pass
        progress.progress(min(scanned / total, 1), text=f"掃描中：{scanned} / {total}")

    progress.empty()
    if not rows:
        return pd.DataFrame(), scanned, total
    out = pd.DataFrame(rows).sort_values(["score", "成交量(張)"], ascending=[False, False]).drop(columns=["score"])
    return out, scanned, total


# =========================================================
# Session / URL
# =========================================================
mode_from_url = st.query_params.get("mode")
if "app_mode" not in st.session_state:
    st.session_state.app_mode = MODE_MAP.get(mode_from_url, MODE_MARKET)

if st.query_params.get("tw"):
    st.session_state.app_mode = MODE_TW_SEARCH
if st.query_params.get("us"):
    st.session_state.app_mode = MODE_US_SEARCH

with st.sidebar:
    st.header("👑 AI 股票智慧系統")
    current_index = MODES.index(st.session_state.app_mode) if st.session_state.app_mode in MODES else 0
    selected = st.radio("請選擇功能模式：", MODES, index=current_index)
    if selected != st.session_state.app_mode:
        st.session_state.app_mode = selected
        st.query_params["mode"] = MODE_QUERY[selected]
        st.rerun()
    st.write("---")


# =========================================================
# A. 台股全市場自動推薦
# =========================================================
if st.session_state.app_mode == MODE_MARKET:
    st.title("🌐 台股全市場 AI 自動推薦")

    with st.sidebar:
        st.subheader("📊 推薦條件")
        market_scope = st.selectbox("掃描範圍", ["上市+上櫃", "上市", "上櫃"], index=0)
        min_volume = st.number_input("最低成交量門檻（張）", min_value=0, max_value=50000, value=3000, step=1000)
        min_stars = st.slider("最低技術星級", min_value=1, max_value=5, value=3)
        refresh_seconds = st.slider("自動刷新秒數", min_value=30, max_value=180, value=60, step=10)
        batch_size = st.selectbox("掃描速度", [40, 60, 80, 100], index=2, format_func=lambda x: f"每批 {x} 檔")
        manual = st.button("🔄 立即重新掃描")

    if not is_tw_market_open():
        st.warning("目前非台股盤中時間，全市場自動推薦暫停。")
    else:
        refresh_count = autorefresh(refresh_seconds, key="market_autorefresh")
        if manual:
            refresh_count += 1

        df_picks, scanned, total = scan_market(
            min_volume_lots=min_volume,
            min_stars=min_stars,
            market_scope=market_scope,
            batch_size=batch_size,
        )

        if df_picks.empty:
            st.warning(f"目前沒有符合條件的標的。更新時間：{tw_time_text()}")
        else:
            st.success(f"最新推薦標的｜更新時間：{tw_time_text()}｜已掃描 {scanned}/{total} 檔")
            st.dataframe(
                df_picks,
                use_container_width=True,
                hide_index=True,
                column_config={"深度分析": st.column_config.LinkColumn("深度分析", display_text="查看")},
            )


# =========================================================
# B. 台股自主搜尋
# =========================================================
elif st.session_state.app_mode == MODE_TW_SEARCH:
    st.title("🔍 台股自主搜尋分析")

    with st.sidebar:
        st.subheader("🔄 台股刷新")
        tw_auto = st.checkbox("開啟台股自動刷新", value=False)
        tw_refresh = st.slider("台股刷新秒數", min_value=15, max_value=120, value=30, step=5) if tw_auto else 30
        if st.button("🔄 重新抓取台股資料"):
            get_history.clear()
            get_first_valid_history.clear()

    if tw_auto:
        autorefresh(tw_refresh, key="tw_autorefresh")

    url_code = only_digits(st.query_params.get("tw", ""))
    default_index = 0
    if url_code:
        for i, option in enumerate(TW_OPTIONS):
            if option.startswith(url_code + " "):
                default_index = i
                break

    search_mode = st.radio("搜尋方式", ["從清單搜尋公司名稱/代號", "手動輸入代號"], horizontal=True)

    if search_mode == "從清單搜尋公司名稱/代號":
        selected_display = st.selectbox("輸入中文名稱或股票代號搜尋：", TW_OPTIONS, index=default_index)
        stock = TW_BY_DISPLAY[selected_display]
        candidates = [stock["yahoo_symbol"]]
    else:
        default_code = url_code or "2330"
        manual_input = st.text_input("輸入台股代號：", value=default_code, placeholder="例如 2330、2317、006208、6488")
        code = only_digits(manual_input)
        if not code:
            st.warning("請輸入台股代號。")
            st.stop()
        matched = TW_BY_CODE.get(code)
        if matched:
            stock = matched
            candidates = [matched["yahoo_symbol"]]
        else:
            stock = {"code": code, "name": code, "yahoo_symbol": f"{code}.TW"}
            candidates = [f"{code}.TW", f"{code}.TWO"]

    st.query_params["mode"] = "tw"
    st.query_params["tw"] = stock["code"]
    render_analysis(stock, candidates, volume_unit="張", volume_divisor=1000, currency="NT$")


# =========================================================
# C. 美股自主搜尋
# =========================================================
elif st.session_state.app_mode == MODE_US_SEARCH:
    st.title("🇺🇸 美股自主搜尋分析")

    with st.sidebar:
        st.subheader("🔄 美股刷新")
        us_auto = st.checkbox("開啟美股自動刷新", value=False)
        us_refresh = st.slider("美股刷新秒數", min_value=15, max_value=120, value=30, step=5) if us_auto else 30
        if st.button("🔄 重新抓取美股資料"):
            get_history.clear()
            get_first_valid_history.clear()

    if us_auto:
        autorefresh(us_refresh, key="us_autorefresh")

    default_us = clean_code(st.query_params.get("us", "NVDA")) or "NVDA"
    us_input = st.text_input("輸入美股或 ETF 代號：", value=default_us, placeholder="例如 NVDA、AAPL、ONDS、SMR、OKLO、QQQ")
    us_symbol = clean_code(us_input)

    if not us_symbol:
        st.warning("請輸入美股代號。")
        st.stop()

    st.query_params["mode"] = "us"
    st.query_params["us"] = us_symbol
    stock = {"code": us_symbol, "name": us_symbol, "yahoo_symbol": us_symbol}
    render_analysis(stock, [us_symbol], volume_unit="股", volume_divisor=1, currency="US$")
