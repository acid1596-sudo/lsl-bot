"use strict";

const LABELS = { openai: "ChatGPT", anthropic: "Claude", ollama: "Ollama" };
const KEY_STORAGE = "lslbot-key";
const ANSWER_WITH_STORAGE = "lslbot-answer-with";

const state = { key: "", conversations: [], current: null, status: null, sending: false, answerWith: "auto" };

const $ = (id) => document.getElementById(id);

class Unauthorized extends Error {}

// --- key handling ---------------------------------------------------------

function readStoredKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch (e) {
    return "";
  }
}

function storeKey(key) {
  state.key = key;
  try {
    localStorage.setItem(KEY_STORAGE, key);
  } catch (e) {
    // Storage blocked (private window): the key still works for this tab.
  }
}

function takeKeyFromUrl() {
  // start.cmd opens the page as /#key=..., so the key never reaches the server
  // logs; it's saved and then wiped from the address bar and history.
  const match = /(?:^#|&)key=([^&]+)/.exec(location.hash);
  if (!match) return;
  storeKey(decodeURIComponent(match[1]));
  history.replaceState(null, "", location.pathname + location.search);
}

function askForKey() {
  const dialog = $("key-dialog");
  if (!dialog.open) {
    $("key-input").value = "";
    dialog.showModal();
  }
}

// --- API --------------------------------------------------------------------

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.key) headers["X-Bot-Secret"] = state.key;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    askForKey();
    throw new Unauthorized("unauthorized");
  }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  // "detail" is the server's plain-language explanation, when it has one.
  if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`);
  return body;
}

// --- provider status --------------------------------------------------------

function providerLabel(name) {
  return LABELS[name] || name || "Unknown";
}

function joinNames(names) {
  return names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function formatWait(seconds) {
  if (seconds < 90) return "about a minute";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  return `${Math.round(minutes / 60)} h`;
}

async function refreshStatus() {
  try {
    state.status = await api("/status");
  } catch (e) {
    if (!(e instanceof Unauthorized)) state.status = null;
  }
  renderStatus();
  renderAnswerWith();
}

function providerOrder(status) {
  return status.order || Object.keys(status.providers);
}

function renderStatus() {
  const bar = $("status-bar");
  const note = $("status-note");
  bar.querySelectorAll(".pill").forEach((pill) => pill.remove());

  const status = state.status;
  if (!status) {
    note.textContent = "Can't reach the bot. Is its window still open?";
    return;
  }

  const primaries = [];
  let fallback = null;
  for (const name of providerOrder(status)) {
    const info = status.providers[name];
    const pill = document.createElement("span");
    pill.className = "pill";
    let text = providerLabel(name);
    if (info.role === "fallback") {
      fallback = info;
      pill.classList.add("local");
      if (info.available) {
        text += " (local backup)";
      } else {
        pill.classList.add("down");
        text += " unavailable";
      }
    } else {
      primaries.push(providerLabel(name));
      if (!info.available) {
        pill.classList.add("cooling");
        text += ` out of usage, back in ${formatWait(info.retry_in_seconds)}`;
      }
    }
    if (name === status.active_provider) pill.classList.add("active");
    pill.title = info.problem || info.model || "";
    pill.textContent = text;
    bar.insertBefore(pill, note);
  }

  const active = status.providers[status.active_provider];
  const backupDown = fallback && !fallback.available;
  const verb = primaries.length > 1 ? "are" : "is";
  if (active && active.role === "fallback" && backupDown) {
    note.textContent = `${joinNames(primaries)} ${verb} out of usage and Ollama isn't available: ${fallback.problem}`;
  } else if (active && active.role === "fallback") {
    note.textContent = `${joinNames(primaries)} ${verb} out of usage, so Ollama is answering. It hands back automatically.`;
  } else if (backupDown) {
    note.textContent = `${providerLabel(status.active_provider)} answers next. No backup right now: ${fallback.problem}`;
  } else {
    note.textContent = `${providerLabel(status.active_provider)} answers next; Ollama steps in if usage runs out.`;
  }
}

// --- "Answer with": pulling a conversation to one provider -------------------

function readAnswerWith() {
  try {
    return localStorage.getItem(ANSWER_WITH_STORAGE) || "auto";
  } catch (e) {
    return "auto";
  }
}

function saveAnswerWith(value) {
  state.answerWith = value;
  try {
    localStorage.setItem(ANSWER_WITH_STORAGE, value);
  } catch (e) {
    // Remembered for this tab only.
  }
}

