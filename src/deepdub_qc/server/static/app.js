/* Deepdub QC Console — polling + copy + path browser + preset card only.
   The GUI displays pipeline output verbatim; nothing here computes QC. */
(function () {
  "use strict";

  /* ---- destructive-action confirmation (bound FIRST, fail closed) ----
     Replaces inline `onsubmit="return confirm(…)"`, which any Content-Security-
     Policy blocks outright. Bound by delegation on document, so it also covers
     forms introduced by a poll refresh. Whitespace in the data-confirm attribute
     is collapsed because the templates wrap it across lines for legibility.

     Controls marked [data-requires-js] ship disabled in the markup and are only
     enabled here, AFTER the confirmation handler is registered: if this script
     fails to load or dies earlier in this closure, the Cancel button stays
     inert instead of submitting an unconfirmed destructive POST. */
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("form[data-confirm]");
    if (!form) { return; }
    var message = form.getAttribute("data-confirm").replace(/\s+/g, " ").trim();
    if (!window.confirm(message)) { event.preventDefault(); }
  });

  function enableJsGated(root) {
    (root || document).querySelectorAll("[data-requires-js]").forEach(function (control) {
      control.disabled = false;
    });
  }
  enableJsGated(document);

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

  /** Copy `fresh`'s attributes onto `current` without touching its children.
   *  Attribute mutation never moves focus, so this is safe on the focused path
   *  — it is how a focused form's data-confirm text follows a state change. */
  function syncAttributes(current, fresh) {
    var changed = false;
    Array.prototype.slice.call(current.attributes).forEach(function (attr) {
      if (!fresh.hasAttribute(attr.name)) {
        current.removeAttribute(attr.name);
        changed = true;
      }
    });
    Array.prototype.forEach.call(fresh.attributes, function (attr) {
      if (current.getAttribute(attr.name) !== attr.value) {
        current.setAttribute(attr.name, attr.value);
        changed = true;
      }
    });
    return changed;
  }

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
    /* Positional patching is only sound when the page kept its shape: equal
       child counts AND matching tags per index. Equal counts alone once let a
       pending→running transition splice stage text into the wrong elements,
       stripping the live region's aria attributes in the process. When the
       shape changed, leave everything; the poll after focus moves reconciles. */
    if (current.children.length !== fresh.children.length) { return false; }
    var sameShape = Array.prototype.every.call(current.children, function (child, i) {
      return child.tagName === fresh.children[i].tagName;
    });
    if (!sameShape) { return false; }
    var changed = false;
    Array.prototype.forEach.call(current.children, function (child, i) {
      var other = fresh.children[i];
      if (child.outerHTML === other.outerHTML) { return; }
      /* Attributes first (safe even on the focused path), then content:
         recursing toward the focused element, plain innerHTML off it. Nodes
         are never swapped out, so live regions and the focused control keep
         their identity. */
      if (syncAttributes(child, other)) { changed = true; }
      if (child.innerHTML === other.innerHTML) { return; }
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
   *  insert new jobs at their server-ordered position, drop finished ones.
   *  Keeps focus and row identity. */
  function patchRows(currentBody, freshBody) {
    var changed = false;
    var freshRows = {};
    var order = [];
    Array.prototype.forEach.call(freshBody.rows, function (row) {
      var id = row.getAttribute("data-job-id");
      if (id) { freshRows[id] = row; order.push(id); }
    });

    var currentRows = {};
    Array.prototype.slice.call(currentBody.rows).forEach(function (row) {
      var id = row.getAttribute("data-job-id");
      if (!id) { return; }
      if (!freshRows[id]) { row.remove(); changed = true; return; }
      currentRows[id] = row;
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
    });

    /* Walk the server's order with a cursor so an unseen row lands where the
       server put it. The list is newest-first: a plain appendChild used to
       file another operator's brand-new job at the bottom, under older jobs. */
    var previous = null;
    order.forEach(function (id) {
      var row = currentRows[id];
      if (!row) {
        row = freshRows[id];
        currentBody.insertBefore(row, previous ? previous.nextSibling : currentBody.firstChild);
        changed = true;
      }
      previous = row;
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
          /* Fresh markup arrives with [data-requires-js] controls disabled
             (fail-closed default); re-enable them now that they are guarded.
             Copy buttons need nothing: their click handler is delegated. */
          if (touched) { enableJsGated(region); }
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

  /* ---- copy affordances ----
     Delegated, like the confirmation handler: per-button addEventListener
     stacked one duplicate listener per poll tick onto buttons that survived a
     focus-preserving patch, so one click wrote the clipboard N times and the
     N-th restore captured "✓" as the label to restore to. Delegation binds
     once, covers poll-introduced buttons, and cannot stack. */
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".copy");
    if (!button) { return; }
    navigator.clipboard.writeText(button.getAttribute("data-copy") || "");
    /* Remember the resting label across rapid clicks so the restore can never
       capture the transient checkmark. */
    if (!button.dataset.copyLabel) { button.dataset.copyLabel = button.textContent; }
    button.textContent = "✓";
    setTimeout(function () {
      button.textContent = button.dataset.copyLabel || button.textContent;
      delete button.dataset.copyLabel;
    }, 1500);
  });

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

    /* A failed navigation must not masquerade as an empty folder: /browse
       returns {"error": …} with a non-2xx status for a deleted, forbidden or
       non-directory path, and rendering that as zero entries (plus a stack
       push for a folder we never entered) left the operator with a blank
       listing and a Back button that needed an extra press. Show the error in
       the list and stay exactly where we were. */
    var renderError = function (message) {
      list.innerHTML = "";
      var item = document.createElement("li");
      item.className = "browser-error";
      item.textContent = "⚠ " + message;
      list.appendChild(item);
    };

    /* `isBack` distinguishes a descent (push where we were) from a pop (the
       caller has already adjusted the stack), so re-entering a folder forwards
       and stepping back stay symmetric. */
    var navigate = function (path, isBack) {
      fetch("/api/v1/browse?path=" + encodeURIComponent(path || ""))
        .then(function (r) {
          return r.json().then(function (data) {
            if (!r.ok) { throw new Error(data.error || "HTTP " + r.status); }
            return data;
          });
        })
        .then(function (data) {
          /* The stack only moves on success, so a failed navigation — forward
             or back — leaves both the crumb and the history exactly as they
             were. */
          if (isBack) {
            pathStack.pop();
          } else if (currentPath !== null) {
            pathStack.push(currentPath);
          }
          currentPath = path || "";
          render(data);
        })
        .catch(function (error) {
          renderError(error.message || "Could not open this location");
        });
    };

    backButton.addEventListener("click", function () {
      if (!pathStack.length) { return; }
      navigate(pathStack[pathStack.length - 1], true);
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
