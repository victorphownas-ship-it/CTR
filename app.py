import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import pytz
from datetime import datetime
import requests

# ============================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================
st.set_page_config(page_title="Escáner CTR", layout="wide", page_icon="📈")
ny_tz = pytz.timezone('America/New_York')

# ============================================================
# SECRETOS DE TELEGRAM (Protegidos)
# ============================================================
# Streamlit leerá esto de st.secrets en la nube
try:
    TOKEN_TELEGRAM = st.secrets["TOKEN_TELEGRAM"]
    CHAT_ID_TELEGRAM = st.secrets["CHAT_ID_TELEGRAM"]
except:
    # Valores por defecto de prueba (reemplazar o configurar en nube)
    TOKEN_TELEGRAM = "TU_TOKEN_AQUI"
    CHAT_ID_TELEGRAM = "TU_CHAT_ID_AQUI"

if 'alertas_enviadas' not in st.session_state:
    st.session_state.alertas_enviadas = set()

def enviar_telegram(mensaje):
    if TOKEN_TELEGRAM == "TU_TOKEN_AQUI":
        return # No enviar si no hay token configurado
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    data = {"chat_id": CHAT_ID_TELEGRAM, "text": mensaje}
    try:
        requests.post(url, data=data)
    except Exception as e:
        st.sidebar.error(f"⚠️ Error Telegram: {e}")

# ============================================================
# DESCARGA DE DATOS CACHEADA
# ============================================================
@st.cache_data(ttl=300) # Se actualiza cada 5 mins
def get_data(ticker, interval, period):
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df = df.xs(ticker, level=1, axis=1)
        except Exception:
            df.columns = df.columns.droplevel(1)
            
    df.columns = [str(c).capitalize() for c in df.columns]
    cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
    df = df[cols].copy()
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert(ny_tz)
    else:
        df.index = df.index.tz_convert(ny_tz)
    return df

