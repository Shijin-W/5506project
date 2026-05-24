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

const FRONTEND_CONFIG = window.FEEDER_CONFIG || {};
const BACKEND_BASE_URL =
  FRONTEND_CONFIG.BACKEND_BASE_URL ||
  "https://multicatfeeder-func-24417624.azurewebsites.net";
const FUNCTION_KEY = FRONTEND_CONFIG.FUNCTION_KEY || "";

function addFunctionKey(url) {
  if (FUNCTION_KEY) {
    url.searchParams.set("code", FUNCTION_KEY);
  }
}

// Fallback only. The primary online/offline signal comes from /api/device-config-status.
const DEVICE_ONLINE_THRESHOLD_MINUTES = 10;

async function fetchFrontendData(partition) {
  const url = new URL(BACKEND_BASE_URL + "/api/frontend-data");
  url.searchParams.set("partition", partition);
  addFunctionKey(url);
  url.searchParams.set("_", Date.now().toString());

  const response = await fetch(url.toString(), { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Backend API failed: " + response.status + " for " + partition);
  }

  return response.json();
}

async function fetchDeviceConfigStatus() {
  const url = new URL(BACKEND_BASE_URL + "/api/device-config-status");
  addFunctionKey(url);
  url.searchParams.set("_", Date.now().toString());

  const response = await fetch(url.toString(), { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Device config status failed: " + response.status);
  }

  return response.json();
}

async function fetchAnalyticsRange(startDate, endDate) {
  const url = new URL(BACKEND_BASE_URL + "/api/analytics/range");
  url.searchParams.set("startDate", startDate);
  url.searchParams.set("endDate", endDate);
  addFunctionKey(url);
  url.searchParams.set("_", Date.now().toString());

  const response = await fetch(url.toString(), { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Analytics range failed: " + response.status);
  }

  return response.json();
}

async function fetchAlertHistory(startDate, endDate) {
  const url = new URL(BACKEND_BASE_URL + "/api/alerts/history");
  url.searchParams.set("startDate", startDate);
  url.searchParams.set("endDate", endDate);
  addFunctionKey(url);
  url.searchParams.set("_", Date.now().toString());

  const response = await fetch(url.toString(), { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Alert history failed: " + response.status);
  }

  return response.json();
}

async function fetchAlertSubscriptions() {
  const url = new URL(BACKEND_BASE_URL + "/api/alert-subscriptions");
  addFunctionKey(url);
  url.searchParams.set("_", Date.now().toString());

  const response = await fetch(url.toString(), { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Alert subscriptions failed: " + response.status);
  }

  return response.json();
}

async function fetchAlertSubscriptionStatus(email) {
  const url = new URL(BACKEND_BASE_URL + "/api/alert-subscriptions");
  url.searchParams.set("email", email);
  addFunctionKey(url);
  url.searchParams.set("_", Date.now().toString());

  const response = await fetch(url.toString(), { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Alert subscription status failed: " + response.status);
  }

  return response.json();
}

async function toggleAlertEmailSubscription(email) {
  const url = new URL(BACKEND_BASE_URL + "/api/alert-subscriptions");
  addFunctionKey(url);

  const response = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      email: email,
      action: "toggle"
    })
  });

  let data = {};

  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.error || "Alert subscription update failed: " + response.status);
  }

  return data;
}

async function resolveBackendAlert(alertId, date) {
  const url = new URL(
    BACKEND_BASE_URL + "/api/alerts/" + encodeURIComponent(alertId) + "/resolve"
  );
  url.searchParams.set("date", date);
  addFunctionKey(url);

  const response = await fetch(url.toString(), {
    method: "POST"
  });

  let data = {};

  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.error || "Resolve alert failed: " + response.status);
  }

  return data;
}

async function startRfidRebindScan(backendCatId, timeoutSec) {
  const url = new URL(
    BACKEND_BASE_URL +
      "/api/cats/" +
      encodeURIComponent(backendCatId) +
      "/rfid/rebind-scan"
  );

  addFunctionKey(url);

  const response = await fetch(url.toString(), {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      timeoutSec: timeoutSec || 120
    })
  });

  let data = {};

  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }

  if (!response.ok) {
    throw new Error(
      data.error ||
        data.message ||
        "RFID rebind scan failed: " + response.status
    );
  }

  return data;
}

