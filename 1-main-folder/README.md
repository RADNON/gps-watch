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

## Team reports (staff add GPS interference reports on the dashboard)

The dashboard has a **Team reports** panel. Staff enter the date, time (Bahrain), affected band(s) (L1, L2, L5, or Clear) and optional notes. Reports are saved in a Google Sheet that only you can open. Adding or viewing reports needs the **team PIN**, so the public can't see or add them. Each browser remembers the PIN after the first use.

### One-time setup (about 10 minutes)
1. Sign in to Google as `bahrain.gps.watch@gmail.com` and create a new Google Sheet at **sheets.new**. Name it `GPS Watch - Team reports`.
2. In the sheet, click **Extensions → Apps Script**.
3. Delete everything in the code box, paste the whole contents of `apps-script/Code.gs`, then change `CHANGE-ME` on line 9 to your team PIN, e.g. `'TRA-4821'`. Click the **Save** icon.
4. Click **Deploy → New deployment**. Click the gear icon next to "Select type" and choose **Web app**. Set:
   - **Execute as:** Me
   - **Who has access:** Anyone
5. Click **Deploy**, then **Authorize access** and choose the Gmail account. Google warns that the app isn't verified. That's normal for your own script: click **Advanced → Go to (project name) (unsafe) → Allow**.
6. Copy the **Web app URL**. It ends in `/exec`.
7. In GitHub, open the `site` folder → **Add file → Create new file**. Name it `config.js` and paste this one line, with your URL between the quotes:
   `window.TEAM_REPORTS_URL = "https://script.google.com/macros/s/.../exec";`
   Then click **Commit changes**.
8. In the `site` folder, click **Add file → Upload files** and upload the new `index.html`. It replaces the old one. Click **Commit changes**.
9. The panel appears on the dashboard after the next 5-minute check.

### Good to know
- **Change the PIN:** edit it in Apps Script, click **Save**, then **Deploy → Manage deployments → ✏️ → Version: New version → Deploy**. The URL stays the same.
- **Delete a report:** click **Delete** next to it on the dashboard, then **Confirm delete**. You can also edit or delete rows directly in the Google Sheet.
- **Team report emails:** each new report is emailed to the addresses in `EMAIL_TO` at the top of the Apps Script. After changing them, save and publish a new version (see "Change the PIN").
- **When submitted:** each report records when it was submitted.

---

## Password lock

The dashboard, the incident log and the monthly reports are encrypted with the password in the GitHub secret `DASHBOARD_PASSWORD`. Anyone opening the dashboard must enter it. Each browser can tick **Remember on this computer**, and the **Lock** button at the top right forgets it again.

- **Alarm-email map links still open without the password.** Each incident's own map stays reachable by its link, as before.
- **Use the same password as the team PIN** if you like. The Team reports panel then fills in the PIN automatically after unlocking.
- **Change the password:** first add the current one as a new secret `DASHBOARD_PASSWORD_OLD`, then update `DASHBOARD_PASSWORD`. After the next 5-minute check has run, you can delete `DASHBOARD_PASSWORD_OLD`.
- **If you lose the password:** set a new one. The old encrypted incident history can't be opened again, so keep the password somewhere safe.

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
- `site/`: dashboard (`index.html`), incident map (`map.html`), monthly report viewer (`report.html`), password lock (`lock.js`) and `config.js` (team reports link).
- `apps-script/Code.gs`: the Google Sheet script that stores team reports.
- `data/incidents.enc.json`: encrypted log of every confirmed incident (`incidents.json` if no password is set).
- `reports/`: saved monthly reports.
- `.github/workflows/`: the two schedules (every 5 minutes, and monthly).
