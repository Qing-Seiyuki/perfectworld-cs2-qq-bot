"""Public Steam OpenID callback for group members on their own devices.

Run behind a fixed HTTPS reverse tunnel. Only the loopback HTTP listener is
exposed locally; the public URL is supplied by the tunnel operator.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .bindings import BindingStore
from .openid_local import OpenIDError, login_url, verified_steam_id
from .qq_check import ENV_PATH


def checked_public_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("公网地址必须是固定的 HTTPS 根地址，例如 https://bot.example.com")
    return parsed.geturl().rstrip("/")


def configured_public_url() -> str | None:
    value = _env_value("STEAM_VERIFY_PUBLIC_URL")
    return checked_public_url(value) if value else None


def _env_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            key, sep, found = line.strip().partition("=")
            if sep and key == name:
                value = found.strip().strip("\"'")
    return value


def qq_link_enabled() -> bool:
    # Enable only after QQ's message URL whitelist approves this exact domain.
    return _env_value("STEAM_VERIFY_QQ_LINKS").lower() == "true"


def link_for_request(request_id: str, store: BindingStore | None = None) -> str | None:
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        return None
    public_url = configured_public_url()
    if not public_url:
        return None
    store = store or BindingStore()
    with store.transaction() as db:
        row = db.execute("SELECT status FROM bindings WHERE request_id=?", (request_id,)).fetchone()
    if row is None or row["status"] != "pending":
        return None
    return f"{public_url}/verify/{request_id}"


def create_server(public_url: str, port: int = 8765,
                  store: BindingStore | None = None) -> ThreadingHTTPServer:
    public_url = checked_public_url(public_url)
    store = store or BindingStore()
    sessions: dict[str, tuple[str, str, float]] = {}
    lock = threading.Lock()
    public_host = urlsplit(public_url).netloc.lower()
    public_hostname = urlsplit(public_url).hostname.lower()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Steam assertions and request IDs must not enter access logs.

        def reply(self, status: int, message: str) -> None:
            body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                    "<title>Steam 账号验证</title><p>" + message + "</p>").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host", "").lower() not in (public_host, public_hostname, local_host):
                self.reply(421, "访问地址不正确。")
                return
            if len(self.path) > 8192:
                self.reply(414, "请求地址过长。")
                return
            path = urlsplit(self.path)
            if path.path == "/health" and not path.query:
                self.reply(200, "服务运行中。")
                return
            match = re.fullmatch(r"/verify/([0-9a-f]{32})", path.path)
            if match and not path.query:
                self.start_login(match.group(1))
                return
            if path.path == "/steam/callback":
                self.finish_login(path.query)
                return
            self.reply(404, "页面不存在。")

        def start_login(self, request_id: str) -> None:
            with store.transaction() as db:
                row = db.execute("SELECT steam_id FROM bindings WHERE request_id=? AND status='pending'",
                                 (request_id,)).fetchone()
            if row is None:
                self.reply(404, "绑定申请不存在或已经验证。请回 QQ 群查看绑定状态。")
                return
            state = secrets.token_urlsafe(32)
            with lock:
                now = time.monotonic()
                for key in list(sessions):
                    if sessions[key][2] < now:
                        del sessions[key]
                if len(sessions) >= 1000:
                    self.reply(503, "验证请求较多，请稍后重试。")
                    return
                sessions[state] = (request_id, row["steam_id"], now + 600)
            callback = f"{public_url}/steam/callback?state={state}"
            self.send_response(302)
            self.send_header("Location", login_url(callback, public_url + "/"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def finish_login(self, query: str) -> None:
            try:
                params = parse_qs(query, keep_blank_values=True, max_num_fields=30)
                states = params.get("state", [])
                if len(states) != 1:
                    raise OpenIDError("验证会话无效。")
                state = states[0]
                with lock:
                    session = sessions.pop(state, None)
                if session is None or session[2] < time.monotonic():
                    raise OpenIDError("验证会话已过期，请重新打开群里的验证链接。")
                request_id, expected_steam_id, _ = session
                callback = f"{public_url}/steam/callback?state={state}"
                actual = verified_steam_id(query, callback)
                if actual != expected_steam_id:
                    raise OpenIDError("登录的 Steam 账号与绑定申请不一致。")
                store.approve(request_id, actual)
            except (OpenIDError, ValueError):
                self.reply(400, "验证未完成。请确认使用申请绑定的 Steam 账号，并重新打开群里的验证链接。")
                return
            self.reply(200, "Steam 账号验证成功！请回 QQ 群发送“我的绑定”查看。")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    local_host = f"127.0.0.1:{server.server_port}"
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="远程 Steam 账号验证回调服务")
    parser.add_argument("--public-url", help="映射提供的固定 HTTPS 根地址；默认读取 .env")
    parser.add_argument("--port", type=int, default=8765, help="本机映射端口，默认 8765")
    args = parser.parse_args()
    try:
        public_url = args.public_url or configured_public_url()
        if not public_url:
            raise ValueError("请先配置 STEAM_VERIFY_PUBLIC_URL")
        server = create_server(public_url, args.port)
    except (OSError, ValueError) as error:
        parser.exit(1, f"无法启动远程验证：{error}\n")
    print(f"远程验证服务已启动，本地端口 {args.port}。请确认 HTTPS 映射指向此端口。", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
