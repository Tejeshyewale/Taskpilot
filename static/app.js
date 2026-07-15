// ============================================================
// TaskPilot — Frontend logic
// ============================================================

const API = "/api";
let currentThreadId = null;
let currentWS = null;
let authToken = localStorage.getItem("taskpilot_token") || null;
let currentUser = null; // {email, name} or null (guest)

// ---------- Utility ----------

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return document.querySelectorAll(sel); }

function showStage(id) {
  $all(".stage").forEach(s => s.classList.add("hidden"));
  $(id).classList.remove("hidden");
}

function showError(message) {
  $("#errorText").textContent = message;
  $("#errorBanner").classList.remove("hidden");
}
$("#dismissError").addEventListener("click", () => $("#errorBanner").classList.add("hidden"));

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function authHeaders() {
  return authToken ? { "Authorization": `Bearer ${authToken}` } : {};
}

// Minimal, safe markdown -> HTML (headers + paragraphs only — enough for our reports)
function renderMarkdown(text) {
  const escaped = escapeHtml(text);
  const lines = escaped.split("\n");
  let html = "";
  let paraBuffer = [];

  const flushPara = () => {
    if (paraBuffer.length) {
      html += `<p>${paraBuffer.join(" ")}</p>`;
      paraBuffer = [];
    }
  };

  for (const line of lines) {
    const h3 = line.match(/^###\s+(.*)/);
    const h2 = line.match(/^##\s+(.*)/);
    const h1 = line.match(/^#\s+(.*)/);
    if (h3) { flushPara(); html += `<h3>${h3[1]}</h3>`; }
    else if (h2) { flushPara(); html += `<h2>${h2[1]}</h2>`; }
    else if (h1) { flushPara(); html += `<h1>${h1[1]}</h1>`; }
    else if (line.trim() === "") { flushPara(); }
    else { paraBuffer.push(line.trim()); }
  }
  flushPara();
  return html;
}

// ============================================================
// Auth
// ============================================================

function showAuthGate() { $("#authGate").classList.remove("hidden"); $("#appShell").classList.add("hidden"); }
function showApp() {
  $("#authGate").classList.add("hidden");
  $("#appShell").classList.remove("hidden");
  updateUserChip();
  checkHealth();
  loadHistory();
}

function updateUserChip() {
  $("#userChipName").textContent = currentUser ? (currentUser.name || currentUser.email) : "Guest (not logged in)";
}

$("#tabLogin").addEventListener("click", () => {
  $("#tabLogin").classList.add("active"); $("#tabSignup").classList.remove("active");
  $("#loginForm").classList.remove("hidden"); $("#signupForm").classList.add("hidden");
});
$("#tabSignup").addEventListener("click", () => {
  $("#tabSignup").classList.add("active"); $("#tabLogin").classList.remove("active");
  $("#signupForm").classList.remove("hidden"); $("#loginForm").classList.add("hidden");
});

function showAuthError(msg) {
  $("#authError").textContent = msg;
  $("#authError").classList.remove("hidden");
}

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#authError").classList.add("hidden");
  try {
    const resp = await fetch(`${API}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("#loginEmail").value, password: $("#loginPassword").value }),
    });
    const data = await resp.json();
    if (!resp.ok) { showAuthError(data.detail || "Login failed."); return; }
    authToken = data.token; currentUser = data.user;
    localStorage.setItem("taskpilot_token", authToken);
    showApp();
  } catch { showAuthError("Could not reach the backend."); }
});

$("#signupForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#authError").classList.add("hidden");
  try {
    const resp = await fetch(`${API}/auth/signup`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: $("#signupEmail").value, password: $("#signupPassword").value, name: $("#signupName").value,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) { showAuthError(data.detail || "Signup failed."); return; }
    authToken = data.token; currentUser = data.user;
    localStorage.setItem("taskpilot_token", authToken);
    showApp();
  } catch { showAuthError("Could not reach the backend."); }
});

$("#skipAuthBtn").addEventListener("click", () => { currentUser = null; showApp(); });

$("#logoutBtn").addEventListener("click", async () => {
  if (authToken) {
    try { await fetch(`${API}/auth/logout`, { method: "POST", headers: authHeaders() }); } catch {}
  }
  authToken = null; currentUser = null;
  localStorage.removeItem("taskpilot_token");
  showAuthGate();
});

async function tryRestoreSession() {
  if (!authToken) { showAuthGate(); return; }
  try {
    const resp = await fetch(`${API}/auth/me`, { headers: authHeaders() });
    if (resp.ok) { currentUser = await resp.json(); showApp(); return; }
  } catch {}
  authToken = null;
  localStorage.removeItem("taskpilot_token");
  showAuthGate();
}

// ============================================================
// Theme toggle
// ============================================================

function applyTheme(theme) {
  document.body.setAttribute("data-theme", theme);
  $("#themeIcon").textContent = theme === "light" ? "☀" : "☾";
  localStorage.setItem("taskpilot_theme", theme);
}
$("#themeToggle").addEventListener("click", () => {
  const current = document.body.getAttribute("data-theme") === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
});
applyTheme(localStorage.getItem("taskpilot_theme") || "dark");

// ---------- Health check ----------

async function checkHealth() {
  try {
    const resp = await fetch(`${API}/health`);
    if (resp.ok) {
      $("#apiStatusDot").classList.add("online");
      $("#apiStatusText").textContent = "Backend connected";
    } else throw new Error();
  } catch {
    $("#apiStatusDot").classList.add("offline");
    $("#apiStatusText").textContent = "Backend unreachable";
  }
}

// ---------- History sidebar ----------

async function loadHistory() {
  try {
    const resp = await fetch(`${API}/tasks/history`, { headers: authHeaders() });
    const items = await resp.json();
    const list = $("#historyList");
    if (!items.length) {
      list.innerHTML = `<div class="history-empty">No reports yet — run your first task.</div>`;
      return;
    }
    list.innerHTML = items.map(item => `
      <div class="history-item" data-thread-id="${item.thread_id}">
        <div class="history-item-goal">${escapeHtml(item.goal)}</div>
        <div class="history-item-date">${item.date_display}${item.feedback ? (item.feedback === "up" ? " · 👍" : " · 👎") : ""}</div>
      </div>
    `).join("");

    $all(".history-item").forEach(el => {
      el.addEventListener("click", () => openHistoryEntry(el.dataset.threadId));
    });
  } catch {
    // silent — sidebar just stays empty if this fails
  }
}

async function openHistoryEntry(threadId) {
  try {
    const resp = await fetch(`${API}/tasks/history/${threadId}`, { headers: authHeaders() });
    if (!resp.ok) throw new Error("Not found");
    const entry = await resp.json();
    currentThreadId = threadId;
    renderComplete(entry.goal, entry.final_report, entry.sources, entry.feedback);
  } catch {
    showError("Could not load that report — it may have been cleared.");
  }
}

// ---------- Stage: Idle / goal input ----------

$("#maxIter").addEventListener("input", (e) => {
  $("#maxIterValue").textContent = e.target.value;
});

$all(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    $("#goalInput").value = chip.textContent;
    $("#goalInput").focus();
  });
});

function resetToIdle() {
  currentThreadId = null;
  if (currentWS) { try { currentWS.close(); } catch {} currentWS = null; }
  $("#goalInput").value = "";
  $("#feedbackInput").value = "";
  showStage("#stageIdle");
}
$("#newTaskBtn").addEventListener("click", resetToIdle);
$("#newTaskBtn2").addEventListener("click", resetToIdle);

$("#startBtn").addEventListener("click", startTask);

function wsUrl(path) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

function startTask() {
  const goal = $("#goalInput").value.trim();
  if (!goal) return;
  const maxIterations = parseInt($("#maxIter").value, 10);
  const language = $("#languageSelect").value;
  const notifyEmail = $("#notifyEmailInput").value.trim();

  $("#runningGoalText").textContent = goal;
  showStage("#stageRunning");
  resetStepper();
  $("#liveTrace").innerHTML = "";

  const ws = new WebSocket(wsUrl("/ws/tasks"));
  currentWS = ws;

  ws.onopen = () => {
    ws.send(JSON.stringify({
      goal, max_iterations: maxIterations, language, notify_email: notifyEmail,
      user_id: currentUser ? currentUser.email : "anonymous",
    }));
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleWsMessage(msg);
  };

  ws.onerror = () => {
    showStage("#stageIdle");
    showError("Could not reach the backend. Is `uvicorn app.main:app` running?");
  };

  ws.onclose = () => { currentWS = null; };
}

function handleWsMessage(msg) {
  if (msg.type === "started") {
    currentThreadId = msg.thread_id;

  } else if (msg.type === "node_update") {
    markStepActive(msg.node);
    appendTraceLine(msg.node, msg.note);

  } else if (msg.type === "waiting_for_human") {
    markStepDone("planner"); markStepDone("research"); markStepDone("critique");
    $("#outlineBox").textContent = msg.draft_outline;
    showStage("#stageReview");

  } else if (msg.type === "complete") {
    renderComplete(msg.goal, msg.final_report, msg.sources, null);

  } else if (msg.type === "error") {
    showStage(currentThreadId ? "#stageReview" : "#stageIdle");
    showError(msg.detail || "Something went wrong.");
  }
}

const STEP_ORDER = ["planner", "research", "critique", "human_review", "compose", "deliver"];
// deliver maps visually onto the "compose" step (last visible stepper node)
const STEP_DISPLAY_MAP = { deliver: "compose" };

function resetStepper() {
  $all(".step").forEach(s => s.classList.remove("active", "done"));
}
function markStepActive(node) {
  const display = STEP_DISPLAY_MAP[node] || node;
  const el = $(`.step[data-step="${display}"]`);
  if (!el) return;
  $all(".step").forEach(s => s.classList.remove("active"));
  el.classList.add("active");
}
function markStepDone(node) {
  const display = STEP_DISPLAY_MAP[node] || node;
  const el = $(`.step[data-step="${display}"]`);
  if (el) { el.classList.remove("active"); el.classList.add("done"); }
}
function appendTraceLine(node, note) {
  const line = document.createElement("div");
  line.className = "trace-line";
  line.innerHTML = `<span class="tag">[${node}]</span> ${escapeHtml(note || "working…")}`;
  $("#liveTrace").appendChild(line);
  $("#liveTrace").scrollTop = $("#liveTrace").scrollHeight;
}

// ---------- Stage: Human review ----------

$("#approveBtn").addEventListener("click", () => submitReview(true));
$("#rejectBtn").addEventListener("click", () => submitReview(false));

function submitReview(approved) {
  const feedback = $("#feedbackInput").value.trim();
  showStage("#stageRunning");
  $("#runningGoalText").textContent = "Writing the final report…";
  markStepActive("compose");

  if (!currentWS || currentWS.readyState !== WebSocket.OPEN) {
    showError("Connection lost — please start a new task.");
    showStage("#stageIdle");
    return;
  }
  currentWS.send(JSON.stringify({ approved, feedback }));
}

// ---------- Stage: Complete ----------

function renderComplete(goal, reportText, sources, feedback) {
  $("#completeGoalText").textContent = goal;
  $("#reportContent").innerHTML = renderMarkdown(reportText || "");

  const sourcesBox = $("#sourcesBox");
  if (sources && sources.length) {
    sourcesBox.innerHTML = `<h4>Sources</h4>` +
      sources.map(s => `<a href="${s}" target="_blank" rel="noopener">${escapeHtml(s)}</a>`).join("");
  } else {
    sourcesBox.innerHTML = "";
  }

  $("#feedbackUpBtn").classList.toggle("selected", feedback === "up");
  $("#feedbackDownBtn").classList.toggle("selected", feedback === "down");
  $("#feedbackThanks").classList.add("hidden");

  $("#tracePanel").classList.add("hidden");
  showStage("#stageComplete");
  loadHistory();
}

$("#feedbackUpBtn").addEventListener("click", () => submitFeedback("up"));
$("#feedbackDownBtn").addEventListener("click", () => submitFeedback("down"));

async function submitFeedback(rating) {
  if (!currentThreadId) return;
  try {
    await fetch(`${API}/tasks/feedback`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: currentThreadId, rating }),
    });
    $("#feedbackUpBtn").classList.toggle("selected", rating === "up");
    $("#feedbackDownBtn").classList.toggle("selected", rating === "down");
    $("#feedbackThanks").classList.remove("hidden");
    loadHistory();
  } catch {
    showError("Could not save feedback.");
  }
}

$("#exportPdfBtn").addEventListener("click", () => downloadExport("pdf"));
$("#exportDocxBtn").addEventListener("click", () => downloadExport("docx"));

function downloadExport(format) {
  if (!currentThreadId) return;
  window.open(`${API}/tasks/${currentThreadId}/export?format=${format}`, "_blank");
}

$("#viewTraceBtn").addEventListener("click", async () => {
  const panel = $("#tracePanel");
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) {
    try {
      const resp = await fetch(`${API}/trace`);
      const entries = await resp.json();
      $("#traceLog").innerHTML = entries.map(e =>
        `<div>[${e.node}] ${e.trace_note || ""} <span style="color:var(--text-muted)">(${e.elapsed_sec}s)</span></div>`
      ).join("");
    } catch {
      $("#traceLog").textContent = "Could not load trace.";
    }
  }
});

// ---------- Quick Web Search panel ----------

$("#quickSearchToggle").addEventListener("click", () => {
  $("#quickSearchOverlay").classList.add("visible");
  $("#quickSearchInput").focus();
});
$("#closeQuickSearch").addEventListener("click", () => {
  $("#quickSearchOverlay").classList.remove("visible");
});
$("#quickSearchOverlay").addEventListener("click", (e) => {
  if (e.target.id === "quickSearchOverlay") $("#quickSearchOverlay").classList.remove("visible");
});

$("#quickSearchBtn").addEventListener("click", runQuickSearch);
$("#quickSearchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runQuickSearch();
});

async function runQuickSearch() {
  const query = $("#quickSearchInput").value.trim();
  if (!query) return;
  const resultBox = $("#quickSearchResult");
  resultBox.innerHTML = `<div class="loading">Searching the web…</div>`;

  try {
    const resp = await fetch(`${API}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      resultBox.innerHTML = `<div style="color:var(--danger)">${escapeHtml(err.detail || "Search failed")}</div>`;
      return;
    }
    const data = await resp.json();
    resultBox.innerHTML = `
      <div style="margin-bottom:10px;">${escapeHtml(data.content)}</div>
      ${data.source ? `<a href="${data.source}" target="_blank" rel="noopener">${escapeHtml(data.source)}</a>` : ""}
    `;
  } catch {
    resultBox.innerHTML = `<div style="color:var(--danger)">Could not reach the backend.</div>`;
  }
}

// ---------- Compare / Battle Mode panel ----------

$("#compareToggle").addEventListener("click", () => {
  $("#compareOverlay").classList.add("visible");
  $("#compareInputA").focus();
});
$("#closeCompare").addEventListener("click", () => {
  $("#compareOverlay").classList.remove("visible");
});
$("#compareOverlay").addEventListener("click", (e) => {
  if (e.target.id === "compareOverlay") $("#compareOverlay").classList.remove("visible");
});

$("#compareBtn").addEventListener("click", runCompare);

async function runCompare() {
  const topicA = $("#compareInputA").value.trim();
  const topicB = $("#compareInputB").value.trim();
  if (!topicA || !topicB) return;
  const resultBox = $("#compareResult");
  resultBox.innerHTML = `<div class="loading">Researching both topics…</div>`;

  try {
    const resp = await fetch(`${API}/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic_a: topicA, topic_b: topicB }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      resultBox.innerHTML = `<div style="color:var(--danger)">${escapeHtml(err.detail || "Compare failed")}</div>`;
      return;
    }
    const data = await resp.json();
    resultBox.innerHTML = renderMarkdown(data.comparison || "");
    if (data.sources && data.sources.length) {
      resultBox.innerHTML += `<div class="sources-box"><h4>Sources</h4>` +
        data.sources.map(s => `<a href="${s}" target="_blank" rel="noopener">${escapeHtml(s)}</a>`).join("") +
        `</div>`;
    }
  } catch {
    resultBox.innerHTML = `<div style="color:var(--danger)">Could not reach the backend.</div>`;
  }
}

// ---------- Init ----------

tryRestoreSession();
