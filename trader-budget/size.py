#!/usr/bin/env python3
"""Position sizing for trader-budget (Taiwan stocks). Standard library only, no network.

Default mode: sizes ONE day trade from trader/plan.json (written by
trader-exit) to your budget and your max loss per trade, then writes one
proposed order (entry, stop-loss, take-profit) to trader/orders.json in the
shape of Alpaca's place_stock_order. It never places anything: trader-risk
checks the order and trader-broker asks you yes or no. The TWSE has no
bracket orders: the stop and target are your plan, entered at a Taiwan broker
as conditional (OCO) orders or watched by hand.

    python3 size.py                                  # trader/plan.json + trader/config.json
    python3 size.py --write                          # write trader/orders.json
    python3 size.py --limit                          # a limit order at the plan's entry
    python3 size.py --limit 205.50 --write           # a limit order at 205.50
    python3 size.py --now "2026-10-19 09:30" --json  # pin the clock (Taipei time)

How many shares. An order is whole board lots (multiples of 1000 shares) or
ONE odd lot of 1 to 999 shares (when "allow_odd_lots" is true), never both.

    shares = the smallest of these four, each rounded down to a valid lot size
      max loss       the most shares whose loss at the stop stays inside
                     max_loss_per_trade_twd; the loss counts the broker fees
                     and the day-trade sell tax on both legs (an odd
                     lot cannot be day traded, so it uses the normal
                     sell_tax_pct, 0.3)
      position cap   budget x max_position_pct / entry
      max order      max_order_twd / entry
      cash           (budget minus the cash buffer) / entry, fee included
                     (and no more than the cash in trader/portfolio.json, if you have one)

The entry it sizes at: a limit order's limit price; for a market order the
plan's entry, or the price in trader/prices.json if that is fresh (under 15
minutes old) and higher, because a price that ran up since the plan means a
bigger loss at the same stop. Zero shares (the stop is too far away for your
max loss) is a plain refusal: no order is written. So is a net reward:risk
under min_reward_risk (costs taken off the reward and added to the risk), and
a stop or target outside today's +/-10 percent price limits.

Weights mode: split a budget across a list of stocks by weight.

    python3 size.py --weights 2330.TW=40,2317.TW=25,2454.TW=15,2412.TW=10,2882.TW=10 --prices trader/prices.json
    python3 size.py --targets my-weights.json --budget 500000 --write

  1. cash buffer   budget x cash_buffer_pct stays in cash, never invested
  2. weights       renormalised to 100 over the stocks you keep (blocked
                   tickers are dropped first; --top N keeps the N biggest)
  3. cap           no stock gets more than max_position_pct of the budget;
                   anything over the cap is shared out to the others by
                   weight, again and again until nobody is over
  4. min order     a slice under min_order_twd is dropped and its weight
                   shared out, so you never place a NT$20 order
  5. lots          whole shares only, rounded down to a valid lot size
                   (board lots, or one odd lot); no top-up, so money can be
                   left idle. Needs a price for every stock.

Money that cannot be invested is reported as "left idle", never hidden.
Only 4-digit common stocks (2317.TW, 6488.TWO) are sized; 00xx ETFs are refused.
"""

