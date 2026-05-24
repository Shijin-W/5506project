const DASHBOARD_POLL_INTERVAL_MS = 15000;
const DASHBOARD_LATEST_RECORD_DAYS = 30;
const DASHBOARD_RECENT_ALERT_DAYS = 7;
const DASHBOARD_RECENT_ALERT_LIMIT = 3;

let dashboardPollTimer = null;
let dashboardRefreshInProgress = false;
let dashboardLatestFeedingRecords = [];
let dashboardRecentAlerts = [];

$(document).ready(async function () {
  await refreshDashboardData({ preserveExistingOnFailure: false });
  startDashboardPolling();
});

async function refreshDashboardData(options) {
  const settings = options || {};

  if (dashboardRefreshInProgress) {
    return false;
  }

  if (settings.skipWhenHidden && document.hidden) {
    return false;
  }

  dashboardRefreshInProgress = true;

  try {
    const loaded = await loadDashboardTodayData({
      preserveExistingOnFailure: settings.preserveExistingOnFailure === true
    });

    renderDashboard();
    return loaded;
  } catch (error) {
    console.warn("Dashboard refresh failed:", error);
    return false;
  } finally {
    dashboardRefreshInProgress = false;
  }
}

function startDashboardPolling() {
  stopDashboardPolling();

  dashboardPollTimer = window.setInterval(function () {
    refreshDashboardData({
      preserveExistingOnFailure: true,
      skipWhenHidden: true
    });
  }, DASHBOARD_POLL_INTERVAL_MS);

  document.addEventListener("visibilitychange", handleDashboardVisibilityChange);
  window.addEventListener("beforeunload", stopDashboardPolling);
}

function stopDashboardPolling() {
  if (dashboardPollTimer) {
    window.clearInterval(dashboardPollTimer);
    dashboardPollTimer = null;
  }
}

function handleDashboardVisibilityChange() {
  if (!document.hidden) {
    refreshDashboardData({ preserveExistingOnFailure: true });
  }
}

async function loadDashboardTodayData(options) {
  const settings = options || {};
  const previousState = snapshotDashboardState();
  const today = await getDashboardToday();
  const backendLoaded = await loadBackendData(today);

  if (!backendLoaded && settings.preserveExistingOnFailure) {
    restoreDashboardState(previousState);
    return false;
  }

  applyDashboardRecordsForDate(today);
  applyDashboardCatTotalsFromRecords();

  try {
    const todayAnalytics = await fetchAnalyticsRange(today, today);
    const summariesByCat = {};

    (todayAnalytics.catSummaries || []).forEach(function (summary) {
      summariesByCat[summary.catId] = summary;
    });

    cats = cats.map(function (cat) {
      const summary = summariesByCat[cat.backendCatId];

      if (!summary) {
        return {
          ...cat,
          todayIntakeGrams: 0,
          lastIntakeGrams: 0
        };
      }

      return {
        ...cat,
        todayIntakeGrams: Number(summary.totalIntakeGrams || 0),
        dailyTarget: Math.round(Number(summary.targetDailyGrams || cat.dailyTarget || 60))
      };
    });

    feedingRecords = transformFeedingRecords(
      filterRawFeedingRowsForDate(todayAnalytics.feedingRecords || [], today),
      cats
    );
  } catch (error) {
    console.warn("Dashboard today analytics unavailable:", error);
  }

  await loadDashboardLatestFeedingRecords(today, settings.preserveExistingOnFailure === true);
  await loadDashboardRecentAlerts(today, settings.preserveExistingOnFailure === true);

  currentDataDate = today;
  return backendLoaded;
}

function snapshotDashboardState() {
  return {
    cats: cats.slice(),
    feedingRecords: feedingRecords.slice(),
    dashboardLatestFeedingRecords: dashboardLatestFeedingRecords.slice(),
    dashboardRecentAlerts: dashboardRecentAlerts.slice(),
    healthAlerts: healthAlerts.slice(),
    deviceStatus: { ...deviceStatus },
    currentDataDate: currentDataDate
  };
}

function restoreDashboardState(state) {
  cats = state.cats;
  feedingRecords = state.feedingRecords;
  dashboardLatestFeedingRecords = state.dashboardLatestFeedingRecords;
  dashboardRecentAlerts = state.dashboardRecentAlerts;
  healthAlerts = state.healthAlerts;
  deviceStatus = state.deviceStatus;
  currentDataDate = state.currentDataDate;
  updateDeviceSyncDisplay();
}

async function getDashboardToday() {
  try {
    const backendStatus = await fetchDeviceConfigStatus();
    return (
      getPerthDateFromUtc(backendStatus.onlineCheckedAtUtc) ||
      getPerthDateFromUtc(backendStatus.lastActivityTimeUtc) ||
      getPerthToday()
    );
  } catch (error) {
    console.warn("Backend clock unavailable; using browser clock:", error);
    return getPerthToday();
  }
}

