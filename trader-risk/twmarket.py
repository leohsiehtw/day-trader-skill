"""Taiwan market helpers shared by the trader-* skills. Standard library only, no network, Python 3.8+.

Not a script: trader-entry, trader-exit, trader-budget, trader-scanner and trader-risk import it
(they look for it in this folder and in a sibling trader-risk folder). It holds the Taipei clock
(no daylight time, a fixed +8 hours), the TWSE holiday list, the price tick table, the 10 percent
daily limits, board-lot rules and the broker fee and day-trade tax arithmetic. Money is done in
Decimal and rounded UP to whole TWD, the way a broker rounds a fee.

Day-trade sell tax. "day_trade_mode" picks the kind of day trade:
  cash_daytrade    (default) a cash day trade: day_trade_sell_tax_pct (0.15) on the sell leg while the
                   trade date is on or before day_trade_tax_halved_until ("2027-12-31"); after that date
                   it reverts to sell_tax_pct (0.3) by itself
  margin_daytrade  a margin / short-sale day trade: sell_tax_pct (0.3), never halved
The trade date is the cost config's "trade_date" (the --now / --today date the tools pass in), else
today in Taipei.

Odd lots (1 to 999 shares) cannot be day traded on the TWSE, so an odd-lot entry is costed as an
overnight position sold later: the sell leg pays the normal sell_tax_pct (0.3), not the day-trade rate.
"""

import datetime
import re
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

TZ_OFFSET = datetime.timedelta(hours=8)
OPEN = datetime.time(9, 0)
CLOSE = datetime.time(13, 30)
BOARD_LOT = 1000
FEE_RATE = Decimal("0.001425")
DAY_TRADE_MODES = ("cash_daytrade", "margin_daytrade")
DAY_TRADE_TAX_HALVED_UNTIL = "2027-12-31"     # last trade date of the halved cash day-trade sell tax
COST_DEFAULTS = {"fee_discount": 0.6, "min_fee_twd": 20, "day_trade_sell_tax_pct": 0.15,
                 "sell_tax_pct": 0.3, "allow_odd_lots": True, "day_trade_mode": "cash_daytrade",
                 "day_trade_tax_halved_until": DAY_TRADE_TAX_HALVED_UNTIL}

# Days the TWSE cash market is closed on a weekday, from the TWSE holiday schedule
# (openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule), 2026 only. Weekends are not listed.
# For any other year only weekends are known: check the TWSE schedule and add the year here.
CALENDAR_YEARS = (2026,)
TWSE_HOLIDAYS = {
    "2026-01-01": "Founding Day of the Republic of China",
    "2026-02-12": "no trading before Lunar New Year (settlement only)",
    "2026-02-13": "no trading before Lunar New Year (settlement only)",
    "2026-02-16": "Lunar New Year",
    "2026-02-17": "Lunar New Year",
    "2026-02-18": "Lunar New Year",
    "2026-02-19": "Lunar New Year",
    "2026-02-20": "Lunar New Year (observed)",
    "2026-02-27": "Peace Memorial Day (observed)",
    "2026-04-03": "Children's Day (observed)",
    "2026-04-06": "Tomb Sweeping Day (observed)",
    "2026-05-01": "Labor Day",
    "2026-06-19": "Dragon Boat Festival",
    "2026-09-25": "Mid-Autumn Festival",
    "2026-09-28": "Confucius' Birthday / Teachers' Day",
    "2026-10-09": "National Day (observed)",
    "2026-10-26": "Taiwan Retrocession Day (observed)",
    "2026-12-25": "Constitution Day",
}

SYMBOL = re.compile(r"^([0-9A-Z]{4,6})\.(TW|TWO)$")
STOCK = re.compile(r"^[1-9]\d{3}\.(TW|TWO)$")
_NOW_HELP = '--now wants a Taipei time like "2026-10-19 09:30" (or ...Z for UTC)'


class TWError(ValueError):
    pass


# ---------------------------------------------------------------- time (Taipei, fixed +8)

def to_taipei(utc):
    """Naive UTC datetime -> naive Taipei datetime."""
    return utc + TZ_OFFSET


def taipei_to_utc(local):
    """Naive Taipei datetime -> naive UTC datetime."""
    return local - TZ_OFFSET


