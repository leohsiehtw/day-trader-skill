# The Day Trader skill

11 Claude skills for day trading: scan thousands of charts, track breaking news, time every entry and exit, and replay every outcome before you risk a dollar.

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts, the exchanges' own symbol lists (the TWSE
and TPEx lists in the Taiwan edition below, Nasdaq Trader's elsewhere), SEC
EDGAR and the House Clerk.

One scans thousands of charts for setups. Another tracks breaking news on
every stock you watch. One watches a setup bar by bar and tells you the moment
to get in, and another sets your stop and your target before you do. And the
craziest one is the Time Machine: before you risk a dollar, it replays the
rest of the session 10,000 times from the stock's own recent bars, plus every
past day the same setup fired, and tells you the honest odds.

And no trade goes through until you say yes. Nothing in this pack can place
an order on its own. Paper trading is the default.

## 台股版 (Taiwan edition)

這個 fork 的 `tw-equities` 分支把下單路徑上的五個 skill 改成台股(上市 `2317.TW`、
上櫃 `6488.TWO` 的四碼普通股):`trader-scanner`、`trader-entry`、`trader-exit`、
`trader-budget`、`trader-risk`。共用的台股規則放在 `trader-risk/twmarket.py`,
所以這幾個資料夾要一起安裝。

已經台股化的部分:

- 時間是台北時間(固定 UTC+8,沒有日光節約),盤中 9:00 到 13:30,沒有提早收盤。
  預設 09:15 之前、13:00 之後不進場,13:20 前出清。
- 數量是整張(1,000 股的倍數)或單一筆零股(1 到 999 股),不能混合。
- 價格要符合升降單位(0.01、0.05、0.1、0.5、1、5),並檢查前一日收盤價上下 10% 的漲跌幅。
- 成本:手續費 0.1425% 乘以折扣(預設 0.6,最低 20 元,逐筆進位到整數元);當沖賣出證交稅預設
  0.15%,一般賣出 0.3%。最大虧損與風報比都把這些成本算進去。當沖 0.15% 是暫行稅率,
  期限以財政部與證交所公告為準,過期請把 `day_trade_sell_tax_pct` 改成 0.3。
- 只處理四碼普通股;00 開頭的 ETF、特別股、權證、DR 都會被拒絕或排除。
- 範例與測試資料都是合成的(檔名帶 `synthetic`),只有證交所、櫃買清單與 Yahoo 回應的格式範例是真實資料的節錄。

**尚未台股化**(仍是美股版:紐約時間、美元、NYSE 假日):`trader-news`、`trader-timemachine`、
`trader-broker`、`trader-alerts`、`trader-analyst`、`trader-pelosi`。拿它們處理台股會把時區與幣別
弄錯,`trader-broker` 也只會對接美國的 Alpaca,所以台股的委託請自己到券商下單
(證交所沒有 bracket 單,停損與停利要在券商用條件單或 OCO 設定,或自己盯盤)。

限制:內建假日表只有 2026 年(來源是證交所 OpenAPI 的休市日清單),其他年份要自己核對;
不檢查當沖資格、處置股、全額交割與信用交易限制;Yahoo 資料免費、非官方,可能延遲;
這不是投資建議。

> **Looking for the original Trader skill?** Copy an investor's 13F, the
> stock screener, tax lots and rebalancing live in
> [github.com/Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill).
> This repo is its day-trading sequel: the Trader skill v2.

## Install

Paste this into Claude:

```
https://github.com/Jakeschincariol/day-trader-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add Jakeschincariol/day-trader-skill
/plugin install day-trader-skill@day-trader-skill
```

Claude Code namespaces plugin skills, so installed as a plugin they show up as
`/day-trader-skill:trader-scanner` and so on. Copy the folders instead if you want
plain `/trader-scanner`:

```bash
git clone https://github.com/Jakeschincariol/day-trader-skill.git
cp -r day-trader-skill/trader-* ~/.claude/skills/
```

Project-local instead of global: copy the same folders into your repo's
`.claude/skills/`. No Claude Code at all? Paste any single `SKILL.md` at the
top of a chat and it runs as a mode. You lose the Python tools, but the method
works.

The tools need Python 3.8 or newer. Nothing to pip install. The SEC tools
(news filings, the analyst) ask you to identify yourself: put your name and
email in `trader/config.json` (`"sec_user_agent": "Your Name you@example.com"`)
or in the `SEC_USER_AGENT` environment variable.

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans thousands of charts for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks breaking news on every stock you watch and flags what moves it. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, so you know when to get out. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a dollar: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade. |
| `/trader-broker` | Order Executor | Sends approved orders to your broker, paper trading by default, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop or the opening bell hits. |
| `/trader-analyst` | Earnings Analyst | Reads earnings reports and sums up what changed. |
| `/trader-pelosi` | Pelosi Tracker | Reads Congress's stock-trade disclosures the minute they are filed. |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by the close                                       (while it is open)
news / analyst / pelosi                                                        (on a schedule)
```

An example, a made-up Taiwan session: 2317.TW, Monday October 19 2026. The
numbers are synthetic, built for the test suite, not market data. Only the five
Taiwan-ready skills appear; the rest of the pack is US-only for now (see the
Taiwan edition above).

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
day) needs an eligible account and an eligible stock at your broker, and the
day-trade sell tax of 0.15 % is a temporary rate. `/trader-risk` does not check
any of that, so confirm it yourself. The US-only skills still follow the US
rules their text describes (FINRA's Regulatory Notice 26-10 removed the
$25,000 pattern-day-trader minimum on June 4, 2026, with brokers allowed to
phase it in until October 20, 2027).

**Congress's trades are public, not inside information.** Members must disclose
trades over $1,000 within 45 days (the STOCK Act). The Pelosi skill reads those
public filings the minute they post.

**Taxes.** Day-trading gains are short-term gains, and frequent trading makes
wash sales likely. Nothing here is tax advice.

## Files

```
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

MIT. Made by [Jake Schincariol](https://opusjake.ai).