async function updateCatProfile(backendCatId, profile) {
  const url = new URL(
    BACKEND_BASE_URL +
      "/api/cats/" +
      encodeURIComponent(backendCatId) +
      "/profile"
  );

  addFunctionKey(url);

  const response = await fetch(url.toString(), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(profile)
  });

  let data = {};

  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.error || "Cat profile update failed: " + response.status);
  }

  return data;
}

async function loadBackendData(selectedDate) {
  try {
    const currentStatus = await fetchFrontendData("current-status");

    const dateToLoad =
      selectedDate ||
      getLatestFeedingDateFromCurrentStatus(currentStatus) ||
      getPerthToday();

    currentDataDate = dateToLoad;

    cats = transformCats(currentStatus);

    try {
      const deviceConfigStatus = await fetchDeviceConfigStatus();
      deviceStatus = transformDeviceStatus(currentStatus, deviceConfigStatus);
    } catch (deviceStatusError) {
      console.warn("Device config status unavailable:", deviceStatusError);
      deviceStatus = transformDeviceStatus(currentStatus);
    }

    try {
      const recentFeedings = await fetchFrontendData(
        "recent-feedings_" + dateToLoad
      );

      feedingRecords = transformFeedingRecords(recentFeedings, cats);
    } catch (feedingError) {
      console.warn("Recent feedings unavailable:", feedingError);
      feedingRecords = [];
    }

    try {
      const latestAlerts = await fetchFrontendData("alerts_latest");
      healthAlerts = transformAlerts(latestAlerts);
    } catch (alertError) {
      console.warn("Alerts unavailable:", alertError);
      healthAlerts = [];
    }

    updateDeviceSyncDisplay();

    return true;
  } catch (error) {
    console.error("Current status loading failed:", error);

    loadFallbackData();
    updateDeviceSyncDisplay();

    return false;
  }
}

function transformCats(rows) {
  if (!Array.isArray(rows)) {
    return [];
  }

  return rows.slice(0, 2).map(function (row, index) {
    return {
      id: index + 1,
      backendCatId: row.catId || row.RowKey || "cat_" + (index + 1),
      name: row.catName || "Cat " + (index + 1),
      rfidTag: row.currentCatUID || "Unknown",
      assignedBowl: index + 1,
      dailyTarget: Math.round(Number(row.targetDailyGrams || 60)),
      todayIntakeGrams: Number(row.todayIntakeGrams || 0),
      lastIntakeGrams: Number(row.lastIntakeGrams || 0),
      todayStatus: row.todayStatus || "unknown",
      lastFeedingCompletedTimeUtc: row.lastFeedingCompletedTimeUtc || ""
    };
  });
}

function transformFeedingRecords(rows, catsList) {
  if (!Array.isArray(rows)) {
    return [];
  }

  return rows.map(function (row, index) {
    const backendCatId = row.catId || row.cat_id || "";

    const matchedCat = catsList.find(function (cat) {
      return cat.backendCatId === backendCatId;
    });

    const catId = matchedCat ? matchedCat.id : index + 1;
    const catName = matchedCat ? matchedCat.name : row.catName || "Unknown Cat";

    const startTimeUtc =
      row.feedingStartTimeUtc ||
      row.startTimeUtc ||
      row.startTime ||
      row.timestampUtc ||
      row.lastFeedingCompletedTimeUtc ||
      "";

    const endTimeUtc =
      row.feedingEndTimeUtc ||
      row.endTimeUtc ||
      row.endTime ||
      row.completedTimeUtc ||
      row.lastFeedingCompletedTimeUtc ||
      "";

    return {
      id: row.RowKey || row.recordId || row.id || index + 1,
      catId: catId,
      backendCatId: backendCatId,
      catName: catName,
      rfidTag:
        row.currentCatUID ||
        row.rfidTag ||
        (matchedCat ? matchedCat.rfidTag : "Unknown"),
      startTime: formatPerthDateTime(startTimeUtc),
      endTime: formatPerthDateTime(endTimeUtc),
      startTimeUtc: startTimeUtc,
      endTimeUtc: endTimeUtc,
      localDate:
        row.localDate ||
        row.date ||
        formatPerthDate(endTimeUtc || startTimeUtc),
      durationSec: Number(row.durationSec || 0),
      intakeGrams: roundOneDecimal(
        Number(row.intakeGrams || row.lastIntakeGrams || 0)
      )
    };
  });
}

