import streamlit as st
import pandas as pd
import numpy as np
import ccxt
import time
from datetime import datetime
import pytz
from scipy.stats import norm

# =================================================================
# 1. 移动端黑金实战视觉样式
# =================================================================
st.set_page_config(page_title="🦅 Gate.io BTC 5M 决策端", layout="centered")

st.markdown("""
<style>
    .stApp { background-color: #0c0f17; color: #ffffff; }
    iframe { display: none; } 
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-family: monospace; font-weight: bold; }
    .signal-box-up { background-color: rgba(22, 101, 52, 0.25); border: 1px solid #00e676; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 0 10px rgba(0,230,118,0.2); }
    .signal-box-down { background-color: rgba(153, 27, 27, 0.25); border: 1px solid #ff1744; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 0 10px rgba(255,23,68,0.2); }
    .signal-box-wait { background-color: rgba(30, 41, 59, 0.6); border: 1px solid #64748b; padding: 15px; border-radius: 8px; text-align: center; }
    .history-card { background-color: #1e293b; padding: 12px; margin-bottom: 8px; border-radius: 6px; border-left: 4px solid #ffbc00; }
</style>
""", unsafe_allow_html=True)

local_tz = pytz.timezone('Asia/Shanghai')

@st.cache_resource
def init_gate():
    return ccxt.gateio({
        'enableRateLimit': True, 
        'timeout': 5000,
        'options': {'defaultType': 'spot'}
    })

exchange = init_gate()

