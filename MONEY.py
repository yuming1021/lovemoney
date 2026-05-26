import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
# 🔥 新增：用來校正台灣時區的套件
from datetime import datetime, timezone, timedelta

# 設定網頁版面為全螢幕寬度
st.set_page_config(layout="wide", page_title="AI 股票智慧系統", page_icon="📈")

# 設定台灣專屬時區 (UTC+8)
tz_tw = timezone(timedelta(hours=8))

def get_tw_time():
    return datetime.now(tz_tw).strftime('%H:%M:%S')

# ==========================================
# 0. 網頁切換魔法
# ==========================================
if "app_mode" not in st.session_state:
    st.session_state.app_mode = "🤖 全市場自動監控推薦"

query_params = st.query_params
url_code = query_params.get("code")

if url_code:
    st.session_state.app_mode = "🔍 個股自主搜尋分析"
    st.session_state.jump_to_code = url_code
    st.query_params.clear() 
    st.rerun()

# ==========================================
# 核心功能一：動態獲取真實市場名單
# ==========================================
@st.cache_data(ttl=3600)
def get_real_market_symbols():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=10)
        
        if res.status_code != 200:
            return [{"code": "2330", "name": "台積電", "yahoo_symbol": "2330.TW", "display_name": "2330 台積電", "volume_shares": 10000000},
                    {"code": "2317", "name": "鴻海", "yahoo_symbol": "2317.TW", "display_name": "2317 鴻海", "volume_shares": 10000000},
                    {"code": "0050", "name": "元大台灣50", "yahoo_symbol": "0050.TW", "display_name": "0050 元大台灣50", "volume_shares": 10000000}]
            
        data = res.json()
        stocks
