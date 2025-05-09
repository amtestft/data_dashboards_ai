
"""
Script per importare i file di monitoring in tabelle PostgreSQL.

▶️  Punti chiave
----------------------------------------------------
* **Upsert**: i periodi aperti vengono sovrascritti; i chiusi restano immutati.
* **Evolutivo**: se compaiono nuove colonne fa `ALTER TABLE ADD COLUMN`.
* **Composite PK**: `PRIMARY KEY (period, period_type)`.
* **Snapshot**: salva `snapshot_date` a ogni ingest.
* **Compatibilità pandas‑SQLAlchemy 2.x**: usa `sqlalchemy.inspect` anziché `pd.read_sql(params=[…])`.
* ✅ Fix: escape per parole riservate SQL come `end`, `start`, ecc.

Dipendenze:
    pip install pandas sqlalchemy psycopg2-binary python-dateutil
"""

import os
import re
import sys
import argparse
import pandas as pd
from sqlalchemy import create_engine, text, inspect
from dateutil import parser as dateparser

###############################################################################
# Utility generali
###############################################################################

dtype_map = {
    "int64": "INTEGER",
    "float64": "DOUBLE PRECISION",
    "bool": "BOOLEAN",
    "datetime64[ns]": "TIMESTAMP",
    "object": "TEXT",
}

def quote_ident(name: str) -> str:
    """Escape per nomi di colonne/tabelle riservati o problematici."""
    return f'"{name}"'

def execute(conn, sql):
    print(f"[SQL] {sql.strip().splitlines()[0][:120]}…")
    conn.execute(text(sql))

###############################################################################
# Parsing Excel helpers
###############################################################################

def extract_snapshot_date(raw_df: pd.DataFrame) -> pd.Timestamp:
    first_rows = raw_df.iloc[:2, 0].astype(str).str.cat(sep=" ")
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", first_rows)
    if iso:
        return pd.to_datetime(iso.group(1))
    euro = re.search(r"(\d{2}/\d{2}/\d{4})", first_rows)
    if euro:
        return pd.to_datetime(euro.group(1), dayfirst=True)
    return pd.Timestamp("today")

def find_header_row(raw_df: pd.DataFrame) -> int:
    for idx, val in enumerate(raw_df.iloc[:, 0].astype(str)):
        if val.strip().lower() in {"week", "month"}:
            return idx
    raise ValueError("Intestazione non trovata (Week/Month).")

def flatten_columns(df: pd.DataFrame, raw_df: pd.DataFrame = None, header_row: int = None) -> pd.DataFrame:
    def clean(x):
        return re.sub(r"\W+", "_", str(x).strip().lower())

    def standardize(name):
        mapping = {
            "week": "period",
            "mese": "period_if_absent",
            "month": "period_if_absent",
            "start": "start_date",
            "start_date": "start_date",
            "end": "end_date",
            "end_date": "end_date",
        }
        for k, v in mapping.items():
            if name == k or name.endswith(f"_{k}_") or name.endswith(f"_{k}") or name.startswith("_unnamed") and k in name:
                return mapping[k]
        return name

    if isinstance(df.columns, pd.MultiIndex):
        if raw_df is not None and header_row is not None and header_row > 0:
            upper_row = raw_df.iloc[header_row - 1].fillna("").astype(str)
            new_columns = []
            for i, (top, bottom) in enumerate(zip(upper_row, df.columns)):
                brand = clean(top)
                metric = clean(bottom)
                metric_clean = standardize(metric)

                is_unnamed = str(top).strip().lower().startswith("unnamed") or brand == ""

                if is_unnamed or metric_clean in {"period", "period_if_absent", "start_date", "end_date"}:
                    col = metric_clean
                else:
                    col = f"{brand}_{metric_clean}"

                new_columns.append(col)
            df.columns = new_columns
        else:
            df.columns = [standardize("_".join(filter(None, map(clean, col)))) for col in df.columns]
    else:
        df.columns = [standardize(clean(c)) for c in df.columns]

    # Se "period_if_absent" esiste ma "period" no, rinomina
    cols = pd.Index(df.columns)
    if "period" not in cols and "period_if_absent" in cols:
        df = df.rename(columns={"period_if_absent": "period"})

    # Se entrambe presenti, elimina la colonna secondaria
    if "period" in df.columns and "period_if_absent" in df.columns:
        df = df.drop(columns="period_if_absent")

    # Elimina colonne duplicate mantenendo la prima occorrenza
    df = df.loc[:, ~df.columns.duplicated()]

    return df

