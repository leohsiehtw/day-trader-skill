"""trader-scanner tests. Fixtures in tests/fixtures/trader-scanner/:

twlists/twse.json, tpex.json   a few REAL rows of the TWSE and TPEx daily-quote lists (fetched 2026-10-29 from
                               openapi.twse.com.tw and www.tpex.org.tw/openapi), cut down to 8 and 6 rows.
spark-3mo-live-2026-10-28.json a REAL Yahoo spark answer: 3 months of daily bars for 2317.TW, 0050.TW, 6488.TWO.
                               The 2026-10-28 daily bar came back with a null close, as Yahoo serves it just
                               after the close.
2317.TW-5m-live-2026-10-28.json a REAL v8 5-minute chart of 2317.TW for 2026-10-28: bars 9:00 to 13:20, a null
                               13:25 bar and the 13:30 closing print.
daily-spark-2026-10-19-synthetic.json  SYNTHETIC daily bars (not market data) for 11 symbols, built so each
                               setup has a known answer.
wall5m-2026-10-19-synthetic.json.gz   SYNTHETIC 5-minute charts for a made-up Monday session, 2026-10-19.
"""

import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

scan = load("trader-scanner", "scan")

SDIR = os.path.join(FIX, "trader-scanner")
WALL = os.path.join(SDIR, "wall5m-2026-10-19-synthetic.json.gz")
DAILY = os.path.join(SDIR, "daily-spark-2026-10-19-synthetic.json")
LIVE = os.path.join(SDIR, "spark-3mo-live-2026-10-28.json")
LISTS = os.path.join(SDIR, "twlists")
REAL5 = os.path.join(SDIR, "2317.TW-5m-live-2026-10-28.json")
DT = datetime.datetime
D = datetime.date
OPEN_TS = 1792371600       # 2026-10-19 09:00 Taipei


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


def ts(tp_text):
    """Taipei wall-clock text -> unix seconds (a fixed +8 hours)."""
    local = DT.strptime(tp_text, "%Y-%m-%d %H:%M:%S" if tp_text.count(":") == 2 else "%Y-%m-%d %H:%M")
    return int((scan.taipei_to_utc(local) - DT(1970, 1, 1)).total_seconds())


