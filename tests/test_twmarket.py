import datetime
import unittest
from decimal import Decimal

from _load import load

tw = load("trader-risk", "twmarket")


class Time(unittest.TestCase):
    def test_taipei_is_utc_plus_8(self):
        self.assertEqual(tw.to_taipei(datetime.datetime(2026, 10, 19, 1, 30)), datetime.datetime(2026, 10, 19, 9, 30))
        self.assertEqual(tw.taipei_to_utc(datetime.datetime(2026, 10, 19, 9, 30)), datetime.datetime(2026, 10, 19, 1, 30))
        # 1792371600 is 09:00 Taipei on 2026-10-19 (synthetic fixture clock)
        self.assertEqual(tw.ts_to_taipei(1792371600), datetime.datetime(2026, 10, 19, 9, 0))

    def test_parse_now(self):
        want = datetime.datetime(2026, 10, 19, 1, 30)
        for text in ("2026-10-19 09:30", "2026-10-19 09:30:00", "2026-10-19 09:30 TPE", "2026-10-19 09:30 Taipei",
                     "2026-10-19T01:30:00Z", "2026-10-19T09:30:00+08:00", "2026-10-19 01:30Z"):
            self.assertEqual(tw.parse_now(text), want, text)
        self.assertEqual(tw.parse_now("2026-10-19"), datetime.datetime(2026, 10, 18, 16, 0))

    def test_parse_now_time_only_is_today_in_taipei(self):
        got = tw.parse_now("09:30")
        self.assertEqual(tw.to_taipei(got).time(), datetime.time(9, 30))

    def test_parse_now_rejects_junk(self):
        for bad in ("", "tomorrow", "2026-13-40 09:30", "25:99"):
            with self.assertRaises(tw.TWError) as cm:
                tw.parse_now(bad)
            self.assertIn("Taipei time", str(cm.exception))

    def test_trading_day(self):
        self.assertEqual(tw.trading_day(datetime.date(2026, 10, 19)), (True, ""))
        self.assertEqual(tw.trading_day(datetime.date(2026, 10, 17)), (False, "weekend"))
        ok, why = tw.trading_day(datetime.date(2026, 10, 26))
        self.assertFalse(ok)
        self.assertTrue(why.startswith("TWSE holiday: "), why)
        self.assertFalse(tw.trading_day(datetime.date(2026, 2, 12))[0])  # settlement only, no trading

    def test_holiday_list_has_only_weekdays_and_known_year(self):
        for iso in tw.TWSE_HOLIDAYS:
            d = datetime.date.fromisoformat(iso)
            self.assertLess(d.weekday(), 5, iso)
            self.assertTrue(tw.calendar_known(d))
        self.assertFalse(tw.calendar_known(datetime.date(2027, 1, 4)))

    def test_session_and_next_open(self):
        o, c = tw.session(datetime.date(2026, 10, 19))
        self.assertEqual((o.hour, o.minute, c.hour, c.minute), (9, 0, 13, 30))
        self.assertEqual(tw.next_open(datetime.datetime(2026, 10, 19, 14, 0)), "2026-10-20 09:00")
        self.assertEqual(tw.next_open(datetime.datetime(2026, 10, 19, 8, 0)), "2026-10-19 09:00")
        self.assertEqual(tw.next_open(datetime.datetime(2026, 10, 23, 14, 0)), "2026-10-27 09:00")  # weekend
        self.assertEqual(tw.next_open(datetime.datetime(2026, 10, 23, 14, 0) + datetime.timedelta(days=0)), "2026-10-27 09:00")
        self.assertEqual(tw.next_open(datetime.datetime(2026, 10, 9 - 1, 14, 0)), "2026-10-12 09:00")  # 10-09 is a holiday


