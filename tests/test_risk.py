import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")

CFG_PATH = os.path.join(ROOT, "trader-budget", "config.example.json")
ORDERS_PATH = os.path.join(FIX, "trader-risk", "orders-2317.json")
SPLIT_PATH = os.path.join(FIX, "trader-risk", "orders-split-tw.json")
NOW = "2026-10-19 09:30"          # Taipei, a made-up Monday session
TODAY = "2026-10-19"
PREV = {"2317.TW": 200.0}         # previous close of the synthetic session
# Synthetic prices (not quotes) for the plain-buy tests
PRICES = {"2330.TW": 1000.0, "2317.TW": 205.0, "2412.TW": 120.0, "2882.TW": 70.0, "6488.TWO": 850.0}
QUOTE_TIME = datetime.datetime(2026, 10, 19, 1, 28, 13)   # a quote of 207.30, 09:28:13 Taipei
# every day-trade check switched off: the plain checks (size, cash, position, duplicates) still hold
OFF = {"require_stop": False, "no_entries_before": None, "no_entries_after": None, "max_trades_per_day": 0,
       "max_daily_loss_twd": 0, "max_loss_per_trade_twd": 0, "min_reward_risk": 0}


def at(text):
    return check.parse_now(text)


def cfg(**over):
    with open(CFG_PATH) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def off(**over):
    c = cfg(**OFF)
    c.update(over)
    return c


def o2317(**over):
    with open(ORDERS_PATH) as fh:
        o = json.load(fh)["orders"][0]
    o.update(over)
    return o


def bracket(sym, qty, entry, stop, target):
    return {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "%.2f" % target,
            "stop_loss_stop_price": "%.2f" % stop,
            "plan": {"entry": entry, "stop": stop, "target": target}}


