// frontend/scripts/chat.js
// Handles the send flow, streaming animation, and file download.

const Chat = (() => {
  let isSending = false;

  const userInputEl = document.getElementById("user-input");
  const sendBtnEl   = document.getElementById("send-btn");

  // ── Send ──────────────────────────────────────────────────
  async function send(getCurrentMode, getCurrentTask, getCareerConfig) {
    if (isSending) return;

    const text       = userInputEl.value.trim();
    const mode       = getCurrentMode();     // 'study' | 'career'
    const task       = getCurrentTask();     // 'notes' | 'assignment' | etc.
    const chatId     = Store.currentId;
    const attachment = Store.getAttachment(chatId);
    const file       = mode === "study" ? attachment?.file || null : null;
    const config     = mode === "career" ? getCareerConfig() : null;
    const markMode   = document.getElementById("mode-select")?.value || "10 Marks";

    if (mode === "career" && !text) return;
    if (!text && !file && mode !== "career") return;

    // Auto-title
    const chat = Store.getCurrentChat();
    if (chat && (chat.title === "New Chat") && text) {
      Store.setChatTitle(chatId, text.slice(0, 24) + (text.length > 24 ? "…" : ""));
    }

    isSending = true;
    sendBtnEl.disabled = true;

    const displayText = text || "📎 Document uploaded";
    Store.addMessage(chatId, "user", displayText);
    Store.addMessage(chatId, "assistant", "__loading__");
    UI.renderMessages(Store.getMessages(chatId), mode);
    userInputEl.value = "";
    _autoResize(userInputEl);

    const history = Store.getHistorySlice(chatId, CONFIG.MAX_HISTORY_TURNS);

    try {
      const data = await Api.generate({
        topic:         text,
        mode:          markMode,
        task:          mode === "study" ? task : "career",
        history,
        file,
        assistantType: mode,
        careerConfig:  config,
        chatId,
      });

      Store.removeLoadingMessage(chatId);

      const responseText = data.text || data.answer || "No response received.";
      console.log("[CHAT] Response received:", { 
        text_length: responseText.length, 
        has_text: !!data.text, 
        has_answer: !!data.answer,
        text_preview: responseText.substring(0, 100)
      });
      
      // Add message and start streaming
      Store.addMessage(chatId, "assistant", responseText);
      console.log("[CHAT] Message added to store, rendering...");
      UI.renderMessages(Store.getMessages(chatId), mode);
      console.log("[CHAT] Message rendered");

      if (data.tracker && Array.isArray(data.tracker) && mode === "career") {
        App.handleTrackerUpdate(data.tracker);
      }

    } catch (err) {
      console.error("[CHAT] Error:", err);
      Store.removeLoadingMessage(chatId);
      Store.addMessage(chatId, "assistant", `⚠️ ${err.message}`);
      UI.renderMessages(Store.getMessages(chatId), mode);
    } finally {
      isSending = false;
      sendBtnEl.disabled = false;
    }
  }

  // ── Streaming animation ───────────────────────────────────
  async function _streamText(chatId, text, mode) {
    if (!text) {
      console.warn("[CHAT] No text to stream");
      return;
    }

    const msgs = Store.getMessages(chatId);
    const idx  = msgs.length - 1;
    
    if (idx < 0 || !msgs[idx]) {
      console.error("[CHAT] Message not found for streaming");
      return;
    }

    // Stream in chunks (not character by character) for better performance
    const CHUNK_SIZE = 5; // stream 5 chars at a time
    let current = "";

    for (let i = 0; i < text.length; i += CHUNK_SIZE) {
      const chunk = text.substring(i, Math.min(i + CHUNK_SIZE, text.length));
      current += chunk;
      msgs[idx].content = current;
      UI.renderMessages(Store.getMessages(chatId), mode);
      await _delay(CONFIG.STREAM_DELAY_MS);
    }
    
    // Final render with complete text
    msgs[idx].content = text;
    UI.renderMessages(Store.getMessages(chatId), mode);
    console.log("[CHAT] Streaming complete, message length:", text.length);
  }

  function _delay(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

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
      alert("This session has no messages to download.");
      return;
    }
    const sep = "=".repeat(50);
    let content = `InterviewSense AI — ${chat.title}\n${sep}\n\n`;
    chat.messages.forEach(m => {
      content += `[${m.role.toUpperCase()}]\n${m.content}\n\n${"-".repeat(40)}\n`;
    });
    const blob = new Blob([content], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${chat.title.replace(/[^a-z0-9]/gi, "_")}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return { send, bindKeyboard, downloadTranscript };
})();
