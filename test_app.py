import os
import unittest

os.environ.update(MYKID_UID="A" * 64, ACCESS_TOKEN="secret-token")

import app  # noqa: E402


def event(summary, start, end, all_day=False):
    kind = ";VALUE=DATE" if all_day else ";TZID=Europe/Oslo"
    return (
        f"BEGIN:VEVENT\r\nUID:{summary}-{start}\r\nDTSTART{kind}:{start}\r\n"
        f"DTEND{kind}:{end}\r\nSUMMARY:{summary}\r\nEND:VEVENT\r\n"
    )


def feed(*events):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:MyKid\r\n"
        + "".join(events)
        + "END:VCALENDAR\r\n"
    )


def summaries(ics):
    return [line[8:] for line in ics.split("\r\n") if line.startswith("SUMMARY:")]


class CleanTest(unittest.TestCase):
    def test_drops_weekly_routines_but_keeps_one_offs(self):
        weekly = [event("Gymrom gr. 1", f"202611{d:02d}T093000", f"202611{d:02d}T110000") for d in (2, 9, 16)]
        out = app.clean(feed(*weekly, event("Nissefest", "20261217", "20261218", all_day=True)))
        self.assertEqual(summaries(out), ["Nissefest"])

    def test_title_variants_count_as_the_same_routine(self):
        out = app.clean(feed(
            event("Gymrom gruppe 1", "20261102T093000", "20261102T110000"),
            event("Gymrom gr. 1", "20261109T093000", "20261109T110000"),
            event("Gymrom  GR. 1", "20261116T093000", "20261116T110000"),
        ))
        self.assertEqual(summaries(out), [])

    def test_merges_all_day_runs_across_short_gaps(self):
        # 24.-27. Dec (Christmas + weekend) are missing from the feed: a 4-day gap.
        days = [("20261222", "20261223"), ("20261223", "20261224"), ("20261228", "20261229")]
        out = app.clean(feed(*(event("Juleferie", s, e, all_day=True) for s, e in days)))
        self.assertEqual(summaries(out), ["Juleferie"])
        self.assertIn("DTEND;VALUE=DATE:20261229", out)

    def test_renames_calendar(self):
        self.assertIn("X-WR-CALNAME:MyKid (viktig)", app.clean(feed()))


class RoutingTest(unittest.TestCase):
    def test_token_route_maps_to_configured_uid(self):
        self.assertEqual(app.uid_for("/secret-token.ics"), "A" * 64)

    def test_any_uid_and_pasted_whitespace(self):
        uid = "b" * 64
        self.assertEqual(app.uid_for(f"/{uid}.ics"), uid)
        self.assertEqual(app.uid_for(f"/{uid}.ics%20"), uid)

    def test_rejects_junk(self):
        for path in ("/", "/nope.ics", "/../etc/passwd", "/short.ics"):
            self.assertIsNone(app.uid_for(path))


if __name__ == "__main__":
    unittest.main()
