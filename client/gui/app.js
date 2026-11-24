const state = {
  profileName: "",
  publicKey: "",
  avatar: "",
  bio: "",
  showOnlineStatus: true,
  connected: false,
  activePeer: null,
  chats: [],
  unread: new Set(),
  selectedProfilePath: null,
  settingsOpen: false,
  draftAvatar: "",
};

const $ = (id) => document.getElementById(id);

function renderAvatar(el, avatarUrl, fallbackText, isOnline = false) {
  el.innerHTML = "";
  if (avatarUrl) {
    el.style.backgroundImage = `url(${avatarUrl})`;
    el.textContent = "";
  } else {
    el.style.backgroundImage = "";
    el.textContent = (fallbackText || "?").slice(0, 2).toUpperCase();
  }
  if (isOnline) {
    const dot = document.createElement("span");
    dot.className = "avatar-online-dot";
    el.appendChild(dot);
  }
}

function resizeImageToDataUrl(file, maxSize = 128) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Datei konnte nicht gelesen werden."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("Ungültiges Bildformat."));
      img.onload = () => {
        const canvas = document.createElement("canvas");
        const scale = Math.min(maxSize / img.width, maxSize / img.height, 1);
        canvas.width = Math.max(1, Math.round(img.width * scale));
        canvas.height = Math.max(1, Math.round(img.height * scale));
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.82));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

function shortKey(key) {
  if (!key || key.length <= 16) return key || "";
  return `${key.slice(0, 8)}...${key.slice(-6)}`;
}

function formatTime(iso) {
  if (!iso) return "";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function showToast(msg) {
  const toast = $("toast");
  toast.textContent = msg;
  toast.classList.remove("hidden");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.add("hidden"), 3200);
}

function showAuthError(msg) {
  const el = $("auth-error");
  if (!msg) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.remove("hidden");
}

async function copyText(text, successMsg) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMsg);
  } catch {
    showToast("Kopieren fehlgeschlagen.");
  }
}

/* ---------- Auth / Profile Flow ---------- */

