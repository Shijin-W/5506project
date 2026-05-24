const ALERT_HISTORY_DAYS = 30;

$(document).ready(async function () {
  await loadBackendData();
  await loadAlertHistoryData();

  renderAlertsPage();
  await renderAlertSubscriptionStatus();

  $("#alertStatusFilter").on("change", function () {
    renderAlertsPage();
  });

  $("#alertLevelFilter").on("change", function () {
    renderAlertsPage();
  });

  $("#resetAlertFiltersBtn").on("click", function () {
    $("#alertStatusFilter").val("all");
    $("#alertLevelFilter").val("all");
    renderAlertsPage();
  });

  $("#alertEmailSubscriptionForm").on("submit", async function (event) {
    event.preventDefault();
    await toggleAlertEmailSubscriptionFromForm();
  });

  $("#alertEmailInput").on("input", debounce(updateAlertEmailButtonState, 400));
});

async function loadAlertHistoryData() {
  const endDate = getPerthToday();
  const startDate = addDaysToIsoDate(endDate, -(ALERT_HISTORY_DAYS - 1));

  try {
    const history = await fetchAlertHistory(startDate, endDate);
    healthAlerts = transformAlerts(history.alerts || []);
  } catch (error) {
    console.warn("Alert history unavailable; using latest alerts snapshot:", error);
  }
}

function addDaysToIsoDate(isoDate, dayOffset) {
  const parts = isoDate.split("-").map(function (part) {
    return Number(part);
  });

  const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  date.setUTCDate(date.getUTCDate() + dayOffset);

  return date.toISOString().slice(0, 10);
}

async function renderAlertSubscriptionStatus() {
  try {
    const data = await fetchAlertSubscriptions();
    const deliveryText = data.emailDeliveryConfigured
      ? "Email delivery is configured."
      : "Subscription is available. Email delivery needs SMTP settings before messages can be sent.";
    $("#alertEmailSubscriptionStatus").text(
      data.subscriberCount +
        " active subscriber(s). " +
        deliveryText
    );
  } catch (error) {
    console.warn("Alert subscription status unavailable:", error);
    $("#alertEmailSubscriptionStatus").text("Notification settings unavailable.");
  }
}

async function updateAlertEmailButtonState() {
  const email = $("#alertEmailInput").val().trim();

  if (!email || !email.includes("@")) {
    setAlertEmailButton(false);
    return;
  }

  try {
    const result = await fetchAlertSubscriptionStatus(email);
    setAlertEmailButton(result.subscribed);
  } catch (error) {
    setAlertEmailButton(false);
  }
}

async function toggleAlertEmailSubscriptionFromForm() {
  const email = $("#alertEmailInput").val().trim();

  $("#alertEmailSubscribeBtn")
    .prop("disabled", true)
    .html('<span class="spinner-border spinner-border-sm me-2"></span>Saving');

  try {
    const result = await toggleAlertEmailSubscription(email);
    $("#alertEmailSubscriptionStatus").text(
      result.email +
        (result.subscribed
          ? " subscribed for Medium and High alerts."
          : " unsubscribed from alert emails.") +
        (result.emailDeliveryConfigured
          ? ""
          : " SMTP delivery is not configured yet.")
    );
    await renderAlertSubscriptionStatus();
    $("#alertEmailInput").val(email);
    setAlertEmailButton(result.subscribed);
  } catch (error) {
    $("#alertEmailSubscriptionStatus").text(error.message);
    await updateAlertEmailButtonState();
  } finally {
    $("#alertEmailSubscribeBtn").prop("disabled", false);
  }
}

function setAlertEmailButton(isSubscribed) {
  $("#alertEmailSubscribeBtn").html(
    isSubscribed
      ? '<i class="bi bi-envelope-x"></i> Unsubscribe'
      : '<i class="bi bi-envelope-plus"></i> Subscribe'
  );
}

function debounce(callback, delayMs) {
  let timeoutId = null;

  return function () {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(callback, delayMs);
  };
}

function renderAlertsPage() {
  const currentAlerts = getCurrentAlerts();
  const historyAlerts = getFilteredHistoryAlerts();

  renderAlertSummary();
  renderAlertCards(currentAlerts);
  renderAlertsTable(historyAlerts);
}

function getCurrentAlerts() {
  const selectedLevel = $("#alertLevelFilter").val();

  let currentAlerts = healthAlerts.filter(function (alert) {
    return alert.status === "Unresolved";
  });

  if (selectedLevel !== "all") {
    currentAlerts = currentAlerts.filter(function (alert) {
      return alert.level === selectedLevel;
    });
  }

  return currentAlerts;
}

