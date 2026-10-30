"""trader-entry tests. Fixtures in tests/fixtures/trader-entry/ are SYNTHETIC (not market data):

2317.TW-2026-10-19-5m-synthetic.json  Yahoo chart JSON v8 shape for 2317.TW, a made-up Taipei session on
                         Monday 2026-10-19 (previous close 200.0): twelve 5-minute bars from 09:00, the 10:00 bar
                         in progress and Yahoo's live tick at 10:02:30. meta looks like a range=1d answer.
DEMO.TW-1m-synthetic.json  one-minute bars: a wick above the range high, a close AT the high, a null bar,
                         a live tick.
"""

import copy
import datetime
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, ROOT

entry = load("trader-entry", "entry")

EDIR = os.path.join(FIX, "trader-entry")
S2317 = os.path.join(EDIR, "2317.TW-2026-10-19-5m-synthetic.json")
DEMO = os.path.join(EDIR, "DEMO.TW-1m-synthetic.json")
OPEN_TS = 1792371600       # 2026-10-19 09:00 Taipei = 01:00 UTC
DT = datetime.datetime


def tp(text):
    return entry.parse_now(text)


def doc(path=S2317):
    with open(path) as fh:
        return json.load(fh)


def chart(d=None, sym="2317.TW"):
    return entry.parse_chart(json.dumps(d if d is not None else doc()), sym)


def at(text, d=None, **kw):
    return entry.evaluate(chart(d), tp(text), **kw)


def shift_to(d, day):
    """The same session moved to another date (09:00 Taipei is 01:00 UTC; Taipei has no daylight time)."""
    d = copy.deepcopy(d)
    r = d["chart"]["result"][0]
    new_open = int((DT.combine(day, datetime.time(1, 0)) - DT(1970, 1, 1)).total_seconds())
    delta = new_open - OPEN_TS
    r["timestamp"] = [t + delta for t in r["timestamp"]]
    r["meta"]["regularMarketTime"] += delta
    return d


def no_breakout(d=None):
    """Every bar after the range stays under the 204.0 high."""
    d = copy.deepcopy(d if d is not None else doc())
    q = d["chart"]["result"][0]["indicators"]["quote"][0]
    for i in range(3, len(q["close"])):
        q["close"][i] = min(q["close"][i], 203.5)
        q["high"][i] = min(q["high"][i], 203.9)
        q["open"][i] = min(q["open"][i], 203.5)
    return d


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entry.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheSession(unittest.TestCase):
    def test_triggers_at_0930_on_the_0925_bar(self):
        r = at("2026-10-19 09:30")
        self.assertEqual(r["status"], "triggered")
        self.assertEqual(r["opening_range"]["high"], 204.0)
        self.assertEqual(r["opening_range"]["low"], 200.5)
        self.assertEqual(r["opening_range"]["bars"], 3)
        t = r["trigger"]
        self.assertEqual(t["time"], "9:30 AM")
        self.assertEqual(t["bar_start"], "09:25")
        self.assertEqual(t["bar_index"], 5)
        self.assertEqual(t["price"], 205.0)
        self.assertEqual(t["close"], 205.0)
        self.assertEqual(t["pct_over"], 0.49)
        self.assertEqual(r["level"], 204.0)
        self.assertEqual((r["prev_close"], r["limit_down"], r["limit_up"]), (200.0, 180.0, 220.0))
        self.assertEqual(r["warnings"], [])

    def test_a_close_at_the_high_is_not_a_trigger_and_the_open_bar_is_still_forming(self):
        r = at("2026-10-19 09:27")
        self.assertEqual(r["status"], "waiting")
        self.assertIsNone(r["trigger"])
        self.assertEqual(r["last"]["bar_start"], "09:20")
        self.assertEqual(r["last"]["close"], 204.0)           # the 09:20 bar closed AT the high
        self.assertEqual(r["forming"]["bar_start"], "09:25")
        self.assertIn("under the range high 204.00", r["reason"])
        self.assertEqual(at("2026-10-19 09:29:59")["status"], "waiting")

    def test_before_the_open_and_while_the_range_forms(self):
        r = at("2026-10-19 08:50")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "pre-open"))
        self.assertIn("opens at 9:00", r["reason"])
        r = at("2026-10-19 09:12")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))
        self.assertEqual(r["opening_range"]["bars"], 2)
        self.assertFalse(r["opening_range"]["complete"])
        r = at("2026-10-19 09:16")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "open"))
        self.assertEqual(r["opening_range"]["bars"], 3)

    def test_the_live_tick_and_the_in_progress_bar_are_dropped(self):
        c = chart()
        self.assertEqual(c["bars"][-1]["t"], OPEN_TS + 3750)       # 10:02:30 is in the file
        r = entry.evaluate(c, entry.utc_of(c["data_time"]))        # read as of the file's own time
        self.assertEqual(r["now"], "2026-10-19 10:02:30")
        self.assertEqual(r["_bars"][-1]["slot"], 11)                # the 09:55 bar
        self.assertEqual(r["forming"]["bar_start"], "10:00")
        self.assertEqual(r["bars_closed"], 12)
        # 10:05: closed by the clock, but Yahoo's last trade (10:02:30) is before its close
        r = at("2026-10-19 10:05")
        self.assertEqual(r["_bars"][-1]["slot"], 11)
        self.assertIn("Yahoo's last trade is 10:02:30", r["lag_note"])
        # a minute later with no newer trade it counts; the 10:02:30 tick never becomes a bar
        r = at("2026-10-19 10:06")
        self.assertEqual(r["_bars"][-1]["slot"], 12)
        self.assertEqual(r["bars_closed"], 13)
        self.assertTrue(all(b["t"] % 300 == 0 for b in r["_bars"]))

    def test_after_the_close_it_stays_triggered_and_says_it_is_late(self):
        r = at("2026-10-19 13:35")
        self.assertEqual((r["status"], r["phase"]), ("triggered", "after-close"))
        self.assertEqual(r["trigger"]["time"], "9:30 AM")
        text = "\n".join(entry.describe(r))
        self.assertIn("minutes ago", text)
        self.assertNotIn("This is the moment", text)

    def test_describe_says_taipei_and_has_no_dollar_signs(self):
        text = "\n".join(entry.describe(at("2026-10-19 09:30")))
        self.assertIn("Taipei", text)
        self.assertIn("TRIGGERED 9:30 AM at 205.00", text)
        self.assertIn("Price limits today: 180.00 down to 220.00 up (previous close 200.00", text)
        self.assertNotIn("$", text)
        self.assertNotIn("New York", text)