class Prices(unittest.TestCase):
    def test_tick_size_bands(self):
        cases = [("0.99", "0.01"), ("9.99", "0.01"), ("10", "0.05"), ("49.95", "0.05"), ("50", "0.1"),
                 ("99.9", "0.1"), ("100", "0.5"), ("499.5", "0.5"), ("500", "1"), ("999", "1"), ("1000", "5"),
                 ("2500", "5")]
        for p, t in cases:
            self.assertEqual(tw.tick_size(p), Decimal(t), p)

    def test_round_tick(self):
        self.assertEqual(tw.round_tick(205.3, "down"), Decimal("205.00"))
        self.assertEqual(tw.round_tick(205.3, "up"), Decimal("205.50"))
        self.assertEqual(tw.round_tick(205.25, "nearest"), Decimal("205.50"))
        self.assertEqual(tw.round_tick(205.2, "nearest"), Decimal("205.00"))
        self.assertEqual(tw.round_tick(9.994, "down"), Decimal("9.99"))
        # the tick comes from the band of the number given, not of the result
        self.assertEqual(tw.round_tick(99.96, "up"), Decimal("100.00"))
        with self.assertRaises(tw.TWError):
            tw.round_tick(10, "sideways")

    def test_on_tick(self):
        self.assertTrue(tw.on_tick(205.0))
        self.assertTrue(tw.on_tick(205.5))
        self.assertFalse(tw.on_tick(205.3))
        self.assertTrue(tw.on_tick(10.05))
        self.assertFalse(tw.on_tick(10.01))

    def test_limit_prices(self):
        for prev, down, up in [(200, "180.00", "220.00"), (96, "86.40", "105.50"), (9.99, "9.00", "10.95"),
                               (1000, "900.00", "1100.00")]:
            self.assertEqual(tw.limit_prices(prev), (Decimal(down), Decimal(up)), prev)


class Lots(unittest.TestCase):
    def test_valid_qty(self):
        for q in (1000, 2000, 1, 999, 500):
            self.assertTrue(tw.valid_qty(q), q)
        for q in (0, -1000, 1001, 1500, 2500, 1000.5, "1000", None):
            self.assertFalse(tw.valid_qty(q), q)
        self.assertFalse(tw.valid_qty(500, allow_odd=False))
        self.assertTrue(tw.valid_qty(3000, allow_odd=False))

    def test_floor_qty(self):
        self.assertEqual(tw.floor_qty(1369), 1000)
        self.assertEqual(tw.floor_qty(2999), 2000)
        self.assertEqual(tw.floor_qty(999), 999)
        self.assertEqual(tw.floor_qty(999, allow_odd=False), 0)
        self.assertEqual(tw.floor_qty(0), 0)

    def test_lot_words(self):
        self.assertEqual(tw.lot_words(1000), "1 board lot")
        self.assertEqual(tw.lot_words(3000), "3 board lots")
        self.assertEqual(tw.lot_words(500), "odd lot of 500 shares")
        self.assertEqual(tw.lot_words(1), "odd lot of 1 share")


class Costs(unittest.TestCase):
    # Expected values were worked out on their own with exact fractions: fee = ceil(notional x 0.1425% x 0.6),
    # minimum 20; tax = ceil(sell notional x 0.15%).
    # Pinned to the synthetic session date so the halved day-trade tax applies whatever today is.
    D = {"trade_date": "2026-10-19"}

    def test_broker_fee(self):
        self.assertEqual(tw.broker_fee(205000), 176)
        self.assertEqual(tw.broker_fee(202000), 173)
        self.assertEqual(tw.broker_fee(1000), 20)
        self.assertEqual(tw.broker_fee(0), 0)
        self.assertEqual(tw.broker_fee(205000, {"fee_discount": 1.0}), 293)   # 292.125 rounded up
        self.assertEqual(tw.broker_fee(1000, {"min_fee_twd": 1}), 1)

    def test_sell_tax(self):
        self.assertEqual(tw.sell_tax(202000, self.D), 303)
        self.assertEqual(tw.sell_tax(211000, self.D), 317)     # 316.5 rounded up
        self.assertEqual(tw.sell_tax(202000, rate_key="sell_tax_pct"), 606)
        self.assertEqual(tw.sell_tax(0, self.D), 0)

    def test_trade_costs(self):
        self.assertEqual(tw.trade_costs(1000, 205, 202, self.D),
                         {"buy_fee": 176, "sell_fee": 173, "tax": 303, "total": 652})
        # a short sale pays the tax on the OPENING sell
        short = tw.trade_costs(1000, 205, 208, self.D, side="sell")
        self.assertEqual(short["tax"], 308)  # 205000 x 0.15% = 307.5 rounded up

    def test_loss_at_stop(self):
        self.assertEqual(tw.loss_at_stop(1000, 205, 202, self.D), 3652)
        self.assertEqual(tw.loss_at_stop(2000, 205, 202, self.D), 7303)

    def test_net_reward(self):
        # 1000 x 6.00 = 6000 less fees 176 + 181 and tax 317
        self.assertEqual(tw.net_reward(1000, 205, 211, self.D), 5326)

    def test_max_qty_for_loss(self):
        self.assertEqual(tw.max_qty_for_loss(5000, 205, 202, self.D), 1369)
        self.assertLessEqual(tw.loss_at_stop(1369, 205, 202, self.D), 5000)
        self.assertGreater(tw.loss_at_stop(1370, 205, 202, self.D), 5000)
        self.assertEqual(tw.max_qty_for_loss(5000, 205, 205, self.D), 0)
        self.assertEqual(tw.max_qty_for_loss(10, 205, 202, self.D), 0)

    def test_max_qty_for_cash(self):
        self.assertEqual(tw.max_qty_for_cash(450000, 205), 2193)
        self.assertEqual(tw.max_qty_for_cash(0, 205), 0)

    def test_round_trip_cost_pct(self):
        # 1000 x 205: fees 176 + 176, tax 308 (307.5 rounded up) = 660 on 205,000 = 0.3220 percent
        self.assertAlmostEqual(tw.round_trip_cost_pct(205, self.D), 660 / 205000 * 100, places=6)

    def test_cost_params_defaults(self):
        self.assertEqual(tw.cost_params({})["fee_discount"], 0.6)
        self.assertEqual(tw.cost_params({"fee_discount": 1})["fee_discount"], 1)