def ts_to_taipei(ts):
    """Epoch seconds -> naive Taipei datetime."""
    return datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=ts) + TZ_OFFSET


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def parse_now(text):
    """A --now value -> naive UTC. Taipei wall time by default; a trailing Z or +hh:mm is honoured."""
    s = (text or "").strip()
    if not s:
        raise TWError(_NOW_HELP)
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s*(?:TPE|Taipei|CST))?$", s, re.I)
    if m:
        h, mi, sec = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        try:
            t = datetime.time(h, mi, sec)
        except ValueError:
            raise TWError(_NOW_HELP)
        return taipei_to_utc(datetime.datetime.combine(to_taipei(utc_now()).date(), t))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*"
                 r"(Z|[+-]\d{2}:?\d{2}|TPE|Taipei|CST)?$", s, re.I)
    if not m:
        raise TWError(_NOW_HELP)
    try:
        local = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                  int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0))
    except ValueError:
        raise TWError(_NOW_HELP)
    zone = (m.group(7) or "").upper()
    if zone == "Z":
        return local
    if zone and zone[0] in "+-":
        digits = zone[1:].replace(":", "")
        off = datetime.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        return local - (off if zone[0] == "+" else -off)
    return taipei_to_utc(local)


def calendar_known(d):
    return d.year in CALENDAR_YEARS


def trading_day(d):
    """date -> (is_trading_day, why_not). why_not is "", "weekend" or "TWSE holiday: <name>"."""
    if d.weekday() >= 5:
        return False, "weekend"
    name = TWSE_HOLIDAYS.get(d.isoformat())
    if name:
        return False, "TWSE holiday: " + name
    return True, ""


def session(d):
    """date -> (open, close) as naive Taipei datetimes. There is no early close in Taiwan."""
    return datetime.datetime.combine(d, OPEN), datetime.datetime.combine(d, CLOSE)


def next_open(when):
    """Naive Taipei datetime (or date) -> the next session open, as "YYYY-MM-DD 09:00"."""
    if isinstance(when, datetime.datetime):
        d = when.date()
        if trading_day(d)[0] and when < session(d)[0]:
            return d.strftime("%Y-%m-%d") + " 09:00"
    else:
        d = when
    d += datetime.timedelta(days=1)
    for _ in range(30):
        if trading_day(d)[0]:
            return d.strftime("%Y-%m-%d") + " 09:00"
        d += datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d") + " 09:00"


# ---------------------------------------------------------------- prices