async function loadProfilesList() {
  showAuthError("");
  const profiles = await window.pywebview.api.list_profiles();
  const listEl = $("profile-list");
  listEl.innerHTML = "";

  if (!profiles.length) {
    $("profile-list-view").classList.add("hidden");
    $("create-form").classList.remove("hidden");
    $("btn-back-to-list").classList.add("hidden");
    return;
  }

  $("profile-list-view").classList.remove("hidden");
  $("create-form").classList.add("hidden");
  $("btn-back-to-list").classList.remove("hidden");

  for (const p of profiles) {
    const item = document.createElement("div");
    item.className = "profile-item";
    item.innerHTML = `<span>${escapeHtml(p.name)}</span><span class="subtitle">Öffnen →</span>`;
    item.addEventListener("click", () => {
      state.selectedProfilePath = p.path;
      $("unlock-profile-name").textContent = p.name;
      $("unlock-password").value = "";
      $("unlock-form").classList.remove("hidden");
      $("unlock-password").focus();
      showAuthError("");
    });
    listEl.appendChild(item);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function applyBackendState(s) {
  state.profileName = s.profile_name;
  state.publicKey = s.public_key;
  state.avatar = s.avatar || "";
  state.bio = s.bio || "";
  state.showOnlineStatus = s.show_online_status !== false;
  state.connected = s.connected;
  state.chats = s.chats || [];
  if (s.active_peer && state.chats.some((c) => c.peer_key === s.active_peer)) {
    state.activePeer = s.active_peer;
  } else if (state.chats.length > 0 && !state.activePeer) {
    state.activePeer = state.chats[0].peer_key;
  }

  $("auth-screen").classList.add("hidden");
  $("chat-screen").classList.remove("hidden");
  renderAll();
}

/* ---------- Rendering ---------- */

function renderConnectionStatus() {
  const pill = $("connection-pill");
  if (state.connected) {
    pill.textContent = "Verbunden";
    pill.classList.add("online");
    pill.classList.remove("offline");
  } else {
    pill.textContent = "Getrennt";
    pill.classList.add("offline");
    pill.classList.remove("online");
  }
}

function renderSidebar() {
  $("sidebar-profile-name").textContent = state.profileName;
  $("own-public-key").textContent = state.publicKey;
  renderAvatar(
    $("sidebar-own-avatar"),
    state.avatar,
    state.profileName,
    state.connected && state.showOnlineStatus
  );
  renderConnectionStatus();

  const list = $("chat-list");
  list.innerHTML = "";

  if (!state.chats.length) {
    const empty = document.createElement("div");
    empty.className = "subtitle";
    empty.style.padding = "12px 8px";
    empty.textContent = "Noch keine Chats. Starte einen über '+ Neuer Chat'.";
    list.appendChild(empty);
    return;
  }

  for (const chat of state.chats) {
    const item = document.createElement("div");
    item.className = "chat-item" + (chat.peer_key === state.activePeer && !state.settingsOpen ? " active" : "");

    const title = chat.label || shortKey(chat.peer_key);
    const time = formatTime(chat.last_timestamp);
    const preview = chat.last_text || "Noch keine Nachrichten";
    const isUnread = state.unread.has(chat.peer_key);
    const isOnline = Boolean(chat.online && chat.show_online_status !== false);

    const avatarEl = document.createElement("div");
    avatarEl.className = "avatar avatar-sm";
    renderAvatar(avatarEl, chat.avatar || "", title, isOnline);

    const contentEl = document.createElement("div");
    contentEl.className = "chat-item-content";
    contentEl.innerHTML = `
      <div class="chat-item-top">
        <span class="chat-item-name">${escapeHtml(title)}</span>
        <span class="chat-item-time">${escapeHtml(time)}</span>
      </div>
      <div class="chat-item-bottom">
        <span class="chat-item-preview">${escapeHtml(preview)}</span>
        ${isUnread ? '<span class="unread-dot"></span>' : ""}
      </div>
    `;

    item.appendChild(avatarEl);
    item.appendChild(contentEl);
    item.addEventListener("click", () => selectChat(chat.peer_key));
    list.appendChild(item);
  }
}

function renderActiveChat() {
  if (state.settingsOpen) {
    $("settings-view").classList.remove("hidden");
    $("chat-header").classList.add("hidden");
    $("messages-container").classList.add("hidden");
    $("message-form").classList.add("hidden");
    $("empty-chat-state").classList.add("hidden");
    return;
  }
  $("settings-view").classList.add("hidden");

  const chat = state.chats.find((c) => c.peer_key === state.activePeer);
  if (!chat) {
    $("chat-header").classList.add("hidden");
    $("messages-container").classList.add("hidden");
    $("message-form").classList.add("hidden");
    $("empty-chat-state").classList.remove("hidden");
    return;
  }

  $("empty-chat-state").classList.add("hidden");
  $("chat-header").classList.remove("hidden");
  $("messages-container").classList.remove("hidden");
  $("message-form").classList.remove("hidden");

  const title = chat.label || shortKey(chat.peer_key);
  const isOnline = Boolean(chat.online && chat.show_online_status !== false);
  renderAvatar($("chat-peer-avatar"), chat.avatar || "", title, isOnline);

  $("chat-peer-title").textContent = title;
  $("chat-peer-online").classList.toggle("hidden", !isOnline);
  const bioEl = $("chat-peer-bio");
  if (chat.bio) {
    bioEl.textContent = chat.bio;
    bioEl.classList.remove("hidden");
  } else {
    bioEl.textContent = "";
    bioEl.classList.add("hidden");
  }
  $("chat-peer-key").textContent = chat.peer_key;

  const container = $("messages-container");
  container.innerHTML = "";

  for (const msg of chat.messages) {
    const row = document.createElement("div");
    row.className = `message-row ${msg.sender === "me" ? "me" : "peer"}`;
    row.innerHTML = `
      <div class="message-bubble">${escapeHtml(msg.text)}</div>
      <span class="message-time">${escapeHtml(formatTime(msg.timestamp))}</span>
    `;
    container.appendChild(row);
  }

  container.scrollTop = container.scrollHeight;
}

function renderAll() {
  renderSidebar();
  renderActiveChat();
}

async function selectChat(peerKey) {
  state.settingsOpen = false;
  state.activePeer = peerKey;
  state.unread.delete(peerKey);
  await window.pywebview.api.select_chat(peerKey);
  renderAll();
  $("message-input").focus();
}

/* ---------- Events from Python Backend ---------- */

window.onIncomingMessage = function (payload) {
  const { peer_key, label, message, avatar, bio, show_online_status, online } = payload;
  let chat = state.chats.find((c) => c.peer_key === peer_key);
  if (!chat) {
    chat = {
      peer_key,
      label: label || "",
      avatar: avatar || "",
      bio: bio || "",
      show_online_status: show_online_status !== false,
      online: Boolean(online),
      last_text: "",
      last_timestamp: "",
      messages: [],
    };
    state.chats.unshift(chat);
  }
  chat.label = label || chat.label;
  if (typeof avatar === "string") chat.avatar = avatar;
  if (typeof bio === "string") chat.bio = bio;
  if (typeof show_online_status === "boolean") chat.show_online_status = show_online_status;
  if (typeof online === "boolean") chat.online = online;

  chat.messages.push(message);
  chat.last_text = message.text;
  chat.last_timestamp = message.timestamp;

  // Move updated chat to top
  state.chats = [chat, ...state.chats.filter((c) => c.peer_key !== peer_key)];

  if (state.activePeer !== peer_key || state.settingsOpen) {
    state.unread.add(peer_key);
  }
  renderAll();
};

window.onPresenceUpdate = function (payload) {
  const statuses = payload.statuses || {};
  let changed = false;
  for (const chat of state.chats) {
    if (Object.prototype.hasOwnProperty.call(statuses, chat.peer_key)) {
      chat.online = Boolean(statuses[chat.peer_key]);
      changed = true;
    }
  }
  if (changed) {
    renderAll();
  }
};

window.onServerError = function (payload) {
  showToast(payload.message || "Server-Fehler");
};

window.onConnectionStatus = function (payload) {
  state.connected = Boolean(payload.connected);
  renderConnectionStatus();
};

/* ---------- DOM Listeners ---------- */

window.addEventListener("pywebviewready", () => {
  loadProfilesList();
});

$("btn-show-create").addEventListener("click", () => {
  showAuthError("");
  $("profile-list-view").classList.add("hidden");
  $("create-form").classList.remove("hidden");
  $("create-name").focus();
});

$("btn-back-to-list").addEventListener("click", () => {
  loadProfilesList();
});

$("btn-cancel-unlock").addEventListener("click", () => {
  state.selectedProfilePath = null;
  $("unlock-form").classList.add("hidden");
  showAuthError("");
});

$("unlock-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selectedProfilePath) return;
  const password = $("unlock-password").value;
  const res = await window.pywebview.api.unlock_profile(state.selectedProfilePath, password);
  if (!res.ok) {
    showAuthError(res.error);
    return;
  }
  applyBackendState(res.state);
});

$("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("create-name").value.trim();
  const pw = $("create-password").value;
  const pw2 = $("create-password-confirm").value;
  if (pw !== pw2) {
    showAuthError("Passwörter stimmen nicht überein.");
    return;
  }
  const res = await window.pywebview.api.create_profile(name, pw);
  if (!res.ok) {
    showAuthError(res.error);
    return;
  }
  $("create-name").value = "";
  $("create-password").value = "";
  $("create-password-confirm").value = "";
  applyBackendState(res.state);
});

