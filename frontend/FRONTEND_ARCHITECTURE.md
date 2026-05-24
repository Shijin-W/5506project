# Multicat Feeder Frontend Architecture

本文档整理当前 `multicatfeeder` 项目的前端架构、页面结构、共享数据层、后端 API 调用、各页面数据流、实时刷新策略、部署方式和已知实现细节。

## 1. Overall Architecture

前端是一个纯静态 Web 应用，没有构建系统，也没有前端框架编译流程。

技术栈：

- HTML
- CSS
- Vanilla JavaScript
- jQuery
- Bootstrap 5
- Bootstrap Icons
- Chart.js
- Google Font: Inter

前端直接部署为静态文件，可以通过：

- 本地 `python -m http.server`
- Azure Storage Static Website

运行。

当前静态站点部署地址：

```txt
https://multicatproject.z8.web.core.windows.net/
```

本地启动方式：

```txt
5506-iot-smart-cat-feeder-frontend/OPEN_FRONTEND.bat
```

该 bat 会：

1. 切换到前端目录。
2. 杀掉已有的 `127.0.0.1:8088` 监听进程。
3. 启动 `python -m http.server 8088 --bind 127.0.0.1`。
4. 打开 `http://127.0.0.1:8088/index.html?v=20260518-local-refresh`。

## 2. Frontend File Structure

```txt
5506-iot-smart-cat-feeder-frontend/
  index.html
  records.html
  analytics.html
  alerts.html
  cats.html
  OPEN_FRONTEND.bat
  static/
    css/
      style.css
    js/
      api.js
      dashboard.js
      records.js
      analytics.js
      alerts.js
      cats.js
      mockData.js
```

Page mapping:

| Page | JS | Purpose |
|---|---|---|
| `index.html` | `dashboard.js` | Dashboard overview |
| `records.html` | `records.js` | Feeding record history |
| `analytics.html` | `analytics.js` | Intake analytics and charts |
| `alerts.html` | `alerts.js` | Alert details, history, email subscription |
| `cats.html` | `cats.js` | Cat profile management and RFID rebind |

Shared files:

| File | Purpose |
|---|---|
| `static/js/api.js` | Shared global state, backend API wrappers, data transformers, formatting helpers |
| `static/css/style.css` | Shared visual styles |
| `static/js/mockData.js` | Legacy/mock data support |

## 3. Page Loading Model

Each HTML page loads:

1. Google Fonts
2. Bootstrap CSS
3. Bootstrap Icons
4. `static/css/style.css`
5. jQuery
6. Bootstrap JS
7. `static/js/api.js`
8. Page-specific JS

Example from Dashboard:

```html
<script src="static/js/api.js?v=20260518-dashboard-recent-alerts"></script>
<script src="static/js/dashboard.js?v=20260518-dashboard-recent-alerts"></script>
```

The query string version is used for cache busting.

There is no module loader. All JavaScript files share global variables and functions.

## 4. Shared Global State

`api.js` defines shared global state:

```js
var cats = [];
var feedingRecords = [];
var healthAlerts = [];

var deviceStatus = {
  feederOnline: false,
  lastSyncTime: "Not synced",
  lastSyncTimeUtc: "",
  connectionState: "Unknown",
  lastSyncLabel: "Last sync"
};

var currentDataDate = "";
```

These arrays are overwritten or reused by page-specific scripts.

Important implications:

- Each page has its own browser page lifecycle.
- State is not persisted between pages.
- Each page reloads data on `$(document).ready`.
- Page scripts depend on `api.js` being loaded first.

## 5. Backend Configuration

Backend base URL is defined in `api.js`:

```js
const BACKEND_BASE_URL = "https://multicatfeeder-func-24417624.azurewebsites.net";
```

Function key is also stored in `api.js`:

```js
const FUNCTION_KEY = "...";
```

Every protected Azure Function request includes:

```txt
code={FUNCTION_KEY}
```

All API calls also include:

```txt
_={Date.now()}
```

This is used to avoid browser/proxy caching.

Fetch calls use:

```js
{ cache: "no-store" }
```

## 6. Shared API Wrapper Functions

Defined in `api.js`.

