# QQ CS2 官方机器人

通过 QQ 官方机器人查询完美平台 CS2 战绩、绑定 Steam 账号，并生成五人战报。自动赛后播报使用本机 NapCat 发送端。职业赛事查询和 CS2 更新由[独立赛事项目](https://github.com/Qing-Seiyuki/napcat-cs2-live-qq-bot)负责。

## 本机启动

需要 Python 3.15（其他版本尚未验证）。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 填入自己的 QQ AppID、AppSecret。查询完美统计和自动播报还需要相应的令牌。密钥只保存在本机。检查连接与启动机器人：

```powershell
.\.venv\Scripts\python.exe -m qq_cs2_bot.qq_check
.\.venv\Scripts\python.exe -u -m qq_cs2_bot.qq_listen --forever --bindings
```

远程 Steam 验证、绑定和赛后播报见 `docs/`。测试命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`data/` 保存本机数据库与运行数据，`output/` 保存战报和日志；两者、`.env` 和虚拟环境已被 Git 忽略。发布仓库不会启动机器人，运行电脑仍需保持联网。
