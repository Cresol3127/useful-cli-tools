import datetime
import hashlib
import os
import re
import uuid
from pathlib import Path
import caldav
from icalendar import Calendar, Event as IcalEvent, Todo as IcalTodo
from calcure.data import UserEvent, Task, Status, Frequency


class Privacy:
    PUBLIC = False
    PRIVATE = True

TIME_PREFIX_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\s*-\s*(\d{1,2}):(\d{2}))?\s+(.+)$")


class LocalRadicaleEvent:
    def __init__(self, path: Path, data: str):
        self.path = path
        self.data = data

    def delete(self):
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception:
            pass


class LocalRadicaleCalendar:
    def __init__(self, col_dir: Path):
        self.dir = col_dir

    def events(self):
        result = []
        if not self.dir.is_dir():
            return result
        for file in self.dir.glob("*.ics"):
            try:
                data = file.read_text(encoding="utf-8")
                result.append(LocalRadicaleEvent(file, data))
            except Exception:
                pass
        return result

    def save_event(self, ical_str: str):
        try:
            ical = Calendar.from_ical(ical_str)
            uid = None
            for comp in ical.walk("VEVENT"):
                uid = comp.get("UID")
                if uid:
                    uid = str(uid)
                    break
        except Exception:
            uid = None
        if not uid:
            uid = str(uuid.uuid4())
        path = self.dir / f"{uid}.ics"
        path.write_text(ical_str, encoding="utf-8")
        return LocalRadicaleEvent(path, ical_str)