class Rules(unittest.TestCase):
    # worked out separately: the 3 range bars average (4.2M + 2.6M + 1.8M) / 3 = 2,866,667 shares
    def test_volume_confirmation_moves_the_trigger(self):
        r = at("2026-10-19 10:00", min_volume_x=1.2)
        self.assertEqual(r["opening_range"]["avg_volume"], 2866667)
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_index"], t["price"]), ("9:35 AM", 6, 205.5))
        self.assertEqual((t["volume_x"], t["pct_over"]), (1.26, 0.74))
        r = at("2026-10-19 09:31", min_volume_x=1.2)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("1.01x the range's volume, under your 1.20x", r["reason"])

    def test_level_setup(self):
        r = at("2026-10-19 09:40", setup="level", level=204.5)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"], r["trigger"]["price"]), ("9:30 AM", 5, 205.0))
        # a level under the open: the first eligible close is the 09:10 bar's, at 09:15 (no_entries_before)
        r = at("2026-10-19 09:40", setup="level", level=200)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:15 AM", 2))
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 09:40", setup="level")

    def test_a_level_above_limit_up_cannot_trigger(self):
        r = at("2026-10-19 10:00", setup="level", level=225)
        self.assertEqual(r["status"], "waiting")
        self.assertTrue(any("above today's limit-up 220.00" in w for w in r["warnings"]))

    def test_no_breakout_waits_then_expires_at_the_cutoff(self):
        d = no_breakout()
        r = at("2026-10-19 10:02", d)
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(at("2026-10-19 12:59", d)["status"], "waiting")
        r = at("2026-10-19 13:00", d)
        self.assertEqual(r["status"], "expired")
        self.assertIn("by 13:00", r["reason"])
        self.assertEqual(at("2026-10-19 13:40", d)["phase"], "after-close")

    def test_the_bar_closing_at_the_cutoff_still_counts_when_yahoo_lags(self):
        d = no_breakout()
        r0 = d["chart"]["result"][0]
        keep = [i for i, t in enumerate(r0["timestamp"]) if t <= OPEN_TS + 11 * 300]   # live: up to the 09:55 bar
        r0["timestamp"] = [r0["timestamp"][i] for i in keep]
        q = r0["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep]
        r0["meta"]["regularMarketTime"] = OPEN_TS + 59 * 60 + 40                       # last trade 09:59:40
        cfg = {"no_entries_before": "09:15", "no_entries_after": "10:00"}
        r = at("2026-10-19 10:00:10", d, cfg=cfg)                           # the 09:55 bar closed by the clock only
        self.assertEqual(r["status"], "waiting")
        self.assertIn("Yahoo's last trade is 09:59:40", r["lag_note"])
        self.assertEqual(at("2026-10-19 10:01", d, cfg=cfg)["status"], "expired")

    def test_config_cutoff_and_start(self):
        cfg = {"no_entries_before": "09:15", "no_entries_after": "09:20"}
        r = at("2026-10-19 09:31", cfg=cfg)
        self.assertEqual(r["status"], "expired")
        cfg = {"no_entries_before": "09:35", "no_entries_after": "13:00"}
        r = at("2026-10-19 09:40", cfg=cfg)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:35 AM", 6))   # first bar to close at or after 09:35

    def test_a_cutoff_after_the_close_is_clamped_to_1330(self):
        cfg = {"no_entries_before": "09:15", "no_entries_after": "14:30"}
        r = at("2026-10-19 10:02", cfg=cfg)
        self.assertEqual((r["closes"], r["no_entries_after"]), ("13:30", "13:30"))

    def test_bad_inputs(self):
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 09:30", or_minutes=7)
        with self.assertRaises(entry.EntryError):
            at("2026-10-19 09:30", interval="15m")
        with self.assertRaises(entry.EntryError) as cm:
            entry.parse_now("tomorrow")
        self.assertIn("Taipei time", str(cm.exception))
        with self.assertRaises(entry.EntryError):
            entry.parse_hhmm("25:00", "x")
        self.assertEqual(entry.parse_now("2026-10-19 09:30"), DT(2026, 10, 19, 1, 30))
        self.assertEqual(entry.parse_now("2026-10-19T01:30:00Z"), DT(2026, 10, 19, 1, 30))
        self.assertEqual(entry.parse_now("2026-10-19 09:30 Taipei"), DT(2026, 10, 19, 1, 30))

    def test_or_minutes_30(self):
        r = at("2026-10-19 10:00", or_minutes=30)
        self.assertEqual(r["opening_range"]["bars"], 6)
        self.assertEqual(r["opening_range"]["high"], 205.5)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["price"]), ("9:40 AM", 206.0))


