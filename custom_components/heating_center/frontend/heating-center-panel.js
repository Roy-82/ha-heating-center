/* HA Heating Center administration panel — vanilla web component, no CDN. */
const DOW = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const PANEL_FRONTEND_VERSION = "0.3.0-beta.5";
const safe = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const mapping = (map) => Object.entries(map || {}).map(([a,b]) => `${a} = ${b}`).join("\n");
const parseMapping = (text) => Object.fromEntries(text.split("\n").map(s=>s.split("=").map(x=>x?.trim())).filter(x=>x.length===2&&x[0]&&x[1]));
const parseSchedule = (day, fallback=[]) => {
  const result = [];
  for (const entry of String(day).split(/[;,]/).map(s=>s.trim()).filter(Boolean)) {
    const parts = entry.split(/\s+/);
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(parts[0]) || !/^(\d+(?:\.\d+)?)$/.test(parts[1] ?? "")) throw Error(`Ungültiger Zeitplan: ${entry}`);
    const t = Number(parts[1]);
    if (t < 5 || t > 30) throw Error("Temperatur muss zwischen 5 und 30 °C liegen");
    result.push({time: parts[0], temp: t});
  }
  return result.length ? result : fallback;
};
class HeatingCenterPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this.data = null;
    this._busy = false;
    this._editing = null;
    this._tab = "rooms";
    this._error = "";
    this.shadowRoot.addEventListener("click", (e) => this._click(e));
    this.shadowRoot.addEventListener("submit", (e) => this._submit(e));
    this.shadowRoot.addEventListener("change", (e) => this._change(e));
  }
  connectedCallback() { this._refresh(); this._timer = setInterval(() => { if (this._editing===null) this._refresh(); }, 60000); }
  disconnectedCallback() { if (this._timer) clearInterval(this._timer); }
  set hass(hass) {
    this._hass = hass;
    if (!this.data && !this._busy && this.isConnected) this._refresh();
    else if (this.data && this._editing === null) this._render();
  }
  set narrow(narrow) { this._narrow = narrow; }
  set panel(panel) { this._panel = panel; }
  async _refresh() {
    if (!this._hass || this._busy) return;
    this._busy = true;
    try {
      this.data = await this._hass.callWS({type: "heating_center/get"});
      this._error = "";
    } catch (error) { this._error = error.message || String(error); }
    finally { this._busy = false; this._render(); }
  }
  async _service(action, values) {
    if (!this.data || this._busy) return;
    this._busy = true;
    try {
      await this._hass.callWS({type:"heating_center/execute", config_entry_id:this.data.entry_id, action, data:values});
      this._busy = false;
      await this._refresh();
      return true;
    } catch(error) {
      this._busy = false;
      const code = error?.code ?? error?.status ?? "";
      const message = error?.message || String(error);
      const forbidden = /403|forbidden|unauthorized/i.test(String(code) + " " + message);
      this._error = "Speichern (" + action + ") fehlgeschlagen: " + (code ? code + ": " : "") + message
        + (forbidden ? ". Berechtigung verweigert oder veraltete Oberfläche. Prüfe die angezeigte Frontend-Version und das HA-Protokoll." : "");
      // Do not rerender the form on failure: unsaved room settings must survive.
      const form = this.shadowRoot.querySelector("#room-form, #settings-form");
      if (form) {
        let alert = form.querySelector(".hc-save-error");
        if (!alert) {
          alert = document.createElement("div");
          alert.className = "error hc-save-error";
          alert.setAttribute("role", "alert");
          form.prepend(alert);
        }
        alert.textContent = this._error;
      } else {
        this._render();
      }
      return false;
    }
  }
  _field(label,name,value="",type="text",extra="") {
    return `<label><span>${safe(label)}</span><input name="${safe(name)}" type="${type}" value="${safe(value)}" ${extra}></label>`;
  }
  _roomCard(id, room) {
    const climates = (room.climates || []);
    const first = this._hass?.states?.[climates[0]];
    const temp = this.data.demand?.[id]?.measured ?? first?.attributes?.current_temperature;
    const demand = this.data.demand?.[id];
    const target = this.data.calculated_targets?.[id] ?? room.target;
    const warnings = this.data.warnings?.[id] || [];
    return `<article class="room ${!room.enabled?'disabled':''}">
      <div class="roomhead"><div><h3>${safe(room.name)}</h3><small>${safe(room.group||'Einzelraum')} · ${climates.length} Thermostat(e)</small></div><span class="chip ${room.child_protection?'on':''}">${room.child_protection?'🔒 Kindersicherung':'Sperre aus'}</span></div>
      <div class="temps"><strong>${temp == null ? '—' : safe(Number(temp).toFixed(1))} °C</strong><span>Soll <b>${safe(target)} °C</b></span></div>
      <div class="control"><input aria-label="Temperatur" id="set-${safe(id)}" type="number" min="5" max="30" step="0.5" value="${safe(target)}"><select id="duration-${safe(id)}"><option value="120">2 Stunden</option><option value="30">30 Minuten</option><option value="0">Dauerhaft / Basis</option></select><button data-act="temp" data-id="${safe(id)}">Setzen</button></div>
      <div class="controls"><button class="secondary" data-act="edit" data-id="${safe(id)}">Bearbeiten</button><button class="secondary" data-act="profile" data-profile="comfort" data-id="${safe(id)}">Komfort</button><button class="secondary" data-act="profile" data-profile="eco" data-id="${safe(id)}">Eco</button><button class="secondary" data-act="profile" data-profile="boost" data-id="${safe(id)}">Boost</button><span class="chip">${room.enabled?'Automatik aktiv':'Nicht aktiviert'}</span>${room.schedule_enabled?'<span class="chip">Wochenplan</span>':''}${demand?.active?'<span class="chip on">Wärmebedarf</span>':''}</div>
      ${warnings.length?`<div class="alerts">${warnings.map(x=>`<p>⚠ ${safe(x)}</p>`).join("")}</div>`:`<div class="good">✓ Keine Warnungen</div>`}
    </article>`;
  }
  _editor() {
    if (this._editing === null || this._editing === 'settings') return "";
    const existing = this.data.rooms[this._editing] || {};
    const isNew = !existing.id;
    const sch = existing.schedule || {};
    const input = (lbl,key,def="",type="text",extra="") => this._field(lbl,key,existing[key] ?? def,type,extra);
    return `<section class="editor"><h2>${isNew?"Neuen Raum anlegen":"Raum bearbeiten"}</h2><form id="room-form">
      <div class="fieldgrid">
        ${this._field('ID (nur Buchstaben, Zahlen, _ oder -)', 'id', existing.id||this._editing, 'text', isNew?'required':'readonly')}
        ${input('Raumname','name', '', 'text','required')}
        ${input('Gruppe (optional)','group')}
        ${input('Basistemperatur in °C','target',19,'number','min="5" max="30" step="0.5"')}
        ${input('Abwesendtemperatur in °C','away_temp',16,'number','min="5" max="30" step="0.5"')}
        ${input('Urlaubstemperatur in °C','vacation_temp',12,'number','min="5" max="30" step="0.5"')}
        ${input('Fenster-offen-Temperatur in °C','window_temp',12,'number','min="5" max="30" step="0.5"')}
        ${input('Externer Temperaturfühler (sensor.*)','sensor')}
        ${input('Fensterkontakt (binary_sensor.*)','window')}
        ${input('Batterie (sensor.*)','battery')}
        ${input('Verfügbarkeit (binary_sensor.*)','availability')}
        ${input('Letzter Kontakt (sensor.*)','last_seen')}
      </div>
      <label>Thermostate, eines je Zeile (climate.*)<textarea name="climates" rows="3" required>${safe((existing.climates||[]).join("\n"))}</textarea></label>
      <h3>Sonoff-Zuordnungen</h3><p class="hint">Pro Zeile: <code>climate.thermostat = switch.thermostat_child_lock</code>. Weitere Thermostate in derselben Art ergänzen.</p>
      <div class="fieldgrid">
        <label>Kindersperre (switch.*, select.* oder lock.*)<textarea name="locks" rows="3">${safe(mapping(existing.locks))}</textarea></label>
        <label>Externer Temperaturwert (number.*)<textarea name="external_inputs" rows="3">${safe(mapping(existing.external_inputs))}</textarea></label>
        <label>Temperaturquelle (select.*)<textarea name="remote_modes" rows="3">${safe(mapping(existing.remote_modes))}</textarea></label>
      </div>
      <h3>Diagnose und Optimierung</h3>
      <div class="fieldgrid">
        ${input('Signalqualität (sensor.*)','lqi')}
        ${input('Ventilöffnung (sensor.*)','valve')}
        ${input('Außentemperatur für den Raum (sensor.*)','outdoor')}
        ${input('Raum-Anwesenheit (person.* optional)','person')}
        ${input('Frostschutz-Untergrenze °C','frost_temp',8,'number','min="5" max="16" step="0.5"')}
        ${input('Max. Vorheizzeit (Min.)','max_preheat_minutes',120,'number','min="0" max="180" step="5"')}
        ${input('LQI-Warngrenze','lqi_warning',40,'number','min="0" max="255" step="1"')}
        ${input('Sensor nach Sekunden veraltet','sensor_max_age',5400,'number','min="120" max="86400" step="60"')}
        ${input('Batteriewarnung unter (%)','battery_warning',20,'number','min="1" max="50" step="1"')}
        ${input('Komfortprofil °C','profile_comfort',existing.profiles?.comfort??21,'number','min="5" max="30" step="0.5"')}
        ${input('Eco-Profil °C','profile_eco',existing.profiles?.eco??18,'number','min="5" max="30" step="0.5"')}
        ${input('Nachtprofil °C','profile_night',existing.profiles?.night??17,'number','min="5" max="30" step="0.5"')}
        ${input('Boost-Profil °C','profile_boost',existing.profiles?.boost??23,'number','min="5" max="30" step="0.5"')}
      </div>
      <label>Sonoff Wochenplan-Textentitäten für Offline-Export (Format: climate.* = 0:text.*,1:text.*; Zuordnung pro Thermostat über eine Zeile)
      <textarea name="native_schedules" rows="3" placeholder="climate.wohnzimmer = 0:text.montag,1:text.dienstag">${safe(Object.entries(existing.native_schedules||{}).map(([cl,week])=>cl+' = '+Object.entries(week).map(([d,e])=>d+':'+e).join(',')).join('\n'))}</textarea></label>
      <div class="checkboxes">
        <label><input type="checkbox" name="adaptive_start" ${existing.adaptive_start?'checked':''}> Adaptives Vorheizen (lernt Heizgeschwindigkeit)</label>
        <label><input type="checkbox" name="child_protection" ${existing.child_protection?'checked':''}> Dauerhafte Kindersicherung und automatische Rückstellung</label>
        <label><input type="checkbox" name="schedule_enabled" ${existing.schedule_enabled?'checked':''}> Wochenplan aktiv</label>
        <label><input type="checkbox" name="enabled" ${existing.enabled?'checked':''}> Steuerung für diesen Raum aktivieren (sendet Befehle)</label>
      </div>
      <h3>Wochenplan</h3><p class="hint">Die Software-Zeitpläne laufen in Home Assistant. Optional die Wochenpläne mit der Schaltfläche "Sonoff-Export" auf die Thermostate schreiben, die Betriebsart bleibt unverändert.</p><p class="hint">Format: <code>06:00 20, 22:00 17</code> · Leer = bisheriger Plan</p>
      <div class="schedule">${DOW.map((name,i)=>`<label><span>${name}</span><input name="day${i}" value="${safe((sch[String(i)]||((i<5)?[{time:'06:00',temp:20},{time:'22:00',temp:17}]:[{time:'08:00',temp:20},{time:'22:00',temp:17}])).map(x=>`${x.time} ${x.temp}`).join(', '))}" placeholder="06:00 20, 22:00 17"></label>`).join("")}</div>
      <div class="controls"><button type="submit">Speichern</button><button type="button" class="secondary" data-act="cancel">Abbrechen</button>${!isNew?`<button type="button" class="secondary" data-act="sync" data-id="${safe(existing.id)}">Sonoff-Export</button><button type="button" class="danger" data-act="delete" data-id="${safe(existing.id)}">Raum entfernen</button>`:''}</div>
    </form></section>`;
  }
  _settingsEditor() {
    if (this._editing !== 'settings') return '';
    const settings=this.data.settings||{};
    const input=(title,key,def='')=>this._field(title,key,settings[key]??def);
    const wolf=settings.wolf_entities||{};
    return `<section class="editor"><h2>Systemeinstellungen</h2><form id="settings-form">
      <div class="fieldgrid">
        ${input('Anwesenheit (person.* / binary_sensor.*)','presence_entity')}
        ${input('Außentemperatur (sensor.*)','outside_entity')}
        ${input('Benachrichtigungsdienst (notify.*)','notify_service')}
        ${input('Benachrichtigungsabstand in Minuten','notify_cooldown_minutes',120)}
        ${input('Ruhezeit von','quiet_start','22:00')}
        ${input('Ruhezeit bis','quiet_end','07:00')}
        ${input('Urlaub ab (ISO mit Zeitzone)','vacation_from')}
        ${input('Urlaub bis (ISO mit Zeitzone)','vacation_to')}
      </div>
      <div class="checkboxes">
        <label><input type="checkbox" name="presence_auto" ${settings.presence_auto?'checked':''}> Hausmodus mit Anwesenheit steuern (5-Minuten-Entprellung)</label>
        <label><input type="checkbox" name="notify_enabled" ${settings.notify_enabled?'checked':''}> Warnungen zustellen</label>
      </div>
      <h3>Wolf COB-20 — nur lesen</h3>
      <p class="hint">Noch keine Kesselbefehle. Sobald eBUS durch eine andere Integration Entitäten liefert, kannst du sie hier zuordnen.</p>
      <div class="fieldgrid">${Object.keys({flow_temp:1,return_temp:1,boiler_temp:1,dhw_temp:1,burner:1,modulation:1,fault:1,outside:1}).map(key=>this._field('Wolf '+key,'wolf_'+key,wolf[key]||'')).join('')}</div>
      <div class="controls"><button type="submit">Einstellungen speichern</button><button type="button" class="secondary" data-act="cancel">Abbrechen</button></div>
    </form></section>`;
  }
  _analytics() {
    const rooms=Object.entries(this.data.rooms||{});
    const histories=this.data.history||{};
    const graph=(rows)=>{
      if (!rows || rows.length < 2) return '<small>Noch keine Historie (Messwerte alle 5 Minuten).</small>';
      const vals=rows.map(r=>Number(r[1])).filter(Number.isFinite);
      const targets=rows.map(r=>Number(r[2])).filter(Number.isFinite);
      const low=Math.floor(Math.min(...vals,...targets)-1), high=Math.ceil(Math.max(...vals,...targets)+1);
      const w=500,h=100, step=Math.max(1,high-low);
      const points=(index)=>rows.map((r,i)=>`${Math.round(i/(rows.length-1)*w)},${Math.round(10+(high-Number(r[index]))/step*(h-20))}`).join(' ');
      return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Temperaturverlauf" preserveAspectRatio="none"><polyline fill="none" stroke="var(--primary-color,#317bbd)" stroke-width="2" points="${safe(points(1))}"/><polyline fill="none" stroke="var(--warning-color,#d78028)" stroke-width="1.5" stroke-dasharray="4 4" points="${safe(points(2))}"/></svg><small>Ist (durchgezogen) · Soll (gestrichelt) · ${safe(low)}–${safe(high)} °C</small>`;
    };
    const telemetry=this.data.wolf?.telemetry||{};
    return `<section class="editor"><h2>Diagnose, Verlauf und Heizbedarf</h2><div class="fieldgrid">
     ${rooms.map(([rid,room])=>{const d=this.data.demand?.[rid]||{};const rate=this.data.heating_rates?.[rid];const pre=this.data.preheat?.[rid];
     return `<article><h3>${safe(room.name)}</h3><p>Ist ${safe(d.measured??'—')} °C · Soll ${safe(d.target??'—')} °C · Bedarf: ${d.active?'ja':'nein'}</p>
       <p>Aufheizrate: ${safe(rate??'noch nicht gelernt')} °C/h${pre?` · Vorheizen: ${safe(pre.minutes)} Min.`:''}</p>
       ${graph(histories[rid])}</article>`;}).join('')}
    </div><h3>Wolf COB-20 Telemetrie</h3><div class="fieldgrid">${Object.entries(telemetry).map(([key,v])=>`<p><b>${safe(key)}</b>: ${safe(v.state)} ${safe(v.unit)}</p>`).join('')}</div><p class="hint">eBUS bleibt ausschließlich lesend. Werte erscheinen erst nach Zuordnung vorhandener Home-Assistant-Entitäten.</p></section>`;
  }

  _suggestThermostatFields(climate) {
    const entity = String(climate || "").trim();
    if (!/^climate\.[a-z0-9_]+$/.test(entity)) return null;
    const id = entity.slice(8), states = this._hass?.states || {};
    if (!states[entity]) return null;
    const find = (...candidates) => candidates.find(key => Boolean(states[key])) || "";
    const original = states[entity].attributes?.friendly_name || id.replaceAll("_", " ");
    const days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"];
    return {
      climate:entity,
      id:id.replace(/_thermostat$/,""),
      name:original.replace(/\s+thermostat$/i,"").trim(),
      lock:find("switch."+id+"_child_lock","select."+id+"_child_lock","lock."+id+"_child_lock"),
      external_inputs:find("number."+id+"_external_temperature_input"),
      remote_modes:find("select."+id+"_temperature_sensor_select"),
      battery:find("sensor."+id+"_batterie","sensor."+id+"_battery"),
      availability:find("binary_sensor."+id+"_availability","binary_sensor."+id+"_verfuegbarkeit"),
      last_seen:find("sensor."+id+"_last_seen"),
      lqi:find("sensor."+id+"_verbindungsqualitaet","sensor."+id+"_linkquality"),
      native_schedules:Object.fromEntries(days.map((day,index)=>[index,find("text."+id+"_weekly_schedule_"+day)]).filter(([,ent])=>ent))
    };
  }
  _autofillThermostatFields(force=false) {
    const form=this.shadowRoot.querySelector("#room-form");
    const textarea=form?.querySelector('[name="climates"]');
    if (!form || !textarea) return;
    const climates=textarea.value.split(/[\n,]+/).map(v=>v.trim()).filter(Boolean);
    const matches=climates.map(climate=>this._suggestThermostatFields(climate)).filter(Boolean);
    if (!matches.length) {
      this._showHelp("Für die eingegebenen climate.*-Entitäten wurden keine geladenen Thermostate in Home Assistant gefunden. Bitte die Entitäts-ID prüfen.");
      return;
    }
    const set=(name,value,overwrite=force)=>{
      const input=form.elements.namedItem(name);
      if (!input || !value) return;
      if (overwrite || !String(input.value || "").trim() || (name==="id" && input.value==="neuer_raum")) input.value=value;
    };
    const first=matches[0];
    if (!this.data.rooms?.[this._editing]) {
      set("id",first.id,false);
      set("name",first.name,false);
    }
    for (const key of ["battery","availability","last_seen","lqi"]) set(key,first[key]);
    const assign=(key,field)=>{
      const pairs=matches.filter(v=>v[key]).map(v=>v.climate+" = "+v[key]);
      set(field,pairs.join("\n"));
    };
    assign("lock","locks");
    assign("external_inputs","external_inputs");
    assign("remote_modes","remote_modes");
    const plans=matches.map(v=>{
      const items=Object.entries(v.native_schedules).map(([day,entity])=>day+":"+entity).join(",");
      return items ? v.climate+" = "+items : "";
    }).filter(Boolean);
    set("native_schedules", plans.join("\n"));
    // Never guess an unrelated room-temperature sensor or a window contact.
    this._showHelp(matches.length+" Thermostat(e) erkannt. Verfügbare Sonoff-Entitäten wurden in die Formularfelder übernommen. Externe Raumfühler und Fensterkontakte bleiben bewusst unverändert. Bitte die Zuordnungen vor dem Speichern prüfen.");
  }
  _showHelp(message) {
    let dialog=this.shadowRoot.querySelector("#hc-help-dialog");
    if (!dialog) {
      dialog=document.createElement("dialog");
      dialog.id="hc-help-dialog";
      dialog.innerHTML='<p id="hc-help-message"></p><button type="button" data-act="close-help">Schließen</button>';
      this.shadowRoot.append(dialog);
    }
    dialog.querySelector("#hc-help-message").textContent=message;
    if (!dialog.open) dialog.showModal();
  }
  _enhanceForms() {
    const root=this.shadowRoot;
    const form=root.querySelector("#room-form");
    if (form) {
      const climate=form.querySelector('[name="climates"]');
      if (climate && !root.querySelector('[data-act="autofill"]')) {
        climate.closest("label").insertAdjacentHTML("afterend",
          '<div class="hc-autofill"><button type="button" class="secondary" data-act="autofill">Thermostat-Entitäten automatisch erkennen</button><small>Findet vorhandene Sonoff-Begleitentitäten. Der separate Raumtemperatursensor bleibt manuell.</small></div>');
      }
    }
    const help={
      id:"Eindeutige Kennung des Raums, zum Beispiel buero. Nach dem Anlegen nicht mehr änderbar.",
      name:"Anzeigename im Dashboard.", group:"Räume mit demselben Gruppennamen kannst du gemeinsam steuern.",
      target:"Normale Solltemperatur des Raums. Zeitpläne und Abwesenheit können diesen Wert zeitweise ersetzen.",
      away_temp:"Solltemperatur für den Hausmodus Abwesend.", vacation_temp:"Solltemperatur für den Urlaubsmodus.",
      window_temp:"Solltemperatur, während der Fensterkontakt geöffnet ist.",
      sensor:"Separater Raum-Klimasensor (sensor.*). Wird nicht automatisch aus der Thermostat-ID abgeleitet.",
      window:"Optionaler Tür- oder Fensterkontakt (binary_sensor.*).",
      battery:"Batterie-Entität des Heizkörperthermostats. Automatisch erkennbar.",
      availability:"Optionaler Online-Status des Thermostats. Darf leer bleiben.",
      last_seen:"Zeitstempel der letzten Zigbee-Nachricht. Zigbee2MQTT muss last_seen bereitstellen.",
      climates:"Hier eine oder mehrere climate.*-Entitäten eintragen. Danach automatische Erkennung starten.",
      locks:"Entitäten für die echte Tastensperre der Thermostate. Zuordnung je Thermostat.",
      external_inputs:"number.*-Entitäten, an welche Heating Center die externe Raumtemperatur schreibt.",
      remote_modes:"select.*-Entitäten zur Wahl zwischen internem und externem Temperaturfühler.",
      lqi:"Zigbee-Signalqualität (LQI). Ein niedriger Wert kann auf eine instabile Funkverbindung hindeuten.",
      valve:"Optionale echte Ventilpositionsanzeige; keine maximale Ventilöffnungsbegrenzung auswählen.",
      outdoor:"Optionaler Außentemperatursensor für adaptives Vorheizen.",
      person:"Optionale Person-Entität. Aktuell keine eigenständige raumbezogene Heizregel.",
      frost_temp:"Softwareseitige Mindesttemperatur. Kein Ersatz für den Frostschutz der Heizung.",
      max_preheat_minutes:"Obergrenze, wie früh die adaptive Vorheizung beginnen darf.",
      lqi_warning:"Unterhalb dieses Werts wird eine Warnung zur Funkqualität angezeigt.",
      sensor_max_age:"Nach dieser Zeit ohne Aktualisierung gilt der externe Temperatursensor als veraltet.",
      battery_warning:"Warnschwelle für die Batterie in Prozent.",
      profile_comfort:"Vorgegebene Temperatur für Komfort.", profile_eco:"Vorgegebene Temperatur für Eco.",
      profile_night:"Vorgegebene Temperatur für Nacht.", profile_boost:"Vorgegebene Temperatur für Boost.",
      native_schedules:"Optionaler Offline-Export in Sonoff-interne Wochenpläne; nicht notwendig für HA-Zeitpläne.",
      adaptive_start:"Lernt die Aufheizgeschwindigkeit und heizt für geplante Komfortzeiten gegebenenfalls früher vor.",
      child_protection:"Hält den hinterlegten Sollwert und aktiviert die Gerätesperre bei Bedarf erneut.",
      schedule_enabled:"Aktiviert die HA-Wochenplanung für diesen Raum.",
      enabled:"Achtung: Nur bei Aktivierung sendet Heating Center tatsächlich Steuerbefehle an diesen Raum.",
      presence_entity:"Entität für die automatische Haus-Anwesenheit.", outside_entity:"Globaler Außentemperatursensor.",
      notify_service:"Benachrichtigungsdienst, etwa notify.*.", notify_cooldown_minutes:"Mindestabstand zwischen wiederholten Warnmeldungen.",
      quiet_start:"Beginn der Ruhezeit (HH:MM).", quiet_end:"Ende der Ruhezeit (HH:MM).",
      presence_auto:"Hausmodus automatisch anhand der Anwesenheits-Entität steuern.",
      notify_enabled:"Benachrichtigungen für Diagnosen aktivieren.",
      vacation_from:"Optionaler Urlaubsbeginn als ISO-Datum.", vacation_to:"Optionales Urlaubsende als ISO-Datum."
    };
    for (const label of root.querySelectorAll(".editor label")) {
      const input=label.querySelector("input[name],textarea[name],select[name]");
      if (!input || label.querySelector(".hc-help")) continue;
      const content=help[input.name] || (input.name.startsWith("day") ? "Wochenplan: Uhrzeiten und Temperaturen als HH:MM Grad, durch Kommas getrennt." : input.name.startsWith("wolf_") ? "Wolf-eBUS-Telemetrie: vorhandene Home-Assistant-Entität. Nur auslesend." : "Optionale Einstellung; kann bei Bedarf unverändert bleiben.");
      const btn=document.createElement("button");
      btn.type="button"; btn.className="hc-help"; btn.dataset.act="help"; btn.dataset.help=content;
      btn.title=content; btn.setAttribute("aria-label","Hilfe zu "+input.name); btn.textContent="?";
      if (input.type==="checkbox") {
        label.classList.add("hc-checkbox");
        label.append(btn);
      } else {
        const heading=document.createElement("span");
        heading.className="hc-field-heading";
        while (label.firstChild && label.firstChild!==input) heading.append(label.firstChild);
        heading.append(btn);label.insertBefore(heading,input);
      }
    }
  }

  _render() {
    if (!this.isConnected) return;
    if (!this.data) {
      this.shadowRoot.innerHTML = `<style>:host{display:block;padding:24px;color:var(--primary-text-color)}</style><p>${safe(this._error||'Heizungszentrale wird geladen …')}</p>`;
      return;
    }
    const rooms = Object.entries(this.data.rooms || {});
    const groups = [...new Set(rooms.map(([,r])=>r.group).filter(Boolean))];
    const warnings = Object.values(this.data.warnings||{}).flat().length;
    const countOn = rooms.filter(([,r])=>r.enabled).length;
    const form = this._editor();
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;min-height:100vh;background:var(--primary-background-color,#f5f6f8);color:var(--primary-text-color,#18212b);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);font-size:14px}
      *{box-sizing:border-box}main{max-width:1240px;margin:auto;padding:24px}h1{font-size:26px;margin:0 0 4px}h2{font-size:20px}h3{font-size:16px;margin:0}p{line-height:1.5}
      header,.row,.controls,.roomhead,.temps,.control{display:flex;gap:12px;align-items:center;justify-content:space-between}header{margin-bottom:20px;flex-wrap:wrap}small,.hint{color:var(--secondary-text-color,#68788c)}
      button{background:var(--primary-color,#287bbd);color:white;border:0;border-radius:9px;padding:10px 14px;cursor:pointer;font:inherit}button.secondary{background:var(--secondary-background-color,#e8ecf1);color:var(--primary-text-color,#24303a)}button.danger{background:#ba4444}button:hover{filter:brightness(.95)}
      select,input,textarea{font:inherit;color:var(--primary-text-color);background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#ccd4dd);border-radius:8px;padding:9px;max-width:100%;min-width:0}textarea{width:100%}input[type=number]{width:90px}input[type=checkbox]{width:auto}
      svg{width:100%;height:110px;margin:8px 0} .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0} .summary,.rooms{display:grid;gap:14px}.summary{grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:22px}.rooms{grid-template-columns:repeat(auto-fit,minmax(285px,1fr))}section.summary article,article.room,.editor{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e1e4e9);border-radius:15px;padding:18px;box-shadow:0 2px 9px rgba(0,0,0,.04)}
      .summary strong{font-size:24px;display:block;margin-top:6px}.room{min-width:0}.room.disabled{opacity:.75}.chip{display:inline-block;background:var(--secondary-background-color,#edf1f4);padding:5px 9px;border-radius:99px;font-size:11px;white-space:nowrap}.chip.on{color:#277548;background:#def7e7}.temps{margin:20px 0}.temps strong{font-size:30px}.control{justify-content:flex-start;gap:6px;flex-wrap:wrap}.control input{width:84px}.control select{width:130px}.controls{justify-content:flex-start;flex-wrap:wrap;margin-top:14px}.alerts{color:#aa5205;background:var(--secondary-background-color,#fff3df);padding:8px 10px;border-radius:8px;margin-top:12px}.alerts p{margin:3px 0}.good{color:#267d48;margin-top:10px}.editor{margin:20px 0}.fieldgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:12px}.editor label{display:flex;flex-direction:column;gap:5px;margin-bottom:10px}.editor input{width:100%}.checkboxes{margin:16px 0}.checkboxes label{flex-direction:row;align-items:center}.schedule{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px}.schedule label{flex-direction:row;align-items:center}.schedule label span{min-width:25px}.error{color:#a82121;background:#ffe9e9;border-radius:8px;padding:10px}.note{margin:10px 0 20px;color:var(--secondary-text-color)}
      .hc-autofill{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 16px}.hc-autofill small{max-width:500px}.hc-field-heading{display:flex;align-items:center;gap:7px;justify-content:flex-start}.hc-help{width:21px;min-width:21px;height:21px;padding:0;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:bold;font-size:12px;background:var(--secondary-background-color,#e9edf2);color:var(--primary-text-color,#24303a);border:1px solid var(--divider-color,#c6cdd5)}.editor .checkboxes{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px 18px}.editor .checkboxes label,.editor label.hc-checkbox{display:flex;flex-direction:row;align-items:center;justify-content:flex-start;gap:10px;line-height:1.35;margin:0;min-width:0}.editor input[type=checkbox]{width:18px!important;min-width:18px;max-width:18px;height:18px;flex:none;margin:0}.editor .hc-checkbox .hc-help{margin-left:auto;flex:none}#hc-help-dialog{border:1px solid var(--divider-color,#ccd4dd);border-radius:15px;max-width:460px;width:calc(100% - 32px);padding:22px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#222);box-shadow:0 14px 55px #0004}#hc-help-dialog::backdrop{background:#0007}#hc-help-dialog p{font-size:15px;line-height:1.55}
      @media(max-width:650px){main{padding:12px}.summary{grid-template-columns:1fr 1fr 1fr;gap:6px}.summary article{padding:10px}.summary strong{font-size:20px}.roomhead{align-items:flex-start}.chip{white-space:normal}}
    </style>
    <main><header><div><h1>🔥 HA Heating Center <small>β</small></h1><small>Lokale Heizungsregelung · Backend ${safe(this.data.version)} · Oberfläche ${PANEL_FRONTEND_VERSION} · WebSocket · Konto ${this.data.session_admin ? "Administrator" : "kein Administrator"}</small></div><div class="controls"><button class="secondary" data-act="refresh">Aktualisieren</button><button data-act="new">+ Raum hinzufügen</button></div></header>
    ${this._error?`<div class="error">${safe(this._error)}</div>`:''}
    <section class="summary"><article><small>Räume aktiv</small><strong>${countOn} / ${rooms.length}</strong></article><article><small>Hinweise</small><strong>${warnings}</strong></article><article><small>Hausmodus</small><select id="housemode"><option value="home" ${this.data.mode==='home'?'selected':''}>Zuhause</option><option value="away" ${this.data.mode==='away'?'selected':''}>Abwesend</option><option value="vacation" ${this.data.mode==='vacation'?'selected':''}>Urlaub</option></select></article></section>
    <div class="tabs"><button class="secondary" data-act="tab" data-tab="rooms">Räume & Gruppen</button><button class="secondary" data-act="tab" data-tab="diagnostics">Diagnose & Verlauf</button><button class="secondary" data-act="settings">Systemeinstellungen</button></div>
    ${this._settingsEditor()}
    ${form}
    ${this._tab==='diagnostics'?this._analytics():''}
    ${this._tab==='rooms' && groups.length?`<section class="editor"><h2>Gruppensteuerung</h2>${groups.map(group=>`<div class="control"><b>${safe(group)}</b><input id="group-${safe(group)}" type="number" min="5" max="30" step="0.5" value="20"><button data-act="group" data-group="${safe(group)}">Gruppe einstellen</button></div>`).join('')}</section>`:''}
    ${this._tab==='rooms'?`<div class="rooms">${rooms.map(([id,room])=>this._roomCard(id,room)).join('')||'<article class="room"><h3>Noch keine Räume</h3><p>Lege einen Raum an und wähle deine bestehenden climate-Entitäten. Standardmäßig ist jede Steuerung zunächst deaktiviert.</p></article>'}</div>`:''}
    <p class="note">Kindersicherung: Schalter am TRV sperren und jede Änderung der Gerätetemperatur wieder auf den autorisierten Sollwert zurücksetzen. Bei Offline-Geräten ist keine sofortige Rückstellung möglich. Wolf-eBUS bleibt in dieser Betaversion ausdrücklich deaktiviert.</p>
    </main>`;
    this._enhanceForms();
  }
  async _click(event) {
    const button = event.target.closest("button[data-act]"); if (!button) return;
    const act = button.dataset.act;
    if (act==='refresh') return this._refresh();
    if (act==='help') {this._showHelp(button.dataset.help || 'Keine Hilfe verfügbar');return;}
    if (act==='close-help') {this.shadowRoot.querySelector('#hc-help-dialog')?.close();return;}
    if (act==='autofill') {this._autofillThermostatFields(true);return;}
    if (act==='tab') {this._editing=null;this._tab=button.dataset.tab;this._render();return;}
    if (act==='settings') {this._editing='settings';this._tab='rooms';this._render();return;}
    if (act==='profile') {return this._service('apply_profile',{room_id:button.dataset.id,profile:button.dataset.profile,minutes:button.dataset.profile==='boost'?30:120});}
    if (act==='sync') {if (confirm('Sonoff-Wochenplan jetzt in die Thermostate exportieren? Der Betriebsmodus wird nicht geändert.')) return this._service('export_schedule',{room_id:button.dataset.id});return;}
    if (act==='new') {this._editing='neuer_raum';this._render();return;}
    if (act==='edit') {this._editing=button.dataset.id;this._render();return;}
    if (act==='cancel') {this._editing=null;this._render();return;}
    if (act==='delete') {if (confirm('Diesen Raum und seine Einstellungen löschen?')) {this._editing=null;await this._service('remove_room',{room_id:button.dataset.id});}return;}
    if (act==='temp') {
      const id=button.dataset.id;
      return this._service('set_room_temperature',{room_id:id,temperature:Number(this.shadowRoot.getElementById('set-'+id).value),minutes:Number(this.shadowRoot.getElementById('duration-'+id).value)});
    }
    if (act==='group') {
      const group=button.dataset.group;
      return this._service('set_group_temperature',{group,temperature:Number(this.shadowRoot.getElementById('group-'+group).value),minutes:120});
    }
  }
  async _change(event) {
    if (event.target.id==='housemode') await this._service('set_mode',{mode:event.target.value});
    if (event.target.name==='climates' && event.target.closest('#room-form')) this._autofillThermostatFields(false);
  }
  async _submit(event) {
    if (!['room-form','settings-form'].includes(event.target.id)) return;
    event.preventDefault();
    if (event.target.id==='settings-form') {
      const f=event.target, val=(k)=>f.elements.namedItem(k)?.value||'';
      const keys=['presence_entity','outside_entity','notify_service','quiet_start','quiet_end','vacation_from','vacation_to'];
      const settings=Object.fromEntries(keys.map(k=>[k,val(k).trim()]));
      settings.notify_cooldown_minutes=Number(val('notify_cooldown_minutes'));
      settings.presence_auto=f.elements.namedItem('presence_auto').checked;
      settings.notify_enabled=f.elements.namedItem('notify_enabled').checked;
      settings.wolf_entities=Object.fromEntries(['flow_temp','return_temp','boiler_temp','dhw_temp','burner','modulation','fault','outside'].map(k=>[k,val('wolf_'+k).trim()]));
      if (await this._service('set_settings',{settings})) {this._editing=null;this._render();}return;
    }
    const form=event.target, value=(x)=>form.elements.namedItem(x)?.value||'';
    try {
      const roomId = value('id').trim();
      const room={id:roomId,name:value('name').trim(),group:value('group').trim(),
        climates:value('climates').split(/[\n,]/).map(x=>x.trim()).filter(Boolean),
        target:Number(value('target')),away_temp:Number(value('away_temp')),vacation_temp:Number(value('vacation_temp')),window_temp:Number(value('window_temp')),
        sensor:value('sensor').trim(),window:value('window').trim(),battery:value('battery').trim(),availability:value('availability').trim(),last_seen:value('last_seen').trim(),
        locks:parseMapping(value('locks')),external_inputs:parseMapping(value('external_inputs')),remote_modes:parseMapping(value('remote_modes')),
        child_protection:form.elements.namedItem('child_protection').checked,
        schedule_enabled:form.elements.namedItem('schedule_enabled').checked,
        enabled:form.elements.namedItem('enabled').checked,
        lqi:value('lqi').trim(),valve:value('valve').trim(),outdoor:value('outdoor').trim(),person:value('person').trim(),
        frost_temp:Number(value('frost_temp')),max_preheat_minutes:Number(value('max_preheat_minutes')),
        lqi_warning:Number(value('lqi_warning')),sensor_max_age:Number(value('sensor_max_age')),battery_warning:Number(value('battery_warning')),
        adaptive_start:form.elements.namedItem('adaptive_start').checked,
        profiles:Object.fromEntries(['comfort','eco','night','boost'].map(k=>[k,Number(value('profile_'+k))])),
        native_schedules:Object.fromEntries(value('native_schedules').split('\n').map(line=>line.trim()).filter(Boolean).map(line=>{const at=line.indexOf('=');if(at<1) throw Error('Sonoff-Zuordnung ungültig'); const cl=line.slice(0,at).trim();const days=Object.fromEntries(line.slice(at+1).split(',').map(item=>item.trim()).filter(Boolean).map(item=>{const split=item.indexOf(':');if(split<1)throw Error('Sonoff Tag:Entität erwartet');return [item.slice(0,split).trim(),item.slice(split+1).trim()];}));return [cl,days];})),
        schedule: Object.fromEntries(DOW.map((_,i)=>[String(i),parseSchedule(value('day'+i),this.data?.rooms?.[roomId]?.schedule?.[String(i)]||[])]))
      };
      if (await this._service('add_room',{room})) {this._editing=null;this._render();}
    } catch(error) {this._error=error.message||String(error);this._render();}
  }
}
customElements.define('heating-center-panel', HeatingCenterPanel);
