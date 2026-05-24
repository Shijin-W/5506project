/* ==============================================
   Analytics Page — analytics.js
   Renders cat summary cards + per-cat trend charts.
   Single-day view: scatter with full 0-24 h axis.
   Multi-day view:  area/line chart per cat.
============================================== */

let analyticsData = null;
let analyticsCharts = {};
let analyticsErrorMessage = "";

const chartColors = [
  {
    border: "rgba(37, 99, 235, 1)",
    background: "rgba(37, 99, 235, 0.65)"
  },
  {
    border: "rgba(22, 163, 74, 1)",
    background: "rgba(22, 163, 74, 0.65)"
  },
  {
    border: "rgba(245, 158, 11, 1)",
    background: "rgba(245, 158, 11, 0.65)"
  },
  {
    border: "rgba(14, 165, 233, 1)",
    background: "rgba(14, 165, 233, 0.65)"
  }
];

/* Per-cat colour themes for the cat summary cards */
const catThemes = [
  { bg: "rgba(219, 234, 254, 0.75)", color: "#2563eb" },
  { bg: "rgba(220, 252, 231, 0.75)", color: "#15803d" },
  { bg: "rgba(254, 243, 199, 0.75)", color: "#b45309" },
  { bg: "rgba(224, 242, 254, 0.75)", color: "#0369a1" }
];

/* ──────────────────────────────────────────────
   Init
────────────────────────────────────────────── */

$(document).ready(async function () {
  await loadBackendData();
  initialiseAnalyticsRangeControls();
  await loadAnalyticsRangeFromControls();
});

function initialiseAnalyticsRangeControls() {
  const today = getPerthToday();

  $("#analyticsRangePreset").val("today");
  setDateInputs(getPresetDateRange("today", today));
  updateCustomDateAvailability();

  $("#analyticsRangePreset").on("change", async function () {
    const preset = $(this).val();

    if (preset !== "custom") {
      setDateInputs(getPresetDateRange(preset, getPerthToday()));
    }

    updateCustomDateAvailability();
    await loadAnalyticsRangeFromControls();
  });

  $("#analyticsApplyRange").on("click", async function () {
    await loadAnalyticsRangeFromControls();
  });
}

function updateCustomDateAvailability() {
  const isCustom = $("#analyticsRangePreset").val() === "custom";
  $("#analyticsStartDate").prop("disabled", !isCustom);
  $("#analyticsEndDate").prop("disabled", !isCustom);
}

function setDateInputs(range) {
  $("#analyticsStartDate").val(range.startDate);
  $("#analyticsEndDate").val(range.endDate);
}

async function loadAnalyticsRangeFromControls() {
  const startDate = $("#analyticsStartDate").val();
  const endDate = $("#analyticsEndDate").val();

  if (!startDate || !endDate) {
    return;
  }

  if (startDate > endDate) {
    showAnalyticsError("Start date must be before end date.");
    return;
  }

  setAnalyticsLoading(true);

  try {
    analyticsData = await fetchAnalyticsRange(startDate, endDate);
    analyticsErrorMessage = "";
  } catch (error) {
    console.error("Analytics range loading failed:", error);
    analyticsData = buildFallbackAnalyticsData(startDate, endDate);
    analyticsErrorMessage = "Unable to load selected range from backend.";
  } finally {
    setAnalyticsLoading(false);
  }

  renderAnalyticsPage();
}

function setAnalyticsLoading(isLoading) {
  $("#analyticsApplyRange")
    .prop("disabled", isLoading)
    .html(
      isLoading
        ? '<span class="spinner-border spinner-border-sm me-2"></span>Loading'
        : '<i class="bi bi-calendar-check"></i> Apply Range'
    );
}

function showAnalyticsError(message) {
  $("#highestIntakeCat").text("-");
  $("#lowestIntakeCat").text("-");
  $("#analyticsAverageIntake").text("0g");
  $(".analytics-range-label").text(message);
}

/* ──────────────────────────────────────────────
   Main render entry point
────────────────────────────────────────────── */

function renderAnalyticsPage() {
  const data = analyticsData || buildFallbackAnalyticsData(getPerthToday(), getPerthToday());
  const catSummaries = data.catSummaries || [];

  const startDate   = data.startDate;
  const endDate     = data.endDate;
  const isSingleDay = !startDate || !endDate || startDate === endDate;

  renderAnalyticsSummary(data, catSummaries);
  renderCatRows(catSummaries, data, isSingleDay);
}

/* ──────────────────────────────────────────────
   Top summary stat cards (highest / lowest / avg)
────────────────────────────────────────────── */