class PriceLimits(unittest.TestCase):
    def test_yahoos_previous_close_wins_on_the_latest_session(self):
        # a 5-day style chart: an earlier session's bar plus the day; previousClose is for the latest day
        c = chart()
        earlier = {"t": entry.ts_of(DT(2026, 10, 16, 5, 25)), "o": 198.0, "h": 199.0, "l": 197.5, "c": 198.5, "v": 1000}
        c["bars"] = [earlier] + c["bars"]
        c["previous_close"] = 200.0
        c["prev_close"] = 200.0
        self.assertEqual(entry.prev_close_for(c, datetime.date(2026, 10, 19)), (200.0, "yahoo"))
        # chartPreviousClose alone (the close before the first day of a multi-day chart) is not used
        c["previous_close"] = None
        c["prev_close"] = 150.0
        self.assertEqual(entry.prev_close_for(c, datetime.date(2026, 10, 19)), (198.5, "last bar"))

    def test_an_older_session_falls_back_to_the_last_bar_and_says_so(self):
        # the chart also holds the next day, so 10-19 is not the latest session: use the last 10-16 bar
        c = chart()
        earlier = {"t": entry.ts_of(DT(2026, 10, 16, 5, 25)), "o": 198.0, "h": 199.0, "l": 197.5, "c": 198.5, "v": 1000}
        later = {"t": entry.ts_of(DT(2026, 10, 20, 1, 0)), "o": 207.0, "h": 208.0, "l": 206.0, "c": 207.5, "v": 1000}
        c["bars"] = [earlier] + c["bars"] + [later]
        self.assertEqual(entry.prev_close_for(c, datetime.date(2026, 10, 19)), (198.5, "last bar"))
        r = entry.evaluate(c, tp("2026-10-19 09:30"))
        self.assertEqual((r["prev_close"], r["limit_down"], r["limit_up"]), (198.5, 179.0, 218.0))   # 178.65 up, 218.35 down
        self.assertTrue(any("can differ a little from the official close" in w for w in r["warnings"]))
        self.assertEqual(entry.prev_close_for(c, datetime.date(2026, 10, 16)), (None, None))

    def test_no_previous_close_is_a_warning_not_a_guess(self):
        d = doc()
        for k in ("previousClose", "chartPreviousClose"):
            del d["chart"]["result"][0]["meta"][k]
        r = at("2026-10-19 09:30", d)
        self.assertEqual(r["status"], "triggered")
        self.assertIsNone(r["limit_up"])
        self.assertIn("no previous close for 2317.TW: the +/-10% limit check was skipped", r["warnings"])
        self.assertIn("Warning: no previous close", "\n".join(entry.describe(r)))

    def test_a_trigger_at_limit_up_is_flagged(self):
        d = doc()
        meta = d["chart"]["result"][0]["meta"]
        meta["previousClose"] = meta["chartPreviousClose"] = 186.0     # 186 x 1.1 = 204.6, floored to 204.50
        r = at("2026-10-19 09:30", d)
        self.assertEqual((r["limit_down"], r["limit_up"]), (167.5, 204.5))
        self.assertTrue(any("at limit-up 204.50" in w for w in r["warnings"]))

    def test_the_next_day_uses_the_last_bar_of_the_day_before(self):
        r = at("2026-10-20 09:30")
        self.assertEqual(r["status"], "no-data")
        self.assertEqual(r["prev_close"], 206.0)


