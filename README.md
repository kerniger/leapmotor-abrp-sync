[🇬🇧 English Version Below](#english-version)

# Leapmotor zu ABRP (A Better Routeplanner)

Dieses Projekt verbindet Deinen Leapmotor automatisch mit ABRP (A Better Routeplanner), um Deine aktuellen Fahrzeugdaten (Ladezustand / SoC, Parkstatus, etc.) für eine genaue Navigation zu nutzen.

**Die Lösung ohne eigenen Server:** Da kostenlose GitHub-Actions sehr unzuverlässig für Live-Daten im Minutentakt sind, nutzt dieses Setup das kostenlose Cloud-Hosting von **Render.com**. Das Skript läuft völlig automatisch in der Cloud und aktualisiert Deinen Ladestand zuverlässig alle 5 Minuten.

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

**Fertig!** UptimeRobot ruft nun rund um die Uhr automatisch deine Render-URL auf. Das Skript läuft dauerhaft im Hintergrund und schickt Deinen Akkustand alle 5 Minuten live an ABRP.

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

1. Klone dieses Repository auf deinen Server:
   `git clone https://github.com/kerniger/leapmotor-abrp-sync.git`
2. Passe die Passwörter in der Datei `docker-compose.yml` an.
3. Starte den Container im Hintergrund:
   `docker-compose up -d --build`

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

**The serverless solution:** Since free GitHub Actions are highly unreliable for minutely live data, this setup uses the free cloud hosting from **Render.com**. The script runs entirely automatically in the cloud and reliably updates your SoC every 5 minutes.

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

**Done!** UptimeRobot will now automatically ping your Render URL around the clock. The script will run continuously in the background and sync your battery level to ABRP every 5 minutes.

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

1. Clone this repository to your server:
   `git clone https://github.com/kerniger/leapmotor-abrp-sync.git`
2. Adjust your passwords in the `docker-compose.yml` file.
3. Start the container in the background:
   `docker-compose up -d --build`

The container will automatically download the necessary certificates and push your data to ABRP every 5 minutes.

---

## Security & Privacy
- **Encrypted credentials:** On Render, your environment variables are strongly encrypted on enterprise servers. They never appear publicly in the code.
- **No remote control possible:** To guarantee your security, all remote control functions (unlocking the car, starting the AC) have been **completely removed** from the code. This script can only **read** your data (Read-Only principle).
- **Certificates & API:** Since the Leapmotor API does not offer a true "Read-Only" login, the script uses your regular login. The script automatically fetches the required certificates for the login on startup.
- **Disclaimer:** Use at your own risk. Neither the developer of this script nor the cloud providers assume liability for locked accounts or unexpected behavior of the Leapmotor API.