function renderAnalyticsSummary(data, catSummaries) {
  const nonEmpty = catSummaries.filter(function (cat) {
    return Number(cat.totalIntakeGrams || 0) > 0 || Number(cat.feedingCount || 0) > 0;
  });

  let highestCat = "-";
  let lowestCat  = "-";

  if (nonEmpty.length > 0) {
    const sortedByIntake = nonEmpty.slice().sort(function (left, right) {
      return Number(left.totalIntakeGrams || 0) - Number(right.totalIntakeGrams || 0);
    });

    const lowest  = sortedByIntake[0];
    const highest = sortedByIntake[sortedByIntake.length - 1];

    highestCat = highest.catName + " (" + roundOneDecimal(Number(highest.totalIntakeGrams || 0)) + "g)";
    lowestCat  = lowest.catName  + " (" + roundOneDecimal(Number(lowest.totalIntakeGrams  || 0)) + "g)";
  }

  const average = data.totals
    ? roundOneDecimal(Number(data.totals.averageIntakeGrams || 0))
    : 0;

  $("#highestIntakeCat").text(highestCat);
  $("#lowestIntakeCat").text(lowestCat);
  $("#analyticsAverageIntake").text(average + "g");
  $(".analytics-range-label").text(
    analyticsErrorMessage || getRangeLabel(data.startDate, data.endDate)
  );
}

/* ──────────────────────────────────────────────
   Combined per-cat rows
   Each cat gets its own Bootstrap row:
     col-lg-5 → summary card (intake + frequency)
     col-lg-7 → trend chart
   This guarantees the two sides are always aligned.
────────────────────────────────────────────── */

function renderCatRows(catSummaries, data, isSingleDay) {
  const container = document.getElementById("catAnalyticsContainer");
  if (!container) {
    return;
  }

  /* Destroy any existing per-cat charts */
  Object.keys(analyticsCharts)
    .filter(function (k) { return k.startsWith("catTrend_"); })
    .forEach(function (k) {
      analyticsCharts[k].destroy();
      delete analyticsCharts[k];
    });

  if (!catSummaries || catSummaries.length === 0) {
    container.innerHTML = '<p class="text-muted">No cat data available for this range.</p>';
    return;
  }

  const trendSubtitle = isSingleDay
    ? "<span class='fw-normal text-muted ms-2' style='font-size:0.8rem'>· Today's feedings by time</span>"
    : "<span class='fw-normal text-muted ms-2' style='font-size:0.8rem'>· Daily intake over range</span>";

  let html = "";

  catSummaries.forEach(function (cat, index) {
    const theme        = catThemes[index % catThemes.length];
    const intake       = roundOneDecimal(Number(cat.totalIntakeGrams || 0));
    const feedingCount = Number(cat.feedingCount || 0);
    const avgPerMeal   = feedingCount > 0 ? roundOneDecimal(intake / feedingCount) : 0;
    const dailyTarget  = Number(cat.targetDailyGrams || 0);
    const progressPct  = isSingleDay && dailyTarget > 0
      ? Math.min(100, Math.round((intake / dailyTarget) * 100))
      : 0;

    const targetBar = isSingleDay && dailyTarget > 0
      ? "<div class='cat-intake-progress mt-2'>" +
          "<div class='cat-intake-progress-fill' style='width:" + progressPct + "%;background:" + theme.color + "'></div>" +
        "</div>" +
        "<div class='cat-stat-sub'>" + progressPct + "% of " + dailyTarget + "g target</div>"
      : "";

    const avgLine = avgPerMeal > 0
      ? "<div class='cat-stat-sub'>" + avgPerMeal + "g avg / meal</div>"
      : "";

    const canvasId = "catTrendCanvas_" + cat.catId;

    html += `
      <div class="row g-4${index > 0 ? " mt-1" : " mb-0"}">
        <div class="col-lg-5 d-flex">
          <div class="cat-summary-card flex-grow-1">
            <div class="cat-summary-header">
              <div class="cat-avatar-circle" style="background:${theme.bg};color:${theme.color}">🐱</div>
              <div>
                <div class="cat-name-label" style="color:${theme.color}">${escHtml(cat.catName)}</div>
                <div class="cat-name-sub">${feedingCount} feeding${feedingCount !== 1 ? "s" : ""} in period</div>
              </div>
            </div>
            <div class="cat-stat-grid">
              <div class="cat-stat-box">
                <div class="cat-stat-icon">🥘</div>
                <div class="cat-stat-value" style="color:${theme.color}">${intake}g</div>
                <div class="cat-stat-label">Total Intake</div>
                ${targetBar}
              </div>
              <div class="cat-stat-box">
                <div class="cat-stat-icon">🔁</div>
                <div class="cat-stat-value" style="color:${theme.color}">${feedingCount}</div>
                <div class="cat-stat-label">Feedings</div>
                ${avgLine}
              </div>
            </div>
          </div>
        </div>
        <div class="col-lg-7 d-flex">
          <div class="card flex-grow-1 cat-trend-card">
            <div class="card-header fw-bold">
              🐱 ${escHtml(cat.catName)}'s Feeding Trend${trendSubtitle}
            </div>
            <div class="card-body d-flex flex-column">
              <div class="cat-trend-chart-body">
                <canvas id="${canvasId}"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>`;
  });

  container.innerHTML = html;

  /* Render each chart after DOM update */
  catSummaries.forEach(function (cat, index) {
    const catColor = getChartColor(index);
    if (isSingleDay) {
      renderSingleDayCatChart(cat, data.feedingRecords || [], catColor);
    } else {
      renderMultiDayCatChart(cat, data.dailySeries || [], catColor);
    }
  });
}