$("btn-copy-own-key").addEventListener("click", () => {
  copyText(state.publicKey, "Eigener Public Key kopiert.");
});

$("btn-copy-peer-key").addEventListener("click", () => {
  if (state.activePeer) {
    copyText(state.activePeer, "Empfänger Public Key kopiert.");
  }
});

$("connection-pill").addEventListener("click", async () => {
  const res = await window.pywebview.api.reconnect();
  if (res.ok) {
    state.connected = res.connected;
    renderConnectionStatus();
    showToast(res.connected ? "Mit Server verbunden." : "Server nicht erreichbar.");
  }
});

$("btn-logout").addEventListener("click", async () => {
  await window.pywebview.api.logout();
  state.activePeer = null;
  state.settingsOpen = false;
  state.chats = [];
  state.unread.clear();
  state.selectedProfilePath = null;
  $("unlock-form").classList.add("hidden");
  $("chat-screen").classList.add("hidden");
  $("auth-screen").classList.remove("hidden");
  loadProfilesList();
});

$("btn-open-settings").addEventListener("click", () => {
  state.settingsOpen = true;
  state.draftAvatar = state.avatar || "";
  renderAvatar($("settings-avatar-preview"), state.draftAvatar, state.profileName);
  $("settings-bio").value = state.bio || "";
  $("settings-show-online").checked = state.showOnlineStatus !== false;
  $("settings-avatar-file").value = "";
  renderAll();
});

