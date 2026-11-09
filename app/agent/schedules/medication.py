"""Offline medication reminder parsing for the health companion.

The generic schedule flow is model-selected; with no model key configured the
common phrasings (「每天早上8点提醒我吃降压药」) still work through these
deterministic rules. The proposal still goes through the same confirmation card
and owner-scoped scheduler as every other schedule.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_NUMBER = r"[零〇一二两三四五六七八九十\d]{1,3}"
_MED_TIME = re.compile(rf"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|夜里|夜间)?({_NUMBER})(?:点|时|:|：)(半|{_NUMBER}分?)?")
_MED_DETECT = re.compile(r"每天|每日|每[早晚]|早上|晚上|上午|中午|下午")
_MED_VERB = re.compile(r"吃|服用|服药|用药")
_FOOD = re.compile(r"早饭|早餐|午饭|午餐|晚饭|晚餐|夜宵|宵夜|盒饭|外卖|吃饭|饭|菜|水果|零食|点心|面包|牛奶|鸡蛋|鱼|肉|虾|粥|面条|米饭")
_DOSE = re.compile(r"(\d+(?:\.\d+)?|[半一两二三四五])\s*(片|粒|颗|丸|袋|支|毫升|mg|毫克)")


def _number(value):
    if value.isdigit():
        return int(value)
    digits = dict(zip('零〇一二两三四五六七八九', (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    if value in digits:
        return digits[value]
    if value.count('十') == 1:
        left, right = value.split('十')
        if (not left or left in digits) and (not right or right in digits):
            return digits.get(left, 1) * 10 + digits.get(right, 0)
    return None


def _clock(match) -> Optional[str]:
    period = match.group(1) or ""
    hour = _number(match.group(2))
    raw_minute = match.group(3) or "0"
    minute = 30 if raw_minute == "半" else _number(raw_minute.removesuffix("分"))
    if hour is None or minute is None or not 0 <= minute <= 59:
        return None
    if period in ("下午", "傍晚"):
        if 1 <= hour <= 11:
            hour += 12
    elif period in ("晚上", "夜里", "夜间"):
        if hour == 12:
            hour = 0
        elif 1 <= hour <= 11:
            hour += 12
    elif period == "中午":
        if 1 <= hour <= 11:
            hour += 12
    # 凌晨/早上/上午/无时段: keep the hour as written.
    if hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"


def looks_like_medication_reminder(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 200:
        return False
    if _FOOD.search(t):
        return False
    return bool(_MED_DETECT.search(t) or _MED_TIME.search(t)) and bool(_MED_VERB.search(t))


def parse_medication(text: str) -> Optional[dict[str, Any]]:
    """Extract {name, dose, times, cron} or None when incomplete/ambiguous."""
    t = (text or "").strip()
    times: list[str] = []
    for m in _MED_TIME.finditer(t):
        value = _clock(m)
        if value is None:
            return None
        if value not in times:
            times.append(value)
    if not times:
        return None

    dose = ""
    dm = _DOSE.search(t)
    if dm:
        dose = dm.group(0)

    name = ""
    nm = re.search(r"(?:吃|服用|服药|用药)\s*([^，,。！!？?\s]{1,20})", t)
    if nm:
        name = nm.group(1).strip()
    if dose:
        name = name.replace(dose, "").strip()
    name = re.sub(r"[了呀啊哦]*(?:要|该)?$", "", name).strip()
    if not name or name in ("药", "的"):
        return None

    hours = sorted({int(v[:2]) for v in times})
    minutes = sorted({int(v[3:5]) for v in times})
    if len(minutes) == 1:
        cron_expr = f"{minutes[0]} {','.join(map(str, hours))} * * *"
    else:
        return None  # Different minute values need separate reminders, never approximate.
    return {"name": name, "dose": dose, "times": times, "cron": cron_expr}


def propose_medication(user_id: str, text: str) -> Optional[dict[str, Any]]:
    """Build a confirmation-card proposal, or a clarifying question."""
    from .service import propose

    if re.search(r"今天|明天|后天|下周|本周|星期|周[一二三四五六日天]|\d+月\d+[日号]", text):
        return {"messages": [{"role": "assistant", "content": "这是一次性用药提醒。请打开「用药与日程 → 新建提醒」，选择日程提醒并填写具体日期和时间。"}]}
    parsed = parse_medication(text)
    if parsed is None:
        return {
            "messages": [{
                "role": "assistant",
                "content": "要提醒你吃什么药、几点吃？比如：每天早上8点提醒我吃降压药。不同分钟的服药时间请分别建立提醒。",
            }],
        }
    name = parsed["name"]
    dose = parsed["dose"]
    title = f"{name}" + (f" {dose}" if dose else "")
    prompt = f"该吃{name}了" + (f"，{dose}" if dose else "") + "。记得按时服药。"
    schedule = {
        "name": title,
        "job_kind": "medication",
        "trigger": {"type": "cron", "expr": parsed["cron"]},
        "prompt_text": prompt,
        "delivery": "both",
    }
    result = propose(user_id, "create", schedule)
    return {
        "schedule_proposal": result["proposal"],
        "messages": [{"role": "assistant", "content": "请核对这张用药提醒卡，确认后才会保存。"}],
    }
