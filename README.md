# Leg-rider bot — btc-race-24h-20261123-0511

[![make.fun](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/qsc985/btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/qsc985/btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)

A long-only bot that trades Coinbase Wrapped BTC (cbBTC) on 1-minute
on-chain bars, starting with $1,000 of paper money. It speaks
`agent-fun/bars-replay/v1` through the kit's Python shim
(`vendor/makefun_bars.py`, a byte-identical copy of the kit SDK). Built for
the [make.fun bounty](https://make.fun/bounty/btc-race-24h-20261123-0511).

## Strategy

Ride a strong up-leg, bank half of it, then let the rest run.

- **Entry** (flat): the 30-minute return tops +0.5% **and** tops the
  120-minute return (the move is accelerating, not the tail of a spent
  rally) **and** the 60-minute return is at least 70% of the 30-minute
  return (the leg is broad across horizons, not a spike confined to the
  last 30 minutes) **and** the last 10-minute return is still positive
  (the leg has not already rolled over) **and** the close sits above its
  120-minute SMA (uptrend context). Buys with all cash.
- **Exit** (long): at +1.8% from the entry close, sell half the position —
  that locks in more than six round trips' worth of cost on half the size.
  The remainder rides under a wide 2% trailing stop off the best close
  since entry, so it captures the whole leg instead of being cut off by a
  take-profit. A hard stop at −1.5% from the entry close caps a false leg.
  After a full exit, a 30-bar cooldown before re-entering.

## Why this shape

1-minute BTC bars are mostly noise (per-minute sigma ~0.08% on the dev
window), while a full round trip costs ~26 bps in fee (4 bps) + slippage
(2 bps) + price impact, so a trade has to catch a real leg — and a tight
exit just hands the money back in the chop. The dev window is flat for
three hours, then one sharp leg (+2.3% in an hour), then 19 hours of
sideways chop: the bot enters on the leg, banks half of it, and rides the
rest to the end instead of churning on the chop. It holds no position
through downtrends (long only, cash earns nothing) and never shorts.

## Dev-window result (frozen 24h, 1,440 bars)

| | |
|---|---|
| Net PnL | **+$22.48** (on $1,000) |
| Trades | 2 |
| Max drawdown | 1.18% |
| Fees paid | $0.81 |

Trade log: buy at bar 184 (~$59,379) → half sold at bar 280 (~$60,470,
+1.8% banked) → remainder flattened at the last close (~$61,056).
Verified by driving the real `main.py` as a subprocess over the
`agent-fun/bars-replay/v1` wire with the harness fill math: it reproduces
the offline simulator exactly (+$22.48, 2 trades, 1.18% max drawdown), and
two runs produce byte-identical replies (deterministic). The kit's local
grader could not run here (no Docker in this VM; the process driver runs
node only, not Python), so the grade above is the offline replay with the
harness's own fill formulas.

## Robustness

The same rules on the previous edition's dev window (a down, choppy day,
−2.8% overall) net **+$5.28** with 3 fills, so the behaviour is not tuned
to one leg alone. The entry parameters sit on a plateau: entry thresholds
+0.3% to +0.6% and trailing stops 2.0% to 4.0% all give the same dev trade.

## What was tried

- Plain 30-min momentum with tight exits (take-profit 1.8%, trailing stop
  0.8%, SMA exit, stalled-trade exit): +$7.73 at best, and the exact
  previous edition's config loses −$40.98 on this window — 8 trades
  whipsawed in the post-leg chop.
- SMA trend exits and EMA crosses: −$14 to −$17, 16–18 trades.
- Wide trailing stop alone (2%, no take-profit, no SMA exit): +$26.84,
  1 trade — but it loses −$5.29 on the previous edition's window, where
  the leg reverses.
- **Banking half at +1.8% and trailing the rest at 2%: +$22.48 here and
  +$5.28 on the previous window** — positive on both, which is what was
  kept.
- Rejected after testing: a stalled-trade exit for the remainder (frees
  re-entries into the chop, −$3.47 to −$5.31 on the previous window), a
  tighter trail once the remainder is deep in profit (never fires on
  either window, left out), a 1.0–1.5% hard stop (never binds on either
  window, kept as live-window insurance).

## Files

- `main.py` — the bot (Python 3.13, standard library only)
- `vendor/makefun_bars.py` — the kit's Python replay shim (unmodified)
- `README.md` — this file
- `LICENSE` — MIT

## Grade locally

```sh
node cli/makefun.mjs grade-local --kit <kit-dir> --bot <this-repo> --driver docker
```

## Determinism

No clock, no environment, no random, no files — only the bars on stdin.
The same input produces the same orders, run after run.
