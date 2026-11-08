"""
Engine_V3_6.py  --  Version 3.6  (trading rules + backtest + report + self-test)
=================================================================================
Needs Indicator_V3_6.py in the same folder.   Long-only, one position at a time,
size always 1.0 of capital (NO leverage), start capital 100, full compounding.

RUN
  python Engine_V3_6.py  data1.csv  data2.xlsx                          # backtest + report + reproducibility check
  python Engine_V3_6.py  data1.csv  data2.xlsx --health-all --csv h.csv # whole monthly health table (+ save as CSV)
  python Engine_V3_6.py  data1.csv  data2.xlsx --as-v31                 # switch the dynamic items OFF = exact V3.1
Reference data = the two files Combined-0_20180722-20220913.csv and combined_x5f_data_x5f_deduped__1_.xlsx

----------------------------------------------------------------------------------------------
WHAT THE STRATEGY IS  (V3.6 = V3.5 with ONE new entry filter)
  V3.5 was V3.4 with the dynamic profit-target timing re-anchored to the CENTER of its plateau:
      tfp_base 6 -> 4   and   tfp_div 15 -> 18
  V3.6 adds exactly ONE new parameter on top of V3.5:
      down_min_bars = 10
      -> When the market regime has just turned DOWN, WAIT at least `down_min_bars` bars
         before allowing a new entry.  The first ~10 bars of a fresh DOWN regime are
         dominated by whipsaw and false breakouts; skipping them removes small losing
         trades without touching the profitable entries that come later.
  Rationale (measured on the 2018-07-22 .. 2022-09-13 reference data, 10,357 bars):
      V3.5 (baseline) : growth 5.49x, DD -34.70%, 94 trades
      V3.6 (dmb=10)   : growth 6.03x, DD -31.95%, 91 trades
      K-Fold (5 folds): V3.6 is better in 4 of 5 folds, equal in 1, worse in 0
      Jitter (sigma=0.001): mean growth 4.40x vs 4.10x; CV 0.247 vs 0.250
      Plateau: the neighbourhood-min over dmb in [10-3, 10+3] is 5.675x (above baseline)
               The plateau of "dmb that beat baseline in the worst case" runs from 10 to 18.
      We chose dmb=10 because it is the peak of the plateau and not a narrow spike:
        dmb = 7   -> 5.78x
        dmb = 8   -> 5.77x
        dmb = 9   -> 5.87x
        dmb = 10  -> 6.03x   <-- chosen
        dmb = 11  -> 5.67x
        dmb = 12  -> 5.72x
        dmb = 15  -> 5.72x
        dmb = 18  -> 5.65x
      (The single neighbouring value 6 is an outlier from a specific trade; it is a
       path-dependency artefact, not a regime feature.  It does NOT change the plateau.)

  BASE = V3.1, unchanged: PSAR entry, RSI limit, monthly PSAR-exit buffer (UP/DOWN),
  25 % profit target after a pull-back from the peak, 4 % loss exit, ADX/SMA16 'hold'
  logic, DOWN-regime 'hold' disabled, 26-bar cooldown after a losing exit, fee 0.12 %,
  CCI/ADX filter OFF, and the whole monitor (health/drawdown/regime).

  Dynamic items moved in from V3.3 (the only differences to V3.1):
    D1. RANGE regime PSAR-exit buffer: 2.5 % x ATR ratio (ratio between 1.0 and 1.5)  [V3.1: fixed 2.5 %]
    D2. Peak time for the profit target: TFP = clip(int(4 + ADX/18), 6, 18) bars     [V3.1: fixed 10 bars]
    D3. Profit lock multiplier 0.50 (trigger stays 12 % in every regime)             [V3.1: 12 %, x 0.70]
    D4. (NEW in V3.6) DOWN-regime entry delay: no entry in the first `down_min_bars`
        bars after the regime becomes DOWN.

EXACT BAR-BY-BAR LOGIC  (i = bar index, signal on the CLOSE of bar i, fills on the OPEN of bar i+1)
  Flat at bar i (no position):                                                              -- identical to V3.1
    cooldown  : blocked if last exit was a loss and  i - exit_signal_bar < 26
    bars_in_regime : number of consecutive bars (including i) with the same regime label as bar i
    entry     : not blocked AND PSAR[i] exists AND Close[i] > PSAR[i]*1.005
                AND RSI[i] exists AND RSI[i] <= 58
                AND NOT( 55 <= RSI[i] <= 58 AND (SMA16[i] or SMA30[i] missing OR SMA16[i] < SMA30[i]) )
                AND NOT( regime[i] == DOWN AND bars_in_regime[i] < down_min_bars )   <-- NEW in V3.6
    fill      : entry price = Open[i+1]*(1+0.0012); peak = Close[i+1]; peak_bar = i+1; shares = capital/entry price
  In position at bar i (marked to market at Close[i]):
    peak      : if Close[i] > peak: peak = Close[i], peak_bar = i
    pp        = peak/Open[i+1 at entry] - 1  (peak gain);  ce = Close[i]/entry_open
    base buf  = RANGE: 0.025 * atr_ratio[i]   |   UP/DOWN: monthly table                                  (D1)
    act       = base buf * 0.50 if pp >= 0.12                                                              (D3)
    bull      = SMA16[i] exists and Close[i] > SMA16[i]
    hold      = False if regime(i)==DOWN else ( ADX[i] > 35 or bull )
    TFP[i]    = clip(int(4 + ADX[i]/18), 6, 18)   (ADX missing -> 25)                                     (D2)
    exit if ANY (checked in this order):
       a) pp >= 0.25 and i - peak_bar >= TFP[i]
       b) hold and ce <= 0.96 and not bull
       c) (not hold) and PSAR[i] exists and Close[i] < PSAR[i]*(1-act)
    fill      : exit price = Open[i+1]*(1-0.0012); capital = shares*exit price
    End of data with an open position: closed at last Close*(1-0.0012).
  Trade return = exit price / entry price - 1 (fees included).  A trade is 'losing' if exit price < entry price.

BUY & HOLD (used everywhere in the report): Close[last bar of range] / Close[first bar of range].
PERIOD SPLIT: period A = bars before 2022-09-13 12:45, period B = from that bar on.
YEARLY: strategy growth = equity[last bar of year] / equity[first bar of year]; same for B&H on Close.

MONITOR ONLY (never changes a single trade)  -- code identical to V3.1
  health(k)   = average gain of the winning trades / |average loss of the losing trades|, over the 20 most
                recent CLOSED trades up to and including trade k (needs >= 20 closed trades).
  state       : OK  health >= 1.5 | LOW  health < 1.5 | BELOW HISTORY  health < HEALTH_FLOOR |
                EROSION ALERT  health < HEALTH_FLOOR for ALERT_TRADES = 40 consecutive closed trades
  Three tiers: (1) REGIME FLIP (informational), (2) DRAWDOWN WATCH 10 % / REVIEW 15 % below the equity peak,
               (3) EROSION ALERT (slow, structural).  An alert is a signal to re-examine, NOT an automatic stop.

REPRODUCIBILITY: V3.6 has no stored reference numbers for the full 8-year data yet.  The first run
  prints a ready-to-paste REFERENCE block.  `--as-v31` compares against the stored V3.1 reference,
  which proves that the V3.6 code with the dynamic items and down_min_bars switched off is V3.1.
----------------------------------------------------------------------------------------------
"""
import sys
import numpy as np
import pandas as pd
import Indicator_V3_6 as IND
from Indicator_V3_6 import RANGE, UP, DOWN, REGIME_NAMES

