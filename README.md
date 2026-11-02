<p align="center"><img src="assets/heating-center-logo.svg" width="150" height="150" alt="HA Heating Center Logo"></p>

# HA Heating Center

[![HACS custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5)](https://hacs.xyz/)

**Heizungszentrale für Home Assistant** — lokal, herstellerunabhängige `climate`-Grundsteuerung und Sonoff-TRVZB-Erweiterungen über Zigbee2MQTT. Eigenes Admin-Dashboard in der Seitenleiste. Keine Cloud und keine weiteren Python-Pakete erforderlich.

> **Version 0.3.0-beta.11 — öffentlich testbare Entwicklungsversion.** Die Python-Logiktests und JavaScript-Syntaxprüfungen laufen lokal. Ein vollständiger Integrationstest in einer realen Home-Assistant-Installation und mit echten Thermostaten wurde **noch nicht** durchgeführt. Zunächst nur **einen Raum** ausprobieren und Home Assistant vorher sichern. Keine zertifizierte Kessel-/Frostschutzsteuerung.

## Versionen und Logo

Ab `0.3.0-beta.11` nutzt HA Heating Center benannte GitHub-Releases zur Anzeige der Versionsnummer in HACS. Bei Vorabversionen muss die Berücksichtigung von Pre-Releases in HACS aktiviert sein. Der aktuelle Stand in `main` bleibt weiterhin über `Erneut herunterladen → main` installierbar.

Das eigene Icon liegt ab Home Assistant 2026.3 unter `custom_components/heating_center/brand/`. Auf GitHub wird dasselbe Motiv im README und in der Heating-Center-Seitenleiste angezeigt.

### Beta.11

- Gruppen-Solltemperatur lässt sich wieder eingeben: kein Fokusverlust bei HA-Zustandsupdates, Eingaben bleiben erhalten.
- Gruppen-Eingaben validiert (5–30 °C in 0,5-°C-Schritten).
- Neues eigenständiges Heating-Center-Logo und HACS-Versionsveröffentlichung.
- Unveränderte Thermostat-/Zigbee-Steuerlogik.

## Installation über HACS

1. In Home Assistant ein Backup erstellen.
2. HACS → **Benutzerdefinierte Repositories** → `https://github.com/Roy-82/ha-heating-center` → Typ **Integration**.
3. **HA Heating Center** installieren und Home Assistant neu starten.
4. Einstellungen → Geräte & Dienste → Integration hinzufügen → **HA Heating Center**.
5. Links in der Seitenleiste **Heating Center** öffnen (Administrator).
6. Raum hinzufügen, bestehende `climate.*`-Entitäten zuweisen (kein erneutes Zigbee-Pairing), Diagnose- und Temperaturentitäten prüfen, speichern. Neue Räume sind **standardmäßig deaktiviert**.
7. Optional Kindersicherung und externe Temperatur aktivieren, **danach den Raum aktivieren**. Auslösevorgänge und Thermostatwerte mindestens einen vollständigen Heizzyklus prüfen.

## Funktionen

- Räume mit einem oder mehreren Thermostaten, frei benannte Gruppen und Gruppensollwerte.
- Zeitpläne Montag–Sonntag mit Nachtabsenkung, manuelle autorisierte Overrides, Komfort-/Eco-/Nacht-/Boost-Temperaturprofile.
- Hausmodi **Zuhause**, **Abwesend**, **Urlaub** sowie optionaler Anwesenheitssensor und datierte Urlaubszeiträume.
- Adaptive Vorheizschätzung, Außentemperatur-Einfluss, Verlauf der Ist-/Solltemperaturen und Heizbedarfsübersicht. Lernwerte sind Schätzwerte; kein exaktes Vorhersagemodell.
- Sensorzuordnung für externe Raumtemperatur: `sensor.*` → Zigbee2MQTT `number.*` `external_temperature_input` und `select.*` `temperature_sensor_select`. Regelmäßiges Synchronisieren alle 10 Minuten und sofort ab 0,2 °C Änderung. Bei ungültigem Sensor Rückfall auf `local_temperature`, sofern diese `select.*`-Entität verfügbar ist.
- **Kindersicherung**: Geräte-Sperre einschalten und nach manueller Entsperrung nachsetzen; Temperaturänderungen am gesperrten Gerät verwerfen und hinterlegten Sollwert wiederherstellen. Ereignisgesteuert sowie per 60-s-Watchdog, begrenzte Wiederholungen und Verifizierung des gemeldeten Sollwerts.
- Fensterkontakt mit Absenkung, Frostschutzuntergrenze für Sollwerte und Störungen/Warnungen zu Batterie, Zigbee-Verfügbarkeit, `last_seen`, LQI, externer Temperatur, fehlenden Setpoint-Antworten.
- Warnungen als persistente HA-Mitteilung oder über vorhandenen `notify.*`-Dienst, mit Ruhezeit und Wiederholabstand.
- Zuordnung der **Wolf COB-20**-Telemetrie aus bestehenden Home-Assistant-Entitäten. Das ist **nur lesend**. eBUS-Verbindung und Kesselsteuerung erfordern später den tatsächlichen Adapter und die Prüfung der eBUS-Datenpunkte.
- Optionaler manueller Export eines Wochenprogramms in die Sonoff-TRVZB-`text.*`-Entitäten. **Kein automatisches Umschalten auf Geräte-Auto-Modus**; damit kann der HA-Zeitplan nicht unbeabsichtigt mit dem Sonoff-Wochenplan konkurrieren.

## Priorität der Regelung

Fenster offen → Urlaub → Abwesend → manuelle autorisierte Übersteuerung → adaptive Vorheizphase → Wochenplan → Basistemperatur. Alle Werte unterliegen mindestens der eingestellten Frostschutz-Sollwertuntergrenze. Die Sicherheit von Heizkessel, Rohrleitungen und Gebäude wird dadurch **nicht** garantiert.

## Sonoff-Anbindung (Zigbee2MQTT)

Alle `climate`-Entitäten funktionieren ohne Sonoff-spezifische Zuordnungen für die Basissollwertsteuerung. Für die Zusatzfunktionen muss jeweils die richtige Home-Assistant-Entität des **gleichen Thermostats** zugeordnet werden:

| Bereich | Entitätsart | Zigbee2MQTT-Gerätefunktion |
|---|---|---|
| Heizkörper | `climate.*` | `occupied_heating_setpoint` |
| Lokale Kindersperre | `switch.*` oder `select.*` oder `lock.*` | `child_lock` |
| Externer Temperaturwert | `number.*` | `external_temperature_input` |
| Quelle intern/extern | `select.*` | `temperature_sensor_select` |
| Sonoff-Wochenplan | `text.*` je Tag | `weekly_schedule_monday` bis `sunday` |
| Diagnose | `sensor.*`, `binary_sensor.*` | Batterie, LQI, Gerät online, Letzter Kontakt |

Die tatsächlichen Entitätsnamen hängen von deinen Zigbee2MQTT-Geräten, Geräteversionen und Einstellungen ab. Nicht vorhandene Zusatzentitäten werden nicht erfunden. Bitte in **Entwicklerwerkzeuge → Zustände** nachsehen.

### Was die Kindersicherung ausdrücklich nicht kann

Die Taste am Sonoff TRVZB kann die *physische* Kindersperre nach ca. drei Sekunden wieder aufheben. Heating Center versucht erneut zu sperren und den HA-Sollwert wiederherzustellen, **sobald HA/Zigbee2MQTT die Änderung bemerkt**. Das ist bei Funkstörungen, Geräten ohne Batterie, HA-Ausfall oder Zigbee-Störungen nicht möglich. Es ist **keine manipulationssichere Sperre**. Falls die Entität für `child_lock` fehlt, bleibt nur die Software-Sollwertkontrolle.

## Einstellungen und Bedienung

Im Dashboard: **Räume & Gruppen**, **Diagnose & Verlauf**, **Systemeinstellungen**. Der Raumeditor enthält Zeitpläne, Sensoren, Zuordnungen und Profile. Zusätzliche Serviceaktionen sind unter `heating_center.*` verfügbar; `config_entry_id` ist bei allen notwendig. Einstellungen werden lokal in `.storage/heating_center` gespeichert.

## Entwicklung und Tests

```bash
python -m unittest discover -s tests -v
python -m compileall -q custom_components
node --check custom_components/heating_center/frontend/heating-center-panel.js
```

**Bekannte Einschränkungen:** Weder die HA-Core-/Frontend-Kompatibilität noch die Sonoff-TRVZB-Hardwareinteraktion wurde in einer Live-Installation bestätigt. Signalqualität (LQI) beweist keine Paket-Zuverlässigkeit. Serviceaufrufe bestätigen nicht unmittelbar die mechanische Ventilbewegung. Geräteinterne Zeitpläne können ohne Geräteseite in `auto` keinen HA-Ausfall übernehmen. Wolf-eBUS-Schreibzugriffe fehlen bewusst bis zur Sicherheitsprüfung.

Siehe [ROADMAP.md](ROADMAP.md) für abgeschlossene und noch offene Arbeitspakete.

Quellen: [Zigbee2MQTT TRVZB](https://www.zigbee2mqtt.io/devices/TRVZB.html), [Home Assistant Custom Panel](https://developers.home-assistant.io/docs/frontend/custom-ui/panel/).
