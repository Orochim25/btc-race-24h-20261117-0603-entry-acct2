"""BTC race bot: a sharp-drop dip buyer with a capitulation-bounce sniper.

Long only, at most one open position, full cash behind every trade. The
harness sends one-minute cbBTC bars; this bot answers each batch with at
most a single order (a buy to enter, a sell to exit) and otherwise stays
in cash. Two long setups:

  * Dip buy (Setup D): buy a fast dip inside a range. The close must have
    fallen hard from the recent high, RSI(14) must sit under 50, the latest
    bar must close up, and -- the account-2 edge -- the fall itself must be
    a sharp 60-bar drop, not a slow drift down. A slow drift is a downtrend
    and the dip buy loses there; a sharp drop is oversold and bounces.
  * Bounce (Setup B): buy the reversal after a real capitulation, when the
    close has fallen a long way from the 720-bar high, a long lower wick
    printed recently, the current bar reverses up hard above the previous
    high, RSI turns up, and the room back to the high is at least twice
    the risk to the stop.

Both exits use a hard stop plus a trailing stop that arms once the trade
is in profit, and a 300-bar maximum hold. Guards cap total entries,
count only bounce losses toward the consecutive-loss stop, halt entries
below 98% of starting equity, and forbid entries late in the window.
Deterministic: no clock, no network, no files, no randomness.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
BPS = 10_000

# --- history and indicator settings ---
MIN_BARS = 200            # closes needed before any entry is allowed
RSI_LEN = 14

# --- Setup B: capitulation bounce ---
B_DROP60_BPS = 150        # fall over 60 bars (prev bar), or ...
B_DROP120_BPS = 250       # ... fall over 120 bars (prev bar)
B_DROP720_BPS = 550       # fall from the highest high of the last 720 bars
B_WICK_RANGE_BPS = 20     # wick bar range at least 20 bps
B_WICK_FRAC = 60          # close in the top 40% of its bar (lower wick >= 60%)
B_WICK_LOOKBACK = 20      # wick bar within the last 20 bars
B_REVERSAL_BPS = 60       # reversal bar up >= 60 bps and above the prev high
B_STOP_LO_BPS = 100       # stop clamped to 50..100 bps below the entry
B_STOP_HI_BPS = 50
B_STOP_BELOW_LOW_BPS = 20 # stop sits 20 bps under the capitulation low
B_ARM_BPS = 80            # trailing stop arms at +80 bps
B_TRAIL_BPS = 80          # ... then trails the peak by 80 bps
B_MAX_HOLD = 300
B_MAX_TRADES = 2

# --- Setup D: sharp-drop dip buy ---
D_DROP120_BPS = 120       # fall from the highest high of the last 120 bars
D_DROP720_MAX_BPS = 550   # the 720-bar fall must stay UNDER this
D_RSI_MAX = 50            # RSI(14) under 50
D_SHARP60_BPS = 150       # ... AND a fall of >= 150 bps over the last 60 bars
D_STOP_BPS = 80           # hard stop 80 bps under the entry
D_ARM_BPS = 100           # trailing stop arms at +100 bps
D_TRAIL_BPS = 100         # ... then trails the peak by 100 bps
D_MAX_HOLD = 300
D_MAX_TRADES = 1

# --- standing guards ---
MAX_TRADES = 3            # at most 3 entries per window (1 dip + 2 bounce)
MAX_CONSEC_BOUNCE_LOSSES = 2   # stop after 2 consecutive BOUNCE losses
MAX_DAILY_LOSS_BPS = 200  # stop entering if equity drops under 98% of start
LAST_ENTRY_SEQ = 1320     # no entries after bar 1320
COOLDOWN_BARS = 60        # bars to wait after an exit
MAX_SLIP_BPS = 200        # max slippage vs the latest close
ROUNDTRIP_COST_BPS = 26   # full-size round trip costs ~26 bps (win/loss calls)

# --- per-run state (fresh process per run: deterministic) ---
closes = []               # close ints, in bar order
highs = []                # high ints
lows = []                 # low ints
rsi_hist = []             # RSI(14) per bar, None until enough closes
_avg_gain = None          # Wilder RSI running averages
_avg_loss = None

holding_kind = None       # None, "dip" or "bounce" while a position is open
entry_px = 0              # reference entry price (the close we decided on)
entry_seq = -1            # seq of the bar where the fill landed
peak_px = 0               # highest close since entry
stop_px = 0               # current stop level
trail_on = False          # trailing stop armed
cap_low_px = 0            # capitulation low stored at a bounce decision
pending_kind = None       # kind of the buy order sent on the last batch
pending_px = 0            # its reference entry price
pending_cap_low = 0       # its capitulation low (bounce only)
dip_trades = 0
bounce_trades = 0
total_trades = 0
bounce_losses = 0
cooldown_until = -1
start_equity = 0
last_bar_t = None          # close time of the last bar actually appended


def _rsi_update():
    """Append the RSI(14) for the newest close (Wilder's smoothing)."""
    global _avg_gain, _avg_loss
    n = len(closes)
    if n < 2:
        rsi_hist.append(None)
        return
    chg = closes[-1] - closes[-2]
    gain = chg if chg > 0 else 0
    loss = -chg if chg < 0 else 0
    if n == RSI_LEN + 1:
        # First value: plain mean of the first RSI_LEN changes.
        gs = 0
        ls = 0
        for i in range(1, RSI_LEN + 1):
            d = closes[i] - closes[i - 1]
            if d > 0:
                gs += d
            else:
                ls -= d
        _avg_gain = gs / RSI_LEN
        _avg_loss = ls / RSI_LEN
    elif n > RSI_LEN + 1:
        _avg_gain = (_avg_gain * (RSI_LEN - 1) + gain) / RSI_LEN
        _avg_loss = (_avg_loss * (RSI_LEN - 1) + loss) / RSI_LEN
    else:
        rsi_hist.append(None)
        return
    if _avg_loss == 0:
        rsi_hist.append(100.0)
    else:
        rs = _avg_gain / _avg_loss
        rsi_hist.append(100.0 - 100.0 / (1.0 + rs))


def _bps_below(ref_px, px):
    """How far px sits below ref_px, in basis points (integer math)."""
    if ref_px <= 0:
        return 0
    return (ref_px - px) * BPS // ref_px


def _has_wick():
    """True when a long-lower-wick bar sits in the last B_WICK_LOOKBACK
    bars ending at the previous bar: range at least B_WICK_RANGE_BPS and
    the close in the top 40% of its own range."""
    end = len(closes) - 1          # previous bar index (exclusive bound)
    start = max(0, end - B_WICK_LOOKBACK)
    for j in range(start, end):
        h = highs[j]
        lo = lows[j]
        c = closes[j]
        span = h - lo
        if span <= 0:
            continue
        if (span * BPS // c) < B_WICK_RANGE_BPS:
            continue
        if (c - lo) * 100 // span >= B_WICK_FRAC:
            return True
    return False


def _bounce_setup():
    """Check every Setup B condition on the latest bars.

    Returns (ok, stop_px, cap_low): the prospective stop and the
    capitulation low when the setup fires, else (False, 0, 0).
    All fall measures anchor on the previous bar (idx -2), because the
    reversal bar itself lifts the close and would shrink the drop.
    """
    m = len(closes)
    if m < 2 or rsi_hist[-1] is None or rsi_hist[-2] is None:
        return (False, 0, 0)
    prev = closes[-2]
    cur = closes[-1]
    # 1. deep fall measured at the previous bar: 60 bars or 120 bars.
    fall60 = _bps_below(closes[-62], prev) if m >= 62 else 0
    fall120 = _bps_below(closes[-122], prev) if m >= 122 else 0
    if fall60 < B_DROP60_BPS and fall120 < B_DROP120_BPS:
        return (False, 0, 0)
    # 2. capitulation: the fall from the 720-bar high must reach 550 bps.
    hi720 = max(highs[-721:-1])
    if _bps_below(hi720, prev) < B_DROP720_BPS:
        return (False, 0, 0)
    # 3. a long lower wick printed in the last 20 bars.
    if not _has_wick():
        return (False, 0, 0)
    # 4. reversal: this bar closes up >= 60 bps and above the prev high.
    if (cur - prev) * BPS // prev < B_REVERSAL_BPS:
        return (False, 0, 0)
    if cur <= highs[-2]:
        return (False, 0, 0)
    # 5. RSI(14) turning up.
    if rsi_hist[-1] <= rsi_hist[-2]:
        return (False, 0, 0)
    # 6. reward/risk: room back to the 720-bar high at least twice the risk.
    cap_low = min(lows[-721:-1])
    stop0 = cap_low * (BPS - B_STOP_BELOW_LOW_BPS) // BPS
    lo_stop = cur * (BPS - B_STOP_LO_BPS) // BPS
    hi_stop = cur * (BPS - B_STOP_HI_BPS) // BPS
    stop = min(max(stop0, lo_stop), hi_stop)
    if hi720 - cur < 2 * (cur - stop):
        return (False, 0, 0)
    return (True, stop, cap_low)


def _dip_setup():
    """Check every Setup D condition on the latest bars.

    A range dip that is also a FAST fall: the close dropped hard from the
    120-bar high, is not a capitulation (720-bar fall under 550 bps),
    RSI(14) sits under 50, this bar closes up, and the close also fell
    at least 150 bps over the last 60 bars (the sharp-drop filter).
    """
    m = len(closes)
    if m < 2 or rsi_hist[-1] is None:
        return False
    prev = closes[-2]
    cur = closes[-1]
    # 1. fall from the highest high of the last 120 bars (prev bar).
    hi120 = max(highs[-121:-1])
    if _bps_below(hi120, prev) < D_DROP120_BPS:
        return False
    # 2. not a capitulation: the 720-bar fall stays under 550 bps.
    hi720 = max(highs[-721:-1])
    if _bps_below(hi720, prev) >= D_DROP720_MAX_BPS:
        return False
    # 3. RSI(14) under 50.
    if rsi_hist[-1] >= D_RSI_MAX:
        return False
    # 4. this bar closes up (any amount).
    if cur <= prev:
        return False
    # 5. sharp-drop filter: fall of >= 150 bps over the last 60 bars.
    if _bps_below(closes[-62], prev) < D_SHARP60_BPS:
        return False
    return True


def _exit_now(state):
    """Sell the whole open position at the latest close (max slippage)."""
    holding = state.positions.get(SYMBOL)
    if holding is None:
        return []
    return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
             "max_slippage_bps": MAX_SLIP_BPS}]


