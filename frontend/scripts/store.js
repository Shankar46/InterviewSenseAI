// frontend/scripts/store.js
// Persistent, mode-scoped chat store.
// All mutations are automatically saved to localStorage.

const Store = (() => {
  const LS_KEY = "isai-chats-v2";

  // ── Internal state ───────────────────────────────────────
  let chats = {};           // { [chatId]: { title, mode, messages, attachmentName } }
  let currentChatId = null;

  // ── Persistence ──────────────────────────────────────────
  function _save() {
    try {
      // We cannot serialise File objects — strip them down to names only
      const serialisable = {};
      Object.keys(chats).forEach(id => {
        const c = chats[id];
        serialisable[id] = {
          title:          c.title,
          mode:           c.mode,
          messages:       c.messages.filter(m => m.content !== "__loading__"),
          attachmentName: c.attachment ? c.attachment.name : (c.attachmentName || null),
        };
      });
      localStorage.setItem(LS_KEY, JSON.stringify({ chats: serialisable, currentChatId }));
    } catch (e) {
      console.warn("[Store] localStorage save failed:", e);
    }
  }

  function _load() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data && data.chats) {
        // Rehydrate — attachment File objects are gone after refresh (correct browser behaviour)
        Object.keys(data.chats).forEach(id => {
          const c = data.chats[id];
          chats[id] = {
            title:          c.title  || "New Chat",
            mode:           c.mode   || "study",
            messages:       Array.isArray(c.messages) ? c.messages : [],
            attachment:     null,          // File object lost on refresh
            attachmentName: c.attachmentName || null,
          };
        });
        currentChatId = data.currentChatId || null;
        // Validate currentChatId still exists
        if (currentChatId && !chats[currentChatId]) currentChatId = null;
      }
    } catch (e) {
      console.warn("[Store] localStorage load failed:", e);
    }
  }

  // ── ID generator ─────────────────────────────────────────
  function _id() {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  // Initialise from persisted state
  _load();

  return {
    // ── Chats ───────────────────────────────────────────────
    createChat(mode) {
      // Reuse if the current chat (of same mode) is still empty
      if (
        currentChatId &&
        chats[currentChatId] &&
        chats[currentChatId].mode === mode &&
        chats[currentChatId].messages.length === 0
      ) {
        return currentChatId;
      }
      const id = _id();
      chats[id] = { title: "New Chat", mode: mode || "study", messages: [], attachment: null, attachmentName: null };
      currentChatId = id;
      _save();
      return id;
    },

    deleteChat(id) {
      const mode = chats[id]?.mode || "study";   // save mode before deletion
      const modeChats = Object.keys(chats).filter(k => chats[k].mode === mode);
      if (modeChats.length <= 1) return false;
      delete chats[id];
      if (currentChatId === id) {
        // Pick the most recent remaining chat of the same mode
        const remaining = Object.keys(chats).filter(k => chats[k].mode === mode);
        currentChatId = remaining.length ? remaining[remaining.length - 1] : Object.keys(chats).pop();
      }
      _save();
      return true;
    },

    selectChat(id) {
      if (chats[id]) { currentChatId = id; _save(); return true; }
      return false;
    },

    get currentId() { return currentChatId; },

    // Return all chat IDs for a given mode
    getChatsByMode(mode) {
      return Object.keys(chats).filter(id => chats[id].mode === mode);
    },

    // Return the most recent chat ID for a given mode (or null)
    getLatestChatForMode(mode) {
      const ids = Object.keys(chats).filter(id => chats[id].mode === mode);
      return ids.length ? ids[ids.length - 1] : null;
    },

    getChatIds() { return Object.keys(chats); },

    getChat(id) { return chats[id] || null; },

    getCurrentChat() { return chats[currentChatId] || null; },

    setChatTitle(id, title) {
      if (chats[id]) { chats[id].title = title; _save(); }
    },

    // ── Messages ────────────────────────────────────────────
    addMessage(chatId, role, content) {
      if (!chats[chatId]) return;
      chats[chatId].messages.push({ role, content });
      _save();
    },

    updateLastMessage(chatId, content) {
      const msgs = chats[chatId]?.messages;
      if (msgs && msgs.length) { msgs[msgs.length - 1].content = content; _save(); }
    },

    popLastMessage(chatId) {
      const msgs = chats[chatId]?.messages;
      if (msgs && msgs.length) { msgs.pop(); _save(); }
    },

    removeLoadingMessage(chatId) {
      const msgs = chats[chatId]?.messages;
      if (!msgs || !msgs.length) return;
      const idx = msgs.findLastIndex(m => m.role === "assistant" && m.content === "__loading__");
      if (idx !== -1) { msgs.splice(idx, 1); _save(); }
    },

    hasLoadingMessage(chatId) {
      return (chats[chatId]?.messages || []).some(m => m.content === "__loading__");
    },

    getMessages(chatId) {
      return chats[chatId]?.messages || [];
    },

    // History slice for backend (excludes loading placeholder)
    getHistorySlice(chatId, n) {
      return (chats[chatId]?.messages || [])
        .filter(m => m.content !== "__loading__")
        .slice(-n);
    },

    hasRoadmap(chatId) {
      return (chats[chatId]?.messages || []).some(m => m.content && m.content.includes("Roadmap"));
    },

    // ── Attachments ─────────────────────────────────────────
    setAttachment(chatId, file) {
      if (chats[chatId]) {
        chats[chatId].attachment     = file ? { file, name: file.name } : null;
        chats[chatId].attachmentName = file ? file.name : null;
        _save();
      }
    },

    getAttachment(chatId) {
      return chats[chatId]?.attachment || null;
    },

    getAttachmentName(chatId) {
      return chats[chatId]?.attachmentName || null;
    },

    // ── Utility ─────────────────────────────────────────────
    clearMessages(chatId) {
      if (chats[chatId]) { chats[chatId].messages = []; _save(); }
    },

    clearAll() {
      chats = {};
      currentChatId = null;
      try { localStorage.removeItem(LS_KEY); } catch {}
    },
  };
})();
