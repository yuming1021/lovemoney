import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 設定網頁版面為全螢幕寬度
st.set_page_config(layout="wide", page_title="AI 股票智慧系統", page_icon="📈")

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
        stocks_pool = []
        for item in data:
            code = item.get('Code', '')
            name = item.get('Name', '')
            if (len(code) == 4 and code.isdigit()) or code.startswith('00'):
                vol_str = str(item.get('TradeVolume', '0')).replace(',', '')
                volume_shares = int(vol_str) if vol_str.isdigit() else 0
                stocks_pool.append({
                    "code": code,
                    "name": name,
                    "yahoo_symbol": f"{code}.TW",
                    "display_name": f"{code} {name}",
                    "volume_shares": volume_shares
                })
        return stocks_pool if stocks_pool else []
    except Exception as e:
        return []

all_market_stocks = get_real_market_symbols()

# ==========================================
# 核心功能二：側邊欄多功能導航選單
# ==========================================
with st.sidebar:
    st.header("👑 AI 股票智慧系統")
    st.radio(
        "請選擇功能模式：",
        ["🤖 全市場自動監控推薦", "🔍 個股自主搜尋分析"],
        key="app_mode" 
    )
    st.write("---")

# ==========================================
# 模式 A：全市場自動監控推薦
# ==========================================
if st.session_state.app_mode == "🤖 全市場自動監控推薦":
    st.title("🌐 真實全市場 AI 自動掃描器")
    
    with st.sidebar:
        st.subheader("📊 篩選嚴格度設定")
        min_volume = st.number_input("最低成交量門檻 (張)", min_value=1000, max_value=50000, value=3000, step=1000)
        min_stars = st.slider("最低綜合技術星級", min_value=1, max_value=5, value=3)
        refresh_rate = st.slider("重新掃描間隔 (秒)", min_value=15, max_value=120, value=15)

    if "latest_picks" not in st.session_state:
        st.session_state.latest_picks = pd.DataFrame()
        st.session_state.last_update_time = "尚未更新"

    status_placeholder = st.empty()
    table_placeholder = st.empty()

    while True:
        if not st.session_state.latest_picks.empty:
            with table_placeholder.container():
                st.success(f"🎉 **最新精選強勢標的：** (最後更新時間: {st.session_state.last_update_time})")
                st.dataframe(
                    st.session_state.latest_picks,
                    use_container_width=True,
                    hide_index=True,
                    column_config={"深度分析": st.column_config.LinkColumn("🔍 深度分析", display_text="👉 點我分析")}
                )

        status_placeholder.info("⚡ 雲端引擎正在進行背景全市場打包下載，請稍候...")
        active_pool = [s for s in all_market_stocks if s["volume_shares"] > (min_volume * 1000)]
        recommended_list = []
        
        if active_pool:
            try:
                tickers_list = [s["yahoo_symbol"] for s in active_pool]
                bulk_data = yf.download(tickers_list, period="3mo", group_by='ticker', progress=False)
                
                for stock in active_pool:
                    symbol = stock["yahoo_symbol"]
                    if symbol in bulk_data.columns.levels[0]:
                        df_daily = bulk_data[symbol].dropna(how='all')
                        if df_daily.empty or len(df_daily) < 50:
                            continue
                        
                        df_daily['MA5'] = df_daily['Close'].rolling(window=5).mean()
                        df_daily['MA10'] = df_daily['Close'].rolling(window=10).mean()
                        df_daily['MA20'] = df_daily['Close'].rolling(window=20).mean()
                        df_daily['MA50'] = df_daily['Close'].rolling(window=50).mean()
                        df_daily['Vol_MA5'] = df_daily['Volume'].rolling(window=5).mean()
                        
                        current_price = df_daily['Close'].iloc[-1]
                        ma5 = df_daily['MA5'].iloc[-1]
                        ma10 = df_daily['MA10'].iloc[-1]
                        ma20 = df_daily['MA20'].iloc[-1]
                        ma50 = df_daily['MA50'].iloc[-1]
                        
                        if pd.isna(current_price) or pd.isna(ma50):
                            continue
                            
                        today_open = df_daily['Open'].iloc[-1]
                        today_vol = df_daily['Volume'].iloc[-1]
                        vol_ma5 = df_daily['Vol_MA5'].iloc[-1]
                        
                        price_change = ((current_price - today_open) / today_open) * 100
                        bias_ratio = ((current_price - ma20) / ma20) * 100
                        latest_volume = int(today_vol / 1000)
                        
                        # 計算純技術星級
                        star_count = 0
                        if current_price > ma20: star_count += 1
                        if ma20 > ma50: star_count += 1
                        if ma5 > ma10: star_count += 1
                        if current_price > today_open and today_vol > vol_ma5: star_count += 1
                        if 0 < bias_ratio < 8.0: star_count += 1
                            
                        if star_count >= min_stars:
                            if star_count >= 4: prediction = "🔥 飆股成型"
                            elif star_count == 3: prediction = "📈 趨勢轉強"
                            elif star_count == 2: prediction = "➖ 震盪打底"
                            else: prediction = "📉 格局偏弱"

                            recommended_list.append({
                                "代號": stock["code"],
                                "名稱": stock["name"],
                                "當前現價": round(current_price, 2),
                                "今日漲跌": f"{price_change:+.2f}%",
                                "技術星評": "⭐" * star_count,
                                "型態短評": prediction,
                                "乖離率": f"{bias_ratio:+.2f}%",
                                "深度分析": f"/?code={stock['code']}",
                                "score_raw": star_count
                            })
            except Exception as e:
                pass

        if recommended_list:
            df_picks = pd.DataFrame(recommended_list)
            st.session_state.latest_picks = df_picks.sort_values(by="score_raw", ascending=False).drop(columns=['score_raw'])
            st.session_state.last_update_time = time.strftime('%H:%M:%S')
            
            with table_placeholder.container():
                st.success(f"🎉 **最新精選強勢標的：** (最後更新時間: {st.session_state.last_update_time})")
                st.dataframe(
                    st.session_state.latest_picks,
                    use_container_width=True,
                    hide_index=True,
                    column_config={"深度分析": st.column_config.LinkColumn("🔍 深度分析", display_text="👉 點我分析")}
                )
        else:
            with table_placeholder.container():
                st.warning("⚠️ 目前市場沒有符合條件的標的，系統將持續監控。")
                
        status_placeholder.success(f"✅ 數據同步完成！準備進入下一次雲端運算。")
        time.sleep(refresh_rate)
        st.rerun()

