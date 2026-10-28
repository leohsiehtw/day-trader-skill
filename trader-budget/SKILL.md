---
name: trader-budget
description: >-
  Budget Manager for Taiwan stocks. Sizes every position to your budget and
  your max loss per trade, in board lots (1,000 shares) or one odd lot. Reads
  the trade plan from trader-exit (entry, stop, target), finds the shares that
  fit inside four limits (max loss per trade with broker fees and day-trade
  tax counted, position cap, max order, cash after your buffer), says which
  limit decided it, and writes ONE order (entry, stop-loss, take-profit) to
  trader/orders.json in the shape of Alpaca's place_stock_order, with the
  price limits and tick grid checked. A stop too far away for your max loss
  is a plain refusal, not a smaller order. Nothing is placed. Use when the
  user says "how many shares", "how many lots", "size this trade", "how much
  should I buy", "I have NT$500,000", "I only want to risk NT$5,000 a trade",
  "set my rules", "keep 10% in cash", or after /trader-exit writes a plan.
argument-hint: "[budget in TWD]"
---

# trader-budget

The Budget Manager turns a plan ("buy 2317.TW at 205.00, stop 202.00") into an
exact order ("buy 1,000 shares, one board lot"), inside rules the user sets
once. The stop decides the size: the further away the stop, the fewer shares.
It writes a proposal only. trader-risk checks it and trader-broker asks the
user yes or no. Day trading loses most people money. Sizing to a max loss
keeps each loss small; it does not make a trade win.

This version is for Taiwan stocks (TWSE `2317.TW`, TPEx `6488.TWO`), money in
TWD, times in Taipei time. Only 4-digit common stocks are sized: 00xx ETFs are
refused because they have their own tick and limit rules. It needs
`trader-risk/twmarket.py` in the folder next to it, so install all the
trader-* folders together.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                        # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                # write trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit --write        # a limit order at the plan's entry
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 204.50 --json  # a limit order at 204.50
python3 "${CLAUDE_SKILL_DIR}/size.py" --weights 2330.TW=40,2317.TW=60 --prices trader/prices.json   # weights mode, below
```

`--now "2026-10-19 09:30"` pins the clock (Taipei time). A plan for another
day is refused: make a new one with trader-exit.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the rules (start from `config.example.json` in this folder) |
| `trader/plan.json` | the trade: entry, stop, target, setup, flat-by time, previous close (trader-exit writes it) |
| `trader/prices.json` | optional: a fresh price above the plan's entry means a bigger risk; `detail.<SYMBOL>.prev_close` is the fallback previous close (trader-alerts writes it) |
| `trader/portfolio.json` | optional: its cash caps the size (trader-broker keeps it) |
| `trader/orders.json` | the one proposed order it writes with `--write` |

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` into
`trader/config.json` and ask the user for each value in plain words:

- **budget**: how much money this is for, in TWD (the example has NT$500,000).
  Only money they can afford to lose.
- **cash_buffer_pct**: how much always stays in cash (default 10).
- **max_loss_per_trade_twd**: the most one trade may lose if the stop fills at the stop, fees and tax
  included (default NT$5,000).
- **max_position_pct**, **max_order_twd**, **min_order_twd**: the biggest position (75% of the
  budget), the biggest order (NT$400,000) and the smallest order (NT$1,000).
- The day limits trader-risk enforces: **max_daily_loss_twd** (15,000), **max_trades_per_day** (3),
  **min_reward_risk** (1.0, counted after costs), **require_stop** (true),
  **no_entries_before** / **no_entries_after** ("09:15" / "13:00") and **flat_by** ("13:20"), all Taipei time.
- **allow_odd_lots** (true): whether a buy under 1,000 shares is allowed. An order is whole board lots
  or ONE odd lot, never both.
- The cost rates: **fee_discount** (0.6 of the 0.1425% broker fee; it may be a monthly rebate at your broker,
  and 1.0 is the worst case), **min_fee_twd** (20), **day_trade_sell_tax_pct** (0.15) and **sell_tax_pct**
  (0.3). The 0.15 day-trade rate is a temporary cut that has been extended before: check the Ministry of
  Finance or TWSE notice and set it to 0.3 if it has lapsed.
- **blocked**: symbols they never want to trade.
- Keep **paper** true until they have watched it work on a paper account.

## Step 2: size the trade

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py" --write
```

The size is the smallest of four limits, each rounded down to a valid lot size
(multiples of 1,000 shares, or an odd lot of 1 to 999 when `allow_odd_lots`
is true):

| limit | shares |
| --- | --- |
| max loss | the most shares whose loss at the stop stays inside `max_loss_per_trade_twd`: price loss plus broker fees on both legs plus the day-trade sell tax |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order_twd` / entry |
| cash | (budget minus the cash buffer) / entry, fee included, never more than the cash in `trader/portfolio.json` |

The entry it sizes at: the limit price with `--limit`. For a market order, the
plan's entry, or the price in `trader/prices.json` if it is fresh (under 15
minutes old) and higher. A price that ran up since the plan means a bigger
loss at the same stop, so fewer shares. A lower price never shrinks the risk.

