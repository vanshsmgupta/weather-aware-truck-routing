from unittest import TestCase

from trips.services import hos

H = 3600


class ElapsedTests(TestCase):
    def test_no_stops_in_the_first_eight_hours(self):
        self.assertEqual(hos.elapsed(0), 0)
        self.assertEqual(hos.elapsed(8 * H), 8 * H)

    def test_thirty_minute_break_after_eight_hours(self):
        self.assertEqual(hos.elapsed(8 * H + 60), 8.5 * H + 60)
        self.assertEqual(hos.elapsed(11 * H), 11.5 * H)

    def test_ten_hour_reset_after_eleven_hours(self):
        self.assertEqual(hos.elapsed(12 * H), 12 * H + 10.5 * H)
        self.assertEqual(hos.elapsed(20 * H), 20 * H + 10.5 * H + 0.5 * H)

    def test_disabled_returns_drive_time(self):
        self.assertEqual(hos.elapsed(30 * H, enabled=False), 30 * H)


class StopsTests(TestCase):
    def test_short_trip_has_no_stops(self):
        self.assertEqual(hos.stops(7 * H), [])

    def test_stops_follow_the_driving_clock(self):
        self.assertEqual(
            hos.stops(20 * H),
            [("break", 8 * H, 1800), ("rest", 11 * H, 10 * H), ("break", 19 * H, 1800)],
        )

    def test_no_rest_when_arriving_exactly_at_the_limit(self):
        self.assertEqual(hos.stops(11 * H), [("break", 8 * H, 1800)])

    def test_stop_times_match_elapsed(self):
        for _, at, length in hos.stops(30 * H):
            self.assertEqual(hos.elapsed(at + 1) - hos.elapsed(at), length + 1)
