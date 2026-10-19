# GPS Jamming & Spoofing Watch — Bahrain

A free ($0/month) version of the dashboard that runs entirely on GitHub.

- **Every 5 minutes** GitHub checks all aircraft within 250 nm of Bahrain using free public ADS-B data.
- **Jamming** is confirmed when 3 or more aircraft close together report degraded GPS.
- **Spoofing** is confirmed when 2 or more aircraft show spoofing signs, or the same aircraft shows them on two separate checks. Spoofing signs include GPS altitude disagreeing with pressure altitude, impossible position jumps, or several aircraft "sitting" at the same spot.
- **One alarm email per new incident**, in HTML. The email has a single link that opens a satellite map showing only the affected aircraft, with the date and time for each one. Anyone with the link can open it.
- **Dashboard**: a live dashboard and an incident list on your own free website.
- **Monthly report** of all confirmed incidents, emailed on the 1st of each month at 07:50 Bahrain time.

Expect an alarm roughly **5–25 minutes** after an incident begins, because GitHub sometimes starts its scheduled checks late.

---

## One-time setup (about 20 minutes)

You'll need two free accounts: **GitHub** (to run it) and **Gmail** (to send the emails).

### 1. Create a GitHub account
Go to **github.com** → **Sign up**, then follow the steps.

### 2. Create the repository
1. Click **+** (top right) → **New repository**.
2. **Repository name:** `gps-watch`
3. Select **Public**. This is required for it to stay free at 5-minute checks.
4. Click **Create repository**.

### 3. Upload the files
1. On the new repository page, click the link **uploading an existing file**.
2. Unzip `gps-watch.zip` on your computer, open the `gps-watch` folder, select **everything inside it** (including the `.github` folder) and drag it onto the GitHub page.
3. Click **Commit changes**.
4. **Check:** the repository should now show a folder named `.github`. If it doesn't (some computers hide folders that start with a dot), add the two schedule files by hand:
   - Click **Add file** → **Create new file**.
   - Type the name `.github/workflows/watch.yml`.
   - Open `watch.yml` from the zip in Notepad, copy everything, paste it into GitHub, then click **Commit changes**.
   - Repeat for `.github/workflows/monthly.yml`.

### 4. Turn on the website
**Settings** → **Pages** (left menu) → under **Source** choose **GitHub Actions**.

### 5. Get a Gmail "app password" (lets GitHub send email from Gmail)
1. Use a Gmail account for sending. A new one just for this is a good idea, e.g. `bahrain.gps.watch@gmail.com`.
2. In that account, turn on **2-Step Verification** (myaccount.google.com → Security).
3. Go to **myaccount.google.com/apppasswords**, create a password named `gps-watch`, and copy the 16-letter code.

### 6. Store the email details in GitHub (kept secret, never shown publicly)
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Add three secrets:

| Name | Value |
|---|---|
| `SMTP_USER` | the Gmail address, e.g. `bahrain.gps.watch@gmail.com` |
| `SMTP_PASS` | the 16-letter app password |
| `ALARM_TO` | who receives alarms and reports, e.g. `rmt@tra.org.bh`. Separate several addresses with commas. |

### 7. Start it
1. Open the **Actions** tab. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
2. Click **GPS watch (every 5 minutes)** → **Run workflow** → **Run workflow**.
3. After about a minute it should show a green tick. Your dashboard is now at **https://YOUR-GITHUB-NAME.github.io/gps-watch/**

From now on it runs by itself every 5 minutes.

---

## Good to know

- **Emails not arriving at a work address?** Ask IT to allow-list the Gmail sender address. Company mail filters often block automated emails from Gmail.
- **Pause the alarms:** delete the `ALARM_TO` secret. Add it back to resume.
- **Stop everything:** Actions tab → **GPS watch** → **⋯** → **Disable workflow**.
- **Re-send a month's report:** Actions → **Monthly report** → **Run workflow**, then type the month, e.g. `2026-10`.
- **The website and incident data are public.** Anyone who has the address can view them. The Gmail password stays secret.
- **Ships are not covered yet.** Free ship-tracking (AIS) data needs a constant live connection, which this 5-minute setup doesn't have.
- **Tuning:** the thresholds are at the top of `monitor.py`, for example how many aircraft confirm jamming (3) or the GPS/pressure altitude gap for spoofing (3,500 ft).
- **GitHub pauses schedules on inactive repositories** after 60 days. The monthly report saves a file every month, which keeps this one active.

## Files
- `monitor.py`: checks the aircraft, decides what is confirmed, builds the website, and sends emails.
- `site/`: dashboard (`index.html`) and incident map (`map.html`).
- `data/incidents.json`: log of every confirmed incident.
- `reports/`: saved monthly reports.
- `.github/workflows/`: the two schedules (every 5 minutes, and monthly).
