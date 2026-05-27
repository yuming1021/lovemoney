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

TZ_TW = timezone(timedelta(hours=8))
def get_tw_time_text(): return datetime.now(TZ_TW).strftime("%Y-%m-%d %H:%M:%S")

# =========================================================
# YFinance 資料清洗機制 (防當機核心)
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
    # 上市
    try:
        res = requests.get(twse_url, headers=headers, timeout=15)
        if res.status_code == 200:
            for item in res.json():
                code = str(item.get("Code", "")).strip()
                if code.isdigit() and (len(code) == 4 or code.startswith("00")):
                    vol = str(item.get("TradeVolume", "0")).replace(",", "")
                    stocks.append({"code": code, "name": item.get("Name", "").strip(), "yahoo_symbol": f"{code}.TW", "display_name": f"{code} {item.get('Name', '').strip()}", "volume_shares": int(vol) if vol.isdigit() else 0, "market": "上市"})
    except: pass

    # 上櫃
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
    """短中長期完整走勢評語"""
    if stars == 5: return "🔥 **長線波段：極度看漲 (Strong Buy)**\n均線結構與量價動能完美，極高機率發動大波段行情，適合順勢積極操作。"
    if stars == 4: return "🚀 **長線波段：穩健看漲 (Buy)**\n多頭趨勢成型，長短天期均線皆給予強大支撐。建議等待回測不破再行進場。"
    if stars == 3: return "📈 **中線走勢：溫和偏多 (Accumulate)**\n目前已站上關鍵支撐，但動能尚未完全爆發。預期短期將震盪走高，可逢低少量佈局。"
    if stars == 2: return "➖ **短線型態：中性盤整 (Hold)**\n多空勢均力敵，技術面正處於區間震盪階段。建議靜待帶量突破方向再行動。"
    if stars == 1: return "📉 **短線型態：轉弱疑慮 (Underperform)**\n股價已跌破重要支撐，且
