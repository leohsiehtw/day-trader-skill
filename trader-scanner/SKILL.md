---
name: trader-scanner
description: >-
  Chart Scanner for Taiwan stocks. Scans thousands of charts for setups:
  opening-range breakouts, flags, oversold bounces. Builds the list of 4-digit
  common stocks (TWSE 2317.TW and TPEx 6488.TWO) from the exchanges' own
  daily-quote lists, runs a pre-market scan of daily closes (20-day
  closing-high breakout, bull flag, reclaimed the 20-day average, oversold,
  oversold bounce) and an intraday opening-range breakout scan on 5-minute
  bars from the 9:00 open, then writes trader/watchlist.json for trader-news
  and trader-entry. Free Yahoo data, bar by bar. Use when the user says "scan
  the market", "find me setups", "what is breaking out", "opening range
  breakouts", "scan for bull flags", "oversold stocks", "pre-market scan",
  "build my watchlist", "what should I look at today", or at the start of a
  trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads thousands of
free charts and lists the ones that match a rule. That is all it does. A scan
is a list of charts that match a rule, not a list of stocks to buy, and a
setup on a chart is not a prediction. Most people who day trade lose money;
the scanner does not change that. It only saves you from flipping through
2,000 charts by hand.

This version is for the Taiwan cash market: TWSE listed stocks (`2317.TW`)
and TPEx OTC stocks (`6488.TWO`), session 9:00 to 13:30 Taipei time, no
daylight time, no early close. Prices are TWD. It needs
`trader-risk/twmarket.py` in the folder next to it, so install all the
trader-* folders together.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                       # -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                          # before the open -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols 2317.TW,2330.TW,6488.TWO   # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                            # after 9:20 Taipei -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 09:45                 # cut the clock at 9:45 Taipei time
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Flags: `--min-price 10` and `--min-volume` (daily 1,000,000 shares, orb 0),
`--or-minutes 15`, `--max-confirm 200` (orb stage 2),
`--now "2026-10-19 09:45"` (Taipei time) to pin the clock, `--offline PATH`
to read saved Yahoo files, `--no-write`, `--show N`, `--json`. Symbols always
carry their market: a bare `2317` is refused. Exit code 0 when the scan found
something, 1 when it found nothing or could not run (the reason is one plain
line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news and trader-entry read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 13:00) |

## The universe

`universe` downloads two lists the exchanges publish themselves: the TWSE
OpenAPI `exchangeReport/STOCK_DAY_ALL` (stocks that traded on the last
session) and the TPEx OpenAPI `tpex_mainboard_daily_close_quotes`. It keeps a
row when, in this order:

1. The code is not `00xx`: those are ETFs and ETNs.
2. The code is exactly four digits starting with 1 to 9. Preferred shares
   (`1101B`), warrants, bonds and every 5- or 6-digit code are out.
3. The name does not end in `-DR`: those are Taiwan Depositary Receipts.
4. Everything else is in, TWSE rows as `.TW` and TPEx rows as `.TWO`.

On the lists fetched on 2026-10-29 (the TWSE list is dated 2026-10-27 and
the TPEx list 2026-10-28) this keeps 1,982 of 14,513 rows: 12,167 are not
4-digit stock codes, 360 are 00xx ETFs and ETNs and 4 are TDRs. The tool does
not know which of the kept stocks are on a disposition, full-delivery or
suspended list, or are not allowed to day trade: check that before you plan a
trade.

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so 1,982
symbols take 100 requests with the polite pause of 0.3 seconds. Liquidity
comes from the spark meta: last price at least `--min-price` (10 TWD) and
last session's volume at least `--min-volume` (1,000,000 shares, that is
1,000 board lots). Run it before the open or after the close: during the
session the volume is the day's so far, and today's daily bar is left out
until 13:30. Yahoo can serve today's daily bar with an empty close for a while
after the market closes; an empty close is dropped, so the last bar can be a
day old.

The setups are computed from daily closes only (spark has no highs or lows):

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

