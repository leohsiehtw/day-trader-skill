import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

size = load("trader-budget", "size")

CFG = os.path.join(ROOT, "trader-budget", "config.example.json")
PLAN = os.path.join(FIX, "trader-budget", "plan-2317.json")
TARGETS = os.path.join(ROOT, "trader-budget", "targets.example.json")
NOW = "2026-10-19 09:30"          # Taipei
TODAY = "2026-10-19"
# Synthetic prices for weights mode (not real quotes)
PRICES = {"2330.TW": 1000.0, "2317.TW": 205.0, "2454.TW": 1200.0, "2412.TW": 120.0, "2882.TW": 70.0}
CONFIG_KEYS = {
    "budget", "cash_buffer_pct", "max_position_pct", "max_order_twd", "min_order_twd", "max_loss_per_trade_twd",
    "max_daily_loss_twd", "max_trades_per_day", "max_orders_per_day", "min_reward_risk", "require_stop",
    "no_entries_before", "no_entries_after", "flat_by", "allow_odd_lots", "fee_discount", "min_fee_twd",
    "day_trade_sell_tax_pct", "sell_tax_pct", "day_trade_sell_tax_note", "day_trade_mode",
    "day_trade_tax_halved_until", "broker", "paper", "blocked",
    "allow_options", "allow_margin", "allow_short", "sec_user_agent",
}


def cfg(**over):
    with open(CFG) as fh:
        c = json.load(fh)
    c.update(over)
    return c


def plan(**over):
    with open(PLAN) as fh:
        p = json.load(fh)
    p.update(over)
    return p


def rows(path):
    with open(path) as fh:
        return size.parse_weights(json.load(fh))


def dollars(result):
    return {p["ticker"]: p["dollars"] for p in result["positions"]}


