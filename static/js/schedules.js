import { $, h, toast } from "./core.js?v=__APP_VERSION__";
import { api, friendlyError } from "./api.js?v=__APP_VERSION__";

const KINDS = { medication: "用药提醒", one_shot_reminder: "一次性提醒", custom_nl: "自定义指令" };
const kindLabel = (kind) => KINDS[kind] || "定时任务";
const STATES = { active: "已启用", paused: "已冻结", paused_idle: "14 天未活跃，已暂停", completed: "已完成", deleted: "已删除" };
const stateLabel = (s) => s.paused_by_idle ? STATES.paused_idle : STATES[s.status];
const deliveryLabel = (s) => s.delivery.includes("email") ? "站内提醒 + 邮件（未配置时跳过）" : s.delivery === "in_app" ? "仅站内提醒" : "站内提醒；有绑定时尝试渠道推送";
const RESULTS = { running: "运行中", success: "成功", failed: "失败" };
let panel, body, generation = 0;
let defaultTimezone = "Asia/Shanghai";
let schedulerState = null;
const button = (text, onClick, cls = "btn btn-ghost btn-sm") => h("button", { type: "button", class: cls, text, onClick });
const date = (value, tz) => value ? new Intl.DateTimeFormat("zh-CN", { timeZone: tz, dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
const summary = (s) => {
  if (s.trigger.type === "cron") {
    const parts = s.trigger.expr.split(/\s+/);
    if (parts.length === 5 && /^\d+$/.test(parts[0]) && /^\d+(,\d+)*$/.test(parts[1]) && parts.slice(2).every(value => value === "*")) {
      const times = parts[1].split(",").map(hour => `${hour.padStart(2, "0")}:${parts[0].padStart(2, "0")}`).join("、");
      return `每天 ${times} · ${s.tz}`;
    }
    return `定时 ${s.trigger.expr} · ${s.tz}`;
  }
  return s.trigger.type === "interval" ? `每 ${s.trigger.every_seconds} 秒 · ${s.tz}` : `一次性 · ${localValue(s.trigger.run_at || "", s.tz).replace("T", " ")} · ${s.tz}`;
};
const errorText = (err) => err.status === 422 ? err.message : friendlyError(err).text;
const setView = (title, view) => {
  $("schedulesTitle").textContent = title;
  body.className = `drawer-body schedule-view-${view}`;
};

export function initSchedules() {
  panel = $("schedulesPanel");
  body = $("schedulesBody");
  $("btnSchedules").addEventListener("click", () => {
    panel.showModal();
    $("btnSchedules").setAttribute("aria-expanded", "true");
    return loadList();
  });
  $("btnSchedulesClose").addEventListener("click", () => panel.close());
  panel.addEventListener("close", () => {
    generation++;
    body.replaceChildren();
    $("btnSchedules").setAttribute("aria-expanded", "false");
    $("btnSchedules").focus();
  });
  panel.addEventListener("click", (e) => {
    // Native dialogs can target the dialog itself when a user clicks its padding.
    // Only a click outside the drawer's bounds should dismiss it.
    if (e.target !== panel) return;
    const bounds = panel.getBoundingClientRect();
    if (e.clientX < bounds.left || e.clientX > bounds.right || e.clientY < bounds.top || e.clientY > bounds.bottom) panel.close();
  });
}

async function loadList() {
  const ticket = ++generation;
  setView("用药与日程", "list");
  body.replaceChildren(h("p", { class: "dw-empty", role: "status", text: "正在读取日程…" }));
  try {
    const res = await api.schedules();
    if (ticket !== generation) return;
    body.replaceChildren();
    defaultTimezone = res.data.tz || "Asia/Shanghai";
    schedulerState = res.data.scheduler || null;
    const { schedules } = res.data;
    if (schedules.length) body.append(h("div", { class: "schedule-list-toolbar" }, [button("新建提醒", () => openScheduleCreate(), "btn btn-primary")]));
    appendSchedulerNotice();
    if (!schedules.length) body.append(h("section", { class: "schedule-empty", "aria-label": "暂无日程" }, [
      h("img", { src: "/static/images/capsule-schedule-empty.svg", alt: "", width: "240", height: "220", "aria-hidden": "true" }),
      h("p", { text: "阿哦～您还有没有建立日程，暂无日程信息" }),
      button("新建提醒", () => openScheduleCreate(), "btn btn-primary"),
    ]));
    for (const s of schedules) {
      body.append(h("button", { type: "button", class: "schedule-row", onClick: () => loadDetail(s.id) }, [
        h("span", { class: "schedule-row-head" }, [h("strong", { text: s.name }), h("span", { class: "badge", text: stateLabel(s) })]),
        h("span", { text: kindLabel(s.job_kind) }),
        h("span", { text: summary(s) }),
        h("span", { text: `下次：${date(s.next_run_at, s.tz)} · ${s.tz}` }),
        h("span", { class: "dw-note", text: `运行次数 ${s.run_count} · 上次 ${RESULTS[s.last_status] || "尚未运行"}` }),
      ]));
    }
  } catch (err) {
    if (ticket !== generation) return;
    body.replaceChildren(h("p", { role: "alert", text: errorText(err) }), button("重试", loadList));
  }
}

function appendSchedulerNotice() {
  if (schedulerState && (!schedulerState.enabled || !schedulerState.alive)) {
    body.append(h("p", { class: "schedule-notice", role: "status", text: "自动提醒服务当前未运行。可以保存提醒，但暂时不会到点执行，请联系管理员开启。" }));
  }
}

export async function openScheduleCreate() {
  if (!panel.open) panel.showModal();
  $("btnSchedules").setAttribute("aria-expanded", "true");
  const ticket = ++generation;
  setView("新建提醒", "create");
  body.replaceChildren(h("p", { text: "正在准备新建提醒…" }));
  try {
    const res = await api.schedules();
    if (ticket !== generation) return;
    defaultTimezone = res.data.tz || "Asia/Shanghai";
    schedulerState = res.data.scheduler || null;
    renderCreate();
  } catch (err) {
    if (ticket === generation) body.replaceChildren(h("p", { role: "alert", text: errorText(err) }), button("重试", openScheduleCreate));
  }
}

function renderCreate() {
  setView("新建提醒", "create");
  const form = h("form", { class: "schedule-form schedule-create" });
  const field = (label, input) => {
    const row = h("label", {}, [h("span", { text: label }), input]);
    form.append(row);
    return row;
  };
  const kind = h("select", { "aria-label": "提醒类型" }, [
    h("option", { value: "medication", text: "每日用药提醒" }),
    h("option", { value: "one_shot_reminder", text: "日程提醒（一次性）" }),
  ]);
  kind.value = "medication";
  field("提醒类型", kind);
  const name = h("input", { required: true, maxlength: 256, placeholder: "填写药品名或日程名称", "aria-label": "提醒名称" });
  field("提醒名称", name);
  const time = h("input", { type: "time", required: true, "aria-label": "每日提醒时间" });
  const timeRow = field("每日提醒时间", time);
  const once = h("input", { type: "datetime-local", "aria-label": "日程日期和时间" });
  const onceRow = field("日程日期和时间", once);
  onceRow.hidden = true;
  const tz = h("input", { value: defaultTimezone, required: true, "aria-label": "提醒时区" });
  field("时区", tz);
  const prompt = h("textarea", { rows: 2, maxlength: 4000, placeholder: "可填写备注；用药名称与剂量请遵循医嘱", "aria-label": "提醒内容" });
  field("提醒内容（用药提醒可选）", prompt);
  const delivery = h("select", { "aria-label": "推送方式" }, [
    h("option", { value: "in_app", text: "仅站内提醒" }),
    h("option", { value: "both", text: "站内 + 已绑定渠道" }),
  ]);
  delivery.value = "in_app";
  field("推送方式", delivery);
  kind.addEventListener("change", () => {
    const medication = kind.value === "medication";
    timeRow.hidden = !medication;
    time.required = medication;
    onceRow.hidden = medication;
    once.required = !medication;
  });
  const status = h("p", { class: "schedule-error", role: "alert" });
  const submit = h("button", { type: "submit", class: "btn btn-primary", text: "下一步：核对提醒" });
  form.append(submit, status);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (submit.disabled) return;
    const title = name.value.trim();
    if (!title) { status.textContent = "请填写提醒名称。"; return; }
    let trigger;
    if (kind.value === "medication") {
      if (!/^\d{2}:\d{2}$/.test(time.value)) { status.textContent = "请选择每日提醒时间。"; return; }
      const [hour, minute] = time.value.split(":").map(Number);
      trigger = { type: "cron", expr: `${minute} ${hour} * * *` };
    } else {
      if (!once.value) { status.textContent = "请选择日程日期和时间。"; return; }
      trigger = { type: "once", run_at: once.value };
    }
    const payload = { name: title, job_kind: kind.value, trigger, tz: tz.value.trim(),
      prompt_text: prompt.value.trim() || (kind.value === "medication" ? `用药提醒：${title}。请按医嘱用药。` : title),
      delivery: delivery.value };
    const ticket = generation;
    submit.disabled = true;
    status.textContent = "正在生成确认卡…";
    try {
      const res = await api.proposeSchedule(payload);
      if (ticket !== generation) return;
      const entry = { data: { proposal: res.data.proposal } };
      const card = scheduleConfirmCard(entry, { save() {}, onDecision: async decision => {
        toast(decision === "confirmed" ? "提醒已创建" : "已取消创建");
        await loadList();
      } });
      const edit = button("", () => {
        generation++;
        status.textContent = "";
        setView("新建提醒", "create");
        body.replaceChildren();
        appendSchedulerNotice();
        body.append(form);
        name.focus();
      }, "btn-icon schedule-confirm-edit");
      edit.setAttribute("aria-label", "修改提醒");
      edit.setAttribute("title", "修改提醒");
      edit.append(h("img", { src: "/static/images/schedule-edit.svg", alt: "", "aria-hidden": "true", width: "22", height: "22" }));
      card.append(edit);
      setView("核对提醒", "confirm");
      body.replaceChildren(card);
    } catch (err) {
      if (ticket === generation) status.textContent = errorText(err);
    } finally {
      submit.disabled = false;
    }
  });
  body.replaceChildren();
  appendSchedulerNotice();
  body.append(form);
  name.focus();
}