It refuses, and writes no order, when: the size is zero shares, the order is
under the minimum, net reward:risk (costs counted) is under `min_reward_risk`,
the stop is not below the entry, the target is not above it (the move already
happened), the stop or target is not on the tick grid, the target is above
limit-up or the stop below limit-down (10 percent either side of the previous
close), the plan is for another day, the symbol is blocked or is an ETF, or
the plan is a short. With no previous close it still sizes, and says that the
limit check was skipped. Say the reason to the user in one line.

An odd-lot order warns: whether an odd-lot buy can be sold the same day is the
broker's rule, and the sell tax may be 0.3 percent, which the numbers do not
include.

## Step 3: show the user

Show the four limits (what each allows, and the rounded-down lot size), which
one decided the size, the shares, the money and the max loss at the stop with
its costs. Say plainly that a stop is an order, not a promise, and that the
TWSE has no bracket orders: the stop and target are the plan, entered at the
Taiwan broker as conditional (OCO) orders or watched by hand. Then hand over to
`/trader-risk`.

## Example: a synthetic session

2317.TW on Monday 2026-10-19. The numbers are made up for the test suite, not
market data. Opening-range breakout: entry 205.00 at 9:30 AM, stop 202.00 (the
opening-range midpoint, rounded down to the 0.5 tick), target 211.00 (2R).
Previous close 200.00, so the limits are 180.00 and 220.00. Risk 3.00 a share.
The example config: NT$500,000 budget, 10% cash buffer, NT$5,000 max loss.

| limit | the math | shares, rounded down to a lot |
| --- | --- | --- |
| max loss | NT$5,000 with costs, 1,369 shares fit | 1,369, so **1,000 (decides it)** |
| position cap | 75% of NT$500,000 = NT$375,000 / 205.00 | 1,829, so 1,000 |
| max order | NT$400,000 / 205.00 | 1,951, so 1,000 |
| cash | NT$500,000 minus NT$50,000 = NT$450,000 / 205.00, fee in | 2,193, so 2,000 |

1,000 shares = NT$205,000. At the stop: 1,000 x 3.00 = NT$3,000, plus a
NT$176 buy fee, a NT$173 sell fee and NT$303 of day-trade tax (NT$652) =
NT$3,652. If the target fills the net gain is NT$5,326, so net reward:risk is
1.46 against 2.00 before costs. It writes:

```json
{"symbol": "2317.TW", "side": "buy", "qty": "1000", "type": "market", "time_in_force": "day",
 "order_class": "bracket", "take_profit_limit_price": "211.00", "stop_loss_stop_price": "202.00",
 "currency": "TWD",
 "why": "opening-range breakout on 2317.TW: 1,000 shares, bound by your NT$5,000 max loss per trade (1,000 x 3.00 = NT$3,000 + NT$652 fees and tax = NT$3,652 at the stop)",
 "plan": {"entry": 205.0, "stop": 202.0, "target": 211.0, "risk_per_share": 3.0, "max_loss": 3652.0,
          "costs_at_stop": 652, "reward_risk_net": 1.46, "setup": "orb", "entry_time": "9:30 AM",
          "flat_by": "13:20"}}
```

`why` and `plan` are notes for trader-risk and trader-broker, and `currency`
is a label. They are never sent to a broker. With a stop at 190.00 and a
target at 220.00 instead, 319 shares fit the max loss, so the order is one
odd lot of 319 shares (with a warning) if `min_reward_risk` is switched off,
and with `allow_odd_lots` false it is refused. A quote of 207.30
sizes to 839 shares at 5.30 a share, and net reward:risk falls to 0.51: refused,
because the move it was waiting for has mostly happened.

## Weights mode (kept from v1)

`--weights 2330.TW=40,2317.TW=60` or `--targets FILE` (`targets.example.json`
here, an example split that is not a recommendation) splits a budget across a
list by weight: the cash buffer comes off the top, weights are renormalised to
100, any stock over `max_position_pct` is pinned at the cap and its excess
shared out, slices under the minimum order (or too small for one lot) are
dropped, and each slice becomes whole shares rounded down to a valid lot size.
There is no top-up, so some money stays idle and is reported. Every stock needs
a price (`--prices trader/prices.json`). With the example weights, NT$500,000,
and made-up prices of 1,000 / 205 / 1,200 / 120 / 70, the shares are 180, 548,
56, 375 and 642 (all odd lots) and NT$520 is left idle. Amounts exclude fees
and tax. These are plain buys with no stop: trader-risk blocks them while
`require_stop` is true and counts each one against `max_trades_per_day`. Use a
separate config (`--config`) for a long-term split.

## Rules

- Proposals only. This skill never calls a broker tool.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan or the prices. Nothing is guessed.
- No projections: never say what a trade will make. A target is a plan, not a forecast.
- Free Yahoo prices are unofficial and can lag. The broker's price is the one that fills.

## What it never does

It never places, approves or schedules an order, never raises a limit on its
own, never shrinks a stop to fit more shares, and never sizes options,
margin or short positions.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on Claude's own card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or the Claude Desktop config, never in the chat.