function transformAlerts(rows) {
  if (!Array.isArray(rows)) {
    return [];
  }

  return rows.map(function (row, index) {
    const backendCatId = row.catId || "";
    const matchedCat = cats.find(function (cat) {
      return cat.backendCatId === backendCatId;
    });

    const createdAtUtc = row.createdAtUtc || row.updatedAtUtc || row.timestampUtc || "";
    const updatedAtUtc = row.updatedAtUtc || "";
    const resolvedAtUtc = row.resolvedAtUtc || "";

    return {
      id: row.alertId || row.RowKey || index + 1,
      catId: backendCatId,
      catName: matchedCat ? matchedCat.name : row.catName || "Unknown Cat",
      level: mapAlertLevel(row.severity || row.alertType || ""),
      message: row.message || mapAlertMessage(row.alertType || ""),
      createdAt: formatPerthDateTime(createdAtUtc),
      createdAtUtc: createdAtUtc,
      updatedAtUtc: updatedAtUtc,
      resolvedAtUtc: resolvedAtUtc,
      alertDate: row.date || row.PartitionKey || formatPerthDate(createdAtUtc),
      status: mapAlertStatus(row.status || "open"),
      alertType: row.alertType || ""
    };
  });
}

function transformDeviceStatus(rows, backendStatus) {
  if (backendStatus && typeof backendStatus.online === "boolean") {
    const lastActivityTimeUtc =
      backendStatus.lastActivityTimeUtc ||
      backendStatus.lastSyncTime ||
      backendStatus.onlineCheckedAtUtc ||
      "";

    return {
      feederOnline: backendStatus.online,
      lastSyncTime: lastActivityTimeUtc
        ? formatPerthDateTime(lastActivityTimeUtc)
        : "No activity recorded",
      lastSyncTimeUtc: lastActivityTimeUtc,
      connectionState: backendStatus.connectionState || "Unknown",
      lastSyncLabel: "Last activity"
    };
  }

  if (!Array.isArray(rows) || rows.length === 0) {
    return {
      feederOnline: false,
      lastSyncTime: "Not synced",
      lastSyncTimeUtc: "",
      connectionState: "Unknown",
      lastSyncLabel: "Last sync"
    };
  }

  const latestUpdatedAt = rows
    .map(function (row) {
      return row.updatedAtUtc;
    })
    .filter(Boolean)
    .sort()
    .reverse()[0];

  const online = isRecentlySynced(
    latestUpdatedAt,
    DEVICE_ONLINE_THRESHOLD_MINUTES
  );

  return {
    feederOnline: online,
    lastSyncTime: latestUpdatedAt
      ? formatPerthDateTime(latestUpdatedAt)
      : "Synced",
    lastSyncTimeUtc: latestUpdatedAt || "",
    connectionState: online ? "Recently updated" : "Stale status",
    lastSyncLabel: "Last sync"
  };
}

function isRecentlySynced(utcTimeString, thresholdMinutes) {
  if (!utcTimeString) {
    return false;
  }

  const syncTime = new Date(utcTimeString);

  if (isNaN(syncTime.getTime())) {
    return false;
  }

  const now = new Date();
  const diffMs = now.getTime() - syncTime.getTime();
  const diffMinutes = diffMs / 1000 / 60;

  return diffMinutes >= 0 && diffMinutes <= thresholdMinutes;
}

function getLatestFeedingDateFromCurrentStatus(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return "";
  }

  const latestTime = rows
    .map(function (row) {
      return row.lastFeedingCompletedTimeUtc;
    })
    .filter(Boolean)
    .sort()
    .reverse()[0];

  if (!latestTime) {
    return "";
  }

  return formatPerthDate(latestTime);
}

function getPerthToday() {
  return formatPerthDateFromDate(new Date());
}

function getPerthDateFromUtc(utcTimeString) {
  if (!utcTimeString) {
    return "";
  }

  const date = new Date(utcTimeString);

  if (isNaN(date.getTime())) {
    return "";
  }

  return formatPerthDateFromDate(date);
}

function formatPerthDateFromDate(date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Australia/Perth",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).formatToParts(date);

  return (
    getDatePart(parts, "year") +
    "-" +
    getDatePart(parts, "month") +
    "-" +
    getDatePart(parts, "day")
  );
}

function formatPerthDate(isoString) {
  if (!isoString) {
    return "";
  }

  const date = new Date(isoString);

  if (isNaN(date.getTime())) {
    return "";
  }

  return formatPerthDateFromDate(date);
}

