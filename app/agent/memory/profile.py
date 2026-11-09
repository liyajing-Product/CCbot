"""Profile memory API — thin facade over app.db (working archive layer)."""

from __future__ import annotations

import re
from typing import Any, Optional

from app import db

# Generic personal profile fields shown in prompts and on the memory card.
SCALAR_FIELDS = ("name", "city", "tz", "occupation", "blood_type", "emergency_contact", "primary_doctor")
LIST_FIELDS = ("interests", "preferences", "facts", "medical_history", "medications", "allergies")
LABELS = {
    "name": "姓名",
    "city": "城市",
    "tz": "时区",
    "occupation": "职业",
    "interests": "兴趣",
    "preferences": "偏好",
    "facts": "备注",
    "dialogue_summary": "对话摘要",
    "blood_type": "血型",
    "emergency_contact": "紧急联系人",
    "primary_doctor": "主治医生",
    "medical_history": "病史",
    "medications": "用药清单",
    "allergies": "过敏史",
}


def get(user_id: str) -> dict[str, Any]:
    return db.get_profile(user_id)


def save(user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    return db.save_profile(user_id, profile)


def merge(user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    return db.merge_and_save(user_id, patch)


_NAME_REQUEST = r"(?:请)?(?:帮我)?(?:记住(?:我(?:的名字)?)?|记一下)"


def _name_value(text: str) -> str:
    # Remove requests before matching CJK names: without a separator, a greedy
    # name match would otherwise pin the request itself as part of the name.
    text = text.strip().rstrip("。.!！ ")
    text = re.sub(rf"[，,。!！\s]*{_NAME_REQUEST}$", "", text).strip()
    if re.search(r"[吗呢吧么嘛]|请|记住|记一下", text):
        return ""
    # In “我叫同事来帮忙”, 叫 introduces an action, not an identity.
    # Reject action phrases, without rejecting names containing e.g. 来 alone.
    if re.search(r"(?:来|去)(?:帮|找|做|开|拿|送|接|处理|工作)|(?:帮|替|让)(?:我|你|他|她)", text):
        return ""
    if re.fullmatch(r"[一-鿿]{2,12}|[A-Za-z][A-Za-z .'-]{0,63}", text):
        return text
    return ""


def _declared_name(message: str) -> str:
    match = re.fullmatch(
        r"\s*(?:(?:你好|是的|对的|对)[，,。!！\s]+)?"
        r"(?:(?:请)?(?:记住|记一下)[，,：:\s]*)?"
        r"(?:我叫(?![你他她它了过]|外卖|出租车|网约车)|我的(?:名字|姓名)(?:是|叫|为|[：:])|my name is\s+)\s*"
        r"(?P<name>[^，,。!！?？；;\n]+?)[。.!！\s]*"
        r"(?:[，,。!！；;\n]\s*(?P<following>.*))?",
        message, re.IGNORECASE,
    )
    # A trailing courtesy/request is not part of the name. A question asking
    # us to verify the declaration still is not confirmed identity evidence.
    if match and re.match(r"(?:对吗|是吗|没错吧)", match.group("following") or ""):
        return ""
    return _name_value(match.group("name")) if match else ""


def _contextual_name(message: str, previous_turn: dict[str, str]) -> str:
    """Resolve only an immediate name question explicitly answered by the user.

    Assistant assertions alone and machine summaries are not identity evidence.
    The caller supplies revision-checked, owner/thread-local conversation turns.
    """
    previous = previous_turn.get("assistant", "").strip()
    confirmation = re.fullmatch(
        rf"\s*(?:是的|是|对的|对|没错|正确|yes)[，,。!！\s]*(?:{_NAME_REQUEST})?[。.!！\s]*",
        message, re.IGNORECASE,
    )
    if confirmation:
        match = re.fullmatch(
            r"(?:所以[，,]?\s*)?(?:你叫|你的(?:名字|姓名)(?:是|叫|为|[：:]))\s*"
            r"(?P<name>.+?)(?:[，,。\s]*(?:对吗|是吗|没错吧)|吗)?[？?。.!！\s]*",
            previous,
        )
        if match and _name_value(match.group("name")):
            return _name_value(match.group("name"))
        if not re.search(r"示例|例如|比如|举.*例|假设|如果|[“”「」\"]", previous):
            # A direct confirmation question can be one clause in a longer
            # conversational reply. Keep clause boundaries and require a
            # question here so incidental mentions are not treated as identity.
            match = re.search(
                r"(?:^|[，,。！？!?\n])\s*(?:所以[，,]?\s*)?"
                r"(?:你叫|你的(?:名字|姓名)(?:是|叫|为|[：:]))\s*"
                r"(?P<name>[^，,。！？!?；;\n]+?)"
                r"(?:[，,\s]*(?:对吗|是吗|没错吧)|吗)[？?]",
                previous,
            )
        return _name_value(match.group("name")) if match else ""
    if re.fullmatch(
        r"(?:请问[，,]?\s*)?(?:你叫什么(?:名字)?|你的(?:名字|姓名)是什么)[？?。\s]*",
        previous,
    ):
        if re.match(r"\s*(?:我)?(?:不|没|暂|稍后|以后|保密|算了|忘了|随便)", message):
            return ""
        return _name_value(message)
    return ""


def remember_name(user_id: str, message: str, *, thread_id: str = "",
                  previous_turn: Optional[dict[str, str]] = None) -> None:
    """Persist a declared or contextually confirmed name before summarization."""
    name = _declared_name(message) or _contextual_name(message, previous_turn or {})
    if not name:
        return
    from app.agent.harness.leak import memory_safe
    from app.agent.memory.redact import display_text
    from app.agent.memory import episodic

    if display_text(name) != name or memory_safe(name, user_id) != name:
        return
    with db.memory_transaction():
        stored = get(user_id)
        if stored.get("name") == name:
            return
        merge(user_id, {
            "name": name,
            "pinned_fields": sorted(set(stored.get("pinned_fields") or []) | {"name"}),
            "memory_rev": int(stored.get("memory_rev", 0)) + 1,
        })
        event = episodic.write_event(
            user_id, "profile_updated", f"姓名：{name}",
            tags=["profile", "memory"], thread_id=thread_id,
        )
        if not event:
            raise RuntimeError("Could not persist name memory")


# Offline health-fact capture: common chronic diseases and simple medication /
# allergy patterns. Conservative by design — LLM tool selection remains the
# authoritative path when a model is configured.
_CHRONIC_DISEASES = (
    "高血压", "糖尿病", "冠心病", "高血脂", "高脂血症", "痛风", "哮喘", "慢阻肺",
    "慢性支气管炎", "脑梗", "心梗", "房颤", "心律失常", "胃溃疡", "慢性胃炎",
    "脂肪肝", "骨质疏松", "甲状腺结节", "慢性肾病", "颈椎病", "腰椎间盘突出",
    "类风湿", "阿尔茨海默", "帕金森", "乙肝", "丙肝",
)
_MED_HINT = re.compile(
    r"药|片|丸|胶囊|素|胺|地平|沙坦|普利|洛尔|他汀|双胍|阿司匹林|胰岛素|"
    r"硝苯|氨氯|缬沙坦|氯沙坦|卡托|美托|比索|辛伐|阿托伐|瑞舒|二甲双|格列"
)
_MED_FOOD = re.compile(r"饭|菜|水果|零食|早餐|午饭|晚饭|夜宵|点心|面包|牛奶|鸡蛋|鱼|肉|虾|粥|面|米")


def _declared_health(message: str) -> dict[str, list[str]]:
    """Conservative offline extraction of health facts → {field: [values]}."""
    t = (message or "").strip()
    if not t:
        return {}
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"对([^，。！？,.!?\n]{1,20}?)过敏", t):
        v = m.group(1).strip()
        if v and "不" not in v and "没" not in v:
            out.setdefault("allergies", []).append(v)
    for name in _CHRONIC_DISEASES:
        if re.search(rf"(?:有|患有|得了|得过|确诊|病史)[^，。！？,.!?\n]{{0,6}}{re.escape(name)}", t):
            out.setdefault("medical_history", []).append(name)
    for m in re.finditer(
        r"(?:在吃|在服用|服用|每天吃|早晚吃|按时吃|吃着|吃的药[是:：]?)\s*([^，。！？,.!?\n]{1,30})", t
    ):
        v = m.group(1).strip()
        if v and _MED_HINT.search(v) and not _MED_FOOD.search(v):
            out.setdefault("medications", []).append(v)
    return out


def remember_health(user_id: str, message: str, *, thread_id: str = "") -> None:
    """Persist conservatively-detected health facts before summarization."""
    patch = _declared_health(message)
    if not patch:
        return
    from app.agent.harness.leak import memory_safe
    from app.agent.memory.redact import display_text
    from app.agent.memory import episodic

    with db.memory_transaction():
        stored = get(user_id)
        clean_patch: dict[str, Any] = {}
        for field, values in patch.items():
            kept = [v for v in values if display_text(v) == v and memory_safe(v, user_id) == v]
            if kept:
                clean_patch[field] = kept
        new_patch: dict[str, Any] = {}
        for field, values in clean_patch.items():
            existing = set(stored.get(field) or [])
            fresh = [v for v in values if v not in existing]
            if fresh:
                new_patch[field] = fresh
        if not new_patch:
            return
        new_patch["memory_rev"] = int(stored.get("memory_rev", 0)) + 1
        merge(user_id, new_patch)
        labels = "、".join(LABELS.get(f, f) for f in new_patch if f != "memory_rev")
        episodic.write_event(
            user_id, "profile_updated", f"已记录：{labels}",
            tags=["profile", "memory", "health"], thread_id=thread_id,
        )


def _clean_items(items: Any, limit: int) -> list[str]:
    from app.agent.memory.redact import display_text

    out: list[str] = []
    for item in list(items or [])[:limit]:
        text = display_text(str(item))
        if text:
            out.append(text)
    return out


def snapshot(user_id: str) -> dict[str, Any]:
    """Compact profile for prompts and the memory card.

    Credential-shaped text is removed so prompts never repeat passwords,
    cookies, or tokens. Reads the saved profile, so an edit is visible on the
    next call.
    """
    from app.agent.memory.redact import display_text

    p = get(user_id) or {}
    out: dict[str, Any] = {
        "name": display_text(str(p.get("name") or "")),
        "city": display_text(str(p.get("city") or "")),
        "tz": display_text(str(p.get("tz") or "")),
        "occupation": display_text(str(p.get("occupation") or "")),
        "interests": _clean_items(p.get("interests"), 30),
        "preferences": _clean_items(p.get("preferences"), 30),
        "facts": _clean_items(p.get("facts"), 40),
        "blood_type": display_text(str(p.get("blood_type") or "")),
        "emergency_contact": display_text(str(p.get("emergency_contact") or "")),
        "primary_doctor": display_text(str(p.get("primary_doctor") or "")),
        "medical_history": _clean_items(p.get("medical_history"), 30),
        "medications": _clean_items(p.get("medications"), 40),
        "allergies": _clean_items(p.get("allergies"), 30),
        "dialogue_summary": display_text(str(p.get("dialogue_summary") or ""))[:800],
        "last_summary_kind": p.get("last_summary_kind") or "",
        "previous_cities": [
            c for c in (display_text(str(x)) for x in (p.get("previous_cities") or [])[:5])
            if c and c != display_text(str(p.get("city") or ""))
        ],
    }
    return out


def format_for_prompt(user_id: str) -> str:
    s = snapshot(user_id)
    if not any(s.get(k) for k in SCALAR_FIELDS + LIST_FIELDS):
        return "【个人档案】（空）"
    parts = ["【个人档案】"]
    if s.get("name"):
        parts.append(f"姓名：{s['name']}")
    if s.get("city"):
        parts.append(f"城市：{s['city']}")
    if s.get("city") and s.get("previous_cities"):
        olds = "、".join(f"「{c}」" for c in s["previous_cities"])
        parts.append(
            f"用户已把城市改为「{s['city']}」（以此为准）；{olds}是旧城市，"
            f"回复里不要再把它说成用户所在的城市。"
        )
    if s.get("occupation"):
        parts.append(f"职业：{s['occupation']}")
    if s.get("interests"):
        parts.append("兴趣：" + "、".join(s["interests"][:20]))
    if s.get("preferences"):
        parts.append("偏好：" + "；".join(s["preferences"][:20]))
    if s.get("facts"):
        parts.append("备注：" + "；".join(s["facts"][:20]))
    if s.get("medical_history"):
        parts.append("病史：" + "；".join(s["medical_history"][:20]))
    if s.get("medications"):
        parts.append("用药清单：" + "；".join(s["medications"][:30]))
    if s.get("allergies"):
        parts.append("过敏史：" + "；".join(s["allergies"][:20]))
    if s.get("blood_type"):
        parts.append(f"血型：{s['blood_type']}")
    if s.get("primary_doctor"):
        parts.append(f"主治医生：{s['primary_doctor']}")
    if s.get("emergency_contact"):
        parts.append(f"紧急联系人：{s['emergency_contact']}")
    if s.get("dialogue_summary"):
        parts.append(
            "对话摘要（可能有误的机器摘要，不是已核实事实）："
            "区分用户与助手的发言，不要把助手的建议或拒绝归于用户；"
            "不要向用户复述摘要中的评价。\n"
            + s["dialogue_summary"][:400]
        )
    return "\n".join(parts)


# Health-query detection + in-thread health card (offline-safe).
_HEALTH_QUERY = re.compile(
    "|".join(
        (
            r"我的健康档案", r"健康档案",
            r"我的病史", r"我的用药", r"我的过敏",
            r"我的血型", r"我的紧急联系人", r"我的主治医生",
            r"我吃什么药", r"我在吃什么药", r"我有什么病",
            r"用药清单", r"过敏史",
        )
    )
)


def looks_like_health_query(text: str) -> bool:
    """Conservative offline check: is the user asking about their own health?"""
    t = (text or "").strip()
    if not t or len(t) > 200:
        return False
    return bool(_HEALTH_QUERY.search(t))


def health_card_view(user_id: str) -> Optional[dict[str, Any]]:
    """Health snapshot for the in-thread health card, or None if empty."""
    from app.agent.memory.redact import display_text

    p = get(user_id) or {}
    scalars: list[dict[str, str]] = []
    for field, label in (("blood_type", "血型"), ("emergency_contact", "紧急联系人"), ("primary_doctor", "主治医生")):
        value = display_text(str(p.get(field) or "")).strip()
        if value:
            scalars.append({"label": label, "value": value})
    lists: list[dict[str, Any]] = []
    for field, label in (("medical_history", "病史"), ("medications", "用药清单"), ("allergies", "过敏史")):
        items = _clean_items(p.get(field), 30)
        if items:
            lists.append({"label": label, "items": items})
    if not scalars and not lists:
        return None
    return {"scalars": scalars, "lists": lists}