function renderAnswerWith() {
  const select = $("answer-with");
  if (state.status) {
    const names = providerOrder(state.status);
    const wanted = ["auto", ...names];
    const current = Array.from(select.options).map((o) => o.value);
    if (wanted.join() !== current.join()) {
      while (select.options.length > 1) select.remove(1);
      for (const name of names) {
        const label = state.status.providers[name].role === "fallback" ? `${providerLabel(name)} (on this PC)` : providerLabel(name);
        select.add(new Option(`${label} only`, name));
      }
    }
    if (!wanted.includes(state.answerWith)) saveAnswerWith("auto");
  }
  select.value = state.answerWith;

  const note = $("forced-note");
  if (state.answerWith === "auto") {
    note.hidden = true;
  } else if (state.answerWith === "ollama") {
    note.textContent = "Ollama is doing this task. Switch back to Auto to hand it back to ChatGPT/Claude.";
    note.hidden = false;
  } else {
    note.textContent = `Only ${providerLabel(state.answerWith)} will answer until you switch back to Auto.`;
    note.hidden = false;
  }
}

// --- conversations ----------------------------------------------------------

async function loadConversations() {
  state.conversations = await api("/api/conversations");
  renderConversationList();
}

function renderConversationList() {
  const list = $("conversation-list");
  list.replaceChildren();
  for (const conversation of state.conversations) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = conversation.title;
    button.title = conversation.title;
    if (state.current && state.current.id === conversation.id) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => openConversation(conversation.id));
    item.append(button);
    list.append(item);
  }
}

async function openConversation(id) {
  try {
    state.current = await api(`/api/conversations/${encodeURIComponent(id)}`);
  } catch (e) {
    if (!(e instanceof Unauthorized)) showError(e.message);
    return;
  }
  hideError();
  renderConversation();
  renderConversationList();
  closeSidebar();
  $("input").focus();
}

function startNewChat() {
  // The conversation is only created when its first message is sent.
  state.current = null;
  hideError();
  renderConversation();
  renderConversationList();
  closeSidebar();
  $("input").focus();
}

async function deleteCurrent() {
  if (!state.current || !confirm(`Delete "${state.current.title}"?`)) return;
  try {
    await api(`/api/conversations/${state.current.id}`, { method: "DELETE" });
  } catch (e) {
    if (!(e instanceof Unauthorized)) showError(e.message);
    return;
  }
  state.current = null;
  renderConversation();
  await loadConversations();
}

async function importChat(text, source) {
  state.current = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ imported_text: text, source }),
  });
  renderConversation();
  await loadConversations();
  $("input").value = "Please continue where we left off.";
  autosize();
  $("input").focus();
}

// --- rendering --------------------------------------------------------------

function renderContent(container, text) {
  // Everything goes in through textContent, never as HTML, because replies
  // are model output and must not be able to inject markup or scripts.
  text.split("```").forEach((part, index) => {
    if (index % 2 === 1) {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = part.replace(/^[\w+.#-]*\n/, "");
      pre.append(code);
      container.append(pre);
      return;
    }
    for (const paragraph of part.split(/\n{2,}/)) {
      const trimmed = paragraph.replace(/^\n+|\n+$/g, "");
      if (!trimmed) continue;
      const p = document.createElement("p");
      p.textContent = trimmed;
      container.append(p);
    }
  });
}

function messageElement(message) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${message.role}`;
  if (message.role === "assistant") {
    const badge = document.createElement("div");
    badge.className = "badge";
    if (message.provider === "ollama") {
      wrapper.classList.add("local");
      badge.textContent = "Ollama (local backup)";
    } else {
      badge.textContent = providerLabel(message.provider);
    }
    wrapper.append(badge);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  renderContent(bubble, message.content);
  wrapper.append(bubble);
  return wrapper;
}

function handoverDivider(previous, next) {
  if (!previous || previous === next) return null;
  const divider = document.createElement("div");
  divider.className = "handover";
  if (next === "ollama") {
    divider.textContent = `Ollama took over from ${providerLabel(previous)}`;
  } else if (previous === "ollama") {
    divider.textContent = `Handed back to ${providerLabel(next)}`;
  } else {
    divider.textContent = `Switched from ${providerLabel(previous)} to ${providerLabel(next)}`;
  }
  return divider;
}

function importedCard(message) {
  const details = document.createElement("details");
  details.className = "imported";
  const summary = document.createElement("summary");
  summary.textContent = `Continued from ${message.imported_from} - show what was pasted`;
  const pre = document.createElement("pre");
  pre.textContent = message.content;
  details.append(summary, pre);
  return details;
}

function emptyState() {
  const wrapper = document.createElement("div");
  wrapper.className = "empty";
  const heading = document.createElement("h2");
  heading.textContent = "Start a conversation";
  const first = document.createElement("p");
  first.textContent =
    "ChatGPT or Claude answers first. If their usage runs out, Ollama carries on with the same conversation on this PC, and hands it back as soon as they're available again.";
  const second = document.createElement("p");
  second.textContent =
    'Already in the middle of something in ChatGPT or Claude? Use "Continue a ChatGPT/Claude chat" to bring it over.';
  wrapper.append(heading, first, second);
  return wrapper;
}

function renderConversation() {
  const messages = $("messages");
  messages.replaceChildren();
  const conversation = state.current;
  $("chat-header").hidden = !conversation;
  if (!conversation) {
    messages.append(emptyState());
    return;
  }
  $("chat-title").textContent = conversation.title;

  let previousProvider = null;
  for (const message of conversation.messages) {
    if (message.imported_from) {
      messages.append(importedCard(message));
      continue;
    }
    if (message.role === "assistant") {
      const divider = handoverDivider(previousProvider, message.provider);
      if (divider) messages.append(divider);
      previousProvider = message.provider;
    }
    messages.append(messageElement(message));
  }
  messages.scrollTop = messages.scrollHeight;
}

let thinkingTimer = null;

function showPending(text) {
  const messages = $("messages");
  messages.querySelectorAll(".empty").forEach((el) => el.remove());
  messages.append(messageElement({ role: "user", content: text }));
  const thinking = document.createElement("div");
  thinking.className = "message assistant thinking";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = "Thinking...";
  thinking.append(bubble);
  messages.append(thinking);
  messages.scrollTop = messages.scrollHeight;

  // A local model on a PC without a strong graphics card can take minutes,
  // so show that it's still working rather than looking stuck.
  const started = Date.now();
  clearInterval(thinkingTimer);
  thinkingTimer = setInterval(() => {
    const seconds = Math.round((Date.now() - started) / 1000);
    bubble.textContent =
      seconds < 15 ? `Thinking... ${seconds}s` : `Thinking... ${seconds}s (a local model can take a few minutes on some PCs)`;
  }, 1000);
}

function stopPending() {
  clearInterval(thinkingTimer);
  thinkingTimer = null;
}

// --- sending ----------------------------------------------------------------

function setSending(sending) {
  state.sending = sending;
  $("send").disabled = sending;
  $("input").readOnly = sending;
}

async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.sending) return;
  setSending(true);
  hideError();
  input.value = "";
  autosize();
  showPending(text);
  try {
    if (!state.current) {
      state.current = await api("/api/conversations", { method: "POST", body: "{}" });
    }
    const result = await api(`/api/conversations/${state.current.id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: text, provider: state.answerWith }),
    });
    stopPending();
    state.current = result.conversation;
    renderConversation();
    await loadConversations();
  } catch (e) {
    stopPending();
    renderConversation();
    input.value = text;
    autosize();
    if (!(e instanceof Unauthorized)) {
      const reason = /[.!?]$/.test(e.message) ? e.message : `${e.message}.`;
      showError(`${reason} Your message is still in the box - press Send to try again.`);
    }
  } finally {
    setSending(false);
    refreshStatus();
    input.focus();
  }
}

