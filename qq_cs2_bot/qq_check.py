"""Validate QQ credentials and gateway access without sending any messages."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://api.bot.qq.com"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class CheckError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials must only be sent to the documented endpoint.
        return None


def credentials(path: Path = ENV_PATH) -> tuple[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                raise CheckError(".env 格式错误，每行应为 名称=内容")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    app_id = os.environ.get("QQ_APP_ID", values.get("QQ_APP_ID", "")).strip()
    secret = os.environ.get("QQ_APP_SECRET", values.get("QQ_APP_SECRET", "")).strip()
    if not app_id or not secret:
        raise CheckError("请先在项目 .env 文件填写 QQ_APP_ID 和 QQ_APP_SECRET。")
    if not app_id.isascii() or not app_id.isdigit():
        raise CheckError("QQ_APP_ID 应为平台提供的数字 AppID。")
    return app_id, secret


def request_json(path: str, *, payload: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "QQBot " + token
    request = Request(BASE_URL + path, headers=headers,
                      data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            body = response.read(1_000_001)
    except HTTPError as error:
        raise CheckError(f"QQ 接口 HTTP {error.code}；请检查机器人状态、网络和平台 IP 白名单设置。") from None
    except (URLError, OSError):
        raise CheckError("无法连接 QQ 接口，请检查网络后重试。") from None
    if len(body) > 1_000_000:
        raise CheckError("QQ 接口响应过大。")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError):
        raise CheckError("QQ 接口返回了非 JSON 数据。") from None
    if not isinstance(data, dict):
        raise CheckError("QQ 接口返回格式异常。")
    for key in ("code", "err_code"):
        code = data.get(key)
        if code not in (None, 0, "0"):
            # Never echo upstream messages or credentials; show only numeric codes.
            safe_code = str(code) if str(code).isascii() and str(code).isdigit() else "未知"
            hint = "，请核对 AppID 和 AppSecret" if safe_code in ("100007", "100016", "10004") else ""
            raise CheckError(f"QQ 接口错误码 {safe_code}{hint}。")
    return data


def check_connection(app_id: str, secret: str) -> None:
    auth = request_json("/app/getAppAccessToken", payload={"appId": app_id, "clientSecret": secret})
    token = auth.get("access_token")
    if not isinstance(token, str) or not token:
        raise CheckError("未获取到有效访问凭证。")
    gateway = request_json("/gateway", token=token)
    address = gateway.get("url")
    if not isinstance(address, str) or urlparse(address).scheme != "wss" or not urlparse(address).hostname:
        raise CheckError("未获取到有效的安全网关地址。")


def main() -> None:
    try:
        check_connection(*credentials())
    except (CheckError, OSError, UnicodeError) as error:
        message = str(error) if isinstance(error, CheckError) else "本机配置文件无法读取，请检查文件编码和权限。"
        print("接入检查未通过：" + message)
        raise SystemExit(1) from None
    print("接入检查通过：凭据有效，已获取 QQ 网关地址。尚未连接消息事件或验证群消息权限。")


if __name__ == "__main__":
    main()