def plain(sym, qty):
    return {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day"}


def placed(sym, side="buy", day=TODAY, max_loss=3652.0, kind=None, status="placed"):
    r = {"symbol": sym, "side": side, "status": status, "date": day, "at": day + "T10:20:00+08:00"}
    if max_loss is not None:
        r["max_loss"] = max_loss
    if kind:
        r["kind"] = kind
    return r


def verdicts(res):
    return [r["verdict"] for r in res["results"]]


def reasons(res, i=0):
    return " | ".join(res["results"][i]["reasons"])


def warnings(res, i=0):
    return " | ".join(res["results"][i]["warnings"])


class TheSession(unittest.TestCase):
    # Expected numbers were worked out separately with exact fractions: fee = ceil(value x 0.1425% x 0.6),
    # tax = ceil(sell value x 0.15%). 1,000 shares 205 -> 202: fees 176 + 173, tax 303 = 652.
    def test_the_2317_order_passes_every_check(self):
        res = check.check([o2317()], cfg(), now=at(NOW), prev_closes=PREV)
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"], [])
        self.assertEqual((r["kind"], r["entry_ref"], r["stop"], r["target"]), ("entry", 205.0, 202.0, 211.0))
        self.assertEqual((r["risk_per_share"], r["max_loss"], r["costs_at_stop"]), (3.0, 3652.0, 652))
        self.assertEqual((r["reward_risk"], r["reward_risk_net"]), (2.0, 1.46))
        self.assertEqual((r["value_twd"], r["lot"]), (205000.0, "1 board lot"))
        self.assertEqual((r["prev_close"], r["limit_down"], r["limit_up"]), (200.0, 180.0, 220.0))
        self.assertEqual(res["cash_after"], 294824.0)             # 500,000 less 205,000 less the 176 fee
        self.assertEqual(res["date"], TODAY)
        self.assertEqual(res["currency"], "TWD")
        self.assertIs(res["paper"], True)

    def test_two_board_lots_are_blocked_by_the_max_loss_only(self):
        # 2,000 shares: NT$6,000 at the stop + fees 351 and 346 + tax 606 = 7,303
        res = check.check([o2317(qty="2000")], cfg(max_order_twd=1000000, max_position_pct=100), now=at(NOW),
                          prev_closes=PREV)
        self.assertEqual(verdicts(res), ["BLOCK"])
        self.assertEqual(res["results"][0]["reasons"],
                         ["loss: 2,000 shares x 3.00 risk a share = NT$6,000, plus NT$1,303 fees and tax = NT$7,303 "
                          "at the stop, over your NT$5,000 max loss per trade"])

    def test_an_odd_lot_passes_with_a_warning(self):
        # 500 shares, no day trade for an odd lot: 1,500 at the stop + 88 + 87 fees + 303 tax
        # (101,000 x 0.3% normal sell tax) = 1,978
        res = check.check([o2317(qty="500")], cfg(), now=at(NOW), prev_closes=PREV)
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["max_loss"], r["lot"]), ("PASS", 1978.0, "odd lot of 500 shares"))
        self.assertIn("odd lot of 500 shares", warnings(res))
        self.assertIn("cannot be day traded", warnings(res))
        self.assertIn("OVERNIGHT position", warnings(res))
        self.assertIn("0.3 percent sell tax", warnings(res))

    def test_margin_day_trade_and_the_tax_cutoff(self):
        # 1,000 x 3.00 + fees 176 + 173 + tax 606 (202,000 x 0.3%) = 3,955
        res = check.check([o2317()], cfg(day_trade_mode="margin_daytrade"), now=at(NOW), prev_closes=PREV)
        self.assertEqual(res["results"][0]["max_loss"], 3955.0)
        # a cash day trade after 2027-12-31 pays 0.3 percent too (Tue 2028-01-04)
        res = check.check([o2317()], cfg(), now=at("2028-01-04 09:30"), prev_closes=PREV)
        self.assertEqual(res["results"][0]["max_loss"], 3955.0)
        res = check.check([o2317()], cfg(), now=at("2027-12-31 09:30"), prev_closes=PREV)
        self.assertEqual(res["results"][0]["max_loss"], 3652.0)

    def test_an_unknown_day_trade_mode_is_refused(self):
        with self.assertRaises(check.RiskError) as cm:
            check.check([o2317()], cfg(day_trade_mode="intraday"), now=at(NOW), prev_closes=PREV)
        self.assertIn("day_trade_mode", str(cm.exception))

    def test_fingerprint_is_shared_with_the_broker(self):
        o = o2317()
        self.assertEqual(check.fingerprint(o), ticket.fingerprint(o))
        self.assertEqual(check.fingerprint(dict(o, why="anything", plan={}, currency="TWD")), check.fingerprint(o))
        self.assertNotEqual(check.fingerprint(dict(o, qty="2000")), check.fingerprint(o))
        self.assertNotEqual(check.fingerprint(dict(o, stop_loss_stop_price="201.00")), check.fingerprint(o))
        self.assertEqual(check.ALPACA_FIELDS, ticket.ALPACA_FIELDS)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "state", "risk.json")
            none = os.path.join(d, "none")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main(["--orders", ORDERS_PATH, "--config", CFG_PATH, "--portfolio", none,
                                   "--prices", none, "--state", none, "--now", NOW, "--out", out])
            text = buf.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("PASS  #1 buy 2317.TW 1,000 shares (1 board lot), entry", text)
            self.assertIn("entry 205.00 (the plan's entry), stop 202.00, target 211.00: risk 3.00 a share", text)
            self.assertIn("max loss NT$3,652 (1,000 x 3.00 + NT$652 fees and tax) (limit NT$5,000), "
                          "reward:risk 1.46 after costs (2.00 before) (min 1)", text)
            self.assertIn("the TWSE has no bracket orders", text)
            self.assertNotIn("no previous close", text)
            self.assertIn("1 passed, 0 blocked at 2026-10-19 09:30 Taipei", text)
            self.assertIn("not financial advice", text)
            self.assertNotIn("$ ", text.replace("NT$", ""))
            with open(out) as fh:
                rec = json.load(fh)
            self.assertEqual(rec["date"], TODAY)
            self.assertEqual(rec["results"][0]["kind"], "entry")
            self.assertEqual(rec["results"][0]["fingerprint"], check.fingerprint(o2317()))