import argparse
import datetime
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(os.path.dirname(_HERE), "trader-risk")):
    if os.path.isfile(os.path.join(_d, "twmarket.py")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break
try:
    import twmarket as tw
except ImportError:
    sys.exit("size.py: needs trader-risk/twmarket.py next to this skill folder (install all trader-* folders together)")

# defaults: the contract's config.example.json. Missing keys fall back to these.
DEFAULTS = {
    "budget": None,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order_twd": 400000,
    "min_order_twd": 1000,
    "max_loss_per_trade_twd": 5000,
    "max_daily_loss_twd": 15000,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "no_entries_before": "09:15",
    "no_entries_after": "13:00",
    "flat_by": "13:20",
    "allow_odd_lots": True,
    "fee_discount": 0.6,
    "min_fee_twd": 20,
    "day_trade_sell_tax_pct": 0.15,
    "sell_tax_pct": 0.3,
    "day_trade_mode": "cash_daytrade",
    "day_trade_tax_halved_until": tw.DAY_TRADE_TAX_HALVED_UNTIL,
    "broker": "alpaca",
    "paper": True,
    "blocked": [],
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
}
EPS = 1e-9
FRESH_MINUTES = 15
SETUP_WORDS = {"orb": "opening-range breakout", "flag": "flag", "bounce": "oversold bounce"}
NO_BRACKET = ("The TWSE has no bracket orders: the stop and target are your plan. Enter them at your Taiwan "
              "broker as conditional (OCO) orders, or watch them yourself.")


class SizeError(Exception):
    pass


# ---------------------------------------------------------------- time (Taipei, fixed +8, no daylight time)

def to_taipei(utc):
    return tw.to_taipei(utc)


def taipei_to_utc(local):
    return tw.taipei_to_utc(local)


def parse_now(text):
    """--now text -> naive UTC. A time without an offset is taken as Taipei time."""
    if not text:
        return tw.utc_now().replace(microsecond=0)
    try:
        return tw.parse_now(text)
    except tw.TWError as e:
        raise SizeError(str(e))


def parse_utc(text):
    """"2026-10-19T14:52:13Z" -> naive UTC, or None."""
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def utc_iso(now_utc=None):
    now_utc = now_utc or tw.utc_now()
    return now_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- inputs

def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SizeError("no %s at %s" % (what, path))
    except json.JSONDecodeError as e:
        raise SizeError("%s is not valid JSON: %s" % (path, e))


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        cfg.update(read_json(path, "config"))
    return cfg


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_weights(data):
    """Accept a weights file, a {ticker: weight} dict or a list of rows.

    Returns [{"ticker", "name", "weight"}] with weight as a float."""
    if isinstance(data, dict) and "weights" in data:
        data = data["weights"]
    rows = []
    if isinstance(data, dict):
        for t, w in data.items():
            rows.append({"ticker": t, "name": "", "weight": w})
    elif isinstance(data, list):
        for i, r in enumerate(data):
            if not isinstance(r, dict):
                raise SizeError("weights[%d] is not an object" % i)
            t = r.get("ticker") or r.get("symbol")
            w = r.get("weight", r.get("weight_pct", r.get("pct")))
            if not t or w is None:
                raise SizeError("weights[%d] needs a ticker and a weight" % i)
            rows.append({"ticker": t, "name": r.get("name", ""), "weight": w})
    else:
        raise SizeError("weights must be a list or an object")
    out = []
    for r in rows:
        try:
            w = float(r["weight"])
        except (TypeError, ValueError):
            raise SizeError("weight for %s is not a number: %r" % (r["ticker"], r["weight"]))
        out.append({"ticker": str(r["ticker"]).strip().upper(), "name": r["name"] or "", "weight": w})
    return out


def weights_from_arg(text):
    """AAPL=22.04,AXP=17.14 -> {ticker: weight}"""
    out = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SizeError("--weights wants TICKER=WEIGHT pairs, got %r" % part)
        t, w = part.split("=", 1)
        out[t.strip().upper()] = w.strip()
    return out


def load_prices(path):
    if not path:
        return {}
    data = read_json(path, "prices")
    prices = data.get("prices", data) if isinstance(data, dict) else {}
    out = {}
    for t, p in prices.items():
        try:
            out[str(t).upper()] = float(p)
        except (TypeError, ValueError):
            continue
    return out


def price_time(doc, sym):
    """When this symbol's price is from: the quote's own time (detail[sym].time), else when it
    was fetched (detail[sym].fetched), else the file's as_of."""
    det = ((doc or {}).get("detail") or {}).get(sym) or {}
    for key in ("time", "fetched"):
        t = parse_utc(det.get(key))
        if t:
            return t
    return parse_utc((doc or {}).get("as_of"))


def fresh_price(doc, sym, now_utc, minutes=FRESH_MINUTES):
    """(price, fetched_utc, fresh) for sym from a prices.json doc, or (None, None, False)."""
    if not isinstance(doc, dict):
        return None, None, False
    p = _f((doc.get("prices") or {}).get(sym))
    if p is None or p <= 0:
        return None, None, False
    t = price_time(doc, sym)
    if t is None:
        return p, None, False
    age = (now_utc - t).total_seconds()
    return p, t, -60 <= age <= minutes * 60


# ---------------------------------------------------------------- money helpers

def round_cent(x):
    """Round a price to the cent (half up)."""
    return float(tw.D(x).quantize(tw.D("0.01"), rounding="ROUND_HALF_UP"))


def shares_for(twd, per_share):
    """Whole shares that fit in twd at per_share, in exact integer cents."""
    u, p = int(round(float(twd) * 100)), int(round(float(per_share) * 100))
    if p <= 0 or u <= 0:
        return 0
    return u // p


def _price(x):
    """205 -> "205.00": Alpaca wants prices as strings."""
    return "%.2f" % round_cent(x)


def _num(x):
    """1250 -> "1250", 1118.13 -> "1118.13" (Alpaca wants these as strings)."""
    x = round(float(x), 2)
    if abs(x - round(x)) < 0.005:
        return str(int(round(x)))
    return "%.2f" % x


def money(x):
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return "NT$" + "{:,.0f}".format(round(x))
    return "NT$" + "{:,.2f}".format(x)


def _n(x):
    return "{:,}".format(int(x))


# ---------------------------------------------------------------- plan mode (the default)

def size_trade(plan, cfg, budget=None, limit=None, price=None, cash=None, today=None, prev_close=None):
    """Pure function: one plan + your rules -> the sizing (a dict). qty may be 0.

    limit       the limit price for a limit order (None = market)
    price       a FRESH latest price; a market order is sized at the higher of it and the plan's entry
    cash        the cash in trader/portfolio.json, if there is one
    today       Taipei date (YYYY-MM-DD); a plan for another day is refused
    prev_close  yesterday's close if the plan has none (for the +/-10 percent price limits)"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    c["trade_date"] = today or None
    problem = tw.cost_problem(c)
    if problem:
        raise SizeError(problem)
    if not isinstance(plan, dict):
        raise SizeError("the plan is not a JSON object")
    sym = str(plan.get("symbol") or "").strip().upper()
    if not sym:
        raise SizeError("the plan has no symbol (run trader-exit)")
    problem = tw.stock_problem(sym)
    if problem:
        raise SizeError(problem)
    side = str(plan.get("side") or "buy").strip().lower()
    if side != "buy":
        raise SizeError("this pack sizes long (buy) day trades only; the plan says %r" % side)
    if today and plan.get("date") and str(plan["date"]) != today:
        raise SizeError("the plan is for %s and today is %s in Taipei: make a new plan with trader-exit"
                        % (plan["date"], today))
    entry_plan, stop, target = _f(plan.get("entry")), _f(plan.get("stop")), _f(plan.get("target"))
    for name, v in (("entry", entry_plan), ("stop", stop), ("target", target)):
        if v is None or v <= 0:
            raise SizeError("the plan needs a positive %s (run trader-exit); an order with a stop and a "
                            "target needs entry, stop and target" % name)
    blocked = {str(b).upper() for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s is on your blocked list" % sym)

    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("no budget: pass --budget or set \"budget\" in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct") or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct must be between 0 and 100")
    allow_odd = bool(c.get("allow_odd_lots", True))

    if limit is not None:
        ref, ref_from = round_cent(limit), "limit"
        if not tw.on_tick(ref):
            raise SizeError("the limit price %s is not on the tick grid (ticks are %s at this price); "
                            "nearest valid price %s" % (_price(ref), tw.tick_size(ref), tw.round_tick(ref)))
    elif price is not None and round_cent(price) > round_cent(entry_plan):
        ref, ref_from = round_cent(price), "price"
    else:
        ref, ref_from = round_cent(entry_plan), "plan"
    stop, target = round_cent(stop), round_cent(target)
    if stop >= ref:
        raise SizeError("the stop %s is not below the entry %s; a long trade needs its stop underneath"
                        % (_price(stop), _price(ref)))
    if target <= ref:
        raise SizeError("the target %s is not above the entry %s: the move has already happened. "
                        "Skip it or make a new plan with trader-exit" % (_price(target), _price(ref)))
    for label, v in (("stop", stop), ("target", target)):
        if not tw.on_tick(v):
            raise SizeError("the %s %s is not on the tick grid (ticks are %s at this price); nearest valid "
                            "price %s. Make a new plan with trader-exit" % (label, _price(v), tw.tick_size(v),
                                                                           tw.round_tick(v)))

    warnings = []
    pc = _f(plan.get("prev_close"))
    if pc is None or pc <= 0:
        pc = _f(prev_close)
    limit_down = limit_up = None
    if pc is not None and pc > 0:
        ld, lu = tw.limit_prices(pc)
        limit_down, limit_up = float(ld), float(lu)
        if target > limit_up + EPS:
            raise SizeError("the target %s is above today's limit-up %s (previous close %s plus 10 percent): "
                            "it cannot be reached today" % (_price(target), _price(limit_up), _price(pc)))
        if stop < limit_down - EPS:
            raise SizeError("the stop %s is below today's limit-down %s (previous close %s minus 10 percent): "
                            "a stop there can never trigger" % (_price(stop), _price(limit_down), _price(pc)))
        if ref > limit_up + EPS or ref < limit_down - EPS:
            raise SizeError("the entry %s is outside today's price limits %s to %s (previous close %s)"
                            % (_price(ref), _price(limit_down), _price(limit_up), _price(pc)))
        if ref >= limit_up - EPS:
            warnings.append("the entry %s is at limit-up %s: a buy there often cannot fill" % (_price(ref), _price(limit_up)))
    else:
        pc = None
        warnings.append("no previous close for %s: the +/-10%% limit check was skipped" % sym)

    risk_c = int(round((ref - stop) * 100))
    reward_c = int(round((target - ref) * 100))
    risk = risk_c / 100.0

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    available = budget - cash_buffer
    cash_note = "budget %s minus the %s cash buffer" % (money(budget), money(cash_buffer))
    if cash is not None and cash - cash_buffer < available - 0.005:
        available = cash - cash_buffer
        cash_note = "cash %s in trader/portfolio.json minus the %s buffer" % (money(cash), money(cash_buffer))
    available = max(round(available, 2), 0.0)

    limits = []

    def add(name, twd, per, raw, how):
        limits.append({"name": name, "twd": twd, "per": per, "raw": raw,
                       "shares": tw.floor_qty(raw, allow_odd), "how": how})

    max_loss = _f(c.get("max_loss_per_trade_twd"))
    if max_loss:
        add("max loss", max_loss, risk, tw.max_qty_for_loss(max_loss, ref, stop, c),
            "%s max loss, costs in, / %s risk a share" % (money(max_loss), _price(risk)))
    cap_pct = _f(c.get("max_position_pct"))
    if cap_pct:
        cap = round(budget * cap_pct / 100.0, 2)
        add("position cap", cap, ref, shares_for(cap, ref),
            "%s%% of %s = %s / %s" % (_num(cap_pct), money(budget), money(cap), _price(ref)))
    max_order = _f(c.get("max_order_twd"))
    if max_order:
        add("max order", max_order, ref, shares_for(max_order, ref), "%s / %s" % (money(max_order), _price(ref)))
    add("cash", available, ref, tw.max_qty_for_cash(available, ref, c),
        "%s = %s / %s, fee in" % (cash_note, money(available), _price(ref)))

    qty = max(0, min(l["shares"] for l in limits))
    tied = [l for l in limits if l["shares"] == qty]
    first = min(tied, key=lambda l: (l["raw"], limits.index(l)))
    for l in limits:
        l["binds"] = l is first
    bound = first["name"]
    if qty > 0:
        costs = tw.trade_costs(qty, ref, stop, c)
        loss = tw.loss_at_stop(qty, ref, stop, c)
        reward_net = tw.net_reward(qty, ref, target, c)
        rr_net = round(reward_net / float(loss), 2) if loss > 0 else None
    else:
        costs, loss, reward_net, rr_net = {"buy_fee": 0, "sell_fee": 0, "tax": 0, "total": 0}, 0, 0, None
    cost = round(qty * ref, 2)
    if 0 < qty < tw.BOARD_LOT:
        warnings.append("odd lot of %d shares: odd lots cannot be day traded under current TWSE rules, so this "
                        "entry becomes an OVERNIGHT position; selling it later pays the normal 0.3 percent sell "
                        "tax, and the costs here use that rate, not the day-trade rate. Use whole board lots "
                        "to day trade"
                        % qty)
    refusal = None
    if qty == 0:
        if first["raw"] > 0:
            refusal = ("%s shares would fit your %s limit, but \"allow_odd_lots\" is false and an order must be "
                       "a whole board lot (1,000 shares = %s). No order."
                       % (_n(first["raw"]), bound, money(1000 * ref)))
        elif bound == "max loss":
            one = tw.loss_at_stop(1, ref, stop, c)
            refusal = ("one share risks %s (entry %s minus stop %s, with fees and tax), more than your %s max "
                       "loss per trade. No order. Skip this trade, or plan a closer stop with trader-exit."
                       % (money(one), _price(ref), _price(stop), money(max_loss)))
        else:
            refusal = ("one share of %s costs %s, more than your %s limit (%s). No order."
                       % (sym, money(ref), bound, first["how"]))
    elif cost < float(c.get("min_order_twd") or 0) - 0.005:
        refusal = ("%s share%s of %s is %s, under your %s minimum order. No order."
                   % (_n(qty), "" if qty == 1 else "s", sym, money(cost), money(c["min_order_twd"])))
    elif _f(c.get("min_reward_risk")) and reward_net < _f(c["min_reward_risk"]) * loss - EPS:
        refusal = ("net reward:risk %.2f (gross %.2f; target %s, entry %s, stop %s, %s of costs in) is "
                   "under your minimum %s, so trader-risk would block it. No order. Skip it, or make a new "
                   "plan with trader-exit."
                   % (reward_net / float(loss), reward_c / float(risk_c), _price(target), _price(ref),
                      _price(stop), money(costs["total"]), _num(c["min_reward_risk"])))
    return {
        "symbol": sym, "side": "buy", "setup": plan.get("setup", ""), "date": plan.get("date"),
        "entry_time": plan.get("entry_time", ""), "entry_plan": round_cent(entry_plan),
        "entry": ref, "entry_from": ref_from, "stop": stop, "target": target,
        "risk_per_share": risk, "reward_risk": round(reward_c / float(risk_c), 2), "reward_risk_net": rr_net,
        "stop_label": plan.get("stop_label", ""), "target_label": plan.get("target_label", ""),
        "prev_close": pc, "limit_down": limit_down, "limit_up": limit_up, "warnings": warnings,
        "budget": budget, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer, "cash_available": available,
        "max_loss_per_trade_twd": max_loss, "limits": limits, "qty": qty, "bound_by": bound,
        "cost": cost, "costs": costs, "costs_at_stop": costs["total"], "max_loss": float(loss),
        "reward_net": reward_net, "currency": "TWD", "flat_by": plan.get("flat_by") or c.get("flat_by"),
        "order_type": "limit" if limit is not None else "market", "refusal": refusal,
        "day_trade_tax": tw.cost_tax_words(qty, c),
    }


def bracket_order(s):
    """The one proposed order, Alpaca place_stock_order fields (strings) plus why and plan."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    o = {"symbol": s["symbol"], "side": "buy", "qty": str(int(s["qty"])), "type": s["order_type"],
         "time_in_force": "day"}
    if s["order_type"] == "limit":
        o["limit_price"] = _price(s["entry"])
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "day trade")
    names = {"max loss": "%s max loss per trade" % money(s["max_loss_per_trade_twd"] or 0),
             "position cap": "position cap", "max order": "max order", "cash": "cash after the buffer"}
    why = ("%s on %s: %s shares, bound by your %s (%s x %s = %s + %s fees and tax = %s at the stop)"
           % (setup, s["symbol"], _n(s["qty"]), names[s["bound_by"]], _n(s["qty"]), _price(s["risk_per_share"]),
              money(round(s["qty"] * s["risk_per_share"], 2)), money(s["costs_at_stop"]), money(s["max_loss"])))
    o.update({
        "order_class": "bracket",
        "take_profit_limit_price": _price(s["target"]),
        "stop_loss_stop_price": _price(s["stop"]),
        "currency": "TWD",
        "why": why,
        "plan": {"entry": s["entry"], "stop": s["stop"], "target": s["target"],
                 "risk_per_share": s["risk_per_share"], "max_loss": s["max_loss"],
                 "costs_at_stop": s["costs_at_stop"], "reward_risk_net": s["reward_risk_net"],
                 "prev_close": s["prev_close"], "limit_down": s["limit_down"], "limit_up": s["limit_up"],
                 "setup": s["setup"], "entry_time": s["entry_time"], "flat_by": s["flat_by"]},
    })
    return o