def D(x):
    """A number (float, int, str, Decimal) -> Decimal without float noise."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(str(x))


_CENT = Decimal("0.01")


def tick_size(price):
    p = D(price)
    if p < 10:
        return Decimal("0.01")
    if p < 50:
        return Decimal("0.05")
    if p < 100:
        return Decimal("0.1")
    if p < 500:
        return Decimal("0.5")
    if p < 1000:
        return Decimal("1")
    return Decimal("5")


def round_tick(price, mode="nearest", band=None):
    """Round to the tick grid. The tick comes from the price band of `price` (or of `band` if given).
    mode: "down", "up" or "nearest" (halves go up). Returns a Decimal with 2 places."""
    p = D(price)
    t = tick_size(p if band is None else band)
    n = p / t
    if mode == "down":
        k = n.to_integral_value(rounding=ROUND_FLOOR)
    elif mode == "up":
        k = n.to_integral_value(rounding=ROUND_CEILING)
    elif mode == "nearest":
        k = n.to_integral_value(rounding=ROUND_HALF_UP)
    else:
        raise TWError("round_tick mode must be down, up or nearest")
    return (k * t).quantize(_CENT)


def on_tick(price):
    p = D(price)
    t = tick_size(p)
    return (p / t) == (p / t).to_integral_value()


def limit_prices(prev_close):
    """Previous close -> (limit_down, limit_up): +/-10 percent, snapped inward to the tick grid."""
    p = D(prev_close)
    up_raw = p * Decimal("1.1")
    dn_raw = p * Decimal("0.9")
    return round_tick(dn_raw, "up"), round_tick(up_raw, "down")


# ---------------------------------------------------------------- lots

def valid_qty(qty, allow_odd=True):
    """Whole board lots (multiples of 1000), or one odd lot of 1 to 999 shares when allowed."""
    try:
        q = int(qty)
    except (TypeError, ValueError):
        return False
    if q != qty or q <= 0:
        return False
    if q % BOARD_LOT == 0:
        return True
    return bool(allow_odd) and q < BOARD_LOT


def floor_qty(qty, allow_odd=True):
    """Largest valid quantity not above qty (0 if none)."""
    q = int(qty)
    if q <= 0:
        return 0
    if q >= BOARD_LOT:
        return q // BOARD_LOT * BOARD_LOT
    return q if allow_odd else 0


def lot_words(qty):
    q = int(qty)
    if q % BOARD_LOT == 0 and q > 0:
        n = q // BOARD_LOT
        return "%d board lot%s" % (n, "" if n == 1 else "s")
    if 0 < q < BOARD_LOT:
        return "odd lot of %d share%s" % (q, "" if q == 1 else "s")
    return "%d shares (not a valid lot size)" % q


# ---------------------------------------------------------------- costs

def cost_params(cfg):
    out = dict(COST_DEFAULTS)
    for k in COST_DEFAULTS:
        if cfg and cfg.get(k) is not None:
            out[k] = cfg[k]
    out["trade_date"] = (cfg or {}).get("trade_date")
    return out


def _as_date(value, what):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise TWError("%s wants a date like 2027-12-31, got %r" % (what, value))


def cost_problem(cfg):
    """None if the day-trade cost keys are valid; else what is wrong (for a config error)."""
    c = cost_params(cfg)
    if c["day_trade_mode"] not in DAY_TRADE_MODES:
        return ("day_trade_mode must be \"cash_daytrade\" or \"margin_daytrade\", got %r" % (c["day_trade_mode"],))
    try:
        _as_date(c["day_trade_tax_halved_until"], "day_trade_tax_halved_until")
        if c["trade_date"] is not None:
            _as_date(c["trade_date"], "trade_date")
    except TWError as e:
        return str(e)
    return None


def day_trade_tax_pct(cfg=None, trade_date=None):
    """The sell-tax rate (percent, Decimal) of a day trade on trade_date (default: the config's
    trade_date, else today in Taipei). Raises TWError on a bad day_trade_mode or date."""
    problem = cost_problem(cfg)
    if problem:
        raise TWError(problem)
    c = cost_params(cfg)
    if c["day_trade_mode"] == "margin_daytrade":
        return D(c["sell_tax_pct"])
    d = trade_date if trade_date is not None else c["trade_date"]
    d = _as_date(d, "trade_date") if d is not None else to_taipei(utc_now()).date()
    if d > _as_date(c["day_trade_tax_halved_until"], "day_trade_tax_halved_until"):
        return D(c["sell_tax_pct"])
    return D(c["day_trade_sell_tax_pct"])


def day_trade_tax_words(cfg=None, trade_date=None):
    """One line on the day-trade sell tax in use, e.g. "0.15% cash day-trade sell tax (halved through 2027-12-31)"."""
    c = cost_params(cfg)
    rate = day_trade_tax_pct(cfg, trade_date)
    pct = format(rate.normalize(), "f")
    if c["day_trade_mode"] == "margin_daytrade":
        return "%s%% margin/short day-trade sell tax (not halved)" % pct
    until = _as_date(c["day_trade_tax_halved_until"], "day_trade_tax_halved_until").isoformat()
    if rate == D(c["day_trade_sell_tax_pct"]) and rate != D(c["sell_tax_pct"]):
        return "%s%% cash day-trade sell tax (halved through %s)" % (pct, until)
    return "%s%% cash day-trade sell tax (the halved rate ended %s)" % (pct, until)


ELIGIBILITY_REMINDER = ("Not checked: whether your account may day trade (account age, trade count, signed "
                        "day-trade consent; sell-first also needs a margin/lending contract) or whether this stock "
                        "is on the TWSE daily day-trade list. Confirm with your broker.")


def is_odd_lot(qty):
    """True for an odd-lot order of 1 to 999 shares (it cannot be day traded)."""
    return 0 < D(qty) < BOARD_LOT


def cost_tax_words(qty, cfg=None, trade_date=None):
    """The sell tax the costs of a qty-share order use: the day-trade tax for board lots, the normal
    sell tax for an odd lot (it cannot be day traded, so it is sold later as an overnight position)."""
    if is_odd_lot(qty):
        pct = format(D(cost_params(cfg)["sell_tax_pct"]).normalize(), "f")
        return "%s%% normal sell tax (odd lot: no day trade, sold later as an overnight position)" % pct
    return day_trade_tax_words(cfg, trade_date)


def _ceil(x):
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def broker_fee(notional, cfg=None):
    """Broker commission for one order, whole TWD, rounded up, with the minimum fee. 0 for no notional."""
    n = D(notional)
    if n <= 0:
        return 0
    c = cost_params(cfg)
    fee = _ceil(n * FEE_RATE * D(c["fee_discount"]))
    return max(int(c["min_fee_twd"]), fee)


def sell_tax(notional, cfg=None, rate_key="day_trade_sell_tax_pct", trade_date=None):
    """Sell tax, whole TWD rounded up. The default rate_key is the day-trade rate, which follows
    day_trade_mode and the trade date (see day_trade_tax_pct); "sell_tax_pct" is the plain rate."""
    n = D(notional)
    if n <= 0:
        return 0
    if rate_key == "day_trade_sell_tax_pct":
        rate = day_trade_tax_pct(cfg, trade_date)
    else:
        rate = D(cost_params(cfg)[rate_key])
    return _ceil(n * rate / Decimal(100))


def trade_costs(qty, open_px, close_px, cfg=None, side="buy"):
    """Fees and tax of opening and closing the same quantity.
    side "buy": buy at open_px, sell at close_px. side "sell": sell at open_px, buy at close_px.
    Board lots pay the day-trade sell tax; an odd lot (1 to 999 shares) cannot be day traded, so it
    pays the normal sell_tax_pct."""
    q = D(qty)
    buy_px, sell_px = (D(open_px), D(close_px)) if side == "buy" else (D(close_px), D(open_px))
    buy_n, sell_n = q * buy_px, q * sell_px
    bf, sf = broker_fee(buy_n, cfg), broker_fee(sell_n, cfg)
    tax = sell_tax(sell_n, cfg, "sell_tax_pct") if is_odd_lot(q) else sell_tax(sell_n, cfg)
    return {"buy_fee": bf, "sell_fee": sf, "tax": tax, "total": bf + sf + tax}


def loss_at_stop(qty, entry, stop, cfg=None, side="buy"):
    """Worst case if the stop fills at the stop: price loss plus costs, whole TWD."""
    gross = D(qty) * abs(D(entry) - D(stop))
    return _ceil(gross) + trade_costs(qty, entry, stop, cfg, side)["total"]


def net_reward(qty, entry, target, cfg=None, side="buy"):
    """Gain if the target fills, after costs (can be negative)."""
    gross = D(qty) * abs(D(target) - D(entry))
    return int(gross.to_integral_value(rounding=ROUND_FLOOR)) - trade_costs(qty, entry, target, cfg, side)["total"]


def _max_q(ok, hi):
    lo = 0
    hi = int(hi)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def max_qty_for_loss(cap, entry, stop, cfg=None, side="buy"):
    """Most shares whose loss at the stop (costs included) stays within cap.
    The loss rises with qty within 1..999 (normal sell tax) and within 1000.. (day-trade tax), but
    can drop at 1000 when the day-trade rate is lower, so the two ranges are searched apart."""
    risk = abs(D(entry) - D(stop))
    if risk <= 0:
        return 0
    hi = int(D(cap) / risk) + 1

    def ok(q):
        return loss_at_stop(q, entry, stop, cfg, side) <= D(cap)

    if hi >= BOARD_LOT and ok(BOARD_LOT):
        return BOARD_LOT + _max_q(lambda k: ok(BOARD_LOT + k), hi - BOARD_LOT)
    return _max_q(ok, min(hi, BOARD_LOT - 1))


def max_qty_for_cash(cash, price, cfg=None):
    """Most shares a buy can pay for, fee included."""
    p = D(price)
    if p <= 0 or D(cash) <= 0:
        return 0
    hi = int(D(cash) / p) + 1
    return _max_q(lambda q: q * p + broker_fee(q * p, cfg) <= D(cash), hi)


def round_trip_cost_pct(price, cfg=None, trade_date=None, qty=BOARD_LOT):
    """Costs of buying and selling qty shares (default one board lot) at the same price, in percent
    of one side's value. An odd-lot qty uses the normal sell tax (see trade_costs)."""
    p = D(price)
    if p <= 0:
        return 0.0
    if trade_date is not None:
        cfg = dict(cfg or {}, trade_date=trade_date)
    q = int(qty)
    if q <= 0:
        return 0.0
    c = trade_costs(q, p, p, cfg)
    return float(Decimal(c["total"]) / (p * q) * 100)


