import { $, h } from "./core.js?v=__APP_VERSION__";
import { getProfile, openDrawer, closeDrawer } from "./drawer.js?v=__APP_VERSION__";

// Reuse the account-scoped profile already loaded by the application.
// No second API request or separate cache of health information.
function renderWorkspace() {
  const profile = document.getElementById("sessionBlocked") ? null : getProfile();
  const name = String(profile?.name || "");
  $("workspaceUser").textContent = "个人空间";
  $("contextAvatar").textContent = name ? Array.from(name)[0] : "H";
  $("contextName").textContent = name || "我的健康档案";
  $("contextMeta").textContent = profile ? (profile.city || "") : "档案暂不可用，可打开档案重试";
  $("contextBlood").textContent = profile?.blood_type ? `血型 ${profile.blood_type}` : "血型待填写";
  for (const [id, key] of [["contextHistory", "medical_history"], ["contextMedications", "medications"], ["contextAllergies", "allergies"]]) {
    const values = profile?.[key];
    const items = Array.isArray(values) ? values : values ? [values] : [];
    $(id).replaceChildren(...(items.length ? items.map(value => h("span", { class: "context-value", text: String(value) })) : [h("p", { class: "context-empty", text: profile ? "尚未记录" : "暂未加载到档案信息" })]));
  }
  const greeting = $("heroGreeting");
  if (greeting) greeting.textContent = name ? `你好，${name}` : "你好，欢迎回来";
}
const navIds = ["workspaceHome", "workspaceAssistant", "btnMemory", "btnSchedules", "btnProfile", "workspaceAccount"];
let baseNav = "workspaceHome";
function syncNavigation() {
  const active = $("schedulesPanel").open ? "btnSchedules" : $("drawer").classList.contains("is-open") ? "btnProfile" : baseNav;
  for (const id of navIds) {
    const selected = id === active;
    $(id).classList.toggle("is-selected", selected);
    if (selected) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
}
function showPage(account = false) {
  if (!account && $("main").hidden) {
    const hero = $("hero");
    if (hero) delete hero.dataset.auroraPlayed;
    $("homeAurora")?.classList.remove("is-playing");
  }
  $("main").hidden = account;
  $("healthSpace").hidden = !account;
  document.body.classList.toggle("show-health-space", account);
  baseNav = account ? "workspaceAccount" : "workspaceHome";
  syncNavigation();
}
function openProfile() { openDrawer(); syncNavigation(); }
for (const id of ["workspaceEditProfile", "contextOpen"]) $(id).addEventListener("click", openProfile);
for (const id of ["workspaceSchedule", "contextReminder"]) $(id).addEventListener("click", () => $("btnSchedules").click());
$("workspaceAccount").addEventListener("click", () => {
  closeDrawer();
  if ($("schedulesPanel").open) $("schedulesPanel").close();
  showPage(true);
  renderWorkspace();
  $("healthSpace").focus();
});
$("spaceBack").addEventListener("click", () => { $("workspaceAssistant").click(); $("workspaceAssistant").focus(); });
$("brandLogo").addEventListener("click", () => showPage());
$("workspaceHome").addEventListener("click", event => {
  event.preventDefault();
  $("brandLogo").click();
  renderWorkspace();
});
$("workspaceAssistant").addEventListener("click", event => {
  event.preventDefault();
  showPage();
  baseNav = "workspaceAssistant";
  syncNavigation();
});
$("btnMemory").addEventListener("click", () => {
  closeDrawer();
  if ($("schedulesPanel").open) $("schedulesPanel").close();
  showPage();
  baseNav = "btnMemory";
  syncNavigation();
});
$("btnSchedules").addEventListener("click", () => { closeDrawer(); syncNavigation(); });
$("btnProfile").addEventListener("click", syncNavigation);
$("schedulesPanel").addEventListener("close", syncNavigation);
const selectAssistant = () => { baseNav = "workspaceAssistant"; syncNavigation(); };
$("composer").addEventListener("submit", selectAssistant);
$("composerInput").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && $("composerInput").value.trim()) selectAssistant();
});
new MutationObserver(syncNavigation).observe($("drawer"), { attributes: true, attributeFilter: ["class"] });
new MutationObserver(syncNavigation).observe($("schedulesPanel"), { attributes: true, attributeFilter: ["open"] });
window.addEventListener("profile-updated", renderWorkspace);
new MutationObserver(() => {
  if (baseNav === "workspaceHome" && !$("hero") && $("log").children.length) baseNav = "workspaceAssistant";
  renderWorkspace();
  syncNavigation();
}).observe($("log"), { childList: true });
new MutationObserver(renderWorkspace).observe($("main"), { childList: true });
showPage();
renderWorkspace();