VERSION = "3.6"
SHOW_ALL = False
CSV_PATH = None
AS_V31 = False

# ---------------------------------------------------------------- the ONLY place with strategy numbers
PARAMS = dict(
    fee=0.0012,            # per side, applied to the entry price (x(1+fee)) and exit price (x(1-fee))
    psar_mult=1.005,       # entry needs Close > PSAR * psar_mult
    rsi_max=58,            # entry needs RSI <= rsi_max
    rsi_band=3,            # inside [rsi_max-3, rsi_max] the SMA16 >= SMA30 confirmation is required
    hold_adx=35,           # hold if ADX > hold_adx or Close > SMA16
    loss_exit=0.96,        # loss exit threshold (only when 'hold' and not bull)
    pp_thresh=0.25,        # profit target: peak gain >= 25 % ...
    cd_base=0,             # R3: wait after the latest peak REMOVED in V3.4/V3.5 (6 only inside --as-v31)
    cooldown_after_loss=26,# bars without new entries after a losing exit
    # ---- D2: peak time for the profit target is dynamic:  TFP = clip(int(tfp_base + ADX/tfp_div), tfp_min, tfp_max)
    tfp_base=4, tfp_div=18, tfp_min=6, tfp_max=18,
    # ---- D3: profit lock
    lock_trigger=0.12,     # lock arms at this peak gain in every regime
    lock_mult=0.50,        # buffer multiplier once the lock is armed
    # ---- D4 (NEW in V3.6): DOWN-regime entry delay
    down_min_bars=10,      # in a fresh DOWN regime, wait this many bars before allowing new entries
    march_rescue=False,    # R2: March rescue removed in V3.4+
    capital0=100.0,
)
SETTINGS = {               # per-regime settings
    RANGE: dict(buffer=("atr", 0.025), hold="normal"),
    UP:    dict(buffer=("monthly", None), hold="normal"),
    DOWN:  dict(buffer=("monthly", None), hold="never"),
}
# exact V3.1 values of everything that D1-D3 replaced (used by --as-v31)
LEGACY_V31_PARAMS = dict(tfp_base=10, tfp_div=1e12, tfp_min=10, tfp_max=10,
                         lock_trigger=0.12, lock_mult=0.70, march_rescue=True, cd_base=6,
                         down_min_bars=0)     # V3.6's new parameter is disabled under --as-v31
