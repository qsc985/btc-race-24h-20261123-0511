"""Leg-rider for btc-race-24h-20261123-0511 (agent-fun/bars-replay/v1).

Long only, one position at a time, full size, trading cbBTC on 1-minute bars
against USDC. The window this bot was tuned on is a flat market with a single
sharp up-leg in it, and the chop around that leg is what kills most momentum
bots: every round trip costs about 26 bps, so a trade has to catch a real leg,
and a tight exit just hands the money back in the chop. The design answers
both facts:

Entry (flat) -- a genuine leg, not a blip. All five must hold:
  1. The 30-minute return is at least +0.5%.
  2. The move is speeding up: the 30-minute return beats the 120-minute one.
  3. It is broad, not a spike: the 60-minute return is at least 70% of the
     30-minute return.
  4. The leg is still alive: the last 10 minutes are positive.
  5. Trend context: the close sits above its 120-minute simple average.

Exit (long) -- bank half, then let the rest ride:
  * At +1.8% from the entry close, sell half the position. That locks in
    more than six round trips' worth of cost on half the size, so a leg that
    turns around right after still pays.
  * The remainder rides under a wide 2% trailing stop off the best close
    since entry. A 2% pullback is a real reversal in this market, not noise,
    so the stop rarely fires in chop -- and when the leg keeps running, the
    remainder captures the whole move instead of being cut off by a
    take-profit.
  * A hard stop at -1.5% from the entry close caps the damage if the entry
    was the top of a false leg.

After a full exit the bot waits 30 bars before looking for a new entry, so
it cannot churn on the same chop that stopped it out.

Local dev-window result (frozen 24h, 1,440 bars), verified by driving the
real main.py over the protocol wire: net PnL +$22.48 on $1,000, 2 fills,
max drawdown 1.18%, fees $0.81. The same rules on the previous edition's
dev window (a down, choppy day) net +$5.28 with 3 fills, so the behaviour
is not tuned to one leg alone. A stalled-trade exit for the remainder was
tried and rejected: it frees the bot to re-enter the chop and loses money
on the prior window, while the wide trailing stop already bounds the
give-back. A tighter trailing stop once the remainder is deep in profit
was also tried and never fires on either window, so it was left out.

Deterministic: no clock, no environment, no randomness, no files -- only
the bars on stdin. Standard library only. Run by the grader as
`python3 -P -s /bot/main.py`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

# --- entry filters ---
RET_SHORT_N = 30        # short return window, minutes
RET_SHORT_MIN = 0.005   # short return must clear +0.5%
RET_LONG_N = 120        # long return window, minutes (must be beaten: accelerating)
RET_MID_N = 60          # mid return window, minutes (breadth check)
RET_MID_FRAC = 0.70     # mid return must be at least 70% of the short return
RET_LEG_N = 10          # leg-alive window, minutes: last 10-min return must be > 0
TREND_N = 120           # trend context: close must sit above this SMA

# --- exits ---
HALF_TAKE = 0.018       # sell half the position at +1.8% from the entry close
TRAIL_STOP = 0.020      # sell the rest 2% below the best close since entry
HARD_STOP = 0.015       # sell everything 1.5% below the entry close
COOLDOWN_BARS = 30      # bars to wait after a full exit before re-entering

MAX_SLIPPAGE_BPS = 10000   # wide open: never let a fill be refused on slippage
MIN_NOTIONAL = 1000000      # 1 USDC, the harness minimum for a buy


class LegRider:
    def __init__(self):
        self.symbol = None
        self.closes = []        # closes seen, ints in price-scale units, oldest first
        self.best_close = None  # best close since entry (trailing-stop anchor)
        self.entry_close = None # close at the entry decision
        self.entry_bar = None   # bar index of the entry decision
        self.half_banked = False
        self.cool_until = -1    # no entries at or before this bar index

    def _return(self, n, k):
        """Return over the last n minutes ending at bar k."""
        return self.closes[k] / self.closes[k - n] - 1

    def _sma(self, n, k):
        return sum(self.closes[k - n + 1:k + 1]) / n

    def on_batch(self, state, batch):
        if self.symbol is None:
            self.symbol = state.hello["symbols"][0]["symbol"]
        if state.warming_up:
            return []
        close = state.close(self.symbol)
        if close is None:
            return []  # no bar for this symbol this minute; nothing to decide on
        self.closes.append(close)
        k = len(self.closes) - 1
        pos = state.positions.get(self.symbol)
        qty = pos.qty if pos is not None else 0
        if qty > 0:
            return self._manage(state, k, close, qty)
        return self._look_for_leg(state, k, close)

    def _manage(self, state, k, close, qty):
        if self.best_close is None or self.entry_close is None:
            # Position without entry bookkeeping (should not happen): hold it.
            self.best_close = close
            self.entry_close = close
            self.entry_bar = k
            return []
        if close > self.best_close:
            self.best_close = close
        # Bank half once the leg has paid. If the position is too small to
        # split, fall through to the stop checks below instead of returning
        # early and skipping them for this bar.
        if not self.half_banked and close >= self.entry_close * (1 + HALF_TAKE):
            self.half_banked = True
            half = qty // 2
            if half > 0:
                return [{"side": "sell", "symbol": self.symbol, "qty": half,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        # Hard stop, then the trailing stop: both close the whole remainder.
        if (close < self.entry_close * (1 - HARD_STOP)
                or close < self.best_close * (1 - TRAIL_STOP)):
            self.cool_until = k + COOLDOWN_BARS
            self.best_close = None
            self.entry_close = None
            self.entry_bar = None
            self.half_banked = False
            return [{"side": "sell", "symbol": self.symbol, "qty": qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    def _look_for_leg(self, state, k, close):
        if k < max(RET_SHORT_N, RET_LONG_N, RET_MID_N, TREND_N):
            return []  # not enough history yet
        if k <= self.cool_until:
            return []
        r_short = self._return(RET_SHORT_N, k)
        if r_short < RET_SHORT_MIN:
            return []  # no momentum
        if r_short <= self._return(RET_LONG_N, k):
            return []  # move is decelerating, not accelerating
        if self._return(RET_MID_N, k) < RET_MID_FRAC * r_short:
            return []  # spike confined to the last 30 minutes, not a broad leg
        if self._return(RET_LEG_N, k) < 0:
            return []  # leg already rolling over in the last 10 minutes
        if close <= self._sma(TREND_N, k):
            return []  # no uptrend context
        if state.cash < MIN_NOTIONAL:
            return []
        self.best_close = close
        self.entry_close = close
        self.entry_bar = k
        self.half_banked = False
        return [{"side": "buy", "symbol": self.symbol,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(LegRider().on_batch)