function localValue(value, tz) {
  // Keep wall time in the schedule's zone, independent of the browser zone.
  if (!/[zZ]|[+-]\d\d:\d\d$/.test(value)) return value.slice(0, 16);
  const parts = Object.fromEntries(new Intl.DateTimeFormat("sv-SE", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value)).map(p => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

async function loadDetail(id) {
  const ticket = ++generation;
  setView("提醒详情", "detail");
  body.replaceChildren(h("p", { class: "dw-empty", text: "正在读取详情…" }));
  try {
    const [res, history] = await Promise.all([api.schedule(id), api.scheduleRuns(id)]);
    if (ticket !== generation) return;
    const s = res.data;
    const form = h("form", { class: "schedule-form" });
    const field = (label, input) => { form.append(h("label", {}, [h("span", { text: label }), input])); return input; };
    const name = field("名称", h("input", { value: s.name, required: true, maxlength: 256 }));
    const tz = field("时区", h("input", { value: s.tz, required: true }));
    const cron = s.trigger.type === "cron" ? s.trigger.expr.split(/\s+/) : [];
    const clock = cron.length === 5 && /^\d+$/.test(cron[0]) && /^\d+$/.test(cron[1]);
    const time = field(s.trigger.type === "once" ? "提醒时间（任务时区）" : s.trigger.type === "interval" ? "执行间隔（秒）" : clock ? "运行时间（任务时区）" : "定时表达式（分 时 日 月 星期）",
      h("input", { required: true, type: s.trigger.type === "once" ? "datetime-local" : s.trigger.type === "interval" ? "number" : clock ? "time" : "text",
        min: s.trigger.type === "interval" ? 60 : null,
        value: s.trigger.type === "once" ? localValue(s.trigger.run_at || "", s.tz) : s.trigger.type === "interval" ? s.trigger.every_seconds : clock ? `${cron[1].padStart(2, "0")}:${cron[0].padStart(2, "0")}` : s.trigger.expr }));
    const prompt = field(s.job_kind === "custom_nl" ? "自定义指令（仅只读查询）" : "提醒内容 / 备注", h("textarea", { rows: 4, maxlength: 4000, required: s.job_kind === "custom_nl", value: s.prompt_text }));
    const delivery = field("推送方式", h("select", {}, [h("option", { value: "both", text: "站内 + 已绑定渠道" }), h("option", { value: "in_app", text: "仅站内" }),
      h("option", { value: "in_app,email", text: "站内 + 邮件（未配置时跳过）" }), h("option", { value: "in_app,channel,email", text: "站内 + 渠道 + 邮件" })]));
    delivery.value = ["channel", "in_app,channel"].includes(s.delivery) ? "both" : s.delivery;
    if (["email", "channel,email"].includes(s.delivery)) delivery.value = s.delivery === "email" ? "in_app,email" : "in_app,channel,email";
    const channel = field("优先渠道", h("select", {}, [h("option", { value: "auto", text: "自动选择" }), h("option", { value: "feishu", text: "飞书" }), h("option", { value: "wechat", text: "微信" })]));
    channel.value = s.channel_preference;
    const status = h("p", { role: "status", "aria-live": "polite" });
    const actions = h("div", { class: "card-actions" });
    const action = async (fn) => {
      for (const btn of actions.querySelectorAll("button")) btn.disabled = true;
      try { await fn(); toast("已保存"); await loadList(); }
      catch (err) { status.textContent = errorText(err); for (const btn of actions.querySelectorAll("button")) btn.disabled = false; }
    };
    const originalTime = time.value;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const patch = { name: name.value, prompt_text: prompt.value, delivery: delivery.value, channel_preference: channel.value };
      if (tz.value !== s.tz) patch.tz = tz.value;
      if (time.value !== originalTime || tz.value !== s.tz) {
        const trigger = { ...s.trigger };
        delete trigger.tz;
        if (trigger.type === "once") trigger.run_at = time.value;
        else if (trigger.type === "interval") trigger.every_seconds = Number(time.value);
        else if (clock) { const [hour, minute] = time.value.split(":"); trigger.expr = `${Number(minute)} ${Number(hour)} ${cron.slice(2).join(" ")}`; }
        else trigger.expr = time.value;
        patch.trigger = trigger;
      }
      action(() => api.updateSchedule(id, patch));
    });
    actions.append(h("button", { type: "submit", class: "btn btn-primary btn-sm", text: "保存" }));
    if (s.status !== "completed") actions.append(button(s.enabled ? "冻结" : "恢复", () => action(() => api.scheduleAction(id, s.enabled ? "pause" : "resume"))));
    actions.append(button("删除", () => {
      if (window.confirm(`确认删除「${s.name}」？删除后不会再运行。`)) action(() => api.deleteSchedule(id));
    }));
    form.append(actions, status);
    body.replaceChildren(button("← 返回列表", loadList), h("h3", { text: s.name }), h("p", { class: "dw-note", text: summary(s) }),
      h("p", { text: `${stateLabel(s)} · 运行次数 ${s.run_count} · 成功 ${s.success_count} · 失败 ${s.fail_count}` }),
      h("p", { text: `下次：${date(s.next_run_at, s.tz)}` }), form);
    if (s.last_error) body.append(h("p", { role: "alert", text: s.last_error }));
    body.append(h("h3", { text: "运行历史（最近 30 次）" }));
    if (!history.data.length) body.append(h("p", { class: "dw-empty", text: "尚未运行，到点后会在这里留下记录。" }));
    for (const run of history.data) body.append(h("div", { class: "schedule-run" }, [
      h("strong", { text: `${date(run.started_at, s.tz)} · ${run.ok === null ? "运行中 / 结果待确认" : run.ok ? "成功" : "失败"}` }),
      h("p", { text: run.detail.error || run.detail.summary || (run.item_id ? `已生成站内提醒 #${run.item_id}` : "已完成检查") }),
      run.detail.delivery ? h("p", { class: "dw-note", text: run.detail.delivery.ok && !run.detail.delivery.skipped ? "已推送到绑定渠道" : "已保留站内提醒，未推送渠道" }) : null,
      run.detail.email ? h("p", { class: "dw-note", text: run.detail.email.ok && !run.detail.email.skipped ? "邮件已发送" : run.detail.email.reason === "email_unconfigured" ? "邮件未配置，已跳过" : "邮件未发送" }) : null,
    ]));
  } catch (err) {
    if (ticket === generation) body.replaceChildren(button("← 返回列表", loadList), h("p", { role: "alert", text: errorText(err) }));
  }
}