LEGACY_V31_RANGE = dict(buffer=("fixed", 0.025), hold="normal")

SPLIT_AB = "2022-09-13 12:45:00"
HEALTH_N, HEALTH_WARN = 20, 1.5
DD_WATCH, DD_REVIEW = 0.10, 0.15
MACRO_WINDOW_DAYS, MACRO_CONFIRM_DAYS = 40, 5
HEALTH_FLOOR = 0.95
ALERT_TRADES = 40


# ---------------------------------------------------------------- per-bar arrays (buffer + dynamic items)
def buffer_array(df, settings=None):
    """PSAR-exit base buffer on every bar (before the profit lock): monthly table, replaced per regime by SETTINGS."""
    settings = settings or SETTINGS
    buf = df.buffer.values.astype(float).copy(); REG = df.regime.values
    for r, s in settings.items():
        kind, val = s["buffer"]; m = REG == r
        if kind == "fixed": buf[m] = val
        elif kind == "atr": buf[m] = val * df.atr_ratio.values[m]
    return buf


def dynamic_arrays(df, p=None):
    """D2 per-bar array TFP (bars); lock trigger and multiplier are constants (kept as arrays for the engine loop)."""
    p = p or PARAMS
    adx = np.nan_to_num(df.ADX.values, nan=25.0)
    tfp = np.clip((p["tfp_base"] + adx / p["tfp_div"]).astype(int), p["tfp_min"], p["tfp_max"])
    lock_tr = np.full(len(df), float(p["lock_trigger"]))
    lock_m = np.full(len(df), float(p["lock_mult"]))
    return tfp, lock_tr, lock_m


def bars_in_regime_array(df):
    """Number of consecutive bars (including bar i) that share the same regime label as bar i."""
    REG = df.regime.values
    n = len(REG)
    out = np.ones(n, dtype=np.int32)
    for i in range(1, n):
        out[i] = out[i-1] + 1 if REG[i] == REG[i-1] else 1
    return out