class LotsTicksAndLimits(unittest.TestCase):
    def one(self, order, now=NOW, **over):
        return check.check([order], cfg(**over), now=at(now), prev_closes=PREV)

    def test_quantities_are_board_lots_or_one_odd_lot(self):
        for q in ("1000", "3000", "500", "1", "999"):
            self.assertEqual(verdicts(self.one(o2317(qty=q), max_loss_per_trade_twd=100000, max_order_twd=10 ** 7,
                                               max_position_pct=100, cash_buffer_pct=0, min_order_twd=0,
                                               min_reward_risk=0, budget=10 ** 7)), ["PASS"], q)
        res = self.one(o2317(qty="1500"))
        self.assertIn("lot: 1,500 shares is not a valid order size", reasons(res))
        self.assertIn("never both", reasons(res))
        self.assertIn("lot: Taiwan orders are whole shares", reasons(self.one(o2317(qty="8.5"))))
        self.assertIn("qty must be a positive number", reasons(self.one(o2317(qty="0"))))
        self.assertIn("\"allow_odd_lots\" is false", reasons(self.one(o2317(qty="500"), allow_odd_lots=False)))
        self.assertEqual(verdicts(self.one(o2317(qty="3000"), allow_odd_lots=False, max_loss_per_trade_twd=10 ** 6,
                                           max_order_twd=10 ** 7, max_position_pct=100, budget=10 ** 7,
                                           min_reward_risk=0)), ["PASS"])

    def test_a_notional_order_is_refused(self):
        res = self.one(dict(o2317(qty=None), notional="205000"))
        self.assertIn("in shares (qty), not a notional amount", reasons(res))
        self.assertIn("give a qty", reasons(self.one(o2317(qty=None))))

    def test_prices_must_sit_on_the_tick_grid(self):
        res = self.one(o2317(take_profit_limit_price="211.20"))
        self.assertIn("tick: take_profit_limit_price 211.20 is not on the tick grid (ticks are 0.5 at this price); "
                      "nearest valid price 211.00", reasons(res))
        res = self.one(o2317(stop_loss_stop_price="201.80"))
        self.assertIn("tick: stop_loss_stop_price 201.80 is not on the tick grid", reasons(res))
        res = self.one(o2317(type="limit", limit_price="204.30"))
        self.assertIn("tick: limit_price 204.30", reasons(res))

    def test_prices_outside_the_daily_limits_are_blocked(self):
        res = self.one(o2317(take_profit_limit_price="225.00"))
        self.assertIn("limit: take_profit_limit_price 225.00 is outside today's price limits 180.00 to 220.00 "
                      "(previous close 200.00)", reasons(res))
        res = self.one(o2317(stop_loss_stop_price="175.00"), max_loss_per_trade_twd=10 ** 6)
        self.assertIn("limit: stop_loss_stop_price 175.00 is outside today's price limits", reasons(res))
        self.assertEqual(verdicts(self.one(o2317(take_profit_limit_price="220.00"))), ["PASS"])

    def test_without_a_previous_close_the_limit_check_is_skipped_and_says_so(self):
        o = o2317(take_profit_limit_price="225.00")
        o["plan"].pop("prev_close")
        res = check.check([o], cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("no previous close for 2317.TW: the +/-10% limit check was skipped", warnings(res))

    def test_the_previous_close_in_the_order_plan_is_enough_for_the_limit_check(self):
        res = check.check([o2317(take_profit_limit_price="225.00")], cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["BLOCK"])
        self.assertIn("limit: take_profit_limit_price 225.00 is outside today's price limits 180.00 to 220.00 "
                      "(previous close 200.00)", reasons(res))

    def test_the_plan_stop_is_range_checked_when_it_is_not_a_bracket_leg(self):
        o = o2317()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price"):
            o.pop(k)
        o["plan"] = {"entry": 205.0, "stop": 175.0, "target": 211.0}
        res = self.one(o, max_loss_per_trade_twd=10 ** 6)
        self.assertIn("limit: the plan stop 175.00 is outside today's price limits", reasons(res))

    def test_a_buy_at_limit_up_is_warned(self):
        o = o2317()
        o["plan"] = dict(o["plan"], entry=220.0, stop=216.0, target=220.0)
        o["stop_loss_stop_price"], o["take_profit_limit_price"] = "216.00", "220.00"
        res = self.one(o, min_reward_risk=0)
        self.assertIn("at limit-up 220.00", warnings(res))

    def test_symbols_must_be_four_digit_stocks_with_a_market(self):
        cases = [("AAPL", "not a Taiwan symbol"), ("BTC/USD", "not a Taiwan symbol"), ("0050.TW", "ETF"),
                 ("00679B.TWO", "ETF"), ("2317", "needs its market: 2317.TW (TWSE listed) or 2317.TWO (TPEx OTC)"),
                 ("23170.TW", "not a 4-digit common stock")]
        for sym, want in cases:
            res = check.check([plain(sym, 1000)], off(), prices={sym: 100.0}, now=at(NOW))
            self.assertEqual(verdicts(res), ["BLOCK"], sym)
            self.assertIn("asset: ", reasons(res))
            self.assertIn(want, reasons(res), sym)
        self.assertEqual(verdicts(check.check([plain("6488.TWO", 100)], off(), prices={"6488.TWO": 850.0},
                                              now=at(NOW))), ["PASS"])

    def test_order_types_and_after_hours(self):
        self.assertIn("orders do not exist on the TWSE", reasons(self.one(o2317(type="stop", stop_price="202.00"))))
        self.assertIn("unknown order type 'iceberg'", reasons(self.one(o2317(type="iceberg"))))
        self.assertIn("unknown time_in_force 'gtc'", reasons(self.one(o2317(time_in_force="gtc"))))
        self.assertIn("needs time_in_force day", reasons(self.one(o2317(time_in_force="ioc"))))
        lim = {"symbol": "2317.TW", "side": "buy", "qty": "1000", "type": "limit", "limit_price": "205.00",
               "time_in_force": "day", "extended_hours": True}
        self.assertIn("after-hours and extended-hours orders are not supported", reasons(self.one(lim)))
        nolimit = {"symbol": "2317.TW", "side": "buy", "qty": "1000", "type": "limit", "time_in_force": "day"}
        self.assertIn("needs a limit_price", reasons(self.one(nolimit)))
        self.assertEqual(verdicts(self.one(o2317(time_in_force="ioc", order_class=None, take_profit_limit_price=None,
                                                 stop_loss_stop_price=None, type="limit", limit_price="205.00"),
                                           require_stop=False, min_reward_risk=0)), ["PASS"])

    def test_bracket_format(self):
        o = o2317()
        o.pop("take_profit_limit_price")
        self.assertIn("needs both take_profit_limit_price and stop_loss_stop_price", reasons(self.one(o)))
        self.assertIn("needs a stop_loss_stop_price", reasons(self.one(dict(o2317(), stop_loss_stop_price=None,
                                                                            stop_loss_limit_price="201.00"))))
        self.assertIn("as a string", warnings(self.one(o2317(stop_loss_stop_price=202.0))))
        self.assertIn("as a string", warnings(self.one(o2317(qty=1000))))


class DayTradeChecks(unittest.TestCase):
    def one(self, order, now=NOW, **over):
        return check.check([order], cfg(**over), now=at(now), prev_closes=PREV)

    def test_a_stop_is_required(self):
        o = o2317()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price", "plan"):
            o.pop(k)
        o["plan"] = {"entry": 205.0}
        res = self.one(o)
        self.assertIn("stop: no stop", reasons(res))
        res = self.one(o, require_stop=False, min_reward_risk=0)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("no stop", warnings(res))

    def test_a_plan_stop_counts_but_warns(self):
        o = o2317()
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price"):
            o.pop(k)
        res = self.one(o)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("in the plan only", warnings(res))
        self.assertEqual(res["results"][0]["max_loss"], 3652.0)

    def test_stop_and_target_on_the_right_side(self):
        self.assertIn("must be below the entry 205.00", reasons(self.one(o2317(stop_loss_stop_price="206.00"))))
        res = self.one(o2317(take_profit_limit_price="204.00"))
        self.assertIn("target: the target 204.00 must be above the entry 205.00", reasons(res))

    def test_reward_risk_is_counted_after_costs(self):
        # target 208: 3,000 gross, less fees 176 + 178 and tax 312 = 2,334 net; 2,334 / 3,652 = 0.64
        res = self.one(o2317(take_profit_limit_price="208.00"))
        self.assertIn("reward:risk: 0.64 after costs (1.00 before; target 208.00, entry 205.00, stop 202.00) "
                      "is under your minimum 1", reasons(res))
        self.assertEqual(verdicts(self.one(o2317(take_profit_limit_price="208.00"), min_reward_risk=0.5)), ["PASS"])
        # gross 2.00 but net 1.46: a 1.5 minimum blocks it
        self.assertIn("reward:risk: 1.46 after costs (2.00 before", reasons(self.one(o2317(), min_reward_risk=1.5)))

    def test_a_fresh_higher_price_is_the_entry(self):
        later = at("2026-10-19 09:40")
        res = check.check([o2317()], cfg(), prices={"2317.TW": 207.3}, now=later, price_times={"2317.TW": QUOTE_TIME},
                          prev_closes=PREV)
        r = res["results"][0]
        self.assertEqual((r["entry_ref"], r["entry_ref_from"], r["risk_per_share"]), (207.3, "price", 5.3))
        self.assertIn("loss: 1,000 shares x 5.30 risk a share = NT$5,300, plus NT$654 fees and tax = NT$5,954",
                      reasons(res))

    def test_a_stale_or_future_price_is_not_used(self):
        for now in ("2026-10-19 11:30", "2026-10-19 09:20"):
            res = check.check([o2317()], cfg(), prices={"2317.TW": 207.3}, now=at(now),
                              price_times={"2317.TW": QUOTE_TIME}, prev_closes=PREV)
            self.assertEqual(verdicts(res), ["PASS"], now)
            self.assertEqual(res["results"][0]["entry_ref"], 205.0)
            self.assertIn("older than 15 minutes", warnings(res))

    def test_a_lower_price_does_not_shrink_the_risk(self):
        res = check.check([o2317()], cfg(), prices={"2317.TW": 200.0}, now=at(NOW), prev_closes=PREV)
        self.assertEqual(res["results"][0]["entry_ref"], 205.0)

    def test_a_limit_order_uses_its_limit_price(self):
        o = o2317(type="limit", limit_price="204.50")
        res = check.check([o], cfg(), prices={"2317.TW": 207.3}, now=at(NOW), prev_closes=PREV)
        r = res["results"][0]
        self.assertEqual((r["entry_ref"], r["max_loss"], r["costs_at_stop"], r["verdict"]),
                         (204.5, 3151.0, 651, "PASS"))

    def test_daily_loss_and_trades_per_day(self):
        two = {"orders": [placed("1101.TW"), placed("1102.TW")]}
        res = check.check([o2317()], cfg(), state=two, now=at(NOW), prev_closes=PREV)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertIn("today before this: 2 of 3 trades, NT$7,304 of NT$15,000 daily loss",
                      res["results"][0]["info"][-1])
        three = {"orders": [placed("1101.TW", max_loss=5000), placed("1102.TW", max_loss=5000),
                            placed("1103.TW", max_loss=5000)]}
        res = check.check([o2317()], cfg(), state=three, now=at(NOW), prev_closes=PREV)
        why = reasons(res)
        self.assertIn("trades: 3 entries placed today", why)
        self.assertIn("daily loss: NT$15,000 already at risk today plus NT$3,652 for this one = NT$18,652, "
                      "over your NT$15,000", why)
        yesterday = {"orders": [placed(s, day="2026-10-16") for s in ("1101.TW", "1102.TW", "1103.TW")]}
        self.assertEqual(verdicts(check.check([o2317()], cfg(), state=yesterday, now=at(NOW), prev_closes=PREV)),
                         ["PASS"])

    def test_exits_and_declines_do_not_count_as_trades(self):
        st = {"orders": [placed("1101.TW"), placed("1101.TW", side="sell", kind="exit", max_loss=None),
                         placed("1102.TW", status="declined"), placed("1103.TW", status="failed")]}
        res = check.check([o2317()], cfg(), state=st, now=at(NOW), prev_closes=PREV)
        self.assertEqual(verdicts(res), ["PASS"])
        self.assertEqual(res["today"]["entries_placed"], 1)

    def test_the_batch_counts_toward_the_daily_limits(self):
        # each: 1,000 x 4.50 = 4,500 + fees 43 + 39 + tax 69 = 4,651 at the stop
        orders = [bracket(s, 1000, 50.0, 45.5, 60.0) for s in ("1101.TW", "1102.TW", "1103.TW", "1104.TW")]
        res = check.check(orders, cfg(), now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS", "PASS", "BLOCK"])
        why = reasons(res, 3)
        self.assertIn("trades: 0 entries placed today plus 3 passed earlier", why)
        self.assertIn("daily loss: NT$13,953 already at risk today plus NT$4,651 for this one = NT$18,604", why)

    def test_entry_window_taipei_time(self):
        cases = [("2026-10-19 09:14", "no new entries before 09:15 Taipei (it is 09:14)"),
                 ("2026-10-19 13:01", "no new entries after 13:00 Taipei (it is 13:01)"),
                 ("2026-10-19 08:00", "the market is closed (Mon 2026-10-19 08:00"),
                 ("2026-10-19 13:35", "the market is closed"),
                 ("2026-10-17 10:15", "the market is closed today (weekend"),
                 ("2026-10-26 10:15", "the market is closed today (TWSE holiday: Taiwan Retrocession Day (observed)"),
                 ("2026-02-13 10:15", "the market is closed today (TWSE holiday: no trading before Lunar New Year"),
                 ("2026-11-02T01:10:00Z", "no new entries before 09:15 Taipei (it is 09:10)")]
        for now, want in cases:
            res = self.one(o2317(), now=now)
            self.assertIn("window: " + want, reasons(res), now)
        for now in ("2026-10-19 09:15", "2026-10-19 13:00", "2026-11-02T01:15:00Z", "2026-12-07 10:00"):
            self.assertEqual(verdicts(self.one(o2317(), now=now)), ["PASS"], now)
        res = self.one(o2317(), now="2026-10-17 10:15", no_entries_before=None, no_entries_after=None)
        self.assertEqual(verdicts(res), ["PASS"])
        with self.assertRaises(check.RiskError):
            self.one(o2317(), no_entries_before="9.15am")

    def test_a_cutoff_after_the_close_counts_as_the_close(self):
        self.assertEqual(verdicts(self.one(o2317(), now="2026-10-19 13:29", no_entries_after="14:30")), ["PASS"])
        self.assertIn("the market is closed", reasons(self.one(o2317(), now="2026-10-19 13:31", no_entries_after="14:30")))

    def test_there_is_no_early_close_and_flat_by_must_be_before_the_close(self):
        self.assertEqual(verdicts(self.one(o2317(), now="2026-12-24 13:00")), ["PASS"])
        with self.assertRaises(check.RiskError) as cm:
            self.one(o2317(), flat_by="13:30")
        self.assertIn("flat_by 13:30 is at or after the 13:30 close", str(cm.exception))
        self.assertEqual(verdicts(self.one(o2317(), flat_by="13:29")), ["PASS"])

    def test_the_holiday_list_covers_2026_and_says_so_for_other_years(self):
        res = self.one(o2317(), now="2027-01-04 10:15")
        self.assertIn("the holiday list covers 2026 only", " ".join(res["warnings"]))
        self.assertNotIn("holiday list", " ".join(self.one(o2317())["warnings"]))

    def test_the_window_uses_taipei_time_not_the_machine(self):
        self.assertEqual(check.to_taipei(at("2026-10-19 09:30")), datetime.datetime(2026, 10, 19, 9, 30))
        self.assertEqual(at("2026-10-19 09:30"), datetime.datetime(2026, 10, 19, 1, 30))
        self.assertEqual(at("2026-12-01 09:30"), datetime.datetime(2026, 12, 1, 1, 30))   # no daylight time

    def test_a_short_entry_when_allowed(self):
        # sell 1,000 at 205, stop buy-back 208, target 199: loss 3,000 + 662 = 3,662; gain 6,000 - 655 = 5,345
        short = {"symbol": "2317.TW", "side": "sell", "qty": "1000", "type": "market", "time_in_force": "day",
                 "order_class": "bracket", "take_profit_limit_price": "199.00", "stop_loss_stop_price": "208.00",
                 "plan": {"entry": 205.0}}
        res = self.one(short)
        self.assertIn("short: selling more 2317.TW than you hold", reasons(res))
        res = self.one(short, allow_short=True)
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["kind"], r["max_loss"], r["reward_risk"], r["reward_risk_net"]),
                         ("PASS", "entry", 3662.0, 2.0, 1.46))
        res = self.one(dict(short, stop_loss_stop_price="204.00"), allow_short=True)
        self.assertIn("must be above the entry 205.00 for a sell", reasons(res))