class OneMinute(unittest.TestCase):
    def c(self):
        return entry.parse_chart(json.dumps(doc(DEMO)), "DEMO.TW")

    def test_wick_and_close_at_the_high_do_not_trigger(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m")
        self.assertEqual(r["now"], "2026-10-19 09:36:30")
        self.assertEqual(r["opening_range"], {"high": 100.5, "low": 99.0, "minutes": 15, "bars": 15, "of": 15,
                                              "complete": True, "avg_volume": 10667})
        t = r["trigger"]
        self.assertEqual((t["time"], t["bar_start"], t["bar_index"], t["price"]), ("9:29 AM", "09:28", 28, 100.62))
        r = entry.evaluate(c, tp("2026-10-19 09:28:59"), interval="1m")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["forming"]["bar_start"], "09:28")
        self.assertEqual(r["last"]["close"], 100.5)             # the 09:27 bar closed AT the high

    def test_null_bar_tick_and_volume(self):
        c = self.c()
        r = entry.evaluate(c, entry.utc_of(c["data_time"]), interval="1m", min_volume_x=2)
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:32 AM", 31))
        slots = [b["slot"] for b in r["_bars"]]
        self.assertNotIn(19, slots)                               # 09:19 came as nulls
        self.assertEqual(slots[-1], 35)                           # 09:36 still forming, 09:36:30 tick dropped
        self.assertEqual(r["forming"]["bar_start"], "09:36")

    def test_the_file_and_the_interval_must_agree(self):
        code, _, err = run(["check", "DEMO.TW", "--offline", DEMO])
        self.assertEqual(code, 1)
        self.assertIn("1m bars, not 5m", err)