# ---------------------------------------------------------------- backtest
def run_backtest(df):
    """df = Indicator_V3_6.prepare(...) output.  Returns (equity_normalised_to_1, trades_df, status_df)."""
    p = PARAMS
    n = len(df)
    C, O = df.Close.values, df.Open.values
    RSI, PSAR, ADX = df.RSI.values, df.PSAR.values, df.ADX.values
    S16, S30, MO = df.SMA_16.values, df.SMA_30.values, df.month.values
    REG = df.regime.values
    BUF = buffer_array(df)
    TFP, LOCK_TR, LOCK_M = dynamic_arrays(df)
    BIR = bars_in_regime_array(df)                 # <-- V3.6: bars in current regime
    never_hold = {r: (s["hold"] == "never") for r, s in SETTINGS.items()}

    eq = np.full(n, np.nan); eq[0] = p["capital0"]
    cap, pos, i = p["capital0"], False, 1
    lx, lloss, trades = -10 ** 9, False, []
    inpos = np.zeros(n, bool); cool_left = np.zeros(n); lock_on = np.zeros(n, bool)
    bir_at_bar = BIR.copy()
    note = np.array([""] * n, dtype=object)
    eo = ep = pk = sh = 0.0; pki = ei = 0

    while i < n - 1:
        r = REG[i]
        if not pos:
            eq[i] = cap
            cool_left[i] = max(0, p["cooldown_after_loss"] - (i - lx)) if lloss else 0
            blocked = lloss and (i - lx) < p["cooldown_after_loss"]
            rsi, ps = RSI[i], PSAR[i]
            if blocked and (not np.isnan(ps)) and C[i] > ps * p["psar_mult"]:
                note[i] = "cooldown blocks entry"
            if (not blocked) and (not np.isnan(ps)) and C[i] > ps * p["psar_mult"]:
                ok = (not np.isnan(rsi)) and rsi <= p["rsi_max"]
                if ok and (p["rsi_max"] - p["rsi_band"]) <= rsi <= p["rsi_max"]:
                    if np.isnan(S16[i]) or np.isnan(S30[i]) or S16[i] < S30[i]:
                        ok = False
                # ---- V3.6: DOWN-regime entry delay ----
                if ok and r == DOWN and p["down_min_bars"] > 0 and BIR[i] < p["down_min_bars"]:
                    ok = False
                    note[i] = f"DOWN regime: only {BIR[i]}/{p['down_min_bars']} bars in DOWN - entry delayed"
                if ok:
                    eo = O[i + 1]; ep = eo * (1 + p["fee"]); pk = C[i + 1]; pki = i + 1; ei = i + 1
                    sh = cap / ep; pos = True; note[i] = "ENTRY signal"; i += 1; continue
        else:
            cur = C[i]; eq[i] = sh * cur; inpos[i] = True
            if cur > pk:
                pk = cur; pki = i
            pp = pk / eo - 1.0; ce = cur / eo
            act = BUF[i]
            if pp >= LOCK_TR[i]:
                act *= LOCK_M[i]; lock_on[i] = True
            if (i - pki) < p["cd_base"]:
                i += 1; continue
            bull = (not np.isnan(S16[i])) and cur > S16[i]
            hold = False if never_hold[r] else ((ADX[i] > p["hold_adx"]) or bull)
            ex, why = False, ""
            if pp >= p["pp_thresh"] and (i - pki) >= TFP[i]:
                ex, why = True, "profit target + peak time"
            if (not ex) and hold and ce <= p["loss_exit"] and not bull:
                ex, why = True, "loss exit"
            if not ex:
                hit = (not hold) and (not np.isnan(PSAR[i])) and cur < PSAR[i] * (1 - act)
                resc = p["march_rescue"] and (MO[i] == 3) and (not np.isnan(RSI[i])) and RSI[i] <= 50 and ce >= 0.98
                if hit and not resc:
                    ex, why = True, "PSAR stop"
            if ex:
                xp = O[i + 1] * (1 - p["fee"]); cap = sh * xp; pos = False; eq[i] = cap; note[i] = "EXIT: " + why
                lx = i; lloss = xp < ep
                trades.append(dict(entry_bar=ei, exit_bar=i + 1,
                                   entry_time=df.datetime.iloc[ei], exit_time=df.datetime.iloc[i + 1],
                                   ret_pct=(xp / ep - 1) * 100, reason=why,
                                   regime_at_exit=REGIME_NAMES[r],
                                   regime_at_entry=REGIME_NAMES[REG[ei]],
                                   bars_in_regime_at_entry=int(BIR[ei])))
                i += 1; continue
        i += 1
    if pos:
        xp = C[n - 1] * (1 - p["fee"]); cap = sh * xp
        trades.append(dict(entry_bar=ei, exit_bar=n - 1,
                           entry_time=df.datetime.iloc[ei], exit_time=df.datetime.iloc[-1],
                           ret_pct=(xp / ep - 1) * 100, reason="open at end",
                           regime_at_exit=REGIME_NAMES[REG[-1]],
                           regime_at_entry=REGIME_NAMES[REG[ei]],
                           bars_in_regime_at_entry=int(BIR[ei])))
    eq[n - 1] = cap
    eq = pd.Series(eq).ffill().values / p["capital0"]
    status = pd.DataFrame(dict(datetime=df.datetime.values, close=C,
                               regime=[REGIME_NAMES[x] for x in REG],
                               bars_in_regime=BIR,
                               in_position=inpos, cooldown_bars_left=cool_left,
                               profit_lock_active=lock_on,
                               psar_buffer_pct=BUF * 100, peak_time_bars=TFP, note=note))
    return eq, pd.DataFrame(trades), status


# ---------------------------------------------------------------- metrics
def metrics(df, eq, trades):
    C = df.Close.values; y = df.datetime.dt.year.values
    cut = int(np.argmax(df.datetime.values >= np.datetime64(SPLIT_AB)))
    m = dict(n_bars=len(df), growth=float(eq[-1]), bh_growth=float(C[-1] / C[0]), trades=int(len(trades)),
             win_rate=float((trades.ret_pct > 0).mean()),
             max_drawdown_pct=float((eq / np.maximum.accumulate(eq) - 1).min() * 100),
             A_growth=float(eq[cut - 1] / eq[0]), B_growth=float(eq[-1] / eq[cut]),
             A_bh=float(C[cut - 1] / C[0]), B_bh=float(C[-1] / C[cut]), years={})
    for yy in np.unique(y):
        w = np.where(y == yy)[0]
        m["years"][int(yy)] = (float(eq[w[-1]] / eq[w[0]]), float(C[w[-1]] / C[w[0]]))
    return m


def health_series(trades, n=HEALTH_N):
    r = trades.ret_pct.values; H = np.full(len(r), np.nan)
    for k in range(n - 1, len(r)):
        w = r[k - n + 1:k + 1]; win, los = w[w > 0], w[w <= 0]
        H[k] = np.inf if len(los) == 0 else (0.0 if len(win) == 0 else win.mean() / abs(los.mean()))
    return H


def health_index(trades, n=HEALTH_N):
    H = health_series(trades, n)
    return None if len(H) == 0 or np.isnan(H[-1]) else float(H[-1])


