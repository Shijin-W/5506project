const RECORD_HISTORY_START_DATE = "2026-01-01";

$(document).ready(async function () {
  await loadBackendData();
  await loadAllFeedingRecords();

  initialiseRecordsPage();

  $("#catFilter").on("change", function () {
    renderRecordsTable();
  });

  $("#startDateFilter").on("change", function () {
    renderRecordsTable();
  });

  $("#endDateFilter").on("change", function () {
    renderRecordsTable();
  });

  $("#resetFiltersBtn").on("click", function () {
    $("#catFilter").val("all");
    $("#startDateFilter").val("");
    $("#endDateFilter").val("");
    renderRecordsTable();
  });
});

async function loadAllFeedingRecords() {
  try {
    const analytics = await fetchAnalyticsRange(RECORD_HISTORY_START_DATE, getPerthToday());
    feedingRecords = transformFeedingRecords(analytics.feedingRecords || [], cats);
  } catch (error) {
    console.warn("All feeding history unavailable; using latest loaded records:", error);
  }
}

function initialiseRecordsPage() {
  populateCatFilter();
  renderRecordsTable();
}

function populateCatFilter() {
  const catFilter = $("#catFilter");
  const selectedValue = catFilter.val() || "all";

  catFilter.empty();
  catFilter.append(`<option value="all">All Cats</option>`);

  cats.forEach(function (cat) {
    const option = `
      <option value="${cat.id}">
        ${cat.name}
      </option>
    `;

    catFilter.append(option);
  });

  catFilter.val(selectedValue);
}

function renderRecordsTable() {
  const tableBody = $("#recordsTable");
  tableBody.empty();

  const filteredRecords = getFilteredRecords();

  updateSummaryCards(feedingRecords);

  if (filteredRecords.length === 0) {
    tableBody.html(`
      <tr>
        <td colspan="7" class="text-center text-muted">
          No feeding records found for the selected filters.
        </td>
      </tr>
    `);

    return;
  }

  filteredRecords.forEach(function (record) {
    const cat = cats.find(function (item) {
      return item.id === record.catId;
    });

    const rfidTag = record.rfidTag || (cat ? cat.rfidTag : "Unknown");
    const duration = getDurationLabel(record);

    const row = `
      <tr>
        <td>${record.id}</td>
        <td>
          <strong>🐱 ${record.catName}</strong>
        </td>
        <td>${rfidTag}</td>
        <td>${record.startTime || "-"}</td>
        <td>${record.endTime || "-"}</td>
        <td>${duration}</td>
        <td><strong>${record.intakeGrams}g</strong></td>
      </tr>
    `;

    tableBody.append(row);
  });
}

function getFilteredRecords() {
  const selectedCatId = $("#catFilter").val();
  const startDate = $("#startDateFilter").val();
  const endDate = $("#endDateFilter").val();

  let filteredRecords = feedingRecords;

  if (selectedCatId !== "all") {
    filteredRecords = filteredRecords.filter(function (record) {
      return record.catId === Number(selectedCatId);
    });
  }

  if (startDate !== "") {
    filteredRecords = filteredRecords.filter(function (record) {
      return getRecordLocalDate(record) >= startDate;
    });
  }

  if (endDate !== "") {
    filteredRecords = filteredRecords.filter(function (record) {
      return getRecordLocalDate(record) <= endDate;
    });
  }

  return filteredRecords;
}

function updateSummaryCards(records) {
  const totalRecords = records.length;

  const totalIntake = records.reduce(function (sum, record) {
    return sum + Number(record.intakeGrams);
  }, 0);

  const averageIntake =
    totalRecords === 0 ? 0 : Math.round(totalIntake / totalRecords);

  $("#totalRecords").text(totalRecords);
  $("#recordsTotalIntake").text(roundOneDecimal(totalIntake) + "g");
  $("#averageIntake").text(averageIntake + "g");
}

function getDurationLabel(record) {
  if (record.durationSec && record.durationSec > 0) {
    return Math.round(record.durationSec) + " sec";
  }

  return calculateDuration(record.startTime, record.endTime);
}

function calculateDuration(startTime, endTime) {
  const start = new Date(startTime);
  const end = new Date(endTime);

  if (isNaN(start.getTime()) || isNaN(end.getTime())) {
    return "-";
  }

  const differenceMs = end - start;
  const differenceMinutes = Math.round(differenceMs / 1000 / 60);

  return differenceMinutes + " min";
}

function getRecordLocalDate(record) {
  return record.localDate || String(record.startTime || "").slice(0, 10);
}
