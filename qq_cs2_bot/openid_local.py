"""One-time Steam OpenID verification on this Windows computer.

The local callback works for a browser running on the same computer. A hosted
callback will be needed before other QQ group members can use this flow.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import re
import secrets
import socket
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener
import webbrowser

from .bindings import BindingStore
from .qq_check import NoRedirect

STEAM_ENDPOINT = "https://steamcommunity.com/openid/login"
OPENID_NS = "http://specs.openid.net/auth/2.0"
SELECT_ID = "http://specs.openid.net/auth/2.0/identifier_select"


class OpenIDError(ValueError):
    pass


def login_url(return_to: str, realm: str) -> str:
    params = {"openid.ns": OPENID_NS, "openid.mode": "checkid_setup",
              "openid.return_to": return_to, "openid.realm": realm,
              "openid.identity": SELECT_ID, "openid.claimed_id": SELECT_ID}
    return STEAM_ENDPOINT + "?" + urlencode(params)


def verified_steam_id(query: str, expected_return_to: str, *, opener=None) -> str:
    values = parse_qs(query, keep_blank_values=True, max_num_fields=30)
    if any(len(v) != 1 for v in values.values()):
        raise OpenIDError("Steam 回调参数重复。")
    fields = {key: value[0] for key, value in values.items()}
    if fields.get("openid.ns") != OPENID_NS or fields.get("openid.mode") != "id_res":
        raise OpenIDError("Steam 登录未完成。")
    if fields.get("openid.op_endpoint") != STEAM_ENDPOINT:
        raise OpenIDError("Steam 身份提供方不匹配。")
    if fields.get("openid.return_to") != expected_return_to:
        raise OpenIDError("登录会话不匹配或已过期。")
    required_signed = {"return_to", "claimed_id", "identity", "response_nonce", "assoc_handle", "op_endpoint"}
    signed = set(fields.get("openid.signed", "").split(","))
    if not required_signed <= signed or not fields.get("openid.sig"):
        raise OpenIDError("Steam 签名字段不完整。")
    claimed = fields.get("openid.claimed_id", "")
    match = re.fullmatch(r"https?://steamcommunity\.com/openid/id/([0-9]{17})", claimed)
    if not match or fields.get("openid.identity") != claimed:
        raise OpenIDError("Steam 账号标识不符合预期。")
    if not fields.get("openid.response_nonce") or not fields.get("openid.assoc_handle"):
        raise OpenIDError("Steam 响应缺少防重放信息。")
    # The claimed identity is trusted only after Steam validates the signed
    # assertion via check_authentication. Never trust a browser redirect alone.
    fields["openid.mode"] = "check_authentication"
    request = Request(STEAM_ENDPOINT, data=urlencode(fields).encode("utf-8"),
                      headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, method="POST")
    try:
        with (opener or build_opener(NoRedirect())).open(request, timeout=15) as response:
            body = response.read(4097)
    except OSError:
        raise OpenIDError("无法向 Steam 核验登录结果。") from None
    if len(body) > 4096:
        raise OpenIDError("Steam 核验响应异常。")
    answers = dict(line.split(":", 1) for line in body.decode("utf-8", "replace").splitlines() if ":" in line)
    if answers.get("is_valid") != "true":
        raise OpenIDError("Steam 未确认这次登录。")
    return match.group(1)


def run(request_id: str, *, store: BindingStore | None = None, timeout: int = 600) -> bool:
    store = store or BindingStore()
    # Only one pending request with this random ID; no user identity is taken
    # from the browser callback. The QQ event created the original record.
    with store.transaction() as db:
        row = db.execute("SELECT steam_id FROM bindings WHERE request_id=? AND status='pending'", (request_id,)).fetchone()
        if row is None:
            raise OpenIDError("找不到待验证申请。请先在群里重新绑定。")
        expected_steam_id = row["steam_id"]
    state = secrets.token_urlsafe(24)
    result = {"approved": False}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log Steam OpenID query values.

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path != "/steam/callback":
                self.send_error(404)
                return
            try:
                actual = verified_steam_id(url.query, callback_url)
                if actual != expected_steam_id:
                    raise OpenIDError("登录的 Steam 账号与绑定申请不一致。")
                store.approve(request_id, actual)
                result["approved"] = True
                message = "Steam 账号验证成功！可以关闭这个页面，回 QQ 群发送“我的绑定”查看。"
                print("Steam 登录已核验，绑定状态已更新为已验证。", flush=True)
            except (OpenIDError, ValueError) as error:
                message = "验证未完成：" + str(error) + " 请回到 QQ 群检查申请，或重新打开 Steam 登录页面。"
                print("Steam 登录验证未通过：" + str(error), flush=True)
            encoded = message.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        port = server.server_port
        realm = f"http://127.0.0.1:{port}/"
        callback_url = f"{realm}steam/callback?state={state}"
        address = login_url(callback_url, realm)
        if not webbrowser.open(address):
            print("未能自动打开浏览器，请手动打开下列 Steam 官方地址：", flush=True)
            print(address, flush=True)
        else:
            print("Steam 官方登录页面已在浏览器打开。请在10分钟内完成登录。", flush=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not result["approved"]:
            server.handle_request()
    return result["approved"]


def main() -> None:
    parser = argparse.ArgumentParser(description="本机 Steam 官方网页登录验证")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--request-id", help="群内我的绑定显示的申请编号")
    choice.add_argument("--steam-id", help="本机唯一待验证申请的 SteamID")
    args = parser.parse_args()
    try:
        request_id = args.request_id
        if args.steam_id:
            store = BindingStore()
            with store.transaction() as db:
                matches = db.execute("SELECT request_id FROM bindings WHERE steam_id=? AND status='pending'", (args.steam_id,)).fetchall()
            if len(matches) != 1:
                raise OpenIDError("未找到唯一的待验证申请。请先在测试群重新发送“绑定 SteamID”，再开始验证。")
            request_id = matches[0]["request_id"]
        if not run(request_id):
            parser.exit(1, "十分钟内未完成 Steam 登录验证。\n")
    except (OpenIDError, OSError) as error:
        parser.exit(1, f"无法验证：{error}\n")


if __name__ == "__main__":
    main()