def plan_report(s, order, notes=()):
    lines = []
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "setup")
    lines.append("%s buy, %s, entry %s%s" % (s["symbol"], setup, _price(s["entry_plan"]),
                                            (" at " + s["entry_time"]) if s["entry_time"] else ""))
    lines.append("Stop %s%s. Target %s%s." % (_price(s["stop"]), (": " + s["stop_label"]) if s["stop_label"] else "",
                                             _price(s["target"]),
                                             (": " + s["target_label"]) if s["target_label"] else ""))
    if s["prev_close"]:
        lines.append("Price limits today: %s down to %s up (previous close %s, +/-10%%)."
                     % (_price(s["limit_down"]), _price(s["limit_up"]), _price(s["prev_close"])))
    for n in notes:
        lines.append(n)
    for w in s["warnings"]:
        lines.append("Warning: " + w)
    src = {"plan": "the plan's entry", "price": "the latest price, above the plan's entry",
           "limit": "your limit price"}[s["entry_from"]]
    lines.append("Sized at %s (%s). Risk %s a share (entry %s minus stop %s). Gross reward:risk %.2f."
                 % (_price(s["entry"]), src, _price(s["risk_per_share"]), _price(s["entry"]), _price(s["stop"]),
                    s["reward_risk"]))
    lines.append("")
    lines.append("Limits (shares; each rounded down to a board lot or one odd lot; the smallest one wins):")
    for l in s["limits"]:
        use = _n(l["shares"]) if l["raw"] == l["shares"] else "%s -> %s" % (_n(l["raw"]), _n(l["shares"]))
        lines.append("  %-13s %-72s %12s shares%s" % (l["name"], l["how"], use, "  <- binds" if l["binds"] else ""))
    lines.append("")
    if order is None:
        lines.append("No order: " + s["refusal"])
        lines.append(tw.ELIGIBILITY_REMINDER)
        lines.append("Education and tooling, not financial advice.")
        return "\n".join(lines)
    lines.append("Size: %s shares (%s) of %s = %s at %s."
                 % (_n(s["qty"]), tw.lot_words(s["qty"]), s["symbol"], money(s["cost"]), _price(s["entry"])))
    lines.append("Max loss at the stop: %s x %s = %s + %s fees and tax = %s."
                 % (_n(s["qty"]), _price(s["risk_per_share"]), money(round(s["qty"] * s["risk_per_share"], 2)),
                    money(s["costs_at_stop"]), money(s["max_loss"])))
    lines.append("If the target fills: %s net of costs. Net reward:risk %.2f (gross %.2f)."
                 % (money(s["reward_net"]), s["reward_risk_net"], s["reward_risk"]))
    lines.append("Costs use the %s." % s["day_trade_tax"])
    lines.append("A stop is an order, not a promise: in a fast market it can fill below %s." % _price(s["stop"]))
    lines.append("")
    lines.append("Proposed order (place_stock_order arguments, nothing has been placed):")
    how = "limit %s" % order["limit_price"] if order["type"] == "limit" else "market"
    lines.append("  buy %s %s, %s, day, take-profit %s, stop-loss %s"
                 % (order["qty"], order["symbol"], how, order["take_profit_limit_price"],
                    order["stop_loss_stop_price"]))
    lines.append(NO_BRACKET)
    if s["flat_by"]:
        lines.append("Flat by %s Taipei: anything still open then gets closed (trader-alerts rings, "
                     "trader-broker flatten)." % s["flat_by"])
    lines.append(tw.ELIGIBILITY_REMINDER)
    lines.append("")
    lines.append("Next: trader-risk checks it, then trader-broker asks you yes or no.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- weights mode

def normalise(rows, blocked=(), top=None):
    """Drop blocked and non-positive weights, keep the top N, renormalise to 100."""
    blocked = {str(b).upper() for b in (blocked or [])}
    dropped, keep, seen = [], [], set()
    for r in rows:
        if r["ticker"] in seen:
            raise SizeError("%s is listed twice in the weights" % r["ticker"])
        seen.add(r["ticker"])
        if r["ticker"] in blocked:
            dropped.append({"ticker": r["ticker"], "reason": "on your blocked list"})
        elif r["weight"] <= 0:
            dropped.append({"ticker": r["ticker"], "reason": "weight is zero or negative"})
        else:
            keep.append(dict(r))
    keep.sort(key=lambda r: -r["weight"])
    if top:
        for r in keep[top:]:
            dropped.append({"ticker": r["ticker"], "reason": "outside the top %d" % top})
        keep = keep[:top]
    total = sum(r["weight"] for r in keep)
    for r in keep:
        r["source_weight"] = r["weight"]
        r["weight"] = 100.0 * r["weight"] / total if total else 0.0
    return keep, dropped


def allocate(rows, investable, cap):
    """Exact (unrounded) dollars per ticker with the cap enforced.

    Proportional to weight; any stock over the cap is pinned at the cap and
    the rest of the money is shared over the others, repeated until no stock
    is over. Returns ({ticker: dollars}, set of capped tickers)."""
    alloc, capped = {}, set()
    active = [r for r in rows]
    money_left = investable
    while active:
        wsum = sum(r["weight"] for r in active)
        trial = {r["ticker"]: money_left * r["weight"] / wsum for r in active}
        over = [r for r in active if trial[r["ticker"]] > cap + EPS]
        if not over:
            alloc.update(trial)
            break
        for r in over:
            alloc[r["ticker"]] = cap
            capped.add(r["ticker"])
            money_left -= cap
        active = [r for r in active if r["ticker"] not in capped]
        if money_left <= EPS:
            for r in active:
                alloc[r["ticker"]] = 0.0
            break
    return alloc, capped


def round_to_unit(exact, capped, order, cap, unit):
    """Round to whole dollars (unit 1) or cents (unit 0.01) and keep the total.

    The total placed is the exact total rounded DOWN to the unit, so it never
    spends money you do not have. Each slice is rounded to the nearest unit,
    then the difference (usually one unit) goes to the biggest stock that is
    not capped, then the next, never pushing anyone over the cap."""
    def units(x):
        return int(math.floor(x / unit + EPS))

    cap_u = units(cap)
    total_u = units(sum(exact.values()))
    out = {}
    for t, v in exact.items():
        out[t] = cap_u if t in capped else int(math.floor(v / unit + 0.5 + EPS))
    diff = total_u - sum(out.values())
    takers = [t for t in order if t not in capped]
    guard = 0
    while diff != 0 and takers and guard < 100000:
        moved = False
        for t in takers:
            if diff == 0:
                break
            if diff > 0 and out[t] + 1 <= cap_u:
                out[t] += 1
                diff -= 1
                moved = True
            elif diff < 0 and out[t] > 0:
                out[t] -= 1
                diff += 1
                moved = True
        if not moved:
            break
        guard += 1
    return {t: round(u * unit, 2) for t, u in out.items()}


def size(rows, cfg, budget=None, prices=None, top=None):
    """Weights mode. Pure function: weights + rules + prices -> the full sizing result (a dict).

    Whole shares only, rounded down to a valid lot size, no top-up; every stock needs a price."""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("no budget: pass --budget or set \"budget\" in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct", 10))
    cap_pct = float(c.get("max_position_pct", 25))
    min_order = float(c.get("min_order_twd", 1000) or 0)
    allow_odd = bool(c.get("allow_odd_lots", True))
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct must be between 0 and 100")
    if not 0 < cap_pct <= 100:
        raise SizeError("max_position_pct must be above 0 and at most 100")
    prices = prices or {}

    for r in rows:
        problem = tw.stock_problem(r["ticker"])
        if problem:
            raise SizeError(problem)
    keep, dropped = normalise(rows, c.get("blocked"), top)
    if not keep:
        raise SizeError("nothing to size: no weights left after the blocked list")

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    investable = round(budget - cash_buffer, 2)
    cap = round(budget * cap_pct / 100.0, 2)

    missing = [r["ticker"] for r in keep if not prices.get(r["ticker"])]
    if missing:
        raise SizeError("weights mode needs a price for: %s (pass --prices with a {\"prices\": {\"2317.TW\": 205.0}} "
                        "file, e.g. trader/prices.json)" % ", ".join(missing))

    while True:
        live = [dict(r) for r in keep]
        tot = sum(r["source_weight"] for r in live)
        for r in live:
            r["weight"] = 100.0 * r["source_weight"] / tot
        exact, capped = allocate(live, investable, cap)
        order = [r["ticker"] for r in sorted(live, key=lambda r: -exact[r["ticker"]])]
        slice_ = round_to_unit(exact, capped, order, cap, 1.0)
        shares = {t: tw.floor_qty(int(slice_[t] / prices[t] + EPS), allow_odd) for t in order}
        dollars = {t: round(shares[t] * prices[t], 2) for t in order}
        small = [r for r in live if shares[r["ticker"]] == 0 or dollars[r["ticker"]] < min_order - EPS]
        if not small:
            break
        worst = min(small, key=lambda r: (r["source_weight"], r["ticker"]))
        t = worst["ticker"]
        if shares[t] == 0:
            reason = ("one %s costs %s, more than its slice of %s" % (
                "share" if allow_odd else "board lot (1,000 shares)",
                money(prices[t] * (1 if allow_odd else 1000)), money(slice_[t])))
        else:
            reason = "its slice (%s) is under your %s minimum order" % (money(dollars[t]), money(min_order))
        dropped.append({"ticker": t, "reason": reason})
        keep = [r for r in keep if r["ticker"] != t]
        if not keep:
            raise SizeError("every slice is under your minimum order or cannot buy one lot; raise the budget "
                            "or hold fewer stocks")

    positions = []
    for r in sorted(live, key=lambda r: -r["weight"]):
        t = r["ticker"]
        positions.append({"ticker": t, "name": r["name"], "weight": round(r["weight"], 2),
                          "source_weight": r["source_weight"], "dollars": dollars[t],
                          "capped": t in capped, "price": prices[t], "shares": shares[t]})
    invested = round(sum(p["dollars"] for p in positions), 2)
    return {
        "budget": budget, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer,
        "investable": investable, "max_position_pct": cap_pct, "cap": cap,
        "min_order_twd": min_order, "currency": "TWD",
        "positions": positions, "invested": invested,
        "idle": round(investable - invested, 2), "dropped": dropped,
    }


