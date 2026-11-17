# BTC Race Bot — Sniper + Sharp-Drop Dip-Buy

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/Orochim25/btc-race-24h-20261117-0603-entry-acct2/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/Orochim25/btc-race-24h-20261117-0603-entry-acct2/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

A long-only cbBTC trading bot for the [Race a BTC trading bot live for 24 hours](https://make.fun/bounty/btc-race-24h-20261117-0603) bounty. It trades two setups and otherwise stays in cash: Setup B, a capitulation-bounce sniper that buys the violent bounce after a multi-hour capitulation (drop >= 550 bps from the 720-bar high, long lower wick, sharp +60 bps reversal bar, RSI turning up, R:R >= 2:1, trailing stop +80/+80); and Setup D, a sharp-drop dip-buy for calm, range-bound windows that buys only a FAST fall (>= 120 bps off the 120-bar high AND >= 150 bps down over 60 bars, RSI(14) < 50, bar closes up) with an 80 bps stop and a +100/+100 trailing stop, capped at one dip trade per window. The sharp-drop filter is the improvement over a loose dip-buy: a slow drift down is a downtrend and loses, a sharp drop is oversold and bounces. At most 3 trades per window, stop after 2 consecutive bounce losses, stop entering below 98% of starting equity, no entries after bar 1320.

## License

MIT — see [LICENSE](LICENSE).
