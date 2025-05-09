import os
import re
import sys
import argparse
import pandas as pd
from sqlalchemy import create_engine, text, inspect
from dateutil import parser as dateparser
from typing import Literal, Optional
import calendar

# ▶️  Import Google Sheets
try:
    from google.oauth2.service_account import Credentials
    import gspread
except ImportError:
    Credentials = None  # type: ignore
    gspread = None  # type: ignore

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
    return f'"{name}"'

def execute(conn, sql):
    print(f"[SQL] {sql.strip().splitlines()[0][:120]}…")
    conn.execute(text(sql))

###############################################################################
# Lettura fogli Excel / Google Sheets
###############################################################################

def _read_google_sheet_raw(spreadsheet_id: str, sheet_name: str, creds_path: str) -> pd.DataFrame:
    if gspread is None or Credentials is None:
        raise RuntimeError(
            "Modulo gspread/google-auth non disponibile. Installa con:\n\n    pip install gspread google-auth\n"
        )
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    ws = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    values = ws.get_all_values()
    return pd.DataFrame(values)

def _read_excel_raw(xlsx_path: str, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None)

SourceType = Literal["excel", "gsheet"]

def read_raw(source_type: SourceType, sheet_name: str, *,
             xlsx_path: Optional[str] = None,
             gsheet_id: Optional[str] = None,
             creds_path: Optional[str] = None) -> pd.DataFrame:
    if source_type == "excel":
        if not xlsx_path:
            raise ValueError("xlsx_path obbligatorio per sorgente Excel")
        return _read_excel_raw(xlsx_path, sheet_name)
    else:
        if not gsheet_id or not creds_path:
            raise ValueError("gsheet_id e creds_path obbligatori per sorgente gsheet")
        return _read_google_sheet_raw(gsheet_id, sheet_name, creds_path)

###############################################################################
# Parsing helpers aggiornati
###############################################################################

import re
import math

import re
import math

def extract_number(s: str) -> float:
    txt = str(s)
    # Rimuovo tutto tranne cifre, virgole, punti e segno meno
    core = re.sub(r"[^0-9\-,\.]+", "", txt)
    if not core:
        return math.nan

    # Caso 1: sia ',' sia '.'
    if ',' in core and '.' in core:
        # ',' è migliaia, '.' decimale
        core = core.replace(',', '')

    # Caso 2: solo ','
    elif ',' in core:
        left, right = core.split(',', 1)
        if len(right) == 3:
            # migliaia
            core = left + right
        else:
            # decimale
            core = left + '.' + right

    # Caso 3: solo '.'
    elif '.' in core:
        left, right = core.split('.', 1)
        if len(right) == 3:
            # migliaia
            core = left + right
        else:
            # decimale (lascia il punto)
            core = left + '.' + right

    try:
        return float(core)
    except ValueError:
        return math.nan

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

def clean(name: str) -> str:
    return re.sub(r"\W+", "_", name.strip().lower())

def normalize_name(name: str) -> str:
    # collapse underscores and strip
    name = re.sub(r"_+", "_", name)
    return name.strip("_")

