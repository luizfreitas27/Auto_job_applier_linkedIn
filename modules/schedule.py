'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

**Schedule windows**: weekday-and-time spans during which the control panel runs the bot on
its own. This module is the pure part: parsing and validating windows, deciding whether a
moment falls inside one, and turning that into start/stop decisions. The control panel
(app.py) owns the clock, the thread and the bot process.

Windows are stored in the `schedule` section of user_config.json as
`{"windows": [{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:30"}, ...]}` with
days 0 = Monday ... 6 = Sunday, in the machine's local time. A window whose end is before
its start spans midnight ("22:00" to "02:00") and belongs to the day it starts on. Start and
end may not be equal: that would be a 24-hour window, far more likely a typo.
'''

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, time

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class ScheduleWindow:
    '''One window: the weekdays it starts on (0 = Monday) and its start and end as "HH:MM".'''
    days: tuple[int, ...]
    start: str
    end: str

    def as_dict(self) -> dict:
        '''JSON shape, days as a list.'''
        data = asdict(self)
        data["days"] = list(self.days)
        return data

    @property
    def spans_midnight(self) -> bool:
        '''True when the window ends on the following day.'''
        return _parse_time(self.end) < _parse_time(self.start)


def _parse_time(text: str) -> time:
    '''"HH:MM" as a time, or ValueError.'''
    match = _TIME.match(text or "")
    if not match:
        raise ValueError(f'Time must be "HH:MM" (24-hour), got {text!r}')
    return time(int(match.group(1)), int(match.group(2)))


def parse_windows(raw: object) -> list[ScheduleWindow]:
    '''
    Validate the JSON the panel sends or the config holds and return windows. Raises
    ValueError with a message meant for the user when anything is off: not a list, a window
    with no days, an unknown day, a malformed time, or a start equal to its end.
    '''
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Schedule windows must be a list")
    windows = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Window {index} must be an object")
        days = item.get("days")
        if not isinstance(days, list) or not days:
            raise ValueError(f"Window {index} needs at least one weekday")
        cleaned = []
        for day in days:
            if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
                raise ValueError(f"Window {index}: weekdays are 0 (Monday) to 6 (Sunday)")
            if day not in cleaned:
                cleaned.append(day)
        start, end = item.get("start"), item.get("end")
        for label, value in (("start", start), ("end", end)):
            try:
                _parse_time(value)
            except ValueError as err:
                raise ValueError(f"Window {index} {label}: {err}") from None
        if _parse_time(start) == _parse_time(end):
            raise ValueError(f"Window {index}: start and end are the same time; a window must last at least a minute")
        windows.append(ScheduleWindow(days=tuple(sorted(cleaned)), start=start, end=end))
    return windows


def window_is_active(windows: list[ScheduleWindow], now: datetime) -> bool:
    '''
    True when `now` (local time) falls inside any window. A window that spans midnight is
    active from its start on one of its days until its end on the following day; "end" is
    exclusive, "start" inclusive.
    '''
    moment = now.time().replace(second=0, microsecond=0)
    today = now.weekday()
    yesterday = (today - 1) % 7
    for window in windows:
        start, end = _parse_time(window.start), _parse_time(window.end)
        if not window.spans_midnight:
            if today in window.days and start <= moment < end:
                return True
        else:
            if today in window.days and moment >= start:
                return True
            if yesterday in window.days and moment < end:
                return True
    return False


def decide(active_now: bool, active_before: bool | None) -> str | None:
    '''
    What the scheduler should do on this tick, given whether a window is active now and
    whether one was on the previous tick (None on the very first tick): "start" on entering
    a window (or when the panel comes up inside one), "stop" on leaving, else None.
    Edge-triggered on purpose: a bot that finished on its own or was stopped by hand inside a
    window is not restarted until the next window begins.
    '''
    if active_now and not active_before:
        return "start"
    if active_before and not active_now:
        return "stop"
    return None
