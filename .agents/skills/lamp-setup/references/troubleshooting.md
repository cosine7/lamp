# 故障排查

## 命令启动器错误

出现 `uv trampoline failed to canonicalize script path` 时，错误发生在 uv 解析启动器中的 Python 路径阶段。在报错的 PowerShell 中检查：

```powershell
Get-Command lamp -All | Select-Object -ExpandProperty Source
uv tool dir
```

某些安装环境会将 AppData 路径重定向到独立的缓存目录。若命令在安装时使用的环境中可以运行，但在日常终端中失败，在日常使用的 PowerShell 中进入项目目录执行：

```powershell
uv tool install --python 3.12 --editable . --force
uv tool update-shell
```

重新打开终端，执行 `lamp --version` 和 `lamp status`。

重装后显示未配置或未运行时，检查原安装使用的数据目录。可以通过 `LAMP_HOME` 指向包含现有配置、计数和实例信息的同一目录，或停止原服务后迁移数据。统一数据目录后，在新安装环境中执行 `lamp autostart on` 更新登录入口。

## 服务与电源

`lamp status` 查询服务状态，`lamp start` 启动服务。运行和启动错误记录在用户目录的 `events.log`、`service.log`。

电脑保持运行、蓝牙打开，灯保持供电。锁屏和关屏时服务继续运行；睡眠、休眠或关机会中断服务。

`lamp stop` 保留登录自启动设置，`lamp autostart off` 关闭该设置。移动源码或重新安装工具后，用新的安装环境刷新自启动入口。

## 手机网络

电脑命令正常、iPhone 请求超时时，先在手机访问 `http://<host>:<port>/health`。检查路由器设备隔离和 Windows 防火墙是否允许安装环境的 Python 接收入站连接。

不同 Wi-Fi 名称或频段可能属于同一局域网，实际访问结果可以确认是否互通。

返回 404 表示请求已到达服务。核对路径，开关接口为 `/api/on`、`/api/off`，方法为 POST；根路径 `/` 返回 404。

`/health` 是 HTTP 接口。命令行查看状态使用 `lamp status`。

电脑 IP 变化后，用 `lamp links` 获取最新地址并更新两个捷径。多网卡或 VPN 场景可以在配置中指定 `server.advertise_host`。

## 协议和学习

学习超时时，检查遥控器协议、蓝牙适配器及按键采集过程。保留原配置，使用已有完整模板手动设置，或继续确认协议。

学习流程复用已有配对关系。模板和计数格式参见[协议参考](protocol.md)。

## 配置生效与发送结果

编辑配置后执行 `lamp restart`。校验失败时原服务继续运行，启动失败时尝试恢复原配置，失败的新配置保存在 `config.failed.json`。

HTTP 请求成功、广播完成和灯实际亮灭分别验证。接口的 `ok: true` 表示广播发送完成，现场观察确认灯的反应。
