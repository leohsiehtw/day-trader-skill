# The Day Trader skill

English | [繁體中文](README.zh-TW.md)

11 Claude skills for day trading: scan thousands of charts, track breaking news, time every entry and exit, and replay every outcome before you risk a dollar.

**This is a Taiwan (TWSE / TPEx) fork**,
[leohsiehtw/day-trader-skill](https://github.com/leohsiehtw/day-trader-skill),
of the original
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
by Jake Schincariol. The Taiwan edition lives on the `tw-equities` branch. It
stays under the MIT license with the original author's copyright and credit
(see `LICENSE`).

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts, the exchanges' own symbol lists (the TWSE
and TPEx lists in the Taiwan edition, Nasdaq Trader's elsewhere), SEC EDGAR
and the House Clerk.

One scans thousands of charts for setups. Another tracks breaking news on
every stock you watch. One watches a setup bar by bar and tells you the moment
to get in, and another sets your stop and your target before you do. And the
craziest one is the Time Machine: before you risk a dollar, it replays the
rest of the session 10,000 times from the stock's own recent bars, plus every
past day the same setup fired, and tells you the honest odds.

And no trade goes through until you say yes. Nothing in this pack can place
an order on its own. Paper trading is the default.

> **Looking for the original Trader skill?** Copy an investor's 13F, the
> stock screener, tax lots and rebalancing live in
> [github.com/Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill).
> This repo is its day-trading sequel: the Trader skill v2.

## Taiwan edition

Five skills on the order path are Taiwan-ready, for 4-digit common stocks
listed on the TWSE (`2317.TW`) or the TPEx (`6488.TWO`): `trader-scanner`,
`trader-entry`, `trader-exit`, `trader-risk` and `trader-budget`. The shared
Taiwan rules live in `trader-risk/twmarket.py`, so install these folders
together.

**Not Taiwan-ready yet** (still the US version: New York time, US dollars,
NYSE holidays): `trader-news`, `trader-timemachine`, `trader-broker`,
`trader-alerts`, `trader-analyst`, `trader-pelosi`. Used on Taiwan stocks they
would get the time zone and the currency wrong, and `trader-broker` only talks
to the US broker Alpaca. Place Taiwan orders by hand at your Taiwan broker.
The TWSE has no bracket orders: set the stop and the target as conditional or
OCO orders at your broker, or watch the screen yourself.

### Taiwan rules the code applies

| rule | value |
| --- | --- |
| tick size | under 10: 0.01; 10 to under 50: 0.05; 50 to under 100: 0.1; 100 to under 500: 0.5; 500 to under 1,000: 1; 1,000 and up: 5 |
| daily price limit | +/-10 % of the previous close |
| session | 09:00 to 13:30 Taipei time (fixed UTC+8, no daylight time, no early close) |
| entry window and flat time | no entries before 09:15 or after 13:00, flat by 13:20 (defaults in `config.example.json`) |
| cash day-trade sell tax | 0.15 % on trades dated through 2027-12-31 (`day_trade_tax_halved_until`), then 0.3 % |
| margin / short day trade | 0.3 %, set `day_trade_mode` to `margin_daytrade` (default `cash_daytrade`) |
| ordinary sell tax | 0.3 % (`sell_tax_pct`) |
| brokerage fee | 0.1425 % x `fee_discount` (default 0.6) per side, rounded up to a whole TWD, minimum `min_fee_twd` (20) |
| board lot | 1,000 shares; an order is whole board lots or one odd lot of 1 to 999 shares, never both |
| odd lots | cannot be day traded under current TWSE rules: an odd-lot entry gets a strong warning (it becomes an overnight position), and its costs and max loss use the normal 0.3 % sell tax (`sell_tax_pct`), not the day-trade rate |
| pattern day trader | Taiwan has no PDT rule, so there is no PDT check |
| symbols | 4-digit common stocks only; 00xx ETFs, preferred shares, warrants and DRs are refused |

The trade date for the tax is the tools' `--now` date, else today's Taipei
date. The halved rate is a temporary measure: if the end date moves, change
`day_trade_tax_halved_until`. Max loss and reward:risk include the fees and the
tax. The built-in holiday list covers 2026 only (from the TWSE OpenAPI holiday
list); for other years check the TWSE schedule yourself.

### Day-trade eligibility (the program does not check it)

As commonly stated by brokers and the news (confirm with your broker or the
TWSE): the account has been open at least 3 months, has at least 10 trades in
the past year, and has a signed day-trade consent form. Selling first and
buying back the same day also needs a margin or securities-lending contract.
The program checks none of this; `size.py` and `exit.py` print a one-line
reminder.

Which stocks may be day traded comes from the TWSE daily list
(`get_daily_day_trading_targets` in the TW Stock connector, or twse.com.tw).
The program does not assume any stock is on it. It also does not check
disposition stocks, full-delivery stocks or margin restrictions.

### Verified and unverified

Verified:

- the cash day-trade sell tax is 0.15 % through 2027-12-31 (news reports of the
  Ministry of Finance extension);
- odd lots cannot be day traded (TWSE day-trading page);
- the +/-10 % daily limit is measured from the previous close.

Unverified, check them yourself:

- the NT$20 minimum fee (differs by broker);
- the rule that a short sale may not be priced below the previous close (not
  checked by the program);
- whether odd-lot day trading will open later (the regulator is only
  evaluating it);
- the rounding direction of the +/-10 % limit prices (the program snaps inward
  to the tick) and the tick table, against the official TWSE rules.

## Install

Paste this into Claude:

```
https://github.com/leohsiehtw/day-trader-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add leohsiehtw/day-trader-skill
/plugin install day-trader-skill@day-trader-skill
```

Both install from this fork (the marketplace and the plugin are both named
`day-trader-skill`). The original US pack stays at
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill).
The install commands were switched to this fork but not tested by an actual install.
Or copy the folders from this fork's `tw-equities` branch by hand:

```bash
git clone -b tw-equities https://github.com/leohsiehtw/day-trader-skill.git
cp -r day-trader-skill/trader-* ~/.claude/skills/
```

Claude Code namespaces plugin skills, so installed as a plugin they show up as
`/day-trader-skill:trader-scanner` and so on. Copied folders give you plain
`/trader-scanner`.

Project-local instead of global: copy the same folders into your repo's
`.claude/skills/`. No Claude Code at all? Paste any single `SKILL.md` at the
top of a chat and it runs as a mode. You lose the Python tools, but the method
works.

The tools need Python 3.8 or newer. Nothing to pip install. Copy
`trader-budget/config.example.json` to `trader/config.json` and set your own
budget, limits and broker fee discount. The SEC tools (news filings, the
analyst) ask you to identify yourself: put your name and email in
`trader/config.json` (`"sec_user_agent": "Your Name you@example.com"`) or in
the `SEC_USER_AGENT` environment variable.

## The eleven

| command | job | what it does | Taiwan edition |
| --- | --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans thousands of charts for setups: opening-range breakouts, flags, oversold bounces. | yes |
| `/trader-news` | News Monitor | Tracks breaking news on every stock you watch and flags what moves it. | not yet (US) |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. | yes |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, so you know when to get out. | yes |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a dollar: 10,000 simulated sessions plus every past time the setup fired. | not yet (US) |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. | yes |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade. | yes |
| `/trader-broker` | Order Executor | Sends approved orders to your broker, paper trading by default, never without your yes. | not yet (US, Alpaca) |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop or the opening bell hits. | not yet (US) |
| `/trader-analyst` | Earnings Analyst | Reads earnings reports and sums up what changed. | not yet (US) |
| `/trader-pelosi` | Pelosi Tracker | Reads Congress's stock-trade disclosures the minute they are filed. | not yet (US) |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by the close                                       (while it is open)
news / analyst / pelosi                                                        (on a schedule)
```

For Taiwan stocks the flow is scanner -> entry -> exit -> budget -> risk, then
you place the order by hand at your broker.

An example, a made-up Taiwan session: 2317.TW, Monday October 19 2026. The
example data is synthetic, built for the test suite, not market data. Only the
five Taiwan-ready skills appear.

1. **`/trader-scanner`** at 9:45 AM Taipei: of the 8 usable charts in the
   synthetic scan, 6 had closed above their 15-minute opening range. 2317.TW
   is one: range 200.50 to 204.00, the 9:25 bar closed at 205.00, 0.49 % over
   the top.
2. **`/trader-entry`** watched 2317.TW bar by bar. At 9:27 it said waiting
   (the 9:25 bar was still forming). At 9:30 it said triggered: the first
   5-minute close above the range, 205.00. The previous close is 200.00, so
   the day's limits are 180.00 and 220.00.
3. **`/trader-exit`** set the plan before the entry: stop at the range's
   midpoint rounded down to the 0.5 tick, 202.00, so 3.00 a share at risk;
   target two times that risk, 211.00; flat by 13:20 either way. Round-trip
   fees and tax come to about 0.32 % of the position.
4. **`/trader-budget`** with a NT$500,000 account and a NT$5,000 max loss per
   trade: 1,369 shares fit once fees and tax are counted, which rounds down to
   one board lot of 1,000 shares (NT$205,000). If the stop fills at 202.00, the
   loss is NT$3,000 plus NT$652 of fees and tax, NT$3,652. If the target
   fills, net reward:risk is 1.46 (2.00 before costs). It writes one order:
   buy 1,000 2317.TW, stop 202.00, target 211.00.
5. **`/trader-risk`** checks it against your limits: the lot size, the tick
   grid, the price limits, the max loss, the daily loss limit, trades per day,
   reward to risk after costs, the entry window, position size and cash. PASS
   or BLOCK, with the reason.

Then you place the order yourself at your Taiwan broker, with the stop and the
target as conditional orders. The TWSE has no bracket orders.

## The tools

All standard-library Python. The data tools read public endpoints and are
polite about it.

```bash
python3 trader-scanner/scan.py universe                                # ~2,000 TWSE and TPEx stocks
python3 trader-scanner/scan.py daily                                   # pre-market setups, whole universe
python3 trader-scanner/scan.py orb --at 09:45                          # opening-range breakouts so far
python3 trader-news/news.py --tickers TSLA --hours 12                  # headlines, 8-Ks, today's move (US only)
python3 trader-entry/entry.py check 2317.TW --setup orb                # waiting / triggered / expired
python3 trader-entry/entry.py watch 2317.TW --every 30                 # bar by bar until it triggers
python3 trader-exit/exit.py plan --stop or-mid --target 2R --write     # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --write                  # 10,000 replays + the history (US only)
python3 trader-budget/size.py --write                                  # -> trader/orders.json
python3 trader-risk/check.py                                           # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                   # the tickets, READY or not
python3 trader-alerts/alerts.py add --from-plan                        # stop, target, flat by close
python3 trader-alerts/alerts.py check                                  # rings what hit, once
python3 trader-analyst/facts.py TSLA                                   # quarters, growth, EPS
python3 trader-pelosi/ptr.py index --member pelosi                     # her PTRs this year
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline. The Taiwan-ready skills use synthetic sessions (2317.TW on
October 19 2026, made-up bars and a made-up scan wall) plus a few real
responses: rows of the TWSE and TPEx lists, a Yahoo spark answer and a Yahoo
5-minute chart of 2317.TW. The skills that are still US-only keep their
original fixtures (TSLA's 5-minute bars, Yahoo's TSLA headlines, the House
Clerk's 2026 index, real PTR text and real XBRL facts). The Taiwan tests
reproduce every number in the example above, and the expected values were
worked out separately from the program's output.

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
Most people who day trade lose money. You can lose money. Decide for
yourself, and talk to a licensed professional if you need advice.

**Not validated with live trading.** The Taiwan edition has only been tested
against synthetic and saved data, never with real orders. Tax rates, fee
discounts, minimum fees and eligibility change and differ by broker: check
them yourself before you trade.

**No trade goes through until you say yes.** Only `/trader-broker` can lead to
an order, and only after `/trader-risk` passes that exact order and you type
yes for it in the chat. Set your brokerage tool to "Needs approval" in Claude
(Customize, Connectors, tool permissions), never "Always allow", so Claude's
own "Allow once / Deny" card is a second check. No options, margin, short
selling or leverage unless you turn them on.

**Paper first.** `"paper": true` is the default in `config.example.json`, and
Alpaca's MCP server defaults to its paper account. Keys live in environment
variables, never in the chat.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: an earnings report, a halt, a headline. Treat its odds as a
reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap, a
stop order can fill well past its price. The max loss shown is the loss at
the stop price.

**The data is free and unofficial.** Yahoo Finance's chart endpoint is not an
official API: it can lag, change or rate-limit you. The scanner and the entry
timer read 1-minute or 5-minute bars, not every tick. Check anything that
matters against your broker before you act on it.

**Day-trading rules.** The Taiwan edition has no pattern-day-trader check:
Taiwan has no PDT rule. Cash day trading (buy and sell the same stock in one
day) needs an eligible account and an eligible stock at your broker (see
"Day-trade eligibility" above), odd lots cannot be day traded under current
TWSE rules, and the 0.15 % cash day-trade sell tax is a temporary rate
(through 2027-12-31 by default; margin day trades pay 0.3 %). `/trader-risk`
does not check eligibility, so confirm it yourself. The US-only skills still
follow the US rules their text describes (FINRA's Regulatory Notice 26-10
removed the $25,000 pattern-day-trader minimum on June 4, 2026, with brokers
allowed to phase it in until October 20, 2027).

**Congress's trades are public, not inside information.** Members must disclose
trades over $1,000 within 45 days (the STOCK Act). The Pelosi skill reads those
public filings the minute they post.

**Taxes.** In the US, day-trading gains are short-term gains, and frequent
trading makes wash sales likely. Nothing here is tax advice.

## Files

```
README.md           this file (English)
README.zh-TW.md     the same in Traditional Chinese
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py, twmarket.py (shared Taiwan market rules)
trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/      SKILL.md, ticket.py, claude_desktop_config.example.json
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, facts.py, metrics.example.json
trader-pelosi/      SKILL.md, ptr.py
tests/              unittest suite + offline fixtures
```

MIT. Made by [Jake Schincariol](https://opusjake.ai). Taiwan edition is a fork
of his work under the same license.
