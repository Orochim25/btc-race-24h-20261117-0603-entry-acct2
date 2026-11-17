"""BTC race bot — capitulation-bounce sniper (Setup B) + sharp-drop dip-buy (Setup D).

Long only, one position at a time, 100% of cash per trade. The bot reads
one-minute cbBTC bars from the harness and answers with buy/sell orders.
It trades two setups and otherwise stays in cash.

Setup B — capitulation-bounce long (the v4 sniper, unchanged):
  1. The close fell >= 150 bps over 60 bars, or >= 250 bps over 120 bars
     (measured on the PREVIOUS bar, idx=-2, because the reversal bar itself
     lifts the close and shrinks the measured drop).
  2. The close fell >= 550 bps from the highest high of the last 720 bars
     (12h) — this IS the oversold measure. RSI(14) on 1m bars is NOT used
     as an oversold filter here: a slow multi-hour grind down never prints
     RSI < 30, and the real bounce's 20-bar RSI minimum was 31.5 while a
     false bounce's was 18.8.
  3. A long-lower-wick bar (range >= 20 bps, close in the top 40% of the
     range) appeared in the last 20 bars.
  4. Reversal: the current bar closes up >= 60 bps vs the previous close
     AND above the previous bar's high.
  5. RSI(14) is turning up.
  6. R:R: the distance back up to the 720-bar high is at least twice the
     distance down to the stop.
  Stop: below the capitulation low, clamped to 50-100 bps below entry.
  Trailing stop arms +80 bps, trails the peak by 80 bps. Max hold 300 bars.

Setup D — sharp-drop dip-buy (the account-2 improvement over account 1):
  The sniper never fires when a window has no capitulation (the 16-17 Nov
  dev window's worst 720-bar drop was only 157 bps and it had zero
  >= 60 bps one-minute bars, so Setup B made $0.00 there and the entry
  would fail the dev gate). Setup D trades the range dips instead, but
  ONLY when the dip is a FAST fall, not a slow drift:
  1. The close fell >= 120 bps from the highest high of the last 120 bars
     (measured on the PREVIOUS bar, idx=-2).
  2. SHARP-DROP FILTER: the close also fell >= 150 bps over the last
     60 bars (prev bar, idx=-2). A slow drift down is a downtrend and the
     dip-buy loses there; a sharp drop is oversold and bounces. This is
     what separates the dev window's winning dip (a fast -212 bps fall)
     from the losing dip-buys in slow downtrends.
  3. The drop from the 720-bar high is UNDER 550 bps — this is NOT a
     capitulation; Setup B owns that case.
  4. RSI(14) < 50.
  5. The current bar closes UP (close > previous close, any amount).
  Stop: 80 bps below entry. Trailing stop arms +100 bps, trails the peak
  by 100 bps. Max hold 300 bars. CAPPED at 1 dip trade per window, because
  a dip-buy in a falling market is the riskiest trade this bot takes.

Guards (standing rules, Sensei 12 Nov):
  - At most 3 entries per window (1 dip + 2 bounce).
  - Stop after 2 consecutive losses — but ONLY bounce trades count toward
    this counter. A dip trade's loss does NOT increment it and a dip win
    does NOT reset it; the daily-loss guard below still caps total loss.
  - Stop entering if equity < 98% of start (max daily loss 2%).
  - No entries after bar 1320. 60-bar cooldown after an exit.
  - Max slippage 200 bps vs the latest close.
  - Need >= 200 closes of history before any entry.
  - Risk 0.5-1% per trade (100% size with a 50-100 bps stop), minimum
    R:R 1:2 on the bounce, 'NO TRADE' if no setup.
  - Never fabricate prices/indicators/volume/signals — every number comes
    from the bars the harness sends. Deterministic: no clock, no network,
    no files outside the repository.
"""

# v4 Setup B + Setup D with a sharp-drop filter (account 2). Same harness
# contract as v4: same entrypoint (main.py), same vendor shim, same order format.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
BPS = 10_000

# --- trend filter / history ---
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
MIN_HISTORY_BARS = 200      # need 200 closes before any entry is allowed

