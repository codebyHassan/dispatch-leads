document.addEventListener("DOMContentLoaded", function () {
  // Copy-to-clipboard buttons
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.getAttribute("data-copy") || "";
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(text).then(function () {
        var orig = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(function () {
          btn.textContent = orig;
        }, 1200);
      });
    });
  });

  // Bulk select-all checkbox on Carrier Search table
  var selectAll = document.getElementById("select-all-carriers");
  var rowBoxes = document.querySelectorAll(".carrier-row-checkbox");
  var selectedCounter = document.getElementById("selected-carriers-count");

  function updateSelectedCount() {
    if (!selectedCounter) return;
    var checked = document.querySelectorAll(".carrier-row-checkbox:checked").length;
    selectedCounter.textContent = checked + " selected";
  }

  if (selectAll) {
    selectAll.addEventListener("change", function () {
      rowBoxes.forEach(function (cb) {
        cb.checked = selectAll.checked;
      });
      updateSelectedCount();
    });
  }

  rowBoxes.forEach(function (cb) {
    cb.addEventListener("change", updateSelectedCount);
  });

  // Mobile filter drawer toggle
  var filterToggleBtn = document.getElementById("toggle-filter-drawer");
  var filterSidebar = document.getElementById("carrier-filter-sidebar");
  if (filterToggleBtn && filterSidebar) {
    filterToggleBtn.addEventListener("click", function () {
      var isHidden = filterSidebar.getAttribute("data-collapsed") === "true";
      filterSidebar.setAttribute("data-collapsed", isHidden ? "false" : "true");
      filterSidebar.style.display = isHidden ? "block" : "none";
    });
  }

  // SyncJob progress polling every 2 seconds on /sync/
  var pollBox = document.getElementById("sync-job-poller");
  if (pollBox) {
    var jobId = pollBox.getAttribute("data-job-id");
    var statusUrl = "/sync/jobs/" + jobId + "/status/";
    var timer = setInterval(function () {
      fetch(statusUrl, { headers: { Accept: "application/json" } })
        .then(function (r) {
          return r.json();
        })
        .then(function (data) {
          var stEl = document.getElementById("job-status-text");
          var prEl = document.getElementById("job-progress-text");
          var barEl = document.getElementById("job-progress-bar");
          var msgEl = document.getElementById("job-summary-msg");

          if (stEl) stEl.textContent = data.status.toUpperCase();
          if (prEl)
            prEl.textContent =
              data.processed +
              " / " +
              data.total +
              " (" +
              data.progress_percent +
              "%) — Created: " +
              data.created_count +
              ", Updated: " +
              data.updated_count;
          if (barEl) barEl.style.width = data.progress_percent + "%";
          if (msgEl && data.summary_message)
            msgEl.textContent = data.summary_message;

          if (data.status === "done" || data.status === "failed") {
            clearInterval(timer);
            setTimeout(function () {
              window.location.reload();
            }, 800);
          }
        })
        .catch(function () {});
    }, 2000);
  }
});