### 6.1 FrontendData Cache

```js
fetchFrontendData(partition)
```

Calls:

```txt
GET /api/frontend-data?partition={partition}
```

Used partitions:

```txt
current-status
daily-summary_YYYY-MM-DD
recent-feedings_YYYY-MM-DD
alerts_latest
```

### 6.2 Device Status

```js
fetchDeviceConfigStatus()
```

Calls:

```txt
GET /api/device-config-status
```

Used to display:

- online/offline
- last activity
- Device Twin sync status

### 6.3 Analytics Range

```js
fetchAnalyticsRange(startDate, endDate)
```

Calls:

```txt
GET /api/analytics/range?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
```

Used by:

- Dashboard today stats
- Dashboard latest feeding records
- Feeding Records page
- Analytics page

### 6.4 Alert History

```js
fetchAlertHistory(startDate, endDate)
```

Calls:

```txt
GET /api/alerts/history?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
```

Used by:

- Dashboard Recent Health Alerts
- Health Alerts page

### 6.5 Alert Subscription

```js
fetchAlertSubscriptions()
fetchAlertSubscriptionStatus(email)
toggleAlertEmailSubscription(email)
```

Calls:

```txt
GET /api/alert-subscriptions
GET /api/alert-subscriptions?email={email}
POST /api/alert-subscriptions
```

Used by:

- Health Alerts page email notification card

### 6.6 Resolve Alert

```js
resolveBackendAlert(alertId, date)
```

Calls:

```txt
POST /api/alerts/{alertId}/resolve?date=YYYY-MM-DD
```

Used by:

- Alert Details `Mark as Resolved` button

### 6.7 RFID Rebind

```js
startRfidRebindScan(backendCatId, timeoutSec)
```

Calls:

```txt
POST /api/cats/{catId}/rfid/rebind-scan
```

Used by:

- Cat Management `Rebind RFID`

### 6.8 Cat Profile Update

```js
updateCatProfile(backendCatId, profile)
```

Calls:

```txt
PATCH /api/cats/{catId}/profile
```

Used by:

- Cat Management edit form

## 7. Shared Data Loading

Main shared loader:

```js
loadBackendData(selectedDate)
```

Flow:

1. Load `current-status` from `/api/frontend-data`.
2. Determine `dateToLoad`:
   - `selectedDate`, if provided
   - latest feeding date from current status
   - Perth today fallback
3. Transform current status into `cats`.
4. Load device config status from `/api/device-config-status`.
5. Transform device status into `deviceStatus`.
6. Load `recent-feedings_{dateToLoad}`.
7. Transform into `feedingRecords`.
8. Load `alerts_latest`.
9. Transform into `healthAlerts`.
10. Update the device sync pill and footer.

If loading fails:

1. Logs error.
2. Calls `loadFallbackData()`.
3. Updates sync pill/footer with fallback status.
4. Returns `false`.

Important note:

`loadBackendData` still loads `alerts_latest` as a general fallback. Dashboard and Alerts page override alert data with `/api/alerts/history` where accurate history is required.

## 8. Data Transformers

### 8.1 Cats

```js
transformCats(rows)
```

Converts backend current status rows into frontend cat objects:

```txt
id
backendCatId
name
rfidTag
assignedBowl
dailyTarget
todayIntakeGrams
lastIntakeGrams
todayStatus
lastFeedingCompletedTimeUtc
```

The frontend currently displays up to 2 cats:

```js
rows.slice(0, 2)
```

### 8.2 Feeding Records

```js
transformFeedingRecords(rows, catsList)
```

Converts backend records into frontend records:

```txt
id
catId
backendCatId
catName
rfidTag
startTime
endTime
startTimeUtc
endTimeUtc
localDate
durationSec
intakeGrams
```

Cat name handling:

- If a record's `catId` matches a current cat profile, current cat name is used.
- Otherwise historical `row.catName` is used.

This ensures Cat Management name changes appear across other pages.

### 8.3 Alerts

```js
transformAlerts(rows)
```

Converts backend alerts into frontend alert objects:

```txt
id
catId
catName
level
message
createdAt
createdAtUtc
updatedAtUtc
resolvedAtUtc
alertDate
status
alertType
```