# ============================================================
# LÓGICA PRINCIPAL
# ============================================================
def procesar_y_graficar(ticker_symbol, tf_config, modo, indice_backtest=1):
    htf_interval = tf_config["htf"]
    ltf_interval = tf_config["ltf"]
    period = tf_config["period"]

    try:
        df_htf = get_data(ticker_symbol, htf_interval, period)
        df_ltf = get_data(ticker_symbol, ltf_interval, period)

        if len(df_htf) < 3:
            return None, f"[{htf_interval}] Datos HTF insuficientes"

        patrones_completados = []
        setup_vivo = None

        # A. BÚSQUEDA HISTÓRICA
        for i in range(2, len(df_htf) - 1):
            c1_o, c1_c = df_htf['Open'].iloc[i-2], df_htf['Close'].iloc[i-2]
            c1_h, c1_l = df_htf['High'].iloc[i-2], df_htf['Low'].iloc[i-2]
            c2_o, c2_c = df_htf['Open'].iloc[i-1], df_htf['Close'].iloc[i-1]
            c2_h, c2_l = df_htf['High'].iloc[i-1], df_htf['Low'].iloc[i-1]
            c3_o, c3_c = df_htf['Open'].iloc[i], df_htf['Close'].iloc[i]
            c3_h, c3_l = df_htf['High'].iloc[i], df_htf['Low'].iloc[i]

            c1_color = "Green" if c1_c > c1_o else "Red"
            c2_color = "Green" if c2_c > c2_o else "Red"
            c3_color = "Green" if c3_c > c3_o else "Red"

            if c1_color != c2_color and c3_color == c2_color:
                idx3_end = df_htf.index[i + 1]
                if c2_h > c1_h and c2_c <= c1_h and c3_color == "Red":
                    patrones_completados.append({
                        'fecha': df_htf.index[i], 'tipo': 'Bearish',
                        'c1_h': c1_h, 'c1_l': c1_l, 'c2_h': c2_h, 'c2_l': c2_l, 'c3_h': c3_h, 'c3_l': c3_l,
                        'idx1': df_htf.index[i-2], 'idx2': df_htf.index[i-1], 'idx3': df_htf.index[i],
                        'idx3_end': idx3_end, 'choch_level': c1_h, 'estado': 'completado'
                    })
                elif c2_l < c1_l and c2_c >= c1_l and c3_color == "Green":
                    patrones_completados.append({
                        'fecha': df_htf.index[i], 'tipo': 'Bullish',
                        'c1_h': c1_h, 'c1_l': c1_l, 'c2_h': c2_h, 'c2_l': c2_l, 'c3_h': c3_h, 'c3_l': c3_l,
                        'idx1': df_htf.index[i-2], 'idx2': df_htf.index[i-1], 'idx3': df_htf.index[i],
                        'idx3_end': idx3_end, 'choch_level': c1_l, 'estado': 'completado'
                    })

        ultimos_5_patrones = patrones_completados[-5:] if len(patrones_completados) >= 5 else patrones_completados

        # B. DETECCIÓN EN VIVO
        c1_o, c1_c, c1_h, c1_l = df_htf['Open'].iloc[-3], df_htf['Close'].iloc[-3], df_htf['High'].iloc[-3], df_htf['Low'].iloc[-3]
        c2_o, c2_c, c2_h, c2_l = df_htf['Open'].iloc[-2], df_htf['Close'].iloc[-2], df_htf['High'].iloc[-2], df_htf['Low'].iloc[-2]
        c3_h, c3_l = df_htf['High'].iloc[-1], df_htf['Low'].iloc[-1]

        c1_color = "Green" if c1_c > c1_o else "Red"
        c2_color = "Green" if c2_c > c2_o else "Red"

        if c1_color != c2_color:
            if c2_h > c1_h and c2_c <= c1_h:
                setup_vivo = {'fecha': df_htf.index[-1], 'tipo': 'Bearish', 'c1_h': c1_h, 'c1_l': c1_l, 'c2_h': c2_h, 'c2_l': c2_l, 'c3_h': c3_h, 'c3_l': c3_l, 'idx1': df_htf.index[-3], 'idx2': df_htf.index[-2], 'idx3': df_htf.index[-1], 'choch_level': c1_h, 'estado': 'en_formacion'}
            elif c2_l < c1_l and c2_c >= c1_l:
                setup_vivo = {'fecha': df_htf.index[-1], 'tipo': 'Bullish', 'c1_h': c1_h, 'c1_l': c1_l, 'c2_h': c2_h, 'c2_l': c2_l, 'c3_h': c3_h, 'c3_l': c3_l, 'idx1': df_htf.index[-3], 'idx2': df_htf.index[-2], 'idx3': df_htf.index[-1], 'choch_level': c1_l, 'estado': 'en_formacion'}

        # SELECCIÓN DEL TARGET
        target_plot = None
        if modo == "Backtest":
            if not ultimos_5_patrones: return None, f"[{htf_interval}] No hay patrones históricos."
            target_plot = ultimos_5_patrones[-indice_backtest] if len(ultimos_5_patrones) >= indice_backtest else ultimos_5_patrones[0]
        else:
            if setup_vivo:
                target_plot = setup_vivo
                identificador = (ticker_symbol, htf_interval, target_plot['fecha'])
                if identificador not in st.session_state.alertas_enviadas:
                    mensaje = f"🚨 SETUP CTR {target_plot['tipo'].upper()} EN VIVO 🚨\nActivo: {ticker_symbol}\nTemporalidad: {htf_interval}-{ltf_interval}\nPrecio CHOCH: {target_plot['choch_level']:.2f}"
                    enviar_telegram(mensaje)
                    st.session_state.alertas_enviadas.add(identificador)
            else:
                return None, None

        # C. RENDERIZADO
        if target_plot:
            estado_str = "COMPLETADO" if target_plot['estado'] == 'completado' else "EN FORMACIÓN"
            titulo = f"{htf_interval}-{ltf_interval} | {target_plot['tipo']} CTR | {estado_str} | Fecha V3: {target_plot['idx3'].strftime('%Y-%m-%d %H:%M')}"

            fig = make_subplots(rows=2, cols=1, shared_xaxes=False, vertical_spacing=0.1, subplot_titles=(f"HTF ({htf_interval})", f"LTF ({ltf_interval})"), row_heights=[0.4, 0.6])

            # HTF
            idx_start = df_htf.index.get_indexer([target_plot['idx1']])[0]
            df_htf_plot = df_htf.iloc[max(0, idx_start - 12):min(len(df_htf), idx_start + 12)]
            x_htf = df_htf_plot.index.tz_localize(None)

            fig.add_trace(go.Candlestick(x=x_htf, open=df_htf_plot['Open'], high=df_htf_plot['High'], low=df_htf_plot['Low'], close=df_htf_plot['Close'], increasing_line_color='#26a69a', decreasing_line_color='#ef5350'), row=1, col=1)

            x1, x2, x3 = target_plot['idx1'].tz_localize(None), target_plot['idx2'].tz_localize(None), target_plot['idx3'].tz_localize(None)
            y1, y2, y3 = (target_plot['c1_h'], target_plot['c2_h'], target_plot['c3_l']) if target_plot['tipo'] == 'Bearish' else (target_plot['c1_l'], target_plot['c2_l'], target_plot['c3_h'])

            fig.add_annotation(x=x1, y=y1, text="1", showarrow=True, row=1, col=1)
            fig.add_annotation(x=x2, y=y2, text="2 (Sweep)", showarrow=True, row=1, col=1)
            fig.add_annotation(x=x3, y=y3, text="3", showarrow=True, row=1, col=1)

            # LTF
            start_ltf = target_plot['idx2']
            mask = (df_ltf.index >= start_ltf) & (df_ltf.index < target_plot['idx3_end']) if target_plot['estado'] == 'completado' else (df_ltf.index >= start_ltf)
            df_ltf_plot = df_ltf.loc[mask].dropna()

            if len(df_ltf_plot) > 0:
                x_ltf = df_ltf_plot.index.tz_localize(None)
                fig.add_trace(go.Candlestick(x=x_ltf, open=df_ltf_plot['Open'], high=df_ltf_plot['High'], low=df_ltf_plot['Low'], close=df_ltf_plot['Close'], increasing_line_color='#26a69a', decreasing_line_color='#ef5350'), row=2, col=1)
                
                line_color = "#ef5350" if target_plot['tipo'] == 'Bearish' else "#26a69a"
                fig.add_hline(y=target_plot['choch_level'], line_color=line_color, line_width=2, annotation_text="CHOCH/BOS", row=2, col=1)
                fig.add_vrect(x0=x3, x1=x_ltf[-1], fillcolor=line_color, opacity=0.1, layer="below", row=2, col=1)

            fig.update_layout(height=700, template="plotly_dark", showlegend=False, xaxis_rangeslider_visible=False, xaxis2_rangeslider_visible=False)
            return fig, titulo
            
    except Exception as e:
        return None, f"Error en {htf_interval}: {str(e)}"

