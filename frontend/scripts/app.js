// frontend/scripts/app.js
// Application controller — wires everything together.

const App = (() => {
  // ── State ─────────────────────────────────────────────────
  let currentMode = null;   // 'study' | 'career'
  let currentTask = "notes";
  let _localNotifs = [];    // client-side notification queue
  let currentCareerDay = null;
  let _sharedQuota = null;

  // ── DOM elements ──────────────────────────────────────────
  const gateway          = document.getElementById("gateway");
  const appEl            = document.getElementById("app");
  const sidebar          = document.getElementById("sidebar");
  const trackerPanel     = document.getElementById("tracker-panel");
  const notifPanel       = document.getElementById("notif-panel");
  const careerConfigBar  = document.getElementById("career-config-bar");
  const studyToolbar     = document.getElementById("study-toolbar");
  const interviewConfigBar = document.getElementById("interview-config-bar");
  const userInput        = document.getElementById("user-input");
  const modeSelect       = document.getElementById("mode-select");
  const fileInputEl      = document.getElementById("file-input");
  const attachMenu       = document.getElementById("attach-menu");

  // ── Safe session storage helpers ──────────────────────────
  const safeGet = k => { try { return sessionStorage.getItem(k); } catch { return null; } };
  const safeSet = (k,v) => { try { sessionStorage.setItem(k,v); } catch {} };
  const safeRm  = k => { try { sessionStorage.removeItem(k); } catch {} };

  // ── Career config reader ───────────────────────────────────
  function _getCareerConfig() {
    return {
      role:          document.getElementById("cc-role").value.trim() || "Python Developer",
      duration:      document.getElementById("cc-duration").value,
      hours_per_day: document.getElementById("cc-hours").value,
      level:         document.getElementById("cc-level").value,
      dsa_track:     document.getElementById("cc-dsa").value,
    };
  }

  // ── Workspace activation ───────────────────────────────────
  function activateWorkspace(mode, pushState = true) {
    currentMode = mode;
    safeSet(CONFIG.STORAGE_KEY, mode);

    // Push a history entry so Back navigates back to gateway
    if (pushState) {
      history.pushState({ isai: true, mode }, "", "#" + mode);
    }

    gateway.classList.add("gw-hidden");
    appEl.classList.add("active");

    const isStudy    = mode === "study";
    const isCareer   = mode === "career";
    const isInterview = mode === "interview";
    UI.setEnvBadge(mode);

    careerConfigBar.classList.toggle("visible", isCareer);
    studyToolbar.classList.toggle("visible", isStudy);
    trackerPanel.classList.toggle("visible", isCareer);

    if (interviewConfigBar) interviewConfigBar.classList.toggle("visible", isInterview);

    const voiceBtn = document.getElementById("voice-toggle-btn");
    if (voiceBtn) voiceBtn.style.display = isInterview ? "" : "none";

    // Hide attach zone in interview mode (not needed)
    const inputZone = document.querySelector(".input-zone");
    if (inputZone) inputZone.style.display = isInterview ? "none" : "";
    // Show interview input instead
    const interviewInput = document.getElementById("interview-input-zone");
    if (interviewInput) interviewInput.style.display = isInterview ? "" : "none";

    userInput.placeholder = isStudy
      ? "Ask anything academic, upload a PDF, or request notes…"
      : isCareer
        ? "Type 'yes' to start your roadmap, 'done' after studying or 'status' for progress…"
        : "Type your interview answer here and press Enter to submit…";

    // ── Restore or create a mode-specific chat ────────────────
    const existingId = Store.getLatestChatForMode(mode);
    if (existingId) {
      Store.selectChat(existingId);
    } else {
      Store.createChat(mode);
    }

    _renderSidebar();

    // Restore attachment name badge (file object is gone after refresh)
    const attName = Store.getAttachmentName(Store.currentId);
    if (attName) UI.showFile(attName + " (re-upload to use)");
    else UI.clearFile();

    if (isInterview) {
      // Use interview renderer for message restoration
      Interview.renderMessages(Store.getMessages(Store.currentId));
    } else {
      UI.renderMessages(Store.getMessages(Store.currentId), mode);
    }

    if (!isStudy && !isInterview) {
      UI.renderTracker([], null, _onDayBoxClick);
      _silentProgressFetch();
      _pollNotifications();
    }

    userInput.focus();
  }

  function deactivateToHub() {
    safeRm(CONFIG.STORAGE_KEY);
    appEl.classList.remove("active");
    gateway.classList.remove("gw-hidden");
    currentMode = null;
    if (Store.currentId) Api.resetSession(Store.currentId).catch(() => {});
    UI.clearFile();
    userInput.value = "";

    // Hide interview config bar
    const interviewBar = document.getElementById("interview-config-bar");
    if (interviewBar) interviewBar.classList.remove("visible", "collapsed");

    // Hide ide toggle btn
    const ideToggleBtn = document.getElementById("ide-toggle-btn");
    if (ideToggleBtn) {
      ideToggleBtn.style.display = "none";
      ideToggleBtn.classList.remove("active");
    }

    // Hide weekly interview btn
    const weeklyBtn = document.getElementById("weekly-interview-btn");
    if (weeklyBtn) weeklyBtn.style.display = "none";

    const voiceBtn = document.getElementById("voice-toggle-btn");
    if (voiceBtn) voiceBtn.style.display = "none";

    // Replace history entry so another Back press leaves the site (expected behaviour)
    history.replaceState({ isai: false }, "", location.pathname);
  }

  // ── History (Back button) handler ─────────────────────────
  window.addEventListener("popstate", e => {
    if (currentMode) {
      // We were in a workspace — go back to gateway
      deactivateToHub();
      // Push a clean state so subsequent Back works normally
      history.pushState({ isai: false }, "", location.pathname);
    }
  });

  // ── Chat management ────────────────────────────────────────
  function _newChat() {
    Store.createChat(currentMode);
    UI.clearFile();
    if (currentMode === "interview") {
      Interview.resetAndRestart();
    } else {
      UI.renderMessages([], currentMode);
    }
    _renderSidebar();
    if (currentMode === "career") _silentProgressFetch();
  }

  function _selectChat(id) {
    Store.selectChat(id);
    const attName = Store.getAttachmentName(id);
    if (attName) UI.showFile(attName + " (re-upload to use)");
    else UI.clearFile();
    if (currentMode === "interview") {
      Interview.renderMessages(Store.getMessages(id));
    } else {
      UI.renderMessages(Store.getMessages(id), currentMode);
    }
    _renderSidebar();
    if (currentMode === "career") _silentProgressFetch();
  }

  function _deleteChat(id) {
    const mode = Store.getChat(id)?.mode || currentMode;
    if (!Store.deleteChat(id)) {
      UI.showToast("Cannot delete the last session in this workspace.", "warning");
      return;
    }
    Api.deleteSession(id).catch(() => {});
    UI.renderMessages(Store.getMessages(Store.currentId), currentMode);
    UI.renderTracker([], null, _onDayBoxClick);
    _renderSidebar();
  }

  function _renderSidebar() {
    if (!currentMode) return;
    const ids = Store.getChatsByMode(currentMode);
    const chats = {};
    ids.forEach(id => { chats[id] = Store.getChat(id); });
    UI.renderSidebar(chats, Store.currentId, _selectChat, Chat.downloadTranscript, _deleteChat);
  }

  // ── Progress & tracker ─────────────────────────────────────
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
      if (data.weekend) handleWeekendInterview(data.weekend);

      const introText = data.text || data.answer || "";
      if (introText && !Store.hasLoadingMessage(chatId) && !Store.hasRoadmap(chatId)) {
        Store.addMessage(chatId, "assistant", introText);
        UI.renderMessages(Store.getMessages(chatId), currentMode);
      }
    } catch { /* silently ignore */ }
  }

  function handleTrackerUpdate(tracker) {
    currentCareerDay = tracker.find(d => d.status === "pending")?.day || null;
    UI.renderTracker(tracker, currentCareerDay, _onDayBoxClick);

    // Toggle weekly interview button
    const weeklyBtn = document.getElementById("weekly-interview-btn");
    if (weeklyBtn) {
      if (currentCareerDay && (currentCareerDay % 7 === 6 || currentCareerDay % 7 === 0)) {
        weeklyBtn.style.display = "inline-block";
      } else {
        weeklyBtn.style.display = "none";
      }
    }
  }

  function _onDayBoxClick(dayObj) {
    const msgs = {
      completed: `✅ Day ${dayObj.day} — completed!`,
      failed:    `❌ Day ${dayObj.day} — failed. Review and try again.`,
      pending:   `⏳ Day ${dayObj.day} — not yet started.`,
    };
    _addLocalNotif("info", `Day ${dayObj.day}`, msgs[dayObj.status] || "");
  }

  // ── Notifications ──────────────────────────────────────────
  async function _pollNotifications() {
    if (!Store.currentId || currentMode !== "career") return;
    try {
      const data = await Api.getNotifications(Store.currentId);
      if (data.count > 0) {
        UI.setNotifDot(true);
        UI.renderNotifications(data.notifications);
      }
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

    if (Store.currentId) {
      try {
        const data = await Api.getNotifications(Store.currentId);
        const merged = [..._localNotifs, ...(data.notifications || [])];
        UI.renderNotifications(merged);
        await Api.markNotificationsRead(Store.currentId);
      } catch { UI.renderNotifications(_localNotifs); }
    }
  }

  // ── Task pills ─────────────────────────────────────────────
  function setTask(task) {
    currentTask = task;
    document.querySelectorAll(".task-pill").forEach(p => {
      p.classList.toggle("active", p.dataset.task === task);
    });
    if (modeSelect) modeSelect.style.display = (task === "notes") ? "inline-block" : "none";
  }

  // ── Attach menu ────────────────────────────────────────────
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

  // ── File input ─────────────────────────────────────────────
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

  function _updateApiKeyStatusUI() {
    const key = localStorage.getItem("user_groq_api_key");
    const gwStatus = document.getElementById("gateway-key-status");
    const modalKeyInput = document.getElementById("modal-groq-key");
    const quotaStatus = document.getElementById("shared-key-quota-status");

    if (key) {
      if (gwStatus) {
        gwStatus.className = "key-status-badge active";
        gwStatus.textContent = "🟢 Using Your Groq Key";
      }
      if (modalKeyInput) {
        modalKeyInput.value = key;
      }
      if (quotaStatus) {
        quotaStatus.textContent = "Your Groq key is active. Requests use your Groq account's limits, not the shared daily allowance.";
      }
    } else {
      if (gwStatus) {
        const remaining = _sharedQuota?.requests_remaining;
        const limit = _sharedQuota?.daily_limit;
        const serverKeyAvailable = _sharedQuota?.server_key_configured;
        gwStatus.className = serverKeyAvailable && Number.isInteger(remaining) && remaining > 0
          ? "key-status-badge active"
          : "key-status-badge shared";
        gwStatus.textContent = serverKeyAvailable && Number.isInteger(remaining) && Number.isInteger(limit)
          ? `Shared key: ${remaining}/${limit} left today`
          : serverKeyAvailable === false
            ? "Shared key unavailable"
            : "Shared Groq Key";
      }
      if (modalKeyInput) {
        modalKeyInput.value = "";
      }
      if (quotaStatus) {
        if (_sharedQuota && !_sharedQuota.server_key_configured) {
          quotaStatus.textContent = "The shared Groq key is not configured. Add your own Groq API key to continue.";
        } else if (_sharedQuota) {
          quotaStatus.textContent =
            `${_sharedQuota.requests_remaining} of ${_sharedQuota.daily_limit} shared-key AI questions remain today (resets at 00:00 UTC). Add your own key to use your Groq account instead.`;
        } else {
          quotaStatus.textContent = "Shared-key use is limited to 5 AI questions per user each UTC day.";
        }
      }
    }
  }

  function _refreshSharedQuota() {
    Api.getUsage()
      .then(data => {
        _sharedQuota = data.quota;
        _updateApiKeyStatusUI();
      })
      .catch(error => console.warn("[API] Could not refresh shared-key usage:", error));
  }

  function _wireApiKeyModal() {
    const apiBtn = document.getElementById("api-key-btn");
    const gwApiBtn = document.getElementById("gateway-key-btn");
    const closeBtn = document.getElementById("api-key-close-btn");
    const modal = document.getElementById("api-key-modal");
    const saveBtn = document.getElementById("api-key-save-btn");
    const clearBtn = document.getElementById("api-key-clear-btn");
    const keyInput = document.getElementById("modal-groq-key");
    const toggleVisBtn = document.getElementById("toggle-groq-key-visibility");

    window.addEventListener("shared-key-quota", event => {
      const { mode, remaining, limit } = event.detail;
      if (mode === "shared" && Number.isInteger(remaining) && Number.isInteger(limit)) {
        _sharedQuota = {
          ..._sharedQuota,
          server_key_configured: true,
          requests_remaining: remaining,
          daily_limit: limit,
        };
        _updateApiKeyStatusUI();
      }
    });

    const openModal = () => {
      _updateApiKeyStatusUI();
      _refreshSharedQuota();
      if (modal) {
        modal.style.display = "flex";
      }
      if (keyInput) {
        keyInput.focus();
      }
    };

    const closeModal = () => {
      if (modal) modal.style.display = "none";
    };

    if (apiBtn) apiBtn.onclick = openModal;
    if (gwApiBtn) gwApiBtn.onclick = openModal;
    if (closeBtn) closeBtn.onclick = closeModal;

    if (modal) {
      modal.onclick = e => {
        if (e.target === modal) closeModal();
      };
    }

    if (saveBtn) {
      saveBtn.onclick = () => {
        if (!keyInput) return;
        const val = keyInput.value.trim();
        if (!val) {
          UI.showToast("Please enter a valid token.", "warning");
          return;
        }
        localStorage.setItem("user_groq_api_key", val);
        _updateApiKeyStatusUI();
        UI.showToast("Groq API key saved successfully!", "success");
        closeModal();
      };
    }

    if (clearBtn) {
      clearBtn.onclick = () => {
        localStorage.removeItem("user_groq_api_key");
        _updateApiKeyStatusUI();
        UI.showToast("Groq API key cleared.", "info");
        closeModal();
      };
    }

    if (toggleVisBtn && keyInput) {
      toggleVisBtn.onclick = () => {
        const isPass = keyInput.type === "password";
        keyInput.type = isPass ? "text" : "password";
        toggleVisBtn.textContent = isPass ? "🙈" : "👁️";
      };
    }
  }

  // ── Bootstrap ──────────────────────────────────────────────
  async function init() {
    // Initialize authentication and verify credentials
    Auth.init();
    const isAuthed = await Auth.checkAuth();

    _updateApiKeyStatusUI();
    _wireApiKeyModal();
    if (isAuthed) _refreshSharedQuota();
    // Ensure a clean history baseline (no #hash from old visits)
    if (location.hash === "") {
      history.replaceState({ isai: false }, "", location.pathname);
    }

    // Gateway buttons
    document.getElementById("choose-study").onclick     = () => activateWorkspace("study");
    document.getElementById("choose-career").onclick    = () => activateWorkspace("career");
    document.getElementById("choose-interview").onclick = () => activateWorkspace("interview");

    // Topbar
    document.getElementById("sidebar-toggle").onclick = () => sidebar.classList.toggle("collapsed");
    document.getElementById("switch-btn").onclick     = () => {
      history.back(); // triggers popstate → deactivateToHub
    };
    const weeklyBtn = document.getElementById("weekly-interview-btn");
    if (weeklyBtn) {
      weeklyBtn.onclick = () => {
        if (!currentCareerDay) return;
        safeSet("weekly_interview_career_day", currentCareerDay);
        activateWorkspace("interview");

        // Prefill config inputs
        const ccRole = document.getElementById("cc-role")?.value.trim() || "Python Developer";
        const icRole = document.getElementById("ic-role");
        const icCompany = document.getElementById("ic-company");
        const icDomain = document.getElementById("ic-domain");
        const icRound = document.getElementById("ic-round");
        const icJd = document.getElementById("ic-jd");

        if (icRole) icRole.value = ccRole;
        if (icCompany) icCompany.value = "Weekly Evaluation (Career Accelerator)";
        if (icDomain) icDomain.value = "it";
        if (icRound) icRound.value = "tech";
        if (icJd) icJd.value = "Mandatory Weekly Assessment to evaluate candidate learning progress.";

        const bar = document.getElementById("interview-config-bar");
        if (bar) bar.classList.remove("collapsed");
      };
    }
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

    // Send button — route to interview handler when in interview mode
    document.getElementById("send-btn").onclick = () => {
      if (currentMode === "interview") Interview.send();
      else Chat.send(() => currentMode, () => currentTask, _getCareerConfig);
    };

    // Keyboard
    Chat.bindKeyboard(() => currentMode, () => currentTask, _getCareerConfig);
    const userInputEl = document.getElementById("user-input");
    if (userInputEl) {
      userInputEl.addEventListener("keydown", e => {
        if (currentMode === "interview" && e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          Interview.send();
        }
      });
      userInputEl.addEventListener("paste", e => {
        if (currentMode === "career") {
          e.preventDefault();
          UI.showToast("Paste is disabled in Career Accelerator to ensure genuine learning.", "warning");
        }
      });
    }

    // Attach + file
    _bindAttachMenu();
    _bindFileInput();

    // Interview buttons
    const icStartBtn  = document.getElementById("ic-start-btn");
    const icMinimizeBtn = document.getElementById("ic-minimize-btn");
    const icResetBtn  = document.getElementById("ic-reset-btn");
    const icExpandBtn = document.getElementById("ic-expand-btn");
    const ideToggleBtn = document.getElementById("ide-toggle-btn");
    const iwSendBtn   = document.getElementById("iw-send-btn");
    const iwAnswerEl  = document.getElementById("iw-answer-input");

    if (icStartBtn)  icStartBtn.onclick  = () => Interview.start();
    if (icMinimizeBtn) icMinimizeBtn.onclick = () => {
      const bar = document.getElementById("interview-config-bar");
      if (bar) bar.classList.add("collapsed");
    };
    if (icResetBtn)  icResetBtn.onclick  = () => Interview.resetAndRestart();
    if (icExpandBtn) icExpandBtn.onclick = () => {
      const bar = document.getElementById("interview-config-bar");
      if (bar) bar.classList.remove("collapsed");
    };
    if (ideToggleBtn) {
      ideToggleBtn.onclick = () => {
        const ide = document.getElementById("ide-panel");
        if (ide) {
          const isHidden = ide.style.display === "none";
          ide.style.display = isHidden ? "flex" : "none";
          ideToggleBtn.classList.toggle("active", isHidden);
        }
      };
    }
    if (iwSendBtn) iwSendBtn.onclick = () => Interview.send();
    if (iwAnswerEl) iwAnswerEl.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); Interview.send(); }
    });

    // Wire resume upload zone and IDE editor
    Interview.initUploadZone();
    Interview.initIDE();
    Interview.initVoiceToggle();
    Interview.initMicButton();

    // Restore workspace from session storage (page refresh)
    if (isAuthed) {
      const saved = safeGet(CONFIG.STORAGE_KEY);
      if (saved === "study" || saved === "career" || saved === "interview") {
        // Don't push a new history entry — we're restoring an existing state
        activateWorkspace(saved, false);
      }
    }
  }


  // ── Weekend interview banner ──────────────────────────────
  function handleWeekendInterview(weekendData) {
    if (!weekendData) { UI.showWeekendBanner(null); return; }
    UI.showWeekendBanner(weekendData);
    _addLocalNotif(
      "reminder",
      "Weekend mock interview ready",
      weekendData.topics?.slice(0, 3).join(", ") || "Your week's topics are ready for review."
    );
  }

    return { init, handleTrackerUpdate, handleWeekendInterview, addNotif: _addLocalNotif };
})();

// Kick off once DOM is ready
document.addEventListener("DOMContentLoaded", App.init);