Status mapping:

```txt
open / active / unresolved -> Unresolved
otherwise                  -> Resolved
```

Level mapping:

```txt
high / critical / very_low / not_eaten -> High
medium / warning / unknown_rfid / over_target -> Medium
otherwise -> Low
```

Cat name handling:

- If alert `catId` matches a current cat profile, current cat name is used.
- Otherwise backend alert `catName` is used.

### 8.4 Device Status

```js
transformDeviceStatus(rows, backendStatus)
```

Primary path:

- Uses `/api/device-config-status`.
- `backendStatus.online` drives online/offline.
- `lastActivityTimeUtc`, `lastSyncTime`, or `onlineCheckedAtUtc` drives displayed time.

Fallback path:

- Uses `current-status.updatedAtUtc`.
- Considers the device online if the latest update is within `DEVICE_ONLINE_THRESHOLD_MINUTES`, currently 10 minutes.

## 9. Time and Formatting

Timezone:

```txt
Australia/Perth
```

Helpers:

```js
getPerthToday()
getPerthDateFromUtc(utcTimeString)
formatPerthDateFromDate(date)
formatPerthDate(isoString)
formatPerthDateTime(isoString)
roundOneDecimal(value)
```

Dates are formatted as:

```txt
YYYY-MM-DD
YYYY-MM-DD HH:mm
```

Dashboard uses backend/device clock where possible to avoid browser-local date mismatch.

## 10. Device Sync Display

```js
updateDeviceSyncDisplay()
```

Updates all:

```txt
.device-sync-pill
.app-footer
```

Displayed content:

```txt
Last activity: YYYY-MM-DD HH:mm | Device ID: FEEDER-01
```

or fallback:

```txt
Last sync: ...
```

The sync dot uses:

```txt
online
offline
```

classes.

## 11. Dashboard Page

Files:

- `index.html`
- `static/js/dashboard.js`

Dashboard sections:

- Today's Feedings
- Total Intake Today
- Active Alerts
- Device Status
- Today's Intake by Cat
- Latest Feeding Records
- Recent Health Alerts

### 11.1 Polling

Dashboard polls backend every 15 seconds:

```js
const DASHBOARD_POLL_INTERVAL_MS = 15000;
```

Flow:

```js
$(document).ready(async function () {
  await refreshDashboardData({ preserveExistingOnFailure: false });
  startDashboardPolling();
});
```

Polling safeguards:

- Prevents overlapping refreshes with `dashboardRefreshInProgress`.
- Skips refresh while tab is hidden when `skipWhenHidden` is true.
- Refreshes immediately when tab becomes visible again.
- Stops timer on `beforeunload`.
- Can preserve previous state if refresh fails.

### 11.2 Dashboard Today Calculation

```js
getDashboardToday()
```

Attempts to derive today from backend/device data:

1. `backendStatus.onlineCheckedAtUtc`
2. `backendStatus.lastActivityTimeUtc`
3. browser Perth date fallback

This prevents selected data from being tied to stale browser or local assumptions.

### 11.3 Dashboard Data Flow

```js
loadDashboardTodayData(options)
```

Flow:

1. Snapshot current dashboard state.
2. Determine backend/device today.
3. Load current backend data for today.
4. Filter feeding records to today.
5. Calculate cat totals from records.
6. Fetch `/api/analytics/range` for today.
7. Override cat daily totals with backend analytics summary.
8. Set today's `feedingRecords`.
9. Load latest feeding records from recent 30 days.
10. Load recent unresolved alerts from recent 7 days.
11. Set `currentDataDate`.

### 11.4 Latest Feeding Records

Constants:

```js
const DASHBOARD_LATEST_RECORD_DAYS = 30;
```

Logic:

- Fetch analytics range from `today - 29 days` to `today`.
- Transform all returned feeding records.
- Sort by feeding time.
- Render latest 5 records.

This list is not limited to today and is not affected by any selected date on other pages.

### 11.5 Recent Health Alerts

Constants:

```js
const DASHBOARD_RECENT_ALERT_DAYS = 7;
const DASHBOARD_RECENT_ALERT_LIMIT = 3;
```

