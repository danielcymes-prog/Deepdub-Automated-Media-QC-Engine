/* Behavioural tests for static/app.js, run in jsdom.
 *
 * tests/unit/test_server_interaction_contract.py asserts the *shape* of this
 * code (no inline handlers, rows keyed by id, visibility gating present). That
 * is cheap and runs everywhere, but it cannot prove the property that actually
 * matters: that a focused control survives a poll. Only executing the script
 * against a DOM can do that.
 *
 * Scope is deliberately narrow — the polling and confirmation logic. Anything
 * requiring layout or real paint belongs in a browser test, not here.
 *
 * See ADR-023. Runs in CI via tests/integration/test_console_behaviour.py;
 * locally: `make js-tests`.
 */
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_JS = resolve(HERE, "../../src/deepdub_qc/server/static/app.js");
const source = readFileSync(APP_JS, "utf8");

const POLL_MS = 2000;
const CAPTION_MS = 1000;

let passed = 0;
const failures = [];

function ok(name, condition, detail = "") {
  if (condition) {
    passed += 1;
    console.log(`  ok   ${name}`);
  } else {
    failures.push(name);
    console.log(`  FAIL ${name}${detail ? `  → ${detail}` : ""}`);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

/** Boot app.js against a document, with timers and fetch under our control. */
function boot(html, { respondWith, url = "http://localhost/jobs" } = {}) {
  const dom = new JSDOM(html, { runScripts: "outside-only", url });
  const w = dom.window;

  let visibility = "visible";
  Object.defineProperty(w.document, "visibilityState", { get: () => visibility });

  let fetchCount = 0;
  w.fetch = () => {
    fetchCount += 1;
    return respondWith();
  };
  w.navigator.clipboard = { writeText: () => {} };

  const timers = [];
  w.setInterval = (fn, ms) => timers.push({ fn, ms });
  w.clearInterval = () => {};

  w.eval(source);

  const settle = async () => {
    // two microtask drains: fetch().then().then()
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
  };

  return {
    window: w,
    settle,
    get fetchCount() {
      return fetchCount;
    },
    setVisibility(value) {
      visibility = value;
    },
    async poll() {
      timers.filter((t) => t.ms === POLL_MS).forEach((t) => t.fn());
      await settle();
    },
    tickCaption() {
      timers.filter((t) => t.ms === CAPTION_MS).forEach((t) => t.fn());
    },
    async becomeVisible() {
      visibility = "visible";
      w.document.dispatchEvent(new w.Event("visibilitychange"));
      await settle();
    },
  };
}

const respond = (html) => () =>
  Promise.resolve({ ok: true, text: () => Promise.resolve(html) });
const reject = () => () => Promise.reject(new Error("network down"));

// ---------------------------------------------------------------- fixtures

function jobRow(id, state, verdict) {
  return `<tr data-job-id="${id}">
    <td class="mono"><a class="row-link" href="/jobs/${id}">${id}…</a></td>
    <td>media-${id}.mov</td><td class="mono">preset@1</td><td>operator</td>
    <td data-cell="state">${state}</td>
    <td data-cell="verdict">${verdict}</td>
    <td class="row-chevron">›</td></tr>`;
}

function jobsPage(rows) {
  return `<!DOCTYPE html><html><body>
    <div id="jobs-region" data-poll="/jobs?page=1">
      <table class="data-table rows-linked"><tbody>${rows}</tbody></table>
      <div class="table-foot">
        <nav class="pagination"><span class="page-current">1</span></nav>
        <span class="poll-caption" id="poll-caption" data-poll-caption>Updated just now</span>
      </div>
    </div></body></html>`;
}

function detailPage(stage) {
  return `<!DOCTYPE html><html><body>
    <div id="job-region" data-poll="/jobs/x">
      <ul class="stage-list"><li>stage ${stage}</li></ul>
      <p class="stage-status" role="status" aria-live="polite" data-stage-status
        >Stage ${stage} complete: probe</p>
      <form method="post" action="/jobs/x/cancel" data-confirm="Cancel?">
        <button class="danger-outline">Cancel job</button></form>
    </div></body></html>`;
}

// ------------------------------------------------------------------- tests

section("A focused row link survives a poll that changes the row");
{
  const app = boot(jobsPage(jobRow("aaa", "<span>Queued</span>", "—")), {
    respondWith: respond(jobsPage(jobRow("aaa", "<span>Running</span>", "—"))),
  });
  const doc = app.window.document;
  const link = doc.querySelector(".row-link");
  link.focus();
  ok("link holds focus before the poll", doc.activeElement === link);

  await app.poll();
  ok(
    "the volatile cell was updated",
    doc.querySelector('[data-cell="state"]').textContent.includes("Running"),
  );
  ok(
    "focus is still on the same element",
    doc.activeElement === link,
    `activeElement=${doc.activeElement.tagName}.${doc.activeElement.className}`,
  );
  ok("the focused node was never recreated", doc.querySelector(".row-link") === link);
}

section("Rows are reconciled by job id, not rebuilt");
{
  const app = boot(jobsPage(jobRow("aaa", "<span>Running</span>", "—")), {
    respondWith: respond(
      jobsPage(
        jobRow("aaa", "<span>Done</span>", "PASS") + jobRow("bbb", "<span>Queued</span>", "—"),
      ),
    ),
  });
  const doc = app.window.document;
  const original = doc.querySelector('[data-job-id="aaa"]');

  await app.poll();
  ok("the existing row is the same node", doc.querySelector('[data-job-id="aaa"]') === original);
  ok("a newly queued job is appended", !!doc.querySelector('[data-job-id="bbb"]'));
  ok(
    "its verdict cell was patched",
    original.querySelector('[data-cell="verdict"]').textContent.includes("PASS"),
  );
  ok(
    "the changed cell is flagged for the flash animation",
    original.querySelector('[data-cell="verdict"]').classList.contains("flash"),
  );
}

section("Rows that leave the page are removed");
{
  const app = boot(
    jobsPage(
      jobRow("aaa", "<span>Done</span>", "PASS") + jobRow("bbb", "<span>Queued</span>", "—"),
    ),
    { respondWith: respond(jobsPage(jobRow("bbb", "<span>Queued</span>", "—"))) },
  );
  const doc = app.window.document;
  await app.poll();
  ok("the departed row is gone", !doc.querySelector('[data-job-id="aaa"]'));
  ok("the remaining row is untouched", !!doc.querySelector('[data-job-id="bbb"]'));
}

section("Polling pauses while the window is hidden");
{
  const app = boot(jobsPage(jobRow("aaa", "<span>Queued</span>", "—")), {
    respondWith: respond(jobsPage(jobRow("aaa", "<span>Queued</span>", "—"))),
  });
  await app.poll();
  ok("polls while visible", app.fetchCount === 1, `fetchCount=${app.fetchCount}`);

  app.setVisibility("hidden");
  await app.poll();
  await app.poll();
  ok("does not poll while hidden", app.fetchCount === 1, `fetchCount=${app.fetchCount}`);

  app.tickCaption();
  const caption = app.window.document.getElementById("poll-caption");
  ok("the caption says it is paused", /paused/i.test(caption.textContent), caption.textContent);

  await app.becomeVisible();
  ok("catches up as soon as it is visible", app.fetchCount === 2, `fetchCount=${app.fetchCount}`);
}

section("A stalled service is reported on the first failure");
{
  const app = boot(jobsPage(jobRow("aaa", "<span>Queued</span>", "—")), {
    respondWith: reject(),
  });
  await app.poll();
  const caption = app.window.document.getElementById("poll-caption");
  ok("caption reports lost contact", /no contact/i.test(caption.textContent), caption.textContent);
  ok("caption is marked stale for styling", caption.classList.contains("stale"));
}

section("data-confirm gates destructive submissions");
{
  const app = boot(
    `<!DOCTYPE html><html><body><form id="f" method="post" action="/cancel"
       data-confirm="Really   cancel
       this job?"><button>Cancel job</button></form></body></html>`,
    { respondWith: respond("") },
  );
  const w = app.window;
  const form = w.document.getElementById("f");

  let asked = null;
  w.confirm = (message) => {
    asked = message;
    return false;
  };
  const declined = new w.Event("submit", { bubbles: true, cancelable: true });
  form.dispatchEvent(declined);
  ok("confirm() is called", asked !== null);
  ok(
    "the message is whitespace-collapsed",
    asked === "Really cancel this job?",
    JSON.stringify(asked),
  );
  ok("declining blocks the submit", declined.defaultPrevented);

  w.confirm = () => true;
  const accepted = new w.Event("submit", { bubbles: true, cancelable: true });
  form.dispatchEvent(accepted);
  ok("accepting lets it through", !accepted.defaultPrevented);
}

section("Stage progress announces without re-reading history");
{
  const app = boot(detailPage(1), { respondWith: respond(detailPage(2)) });
  const doc = app.window.document;
  const liveRegion = doc.querySelector("[data-stage-status]");
  const cancel = doc.querySelector("button.danger-outline");

  cancel.focus();
  ok("cancel button holds focus before the poll", doc.activeElement === cancel);

  await app.poll();
  ok(
    "the live region element is preserved, so the update is announced",
    doc.querySelector("[data-stage-status]") === liveRegion,
  );
  ok("its text advanced", /Stage 2/.test(liveRegion.textContent), liveRegion.textContent);
  ok(
    "the Cancel button kept focus through the poll",
    doc.activeElement === cancel,
    `activeElement=${doc.activeElement.tagName}.${doc.activeElement.className}`,
  );
  ok(
    "the stage list around it still updated",
    /stage 2/.test(doc.querySelector(".stage-list").textContent),
  );
}

// ------------------------------------------- regressions from the 2026-07 review

section("A new job is inserted at its server position, not appended");
{
  // The list is newest-first: a job submitted by another operator arrives at
  // the TOP of the fresh response and must land there, not under older rows.
  const app = boot(jobsPage(jobRow("bbb", "<span>Queued</span>", "—")), {
    respondWith: respond(
      jobsPage(
        jobRow("aaa", "<span>Queued</span>", "—") + jobRow("bbb", "<span>Queued</span>", "—"),
      ),
    ),
  });
  const doc = app.window.document;
  await app.poll();
  const ids = Array.from(doc.querySelectorAll("[data-job-id]")).map((r) =>
    r.getAttribute("data-job-id"),
  );
  ok(
    "the newest job is the first row",
    ids.join(",") === "aaa,bbb",
    `order=${ids.join(",")}`,
  );
}

function detailWithCopy(stage, confirm = "Cancel?") {
  return `<!DOCTYPE html><html><body>
    <div id="job-region" data-poll="/jobs/x">
      <div class="hero"><button type="button" class="icon-button copy"
        data-copy="/media/x.mov">⧉</button></div>
      <ul class="stage-list"><li>stage ${stage}</li></ul>
      <p class="stage-status" role="status" aria-live="polite" data-stage-status
        >Stage ${stage} complete: probe</p>
      <form method="post" action="/jobs/x/cancel" data-confirm="${confirm}">
        <button class="danger-outline">Cancel job</button></form>
    </div></body></html>`;
}

section("Copy handlers do not stack across focus-preserving polls");
{
  let stage = 1;
  const app = boot(detailWithCopy(1), {
    respondWith: () => {
      stage += 1;
      return Promise.resolve({ ok: true, text: () => Promise.resolve(detailWithCopy(stage)) });
    },
  });
  const w = app.window;
  const doc = w.document;
  let writes = 0;
  w.navigator.clipboard = { writeText: () => { writes += 1; } };
  w.setTimeout = () => {};

  const copy = doc.querySelector(".copy");
  doc.querySelector("button.danger-outline").focus(); // forces partial patches
  await app.poll();
  await app.poll();
  ok("the copy button survived the patches", doc.querySelector(".copy") === copy);

  copy.click();
  ok("one click writes the clipboard exactly once", writes === 1, `writes=${writes}`);
  ok("the button shows the checkmark", copy.textContent === "✓");
  copy.click();
  ok("a second click writes exactly once more", writes === 2, `writes=${writes}`);
}

section("A focused form's confirmation text follows the fresh markup");
{
  const app = boot(detailWithCopy(1, "Cancel stage 1?"), {
    respondWith: respond(detailWithCopy(2, "Cancel stage 2?")),
  });
  const doc = app.window.document;
  const cancel = doc.querySelector("button.danger-outline");
  cancel.focus();
  await app.poll();
  ok(
    "data-confirm was synced despite focus inside the form",
    doc.querySelector("form").getAttribute("data-confirm") === "Cancel stage 2?",
    doc.querySelector("form").getAttribute("data-confirm"),
  );
  ok("focus survived the attribute sync", doc.activeElement === cancel);
}

function pendingPage() {
  return `<!DOCTYPE html><html><body>
    <div id="job-region" data-poll="/jobs/x">
      <div class="hero"><h1>x.mov</h1></div>
      <p>Queued — position 1 of 1</p>
      <p class="dim">One job runs at a time. This job starts automatically.</p>
      <form method="post" action="/jobs/x/cancel" data-confirm="Cancel queued?">
        <button class="danger-outline" data-requires-js disabled>Cancel job</button></form>
    </div></body></html>`;
}

function runningPage() {
  return `<!DOCTYPE html><html><body>
    <div id="job-region" data-poll="/jobs/x">
      <div class="hero"><h1>x.mov</h1></div>
      <ul class="stage-list"><li>stage 1</li></ul>
      <p class="stage-status" role="status" aria-live="polite" data-stage-status
        >Stage 1 complete: probe</p>
      <form method="post" action="/jobs/x/cancel" data-confirm="Cancel running?">
        <button class="danger-outline" data-requires-js disabled>Cancel job</button></form>
    </div></body></html>`;
}

section("A pending→running transition never splices under held focus");
{
  // Both shapes have four children, so the old equal-count guard passed and
  // index-patching wrote stage text into <p class=dim> — an element with no
  // aria-live plumbing — killing announcements for the rest of the job.
  const app = boot(pendingPage(), { respondWith: respond(runningPage()) });
  const doc = app.window.document;
  const cancel = doc.querySelector("button.danger-outline");
  ok("the JS-gated cancel button was enabled at boot", cancel.disabled === false);

  cancel.focus();
  await app.poll();
  ok(
    "the pending copy is untouched, not spliced",
    doc.querySelector("p.dim").textContent.includes("One job runs"),
    doc.querySelector("p.dim").textContent,
  );
  ok("no half-imported stage list", !doc.querySelector("ul.stage-list"));
  ok("focus never moved", doc.activeElement === cancel);

  cancel.blur();
  await app.poll();
  ok("the page reconciled once focus was released", !!doc.querySelector("ul.stage-list"));
  const live = doc.querySelector("[data-stage-status]");
  ok("the live region arrived with its aria plumbing", !!live && live.getAttribute("role") === "status");
  ok(
    "the replacement gated button was re-enabled",
    doc.querySelector("button.danger-outline").disabled === false,
  );
}

function browserPage() {
  return `<!DOCTYPE html><html><body>
    <input id="input_path">
    <button id="browse-button" type="button">Browse…</button>
    <dialog id="browser-modal">
      <div class="modal-head-left">
        <button id="browser-back" type="button" hidden>‹ Back</button>
        <span id="browser-crumb"></span>
      </div>
      <ul id="browser-list" class="browser-list"></ul>
      <button id="browser-close" type="button">Close</button>
    </dialog></body></html>`;
}

const jsonResponse = (status, data) => ({
  ok: status >= 200 && status < 300,
  status,
  json: () => Promise.resolve(data),
});

section("A failed browse renders an error and leaves history untouched");
{
  const dirEntry = (name, path) => ({ kind: "dir", name, path });
  const responses = [
    jsonResponse(200, { path: "", entries: [dirEntry("A", "/roots/A")] }),
    jsonResponse(200, { path: "/roots/A", entries: [dirEntry("B", "/roots/A/B")] }),
    jsonResponse(404, { error: "not found" }),
    jsonResponse(200, { path: "", entries: [dirEntry("A", "/roots/A")] }),
  ];
  const app = boot(browserPage(), {
    respondWith: () => Promise.resolve(responses.shift()),
  });
  const doc = app.window.document;
  const modal = doc.getElementById("browser-modal");
  modal.showModal = () => {};
  modal.close = () => {};
  const crumb = doc.getElementById("browser-crumb");
  const back = doc.getElementById("browser-back");

  doc.getElementById("browse-button").click();
  await app.settle();
  ok("the root listing renders", crumb.textContent === "Allowed media locations");

  doc.querySelector("#browser-list li").click(); // descend into A — succeeds
  await app.settle();
  ok("descending updates the crumb", crumb.textContent === "/roots/A");
  ok("back appears after a descent", back.hidden === false);

  doc.querySelector("#browser-list li").click(); // descend into B — 404s
  await app.settle();
  ok(
    "the failure is shown as an error, not an empty folder",
    /not found/.test(doc.querySelector("#browser-list li.browser-error")?.textContent || ""),
    doc.getElementById("browser-list").innerHTML,
  );
  ok("the crumb stays where the operator actually is", crumb.textContent === "/roots/A");

  back.click(); // one press must return to the root — no phantom stack entry
  await app.settle();
  ok("one Back returns to the root", crumb.textContent === "Allowed media locations");
  ok("the stack is empty again, so back hides", back.hidden === true);
}

// ------------------------------------------------------------------ summary

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length) {
  console.log(`\nFailed:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
