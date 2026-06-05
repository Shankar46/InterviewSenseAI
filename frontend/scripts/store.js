// frontend/scripts/store.js
// In-memory chat store. All other modules read/write through this API.

const Store = (() => {
  let chats = {};       // { [chatId]: { title, messages, attachment } }
  let currentChatId = null;

  function _id() {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  return {
    // ── Chats ──────────────────────────────────────────────
    createChat() {
      // Reuse if current chat is empty
      if (currentChatId && chats[currentChatId] && chats[currentChatId].messages.length === 0) {
        return currentChatId;
      }
      const id = _id();
      chats[id] = { title: "New Chat", messages: [], attachment: null };
      currentChatId = id;
      return id;
    },

    deleteChat(id) {
      if (Object.keys(chats).length <= 1) return false;
      delete chats[id];
      if (currentChatId === id) {
        currentChatId = Object.keys(chats).pop();
      }
      return true;
    },

    selectChat(id) {
      if (chats[id]) { currentChatId = id; return true; }
      return false;
    },

    get currentId() { return currentChatId; },

    getChatIds() { return Object.keys(chats); },

    getChat(id) { return chats[id] || null; },

    getCurrentChat() { return chats[currentChatId] || null; },

    setChatTitle(id, title) {
      if (chats[id]) chats[id].title = title;
    },

    // ── Messages ───────────────────────────────────────────
    addMessage(chatId, role, content) {
      if (!chats[chatId]) return;
      chats[chatId].messages.push({ role, content });
    },

    updateLastMessage(chatId, content) {
      const msgs = chats[chatId]?.messages;
      if (msgs && msgs.length) msgs[msgs.length - 1].content = content;
    },

    popLastMessage(chatId) {
      const msgs = chats[chatId]?.messages;
      if (msgs && msgs.length) msgs.pop();
    },

    removeLoadingMessage(chatId) {
      const msgs = chats[chatId]?.messages;
      if (!msgs || !msgs.length) return;
      const idx = msgs.findLastIndex(m => m.role === "assistant" && m.content === "__loading__");
      if (idx !== -1) msgs.splice(idx, 1);
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
      return (chats[chatId]?.messages || []).some(m => m.content.includes("Roadmap"));
    },

    // ── Attachments ────────────────────────────────────────
    setAttachment(chatId, file) {
      if (chats[chatId]) chats[chatId].attachment = file ? { file, name: file.name } : null;
    },

    getAttachment(chatId) {
      return chats[chatId]?.attachment || null;
    },
  };
})();