def orders_from(result, source=""):
    """Weights mode: proposed buy orders, one per position, in place_stock_order shape."""
    out = []
    for p in result["positions"]:
        if p["shares"] <= 0:
            continue
        why = "%.2f%% of the split" % p["weight"]
        if source:
            why = "%s, weights from %s" % (why, source)
        if p["capped"]:
            why += "; capped at %s%% of the %s budget" % (_num(result["max_position_pct"]), money(result["budget"]))
        out.append({"symbol": p["ticker"], "side": "buy", "qty": str(int(p["shares"])), "type": "market",
                    "time_in_force": "day", "currency": "TWD", "why": why})
    return out


def report(result, orders, source=""):
    """Weights mode table."""
    r = result
    lines = []
    if source:
        lines.append("Weights from: %s" % source)
    lines.append("Budget %s, cash buffer %s%% = %s, investing %s, cap %s%% = %s per stock"
                 % (money(r["budget"]), _num(r["cash_buffer_pct"]), money(r["cash_buffer"]),
                    money(r["investable"]), _num(r["max_position_pct"]), money(r["cap"])))
    lines.append("")
    lines.append("%-9s %-26s %8s %12s %10s %9s  %s" % ("ticker", "name", "weight", "amount", "price", "shares", "note"))
    for p in r["positions"]:
        row = "%-9s %-26s %7.2f%% %12s %10s %9s" % (p["ticker"], (p["name"] or "")[:26], p["weight"],
                                                    money(p["dollars"]), _price(p["price"]), _n(p["shares"]))
        if p["capped"]:
            row += "  capped at %s%%" % _num(r["max_position_pct"])
        if 0 < p["shares"] < tw.BOARD_LOT:
            row += "  odd lot"
        lines.append(row)
    lines.append("%-9s %-26s %8s %12s" % ("", "invested", "", money(r["invested"])))
    lines.append("%-9s %-26s %8s %12s" % ("", "cash buffer", "", money(r["cash_buffer"])))
    lines.append("%-9s %-26s %8s %12s" % ("", "left idle", "", money(r["idle"])))
    if r["idle"] >= 1:
        lines.append("")
        lines.append("Left idle %s: whole shares and board lots do not divide evenly, or every stock is at its "
                     "cap (add stocks or raise max_position_pct)." % money(r["idle"]))
    for d in r["dropped"]:
        lines.append("Dropped %s: %s" % (d["ticker"], d["reason"]))
    lines.append("Amounts are share value only; broker fees and tax come on top.")
    lines.append("")
    lines.append("Proposed orders (place_stock_order arguments, nothing has been placed):")
    for o in orders:
        lines.append("  %s %s qty \"%s\", %s, %s" % (o["side"], o["symbol"], o["qty"], o["type"], o["time_in_force"]))
    lines.append("")
    lines.append("These buys have no stop. trader-risk blocks them while \"require_stop\" is true and applies "
                 "your day-trade limits to every buy.")
    lines.append("Next: trader-risk checks every order, then trader-broker asks you yes or no for each one.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- orders file

def write_orders(path, orders, cfg, source="", now_utc=None):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    doc = {
        "created_by": "trader-budget",
        "created_at": utc_iso(now_utc),
        "status": "proposed",
        "paper": bool(cfg.get("paper", True)),
        "note": ("Proposals only. Nothing is placed until trader-risk passes each order "
                 "and you say yes to it in the chat."),
        "source": source,
        "orders": orders,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)



# ---------------------------------------------------------------- main

def run_plan(a, cfg):
    now = parse_now(a.now)
    today = to_taipei(now).date().isoformat()
    plan = read_json(a.plan, "plan (run trader-exit first, or use --weights for a split)")
    limit = None
    if a.limit is not None:
        if a.limit == "plan":
            limit = _f((plan or {}).get("entry"))
        else:
            limit = _f(a.limit)
            if limit is None or limit <= 0:
                raise SizeError("--limit wants a price, like --limit 205.50")
    sym = str((plan or {}).get("symbol") or "").upper()
    notes, price, prev_close = [], None, None
    ppath = a.prices or ("trader/prices.json" if os.path.exists("trader/prices.json") else None)
    if ppath and sym:
        pdoc = read_json(ppath, "prices")
        det = ((pdoc or {}).get("detail") or {}).get(sym) if isinstance(pdoc, dict) else None
        prev_close = _f((det or {}).get("prev_close"))
        if limit is None:
            p, t, fresh = fresh_price(pdoc, sym, now)
            if p is not None and fresh:
                price = p
                if round_cent(p) > round_cent(_f(plan.get("entry")) or 0):
                    notes.append("%s last %s (as of %s Taipei) is above the plan's entry %s, so the risk "
                                 "is bigger: sized at %s." % (sym, _price(p), to_taipei(t).strftime("%H:%M"),
                                                              _price(plan.get("entry")), _price(p)))
            elif p is not None:
                notes.append("%s in %s is %s: not used (older than %d minutes). Sized at the plan's entry."
                             % (sym, ppath, ("from " + to_taipei(t).strftime("%Y-%m-%d %H:%M") + " Taipei")
                                if t else "undated", FRESH_MINUTES))
    cash = None
    if a.portfolio and os.path.exists(a.portfolio):
        pf = read_json(a.portfolio, "portfolio")
        cash = _f(pf.get("cash")) if isinstance(pf, dict) else None
    s = size_trade(plan, cfg, a.budget, limit, price, cash, today, prev_close)
    order = bracket_order(s)
    if order and a.write:
        src = "trader/plan.json (%s %s %s)" % (s["symbol"], s["setup"] or "plan", s["date"] or today)
        write_orders(a.write, [order], cfg, src, now)
    if a.json:
        print(json.dumps({"sizing": s, "orders": [order] if order else [], "notes": notes}, indent=2))
    else:
        print(plan_report(s, order, notes))
        if order and a.write:
            print("Wrote 1 proposed order to %s" % a.write)
    return 0 if order else 1


def run_weights(a, cfg):
    source = ""
    if a.weights:
        rows = parse_weights(weights_from_arg(a.weights))
    else:
        data = read_json(a.targets, "weights file")
        rows = parse_weights(data)
        if isinstance(data, dict):
            source = data.get("source", "")
    prices = load_prices(a.prices)
    if not prices and os.path.exists("trader/prices.json") and not a.prices:
        prices = load_prices("trader/prices.json")
    result = size(rows, cfg, a.budget, prices, a.top)
    orders = orders_from(result, source)
    if a.write:
        write_orders(a.write, orders, cfg, source, parse_now(a.now))
    if a.json:
        print(json.dumps({"result": result, "orders": orders}, indent=2))
    else:
        print(report(result, orders, source))
        if a.write:
            print("Wrote %d proposed orders to %s" % (len(orders), a.write))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Size a Taiwan day trade to your budget and max loss (trader-budget).")
    ap.add_argument("--plan", default="trader/plan.json", help="the trade plan (default trader/plan.json)")
    ap.add_argument("--config", default="trader/config.json", help="rules (default trader/config.json)")
    ap.add_argument("--budget", type=float, help="override the budget in the config (TWD)")
    ap.add_argument("--limit", nargs="?", const="plan", metavar="PRICE",
                    help="a limit order instead of market, at the plan's entry or at PRICE")
    ap.add_argument("--prices", help="prices JSON (default trader/prices.json if it exists)")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="your account; its cash caps the size if it exists")
    ap.add_argument("--now", help="pretend it is this Taipei time, e.g. \"2026-10-19 09:30\"")
    ap.add_argument("--write", nargs="?", const="trader/orders.json", metavar="PATH",
                    help="write the proposed order (default trader/orders.json)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the report")
    g = ap.add_argument_group("weights mode (split a budget across a list)")
    g.add_argument("--weights", help="inline weights: 2330.TW=40,2317.TW=25")
    g.add_argument("--targets", help="a weights file: {\"weights\": [{\"ticker\", \"weight\"}]}")
    g.add_argument("--top", type=int, help="keep only the N biggest weights")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        if a.weights or a.targets:
            return run_weights(a, cfg)
        if a.top:
            raise SizeError("--top works with --weights or --targets")
        return run_plan(a, cfg)
    except SizeError as e:
        print("size.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
