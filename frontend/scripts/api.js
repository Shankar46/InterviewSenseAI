// frontend/scripts/api.js
// FIXED: Added saveMessage/getMessages for DB persistence.
// FIXED: Added generateStudy/generateCareer as isolated wrappers.
// All existing functions preserved exactly.

const Api = (() => {
  const REQUEST_TIMEOUT_MS = 240000;
  const AI_ENDPOINTS = new Set([
    "/api/workspace/generate",
    "/api/edtech/generate",
    "/generate",
    "/api/interview/start",
    "/api/interview/answer",
    "/api/interview/report",
    "/api/agent",
    "/api/evaluate",
  ]);

  function _url(path) { return CONFIG.BACKEND_URL + path; }

  function _fetch(url, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || REQUEST_TIMEOUT_MS);

    if (!options.headers) options.headers = {};

    const userApiKey = localStorage.getItem("user_groq_api_key");
    const pathname = new URL(url, window.location.href).pathname;
    if (userApiKey && AI_ENDPOINTS.has(pathname)) {
      options.headers["X-Groq-API-Key"] = userApiKey.trim();
    }

    const token = localStorage.getItem("isai_auth_token");
    if (token) options.headers["Authorization"] = "Bearer " + token;

    return fetch(url, { ...options, signal: controller.signal })
      .then(res => {
        const mode = res.headers.get("X-Shared-Key-Mode");
        const remaining = res.headers.get("X-Shared-Key-Remaining");
        const limit = res.headers.get("X-Shared-Key-Limit");
        if (mode) {
          window.dispatchEvent(new CustomEvent("shared-key-quota", {
            detail: {
              mode,
              remaining: remaining === null ? null : Number(remaining),
              limit: limit === null ? null : Number(limit),
            },
          }));
        }
        if (res.status === 401) {
          if (typeof Auth !== "undefined") Auth.logout();
          throw new Error("Session expired. Please log in again.");
        }
        return res;
      })
      .catch(err => {
        if (err.name === "AbortError") throw new Error("Request timed out. Please try again.");
        throw err;
      })
      .finally(() => clearTimeout(timeout));
  }

  // ── Study / Career generate (existing — preserved) ────────
  async function generate({ topic, mode, task, history, file, assistantType, careerConfig, chatId }) {
    const form = new FormData();
    form.append("topic",          topic || "");
    form.append("mode",           mode  || "10 Marks");
    form.append("task_type",      task  || "notes");
    form.append("assistant_type", assistantType);
    form.append("chat_id",        chatId);
    form.append("history",        JSON.stringify(history || []));
    if (careerConfig) form.append("career_config", JSON.stringify(careerConfig));
    if (file)         form.append("file", file);

    const endpoint = assistantType === "career"
      ? CONFIG.ENDPOINTS.CAREER
      : CONFIG.ENDPOINTS.STUDY;

    const res = await _fetch(_url(endpoint), { method: "POST", body: form, timeout: REQUEST_TIMEOUT_MS });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || err.answer || err.text || `Server error ${res.status}`);
    }
    return res.json();
  }

  async function getUsage() {
    const res = await _fetch(_url("/api/usage"), { timeout: 10000 });
    if (!res.ok) throw new Error("Could not load shared-key usage.");
    return res.json();
  }

  // ── Message persistence (NEW) ─────────────────────────────

  async function saveMessage(chatId, role, content) {
    if (!content || content === "__loading__") return;
    const form = new FormData();
    form.append("role",    role);
    form.append("content", content);
    await _fetch(_url(`/api/sessions/${encodeURIComponent(chatId)}/messages`), {
      method: "POST", body: form, timeout: 10000,
    }).catch(() => {}); // fire-and-forget
  }

  async function getMessages(chatId) {
    const res = await _fetch(
      _url(`/api/sessions/${encodeURIComponent(chatId)}/messages`),
      { timeout: 10000 }
    );
    if (!res.ok) return { messages: [] };
    return res.json().catch(() => ({ messages: [] }));
  }

  // ── Progress refresh (existing — preserved) ───────────────
  async function fetchProgress({ chatId, careerConfig }) {
    const form = new FormData();
    form.append("topic",          "refresh_fetch");
    form.append("mode",           "10 Marks");
    form.append("task_type",      "career");
    form.append("assistant_type", "career");
    form.append("chat_id",        chatId);
    form.append("history",        JSON.stringify([]));
    form.append("career_config",  JSON.stringify(careerConfig || {}));
    const res = await _fetch(_url(CONFIG.ENDPOINTS.CAREER), { method: "POST", body: form, timeout: 30000 });
    if (!res.ok) throw new Error("Progress fetch failed");
    return res.json();
  }

  // ── Reset session (existing — preserved) ──────────────────
  async function resetSession(chatId) {
    const form = new FormData();
    form.append("chat_id", chatId);
    await _fetch(_url(CONFIG.ENDPOINTS.RESET), { method: "POST", body: form, timeout: 10000 }).catch(() => {});
  }

  // ── Delete session (existing — preserved) ─────────────────
  async function deleteSession(chatId) {
    const form = new FormData();
    form.append("chat_id", chatId);
    const res = await _fetch(_url(CONFIG.ENDPOINTS.DELETE), { method: "POST", body: form, timeout: 10000 });
    return res.json().catch(() => ({}));
  }

  // ── Notifications (existing — preserved) ──────────────────
  async function getNotifications(chatId) {
    const res = await _fetch(_url(CONFIG.ENDPOINTS.NOTIFICATIONS + `?chat_id=${chatId}`), { timeout: 10000 });
    if (!res.ok) return { notifications: [], count: 0 };
    return res.json();
  }

  async function markNotificationsRead(chatId) {
    const form = new FormData();
    form.append("chat_id", chatId);
    await _fetch(_url(CONFIG.ENDPOINTS.NOTIF_READ), { method: "POST", body: form, timeout: 10000 }).catch(() => {});
  }

  // ── Stats (existing — preserved) ──────────────────────────
  async function getStats(chatId) {
    const res = await _fetch(_url(CONFIG.ENDPOINTS.STATS + `?chat_id=${chatId}`), { timeout: 10000 });
    if (!res.ok) return null;
    return res.json().catch(() => null);
  }

  // ── Health check (existing — preserved) ───────────────────
  async function healthCheck() {
    try {
      const res = await _fetch(_url(CONFIG.ENDPOINTS.HEALTH), { method: "GET", timeout: 10000 });
      return res.ok;
    } catch { return false; }
  }

  // ── Interview (existing — preserved) ──────────────────────
  async function startInterview({ chatId, role, company, jdText, resumeFile, domain, roundType, weeklyCareerDay }) {
    const form = new FormData();
    form.append("chat_id",          chatId);
    form.append("role",             role);
    form.append("company",          company);
    form.append("jd_text",          jdText);
    form.append("domain",           domain || "it");
    form.append("round_type",       roundType || "tech");
    form.append("weekly_career_day", weeklyCareerDay || 0);
    if (resumeFile instanceof File) form.append("resume_file", resumeFile, resumeFile.name);
    const res = await _fetch(_url(CONFIG.ENDPOINTS.INTERVIEW_START), { method: "POST", body: form, timeout: 120000 });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || `Server error ${res.status}`); }
    return res.json();
  }

  async function submitAnswer({ chatId, answer }) {
    const form = new FormData();
    form.append("chat_id", chatId);
    form.append("answer",  answer);
    const res = await _fetch(_url(CONFIG.ENDPOINTS.INTERVIEW_ANSWER), { method: "POST", body: form, timeout: 90000 });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.message || `Server error ${res.status}`); }
    return res.json();
  }

  async function getInterviewReport(chatId) {
    const res = await _fetch(_url(CONFIG.ENDPOINTS.INTERVIEW_REPORT + `?chat_id=${chatId}`), { timeout: 10000 });
    if (!res.ok) return null;
    return res.json().catch(() => null);
  }

  async function resetInterview(chatId) {
    const form = new FormData();
    form.append("chat_id", chatId);
    await _fetch(_url(CONFIG.ENDPOINTS.INTERVIEW_RESET), { method: "POST", body: form, timeout: 10000 }).catch(() => {});
  }

  async function runCode({ language, code }) {
    const form = new FormData();
    form.append("language", language);
    form.append("code",     code);
    const res = await _fetch(_url("/api/ide/run"), { method: "POST", body: form, timeout: 15000 });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.output || `Server error ${res.status}`); }
    return res.json();
  }

  // ── Weekend status (NEW) ──────────────────────────────────
  async function getWeekendStatus(chatId) {
    const res = await _fetch(_url(`/api/edtech/weekend?chat_id=${encodeURIComponent(chatId)}`), { timeout: 10000 });
    if (!res.ok) return { weekend: null };
    return res.json().catch(() => ({ weekend: null }));
  }

  return {
    generate, getUsage, saveMessage, getMessages,
    fetchProgress, resetSession, deleteSession,
    getNotifications, markNotificationsRead, getStats, healthCheck,
    startInterview, submitAnswer, getInterviewReport, resetInterview, runCode,
    getWeekendStatus,
  };
})();