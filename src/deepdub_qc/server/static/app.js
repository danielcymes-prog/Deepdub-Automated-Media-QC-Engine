/* Deepdub QC Console — polling + copy + path browser + preset card only.
   The GUI displays pipeline output verbatim; nothing here computes QC. */
(function () {
  "use strict";

  /* ---- polling: replace the [data-poll] region with the fresh page's ---- */
  var region = document.querySelector("[data-poll]");
  var pollSeconds = 2;
  if (region) {
    var url = region.getAttribute("data-poll");
    var failures = 0;
    setInterval(function () {
      fetch(url, { headers: { "X-Requested-With": "poll" } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) {
          failures = 0;
          var doc = new DOMParser().parseFromString(html, "text/html");
          var fresh = doc.querySelector("[data-poll]");
          if (!fresh) { location.reload(); return; }
          if (fresh.innerHTML !== region.innerHTML) {
            region.innerHTML = fresh.innerHTML;
            bindCopy(region);
          }
          var caption = document.getElementById("poll-caption");
          if (caption) caption.textContent = "Updated just now · auto-refresh";
        })
        .catch(function () {
          failures += 1;
          var caption = document.getElementById("poll-caption");
          if (caption && failures >= 3) {
            caption.textContent = "Lost contact with the QC service — retrying.";
          }
        });
    }, pollSeconds * 1000);
  }

  /* ---- copy affordances ---- */
  function bindCopy(root) {
    (root || document).querySelectorAll(".copy").forEach(function (button) {
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(button.getAttribute("data-copy") || "");
        var previous = button.textContent;
        button.textContent = "✓";
        setTimeout(function () { button.textContent = previous; }, 1500);
      });
    });
  }
  bindCopy(document);

  /* ---- submit page: remembered requested_by ---- */
  var requestedBy = document.getElementById("requested_by");
  if (requestedBy) {
    if (!requestedBy.value) {
      requestedBy.value = localStorage.getItem("qc_requested_by") || "";
    }
    requestedBy.addEventListener("change", function () {
      localStorage.setItem("qc_requested_by", requestedBy.value);
    });
  }

  /* ---- submit page: path validate-on-blur ---- */
  var pathInput = document.getElementById("input_path");
  var pathCheck = document.getElementById("path-check");
  if (pathInput && pathCheck) {
    pathInput.addEventListener("blur", function () {
      if (!pathInput.value.trim()) { pathCheck.textContent = ""; return; }
      fetch("/api/v1/validate-path?path=" + encodeURIComponent(pathInput.value))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            var gb = data.size_bytes / (1024 * 1024 * 1024);
            var size = gb >= 1 ? gb.toFixed(1) + " GB"
                               : (data.size_bytes / (1024 * 1024)).toFixed(1) + " MB";
            pathCheck.className = "field-check mono";
            pathCheck.textContent = "✓ " + size + " · found · readable";
          } else {
            pathCheck.className = "field-check mono bad";
            pathCheck.textContent = "✕ " + data.message;
          }
        });
    });
  }

  /* ---- submit page: preset summary card ---- */
  var presetSelect = document.getElementById("preset");
  if (presetSelect) {
    var card = document.getElementById("preset-card");
    var update = function () {
      var option = presetSelect.selectedOptions[0];
      if (!option || !option.value) { card.hidden = true; return; }
      card.hidden = false;
      document.getElementById("preset-card-id").textContent = option.value;
      var status = option.getAttribute("data-status");
      var pill = document.getElementById("preset-card-status");
      pill.innerHTML = '<span class="pill pill-' + status + '">' + status + "</span>";
      document.getElementById("preset-card-meta").textContent =
        option.getAttribute("data-title") + " · " + option.getAttribute("data-content") +
        " · Effective " + option.getAttribute("data-date");
      var caption = document.getElementById("preset-card-caption");
      caption.textContent = status === "draft"
        ? "Draft preset — not approved for delivery decisions."
        : status === "deprecated" ? "Deprecated preset — confirm before use." : "";
    };
    presetSelect.addEventListener("change", update);
    update();
  }

  /* ---- submit page: server-side path browser ---- */
  var browseButton = document.getElementById("browse-button");
  var modal = document.getElementById("browser-modal");
  if (browseButton && modal) {
    var list = document.getElementById("browser-list");
    var crumb = document.getElementById("browser-crumb");
    var load = function (path) {
      fetch("/api/v1/browse?path=" + encodeURIComponent(path || ""))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          crumb.textContent = data.path || "Allowed media locations";
          list.innerHTML = "";
          (data.entries || []).forEach(function (entry) {
            var item = document.createElement("li");
            var name = document.createElement("span");
            name.textContent = (entry.kind === "file" ? "🎞 " : "📁 ") + entry.name;
            item.appendChild(name);
            if (entry.kind === "file" && entry.size_bytes != null) {
              var size = document.createElement("span");
              size.className = "dim mono";
              size.textContent = (entry.size_bytes / (1024 * 1024)).toFixed(1) + " MB";
              item.appendChild(size);
            }
            item.addEventListener("click", function () {
              if (entry.kind === "file") {
                pathInput.value = entry.path;
                modal.close();
                pathInput.dispatchEvent(new Event("blur"));
              } else {
                load(entry.path);
              }
            });
            list.appendChild(item);
          });
        });
    };
    browseButton.addEventListener("click", function () { load(""); modal.showModal(); });
    document.getElementById("browser-close")
      .addEventListener("click", function () { modal.close(); });
  }

  /* ---- header health dot ---- */
  var dot = document.getElementById("health-dot");
  if (dot) {
    fetch("/api/v1/health").then(function (r) { return r.json(); }).then(function (h) {
      dot.title = "Service ok · queue depth " + h.queue_depth;
    }).catch(function () { dot.classList.add("down"); dot.title = "Service unreachable"; });
  }
})();
