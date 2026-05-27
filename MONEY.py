import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timezone, timedelta

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

# =========================================================
# 基本設定與時間
# =========================================================
st.set_page_config(page_title="AI 股票智慧系統", page_icon="📈", layout="wide")

# 隱藏預設選單防止干擾
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

TZ_TW = timezone(timedelta(hours=8))
def get_tw_time_text(): return datetime.now(TZ_TW).strftime("%Y-%m-%d %H:%M:%S")

# =========================================================
# YFinance 資料清洗機制
# =========================================================
def safe_history(symbol, period="6mo"):
    try:
        df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
        if df.empty: return df
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]
        return df
    except: return pd.DataFrame()

def extract_single_from_bulk(bulk, symbol):
    if bulk is None or bulk.empty: return pd.DataFrame()
    try:
        if isinstance(bulk.columns, pd.MultiIndex):
            if symbol in bulk.columns.get_level_values(0): df = bulk[symbol]
            elif symbol in bulk.columns.get_level_values(1): df = bulk.xs(symbol, level=1, axis=1)
            else: return pd.DataFrame()
        else:
            df = bulk
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()]
        return df.dropna(how="all")
    except: return pd.DataFrame()

# =========================================================
# 獲取台股全市場名單
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_tw_market_symbols():
    headers = {"User-Agent": "Mozilla/5.0"}
    twse_url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    tpex_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    
    stocks = []
    try:
        res = requests.get(twse_url, headers=headers, timeout=15)
        if res.status_code == 200:
            for item in res.json():
                code = str(item.get("Code", "")).strip()
                if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                    vol = str(item.get("TradeVolume", "0")).replace(",", "")
                    stocks.append({"code": code, "name": item.get("Name", "").strip(), "yahoo_symbol": f"{code}.TW", "display_name": f"{code} {item.get('Name', '').strip()}", "volume_shares": int(vol) if vol.isdigit() else 0, "market": "上市"})
    except: pass

    try:
        res = requests.get(tpex_url, headers=headers, timeout=15)
        if res.status_code == 200:
            for item in res.json():
                code = str(item.get("SecuritiesCompanyCode", item.get("代號", ""))).strip()
                if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                    name = str(item.get("CompanyName", item.get("名稱", ""))).strip()
                    vol = str(item.get("TradingVolume", item.get("成交股數", "0"))).replace(",", "")
                    stocks.append({"code": code, "name": name, "yahoo_symbol": f"{code}.TWO", "display_name": f"{code} {name}", "volume_shares": int(float(vol)) if vol.replace(".","",1).isdigit() else 0, "market": "上櫃"})
    except: pass
    return stocks

TW_STOCKS = get_tw_market_symbols()
TW_DISPLAY_OPTIONS = [s["display_name"] for s in TW_STOCKS]

# =========================================================
# 資料下載與技術分析快取
# =========================================================
@st.cache_data(ttl=45, show_spinner=False)
def download_history_one(yahoo_symbol, period="6mo"):
    return yf.Ticker(yahoo_symbol).history(period=period, auto_adjust=False)

@st.cache_data(ttl=45, show_spinner=False)
def download_history_candidates(candidates, period="6mo"):
    for symbol in candidates:
        try:
            df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            if df is not None and not df.empty and len(df.dropna(how="all")) >= 50:
                return symbol, df
        except Exception:
            continue
    return candidates[0] if candidates else "", pd.DataFrame()

# =========================================================
# 指標運算與 AI 預測邏輯
# =========================================================
def prepare_indicators(df):
    if df is None or len(df) < 20: return pd.DataFrame()
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA10"] = df["Close"].rolling(10).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["Vol_MA5"] = df["Volume"].rolling(5).mean()
    df["Low5"] = df["Low"].rolling(5).min()
    df["Low10"] = df["Low"].rolling(10).min()
    
    prev_close = df["Close"].shift(1)
    df["TR"] = pd.concat([df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()], axis=1).max(axis=1)
    df["ATR14"] = df["TR"].rolling(14).mean()
    return df

