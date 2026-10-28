---
name: trader-risk
description: >-
  Risk Manager for Taiwan stocks. Checks every trade against your limits and
  stops anything over them, before it can reach the broker. For a day trade:
  a stop is required, the loss at the stop (broker fees and the day-trade
  sell tax included) must fit your max loss per trade, measured from the
  higher of the plan's entry and a fresh price, reward:risk after costs must
  meet your minimum, the day's total risk must fit your daily loss limit, no
  more than your trades per day, and no new entries outside your entry
  window (Taipei time) or when the TWSE is closed. It also keeps the basics:
  board-lot and odd-lot sizes, the tick grid, the 10 percent daily price
  limits, 4-digit common stocks only (no 00xx ETFs, no US tickers), blocked
  symbols, order size, position cap, cash buffer, margin, short sales,
  malformed orders, duplicates and a daily order limit. Getting out is never
  blocked by a day limit. Prints PASS or BLOCK with the reason and records
  the verdicts so trader-broker only shows an order that passed. Use when the
  user says "check my order", "is this safe", "risk check", "does this break
  my rules", "can I take this trade", "how much have I risked today", or
  before /trader-broker, always.
argument-hint: "[path to orders.json]"
---

# trader-risk

The Risk Manager is the gate between a proposal and the broker. Every order
written by trader-budget or trader-broker's flatten passes through it. A
BLOCK is final for that order: it does not go to the user for a yes, and it
does not go to the broker. Most people who day trade lose money. These limits
keep each loss and each day's losses small. They do not make a trade win.