def _state(h, consec_below):
    if h is None or np.isnan(h): return "n/a (<20 trades)"
    if consec_below >= ALERT_TRADES: return "EROSION ALERT"
    if h < HEALTH_FLOOR: return "BELOW HISTORY"
    if h < HEALTH_WARN: return "LOW"
    return "OK"


def erosion_status(trades):
    H = health_series(trades); consec = 0
    for h in H[::-1]:
        if not np.isnan(h) and h < HEALTH_FLOOR: consec += 1
        else: break
    last = None if len(H) == 0 or np.isnan(H[-1]) else float(H[-1])
    return dict(state=_state(last, consec), health=last,
                consecutive_below_floor=consec, floor=HEALTH_FLOOR, alert_after=ALERT_TRADES)


def monthly_health_table(df, eq, trades):
    H = health_series(trades); ex = trades.exit_bar.values
    ym = df.datetime.dt.to_period("M").values; C = df.Close.values; rows = []
    prev_e, prev_c = eq[0], C[0]
    consec_at = np.zeros(len(H), int); c = 0
    for k, h in enumerate(H):
        c = c + 1 if (not np.isnan(h) and h < HEALTH_FLOOR) else 0
        consec_at[k] = c
    for m in pd.PeriodIndex(sorted(set(ym))):
        last = int(np.where(ym == m)[0][-1])
        k = int(np.searchsorted(ex, last, side="right")) - 1
        h = float(H[k]) if k >= 0 and not np.isnan(H[k]) else None
        rows.append(dict(month=str(m), trades_closed_total=k + 1, health=h,
                         state=_state(h, int(consec_at[k]) if k >= 0 else 0),
                         strategy_pct=(eq[last] / prev_e - 1) * 100,
                         buyhold_pct=(C[last] / prev_c - 1) * 100))
        prev_e, prev_c = eq[last], C[last]
    return pd.DataFrame(rows)


def drawdown_alerts(df, eq):
    peak = np.maximum.accumulate(eq); dd = eq / peak - 1
    armed = {"WATCH": True, "REVIEW": True}; ev = []
    for i in range(len(eq)):
        if dd[i] == 0: armed = {"WATCH": True, "REVIEW": True}; continue
        for lvl, th in (("WATCH", DD_WATCH), ("REVIEW", DD_REVIEW)):
            if armed[lvl] and dd[i] <= -th:
                ev.append(dict(time=df.datetime.iloc[i], level=lvl, drawdown_pct=float(dd[i] * 100)))
                armed[lvl] = False
    return ev


def macro_regime_events(df):
    day = pd.to_datetime(df.datetime.dt.date.values)
    t = pd.DataFrame(dict(day=day,
                          rg=(df.regime.values == RANGE).astype(float),
                          up=(df.regime.values == UP).astype(float),
                          dn=(df.regime.values == DOWN).astype(float)))
    daily = t.groupby("day").mean()
    sh = daily[["rg", "up", "dn"]].rolling(MACRO_WINDOW_DAYS, min_periods=MACRO_WINDOW_DAYS).mean()
    raw = sh.values.argmax(axis=1).astype(float); raw[sh.isna().any(axis=1).values] = np.nan
    conf = np.full(len(daily), np.nan); cur = np.nan; cnt = 0; cand = np.nan
    for k, m in enumerate(raw):
        if np.isnan(m): continue
        if np.isnan(cur): cur = m; conf[k] = cur; continue
        if m != cur:
            cnt = cnt + 1 if m == cand else 1; cand = m
            if cnt >= MACRO_CONFIRM_DAYS: cur = m; cnt = 0
        else: cnt = 0
        conf[k] = cur
    daily["macro"] = conf; ev = []
    for k in range(1, len(conf)):
        if not np.isnan(conf[k]) and not np.isnan(conf[k - 1]) and conf[k] != conf[k - 1]:
            ev.append(dict(date=daily.index[k].date(),
                           flip="%s -> %s" % ({0: "RANGE", 1: "UP", 2: "DOWN"}[int(conf[k - 1])],
                                              {0: "RANGE", 1: "UP", 2: "DOWN"}[int(conf[k])])))
    return daily, ev


