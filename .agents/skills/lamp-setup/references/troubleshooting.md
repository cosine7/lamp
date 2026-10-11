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

重装后显示未配置或未运行时，对比原安装和新安装使用的数据目录，原数据也可能位于应用缓存中。可以通过 `LAMP_HOME` 指向包含现有配置、计数和实例信息的同一目录，或停止原服务后迁移数据。已有模板可以继续使用。统一数据目录后，在新安装环境中执行 `lamp autostart on` 更新登录入口。

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

## Homebridge 未响应

先区分控制路径。手机捷径直接调用 lamp HTTP 服务；苹果“家庭”通过 Homebridge 转发。捷径正常可以验证 lamp 链路，Homebridge 与手机之间的连接和发现广播需要单独检查。

按以下顺序定位：

1. 确认 `lamp on`、`lamp off` 和手机捷径能实际控制灯。检查 Homebridge 配件中的两个 URL 是否与 lamp 的实际端口一致；同机运行时主机地址使用 `127.0.0.1`。
2. 检查 Homebridge 服务、日志和监听端口。Windows 可执行 `Get-Service Homebridge`，并查看管理界面或 Homebridge 数据目录中的 `homebridge.log`，确认 HTTP-SWITCH 插件加载、配件初始化和 HomeKit 端口开始监听。服务管理器显示运行中，还需要核对其中的 HomeKit 子进程是否就绪。
3. 确认手机处于能够访问电脑的局域网，用 Safari 访问 `http://<host>:<hap-port>/accessories`。`<hap-port>` 来自日志或配置的 `bridge.port`，与 Homebridge 管理页面端口、lamp HTTP 端口分开。JSON 或要求授权的响应表示 TCP/HTTP 可达，不能据此认定 mDNS 发现或配对会话正常；超时则继续检查防火墙、路由器隔离和手机 VPN。
4. 检查 `_hap._tcp.local` 的 mDNS 发现结果。多网卡环境分别检查家庭局域网接口和虚拟接口，记录发现来源及广播中的地址。如果家庭接口没有发现广播，而虚拟接口有响应，优先调整 Homebridge 的接口选择。
5. 在 Homebridge 设置中，将 Network Interfaces 限定为连接家庭局域网的实际网卡，并将 mDNS Advertiser 设为 Ciao。配置项分别为 `bridge.bind` 和 `bridge.advertiser`。保存后重启 Homebridge，重新验证发现结果及手机实际控制；保留现有桥接身份和配对数据。更换网络接口后更新该选择。

设置依据见 [Homebridge mDNS 与网络接口说明](https://github.com/homebridge/homebridge/wiki/mDNS-Options)。调整 Homebridge 的发现接口与修改 lamp 的 `server.advertise_host` 分别作用于两套服务。

已验证的案例：Windows 环境使用 Homebridge 2.4.0 和 homebridge-http-switch 0.5.36，完成扫码配对及实灯开关验证。电脑同时有家庭 Wi-Fi 和 VPN 虚拟网卡，随后出现 lamp CLI、手机捷径和 Homebridge 的 HomeKit HTTP 端口都可用，但“家庭”显示未响应的情况。调整前只在虚拟网卡上发现 Homebridge 广播；改用 Ciao 并指定家庭 Wi-Fi 接口后，该接口能够收到广播，用户确认“家庭”恢复正常，并在随后连续数天的使用中未再遇到问题。

## Homebridge 重启超时

管理页面的等待超时与服务启动失败分开判断。实测一次完整重启约需 42 秒，页面提示超时后，服务已完成启动。

先等待约一分钟，再刷新管理页面、查看最新日志和 HomeKit 端口。插件加载完成、配件初始化成功且端口响应后，继续验证 mDNS 发现及手机控制。确认仍未就绪时，根据最新错误处理，再按 Homebridge 自身的服务管理流程重启；`lamp restart` 管理的是 lamp 服务。

排查记录包括发生时间、手机网络、所选接口、广播发现结果和日志错误。持续使用反馈用于补充稳定性验证；电脑重启、网络重连和 VPN 切换后的行为分别记录实际观察结果。

## 协议和学习

蓝牙发送或学习失败时，先检查电脑蓝牙是否打开、灯是否通电，以及适配器是否支持 BLE 广播。通过 `lamp status` 获取日志路径。

学习超时时，检查遥控器协议和两个按键是否都已采集。保留原配置，使用 `lamp config set` 设置已有完整模板，或用 `lamp config import` 导入配置。

学习流程复用已有配对关系。模板和计数格式参见[协议参考](protocol.md)。

## 配置生效与发送结果

编辑配置后执行 `lamp restart`。配置校验失败时，原服务继续运行；新配置通过校验但启动失败时，工具尝试恢复原配置和服务，将失败的新配置保存在 `config.failed.json`。

HTTP 请求成功、广播完成和灯实际亮灭分别验证。接口的 `ok: true` 表示广播发送完成，现场观察确认灯的反应。
