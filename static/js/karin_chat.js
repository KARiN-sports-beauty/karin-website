(function () {
  "use strict";

  var GREETING =
    "身体のことで気になることがあれば、お気軽にご相談ください。";
  var THINKING_LABEL = "考えています…";
  var USER_ERROR =
    "申し訳ありません。現在うまくご案内できないようです。少し時間をおいてもう一度お試しください。";
  var SAMPLES = [
    "腰が痛いんですが、何をしたらいいですか？",
    "鍼と整体、どちらが合いそうですか？",
    "初めてなんですが、どんな施術がありますか？",
    "東京で施術を受けたいです",
  ];

  var root = document.getElementById("karin-chat-root");
  if (!root) return;

  var iconUrl = root.getAttribute("data-icon-url") || "";
  var bookUrl = root.getAttribute("data-book-url") || "/book";
  var isPage = root.getAttribute("data-mode") === "page";

  var panel = root.querySelector("[data-karin-panel]");
  var fab = root.querySelector("[data-karin-fab]");
  var closeBtn = root.querySelector("[data-karin-close]");
  var resetBtn = root.querySelector("[data-karin-reset]");
  var logEl = root.querySelector("[data-karin-log]");
  var samplesEl = root.querySelector("[data-karin-samples]");
  var form = root.querySelector("[data-karin-form]");
  var input = root.querySelector("#karin-chat-input");
  var sendBtn = root.querySelector("[data-karin-send]");

  var conversationId = null;
  var sending = false;
  var lastRole = null;
  var lastUserWantsBooking = false;
  var thinkingRow = null;

  function isMobile() {
    return window.matchMedia("(max-width: 767px)").matches;
  }

  function openPanel() {
    if (!panel) return;
    panel.hidden = false;
    if (!isPage) document.body.classList.add("karin-chat-open");
    if (fab) fab.setAttribute("aria-expanded", "true");
    syncViewport();
    if (input && !isMobile()) input.focus();
  }

  function closePanel() {
    if (isPage || !panel) return;
    panel.hidden = true;
    document.body.classList.remove("karin-chat-open");
    if (fab) {
      fab.setAttribute("aria-expanded", "false");
      fab.focus();
    }
  }

  function syncViewport() {
    if (!panel || panel.hidden) return;
    if (!window.visualViewport) return;
    if (!(isPage || isMobile())) return;
    var height = window.visualViewport.height;
    if (isPage) {
      panel.style.height = Math.max(240, height - 70) + "px";
    } else if (isMobile()) {
      panel.style.height = height + "px";
      var offsetTop = window.visualViewport.offsetTop || 0;
      panel.style.top = offsetTop + "px";
    }
  }

  function scrollToEnd() {
    if (!logEl) return;
    logEl.scrollTop = logEl.scrollHeight;
  }

  function renderSafeText(target, text) {
    var raw = String(text == null ? "" : text);
    var lines = raw.split("\n");
    var list = null;

    lines.forEach(function (line) {
      var bullet = line.match(/^\s*(?:[-*・]|[0-9]+[.)])\s+(.*)$/);
      if (bullet) {
        if (!list) {
          list = document.createElement("ul");
          target.appendChild(list);
        }
        var li = document.createElement("li");
        li.textContent = bullet[1];
        list.appendChild(li);
        return;
      }
      if (!line.trim()) {
        list = null;
        return;
      }
      list = null;
      var p = document.createElement("p");
      p.textContent = line;
      target.appendChild(p);
    });
  }

  function looksLikeEmergencyReply(text) {
    return /救急|医療機関/.test(String(text || ""));
  }

  function shouldOfferBookLink(reply) {
    if (!lastUserWantsBooking) return false;
    if (looksLikeEmergencyReply(reply)) return false;
    return true;
  }

  function appendBookLink(parent) {
    var link = document.createElement("a");
    link.className = "karin-chat-book-link";
    link.href = bookUrl;
    link.textContent = "Web予約ページへ進む";
    parent.appendChild(link);
  }

  function appendMessage(role, text, options) {
    options = options || {};
    var grouped = role === "ai" && lastRole === "ai" && !options.thinking;
    var row = document.createElement("div");
    row.className = "karin-chat-row karin-chat-row--" + role;
    if (grouped) row.classList.add("is-grouped");

    if (role === "ai") {
      var avatarCol = document.createElement("div");
      avatarCol.className = "karin-chat-avatar-col";
      if (!grouped) {
        var avatar = document.createElement("div");
        avatar.className = "karin-chat-avatar";
        var img = document.createElement("img");
        img.src = iconUrl;
        img.alt = "KARiN.chatbot";
        img.width = 44;
        img.height = 44;
        avatar.appendChild(img);
        avatarCol.appendChild(avatar);
      }
      row.appendChild(avatarCol);

      var col = document.createElement("div");
      col.className = "karin-chat-ai-col";
      if (!grouped) {
        var name = document.createElement("p");
        name.className = "karin-chat-name";
        name.textContent = "KARiN.chatbot";
        col.appendChild(name);
      }
      var bubble = document.createElement("div");
      bubble.className = "karin-chat-bubble karin-chat-bubble--ai";
      if (options.thinking) {
        bubble.classList.add("is-thinking");
        bubble.textContent = THINKING_LABEL;
      } else {
        renderSafeText(bubble, text);
      }
      col.appendChild(bubble);
      if (!options.thinking && shouldOfferBookLink(text)) {
        appendBookLink(col);
      }
      row.appendChild(col);
    } else {
      var userBubble = document.createElement("div");
      userBubble.className = "karin-chat-bubble karin-chat-bubble--user";
      renderSafeText(userBubble, text);
      row.appendChild(userBubble);
    }

    logEl.appendChild(row);
    lastRole = options.thinking ? "ai" : role;
    scrollToEnd();
    return row;
  }

  function showSamples() {
    if (!samplesEl) return;
    samplesEl.replaceChildren();
    SAMPLES.forEach(function (sample) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "karin-chat-chip";
      chip.textContent = sample;
      chip.addEventListener("click", function () {
        if (!input || sending) return;
        input.value = sample;
        input.focus();
      });
      samplesEl.appendChild(chip);
    });
    samplesEl.hidden = false;
  }

  function resetConversation() {
    conversationId = null;
    sending = false;
    lastRole = null;
    lastUserWantsBooking = false;
    thinkingRow = null;
    if (logEl) logEl.replaceChildren();
    if (sendBtn) sendBtn.disabled = false;
    if (input) {
      input.value = "";
      input.disabled = false;
    }
    appendMessage("ai", GREETING);
    showSamples();
  }

  function setSending(on) {
    sending = on;
    if (sendBtn) sendBtn.disabled = on;
    if (input) input.disabled = on;
  }

  function removeThinking() {
    if (thinkingRow && thinkingRow.parentNode) {
      thinkingRow.parentNode.removeChild(thinkingRow);
    }
    thinkingRow = null;
    var rows = logEl ? logEl.querySelectorAll(".karin-chat-row") : [];
    if (rows.length) {
      lastRole = rows[rows.length - 1].classList.contains("karin-chat-row--user")
        ? "user"
        : "ai";
    } else {
      lastRole = null;
    }
  }

  function userAskedBooking(message) {
    if (/まだ予約|決めてな|相談だけ|相談しても/.test(message)) return false;
    return /予約したい|予約をお願い|空いて|空き枠|空き.*確認/.test(message);
  }

  function sendMessage(raw) {
    var message = String(raw || "").trim();
    if (!message || sending) return;

    lastUserWantsBooking = userAskedBooking(message);
    if (samplesEl) samplesEl.hidden = true;
    appendMessage("user", message);
    input.value = "";
    setSending(true);
    thinkingRow = appendMessage("ai", THINKING_LABEL, { thinking: true });

    var payload = { message: message };
    if (conversationId) payload.conversation_id = conversationId;

    fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, status: res.status, body: body || {} };
        }).catch(function () {
          return { ok: false, status: res.status, body: {} };
        });
      })
      .then(function (result) {
        removeThinking();
        var reply = result.body && typeof result.body.reply === "string"
          ? result.body.reply
          : "";
        var nextId = result.body && result.body.conversation_id;
        if (result.ok && reply) {
          if (typeof nextId === "string" && nextId) conversationId = nextId;
          appendMessage("ai", reply);
          return;
        }
        appendMessage("ai", USER_ERROR);
      })
      .catch(function () {
        removeThinking();
        appendMessage("ai", USER_ERROR);
      })
      .then(function () {
        setSending(false);
        if (input && !isMobile()) input.focus();
      });
  }

  if (fab) {
    fab.addEventListener("click", function () {
      if (panel && !panel.hidden) closePanel();
      else openPanel();
    });
  }
  if (closeBtn) closeBtn.addEventListener("click", closePanel);
  if (resetBtn) resetBtn.addEventListener("click", resetConversation);

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !isPage) closePanel();
  });

  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendMessage(input && input.value);
    });
  }

  if (input) {
    input.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      if (event.shiftKey) return;
      if (event.isComposing || event.keyCode === 229) return;
      if (isMobile()) return;
      event.preventDefault();
      sendMessage(input.value);
    });
  }

  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", syncViewport);
    window.visualViewport.addEventListener("scroll", syncViewport);
  }

  resetConversation();
  if (isPage) openPanel();
})();
