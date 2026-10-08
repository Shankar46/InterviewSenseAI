// frontend/scripts/chat.js
// FIXED: _streamText() is now actually called after response.
// FIXED: Study uses ENDPOINTS.STUDY, Career uses ENDPOINTS.CAREER — no mixing.
// FIXED: Messages saved to DB after each turn for cross-device persistence.

const Chat = (() => {
  let isSending = false;

  const userInputEl = document.getElementById("user-input");
  const sendBtnEl   = document.getElementById("send-btn");

  // ── Send ──────────────────────────────────────────────────
  async function send(getCurrentMode, getCurrentTask, getCareerConfig) {
    if (isSending) return;

    const mode       = getCurrentMode();
    const task       = getCurrentTask();
    const chatId     = Store.currentId;
    const text       = userInputEl.value.trim();
    const attachment = Store.getAttachment(chatId);
    const file       = mode === "study" ? (attachment?.file || null) : null;
    const markMode   = document.getElementById("mode-select")?.value || "10 Marks";

    // Guards
    if (mode === "career" && !text) return;
    if (mode === "study"  && !text && !file) return;

    // Auto-title from first message
    const chat = Store.getCurrentChat();
    if (chat && chat.title === "New Chat" && text) {
      Store.setChatTitle(chatId, text.slice(0, 28) + (text.length > 28 ? "…" : ""));
    }

    isSending = true; sendBtnEl.disabled = true;

    const displayText = text || "📎 Document uploaded";
    Store.addMessage(chatId, "user", displayText);
    Store.addMessage(chatId, "assistant", "__loading__");
    UI.renderMessages(Store.getMessages(chatId), mode);
    userInputEl.value = ""; _autoResize(userInputEl);

    const history = Store.getHistorySlice(chatId, CONFIG.MAX_HISTORY_TURNS);

    try {
      let data;

      if (mode === "career") {
        // Career → always hits ENDPOINTS.CAREER
        data = await Api.generate({
          topic:         text,
          mode:          markMode,
          task:          "career",
          history,
          file:          null,
          assistantType: "career",
          careerConfig:  getCareerConfig(),
          chatId,
        });
      } else {
        // Study → always hits ENDPOINTS.STUDY
        data = await Api.generate({
          topic:         text,
          mode:          markMode,
          task,
          history,
          file,
          assistantType: "study",
          careerConfig:  null,
          chatId,
        });
      }

      Store.removeLoadingMessage(chatId);

      // Career returns data.text, study returns data.answer
      const responseText = mode === "career"
        ? (data.text   || "No response received.")
        : (data.answer || "No response received.");

      // Add empty slot then STREAM into it (actually wired up now)
      Store.addMessage(chatId, "assistant", "");
      await _streamText(chatId, responseText, mode);

      // Save completed assistant message to DB (for cross-device persistence)
      _persistMessage(chatId, "assistant", responseText);

      // Career-specific updates
      if (mode === "career") {
        if (data.tracker && Array.isArray(data.tracker)) {
          App.handleTrackerUpdate(data.tracker);
        }
        if (data.weekend) {
          App.handleWeekendInterview(data.weekend);
        }
      }

      // Study concept navigator
      if (mode === "study" && data.navigator) {
        UI.showConceptProgress(data.concept_number, data.total_concepts);
      }

    } catch (err) {
      console.error("[CHAT] Error:", err);
      Store.removeLoadingMessage(chatId);
      Store.addMessage(chatId, "assistant", `⚠️ ${err.message}`);
      UI.renderMessages(Store.getMessages(chatId), mode);
    } finally {
      isSending = false; sendBtnEl.disabled = false;
    }
  }

  // ── Streaming — actually called now ───────────────────────
  async function _streamText(chatId, text, mode) {
    if (!text) return;
    const msgs = Store.getMessages(chatId);
    const idx  = msgs.length - 1;
    if (idx < 0 || !msgs[idx]) return;

    // Adaptive chunking for performance
    const len       = text.length;
    const chunkSize = len > 3000 ? 16 : len > 1000 ? 8 : 4;
    const delay     = len > 3000 ? 6  : len > 1000 ? 12 : CONFIG.STREAM_DELAY_MS;

    let current = "";
    for (let i = 0; i < text.length; i += chunkSize) {
      current += text.substring(i, Math.min(i + chunkSize, text.length));
      msgs[idx].content = current;
      UI.renderMessages(msgs, mode, true); // skipScroll during stream
      await _delay(delay);
    }

    // Final render with full text + scroll to bottom
    msgs[idx].content = text;
    UI.renderMessages(Store.getMessages(chatId), mode, false);
  }

  // ── DB persistence (fire-and-forget) ─────────────────────
  function _persistMessage(chatId, role, content) {
    if (!content || content === "__loading__") return;
    Api.saveMessage(chatId, role, content).catch(() => {
      // Silently ignore — message is already in localStorage via Store
    });
  }

  function _delay(ms) { return new Promise(r => setTimeout(r, ms)); }

  function _autoResize(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }

  // ── Keyboard ──────────────────────────────────────────────
  function bindKeyboard(getCurrentMode, getCurrentTask, getCareerConfig) {
    userInputEl.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send(getCurrentMode, getCurrentTask, getCareerConfig);
      }
    });
    userInputEl.addEventListener("input", () => _autoResize(userInputEl));
  }

  // ── Download transcript ───────────────────────────────────
  function downloadTranscript(chatId) {
    const chat = Store.getChat(chatId);
    if (!chat || !chat.messages.length) {
      alert("This session has no messages to download."); return;
    }
    const sep = "=".repeat(60);
    let content = `InterviewSense AI — ${chat.title}\nExported: ${new Date().toLocaleString()}\n${sep}\n\n`;
    chat.messages.forEach(m => {
      if (m.content === "__loading__") return;
      content += `[${m.role.toUpperCase()}]\n${m.content}\n\n${"─".repeat(40)}\n\n`;
    });
    const blob = new Blob([content], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${chat.title.replace(/[^a-z0-9]/gi, "_")}_transcript.txt`;
    a.click(); URL.revokeObjectURL(a.href);
  }

  return { send, bindKeyboard, downloadTranscript };
})();