Logic:

- Fetch `/api/alerts/history` from `today - 6 days` to `today`.
- Transform alerts.
- Keep only `Unresolved`.
- Sort by raw UTC timestamp.
- `healthAlerts` stores all unresolved alerts in the recent window for the summary card.
- `dashboardRecentAlerts` stores only the latest 3 for the Recent Health Alerts panel.

This avoids stale `alerts_latest` data.

### 11.6 Dashboard Rendering

Render functions:

```js
renderDashboard()
renderSummaryCards()
renderCatIntakeTable()
renderLatestRecordsTable()
renderRecentAlerts()
```

Summary card logic:

- Today's Feedings = `feedingRecords.length`
- Total Intake Today = sum of `cats.todayIntakeGrams`
- Active Alerts = unresolved alert count from recent alert window
- Device Status = `deviceStatus.feederOnline`

## 12. Feeding Records Page

Files:

- `records.html`
- `static/js/records.js`

Sections:

- Total Records
- Total Intake
- Average Intake
- Filters
- Feeding History

### 12.1 Data Loading

Constant:

```js
const RECORD_HISTORY_START_DATE = "2026-01-01";
```

Flow:

1. `loadBackendData()`
2. `loadAllFeedingRecords()`
3. `initialiseRecordsPage()`

`loadAllFeedingRecords()` calls:

```txt
GET /api/analytics/range?startDate=2026-01-01&endDate={PerthToday}
```

This loads the full feeding history window into `feedingRecords`.

### 12.2 Filters

Filter controls:

- Cat select
- Start Date
- End Date
- Reset Filters

Default state:

- Cat: `All Cats`
- Start Date: empty
- End Date: empty

Empty date fields mean all time within loaded history.

Filter logic:

```js
getFilteredRecords()
```

Applies:

- cat filter, if selected cat is not `all`
- start date, if not empty
- end date, if not empty

### 12.3 Summary Cards

Important behavior:

Summary cards use all loaded `feedingRecords`, not filtered records.

```js
updateSummaryCards(feedingRecords)
```

This means:

- Total Records = all loaded records
- Total Intake = all loaded intake
- Average Intake = all loaded average

The filter only affects the table.

## 13. Analytics Page

Files:

- `analytics.html`
- `static/js/analytics.js`

Sections:

- Highest Intake Cat
- Lowest Intake Cat
- Average Intake
- Range controls
- Per-cat summary cards
- Per-cat trend charts

Uses Chart.js.

### 13.1 Range Controls

Default preset:

```txt
today
```

Presets:

- today
- week
- month
- custom

For non-custom presets, start/end date inputs are auto-filled and disabled.

For custom preset, start/end date inputs are enabled.

### 13.2 Data Loading

```js
loadAnalyticsRangeFromControls()
```

Flow:

1. Read start and end date.
2. Validate `startDate <= endDate`.
3. Show loading state.
4. Fetch `/api/analytics/range`.
5. On failure, build fallback analytics from currently loaded data.
6. Render summary and charts.

### 13.3 Single-Day Chart

If `startDate === endDate`:

- One scatter chart per cat.
- X-axis is full 0-24h day.
- Each feeding is one point.
- X value is minutes since midnight Perth time.
- Y value is intake grams.

### 13.4 Multi-Day Chart

If `startDate !== endDate`:

- One line/area chart per cat.
- X-axis is date.
- Y-axis is daily intake grams.
- Uses `dailySeries` from analytics API.

### 13.5 Chart Lifecycle

Before rendering new cat charts:

- Existing charts whose keys start with `catTrend_` are destroyed.
- This prevents duplicate Chart.js instances and canvas reuse errors.

## 14. Health Alerts Page

Files:

- `alerts.html`
- `static/js/alerts.js`

Sections:

- Total Alerts
- Unresolved
- High Level
- Resolved
- Email Notifications
- Filters
- Alert Details
- Alert History

### 14.1 Alert History Loading

Constant:

```js
const ALERT_HISTORY_DAYS = 30;
```

Flow:

1. `loadBackendData()`
2. `loadAlertHistoryData()`
3. `renderAlertsPage()`
4. `renderAlertSubscriptionStatus()`

`loadAlertHistoryData()`:

- Computes `endDate = getPerthToday()`
- Computes `startDate = endDate - 29 days`
- Calls `/api/alerts/history`
- Transforms result into `healthAlerts`

If history loading fails:

- Uses whatever latest alert snapshot was loaded by `loadBackendData()`.

### 14.2 Alert Details vs Alert History

Current alert details:

```js
getCurrentAlerts()
```

Contains:

- only `Unresolved` alerts
- filtered by level if selected

Alert history:

```js
getFilteredHistoryAlerts()
```

Contains:

- all loaded alerts
- optionally filtered by status
- optionally filtered by level

Therefore:

- Alert Details shows current unresolved alerts.
- Alert History includes both current and resolved historical alerts.

### 14.3 Alert Filters

Controls:

- Status:
  - all
  - Unresolved
  - Resolved
- Level:
  - all
  - High
  - Medium
  - Low

Reset restores both filters to `all`.

### 14.4 Resolve Alert

Each unresolved alert gets:

```txt
Mark as Resolved
```

Click flow:

1. Find alert in `healthAlerts`.
2. Disable button and show resolving state.
3. Call `resolveBackendAlert(alert.id, alert.alertDate)`.
4. Update local alert status to `Resolved`.
5. Re-render page.

### 14.5 Email Subscription

Email form supports:

- subscribe
- unsubscribe
- status check

Behavior:

- On page load, calls `fetchAlertSubscriptions()`.
- On email input, debounced 400ms status check.
- Submit calls `toggleAlertEmailSubscription(email)`.
- Button text changes between Subscribe and Unsubscribe.
- Threshold is fixed in UI as `Medium and High`.

## 15. Cat Management Page

Files:

- `cats.html`
- `static/js/cats.js`

Sections:

- Total Cats
- RFID Tags
- Assigned Bowls
- Average Target
- Cat list/table
- Add/Edit form
- RFID status

### 15.1 Initial Loading

Flow:

1. `loadBackendData()`
2. `renderCatsPage()`
3. `resetCatForm()`

### 15.2 Rendering

Render functions:

```js
renderCatsPage()
renderCatSummary()
renderCatsTable()
updateCapacityState()
```

The prototype supports max 2 cats.

### 15.3 Add Cat

Adding a cat is local-only.

New local cats get:

```txt
backendCatId = local_cat_{id}
todayStatus = local
```

Validation:

- name required
- RFID required
- assigned bowl required
- daily target required
- max 2 cats
- bowl cannot be reused
- RFID cannot be reused

Local-added cats are not persisted to backend.

### 15.4 Edit Cat

If editing a backend cat:

```js
cat.backendCatId && !cat.backendCatId.startsWith("local_cat_")
```

Flow:

1. Validate form.
2. Call `updateCatProfile(cat.backendCatId, { catName, targetDailyGrams })`.
3. Reload backend data.
4. Re-render.

Backend profile changes then appear across:

- Dashboard
- Feeding Records
- Analytics
- Health Alerts
- Cat Management

because transformers prefer current cat profile names when matching `catId`.

If editing a local-only cat:

- Only updates the local `cats` array.

### 15.5 Delete Cat

Delete is local-only.

It removes the cat from the frontend `cats` array after confirmation.

It does not delete backend cat profiles.

### 15.6 RFID Rebind

For backend cats only.

Flow:

1. User clicks `Rebind RFID`.
2. Confirm prompt appears.
3. Frontend creates `activeRfidRebind`.
4. Calls `startRfidRebindScan(backendCatId, 120)`.
5. Backend sends C2D command to ESP32.
6. Frontend polls every 3 seconds.
7. Each poll calls `loadBackendData()`.
8. If cat RFID changes from old UID to new UID, scan is considered successful.
9. If timeout expires, active scan is cleared.

Polling interval:

```js
setInterval(..., 3000)
```

During active rebind:

- edit/delete/rebind buttons are disabled
- save/generate RFID controls are disabled

### 15.7 Local RFID Simulation

```js
simulateRfidScan()
```