def on_batch(state, batch):
    """Decide the orders for one batch. At most one order per reply."""
    global holding_kind, entry_px, entry_seq, peak_px, stop_px, trail_on
    global cap_low_px, pending_kind, pending_px, pending_cap_low
    global dip_trades, bounce_trades, total_trades, bounce_losses
    global cooldown_until, start_equity, last_bar_t

    if state.warming_up:
        return []
    bar = state.latest.get(SYMBOL)
    if bar is None:
        return []
    # A batch with no new bar for the symbol (a missing minute) must not
    # duplicate the previous close into the history: skip it entirely.
    if state.t == last_bar_t:
        return []
    last_bar_t = state.t
    closes.append(int(bar["c"]))
    highs.append(int(bar["h"]))
    lows.append(int(bar["l"]))
    _rsi_update()

    if start_equity == 0:
        start_equity = state.equity

    holding = state.positions.get(SYMBOL)

    # A buy sent on the last batch has filled when we now hold the symbol.
    if pending_kind is not None:
        if holding is not None:
            holding_kind = pending_kind
            entry_px = pending_px
            entry_seq = state.seq
            peak_px = entry_px
            cap_low_px = pending_cap_low
            if holding_kind == "dip":
                stop_px = entry_px * (BPS - D_STOP_BPS) // BPS
            else:
                stop0 = cap_low_px * (BPS - B_STOP_BELOW_LOW_BPS) // BPS
                lo_stop = entry_px * (BPS - B_STOP_LO_BPS) // BPS
                hi_stop = entry_px * (BPS - B_STOP_HI_BPS) // BPS
                stop_px = min(max(stop0, lo_stop), hi_stop)
            trail_on = False
        pending_kind = None
        pending_px = 0
        pending_cap_low = 0

    # A position with no tracked entry (a sell was rejected last batch):
    # flatten it rather than trading around it.
    if holding is not None and holding_kind is None:
        return _exit_now(state)

    if holding is not None and holding_kind is not None:
        # --- manage the open position: hard stop, trailing stop, max hold.
        cur = closes[-1]
        if cur > peak_px:
            peak_px = cur
        if holding_kind == "dip":
            arm, trail, max_hold = D_ARM_BPS, D_TRAIL_BPS, D_MAX_HOLD
        else:
            arm, trail, max_hold = B_ARM_BPS, B_TRAIL_BPS, B_MAX_HOLD
        if peak_px >= entry_px * (BPS + arm) // BPS:
            trail_on = True
        if trail_on:
            cand = peak_px * (BPS - trail) // BPS
            if cand > stop_px:
                stop_px = cand
        done = False
        if cur <= stop_px:
            done = True
        if state.seq - entry_seq >= max_hold:
            done = True
        if done:
            # Win/loss for the bounce counter only; dip trades never count.
            if holding_kind == "bounce":
                if cur >= entry_px * (BPS + ROUNDTRIP_COST_BPS) // BPS:
                    bounce_losses = 0
                else:
                    bounce_losses += 1
            cooldown_until = state.seq + COOLDOWN_BARS
            holding_kind = None
            return _exit_now(state)
        return []

    # --- flat: look for an entry, under the standing guards. ---
    if len(closes) < MIN_BARS:
        return []
    if state.seq > LAST_ENTRY_SEQ:
        return []
    if state.seq <= cooldown_until:
        return []
    if total_trades >= MAX_TRADES:
        return []
    if bounce_losses >= MAX_CONSEC_BOUNCE_LOSSES:
        return []
    if state.equity < start_equity * (BPS - MAX_DAILY_LOSS_BPS) // BPS:
        return []

    # Setup B first; it is mutually exclusive with D via the 720-bar fall.
    ok_b, _stop_b, cap_low = _bounce_setup()
    if ok_b and bounce_trades < B_MAX_TRADES:
        pending_kind = "bounce"
        pending_px = closes[-1]
        pending_cap_low = cap_low
        bounce_trades += 1
        total_trades += 1
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIP_BPS}]

    if _dip_setup() and dip_trades < D_MAX_TRADES:
        pending_kind = "dip"
        pending_px = closes[-1]
        pending_cap_low = 0
        dip_trades += 1
        total_trades += 1
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIP_BPS}]

    return []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