def flatten_columns(df: pd.DataFrame, raw_df: pd.DataFrame = None, header_row: int = None) -> pd.DataFrame:
    mapping = {"week": "period", "month": "period", "start": "start_date", "end": "end_date"}

    if isinstance(df.columns, pd.MultiIndex) and raw_df is not None and header_row is not None:
        # Estrai le due righe di header "grezze"
        upper = raw_df.iloc[header_row - 1].astype(str)
        lower = raw_df.iloc[header_row].astype(str)

        # 1) Riempio in avanti i brand per coprire anche le colonne adform_delta
        upper = upper.replace(r"^\s*$", pd.NA, regex=True)  # trasforma stringhe vuote in NA
        upper = upper.ffill()  # forward-fill: propaga l'ultimo brand valido

        # 2) Ora pulisco e genero i nomi
        new_cols = []
        for top, bottom in zip(upper, lower):
            brand = clean(top) if pd.notna(top) else ""
            metric = clean(bottom)
            base = f"{brand}_{metric}" if brand else metric

            # standardizzo parola per parola
            parts = base.split("_")
            parts = [mapping.get(p, p) for p in parts]
            col = normalize_name("_".join(parts))
            new_cols.append(col)

        df.columns = new_cols

    else:
        # caso single header invariato...
        cols = [str(c) for c in df.columns]
        new_cols = []
        for c in cols:
            cleaned = clean(c)
            parts = cleaned.split("_")
            parts = [mapping.get(p, p) for p in parts]
            new_cols.append(normalize_name("_".join(parts)))
        df.columns = new_cols

    # resto della funzione invariato...
    if "period" not in df.columns and "period_if_absent" in df.columns:
        df = df.rename(columns={"period_if_absent": "period"})
    if "period" in df.columns and "period_if_absent" in df.columns:
        df = df.drop(columns="period_if_absent")
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def mark_open_period(df: pd.DataFrame,
                     period_col: str = "period",
                     period_type_col: str = "period_type") -> pd.DataFrame:
    import calendar
    df = df.copy()
    today = pd.Timestamp.today().normalize()

    # Identifico start/end
    start_col = next((c for c in df.columns if c.lower()=="start_date"), None)
    end_col   = next((c for c in df.columns if c.lower()=="end_date"),   None)

    # Maschere e is_final
    if end_col:
        # Caso con date
        df[start_col] = pd.to_datetime(df[start_col], errors="coerce")
        df[end_col]   = pd.to_datetime(df[end_col],   errors="coerce")
        df["is_final"] = df[end_col] < today
        mask_current = (df[start_col] <= today) & (df[end_col] >= today)
        # Serie di giorni per riga
        total_days = (df[end_col] - df[start_col]).dt.days + 1
        elapsed    = (today - df[start_col]).dt.days + 1

    else:
        # Caso senza date
        if df[period_type_col].iloc[0] == "week":
            current = today.isocalendar().week
            total_days = 7
            elapsed    = today.weekday() + 1
        else:
            current = today.month
            total_days = calendar.monthrange(today.year, today.month)[1]
            elapsed    = today.day

        df["is_final"] = df[period_col] < current
        mask_current = df[period_col] == current

    # Pulizia dei valori (skip chiavi)
    skip = {period_col, period_type_col, start_col, end_col, "is_final", "snapshot_date"}
    for col in df.columns:
        if col in skip:
            continue
        # Applico estrazione numero a tutte le celle:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(r"[ \s]+", "", regex=True)   # rimuove spazi normali e no‑break
            .apply(extract_number)
        )


    # Seleziono le metriche numeriche
    numeric_cols = [c for c in df.select_dtypes(include="number").columns if c not in skip]

    # Inizializzo forecast
        # 6) inizializzo forecast come nullable integer
    for col in numeric_cols:
        df[f"{col}_forecast"] = pd.Series([pd.NA] * len(df), dtype="Int64")

    # 7) calcolo forecast
    if end_col:
        # caso con date: itero riga per riga
        for idx in df.index[mask_current]:
            td = int(total_days.loc[idx])
            ed = int(elapsed.loc[idx])
            if ed <= 0:
                continue
            # override totale per week/month
            if df.at[idx, period_type_col] == "week":
                td = 7
            else:
                st = df.at[idx, start_col]
                td = calendar.monthrange(st.year, st.month)[1]
            for col in numeric_cols:
                val = df.at[idx, col]
                if pd.notna(val):
                    raw_fc = val / ed * td
                    df.at[idx, f"{col}_forecast"] = int(round(raw_fc))
    else:
        # caso senza date: scalari elapsed/total_days
        if elapsed > 0:
            for idx in df.index[mask_current]:
                for col in numeric_cols:
                    val = df.at[idx, col]
                    if pd.notna(val):
                        raw_fc = val / elapsed * total_days
                        df.at[idx, f"{col}_forecast"] = int(round(raw_fc))


    print("[DEBUG forecast cols]", [c for c in df.columns if c.endswith("_forecast")])
    return df



###############################################################################
# DDL / Upsert (invariati)
###############################################################################

def build_table_if_absent(df: pd.DataFrame, table: str, pkeys: list[str], engine):
    cols_sql = [f"{quote_ident(c)} {dtype_map.get(str(t), 'TEXT')}" for c, t in df.dtypes.items()]
    pk_clause = f",\n  PRIMARY KEY ({', '.join(map(quote_ident, pkeys))})" if pkeys else ""
    sql = f"CREATE TABLE IF NOT EXISTS {quote_ident(table)} (\n  " + ",\n  ".join(cols_sql) + pk_clause + "\n);"
    with engine.begin() as conn:
        execute(conn, sql)

def ensure_table_columns(df: pd.DataFrame, table: str, engine):
    with engine.begin() as conn:
        existing = [col["name"] for col in inspect(conn).get_columns(table)]
        for col, t in df.dtypes.items():
            if col not in existing:
                execute(conn, f"ALTER TABLE {quote_ident(table)} ADD COLUMN {quote_ident(col)} {dtype_map.get(str(t), 'TEXT')};")

