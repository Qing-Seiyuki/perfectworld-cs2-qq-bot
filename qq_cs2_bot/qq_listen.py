"""Bounded QQ gateway diagnostic with an optional one-shot test reply."""
from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlparse

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import connect

from .qq_check import CheckError, credentials, request_json
from .qq_reply import reply_to_test
from .bindings import BindingStore
from .binding_commands import reply_to_binding


def identify(token: str) -> dict:
    return {"op": 2, "d": {"token": "QQBot " + token,
                           "intents": 1 << 25, "shard": [0, 1]}}


def listen(seconds: int | None, ready_only: bool = False, reply_test: bool = False, reply_report: bool = False,
           bindings: bool = False) -> None:
    app_id, secret = credentials()
    store = BindingStore() if bindings else None
    auth = request_json("/app/getAppAccessToken", payload={"appId": app_id, "clientSecret": secret})
    token = auth.get("access_token")
    if not isinstance(token, str) or not token:
        raise CheckError("未获取有效凭证。")
    gateway = request_json("/gateway", token=token)
    address = gateway.get("url", "")
    parsed = urlparse(address)
    # Authentication is only sent to an official QQ gateway.
    host = parsed.hostname or ""
    if parsed.scheme != "wss" or not host.endswith(".qq.com") or parsed.username or parsed.password:
        raise CheckError("网关地址不符合预期，已停止连接。")
    with connect(address, open_timeout=15, close_timeout=3, max_size=1_000_000) as ws:
        hello = json.loads(ws.recv(timeout=15))
        if hello.get("op") != 10:
            raise CheckError("未收到网关 Hello。")
        interval = hello.get("d", {}).get("heartbeat_interval")
        if type(interval) not in (int, float) or not 1000 <= interval <= 300000:
            raise CheckError("网关心跳周期异常。")
        interval /= 1000
        ws.send(json.dumps(identify(token)))
        # Refresh the API token before its two-hour lifetime expires.
        deadline = time.monotonic() + (seconds if seconds is not None else 105 * 60)
        ready_deadline = time.monotonic() + 15
        next_heartbeat = time.monotonic() + interval
        sequence = None
        ack_pending = False
        ready = False
        received = 0
        attempted = set()
        while time.monotonic() < deadline:
            now = time.monotonic()
            if not ready and now >= ready_deadline:
                raise CheckError("网关未在规定时间内完成登录。")
            if now >= next_heartbeat:
                if ack_pending:
                    raise CheckError("网关心跳未确认，已断开本次诊断连接。")
                ws.send(json.dumps({"op": 1, "d": sequence}))
                ack_pending = True
                next_heartbeat = now + interval
            try:
                event = json.loads(ws.recv(timeout=min(1, max(0.01, deadline - now))))
            except TimeoutError:
                continue
            if event.get("s") is not None:
                sequence = event["s"]
            op = event.get("op")
            if op == 11:
                ack_pending = False
            elif op == 1:
                ws.send(json.dumps({"op": 1, "d": sequence}))
            elif op in (7, 9):
                raise CheckError("网关要求重连或拒绝会话；本次诊断已停止。")
            elif op == 0 and event.get("t") == "READY":
                ready = True
                print("QQ 网关登录成功，群 @消息订阅已接受。", flush=True)
                if ready_only:
                    return
                print("群指令已就绪：帮助、绑定、称呼、我的绑定、解绑、播报、战报、数据、最近比赛、我的比赛、我的比赛列表。" if bindings else
                      "等待群内 @机器人 战报 比赛ID SteamID，回复一次后退出。" if reply_report else
                      "等待群内 @机器人 测试，成功回复一次后退出。" if reply_test else
                      "正在等待测试群 @消息；不保存聊天内容、不自动回复。", flush=True)
            elif op == 0 and event.get("t") == "GROUP_AT_MESSAGE_CREATE":
                received += 1
                print(f"已收到第 {received} 条群 @消息。", flush=True)
                if store is not None:
                    try:
                        if reply_to_binding(event, token, app_id, store):
                            print("绑定相关指令已处理并取得回复回执。", flush=True)
                    except CheckError as error:
                        print(f"回复未确认：{error} 请在群内查询当前绑定状态。", flush=True)
                if (reply_test or reply_report) and reply_to_test(event, token, attempted, report_mode=reply_report):
                    print("指令回复已发送，QQ 平台已返回消息回执。本次测试结束。", flush=True)
                    return
        if not ready:
            raise CheckError("未完成网关登录。")
        print(f"本次监听结束，共收到 {received} 条群 @消息。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="QQ 网关诊断，默认只接收")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--ready-only", action="store_true")
    parser.add_argument("--reply-test", action="store_true", help="仅回复一次群 @测试 指令")
    parser.add_argument("--reply-report", action="store_true", help="回复一次手动战报查询")
    parser.add_argument("--bindings", action="store_true", help="处理绑定、我的绑定、解绑指令")
    parser.add_argument("--forever", action="store_true", help="持续运行，断线后自动重新连接")
    args = parser.parse_args()
    if not args.forever and not 15 <= args.seconds <= 600:
        parser.error("监听时长须为 15～600 秒")
    if sum((args.ready_only, args.reply_test, args.reply_report, args.bindings)) > 1:
        parser.error("请只选择一种诊断模式")
    if args.forever and (args.ready_only or args.reply_test or args.reply_report or not args.bindings):
        parser.error("持续运行模式需单独使用 --forever --bindings")
    delay = 5
    while True:
        try:
            listen(None if args.forever else args.seconds,
                   args.ready_only, args.reply_test, args.reply_report, args.bindings)
            if not args.forever:
                return
            delay = 5
        except KeyboardInterrupt:
            print("已停止监听。")
            return
        except CheckError as error:
            message = f"连接检查失败：{error}"
        except ConnectionClosed as error:
            code = error.rcvd.code if error.rcvd else "未知"
            message = f"网关关闭连接，代码 {code}；需检查事件权限或接入方式。"
        except (OSError, ValueError, WebSocketException, TimeoutError):
            message = "连接或响应异常；请检查网络与平台接入配置。"
        print(message, flush=True)
        if not args.forever:
            parser.exit(1)
        print(f"{delay} 秒后重新连接。", flush=True)
        time.sleep(delay)
        delay = min(delay * 2, 60)


if __name__ == "__main__":
    main()