def get_long_prediction(stars):
    if stars == 5: return "🔥 **長線波段：極度看漲 (Strong Buy)**\n均線結構與量價動能完美，極高機率發動大波段行情，適合順勢積極操作。"
    if stars == 4: return "🚀 **長線波段：穩健看漲 (Buy)**\n多頭趨勢成型，長短天期均線皆給予強大支撐。建議等待回測不破再行進場。"
    if stars == 3: return "📈 **中線走勢：溫和偏多 (Accumulate)**\n目前已站上關鍵支撐，但動能尚未完全爆發。預期短期將震盪走高，可逢低少量佈局。"
    if stars == 2: return "➖ **短線型態：中性盤整 (Hold)**\n多空勢均力敵，技術面正處於區間震盪階段。建議靜待帶量突破方向再行動。"
    if stars == 1: return "📉 **短線型態：轉弱疑慮 (Underperform)**\n股價已跌破重要支撐，且均線開始下彎。短線面臨較大回檔壓力，建議退場觀望。"
    return "🚨 **長線波段：極度弱勢 (Strong Sell)**\n空頭格局完全成型，K線與成交量顯示賣壓沉重。極有可能持續向下探底，請嚴格避開！"

def calc_metrics(df, volume_divisor):
    if df is None or len(df) < 20: return None
    latest = df.iloc[-1]
    prev_day = df.iloc[-2]
    
    try:
        current_price = float(latest["Close"])
        today_open = float(latest["Open"])
        today_vol = float(latest["Volume"])
        prev_close = float(prev_day["Close"])
        
        ma5 = float(latest["MA5"])
        ma10 = float(latest["MA10"])
        ma20 = float(latest["MA20"])
        ma50 = float(latest["MA50"])
        vol_ma5 = float(latest["Vol_MA5"])
        low5 = float(latest["Low5"])
        low10 = float(latest["Low10"])
        atr14 = float(latest["ATR14"]) if not pd.isna(latest["ATR14"]) else (current_price * 0.02)
    except: return None

    if any(pd.isna(x) for x in [current_price, prev_close, ma20]) or ma20 == 0 or prev_close == 0: return None

    price_change = ((current_price - prev_close) / prev_close) * 100
    bias_ratio = ((current_price - ma20) / ma20) * 100

    stars = sum([current_price > ma20, ma20 > ma50, ma5 > ma10, (current_price > today_open and today_vol > vol_ma5), (0 < bias_ratio < 8)])

    entry_price = max(ma10, low5) * 0.995
    stop_loss = low10 * 0.985
    
    if stars >= 4: target_price = current_price + (atr14 * 2.5)
    elif stars == 3: target_price = current_price + (atr14 * 1.5)
    elif stars == 2: target_price = current_price + (atr14 * 0.8)
    else: target_price = ma20 

    preds = {0:"🚨 弱勢", 1:"📉 轉弱", 2:"➖ 盤整", 3:"📈 偏多", 4:"🚀 穩健", 5:"🔥 飆股"}
    
    return {
        "current_price": current_price, "actual_volume": int(today_vol / volume_divisor),
        "price_change": price_change, "bias_ratio": bias_ratio, "stars": stars,
        "entry_price": entry_price, "stop_loss": stop_loss, "target_price": target_price,
        "short_prediction": preds.get(stars, "➖ 盤整"),
        "long_prediction": get_long_prediction(stars)
    }