Generates a random 8-character RFID tag and fills the form input.

This is local UI simulation only and does not communicate with backend.

## 16. Navigation and Shared Layout

Each HTML page has the same navbar:

- Dashboard
- Feeding Records
- Analytics
- Health Alerts
- Cat Management

Each page has:

- `page-heading-row`
- title and subtitle
- `device-sync-pill`
- footer with sync status

The active nav item is hard-coded per page.

## 17. Styling Architecture

All project-specific styles are in:

```txt
static/css/style.css
```

The frontend uses Bootstrap layout primitives:

- navbar
- container
- row/col grid
- cards
- tables
- forms
- buttons
- badges

Custom CSS handles:

- page title
- summary cards
- summary icons
- device sync pill
- sync dot
- alert callouts
- alert badges
- status badges
- intake progress bars
- analytics cat cards
- chart layout

## 18. Cache Busting

The project uses query string versions in script URLs:

```txt
?v=20260518-dashboard-recent-alerts
?v=20260518-records-range
?v=20260518-alert-current-history
?v=20260518-cat-profile-sync
```

The local `.bat` also opens:

```txt
index.html?v=20260518-local-refresh
```

Backend API calls include:

```txt
_={Date.now()}
```

Azure Storage uploads have been deployed with:

```txt
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
```

## 19. Fallback Behavior

If backend loading fails:

```js
loadFallbackData()
```

sets:

- two sample cats
- sample feeding records
- sample health alert
- offline device status

This keeps the UI renderable even when backend is unavailable.

Pages may also have page-specific fallbacks:

- Analytics builds fallback analytics from currently loaded `cats` and `feedingRecords`.
- Alerts page falls back to the latest alert snapshot if history endpoint fails.
- Dashboard can preserve previous state during polling failures.

## 20. Deployment

Frontend files are static assets.

Azure Static Website storage account:

```txt
multicatproject
```

Static website URL:

```txt
https://multicatproject.z8.web.core.windows.net/
```

Typical upload command pattern:

```powershell
$account='multicatproject'
$root=Resolve-Path '5506-iot-smart-cat-feeder-frontend'
$files=@(
  'alerts.html',
  'analytics.html',
  'cats.html',
  'index.html',
  'records.html',
  'static/css/style.css',
  'static/js/alerts.js',
  'static/js/analytics.js',
  'static/js/api.js',
  'static/js/cats.js',
  'static/js/dashboard.js',
  'static/js/mockData.js',
  'static/js/records.js'
)

foreach ($file in $files) {
  az storage blob upload `
    --account-name $account `
    --auth-mode key `
    --container-name '$web' `
    --file (Join-Path $root $file) `
    --name $file `
    --overwrite true `
    --content-cache-control 'no-store, no-cache, must-revalidate, max-age=0' `
    --output none
}
```

Avoid broad `upload-batch` unless the source directory is clean, because it may upload unintended files.

## 21. Current Design Decisions

- Static frontend is simple to deploy and easy to run locally.
- Shared `api.js` avoids duplicated API wrappers.
- Global variables are acceptable for this small multi-page prototype.
- Backend is the source of truth for cat profiles, RFID, feeding data and alerts.
- Frontend-added cats are local-only.
- Dashboard uses polling rather than WebSocket/SSE.
- Dashboard recent alerts use alert history, not `alerts_latest`.
- Feeding Records summary cards intentionally ignore filters.
- Feeding Records table filters are client-side over loaded history.
- Cat name updates are propagated by backend profile update and frontend transform matching.

## 22. Known Limitations

- Function key is stored in frontend JavaScript, which is acceptable for this prototype but not ideal for production.
- No frontend router; each page is a separate HTML file.
- No bundler or module system; scripts rely on global scope and load order.
- No persistent client-side store.
- Local-added cats are not saved to backend.
- Delete cat is local-only.
- Feeding Records loads history from `2026-01-01`; older records would require changing `RECORD_HISTORY_START_DATE`.
- Dashboard polling is HTTP polling, not true push.
- Alert History currently loads the most recent 30 days.
- Dashboard Recent Alerts currently displays latest 3 unresolved alerts from the latest 7-day window.