function getFilteredHistoryAlerts() {
  const selectedStatus = $("#alertStatusFilter").val();
  const selectedLevel = $("#alertLevelFilter").val();

  let historyAlerts = healthAlerts;

  if (selectedStatus !== "all") {
    historyAlerts = historyAlerts.filter(function (alert) {
      return alert.status === selectedStatus;
    });
  }

  if (selectedLevel !== "all") {
    historyAlerts = historyAlerts.filter(function (alert) {
      return alert.level === selectedLevel;
    });
  }

  return historyAlerts;
}

function renderAlertSummary() {
  const totalAlerts = healthAlerts.length;

  const unresolvedAlerts = healthAlerts.filter(function (alert) {
    return alert.status === "Unresolved";
  }).length;

  const resolvedAlerts = healthAlerts.filter(function (alert) {
    return alert.status === "Resolved";
  }).length;

  const highAlerts = healthAlerts.filter(function (alert) {
    return alert.level === "High";
  }).length;

  $("#totalAlerts").text(totalAlerts);
  $("#unresolvedAlerts").text(unresolvedAlerts);
  $("#resolvedAlerts").text(resolvedAlerts);
  $("#highAlerts").text(highAlerts);
}

function renderAlertCards(alerts) {
  const container = $("#alertsContainer");
  container.empty();

  if (alerts.length === 0) {
    container.html(`
      <p class="text-muted mb-0">
        No current unresolved alerts match the selected filters.
      </p>
    `);

    return;
  }

  alerts.forEach(function (alert) {
    const badgeClass = getAlertBadgeClass(alert.level);
    const statusClass = getStatusBadgeClass(alert.status);
    const calloutClass = getAlertCalloutClass(alert.level);
    const titleClass = getAlertTitleClass(alert.level);
    const actionButton = getAlertActionButton(alert);

    const alertCard = `
      <div class="alert-callout ${calloutClass}">
        <div class="row align-items-center g-3">
          <div class="col-md-2">
            <strong>🐱 ${alert.catName}</strong>
            <div class="mt-1">
              <span class="badge ${badgeClass}">${alert.level}</span>
            </div>
          </div>

          <div class="col-md-5">
            <div class="${titleClass}">
              ${getAlertTitle(alert)}
            </div>

            <div>
              ${alert.message}
            </div>
          </div>

          <div class="col-md-2">
            <div class="text-muted small">Detected</div>
            <div>${alert.createdAt || "-"}</div>
          </div>

          <div class="col-md-1">
            <div class="text-muted small">Status</div>
            <span class="badge ${statusClass}">${alert.status}</span>
          </div>

          <div class="col-md-2 text-end">
            ${actionButton}
          </div>
        </div>
      </div>
    `;

    container.append(alertCard);
  });

  $(".resolve-alert-btn").on("click", async function () {
    const alertId = String($(this).data("id"));
    await resolveAlert(alertId, $(this));
  });
}

function renderAlertsTable(alerts) {
  const tableBody = $("#alertsTable");
  tableBody.empty();

  if (alerts.length === 0) {
    tableBody.html(`
      <tr>
        <td colspan="6" class="text-center text-muted">
          No health alerts found.
        </td>
      </tr>
    `);

    return;
  }

  alerts.forEach(function (alert) {
    const badgeClass = getAlertBadgeClass(alert.level);
    const statusClass = getStatusBadgeClass(alert.status);

    const row = `
      <tr>
        <td>${alert.id}</td>
        <td><strong>🐱 ${alert.catName}</strong></td>
        <td><span class="badge ${badgeClass}">${alert.level}</span></td>
        <td>${alert.message}</td>
        <td>${alert.createdAt || "-"}</td>
        <td><span class="badge ${statusClass}">${alert.status}</span></td>
      </tr>
    `;

    tableBody.append(row);
  });
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

  if (alert.alertType === "invalid_payload") {
    return "Invalid payload";
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

function getAlertActionButton(alert) {
  if (alert.status === "Resolved") {
    return `
      <button class="btn btn-sm btn-outline-secondary" disabled>
        Resolved
      </button>
    `;
  }

  return `
    <button
      class="btn btn-sm btn-primary resolve-alert-btn"
      data-id="${alert.id}"
    >
      Mark as Resolved
    </button>
  `;
}

async function resolveAlert(alertId, button) {
  const alert = healthAlerts.find(function (item) {
    return String(item.id) === String(alertId);
  });

  if (!alert) {
    return;
  }

  button.prop("disabled", true).text("Resolving...");

  try {
    await resolveBackendAlert(alert.id, alert.alertDate);
    alert.status = "Resolved";
    renderAlertsPage();
  } catch (error) {
    $("#alertEmailSubscriptionStatus").text(error.message);
    button.prop("disabled", false).text("Mark as Resolved");
  }
}
