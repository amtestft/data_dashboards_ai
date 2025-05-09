# TTT_dashboard.py
"""Streamlit dashboard for TTT (Costo-Per-Servizio) weekly KPIs – multi-channel."""

import os
import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import create_engine

# ──────────────────────────────────────────────────────────────────────────────
# DB connection
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# Data loading
# ──────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=True)
def load_ttt_data() -> pd.DataFrame:
    engine = get_connection()
    df = pd.read_sql(
        "SELECT * FROM ttt_weekly_cps "
        "WHERE period_type = 'week' ORDER BY period",
        engine,
    )

    # Cast numerici (tutto ciò che NON è chisura/logica)
    skip = {"period_type", "snapshot_date", "is_final"}
    for col in df.columns:
        if col not in skip:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Etichetta “Week 12”
    df["week_label"] = df["period"].astype(int).apply(lambda x: f"Week {x}")

    # Calcola la settimana corrente secondo calendario ISO (inizia il lunedì)
    today = pd.Timestamp.today()
    current_week = today.isocalendar().week

    # Filtro: tieni solo le righe fino alla settimana corrente (inclusa)
    df = df[df["period"].astype(int) <= current_week]

    return df



# ──────────────────────────────────────────────────────────────────────────────
# Helper – view for a single channel
# ──────────────────────────────────────────────────────────────────────────────
def single_channel_view(df: pd.DataFrame, prefix: str, color: str) -> None:
    p = f"{prefix}_"
    col = lambda m: p + m

    s1, s2, s3, s4 = st.columns(4)

    previous = df.iloc[-2]
    s1.metric("Previous Week", previous["week_label"])
    s2.metric("CPS-YTD", f"€ {previous[col('cps_ytd')]:,.2f}")
    s3.metric("CPS (Week)", f"€ {previous[col('cps_period')]:,.2f}")
    s4.metric("Budget €", f"€ {previous[col('budget_speso_cost')]:,.2f}")

    latest = df.iloc[-1]
    s1.metric("Current Week", latest["week_label"])
    s2.metric("CPS-YTD", f"€ {latest[col('cps_ytd')]:,.2f}")
    s3.metric("CPS (Week)", f"€ {latest[col('cps_period')]:,.2f}")
    s4.metric("Budget €", f"€ {latest[col('budget_speso_cost')]:,.2f}")

    # Charts
    week_order = df["week_label"].tolist()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("CPS-YTD Trend")
        st.altair_chart(
            alt.Chart(df)
            .mark_line(strokeWidth=4, color=color)
            .encode(
                x=alt.X("week_label:N", sort=week_order, title="Week"),
                y=alt.Y(col("cps_ytd") + ":Q", title="CPS-YTD"),
                tooltip=["week_label", col("cps_ytd")],
            )
            .properties(height=340),
            use_container_width=True,
        )

    with c2:
        st.subheader("CPS per Week")
        st.altair_chart(
            alt.Chart(df)
            .mark_line(strokeWidth=4, color=color)
            .encode(
                x=alt.X("week_label:N", sort=week_order, title="Week"),
                y=alt.Y(col("cps_period") + ":Q", title="CPS (Week)"),
                tooltip=["week_label", col("cps_period")],
            )
            .properties(height=340),
            use_container_width=True,
        )

    # Budget bar
    st.subheader("Budget Speso per Week")
    st.altair_chart(
        alt.Chart(df)
        .mark_bar(color=color, opacity=0.7)
        .encode(
            x=alt.X("week_label:N", sort=week_order, title="Week"),
            y=alt.Y(col("budget_speso_cost") + ":Q", title="Budget €"),
            tooltip=["week_label", col("budget_speso_cost")],
        )
        .properties(height=240),
        use_container_width=True,
    )

    # Data table
    st.markdown("##### Data Table")
    st.dataframe(
        df[
            [
                "week_label",
                col("cps_ytd"),
                col("cps_period"),
                col("budget_speso_cost"),
            ]
        ].rename(
            columns={
                "week_label": "Week",
                col("cps_ytd"): "CPS-YTD",
                col("cps_period"): "CPS (Week)",
                col("budget_speso_cost"): "Budget €",
            }
        ),
        use_container_width=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main dashboard renderer
# ──────────────────────────────────────────────────────────────────────────────
def render_ttt_dashboard(
    df: pd.DataFrame,
    *,
    primary_color: str = "#008CFF",
    logo_url: str = "",
    footer_logo_url: str = "",
) -> None:
    # mostra solo le settimane dell’anno già trascorse
    current_week = pd.Timestamp.today().isocalendar().week
    df = df[df["period"] <= current_week]

    # ─ canali disponibili ─────────────────────────────────────────────
    import re

    # prendo tutto ciò che termina con una delle metriche chiave
    metric_suffixes = ("_cps_ytd", "_cps_period", "_budget_speso_cost")
    prefixes = sorted({
        re.sub(r"_(cps_ytd|cps_period|budget_speso_cost)$", "", c)
        for c in df.columns
        if c.endswith(metric_suffixes)
    })

    if len(prefixes) == 0:
        st.error("⚠️ Nessuna colonna canale-specifica trovata. "
                 "Riesegui l’ETL o controlla la tabella.")
        return


    # ─ Header
    c_logo, c_title, _ = st.columns([1, 6, 1])
    with c_logo:
        if logo_url:
            st.image(logo_url, width=120)
    with c_title:
        st.markdown(
            f"<h1 style='text-align:center; font-family:Gotham HTF, sans-serif;'>"
            f"<span style='color:{primary_color};'>TTT</span> CPS Settimanale"
            f"</h1>",
            unsafe_allow_html=True,
        )

    # ─ Tabs (Google Ads | Facebook Ads | Comparison)
        # ─ Tabs (uno per canale, più 'Comparison' se >1) ──────────────────
    tab_names = [p.replace("_", " ").title() for p in prefixes]
    tabs = st.tabs(tab_names)


    # ► singoli canali
    for tab, pref in zip(tabs, prefixes):
        with tab:
            single_channel_view(df, pref, primary_color)
    
    # ─ Footer
    date_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    footer_html = f"""
    <div class="footer">
        <div class="footer-text">
            <p>Data aggiornati al {date_str}</p>
        </div>"""
    st.markdown(footer_html, unsafe_allow_html=True)
