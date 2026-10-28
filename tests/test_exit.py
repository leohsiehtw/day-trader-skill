"""trader-exit tests. Bars for the ATR stop reuse tests/fixtures/trader-entry/
(the SYNTHETIC 2317.TW session of 2026-10-19, see test_entry.py)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal

from _load import load, FIX, ROOT

exitp = load("trader-exit", "exit")
entry = load("trader-entry", "entry")

S2317 = os.path.join(FIX, "trader-entry", "2317.TW-2026-10-19-5m-synthetic.json")

# trader/plan.json for the synthetic session, exactly as the contract writes it
PLAN_2317 = {"created_by": "trader-exit", "symbol": "2317.TW", "side": "buy", "date": "2026-10-19", "setup": "orb",
             "entry": 205.0, "entry_time": "9:30 AM", "entry_bar": 5, "interval": "5m",
             "opening_range": {"high": 204.0, "low": 200.5, "minutes": 15},
             "stop": 202.0, "stop_rule": "or_mid", "stop_label": "opening-range midpoint",
             "target": 211.0, "target_r": 2.0, "target_label": "2R (two times the risk)",
             "risk_per_share": 3.0, "reward_risk": 2.0, "flat_by": "13:20",
             "prev_close": 200.0, "limit_up": 220.0, "limit_down": 180.0, "currency": "TWD"}
ENTRY_2317 = {"created_by": "trader-entry", "symbol": "2317.TW", "setup": "orb", "side": "buy", "date": "2026-10-19",
              "status": "triggered", "time": "9:30 AM", "bar_start": "09:25", "bar_index": 5, "price": 205.0,
              "level": 204.0, "interval": "5m", "opening_range": {"high": 204.0, "low": 200.5, "minutes": 15},
              "prev_close": 200.0, "source": "yahoo", "checked_at": "2026-10-19T01:30:00Z"}


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


def c(entry_px, stop, target="2R", oh=204.0, ol=200.5, atr=None, n=None, prev=None):
    sr, sp = exitp.parse_stop(stop)
    tr, tp = exitp.parse_target(target)
    return exitp.compute(entry_px, sr, sp, tr, tp, oh, ol, atr, n, prev)


class Math(unittest.TestCase):
    def test_or_mid_snaps_down_to_the_tick(self):
        p = c(205, "or-mid", "1R")
        self.assertEqual(p["stop"], Decimal("202.00"))           # (204 + 200.5) / 2 = 202.25, tick 0.5
        self.assertEqual(p["risk"], Decimal("3.00"))
        self.assertEqual(p["target"], Decimal("208.00"))
        self.assertEqual(p["reward_risk"], Decimal("1.00"))
        self.assertEqual(p["target_label"], "1R (one times the risk)")
        self.assertIn("rounded down to the tick", p["stop_detail"])

    def test_the_default_2r(self):
        p = c(205, "or-mid")
        self.assertEqual(p["target"], Decimal("211.00"))
        self.assertEqual(p["target_label"], "2R (two times the risk)")

    def test_raw_yahoo_floats_land_on_the_same_ticks(self):
        p = c(204.99999237060547, "or-mid", "2R", 204.00001525878906, 200.5)
        self.assertEqual((p["entry"], p["stop"], p["target"]), (Decimal("205.00"), Decimal("202.00"), Decimal("211.00")))

    def test_other_stops(self):
        p = c(205, "or-low")
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("200.50"), Decimal("4.50"), Decimal("214.00")))
        p = c(205, "price:202.3")
        self.assertEqual(p["stop"], Decimal("202.00"))              # rounds away from the entry
        p = c(205, "pct:1")
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("202.50"), Decimal("2.50"), Decimal("210.00")))
        p = c(205, "atr:1.5", atr=2.25, n=6)
        self.assertEqual(p["stop"], Decimal("201.50"))              # 205 - 3.375 = 201.625, tick 0.5
        self.assertEqual((p["risk"], p["target"]), (Decimal("3.50"), Decimal("212.00")))
        self.assertEqual(p["stop_label"], "1.5 x ATR(6) under the entry")
        # a cheaper stock has a finer grid: 48 less 2% = 47.04, tick 0.05
        p = c(48, "pct:2", oh=None, ol=None)
        self.assertEqual((p["stop"], p["risk"], p["target"]), (Decimal("47.00"), Decimal("1.00"), Decimal("50.00")))

    def test_targets_snap_to_the_nearest_tick_and_halves_go_up(self):
        p = c(100, "price:98.5", "1.5R", None, None)
        self.assertEqual(p["target"], Decimal("102.50"))            # 100 + 2.25 is halfway between 102.0 and 102.5
        self.assertEqual(p["target_label"], "1.5R (1.5 times the risk)")
        p = c(100, "price:98.8", "1.5R", None, None)
        self.assertEqual(p["target"], Decimal("102.00"))            # 100 + 1.8: 102.0 is nearer than 101.5
        p = c(205, "or-mid", "price:210.3")
        self.assertEqual(p["target"], Decimal("210.50"))
        self.assertEqual(p["reward_risk"], Decimal("1.83"))
        self.assertEqual(p["target_label"], "your price (1.83R)")
        self.assertEqual(p["target_r"], Decimal("1.83"))

    def test_refusals_say_why(self):
        cases = [("price:205", "2R", "at or above the entry"),
                 ("price:206", "2R", "at or above the entry"),
                 ("or-mid", "price:204", "at or below the entry"),
                 ("price:204.5", "2R", "less than 2 ticks (1.00 at this price)"),
                 ("pct:0.2", "2R", "too tight to survive the spread")]
        for stop, target, why in cases:
            with self.assertRaises(exitp.PlanError) as cm:
                c(205, stop, target)
            self.assertIn(why, str(cm.exception), stop)
        # two ticks of 0.5 is 1.00: a risk of exactly that is allowed
        self.assertEqual(c(205, "price:204")["risk"], Decimal("1.00"))
        with self.assertRaises(exitp.PlanError):
            c(200, "or-mid")                                        # the midpoint snaps above this entry
        for bad in ("mid-ish", "pct:100", "price:0", "atr:-1"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_stop(bad)
        for bad in ("0R", "R", "lots", "price:x"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_target(bad)
        with self.assertRaises(exitp.PlanError):
            c(205, "or-mid", oh=None, ol=None)
        with self.assertRaises(exitp.PlanError):
            c(205, "or-mid", oh=200.5, ol=204.0)

    def test_price_limits(self):
        p = c(205, "or-mid", prev=200)
        self.assertEqual((p["limit_down"], p["limit_up"]), (Decimal("180.00"), Decimal("220.00")))
        self.assertIsNone(c(205, "or-mid")["limit_up"])
        with self.assertRaises(exitp.PlanError) as cm:
            c(205, "or-mid", "price:225", prev=200)
        self.assertIn("above today's limit-up 220.00", str(cm.exception))
        self.assertEqual(c(205, "or-mid", "price:220", prev=200)["target"], Decimal("220.00"))
        with self.assertRaises(exitp.PlanError) as cm:
            c(185, "price:179", prev=200)
        self.assertIn("below today's limit-down 180.00", str(cm.exception))
        with self.assertRaises(exitp.PlanError) as cm:
            c(225, "price:215", prev=200)
        self.assertIn("outside today's price limits 180.00 to 220.00", str(cm.exception))

    def test_atr_on_the_session_bars(self):
        ch = exitp.load_chart("2317.TW", "5m", None, S2317)
        day = exitp.datetime.date(2026, 10, 19)
        bars = exitp.session_bars(ch, day, "5m", upto_slot=5)
        self.assertEqual(len(bars), 6)                              # 9:00 ... the 9:25 entry bar
        # by hand: the true range of each bar, the first one without the overnight gap
        trs, prev = [], None
        for b in bars:
            r = b["h"] - b["l"]
            if prev is not None:
                r = max(r, abs(b["h"] - prev), abs(b["l"] - prev))
            trs.append(r)
            prev = b["c"]
        self.assertEqual(trs, [2.5, 2.5, 2.5, 2.0, 2.0, 2.0])
        atr, n = exitp.atr_of(bars)
        self.assertEqual(n, 6)
        self.assertAlmostEqual(atr, 2.25, places=9)
        # the file's in-progress 10:00 bar and live tick never count
        all_bars = exitp.session_bars(ch, day, "5m")
        self.assertEqual(len(all_bars), 12)
        self.assertEqual(exitp.atr_of(all_bars)[1], 12)
        self.assertAlmostEqual(exitp.atr_of(all_bars)[0], 20.5 / 12, places=9)

    def test_symbols_keep_their_dot(self):
        with self.assertRaises(exitp.PlanError) as cm:
            exitp.load_chart("2317", "5m", None, S2317)
        self.assertIn("needs its market", str(cm.exception))
        with self.assertRaises(exitp.PlanError) as cm:
            exitp.load_chart("2330.TW", "5m", None, S2317)
        self.assertIn("holds 2317.TW, not 2330.TW", str(cm.exception))


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)
        os.mkdir("trader")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def write(self, path, doc):
        with open(path, "w") as fh:
            json.dump(doc, fh)

    def plan(self, *args):
        return run(exitp, ["plan", "--now", "2026-10-19 09:31"] + list(args))

    def read_plan(self):
        with open(os.path.join("trader", "plan.json")) as fh:
            return json.load(fh)

    def test_entry_to_plan_end_to_end(self):
        code, _, _ = run(entry, ["check", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:30", "--write"])
        self.assertEqual(code, 0)
        code, text, err = self.plan("--stop", "or-mid", "--target", "2R", "--write")
        self.assertEqual(code, 0, err)
        p = self.read_plan()
        for k, v in PLAN_2317.items():
            self.assertEqual(p[k], v, k)
        with open(os.path.join(FIX, "trader-budget", "plan-2317.json")) as fh:
            fixture = json.load(fh)
        for k, v in fixture.items():
            self.assertEqual(p[k], v, k)                            # the budget fixture is what this writes
        self.assertEqual(p["round_trip_cost_pct"], 0.32)            # 660 / 205,000 = 0.322 percent
        self.assertIn("Stop          202.00  opening-range midpoint", text)
        self.assertIn("Target        211.00  2R (two times the risk)", text)
        self.assertIn("Risk a share  3.00 (1.46% of the entry)", text)
        self.assertIn("Reward:risk   2.0", text)
        self.assertIn("Price limits  180.00 down to 220.00 up (previous close 200.00", text)
        self.assertIn("Costs         about 0.32% of the position round trip", text)
        self.assertIn("Flat by       13:20 Taipei", text)
        self.assertIn("not a guarantee", text)
        self.assertIn("no bracket orders", text)
        self.assertIn("/trader-timemachine", text)
        self.assertNotIn("$", text)
        self.assertNotIn("pro" + "fit", text.lower())   # never on screen
        code, text, _ = self.plan("--target", "1R", "--write")
        self.assertEqual(self.read_plan()["target"], 208.0)
        self.assertEqual(self.read_plan()["target_r"], 1.0)
        code, text, _ = run(exitp, ["show", "--now", "2026-10-19 09:40"])
        self.assertEqual(code, 0)
        self.assertIn("208.00", text)
        self.assertNotIn("not today", text)
        code, text, _ = run(exitp, ["show", "--now", "2026-10-20 09:40"])
        self.assertIn("not today", text)

    def test_manual_flags_and_json(self):
        code, text, _ = self.plan("--symbol", "2317.tw", "--entry", "205", "--or-high", "204", "--or-low", "200.5",
                                  "--time", "9:30", "--entry-bar", "5", "--date", "2026-10-19", "--prev-close", "200",
                                  "--json")
        self.assertEqual(code, 0)
        p = json.loads(text)
        for k, v in PLAN_2317.items():
            self.assertEqual(p[k], v, k)
        self.assertEqual(p["warnings"], [])

    def test_no_previous_close_is_a_warning(self):
        code, text, _ = self.plan("--symbol", "2317.TW", "--entry", "205", "--or-high", "204", "--or-low", "200.5",
                                  "--json")
        self.assertEqual(code, 0)
        p = json.loads(text)
        self.assertIsNone(p["limit_up"])
        self.assertIn("no previous close for 2317.TW: the +/-10% limit check was skipped", p["warnings"][0])

    def test_a_target_above_limit_up_is_refused(self):
        code, _, err = self.plan("--symbol", "2317.TW", "--entry", "205", "--or-high", "204", "--or-low", "200.5",
                                 "--prev-close", "200", "--target", "price:225")
        self.assertEqual(code, 1)
        self.assertIn("above today's limit-up 220.00", err)

    def test_atr_stop_reads_bars(self):
        self.write(os.path.join("trader", "entry.json"), ENTRY_2317)
        code, text, err = self.plan("--stop", "atr:1.5", "--offline", S2317, "--json")
        self.assertEqual(code, 0, err)
        p = json.loads(text)
        self.assertEqual((p["stop"], p["risk_per_share"], p["target"]), (201.5, 3.5, 212.0))
        self.assertEqual((p["stop_rule"], p["atr_bars"]), ("atr", 6))
        self.assertAlmostEqual(p["atr"], 2.25, places=4)
        code, _, err = self.plan("--stop", "atr:1.5", "--offline", S2317, "--entry-bar", "1")
        self.assertEqual(code, 1)
        self.assertIn("at least 3 closed", err)

    def test_refusals_from_the_cli(self):
        self.write(os.path.join("trader", "entry.json"), dict(ENTRY_2317, status="waiting", time=None, price=None,
                                                              bar_index=None, bar_start=None))
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("2317.TW is waiting, not triggered", err)
        code, text, _ = self.plan("--entry", "204.5", "--json")    # plan ahead at the level
        self.assertEqual(code, 0)
        p = json.loads(text)
        self.assertEqual((p["entry"], p["stop"], p["entry_time"]), (204.5, 202.0, None))

        self.write(os.path.join("trader", "entry.json"), dict(ENTRY_2317, setup="level", level=204.0))
        code, _, err = self.plan()
        self.assertIn("level setup has no opening-range stop", err)
        self.assertEqual(self.plan("--stop", "pct:1")[0], 0)

        code, _, err = self.plan("--side", "sell")
        self.assertIn("v2 plans longs only", err)
        self.write(os.path.join("trader", "entry.json"), dict(ENTRY_2317, side="sell"))
        code, _, err = self.plan()
        self.assertIn("longs only", err)
        code, _, err = self.plan("--stop", "price:204.10")
        self.assertIn("longs only", err)
        os.remove(os.path.join("trader", "entry.json"))
        code, _, err = self.plan()
        self.assertIn("no entry", err)
        code, _, err = self.plan("--symbol", "2317.TW")
        self.assertIn("needs --entry", err)
        code, _, err = self.plan("--symbol", "2317.TW", "--from", "x.json", "--entry", "1")
        self.assertIn("not both", err)
        code, _, err = self.plan("--symbol", "2317.TW", "--entry", "205", "--or-high", "204")
        self.assertIn("both --or-high and --or-low", err)
        code, _, err = self.plan("--symbol", "2317", "--entry", "205", "--or-high", "204", "--or-low", "200.5")
        self.assertIn("needs its market", err)
        code, _, err = self.plan("--symbol", "0050.TW", "--entry", "100", "--stop", "pct:1")
        self.assertIn("ETF", err)
        self.assertNotIn("Traceback", err)

    def test_flat_by_config_and_late_entries(self):
        self.write(os.path.join("trader", "entry.json"), ENTRY_2317)
        self.write(os.path.join("trader", "config.json"), {"flat_by": "13:25", "min_reward_risk": 2.5})
        code, text, _ = self.plan("--json")
        p = json.loads(text)
        self.assertEqual(p["flat_by"], "13:25")
        self.assertIn("under your min_reward_risk 2.5", p["warnings"][0])
        self.write(os.path.join("trader", "config.json"), {"flat_by": "13:30"})
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("at or after the 13:30 close", err)
        os.remove(os.path.join("trader", "config.json"))

        code, text, _ = run(exitp, ["plan", "--now", "2026-10-19 09:31"])
        self.assertEqual(code, 0)
        self.assertIn("Flat by       13:20 Taipei", text)
        self.assertNotIn("early close", text)
        code, _, err = run(exitp, ["plan", "--now", "2026-10-19 09:31", "--flat-by", "14:00"])
        self.assertEqual(code, 1)
        self.assertIn("at or after the 13:30 close", err)

        self.write(os.path.join("trader", "entry.json"), dict(ENTRY_2317, time="1:25 PM"))
        code, _, err = self.plan()
        self.assertEqual(code, 1)
        self.assertIn("no time left to hold it", err)

    def test_show_without_a_plan(self):
        code, text, _ = run(exitp, ["show"])
        self.assertEqual(code, 1)
        self.assertIn("No plan", text)


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "trader-exit", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(ROOT, "trader-risk", "SKILL.md"), encoding="utf-8") as fh:
            risk = fh.read()
        self.assertTrue(text.startswith("---\nname: trader-exit\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertEqual(text[text.index("## Safety"):], risk[risk.index("## Safety"):])
        low = " ".join(text.lower().split())
        for must in ("before the entry", "a stop is a plan, not a guarantee", "day trading loses most people money",
                     "/trader-timemachine", "/trader-budget", "longs only", "202.00", "211.00", "3.00", "limit-up",
                     "taipei", "tick", "no bracket orders", "13:20"):
            self.assertIn(must, low)
        for never in ("\u2014", "tick " + "by tick", "real " + "time", "pro" + "fit", "new york", "nyse"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
