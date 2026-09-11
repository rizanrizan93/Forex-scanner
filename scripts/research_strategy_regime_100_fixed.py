from __future__ import annotations

import pandas as pd

import research_strategy_regime_100 as bench


def load_data_robust(symbol: str) -> pd.DataFrame:
    url = bench.SOURCE.format(symbol=symbol)
    # MT5 exports often use tabs and angle-bracket headers such as <DATE>/<OPEN>.
    df = pd.read_csv(url, sep=None, engine="python")
    normalized = {}
    for c in df.columns:
        key = str(c).strip().strip("<>").strip().upper()
        normalized[c] = key
    df = df.rename(columns=normalized)

    required = {"OPEN", "HIGH", "LOW", "CLOSE"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(f"{symbol}: missing columns {sorted(missing)}; got={list(df.columns)}")

    if "DATE" in df.columns and "TIME" in df.columns:
        timestamp = df["DATE"].astype(str).str.strip() + " " + df["TIME"].astype(str).str.strip()
    elif "DATE" in df.columns:
        timestamp = df["DATE"].astype(str).str.strip()
    elif "DATETIME" in df.columns:
        timestamp = df["DATETIME"].astype(str).str.strip()
    else:
        raise RuntimeError(f"{symbol}: no DATE/DATETIME column; got={list(df.columns)}")

    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(timestamp, errors="coerce"),
            "Open": pd.to_numeric(df["OPEN"], errors="coerce"),
            "High": pd.to_numeric(df["HIGH"], errors="coerce"),
            "Low": pd.to_numeric(df["LOW"], errors="coerce"),
            "Close": pd.to_numeric(df["CLOSE"], errors="coerce"),
            "Spread": pd.to_numeric(df["SPREAD"], errors="coerce") if "SPREAD" in df.columns else 0.0,
        }
    )
    out["Spread"] = out["Spread"].fillna(0.0)
    out = (
        out.dropna(subset=["Date", "Open", "High", "Low", "Close"])
        .sort_values("Date")
        .drop_duplicates("Date")
        .reset_index(drop=True)
    )
    if out.empty:
        raise RuntimeError(f"{symbol}: parsed dataset is empty")
    return bench.add_features(out)


bench.load_data = load_data_robust

if __name__ == "__main__":
    bench.main()
