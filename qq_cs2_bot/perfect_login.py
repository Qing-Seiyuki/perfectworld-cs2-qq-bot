"""Local-only SMS login setup; never displays or logs the returned token."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .bindings import valid_steam_id
from .perfect_detail import ENV_PATH, _NoRedirect, fetch_stars


LOGIN_URL = "https://passport.pwesports.cn/account/login"
SAMPLE_S_STEAM_ID = "76561199690813601"


def login(phone: str, code: str) -> tuple[str, str]:
    if not re.fullmatch(r"1[0-9]{10}", phone) or not re.fullmatch(r"[0-9]{4,8}", code):
        raise ValueError("请核对手机号和短信验证码。")
    body = json.dumps({"appId": 2, "mobilePhone": phone, "securityCode": code}).encode()
    request = Request(LOGIN_URL, data=body, method="POST",
                      headers={"Content-Type": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(100_001)
        if len(raw) > 100_000:
            raise ValueError("登录响应格式异常。")
        result = json.loads(raw)
    except HTTPError as error:
        raise ValueError(f"平台登录接口返回 HTTP {error.code}。") from None
    except (URLError, OSError):
        raise ValueError("无法连接完美平台登录接口。") from None
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("登录响应格式异常。") from None
    if not isinstance(result, dict) or result.get("code") != 0:
        raise ValueError("登录未成功。请检查验证码是否有效，或稍后重试。")
    payload = result.get("result")
    login_result = payload.get("loginResult") if isinstance(payload, dict) else None
    info = login_result.get("accountInfo") if isinstance(login_result, dict) else None
    info = info if isinstance(info, dict) else {}
    token, steam_id = info.get("token"), str(info.get("steamId", ""))
    if not isinstance(token, str) or not token or not valid_steam_id(steam_id):
        raise ValueError("登录成功，但平台未返回可用令牌或 SteamID。")
    return token, steam_id


def save_account(token: str, steam_id: str, path: Path = ENV_PATH) -> None:
    if not token or "\n" in token or "\r" in token or not valid_steam_id(steam_id):
        raise ValueError("账号凭证格式异常。")
    original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = [line for line in original.splitlines()
             if not line.startswith(("PERFECT_TOKEN=", "PERFECT_STEAM_ID="))]
    lines.extend((f"PERFECT_TOKEN={token}", f"PERFECT_STEAM_ID={steam_id}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".perfect-env-", delete=False) as file:
        temporary = Path(file.name)
        file.write("\n".join(lines) + "\n")
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    root = tk.Tk()
    root.title("完美平台星数查询设置")
    root.geometry("480x260")
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="先在完美世界电竞 App 的短信登录页获取验证码；\n"
                          "验证码请填在本窗口，不要发到 QQ 或聊天中。", justify="left").pack(anchor="w")
    phone = tk.StringVar()
    code = tk.StringVar()
    for title, variable, secret in (("手机号", phone, False), ("短信验证码", code, True)):
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=7)
        ttk.Label(row, text=title, width=12).pack(side="left")
        ttk.Entry(row, textvariable=variable, show="●" if secret else "").pack(side="left", fill="x", expand=True)
    status = tk.StringVar(value="令牌只保存在这台电脑的机器人配置中。")
    ttk.Label(frame, textvariable=status, wraplength=430).pack(anchor="w", pady=12)

    def submit() -> None:
        button.configure(state="disabled")
        status.set("正在验证，请稍候……")
        entered_phone, entered_code = phone.get().strip(), code.get().strip()
        code.set("")

        def work() -> None:
            try:
                token, steam_id = login(entered_phone, entered_code)
                stars = fetch_stars(SAMPLE_S_STEAM_ID, credentials=(token, steam_id))
                save_account(token, steam_id)
                message = (f"设置完成。样例玩家读取到 S {stars}星；现在可在群里试“数据 Black电竞poikiKOOK718”。"
                           if stars is not None else
                           "登录成功并已保存令牌，但星数接口暂未返回数据；机器人会显示“星数暂无”。")
            except ValueError as error:
                message = str(error)
            except OSError:
                message = "本机保存配置失败，请检查项目目录权限。"
            root.after(0, lambda: (status.set(message), button.configure(state="normal")))

        threading.Thread(target=work, daemon=True).start()

    button = ttk.Button(frame, text="登录并验证星数", command=submit)
    button.pack(anchor="w")
    root.mainloop()


if __name__ == "__main__":
    main()