// --- copy chat (handing a task back to ChatGPT/Claude) ----------------------

function transcript(conversation) {
  return conversation.messages
    .map((message) => {
      if (message.imported_from) return `(Earlier, in ${message.imported_from}:)\n${message.content}`;
      if (message.role === "user") return `You: ${message.content}`;
      return `${providerLabel(message.provider)}: ${message.content}`;
    })
    .join("\n\n");
}

async function copyChat() {
  if (!state.current) return;
  const text =
    "Here is our conversation so far, including the part another assistant handled while you were unavailable. Please continue from here.\n\n" +
    transcript(state.current);
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  toast("Copied. Paste it into ChatGPT or Claude to hand the task back.");
}

// --- small UI helpers -------------------------------------------------------

function showError(message) {
  const error = $("send-error");
  error.textContent = message;
  error.hidden = false;
}

function hideError() {
  $("send-error").hidden = true;
}

let toastTimer = null;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}

function autosize() {
  const input = $("input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

function closeSidebar() {
  $("app").classList.remove("sidebar-open");
}

// --- start up ---------------------------------------------------------------

async function load() {
  try {
    await Promise.all([loadConversations(), refreshStatus()]);
  } catch (e) {
    if (!(e instanceof Unauthorized)) showError(e.message);
  }
  renderConversation();
}

function wireUp() {
  $("new-chat").addEventListener("click", startNewChat);
  $("import-chat").addEventListener("click", () => {
    $("import-text").value = "";
    $("import-dialog").showModal();
  });
  $("import-cancel").addEventListener("click", () => $("import-dialog").close());
  $("import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = $("import-text").value;
    if (!text.trim()) return;
    $("import-dialog").close();
    try {
      await importChat(text, $("import-source").value);
    } catch (e) {
      if (!(e instanceof Unauthorized)) showError(e.message);
    }
  });

  $("key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    storeKey($("key-input").value.trim());
    $("key-dialog").close();
    await load();
  });

  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    send();
  });
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });
  $("input").addEventListener("input", autosize);

  $("copy-chat").addEventListener("click", copyChat);
  $("delete-chat").addEventListener("click", deleteCurrent);
  $("menu-toggle").addEventListener("click", () => $("app").classList.toggle("sidebar-open"));
  $("answer-with").addEventListener("change", (event) => {
    saveAnswerWith(event.target.value);
    renderAnswerWith();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  state.key = readStoredKey();
  state.answerWith = readAnswerWith();
  takeKeyFromUrl();
  wireUp();
  renderConversation();
  load();
  setInterval(refreshStatus, 15000);
});
