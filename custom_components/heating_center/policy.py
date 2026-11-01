"""Pure, hardware-agnostic room control policies; no Home Assistant imports."""
from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
import re

DAYS = ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')


def valid_temp(value, minimum=5.0, maximum=30.0):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(result, 1) if isfinite(result) and minimum <= result <= maximum else None


def schedule_target(schedule: dict, now: datetime, fallback: float) -> float:
    for days_back in range(8):
        weekday = (now.weekday()-days_back)%7
        choices = []
        for row in schedule.get(str(weekday), []):
            try:
                hour, minute = map(int, str(row['time']).split(':'))
                temp = valid_temp(row['temp'])
                if temp is None or not (0 <= hour < 24 and 0 <= minute < 60):
                    continue
                if days_back == 0 and (hour, minute) > (now.hour, now.minute):
                    continue
                choices.append((hour*60+minute,temp))
            except (KeyError, ValueError, TypeError):
                continue
        if choices:
            return max(choices)[1]
    return fallback


def next_schedule_change(schedule: dict, now: datetime):
    chosen = None
    for day_offset in range(8):
        date = (now+timedelta(days=day_offset)).date()
        for row in schedule.get(str(date.weekday()), []):
            try:
                hour, minute = map(int, str(row['time']).split(':'))
                if not (0<=hour<24 and 0<=minute<60):
                    continue
                moment = datetime.combine(date, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=hour,minute=minute)
                if moment>now and (chosen is None or moment<chosen):
                    chosen=moment
            except (KeyError, ValueError, TypeError):
                continue
    return chosen


def resolve_target(room: dict, mode: str, now: datetime, *, window=False, preheat=None):
    """Return temperature and winning rule. Safety floor is never below 5 C."""
    floor = valid_temp(room.get('frost_temp', 8)) or 8
    if window:
        return max(floor, valid_temp(room.get('window_temp', 12)) or 12), 'window'
    if mode == 'vacation':
        return max(floor, valid_temp(room.get('vacation_temp', 12)) or 12), 'vacation'
    if mode == 'away':
        return max(floor, valid_temp(room.get('away_temp', 16)) or 16), 'away'
    end = room.get('override_until')
    if room.get('override_temp') is not None and end:
        try:
            if datetime.fromisoformat(end) > now:
                return max(floor, float(room['override_temp'])), 'override'
        except (ValueError, TypeError):
            pass
    if preheat is not None and room.get('adaptive_start'):
        return max(floor, preheat), 'adaptive_start'
    if room.get('schedule_enabled'):
        return max(floor, schedule_target(room.get('schedule',{}), now, room.get('target',19))), 'schedule'
    return max(floor, float(room.get('target',19))), 'base'


def room_target(room: dict, global_mode: str, now: datetime) -> float:
    return resolve_target(room,global_mode,now,window=room.get('window_open',False))[0]


def is_locked(value):
    return str(value).strip().lower() in {'lock','locked','on','true','1'}


def needs_restore(actual, desired, tolerance=0.25):
    try:
        v = float(actual)
        return isfinite(v) and abs(v-float(desired))>tolerance
    except (ValueError,TypeError):
        return False


def validate_schedule(schedule):
    if not isinstance(schedule, dict):
        raise ValueError('Wochenplan muss ein Objekt sein')
    out={}
    for day in range(7):
        rows=schedule.get(str(day),[])
        if not isinstance(rows,list) or len(rows)>24:
            raise ValueError('Pro Tag sind höchstens 24 Schaltzeiten möglich')
        clean=[]
        for item in rows:
            if not isinstance(item,dict) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(item.get('time',''))):
                raise ValueError('Ungültige Uhrzeit im Wochenplan')
            temp=valid_temp(item.get('temp'))
            if temp is None:
                raise ValueError('Ungültige Temperatur im Wochenplan')
            clean.append({'time':item['time'],'temp':temp})
        times=[x['time'] for x in clean]
        if len(times)!=len(set(times)):
            raise ValueError('Doppelte Uhrzeit im Wochenplan')
        out[str(day)]=sorted(clean,key=lambda x:x['time'])
    return out


def native_sonoff_schedule(schedule: dict, day: int, fallback: float) -> str:
    """Z2M TRVZB string format with max six 0.5C-step transitions and 00:00 boundary."""
    entries = sorted(schedule.get(str(day), []), key=lambda x:x['time'])
    if len(entries)>6:
        raise ValueError('Sonoff unterstützt höchstens sechs Schaltpunkte pro Tag')
    vals=[]
    if not entries or entries[0]['time']!='00:00':
        previous = schedule_target(schedule, datetime(2026,11,2+day,0,0), fallback)
        vals.append(('00:00',previous))
    vals += [(e['time'], e['temp']) for e in entries]
    if len(vals)>6:
        raise ValueError('Sonoff unterstützt höchstens sechs Schaltpunkte pro Tag einschließlich 00:00')
    if any((valid_temp(t,4,35) is None or abs(t*2-round(t*2))>0.01) for _,t in vals):
        raise ValueError('Sonoff verlangt 0,5 °C Schritte')
    return ' '.join(f'{clock}/{value:g}' for clock,value in vals)


def recommend_preheat_minutes(current: float, next_target: float, rate_c_per_hour: float,
                              outside=None, max_minutes=120) -> int:
    """Conservative learning estimate; does not pretend to know burner behavior."""
    if next_target<=current or rate_c_per_hour<=0:
        return 0
    rate = max(.15,min(3.,rate_c_per_hour))
    if outside is not None and outside<0:
        rate*=.85
    return max(0,min(int(max_minutes),round(60*(next_target-current)/rate)))
