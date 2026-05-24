var activeRfidRebind = null;
var rfidRebindPollTimer = null;

$(document).ready(async function () {
  await loadBackendData();

  renderCatsPage();
  resetCatForm();

  $("#catForm").on("submit", async function (event) {
    event.preventDefault();
    await saveCat();
  });

  $("#cancelEditBtn").on("click", function () {
    resetCatForm();
  });

  $("#generateRfidBtn").on("click", function () {
    simulateRfidScan();
  });
});

function renderCatsPage() {
  renderCatSummary();
  renderCatsTable();
  updateCapacityState();
}

function renderCatSummary() {
  const totalCats = cats.length;

  const totalRfidTags = cats.filter(function (cat) {
    return cat.rfidTag && cat.rfidTag.trim() !== "";
  }).length;

  const assignedBowls = cats.filter(function (cat) {
    return cat.assignedBowl !== null && cat.assignedBowl !== undefined;
  }).length;

  const totalTarget = cats.reduce(function (sum, cat) {
    return sum + Number(cat.dailyTarget);
  }, 0);

  const averageTarget =
    totalCats === 0 ? 0 : Math.round(totalTarget / totalCats);

  $("#totalCats").text(totalCats);
  $("#totalRfidTags").text(totalRfidTags);
  $("#assignedBowls").text(assignedBowls);
  $("#averageTarget").text(averageTarget + "g");
}

function renderCatsTable() {
  const tableBody = $("#catsTable");
  tableBody.empty();

  if (cats.length === 0) {
    tableBody.html(`
      <tr>
        <td colspan="6" class="text-center text-muted">
          No cats registered.
        </td>
      </tr>
    `);

    return;
  }

  cats.forEach(function (cat) {
    const isRebinding =
      activeRfidRebind &&
      activeRfidRebind.backendCatId === cat.backendCatId;

    const disabledAttribute = activeRfidRebind ? "disabled" : "";
    const rebindButtonText = isRebinding ? "Scanning..." : "Rebind RFID";

    const row = `
      <tr>
        <td>${cat.id}</td>

        <td>
          <strong>🐱 ${cat.name}</strong>
          <div>
            <span class="badge badge-cat">Cat ${cat.id}</span>
          </div>
        </td>

        <td>${cat.rfidTag}</td>

        <td>
          <span class="badge bg-light text-dark border">
            Bowl ${cat.assignedBowl}
          </span>
        </td>

        <td>
          <strong>${cat.dailyTarget}g</strong>
        </td>

        <td>
          <button
            class="btn btn-sm btn-outline-primary edit-cat-btn"
            data-id="${cat.id}"
            ${disabledAttribute}
          >
            Edit
          </button>

          <button
            class="btn btn-sm btn-outline-info rebind-cat-btn"
            data-id="${cat.id}"
            ${disabledAttribute}
          >
            ${rebindButtonText}
          </button>

          <button
            class="btn btn-sm btn-outline-danger delete-cat-btn"
            data-id="${cat.id}"
            ${disabledAttribute}
          >
            Delete
          </button>
        </td>
      </tr>
    `;

    tableBody.append(row);
  });

  $(".edit-cat-btn").on("click", function () {
    const catId = Number($(this).data("id"));
    editCat(catId);
  });

  $(".rebind-cat-btn").on("click", function () {
    const catId = Number($(this).data("id"));
    rebindRfid(catId);
  });

  $(".delete-cat-btn").on("click", function () {
    const catId = Number($(this).data("id"));
    deleteCat(catId);
  });
}

async function saveCat() {
  const catId = $("#catId").val();

  const catData = {
    name: $("#catName").val().trim(),
    rfidTag: $("#rfidTag").val().trim(),
    assignedBowl: Number($("#assignedBowl").val()),
    dailyTarget: Number($("#dailyTarget").val())
  };

  if (
    !catData.name ||
    !catData.rfidTag ||
    !catData.assignedBowl ||
    !catData.dailyTarget
  ) {
    setRfidStatus(
      "Please complete all cat information before saving.",
      "danger"
    );
    return;
  }

  let savedSuccessfully = false;

  if (catId) {
    savedSuccessfully = await updateCat(Number(catId), catData);
  } else {
    savedSuccessfully = addCat(catData);
  }

  if (savedSuccessfully) {
    resetCatForm();
    renderCatsPage();

    setRfidStatus("Cat information has been saved.", "success");
  }
}

function addCat(catData) {
  if (cats.length >= 2) {
    setRfidStatus(
      "This prototype currently supports a maximum of 2 cats.",
      "danger"
    );
    return false;
  }

  if (isBowlAlreadyUsed(catData.assignedBowl)) {
    setRfidStatus(
      "This feeding bowl is already assigned to another cat.",
      "danger"
    );
    return false;
  }

  if (isRfidAlreadyUsed(catData.rfidTag)) {
    setRfidStatus(
      "This RFID tag is already bound to another cat.",
      "danger"
    );
    return false;
  }

  const newId = getNextCatId();

  cats.push({
    id: newId,
    backendCatId: "local_cat_" + newId,
    name: catData.name,
    rfidTag: catData.rfidTag,
    assignedBowl: catData.assignedBowl,
    dailyTarget: catData.dailyTarget,
    todayIntakeGrams: 0,
    lastIntakeGrams: 0,
    todayStatus: "local"
  });

  return true;
}