export function scheduleConfirmCard(entry, ctx) {
  const proposal = entry.data.proposal, s = proposal.preview;
  const operation = { create: "创建", update: "修改", delete: "删除" }[proposal.operation];
  const actions = h("div", { class: "card-actions" });
  const status = h("p", { role: "status", "aria-live": "polite" });
  const root = h("section", { class: "card schedule-confirm" }, [
    h("h3", { text: `请确认${operation}定时任务` }), h("strong", { text: s.name }),
    h("p", { text: kindLabel(s.job_kind) }), h("p", { text: summary(s) }),
    h("p", { text: `下次：${date(s.next_run_at, s.tz)}` }),
    h("p", { text: s.prompt_text }),
    h("p", { class: "dw-note", text: deliveryLabel(s) }), actions, status,
  ]);
  const render = () => {
    actions.replaceChildren();
    if (entry.data.decision) { status.textContent = entry.data.decision === "confirmed" ? "已确认并保存" : "已取消"; return; }
    for (const confirmed of [true, false]) actions.append(button(confirmed ? `确认${operation}` : "取消", async () => {
      for (const btn of actions.children) btn.disabled = true;
      try {
        const res = await api.decideSchedule(proposal.id, confirmed);
        entry.data.decision = res.data.status;
        ctx.save(entry);
        render();
        if (ctx.onDecision) await ctx.onDecision(entry.data.decision);
      } catch (err) { status.textContent = errorText(err); for (const btn of actions.children) btn.disabled = false; }
    }, confirmed ? "btn btn-primary btn-sm" : "btn btn-ghost btn-sm"));
  };
  render();
  return root;
}
