# chiesi_budget.py
"""Streamlit dashboard – Chiesi Weekly Budget Δ€ (GAds vs Adform)"""

import os
import re
import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import create_engine


# ───────────────────── DB
@st.cache_resource
def get_engine():
    creds = st.secrets["postgres"]
    dsn = (
        f"postgresql://{creds['user']}:{creds['password']}"
        f"@{creds['host']}:{creds['port']}/{creds['database']}"
    )
    return create_engine(dsn)

def get_connection():
    return get_engine().connect()

@st.cache_data(show_spinner=True)
def load_budget_data() -> pd.DataFrame:
    engine = get_connection()
    df = pd.read_sql(
        "SELECT * FROM chiesi_weekly_budget "
        "WHERE period_type = 'week' ORDER BY period",
        engine,
    )

    # numerici
    meta = {"period_type", "snapshot_date", "is_final"}
    for c in df.columns:
        if c not in meta:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["week_label"] = df["period"].astype(int).apply(lambda w: f"Week {w}")

    # return only data until current week (until row containing end_date>= today)
    today = pd.Timestamp.today()
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")

    df["period"] = pd.to_numeric(df["period"], errors="coerce")
    df["period"] = df["period"].fillna(0).astype(int)
    df = df[df["start_date"] <= today]

    return df


# ───────────────────── helper – view per singolo canale
def single_channel_view(df: pd.DataFrame, brand: str, channel: str, color: str) -> None:
    col_name = f"{brand}_{channel}_delta"
    col_fc   = f"{col_name}_forecast"

    c1, c2, c3 = st.columns(3)

    latest = df.iloc[-1]
    c1.metric("Current Week", latest["week_label"])
    c2.metric("Δ € (Week)", f"{latest[col_name]:+.2f}")
    c3.metric("Forecast", f"{latest[col_fc]:+.2f}" if col_fc in df else "—")

    prev_week = df.iloc[-2]
    c1.metric("Previous Week", prev_week["week_label"])
    c2.metric("Δ € (Prev Week)", f"{prev_week[col_name]:+.2f}")

    # ─ Trend Δ € settimanale ──────────────────────────────────────────
    week_order = df["week_label"].tolist()

    st.subheader("Δ € per Week")
    # Linea dati principali
    line_chart = alt.Chart(df).mark_line(strokeWidth=4, color=color).encode(
        x=alt.X("week_label:N", sort=week_order, title="Week"),
        y=alt.Y(f"{col_name}:Q", title="Δ €"),
        tooltip=["week_label", alt.Tooltip(col_name, format="+.2f")],
    )
    
    # Linea orizzontale y=0 tratteggiata nera
    zero_line = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
        color='black',
        strokeDash=[5, 5],
        strokeWidth=1
    ).encode(
        y='y:Q'
    )
    
    # Combinazione grafici
    final_chart = (line_chart + zero_line).properties(height=320)
    
    st.altair_chart(final_chart, use_container_width=True)

    # data table
    tbl = df[["week_label", col_name]]
    st.dataframe(tbl.rename(columns={col_name: "Δ €"}), use_container_width=True)


# ───────────────────── main renderer
def render_budget_dashboard(df: pd.DataFrame,
                            primary_color="#0060E0",
                            logo_url="",
                            footer_logo_url="") -> None:

    current_week = pd.Timestamp.today().isocalendar().week
    df = df[df["period"] <= current_week]

    # ─ Header
    c_logo, c_title, _ = st.columns([1, 6, 1])
    with c_logo:
        if logo_url:
            st.image(logo_url, width=120)
    with c_title:
        st.markdown(
            f"<h1 style='text-align:center; font-family:Gotham HTF, sans-serif;'>"
            f"<span style='color:{primary_color};'>Chiesi</span> Budget Settimanale"
            f"</h1>",
            unsafe_allow_html=True,
        )

    # ─ brand & channel detection
    brand_channel = [
        re.match(r"^(.*?)_(gads|adform)_delta$", c)
        for c in df.columns if c.endswith("_delta")
    ]
    pairs = [m.groups() for m in brand_channel if m]
    brands   = sorted({b for b, _ in pairs})
    channels = sorted({c for _, c in pairs})

    if not pairs:
        st.error("No brand/channel columns found – check the ETL.")
        return

    # brand selector
    brand = st.selectbox("Brand", brands, index=0, format_func=lambda b: b.title())

    tabs = st.tabs([c.replace("gads", "Google Ads").title() for c in channels])

    # ► channel tabs
    for tab, ch in zip(tabs, channels):
        with tab:
            single_channel_view(df, brand, ch, primary_color)