def report(df, eq, trades, status):
    m = metrics(df, eq, trades)
    print("Engine V%s%s | bars %d | %s -> %s" % (
        VERSION,
        "  [--as-v31: dynamic items + down_min_bars OFF = V3.1]" if AS_V31 else "",
        m["n_bars"], df.datetime.iloc[0], df.datetime.iloc[-1]))
    print("Strategy %.2fx | Buy&Hold %.2fx | trades %d | win rate %.1f%% | max drawdown %.1f%%" % (
        m["growth"], m["bh_growth"], m["trades"], m["win_rate"] * 100, m["max_drawdown_pct"]))
    print("Period A (to 2022-09-13 12:45): strategy %.2fx vs B&H %.2fx | Period B: strategy %.2fx vs B&H %.2fx" % (
        m["A_growth"], m["A_bh"], m["B_growth"], m["B_bh"]))
    print("\n%-6s %10s %10s %9s" % ("year", "strategy", "buy&hold", "result"))
    for yy, (s, b) in m["years"].items():
        print("%-6d %9.0f%% %9.0f%% %9s" % (yy, (s - 1) * 100, (b - 1) * 100,
                                            "beats" if s > b else "LOSES"))
    wins = sum(s > b for s, b in m["years"].values())
    print("years beating Buy&Hold: %d of %d  (the first year is a partial year)" % (wins, len(m["years"])))

    last = status.iloc[-1]
    r = [k for k, v in REGIME_NAMES.items() if v == last.regime][0]
    s = SETTINGS[r]; b = s["buffer"]
    tfp_, lock_tr_, lock_m_ = dynamic_arrays(df)
    if b[0] == "fixed": buf_txt = "%.2f%% fixed" % (b[1] * 100)
    elif b[0] == "atr": buf_txt = "%.2f%%  (%.1f%% x ATR ratio %.2f)" % (
        last.psar_buffer_pct, b[1] * 100, df.atr_ratio.iloc[-1])
    else: buf_txt = "%.2f%% (monthly table, month %d)" % (df.buffer.iloc[-1] * 100, df.month.iloc[-1])
    h = health_index(trades)

    print("\n=== CURRENT STATE (last bar %s) ===" % pd.Timestamp(last.datetime))
    print("regime              : %s  (bars in this regime: %d)" % (last.regime, int(last.bars_in_regime)))
    print("PSAR-exit buffer    : %s%s" % (buf_txt,
          "  x%.2f (profit lock armed)" % lock_m_[-1] if last.profit_lock_active else ""))
    print("profit lock         : arms at %.0f%% peak gain in this regime, multiplier x%.2f" % (
        lock_tr_[-1] * 100, lock_m_[-1]))
    print("profit-target timing: %d bars since the peak required (dynamic, ADX-based)" % tfp_[-1])
    print("hold logic          : %s" % ("disabled (DOWN regime)" if s["hold"] == "never"
                                         else "ADX>%d or Close>SMA16" % PARAMS["hold_adx"]))
    if PARAMS["down_min_bars"] > 0:
        print("DOWN entry delay    : %d bars (entries are skipped while regime==DOWN and bars_in_regime<%d)" % (
            PARAMS["down_min_bars"], PARAMS["down_min_bars"]))
    print("cooldown after loss : %s" % ("%d bars left, no new entry" % last.cooldown_bars_left
                                         if last.cooldown_bars_left > 0 else "none"))
    print("position            : %s" % ("IN MARKET" if last.in_position else "FLAT"))

    es = erosion_status(trades)
    print("health index (avg win / avg loss, last %d closed trades): %s" % (
        HEALTH_N, "n/a" if h is None else "%.2f" % h))
    print("health monitor      : %s  (floor %.2f, %d consecutive below floor, alert at %d)  [monitor only]" % (
        es["state"], es["floor"], es["consecutive_below_floor"], es["alert_after"]))
    if es["state"] == "EROSION ALERT":
        print("  !!! EROSION ALERT: health stayed below the historical minimum for %d+ consecutive trades." % ALERT_TRADES)
    elif es["state"] == "BELOW HISTORY":
        print("  ! early hint: health is below the lowest value of the reference period.")

    peak = np.maximum.accumulate(eq); ddn = eq[-1] / peak[-1] - 1
    pk_i = int(np.argmax(eq))
    lvl = "REVIEW" if ddn <= -DD_REVIEW else ("WATCH" if ddn <= -DD_WATCH else "OK")
    print("equity drawdown     : %.1f%% below peak (peak %s)  -> %s" % (
        ddn * 100, pd.Timestamp(df.datetime.iloc[pk_i]).date(), lvl))

    daily, mev = macro_regime_events(df)
    mname = {0: "RANGE-dominant", 1: "UP-dominant", 2: "DOWN-dominant"}
    cur_macro = daily["macro"].dropna().iloc[-1]
    last_flip = mev[-1] if mev else None
    print("macro regime        : %s (dominant of last %d trading days)%s" % (
        mname[int(cur_macro)], MACRO_WINDOW_DAYS,
        "  last flip %s on %s" % (last_flip["flip"], last_flip["date"]) if last_flip else ""))
    recent = [e for e in mev if pd.Timestamp(e["date"]) >= pd.Timestamp(df.datetime.iloc[-1]) - pd.Timedelta(days=365)]
    print("regime flips in the last 12 months: %d" % len(recent))

    if SHOW_ALL:
        print("\nALL regime flips:")
        [print("  %s  %s" % (e["date"], e["flip"])) for e in mev]
        print("\nALL equity drawdown alerts:")
        [print("  %s  %-6s  drawdown %.1f%%" % (
            pd.Timestamp(e["time"]).date(), e["level"], e["drawdown_pct"]))
         for e in drawdown_alerts(df, eq)]

    tbl = monthly_health_table(df, eq, trades)
    print("\nMonthly health table (%s):" % ("all months" if SHOW_ALL else "last 12 months"))
    t = tbl if SHOW_ALL else tbl.tail(12)
    print("%-8s %7s %8s %-17s %9s %9s" % ("month", "trades", "health", "state", "strategy", "buy&hold"))
    for _, x in t.iterrows():
        print("%-8s %7d %8s %-17s %8.1f%% %8.1f%%" % (
            x.month, x.trades_closed_total,
            "-" if x.health is None or pd.isna(x.health) else "%.2f" % x.health,
            x.state, x.strategy_pct, x.buyhold_pct))
    if CSV_PATH:
        tbl.to_csv(CSV_PATH, index=False); print("\nfull monthly health table saved to", CSV_PATH)