class Calendar(unittest.TestCase):
    def test_taipei_has_no_daylight_time(self):
        for day in (datetime.date(2026, 12, 7), datetime.date(2026, 7, 13), datetime.date(2026, 3, 9)):
            d = shift_to(doc(), day)
            r = entry.evaluate(chart(d), tp("%s 09:30" % day))
            self.assertEqual(r["status"], "triggered", day)
            self.assertEqual(r["trigger"]["time"], "9:30 AM", day)
            self.assertEqual(r["trigger"]["bar_index"], 5, day)
            self.assertEqual(entry.evaluate(chart(d), tp("%s 09:27" % day))["status"], "waiting", day)
        self.assertEqual(tp("2026-12-07 09:30"), DT(2026, 12, 7, 1, 30))

    def test_no_early_close(self):
        d = no_breakout()
        r = entry.evaluate(chart(d), tp("2026-10-19 10:02"))
        self.assertEqual((r["opens"], r["closes"]), ("09:00", "13:30"))
        self.assertFalse(any("early" in line.lower() for line in entry.describe(r)))

    def test_weekend_holiday_and_empty_data(self):
        r = at("2026-10-17 10:30")
        self.assertEqual((r["status"], r["phase"]), ("no-data", "closed"))
        self.assertEqual(r["next_open"], "2026-10-19 09:00")
        self.assertIn("weekend", r["reason"])
        r = at("2026-10-26 10:30")                                # Taiwan Retrocession Day (observed)
        self.assertEqual(r["status"], "no-data")
        self.assertIn("TWSE holiday", r["reason"])
        self.assertEqual(r["next_open"], "2026-10-27 09:00")
        self.assertIn("TWSE is closed", at("2026-02-12 10:30")["reason"])
        empty = copy.deepcopy(doc())
        res = empty["chart"]["result"][0]
        del res["timestamp"]
        res["indicators"] = {"quote": [{}]}
        r = at("2026-10-19 09:30", empty)
        self.assertEqual((r["status"], r["phase"]), ("no-data", "open"))
        r = at("2026-10-20 09:30")                                # Yahoo sent yesterday's bars only
        self.assertEqual(r["status"], "no-data")
        self.assertFalse(at("2028-03-01 10:30")["calendar_known"])
        self.assertIn("twse.com.tw", "\n".join(entry.describe(at("2028-03-01 10:30"))))

    def test_yahoo_errors(self):
        bad = json.dumps({"chart": {"result": None, "error": {"code": "Not Found",
                                                              "description": "No data found, symbol may be delisted"}}})
        with self.assertRaises(entry.EntryError) as cm:
            entry.parse_chart(bad, "9999.TW")
        self.assertIn("No data found", str(cm.exception))
        with self.assertRaises(entry.EntryError):
            entry.parse_chart("<html>", "2317.TW")


class Symbols(unittest.TestCase):
    def test_yahoo_symbols_keep_their_dot(self):
        self.assertEqual(entry.yahoo_symbol("2317.tw"), "2317.TW")
        self.assertEqual(entry.yahoo_symbol("6488.TWO"), "6488.TWO")
        self.assertIn("/chart/2317.TW?range=1d&interval=5m", entry.chart_path("2317.tw", "1d", "5m"))
        self.assertNotIn("2317-TW", entry.chart_path("2317.TW", "1d", "5m"))

    def test_a_bare_code_needs_its_market(self):
        with self.assertRaises(entry.EntryError) as cm:
            entry.yahoo_symbol("2317")
        self.assertIn("2317.TW (TWSE listed) or 2317.TWO (TPEx OTC)", str(cm.exception))
        code, _, err = run(["check", "2317", "--offline", S2317])
        self.assertEqual(code, 1)
        self.assertIn("needs its market", err)
        with self.assertRaises(entry.EntryError):
            entry.yahoo_symbol("TSLA")