async function updateCat(catId, catData) {
  const cat = cats.find(function (item) {
    return item.id === catId;
  });

  if (!cat) {
    setRfidStatus("Cat not found.", "danger");
    return false;
  }

  if (isBowlAlreadyUsed(catData.assignedBowl, catId)) {
    setRfidStatus(
      "This feeding bowl is already assigned to another cat.",
      "danger"
    );
    return false;
  }

  if (isRfidAlreadyUsed(catData.rfidTag, catId)) {
    setRfidStatus(
      "This RFID tag is already bound to another cat.",
      "danger"
    );
    return false;
  }

  if (cat.backendCatId && !cat.backendCatId.startsWith("local_cat_")) {
    try {
      setRfidStatus("Saving cat profile to backend...", "success");

      await updateCatProfile(cat.backendCatId, {
        catName: catData.name,
        targetDailyGrams: catData.dailyTarget
      });

      await loadBackendData();

      return true;
    } catch (error) {
      console.error("Cat profile update failed:", error);
      setRfidStatus(error.message, "danger");
      return false;
    }
  }

  cat.name = catData.name;
  cat.rfidTag = catData.rfidTag;
  cat.assignedBowl = catData.assignedBowl;
  cat.dailyTarget = catData.dailyTarget;

  return true;
}

function editCat(catId) {
  if (activeRfidRebind) {
    setRfidStatus(
      "RFID scan is currently active. Please wait until it finishes.",
      "danger"
    );
    return;
  }

  const cat = cats.find(function (item) {
    return item.id === catId;
  });

  if (!cat) {
    setRfidStatus("Cat not found.", "danger");
    return;
  }

  $("#catId").val(cat.id);
  $("#catName").val(cat.name);
  $("#rfidTag").val(cat.rfidTag);
  $("#assignedBowl").val(cat.assignedBowl);
  $("#dailyTarget").val(cat.dailyTarget);

  $("#formTitle").text("Edit Cat");
  $("#saveCatBtn").text("Save Changes").prop("disabled", false);

  setRfidStatus("Editing cat locally: " + cat.name, "success");
}

function deleteCat(catId) {
  if (activeRfidRebind) {
    setRfidStatus(
      "RFID scan is currently active. Please wait until it finishes.",
      "danger"
    );
    return;
  }

  const catIndex = cats.findIndex(function (item) {
    return item.id === catId;
  });

  if (catIndex === -1) {
    setRfidStatus("Cat not found.", "danger");
    return;
  }

  const catName = cats[catIndex].name;

  const confirmed = confirm(
    "Delete " + catName + " from the local frontend list?"
  );

  if (!confirmed) {
    return;
  }

  cats.splice(catIndex, 1);

  setRfidStatus(catName + " has been deleted locally.", "success");

  resetCatForm();
  renderCatsPage();
}

async function rebindRfid(catId) {
  if (activeRfidRebind) {
    setRfidStatus(
      "Another RFID scan is already running. Please wait until it finishes.",
      "danger"
    );
    return;
  }

  const cat = cats.find(function (item) {
    return item.id === catId;
  });

  if (!cat) {
    setRfidStatus("Cat not found.", "danger");
    return;
  }

  if (!cat.backendCatId || cat.backendCatId.startsWith("local_cat_")) {
    setRfidStatus(
      "This cat does not have a backend cat ID, so RFID rebind cannot be started.",
      "danger"
    );
    return;
  }

  const confirmed = confirm(
    "Start RFID rebind scan for " +
      cat.name +
      "?\n\nPlease place the new RFID tag near the feeder after the scan starts."
  );

  if (!confirmed) {
    return;
  }

  const oldRfidTag = cat.rfidTag;
  const timeoutSec = 120;

  activeRfidRebind = {
    catId: cat.id,
    backendCatId: cat.backendCatId,
    catName: cat.name,
    oldRfidTag: oldRfidTag,
    operationId: "",
    expiresAtMs: Date.now() + timeoutSec * 1000
  };

  renderCatsPage();

  setRfidStatus(
    "Starting RFID scan for " +
      cat.name +
      "... Please keep the new RFID tag close to the reader.",
    "success"
  );

  try {
    const result = await startRfidRebindScan(cat.backendCatId, timeoutSec);

    activeRfidRebind.operationId = result.operationId || "";
    activeRfidRebind.expiresAtMs = result.expiresAtUtc
      ? new Date(result.expiresAtUtc).getTime()
      : Date.now() + timeoutSec * 1000;

    setRfidStatus(
      "RFID scan command sent for " +
        cat.name +
        ". Please scan the new RFID tag now. " +
        "Old UID: " +
        oldRfidTag +
        ". Operation ID: " +
        (activeRfidRebind.operationId || "N/A") +
        ".",
      "success"
    );

    startRfidRebindPolling();
  } catch (error) {
    console.error("RFID rebind scan failed:", error);

    activeRfidRebind = null;
    stopRfidRebindPolling();
    renderCatsPage();

    setRfidStatus(
      "Failed to start RFID scan. Please check whether ESP32 is online and try again. " +
        error.message,
      "danger"
    );
  }
}