$("btn-close-settings").addEventListener("click", () => {
  state.settingsOpen = false;
  renderAll();
});

$("settings-avatar-file").addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  try {
    state.draftAvatar = await resizeImageToDataUrl(file, 128);
    renderAvatar($("settings-avatar-preview"), state.draftAvatar, state.profileName);
  } catch (err) {
    showToast(err.message || "Bild konnte nicht geladen werden.");
  }
});

$("btn-remove-avatar").addEventListener("click", () => {
  state.draftAvatar = "";
  $("settings-avatar-file").value = "";
  renderAvatar($("settings-avatar-preview"), "", state.profileName);
});

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const bio = $("settings-bio").value;
  const showOnline = $("settings-show-online").checked;
  const res = await window.pywebview.api.update_profile_settings(state.draftAvatar, bio, showOnline);
  if (!res.ok) {
    showToast(res.error || "Speichern fehlgeschlagen.");
    return;
  }
  state.settingsOpen = false;
  applyBackendState(res.state);
  showToast("Profileinstellungen gespeichert.");
});

$("btn-new-chat").addEventListener("click", () => {
  $("new-chat-key").value = "";
  $("new-chat-alias").value = "";
  $("modal-new-chat").classList.remove("hidden");
  $("new-chat-key").focus();
});

$("btn-close-new-chat").addEventListener("click", () => {
  $("modal-new-chat").classList.add("hidden");
});

$("new-chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const key = $("new-chat-key").value.trim();
  const alias = $("new-chat-alias").value.trim();
  const res = await window.pywebview.api.start_chat(key, alias);
  if (!res.ok) {
    showToast(res.error);
    return;
  }
  $("modal-new-chat").classList.add("hidden");
  state.activePeer = res.peer_key;
  applyBackendState(res.state);
  $("message-input").focus();
});

$("btn-rename-peer").addEventListener("click", () => {
  if (!state.activePeer) return;
  const chat = state.chats.find((c) => c.peer_key === state.activePeer);
  $("alias-input").value = chat?.label || "";
  $("modal-alias").classList.remove("hidden");
  $("alias-input").focus();
});

$("btn-close-alias").addEventListener("click", () => {
  $("modal-alias").classList.add("hidden");
});

$("alias-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.activePeer) return;
  const name = $("alias-input").value.trim();
  const res = await window.pywebview.api.save_contact(name, state.activePeer);
  if (!res.ok) {
    showToast(res.error);
    return;
  }
  $("modal-alias").classList.add("hidden");
  applyBackendState(res.state);
});

$("message-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.activePeer) return;
  const input = $("message-input");
  const text = input.value.trim();
  if (!text) return;

  const res = await window.pywebview.api.send_message(state.activePeer, text);
  if (!res.ok) {
    showToast(res.error);
    return;
  }

  input.value = "";
  const chat = state.chats.find((c) => c.peer_key === res.peer_key);
  if (chat) {
    chat.messages.push(res.message);
    chat.last_text = res.message.text;
    chat.last_timestamp = res.message.timestamp;
    state.chats = [chat, ...state.chats.filter((c) => c.peer_key !== res.peer_key)];
  }
  renderAll();
});