/* ──────────────────────────────────────────────
   Single-day scatter chart (full 0-24 h axis)
   Each feeding = one bubble; colour per cat.
   Solves the "sparse isolated dots" problem by
   always showing the full day context.
────────────────────────────────────────────── */

function renderSingleDayCatChart(cat, feedingRecords, catColor) {
  const catRecords = feedingRecords
    .filter(function (r) { return r.catId === cat.catId; })
    .sort(function (a, b) {
      return String(a.feedingEndTimeUtc || a.feedingStartTimeUtc || "")
        .localeCompare(String(b.feedingEndTimeUtc || b.feedingStartTimeUtc || ""));
    });

  /* Convert each feeding to {x: minutes-since-midnight, y: grams} */
  const scatterData = catRecords.map(function (r) {
    const timeStr  = formatPerthTime(r.feedingEndTimeUtc || r.feedingStartTimeUtc || "");
    const parts    = timeStr.split(":");
    const h        = parseInt(parts[0] || "0", 10);
    const m        = parseInt(parts[1] || "0", 10);
    return { x: h * 60 + m, y: roundOneDecimal(Number(r.intakeGrams || 0)) };
  });

  const canvasId = "catTrendCanvas_" + cat.catId;
  const hasData  = scatterData.length > 0;

  renderChart("catTrend_" + cat.catId, canvasId, {
    type: "scatter",
    data: {
      datasets: [
        {
          label: cat.catName,
          data: scatterData,
          backgroundColor: catColor.border,
          borderColor: catColor.border,
          pointRadius: hasData ? 9 : 0,
          pointHoverRadius: 12,
          pointStyle: "circle"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function (items) {
              const x = Math.round(items[0].parsed.x);
              return padTwo(Math.floor(x / 60)) + ":" + padTwo(x % 60);
            },
            label: function (item) {
              return cat.catName + ": " + item.parsed.y + "g";
            }
          }
        }
      },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: 1440,
          title: { display: true, text: "Time of Day" },
          grid: { color: "rgba(148, 163, 184, 0.2)" },
          ticks: {
            stepSize: 240,
            callback: function (val) {
              return padTwo(Math.floor(val / 60)) + ":00";
            }
          }
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: "Food Intake (g)" },
          grid: { color: "rgba(148, 163, 184, 0.22)" }
        }
      }
    }
  });
}

/* ──────────────────────────────────────────────
   Multi-day area/line chart per cat
────────────────────────────────────────────── */

function renderMultiDayCatChart(cat, dailySeries, catColor) {
  const catRows = dailySeries.filter(function (row) {
    return row.catId === cat.catId;
  });

  const rowsByDate = {};
  catRows.forEach(function (row) {
    rowsByDate[row.date] = Number(row.totalIntakeGrams || 0);
  });

  const labels = Object.keys(rowsByDate).sort();
  const values = labels.map(function (d) {
    return roundOneDecimal(rowsByDate[d] || 0);
  });

  /* Lighter fill for area under the line */
  const fillColor = catColor.background.replace("0.65", "0.12");

  renderChart("catTrend_" + cat.catId, "catTrendCanvas_" + cat.catId, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: cat.catName,
          data: values,
          fill: true,
          tension: 0.3,
          borderColor: catColor.border,
          backgroundColor: fillColor,
          pointBackgroundColor: catColor.border,
          pointBorderColor: catColor.border,
          pointRadius: 4,
          pointHoverRadius: 7
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: "Food Intake (g)" },
          grid: { color: "rgba(148, 163, 184, 0.22)" }
        },
        x: {
          grid: { color: "rgba(148, 163, 184, 0.12)" }
        }
      }
    }
  });
}

