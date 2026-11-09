import { $, h, icon, announce, prefersReducedMotion, debugBlock } from "./core.js?v=__APP_VERSION__";
import { renderMarkdown } from "./markdown.js?v=__APP_VERSION__";

const COLLAPSE_CHARS = 520;
const COLLAPSE_LINES = 9;
let stickToBottom = true;
let isProgrammatic = false;
let programmaticTimer;

function endProgrammaticScroll() {
  isProgrammatic = false;
  clearTimeout(programmaticTimer);
  updateJumpLatest();
}

export function programmaticScroll(action) {
  isProgrammatic = true;
  clearTimeout(programmaticTimer);
  programmaticTimer = setTimeout(endProgrammaticScroll, 400);
  action();
  updateJumpLatest();
}

export function initThread() {
  const scroller = $("logScroll");
  scroller.addEventListener(
    "scroll",
    () => {
      updateJumpLatest();
      if (isProgrammatic) return;
      stickToBottom = isNearBottom();
    },
    { passive: true }
  );
  scroller.addEventListener("scrollend", endProgrammaticScroll);
  const stopSticking = () => {
    stickToBottom = false;
    updateJumpLatest();
    endProgrammaticScroll();
  };
  scroller.addEventListener("wheel", (event) => {
    if (event.deltaY < 0) stopSticking();
  }, { passive: true });
  let touchY;
  scroller.addEventListener("touchstart", (event) => {
    touchY = event.touches[0].clientY;
  }, { passive: true });
  scroller.addEventListener("touchmove", (event) => {
    const clientY = event.touches[0].clientY;
    if (clientY > touchY) stopSticking();
    touchY = clientY;
  }, { passive: true });
  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input, textarea, select, [contenteditable]")) return;
    if (["PageUp", "ArrowUp", "Home"].includes(event.key)) stopSticking();
  });
  $("jumpLatest").addEventListener("click", () => {
    scrollToBottom({ force: true, smooth: true });
    $("composerInput").focus({ preventScroll: true });
  });
  // Layout changes can change the bottom gap without a scroll event.
  const resizeObserver = new ResizeObserver(updateJumpLatest);
  resizeObserver.observe(scroller);
  resizeObserver.observe($("log"));
  window.addEventListener("pageshow", updateJumpLatest);
  updateJumpLatest();
}

function updateJumpLatest() {
  if (!$("jumpLatest")) return;
  $("jumpLatest").hidden = isNearBottom();
}

function isNearBottom() {
  const s = $("logScroll");
  if (!s) return true;
  return s.scrollHeight - s.scrollTop - s.clientHeight <= 80;
}

export function scrollToBottom({ force = false, smooth = false } = {}) {
  if (force) stickToBottom = true;
  const s = $("logScroll");
  if (!stickToBottom) {
    updateJumpLatest();
    return;
  }
  programmaticScroll(() => s.scrollTo({ top: s.scrollHeight, behavior: smooth && !prefersReducedMotion() ? "smooth" : "auto" }));
  updateJumpLatest();
}