class RadicaleStorage:
    def __init__(self, cf):
        self.enabled = getattr(cf, "RADICALE_ENABLED", True)
        self.url = os.environ.get("RADICALE_URL", getattr(cf, "RADICALE_URL", ""))
        self.username = os.environ.get("RADICALE_USERNAME", getattr(cf, "RADICALE_USERNAME", ""))
        self.password = os.environ.get("RADICALE_PASSWORD", getattr(cf, "RADICALE_PASSWORD", ""))
        self.calendar_name = os.environ.get("RADICALE_CALENDAR", getattr(cf, "RADICALE_CALENDAR", ""))
        self._calendar = None
        self._remote_event_hashes = {}  # uid -> (hash, caldav_obj)
        self._remote_todo_hashes = {}   # uid -> (hash, caldav_obj)

    def connect(self):
        if not self.enabled:
            return None
        if self._calendar is not None:
            return self._calendar

        # 1. Try remote CalDAV server if url is specified and not "local"
        if self.url and self.url != "local":
            try:
                client = caldav.DAVClient(
                    url=self.url,
                    username=self.username or None,
                    password=self.password or None,
                )
                principal = client.principal()
                calendars = principal.calendars()
                if not calendars:
                    self._calendar = principal.make_calendar(name=self.calendar_name or "Official")
                elif self.calendar_name:
                    self._calendar = next(
                        (c for c in calendars if self.calendar_name.lower() in (c.name or "").lower() or self.calendar_name.lower() in str(c.url).lower()),
                        calendars[0],
                    )
                else:
                    self._calendar = calendars[0]
                if self._calendar:
                    return self._calendar
            except Exception:
                pass

        # 2. Local Radicale collections fallback if remote CalDAV failed or was unauthorized
        user = self.username or os.environ.get("USER", "user")
        local_base = Path.home() / ".local/share/radicale/collections/collection-root" / user
        if local_base.is_dir():
            target_dir = None
            target_name = (self.calendar_name or "Official").lower()
            for col in local_base.iterdir():
                if not col.is_dir():
                    continue
                props_file = col / ".Radicale.props"
                display_name = col.name
                if props_file.exists():
                    try:
                        import json
                        props = json.loads(props_file.read_text(encoding="utf-8"))
                        display_name = props.get("D:displayname", display_name)
                    except Exception:
                        pass
                if target_name in display_name.lower() or target_name in col.name.lower():
                    target_dir = col
                    break
            if not target_dir:
                dirs = [d for d in local_base.iterdir() if d.is_dir()]
                if dirs:
                    target_dir = dirs[0]

            if target_dir:
                self._calendar = LocalRadicaleCalendar(target_dir)
                return self._calendar

        return None

    @staticmethod
    def _event_signature(year: int, month: int, day: int, name: str, status, privacy) -> str:
        raw = f"{year:04d}-{month:02d}-{day:02d}|{name}|{status}|{privacy}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def load_events(self, user_events):
        cal = self.connect()
        if not cal:
            return
        self._remote_event_hashes.clear()
        user_events.items.clear()
        item_id = 0

        for obj in cal.events():
            try:
                ical = Calendar.from_ical(obj.data)
            except Exception:
                continue
            for comp in ical.walk("VEVENT"):
                uid = str(comp.get("UID", uuid.uuid4()))
                summary = str(comp.get("SUMMARY", "Untitled"))
                dtstartProp = comp.get("DTSTART")
                if not dtstartProp:
                    continue
                dt = dtstartProp.dt
                dtendProp = comp.get("DTEND")
                dtend = dtendProp.dt if dtendProp else None

                if isinstance(dt, datetime.datetime):
                    local_dt = dt.astimezone()
                    if isinstance(dtend, datetime.datetime):
                        local_end = dtend.astimezone()
                        display_name = f"{local_dt.strftime('%H:%M')}-{local_end.strftime('%H:%M')} {summary}"
                    else:
                        display_name = f"{local_dt.strftime('%H:%M')} {summary}"
                    year, month, day = local_dt.year, local_dt.month, local_dt.day
                else:
                    display_name = summary
                    year, month, day = dt.year, dt.month, dt.day

                priority = int(comp.get("PRIORITY", 0) or 0)
                status = Status.IMPORTANT if priority in (1, 2, 3) else Status.NORMAL
                clas = str(comp.get("CLASS", "PUBLIC")).upper()
                privacy = Privacy.PRIVATE if clas == "PRIVATE" else Privacy.PUBLIC

                ev = UserEvent(
                    item_id, year, month, day, display_name,
                    1, Frequency.ONCE, status, privacy
                )
                ev.uid = uid
                user_events.items.append(ev)
                self._remote_event_hashes[uid] = (
                    self._event_signature(year, month, day, display_name, status, privacy),
                    obj,
                )
                item_id += 1

    def sync_events(self, user_events):
        cal = self.connect()
        if not cal:
            return
        seen_uids = set()

        for ev in user_events.items:
            uid = getattr(ev, "uid", None) or str(uuid.uuid4())
            ev.uid = uid
            seen_uids.add(uid)
            sig = self._event_signature(ev.year, ev.month, ev.day, ev.name, ev.status, ev.privacy)

            if uid in self._remote_event_hashes and self._remote_event_hashes[uid][0] == sig:
                continue  # Unchanged

            ical_str = self._build_vevent_ical(uid, ev.year, ev.month, ev.day, ev.name, ev.status, ev.privacy)
            if uid in self._remote_event_hashes:
                try:
                    self._remote_event_hashes[uid][1].delete()
                except Exception:
                    pass
            saved_obj = cal.save_event(ical_str)
            self._remote_event_hashes[uid] = (sig, saved_obj)

        # Delete any events removed via 'x' in calcure (works for both All-Day and Timed)
        removed_uids = set(self._remote_event_hashes.keys()) - seen_uids
        for uid in removed_uids:
            try:
                self._remote_event_hashes[uid][1].delete()
            except Exception:
                pass
            self._remote_event_hashes.pop(uid, None)

    @staticmethod
    def _build_vevent_ical(uid: str, year: int, month: int, day: int, raw_name: str, status, privacy) -> str:
        cal = Calendar()
        cal.add("prodid", "-//calcure-radicale//EN")
        cal.add("version", "2.0")

        ev = IcalEvent()
        ev.add("uid", uid)
        ev.add("dtstamp", datetime.datetime.now(datetime.timezone.utc))

        match = TIME_PREFIX_RE.match(raw_name)
        if match:
            sh, sm, eh, em, clean_title = match.groups()
            start_dt = datetime.datetime(year, month, day, int(sh), int(sm)).astimezone()
            if eh is not None and em is not None:
                end_dt = datetime.datetime(year, month, day, int(eh), int(em)).astimezone()
            else:
                end_dt = start_dt + datetime.timedelta(hours=1)
            ev.add("dtstart", start_dt)
            ev.add("dtend", end_dt)
            ev.add("summary", clean_title)
        else:
            # All-Day Event (VALUE=DATE)
            start_date = datetime.date(year, month, day)
            ev.add("dtstart", start_date)
            ev.add("dtend", start_date + datetime.timedelta(days=1))
            ev.add("summary", raw_name.strip())

        if status == Status.IMPORTANT:
            ev.add("priority", 1)
        if privacy == Privacy.PRIVATE:
            ev.add("class", "PRIVATE")

        cal.add_component(ev)
        return cal.to_ical().decode("utf-8")