function applyDashboardRecordsForDate(localDate) {
  feedingRecords = feedingRecords.filter(function (record) {
    return record.localDate === localDate;
  });
}

function applyDashboardCatTotalsFromRecords() {
  const totalsByCat = {};

  feedingRecords.forEach(function (record) {
    totalsByCat[record.backendCatId] =
      (totalsByCat[record.backendCatId] || 0) + Number(record.intakeGrams || 0);
  });

  cats = cats.map(function (cat) {
    return {
      ...cat,
      todayIntakeGrams: roundOneDecimal(totalsByCat[cat.backendCatId] || 0)
    };
  });
}

function filterRawFeedingRowsForDate(rows, localDate) {
  return rows.filter(function (row) {
    const rowDate =
      row.localDate ||
      row.date ||
      formatPerthDate(row.feedingEndTimeUtc || row.feedingStartTimeUtc || "");

    return rowDate === localDate;
  });
}

async function loadDashboardLatestFeedingRecords(today, preserveExistingOnFailure) {
  const startDate = addDaysToIsoDate(today, -(DASHBOARD_LATEST_RECORD_DAYS - 1));

  try {
    const recentAnalytics = await fetchAnalyticsRange(startDate, today);
    dashboardLatestFeedingRecords = transformFeedingRecords(
      recentAnalytics.feedingRecords || [],
      cats
    ).sort(compareFeedingRecordsByTime);
  } catch (error) {
    console.warn("Dashboard latest feeding records unavailable:", error);

    if (!preserveExistingOnFailure) {
      dashboardLatestFeedingRecords = feedingRecords.slice().sort(compareFeedingRecordsByTime);
    }
  }
}

async function loadDashboardRecentAlerts(today, preserveExistingOnFailure) {
  const startDate = addDaysToIsoDate(today, -(DASHBOARD_RECENT_ALERT_DAYS - 1));

  try {
    const history = await fetchAlertHistory(startDate, today);

    const unresolvedAlerts = transformAlerts(history.alerts || [])
      .filter(function (alert) {
        return alert.status === "Unresolved";
      })
      .sort(compareAlertsByTime);

    healthAlerts = unresolvedAlerts;
    dashboardRecentAlerts = unresolvedAlerts.slice(0, DASHBOARD_RECENT_ALERT_LIMIT);
  } catch (error) {
    console.warn("Dashboard recent alerts unavailable:", error);

    if (!preserveExistingOnFailure) {
      const fallbackAlerts = healthAlerts
        .filter(function (alert) {
          return alert.status === "Unresolved";
        })
        .sort(compareAlertsByTime);

      healthAlerts = fallbackAlerts;
      dashboardRecentAlerts = fallbackAlerts.slice(0, DASHBOARD_RECENT_ALERT_LIMIT);
    }
  }
}

function compareAlertsByTime(left, right) {
  return getAlertTimestamp(right) - getAlertTimestamp(left);
}

function getAlertTimestamp(alert) {
  const date = new Date(
    alert.createdAtUtc ||
      alert.updatedAtUtc ||
      alert.resolvedAtUtc ||
      alert.createdAt ||
      alert.alertDate ||
      ""
  );

  if (isNaN(date.getTime())) {
    return 0;
  }

  return date.getTime();
}

function compareFeedingRecordsByTime(left, right) {
  return getFeedingRecordTimestamp(left) - getFeedingRecordTimestamp(right);
}

function getFeedingRecordTimestamp(record) {
  const date = new Date(record.endTimeUtc || record.startTimeUtc || record.endTime || record.startTime || "");

  if (isNaN(date.getTime())) {
    return 0;
  }

  return date.getTime();
}

function addDaysToIsoDate(isoDate, dayOffset) {
  const parts = isoDate.split("-").map(function (part) {
    return Number(part);
  });

  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  date.setUTCDate(date.getUTCDate() + dayOffset);

  return date.toISOString().slice(0, 10);
}

function renderDashboard() {
  renderSummaryCards();
  renderCatIntakeTable();
  renderLatestRecordsTable();
  renderRecentAlerts();
}

function renderSummaryCards() {
  const todayFeedings = feedingRecords.length;

  const totalIntake = cats.reduce(function (sum, cat) {
    return sum + Number(cat.todayIntakeGrams || 0);
  }, 0);

  const activeAlerts = healthAlerts.filter(function (alert) {
    return alert.status === "Unresolved";
  }).length;

  $("#todayFeedings").text(todayFeedings);
  $("#totalIntake").text(roundOneDecimal(totalIntake) + "g");
  $("#activeAlerts").text(activeAlerts);

  if (deviceStatus.feederOnline) {
    $("#deviceStatus")
      .text("Online")
      .removeClass("text-danger")
      .addClass("text-success");
  } else {
    $("#deviceStatus")
      .text("Offline")
      .removeClass("text-success")
      .addClass("text-danger");
  }
}