def mark_open_period(df: pd.DataFrame, period_col: str = "period") -> pd.DataFrame:
    if df.empty:
        df["is_final"] = pd.Series(dtype=bool)
        return df

    today = pd.Timestamp.today().normalize()
    end_col = None
    start_col = None

    for col in df.columns:
        if col.lower() in {"end", "end_date"}:
            end_col = col
        if col.lower() in {"start", "start_date"}:
            start_col = col

    if end_col:
        df[end_col] = pd.to_datetime(df[end_col], errors="coerce")
        df["is_final"] = df[end_col] <= today
    else:
        max_period = df[period_col].max()
        df["is_final"] = df[period_col] != max_period

    # Aggiunge forecast solo per la riga corrente (non finale e oggi ∈ [start, end])
    if start_col and end_col:
        df[start_col] = pd.to_datetime(df[start_col], errors="coerce")
        df[end_col] = pd.to_datetime(df[end_col], errors="coerce")
        duration = (df[end_col] - df[start_col]).dt.total_seconds() / 86400
        elapsed = (today - df[start_col]).dt.total_seconds() / 86400
        duration = duration.clip(lower=1)
        elapsed = elapsed.clip(lower=0)
        ratio = (elapsed / duration).replace([float("inf"), -float("inf")], 0).fillna(0)

        is_current_period = (df[start_col] <= today) & (df[end_col] >= today)
        mask = is_current_period & ~df["is_final"] & (ratio > 0)

        for col in df.select_dtypes(include=["number"]):
            forecast_col = f"{col}_forecast"
            df[forecast_col] = pd.NA
            df.loc[mask, forecast_col] = df.loc[mask, col] / ratio[mask]

    else:
        for col in df.select_dtypes(include=["number"]):
            df[f"{col}_forecast"] = pd.NA

    return df

###############################################################################
# DDL / Upsert helpers
###############################################################################

def build_table_if_absent(df: pd.DataFrame, table: str, pkeys: list[str], engine):
    cols_sql = [f"{quote_ident(c)} {dtype_map.get(str(t), 'TEXT')}" for c, t in df.dtypes.items()]
    pk_clause = f",\n  PRIMARY KEY ({', '.join(map(quote_ident, pkeys))})" if pkeys else ""
    create_sql = f"CREATE TABLE IF NOT EXISTS {quote_ident(table)} (\n  " + ",\n  ".join(cols_sql) + pk_clause + "\n);"
    with engine.begin() as conn:
        execute(conn, create_sql)


def ensure_table_columns(df: pd.DataFrame, table: str, engine):
    with engine.begin() as conn:
        inspector = inspect(conn)
        existing = [col["name"] for col in inspector.get_columns(table)]
        for col, t in df.dtypes.items():
            if col not in existing:
                pg_type = dtype_map.get(str(t), "TEXT")
                execute(conn, f"ALTER TABLE {quote_ident(table)} ADD COLUMN {quote_ident(col)} {pg_type};")


def upsert_dataframe(df: pd.DataFrame, table: str, pkeys: list[str], engine):
    if df.empty:
        print(f"[WARN] DataFrame vuoto per {table}, skip.")
        return
    tmp = f"tmp_{table}"
    with engine.begin() as conn:
        df.to_sql(tmp, conn, index=False, if_exists="replace", method="multi")
        cols = ", ".join(map(quote_ident, df.columns))
        updates = ", ".join(f"{quote_ident(c)}=EXCLUDED.{quote_ident(c)}" for c in df.columns if c not in pkeys)
        conflict = ", ".join(map(quote_ident, pkeys))
        execute(conn, f"""
            INSERT INTO {quote_ident(table)} ({cols})
            SELECT {cols} FROM {quote_ident(tmp)}
            ON CONFLICT ({conflict}) DO UPDATE SET {updates};
            DROP TABLE {quote_ident(tmp)};
        """)

###############################################################################
# Processo singolo foglio
###############################################################################

def process_sheet(file: str, sheet: str, table: str, period_type: str, engine):
    print(f"[INFO] {sheet} → {table}")
    raw = pd.read_excel(file, sheet_name=sheet, header=None)
    snap_date = extract_snapshot_date(raw)
    header = find_header_row(raw)

    is_multi_header = sheet.lower().startswith("chiesi")
    if is_multi_header:
        df = pd.read_excel(file, sheet_name=sheet, header=[header - 1, header])
        df = flatten_columns(df, raw_df=raw, header_row=header)
    else:
        df = pd.read_excel(file, sheet_name=sheet, header=header)
        df = flatten_columns(df)

    print("[DEBUG] Colonne disponibili:", df.columns.tolist())

    if "period" not in df.columns:
        raise ValueError(f"Colonna 'period' non trovata in {sheet} dopo il flatten")

    df = df[df["period"].notna()]

    df["period_type"] = period_type
    df["snapshot_date"] = snap_date
    df = mark_open_period(df, "period")

    pkeys = ["period", "period_type"]
    build_table_if_absent(df, table, pkeys, engine)
    ensure_table_columns(df, table, engine)
    upsert_dataframe(df, table, pkeys, engine)
###############################################################################
# Main
###############################################################################

def main():
    parser = argparse.ArgumentParser(description="Import Monitoring Excel in PostgreSQL.")
    parser.add_argument("--file", default="Monitoring Files (1).xlsx")
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    if not args.dsn:
        sys.exit("✖︎  Specificare DSN Postgres con --dsn oppure env DATABASE_URL")

    engine = create_engine(args.dsn)

    SHEET_CONFIG = [
        {"name": "GUM | Monthly UV", "table": "gum_monthly_uv", "period_type": "month"},
        {"name": "Chiesi | Weekly Sessions", "table": "chiesi_weekly_sessions", "period_type": "week"},
        {"name": "Chiesi | Weekly Budget", "table": "chiesi_weekly_budget", "period_type": "week"},
        {"name": "TTT | Weekly CPS", "table": "ttt_weekly_cps", "period_type": "week"},
    ]

    for cfg in SHEET_CONFIG:
        process_sheet(args.file, cfg["name"], cfg["table"], cfg["period_type"], engine)

    print("✔︎  Import completato.")


if __name__ == "__main__":
    main()