function startRfidRebindPolling() {
  stopRfidRebindPolling();

  rfidRebindPollTimer = setInterval(async function () {
    await checkRfidRebindResult();
  }, 3000);

  checkRfidRebindResult();
}

function stopRfidRebindPolling() {
  if (rfidRebindPollTimer) {
    clearInterval(rfidRebindPollTimer);
    rfidRebindPollTimer = null;
  }
}

async function checkRfidRebindResult() {
  if (!activeRfidRebind) {
    stopRfidRebindPolling();
    return;
  }

  if (Date.now() > activeRfidRebind.expiresAtMs) {
    const catName = activeRfidRebind.catName;

    activeRfidRebind = null;
    stopRfidRebindPolling();

    await loadBackendData();
    renderCatsPage();

    setRfidStatus(
      "RFID scan timed out for " +
        catName +
        ". Please click Rebind RFID and try again.",
      "danger"
    );

    return;
  }

  try {
    await loadBackendData();

    const updatedCat = cats.find(function (item) {
      return item.backendCatId === activeRfidRebind.backendCatId;
    });

    if (!updatedCat) {
      return;
    }

    const newRfidTag = updatedCat.rfidTag;

    if (
      newRfidTag &&
      newRfidTag !== "Unknown" &&
      newRfidTag !== activeRfidRebind.oldRfidTag
    ) {
      const catName = activeRfidRebind.catName;
      const oldTag = activeRfidRebind.oldRfidTag;

      activeRfidRebind = null;
      stopRfidRebindPolling();

      renderCatsPage();

      setRfidStatus(
        "RFID successfully rebound for " +
          catName +
          ". Old UID: " +
          oldTag +
          ". New UID: " +
          newRfidTag +
          ".",
        "success"
      );

      return;
    }

    renderCatsPage();

    setRfidStatus(
      "RFID scan is active for " +
        activeRfidRebind.catName +
        ". Waiting for the new RFID tag. Old UID: " +
        activeRfidRebind.oldRfidTag +
        ".",
      "success"
    );
  } catch (error) {
    console.warn("RFID rebind polling failed:", error);

    setRfidStatus(
      "RFID scan is running, but the frontend could not refresh current status. Please check the backend connection.",
      "danger"
    );
  }
}

function simulateRfidScan() {
  const newTag = generateUniqueRfidTag();

  $("#rfidTag").val(newTag);

  setRfidStatus("RFID tag detected locally: " + newTag, "success");
}

function resetCatForm() {
  $("#catForm")[0].reset();
  $("#catId").val("");

  $("#formTitle").text("Add New Cat");
  $("#saveCatBtn").text("Add Cat");

  updateCapacityState();
}

function updateCapacityState() {
  const usedSlots = cats.length;
  const isFull = usedSlots >= 2;
  const isEditing = $("#catId").val() !== "";

  $("#slotsUsed").text(usedSlots + " of 2 slots used");

  if (activeRfidRebind) {
    $("#saveCatBtn").prop("disabled", true);
    $("#generateRfidBtn").prop("disabled", true);
    return;
  }

  $("#generateRfidBtn").prop("disabled", false);

  if (isFull && !isEditing) {
    $("#saveCatBtn").prop("disabled", true);
    setRfidStatus(
      "Maximum capacity reached. This prototype supports 2 cats.",
      "danger"
    );
  } else {
    $("#saveCatBtn").prop("disabled", false);

    if (!isEditing) {
      setRfidStatus("Waiting for user action.", "success");
    }
  }
}

function setRfidStatus(message, type) {
  const statusElement = $("#rfidStatus");

  statusElement.removeClass("text-success text-danger text-warning");

  if (type === "danger") {
    statusElement.addClass("text-danger");
  } else if (type === "warning") {
    statusElement.addClass("text-warning");
  } else {
    statusElement.addClass("text-success");
  }

  statusElement.text(message);
}

function isBowlAlreadyUsed(bowlNumber, currentCatId) {
  return cats.some(function (cat) {
    return cat.assignedBowl === bowlNumber && cat.id !== currentCatId;
  });
}

function isRfidAlreadyUsed(rfidTag, currentCatId) {
  return cats.some(function (cat) {
    return cat.rfidTag === rfidTag && cat.id !== currentCatId;
  });
}

function getNextCatId() {
  if (cats.length === 0) {
    return 1;
  }

  const ids = cats.map(function (cat) {
    return cat.id;
  });

  return Math.max.apply(null, ids) + 1;
}

function generateUniqueRfidTag() {
  let tag = generateRandomRfidTag();

  while (isRfidAlreadyUsed(tag)) {
    tag = generateRandomRfidTag();
  }

  return tag;
}

function generateRandomRfidTag() {
  const characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  let tag = "";

  for (let i = 0; i < 8; i++) {
    const randomIndex = Math.floor(Math.random() * characters.length);
    tag += characters[randomIndex];
  }

  return tag;
}