Taiwan's 10 percent daily limit is not modelled: a stock that closed at
limit-up is listed like any other breakout, and a stock stuck at limit-up
often cannot be bought. Hits are listed most traded first (price times
volume).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 9:00,
9:05 and 9:10 five-minute bars. A hit is the first completed 5-minute bar to
CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range. That is a necessary condition
   (the range high is at least every range close), so no breakout is lost.
2. Stage 2, each candidate: the v8 chart with real highs and lows, one
   request each. Range high = the highest high of the range bars, range low =
   the lowest low. If many charts are candidates, stage 2 checks at most
   `--max-confirm` (200) of them, the most traded first (price times volume
   so far), and prints PARTIAL with the count it skipped. `--max-confirm 0`
   checks them all.

For a fast answer, scan the daily watchlist or a list of names you trade
(`--watchlist`, `--symbols`). I have not timed a full-universe run on live
data; the request counts above are what to expect.

A chart is usable only when every 5-minute bar from 9:00 to the cutoff is
there; a missing bar means a halt or a thin stock, and many thinly traded
Taiwan stocks skip bars, so they drop out of this scan. Null closes are
dropped, a bar off the 5-minute grid (the live tick, like 10:02:30) is
dropped, and a bar counts only once it is complete (start + 5 minutes). The
13:30 closing-auction print Yahoo adds is not a bar. Before 9:20 AM, on a
weekend or holiday, after the close, or after `no_entries_after` (an expired
setup) it prints one plain line and writes nothing. The holiday list inside
the tool covers 2026: for another year check the TWSE holiday schedule.

## Data and limits

- Yahoo's chart and spark endpoints are free, unofficial and can lag, and
  Taiwan quotes may be delayed. Bars are 5-minute bars, bar by bar, never
  tick by tick. query2 first, query1 on a 429 or 5xx, one retry after a
  5-second wait on a 429.
- Partial results are said as partial: "Fetched 1,900 of 1,982 charts (82
  failed or had no data)". Never round a partial scan up to "the whole market".
- The exchange lists are daily files from the TWSE and TPEx OpenAPI; the
  field names this tool reads are `Code` / `Name` (TWSE) and
  `SecuritiesCompanyCode` / `CompanyName` (TPEx).

## Steps

1. Once a week or so: `scan.py universe`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:20 AM Taipei (9:30 to 9:45 is the usual time): `scan.py orb`. Tell
   the user how many usable charts broke their range and when, and that a
   later hit is closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL` (what is moving
   it), then `/trader-entry SYMBOL` (the entry bar by bar). Never pick for them.

## Example: a synthetic session

The test suite replays a made-up Monday, 2026-10-19, over 11 synthetic
5-minute charts (`tests/fixtures/trader-scanner/wall5m-2026-10-19-synthetic.json.gz`,
not market data). A scan at 9:45 AM with `--min-price 0`:

```
python3 scan.py orb --offline wall5m-2026-10-19-synthetic.json.gz --now "2026-10-19 09:45" --min-price 0
Fetched 10 of 11 charts (1 failed or had no data); 8 usable; 7 candidates, 7 confirmed with real highs and lows.
6 of 8 charts closed above their opening-range high by 9:45 AM:
   9:20 AM  1101.TW        28.40  range 27.85 to 28.15  +0.89% over
   9:20 AM  5871.TW         8.40  range 7.85 to 8.15  +3.07% over
   9:25 AM  2330.TW     1,010.00  range 996.00 to 1,007.00  +0.30% over
   9:30 AM  2317.TW       205.00  range 200.50 to 204.00  +0.49% over
   9:35 AM  6488.TWO      858.00  range 846.50 to 853.50  +0.53% over
```

One chart has no data at all, one has no bars and one is missing its 9:15
bar, so they are not scanned. 5871.TW trades under 10 TWD, so the default
`--min-price 10` drops it. Real data is used in the tests too: a real spark
answer for 2317.TW, 0050.TW and 6488.TWO, and a real 5-minute chart of
2317.TW whose 13:25 bar came back empty.

The daily scan over the synthetic daily charts tags 1101.TW and 1102.TW as a
20-day breakout, 2002.TW as a bull flag, 2207.TW as a reclaim of the 20-day
average, 2301.TW and 2303.TW as oversold and 2308.TW as an oversold bounce.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data real time, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
