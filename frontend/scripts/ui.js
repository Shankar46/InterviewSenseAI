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
  const toastContainer = document.getElementById("toast-container");

  // ── Markdown rendering ─────────────────────────────────────
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

  // ── Skeleton loader ────────────────────────────────────────
  function _buildSkeleton() {
    return `
      <div class="skeleton-wrap">
        <div class="skeleton-line" style="width:85%"></div>
        <div class="skeleton-line" style="width:65%"></div>
        <div class="skeleton-line" style="width:75%"></div>
        <div class="skeleton-line" style="width:50%"></div>
      </div>`;
  }

  // ── Copy to clipboard ──────────────────────────────────────
  function _copyText(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = "✓";
      btn.classList.add("copied");
      setTimeout(() => { btn.textContent = "⎘"; btn.classList.remove("copied"); }, 1800);
    }).catch(() => showToast("Copy failed.", "warning"));
  }

  // ── Messages ───────────────────────────────────────────────
  function renderMessages(messages, mode, skipScroll = false) {
    messagesWrap.innerHTML = "";

    if (!messages || messages.length === 0) {
      messagesWrap.appendChild(_buildEmptyState(mode));
      return;
    }

    messages.forEach((m, idx) => {
      const wrap = document.createElement("div");
      wrap.className = `msg ${m.role}`;
      // Stagger fade-in
      wrap.style.animationDelay = `${Math.min(idx * 0.04, 0.4)}s`;

      const bubble = document.createElement("div");
      bubble.className = "bubble";

      if (m.content === "__loading__") {
        bubble.innerHTML = _buildSkeleton();
      } else {
        const scoreCard = _buildScoreCard(m.content || "");
        if (scoreCard) {
          bubble.appendChild(scoreCard);
          // Remove STATUS/SCORE lines from markdown body
          const cleaned = (m.content || "")
            .replace(/^STATUS:\s*(PASS|FAIL)\s*\n?/im, "")
            .replace(/^SCORE:\s*\d+\s*\/\s*10\s*\n?/im, "")
            .trim();
          bubble.innerHTML += _renderMarkdown(cleaned);
        } else {
          bubble.innerHTML = _renderMarkdown(m.content || "");
        }

        // Copy button for assistant messages
        if (m.role === "assistant") {
          const copyBtn = document.createElement("button");
          copyBtn.className = "copy-btn";
          copyBtn.title     = "Copy response";
          copyBtn.textContent = "⎘";
          copyBtn.onclick   = () => _copyText(m.content, copyBtn);
          bubble.appendChild(copyBtn);
        }
      }

      wrap.appendChild(bubble);
      messagesWrap.appendChild(wrap);
    });

    if (!skipScroll) messagesWrap.scrollTop = messagesWrap.scrollHeight;
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

  // ── Sidebar ────────────────────────────────────────────────
  function renderSidebar(chats, currentId, onSelect, onDownload, onDelete) {
    chatListEl.innerHTML = "";

    const ids = Object.keys(chats).reverse();
    if (ids.length === 0) {
      const empty = document.createElement("div");
      empty.className = "sidebar-empty";
      empty.textContent = "No sessions yet";
      chatListEl.appendChild(empty);
      return;
    }

    ids.forEach(id => {
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
      delBtn.className = "ci-btn ci-del"; delBtn.textContent = "✕"; delBtn.title = "Delete session";
      delBtn.onclick = e => { e.stopPropagation(); onDelete(id); };

      actions.append(dlBtn, delBtn);
      item.append(title, actions);
      chatListEl.appendChild(item);
    });
  }

  // ── Tracker ────────────────────────────────────────────────
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

  // ── Notifications ──────────────────────────────────────────
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
        ? (typeof n.created_at === "string" && n.created_at.includes(":")
            ? n.created_at   // already formatted HH:MM
            : new Date(n.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))
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

  // ── Toast notifications ────────────────────────────────────
  function showToast(message, type = "info") {
    if (!toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const icon = { info: "ℹ️", success: "✅", warning: "⚠️", error: "❌" }[type] || "ℹ️";
    toast.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-msg">${message}</span>`;

    toastContainer.appendChild(toast);
    // Trigger animation
    requestAnimationFrame(() => toast.classList.add("toast-show"));

    setTimeout(() => {
      toast.classList.remove("toast-show");
      toast.classList.add("toast-hide");
      setTimeout(() => toast.remove(), 350);
    }, 3500);
  }

  // ── Env badge ──────────────────────────────────────────────
  function setEnvBadge(mode) {
    if (!envBadge) return;
    if (mode === "career") {
      envBadge.textContent = "🚀 Career Mode";
      envBadge.className = "env-badge career";
    } else if (mode === "interview") {
      envBadge.textContent = "🎯 Interview Mode";
      envBadge.className = "env-badge interview";
    } else {
      envBadge.textContent = "📚 Study Mode";
      envBadge.className = "env-badge study";
    }
  }

  // ── File badge ─────────────────────────────────────────────
  function showFile(name) {
    if (!fileBadge) return;
    if (fileNameEl) fileNameEl.textContent = name;
    fileBadge.classList.add("visible");
  }

  function clearFile() {
    if (fileBadge) fileBadge.classList.remove("visible");
    if (fileNameEl) fileNameEl.textContent = "";
  }


  // ── Score card — renders evaluation responses visually ────
  function _buildScoreCard(content) {
    const statusMatch = content.match(/^STATUS:\s*(PASS|FAIL)/im);
    const scoreMatch  = content.match(/SCORE:\s*(\d+)\s*\/\s*10/i);
    if (!statusMatch || !scoreMatch) return null;
    const passed = statusMatch[1].toUpperCase() === "PASS";
    const score  = parseInt(scoreMatch[1], 10);
    const pct    = Math.round((score / 10) * 100);
    const color  = score >= 8 ? "var(--teal)" : score >= 6 ? "var(--amber)" : "var(--red)";
    const ring   = Math.round(pct * 1.131);
    const card   = document.createElement("div");
    card.className = `score-card ${passed ? "pass" : "fail"}`;
    card.innerHTML = `
      <div class="sc-header">
        <div>
          <div class="sc-badge ${passed ? "pass" : "fail"}">${passed ? "PASSED" : "NEEDS REVIEW"}</div>
          <div class="sc-topic">Assessment Result</div>
        </div>
        <div class="sc-score-wrap">
          <svg class="sc-ring" viewBox="0 0 44 44" aria-hidden="true">
            <circle cx="22" cy="22" r="18" fill="none" stroke="var(--surface2)" stroke-width="4"/>
            <circle cx="22" cy="22" r="18" fill="none" stroke="${color}" stroke-width="4"
              stroke-dasharray="${ring} 113.1" stroke-dashoffset="28.275" stroke-linecap="round"/>
          </svg>
          <span class="sc-score-num" style="color:${color}">${score}<span class="sc-denom">/10</span></span>
        </div>
      </div>`;
    return card;
  }


  // ── Concept navigator progress bar ───────────────────────
  function showConceptProgress(current, total) {
    let bar = document.getElementById("concept-progress-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "concept-progress-bar";
      bar.className = "concept-progress-bar";
      const iz = document.querySelector(".input-zone");
      if (iz) iz.prepend(bar);
    }
    if (!current || !total) { bar.style.display = "none"; return; }
    const pct = Math.round((current / total) * 100);
    bar.style.display = "flex";
    bar.innerHTML = `
      <span class="cpb-label">Concept ${current} / ${total}</span>
      <div class="cpb-track"><div class="cpb-fill" style="width:${pct}%"></div></div>
      <span class="cpb-pct">${pct}%</span>`;
  }


  // ── Weekend interview banner ──────────────────────────────
  function showWeekendBanner(weekendData) {
    let banner = document.getElementById("weekend-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "weekend-banner";
      banner.className = "weekend-banner";
      const actions = document.querySelector(".topbar-actions");
      if (actions) actions.prepend(banner);
    }
    if (!weekendData) { banner.style.display = "none"; return; }
    banner.style.display = "flex";
    banner.innerHTML = `
      <span class="wb-dot"></span>
      <span class="wb-text">Weekend interview ready</span>
      <button class="wb-btn" id="wb-start-btn" type="button">Start →</button>`;
    const btn = document.getElementById("wb-start-btn");
    if (btn) btn.onclick = () => {
      const inp = document.getElementById("user-input");
      if (inp) { inp.value = "interview"; inp.dispatchEvent(new Event("input")); inp.focus(); }
      banner.style.display = "none";
    };
  }

  return {
    renderMessages,
    renderSidebar,
    renderTracker,
    renderStreak,
    renderNotifications,
    setNotifDot,
    showToast,
    setEnvBadge,
    showFile,
    clearFile,
    showConceptProgress,
    showWeekendBanner,
  };
})();