function formatPerthDateTime(isoString) {
  if (!isoString) {
    return "";
  }

  const date = new Date(isoString);

  if (isNaN(date.getTime())) {
    return isoString;
  }

  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Australia/Perth",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(date);

  return (
    getDatePart(parts, "year") +
    "-" +
    getDatePart(parts, "month") +
    "-" +
    getDatePart(parts, "day") +
    " " +
    getDatePart(parts, "hour") +
    ":" +
    getDatePart(parts, "minute")
  );
}

function getDatePart(parts, type) {
  const item = parts.find(function (part) {
    return part.type === type;
  });

  return item ? item.value : "";
}

function roundOneDecimal(value) {
  return Math.round(value * 10) / 10;
}

function mapAlertLevel(value) {
  const text = String(value).toLowerCase();

  if (
    text.includes("high") ||
    text.includes("critical") ||
    text.includes("very_low") ||
    text.includes("not_eaten")
  ) {
    return "High";
  }

  if (
    text.includes("medium") ||
    text.includes("warning") ||
    text.includes("unknown_rfid") ||
    text.includes("over_target")
  ) {
    return "Medium";
  }

  return "Low";
}

function mapAlertStatus(value) {
  const text = String(value).toLowerCase();

  if (text === "open" || text === "active" || text === "unresolved") {
    return "Unresolved";
  }

  return "Resolved";
}

function mapAlertMessage(alertType) {
  const type = String(alertType).toLowerCase();

  if (type === "not_eaten") {
    return "No completed feeding record was found for this cat.";
  }

  if (type === "very_low_intake" || type === "under_target") {
    return "Food intake is lower than the daily target.";
  }

  if (type === "over_target") {
    return "Food intake is above the daily target.";
  }

  if (type === "unknown_rfid") {
    return "Unknown RFID tag detected.";
  }

  if (type === "invalid_payload") {
    return "Invalid feeding data payload received.";
  }

  return "Health alert detected.";
}

function updateDeviceSyncDisplay() {
  const dotClass = deviceStatus.feederOnline ? "online" : "offline";
  const syncText = deviceStatus.lastSyncTime || "Not synced";
  const syncLabel = deviceStatus.lastSyncLabel || "Last sync";

  $(".device-sync-pill").html(`
    <span class="sync-dot ${dotClass}"></span>
    <span>${syncLabel}: ${syncText}</span>
    <span class="sync-divider"></span>
    <span>Device ID: FEEDER-01</span>
  `);

  $(".app-footer").each(function () {
    const extraText = $(this).text().includes("Supports up to 2 cats")
      ? " | Supports up to 2 cats"
      : "";

    $(this).text(
      "Smart Multi-Cat Feeder | Frontend Prototype | " +
        syncLabel +
        ": " +
        syncText +
        " | Device: FEEDER-01" +
        extraText
    );
  });
}

function loadFallbackData() {
  cats = [
    {
      id: 1,
      backendCatId: "cat_a",
      name: "CatA",
      rfidTag: "B9BD18C9",
      assignedBowl: 1,
      dailyTarget: 60,
      todayIntakeGrams: 51.7,
      lastIntakeGrams: 15.1,
      todayStatus: "under_target"
    },
    {
      id: 2,
      backendCatId: "cat_b",
      name: "CatB",
      rfidTag: "0420D6BAFD1691",
      assignedBowl: 2,
      dailyTarget: 60,
      todayIntakeGrams: 347.4,
      lastIntakeGrams: 9,
      todayStatus: "over_target"
    }
  ];

  feedingRecords = [
    {
      id: 101,
      catId: 1,
      backendCatId: "cat_a",
      catName: "CatA",
      rfidTag: "B9BD18C9",
      startTime: "2026-05-13 15:57",
      endTime: "2026-05-13 15:58",
      durationSec: 60,
      intakeGrams: 15.1
    },
    {
      id: 102,
      catId: 2,
      backendCatId: "cat_b",
      catName: "CatB",
      rfidTag: "0420D6BAFD1691",
      startTime: "2026-05-13 15:58",
      endTime: "2026-05-13 15:59",
      durationSec: 60,
      intakeGrams: 9
    }
  ];

  healthAlerts = [
    {
      id: 201,
      catId: "cat_b",
      catName: "CatB",
      level: "High",
      message: "Food intake is above the daily target.",
      createdAt: "2026-05-13 16:00",
      status: "Unresolved",
      alertType: "over_target"
    }
  ];

  deviceStatus = {
    feederOnline: false,
    lastSyncTime: "Backend unavailable",
    lastSyncTimeUtc: "",
    connectionState: "Unknown",
    lastSyncLabel: "Last sync"
  };
}
