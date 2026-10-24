"""One-shot reply diagnostic for an explicit group test command."""
import re
from urllib.parse import quote

from .qq_check import CheckError, request_json
from .provider import fetch_detail
from .report import render_report

TEST_REPLY = "收到测试消息！QQ 机器人收发连接正常。"


def reply_to_test(event: dict, token: str, attempted: set[tuple[str, str]], *, report_mode: bool = False) -> bool:
    if event.get("op") != 0 or event.get("t") != "GROUP_AT_MESSAGE_CREATE":
        return False
    data = event.get("d")
    if not isinstance(data, dict):
        return False
    content = data.get("content")
    if not isinstance(content, str):
        return False
    # QQ may retain a leading bot mention in the event text.
    command = re.sub(r"^\s*<@!?[A-Za-z0-9_-]+>\s*", "", content).strip()
    report_args = None
    if report_mode:
        report_args = re.fullmatch(r"战报\s+((?:PVP@)?[0-9]{19})\s+([0-9]{17})", command)
        if not report_args:
            return False
    elif command != "测试":
        return False
    group, message = data.get("group_openid"), data.get("id")
    if not all(isinstance(value, str) and value for value in (group, message)):
        raise CheckError("测试事件缺少群或消息标识。")
    key = (group, message)
    if key in attempted:
        return False
    # Do not retry an ambiguous send: the server may have accepted it already.
    attempted.add(key)
    content = TEST_REPLY
    if report_args:
        try:
            # This is a manual lookup, not a verified QQ-to-Steam binding.
            content = render_report(fetch_detail(report_args[1]), report_args[2])
        except (OSError, ValueError):
            content = "暂时无法生成完整战报，请核对比赛 ID 和 SteamID，或稍后重试。"
    result = request_json(f"/v2/groups/{quote(group, safe='')}/messages", token=token,
                          payload={"msg_type": 0, "content": content,
                                   "msg_id": message, "msg_seq": 1})
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise CheckError("发送未获得消息回执；请核对群内是否收到，程序不会自动重发。")
    return True
