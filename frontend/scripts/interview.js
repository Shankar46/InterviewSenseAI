// frontend/scripts/interview.js
// Interview Assistant — full UI controller.
// Manages setup, question rendering, feedback cards, and final report.

const Interview = (() => {
  // ── Internal state ─────────────────────────────────────────
  let _isActive    = false;
  let _currentQNum = 0;
  let _totalQ      = 0;
  let _scores      = [];
  let _resumeFile  = null;   // File object from upload zone
  let _isFullscreenRequired = false;
  let _voiceMuted = false;
  let _recognition = null;
  let _isListening = false;

  // ── Getters ───────────────────────────────────────────────
  function _getConfig() {
    const weeklyCareerDay = sessionStorage.getItem("weekly_interview_career_day");
    if (weeklyCareerDay !== null) {
      sessionStorage.removeItem("weekly_interview_career_day");
    }
    return {
      role:       (document.getElementById("ic-role")?.value    || "").trim() || "Software Engineer",
      company:    (document.getElementById("ic-company")?.value || "").trim() || "the company",
      jdText:     (document.getElementById("ic-jd")?.value      || "").trim(),
      resumeFile: _resumeFile,   // File object (may be null)
      domain:     document.getElementById("ic-domain")?.value || "it",
      roundType:  document.getElementById("ic-round")?.value || "tech",
      weeklyCareerDay: weeklyCareerDay ? parseInt(weeklyCareerDay, 10) : 0,
    };
  }

  // ── Upload zone wiring ──────────────────────────────────────────
  function initUploadZone() {
    const zone      = document.getElementById("ic-upload-zone");
    const fileInput = document.getElementById("ic-resume-file");
    const browseBtn = document.getElementById("ic-browse-btn");
    const clearBtn  = document.getElementById("ic-file-clear");
    if (!zone || !fileInput) return;

    // Click zone or browse button to open picker
    zone.addEventListener("click", e => {
      if (e.target === clearBtn || clearBtn?.contains(e.target)) return;
      fileInput.click();
    });
    if (browseBtn) browseBtn.addEventListener("click", e => { e.stopPropagation(); fileInput.click(); });

    // File selected via picker
    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) _setResumeFile(fileInput.files[0]);
    });

    // Clear button
    if (clearBtn) clearBtn.addEventListener("click", e => {
      e.stopPropagation();
      _clearResumeFile();
      fileInput.value = "";
    });

    // Drag-and-drop
    zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", ()  => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", e => {
      e.preventDefault();
      zone.classList.remove("drag-over");
      const f = e.dataTransfer?.files[0];
      if (f) { _setResumeFile(f); fileInput.value = ""; }
    });
  }

  function _setResumeFile(file) {
    _resumeFile = file;
    const prompt   = document.getElementById("ic-upload-prompt");
    const selected = document.getElementById("ic-file-selected");
    const nameEl   = document.getElementById("ic-file-name");
    if (prompt)   prompt.style.display   = "none";
    if (selected) selected.style.display = "flex";
    if (nameEl)   nameEl.textContent     = file.name;
  }

  function _clearResumeFile() {
    _resumeFile = null;
    const prompt   = document.getElementById("ic-upload-prompt");
    const selected = document.getElementById("ic-file-selected");
    if (prompt)   prompt.style.display   = "flex";
    if (selected) selected.style.display = "none";
  }

  // ── Start interview ────────────────────────────────────────
  async function start() {
    const config  = _getConfig();
    const chatId  = Store.currentId;
    const startBtn = document.getElementById("ic-start-btn");

    if (!config.role) {
      UI.showToast("Please enter a target role.", "warning");
      return;
    }

    const userApiKey = localStorage.getItem("user_hf_api_key");
    if (config.weeklyCareerDay > 0 && !userApiKey) {
      UI.showToast("A personal Hugging Face API key is required to take weekly milestone evaluations.", "warning");
      const modal = document.getElementById("api-key-modal");
      if (modal) {
        modal.style.display = "flex";
        const keyInput = document.getElementById("modal-hf-key");
        if (keyInput) keyInput.focus();
      }
      return;
    }

    if (!userApiKey) {
      UI.showToast("Running in Demo Mode (limited to 3 questions).", "info");
    }

    if (!config.resumeFile && !config.jdText) {
      UI.showToast("Please upload a resume or paste a JD for better questions.", "warning");
      // Don't block — let them proceed without
    }

    // Request fullscreen immediately synchronously under user click event handler
    _enterFullscreen();

    // Disable button, show loading
    if (startBtn) { startBtn.disabled = true; startBtn.textContent = "⏳ Generating questions…"; }

    // Show loading placeholder
    Store.clearMessages(chatId);
    Store.addMessage(chatId, "assistant", "__loading__");
    _renderInterviewMessages(Store.getMessages(chatId));

    try {
      const data = await Api.startInterview({
        chatId,
        role:       config.role,
        company:    config.company,
        jdText:     config.jdText,
        resumeFile: config.resumeFile,   // File object or null
        domain:     config.domain,
        roundType:  config.roundType,
        weeklyCareerDay: config.weeklyCareerDay,
      });

      Store.removeLoadingMessage(chatId);
      _isActive    = true;
      _currentQNum = 1;
      _totalQ      = data.total || 10;
      _scores      = [];

      // Collapse config bar, show progress
      _collapseConfig(config.role, config.company);
      _updateProgress();

      // Show IDE and Toggle button if IT + Tech round
      _setupIDE(config.domain, config.roundType);

      // Persist welcome + first question
      Store.addMessage(chatId, "assistant", `__IQ__${JSON.stringify({
        type: "welcome", text: data.message,
      })}`);
      Store.addMessage(chatId, "assistant", `__IQ__${JSON.stringify({
        question: data.question,
        q_type:   data.q_type,
        q_num:    1,
        total:    data.total,
      })}`);

      _renderInterviewMessages(Store.getMessages(chatId));
      _speakText(data.message + ". " + data.question);

    } catch (err) {
      // Revert fullscreen on failure
      _exitFullscreen();
      Store.removeLoadingMessage(chatId);
      Store.addMessage(chatId, "assistant", `⚠️ ${err.message}`);
      _renderInterviewMessages(Store.getMessages(chatId));
      UI.showToast("Failed to start interview.", "error");
    } finally {
      if (startBtn) { startBtn.disabled = false; startBtn.textContent = "🎯 Start Mock Interview"; }
    }
  }

  // ── Submit answer ─────────────────────────────────────────────
  async function send() {
    _stopSpeechRecognition();
    if (!_isActive) {
      UI.showToast("Fill in the form above and click 'Start Mock Interview' first.", "warning");
      return;
    }

    const answerEl = document.getElementById("iw-answer-input");
    const answer   = answerEl?.value.trim();
    if (!answer) return;

    const chatId  = Store.currentId;
    const sendBtn = document.getElementById("iw-send-btn");
    if (sendBtn) sendBtn.disabled = true;

    Store.addMessage(chatId, "user", answer);
    Store.addMessage(chatId, "assistant", "__loading__");
    _renderInterviewMessages(Store.getMessages(chatId));
    if (answerEl) answerEl.value = "";

    try {
      const data = await Api.submitAnswer({ chatId, answer });
      Store.removeLoadingMessage(chatId);

      const fb = data.feedback || {};
      _scores.push(fb.score || 0);

      // Persist feedback
      Store.addMessage(chatId, "assistant", `__IF__${JSON.stringify({
        score:        fb.score,
        strengths:    fb.strengths,
        gaps:         fb.gaps,
        model_answer: fb.model_answer,
        overall:      fb.overall,
        q_num:        data.q_num,
        total:        data.total,
      })}`);

      if (data.status === "feedback_and_next") {
        _currentQNum = data.next_q_num;
        Store.addMessage(chatId, "assistant", `__IQ__${JSON.stringify({
          question: data.next_question,
          q_type:   data.next_q_type,
          q_num:    data.next_q_num,
          total:    data.total,
        })}`);
        _updateProgress();
        _speakText(data.next_question);

      } else if (data.status === "feedback_and_complete") {
        const report = data.report || {};
        Store.addMessage(chatId, "assistant", `__IR__${JSON.stringify(report)}`);
        _isActive = false;
        _showCompletionBadge();
        _exitFullscreen();
        _speakText("The mock interview is complete. Generating your performance report card.");
      }

      _renderInterviewMessages(Store.getMessages(chatId));

    } catch (err) {
      Store.removeLoadingMessage(chatId);
      Store.addMessage(chatId, "assistant", `⚠️ ${err.message}`);
      _renderInterviewMessages(Store.getMessages(chatId));
      UI.showToast("Evaluation failed. Please try again.", "error");
    } finally {
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  // ── Render interview messages ──────────────────────────────
  function renderMessages(messages) {
    // Restore active state from stored messages on page refresh
    const feedbackMsgs = messages.filter(m => m.content?.startsWith("__IF__"));
    _scores = feedbackMsgs.map(m => {
      try { return JSON.parse(m.content.slice(6)).score || 0; } catch { return 0; }
    });

    const hasReport = messages.some(m => m.content?.startsWith("__IR__"));
    const lastQMsg  = [...messages].reverse().find(
      m => m.content?.startsWith("__IQ__") && !m.content.includes('"type":"welcome"')
    );
    if (lastQMsg && !hasReport) {
      try {
        const d = JSON.parse(lastQMsg.content.slice(6));
        _currentQNum = d.q_num;
        _totalQ      = d.total;
        _isActive    = true;
        _collapseConfig(
          document.getElementById("ic-role")?.value || "",
          document.getElementById("ic-company")?.value || ""
        );
        _updateProgress();

        // Restore IDE state if IT + Tech
        const domain = document.getElementById("ic-domain")?.value || "it";
        const round = document.getElementById("ic-round")?.value || "tech";
        _setupIDE(domain, round);

        _enterFullscreen();
      } catch { /* ignore */ }
    }
    if (hasReport) {
      _isActive = false;
      _showCompletionBadge();
      _setupIDE("none", "none");
      _exitFullscreen();
    }

    _renderInterviewMessages(messages);
  }

  function _renderInterviewMessages(messages) {
    const wrap = document.getElementById("messages-wrap");
    if (!wrap) return;
    wrap.innerHTML = "";

    if (!messages || messages.length === 0) {
      wrap.appendChild(_buildEmptyState());
      return;
    }

    messages.forEach((m, idx) => {
      const el = _buildMessageEl(m, idx);
      if (el) wrap.appendChild(el);
    });

    wrap.scrollTop = wrap.scrollHeight;
  }

  function _buildMessageEl(m, idx) {
    if (m.content === "__loading__") {
      const div = document.createElement("div");
      div.className = "msg assistant";
      div.innerHTML = `<div class="bubble">${_buildSkeleton()}</div>`;
      return div;
    }

    if (m.role === "user") {
      const div = document.createElement("div");
      div.className = "msg user";
      div.style.animationDelay = `${Math.min(idx * 0.04, 0.4)}s`;
      div.innerHTML = `<div class="bubble">${_esc(m.content)}</div>`;
      return div;
    }

    if (m.content?.startsWith("__IQ__")) {
      try {
        const data = JSON.parse(m.content.slice(6));
        if (data.type === "welcome") return _buildWelcomeCard(data.text);
        return _buildQuestionCard(data);
      } catch { return null; }
    }

    if (m.content?.startsWith("__IF__")) {
      try { return _buildFeedbackCard(JSON.parse(m.content.slice(6))); } catch { return null; }
    }

    if (m.content?.startsWith("__IR__")) {
      try { return _buildReportCard(JSON.parse(m.content.slice(6))); } catch { return null; }
    }

    // Fallback: plain assistant message
    const div = document.createElement("div");
    div.className = "msg assistant";
    div.style.animationDelay = `${Math.min(idx * 0.04, 0.4)}s`;
    div.innerHTML = `<div class="bubble">${_esc(m.content)}</div>`;
    return div;
  }

  // ── Card builders ──────────────────────────────────────────
  function _buildEmptyState() {
    const d = document.createElement("div");
    d.className = "empty-state";
    d.innerHTML = `
      <div class="empty-icon">🎯</div>
      <div class="empty-title">Ready for your mock interview</div>
      <div class="empty-sub">
        Fill in your role, company, JD and resume above —<br>
        then click <b>Start Mock Interview</b>
      </div>`;
    return d;
  }

  function _buildWelcomeCard(text) {
    const div = document.createElement("div");
    div.className = "msg assistant iw-welcome-wrap";
    let html = text || "";
    if (window.marked && typeof marked.parse === "function") html = marked.parse(text);
    div.innerHTML = `<div class="bubble iw-welcome">${html}</div>`;
    return div;
  }

  function _buildQuestionCard(data) {
    const types = {
      company: { label: "Company Fit",    emoji: "🏢", cls: "iq-company" },
      jd:      { label: "Job Description",emoji: "📄", cls: "iq-jd"      },
      resume:  { label: "Your Experience",emoji: "👤", cls: "iq-resume"  },
      career:  { label: "Daily Study",    emoji: "📚", cls: "iq-career"  },
      coding:  { label: "Coding Task",    emoji: "💻", cls: "iq-coding"  },
    };
    const t = types[data.q_type] || types.jd;

    const div = document.createElement("div");
    div.className = "iw-question-wrap";
    div.innerHTML = `
      <div class="iw-q-meta">
        <span class="iq-badge ${t.cls}">${t.emoji} ${t.label}</span>
        <span class="iq-counter">Question ${data.q_num} of ${data.total}</span>
      </div>
      <div class="iw-q-card">
        <div class="iw-q-num">Q${data.q_num}</div>
        <div class="iw-q-text">${_esc(data.question)}</div>
      </div>`;
    return div;
  }

  function _buildFeedbackCard(fb) {
    const score = fb.score ?? 0;
    const sc    = score >= 8 ? "score-high" : score >= 6 ? "score-mid" : "score-low";
    const label = score >= 8 ? "Excellent" : score >= 6 ? "Good" : score >= 4 ? "Average" : "Needs Work";

    const div = document.createElement("div");
    div.className = "iw-feedback-card";
    div.innerHTML = `
      <div class="iw-fb-header">
        <div class="iw-fb-score-wrap">
          <div class="iw-fb-score ${sc}">${score}<span>/10</span></div>
          <div class="iw-fb-label ${sc}">${label}</div>
        </div>
        <div class="iw-fb-verdict">${_esc(fb.overall || "")}</div>
      </div>
      <div class="iw-fb-body">
        ${fb.strengths ? `
        <div class="iw-fb-section iw-fb-good">
          <span class="iw-fb-icon">✅</span>
          <div><strong>Strengths</strong><p>${_esc(fb.strengths)}</p></div>
        </div>` : ""}
        ${fb.gaps ? `
        <div class="iw-fb-section iw-fb-bad">
          <span class="iw-fb-icon">⚠️</span>
          <div><strong>What was missing</strong><p>${_esc(fb.gaps)}</p></div>
        </div>` : ""}
        ${fb.model_answer ? `
        <details class="iw-fb-model">
          <summary>💡 See model answer</summary>
          <div class="iw-fb-model-body">${_esc(fb.model_answer)}</div>
        </details>` : ""}
      </div>`;
    return div;
  }

  function _buildReportCard(report) {
    if (!report || report.status === "report_empty" || report.status === "error") {
      const d = document.createElement("div");
      d.className = "msg assistant";
      d.innerHTML = `<div class="bubble">⚠️ ${_esc(report?.message || "No data available.")}</div>`;
      return d;
    }

    const avg = report.avg_score || 0;
    const sc  = avg >= 8 ? "score-high" : avg >= 6 ? "score-mid" : "score-low";

    const typeEmojis  = { company: "🏢", jd: "📄", resume: "👤", career: "📚" };
    const typeLabels  = { company: "Company Fit", jd: "Technical", resume: "Experience", career: "Daily Study" };

    let typeBars = "";
    for (const [type, avg_t] of Object.entries(report.type_averages || {})) {
      const pct = Math.round((avg_t / 10) * 100);
      const bsc = avg_t >= 8 ? "score-high" : avg_t >= 6 ? "score-mid" : "score-low";
      typeBars += `
        <div class="ir-type-row">
          <span class="ir-type-label">${typeEmojis[type] || "•"} ${typeLabels[type] || type}</span>
          <div class="ir-type-bar-wrap">
            <div class="ir-type-bar"><div class="ir-type-fill ${bsc}" style="width:${pct}%"></div></div>
          </div>
          <span class="ir-type-score ${bsc}">${avg_t}/10</span>
        </div>`;
    }

    let breakdown = "";
    for (const q of (report.breakdown || [])) {
      const qs  = q.score || 0;
      const qsc = qs >= 8 ? "score-high" : qs >= 6 ? "score-mid" : "score-low";
      breakdown += `
        <div class="ir-breakdown-row">
          <span class="ir-bq-num">Q${q.q_num}</span>
          <span class="ir-bq-text" title="${_esc(q.question)}">
            ${_esc(q.question.length > 70 ? q.question.slice(0, 70) + "…" : q.question)}
          </span>
          <span class="ir-bq-score ${qsc}">${qs}/10</span>
        </div>`;
    }

    const chatId = Store.currentId;
    const div = document.createElement("div");
    div.className = "iw-report-card";
    div.innerHTML = `
      <div class="ir-header">
        <div class="ir-crown">🏆</div>
        <div class="ir-title">Interview Complete</div>
        <div class="ir-subtitle">${_esc(report.role || "")} @ ${_esc(report.company || "")}</div>
      </div>
 
      <div class="ir-score-section">
        <div class="ir-big-score ${sc}">
          ${avg}<span class="ir-score-denom">/10</span>
        </div>
        <div class="ir-score-meta">
          <div class="ir-score-label">Overall Score</div>
          <div class="ir-score-detail">
            ${report.total_questions} questions ·
            <span style="color:var(--teal)">${report.strong_count} strong</span> ·
            <span style="color:var(--red)">${report.weak_count} needs work</span>
          </div>
        </div>
      </div>

      ${report.overall_feedback ? `
      <div class="ir-feedback-section">
        <h4>Performance Review</h4>
        <p class="ir-feedback-text">${_esc(report.overall_feedback)}</p>
      </div>` : ""}

      ${report.improvement_areas && report.improvement_areas.length > 0 ? `
      <div class="ir-improvements-section">
        <h4>Key Areas to Focus &amp; Update</h4>
        <ul class="ir-improvements-list">
          ${report.improvement_areas.map(item => `<li>${_esc(item)}</li>`).join("")}
        </ul>
      </div>` : ""}
 
      ${typeBars ? `<div class="ir-type-section"><h4>Performance by Category</h4>${typeBars}</div>` : ""}
      ${breakdown ? `<div class="ir-breakdown"><h4>Question Breakdown</h4>${breakdown}</div>` : ""}

      <div class="ir-footer">
        <button class="ir-restart-btn" id="ir-restart-btn-${chatId}" type="button">↺ Start New Interview</button>
      </div>`;

    // Wire restart button after insertion
    setTimeout(() => {
      const btn = document.getElementById(`ir-restart-btn-${chatId}`);
      if (btn) btn.onclick = () => resetAndRestart();
    }, 0);

    return div;
  }

  // ── Utility DOM builders ───────────────────────────────────
  function _buildSkeleton() {
    return `<div class="skeleton-wrap">
      <div class="skeleton-line" style="width:85%"></div>
      <div class="skeleton-line" style="width:65%"></div>
      <div class="skeleton-line" style="width:70%"></div>
    </div>`;
  }

  function _esc(str) {
    return (str || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── Progress & config helpers ──────────────────────────────
  function _collapseConfig(role, company) {
    const bar   = document.getElementById("interview-config-bar");
    const label = document.getElementById("ic-session-label");
    const prog  = document.getElementById("interview-progress");
    if (bar)   bar.classList.add("collapsed");
    if (label) label.textContent = `${role || "Interview"} @ ${company || "Company"}`;
    if (prog)  prog.style.display = "flex";
  }

  function _updateProgress() {
    const fill    = document.getElementById("ip-fill");
    const label   = document.getElementById("ip-label");
    const scoreEl = document.getElementById("ip-score");

    const answeredCount = Math.max(0, _currentQNum - 1);
    const pct = _totalQ > 0 ? (answeredCount / _totalQ) * 100 : 0;
    if (fill)  { fill.style.width = pct + "%"; }
    if (label) { label.textContent = `Q${_currentQNum} / ${_totalQ}`; }
    if (scoreEl && _scores.length > 0) {
      const avg = (_scores.reduce((a, b) => a + b, 0) / _scores.length).toFixed(1);
      scoreEl.textContent = `Avg: ${avg}/10`;
    }
  }

  function _showCompletionBadge() {
    const fill  = document.getElementById("ip-fill");
    const label = document.getElementById("ip-label");
    if (fill)  { fill.style.width = "100%"; fill.classList.add("ip-complete"); }
    if (label) { label.textContent = "✅ Complete"; }
  }

  // ── Reset ──────────────────────────────────────────────────
  function resetAndRestart() {
    _stopSpeechRecognition();
    window.speechSynthesis.cancel();
    _isActive    = false;
    _currentQNum = 0;
    _totalQ      = 0;
    _scores      = [];
    _exitFullscreen();
    _clearResumeFile();
    const fileInput = document.getElementById("ic-resume-file");
    if (fileInput) fileInput.value = "";

    const bar  = document.getElementById("interview-config-bar");
    const prog = document.getElementById("interview-progress");
    const fill = document.getElementById("ip-fill");
    if (bar)  bar.classList.remove("collapsed");
    if (prog) prog.style.display = "none";
    if (fill) { fill.style.width = "0%"; fill.classList.remove("ip-complete"); }

    // Reset IDE
    _setupIDE("none", "none");
    const ideCode = document.getElementById("ide-code");
    if (ideCode) ideCode.value = "";
    const consoleOut = document.getElementById("ide-console-output");
    if (consoleOut) consoleOut.textContent = "No code executed yet.";

    const chatId = Store.currentId;
    Api.resetInterview(chatId).catch(() => {});
    Store.clearMessages(chatId);
    _renderInterviewMessages([]);
  }

  function _setupIDE(domain, roundType) {
    const ide = document.getElementById("ide-panel");
    const toggleBtn = document.getElementById("ide-toggle-btn");
    if (domain === "it" && roundType === "tech") {
      if (ide) ide.style.display = "flex";
      if (toggleBtn) {
        toggleBtn.style.display = "inline-block";
        toggleBtn.classList.add("active");
      }
      // Load default template
      const ideCode = document.getElementById("ide-code");
      const ideLang = document.getElementById("ide-lang")?.value || "python";
      if (ideCode && !ideCode.value.trim()) {
        ideCode.value = _getDefaultTemplate(ideLang);
      }
    } else {
      if (ide) ide.style.display = "none";
      if (toggleBtn) {
        toggleBtn.style.display = "none";
        toggleBtn.classList.remove("active");
      }
    }
  }

  function _getDefaultTemplate(lang) {
    if (lang === "python") {
      return `# Write your Python solution here\n\ndef solve():\n    # code goes here\n    pass\n\nsolve()\n`;
    } else if (lang === "javascript") {
      return `// Write your JavaScript solution here\n\nfunction solve() {\n    // code goes here\n}\n\nsolve();\n`;
    } else if (lang === "java") {
      return `// Write your Java solution here\n\npublic class Solution {\n    public static void main(String[] args) {\n        // code goes here\n    }\n}\n`;
    } else if (lang === "cpp") {
      return `// Write your C++ solution here\n\n#include <iostream>\nusing namespace std;\n\nint main() {\n    // code goes here\n    return 0;\n}\n`;
    }
    return `// Write your code here\n`;
  }

  function initIDE() {
    const runBtn = document.getElementById("ide-run-btn");
    const copyBtn = document.getElementById("ide-copy-to-chat");
    const langSelect = document.getElementById("ide-lang");
    const ideCode = document.getElementById("ide-code");
    const consoleOut = document.getElementById("ide-console-output");

    if (runBtn) {
      runBtn.onclick = async () => {
        if (!ideCode) return;
        const code = ideCode.value;
        const language = langSelect?.value || "python";
        if (consoleOut) consoleOut.textContent = "⏳ Running code...";
        runBtn.disabled = true;
        runBtn.textContent = "Running...";
        try {
          const res = await Api.runCode({ language, code });
          if (consoleOut) consoleOut.textContent = res.output;
        } catch (err) {
          if (consoleOut) consoleOut.textContent = "Execution Error: " + err.message;
        } finally {
          runBtn.disabled = false;
          runBtn.textContent = "Run Code";
        }
      };
    }

    if (copyBtn) {
      copyBtn.onclick = () => {
        if (!ideCode) return;
        const code = ideCode.value;
        const lang = langSelect?.value || "python";
        const answerEl = document.getElementById("iw-answer-input");
        if (answerEl) {
          const codeBlock = `\n\`\`\`${lang}\n${code}\n\`\`\`\n`;
          answerEl.value += codeBlock;
          answerEl.focus();
          UI.showToast("Code copied to answer box!", "info");
        }
      };
    }

    if (langSelect && ideCode) {
      langSelect.onchange = () => {
        ideCode.value = _getDefaultTemplate(langSelect.value);
      };
    }

    // Add paste blocker on mock interview answer textarea
    const iwAnswerEl = document.getElementById("iw-answer-input");
    if (iwAnswerEl) {
      iwAnswerEl.addEventListener("paste", e => {
        e.preventDefault();
        UI.showToast("Paste is disabled in Interview Assistant to ensure genuine learning.", "warning");
      });
    }

    // Fullscreen event listeners
    document.addEventListener("fullscreenchange", _updateFullscreenOverlay);
    document.addEventListener("webkitfullscreenchange", _updateFullscreenOverlay);
    document.addEventListener("mozfullscreenchange", _updateFullscreenOverlay);
    document.addEventListener("MSFullscreenChange", _updateFullscreenOverlay);

    const fsResumeBtn = document.getElementById("fs-resume-btn");
    if (fsResumeBtn) {
      fsResumeBtn.onclick = () => {
        _enterFullscreen();
      };
    }
  }

  function _enterFullscreen() {
    _isFullscreenRequired = true;
    const docEl = document.documentElement;
    if (docEl.requestFullscreen) {
      docEl.requestFullscreen().catch(() => {});
    } else if (docEl.webkitRequestFullscreen) {
      docEl.webkitRequestFullscreen().catch(() => {});
    } else if (docEl.mozRequestFullScreen) {
      docEl.mozRequestFullScreen().catch(() => {});
    } else if (docEl.msRequestFullscreen) {
      docEl.msRequestFullscreen().catch(() => {});
    }
    _updateFullscreenOverlay();
  }

  function _exitFullscreen() {
    _isFullscreenRequired = false;
    if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    } else if (document.webkitExitFullscreen) {
      document.webkitExitFullscreen().catch(() => {});
    } else if (document.mozCancelFullScreen) {
      document.mozCancelFullScreen().catch(() => {});
    } else if (document.msExitFullscreen) {
      document.msExitFullscreen().catch(() => {});
    }
    _updateFullscreenOverlay();
  }

  function _updateFullscreenOverlay() {
    const isFS = document.fullscreenElement || 
                 document.webkitFullscreenElement || 
                 document.mozFullScreenElement || 
                 document.msFullscreenElement;
                 
    const overlay = document.getElementById("fullscreen-lock-overlay");
    if (!overlay) return;
    
    if (_isFullscreenRequired && !isFS) {
      _stopSpeechRecognition();
      window.speechSynthesis.cancel();
      overlay.style.display = "flex";
      document.getElementById("fs-resume-btn")?.focus();
    } else {
      overlay.style.display = "none";
    }
  }

  // ── Speech Synthesis & Recognition ─────────────────────────
  function _speakText(text) {
    if (_voiceMuted) return;
    window.speechSynthesis.cancel();
    
    const cleaned = text
      .replace(/[\*\#\`\_\-\>]/g, "")
      .replace(/\[.*?\]/g, "")
      .replace(/\(.*?\)/g, "")
      .replace(/__IQ__/g, "")
      .replace(/__IF__/g, "")
      .replace(/__IR__/g, "")
      .replace(/\\n/g, " ")
      .trim();

    const utterance = new SpeechSynthesisUtterance(cleaned);
    const voices = window.speechSynthesis.getVoices();
    const enVoice = voices.find(v => v.lang.startsWith("en"));
    if (enVoice) utterance.voice = enVoice;
    
    window.speechSynthesis.speak(utterance);
  }

  function _initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    
    _recognition = new SpeechRecognition();
    _recognition.continuous = false;
    _recognition.interimResults = true;
    _recognition.lang = "en-US";

    _recognition.onstart = () => {
      _isListening = true;
      const micBtn = document.getElementById("iw-mic-btn");
      if (micBtn) {
        micBtn.classList.add("listening");
        micBtn.textContent = "🛑";
      }
      const statusBar = document.getElementById("iw-mic-status");
      if (statusBar) statusBar.style.display = "flex";
    };

    _recognition.onresult = event => {
      let interimTranscript = "";
      let finalTranscript = "";

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }

      const answerEl = document.getElementById("iw-answer-input");
      if (answerEl) {
        const currentVal = answerEl.value;
        if (finalTranscript) {
          answerEl.value = (currentVal + " " + finalTranscript).trim();
        }
      }
    };

    _recognition.onerror = event => {
      console.error("Speech recognition error:", event.error);
      if (event.error === "not-allowed") {
        UI.showToast("Microphone access denied. Please grant permission in browser settings.", "error");
      }
      _stopSpeechRecognition();
    };

    _recognition.onend = () => {
      _isListening = false;
      const micBtn = document.getElementById("iw-mic-btn");
      if (micBtn) {
        micBtn.classList.remove("listening");
        micBtn.textContent = "🎙️";
      }
      const statusBar = document.getElementById("iw-mic-status");
      if (statusBar) statusBar.style.display = "none";
    };
  }

  function _toggleSpeechRecognition() {
    if (!_recognition) {
      _initSpeechRecognition();
    }
    if (!_recognition) {
      UI.showToast("Speech Recognition is not supported in this browser. Please use Chrome or Edge.", "warning");
      return;
    }

    if (_isListening) {
      _stopSpeechRecognition();
    } else {
      window.speechSynthesis.cancel();
      try {
        _recognition.start();
      } catch (e) {
        console.error("Failed to start speech recognition:", e);
      }
    }
  }

  function _stopSpeechRecognition() {
    if (_recognition && _isListening) {
      _recognition.stop();
    }
  }

  function stopVoice() {
    _stopSpeechRecognition();
    window.speechSynthesis.cancel();
  }

  function initVoiceToggle() {
    const btn = document.getElementById("voice-toggle-btn");
    if (!btn) return;
    
    const saved = localStorage.getItem("user_interview_voice_muted");
    if (saved === "true") {
      _voiceMuted = true;
      btn.textContent = "🔇 Voice: Off";
      btn.classList.add("muted");
    } else {
      _voiceMuted = false;
      btn.textContent = "🔊 Voice: On";
      btn.classList.remove("muted");
    }
    
    btn.onclick = () => {
      _voiceMuted = !_voiceMuted;
      if (_voiceMuted) {
        btn.textContent = "🔇 Voice: Off";
        btn.classList.add("muted");
        localStorage.setItem("user_interview_voice_muted", "true");
        window.speechSynthesis.cancel();
      } else {
        btn.textContent = "🔊 Voice: On";
        btn.classList.remove("muted");
        localStorage.setItem("user_interview_voice_muted", "false");
        const wrap = document.getElementById("messages-wrap");
        if (wrap) {
          const qTextEl = wrap.querySelector(".iw-q-text");
          if (qTextEl) {
            _speakText(qTextEl.textContent);
          }
        }
      }
    };
  }

  function initMicButton() {
    const micBtn = document.getElementById("iw-mic-btn");
    if (micBtn) {
      micBtn.onclick = () => _toggleSpeechRecognition();
    }
  }

  return { start, send, renderMessages, resetAndRestart, initUploadZone, initIDE, initVoiceToggle, initMicButton, stopVoice };
})();