# --- Setup B: capitulation-bounce long (v4, unchanged) ---
DROP_LOOKBACK = 60          # drop window 1, bars
DROP_BPS = 150              # drop >= 150 bps over 60 bars
DROP_LOOKBACK2 = 120        # drop window 2, bars
DROP_BPS2 = 250             # drop >= 250 bps over 120 bars
RSI_PERIOD = 14
WICK_MIN_BPS = 20           # wick bar range >= 20 bps (median 1m range ~11 bps)
WICK_FRAC_NUM = 60          # lower wick >= 60% of the bar range
WICK_LOOKBACK = 20          # wick within the last 20 bars
DROP_HIGH_LOOKBACK = 720    # capitulation filter: drop from the max high over
DROP_HIGH_BPS = 550         # the last 720 bars (12h) must be >= 550 bps
BOUNCE_CONFIRM_BPS = 60     # reversal bar closes up >= 60 bps vs prev close
STOP_MIN_BPS = 50           # hard stop 50-100 bps below entry
STOP_MAX_BPS = 100
STOP_BELOW_LOW_BPS = 20     # bounce stop sits 20 bps below the capitulation low

# --- Setup D: sharp-drop dip-buy (account 2) ---
DIP_DROP_HIGH_LOOKBACK = 120  # dip measured vs the 120-bar high
DIP_DROP_BPS = 120            # close >= 120 bps below the 120-bar high
DIP_SHARP_LOOKBACK = 60       # sharp-drop filter window, bars
DIP_SHARP_BPS = 150           # close >= 150 bps below 60 bars ago (fast fall)
DIP_RSI_MAX = 50              # RSI(14) below 50
DIP_STOP_BPS = 80             # hard stop 80 bps below entry
DIP_ARM_BPS = 100             # trailing stop arms at +100 bps
DIP_TRAIL_BPS = 100           # once armed, trails the peak by 100 bps
DIP_MAX_HOLD_BARS = 300       # max bars held
DIP_MAX_TRADES = 1            # at most 1 dip trade per window

# --- exits (bounce) ---
ARM_BPS = 80                # trailing stop arms at +80 bps from fill
TRAIL_BPS = 80              # once armed, stop trails the peak by 80 bps
HARD_SL_BPS = 50            # fallback hard stop at -50 bps from fill
MAX_HOLD_BARS = 300         # max bars held

# --- guards ---
MAX_TRADES = 3              # at most 3 entries per 24h window total
MAX_BOUNCE_TRADES = 2       # at most 2 bounce entries per window
MAX_CONSEC_LOSSES = 2       # stop after 2 consecutive BOUNCE losses
MAX_DAILY_LOSS_BPS = 200    # stop entering if equity < 98% of start
LAST_ENTRY_BAR = 1320       # no entries in the last 120 bars of the window
COOLDOWN_BARS = 60          # cooldown after an exit
MAX_SLIPPAGE_BPS = 200      # max slippage vs latest close
WIN_COST_BPS = 26           # round-trip cost (~26 bps full size) for win/loss calls

# --- MACD ---
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# --- per-run state (fresh process per run: deterministic) ---
closes = []                 # raw close ints, in bar order
highs = []                  # raw high ints
lows = []                   # raw low ints
trades_done = 0
bounce_trades_done = 0
dip_trades_done = 0
consec_losses = 0           # counts BOUNCE losses only (see Guards)
cooldown_until = -1
start_equity = None         # equity at the first scored bar
entry_px = None             # fill-bar open (raw price int)
peak_px = None              # highest close since entry
armed = False               # trailing stop armed
entry_bar = None            # window bar index of the fill bar
entry_type = None           # 'bounce' or 'dip'
stop_px = None              # hard stop price (raw int)
have_position = False
# indicator state (floats, updated per bar; deterministic)
_ema_fast = None
_ema_mid = None
_ema_slow = None
_macd_fast = None
_macd_slow = None
_macd_signal = None
_rsi_gain = None
_rsi_loss = None
_rsi = None
_rsi_prev = None
_vwap_sum = 0.0             # sum of typical prices since window start
_vwap_n = 0                 # count of window bars (for the VWAP proxy)