class Symbols(unittest.TestCase):
    def test_yahoo_symbol(self):
        self.assertEqual(tw.yahoo_symbol("2317.tw"), "2317.TW")
        self.assertEqual(tw.yahoo_symbol(" 6488.two "), "6488.TWO")
        self.assertEqual(tw.yahoo_symbol("DEMO.TW"), "DEMO.TW")
        with self.assertRaises(tw.TWError) as cm:
            tw.yahoo_symbol("2317")
        self.assertIn("2317.TW (TWSE listed) or 2317.TWO (TPEx OTC)", str(cm.exception))
        with self.assertRaises(tw.TWError):
            tw.yahoo_symbol("TSLA.US")

    def test_stock_problem(self):
        self.assertIsNone(tw.stock_problem("2317.TW"))
        self.assertIsNone(tw.stock_problem("6488.TWO"))
        self.assertIn("ETF", tw.stock_problem("0050.TW"))
        self.assertIsNotNone(tw.stock_problem("00679B.TWO"))
        self.assertIsNotNone(tw.stock_problem("23170.TW"))
        self.assertIsNotNone(tw.stock_problem("TSLA"))



class OddLotCosts(unittest.TestCase):
    # An odd lot (1 to 999 shares) cannot be day traded, so its sell leg pays the normal 0.3% tax.
    # Expected values worked out on their own with Decimal (see _loss below).
    D = {"trade_date": "2026-10-19"}

    @staticmethod
    def _loss(q, entry, stop, rate):
        ceil = lambda x: int(x.to_integral_value(rounding="ROUND_CEILING"))
        fee = lambda n: max(20, ceil(n * Decimal("0.001425") * Decimal("0.6")))
        e, s = Decimal(str(entry)), Decimal(str(stop))
        return ceil(q * abs(e - s)) + fee(q * e) + fee(q * s) + ceil(q * s * Decimal(rate) / 100)

    def test_odd_lot_pays_the_normal_sell_tax(self):
        self.assertTrue(tw.is_odd_lot(999))
        self.assertFalse(tw.is_odd_lot(1000))
        self.assertFalse(tw.is_odd_lot(0))
        # 500 x 202 = 101,000 x 0.3% = 303; fees 88 + 87; 1,500 at the stop
        self.assertEqual(tw.trade_costs(500, 205, 202, self.D),
                         {"buy_fee": 88, "sell_fee": 87, "tax": 303, "total": 478})
        self.assertEqual(tw.loss_at_stop(500, 205, 202, self.D), 1978)
        self.assertEqual(tw.loss_at_stop(500, 205, 202, self.D), self._loss(500, 205, 202, "0.3"))
        self.assertEqual(tw.loss_at_stop(999, 205, 202, self.D), self._loss(999, 205, 202, "0.3"))
        self.assertEqual(tw.loss_at_stop(1000, 205, 202, self.D), self._loss(1000, 205, 202, "0.15"))
        # margin mode and the date do not matter for an odd lot
        self.assertEqual(tw.loss_at_stop(500, 205, 202, {"trade_date": "2028-01-03"}), 1978)
        # 500 x 6.00 = 3,000 less fees 88 + 91 and tax 317 (105,500 x 0.3% = 316.5 rounded up)
        self.assertEqual(tw.net_reward(500, 205, 211, self.D), 2504)
        # 500 x 205: fees 88 + 88, tax 308 (307.5 rounded up) = 484 on 102,500
        self.assertAlmostEqual(tw.round_trip_cost_pct(205, self.D, qty=500), 484 / 102500 * 100, places=6)
        self.assertIn("0.3% normal sell tax", tw.cost_tax_words(500, self.D))
        self.assertIn("halved through", tw.cost_tax_words(1000, self.D))

    def test_max_qty_for_loss_across_the_board_lot_boundary(self):
        # 999 shares lose 3,952 (0.3% tax) but 1,000 lose only 3,652 (0.15%): the loss drops at 1,000
        self.assertEqual(tw.loss_at_stop(999, 205, 202, self.D), 3952)
        self.assertEqual(tw.max_qty_for_loss(3700, 205, 202, self.D), 1013)
        self.assertEqual(tw.max_qty_for_loss(3651, 205, 202, self.D), 923)

    def test_max_qty_for_loss_matches_brute_force(self):
        for entry, stop in ((205, 202), (205, 190), (50.5, 49.8), (980, 960)):
            risk = abs(Decimal(str(entry)) - Decimal(str(stop)))
            top = 3000
            losses = [0] + [tw.loss_at_stop(q, entry, stop, self.D) for q in range(1, top + 1)]
            for cap in range(0, int(risk * 2500), max(1, int(risk * 2500) // 120)):
                want = max(q for q in range(top + 1) if losses[q] <= cap)
                self.assertEqual(tw.max_qty_for_loss(cap, entry, stop, self.D), want, (entry, stop, cap))


class DayTradeTax(unittest.TestCase):
    # Expected values worked out on their own with Decimal: tax = ceil(sell notional x rate / 100),
    # fee = ceil(notional x 0.001425 x 0.6), minimum 20.
    MARGIN = {"day_trade_mode": "margin_daytrade", "trade_date": "2026-10-19"}

    def test_margin_day_trade_pays_the_full_rate(self):
        self.assertEqual(tw.sell_tax(202000, self.MARGIN), 606)          # 202000 x 0.3% = 606
        self.assertEqual(tw.day_trade_tax_pct(self.MARGIN), Decimal("0.3"))
        # fees 176 + 173, tax 606
        self.assertEqual(tw.trade_costs(1000, 205, 202, self.MARGIN),
                         {"buy_fee": 176, "sell_fee": 173, "tax": 606, "total": 955})
        self.assertEqual(tw.loss_at_stop(1000, 205, 202, self.MARGIN), 3955)
        self.assertEqual(tw.max_qty_for_loss(5000, 205, 202, self.MARGIN), 1264)
        self.assertIn("margin/short", tw.day_trade_tax_words(self.MARGIN))

    def test_cash_rate_is_halved_through_the_cutoff_then_reverts(self):
        self.assertEqual(tw.DAY_TRADE_TAX_HALVED_UNTIL, "2027-12-31")
        self.assertEqual(tw.sell_tax(202000, {"trade_date": "2027-12-31"}), 303)
        self.assertEqual(tw.sell_tax(202000, {"trade_date": "2028-01-03"}), 606)
        self.assertEqual(tw.sell_tax(202000, trade_date=datetime.date(2028, 1, 3)), 606)
        self.assertEqual(tw.loss_at_stop(1000, 205, 202, {"trade_date": "2028-01-03"}), 3955)
        # the cutoff is a config key
        self.assertEqual(tw.sell_tax(202000, {"trade_date": "2028-01-03",
                                              "day_trade_tax_halved_until": "2028-12-31"}), 303)
        self.assertIn("halved through 2027-12-31", tw.day_trade_tax_words({"trade_date": "2026-10-19"}))
        self.assertIn("ended 2027-12-31", tw.day_trade_tax_words({"trade_date": "2028-01-03"}))
        # 1000 x 205: fees 176 + 176, tax 615 = 967 on 205,000
        self.assertAlmostEqual(tw.round_trip_cost_pct(205, None, "2028-01-03"), 967 / 205000 * 100, places=6)

    def test_bad_mode_or_date_is_refused(self):
        self.assertIn("day_trade_mode", tw.cost_problem({"day_trade_mode": "intraday"}))
        self.assertIsNone(tw.cost_problem({}))
        self.assertIsNotNone(tw.cost_problem({"day_trade_tax_halved_until": "end of 2027"}))
        with self.assertRaises(tw.TWError):
            tw.sell_tax(202000, {"day_trade_mode": "intraday"})


if __name__ == "__main__":
    unittest.main()
