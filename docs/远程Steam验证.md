# 群友远程 Steam 验证

群友不需要使用机器人运行电脑。机器人在群里收到“绑定 17位SteamID”后建立待验证申请。
维护者可将该申请的验证链接发给群友；若赛事专用 QQ 账号也在同一群，群友可发送
`#绑定链接 申请编号`，由该账号回复链接。群友在自己的设备上打开链接，跳转到 Steam 官方页面登录；
服务端再向 Steam 核验签名、比对 SteamID，成功后在原群发送“我的绑定”查看状态。

## 樱花映射

使用固定且能从公网访问的 **HTTPS** 地址。按照[樱花映射 Web 应用指南](https://doc.natfrp.com/app/http.html)
建立 HTTPS 隧道，或按[子域绑定指南](https://doc.natfrp.com/bestpractice/domain-bind.html)
使用自动 HTTPS。将外部 HTTPS 地址转发到本机 `127.0.0.1:8765` 的 HTTP 服务。
若使用国内节点，请遵守樱花映射对备案的要求。临时变化的地址会使旧验证链接失效。

在项目根目录 `.env` 增加一行，替换为隧道实际公开地址，不带末尾路径：

```text
STEAM_VERIFY_PUBLIC_URL=https://你的固定HTTPS地址
```

启动服务：

```powershell
.\.venv\Scripts\python.exe -u -m qq_cs2_bot.openid_remote --port 8765
```

本机可访问 `http://127.0.0.1:8765/health`；外部设备应能访问
`https://你的固定HTTPS地址/health`，看到“服务运行中”。
验证链接格式为 `https://你的固定HTTPS地址/verify/申请编号`。申请编号可从群内机器人回复或
“我的绑定”查到。维护者可通过自己的 QQ 账号发送链接。

官方机器人默认不发送外链，因为 QQ 的[消息 URL 白名单要求](https://github.com/tencent-connect/bot-docs/blob/main/docs/README.md)
包括域名报备和备案，樱花映射免费子域名不一定能通过。只有在该域名已获 QQ 批准后，才可在
`.env` 增加 `STEAM_VERIFY_QQ_LINKS=true`，让机器人在“绑定”和“验证绑定”回复中附上链接。

登录会话十分钟过期后，可重新打开同一申请链接生成新的登录会话。验证结果必须由 Steam
确认，且登录 SteamID 必须与绑定申请一致；仅提供 SteamID、QQ 截图或申请编号不会通过验证。
服务只监听本机回环地址，隧道只需转发此端口，不要把 NapCat、数据库或其他本地服务映射到公网。