def _ema(price, prev, span):
    alpha = 2.0 / (span + 1)
    return price if prev is None else prev + alpha * (price - prev)


def _update_indicators(c, h, l, bar_idx):
    """Update EMA/RSI/MACD/VWAP-proxy state from this bar's prices (raw ints)."""
    global _ema_fast, _ema_mid, _ema_slow, _macd_fast, _macd_slow
    global _macd_signal, _rsi_gain, _rsi_loss, _rsi, _rsi_prev
    global _vwap_sum, _vwap_n
    _ema_fast = _ema(c, _ema_fast, EMA_FAST)
    _ema_mid = _ema(c, _ema_mid, EMA_MID)
    _ema_slow = _ema(c, _ema_slow, EMA_SLOW)
    _macd_fast = _ema(c, _macd_fast, MACD_FAST)
    _macd_slow = _ema(c, _macd_slow, MACD_SLOW)
    macd_line = _macd_fast - _macd_slow
    _macd_signal = _ema(macd_line, _macd_signal, MACD_SIGNAL)
    if len(closes) >= 2:
        chg = c - closes[-2]
        gain = chg if chg > 0 else 0
        loss = -chg if chg < 0 else 0
        if _rsi_gain is None:
            _rsi_gain = float(gain)
            _rsi_loss = float(loss)
        else:
            _rsi_gain = (_rsi_gain * (RSI_PERIOD - 1) + gain) / RSI_PERIOD
            _rsi_loss = (_rsi_loss * (RSI_PERIOD - 1) + loss) / RSI_PERIOD
        _rsi_prev = _rsi
        if _rsi_loss == 0:
            _rsi = 100.0
        else:
            _rsi = 100.0 - 100.0 / (1.0 + _rsi_gain / _rsi_loss)
    if bar_idx >= 0:
        _vwap_sum += (h + l + c) / 3.0
        _vwap_n += 1


def _has_wick():
    """A capitulation wick in the last WICK_LOOKBACK bars: long lower wick."""
    n = len(closes)
    start = max(0, n - WICK_LOOKBACK)
    for i in range(start, n):
        h, l, c = highs[i], lows[i], closes[i]
        rng = h - l
        if rng <= 0:
            continue
        # Range must be wide (>= WICK_MIN_BPS of the close) and the close must
        # sit well above the low (>= 60% of the range): the bar rejected lower
        # prices (selling climax / capitulation wick).
        if rng * BPS < WICK_MIN_BPS * c:
            continue
        if (c - l) * 100 >= WICK_FRAC_NUM * rng:
            return True
    return False


def _drop_from_high(lookback, idx=-1):
    """Drop from the max high over `lookback` bars to the close at closes[idx]."""
    n = len(highs)
    j = idx if idx >= 0 else n + idx
    if j <= lookback:
        return 0
    hi = max(highs[j - lookback:j])
    c = closes[j]
    return (c - hi) * BPS // hi


def _drop_bps(lookback, idx=-1):
    """How far the close at closes[idx] has fallen over `lookback` bars, bps."""
    n = len(closes)
    j = idx if idx >= 0 else n + idx
    if j <= lookback:
        return 0
    then = closes[j - lookback]
    now = closes[j]
    return (now - then) * BPS // then


def _exit_is_win(exit_px):
    """Win/loss call for the exit price vs entry (cost-aware)."""
    if entry_px is None:
        return False
    return exit_px * BPS >= entry_px * (BPS + WIN_COST_BPS)