function renderCatIntakeTable() {
  const tableBody = $("#catIntakeTable");
  tableBody.empty();

  if (cats.length === 0) {
    tableBody.html(`
      <tr>
        <td colspan="4" class="text-center text-muted">
          No cat status data found.
        </td>
      </tr>
    `);
    return;
  }

  cats.forEach(function (cat) {
    const totalIntake = Number(cat.todayIntakeGrams || 0);

    const progressPercentage = calculateProgressPercentage(
      totalIntake,
      cat.dailyTarget
    );

    const row = `
      <tr>
        <td>
          <strong>🐱 ${cat.name}</strong>
          <div>
            <span class="badge badge-cat">Cat ${cat.id}</span>
          </div>
        </td>

        <td>${cat.rfidTag}</td>

        <td>
          <strong class="text-success">${roundOneDecimal(totalIntake)}g</strong>
        </td>

        <td>
          <div class="intake-progress-wrapper">
            <div class="intake-progress-label">
              <span>${roundOneDecimal(totalIntake)}g / ${cat.dailyTarget}g</span>
              <span class="intake-progress-value">${progressPercentage}%</span>
            </div>

            <div class="intake-progress">
              <div
                class="intake-progress-fill"
                style="width: ${progressPercentage}%"
              ></div>
            </div>
          </div>
        </td>
      </tr>
    `;

    tableBody.append(row);
  });
}

function renderLatestRecordsTable() {
  const tableBody = $("#latestRecordsTable");
  tableBody.empty();

  const latestRecords = dashboardLatestFeedingRecords.slice(-5).reverse();

  if (latestRecords.length === 0) {
    tableBody.html(`
      <tr>
        <td colspan="3" class="text-center text-muted">
          No completed feeding records found.
        </td>
      </tr>
    `);
    return;
  }

  latestRecords.forEach(function (record) {
    const row = `
      <tr>
        <td>
          <strong>🐱 ${record.catName}</strong>
        </td>
        <td>${record.startTime || "-"}</td>
        <td><strong>${record.intakeGrams}g</strong></td>
      </tr>
    `;

    tableBody.append(row);
  });
}

function renderRecentAlerts() {
  const alertContainer = $("#recentAlerts");
  alertContainer.empty();

  if (dashboardRecentAlerts.length === 0) {
    alertContainer.html(`<p class="text-muted mb-0">No health alerts.</p>`);
    return;
  }

  dashboardRecentAlerts.forEach(function (alert) {
    const badgeClass = getAlertBadgeClass(alert.level);
    const statusClass = getStatusBadgeClass(alert.status);
    const calloutClass = getAlertCalloutClass(alert.level);
    const titleClass = getAlertTitleClass(alert.level);

    const alertItem = `
      <div class="alert-callout ${calloutClass}">
        <div class="row align-items-center g-3">
          <div class="col-md-2">
            <strong>🐱 ${alert.catName}</strong>
            <div class="mt-1">
              <span class="badge ${badgeClass}">${alert.level}</span>
            </div>
          </div>

          <div class="col-md-6">
            <div class="${titleClass}">${getAlertTitle(alert)}</div>
            <div>${alert.message}</div>
          </div>

          <div class="col-md-3 text-muted">
            Detected: ${alert.createdAt || "-"}
          </div>

          <div class="col-md-1 text-end">
            <span class="badge ${statusClass}">${alert.status}</span>
          </div>
        </div>
      </div>
    `;

    alertContainer.append(alertItem);
  });
}

function calculateProgressPercentage(currentValue, targetValue) {
  if (!targetValue || targetValue <= 0) {
    return 0;
  }

  const percentage = Math.round((currentValue / targetValue) * 100);

  return Math.min(percentage, 100);
}

function getAlertTitle(alert) {
  if (alert.alertType === "over_target") {
    return "Over daily target";
  }

  if (alert.alertType === "very_low_intake") {
    return "Very low intake";
  }

  if (alert.alertType === "unknown_rfid") {
    return "Unknown RFID detected";
  }

  if (alert.level === "High") {
    return "High priority alert";
  }

  if (alert.level === "Medium") {
    return "Feeding pattern warning";
  }

  return "Health notice";
}

function getAlertBadgeClass(level) {
  if (level === "High") {
    return "badge-alert-high";
  }

  if (level === "Medium") {
    return "badge-alert-medium";
  }

  return "badge-alert-low";
}

function getAlertCalloutClass(level) {
  if (level === "High") {
    return "alert-callout-high";
  }

  if (level === "Medium") {
    return "alert-callout-medium";
  }

  return "alert-callout-low";
}

function getAlertTitleClass(level) {
  if (level === "High") {
    return "alert-title-high";
  }

  if (level === "Medium") {
    return "alert-title-medium";
  }

  return "alert-title-low";
}

function getStatusBadgeClass(status) {
  if (status === "Resolved") {
    return "status-resolved";
  }

  return "status-unresolved";
}