# ============================================================
# INTERFAZ DE USUARIO (UI)
# ============================================================
st.title("📈 Escáner de Patrones CTR")

with st.sidebar:
    st.header("Configuración")
    activo_raw = st.selectbox("Activo", ["^GSPC (S&P 500 Index)", "^NDX (Nasdaq 100 Index)", "NQ=F (Nasdaq Futuros)", "GC=F (Oro Futuros)", "ES=F (S&P 500 Futuros)"])
    ticker_symbol = activo_raw.split(" ")[0]
    
    modo = st.radio("Modo de Ejecución", ["Backtest (Histórico)", "En Vivo (Monitoreo)"])
    
    if modo == "Backtest (Histórico)":
        temp_backtest = st.selectbox("Temporalidad", ["1D - 15m", "4H - 5m", "1H - 1m"])
        patron_idx = st.selectbox("Patrón Histórico", ["1 (El mas reciente)", "2", "3", "4", "5 (El mas antiguo)"])
        indice_backtest = int(patron_idx.split(" ")[0])
    
    if st.button("🔄 Refrescar / Ejecutar"):
        st.cache_data.clear()

pares_temporales = [
    {"htf": "1d", "ltf": "15m", "period": "60d"},
    {"htf": "4h", "ltf": "5m", "period": "60d"},
    {"htf": "1h", "ltf": "1m", "period": "7d"}
]

# Ejecución según modo
if modo == "Backtest (Histórico)":
    st.subheader(f"Modo Backtest | Activo: {activo_raw}")
    tf_dict = {"1D - 15m": pares_temporales[0], "4H - 5m": pares_temporales[1], "1H - 1m": pares_temporales[2]}
    tf_selected = tf_dict[temp_backtest]
    
    with st.spinner("Buscando patrones históricos..."):
        fig, titulo = procesar_y_graficar(ticker_symbol, tf_selected, "Backtest", indice_backtest)
        if fig:
            st.success(titulo)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(titulo or "No se encontraron patrones.")

else:
    st.subheader(f"🔴 Escáner En Vivo | Activo: {activo_raw}")
    st.info(f"Última actualización: {datetime.now(ny_tz).strftime('%Y-%m-%d %H:%M:%S')} (La app se refrescará cada 5 min)")
    
    setups_encontrados = 0
    with st.spinner("Escaneando todas las temporalidades..."):
        for tf in pares_temporales:
            fig, titulo = procesar_y_graficar(ticker_symbol, tf, "Vivo")
            if fig:
                setups_encontrados += 1
                st.success(titulo)
                st.plotly_chart(fig, use_container_width=True)
                
    if setups_encontrados == 0:
        st.write("✔️ No hay setups CTR activos en este momento.")

    # Loop de auto-refresco (Streamlit way)
    time.sleep(300)
    st.rerun()
