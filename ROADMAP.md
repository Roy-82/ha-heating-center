# Roadmap — HA Heating Center

Der Stand bezieht sich auf **Quellcode**, nicht auf verifizierte Live-Hardware. Die Entwicklungsversion ist kein freigegebenes Heizungs- oder Sicherheitsprodukt.

## In v0.3.0-beta.1 im Code

- [x] Eigenständige HACS-Integration, Einrichtung, Admin-Seitenleiste, dauerhafte lokale Speicherung
- [x] Bestehende Home-Assistant-Thermostate einzeln oder gruppiert
- [x] Basis-Sollwerte, Gruppen-Sollwerte, Zeitpläne, Nachtabsenkung, autorisierte manuelle Overrides
- [x] Komfort, Eco, Nacht und zeitgesteuerter Boost (Dashboard)
- [x] Fensterabsenkung, Abwesenheit, Urlaub und optional Anwesenheit
- [x] Externe Sensoren an Sonoff TRVZB übertragen, Rückfall auf internen Sensor bei Ausfall
- [x] Physische Kindersperre reaktivieren, fremde Sollwertänderungen zurücksetzen und Wiederholungen begrenzen
- [x] Überwachung von Batterie, Online-Status, Zeitstempel, LQI und Sollwert-Rückmeldungen
- [x] Benachrichtigungen mit Ruhezeiten und Duplikatunterdrückung
- [x] Adaptive Aufheizzeit-Schätzung, Heizbedarf und Ist-/Soll-Temperaturhistorie
- [x] Freiwilliger Export von Sonoff-Gerätewochenplänen (Betriebsart bleibt unverändert)
- [x] Wolf COB-20 Anzeige mittels bereits vorhandener HA-Entitäten (nur lesen)

## Noch zu validieren / ausbauen

- [ ] Live-Tests in HA OS und Sonoff TRVZB, u. a. mehrere Ventile pro Raum
- [ ] Bedienbarkeit, Barrierefreiheit, automatische Entitätsauswahl und HA-Entity-Registry-Renames
- [ ] Benachrichtigungstests an lokal konfigurierten `notify.*`-Diensten
- [ ] Sonoff-Offline-Zeitplanstrategie ohne Konflikte mit HA; kontrolliertes Umschalten erst nach Hardwaretest
- [ ] Zigbee-Router-/Mesh-Diagnose und automatische Entitätserkennung von Z2M
- [ ] Weitere Thermostat-Adapter, herstellerspezifische Diagnose und Kalibrierung
- [ ] Exakte Vorheiz-Validierung mit realen Aufheizkurven über mehrere Wochen
- [ ] Echte Wolf COB-20 eBUS-Hardwareanbindung und nur nach dokumentierter Prüfung sichere Schreibfunktionen; Kessel-Frostschutz, Warmwasser, Heizpumpen und Mindestzeiten niemals außer Kraft setzen

## Sicherheit und Umfang

Für neue Räume keine Gerätewrites ohne aktivierte Raumsteuerung. Regelmäßig gültige Heizpläne vorhalten. Remote-Sensor-Fallback erfordert vom Gerät bereitgestellte `select`-Entität. Fehlerfälle dokumentieren und bei Verbindungsausfall nicht endlos wiederholen.