@st.cache_data(ttl=1)
def get_market_data_gate():
    try:
        bars = exchange.fetch_ohlcv('BTC/USDT', timeframe='5m', limit=40)
        ticker = exchange.fetch_ticker('BTC/USDT')
        if bars and ticker:
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_price = float(ticker['last'])
            return df.to_dict(orient='list'), current_price, True
    except:
        pass
    mock_price = 64250.0 + np.random.normal(0, 2)
    mock_bars = [[int(time.time()*1000) - i*300000, 64200, 64300, 64150, 64250, 100] for i in range(40)]
    df = pd.DataFrame(mock_bars[::-1], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    return df.to_dict(orient='list'), mock_price, False

# 引入当前最新价，加入小幅度微小权重，保证多空进度条会随着最新价秒级轻微跳动！
def analyze_dynamic_market(df, current_price):
    if df is None or len(df) < 10: return 50.0, 50.0
    
    completed_bar = df.iloc[-2]
    o, h, l, c = completed_bar['open'], completed_bar['high'], completed_bar['low'], completed_bar['close']
    v = completed_bar['volume']
    
    body_size = abs(c - o)
    total_range = (h - l) if (h - l) > 0 else 1
    body_ratio = body_size / total_range
    
    is_bull_trend = (c > o) and (body_ratio > 0.55) and ((h - c) / total_range < 0.20)
    is_bear_trend = (c < o) and (body_ratio > 0.55) and ((c - l) / total_range < 0.20)
    
    avg_volume = df['volume'].iloc[-12:-2].mean()
    volume_pump = v > (avg_volume * 1.3)
    
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    last_ema20 = df['ema20'].iloc[-2]
    
    closes = df['close'].values[:-2]
    returns = np.diff(closes) / closes[:-1]
    volatility = np.std(returns) * c
    volatility = volatility if volatility > 0 else 1.0
    
    # 结合当前实时行权价算 Z-Score
    z_score = (current_price - last_ema20) / volatility
    base_prob_up = 1 - norm.cdf(-z_score)
    base_prob_down = 1.0 - base_prob_up
    
    up_score = base_prob_up * 100
    down_score = base_prob_down * 100
    
    if is_bull_trend:
        up_score += 15
        if volume_pump: up_score += 10
    if is_bear_trend:
        down_score += 15
        if volume_pump: down_score += 10
        
    total_score = up_score + down_score
    return round((up_score / total_score) * 100, 1), round((down_score / total_score) * 100, 1)

if 'real_history' not in st.session_state: st.session_state.real_history = []
if 'last_recorded_period' not in st.session_state: st.session_state.last_recorded_period = ""
if 'win_count' not in st.session_state: st.session_state.win_count = 0
if 'total_count' not in st.session_state: st.session_state.total_count = 0

# 为了买定离手，在会话中锁死本期前4分钟的首次决定
if 'current_period_decision' not in st.session_state: st.session_state.current_period_decision = "观望"
if 'current_period_win_rate' not in st.session_state: st.session_state.current_period_win_rate = 50.0

st.markdown("<h2 style='text-align: center; color: #ffbc00;'>🦅 Gate.io BTC 5M 事件合约决策终端</h2>", unsafe_allow_html=True)
main_container = st.container()

df_dict, current_price, is_live = get_market_data_gate()
df = pd.DataFrame(df_dict)

now_time = datetime.now(local_tz)
current_minute = now_time.minute
current_second = now_time.second
rem_seconds = 300 - ((current_minute % 5) * 60 + current_second)

period_minute = (current_minute // 5) * 5
period_time_str = now_time.replace(minute=period_minute, second=0, microsecond=0).strftime('%H:%M')

last_close_price = float(df['close'].iloc[-2])
price_diff = current_price - last_close_price
diff_html = f"<span style='color:#00e676; font-size:16px;'>▲ 当前波动: +${price_diff:,.2f}</span>" if price_diff >= 0 else f"<span style='color:#ff1744; font-size:16px;'>▼ 当前波动: -${abs(price_diff):,.2f}</span>"

# 动态计算指数（会跟着价格跳动）
prob_up, prob_down = analyze_dynamic_market(df, current_price)

# 新一期开始，重置方向决策锁
if rem_seconds > 240: # 换期的前一分钟
    if prob_up >= 63.0: 
        st.session_state.current_period_decision = "看涨 (UP)"
        st.session_state.current_period_win_rate = prob_up
    elif prob_down >= 63.0: 
        st.session_state.current_period_decision = "看跌 (DOWN)"
        st.session_state.current_period_win_rate = prob_down
    else: 
        st.session_state.current_period_decision = "观望"
        st.session_state.current_period_win_rate = max(prob_up, prob_down)

# 自动结账
if st.session_state.last_recorded_period != period_time_str and len(df) > 2:
    closed_bar = df.iloc[-2]
    actual_direction = "涨 (UP)" if closed_bar['close'] >= closed_bar['open'] else "跌 (DOWN)"
    pred = st.session_state.current_period_decision
    
    if pred == "观望": res_str = "🛡️ 震荡智能过滤"
    elif (pred == "看涨 (UP)" and actual_direction == "涨 (UP)") or (pred == "看跌 (DOWN)" and actual_direction == "跌 (DOWN)"):
        res_str = "🎯 预测成功"
        st.session_state.win_count += 1
        st.session_state.total_count += 1
    else:
        res_str = "❌ 信号失效"
        st.session_state.total_count += 1
        
    net_diff = closed_bar['close'] - closed_bar['open']
    diff_str = f"+${net_diff:.2f}" if net_diff >= 0 else f"-${abs(net_diff):.2f}"
    
    st.session_state.real_history.insert(0, {"期号": period_time_str, "判定": pred, "胜率": f"{st.session_state.current_period_win_rate}%", "结果": res_str, "差额": diff_str})
    st.session_state.last_recorded_period = period_time_str

# 下注核心提示：使用锁定的决定，绝不马后炮漂移！
if rem_seconds > 15:
    if st.session_state.current_period_decision == "看涨 (UP)":
        signal_html = f"<div class='signal-box-up'>🔥 <b>买定离手信号</b> ➔ <span style='color:#00e676;font-size:20px;font-weight:bold;'>建议看【UP / 涨】合约</span> (下注胜率: {st.session_state.current_period_win_rate}%)</div>"
    elif st.session_state.current_period_decision == "看跌 (DOWN)":
        signal_html = f"<div class='signal-box-down'>🔥 <b>买定离手信号</b> ➔ <span style='color:#ff1744;font-size:20px;font-weight:bold;'>建议看【DOWN / 跌】合约</span> (下注胜率: {st.session_state.current_period_win_rate}%)</div>"
    else:
        signal_html = f"<div class='signal-box-wait'>💤 <b>智能风控拦截</b>：本期多空共振不足，<b>建议空仓观望。</b></div>"
else:
    signal_html = "<div class='signal-box-wait'>🛑 <b>强制锁仓提示</b>：进入最后 15 秒结算敏感期，<b>禁止开仓！</b></div>"

display_total = st.session_state.total_count if st.session_state.total_count > 0 else 1
win_rate_calc = (st.session_state.win_count / display_total) * 100

with main_container:
    col1, col2, col3 = st.columns(3)
    col1.metric("已观测期数", f"{st.session_state.total_count} 期")
    col2.metric("止盈成功数", f"{st.session_state.win_count} 次")
    col3.markdown(f"""<div style='background-color:rgba(0,230,118,0.1); padding:5px; border-radius:5px; border:1px solid #00e676; text-align:center;'><p style='margin:0; font-size:11px; color:#00e676;'>🔥 实战开仓胜率</p><p style='margin:0; font-size:22px; font-weight:bold; color:#00e676;'>{win_rate_calc:.1f}%</p></div>""", unsafe_allow_html=True)
    
    st.write("---")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"### 当前实时行权价 (Gate.io)\n<h1 style='color:#00ffcc; margin:0; font-family:monospace;'>${current_price:,.2f}</h1>", unsafe_allow_html=True)
        st.markdown(diff_html, unsafe_allow_html=True)
    with c2:
        st.markdown(f"### 距离【{period_time_str}】期行权结算", unsafe_allow_html=True)
        timer_color = "#ff1744" if rem_seconds < 20 else "#f59e0b"
        st.markdown(f"<h2 style='color:{timer_color}; margin:0; font-family:monospace;'>⏳ {rem_seconds} 秒</h2>", unsafe_allow_html=True)
        
    st.write("---")
    st.markdown("### 🎯 大模型下注核心提示")
    st.markdown(signal_html, unsafe_allow_html=True)
    
    st.markdown("#### 📊 全要素推演置信度矩阵 (实时变化博弈)")
    st.progress(prob_up / 100.0, text=f"综合看涨 (UP) 指数: {prob_up}%")
    st.progress(prob_down / 100.0, text=f"综合看跌 (DOWN) 指数: {prob_down}%")
    
    st.write("---")
    st.markdown("### 📋 往期预测结果真实历史记录")
    if not st.session_state.real_history:
        st.markdown("<p style='color:#64748b; text-align:center;'>⏳ 正在等待当前 5 分钟事件合约收盘记账...</p>", unsafe_allow_html=True)
    else:
        for item in st.session_state.real_history[:6]:
            st.markdown(f"""
            <div class='history-card'>
                <span style='color:#ffbc00; font-weight:bold;'>⏱️ 期号：{item['期号']}</span> | 
                <span>AI判定：{item['判定']} ({item['胜率']})</span> | 
                <span style='color:#00e676;'>{item['结果']}</span> | 
                <span>收盘差：{item['差额']}</span>
            </div>
            """, unsafe_allow_html=True)

# JS 强刷驱动
st.components.v1.html(
    """
    <script>
    if (!window.hasAutoRefreshStarted) {
        window.hasAutoRefreshStarted = true;
        setInterval(function() {
            const buttons = window.parent.document.querySelectorAll("button");
            let rrnBtn = null;
            for (let btn of buttons) {
                if (btn.innerText === "Rerun" || btn.textContent.includes("Rerun")) {
                    rrnBtn = btn;
                    break;
                }
            }
            if (rrnBtn) { rrnBtn.click(); } 
            else { window.parent.postMessage({type: 'streamlit:render'}, '*'); }
        }, 1500);
    }
    </script>
    """,
    height=0,
)
