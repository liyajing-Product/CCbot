"""Read-only Feishu office tools: calendars and tasks.

These read the *current user's* Feishu data through the OAuth user_access_token
stored in app.data_access.feishu_token. The app-level tenant token cannot read
private calendars, so an absent OAuth grant is reported as a clear, actionable
message for the model to relay — never as a hard failure.
"""

from __future__ import annotations

from app.agent.tool_registry import tool
from app.channels import feishu_client
from app.channels.binding import list_bindings

NOT_CONFIGURED = {
    "ok": False,
    "reason": "feishu_not_configured",
    "message": "飞书应用未配置（缺少 FEISHU_APP_ID / FEISHU_APP_SECRET），暂时读不了飞书日历和任务。",
}

NOT_AUTHORIZED = {
    "ok": False,
    "reason": "feishu_not_authorized",
    "message": "还没有授权我读取你的飞书日历和任务。请打开授权链接 /api/feishu/oauth/start 完成一次授权，之后我就能帮你查日程和待办。",
}


def _open_id_for(user_id: str) -> str:
    for b in list_bindings(user_id):
        if b.get("channel") == "feishu" and b.get("external_user_id"):
            return b["external_user_id"]
    return ""


def _user_token_for(user_id: str) -> tuple[str, str]:
    open_id = _open_id_for(user_id)
    if not open_id:
        return "", ""
    return open_id, feishu_client.get_user_token(open_id=open_id) or ""


@tool(
    "feishu_calendar_list",
    risk_level="read",
    description="列出当前用户的飞书日历列表。 List the current user's Feishu calendars.",
    when_to_use="用户询问自己的飞书日历、日程或会议安排时，先列出日历拿到 calendar_id。 Use to list the user's Feishu calendars before reading events.",
    when_not_to_use="不用于查询他人日历，也不用于创建或修改日程。 Never read another user's calendar or modify events.",
    timeout=30,
)
def feishu_calendar_list(user_id: str = "") -> dict:
    if not feishu_client.is_configured():
        return NOT_CONFIGURED
    open_id, token = _user_token_for(user_id)
    if not open_id or not token:
        return NOT_AUTHORIZED
    return feishu_client.list_calendars(user_token=token)


@tool(
    "feishu_calendar_events",
    risk_level="read",
    description="读取当前用户指定飞书日历在某时间段的日程。 List events in one of the user's Feishu calendars.",
    when_to_use="用户询问某天或某段时间的日程、会议时，先用 feishu_calendar_list 拿 calendar_id，再查日程。 Use to list events for a calendar_id and time range.",
    when_not_to_use="没有 calendar_id 时先列日历；不用于修改或创建日程。 Never modify events or guess a calendar_id.",
    timeout=30,
)
def feishu_calendar_events(
    calendar_id: str,
    start_time: str = "",
    end_time: str = "",
    user_id: str = "",
) -> dict:
    if not feishu_client.is_configured():
        return NOT_CONFIGURED
    if not calendar_id:
        return {"ok": False, "reason": "missing_calendar_id",
                "message": "需要先拿到日历 calendar_id，可以先调用 feishu_calendar_list。"}
    open_id, token = _user_token_for(user_id)
    if not open_id or not token:
        return NOT_AUTHORIZED
    return feishu_client.list_calendar_events(
        user_token=token, calendar_id=calendar_id,
        start_time=start_time, end_time=end_time,
    )


@tool(
    "feishu_task_list",
    risk_level="read",
    description="列出当前用户的飞书任务（待办）。 List the current user's Feishu tasks.",
    when_to_use="用户询问自己的待办、任务清单或今天要做什么时使用。 Use to list the user's Feishu tasks.",
    when_not_to_use="不用于查询他人任务，也不用于创建或修改任务。 Never read another user's tasks or modify them.",
    timeout=30,
)
def feishu_task_list(user_id: str = "") -> dict:
    if not feishu_client.is_configured():
        return NOT_CONFIGURED
    open_id, token = _user_token_for(user_id)
    if not open_id or not token:
        return NOT_AUTHORIZED
    return feishu_client.list_tasks(user_token=token)
