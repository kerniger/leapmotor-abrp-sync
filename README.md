# Leapmotor zu ABRP (A Better Routeplanner)

Dieses Projekt verbindet Deinen Leapmotor automatisch mit ABRP (A Better Routeplanner), um Deine aktuellen Fahrzeugdaten (Ladezustand / SoC, Parkstatus, etc.) für eine genaue Navigation zu nutzen.

**Der Clou:** Du musst hierfür keinen eigenen Server oder Raspberry Pi betreiben! Du nutzt einfach dieses kostenlose GitHub Actions Template, welches das Skript automatisch alle 5 Minuten im Hintergrund für Dich ausführt.

---

## 🚀 Einrichtung in 3 einfachen Schritten

### 1. Dein eigenes Repository erstellen
Klicke oben rechts auf den grünen Button **"Use this template"** -> **"Create a new repository"**.
- Wähle einen Namen für Dein Projekt (z.B. `mein-leapmotor-sync`).
- **WICHTIG:** Wähle **"Public"** (Öffentlich) aus! GitHub bietet für öffentliche Projekte unendlich viele kostenlose Server-Minuten an. Keine Sorge: Deine Passwörter bleiben über die "Secrets" komplett unsichtbar und verschlüsselt!
- Klicke auf "Create repository".

### 2. Deine Zugangsdaten hinterlegen (Sicher!)
Gehe in Deinem neu erstellten Repository auf **Settings** -> **Secrets and variables** -> **Actions**.
Klicke auf **"New repository secret"** und lege nacheinander folgende drei Secrets an:

1. **`LEAPMOTOR_USERNAME`** (Deine E-Mail-Adresse für die Leapmotor App)
2. **`LEAPMOTOR_PASSWORD`** (Dein Leapmotor Passwort)
3. **`ABRP_TOKEN`** (Dein ABRP Telemetry Token. In der ABRP App unter Einstellungen -> Fahrzeug -> Live-Daten -> "Verknüpfen" klicken, dort wird ein Token generiert.)

*(Die Zertifikate für den Login holt sich das Skript automatisch von einem öffentlichen Mirror. Die VIN sucht sich das Skript beim ersten Login automatisch aus Deinem Account!)*

### 3. Den Sync aktivieren
Gehe oben auf den Reiter **Actions**.
- GitHub fragt Dich vermutlich, ob Du Workflows aktivieren möchtest. Bestätige mit "I understand my workflows, go ahead and enable them".
- Klicke links auf **"ABRP Sync Loop"** und dann auf den blauen Button **"Run workflow"**, um den Sync zum ersten Mal manuell zu starten.
- Ab sofort läuft der Sync vollautomatisch im **5-Minuten-Takt** im Hintergrund!

---

## Sicherheit & Privatsphäre
- **Verschlüsselte Zugangsdaten:** Durch die Nutzung von GitHub Secrets liegen Deine Zugangsdaten (E-Mail, Passwort, Token) stark verschlüsselt auf den Servern von Microsoft/GitHub. Selbst wenn dieses Repository "Public" ist, kann niemand im Internet Deine Passwörter auslesen (auch Du selbst nicht mehr nach dem Speichern).
- **Keine Fernsteuerung möglich:** Um Deine Sicherheit zu garantieren, wurden in diesem Fork alle Funktionen zur Fernsteuerung (Auto aufschließen, Klimaanlage starten) aus dem Code des `leapmotor_client.py` **restlos entfernt**. Dieses Skript kann Deine Daten nur **lesen** (Read-Only Prinzip).
- **Zertifikate & API:** Da die Leapmotor-API keinen echten "Nur-Lese"-Login anbietet, nutzt das Skript Deinen regulären Login. Die benötigten App-Zertifikate werden dynamisch aus einem öffentlichen Mirror geladen und sind nicht mehr Teil dieses Repositories.
- **TLS-Zertifikatsprüfung:** Die TLS-Zertifikatsprüfung (`verify_tls`) ist im Skript standardmäßig deaktiviert, da der offizielle Leapmotor-API-Endpunkt (carownerservice) in den meisten Standard-Linux-Umgebungen eine unvollständige oder nicht vertrauenswürdige Zertifikatskette ausliefert und die Abfragen sonst mit einem `SSLError` abbrechen würden. Dies ist eine Besonderheit der Leapmotor-Serverarchitektur.
- **Haftungsausschluss:** Die Nutzung erfolgt auf eigene Gefahr. Weder der Entwickler dieses Skripts noch GitHub übernehmen Haftung für gesperrte Accounts oder unerwartetes Verhalten der inoffiziellen Leapmotor API.