export function reveal(node, { focus = null, user = false } = {}) {
  if (!node) return;
  if (!stickToBottom && !user) {
    updateJumpLatest();
    return;
  }
  programmaticScroll(() => node.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" }));
  if (focus) focus.focus({ preventScroll: true });
}

export function append(node, { scroll = true } = {}) {
  removeHero();
  $("log").appendChild(node);
  updateJumpLatest();
  if (scroll) requestAnimationFrame(() => {
    if (!stickToBottom) {
      updateJumpLatest();
      return;
    }
    if (!node.isConnected) return;
    const scroller = $("logScroll");
    if (node.offsetHeight > scroller.clientHeight) {
      programmaticScroll(() => { scroller.scrollTop = node.offsetTop - 16; });
    } else {
      scrollToBottom();
    }
  });
  return node;
}

export function clearLog() {
  removeHero();
  $("log").replaceChildren();
  stickToBottom = true;
  updateJumpLatest();
}

export function collapsible(text, cls = "bubble-text", { markdown = false } = {}) {
  const value = String(text || "");
  const long = value.length > COLLAPSE_CHARS || value.split("\n").length > COLLAPSE_LINES;
  const body = h("div", { class: cls, text: value });
  if (markdown) body.innerHTML = renderMarkdown(value);
  if (!long) return body;
  body.classList.add("is-clamped");
  const toggle = h("button", {
    type: "button",
    class: "btn-text more-toggle",
    "aria-expanded": "false",
    text: "展开全文",
  });
  toggle.addEventListener("click", () => {
    const open = body.classList.toggle("is-clamped") === false;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.textContent = open ? "收起" : "展开全文";
  });
  return h("div", { class: "collapsible" }, [body, toggle]);
}

function avatar() {
  return h("span", { class: "msg-avatar", "aria-hidden": "true", text: "助" });
}

export function userMessage(data, { animate = true, scroll = true } = {}) {
  const node = append(userRow(data, { animate }), { scroll: false });
  // A new send resumes following immediately; restored rows stay in place.
  if (scroll) scrollToBottom({ force: true });
  return node;
}

export function userRow({ text, omitted = 0 }, { animate = true } = {}) {
  const bubble = h("div", { class: "bubble bubble-user" });
  if (text) bubble.append(collapsible(text));
  if (omitted) bubble.append(h("div", { class: "bubble-note", text: `（本机只保存了前面一部分，省略 ${omitted} 字）` }));
  return h("div", { class: `msg msg-user${animate ? " enter" : ""}` }, [
    h("span", { class: "sr-only", text: "你：" }),
    bubble,
  ]);
}

function feedbackBar(initial, onFeedback) {
  const status = h("span", { class: "fb-status", role: "status" });
  const buttons = [];
  const mark = (value) => {
    for (const b of buttons) {
      b.setAttribute("aria-pressed", String(b.dataset.value === value));
      b.disabled = !!value;
    }
    status.textContent = value ? "已收到反馈，谢谢" : "";
  };
  const make = (value, glyph, label) => {
    const btn = h("button", {
      type: "button",
      class: "btn-text fb-btn",
      "aria-label": label,
      title: label,
      "aria-pressed": "false",
      dataset: { value },
      text: glyph,
      onClick: async () => {
        for (const b of buttons) b.disabled = true;
        try {
          await onFeedback(value);
          mark(value);
        } catch {
          for (const b of buttons) b.disabled = false;
          status.textContent = "反馈没发出去，稍后再试";
        }
      },
    });
    buttons.push(btn);
    return btn;
  };
  const bar = h("div", { class: "msg-feedback", role: "group", "aria-label": "这条回复有帮助吗" }, [
    make("up", "👍", "有帮助"),
    make("down", "👎", "没帮助"),
    status,
  ]);
  if (initial) mark(initial);
  return bar;
}

export function assistantMessage(text, { scroll = true, animate = true, speak = true, feedback = null, onFeedback = null } = {}) {
  const row = h("div", { class: `msg msg-assistant${animate ? " enter" : ""}` }, [
    avatar(),
    h("div", { class: "bubble bubble-assistant" }, [
      h("span", { class: "sr-only", text: "小H：" }),
      collapsible(text, "bubble-text", { markdown: true }),
      onFeedback ? feedbackBar(feedback, onFeedback) : null,
    ]),
  ]);
  if (speak) announce(`小H：${text}`);
  return append(row, { scroll });
}

export function systemLine(text, { divider = false, scroll = true } = {}) {
  return append(h("div", { class: `sys-line${divider ? " is-divider" : ""}`, role: "note" }, [h("span", { text })]), { scroll });
}

export function errorMessage({ text, onRetry = null, debug = "" }) {
  const actions = [];
  let row;
  if (onRetry) {
    actions.push(
      h("button", {
        type: "button",
        class: "btn btn-ghost btn-sm",
        text: "重试",
        onClick: () => {
          row.remove();
          onRetry();
        },
      })
    );
  }
  row = h("div", { class: "msg msg-assistant enter" }, [
    avatar(),
    h("div", { class: "bubble bubble-error", role: "alert" }, [
      h("div", { class: "err-line" }, [icon("alert", "err-icon"), h("span", { text })]),
      actions.length ? h("div", { class: "err-actions" }, actions) : null,
      debug ? debugBlock("调试信息", debug) : null,
    ]),
  ]);
  return append(row);
}

export function typing({ hint = "", slowHint = "" } = {}) {
  const hintNode = h("span", { class: "typing-hint", text: hint });
  const row = h("div", { class: "msg msg-assistant msg-typing", "aria-hidden": "true" }, [
    avatar(),
    h("div", { class: "bubble bubble-assistant bubble-typing" }, [
      h("span", { class: "typing-dots" }, [h("span"), h("span"), h("span")]),
      hintNode,
    ]),
  ]);
  append(row);
  announce(hint || "正在处理…");
  const timer = slowHint
    ? window.setTimeout(() => {
        hintNode.textContent = slowHint;
      }, 6000)
    : 0;
  return {
    done() {
      window.clearTimeout(timer);
      row.remove();
    },
  };
}

export function renderHero({ onChip, onMemory, onMedication }) {
  if ($("hero")) return;
  const featureIcon = (name) => {
    const svg = icon(name);
    const paths = {
      list: '<rect x="3" y="3" width="18" height="18" rx="5"/><path class="feature-pulse" d="M5 12h4l2-5 3 10 2-5h3"/>',
      bell: '<g class="feature-bell"><path d="M18 8a6 6 0 0 0-12 0c0 7-2 8-2 8h16s-2-1-2-8Z"/><path d="M10 20a2 2 0 0 0 4 0"/><path d="M12 2v1"/></g>',
      doc: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z"/><path d="M14 3v6h6"/><path class="feature-writing" d="M8 13h8m-8 4h5"/>',
      shield: '<g class="feature-memory"><path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 12 9 5 9-5m-18 5 9 5 9-5"/></g>',
    };
    svg.innerHTML = paths[name];
    return svg;
  };
  const chip = (title, detail, glyph, prompt, onClick = () => onChip(prompt)) =>
    h("button", { type: "button", class: `hero-chip feature-${glyph}`, onClick }, [
      h("span", { class: "quick-overlay", "aria-hidden": "true" }),
      h("span", { class: "quick-icon", "aria-hidden": "true" }, [featureIcon(glyph)]),
      h("span", { class: "quick-copy" }, [h("strong", { text: title })]),
      h("span", { class: "quick-arrow", "aria-hidden": "true", text: "↗" }),
    ]);
  const hero = h("section", { class: "hero enter", id: "hero", "aria-labelledby": "heroTitle" }, [
    h("div", { class: "hero-mascot", role: "img", "aria-label": "向你招手的胶囊健康伙伴" }, [
      h("div", { class: "hero-mascot-frame", "aria-hidden": "true" }, [
        h("img", {
          class: "hero-mascot-sprite",
          src: "/static/images/capsule-companion-wave.png",
          alt: "",
          decoding: "async",
          fetchpriority: "high",
          onError: (event) => { event.currentTarget.closest(".hero-mascot").hidden = true; },
        }),
      ]),
    ]),
    h("p", { class: "hero-kicker", id: "heroGreeting", text: "你好，欢迎回来" }),
    h("h2", { id: "heroTitle", text: "今天，有什么可以帮你？" }),
  ]);
  $("log").appendChild(hero);

  const actions = $("heroActions");
  actions.replaceChildren(
    chip("记录身体近况", "记录最近的症状与身体变化", "list", "我想记录一下最近的健康状况，请引导我填写"),
    chip("安排用药提醒", "按你的用药计划，安排日常提醒", "bell", "我想设置用药提醒，请先问我药名和时间", onMedication),
    chip("整理就医笔记", "梳理症状，准备想和医生说的话", "doc", "帮我准备一份就医笔记，请先询问我的症状和就诊需求"),
    chip("回顾健康记忆", "查看已记录的信息与健康近况", "shield", "你记得我什么", onMemory || (() => onChip("你记得我什么"))),
  );
  actions.hidden = false;
}

export function removeHero() {
  const hero = $("hero");
  if (!hero) return;
  hero.remove();
  const actions = $("heroActions");
  actions.hidden = true;
  actions.replaceChildren();
}
