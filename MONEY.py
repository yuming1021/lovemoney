import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, timedelta

# 嘗試載入自動刷新套件，若無則使用內建迴圈機制
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

MODE_MARKET = "🤖 台股全市場監控 (支援盤後)"
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
    dt = dt or now_tw()
    if dt.weekday() >= 5:
        return False, "目前為週末，台股未開盤。"
    start = dt.replace(hour=9, minute=0, second=0, microsecond=0)
    end = dt.replace(hour=13, minute=30, second=0, microsecond=0)
    if dt < start or dt > end:
        return False, "目前非盤中交易時間。"
    return True, "目前為台股盤中交易時間。"

def safe_autorefresh(seconds, key):
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=int(seconds) * 1000, key=key)
    else:
        # 若無套件，則透過 session_state 傳遞給程式碼最後面執行 sleep
        st.session_state["fallback_refresh"] = seconds

def clean_symbol(text):
    return str(text or "").strip().upper().replace(" ", "")

# =========================================================
# 台股清單：抓好抓滿 (上市+上櫃)
# =========================================================
def _pick_first(item, keys, default=""):
    for key in keys:
        if key in item and item.get(key) not in [None, ""]:
            return item.get(key)
    return default

@st.cache_data(ttl=3600, show_spinner=False)
def get_twse_symbols():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200: return []
        data = res.json()
        output = []
        for item in data:
            code = str(item.get("Code", "")).strip()
            name = str(item.get("Name", "")).strip()
            vol_text = str(item.get("TradeVolume", "0")).replace(",", "")
            volume_shares = int(vol_text) if vol_text.isdigit() else 0
            if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                output.append({
                    "code": code, "name": name, "yahoo_symbol": f"{code}.TW",
                    "display_name": f"{code} {name}", "volume_shares": volume_shares, "market": "上市",
                })
        return output
    except Exception: return []