def bars_series(day, closes, highs=None, lows=None, start="09:00", extra=None):
    """A v8-like series of 5-min bars from `start` on `day` (YYYY-MM-DD)."""
    t0 = DT.strptime(day + " " + start, "%Y-%m-%d %H:%M")
    t = [ts((t0 + datetime.timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M")) for i in range(len(closes))]
    s = {"t": t, "c": list(closes), "h": list(highs or [c + 0.1 if c is not None else None for c in closes]),
         "l": list(lows or [c - 0.1 if c is not None else None for c in closes]), "o": None,
         "v": [1000] * len(closes), "meta": {}}
    for when, c in (extra or []):
        s["t"].append(ts(when))
        for k in ("c", "h", "l"):
            s[k].append(c)
        s["v"].append(10)
    return s


class Universe(unittest.TestCase):
    def setUp(self):
        self.texts = {}
        for f in scan.TW_FILES:
            with open(os.path.join(LISTS, f), encoding="utf-8") as fh:
                self.texts[f] = fh.read()
        self.kept, self.counts, self.dates = scan.build_universe(self.texts)

    def test_the_kept_list(self):
        self.assertEqual([s for s, _ in self.kept],
                         ["1101.TW", "2317.TW", "2330.TW", "2412.TW", "3293.TWO", "6488.TWO", "8069.TWO"])
        self.assertEqual(self.counts["rows"], 14)
        self.assertEqual(self.dates, {"twse": "2026-10-27", "tpex": "2026-10-28"})
        self.assertTrue(all(name for _, name in self.kept))

    def test_what_was_dropped(self):
        # 0050, 00411A, 006201 are ETFs; 1101B (preferred), 910322 and 700019 (a warrant) are not 4-digit
        # stock codes; 9103 is a Taiwan Depositary Receipt
        self.assertEqual({k: v for k, v in self.counts.items() if k not in ("rows", "keep")},
                         {"ETF / ETN (00xx)": 3, "not a 4-digit stock code": 3, "TDR (-DR)": 1})

    def test_one_case_per_rule(self):
        cases = [("0050", "x", "ETF / ETN (00xx)"), ("0001", "x", "ETF / ETN (00xx)"),
                 ("00679B", "x", "ETF / ETN (00xx)"), ("1101B", "x", "not a 4-digit stock code"),
                 ("910322", "x-DR", "not a 4-digit stock code"), ("23170", "x", "not a 4-digit stock code"),
                 ("700019", "x", "not a 4-digit stock code"), ("", "x", "not a 4-digit stock code"),
                 ("9103", "Meide Medical-DR", "TDR (-DR)"), ("2317", "Hon Hai", "keep"), (" 2330 ", "TSMC", "keep"),
                 ("6488", "GlobalWafers", "keep"), ("1000", "x", "keep")]
        for code, name, want in cases:
            self.assertEqual(scan.classify_tw(code, name), want, code)

    def test_roc_dates(self):
        self.assertEqual(scan.roc_date("1151027"), "2026-10-27")
        self.assertIsNone(scan.roc_date("20261027"))
        self.assertIsNone(scan.roc_date(None))

    def test_not_a_list(self):
        with self.assertRaises(scan.ScanError):
            scan.parse_list("<html>maintenance</html>", "twse")
        with self.assertRaises(scan.ScanError):
            scan.parse_list('{"a": 1}', "twse")
        with self.assertRaises(scan.ScanError) as cm:
            scan.parse_list('[{"Code": "2317"}]', "tpex")
        self.assertIn("SecuritiesCompanyCode", str(cm.exception))
        with self.assertRaises(scan.ScanError):
            scan.build_universe({"twse.json": self.texts["twse.json"]})


class Time(unittest.TestCase):
    def test_taipei_has_no_daylight_time(self):
        self.assertEqual(scan.ts_to_taipei(OPEN_TS), DT(2026, 10, 19, 9, 0))
        self.assertEqual(scan.ts_to_taipei(ts("2026-12-01 09:00")), DT(2026, 12, 1, 9, 0))
        self.assertEqual(scan.ts_to_taipei(ts("2026-07-01 09:00")), DT(2026, 7, 1, 9, 0))
        self.assertEqual(scan.parse_now("2026-10-19 09:45"), DT(2026, 10, 19, 1, 45))
        self.assertEqual(scan.parse_now("2026-12-01 09:45"), DT(2026, 12, 1, 1, 45))
        self.assertEqual(scan.parse_now("2026-10-19T01:45:00Z"), DT(2026, 10, 19, 1, 45))
        self.assertEqual(scan.clock_label(DT(2026, 10, 19, 9, 45)), "9:45 AM")
        self.assertEqual(scan.clock_label(datetime.time(12, 5)), "12:05 PM")
        self.assertEqual(scan.clock_label(datetime.time(13, 30)), "1:30 PM")
        with self.assertRaises(scan.ScanError) as cm:
            scan.parse_now("tomorrow")
        self.assertIn("Taipei time", str(cm.exception))
        with self.assertRaises(scan.ScanError):
            scan.parse_hhmm("25:00")

    def test_the_session(self):
        self.assertEqual(scan.session(D(2026, 10, 19)), (datetime.time(9, 0), datetime.time(13, 30)))
        self.assertEqual(scan.session(D(2026, 12, 24)), (datetime.time(9, 0), datetime.time(13, 30)))   # no early close
        self.assertIsNone(scan.session(D(2026, 10, 17)))
        self.assertIsNone(scan.session(D(2026, 10, 26)))


class Spark(unittest.TestCase):
    def test_a_real_spark_answer(self):
        with open(LIVE, encoding="utf-8") as fh:
            text = fh.read()
        wanted = {scan.to_yahoo(s): s for s in ["2317.TW", "6488.TWO", "0050.TW", "ZZZZ.TW"]}
        data = scan.parse_spark(text, wanted)
        self.assertEqual(sorted(data), ["0050.TW", "2317.TW", "6488.TWO"])   # the dot stays: not 2317-TW
        t = data["2317.TW"]
        self.assertEqual(len(t["t"]), 62)
        self.assertIsNone(t["h"])                  # spark is closes only
        self.assertIsNone(t["c"][-1])              # the 2026-10-28 bar had no close yet
        self.assertEqual(t["c"][-2], 247.5)
        self.assertEqual(t["meta"]["regularMarketVolume"], 42224529)
        self.assertEqual(t["meta"]["currency"], "TWD")
        self.assertEqual(data["6488.TWO"]["meta"]["regularMarketPrice"], 849.0)
        self.assertEqual(scan.ts_to_taipei(t["t"][-1]), DT(2026, 10, 28, 9, 0))   # daily bars are stamped 09:00
        closes = scan.daily_closes(t, scan.parse_now("2026-10-29 06:00"))
        self.assertEqual(closes[-1], (D(2026, 10, 27), 247.5))      # the null bar is dropped
        self.assertEqual(scan.daily_closes(data["6488.TWO"], scan.parse_now("2026-10-29 06:00"))[-1],
                         (D(2026, 10, 27), 814.0))

    def test_spark_errors(self):
        too_many = '{"spark":{"result":null,"error":{"code":"Bad Request",' \
                   '"description":"Number of symbols needs to be less than or equal to 20"}}}'
        with self.assertRaises(scan.ScanError) as cm:
            scan.parse_spark(too_many)
        self.assertIn("less than or equal to 20", str(cm.exception))
        self.assertEqual(scan.parse_spark('{"spark":{"result":[],"error":null}}'), {})
        with self.assertRaises(scan.ScanError):
            scan.parse_spark('{"chart":{}}')

    def test_urls_keep_the_dot(self):
        self.assertEqual(scan.spark_path(["2317.tw", "6488.TWO"], "3mo", "1d"),
                         "/v7/finance/spark?symbols=2317.TW,6488.TWO&range=3mo&interval=1d")
        self.assertEqual(scan.chart_path("2317.TW", "1d", "5m"), "/v8/finance/chart/2317.TW?range=1d&interval=5m")
        self.assertEqual(scan.to_yahoo("6488.two"), "6488.TWO")

    def test_a_bare_code_is_refused(self):
        code, _, err = run(["daily", "--symbols", "2317,6488.TWO", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("2317 needs its market: 2317.TW (TWSE listed) or 2317.TWO (TPEx OTC)", err)


class RealFiveMinute(unittest.TestCase):
    """A real v8 chart of 2317.TW (2026-10-28): the closing print and a null bar."""

    def setUp(self):
        with open(REAL5, encoding="utf-8") as fh:
            self.s = scan.parse_chart(fh.read(), "2317.TW")
        self.day = D(2026, 10, 28)

    def test_the_closing_print_is_not_a_bar(self):
        self.assertEqual(scan.ts_to_taipei(self.s["t"][-1]), DT(2026, 10, 28, 13, 30))
        bars = scan.session_bars(self.s, self.day, DT(2026, 10, 28, 13, 35))
        self.assertEqual(bars[0]["start"], DT(2026, 10, 28, 9, 0))
        self.assertEqual(bars[-1]["start"], DT(2026, 10, 28, 13, 20))
        self.assertEqual(len(bars), 53)                 # the 13:25 bar has a null close
        self.assertFalse(scan.usable(bars, self.day, DT(2026, 10, 28, 13, 35), 3))
        self.assertTrue(scan.usable(scan.session_bars(self.s, self.day, DT(2026, 10, 28, 13, 25)),
                                    self.day, DT(2026, 10, 28, 13, 25), 3))

    def test_the_opening_range_of_the_real_day(self):
        cutoff = DT(2026, 10, 28, 10, 0)
        bars = scan.session_bars(self.s, self.day, cutoff)
        self.assertEqual(len(bars), 12)
        self.assertTrue(scan.usable(bars, self.day, cutoff, 3))
        rng = bars[:3]
        self.assertEqual(rng[0]["h"], 248.5)            # the 9:00 bar's real high
        self.assertEqual(rng[0]["l"], 246.5)            # and its real low


class Network(unittest.TestCase):
    """429s and 5xx without the network."""

    def setUp(self):
        self.calls, self.sleeps = [], []
        self._get, self._sleep = scan.http_get, scan.SLEEP
        scan.SLEEP = self.sleeps.append
        with open(LIVE, encoding="utf-8") as fh:
            self.body = fh.read()

    def tearDown(self):
        scan.http_get, scan.SLEEP = self._get, self._sleep

    def answers(self, codes):
        codes = list(codes)

        def fake(url, timeout=20):
            self.calls.append(url.split("/v")[0])
            code = codes.pop(0) if codes else 200
            if code != 200:
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            return self.body
        scan.http_get = fake

    def test_429_falls_back_then_waits_once(self):
        self.answers([429, 429, 200])
        text = scan.yahoo_get("/v7/finance/spark?symbols=2317.TW&range=3mo&interval=1d")
        self.assertEqual(text, self.body)
        self.assertEqual(self.calls, ["https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com",
                                      "https://query2.finance.yahoo.com"])
        self.assertEqual(self.sleeps, [scan.BACKOFF])

    def test_5xx_goes_to_query1_without_waiting(self):
        self.answers([503, 200])
        scan.yahoo_get("/v8/finance/chart/2317.TW?range=1d&interval=5m")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.sleeps, [])

    def test_429_for_good_is_reported_as_partial(self):
        self.answers([200] + [429] * 10)
        syms = ["2317.TW", "6488.TWO", "0050.TW"] + ["1%03d.TW" % i for i in range(37)]
        data, failed = scan.fetch_spark(syms, "3mo", "1d", 0.3)
        self.assertEqual(sorted(data), ["0050.TW", "2317.TW", "6488.TWO"])
        self.assertEqual(len(failed), 37)
        self.assertEqual(failed["1000.TW"], "no data from Yahoo")     # in the first batch, Yahoo did not know it
        self.assertIn("HTTP 429", failed["1030.TW"])                  # the second batch never got through
        self.assertEqual(self.sleeps, [0.3, scan.BACKOFF])  # a pause between batches, one backoff
        hits, counts, _ = scan.scan_daily(data, syms, scan.parse_now("2026-10-29 06:00"), 10, 1000000)
        self.assertEqual(counts["requested"], 40)
        self.assertEqual(counts["fetched"], 3)

    def test_a_404_is_final(self):
        self.answers([404])
        with self.assertRaises(scan.ScanError):
            scan.yahoo_get("/v8/finance/chart/9999.TW?range=1d&interval=5m")
        self.assertEqual(len(self.calls), 1)


class Daily(unittest.TestCase):
    # Built by a separate script from plain closes (rules re-implemented there): through Fri Oct 16 2026.
    EXPECT = {
        "1101.TW": ["breakout_20d"],      # 103.00 over a 20-day best of 101.00
        "1102.TW": ["breakout_20d"],      # 53.50 over 52.90
        "2002.TW": ["bull_flag"],         # 100 -> 112 over ten sessions, last 5 inside a 1.3 % range
        "2207.TW": ["reclaim_ma20"],      # 99.00 under its average, then 100.60 over it
        "2301.TW": ["oversold"],          # RSI 1.9 after a long slide
        "2303.TW": ["oversold"],          # RSI 2.0
        "2308.TW": ["oversold_bounce"],   # RSI 24.5 the day before, closed up to 35.6
        "2412.TW": ["breakout_20d"],      # 123.00 over 120.40, on thin volume
        "2610.TW": ["breakout_20d"],      # 9.20 over 8.60, under the price floor
    }
    RSI = {"1101.TW": 67.4, "1102.TW": 67.2, "2002.TW": 80.3, "2207.TW": 54.1, "2301.TW": 1.9, "2303.TW": 2.0,
           "2308.TW": 35.6, "2412.TW": 74.1, "2610.TW": 76.1}

    def setUp(self):
        self.data, self.errors = scan.load_offline(DAILY)
        self.syms = sorted(self.data)

    def test_setups_before_the_open(self):
        self.assertEqual(len(self.syms), 11)
        hits, counts, last = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 09:00"), 0, 0)
        self.assertEqual({h["symbol"]: h["setups"] for h in hits}, self.EXPECT)
        self.assertEqual(last, D(2026, 10, 16))
        self.assertEqual(counts, {"requested": 11, "fetched": 11, "illiquid": 0, "short": 1, "scanned": 10,
                                  "hits": 9})
        self.assertEqual({h["symbol"]: h["rsi"] for h in hits}, self.RSI)
        h = [h for h in hits if h["symbol"] == "1101.TW"][0]
        self.assertEqual((h["price"], h["rsi"], h["close_date"], h["volume"]), (103.0, 67.4, "2026-10-16", 8400000))
        # most dollars traded first: price x volume, worked out separately
        self.assertEqual([h["symbol"] for h in hits],
                         ["1101.TW", "2002.TW", "2301.TW", "2303.TW", "2207.TW", "1102.TW", "2308.TW", "2610.TW",
                          "2412.TW"])

    def test_the_in_progress_bar_is_dropped(self):
        before = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 09:00"), 0, 0)
        during = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 10:50"), 0, 0)
        self.assertEqual(before, during)
        bars = scan.daily_closes(self.data["1101.TW"], scan.parse_now("2026-10-19 13:29"))
        self.assertEqual(bars[-1], (D(2026, 10, 16), 103.0))
        bars = scan.daily_closes(self.data["1101.TW"], scan.parse_now("2026-10-19 13:30"))
        self.assertEqual(bars[-1], (D(2026, 10, 19), 104.03))

    def test_no_early_close_in_taiwan(self):
        s = {"t": [ts("2026-12-22 09:00"), ts("2026-12-24 09:00")], "c": [10.0, 11.0], "meta": {}}
        self.assertEqual(len(scan.daily_closes(s, scan.parse_now("2026-12-24 12:59"))), 1)
        self.assertEqual(len(scan.daily_closes(s, scan.parse_now("2026-12-24 13:29"))), 1)
        self.assertEqual(len(scan.daily_closes(s, scan.parse_now("2026-12-24 13:30"))), 2)

    def test_liquidity_filter(self):
        # the defaults: price at least 10, volume at least 1,000,000 shares
        hits, counts, _ = scan.scan_daily(self.data, self.syms, scan.parse_now("2026-10-19 10:50"), 10, 1000000)
        self.assertEqual(sorted(h["symbol"] for h in hits),
                         ["1101.TW", "1102.TW", "2002.TW", "2207.TW", "2301.TW", "2303.TW", "2308.TW"])
        self.assertEqual(counts["illiquid"], 2)     # 2610.TW under 10 TWD; 2412.TW under 1M shares
        self.assertEqual(counts["scanned"], 8)

    def test_short_and_empty_charts(self):
        s = {"t": [ts("2026-10-%02d 09:00" % d) for d in range(1, 11)], "c": [10.0] * 10,
             "meta": {"regularMarketPrice": 10, "regularMarketVolume": 5000000}}
        hits, counts, last = scan.scan_daily({"1000.TW": s, "1001.TW": {"t": [], "c": [], "meta": {}}},
                                             ["1000.TW", "1001.TW", "1002.TW"],
                                             scan.parse_now("2026-10-20 09:00"), 10, 1000000)
        self.assertEqual(hits, [])
        self.assertEqual((counts["fetched"], counts["short"], counts["illiquid"], counts["scanned"]), (2, 1, 1, 0))
        self.assertIsNone(last)

    def test_rsi_matches_the_reel_math(self):
        self.assertIsNone(scan.rsi([1.0] * 10))
        self.assertEqual(scan.rsi([float(x) for x in range(1, 40)]), 100.0)
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
                  46.28, 46.28]
        self.assertAlmostEqual(scan.rsi(closes), 70.46, places=1)  # Wilder's textbook example


class Orb(unittest.TestCase):
    # Hits worked out by a separate script from the bars (range = first three bars' highs and lows):
    #   1101.TW 28.40 closes 9:20, range 27.85-28.15 | 5871.TW 8.40 at 9:20 (under the 10 TWD floor)
    #   2330.TW 1,010 at 9:25 | 2317.TW 205.00 at 9:30, range 200.50-204.00 | 6488.TWO 858 at 9:35
    #   1102.TW 52.30 at 9:45 | 2454.TW and 2412.TW never close above the range high
    #   2882.TW misses its 9:15 bar, 3008.TW has no bars, 9999.TW has no data at all
    @classmethod
    def setUpClass(cls):
        cls.data, cls.errors = scan.load_offline(WALL)
        cls.syms = sorted(set(cls.data) | set(cls.errors))

    def scan_at(self, now, min_price=0, syms=None, or_minutes=15):
        day, cutoff = scan.orb_window(scan.parse_now(now), None, or_minutes, datetime.time(13, 0))
        return scan.scan_orb(self.data, syms or self.syms, day, cutoff, or_minutes, min_price, 0)

    def test_the_scan_at_0945(self):
        hits, counts, failed = self.scan_at("2026-10-19 09:45")
        self.assertEqual(len(self.syms), 11)
        self.assertEqual(counts["scanned"], 8)             # usable charts
        self.assertEqual(self.errors, {"9999.TW": "no data for 9999.TW: No data found, symbol may be delisted"})
        self.assertEqual(counts["unusable"], 2)            # 3008.TW (no bars), 2882.TW (a missing bar)
        self.assertEqual([h["symbol"] for h in hits],
                         ["1101.TW", "5871.TW", "2330.TW", "2317.TW", "6488.TWO", "1102.TW"])
        r = [h for h in hits if h["symbol"] == "2317.TW"][0]
        self.assertEqual(r, {"symbol": "2317.TW", "setups": ["orb"], "price": 205.0, "at": "9:30 AM",
                             "bar_start": "09:25", "bar_index": 5, "or_high": 204.0, "or_low": 200.5,
                             "pct_over": 0.49})
        self.assertEqual([h["at"] for h in hits], ["9:20 AM", "9:20 AM", "9:25 AM", "9:30 AM", "9:35 AM", "9:45 AM"])
        x = [h for h in hits if h["symbol"] == "1101.TW"][0]
        self.assertEqual((x["price"], x["or_high"], x["or_low"], x["pct_over"]), (28.4, 28.15, 27.85, 0.89))
        # at 09:45 the stage-one rule lets in 7 charts; 2412.TW closes at its range's top but never above its high
        self.assertEqual(counts["candidates"], 7)
        self.assertEqual(counts["confirmed"], 7)

    def test_price_floor(self):
        hits, counts, _ = self.scan_at("2026-10-19 09:45", min_price=10)
        self.assertEqual(len(hits), 5)                     # 5871.TW at 8.40 drops out
        self.assertEqual(counts["illiquid"], 1)
        self.assertNotIn("5871.TW", [h["symbol"] for h in hits])

    def test_in_progress_bar_and_no_breakout_yet(self):
        hits, _, _ = self.scan_at("2026-10-19 09:44", syms=["1102.TW"])
        self.assertEqual(hits, [])                         # the 9:40 bar is not done until 9:45
        hits, _, _ = self.scan_at("2026-10-19 09:45", syms=["1102.TW"])
        self.assertEqual(hits[0]["at"], "9:45 AM")

    def test_the_live_tick_is_dropped(self):
        s = self.data["2317.TW"]
        self.assertEqual(scan.ts_to_taipei(s["t"][-1]), DT(2026, 10, 19, 10, 2, 30))   # off the grid
        bars = scan.session_bars(s, D(2026, 10, 19), DT(2026, 10, 19, 10, 4))
        self.assertEqual(len(bars), 12)                    # 9:00 to 9:55; 10:00 in progress, the tick dropped
        self.assertTrue(scan.usable(bars, D(2026, 10, 19), DT(2026, 10, 19, 10, 4), 3))
        hits, _, _ = self.scan_at("2026-10-19 10:04", syms=["2317.TW"])
        self.assertEqual(hits[0]["price"], 205.0)          # still the first close above the range

    def test_ties_are_sorted_by_symbol(self):
        hits, _, _ = self.scan_at("2026-10-19 09:45")
        at_920 = [h["symbol"] for h in hits if h["at"] == "9:20 AM"]
        self.assertEqual(at_920, sorted(at_920))

    def test_stage_one_is_a_necessary_condition(self):
        day, cut = D(2026, 10, 19), DT(2026, 10, 19, 9, 45)
        for sym, s in self.data.items():
            bars = scan.session_bars(s, day, cut)
            if scan.usable(bars, day, cut, 3) and scan.orb_hit(bars, 3):
                self.assertTrue(scan.orb_candidate(bars, 3), sym)

    def test_confirm_uses_the_v8_highs(self):
        spark_like = {k: dict(v, h=None, l=None) for k, v in self.data.items()}  # closes only, like spark
        asked = []

        def confirm(sym):
            asked.append(sym)
            return self.data[sym]
        hits, counts, failed = scan.scan_orb(spark_like, self.syms, D(2026, 10, 19), DT(2026, 10, 19, 9, 45), 15,
                                             0, 0, confirm)
        self.assertEqual(len(hits), 6)
        self.assertEqual(counts["candidates"], len(asked))
        self.assertEqual(sorted(asked), ["1101.TW", "1102.TW", "2317.TW", "2330.TW", "2412.TW", "5871.TW",
                                         "6488.TWO"])      # 2454.TW never gets to the range top again

        def broken(sym):
            raise scan.ScanError("Yahoo answered HTTP 429 for /v8/finance/chart/%s" % sym)
        hits, counts, failed = scan.scan_orb(spark_like, ["2317.TW", "1101.TW"], D(2026, 10, 19),
                                             DT(2026, 10, 19, 9, 45), 15, 0, 0, broken)
        self.assertEqual(hits, [])
        self.assertIn("429", failed["2317.TW"])

    def test_a_missing_bar_makes_a_chart_unusable(self):
        s = bars_series("2026-10-20", [10, 10.2, 10.1, None, 10.5, 10.6, 10.7, 10.8, 10.9])
        bars = scan.session_bars(s, D(2026, 10, 20), DT(2026, 10, 20, 9, 45))
        self.assertFalse(scan.usable(bars, D(2026, 10, 20), DT(2026, 10, 20, 9, 45), 3))

    def test_a_30_minute_range_and_the_closing_print(self):
        # 9:00 to 9:30 range (six bars, high 101.4); the 9:30 bar closes 101.5, reported at 9:35
        closes = [100, 101, 100.5, 100.8, 101.2, 100.9, 101.5] + [101.0] * 40
        s = bars_series("2026-10-19", closes, highs=[c + 0.2 for c in closes],
                        extra=[("2026-10-19 13:30", 101.0)])
        hits, counts, _ = scan.scan_orb({"1101.TW": s}, ["1101.TW"], D(2026, 10, 19), DT(2026, 10, 19, 12, 0), 30, 0, 0)
        self.assertEqual(counts["scanned"], 1)
        self.assertEqual(hits[0]["at"], "9:35 AM")
        self.assertEqual(hits[0]["or_high"], 101.4)
        bars = scan.session_bars(s, D(2026, 10, 19), DT(2026, 10, 19, 13, 40))
        self.assertEqual(len(bars), 47)                    # 9:00 to 12:50; the 13:30 print is not a bar
        self.assertEqual(scan.ts_to_taipei(s["t"][0]), DT(2026, 10, 19, 9, 0))
        with self.assertRaises(scan.ScanError) as cm:
            scan.orb_window(scan.parse_now("2026-10-19 13:40"), None, 15, datetime.time(13, 0))
        self.assertIn("closed at 1:30 PM", str(cm.exception))

    def test_window_messages(self):
        until = datetime.time(13, 0)

        def msg(now, at=None, until=until):
            with self.assertRaises(scan.ScanError) as cm:
                scan.orb_window(scan.parse_now(now), at, 15, until)
            return str(cm.exception)
        self.assertIn("weekend", msg("2026-10-17 10:15"))
        self.assertIn("TWSE holiday: Taiwan Retrocession Day", msg("2026-10-26 10:15"))
        self.assertIn("Run orb again after 9:20 AM", msg("2026-10-19 09:10"))
        self.assertIn("Run orb again after 9:20 AM", msg("2026-10-19 09:17"))
        self.assertIn("runs 9:00 to 9:15", msg("2026-10-19 09:10"))
        self.assertIn("expired", msg("2026-10-19 13:10"))
        self.assertIn("expired", msg("2026-10-19 11:30", until=datetime.time(11, 0)))
        self.assertIn("closed at 1:30 PM", msg("2026-10-19 13:35"))
        self.assertIn("later than now", msg("2026-10-19 09:30", at=datetime.time(9, 45)))
        self.assertIn("after the 1:30 PM close", msg("2026-10-19 15:00", at=datetime.time(14, 0)))
        self.assertEqual(scan.orb_window(scan.parse_now("2026-10-19 15:00"), datetime.time(9, 45), 15, until),
                         (D(2026, 10, 19), DT(2026, 10, 19, 9, 45)))
        self.assertEqual(scan.orb_window(scan.parse_now("2026-10-19 09:20"), None, 15, until)[1],
                         DT(2026, 10, 19, 9, 20))
        with self.assertRaises(scan.ScanError):
            scan.orb_window(scan.parse_now("2026-10-19 09:45"), None, 7, until)


class StageTwoCap(unittest.TestCase):
    def test_stage_two_cap_takes_the_most_traded(self):
        data, _ = scan.load_offline(WALL)
        spark_like = {k: dict(v, h=None, l=None) for k, v in data.items()}
        asked = []

        def confirm(sym):
            asked.append(sym)
            return data[sym]
        day, cut = D(2026, 10, 19), DT(2026, 10, 19, 9, 45)
        hits, counts, _ = scan.scan_orb(spark_like, sorted(data), day, cut, 15, 0, 0, confirm, max_confirm=3)
        self.assertEqual((counts["confirmed"], counts["unconfirmed"]), (3, 4))
        # price x volume so far: 2330.TW 6.4e9, 2317.TW 8.7e8, 1102.TW 4.4e8 (worked out separately)
        self.assertEqual(asked, ["2330.TW", "2317.TW", "1102.TW"])
        self.assertEqual([h["symbol"] for h in hits], ["2330.TW", "2317.TW", "1102.TW"])
        hits_all, _, _ = scan.scan_orb(spark_like, sorted(data), day, cut, 15, 0, 0, confirm, max_confirm=0)
        self.assertEqual(len(hits_all), 6)
        for h in hits:
            self.assertIn(h, hits_all)


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.t = os.path.join(self.d, "trader")
        self.wl = os.path.join(self.t, "watchlist.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_universe_daily_orb_end_to_end(self):
        uni = os.path.join(self.t, "universe.txt")
        code, text, _ = run(["universe", "--offline", LISTS, "--out", uni])
        self.assertEqual(code, 0)
        self.assertIn("Kept 7 listed and OTC 4-digit common stocks", text)
        self.assertIn("3 ETF / ETN (00xx)", text)
        with open(uni, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(len(lines), 7)
        self.assertEqual([ln.split("|")[0] for ln in lines],
                         ["1101.TW", "2317.TW", "2330.TW", "2412.TW", "3293.TWO", "6488.TWO", "8069.TWO"])

        # daily over that universe with the synthetic charts: only 1101, 2317 and 2412 are in both, so partial
        code, text, _ = run(["daily", "--universe", uni, "--offline", DAILY, "--now", "2026-10-19 09:00",
                             "--out", self.wl, "--min-volume", "0", "--min-price", "0"])
        self.assertEqual(code, 0)
        self.assertIn("Fetched 3 of 7 charts (4 failed or had no data)", text)
        self.assertIn("Taipei", text)
        doc = self.read(self.wl)
        self.assertEqual((doc["mode"], doc["universe"], doc["scanned"], doc["failed"]), ("daily", 7, 3, 4))
        self.assertEqual(doc["hits"][0], {"symbol": "1101.TW", "setups": ["breakout_20d"], "price": 103.0,
                                          "close_date": "2026-10-16", "rsi": 67.4, "volume": 8400000})
        self.assertEqual([h["symbol"] for h in doc["hits"]], ["1101.TW", "2412.TW"])
        self.assertEqual(doc["as_of"], "2026-10-16 close")

        # the 9:45 scan
        code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-10-19 09:45", "--min-price", "0",
                             "--out", self.wl])
        self.assertEqual(code, 0)
        self.assertIn("6 of 8 charts closed above their opening-range high by 9:45 AM", text)
        self.assertIn("9:30 AM  2317.TW       205.00  range 200.50 to 204.00  +0.49% over", text)
        self.assertIn("not a list of stocks to buy", text)
        self.assertNotIn("$", text)
        doc = self.read(self.wl)
        self.assertEqual({k: doc[k] for k in ("created_by", "created_at", "mode", "as_of", "universe", "scanned",
                                              "source")},
                         {"created_by": "trader-scanner", "created_at": "2026-10-19T01:45:00Z", "mode": "orb",
                          "as_of": "2026-10-19 09:45 Taipei", "universe": 11, "scanned": 8, "source": "yahoo"})
        self.assertEqual(len(doc["hits"]), 6)
        self.assertIn({"symbol": "2317.TW", "setups": ["orb"], "price": 205.0, "at": "9:30 AM", "bar_start": "09:25",
                       "bar_index": 5, "or_high": 204.0, "or_low": 200.5, "pct_over": 0.49}, doc["hits"])

        # the hits read back as a watchlist, with --at instead of --now
        code, text, _ = run(["orb", "--offline", WALL, "--at", "09:45", "--watchlist", self.wl, "--min-price", "0",
                             "--json", "--no-write"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual((out["universe"], out["scanned"], len(out["hits"])), (6, 6, 6))

    def test_partial_stage_two_is_said(self):
        """The networked path with a fake Yahoo that answers from the synthetic bundle."""
        bundle = json.loads(scan._read_maybe_gz(WALL))
        calls = []

        def get(path):
            calls.append(path)
            if path.startswith("/v7/finance/spark"):
                res = []
                for y in path.split("symbols=")[1].split("&")[0].split(","):
                    r = ((bundle.get(y) or {}).get("chart") or {}).get("result")
                    if r:
                        closes = r[0]["indicators"]["quote"][0].get("close", [])
                        res.append({"symbol": y, "response": [dict(r[0], indicators={"quote": [{"close": closes}]})]})
                return json.dumps({"spark": {"result": res, "error": None}})
            return json.dumps(bundle[path.split("/chart/")[1].split("?")[0]])
        old_get, old_sleep, real_now = scan.yahoo_get, scan.SLEEP, scan.parse_now
        scan.yahoo_get, scan.SLEEP = get, (lambda s: None)
        scan.parse_now = lambda text: real_now(text or "2026-10-19 09:50")  # the machine clock, pinned
        uni = os.path.join(self.d, "u.txt")
        with open(uni, "w") as fh:
            fh.write("\n".join(sorted(bundle)) + "\n")
        try:
            code, text, _ = run(["orb", "--universe", uni, "--now", "2026-10-19 09:45", "--min-price", "0",
                                 "--max-confirm", "3", "--no-write"])
        finally:
            scan.yahoo_get, scan.SLEEP, scan.parse_now = old_get, old_sleep, real_now
        self.assertEqual(code, 0)
        self.assertIn("8 usable; 7 candidates, 3 confirmed", text)
        self.assertIn("PARTIAL: 4 more candidates were not checked", text)
        self.assertIn("3 of the 3 checked charts closed above their opening-range high by 9:45 AM", text)
        self.assertEqual(sum(1 for c in calls if c.startswith("/v8/")), 3)
        self.assertEqual(sum(1 for c in calls if c.startswith("/v7/")), 1)   # 11 symbols, 20 a request
        self.assertTrue(all("range=1d&interval=5m" in c for c in calls))
        self.assertTrue(all("2317-TW" not in c for c in calls))

    def test_plain_messages_and_exit_codes(self):
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-17 10:15", "--out", self.wl])
        self.assertEqual(code, 1)
        self.assertIn("No session on Sat 2026-10-17 (weekend)", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(self.wl))
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-19 09:14", "--out", self.wl])
        self.assertIn("after 9:20 AM", err)
        cfg = os.path.join(self.t, "config.json")
        os.makedirs(self.t)
        with open(cfg, "w") as fh:
            json.dump({"no_entries_after": "09:30"}, fh)
        code, _, err = run(["orb", "--offline", WALL, "--now", "2026-10-19 09:45", "--config", cfg])
        self.assertEqual(code, 1)
        self.assertIn("expired", err)
        code, _, err = run(["orb", "--offline", WALL])
        self.assertIn("--at HH:MM", err)
        code, text, _ = run(["orb", "--offline", WALL, "--now", "2026-10-19 09:40", "--symbols", "1102.TW",
                             "--out", self.wl])
        self.assertEqual(code, 1)                          # no breakout yet, but the empty list is written
        self.assertIn("No chart closed above its opening-range high by 9:40 AM", text)
        self.assertEqual(self.read(self.wl)["hits"], [])
        code, _, err = run(["daily", "--universe", os.path.join(self.d, "nope.txt")])
        self.assertEqual(code, 1)
        self.assertIn("scan.py universe", err)
        code, _, err = run(["daily", "--offline", os.path.join(self.d, "nothing-here")])
        self.assertIn("no offline file", err)
        empty = os.path.join(self.d, "empty.json")
        with open(empty, "w") as fh:
            fh.write("{}")
        code, _, err = run(["daily", "--offline", empty])
        self.assertEqual(code, 1)
        self.assertIn("no symbols to scan", err)

    def test_offline_folder_of_v8_files(self):
        folder = os.path.join(self.d, "charts")
        os.makedirs(folder)
        bundle = json.loads(scan._read_maybe_gz(WALL))
        for sym in ("2317.TW", "1101.TW", "2412.TW", "9999.TW"):
            with open(os.path.join(folder, sym + ".json"), "w") as fh:
                json.dump(bundle[sym], fh)
        code, text, _ = run(["orb", "--offline", folder, "--now", "2026-10-19 09:45", "--no-write", "--json",
                             "--min-price", "0"])
        out = json.loads(text)
        self.assertEqual((out["universe"], out["scanned"], out["failed"]), (4, 3, 1))
        self.assertEqual([h["symbol"] for h in out["hits"]], ["1101.TW", "2317.TW"])
        self.assertEqual(code, 0)

    def test_symbol_lists(self):
        txt = os.path.join(self.d, "list.txt")
        with open(txt, "w") as fh:
            fh.write("# my list\n2317.TW|Hon Hai\n1101.tw\n\n2317.TW\n")
        self.assertEqual(scan.symbols_from_file(txt), ["2317.TW", "1101.TW", "2317.TW"])
        js = os.path.join(self.d, "wl.json")
        with open(js, "w") as fh:
            json.dump({"hits": [{"symbol": "2317.tw"}, {"symbol": "6488.TWO"}]}, fh)
        self.assertEqual(scan.symbols_from_file(js), ["2317.TW", "6488.TWO"])
        code, text, _ = run(["daily", "--offline", DAILY, "--watchlist", txt, "--now", "2026-10-19 09:00",
                             "--json", "--no-write", "--min-volume", "0"])
        out = json.loads(text)
        self.assertEqual((out["universe"], out["scanned"]), (2, 2))
        code, text, _ = run(["daily", "--offline", DAILY, "--limit", "3", "--now", "2026-10-19 09:00", "--json",
                             "--no-write", "--min-volume", "0"])
        self.assertEqual(json.loads(text)["universe"], 3)

    def test_daily_json(self):
        code, text, _ = run(["daily", "--offline", DAILY, "--now", "2026-10-19 09:00", "--json", "--no-write",
                             "--min-volume", "0", "--min-price", "0"])
        self.assertEqual(code, 0)
        out = json.loads(text)
        self.assertEqual(len(out["hits"]), 9)
        self.assertEqual(out["note"], "A scan is a list of charts that match a rule, not a list of stocks to buy.")
        # the defaults (price 10, 1,000,000 shares) drop the thin and the cheap
        code, text, _ = run(["daily", "--offline", DAILY, "--now", "2026-10-19 09:00", "--json", "--no-write"])
        self.assertEqual(len(json.loads(text)["hits"]), 7)


if __name__ == "__main__":
    unittest.main()
