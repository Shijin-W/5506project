# Smart Multi-Cat Feeder Frontend

The frontend is a static web app built with HTML, CSS, JavaScript, Bootstrap, jQuery, and Chart.js.

## Pages

| Page | Purpose |
|---|---|
| `index.html` | Dashboard overview |
| `records.html` | Feeding record history |
| `analytics.html` | Intake analytics and charts |
| `alerts.html` | Alert history, resolution, and email subscription |
| `cats.html` | Cat profile editing and RFID rebind workflow |

## Local Run

From the `frontend` folder:

```powershell
python -m http.server 8088 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:8088/index.html
```

`OPEN_FRONTEND.bat` does the same startup step automatically on Windows.

## Backend Configuration

The frontend reads backend settings from `window.FEEDER_CONFIG` when present:

```javascript
window.FEEDER_CONFIG = {
  BACKEND_BASE_URL: "https://<function-app-name>.azurewebsites.net",
  FUNCTION_KEY: "<function key for protected APIs>"
};
```

Do not commit real Function keys. For local testing, create an untracked file named:

```text
frontend/static/js/config.local.js
```

and load it before `static/js/api.js` if you need live backend access.

If no Function key is provided, the UI still renders with fallback data when protected API calls fail.

## Deployment

The app can be deployed as static files, for example to Azure Storage Static Website. Upload only the HTML files plus `static/css` and `static/js`.
