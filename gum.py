# GUM_dashboard.py
import os
import streamlit as st
import pandas as pd
import altair as alt
from sqlalchemy import create_engine

def get_connection():
    creds = st.secrets["postgres"]
    dsn = (
        f"postgresql://{creds['user']}:{creds['password']}"
        f"@{creds['host']}:{creds['port']}/{creds['database']}"
    )
    return create_engine(dsn)

@st.cache_data
def load_gum_data() -> pd.DataFrame:
    engine = get_connection()

    # prendo tutte le colonne: così future aggiunte non richiedono
    # di toccare la query
    df = pd.read_sql("SELECT * FROM gum_monthly_uv ORDER BY period", engine)

    # numeric ⇢ coerced / NA→0
    num_cols = [c for c in df.columns if c not in
                {'period', 'period_type', 'snapshot_date', 'is_final'}]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # month label
    df['month'] = (
        pd.to_datetime(df['period'].astype(int), format='%m')
          .dt.month_name()
    )
    return df

def single_channel_view(df: pd.DataFrame,
                        prefix: str,
                        primary_color: str) -> None:
    """Stampa KPI, 2 line-chart e data-table per un solo canale."""
    p = f"{prefix}_"
    col = lambda m: p + m      # alias interno

    # — KPI —
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Current Month", df['month'].iloc[-1])
    ytd = df[col('ytd_delta')].iloc[-1]
    col2.metric("YTD Δ", f"{ytd:,.0f}")
    col3.metric("Current Contribution", f"{df[col('contribution')].iloc[-1]:.0%}")
    col4.metric("Forecast Fine Mese", f"{df[col('forecast_fine_mese')].iloc[-1]:,.0f}")

    # — Trend: YTD Δ —
    month_ord = (pd.to_datetime(df['month'], format='%B')
                   .dt.month.argsort().argsort())
    sorted_months = df['month'].iloc[month_ord].unique().tolist()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Monthly YTD Δ Trend")
        st.altair_chart(
            alt.Chart(df)
               .mark_line(strokeWidth=4, color=primary_color)
               .encode(
                   x=alt.X('month:N', sort=sorted_months, title='Month'),
                   y=alt.Y(col('ytd_delta') + ':Q', title='YTD Δ'),
                   tooltip=['month', col('ytd_delta')]
               )
               .properties(height=320),
            use_container_width=True
        )

    # — Trend: Contribution —
    with c2:
        st.subheader("Contribution by Month")
        st.altair_chart(
            alt.Chart(df)
               .mark_line(strokeWidth=4, color=primary_color)
               .encode(
                   x=alt.X('month:N', sort=sorted_months, title='Month'),
                   y=alt.Y(col('contribution') + ':Q', title='Contribution'),
                   tooltip=['month', alt.Tooltip(col('contribution'), format='.2%')]
               )
               .properties(height=320),
            use_container_width=True
        )

    # — Data table —
    st.markdown("##### Data Table")
    tbl_cols = ['month', col('ytd_delta'), col('contribution'), col('forecast_fine_mese')]
    st.dataframe(
        df[tbl_cols].rename(columns={
            col('ytd_delta'): 'YTD Δ',
            col('contribution'): 'Contribution',
            col('forecast_fine_mese'): 'Forecast Fine Mese'
        }),
        use_container_width=True
    )

def render_gum_dashboard(df: pd.DataFrame,
                         primary_color: str = "#38D430",
                         logo_url: str = "",
                         footer_logo_url: str = "") -> None:

    # Limita ai mesi già passati
    current_month = pd.Timestamp.today().month
    df = df[df['period'] <= current_month]

    # Prefissi disponibili (es. organic, paid, …)
    prefixes = sorted({
        c.split("_")[0] for c in df.columns
        if "_" in c and c.endswith("_delta")
    })
    assert {'organic', 'paid'}.issubset(prefixes), \
        "Mi aspetto almeno i prefissi 'organic' e 'paid'"

    # ——— HEADER ———
    col_logo, col_title, _ = st.columns([1, 6, 1])
    with col_logo:
        if logo_url:
            st.image(logo_url, width=120)
    with col_title:
        st.markdown(
            "<h1 style='text-align:center; font-family:Gotham HTF, sans-serif;'>"
            "<span style='color:#38D430;'>GUM</span> Unique Visitors Mensili"
            "</h1>",
            unsafe_allow_html=True
        )

    # ——— TABS ———
    tabs = st.tabs([p.capitalize() for p in prefixes])

    # ▸ Tab singoli (Organic e Paid)
    for tab, pref in zip(tabs, prefixes):
        with tab:
            single_channel_view(df, pref, primary_color)

    # ——— FOOTER ———
    date_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    footer_html = f"""
    <div class="footer">
        <div class="footer-text">
            <p>Data aggiornati al {date_str}</p>
        </div>"""
    st.markdown(footer_html, unsafe_allow_html=True)