# ---------------------------------------------------------------- symbols

def stock_problem(sym):
    """None if sym is a 4-digit common stock like 2317.TW; else the reason this tool will not size it."""
    s = (sym or "").upper()
    m = SYMBOL.match(s)
    if not m:
        return "%s is not a Taiwan symbol like 2317.TW (TWSE) or 6488.TWO (TPEx)" % sym
    code = m.group(1)
    if code.startswith("00"):
        return ("%s looks like an ETF or ETN (00xx code). This tool sizes 4-digit common stocks only; "
                "ETFs have their own tick and limit rules" % s)
    if not STOCK.match(s):
        return "%s is not a 4-digit common stock code; this tool handles codes like 2317.TW only" % s
    return None


def yahoo_symbol(text):
    """User text -> Yahoo symbol like 2317.TW. A bare code is refused: TWSE or TPEx is not guessable."""
    s = (text or "").strip().upper()
    if SYMBOL.match(s):
        return s
    if re.match(r"^[0-9A-Z]{4,6}$", s):
        raise TWError("%s needs its market: %s.TW (TWSE listed) or %s.TWO (TPEx OTC)" % (s, s, s))
    raise TWError("%s is not a Taiwan symbol like 2317.TW (TWSE) or 6488.TWO (TPEx)" % (text or "").strip())
