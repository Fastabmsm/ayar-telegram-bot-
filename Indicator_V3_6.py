"""
Indicator_V3_6.py  --  Version 3.6  (data rules + indicators + market-regime classifier)
=========================================================================================
Companion of Engine_V3_6.py.  Put both files in the same folder.

V3.6 vs V3.5: NOTHING changes in this file.  Every formula, constant and output column is
byte-identical to Indicator_V3_5.py / Indicator_V3_4.py / Indicator_V3_1.py.
The only change of V3.6 versus V3.5 lives in the ENGINE (the `down_min_bars` entry filter).
Everything below -- the loader, PSAR, RSI, ADX, SMAs, monthly buffer, ATR ratio and the
regime classifier -- is untouched and produces exactly the same table as V3.1.

PURPOSE
  Everything that turns raw 15-minute OHLC rows into the table the engine trades on.
  The engine contains NO indicator maths; the indicator file contains NO trading rules.

INPUT FORMAT (CSV or XLSX)
  Columns:  Date (YYYYMMDD int), Time (HHMMSS int), Open, High, Low, Close   [Volume ignored]

DATA RULES (applied in this exact order by load_data)
  1. datetime = Date (8 digits) + Time (6 digits, zero padded), format %Y%m%d%H%M%S
  2. concatenate all files in the order given
  3. STABLE sort by datetime (mergesort)
  4. drop duplicated datetimes, keep the FIRST occurrence
  5. drop placeholder rows with Open == High == Low == Close == 10000
  6. OHLC cast to float64, index reset to 0..n-1
  Nothing else is filtered, filled or adjusted.

ATR RATIO (unchanged since V3.4)
  TR        = max(H-L, |H-prevC|, |L-prevC|)           (bar 0: H-L)
  ATR       = 0 until bar 12; ATR[13] = mean(TR[0..13]); then Wilder: ATR[i] = (ATR[i-1]*13 + TR[i]) / 14
  atr_pct   = ATR / Close
  mean_long = rolling mean of atr_pct, 960 bars (min 240) ;  mean_short = same, 240 bars (min 60)
  mean_used = mean_short if ADX > 35 else mean_long
  atr_ratio = clip(atr_pct / max(mean_used, 1e-9), 1.0, 1.5);   NaN (warm-up) -> 1.0 (neutral)

OUTPUT TABLE (prepare)
  datetime, Open, High, Low, Close,
  month, PSAR, RSI, ADX, SMA_16, SMA_30, buffer,
  atr_ratio,
  regime (0=RANGE 1=UP 2=DOWN), adx_threshold

ALL columns are causal: the value on bar i uses bars <= i only.
"""
import hashlib
import numpy as np
import pandas as pd

VERSION = "3.6"

# ---------------------------------------------------------------- constants
BASE_MONTHLY_V3 = {          # PSAR-exit buffer by calendar month (unchanged from V3)
    1: 0.035, 2: 0.030, 3: 0.010, 4: 0.010, 5: 0.010, 6: 0.025,
    7: 0.025, 8: 0.020, 9: 0.0175, 10: 0.025, 11: 0.035, 12: 0.010,
}
RANGE, UP, DOWN = 0, 1, 2
REGIME_NAMES = {RANGE: "RANGE", UP: "UP (strong trend)", DOWN: "DOWN"}

REGIME_PARAMS = dict(
    fast=96, slow=480,
    adx_q=0.60, adx_win=960,
)
PLACEHOLDER_PRICE = 10000
FIRST_REAL_BAR = "2018-07-22 13:00:00"


# ---------------------------------------------------------------- data loading
def load_data(paths):
    """Deterministic loader.  paths: list of CSV/XLSX file paths."""
    parts = []
    for p in paths:
        raw = pd.read_excel(p) if str(p).lower().endswith((".xlsx", ".xls")) else pd.read_csv(p)
        raw["datetime"] = pd.to_datetime(
            raw["Date"].astype(int).astype(str).str.zfill(8) +
            raw["Time"].astype(int).astype(str).str.zfill(6),
            format="%Y%m%d%H%M%S")
        parts.append(raw[["datetime", "Open", "High", "Low", "Close"]])
    full = pd.concat(parts, ignore_index=True)
    full = full.sort_values("datetime", kind="mergesort")
    full = full.drop_duplicates("datetime", keep="first")
    flat = ((full.Open == PLACEHOLDER_PRICE) & (full.High == PLACEHOLDER_PRICE)
            & (full.Low == PLACEHOLDER_PRICE) & (full.Close == PLACEHOLDER_PRICE))
    full = full[~flat].reset_index(drop=True)
    for c in ("Open", "High", "Low", "Close"):
        full[c] = full[c].astype("float64")
    return full


def data_fingerprint(df):
    """Short identity of a dataset."""
    close = np.ascontiguousarray(df["Close"].values, dtype=np.float64)
    return dict(n_bars=int(len(df)),
                first=str(df["datetime"].iloc[0]),
                last=str(df["datetime"].iloc[-1]),
                close_sum=int(round(float(close.sum()))),
                close_sha256_16=hashlib.sha256(close.tobytes()).hexdigest()[:16])