class Network(unittest.TestCase):
    """Yahoo is never called: _open_url and _sleep are swapped for fakes."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._open, self._sleep = entry._open_url, entry._sleep
        entry._sleep = lambda s: self.sleeps.append(s)
        with open(S2317) as fh:
            self.body = fh.read()
        self.day = datetime.date(2026, 10, 19)

    def tearDown(self):
        entry._open_url, entry._sleep = self._open, self._sleep

    def answers(self, *codes):
        seq = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url)
            code = seq.pop(0)
            if code == 200:
                return self.body
            raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b'{"chart":{"result":null,'
                                                                           b'"error":{"description":"No data found"}}}'))
        entry._open_url = fake

    def test_url_and_429_retry_once_after_a_pause(self):
        self.answers(429, 200)
        c = entry.get_chart("2317.TW", "5m", self.day, today=self.day)
        self.assertEqual(len(c["bars"]), 14)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com/v8/finance/chart/2317.TW?range=1d&interval=5m"] * 2)
        self.assertEqual(self.sleeps, [entry.BACKOFF])

    def test_429_twice_falls_back_to_query1(self):
        self.answers(429, 429, 200)
        entry.get_chart("2317.TW", "5m", self.day, today=self.day)
        self.assertEqual([u.split("/")[2] for u in self.calls],
                         ["query2.finance.yahoo.com", "query2.finance.yahoo.com", "query1.finance.yahoo.com"])

    def test_5xx_falls_back_without_waiting(self):
        self.answers(503, 200)
        entry.get_chart("2317.TW", "5m", self.day, today=self.day)
        self.assertEqual(self.sleeps, [])
        self.assertIn("query1", self.calls[1])

    def test_still_busy_is_one_plain_error(self):
        self.answers(429, 429, 429, 429)
        # pin the real clock too: the CLI refuses a --now date older than Yahoo's ~60 days of 5-minute bars
        real_now = entry.utc_now
        entry.utc_now = lambda: datetime.datetime(2026, 10, 19, 1, 30)
        try:
            code, out, err = run(["check", "2317.TW", "--now", "2026-10-19 09:30"])
        finally:
            entry.utc_now = real_now
        self.assertEqual(code, 1)
        self.assertIn("HTTP 429", err)
        self.assertNotIn("Traceback", err)

    def test_unknown_ticker_404(self):
        self.answers(404)
        with self.assertRaises(entry.EntryError) as cm:
            entry.get_chart("9999.TW", "5m", self.day, today=self.day)
        self.assertIn("No data found", str(cm.exception))

    def test_ranges_for_past_sessions(self):
        today = datetime.date(2026, 10, 20)
        self.assertEqual(entry.chart_range(today, today, "5m"), "1d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 19), today, "5m"), "5d")
        self.assertEqual(entry.chart_range(datetime.date(2026, 10, 1), today, "5m"), "1mo")
        self.assertEqual(entry.chart_range(datetime.date(2026, 8, 31), today, "5m"), "60d")
        with self.assertRaises(entry.EntryError):
            entry.chart_range(datetime.date(2026, 10, 1), today, "1m")


def live_provider(d, lag_until=None, calls=None):
    """Bars the way Yahoo serves them at `now`: closed bars final, the in-progress bar
    showing a spike to 205.50 (above the high, then it closes lower), plus a live tick.
    lag_until: before this UTC time Yahoo's last trade lags 30 seconds behind."""
    base = chart(d)

    def provider(now):
        if calls is not None:
            calls.append(now)
        nts = entry.ts_of(now)
        lagging = lag_until is not None and now < lag_until
        data_ts = nts - 30 if lagging else nts
        bars = []
        for b in base["bars"]:
            if b["t"] % 300 or b["t"] > data_ts:
                continue
            b = dict(b)
            if b["t"] + 300 > data_ts:
                b["c"], b["h"] = 205.50, max(b["h"], 205.50)
            bars.append(b)
        if data_ts % 300:
            bars.append({"t": data_ts, "o": 205.5, "h": 205.5, "l": 205.5, "c": 205.5, "v": 0})
        return {"symbol": "2317.TW", "meta": {}, "bars": bars, "prev_close": 200.0, "previous_close": 200.0,
                "data_time": data_ts}
    return provider


