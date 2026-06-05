// frontend/scripts/app.js
// Application controller — wires everything together.

const App = (() => {
  // ── State ────────────────────────────────────────────────
  let currentMode = null;   // 'study' | 'career'
  let currentTask = "notes";
  let _localNotifs = [];    // client-side notification queue

  // ── DOM elements ─────────────────────────────────────────
  const gateway          = document.getElementById("gateway");
  const appEl            = document.getElementById("app");
  const sidebar          = document.getElementById("sidebar");
  const trackerPanel     = document.getElementById("tracker-panel");
  const notifPanel       = document.getElementById("notif-panel");
  const careerConfigBar  = document.getElementById("career-config-bar");
  const studyToolbar     = document.getElementById("study-toolbar");
  const userInput        = document.getElementById("user-input");
  const modeSelect       = document.getElementById("mode-select");
  const fileInputEl      = document.getElementById("file-input");
  const attachMenu       = document.getElementById("attach-menu");

  // ── Safe session storage helpers ─────────────────────────
  const safeGet = k => { try { return sessionStorage.getItem(k); } catch { return null; } };
  const safeSet = (k,v) => { try { sessionStorage.setItem(k,v); } catch {} };
  const safeRm  = k => { try { sessionStorage.removeItem(k); } catch {} };

  // ── Career config reader ──────────────────────────────────
  function _getCareerConfig() {
    return {
      role:          document.getElementById("cc-role").value.trim() || "Python Developer",
      duration:      document.getElementById("cc-duration").value,
      hours_per_day: document.getElementById("cc-hours").value,
      level:         document.getElementById("cc-level").value,
      dsa_track:     document.getElementById("cc-dsa").value,
    };
  }

  // ── Workspace activation ──────────────────────────────────
  function activateWorkspace(mode) {
    currentMode = mode;
    safeSet(CONFIG.STORAGE_KEY, mode);

    gateway.style.display = "none";
    appEl.classList.add("active");

    const isStudy = mode === "study";
    UI.setEnvBadge(mode);

    careerConfigBar.classList.toggle("visible", !isStudy);
    studyToolbar.classList.toggle("visible", isStudy);
    trackerPanel.classList.toggle("visible", !isStudy);

    userInput.placeholder = isStudy
      ? "Ask anything academic, upload a PDF, or request notes…"
      : "Type 'yes' to start your roadmap, 'done' after studying, or 'status' for progress…";

    if (!Store.currentId) Store.createChat();

    _renderSidebar();
    UI.renderMessages(Store.getMessages(Store.currentId), mode);

    if (!isStudy) {
      UI.renderTracker([], null, _onDayBoxClick);
      _silentProgressFetch();
      _pollNotifications();
    }

    userInput.focus();
  }

  function deactivateToHub() {
    safeRm(CONFIG.STORAGE_KEY);
    appEl.classList.remove("active");
    gateway.style.display = "flex";
    currentMode = null;
    Api.resetSession(Store.currentId).catch(() => {});
    UI.clearFile();
    userInput.value = "";
  }

  // ── Chat management ───────────────────────────────────────
  function _newChat() {
    Store.createChat();
    UI.clearFile();
    UI.renderMessages([], currentMode);
    _renderSidebar();
    if (currentMode === "career") _silentProgressFetch();
  }

  function _selectChat(id) {
    Store.selectChat(id);
    const att = Store.getAttachment(id);
    if (att) UI.showFile(att.name); else UI.clearFile();
    UI.renderMessages(Store.getMessages(id), currentMode);
    _renderSidebar();
    if (currentMode === "career") _silentProgressFetch();
  }

  function _deleteChat(id) {
    if (!Store.deleteChat(id)) {
      alert("Cannot delete the last remaining session.");
      return;
    }
    Api.deleteSession(id).catch(() => {});
    UI.renderMessages(Store.getMessages(Store.currentId), currentMode);
    UI.renderTracker([], null, _onDayBoxClick);
    _renderSidebar();
  }

  function _renderSidebar() {
    const ids = Store.getChatIds();
    const chats = {};
    ids.forEach(id => { chats[id] = Store.getChat(id); });
    UI.renderSidebar(chats, Store.currentId, _selectChat, Chat.downloadTranscript, _deleteChat);
  }

  // ── Progress & tracker ────────────────────────────────────
  async function _silentProgressFetch() {
    if (!Store.currentId) return;
    const chatId = Store.currentId;
    try {
      const data = await Api.fetchProgress({ chatId, careerConfig: _getCareerConfig() });
      if (Store.currentId !== chatId || currentMode !== "career") return;

      if (data.text === "") {
        UI.renderTracker([], null, _onDayBoxClick);
        return;
      }
      if (data.tracker) handleTrackerUpdate(data.tracker);

      const introText = data.text || data.answer || "";
      if (introText && !Store.hasLoadingMessage(chatId) && !Store.hasRoadmap(chatId)) {
        Store.addMessage(chatId, "assistant", introText);
        UI.renderMessages(Store.getMessages(chatId), currentMode);
      }
    } catch { /* silently ignore */ }
  }

  function handleTrackerUpdate(tracker) {
    // Find current day (first pending day)
    const currentDay = tracker.find(d => d.status === "pending")?.day || null;
    UI.renderTracker(tracker, currentDay, _onDayBoxClick);
  }

  function _onDayBoxClick(dayObj) {
    const msgs = {
      completed: `✅ Day ${dayObj.day} — completed!`,
      failed:    `❌ Day ${dayObj.day} — failed. Review the topic and try again.`,
      pending:   `⏳ Day ${dayObj.day} — not yet started.`,
    };
    _addLocalNotif("info", `Day ${dayObj.day}`, msgs[dayObj.status] || "");
  }

  // ── Notifications ─────────────────────────────────────────
  async function _pollNotifications() {
    if (!Store.currentId || currentMode !== "career") return;
    try {
      const data = await Api.getNotifications(Store.currentId);
      if (data.count > 0) {
        UI.setNotifDot(true);
        UI.renderNotifications(data.notifications);
      }
      // Poll every 30 s while in career mode
      setTimeout(_pollNotifications, 30_000);
    } catch { setTimeout(_pollNotifications, 60_000); }
  }

  function _addLocalNotif(type, title, body) {
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    _localNotifs.unshift({ type, title, body, created_at: time });
    UI.setNotifDot(true);
    UI.renderNotifications(_localNotifs);
  }

  async function _openNotifPanel() {
    if (notifPanel.classList.contains("open")) {
      notifPanel.classList.remove("open");
      return;
    }
    notifPanel.classList.add("open");
    UI.setNotifDot(false);

    // Merge server notifications with local ones
    if (Store.currentId) {
      try {
        const data = await Api.getNotifications(Store.currentId);
        const merged = [..._localNotifs, ...(data.notifications || [])];
        UI.renderNotifications(merged);
        await Api.markNotificationsRead(Store.currentId);
      } catch { UI.renderNotifications(_localNotifs); }
    }
  }

  // ── Task pills ────────────────────────────────────────────
  function setTask(task) {
    currentTask = task;
    document.querySelectorAll(".task-pill").forEach(p => {
      p.classList.toggle("active", p.dataset.task === task);
    });
    if (modeSelect) modeSelect.style.display = (task === "notes") ? "inline-block" : "none";
  }

  // ── Attach menu ───────────────────────────────────────────
  function _bindAttachMenu() {
    document.getElementById("attach-btn").onclick = e => {
      e.stopPropagation();
      attachMenu.classList.toggle("open");
    };
    document.addEventListener("click", () => attachMenu.classList.remove("open"));

    document.querySelectorAll(".am-item").forEach(item => {
      item.onclick = () => {
        const action = item.dataset.action;
        const task   = item.dataset.task;
        if (action === "upload") fileInputEl.click();
        if (task) setTask(task);
        attachMenu.classList.remove("open");
      };
    });
  }

  // ── File input ────────────────────────────────────────────
  function _bindFileInput() {
    fileInputEl.onchange = e => {
      const f = e.target.files[0];
      if (!f) return;
      Store.setAttachment(Store.currentId, f);
      UI.showFile(f.name);
    };

    document.getElementById("file-badge-clear").onclick = () => {
      Store.setAttachment(Store.currentId, null);
      fileInputEl.value = "";
      UI.clearFile();
    };
  }

  // ── Bootstrap ─────────────────────────────────────────────
  function init() {
    // Gateway buttons
    document.getElementById("choose-study").onclick  = () => activateWorkspace("study");
    document.getElementById("choose-career").onclick = () => activateWorkspace("career");

    // Topbar
    document.getElementById("sidebar-toggle").onclick = () => sidebar.classList.toggle("collapsed");
    document.getElementById("switch-btn").onclick     = deactivateToHub;
    document.getElementById("notif-btn").onclick      = _openNotifPanel;
    document.getElementById("np-close").onclick       = () => notifPanel.classList.remove("open");
    document.getElementById("np-clear").onclick       = () => {
      _localNotifs = [];
      UI.renderNotifications([]);
      Api.markNotificationsRead(Store.currentId).catch(() => {});
    };

    // Sidebar
    document.getElementById("new-chat-btn").onclick = _newChat;

    // Task pills
    document.querySelectorAll(".task-pill").forEach(p => {
      p.onclick = () => setTask(p.dataset.task);
    });

    // Send button
    document.getElementById("send-btn").onclick = () =>
      Chat.send(() => currentMode, () => currentTask, _getCareerConfig);

    // Keyboard
    Chat.bindKeyboard(() => currentMode, () => currentTask, _getCareerConfig);

    // Attach + file
    _bindAttachMenu();
    _bindFileInput();

    // Restore workspace from session storage
    const saved = safeGet(CONFIG.STORAGE_KEY);
    if (saved === "study" || saved === "career") activateWorkspace(saved);
  }

  return { init, handleTrackerUpdate, addNotif: _addLocalNotif };
})();

// Kick off once DOM is ready
document.addEventListener("DOMContentLoaded", App.init);