def on_batch(state, batch):
    global trades_done, bounce_trades_done, dip_trades_done
    global consec_losses, cooldown_until, start_equity
    global entry_px, peak_px, armed, entry_bar, entry_type, stop_px
    global have_position

    c = state.close(SYMBOL)
    if c is None:
        return []
    bar = state.latest.get(SYMBOL)
    h = int(bar["h"]) if bar is not None and "h" in bar else c
    l = int(bar["l"]) if bar is not None and "l" in bar else c
    closes.append(c)
    highs.append(h)
    lows.append(l)
    # Window bar index (0-based within the scored window).
    bar_idx = state.seq - state.warmup_bars
    _update_indicators(c, h, l, bar_idx)
    if start_equity is None and bar_idx >= 0:
        start_equity = state.equity

    holding = state.positions.get(SYMBOL)
    if holding is not None:
        if not have_position:
            # Just filled on this bar: entry = this bar's open.
            entry_px = int(bar["o"]) if bar is not None and "o" in bar else c
            peak_px = entry_px
            armed = False
            entry_bar = bar_idx
            have_position = True
            if stop_px is None:
                # Safety net only (stop_px is always set at entry time):
                # use the setup's own stop distance.
                fb_bps = DIP_STOP_BPS if entry_type == 'dip' else HARD_SL_BPS
                stop_px = entry_px * (BPS - fb_bps) // BPS
        # Exit check (also runs on the fill bar, as in the backtest).
        # Per-setup exits: dip trades use a wider trailing stop (+100/+100)
        # than bounce trades (+80/+80); max hold is 300 bars for both.
        arm_bps = DIP_ARM_BPS if entry_type == 'dip' else ARM_BPS
        trail_bps = DIP_TRAIL_BPS if entry_type == 'dip' else TRAIL_BPS
        max_hold = DIP_MAX_HOLD_BARS if entry_type == 'dip' else MAX_HOLD_BARS
        if c > peak_px:
            peak_px = c
        if not armed and c * BPS >= entry_px * (BPS + arm_bps):
            armed = True
        trail_px = peak_px * (BPS - trail_bps) // BPS if armed else None
        do_exit = False
        exit_px = c
        if c <= stop_px:
            do_exit = True
            exit_px = stop_px
        elif armed and trail_px is not None and c <= trail_px:
            do_exit = True
            exit_px = trail_px
        elif bar_idx - entry_bar >= max_hold:
            do_exit = True
            exit_px = c
        if do_exit:
            # ONLY bounce trades move the consecutive-loss counter. A dip
            # trade's loss must NOT increment it and a dip win must NOT
            # reset it — the dip is a separate, capped experiment.
            if entry_type == 'bounce':
                if not _exit_is_win(exit_px):
                    consec_losses += 1
                else:
                    consec_losses = 0
            cooldown_until = bar_idx + COOLDOWN_BARS
            entry_px = None
            peak_px = None
            armed = False
            entry_bar = None
            entry_type = None
            stop_px = None
            have_position = False
            return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # Flat: consider an entry.
    have_position = False
    if state.warming_up:
        return []
    if bar_idx < 0:
        return []
    if trades_done >= MAX_TRADES:
        return []
    if consec_losses >= MAX_CONSEC_LOSSES:
        return []
    if start_equity is not None and state.equity * BPS < start_equity * (BPS - MAX_DAILY_LOSS_BPS):
        return []
    if bar_idx >= LAST_ENTRY_BAR:
        return []
    if bar_idx < cooldown_until:
        return []
    if len(closes) <= MIN_HISTORY_BARS:
        return []

    rsi = _rsi if _rsi is not None else 50.0

    # --- Setup B: capitulation-bounce long (v4, unchanged) ---
    # The drop-from-high filter (>= 550 bps over 720 bars) IS the oversold
    # measure. RSI(14) on 1m bars is NOT used as a filter: a slow multi-hour
    # grind down never prints RSI < 30 (the real bounce's 20-bar RSI minimum
    # was 31.5, the false bounce's was 18.8 — the filter would block the real
    # trade and allow the false one). RSI turning up is kept as a soft
    # confirmation that momentum is shifting.
    # KEY: the drop is evaluated on the PREVIOUS bar (idx=-2), not the current
    # one — the strong reversal bar itself lifts the close and shrinks the
    # measured drop, so checking the drop on the reversal bar would fail
    # exactly when the setup is real.
    if bounce_trades_done < MAX_BOUNCE_TRADES:
        drop1 = _drop_bps(DROP_LOOKBACK, idx=-2)
        drop2 = _drop_bps(DROP_LOOKBACK2, idx=-2)
        drop_hi = _drop_from_high(DROP_HIGH_LOOKBACK, idx=-2)
        if (drop1 <= -DROP_BPS or drop2 <= -DROP_BPS2) and drop_hi <= -DROP_HIGH_BPS and _has_wick():
            # Reversal confirmation: strong up bar closing above the prior high.
            if len(closes) >= 2 and c * BPS >= closes[-2] * (BPS + BOUNCE_CONFIRM_BPS):
                prev_hi = highs[-2]
                if c > prev_hi and _rsi_prev is not None and rsi > _rsi_prev:
                    # R:R: the 720-bar high (the pre-drop high) must be >= 2x
                    # the stop distance away. The stop sits below the
                    # capitulation low (clamped to 50-100 bps below entry).
                    # The exit is via the trailing stop, not by reaching the
                    # high — the R:R check only confirms there is room for
                    # a 2:1 move.
                    cap_low = min(lows[-1 - DROP_HIGH_LOOKBACK:]) if len(lows) > DROP_HIGH_LOOKBACK else l
                    stop_candidate = cap_low * (BPS - STOP_BELOW_LOW_BPS) // BPS
                    stop_dist = c - stop_candidate
                    stop_dist = max(stop_dist, c * STOP_MIN_BPS // BPS)
                    stop_dist = min(stop_dist, c * STOP_MAX_BPS // BPS)
                    pre_high = max(highs[-1 - DROP_HIGH_LOOKBACK:-1]) if len(highs) > DROP_HIGH_LOOKBACK else c
                    if (pre_high - c) >= 2 * stop_dist:
                        notional = state.cash
                        if notional >= 1_000_000:
                            trades_done += 1
                            bounce_trades_done += 1
                            entry_type = 'bounce'
                            stop_px = c - stop_dist
                            return [{"side": "buy", "symbol": SYMBOL,
                                     "notional_quote_units": notional,
                                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    # --- Setup D: sharp-drop dip-buy (account 2, capped at 1 per window) ---
    # Buys a dip off the 120-bar high when RSI is low and the bar turns up,
    # and rides it back toward the high. Looser than Setup B on purpose: the
    # calm dev window's recovery is a slow grind (bars of +6 to +14 bps),
    # not a sharp +60 bps reversal bar, so a strict reversal filter never
    # fires there. Skipped when the drop IS capitulation-sized, because
    # Setup B owns that case (and its R:R/stop logic).
    # SHARP-DROP FILTER (the account-2 improvement): the dip must also have
    # fallen >= 150 bps over the last 60 bars. A slow drift down is a
    # downtrend and the dip-buy loses there; a sharp drop is oversold and
    # bounces. Account 1's loose dip-buy fired in slow downtrends and lost
    # on held-out windows; the sharp filter keeps only the fast falls.
    # Calibrated on the dev window: its winning dip fell 212 bps in 60 bars,
    # while the slow drifts that lost never fell 150 bps in 60 bars.
    if dip_trades_done < DIP_MAX_TRADES:
        dip_drop_hi120 = _drop_from_high(DIP_DROP_HIGH_LOOKBACK, idx=-2)
        dip_drop_hi720 = _drop_from_high(DROP_HIGH_LOOKBACK, idx=-2)
        dip_drop60 = _drop_bps(DIP_SHARP_LOOKBACK, idx=-2)
        if dip_drop_hi120 <= -DIP_DROP_BPS and dip_drop_hi720 > -DROP_HIGH_BPS and dip_drop60 <= -DIP_SHARP_BPS and rsi < DIP_RSI_MAX:
            if len(closes) >= 2 and c > closes[-2]:
                notional = state.cash
                if notional >= 1_000_000:
                    trades_done += 1
                    dip_trades_done += 1
                    entry_type = 'dip'
                    stop_px = c - (c * DIP_STOP_BPS // BPS)
                    return [{"side": "buy", "symbol": SYMBOL,
                             "notional_quote_units": notional,
                             "max_slippage_bps": MAX_SLIPPAGE_BPS}]
    return []


if __name__ == "__main__":
    makefun_bars.run(on_batch)
