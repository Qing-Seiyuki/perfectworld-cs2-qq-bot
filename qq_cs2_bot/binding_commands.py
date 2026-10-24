"""Handle account commands using authenticated QQ event identity."""
import re
from urllib.parse import quote

from .bindings import BindingStore, valid_steam_id
from .qq_check import CheckError, request_json
from .provider import fetch_detail
from .player_lookup import search_players
from .player_query import render_lookup, render_player_data, render_recent_matches
from .perfect_detail import fetch_season, fetch_recent_matches, fetch_match_page
from .player_history import historical_best
from .report import IncompleteMatch, render_report
from .openid_remote import configured_public_url, qq_link_enabled
from .my_matches import PAGE_SIZE, MAX_PAGE, page_for_number, render_match_list, select_match_id


MATCH_QUERY = re.compile(r"战报\s+((?:PVP@)?[0-9]{19})\Z")


def reply_to_binding(event: dict, token: str, app_id: str, store: BindingStore) -> bool:
    if event.get("op") != 0 or event.get("t") != "GROUP_AT_MESSAGE_CREATE":
        return False
    data = event.get("d")
    if not isinstance(data, dict) or not isinstance(data.get("content"), str):
        return False
    text = re.sub(r"^\s*<@!?[A-Za-z0-9_-]+>\s*", "", data["content"]).strip()
    author = data.get("author")
    if not isinstance(author, dict):
        return False
    member, group, message = author.get("member_openid"), data.get("group_openid"), data.get("id")
    if not all(isinstance(x, str) and x for x in (member, group, message)):
        return False
    # All identity is from the authenticated event, never a QQ number in command text.
    slash_command = text.startswith("/")
    command = text.removeprefix("#").removeprefix("/").strip()
    if command == "帮助":
        if not store.claim_event(app_id, group, message):
            return False
        response = ("【donk666 指令帮助】先 @机器人，再发送：\n"
                    "查询（所有群友可用）：\n"
                    "/数据 昵称或SteamID：查玩家统计\n"
                    "/最近比赛 昵称或SteamID：查该玩家最近五场\n"
                    "绑定：/绑定 SteamID、/验证绑定、/我的绑定、/称呼 名称、/解绑\n"
                    "自己的比赛（须在本群完成绑定验证）：\n"
                    "/我的比赛：最近一场完整战报；/我的比赛 9：最近第 9 场\n"
                    "/我的比赛列表：每页 8 场；/我的比赛列表 2：翻到第 2 页\n"
                    "/9：按列表编号查看第 9 场；/战报 比赛ID：按 ID 查询\n"
                    "自动播报：/播报 状态 分别查看个人订阅与本群总开关。"
                    "验证后用 /个人播报 开 或 /个人播报 关，只切换自己的比赛订阅。\n"
                    "个人订阅和群总开关都开启后，新结束的完美比赛由播报专用账号发到本群。\n"
                    "维护者专用：本群总开关仅由机器人维护者在运行电脑上单独设置；"
                    "群管理员身份不会自动取得此权限，群内没有管理员专用开关指令。")
    elif command == "确认绑定":
        if not store.claim_event(app_id, group, message):
            return False
        binding = store.get_binding(app_id, group, member)
        response = ("账号已验证。发送“我的绑定”查看状态。" if binding and binding["status"] == "verified" else
                    "请向机器人维护者索取 Steam 验证链接；如消息末尾附有链接，也可直接使用。")
    elif command.split()[:1] == ["战报"]:
        if not store.claim_event(app_id, group, message):
            return False
        args = MATCH_QUERY.fullmatch(command)
        binding = store.get_binding(app_id, group, member)
        if not args:
            response = "验证绑定后，可发送：战报 19位比赛ID（无需再填写 SteamID）。"
        elif not binding or binding["status"] != "verified":
            response = "请先绑定并验证账号，再查询自己的战报。"
        else:
            try:
                raw = fetch_detail(args[1])
                # Recheck after the network call: unbinding revokes this association.
                current = store.get_binding(app_id, group, member)
                if not current or current["status"] != "verified" or current["request_id"] != binding["request_id"]:
                    response = "绑定状态已变更，请重新确认后查询。"
                else:
                    response = render_report(raw, binding["steam_id"], qq_labels=store.labels(app_id, group))
            except IncompleteMatch as error:
                response = ("这场比赛里没有找到你绑定的 Steam 账号，请核对比赛 ID。"
                            if str(error) == "这场比赛未找到指定 SteamID" else
                            "这场比赛的数据尚不完整，暂时无法生成战报；请稍后重试。")
            except (OSError, ValueError):
                response = "暂时查不到这场比赛，请核对比赛 ID 或稍后重试。"
    elif command.split()[:1] in (["我的比赛"], ["我的比赛列表"]) or (slash_command and command.isdecimal()):
        if not store.claim_event(app_id, group, message):
            return False
        parts = command.split()
        listing = parts[0] == "我的比赛列表"
        usage = ("请发送：@donk666 /我的比赛列表 [页码]，页码从 1 开始。" if listing else
                 "请发送：@donk666 /我的比赛 [序号]，或从列表发送 @donk666 /数字。")
        number_text = (command if slash_command and command.isdecimal() else
                       parts[1] if len(parts) == 2 else "1" if len(parts) == 1 else "")
        binding = store.get_binding(app_id, group, member)
        if not binding or binding["status"] != "verified":
            response = "请先在本群绑定并验证自己的 Steam 账号，再查询我的比赛。"
        elif not number_text.isdecimal() or len(number_text) > 3:
            response = usage
        else:
            number = int(number_text)
            if listing and not 1 <= number <= MAX_PAGE:
                response = usage
            elif not listing and not 1 <= number <= PAGE_SIZE * MAX_PAGE:
                response = usage
            else:
                try:
                    page, _ = (number, 0) if listing else page_for_number(number)
                    rows = fetch_match_page(binding["steam_id"], page)
                    if rows is None:
                        response = "完美平台的比赛列表暂不可查，请稍后重试。"
                    else:
                        current = store.get_binding(app_id, group, member)
                        if not current or current["status"] != "verified" or current["request_id"] != binding["request_id"]:
                            response = "绑定状态已变更，请重新确认后查询。"
                        elif listing:
                            response = render_match_list(rows, page)
                        else:
                            match_id = select_match_id(rows, number)
                            if match_id is None:
                                response = "没有找到这个序号对应的比赛。可发送 /我的比赛列表 查看。"
                            else:
                                raw = fetch_detail(match_id)
                                current = store.get_binding(app_id, group, member)
                                if not current or current["status"] != "verified" or current["request_id"] != binding["request_id"]:
                                    response = "绑定状态已变更，请重新确认后查询。"
                                else:
                                    response = render_report(raw, binding["steam_id"],
                                                             qq_labels=store.labels(app_id, group))
                except IncompleteMatch:
                    response = "这场比赛的数据尚不完整，暂时无法生成战报；请稍后重试。"
                except (OSError, ValueError):
                    response = "比赛查询暂不可用，请稍后重试。"
    elif command.split()[:1] in (["数据"], ["战绩"], ["最近比赛"]):
        if not store.claim_event(app_id, group, message):
            return False
        parts = command.split(maxsplit=1)
        query = parts[1].strip() if len(parts) == 2 else ""
        recent_only = parts[0] == "最近比赛"
        selected_command = "最近比赛" if recent_only else "数据"
        if not query:
            response = f"发送：{selected_command} 完美昵称，或 {selected_command} 17位SteamID。无需先绑定。"
        elif query.isdecimal() and not valid_steam_id(query):
            response = "SteamID 格式不正确，请填写 17 位 SteamID64。"
        else:
            try:
                candidates = search_players(query)
                if len(candidates) != 1:
                    response = render_lookup(candidates, selection_command=selected_command)
                else:
                    candidate = candidates[0]
                    matches = fetch_recent_matches(candidate.steam_id)
                    if recent_only:
                        response = render_recent_matches(candidate, matches)
                    else:
                        current = fetch_season(candidate.steam_id)
                        if current is None:
                            response = render_lookup(candidates)
                        else:
                            best, complete = historical_best(candidate.steam_id, current)
                            response = render_player_data(candidate, current, best, complete, matches)
            except (OSError, ValueError):
                response = "玩家搜索暂不可用，请稍后重试。"
    else:
        response = store.command(app_id, group, member, message, command)
    if response is None:
        return False
    if command in ("验证绑定", "确认绑定") or command.split()[:1] == ["绑定"]:
        try:
            public_url = configured_public_url()
        except ValueError:
            public_url = None
        if public_url and qq_link_enabled():
            binding = store.get_binding(app_id, group, member)
            if binding and binding["status"] == "pending":
                response += f"\nSteam 验证链接：{public_url}/verify/{binding['request_id']}"
    result = request_json(f"/v2/groups/{quote(group, safe='')}/messages", token=token,
                          payload={"msg_type": 0, "content": response, "msg_id": message, "msg_seq": 1})
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise CheckError("绑定指令已处理，但回复没有取得回执；请发送“我的绑定”核对。")
    return True