# =========================================================
# UI 與繪圖
# =========================================================
def draw_stock_chart(df, volume_unit, volume_divisor):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="日K線", increasing_line_color="red", increasing_fillcolor="red", decreasing_line_color="green", decreasing_fillcolor="green"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA5"], mode="lines", name="5日線", line=dict(color="pink", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA10"], mode="lines", name="10日線", line=dict(color="cyan", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], mode="lines", name="20日線", line=dict(color="orange", width=1.8)), row=1, col=1)
    
    colors = ["red" if c >= o else "green" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"] / volume_divisor, name=f"成交量({volume_unit})", marker_color=colors), row=2, col=1)
    fig.update_layout(xaxis_rangeslider_visible=False, height=550, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

def render_analysis(stock_info, volume_unit, volume_divisor, currency, candidates=None):
    st.subheader(f"📊 【{stock_info['name']}】量價與 AI 預測")
    
    raw = pd.DataFrame()
    if candidates:
        for sym in candidates:
            temp_df = safe_history(sym)
            if not temp_df.empty and len(temp_df) >= 20:
                raw = temp_df
                break
    else:
        raw = safe_history(stock_info["yahoo_symbol"])

    df = prepare_indicators(raw)
    metrics = calc_metrics(df, volume_divisor)
    
    if metrics is None:
        st.error(f"無法取得 {stock_info['name']} 的歷史資料，請確認代號是否正確。")
        return

    draw_stock_chart(df, volume_unit, volume_divisor)
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("目前最新報價", f"{currency}{metrics['current_price']:.2f}", f"{metrics['price_change']:+.2f}%")
    c2.metric("🎯 AI 預測目標價", f"{currency}{metrics['target_price']:.2f}")
    c3.metric("📥 建議進場價", f"{currency}{metrics['entry_price']:.2f}")
    c4.metric("🚨 建議停損價", f"{currency}{metrics['stop_loss']:.2f}")

    st.write("### 📐 綜合技術評鑑與 AI 點評")
    c_left, c_right = st.columns([1, 1])
    c_left.info(f"**📈 今日總成交量：** {metrics['actual_volume']:,} {volume_unit}")
    c_right.success(f"**🤖 綜合技術星評：** {'⭐' * metrics['stars'] if metrics['stars'] > 0 else '💀 0星'} ({metrics['short_prediction']})")
    
    if metrics['stars'] >= 4: st.success(metrics['long_prediction'])
    elif metrics['stars'] == 3: st.info(metrics['long_prediction'])
    elif metrics['stars'] == 2: st.warning(metrics['long_prediction'])
    else: st.error(metrics['long_prediction'])

# =========================================================
# 全市場掃描核心邏輯
# =========================================================
def scan_tw_market(min_volume_lots, min_stars, batch_size=80):
    active_pool = [s for s in TW_STOCKS if s.get("volume_shares", 0) >= min_volume_lots * 1000]
    active_pool = sorted(active_pool, key=lambda x: x.get("volume_shares", 0), reverse=True)
    
    if not active_pool: return pd.DataFrame()
    
    result = []
    progress = st.progress(0, text=f"準備掃描 {len(active_pool)} 檔活躍股票...")

    for start_idx in range(0, len(active_pool), batch_size):
        batch = active_pool[start_idx:start_idx + batch_size]
        symbols = [s["yahoo_symbol"] for s in batch]
        
        try: bulk = yf.download(symbols, period="3mo", group_by="ticker", progress=False, auto_adjust=False, threads=True, timeout=15)
        except: bulk = pd.DataFrame()

        for stock in batch:
            raw = extract_single_from_bulk(bulk, stock["yahoo_symbol"])
            df = prepare_indicators(raw)
            metrics = calc_metrics(df, volume_divisor=1000)
            
            if metrics and metrics["stars"] >= min_stars:
                result.append({
                    "市場": stock.get("market", ""), "代號": stock["code"], "名稱": stock["name"],
                    "當前現價": round(metrics["current_price"], 2), "今日漲跌": f"{metrics['price_change']:+.2f}%",
                    "成交量(張)": metrics['actual_volume'], "🎯 目標價": round(metrics["target_price"], 2),
                    "技術星評": "⭐" * metrics["stars"], "型態短評": metrics["short_prediction"],
                    "乖離率": f"{metrics['bias_ratio']:+.2f}%", "score": metrics["stars"],
                })

        progress.progress(min((start_idx + len(batch)) / len(active_pool), 1.0))
    progress.empty()
    
    if result: return pd.DataFrame(result).sort_values(["score", "成交量(張)"], ascending=False).drop(columns=["score"])
    return pd.DataFrame()

# =========================================================
# 側邊欄與頁面導航
# =========================================================
if "app_mode" not in st.session_state: st.session_state.app_mode = "🤖 全市場自動監控推薦"

with st.sidebar:
    st.header("👑 AI 股票智慧系統")

    # 💡 亮點新增：全局強制刷新大按鈕
    if st.button("🔄 立即強制全面刷新", type="primary", use_container_width=True):
        get_tw_market_symbols.clear()
        download_history_one.clear()
        download_history_candidates.clear()
        st.rerun()
        
    st.write("---")
    st.session_state.app_mode = st.radio("請選擇功能模式：", ["🤖 全市場自動監控推薦", "🔍 個股自主搜尋分析", "🇺🇸 美股自主搜尋分析"])
    st.write("---")

# =========================================================
# 模式 A: 全市場自動監控
# =========================================================
if st.session_state.app_mode == "🤖 全市場自動監控推薦":
    st.title("🌐 台股全市場 AI 自動監控")
    st.caption(f"🕒 資料最後更新時間：{get_tw_time_text()}")

    with st.sidebar:
        st.subheader("📊 掃描設定")
        min_volume = st.number_input("最低成交量門檻(張)", min_value=500, max_value=50000, value=1000, step=500)
        min_stars = st.slider("最低綜合技術星級", min_value=1, max_value=5, value=3)
        refresh_seconds = st.slider("自動刷新秒數", min_value=30, max_value=120, value=60, step=10)

    if HAS_AUTOREFRESH: st_autorefresh(interval=refresh_seconds * 1000, key="market_auto")

    picks = scan_tw_market(min_volume, min_stars)
    
    if picks.empty:
        st.warning("目前沒有符合條件的標的。")
    else:
        st.success("🎉 AI 最新精選強勢標的")
        st.dataframe(picks, use_container_width=True, hide_index=True)

# =========================================================
# 模式 B: 台股搜尋
# =========================================================
elif st.session_state.app_mode == "🔍 個股自主搜尋分析":
    st.title("🔍 台股自主搜尋與量價分析")
    
    with st.sidebar:
        st.subheader("🔄 自動刷新設定")
        tw_auto = st.checkbox("開啟自動刷新", value=False)
        if tw_auto:
            tw_refresh = st.slider("刷新秒數", 15, 120, 30, step=5)
            st_autorefresh(interval=tw_refresh * 1000, key="tw_auto")
    
    user_input = st.text_input("👉 請輸入台股代號 (如 2330, 00929) 或中文名稱：", value="2330").strip()
    
    if user_input:
        stock_info = None
        candidates = []
        
        if user_input.isdigit():
            stock_info = {"code": user_input, "name": user_input, "yahoo_symbol": f"{user_input}.TW"}
            candidates = [f"{user_input}.TW", f"{user_input}.TWO"]
            for s in TW_STOCKS:
                if s["code"] == user_input:
                    stock_info["name"] = s["name"]
                    break
        else:
            for s in TW_STOCKS:
                if user_input in s["name"] or user_input in s["code"]:
                    stock_info = s
                    break

        if stock_info:
            st.caption(f"🕒 資料最後更新時間：{get_tw_time_text()}")
            render_analysis(stock_info, "張", 1000, "NT$", candidates=candidates)
        else:
            st.warning(f"找不到名稱包含「{user_input}」的股票，請嘗試輸入代號。")

# =========================================================
# 模式 C: 美股搜尋
# =========================================================
elif st.session_state.app_mode == "🇺🇸 美股自主搜尋分析":
    st.title("🇺🇸 美股自主搜尋與量價分析")
    
    with st.sidebar:
        st.subheader("🔄 自動刷新設定")
        us_auto = st.checkbox("開啟自動刷新", value=False)
        if us_auto:
            us_refresh = st.slider("刷新秒數", 15, 120, 30, step=5)
            st_autorefresh(interval=us_refresh * 1000, key="us_auto")

    us_input = st.text_input("👉 輸入美股 / ETF 代號 (例如 NVDA, TSLA, QQQ)：", "NVDA").strip().upper()
    
    if us_input:
        stock_info = {"code": us_input, "name": us_input, "yahoo_symbol": us_input}
        st.caption(f"🕒 資料最後更新時間：{get_tw_time_text()}")
        render_analysis(stock_info, "股", 1, "US$")