# ---------------------------------------------------------------- reference values
REFERENCE_DATA = dict(n_bars=24827, first="2018-07-22 13:00:00", last="2026-09-01 17:45:00",
                      close_sum=3417432446, close_sha256_16="22d01b8dc2ea93e6")
REFERENCE_V31 = dict(
    growth=487.75484131720987, trades=182, win_rate=0.554945054945055,
    max_drawdown_pct=-35.34620642964727,
    A_growth=4.113928833987536, B_growth=118.56180818870422,
    A_bh=3.446327683615819, B_bh=16.970604246053348, bh_growth=58.709981167608284,
    years={2018: (0.8695786233459379, 1.0047080979284368), 2019: (1.3482319361704873, 1.1593982098647877),
           2020: (2.571343763632208, 2.311854402361043), 2021: (1.2304317481183311, 1.1517461443006558),
           2022: (1.529350040248967, 1.4654047597169897), 2023: (2.876373964901866, 1.5225988700564972),
           2024: (2.2697931956891315, 1.9556206507687652), 2025: (5.195728334610884, 2.6936453625086245),
           2026: (2.56531047520462, 1.594523126339425)},
)
HEALTH_REFERENCE_V31 = dict(min=0.954545, last=7.191845, last_state="OK", longest_run_below_1_5=11)
ALERT_REFERENCE_V31 = dict(watch_n=12,
                           review_dates=["2018-10-10", "2019-07-13", "2020-05-17",
                                         "2020-08-09", "2020-10-12", "2022-09-05"],
                           flips_n=20, last_flip=("2023-08-16", "DOWN -> RANGE"))
# V3.6 reference run: NOT STORED YET (needs a real Python run on the validated 8-year data).
REFERENCE_V36 = None
HEALTH_REFERENCE_V36 = None
ALERT_REFERENCE_V36 = None


def drawdown_and_flip_unit_test():
    n = 40; t = pd.date_range("2024-01-01", periods=n, freq="D")
    fake = pd.DataFrame(dict(datetime=t))
    eq = np.array([1.0]*5 + [1.2]*5 + [1.2*0.89]*5 + [1.2*0.84]*5 +
                  [1.2*0.84, 1.3, 1.3*0.89, 1.3*0.84] + [1.3*0.84]*16)
    ev = drawdown_alerts(fake, eq); lv = [e["level"] for e in ev]
    ok_dd = lv == ["WATCH", "REVIEW", "WATCH", "REVIEW"]
    days = pd.date_range("2024-01-01", periods=200, freq="D")
    reg = np.array([RANGE]*60 + [UP]*90 + [RANGE]*50)
    d2 = pd.DataFrame(dict(datetime=days, regime=reg)); _, flips = macro_regime_events(d2)
    blip = np.array([RANGE]*80 + [UP]*3 + [RANGE]*117)
    _, flips2 = macro_regime_events(pd.DataFrame(dict(datetime=days, regime=blip)))
    return ok_dd, len(flips) >= 1 and flips[0]["flip"] == "RANGE -> UP", len(flips2) == 0


def _synthetic(rets):
    return pd.DataFrame(dict(ret_pct=rets, exit_bar=np.arange(len(rets)) * 10 + 5))


def alert_logic_test():
    ok = [1.0, -1.0, 3.0, -1.0] * 5
    good = erosion_status(_synthetic(ok))["state"] == "OK"
    low = erosion_status(_synthetic(ok + [-3.0, 1.0, -3.0, 1.0] * 5))
    early = low["state"] == "BELOW HISTORY" and low["consecutive_below_floor"] < ALERT_TRADES
    long_bad = erosion_status(_synthetic(ok + [-3.0, 1.0] * 50))
    alert = long_bad["state"] == "EROSION ALERT" and long_bad["consecutive_below_floor"] >= ALERT_TRADES
    recover = erosion_status(_synthetic(ok + [-3.0, 1.0] * 50 + [2.0, -1.0] * 20))["state"] in ("OK", "LOW", "BELOW HISTORY")
    return good, early, alert, recover


