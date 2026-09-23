[🇬🇧 English Version Below](#english-version)

# Leapmotor zu ABRP (A Better Routeplanner)

Dieses Projekt verbindet Deinen Leapmotor automatisch mit ABRP (A Better Routeplanner), um Deine aktuellen Fahrzeugdaten (Ladezustand / SoC, Parkstatus, etc.) für eine genaue Navigation zu nutzen.

**Die Lösung ohne eigenen Server:** Da kostenlose GitHub-Actions sehr unzuverlässig für Live-Daten im Minutentakt sind, nutzt dieses Setup das kostenlose Cloud-Hosting von **Render.com**. Das Skript läuft völlig automatisch in der Cloud und prüft alle 5 Minuten auf neue Fahrzeugdaten.

---

## 🚀 Einrichtung in 3 simplen Schritten

### Schritt 1: Das Skript bei Render starten
Du musst dafür nichts herunterladen und auch keinen eigenen GitHub Account besitzen!

1. Gehe auf **[Render.com](https://render.com/)** und erstelle dir einen kostenlosen Account (oder logge dich ein).
2. Klicke im Dashboard oben rechts auf **"New"** und wähle **"Web Service"**.
3. Wähle **"Public Git repository"** aus und kopiere diesen Link in das Textfeld:
   `https://github.com/kerniger/leapmotor-abrp-sync`
   Klicke dann auf **"Continue"**.
4. Fülle die Einstellungen wie folgt aus:
   - **Name:** beliebig (z.B. `leapmotor-abrp`)
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python render_app.py`
   - **Instance Type:** Ganz unten sicherstellen, dass **"Free"** ($0/month) ausgewählt ist.
5. Klappe den Bereich **"Advanced"** (oder Environment Variables) auf und klicke auf **"Add Environment Variable"**. Füge folgende drei Passwörter ein:
   - `LEAPMOTOR_USERNAME` = (Deine E-Mail-Adresse der Leapmotor App)
   - `LEAPMOTOR_PASSWORD` = (Dein Leapmotor Passwort)
   - `ABRP_TOKEN` = (Dein ABRP Telemetry Token. In der ABRP App unter "Live-Daten" -> "Verknüpfen" generieren)
   
   > 💡 **WICHTIGER TIPP:** Lege dir am besten in der Leapmotor App einen kostenlosen Zweit-Account an und teile (share) dein Fahrzeug mit diesem. Nutze dann hier die Login-Daten des Zweit-Accounts. So verhinderst du, dass du auf deinem Handy ständig aus der Leapmotor-App ausgeloggt wirst!
6. Klicke ganz unten auf **"Create Web Service"**.

Render startet nun Dein persönliches Skript. Oben links im Dashboard siehst Du eine URL (z.B. `https://leapmotor-abrp-xyz.onrender.com`). 

### Schritt 2: Den "Schlaf-Modus" austricksen (Wichtig!)
Kostenlose Server bei Render.com schalten sich nach 15 Minuten ab, wenn niemand die Website besucht. Um den 5-Minuten-Takt von ABRP 24/7 am Leben zu erhalten, nutzen wir einen simplen Trick:

1. Kopiere dir die oben genannte URL deines Render-Services.
2. Gehe auf **[UptimeRobot.com](https://uptimerobot.com/)** und erstelle einen kostenlosen Account.
3. Klicke auf **"Add New Monitor"**:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `Render Wachhalter`
   - **URL (or IP):** *(Hier die Render URL einfügen)*
   - **Monitoring Interval:** `10 minutes` (oder 5 minutes)
4. Klicke auf **"Create Monitor"**.

**Fertig!** UptimeRobot ruft nun rund um die Uhr automatisch deine Render-URL auf. Das Skript läuft dauerhaft im Hintergrund und prüft alle 5 Minuten auf neue, ausreichend aktuelle Fahrzeugdaten für ABRP.

### Schritt 3: Erfolg prüfen
1. Kontrolliere den aktuellen Ladestand (SoC) in Deiner Leapmotor App.
2. Öffne die ABRP App, gehe auf Deine Fahrzeugeinstellungen. Der Status für Live-Daten sollte nun auf **"Verbunden"** stehen.
3. Prüfe, ob der in ABRP angezeigte Akkustand mit der Leapmotor App übereinstimmt.

### Spätere Updates einspielen
Da Du das Repository "Public" verknüpft hast, musst Du Updates manuell anstoßen:
Wenn es neue Funktionen gibt, logge Dich einfach bei Render.com ein, klicke auf Deinen Web Service und drücke oben rechts auf **"Manual Deploy" -> "Deploy latest commit"**.

---

## 💻 Alternative: Self-Hosting (Docker / NAS / Raspberry Pi)
Wenn Du ohnehin einen eigenen kleinen Server 24/7 am Laufen hast, ist das die beste und stabilste Lösung – komplett ohne Cloud-Abhängigkeiten!

Das fertige Image `ghcr.io/kerniger/leapmotor-abrp-sync:latest` unterstützt
`amd64` und `arm64`. Passe die drei Werte in `docker-compose.yml` an und starte
den Container mit:

`docker compose up -d`

Für spätere Updates genügen:

`docker compose pull && docker compose up -d`

### Synology Container Manager ohne SSH

1. Öffne **Container Manager → Projekt → Erstellen**.
2. Wähle einen leeren Ordner auf dem NAS als Projektpfad.
3. Wähle als Quelle **docker-compose.yml erstellen** und füge den Inhalt der
   [`docker-compose.yml`](docker-compose.yml) aus diesem Repository ein.
4. Ersetze `LEAPMOTOR_USERNAME`, `LEAPMOTOR_PASSWORD` und `ABRP_TOKEN` durch
   Deine Werte und stelle das Projekt fertig.

Container Manager lädt das fertige Image selbstständig. Es sind weder SSH noch
Root-Rechte und auch kein lokaler Build erforderlich. Zugangsdaten stehen in
der Projektkonfiguration im Klartext und sollten nur für NAS-Administratoren
zugänglich sein.

Der Container lädt sich automatisch die nötigen Zertifikate und schickt Deine Daten im 5-Minuten-Takt an ABRP.

---

## Sicherheit & Privatsphäre
- **Verschlüsselte Zugangsdaten:** Bei Render liegen Deine Umgebungsvariablen stark verschlüsselt auf Enterprise-Servern. Sie tauchen nie öffentlich im Code auf.
- **Keine Fernsteuerung möglich:** Um Deine Sicherheit zu garantieren, wurden in diesem Skript alle Funktionen zur Fernsteuerung (Auto aufschließen, Klimaanlage starten) aus dem Code **restlos entfernt**. Dieses Skript kann Deine Daten nur **lesen** (Read-Only Prinzip).
- **Zertifikate & API:** Da die Leapmotor-API keinen echten "Nur-Lese"-Login anbietet, nutzt das Skript Deinen regulären Login. Die Zertifikate für den Login holt sich das Skript beim Start automatisch.
- **Haftungsausschluss:** Die Nutzung erfolgt auf eigene Gefahr. Weder der Entwickler dieses Skripts noch die Cloud-Anbieter übernehmen Haftung für gesperrte Accounts oder unerwartetes Verhalten der Leapmotor API.

<br>
<br>
<br>

---

<a name="english-version"></a>
# Leapmotor to ABRP (A Better Routeplanner)

This project automatically connects your Leapmotor to ABRP (A Better Routeplanner) to sync your live vehicle data (State of Charge / SoC, parking status, etc.) for accurate routing.

**The serverless solution:** Since free GitHub Actions are highly unreliable for minutely live data, this setup uses the free cloud hosting from **Render.com**. The script runs entirely automatically in the cloud and checks for new vehicle data every 5 minutes.

---

## 🚀 Setup in 3 Simple Steps

### Step 1: Start the script on Render
You do not need to download anything and you do not even need a GitHub account!

1. Go to **[Render.com](https://render.com/)** and create a free account (or log in).
2. Click **"New"** in the top right of your dashboard and select **"Web Service"**.
3. Select **"Public Git repository"** and copy this link into the text field:
   `https://github.com/kerniger/leapmotor-abrp-sync`
   Then click **"Continue"**.
4. Fill out the settings as follows:
   - **Name:** anything you like (e.g., `leapmotor-abrp`)
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python render_app.py`
   - **Instance Type:** Scroll down and make sure **"Free"** ($0/month) is selected.
5. Expand the **"Advanced"** (or Environment Variables) section and click **"Add Environment Variable"**. Add the following three passwords/tokens:
   - `LEAPMOTOR_USERNAME` = (Your Leapmotor App email address)
   - `LEAPMOTOR_PASSWORD` = (Your Leapmotor password)
   - `ABRP_TOKEN` = (Your ABRP Telemetry Token. Generate it in the ABRP app under "Live Data" -> "Link")
   
   > 💡 **IMPORTANT TIP:** We highly recommend creating a free secondary account in the Leapmotor app and sharing your vehicle with it. Use the login details of that secondary account here. This prevents the script from constantly logging you out of the Leapmotor app on your phone!
6. Scroll down and click **"Create Web Service"**.

Render will now start your personal script. In the top left of the dashboard, you will see a URL (e.g., `https://leapmotor-abrp-xyz.onrender.com`).

### Step 2: Bypass the "Sleep Mode" (Important!)
Free servers on Render.com go to sleep after 15 minutes without any website visitors. To keep the 5-minute ABRP sync alive 24/7, we use a simple trick:

1. Copy the URL of your Render service mentioned above.
2. Go to **[UptimeRobot.com](https://uptimerobot.com/)** and create a free account.
3. Click **"Add New Monitor"**:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `Render Keep-Awake`
   - **URL (or IP):** *(Paste your Render URL here)*
   - **Monitoring Interval:** `10 minutes` (or 5 minutes)
4. Click **"Create Monitor"**.

**Done!** UptimeRobot will now automatically ping your Render URL around the clock. The script will run continuously in the background and check for fresh vehicle data to forward to ABRP every 5 minutes.

### Step 3: Verification
1. Check your current State of Charge (SoC) in the Leapmotor app.
2. Open the ABRP app, go to your vehicle settings. The status for Live Data should now say **"Connected"**.
3. Verify that the battery level displayed in ABRP matches the Leapmotor app.

### Applying future updates
Because you linked the repository as "Public", you must trigger updates manually:
Whenever there are new features, simply log into Render.com, click on your Web Service, and click **"Manual Deploy" -> "Deploy latest commit"** in the top right corner.

---

## 💻 Alternative: Self-Hosting (Docker / NAS / Raspberry Pi)
If you already run your own small server 24/7, this is the best and most robust solution – completely independent of cloud limits!

The prebuilt image `ghcr.io/kerniger/leapmotor-abrp-sync:latest` supports
`amd64` and `arm64`. Adjust the three values in `docker-compose.yml` and start
the container with:

`docker compose up -d`

To install future updates, run:

`docker compose pull && docker compose up -d`

### Synology Container Manager without SSH

1. Open **Container Manager → Project → Create**.
2. Select an empty folder on the NAS as the project path.
3. Choose **Create docker-compose.yml** as the source and paste the contents of
   this repository's [`docker-compose.yml`](docker-compose.yml).
4. Replace `LEAPMOTOR_USERNAME`, `LEAPMOTOR_PASSWORD`, and `ABRP_TOKEN` with
   your values and finish creating the project.

Container Manager downloads the prebuilt image automatically. SSH, root access,
and a local image build are not required. Credentials are stored as plain text
in the project configuration and should only be accessible to NAS administrators.

The container will automatically download the necessary certificates and check for fresh vehicle data to forward to ABRP every 5 minutes.

---

## Security & Privacy
- **Encrypted credentials:** On Render, your environment variables are strongly encrypted on enterprise servers. They never appear publicly in the code.
- **No remote control possible:** To guarantee your security, all remote control functions (unlocking the car, starting the AC) have been **completely removed** from the code. This script can only **read** your data (Read-Only principle).
- **Certificates & API:** Since the Leapmotor API does not offer a true "Read-Only" login, the script uses your regular login. The script automatically fetches the required certificates for the login on startup.
- **Disclaimer:** Use at your own risk. Neither the developer of this script nor the cloud providers assume liability for locked accounts or unexpected behavior of the Leapmotor API.

## Telemetrie-Korrekturen und Einstellungen (September 2026)

Der Sync übernimmt die geprüfte EU-Statusinterpretation aus Leapmotor HA 0.7.3:
Ladeerkennung einschließlich REEV/READY/Rekuperation, Parkzustand über Gang und
Geschwindigkeit, signierte GPS-Koordinaten und T03-Statusfelder. Signal 1939 ist
kein Ladesignal; die Innenraumtemperatur wird nicht mehr als Außentemperatur gesendet.
CN-Fahrzeuge werden durch dieses Update nicht unterstützt.

| Umgebungsvariable | Standard | Bedeutung |
|---|---|---|
| `LEAPMOTOR_VIN` | automatische Auswahl bei genau einem Fahrzeug | Bei mehreren Fahrzeugen zwingend setzen; der ABRP-Token muss zu diesem Fahrzeug gehören. |
| `SYNC_INTERVAL` | `300` | Abfrageintervall in Sekunden. |
| `MAX_TELEMETRY_AGE` | `900` | Maximales Alter der Fahrzeugdaten in Sekunden. |
| `TELEMETRY_STATE_DIR` | `state` neben dem Skript | Beschreibbarer Speicher für GPS-Vorzeichen und zuletzt gesendeten Fahrzeugzeitpunkt. |

ABRP erhält den **Fahrzeugzeitpunkt**, nicht die Uhrzeit der Cloud-Abfrage.
Fehlende, mehr als 60 Sekunden zukünftige, zu alte oder bereits gesendete
Zeitpunkte werden übersprungen. Sekunden, Millisekunden und ISO-Zeitstempel mit
Zeitzone werden akzeptiert; beim T03 hat `collectTimeMs` Vorrang. ISO-Werte ohne
Zeitzone werden nicht geraten. Ein schlafendes Fahrzeug erzeugt daher nicht
alle fünf Minuten einen neuen ABRP-Datenpunkt. SoC 0 % bleibt ein gültiger Wert;
die noch ungeklärten SOC-Ausreißer beim Aufwachen werden nicht pauschal gefiltert.

GPS-Vorzeichen werden pro VIN gespeichert. Fehlen sowohl signierte Koordinaten
als auch bekannte Vorzeichen, werden Positionen ausgelassen. SoC kann trotzdem
übermittelt werden. Die Compose-Datei verwendet ein persistentes Volume; bei
`docker run` dafür `-v leapmotor-abrp-state:/app/state` ergänzen. Render Free kann
den lokalen Zustand bei einem Redeploy verlieren; ein dauerhafter Datenträger
ist für die Speicherung über Redeploys hinweg nötig. Nur einen Sync-Prozess pro
Fahrzeug/ABRP-Zuordnung betreiben.

Die Zustandsdateien enthalten keine Zugangsdaten oder vollständigen Koordinaten,
sondern Hashes, Vorzeichen, Bestätigungszähler und den letzten Sendezeitpunkt.
Die Speicherung erfolgt erst nach bestätigter ABRP-Annahme. Fehlerantworten und
Client-Diagnosen werden nicht mit Zugangsdaten ins Log übernommen.

Tests: `python -m unittest discover -s tests -v`. Sie verwenden ausschließlich
synthetische Daten; der Container wird zusätzlich ohne Netzwerk getestet.

## Telemetry corrections and configuration (September 2026)

The bridge now uses the validated EU status interpretation from Leapmotor HA
0.7.3: charging detection including REEV, READY and regenerative braking;
parking derived from gear/speed; signed GPS coordinates; and T03 status fields.
Signal 1939 is not a charging indicator. Cabin temperature is no longer sent
as outside temperature. This update does not add CN vehicle support.

Set `LEAPMOTOR_VIN` when the account has multiple vehicles and use the matching
ABRP vehicle token. Auto-selection is allowed only for a single vehicle.
`SYNC_INTERVAL` defaults to 300 seconds, `MAX_TELEMETRY_AGE` to 900 seconds,
and `TELEMETRY_STATE_DIR` to the `state` directory beside the script.

Telemetry carries the vehicle timestamp. Missing, stale, duplicate, out-of-order
or more than 60 seconds future timestamps are skipped. Epoch seconds,
milliseconds and timezone-aware ISO timestamps are supported, with T03
`collectTimeMs` preferred. Timezone-less timestamps are skipped. Sleeping cars
therefore do not generate artificial fresh updates. Zero SOC remains valid;
unresolved wake-up SOC transients are not filtered speculatively.

GPS hemisphere signs are remembered per VIN. Positions with neither signed
coordinates nor known signs are omitted while SOC can still be forwarded.
Compose includes a persistent state volume; for `docker run`, add
`-v leapmotor-abrp-state:/app/state`. Render Free may lose local state on redeploy;
use persistent storage to retain it across deployments. Run one sync process per
vehicle/token assignment. State contains hashes, signs, counters and the last
accepted vehicle timestamp, not credentials or full coordinates, and is saved
only after ABRP confirms acceptance. Raw client errors are not logged.

Run offline regressions with `python -m unittest discover -s tests -v`.
The container smoke test and regression suite also run without network access.