class Exits(unittest.TestCase):
    PF = {"cash": 294824.0, "positions": [{"ticker": "2317.TW", "shares": 1000,
                                           "lots": [{"date": TODAY, "shares": 1000, "cost": 205176.0}]}]}
    SELL = {"symbol": "2317.TW", "side": "sell", "qty": "1000", "type": "market", "time_in_force": "day"}

    def test_getting_out_is_never_blocked_by_the_day_limits(self):
        full = {"orders": [placed("2317.TW"), placed("1101.TW"), placed("1102.TW")] +
                          [placed("T%d" % i, max_loss=1) for i in range(6)] +
                          [placed("2317.TW", side="sell", kind="exit", max_loss=None)]}
        c = cfg(blocked=["2317.TW"], max_order_twd=100, max_daily_loss_twd=50)
        res = check.check([self.SELL], c, portfolio=self.PF, state=full, now=at("2026-10-19 13:25"))
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["kind"]), ("PASS", "exit"), r["reasons"])
        why = warnings(res)
        for word in ("blocked:", "duplicate:", "daily limit:"):
            self.assertIn("exit, not blocked: " + word, why)
        self.assertNotIn("price", why)
        res = check.check([self.SELL], cfg(), portfolio=self.PF, now=at("2026-10-17 12:00"))
        self.assertEqual(verdicts(res), ["PASS"])

    def test_a_partial_exit_and_the_rest(self):
        half = dict(self.SELL, qty="500")
        res = check.check([half, half], cfg(), portfolio=self.PF, prices={"2317.TW": 206.0}, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual([r["kind"] for r in res["results"]], ["exit", "exit"])
        self.assertIn("exit, not blocked: duplicate", warnings(res, 1))
        res = check.check([half, half, half], cfg(), portfolio=self.PF, prices={"2317.TW": 206.0}, now=at(NOW))
        self.assertEqual(verdicts(res), ["PASS", "PASS", "BLOCK"])
        self.assertIn("short:", reasons(res, 2))

    def test_a_sell_must_still_be_a_valid_lot(self):
        res = check.check([dict(self.SELL, qty="1500")], cfg(), portfolio=dict(self.PF, positions=[
            {"ticker": "2317.TW", "shares": 1500}]), now=at(NOW))
        self.assertIn("lot: 1,500 shares is not a valid order size", reasons(res))

    def test_format_asset_and_short_still_apply_to_a_sell(self):
        res = check.check([dict(self.SELL, type="limit")], cfg(), portfolio=self.PF, now=at(NOW))
        self.assertIn("needs a limit_price", reasons(res))
        res = check.check([dict(self.SELL, qty="2000")], cfg(), portfolio=self.PF, now=at(NOW))
        self.assertIn("short: selling more 2317.TW than you hold (1000 shares)", reasons(res))
        res = check.check([self.SELL], cfg(), now=at(NOW))
        self.assertIn("record the fill first", reasons(res))

    def test_buy_then_sell_in_one_batch(self):
        res = check.check([o2317(), self.SELL], cfg(), now=at(NOW), prev_closes=PREV)
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual(res["results"][1]["kind"], "exit")


class PlainChecks(unittest.TestCase):
    """Size, cash, position, blocked list and duplicates still hold (day-trade checks off)."""

    def one(self, order, prices=PRICES, **over):
        return check.check([order], off(**over), prices=prices, today=TODAY)["results"][0]

    def test_the_split_buys_on_a_fresh_500000_paper_account(self):
        # cash after four buys is NT$131,183; the fifth would leave 46,110, under the 10% buffer of 49,968.30
        with open(SPLIT_PATH) as fh:
            orders = json.load(fh)["orders"]
        res = check.check(orders, off(), prices=PRICES, today=TODAY)
        self.assertEqual(verdicts(res), ["PASS"] * 4 + ["BLOCK"])
        self.assertIn("cash: leaves NT$46,110 cash, under your 10% buffer of NT$49,968.30", reasons(res, 4))
        self.assertEqual(res["results"][0]["value_twd"], 100000)
        self.assertEqual(res["results"][0]["amount"], "100 shares")
        self.assertEqual(res["cash_after"], 131183.0)

    def test_max_and_min_order(self):
        self.assertIn("over your NT$400,000 max order",
                      " ".join(self.one(plain("2317.TW", 2000), max_position_pct=100)["reasons"]))
        self.assertIn("under your NT$1,000 minimum", " ".join(self.one(plain("2317.TW", 4))["reasons"]))

    def test_the_position_cap(self):
        r = self.one(plain("2317.TW", 2000), max_order_twd=10 ** 7, max_position_pct=50)
        self.assertIn("position: 2317.TW would be NT$410,000, 82.0% of the NT$500,000 account, over your 50% cap",
                      " ".join(r["reasons"]))

    def test_blocked_list(self):
        r = self.one(plain("2317.TW", 1000), blocked=["2317.TW"])
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertIn("blocked list", r["reasons"][0])

    def test_share_orders_need_a_price(self):
        r = self.one(plain("2330.TW", 1000), prices={})
        self.assertIn("no price for 2330.TW", " ".join(r["reasons"]))
        r = self.one(plain("2412.TW", 1000))
        self.assertEqual(r["verdict"], "PASS")
        self.assertAlmostEqual(r["value_twd"], 120000.0)

    def test_margin(self):
        r = check.check([plain("2317.TW", 1000)], off(cash_buffer_pct=0, max_position_pct=100),
                        portfolio={"cash": 100000, "positions": []}, prices=PRICES, today=TODAY)["results"][0]
        self.assertIn("margin", " ".join(r["reasons"]))
        self.assertIn("NT$205,176 (NT$205,000 plus a NT$176 fee)", " ".join(r["reasons"]))

    PF = {"cash": 100000.0, "positions": [{"ticker": "2317.TW", "shares": 1000,
                                           "lots": [{"date": "2026-10-13", "shares": 1000, "cost": 200000.0}]}]}

    def test_a_sell_frees_cash_for_a_later_buy(self):
        # selling 500 at 205 credits 102,500 less the 88 fee and 308 tax at 0.3% = 102,104
        c = off(max_position_pct=100, cash_buffer_pct=0, max_order_twd=10 ** 7)
        sell = {"symbol": "2317.TW", "side": "sell", "qty": "500", "type": "market", "time_in_force": "day"}
        res = check.check([sell, plain("2412.TW", 1000)], c, portfolio=self.PF, prices=PRICES, today=TODAY)
        self.assertEqual(verdicts(res), ["PASS", "PASS"])
        self.assertEqual(res["cash_after"], 82001.0)
        res = check.check([plain("2412.TW", 1000)], c, portfolio=self.PF, prices=PRICES, today=TODAY)
        self.assertEqual(verdicts(res), ["BLOCK"])

    def test_daily_limit_and_already_placed_today(self):
        st = {"orders": [{"symbol": "T%d" % i, "side": "buy", "status": "placed", "at": TODAY + "T10:00:00"}
                         for i in range(10)]}
        res = check.check([plain("2412.TW", 1000)], off(), prices=PRICES, state=st, today=TODAY)
        self.assertIn("daily limit", reasons(res))
        res = check.check([plain("2412.TW", 1000)], off(), prices=PRICES, state=st, today="2026-10-20")
        self.assertEqual(verdicts(res), ["PASS"])
        ko = {"orders": [{"symbol": "2412.TW", "side": "buy", "status": "placed", "at": TODAY + "T10:00:00"}]}
        res = check.check([plain("2412.TW", 1000)], off(), prices=PRICES, state=ko, today=TODAY)
        self.assertIn("already placed today", reasons(res))
        declined = {"orders": [{"symbol": "2412.TW", "side": "buy", "status": "declined", "at": TODAY + "T10:00:00"}]}
        self.assertEqual(verdicts(check.check([plain("2412.TW", 1000)], off(), prices=PRICES, state=declined,
                                              today=TODAY)), ["PASS"])

    def test_live_account_warns(self):
        res = check.check([plain("2412.TW", 1000)], off(paper=False), prices=PRICES, today=TODAY)
        self.assertIn("LIVE", res["warnings"][0])

    def test_format_rules(self):
        bad = {"symbol": "2317.TW", "side": "hold", "qty": "1000"}
        self.assertIn("side must be buy or sell", " ".join(self.one(bad)["reasons"]))


class Cli(unittest.TestCase):
    def test_prices_file_freshness_and_previous_close(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump({"as_of": "2026-10-19T01:35:00Z", "prices": {"2317.TW": 207.3},
                           "detail": {"2317.TW": {"time": "2026-10-19T01:28:13Z", "fetched": "2026-10-19T01:35:00Z",
                                                  "prev_close": 200.0}}}, fh)
            none = os.path.join(d, "none")
            base = ["--orders", ORDERS_PATH, "--config", CFG_PATH, "--portfolio", none, "--prices", pp,
                    "--state", none, "--no-write"]
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(check.main(base + ["--now", "2026-10-19 09:40"]), 1)
            self.assertIn("1,000 shares x 5.30 risk a share = NT$5,300, plus NT$654 fees and tax = NT$5,954",
                          buf.getvalue())
            self.assertNotIn("no previous close", buf.getvalue())      # detail.prev_close was read
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(check.main(base + ["--now", "2026-10-19 11:30"]), 0)      # the quote is stale
            self.assertIn("older than 15 minutes", buf.getvalue())

    def test_the_split_orders_with_a_plain_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump(off(), fh)
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump({"prices": PRICES}, fh)
            none = os.path.join(d, "none")
            out = os.path.join(d, "state", "risk.json")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = check.main(["--orders", SPLIT_PATH, "--config", c, "--portfolio", none, "--prices", pp,
                                   "--state", none, "--today", TODAY, "--out", out])
            self.assertEqual(code, 1)
            self.assertIn("4 passed, 1 blocked", buf.getvalue())
            with open(out) as fh:
                rec = json.load(fh)
            self.assertEqual(rec["date"], TODAY)
            self.assertTrue(all(len(r["fingerprint"]) == 16 for r in rec["results"]))

    def test_errors_are_one_line(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", "/nonexistent.json", "--no-write"]), 1)
        self.assertIn("no orders file", err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", ORDERS_PATH, "--now", "noon", "--no-write"]), 1)
        self.assertIn("--now wants a Taipei time", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(check.main(["--orders", ORDERS_PATH, "--today", "monday", "--no-write"]), 1)
        self.assertIn("--today wants", err.getvalue())


if __name__ == "__main__":
    unittest.main()