This version is for the Taiwan cash market (TWSE `2317.TW`, TPEx `6488.TWO`).
Times are Taipei time (no daylight time, session 9:00 to 13:30, no early
close), prices and money are TWD. Taiwan has no pattern-day-trader rule, so
there is no PDT check. Cash day trading (buying and selling the same stock in
one day) needs an eligible account and an eligible stock at your broker: this
tool does not check that, so confirm it yourself.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).
It also holds `twmarket.py`, the shared Taiwan market module (clock, holidays,
ticks, price limits, lots, fees and tax) that trader-entry, trader-exit,
trader-budget and trader-scanner import, so install all the trader-* folders
together.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files; writes trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                # look without recording
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-10-19 09:30"  # pin the clock (Taipei time)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten) |
| `trader/config.json` | the limits (trader-budget ships `config.example.json`) |
| `trader/portfolio.json` | cash and holdings; if missing, a fresh account funded with the budget |
| `trader/prices.json` | a fresh price raises the entry it measures risk from; also values holdings. `detail.<SYMBOL>.prev_close` gives the previous close for the price limits |
| `trader/state/broker.json` | what was placed today: duplicates, trades per day, daily loss |
| `trader/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

## Entries and exits

An **entry** opens or adds to a position: a buy, or a sell that would go
short. An **exit** only reduces what you already hold. Getting out must
always be possible, so an exit is checked for format, lot size, tick grid,
price limits, asset and short sales only. Every other rule (day limits, entry
window, loss, reward:risk, blocked list, size, duplicates) turns into a
warning for an exit, never a BLOCK.

## The checks

Orders are checked in file order, as if each passed order had filled, so a
batch that is fine order by order but breaks a limit together is caught.

| check | blocks when |
| --- | --- |
| format | no symbol, side not buy or sell, no `qty` (a notional amount is refused: Taiwan orders are in shares), a limit order with no limit price, a type other than market or limit (the TWSE has no stop orders), a `time_in_force` other than day, ioc or fok, after-hours or extended-hours orders; a bracket that is not `day` or misses its stop-loss or take-profit |
| lot | a quantity that is not whole board lots (multiples of 1,000 shares) or ONE odd lot of 1 to 999 shares, never both; any odd lot when `allow_odd_lots` is false |
| tick | a price not on the tick grid: 0.01 under 10, 0.05 under 50, 0.1 under 100, 0.5 under 500, 1 under 1,000, 5 above |
| limit | a price outside the day's limits, 10 percent either side of the previous close (snapped inward to the tick grid). With no previous close the check is skipped and a warning says so |
| asset | anything that is not a 4-digit common stock with its market, like `2317.TW` or `6488.TWO`: a bare `2317`, 00xx ETFs, other codes, US tickers, crypto |
| short | a sell of more than you hold (`allow_short` false) |
| blocked | (entries) the symbol is on the `blocked` list |
| size | (entries) under `min_order_twd` or over `max_order_twd` |
| position | (entries) the stock would be over `max_position_pct` of the account |
| cash | (entries) the buy plus its broker fee would leave less than the cash buffer, or need margin |
| stop | (entries) no stop while `require_stop` is true (a bracket `stop_loss_stop_price`, or the order's plan stop); a stop on the wrong side of the entry |
| loss | (entries) qty x (entry minus stop), plus broker fees on both legs and the day-trade sell tax, over `max_loss_per_trade_twd` |
| reward:risk | (entries) (target minus entry) / (entry minus stop), both after costs, under `min_reward_risk` |
| daily loss | (entries) the max losses at the stops of today's entries, plus this one, over `max_daily_loss_twd` |
| trades | (entries) `max_trades_per_day` entries already placed today |
| window | (entries) before `no_entries_before` or after `no_entries_after` (default 09:15 and 13:00), or the market is closed |
| duplicate | (entries) the same symbol and side twice in one batch, or already placed today |
| daily limit | (entries) `max_orders_per_day` orders already placed today |

How the numbers work:

- **The entry it measures from**: the limit price for a limit order. For a
  market order, the HIGHER of the plan's entry and a fresh price from
  `trader/prices.json` (under 15 minutes old). A plan written at 9:30 cannot
  understate the risk at 10:30 after the price ran up. An older price is not
  used, and it says so.
- **Costs.** Broker fee 0.1425 percent times `fee_discount` (default 0.6, set
  1.0 if you get no discount), at least `min_fee_twd` (20), on each order and
  rounded up to a whole TWD. The sell leg of a day trade pays
  `day_trade_sell_tax_pct` (0.15 by default). That halved day-trade rate is a
  temporary measure that has been extended before: check the Ministry of
  Finance or TWSE notice and set it to 0.3 if it has lapsed. A plain sell that
  credits cash uses `sell_tax_pct` (0.3).
- **Daily loss** counts the full max loss of every entry placed today, win or
  lose, as trader-broker logged it. Three full-size trades use up a NT$15,000
  day.
- **The window** is Taipei time, a fixed +8 hours, never from the computer's
  clock zone. Weekends and TWSE holidays are closed (the holiday list inside
  the tool covers 2026; for any other year it warns, so check the TWSE
  holiday schedule). A `no_entries_after` later than 13:30 counts as 13:30,
  and `flat_by` at or after 13:30 is an error. Set both `no_entries_*` to
  null to switch the window off.
- **Odd lots.** An odd-lot entry passes with a warning: whether it can be
  sold the same day is the broker's rule, and the sell tax may be the full
  0.3 percent, which these numbers do not include.

Warnings do not block, but say them to the user: a LIVE account, a number
sent as a number instead of a string, a stop that lives only in the plan and
not at the broker, a price too old to use, a missing previous close, an odd
lot, a holiday list that does not cover the year.

## Steps

1. If the price may have moved since the plan, refresh it first and keep the
   previous close in `detail.<SYMBOL>.prev_close` so the price limits can be
   checked.
2. Run `check.py`. Exit code 0 means every order passed, 1 means at least one
   was blocked.
3. Tell the user the result in plain words, order by order: the max loss at
   the stop with costs, reward:risk after costs, and how much of today's
   limits it uses. For a BLOCK, give the reason and the fix (fewer shares, a
   closer stop from trader-exit, wait for the window, or skip the trade).
   Never change a limit yourself.
4. If the order changes in any way, run the check again. trader-broker matches
   each order to its verdict by fingerprint, so an edited order is not ready
   until it passes again, and a verdict from yesterday does not count today.
5. Remind the user that the TWSE has no bracket orders: a PASS here means the
   plan fits the rules, and the stop and target still have to be entered at the
   Taiwan broker as conditional (OCO) orders, or watched by hand.

## Example: a synthetic session

A 2317.TW order from trader-budget at 9:30 AM on Monday 2026-10-19, on a fresh
NT$500,000 paper account with the example config. The numbers are made up for
the test suite, not market data:

```
PASS  #1 buy 2317.TW 1,000 shares (1 board lot), entry
          the TWSE has no bracket orders: the stop and target are your plan; enter them at your broker as conditional (OCO) orders
          entry 205.00 (the plan's entry), stop 202.00, target 211.00: risk 3.00 a share
          max loss NT$3,652 (1,000 x 3.00 + NT$652 fees and tax) (limit NT$5,000), reward:risk 1.46 after costs (2.00 before) (min 1)
          today before this: 0 of 3 trades, NT$0 of NT$15,000 daily loss

1 passed, 0 blocked at 2026-10-19 09:30 Taipei. Cash after the passed orders: NT$294,824 (paper account).
```

Two board lots is blocked, three ways at once (the order is too big, too much
of the account, and too much loss):

```
BLOCK #1 buy 2317.TW 2,000 shares (2 board lots), entry
          max loss NT$7,303 (2,000 x 3.00 + NT$1,303 fees and tax) (limit NT$5,000), reward:risk 1.46 after costs (2.00 before) (min 1)
        - size: NT$410,000 is over your NT$400,000 max order
        - position: 2317.TW would be NT$410,000, 82.0% of the NT$500,000 account, over your 75% cap
        - loss: 2,000 shares x 3.00 risk a share = NT$6,000, plus NT$1,303 fees and tax = NT$7,303 at the stop, over your NT$5,000 max loss per trade
```

The fees are 351 on the buy, 346 on the sell, plus 606 of sell tax. A 500-share
odd lot passes with an odd-lot warning (NT$1,827 at the stop). A quote of
207.30 at 9:40 raises the entry the risk is measured from and blocks the
1,000 shares: 1,000 x 5.30 + NT$654 = NT$5,954. A target above limit-up
(220.00 on a previous close of 200.00) is blocked. At 9:10 the window blocks
it (no new entries before 9:15). The 13:25 sell that closes the position passes
even though it is after the 13:00 entry cutoff: it is an exit.

## Rules

- A PASS only means the order is allowed to be shown to the user. It is not a yes.
- Every number comes from the config, the order, the portfolio, the prices or the broker log.
- Free Yahoo prices are unofficial and can lag; the broker's price is the one that fills, and a
  stop can fill worse than its price in a fast market.

## What it never does

It never places an order, never edits an order to make it pass, never
loosens a limit, never blocks a sell that only gets the user out, and never
treats a PASS as the user's yes.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