# ---------------------------------------------------------------- V3 indicators (formulas unchanged)
def wilder_rma(s, p):
    return s.ewm(alpha=1.0 / p, adjust=False).mean()


def compute_psar(high, low, start=0.005, step=0.015, max_af=0.25):
    n = len(high)
    h = high.values.astype(float)
    l = low.values.astype(float)
    psar = np.zeros(n)
    bull = True
    af = start
    ep = h[0]
    psar[0] = l[0]
    for i in range(1, n):
        prev = psar[i - 1]
        if bull:
            psar[i] = min(prev + af * (ep - prev), l[i - 1], l[i - 2]) if i >= 2 else min(prev + af * (ep - prev), l[i - 1])
            if l[i] < psar[i]:
                bull = False; psar[i] = ep; ep = l[i]; af = start
            else:
                if h[i] > ep: ep = h[i]; af = min(af + step, max_af)
        else:
            psar[i] = max(prev + af * (ep - prev), h[i - 1], h[i - 2]) if i >= 2 else max(prev + af * (ep - prev), h[i - 1])
            if h[i] > psar[i]:
                bull = True; psar[i] = ep; ep = h[i]; af = start
            else:
                if l[i] < ep: ep = l[i]; af = min(af + step, max_af)
    return pd.Series(psar, index=high.index)


def compute_rsi(close, p=14):
    d = close.diff()
    g = wilder_rma(d.clip(lower=0), p)
    l = wilder_rma((-d).clip(lower=0), p)
    rs = g / l.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_adx(high, low, close, p=14):
    up = high.diff(); dn = -low.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([high - low,
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = wilder_rma(tr, p)
    pdi = 100 * wilder_rma(pd.Series(pdm, index=close.index), p) / atr.replace(0, np.nan)
    mdi = 100 * wilder_rma(pd.Series(mdm, index=close.index), p) / atr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder_rma(dx, p)


def compute_sma(c, p):
    return c.rolling(p, min_periods=p).mean()


ATR_PARAMS = dict(
    period=14,
    win_long=960, min_long=240,
    win_short=240, min_short=60,
    adx_switch=35,
    ratio_min=1.0, ratio_max=1.5,
)


def compute_atr_ratio(df, **override):
    """ATR volatility ratio (causal)."""
    q = dict(ATR_PARAMS); q.update(override)
    high, low, close = df["High"].values, df["Low"].values, df["Close"].values
    n, p = len(df), q["period"]
    prev = np.empty(n); prev[0] = close[0]; prev[1:] = close[:-1]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    atr = np.zeros(n)
    if n >= p:
        atr[p - 1] = tr[:p].mean()
        for i in range(p, n):
            atr[i] = (atr[i - 1] * (p - 1) + tr[i]) / p
    atr_pct = pd.Series(atr / close)
    m_long = atr_pct.rolling(q["win_long"], min_periods=q["min_long"]).mean().values
    m_short = atr_pct.rolling(q["win_short"], min_periods=q["min_short"]).mean().values
    used = np.where(df["ADX"].values > q["adx_switch"], m_short, m_long)
    ratio = np.clip(atr_pct.values / np.maximum(used, 1e-9), q["ratio_min"], q["ratio_max"])
    return np.where(np.isnan(ratio), 1.0, ratio)


# ---------------------------------------------------------------- market-state layer
def regime_features(df, **override):
    """Returns (regime array, adx threshold array).  Causal."""
    q = dict(REGIME_PARAMS); q.update(override)
    c = df["Close"]
    sma_f = c.rolling(q["fast"], min_periods=q["fast"]).mean()
    sma_s = c.rolling(q["slow"], min_periods=q["slow"]).mean()
    slope_s = sma_s / sma_s.shift(q["fast"]) - 1
    adx_th = df["ADX"].rolling(q["adx_win"], min_periods=q["adx_win"] // 4).quantile(q["adx_q"]).fillna(25.0)
    up = ((c > sma_f) & (sma_f > sma_s) & (slope_s > 0) & (df["ADX"] > adx_th)).values
    dn = ((c < sma_f) & (sma_f < sma_s) & (slope_s < 0)).values
    reg = np.where(up, UP, np.where(dn, DOWN, RANGE)).astype(np.int64)
    return reg, adx_th.values


def prepare(ohlc):
    """ohlc: DataFrame(datetime, Open, High, Low, Close) -> full table used by the engine."""
    df = ohlc.copy().reset_index(drop=True)
    df["month"] = df["datetime"].dt.month
    df["PSAR"] = compute_psar(df["High"], df["Low"])
    df["RSI"] = compute_rsi(df["Close"], 14)
    df["ADX"] = compute_adx(df["High"], df["Low"], df["Close"], 14)
    df["SMA_16"] = compute_sma(df["Close"], 16)
    df["SMA_30"] = compute_sma(df["Close"], 30)
    df["buffer"] = df["month"].map(BASE_MONTHLY_V3)
    df["atr_ratio"] = compute_atr_ratio(df)
    reg, th = regime_features(df)
    df["regime"] = reg
    df["adx_threshold"] = th
    return df


def build(paths):
    """load_data + prepare in one call."""
    return prepare(load_data(paths))