@st.cache_data(ttl=3600, show_spinner=False)
def get_tpex_symbols():
    urls = [
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code != 200: continue
            data = res.json()
            output = []
            for item in data:
                code = str(_pick_first(item, ["SecuritiesCompanyCode", "SecuritiesCode", "Code", "代號", "股票代號"], "")).strip()
                name = str(_pick_first(item, ["CompanyName", "SecuritiesCompanyName", "Name", "名稱", "股票名稱"], "")).strip()
                vol_text = str(_pick_first(item, ["TradingVolume", "TradeVolume", "成交股數", "成交量"], "0")).replace(",", "")
                volume_shares = int(float(vol_text)) if vol_text.replace(".", "", 1).isdigit() else 0
                if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                    output.append({
                        "code": code, "name": name or code, "yahoo_symbol": f"{code}.TWO",
                        "display_name": f"{code} {name or code}", "volume_shares": volume_shares, "market": "上櫃",
                    })
            if output: return output
        except Exception: continue
    return []

TWSE_STOCKS = get_twse_symbols()
TPEX_STOCKS = get_tpex_symbols()
TW_STOCKS = TWSE_STOCKS + [s for s in TPEX_STOCKS if s["code"] not in {x["code"] for x in TWSE_STOCKS}]
TW_BY_CODE = {s["code"]: s for s in TW_STOCKS}
TW_DISPLAY_OPTIONS = [s["display_name"] for s in TW_STOCKS]


# =========================================================
# 資料下載與技術分析 (縮短快取時間確保拿到最新資料)
# =========================================================
@st.cache_data(ttl=15, show_spinner=False) # 縮短為 15 秒
def download_history_one(yahoo_symbol, period="6mo"):
    return yf.Ticker(yahoo_symbol).history(period=period, auto_adjust=False)

@st.cache_data(ttl=15, show_spinner=False)
def download_history_candidates(candidates, period="6mo"):
    for symbol in candidates:
        try:
            df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            if df is not None and not df.empty and len(df.dropna(how="all")) >= 50:
                return symbol, df
        except Exception: continue
    return candidates[0] if candidates else "", pd.DataFrame()

def prepare_indicators(df_raw):
    if df_raw is None or df_raw.empty: return pd.DataFrame()
    df = df_raw.copy().dropna(how="all")
    if len(df) < 50: return pd.DataFrame()

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
    df["ATR14"] = df["TR"].rolling(14).mean() # 真實波動幅度
    return df

def get_short_prediction(stars):
    if stars >= 4: return "🔥 飆股成型"
    if stars == 3: return "📈 趨勢轉強"
    if stars == 2: return "➖ 震盪打底"
    if stars == 1: return "📉 格局偏弱"
    return "🚨 極度弱勢"

def calc_metrics(df, volume_divisor):
    if df is None or df.empty or len(df) < 50: return None
    latest = df.iloc[-1]
    
    current_price, today_open, today_vol = float(latest["Close"]), float(latest["Open"]), float(latest["Volume"])
    ma5, ma10, ma20, ma50 = float(latest["MA5"]), float(latest["MA10"]), float(latest["MA20"]), float(latest["MA50"])
    vol_ma5, low5, low10, atr14 = float(latest["Vol_MA5"]), float(latest["Low5"]), float(latest["Low10"]), float(latest["ATR14"])

    if any(pd.isna(x) for x in [current_price, today_open, ma5, ma20, atr14]) or today_open == 0 or ma20 == 0:
        return None

    price_change = ((current_price - today_open) / today_open) * 100
    bias_ratio = ((current_price - ma20) / ma20) * 100

    stars = 0
    if current_price > ma20: stars += 1
    if ma20 > ma50: stars += 1
    if ma5 > ma10: stars += 1
    if current_price > today_open and today_vol > vol_ma5: stars += 1
    if 0 < bias_ratio < 8: stars += 1

    entry_price = max(ma10, low5) * 0.995
    stop_loss = low10 * 0.985
    
    # 🎯 AI 預測目標價計算 (結合 ATR 波動率)
    if stars >= 4: target_price = current_price + (atr14 * 2.5)
    elif stars == 3: target_price = current_price + (atr14 * 1.5)
    elif stars == 2: target_price = current_price + (atr14 * 0.8)
    else: target_price = ma20 # 弱勢股以月線為反彈目標

    return {
        "current_price": current_price,
        "actual_volume": int(today_vol / volume_divisor),
        "price_change": price_change,
        "bias_ratio": bias_ratio,
        "stars": stars,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_price": target_price,
        "short_prediction": get_short_prediction(stars),
    }

def draw_stock_chart(df, volume_unit, volume_divisor):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="日K線",
                                 increasing_line_color="red", increasing_fillcolor="red",
                                 decreasing_line_color="green", decreasing_fillcolor="green"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], mode="lines", name="5日線", line=dict(color="pink", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA10"], mode="lines", name="10日線", line=dict(color="cyan", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], mode="lines", name="20日線", line=dict(color="orange", width=1.8)), row=1, col=1)
    
    colors = ["red" if c >= o else "green" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"] / volume_divisor, name=f"成交量({volume_unit})", marker_color=colors), row=2, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False, height=540, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

def render_analysis(stock_info, volume_unit, volume_divisor, currency, subtitle, candidates=None):
    st.write("---")
    st.subheader(f"📊 【{stock_info['code']} {stock_info['name']}】{subtitle}")

    try:
        if candidates: used_symbol, raw = download_history_candidates(candidates, period="6mo")
        else:
            used_symbol = stock_info["yahoo_symbol"]
            raw = download_history_one(used_symbol, period="6mo")

        df = prepare_indicators(raw)
        if df.empty:
            st.error("此標的無足夠歷史資料。")
            return

        draw_stock_chart(df, volume_unit, volume_divisor)
        metrics = calc_metrics(df, volume_divisor)
        if metrics is None: return

        st.caption(f"🕒 資料最後更新時間：**{get_tw_time_text()}** (台灣時間)")
        
        # 數據面板升級
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("目前最新報價", f"{currency}{metrics['current_price']:.2f}", f"{metrics['price_change']:+.2f}%")
        col2.metric("🎯 AI 預測目標價", f"{currency}{metrics['target_price']:.2f}", help="依據近期 ATR 波動率計算的波段滿足點")
        col3.metric("📥 建議進場價", f"{currency}{metrics['entry_price']:.2f}", help="均線與近期低點之防守位")
        col4.metric("🚨 建議停損價", f"{currency}{metrics['stop_loss']:.2f}", help="跌破近期低點警戒線")

        st.write("### 📐 綜合技術評鑑與籌碼狀態")
        stars = metrics["stars"]
        c1, c2 = st.columns([1, 2])
        c1.info(f"**📈 今日成交量：** {metrics['actual_volume']:,} {volume_unit}")
        c2.success(f"**推薦星評：** {'⭐' * stars if stars > 0 else '💀 0星'} ({metrics['short_prediction']})")

    except Exception as e: st.error(f"分析失敗：{e}")


# =========================================================
# 台股全市場掃描核心
# =========================================================
def scan_tw_market_live(min_volume_lots, min_stars, market_scope, batch_size=80, max_scan=0):
    base_pool = TWSE_STOCKS if market_scope == "上市" else TPEX_STOCKS if market_scope == "上櫃" else TW_STOCKS
    
    # 用戶通常不知道 3000 張其實很多，這裡依據設定過濾
    active_pool = [s for s in base_pool if int(s.get("volume_shares", 0)) >= min_volume_lots * 1000]
    active_pool = sorted(active_pool, key=lambda x: int(x.get("volume_shares", 0)), reverse=True)
    if max_scan > 0: active_pool = active_pool[:int(max_scan)]

    result = []
    scanned = 0
    if not active_pool: return pd.DataFrame(), get_tw_time_text(), 0, len(base_pool)
    
    progress = st.progress(0, text=f"準備掃描 {len(active_pool)} 檔活躍股票……")

    for start_idx in range(0, len(active_pool), batch_size):
        batch = active_pool[start_idx:start_idx + batch_size]
        symbols = [s["yahoo_symbol"] for s in batch]
        try:
            bulk = yf.download(symbols, period="3mo", group_by="ticker", progress=False, auto_adjust=False, threads=True, timeout=20)
        except Exception: bulk = pd.DataFrame()

        for stock in batch:
            scanned += 1
            try:
                raw = bulk[stock["yahoo_symbol"]].dropna(how="all") if isinstance(bulk.columns, pd.MultiIndex) else bulk.dropna(how="all")
                df = prepare_indicators(raw)
                metrics = calc_metrics(df, volume_divisor=1000)
                if metrics is None or metrics["stars"] < min_stars: continue
                
                result.append({
                    "市場": stock.get("market", ""), "代號": stock["code"], "名稱": stock["name"],
                    "當前現價": round(metrics["current_price"], 2), "今日漲跌": f"{metrics['price_change']:+.2f}%",
                    "成交量(張)": f"{metrics['actual_volume']:,}", "🎯 預測目標價": round(metrics["target_price"], 2),
                    "技術星評": "⭐" * metrics["stars"], "型態短評": metrics["short_prediction"],
                    "乖離率": f"{metrics['bias_ratio']:+.2f}%", "深度分析": f"/?mode=tw&tw={stock['code']}",
                    "score": metrics["stars"],
                })
            except Exception: continue

        progress.progress(min((start_idx + len(batch)) / len(active_pool), 1.0), text=f"正在掃描：{scanned} / {len(active_pool)} 檔")
    progress.empty()
    
    if not result: return pd.DataFrame(), get_tw_time_text(), scanned, len(active_pool)
    df_result = pd.DataFrame(result).sort_values(["score", "成交量(張)"], ascending=False).drop(columns=["score"])
    return df_result, get_tw_time_text(), scanned, len(active_pool)


# =========================================================
# URL / Session 與側邊欄初始化
# =========================================================
st.session_state["fallback_refresh"] = 0 # 重置回調
mode_query = st.query_params.get("mode")
if "app_mode" not in st.session_state: st.session_state.app_mode = QUERY_TO_MODE.get(mode_query, MODE_MARKET)
if st.query_params.get("tw"): st.session_state.app_mode = MODE_TW_SEARCH
if st.query_params.get("us"): st.session_state.app_mode = MODE_US_SEARCH

with st.sidebar:
    st.header("👑 AI 股票智慧系統")
    current_index = MODE_OPTIONS.index(st.session_state.app_mode) if st.session_state.app_mode in MODE_OPTIONS else 0
    selected_mode = st.radio("請選擇功能模式：", MODE_OPTIONS, index=current_index, key="mode_radio")
    
    if selected_mode != st.session_state.app_mode:
        st.session_state.app_mode = selected_mode
        st.query_params["mode"] = MODE_TO_QUERY[selected_mode]
        if selected_mode != MODE_TW_SEARCH and "tw" in st.query_params: del st.query_params["tw"]
        if selected_mode != MODE_US_SEARCH and "us" in st.query_params: del st.query_params["us"]
        st.rerun()


# =========================================================
# 頁面 A：台股全市場自動監控
# =========================================================
if st.session_state.app_mode == MODE_MARKET:
    st.title("🌐 台股全市場 AI 自動監控")
    market_open, msg = is_tw_market_open()
    
    with st.sidebar:
        st.subheader("📊 掃描條件")
        # 💡 將預設門檻調低至 500 張，確保能掃到足夠數量的股票
        min_volume = st.number_input("最低成交量門檻（張）", min_value=500, max_value=50000, value=500, step=500)
        min_stars = st.slider("最低綜合技術星級", min_value=1, max_value=5, value=3)
        market_scope = st.selectbox("掃描範圍", ["上市+上櫃", "上市", "上櫃"], index=0)
        refresh_seconds = st.slider("自動刷新秒數", min_value=30, max_value=180, value=60, step=10)
        manual_refresh = st.button("🔄 立即重新掃描")

    if not market_open:
        st.warning(f"⏸️ {msg} (目前將執行單次靜態掃描，盤後不啟動瘋狂刷新以節省效能)")
        if manual_refresh: pass # 允許盤後手動按鈕更新
    else:
        st.info(f"⚡ 盤中自動刷新已啟動：每 {refresh_seconds} 秒掃描一次。")
        safe_autorefresh(refresh_seconds, key="market_auto")

    picks, update_time, scanned, total_candidates = scan_tw_market_live(min_volume, min_stars, market_scope)

    if picks.empty:
        st.warning(f"目前沒有符合條件的標的。（資料時間：{update_time}，共掃描 {scanned} 檔活絡股票）")
    else:
        st.success(f"🎉 掃描完成！從 {total_candidates} 檔活躍標的抓出精選強勢股（資料時間：{update_time}）")
        st.dataframe(picks, use_container_width=True, hide_index=True, column_config={"深度分析": st.column_config.LinkColumn("🔍 深度分析", display_text="👉 點我分析")})

# =========================================================
# 頁面 B：台股自主搜尋
# =========================================================
elif st.session_state.app_mode == MODE_TW_SEARCH:
    st.title("🔍 台股自主搜尋與量價分析")
    with st.sidebar:
        st.subheader("🔄 台股自動刷新")
        tw_auto = st.checkbox("開啟台股自動刷新", value=False)
        tw_refresh = st.slider("台股刷新秒數", min_value=15, max_value=120, value=30, step=5) if tw_auto else 30
        if st.button("🔄 重新抓取資料"):
            download_history_one.clear()
            download_history_candidates.clear()

    if tw_auto: safe_autorefresh(tw_refresh, key="tw_search_auto")

    default_idx = 0
    tw_query = st.query_params.get("tw")
    if tw_query:
        for i, s in enumerate(TW_STOCKS):
            if s["code"] == tw_query:
                default_idx = i
                break

    user_select = st.selectbox("👉 請選擇或輸入台股代號/名稱 (支援中文)：", TW_DISPLAY_OPTIONS, index=default_idx)
    selected_stock_info = next((s for s in TW_STOCKS if s["display_name"] == user_select), None)
    
    if selected_stock_info:
        tw_code = selected_stock_info["code"]
        if st.query_params.get("tw") != tw_code:
            st.query_params["mode"] = "tw"
            st.query_params["tw"] = tw_code

        render_analysis(selected_stock_info, volume_unit="張", volume_divisor=1000, currency="NT$", subtitle="技術與目標價分析", candidates=[selected_stock_info["yahoo_symbol"]])

# =========================================================
# 頁面 C：美股自主搜尋
# =========================================================
elif st.session_state.app_mode == MODE_US_SEARCH:
    st.title("🇺🇸 美股自主搜尋與量價分析")
    with st.sidebar:
        st.subheader("🔄 美股自動刷新")
        us_auto = st.checkbox("開啟美股自動刷新", value=False)
        us_refresh = st.slider("美股刷新秒數", min_value=15, max_value=120, value=30, step=5) if us_auto else 30

    if us_auto: safe_autorefresh(us_refresh, key="us_search_auto")

    quick_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "AMZN", "GOOGL", "META", "PLTR", "SOFI", "QQQ", "VOO"]
    default_us = clean_symbol(st.query_params.get("us", "NVDA")) or "NVDA"
    
    col1, col2 = st.columns([2, 1])
    with col1: us_input = st.text_input("👉 輸入美股 / ETF 代號：", value=default_us)
    with col2: quick_pick = st.selectbox("常用選擇：", ["不使用"] + quick_symbols)

    us_symbol = clean_symbol(quick_pick if quick_pick != "不使用" else us_input)
    if us_symbol and st.query_params.get("us") != us_symbol:
        st.query_params["mode"] = "us"
        st.query_params["us"] = us_symbol

    if us_symbol:
        stock = {"code": us_symbol, "name": us_symbol, "yahoo_symbol": us_symbol}
        render_analysis(stock, volume_unit="股", volume_divisor=1, currency="US$", subtitle="技術與目標價分析", candidates=[us_symbol])

# =========================================================
# 解決無套件時的自動刷新 (保險機制)
# =========================================================
if not HAS_AUTOREFRESH and st.session_state.get("fallback_refresh", 0) > 0:
    time.sleep(st.session_state["fallback_refresh"])
    st.session_state["fallback_refresh"] = 0
    st.rerun()