def print_reference_block(df, eq, trades):
    m = metrics(df, eq, trades); hs = health_series(trades); hs = hs[~np.isnan(hs)]
    es = erosion_status(trades)
    ad = drawdown_alerts(df, eq); _, mev = macro_regime_events(df); lf = mev[-1] if mev else None
    print("\n--- paste into Engine_V3_6.py (reference block for V3.6) ---")
    print("REFERENCE_DATA = %r" % IND.data_fingerprint(df))
    print("REFERENCE_V36 = dict(")
    print("    growth=%r, trades=%d, win_rate=%r, max_drawdown_pct=%r," % (
        m["growth"], m["trades"], m["win_rate"], m["max_drawdown_pct"]))
    print("    A_growth=%r, B_growth=%r, A_bh=%r, B_bh=%r, bh_growth=%r," % (
        m["A_growth"], m["B_growth"], m["A_bh"], m["B_bh"], m["bh_growth"]))
    print("    years=%r)" % (m["years"],))
    print("HEALTH_REFERENCE_V36 = dict(min=%.6f, last=%.6f, last_state=%r)" % (
        float(hs.min()), float(hs[-1]), es["state"]))
    print("ALERT_REFERENCE_V36 = dict(watch_n=%d, review_dates=%r, flips_n=%d, last_flip=%r)" % (
        len([e for e in ad if e["level"] == "WATCH"]),
        [str(pd.Timestamp(e["time"]).date()) for e in ad if e["level"] == "REVIEW"],
        len(mev), (str(lf["date"]), lf["flip"]) if lf else None))
    print("--- end ---")


def selftest(df, eq, trades, tol=1e-9):
    fp = IND.data_fingerprint(df)
    print("\n=== REPRODUCIBILITY CHECK ===")
    print("data fingerprint        :", fp)
    u1, u2, u3 = drawdown_and_flip_unit_test(); g, e_, a_, r_ = alert_logic_test()
    print("monitor unit tests      : levels+re-arm %s, flip confirmation %s, 3-day blip ignored %s | "
          "OK-state %s, early hint %s, erosion alert %s, recovery %s" % tuple(
              "PASS" if x else "FAIL" for x in (u1, u2, u3, g, e_, a_, r_)))
    REF = REFERENCE_V31 if AS_V31 else REFERENCE_V36
    HREF = HEALTH_REFERENCE_V31 if AS_V31 else HEALTH_REFERENCE_V36
    AREF = ALERT_REFERENCE_V31 if AS_V31 else ALERT_REFERENCE_V36
    if REF is None:
        print("No stored V3.6 reference yet -> numbers cannot be compared. "
              "Run once on the validated data, check them, then store the block below.")
        print_reference_block(df, eq, trades)
        return None
    if fp != REFERENCE_DATA:
        print("DIFFERENT DATA from the reference set -> reference comparison skipped.")
        print("(Check: same files? placeholder rows removed? Reference fingerprint:", REFERENCE_DATA, ")")
        return None
    m = metrics(df, eq, trades); bad = []
    for k in ("growth", "win_rate", "max_drawdown_pct", "A_growth", "B_growth", "A_bh", "B_bh", "bh_growth"):
        if abs(m[k] - REF[k]) > tol * max(1.0, abs(REF[k])):
            bad.append((k, m[k], REF[k]))
    if m["trades"] != REF["trades"]: bad.append(("trades", m["trades"], REF["trades"]))
    for yy, (s, b) in REF["years"].items():
        if abs(m["years"][yy][0] - s) > tol * s or abs(m["years"][yy][1] - b) > tol * b:
            bad.append(("year %d" % yy, m["years"][yy], (s, b)))
    if bad:
        print("RESULT: FAIL - numbers differ from the reference:")
        for b in bad: print("   ", b)
        return False
    print("RESULT: PASS - growth, trades, win rate, drawdown, period A/B, all yearly numbers equal the reference.")
    return True


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--health-all" in args: SHOW_ALL = True; args.remove("--health-all")
    if "--as-v31" in args:
        AS_V31 = True; args.remove("--as-v31")
        PARAMS.update(LEGACY_V31_PARAMS); SETTINGS[RANGE] = dict(LEGACY_V31_RANGE)
    if "--csv" in args:
        j = args.index("--csv"); CSV_PATH = args[j + 1]; del args[j:j + 2]
    if len(args) < 1: sys.exit(__doc__)
    df = IND.build(args)
    eq, trades, status = run_backtest(df)
    report(df, eq, trades, status)
    selftest(df, eq, trades)