# ==========================================
# 模式 B：個股自主搜尋分析
# ==========================================
elif st.session_state.app_mode == "🔍 個股自主搜尋分析":
    st.title("🔎 個股自主搜尋與量價分析")
    
    with st.sidebar:
        st.subheader("🔄 個股即時盯盤設定")
        auto_refresh_search = st.checkbox("開啟個股無縫自動刷新", value=False)
        if auto_refresh_search:
            search_refresh_rate = st.slider("個股刷新間隔 (秒)", min_value=15, max_value=60, value=15)
    
    if all_market_stocks:
        search_options = [s["display_name"] for s in all_market_stocks]
        
        default_idx = 0
        if "jump_to_code" in st.session_state and st.session_state.jump_to_code:
            for i, s in enumerate(all_market_stocks):
                if s["code"] == st.session_state.jump_to_code:
                    default_idx = i
                    break
            st.session_state.jump_to_code = None 

        user_select = st.selectbox("👉 請選擇或輸入您想查詢的標的 (支援搜尋 ETF)：", search_options, index=default_idx)
        selected_stock_info = next((s for s in all_market_stocks if s["display_name"] == user_select), None)
                
        if selected_stock_info:
            st.write("---")
            st.subheader(f"📊 【{selected_stock_info['code']} {selected_stock_info['name']}】 真實量價與綜合評鑑")
            
            chart_placeholder = st.empty()
            
            with chart_placeholder.container():
                try:
                    ticker = yf.Ticker(selected_stock_info["yahoo_symbol"])
                    df_chart = ticker.history(period="6mo")
                    
                    if not df_chart.empty and len(df_chart) >= 50:
                        df_chart['MA5'] = df_chart['Close'].rolling(window=5).mean()
                        df_chart['MA10'] = df_chart['Close'].rolling(window=10).mean()
                        df_chart['MA20'] = df_chart['Close'].rolling(window=20).mean()
                        df_chart['MA50'] = df_chart['Close'].rolling(window=50).mean()
                        df_chart['Vol_MA5'] = df_chart['Volume'].rolling(window=5).mean()
                        df_chart['Volume_K'] = df_chart['Volume'] / 1000 
                        
                        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
                        
                        fig.add_trace(go.Candlestick(
                            x=df_chart.index, open=df_chart['Open'], high=df_chart['High'],
                            low=df_chart['Low'], close=df_chart['Close'], name='日K線',
                            increasing_line_color='red', increasing_fillcolor='red',
                            decreasing_line_color='green', decreasing_fillcolor='green'
                        ), row=1, col=1)
                        
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA5'], mode='lines', name='5日線', line=dict(color='pink', width=1.5)), row=1, col=1)
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA10'], mode='lines', name='10日線', line=dict(color='cyan', width=1.5)), row=1, col=1)
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MA20'], mode='lines', name='20日線', line=dict(color='orange', width=2)), row=1, col=1)
                        
                        vol_colors = ['red' if row['Close'] >= row['Open'] else 'green' for index, row in df_chart.iterrows()]
                        fig.add_trace(go.Bar(
                            x=df_chart.index, y=df_chart['Volume_K'], marker_color=vol_colors, name='實際成交量(張)'
                        ), row=2, col=1)
                        
                        fig.update_layout(xaxis_rangeslider_visible=False, height=550, margin=dict(l=10, r=10, t=10, b=10), hovermode='x unified')
                        st.plotly_chart(fig, use_container_width=True)
                        
                        current_price = df_chart['Close'].iloc[-1]
                        actual_volume = int(df_chart['Volume'].iloc[-1] / 1000) 
                        ma5 = df_chart['MA5'].iloc[-1]
                        ma10 = df_chart['MA10'].iloc[-1]
                        ma20 = df_chart['MA20'].iloc[-1]
                        ma50 = df_chart['MA50'].iloc[-1]
                        today_open = df_chart['Open'].iloc[-1]
                        today_vol = df_chart['Volume'].iloc[-1]
                        vol_ma5 = df_chart['Vol_MA5'].iloc[-1]
                        bias_ratio = ((current_price - ma20) / ma20) * 100

                        star_count = 0
                        if current_price > ma20: star_count += 1
                        if ma20 > ma50: star_count += 1
                        if ma5 > ma10: star_count += 1
                        if current_price > today_open and today_vol > vol_ma5: star_count += 1
                        if 0 < bias_ratio < 8.0: star_count += 1
                        
                        if star_count == 5:
                            ai_pred = "🔥 **型態走勢：極度看漲 (Strong Buy)**\n\n目前技術面完美，均線呈現強勢多頭排列且伴隨成交量放大，預測短線將發動大波段行情。"
                        elif star_count == 4:
                            ai_pred = "🚀 **型態走勢：穩健看漲 (Buy)**\n\n趨勢已明顯轉強，長短天期均線皆給予支撐。預期將沿著 5 日線向上推升。"
                        elif star_count == 3:
                            ai_pred = "📈 **型態走勢：溫和偏多 (Accumulate)**\n\n目前已站上關鍵支撐，但動能尚未完全爆發。預期短期將震盪走高，可逢低佈局。"
                        elif star_count == 2:
                            ai_pred = "➖ **型態走勢：中性盤整 (Hold)**\n\n多空勢均力敵，技術面正處於區間震盪階段。建議靜待帶量突破方向再行動。"
                        elif star_count == 1:
                            ai_pred = "📉 **型態走勢：轉弱疑慮 (Underperform)**\n\n股價已跌破重要支撐，且均線開始下彎。短線面臨回檔壓力，建議退場觀望。"
                        else:
                            ai_pred = "🚨 **型態走勢：極度弱勢 (Strong Sell)**\n\n空頭格局完全成型，K線與成交量顯示賣壓沉重。極有可能持續向下探底，請避開！"

                        col_data, col_ai = st.columns([1, 1])
                        with col_data:
                            st.write("### 🗃️ 盤中真實數據面板")
                            st.info(f"**📈 實際總成交量：** {actual_volume:,} 張")
                            st.metric(label="目前最新報價", value=f"${round(current_price, 2)}")
                            st.metric(label="📥 建議安全進場價(月線)", value=f"${round(ma20 * 0.99, 2)}")
                            st.metric(label="🚨 建議果斷停損價(破月線)", value=f"${round(ma20 * 0.95, 2)}")

                        with col_ai:
                            st.write("### 📐 綜合技術評鑑")
                            st.subheader(f"推薦星評：{'⭐' * star_count if star_count > 0 else '💀 (0星)'}")
                            if star_count >= 4: st.success(ai_pred)
                            elif star_count == 3: st.info(ai_pred)
                            elif star_count == 2: st.warning(ai_pred)
                            else: st.error(ai_pred)
                                
                    else:
                        st.error("此標的目前無足夠歷史交易數據可供分析。")
                except Exception as e:
                    st.error(f"分析過程中發生錯誤: {e}")
            
            if auto_refresh_search:
                st.info(f"⏱️ 系統將在 {search_refresh_rate} 秒後自動為您更新 {selected_stock_info['name']} 的真實報價與成交量...")
                time.sleep(search_refresh_rate)
                st.rerun()
            else:
                st.caption("⏸️ 自動刷新已暫停。勾選左側「開啟個股無縫自動刷新」即可啟動即時盯盤。")
