"""Enhanced heating orchestration, diagnostics, data-driven preheat and Wolf telemetry.

Important: No Wolf eBUS writing, burner control, or safety system overrides.
"""
from __future__ import annotations
import asyncio
import logging
import time
from collections import deque
from copy import deepcopy
from datetime import timedelta
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from .manager import HeatingManager
from .const import STALE_SENSOR_SECONDS
from .policy import (
    valid_temp, resolve_target, next_schedule_change, schedule_target,
    recommend_preheat_minutes, native_sonoff_schedule, validate_schedule,
)

_LOGGER = logging.getLogger(__name__)
DEFAULT_SETTINGS = {
    "presence_entity": "", "presence_auto": False, "outside_entity": "",
    "notify_service": "", "notify_enabled": False, "notify_cooldown_minutes": 120,
    "quiet_start": "22:00", "quiet_end": "07:00",
    "vacation_from": "", "vacation_to": "",
    "wolf_entities": {"flow_temp":"", "return_temp":"", "boiler_temp":"", "dhw_temp":"",
                      "burner":"", "modulation":"", "fault":"", "outside":""},
}
DEFAULT_PROFILES={"comfort":21.0,"eco":18.0,"night":17.0,"boost":23.0}

class AdvancedHeatingManager(HeatingManager):
    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self.settings=deepcopy(DEFAULT_SETTINGS)
        self.history={}
        self._samples={}
        self._rates={}
        self._outstanding={}
        self._ack_failures={}
        self._battery_history={}
        self._last_notify=0.
        self._last_notice_signature=''
        self._last_history_save=0.
        self._last_history_sample=0.
        self._previous_non_vacation_mode='home'
        self._presence_last_changed=0.
        self._last_preheat={}
        self._last_demand_update=0.0

    async def async_start(self):
        data=await self.store.async_load() or {}
        self.settings={**deepcopy(DEFAULT_SETTINGS), **data.get('settings',{})}
        self.history=data.get('history',{})
        self._rates=data.get('rates',{})
        self._previous_non_vacation_mode=data.get('previous_mode','home')
        self._battery_history=data.get('battery_history',{})
        await super().async_start()
        self._update_watch()

    def _storage_snapshot(self):
        """Materialize a consistent, serializable persisted Heating Center state."""
        return {
            'rooms': deepcopy(self.rooms), 'mode': self.mode,
            'settings': deepcopy(self.settings),
            'history': deepcopy(self.history), 'rates': deepcopy(self._rates),
            'battery_history': deepcopy(self._battery_history),
            'previous_mode': self._previous_non_vacation_mode,
        }

    def _save(self):
        self.store.async_delay_save(self._storage_snapshot, 2)

    async def async_flush(self):
        """Persist confirmed configuration writes before reporting success."""
        await self.store.async_save(self._storage_snapshot())

    def _update_watch(self):
        super()._update_watch()
        for key in ('presence_entity','outside_entity'):
            if self.settings.get(key): self._watched.add(self.settings[key])
        for ent in self.settings.get('wolf_entities',{}).values():
            if ent: self._watched.add(ent)
        for room in self.rooms.values():
            for key in ('lqi','valve','person','outdoor'):
                if room.get(key): self._watched.add(room[key])
            for mapping in ('native_schedules',):
                self._watched.update(v for week in room.get(mapping,{}).values() for v in week.values())

    @callback
    def _on_event(self,event):
        super()._on_event(event)
        entity=event.data.get('entity_id')
        if not self._active or entity not in self._watched: return
        if entity==self.settings.get('presence_entity'):
            self._presence_last_changed=time.monotonic()
        for room_id,room in self.rooms.items():
            if room.get('enabled') and entity in {room.get('lqi'),room.get('valve'),room.get('person')}:
                self._queue(room_id)
        self._confirm_acks()

    def _get_measured(self,room):
        if room.get('sensor'):
            measured=self._valid_sensor(room)
            if measured is not None: return measured
        # For demand and charts only: the independent control path falls back to the TRV sensor.
        for climate in room.get('climates',[]):
            state=self._state(climate)
            if state:
                temp=valid_temp(state.attributes.get('current_temperature'),-20,60)
                if temp is not None: return temp
        return None

    def _outside(self,room=None):
        entity=(room or {}).get('outdoor') or self.settings.get('outside_entity')
        st=self._state(entity)
        return valid_temp(st.state,-40,55) if st else None

    def _target(self,room):
        now=dt_util.now()
        window=self._window(room)
        preheat=None
        rid=room.get('id','')
        if self.mode=='home' and not window and room.get('adaptive_start') and room.get('schedule_enabled'):
            next_event=next_schedule_change(room.get('schedule',{}),now)
            measured=self._get_measured(room)
            if next_event is not None and measured is not None:
                next_target=schedule_target(room.get('schedule',{}),next_event,room.get('target',19))
                current=schedule_target(room.get('schedule',{}),now,room.get('target',19))
                if next_target>=current+.5:
                    lead=recommend_preheat_minutes(measured,next_target,self._rates.get(rid,.7),
                          self._outside(room),int(room.get('max_preheat_minutes',120)))
                    until=(next_event-now).total_seconds()/60
                    self._last_preheat[rid]={'minutes':lead,'next_target':next_target,'starts_in':round(until-lead)}
                    if 0<=until<=lead and measured<next_target-.2:
                        preheat=next_target
                else:
                    self._last_preheat.pop(rid,None)
        target, _=resolve_target(room,self.mode,now,window=window,preheat=preheat)
        return round(target*2)/2

    def _target_reason(self,room):
        now=dt_util.now()
        preheat=None
        rid=room.get('id','')
        value=self._last_preheat.get(rid)
        if value and value.get('starts_in',1)<=0 and self.mode=='home' and room.get('adaptive_start'):
            preheat=value['next_target']
        return resolve_target(room,self.mode,now,window=self._window(room),preheat=preheat)[1]

    def _confirm_acks(self):
        for key,ack in list(self._outstanding.items()):
            if key.startswith('temp:'):
                st=self._state(key[5:])
                actual=valid_temp(st.attributes.get('temperature')) if st else None
                if actual is not None and abs(actual-ack['expected'])<=.25:
                    self._outstanding.pop(key,None)
                    self._ack_failures.pop(key,None)
            elif key.startswith('lock:'):
                st=self._state(key[5:])
                if st and str(st.state).lower() in ('on','lock','locked','true','1'):
                    self._outstanding.pop(key,None)
                    self._ack_failures.pop(key,None)

    async def _call(self,domain,service,data,key):
        if key.startswith(('temp:','lock:')):
            ack=self._outstanding.get(key)
            if ack:
                elapsed=time.monotonic()-ack['sent']
                expected=data.get('temperature',True)
                # New authorized targets must not be blocked by stale acknowledgements.
                if ack['expected'] != expected:
                    self._outstanding.pop(key,None)
                    ack=None
                elif elapsed<120:
                    return False
                elif ack['attempts']>=4 and time.monotonic()-ack['first']<3600:
                    return False
        ok=await super()._call(domain,service,data,key)
        if ok and key.startswith(('temp:','lock:')):
            prev=self._outstanding.get(key,{})
            self._outstanding[key]={
                'expected':data.get('temperature',True),
                'first':prev.get('first',time.monotonic()),
                'sent':time.monotonic(),'attempts':prev.get('attempts',0)+1,
            }
        return ok

    @callback
    def _on_tick(self,now):
        self._auto_modes()
        self._record_samples()
        self._confirm_acks()
        super()._on_tick(now)
        if self.settings.get('notify_enabled'):
            self.hass.async_create_task(self._notify_warnings())

    def _auto_modes(self):
        now=dt_util.now()
        start=self.settings.get('vacation_from')
        end=self.settings.get('vacation_to')
        if start and end:
            try:
                start_date=dt_util.parse_datetime(start)
                end_date=dt_util.parse_datetime(end)
                if start_date and end_date:
                    start_local=dt_util.as_local(start_date)
                    end_local=dt_util.as_local(end_date)
                    if start_local<=now<end_local:
                        if self.mode!='vacation':
                            self._previous_non_vacation_mode=self.mode
                            self.mode='vacation';self._save()
                        return
                    if now>=end_local and self.mode=='vacation':
                        self.mode=self._previous_non_vacation_mode
                        self.settings['vacation_from']=''
                        self.settings['vacation_to']=''
                        self._save()
            except (ValueError,TypeError): pass
        if self.settings.get('presence_auto') and self.mode in ('home','away'):
            # Debounce presence dropouts for >=5 min; never override manual vacation.
            if time.monotonic()-self._presence_last_changed<300: return
            st=self._state(self.settings.get('presence_entity'))
            if st and st.state not in ('unknown','unavailable'):
                desired='home' if st.state in ('home','on') else 'away'
                if desired!=self.mode:
                    self.mode=desired;self._save()

    def _record_samples(self):
        stamp=time.time()
        if stamp-self._last_history_sample<300: return
        self._last_history_sample=stamp
        for rid,room in self.rooms.items():
            if not room.get('enabled'): continue
            current=self._get_measured(room)
            if current is None: continue
            target=self._target(room)
            bucket=self.history.setdefault(rid,[])
            prev=bucket[-1] if bucket else None
            bucket.append([int(stamp),current,target])
            cutoff=stamp-7*86400
            while bucket and bucket[0][0]<cutoff: bucket.pop(0)
            if len(bucket)>2100: del bucket[:-2100]
            if prev and current>prev[1]+.05 and target>=current and not self._window(room):
                hours=(stamp-prev[0])/3600
                if .05<=hours<=1:
                    rate=(current-prev[1])/hours
                    if .15<=rate<=3.0:
                        old=self._rates.get(rid,.7)
                        self._rates[rid]=round(.85*old+.15*rate,3)
            battery=self._state(room.get('battery'))
            if battery and battery.state not in ('unknown','unavailable'):
                try:
                    val=float(battery.state)
                    if 0<=val<=100:
                        arr=self._battery_history.setdefault(rid,[])
                        if not arr or stamp-arr[-1][0]>=86400: arr.append([int(stamp),val])
                        self._battery_history[rid]=arr[-90:]
                except (TypeError,ValueError): pass
        self._save()

    def _compute_warnings(self):
        super()._compute_warnings()
        for rid,room in self.rooms.items():
            if not room.get('enabled'): continue
            warnings=self._warnings.setdefault(rid,[])
            lqi=self._state(room.get('lqi'))
            if lqi and lqi.state not in ('unknown','unavailable'):
                try:
                    if float(lqi.state)<int(room.get('lqi_warning',40)):
                        warnings.append('Zigbee-Signalqualität niedrig (LQI '+lqi.state+')')
                except (TypeError,ValueError): pass
            for entity in room.get('climates',[]):
                for kind in ('temp:','lock:'):
                    key=kind+(entity if kind=='temp:' else room.get('locks',{}).get(entity,''))
                    pending=self._outstanding.get(key)
                    if pending and time.monotonic()-pending['sent']>120:
                        warnings.append(entity+': Stellbefehl nicht bestätigt ('+str(pending['attempts'])+' Versuche)')
            trend=self._battery_history.get(rid,[])
            if len(trend)>5 and trend[-1][1]<25 and trend[0][1]-trend[-1][1]>20:
                warnings.append('Batterie fällt auffällig schnell')
            valve=self._state(room.get('valve'))
            if valve and valve.state in ('unknown','unavailable'):
                warnings.append('Ventilpositionsanzeige fehlt')
            if room.get('sensor') and self._valid_sensor(room) is None:
                warnings.append('Externer Temperaturfühler nicht verfügbar: Gerät auf internen Sensor zurücksetzen')

    async def _notify_warnings(self):
        issues={rid:w for rid,w in self._warnings.items() if w and self.rooms.get(rid,{}).get('enabled')}
        signature=repr(issues)
        if not issues or signature==self._last_notice_signature: return
        if time.monotonic()-self._last_notify<int(self.settings.get('notify_cooldown_minutes',120))*60: return
        clock=dt_util.now().strftime('%H:%M')
        start=self.settings.get('quiet_start','22:00');end=self.settings.get('quiet_end','07:00')
        quiet=(start<=clock<end) if start<end else (clock>=start or clock<end)
        if quiet: return
        message='\n'.join(f"{self.rooms[rid].get('name',rid)}: "+' | '.join(w[:4]) for rid,w in issues.items())[:2000]
        svc=self.settings.get('notify_service','')
        try:
            if svc:
                dom,name=svc.split('.',1)
                if dom!='notify': raise ValueError('Nur notify.<service> erlaubt')
                await self.hass.services.async_call(dom,name,{'title':'Heating Center Warnung','message':message},blocking=False)
            else:
                from homeassistant.components import persistent_notification
                persistent_notification.async_create(self.hass,message,'Heating Center Warnung',notification_id='heating_center_warning')
        except Exception:
            _LOGGER.exception('Unable to deliver heating diagnostics')
            return
        self._last_notice_signature=signature
        self._last_notify=time.monotonic()

    def _wolf_snapshot(self):
        result={}
        for label,entity in self.settings.get('wolf_entities',{}).items():
            state=self._state(entity)
            result[label]={'entity':entity,'state':state.state if state else 'not_configured',
                           'unit':state.attributes.get('unit_of_measurement','') if state else ''}
        return result

    def snapshot(self):
        data=super().snapshot()
        data['version']='0.3.0-beta.12'
        data['settings']=deepcopy(self.settings)
        data['profiles']={rid:room.get('profiles',DEFAULT_PROFILES) for rid,room in self.rooms.items()}
        data['history']={rid:rows[-160:] for rid,rows in self.history.items()}
        data['heating_rates']=deepcopy(self._rates)
        data['preheat']=deepcopy(self._last_preheat)
        data['target_rules']={rid:self._target_reason(room) for rid,room in self.rooms.items()}
        demand={}
        for rid,room in self.rooms.items():
            measured=self._get_measured(room)
            target=self._target(room)
            active=bool(room.get('enabled') and measured is not None and measured<target-.3 and not self._window(room))
            demand[rid]={'measured':measured,'target':target,'active':active,
                         'delta':round(max(0,target-measured),1) if measured is not None else None}
        data['demand']=demand
        data['demand_rooms']=sum(x['active'] for x in demand.values())
        data['wolf']={'read_only':True,'telemetry':self._wolf_snapshot()}
        data['battery_history']={rid:points[-14:] for rid,points in self._battery_history.items()}
        data['pending_acks']={k:{'attempts':v['attempts'],'seconds':round(time.monotonic()-v['sent'])}
                              for k,v in self._outstanding.items()}
        return data

    async def add_room(self,data):
        rid=str(data.get('id',''))
        existing=deepcopy(self.rooms.get(rid, {}))
        schedule=data.get('schedule')
        if schedule is not None: data['schedule']=validate_schedule(schedule)
        await super().add_room(data)
        room=self.rooms[rid]
        old=existing
        for key in ('lqi','valve','person','outdoor'):
            room[key]=str(data.get(key,old.get(key,'')))[:220]
        room['profiles']={name:valid_temp(data.get('profiles',old.get('profiles',DEFAULT_PROFILES)).get(name, DEFAULT_PROFILES[name])) or DEFAULT_PROFILES[name]
                          for name in DEFAULT_PROFILES}
        for key,default,minimum,maximum in [('frost_temp',8,5,16),('max_preheat_minutes',120,0,180),('lqi_warning',40,0,255)]:
            try: v=float(data.get(key,old.get(key,default)))
            except (ValueError,TypeError): v=default
            room[key]=max(minimum,min(maximum,v))
        room['adaptive_start']=bool(data.get('adaptive_start',old.get('adaptive_start',False)))
        room['native_schedules']=data.get('native_schedules',old.get('native_schedules',{}))
        if not isinstance(room['native_schedules'],dict): raise ValueError('Ungültige native Zeitplan-Zuordnung')
        # Each climate maps to a map of weekday to text.* entity, never writes unrequested.
        for cl,mapping in room['native_schedules'].items():
            if cl not in room['climates'] or not isinstance(mapping,dict): raise ValueError('Ungültige Sonoff Zeitplan-Zuordnung')
            if any(str(day) not in [str(i) for i in range(7)] or not ent.startswith('text.')
                   for day,ent in mapping.items()): raise ValueError('Sonoff Zeitpläne benötigen text.* Entitäten')
        self._update_watch()
        self._save()
        # A room creation/edit must survive a restart and return to the panel immediately.
        await self.async_flush()

    async def set_settings(self,settings):
        if not isinstance(settings,dict): raise ValueError('Einstellungen müssen ein Objekt sein')
        cleaned=deepcopy(self.settings)
        for key in ('presence_entity','outside_entity','notify_service','vacation_from','vacation_to'):
            if key in settings: cleaned[key]=str(settings[key])[:250].strip()
        if cleaned.get('notify_service') and not cleaned['notify_service'].startswith('notify.'):
            raise ValueError('Benachrichtigungsdienst muss notify.* sein')
        for key in ('quiet_start','quiet_end'):
            if key in settings:
                import re
                value=str(settings[key])
                if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value): raise ValueError('Ungültige Ruhezeit')
                cleaned[key]=value
        for key in ('presence_auto','notify_enabled'):
            if key in settings: cleaned[key]=bool(settings[key])
        if 'notify_cooldown_minutes' in settings:
            cleaned['notify_cooldown_minutes']=max(15,min(1440,int(settings['notify_cooldown_minutes'])))
        if 'wolf_entities' in settings:
            if not isinstance(settings['wolf_entities'],dict): raise ValueError('Wolf-Einstellungen müssen ein Objekt sein')
            cleaned['wolf_entities']=dict(cleaned.get('wolf_entities',{}))
            for key,value in settings['wolf_entities'].items():
                if key not in DEFAULT_SETTINGS['wolf_entities']: raise ValueError('Unbekannter Wolf-Telemetrietyp')
                if value and not str(value).startswith(('sensor.','binary_sensor.')):
                    raise ValueError('Wolf-Telemetrie muss sensor.* oder binary_sensor.* verwenden')
                cleaned['wolf_entities'][key]=str(value)
        for key in ('vacation_from','vacation_to'):
            if cleaned[key] and dt_util.parse_datetime(cleaned[key]) is None:
                raise ValueError('Urlaubsbeginn/Ende benötigt ISO Datum mit Zeitzone')
        if cleaned.get('vacation_from') and cleaned.get('vacation_to'):
            if dt_util.parse_datetime(cleaned['vacation_from']) >= dt_util.parse_datetime(cleaned['vacation_to']):
                raise ValueError('Urlaubsende muss nach Urlaubsbeginn liegen')
        self.settings=cleaned
        self._update_watch()
        self._save()

    async def apply_profile(self,room_id,profile,minutes=120):
        room=self.rooms.get(room_id)
        if room is None: raise ValueError('Raum nicht gefunden')
        if profile not in DEFAULT_PROFILES: raise ValueError('Profil nicht gefunden')
        await self.set_room_temperature(room_id,room.get('profiles',DEFAULT_PROFILES)[profile],minutes)

    async def sync_native_schedule(self,room_id):
        """Explicit opt-in export only. Never switch TRV to auto: avoids dual schedulers."""
        room=self.rooms.get(room_id)
        if not room: raise ValueError('Raum nicht gefunden')
        if not room.get('schedule_enabled'): raise ValueError('Zuerst Wochenplan aktivieren')
        if not room.get('enabled'): raise ValueError('Raum muss aktiviert sein')
        mapping=room.get('native_schedules',{})
        if not mapping: raise ValueError('Keine Sonoff text.* Zeitplan-Entitäten hinterlegt')
        items=[]
        for climate,days in mapping.items():
            if climate not in room['climates']: raise ValueError('Thermostat nicht zugeordnet')
            for day,entity in days.items():
                value=native_sonoff_schedule(room['schedule'],int(day),room['target'])
                st=self._state(entity)
                if not st or st.state in ('unavailable','unknown'):
                    raise ValueError('Zeitplan-Entität nicht verfügbar: '+entity)
                items.append((entity,value))
        # Validation for the entire batch finishes before any writes are made.
        for entity,value in items:
            await self.hass.services.async_call('text','set_value',{'entity_id':entity,'value':value},blocking=True)
        return len(items)