/* ──────────────────────────────────────────────
   Chart utility — create / destroy
────────────────────────────────────────────── */

function renderChart(key, canvasId, config) {
  if (analyticsCharts[key]) {
    analyticsCharts[key].destroy();
  }

  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    return;
  }

  analyticsCharts[key] = new Chart(canvas, config);
}

function getChartColor(index) {
  return chartColors[index % chartColors.length];
}

/* ──────────────────────────────────────────────
   Date range helpers
────────────────────────────────────────────── */

function getPresetDateRange(preset, today) {
  if (preset === "week") {
    const day = getIsoDayOfWeek(today);
    const startDate = addDaysIso(today, 1 - day);
    return { startDate: startDate, endDate: addDaysIso(startDate, 6) };
  }

  if (preset === "month") {
    const parts = parseIsoDate(today);
    return {
      startDate: parts.year + "-" + padTwo(parts.month) + "-01",
      endDate: formatIsoDate(new Date(Date.UTC(parts.year, parts.month, 0)))
    };
  }

  return { startDate: today, endDate: today };
}

function getIsoDayOfWeek(isoDate) {
  const date = new Date(isoDate + "T00:00:00Z");
  const day  = date.getUTCDay();
  return day === 0 ? 7 : day;
}

function addDaysIso(isoDate, days) {
  const date = new Date(isoDate + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + days);
  return formatIsoDate(date);
}

function formatIsoDate(date) {
  return (
    date.getUTCFullYear() +
    "-" +
    padTwo(date.getUTCMonth() + 1) +
    "-" +
    padTwo(date.getUTCDate())
  );
}

function formatPerthTime(isoString) {
  if (!isoString) {
    return "";
  }

  const date = new Date(isoString);

  if (isNaN(date.getTime())) {
    return isoString;
  }

  const parts = new Intl.DateTimeFormat("en-AU", {
    timeZone: "Australia/Perth",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(date);

  return getDatePart(parts, "hour") + ":" + getDatePart(parts, "minute");
}

function parseIsoDate(isoDate) {
  const parts = isoDate.split("-").map(function (part) {
    return Number(part);
  });
  return { year: parts[0], month: parts[1], day: parts[2] };
}

function padTwo(value) {
  return String(value).padStart(2, "0");
}

function getRangeLabel(startDate, endDate) {
  if (!startDate || !endDate) {
    return "based on selected range";
  }

  if (startDate === endDate) {
    return "range: " + startDate;
  }

  return "range: " + startDate + " to " + endDate;
}

/* ──────────────────────────────────────────────
   XSS helper
────────────────────────────────────────────── */

function escHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

/* ──────────────────────────────────────────────
   Fallback data (when backend is unreachable)
────────────────────────────────────────────── */

function buildFallbackAnalyticsData(startDate, endDate) {
  const fallbackSummaries = cats.map(function (cat) {
    const matchingRecords = feedingRecords.filter(function (record) {
      return record.backendCatId === cat.backendCatId;
    });

    const total = matchingRecords.reduce(function (sum, record) {
      return sum + Number(record.intakeGrams || 0);
    }, 0);

    return {
      catId:             cat.backendCatId,
      catName:           cat.name,
      totalIntakeGrams:  roundOneDecimal(total),
      feedingCount:      matchingRecords.length,
      averageIntakeGrams: matchingRecords.length
        ? roundOneDecimal(total / matchingRecords.length)
        : 0,
      targetDailyGrams:  cat.dailyTarget,
      daysWithData:      matchingRecords.length ? 1 : 0
    };
  });

  const totalAll     = fallbackSummaries.reduce(function (s, c) { return s + Number(c.totalIntakeGrams || 0); }, 0);
  const countAll     = fallbackSummaries.reduce(function (s, c) { return s + Number(c.feedingCount    || 0); }, 0);
  const averageAll   = countAll > 0 ? roundOneDecimal(totalAll / countAll) : 0;

  return {
    startDate:    startDate,
    endDate:      endDate,
    catSummaries: fallbackSummaries,
    dailySeries:  fallbackSummaries.map(function (cat) {
      return {
        date:             startDate,
        catId:            cat.catId,
        catName:          cat.catName,
        totalIntakeGrams: cat.totalIntakeGrams,
        feedingCount:     cat.feedingCount
      };
    }),
    feedingRecords: feedingRecords,
    totals: {
      totalIntakeGrams:   roundOneDecimal(totalAll),
      feedingCount:       countAll,
      averageIntakeGrams: averageAll
    }
  };
}