def upsert_dataframe(df: pd.DataFrame, table: str, pkeys: list[str], engine):
    if df.empty:
        print(f"[WARN] DataFrame vuoto per {table}, skip.")
        return
    tmp = f"tmp_{table}"
    with engine.begin() as conn:
        df.to_sql(tmp, conn, index=False, if_exists="replace", method="multi")
        cols = ", ".join(map(quote_ident, df.columns))
        updates = ", ".join(f"{quote_ident(c)}=EXCLUDED.{quote_ident(c)}" for c in df.columns if c not in pkeys)
        pk = ", ".join(map(quote_ident, pkeys))
        sql = f"""
            INSERT INTO {quote_ident(table)} ({cols})
            SELECT {cols} FROM {quote_ident(tmp)}
            ON CONFLICT ({pk}) DO UPDATE SET {updates};
            DROP TABLE {quote_ident(tmp)};
        """
        execute(conn, sql)

###############################################################################
# Processo singolo foglio
###############################################################################

def has_multi_header(raw_df: pd.DataFrame, header_row: int) -> bool:
    """
    Ritorna True se la riga immediatamente sopra l'header individuato
    contiene valori non-vuoti *e* diversi dall’header stesso.
    Serve per capire se siamo in presenza di una struttura Brand / Metric.
    """
    if header_row == 0:          # non c’è nulla sopra
        return False

    upper = raw_df.iloc[header_row - 1].astype(str)
    lower = raw_df.iloc[header_row    ].astype(str)

    # almeno una cella non vuota sulla riga superiore…
    upper_has_values = (upper.str.strip() != "").any()
    # …e la riga superiore non è identica all’header metrico
    upper_differs    = (upper != lower).any()

    return upper_has_values and upper_differs

def process_sheet(
    sheet_source: str,
    sheet_name: str,
    table: str,
    period_type: str,
    engine,
    source_type: SourceType,
    creds_path: Optional[str] = None,
):
    print(f"[INFO] {sheet_name} → {table} (source={source_type})")

    raw = read_raw(source_type, sheet_name,
                   xlsx_path=(sheet_source if source_type == "excel" else None),
                   gsheet_id=(sheet_source if source_type == "gsheet" else None),
                   creds_path=creds_path)

    snap_date = extract_snapshot_date(raw)
    header = find_header_row(raw)
    is_multi = has_multi_header(raw, header)

    if is_multi:
        if source_type == "excel":
            df = pd.read_excel(sheet_source, sheet_name=sheet_name, header=[header-1, header])
        else:
            upper = raw.iloc[header-1].tolist()
            lower = raw.iloc[header].tolist()
            cols = pd.MultiIndex.from_arrays([upper, lower])
            data = raw.iloc[header+1:].reset_index(drop=True)
            data.columns = cols
            df = data
        df = flatten_columns(df, raw_df=raw, header_row=header)
    else:
        if source_type == "excel":
            df = pd.read_excel(sheet_source, sheet_name=sheet_name, header=header)
        else:
            cols = raw.iloc[header].tolist()
            data = raw.iloc[header+1:].reset_index(drop=True)
            data.columns = cols
            df = data
        df = flatten_columns(df)

    # Evito SettingWithCopy: assicuro una copia vera
    df = df.copy()
    # Sostituisco stringhe vuote con NA
    df = df.replace("", pd.NA)
    # Converte in numerico dove possibile, senza errors arg (catcho eccezioni)
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            # non numerica, la lascio così
            pass

    if "period" not in df.columns:
        raise ValueError(f"Colonna 'period' non trovata in {sheet_name} dopo il flatten")
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
    parser = argparse.ArgumentParser(description="Import Monitoring (Excel o Google Sheets) in PostgreSQL.")
    parser.add_argument("--file", default="Monitoring Files.xlsx", help="Percorso Excel locale")
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"), help="DSN PostgreSQL")
    parser.add_argument("--gsheet-id", help="ID del Google Sheets")
    parser.add_argument("--creds", default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), help="Path file JSON credenziali service account")

    args = parser.parse_args()
    if not args.dsn:
        sys.exit("✖ Specificare DSN Postgres con --dsn oppure env DATABASE_URL")

    if args.gsheet_id:
        source_type = "gsheet"
        sheet_source = args.gsheet_id
    else:
        source_type = "excel"
        sheet_source = args.file

    engine = create_engine(args.dsn)

    SHEET_CONFIG = [
        {"name": "GUM | Monthly UV",    "table": "gum_monthly_uv",       "period_type": "month"},
        {"name": "Chiesi | Weekly Sessions", "table": "chiesi_weekly_sessions", "period_type": "week"},
        {"name": "Chiesi | Weekly Budget",   "table": "chiesi_weekly_budget",   "period_type": "week"},
        {"name": "TTT | Weekly CPS",         "table": "ttt_weekly_cps",         "period_type": "week"},
    ]
    for cfg in SHEET_CONFIG:
        process_sheet(sheet_source, cfg["name"], cfg["table"], cfg["period_type"], engine, source_type, creds_path=args.creds)

    print("✔ Import completato.")

if __name__ == "__main__":
    main()
