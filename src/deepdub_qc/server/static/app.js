/* Deepdub QC Console — polling + copy + path browser + preset card only.
   The GUI displays pipeline output verbatim; nothing here computes QC. */
(function () {
  "use strict";

  /* ---- polling ----
     Refreshes the [data-poll] region from the server every POLL_SECONDS.

     This used to do `region.innerHTML = fresh.innerHTML`, which had three
     defects that only show up in real operator use:

       1. Replacing the subtree moves focus to <body>. On the job detail page
          the polled region *contains the Cancel button*, so an operator who
          tabbed to it lost focus every two seconds and could never activate it
          from the keyboard.
       2. It discarded any text selection in the region — you could not select
          a media path for long enough to copy it.
       3. It re-ran on every byte of difference, so a timestamp ticking over
          rebuilt the whole table.

     Instead: patch only what changed, keyed by data-job-id, and never touch a
     node that contains the focused element unless its text actually differs.
     Cheap because the shape of the page is stable — only chips, badges and
     timestamps move. */
  var POLL_SECONDS = 2;
  var region = document.querySelector("[data-poll]");

  /** Replace `current`'s content with `fresh`'s, preserving focus and caret.
   *  Recurses along the path to the focused element so that a focused control
   *  (in practice: the Cancel button on a running job) is never re-created,
   *  while everything around it still updates. Returns true if anything changed.
   */
  function patchElement(current, fresh) {
    if (current.innerHTML === fresh.innerHTML) { return false; }
    var active = document.activeElement;
    var holdsFocus = active && active !== document.body && current.contains(active);
    if (!holdsFocus) {
      current.innerHTML = fresh.innerHTML;
      return true;
    }
    /* Structure changed under the focused node — nothing safe to do positionally,
       so leave it; the next poll after focus moves will reconcile it. */
    if (current.children.length !== fresh.children.length) { return false; }
    var changed = false;
    Array.prototype.forEach.call(current.children, function (child, i) {
      var other = fresh.children[i];
      if (!other || child.innerHTML === other.innerHTML) { return; }
      if (child.contains(active)) {
        if (patchElement(child, other)) { changed = true; }
      } else {
        child.innerHTML = other.innerHTML;
        changed = true;
      }
    });
    return changed;
  }

  /** Update an aria-live region's text in place.
   *  The node itself must survive: replacing a live region element (rather than
   *  mutating its contents) is unreliably announced across screen readers. */
  function patchLiveRegions(current, fresh) {
    current.querySelectorAll("[data-stage-status]").forEach(function (node) {
      var other = fresh.querySelector("[data-stage-status]");
      if (!other) { return; }
      var text = other.textContent.trim();
      if (node.textContent.trim() !== text) { node.textContent = text; }
    });
  }

  /** Reconcile the jobs table body by data-job-id: patch shared rows in place,
   *  append new jobs, drop finished ones. Keeps focus and row identity. */
  function patchRows(currentBody, freshBody) {
    var changed = false;
    var freshRows = {};
    var order = [];
    Array.prototype.forEach.call(freshBody.rows, function (row) {
      var id = row.getAttribute("data-job-id");
      if (id) { freshRows[id] = row; order.push(id); }
    });

    Array.prototype.slice.call(currentBody.rows).forEach(function (row) {
      var id = row.getAttribute("data-job-id");
      if (!id) { return; }
      if (!freshRows[id]) { row.remove(); changed = true; return; }
      /* Only the state and verdict cells are volatile; the id, filename, preset
         and requester are fixed for the life of a job. Patching just those two
         means a hovered badge or a focused row link is never disturbed. */
      ["state", "verdict"].forEach(function (name) {
        var mine = row.querySelector('[data-cell="' + name + '"]');
        var theirs = freshRows[id].querySelector('[data-cell="' + name + '"]');
        if (mine && theirs && mine.innerHTML !== theirs.innerHTML) {
          mine.innerHTML = theirs.innerHTML;
          mine.classList.remove("flash");
          void mine.offsetWidth;  /* restart the CSS animation */
          mine.classList.add("flash");
          changed = true;
        }
      });
      delete freshRows[id];
    });

    order.forEach(function (id) {
      if (freshRows[id]) { currentBody.appendChild(freshRows[id]); changed = true; }
    });
    return changed;
  }

  if (region) {
    var url = region.getAttribute("data-poll");
    var lastSuccess = Date.now();
    var stale = false;
    var caption = region.querySelector("[data-poll-caption]")
      || document.querySelector("[data-poll-caption]");

    /* Honest freshness: derived from the last successful response, not asserted.
       Degrades on the FIRST failure — a frozen queue must never read as a quiet
       one, which is exactly the mistake an operator would act on. */
    function renderCaption() {
      if (!caption) { return; }
      var age = Math.round((Date.now() - lastSuccess) / 1000);
      caption.classList.toggle("stale", stale);
      if (stale) {
        caption.textContent =
          "No contact with the QC service for " + age + "s — retrying";
      } else if (document.visibilityState === "hidden") {
        caption.textContent = "Paused — updates resume when this window is active";
      } else {
        caption.textContent = age < 5 ? "Updated just now" : "Updated " + age + "s ago";
      }
    }

    function poll() {
      /* Skip while hidden: a minimised RDP session was still forcing a full
         server-side page render every 2s for every connected operator. */
      if (document.visibilityState === "hidden") { return; }
      fetch(url, { headers: { "X-Requested-With": "poll" } })
        .then(function (r) {
          if (!r.ok) { throw new Error("HTTP " + r.status); }
          return r.text();
        })
        .then(function (html) {
          lastSuccess = Date.now();
          stale = false;
          var doc = new DOMParser().parseFromString(html, "text/html");
          var fresh = doc.querySelector("[data-poll]");
          /* No region in the response means the page shape changed underneath us
             (job finished, session capped, redirect) — a reload is correct. */
          if (!fresh) { location.reload(); return; }

          /* Live regions first, and always in place, so the announcement fires
             even when the surrounding markup is otherwise untouched. */
          patchLiveRegions(region, fresh);

          var currentBody = region.querySelector("tbody");
          var freshBody = fresh.querySelector("tbody");
          var touched;
          if (currentBody && freshBody) {
            touched = patchRows(currentBody, freshBody);
            var currentFoot = region.querySelector(".table-foot .pagination");
            var freshFoot = fresh.querySelector(".table-foot .pagination");
            if (currentFoot && freshFoot) { patchElement(currentFoot, freshFoot); }
          } else {
            touched = patchElement(region, fresh);
          }
          if (touched) { bindCopy(region); }
          renderCaption();
        })
        .catch(function () {
          stale = true;
          renderCaption();
        });
    }

    var timer = setInterval(poll, POLL_SECONDS * 1000);
    /* Tick the caption every second so the displayed age stays truthful even
       between polls, and catch up immediately when the window regains focus. */
    setInterval(renderCaption, 1000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") { poll(); }
      renderCaption();
    });
    window.addEventListener("pagehide", function () { clearInterval(timer); });
  }

  /* ---- destructive-action confirmation ----
     Replaces inline `onsubmit="return confirm(…)"`, which any Content-Security-
     Policy blocks outright. Bound by delegation on document, so it also covers
     forms introduced by a poll refresh. Whitespace in the data-confirm attribute
     is collapsed because the templates wrap it across lines for legibility. */
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("form[data-confirm]");
    if (!form) { return; }
    var message = form.getAttribute("data-confirm").replace(/\s+/g, " ").trim();
    if (!window.confirm(message)) { event.preventDefault(); }
  });

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

  /* ---- submit page: server-side path browser ----
     Navigation keeps a history stack so "back" returns to the exact folder the
     operator came from, rather than deriving a parent path (which would have to
     parse POSIX "/", Windows "\" and UNC "\\server\share" roots differently).
     The stack holds ancestor locations only; "" is the allowed-locations root
     list, which the modal always opens on, so back naturally bottoms out there
     and the button hides. The server re-checks the media-root sandbox on every
     /browse call, so nothing here can navigate outside the allowed roots. */
  var browseButton = document.getElementById("browse-button");
  var modal = document.getElementById("browser-modal");
  if (browseButton && modal) {
    var list = document.getElementById("browser-list");
    var crumb = document.getElementById("browser-crumb");
    var backButton = document.getElementById("browser-back");
    var pathStack = [];
    var currentPath = null;

    var render = function (data) {
      crumb.textContent = data.path || "Allowed media locations";
      backButton.hidden = pathStack.length === 0;
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
            navigate(entry.path, false);
          }
        });
        list.appendChild(item);
      });
    };

    /* `isBack` distinguishes a descent (push where we were) from a pop (the
       caller has already adjusted the stack), so re-entering a folder forwards
       and stepping back stay symmetric. */
    var navigate = function (path, isBack) {
      fetch("/api/v1/browse?path=" + encodeURIComponent(path || ""))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!isBack && currentPath !== null) { pathStack.push(currentPath); }
          currentPath = path || "";
          render(data);
        });
    };

    backButton.addEventListener("click", function () {
      if (!pathStack.length) { return; }
      navigate(pathStack.pop(), true);
    });

    browseButton.addEventListener("click", function () {
      pathStack = [];
      currentPath = null;
      navigate("", false);
      modal.showModal();
    });
    document.getElementById("browser-close")
      .addEventListener("click", function () { modal.close(); });
  }

  /* ---- header health indicator ----
     The coloured dot is a CSS ::before pseudo-element; the inner <span> carries
     the text label so the status is not conveyed by colour alone. Only the
     label text and the .down class are touched here. */
  var health = document.getElementById("health-dot");
  if (health) {
    var healthLabel = health.querySelector("span");
    var setHealth = function (down, label, title) {
      health.classList.toggle("down", down);
      health.title = title;
      if (healthLabel) { healthLabel.textContent = label; }
    };
    fetch("/api/v1/health").then(function (r) { return r.json(); }).then(function (h) {
      var depth = h.queue_depth;
      setHealth(
        false,
        depth ? "Queue " + depth : "Service up",
        "QC service ok · queue depth " + depth
      );
    }).catch(function () {
      setHealth(true, "Service down", "QC service unreachable");
    });
  }
})();
