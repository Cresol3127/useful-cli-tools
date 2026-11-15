"""Unit tests for two-way Radicale CalDAV sync and time parsing."""

import datetime
import tempfile
import unittest
from pathlib import Path
from icalendar import Calendar

from calcure.radicale import RadicaleStorage, LocalRadicaleCalendar, TIME_PREFIX_RE
from calcure.data import UserEvent, Events, Status, Frequency, Privacy
from calcure.configuration import Config


class RadicaleSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="radicale-test-")
        self.col_path = Path(self.temp_dir.name)

        class MockConfig:
            RADICALE_ENABLED = True
            RADICALE_URL = ""
            RADICALE_USERNAME = "testuser"
            RADICALE_PASSWORD = ""
            RADICALE_CALENDAR = "TestCalendar"

        self.cf = MockConfig()
        self.storage = RadicaleStorage(self.cf)
        self.storage._calendar = LocalRadicaleCalendar(self.col_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_time_prefix_regex(self):
        m1 = TIME_PREFIX_RE.match("14:30 Team Standup")
        self.assertIsNotNone(m1)
        self.assertEqual(m1.group(1), "14")
        self.assertEqual(m1.group(2), "30")
        self.assertIsNone(m1.group(3))
        self.assertEqual(m1.group(5), "Team Standup")

        m2 = TIME_PREFIX_RE.match("10:00 - 11:30 Architecture Review")
        self.assertIsNotNone(m2)
        self.assertEqual(m2.group(1), "10")
        self.assertEqual(m2.group(2), "00")
        self.assertEqual(m2.group(3), "11")
        self.assertEqual(m2.group(4), "30")
        self.assertEqual(m2.group(5), "Architecture Review")

        m3 = TIME_PREFIX_RE.match("All Day Holiday")
        self.assertIsNone(m3)

    def test_build_vevent_all_day(self):
        raw_ical = RadicaleStorage._build_vevent_ical(
            "uid-all-day", 2026, 11, 20, "Holiday Celebration", Status.NORMAL, Privacy.PUBLIC
        )
        cal = Calendar.from_ical(raw_ical)
        events = [c for c in cal.walk("VEVENT")]
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(str(ev.get("UID")), "uid-all-day")
        self.assertEqual(str(ev.get("SUMMARY")), "Holiday Celebration")
        dtstart = ev.get("DTSTART").dt
        self.assertIsInstance(dtstart, datetime.date)
        self.assertNotIsInstance(dtstart, datetime.datetime)
        self.assertEqual(dtstart, datetime.date(2026, 11, 20))

    def test_build_vevent_timed(self):
        raw_ical = RadicaleStorage._build_vevent_ical(
            "uid-timed", 2026, 11, 20, "15:00-16:30 Design Review", Status.IMPORTANT, Privacy.PRIVATE
        )
        cal = Calendar.from_ical(raw_ical)
        events = [c for c in cal.walk("VEVENT")]
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(str(ev.get("UID")), "uid-timed")
        self.assertEqual(str(ev.get("SUMMARY")), "Design Review")
        self.assertEqual(int(ev.get("PRIORITY")), 1)
        self.assertEqual(str(ev.get("CLASS")), "PRIVATE")
        dtstart = ev.get("DTSTART").dt
        self.assertIsInstance(dtstart, datetime.datetime)
        self.assertEqual(dtstart.hour, 15)
        self.assertEqual(dtstart.minute, 0)
        dtend = ev.get("DTEND").dt
        self.assertEqual(dtend.hour, 16)
        self.assertEqual(dtend.minute, 30)

    def test_two_way_sync_lifecycle(self):
        user_events = Events()

        # 1. Add event in memory
        ev1 = UserEvent(0, 2026, 11, 15, "10:00 Morning Sync", 1, Frequency.ONCE, Status.NORMAL, Privacy.PUBLIC)
        ev1.uid = "test-uid-1"
        user_events.items.append(ev1)

        # 2. Sync to storage
        self.storage.sync_events(user_events)
        created_file = self.col_path / "test-uid-1.ics"
        self.assertTrue(created_file.exists())

        # 3. Reload in a new Events instance
        reloaded = Events()
        self.storage.load_events(reloaded)
        self.assertEqual(len(reloaded.items), 1)
        self.assertEqual(reloaded.items[0].uid, "test-uid-1")
        self.assertIn("Morning Sync", reloaded.items[0].name)

        # 4. Modify event
        reloaded.items[0].name = "11:00 Rescheduled Sync"
        self.storage.sync_events(reloaded)

        # 5. Verify update
        cal = Calendar.from_ical(created_file.read_text(encoding="utf-8"))
        summary = str(list(cal.walk("VEVENT"))[0].get("SUMMARY"))
        self.assertEqual(summary, "Rescheduled Sync")

        # 6. Delete event
        reloaded.items.clear()
        self.storage.sync_events(reloaded)
        self.assertFalse(created_file.exists())


if __name__ == "__main__":
    unittest.main()
