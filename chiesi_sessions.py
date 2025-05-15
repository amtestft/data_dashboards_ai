# chiesi_sessions.py
"""Streamlit dashboard – Chiesi Weekly Sessions (YTD Δ & Paid Contribution)"""

import os
import re
import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import create_engine
import plotly.express as px
import plotly.graph_objects as go


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
def load_sessions_data() -> pd.DataFrame:
    engine = get_connection()
    df = pd.read_sql(
        "SELECT * FROM chiesi_weekly_sessions "
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


# ───────────────────── helper – brand view
def confronto_view(df: pd.DataFrame, brands: list[str]) -> None:
    st.header("Confronto tra Brand")

    # Ordine delle settimane
    week_order = df["week_label"].tolist()

    # ─────────────────────── STACKED BAR – Paid Contribution %
    contr_cols = [f"{b}_paid_contribution" for b in brands]
    contr_df = df[["week_label"] + contr_cols].copy()
    contr_df = contr_df.melt(id_vars="week_label", 
                              var_name="Brand", 
                              value_name="Contribution")
    contr_df["Brand"] = contr_df["Brand"].str.replace("_paid_contribution", "", regex=False).str.upper()

    st.subheader("Paid Contribution (%) – Colonne impilate")

    fig1 = px.bar(
        contr_df,
        x="week_label",
        y="Contribution",
        color="Brand",
        title="Paid Contribution %",
        labels={"week_label": "Settimana", "Contribution": "Percentuale"},
    )
    fig1.update_layout(barmode="stack", height=450)
    fig1.update_yaxes(tickformat=".0%", title="%")
    st.plotly_chart(fig1, use_container_width=True)

    # ─────────────────────── CLUSTERED BAR – YTD Δ
    ytd_cols = [f"{b}_ytd_delta" for b in brands]
    ytd_df = df[["week_label"] + ytd_cols].copy()
    ytd_df = ytd_df.melt(id_vars="week_label", 
                         var_name="Brand", 
                         value_name="Delta")
    ytd_df["Brand"] = ytd_df["Brand"].str.replace("_ytd_delta", "", regex=False).str.upper()

    st.subheader("YTD Delta settimanale – Colonne affiancate")

    fig2 = px.bar(
        ytd_df,
        x="week_label",
        y="Delta",
        color="Brand",
        barmode="group",
        title="YTD Delta settimanale",
        labels={"week_label": "Settimana", "Delta": "Delta"}
    )
    fig2.update_layout(height=450)
    st.plotly_chart(fig2, use_container_width=True)




def brand_view(df: pd.DataFrame, brand: str, color: str) -> None:
    ytd_col   = f"{brand}_ytd_delta"
    contr_col = f"{brand}_paid_contribution"

    c1, c2, c3 = st.columns(3)
    
    latest = df.iloc[-1]
    c1.metric("Current Week", latest["week_label"])
    c2.metric("YTD Δ", f"{latest[ytd_col]:+.0f}")
    c3.metric("Paid Contribution", f"{latest[contr_col]:.2%}")

    prev_week = df.iloc[-2]
    c1.metric("Previous Week", prev_week["week_label"])
    c2.metric("YTD Δ € (Prev Week)", f"{prev_week[ytd_col]:+.0f}")
    c3.metric("Paid Contribution (Prev Week)", f"{prev_week[contr_col]:+.2%}")

    

    week_order = df["week_label"].tolist()

    c1_, c2_ = st.columns(2)
    with c1_:
        st.subheader("YTD Δ Trend")
        # Linea dati principali (YTD Δ)
        line_chart_ytd = alt.Chart(df).mark_line(strokeWidth=4, color=color).encode(
            x=alt.X("week_label:N", sort=week_order),
            y=alt.Y(f"{ytd_col}:Q", title="YTD Δ"),
            tooltip=["Week", ytd_col],
        )
        
        # Linea orizzontale y=0 tratteggiata nera
        zero_line_ytd = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
            color='black',
            strokeDash=[5, 5],
            strokeWidth=1
        ).encode(
            y='y:Q'
        )
        
        # Combinazione grafici
        final_chart_ytd = (line_chart_ytd + zero_line_ytd).properties(height=340)
        
        st.altair_chart(final_chart_ytd, use_container_width=True)

    with c2_:
        st.subheader("Paid Contribution %")
        st.altair_chart(
            alt.Chart(df)
            .mark_line(strokeWidth=4, color=color)
            .encode(
                x=alt.X("week_label:N", sort=week_order),
                y=alt.Y(contr_col + ":Q", title="Contribution", axis=alt.Axis(format="%")),
                tooltip=["week_label", alt.Tooltip(contr_col, format=".2%")],
            )
            .properties(height=340),
            use_container_width=True,
        )

# ───────────────────── main renderer
def render_sessions_dashboard(df: pd.DataFrame,
                              primary_color="#00985F",
                              logo_url="") -> None:

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
            f"<span style='color:{primary_color};'>Chiesi</span> Sessioni Settimanali"
            f"</h1>",
            unsafe_allow_html=True,
        )

    # brand detection
    brands = sorted({
        re.sub(r"_ytd_delta$", "", c) for c in df.columns if c.endswith("_ytd_delta")
    })
    if not brands:
        st.error("Brand columns not found – check the ETL.")
        return

    view_mode = st.radio("Modalità di visualizzazione", ["Singolo Brand", "Confronto"], horizontal=True)

    if view_mode == "Singolo Brand":
        brand = st.selectbox("Brand", brands, index=0, format_func=lambda b: b.title())
        brand_view(df, brand, primary_color)
    else:
        confronto_view(df, brands)