def shares(result):
    return {p["ticker"]: p["shares"] for p in result["positions"]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = size.main(argv)
    return code, out.getvalue(), err.getvalue()


def prices_doc(price, quote_time="2026-10-19T01:28:13Z", prev_close=200.0):
    return {"as_of": quote_time, "source": "synthetic", "prices": {"2317.TW": price},
            "detail": {"2317.TW": {"prev_close": prev_close, "time": quote_time, "source": "synthetic"}}}


class ThePlan(unittest.TestCase):
    """Synthetic day: 2317.TW, previous close 200.00, entry 205.00, stop 202.00, target 211.00.
    NT$500,000 budget, 10% buffer, NT$5,000 max loss. Costs: fee 0.1425% x 0.6, min 20; sell tax 0.15%."""

    def test_config_example_keys_and_taiwan_defaults(self):
        with open(CFG) as fh:
            c = json.load(fh)
        self.assertEqual(set(c), CONFIG_KEYS)
        self.assertEqual((c["budget"], c["max_loss_per_trade_twd"], c["max_daily_loss_twd"]), (500000, 5000, 15000))
        self.assertEqual((c["no_entries_before"], c["no_entries_after"], c["flat_by"]), ("09:15", "13:00", "13:20"))
        self.assertEqual((c["fee_discount"], c["min_fee_twd"], c["day_trade_sell_tax_pct"], c["sell_tax_pct"]),
                         (0.6, 20, 0.15, 0.3))
        self.assertEqual((c["day_trade_mode"], c["day_trade_tax_halved_until"]), ("cash_daytrade", "2027-12-31"))

    def test_2317_is_one_board_lot_bound_by_the_max_loss(self):
        s = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertEqual(s["qty"], 1000)
        self.assertEqual(s["bound_by"], "max loss")
        self.assertEqual(s["risk_per_share"], 3.0)
        self.assertEqual(s["cost"], 205000.0)
        self.assertEqual(s["costs"], {"buy_fee": 176, "sell_fee": 173, "tax": 303, "total": 652})
        self.assertEqual(s["costs_at_stop"], 652)
        self.assertEqual(s["max_loss"], 3652.0)
        self.assertEqual(s["reward_risk"], 2.0)
        self.assertEqual(s["reward_risk_net"], 1.46)
        self.assertEqual(s["reward_net"], 5326)
        self.assertEqual(s["cash_buffer"], 50000)
        self.assertEqual([(l["name"], l["raw"], l["shares"]) for l in s["limits"]],
                         [("max loss", 1369, 1000), ("position cap", 1829, 1000), ("max order", 1951, 1000),
                          ("cash", 2193, 2000)])
        self.assertEqual([l["name"] for l in s["limits"] if l["binds"]], ["max loss"])
        self.assertEqual((s["limit_down"], s["limit_up"], s["currency"]), (180.0, 220.0, "TWD"))
        self.assertEqual(s["warnings"], [])
        self.assertIsNone(s["refusal"])

    def test_the_order(self):
        o = size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY))
        why = o.pop("why")
        self.assertEqual(o, {
            "symbol": "2317.TW", "side": "buy", "qty": "1000", "type": "market", "time_in_force": "day",
            "order_class": "bracket", "take_profit_limit_price": "211.00", "stop_loss_stop_price": "202.00",
            "currency": "TWD",
            "plan": {"entry": 205.0, "stop": 202.0, "target": 211.0, "risk_per_share": 3.0, "max_loss": 3652.0,
                     "costs_at_stop": 652, "reward_risk_net": 1.46, "prev_close": 200.0,
                     "limit_down": 180.0, "limit_up": 220.0, "setup": "orb", "entry_time": "9:30 AM",
                     "flat_by": "13:20"}})
        self.assertIn("bound by your NT$5,000 max loss", why)
        self.assertIn("NT$3,652", why)

    def test_the_fixture_orders_file_is_what_it_writes(self):
        with open(os.path.join(FIX, "trader-risk", "orders-2317.json")) as fh:
            fixture = json.load(fh)["orders"][0]
        self.assertEqual(size.bracket_order(size.size_trade(plan(), cfg(), today=TODAY)), fixture)

    def test_a_limit_order_must_sit_on_the_tick_grid(self):
        # worked out separately: 1,586 shares fit the loss cap at 204.50, floor to 1 board lot
        s = size.size_trade(plan(), cfg(), limit=204.5, today=TODAY)
        self.assertEqual((s["qty"], s["risk_per_share"], s["max_loss"], s["costs_at_stop"]), (1000, 2.5, 3151.0, 651))
        o = size.bracket_order(s)
        self.assertEqual((o["type"], o["limit_price"], o["qty"]), ("limit", "204.50", "1000"))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), limit=204.3, today=TODAY)
        self.assertIn("not on the tick grid", str(e.exception))
        self.assertIn("204.50", str(e.exception))

    def test_cli_writes_one_order(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("Size: 1,000 shares (1 board lot) of 2317.TW = NT$205,000 at 205.00.", text)
            self.assertIn("1,000 x 3.00 = NT$3,000 + NT$652 fees and tax = NT$3,652", text)
            self.assertIn("<- binds", text)
            self.assertIn("no bracket orders", text)
            self.assertIn("Flat by 13:20 Taipei", text)
            self.assertIn("not financial advice", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual(doc["status"], "proposed")
            self.assertIs(doc["paper"], True)
            self.assertEqual(doc["created_at"], "2026-10-19T01:30:00Z")   # 09:30 Taipei
            self.assertEqual(len(doc["orders"]), 1)
            self.assertEqual(doc["orders"][0]["plan"]["max_loss"], 3652.0)

    def test_cli_json_and_limit(self):
        code, text, _ = run(["--plan", PLAN, "--config", CFG, "--portfolio", "/nonexistent", "--now", NOW,
                             "--limit", "--json"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual(out["sizing"]["qty"], 1000)
        self.assertEqual(out["orders"][0]["limit_price"], "205.00")


class PlanRules(unittest.TestCase):
    def test_zero_shares_is_a_plain_refusal(self):
        s = size.size_trade(plan(), cfg(max_loss_per_trade_twd=40), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("more than your NT$40 max loss per trade", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump(cfg(max_loss_per_trade_twd=40), fh)
            out = os.path.join(d, "orders.json")
            code, text, _ = run(["--plan", PLAN, "--config", c, "--portfolio", os.path.join(d, "none"),
                                 "--now", NOW, "--write", out])
            self.assertEqual(code, 1)
            self.assertIn("No order:", text)
            self.assertFalse(os.path.exists(out))

    def test_a_wide_stop_gives_one_odd_lot(self):
        # stop 190: 319 shares keep the loss at NT$4,984 (worked out separately), so one odd lot, no board lot
        s = size.size_trade(plan(stop=190.0, target=220.0), cfg(min_reward_risk=0), today=TODAY)
        self.assertEqual((s["qty"], s["bound_by"], s["max_loss"]), (319, "max loss", 4984.0))
        self.assertEqual(s["limits"][0]["raw"], 319)
        self.assertTrue(any("odd lot" in w for w in s["warnings"]))
        self.assertEqual(size.bracket_order(s)["qty"], "319")
        self.assertIn("odd lot of 319 shares", size.plan_report(s, size.bracket_order(s)))
        odd = [w for w in s["warnings"] if "odd lot" in w][0]
        self.assertIn("cannot be day traded", odd)
        self.assertIn("OVERNIGHT position", odd)
        self.assertIn("0.3 percent sell tax", odd)

    def test_margin_mode_and_the_tax_cutoff(self):
        # 1,000 x 3.00 + fees 176 + 173 + tax 606 (202,000 x 0.3%) = 3,955
        s = size.size_trade(plan(), cfg(day_trade_mode="margin_daytrade"), today=TODAY)
        self.assertEqual((s["qty"], s["max_loss"], s["costs"]["tax"]), (1000, 3955.0, 606))
        self.assertEqual(s["limits"][0]["raw"], 1264)
        s = size.size_trade(plan(date="2028-01-04"), cfg(), today="2028-01-04")
        self.assertEqual((s["max_loss"], s["costs"]["tax"]), (3955.0, 606))
        self.assertIn("ended 2027-12-31", size.plan_report(s, size.bracket_order(s)))
        s = size.size_trade(plan(), cfg(), today=TODAY)
        self.assertIn("0.15% cash day-trade sell tax (halved through 2027-12-31)",
                      size.plan_report(s, size.bracket_order(s)))
        with self.assertRaises(size.SizeError) as cm:
            size.size_trade(plan(), cfg(day_trade_mode="daytrade"), today=TODAY)
        self.assertIn("day_trade_mode", str(cm.exception))

    def test_the_report_reminds_that_eligibility_is_unchecked(self):
        s = size.size_trade(plan(), cfg(), today=TODAY)
        text = size.plan_report(s, size.bracket_order(s))
        self.assertEqual(text.count("Not checked: whether your account may day trade"), 1)
        self.assertIn("TWSE daily day-trade list", text)
        s = size.size_trade(plan(stop=190.0, target=220.0), cfg(allow_odd_lots=False, min_reward_risk=0), today=TODAY)
        self.assertIn("Not checked: whether your account may day trade", size.plan_report(s, None))

    def test_odd_lots_off_needs_a_whole_board_lot(self):
        s = size.size_trade(plan(stop=190.0, target=220.0), cfg(allow_odd_lots=False, min_reward_risk=0), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("allow_odd_lots", s["refusal"])
        self.assertIsNone(size.bracket_order(s))

    def test_each_limit_can_bind(self):
        s = size.size_trade(plan(), cfg(max_order_twd=100000), today=TODAY)       # 100000 / 205 = 487
        self.assertEqual((s["qty"], s["bound_by"]), (487, "max order"))
        s = size.size_trade(plan(), cfg(max_position_pct=20), today=TODAY)         # 100000 / 205 = 487
        self.assertEqual((s["qty"], s["bound_by"]), (487, "position cap"))
        s = size.size_trade(plan(), cfg(), cash=200000, today=TODAY)               # 150000 after buffer: 731 shares
        self.assertEqual((s["qty"], s["bound_by"], s["cash_available"]), (731, "cash", 150000))
        s = size.size_trade(plan(), cfg(max_loss_per_trade_twd=10000), today=TODAY)
        self.assertEqual(s["bound_by"], "position cap")                            # 1,829 raw beats 2,7xx loss raw
        self.assertEqual(s["qty"], 1000)

    def test_a_fresh_higher_price_means_a_bigger_risk(self):
        # 207.30: risk 5.30; 839 shares keep the loss at NT$4,996; net reward 2,537 -> net 0.51 (worked out separately)
        s = size.size_trade(plan(), cfg(min_reward_risk=0), price=207.3, today=TODAY)
        self.assertEqual((s["entry"], s["entry_from"], s["risk_per_share"]), (207.3, "price", 5.3))
        self.assertEqual((s["qty"], s["max_loss"], s["reward_risk"], s["reward_risk_net"]), (839, 4996.0, 0.7, 0.51))
        self.assertIsNone(s["refusal"])
        s = size.size_trade(plan(), cfg(), price=207.3, today=TODAY)
        self.assertIn("net reward:risk 0.51 (gross 0.70", s["refusal"])
        self.assertIn("is under your minimum 1", s["refusal"])
        self.assertIsNone(size.bracket_order(s))
        lower = size.size_trade(plan(), cfg(), price=203.0, today=TODAY)
        self.assertEqual((lower["entry"], lower["qty"]), (205.0, 1000))

    def test_the_min_reward_risk_uses_the_net_numbers(self):
        # gross 2.00 but net 1.46: a 1.5 minimum refuses it
        s = size.size_trade(plan(), cfg(min_reward_risk=1.5), today=TODAY)
        self.assertIn("net reward:risk 1.46 (gross 2.00", s["refusal"])
        self.assertIsNone(size.size_trade(plan(), cfg(min_reward_risk=1.4), today=TODAY)["refusal"])

    def test_prices_file_is_used_only_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump(prices_doc(207.3), fh)
            c = os.path.join(d, "config.json")
            with open(c, "w") as fh:
                json.dump(cfg(min_reward_risk=0), fh)
            base = ["--plan", PLAN, "--config", c, "--portfolio", os.path.join(d, "none"), "--prices", pp, "--json"]
            out = json.loads(run(base + ["--now", "2026-10-19 09:40"])[1])        # 12 minutes after the quote
            self.assertEqual(out["sizing"]["qty"], 839)
            self.assertIn("above the plan's entry", out["notes"][0])
            self.assertIn("Taipei", out["notes"][0])
            out = json.loads(run(base + ["--now", "2026-10-19 11:30"])[1])
            self.assertEqual(out["sizing"]["qty"], 1000)
            self.assertIn("not used", out["notes"][0])

    def test_the_portfolio_cash_caps_the_size(self):
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "portfolio.json")
            with open(pf, "w") as fh:
                json.dump({"cash": 200000, "positions": []}, fh)
            out = json.loads(run(["--plan", PLAN, "--config", CFG, "--portfolio", pf, "--now", NOW, "--json"])[1])
            self.assertEqual((out["sizing"]["qty"], out["sizing"]["bound_by"]), (731, "cash"))

    def test_bad_plans(self):
        for p, word in ((plan(stop=205.5), "not below the entry"),
                        (plan(target=204.0), "already happened"),
                        (plan(target=None), "positive target"),
                        (plan(side="sell"), "long (buy) day trades only"),
                        (plan(symbol=""), "no symbol"),
                        (plan(stop=202.3), "stop 202.30 is not on the tick grid"),
                        (plan(target=211.2), "target 211.20 is not on the tick grid"),
                        (plan(symbol="0050.TW"), "ETF"),
                        (plan(symbol="2317"), "not a Taiwan symbol")):
            with self.assertRaises(size.SizeError) as e:
                size.size_trade(p, cfg(), today=TODAY)
            self.assertIn(word, str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), price=212.0, today=TODAY)
        self.assertIn("already happened", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(blocked=["2317.tw"]), today=TODAY)
        self.assertIn("blocked list", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(), cfg(), today="2026-10-20")
        self.assertIn("make a new plan", str(e.exception))
        self.assertIn("in Taipei", str(e.exception))

    def test_price_limits(self):
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(target=225.0), cfg(), today=TODAY)
        self.assertIn("above today's limit-up 220.00", str(e.exception))
        with self.assertRaises(size.SizeError) as e:
            size.size_trade(plan(entry=185.0, stop=179.5, target=190.0), cfg(), today=TODAY)
        self.assertIn("below today's limit-down 180.00", str(e.exception))
        s = size.size_trade(plan(target=220.0), cfg(), today=TODAY)           # exactly limit-up is allowed
        self.assertEqual(s["target"], 220.0)

    def test_no_previous_close_is_a_warning_not_a_guess(self):
        p = plan()
        for k in ("prev_close", "limit_up", "limit_down"):
            del p[k]
        s = size.size_trade(p, cfg(), today=TODAY)
        self.assertEqual(s["qty"], 1000)
        self.assertIsNone(s["limit_up"])
        self.assertIn("no previous close for 2317.TW: the +/-10% limit check was skipped", s["warnings"])
        self.assertEqual(size.size_trade(p, cfg(), today=TODAY, prev_close=200.0)["limit_up"], 220.0)

    def test_under_the_minimum_order(self):
        s = size.size_trade(plan(), cfg(min_order_twd=300000), today=TODAY)
        self.assertEqual(s["qty"], 1000)
        self.assertIn("under your NT$300,000 minimum order", s["refusal"])
        self.assertIsNone(size.bracket_order(s))

    def test_missing_plan_and_weights_only_flags(self):
        code, _, err = run(["--plan", "/nonexistent/plan.json", "--config", CFG, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("no plan", err)
        code, _, err = run(["--plan", PLAN, "--config", CFG, "--now", NOW, "--top", "2"])
        self.assertEqual(code, 1)
        self.assertIn("--weights", err)
        code, _, err = run(["--plan", PLAN, "--config", CFG, "--now", "tomorrow"])
        self.assertEqual(code, 1)
        self.assertIn("Taipei time", err)
        self.assertNotIn("Traceback", err)


class WeightsMode(unittest.TestCase):
    """NT$500,000, 10% cash, so NT$450,000 to invest. Weights 40/25/15/10/10, synthetic prices."""

    def test_split_into_lots_with_no_top_up(self):
        # slices 180000 / 112500 / 67500 / 45000 / 45000 -> floor(slice / price) shares (worked out separately)
        r = size.size(rows(TARGETS), cfg(), prices=PRICES)
        self.assertEqual(shares(r), {"2330.TW": 180, "2317.TW": 548, "2454.TW": 56, "2412.TW": 375, "2882.TW": 642})
        self.assertEqual(dollars(r), {"2330.TW": 180000, "2317.TW": 112340, "2454.TW": 67200,
                                      "2412.TW": 45000, "2882.TW": 44940})
        self.assertEqual((r["cash_buffer"], r["invested"], r["idle"], r["cap"]), (50000, 449480, 520, 375000))
        self.assertEqual(r["currency"], "TWD")

    def test_the_cap_shares_the_excess_out(self):
        # cap 30% = 150000: 2330 pinned at 150000, the other 300000 split 25:15:10:10 (worked out separately)
        r = size.size(rows(TARGETS), cfg(max_position_pct=30), prices=PRICES)
        self.assertEqual(shares(r), {"2330.TW": 150, "2317.TW": 609, "2454.TW": 62, "2412.TW": 416, "2882.TW": 714})
        self.assertEqual([p["ticker"] for p in r["positions"] if p["capped"]], ["2330.TW"])
        self.assertEqual(r["invested"], 449145)

    def test_board_lots_only_when_odd_lots_are_off(self):
        # NT$5,000,000: 2454 cannot buy a lot of 1,000 at 1,200 inside its slice, so it is dropped and the
        # rest is renormalised (worked out separately)
        r = size.size(rows(TARGETS), cfg(budget=5000000, max_order_twd=4000000, allow_odd_lots=False),
                      prices=PRICES)
        self.assertEqual(shares(r), {"2330.TW": 2000, "2317.TW": 6000, "2412.TW": 4000, "2882.TW": 7000})
        self.assertEqual([d["ticker"] for d in r["dropped"]], ["2454.TW"])
        self.assertIn("board lot", r["dropped"][0]["reason"])
        self.assertEqual(r["invested"], 4200000)

    def test_weights_are_renormalised(self):
        r = size.size(size.parse_weights({"2330.TW": 2, "2317.TW": 2}), cfg(max_position_pct=100), prices=PRICES)
        self.assertEqual({p["ticker"]: p["weight"] for p in r["positions"]}, {"2330.TW": 50.0, "2317.TW": 50.0})

    def test_inline_weights_and_top_n(self):
        w = size.parse_weights(size.weights_from_arg("2330.TW=40,2317.TW=25,2454.TW=15"))
        r = size.size(w, cfg(max_position_pct=100), prices=PRICES, top=2)
        self.assertEqual(sorted(shares(r)), ["2317.TW", "2330.TW"])

    def test_orders_are_whole_share_place_stock_order_shaped(self):
        r = size.size(rows(TARGETS), cfg(max_position_pct=30), prices=PRICES)
        orders = size.orders_from(r, "example weights")
        self.assertEqual(orders[0], {"symbol": "2330.TW", "side": "buy", "qty": "150", "type": "market",
                                     "time_in_force": "day", "currency": "TWD", "why": orders[0]["why"]})
        self.assertIn("capped at 30%", orders[0]["why"])
        for o in orders:
            self.assertIsInstance(o["qty"], str)
            self.assertNotIn("notional", o)
        self.assertEqual([o["qty"] for o in orders], ["150", "609", "62", "416", "714"])

    def test_blocked_tickers_are_dropped_first(self):
        r = size.size(rows(TARGETS), cfg(blocked=["2412.tw"]), prices=PRICES)
        self.assertNotIn("2412.TW", dollars(r))
        self.assertIn("blocked", r["dropped"][0]["reason"])

    def test_slices_under_the_minimum_are_dropped(self):
        r = size.size(rows(TARGETS), cfg(min_order_twd=60000), prices=PRICES)
        self.assertNotIn("2412.TW", dollars(r))
        self.assertNotIn("2882.TW", dollars(r))
        self.assertTrue(all(v >= 60000 for v in dollars(r).values()))
        self.assertIn("minimum order", r["dropped"][0]["reason"])

    def test_errors(self):
        with self.assertRaises(size.SizeError) as e:
            size.size(rows(TARGETS), cfg())
        self.assertIn("needs a price", str(e.exception))
        with self.assertRaises(size.SizeError):
            size.size(rows(TARGETS), cfg(budget=None), prices=PRICES)
        with self.assertRaises(size.SizeError) as e:
            size.size(size.parse_weights({"0050.TW": 1}), cfg(), prices={"0050.TW": 90.0})
        self.assertIn("ETF", str(e.exception))
        with self.assertRaises(size.SizeError):
            size.size([{"ticker": "2412.TW", "name": "", "weight": 1}, {"ticker": "2412.TW", "name": "", "weight": 2}],
                      cfg(), prices=PRICES)

    def test_report_names_the_lots(self):
        r = size.size(rows(TARGETS), cfg(), prices=PRICES)
        text = size.report(r, size.orders_from(r))
        self.assertIn("NT$449,480", text)
        self.assertIn("odd lot", text)
        self.assertIn("fees and tax come on top", text)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, "prices.json")
            with open(pp, "w") as fh:
                json.dump({"prices": PRICES}, fh)
            out = os.path.join(d, "trader", "orders.json")
            code, text, _ = run(["--targets", TARGETS, "--config", CFG, "--prices", pp, "--write", out])
            self.assertEqual(code, 0)
            self.assertIn("left idle", text)
            self.assertIn("require_stop", text)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual([o["symbol"] for o in doc["orders"]], ["2330.TW", "2317.TW", "2454.TW", "2412.TW", "2882.TW"])
            code, text, _ = run(["--targets", TARGETS, "--config", CFG, "--prices", pp, "--json"])
            self.assertEqual(json.loads(text)["result"]["idle"], 520)
            code, _, err = run(["--targets", "/nonexistent/targets.json", "--config", CFG])
            self.assertEqual(code, 1)
            self.assertIn("no weights file", err)


if __name__ == "__main__":
    unittest.main()
