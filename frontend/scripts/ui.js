// frontend/scripts/ui.js
// Pure DOM rendering — no API calls, no state mutations.

const UI = (() => {
  // Elements
  const messagesWrap  = document.getElementById("messages-wrap");
  const chatListEl    = document.getElementById("chat-list");
  const trackerGrid   = document.getElementById("tracker-grid");
  const statDone      = document.getElementById("stat-done");
  const statFail      = document.getElementById("stat-fail");
  const statPend      = document.getElementById("stat-pend");
  const streakEl      = document.getElementById("tp-streak");
  const notifList     = document.getElementById("notif-list");
  const npEmpty       = document.getElementById("np-empty");
  const notifDot      = document.getElementById("notif-dot");
  const fileBadge     = document.getElementById("file-badge");
  const fileNameEl    = document.getElementById("file-name");
  const envBadge      = document.getElementById("env-badge");

  // ── Markdown rendering ────────────────────────────────────
  function _renderMarkdown(content) {
    if (!content) return "";
    if (window.marked && typeof marked.parse === "function") {
      return marked.parse(content);
    }
    // Minimal fallback
    return content
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/\n/g, "<br>");
  }

  // ── Messages ──────────────────────────────────────────────
  function renderMessages(messages, mode) {
    messagesWrap.innerHTML = "";

    if (!messages || messages.length === 0) {
      messagesWrap.appendChild(_buildEmptyState(mode));
      return;
    }

    messages.forEach(m => {
      const wrap = document.createElement("div");
      wrap.className = `msg ${m.role}`;

      const bubble = document.createElement("div");
      bubble.className = "bubble";

      if (m.content === "__loading__") {
        bubble.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;
      } else {
        bubble.innerHTML = _renderMarkdown(m.content || "");
      }

      wrap.appendChild(bubble);
      messagesWrap.appendChild(wrap);
    });

    messagesWrap.scrollTop = messagesWrap.scrollHeight;
  }

  function _buildEmptyState(mode) {
    const hints = mode === "career"
      ? ["Type <b>yes</b> to start your roadmap", "Say <b>done</b> after studying to take a quiz", "Type <b>status</b> to see your progress", "Type <b>skip</b> to move to the next day"]
      : ["Upload a PDF to extract topics by number", "Ask for 10-mark notes on any subject", "Request an assignment, report, or research paper", "Use the Tools menu to switch output format"];

    const d = document.createElement("div");
    d.className = "empty-state";
    d.innerHTML = `
      <div class="empty-icon">✦</div>
      <div class="empty-title">Ready to assist</div>
      <div class="empty-sub">${hints.map(h => `• ${h}`).join("<br>")}</div>
    `;
    return d;
  }

  // ── Sidebar ───────────────────────────────────────────────
  function renderSidebar(chats, currentId, onSelect, onDownload, onDelete) {
    chatListEl.innerHTML = "";

    Object.keys(chats).reverse().forEach(id => {
      const chat = chats[id];
      const item = document.createElement("div");
      item.className = `chat-item${id === currentId ? " active" : ""}`;
      item.onclick = e => { if (!e.target.closest(".ci-btn")) onSelect(id); };

      const title = document.createElement("div");
      title.className = "chat-item-title";
      title.textContent = chat.title;
      title.title = chat.title;

      const actions = document.createElement("div");
      actions.className = "chat-item-actions";

      const dlBtn = document.createElement("button");
      dlBtn.className = "ci-btn"; dlBtn.textContent = "↓"; dlBtn.title = "Download transcript";
      dlBtn.onclick = e => { e.stopPropagation(); onDownload(id); };

      const delBtn = document.createElement("button");
      delBtn.className = "ci-btn"; delBtn.textContent = "✕"; delBtn.title = "Delete session";
      delBtn.onclick = e => { e.stopPropagation(); onDelete(id); };

      actions.append(dlBtn, delBtn);
      item.append(title, actions);
      chatListEl.appendChild(item);
    });
  }

  // ── Tracker ───────────────────────────────────────────────
  function renderTracker(tracker, currentDay, onDayClick) {
    trackerGrid.innerHTML = "";
    let done = 0, fail = 0, pend = 0;

    (tracker || []).forEach(d => {
      const box = document.createElement("div");
      const isCurrent = d.day === currentDay && d.status === "pending";
      box.className = `day-box ${isCurrent ? "current" : (d.status || "pending")}`;
      box.textContent = `D${d.day}`;
      box.title = `Day ${d.day} — ${d.status || "pending"}`;
      if (onDayClick) box.onclick = () => onDayClick(d);
      trackerGrid.appendChild(box);

      if (d.status === "completed") done++;
      else if (d.status === "failed") fail++;
      else pend++;
    });

    if (statDone) statDone.textContent = done;
    if (statFail) statFail.textContent = fail;
    if (statPend) statPend.textContent = pend;
  }

  function renderStreak(streak) {
    if (streakEl) {
      streakEl.textContent = streak > 0 ? `🔥 ${streak}-day streak` : "";
      streakEl.style.display = streak > 0 ? "block" : "none";
    }
  }

  // ── Notifications ─────────────────────────────────────────
  function renderNotifications(notifications) {
    notifList.innerHTML = "";

    if (!notifications || notifications.length === 0) {
      if (npEmpty) npEmpty.style.display = "flex";
      return;
    }
    if (npEmpty) npEmpty.style.display = "none";

    notifications.forEach(n => {
      const item = document.createElement("div");
      item.className = `notif-item ${n.type || "info"}`;
      const time = n.created_at
        ? new Date(n.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "";
      item.innerHTML = `
        <div class="ni-title">${n.title}</div>
        <div class="ni-body">${n.body || ""}</div>
        ${time ? `<div class="ni-time">${time}</div>` : ""}
      `;
      notifList.appendChild(item);
    });
  }

  function setNotifDot(active) {
    if (notifDot) notifDot.classList.toggle("active", active);
  }

  // ── Env badge ─────────────────────────────────────────────
  function setEnvBadge(mode) {
    if (!envBadge) return;
    if (mode === "career") {
      envBadge.textContent = "🚀 Career Mode";
      envBadge.className = "env-badge career";
    } else {
      envBadge.textContent = "📚 Study Mode";
      envBadge.className = "env-badge study";
    }
  }

  // ── File badge ────────────────────────────────────────────
  function showFile(name) {
    if (!fileBadge) return;
    if (fileNameEl) fileNameEl.textContent = name;
    fileBadge.classList.add("visible");
  }

  function clearFile() {
    if (fileBadge) fileBadge.classList.remove("visible");
    if (fileNameEl) fileNameEl.textContent = "";
  }

  return {
    renderMessages,
    renderSidebar,
    renderTracker,
    renderStreak,
    renderNotifications,
    setNotifDot,
    setEnvBadge,
    showFile,
    clearFile,
  };
})();