class Watch(unittest.TestCase):
    OPTS = {"setup": "orb", "or_minutes": 15, "interval": "5m", "level": None, "min_volume_x": None, "cfg": None}

    def loop(self, provider, start, **kw):
        clock = entry.SimClock(tp(start))
        lines, fired = [], []
        code, res = entry.watch_loop(provider, clock.now, clock.sleep, lines.append, dict(self.OPTS),
                                     on_trigger=lambda r, now: fired.append((r, now)), **kw)
        return code, res, lines, fired, clock

    def test_fires_on_the_first_closed_bar_not_the_spike_in_progress(self):
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), calls=calls), "2026-10-19 09:22", every=60)
        self.assertEqual(code, 0)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0][0]["trigger"]["time"], "9:30 AM")
        self.assertEqual(fired[0][0]["trigger"]["price"], 205.0)
        # it looked at 09:22 (the 09:20 bar spiking to 205.50 in progress) and at 09:25:02 (that bar closed AT 204.00)
        self.assertEqual([entry.to_taipei(c).strftime("%H:%M:%S") for c in calls], ["09:22:00", "09:25:02", "09:30:02"])
        text = "\n".join(lines)
        self.assertIn("9:20 bar  closed 204.00  0.00 under 204.00", text)
        self.assertIn("9:25 bar  closed 205.00  TRIGGERED", text)
        self.assertEqual(text.count("TRIGGERED"), 1)
        self.assertNotIn("$", text)

    def test_waits_for_yahoo_to_catch_up(self):
        lag = tp("2026-10-19 09:30:30")
        calls = []
        code, res, lines, fired, clock = self.loop(live_provider(doc(), lag_until=lag, calls=calls),
                                                   "2026-10-19 09:27", every=30)
        self.assertEqual(code, 0)
        times = [entry.to_taipei(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times, ["09:27:00", "09:30:02", "09:30:32"])   # 09:30:02: Yahoo still at 09:29:32
        self.assertEqual(fired[0][0]["trigger"]["time"], "9:30 AM")

    def test_from_before_the_open_prints_the_range_bar_by_bar(self):
        code, res, lines, fired, clock = self.loop(live_provider(doc()), "2026-10-19 08:55", every=30)
        self.assertEqual(code, 0)
        text = "\n".join(lines)
        self.assertIn("not open yet", lines[0])
        self.assertIn(" 9:10 bar  closed 202.00  opening range set: high 204.00, low 200.50", text)
        self.assertEqual(sum(1 for x in lines if " bar  closed " in x), 6)    # 09:00 ... 09:25, one line each

    def test_a_computer_that_dozes_off_catches_up_when_it_wakes(self):
        class Dozing(entry.SimClock):
            naps = 0

            def sleep(self, seconds):
                entry.SimClock.sleep(self, seconds)
                self.naps += 1
                if self.naps == 3:                      # the laptop sleeps for 17 minutes mid-wait
                    self.t += datetime.timedelta(minutes=17)
        clock = Dozing(tp("2026-10-19 09:16"))
        calls, lines = [], []
        code, res = entry.watch_loop(live_provider(doc(), calls=calls), clock.now, clock.sleep, lines.append,
                                     dict(self.OPTS), every=30)
        self.assertEqual(code, 0)
        times = [entry.to_taipei(c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times[:2], ["09:16:00", "09:34:30"])   # straight after waking, not a long sleep later
        text = "\n".join(lines)
        for start in (" 9:15", " 9:20", " 9:25"):
            self.assertIn(start + " bar  closed", text)          # the bars it slept through, one line each
        self.assertEqual(res["trigger"]["time"], "9:30 AM")

    def test_expires_and_until(self):
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-10-19 12:30", every=300)
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "expired")
        self.assertEqual(fired, [])
        self.assertEqual(entry.to_taipei(clock.now()).strftime("%H:%M"), "13:00")
        until = DT(2026, 10, 19, 11, 0)
        code, res, lines, fired, clock = self.loop(live_provider(no_breakout()), "2026-10-19 10:30", every=300,
                                                   until=until)
        self.assertEqual(code, 1)
        self.assertIn("--until 11:00", lines[-1])

    def test_closed_day_and_repeated_errors(self):
        code, _, lines, _, _ = self.loop(live_provider(doc()), "2026-10-17 10:00")
        self.assertEqual(code, 1)
        self.assertIn("weekend", lines[0])

        def broken(now):
            raise entry.EntryError("Yahoo did not answer")
        code, _, lines, _, _ = self.loop(broken, "2026-10-19 10:00", every=30)
        self.assertEqual(code, 1)
        self.assertIn("Stopping after 5 failed reads", lines[-1])


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.d)

    def test_check_write_is_the_contract_shape(self):
        code, text, _ = run(["check", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:30", "--write"])
        self.assertEqual(code, 0)
        self.assertIn("TRIGGERED 9:30 AM at 205.00", text)
        self.assertIn("/trader-exit", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            e = json.load(fh)
        want = {"created_by": "trader-entry", "symbol": "2317.TW", "setup": "orb", "side": "buy", "date": "2026-10-19",
                "status": "triggered", "time": "9:30 AM", "bar_start": "09:25", "bar_index": 5, "price": 205.0,
                "level": 204.0, "interval": "5m", "opening_range": {"high": 204.0, "low": 200.5, "minutes": 15},
                "prev_close": 200.0, "currency": "TWD",
                "source": "yahoo", "checked_at": "2026-10-19T01:30:00Z"}
        for k, v in want.items():
            self.assertEqual(e[k], v, k)

    def test_check_waiting_json_and_exit_codes(self):
        code, text, _ = run(["check", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:27", "--json"])
        self.assertEqual(code, 1)
        r = json.loads(text)
        self.assertEqual(r["status"], "waiting")
        self.assertNotIn("_bars", r)
        code, text, _ = run(["check", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:27", "--write", "e.json"])
        with open("e.json") as fh:
            self.assertEqual(json.load(fh)["status"], "waiting")
        self.assertIn("still forming", text)

    def test_offline_gz_folder_and_mismatch(self):
        os.mkdir("charts")
        with open(S2317, "rb") as src, gzip.open(os.path.join("charts", "2317.TW.json.gz"), "wb") as dst:
            dst.write(src.read())
        code, text, _ = run(["check", "2317.tw", "--offline", "charts", "--now", "2026-10-19 09:30"])
        self.assertEqual(code, 0)
        code, _, err = run(["check", "2330.TW", "--offline", S2317])
        self.assertEqual(code, 1)
        self.assertIn("holds 2317.TW, not 2330.TW", err)

    def test_longs_only_and_flag_errors(self):
        code, _, err = run(["check", "2317.TW", "--offline", S2317, "--side", "short"])
        self.assertEqual(code, 1)
        self.assertIn("v2 plans longs only", err)
        code, _, err = run(["check", "2317.TW", "--offline", S2317, "--level", "300"])
        self.assertIn("--level is for --setup level", err)
        code, _, err = run(["check", "2317.TW", "--offline", S2317, "--setup", "level"])
        self.assertIn("needs --level", err)

    def test_config_is_read(self):
        os.mkdir("trader")
        with open(os.path.join("trader", "config.json"), "w") as fh:
            json.dump({"no_entries_after": "09:20"}, fh)
        code, text, _ = run(["check", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:30"])
        self.assertEqual(code, 1)
        self.assertIn("EXPIRED", text)
        with open(os.path.join("trader", "config.json"), "w") as fh:
            fh.write("{nope")
        code, _, err = run(["check", "2317.TW", "--offline", S2317])
        self.assertIn("not valid JSON", err)

    def test_watch_replays_the_file_and_writes_the_entry(self):
        code, text, _ = run(["watch", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:10", "--every", "30"])
        self.assertEqual(code, 0)
        self.assertIn("9:25 bar  closed 205.00  TRIGGERED", text)
        with open(os.path.join("trader", "entry.json")) as fh:
            self.assertEqual(json.load(fh)["bar_index"], 5)
        code, text, _ = run(["watch", "2317.TW", "--offline", S2317, "--now", "2026-10-19 09:10", "--until", "09:20",
                             "--out", "x.json"])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists("x.json"))

    def test_watchlist(self):
        os.mkdir("charts")
        shutil.copy(S2317, os.path.join("charts", "2317.TW.json"))
        shutil.copy(DEMO, os.path.join("charts", "DEMO.TW.json"))
        os.mkdir("trader")
        with open(os.path.join("trader", "watchlist.json"), "w") as fh:
            json.dump({"created_by": "trader-scanner", "hits": [
                {"symbol": "2317.TW", "setups": ["orb"], "or_high": 204.0, "or_low": 200.5},
                {"symbol": "9999.TW", "setups": ["orb"]}, {"symbol": "DEMO.TW", "setups": ["orb"]}]}, fh)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-19 09:30"])
        self.assertEqual(code, 0)
        rows = text.splitlines()
        self.assertTrue(rows[1].startswith("2317.TW    triggered  9:30 AM   205.00    204.00"), rows[1])
        self.assertIn("9999.TW    error: no offline file", rows[2])
        self.assertIn("DEMO.TW    error: DEMO.TW has 1m bars", rows[3])
        self.assertIn("1 of 3 triggered", text)
        code, text, _ = run(["watchlist", "--offline", "charts", "--now", "2026-10-19 09:27", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)[0]["result"]["status"], "waiting")
        code, _, err = run(["watchlist", "--watchlist", "missing.json"])
        self.assertIn("run /trader-scanner first", err)


class SkillDoc(unittest.TestCase):
    def test_skill_md(self):
        with open(os.path.join(ROOT, "trader-entry", "SKILL.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(ROOT, "trader-risk", "SKILL.md"), encoding="utf-8") as fh:
            risk = fh.read()
        self.assertTrue(text.startswith("---\nname: trader-entry\n"))
        self.assertGreater(len(text.splitlines()), 60)
        self.assertEqual(text[text.index("## Safety"):], risk[risk.index("## Safety"):])
        low = " ".join(text.lower().split())
        for must in ("bar by bar", "can lag", "day trading loses most people money", "/trader-exit", "longs only",
                     "in the background", "/loop", "nothing was placed", "9:30 am", "205.00", "bar 5", "taipei",
                     "2317.tw", "limit-up"):
            self.assertIn(must, low)
        for never in ("\u2014", "tick " + "by tick", "real " + "time", "pro" + "fit", "new york", "nyse"):
            self.assertNotIn(never, low)


if __name__ == "__main__":
    unittest.main()
