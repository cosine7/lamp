# lamp

自用吸顶灯控制工具，提供开灯、关灯命令和局域网 HTTP 接口。电脑通过蓝牙广播发送指令。

推荐通过 **Homebridge 接入苹果“家庭”**，扫码添加后直接开关灯，也可以通过 Siri 控制。也支持 iPhone 捷径直接调用 HTTP 接口。这两种方式都复用运行中的 `lamp` 服务。

## 运行条件

- Windows、Python 3.12 或更高版本，以及支持 BLE 广播的蓝牙适配器。蓝牙发送使用 WinRT，自启动在当前用户登录后执行。
- 使用 Argrace remote v4 协议的灯，默认厂商数据 ID 为 `0x09F9`。目前已在 Intel AX201 上完成实灯开关验证。
- 电脑保持运行、蓝牙打开，灯的墙壁开关保持打开。锁屏和关屏时服务继续运行；睡眠、休眠和关机会中断控制。
- 手机与电脑处于能够互通的局域网。同一路由器的 2.4 GHz 和 5 GHz Wi-Fi 通常可以互通。

Linux、macOS 的蓝牙发送和自启动接口尚待适配。其他灯的兼容性需要确认协议并实际测试。

## 从源码安装

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)。Windows 下，在日常使用的 PowerShell 终端中进入项目目录，运行：

```powershell
uv tool install --python 3.12 --editable .
uv tool update-shell
```

重新打开终端，检查安装结果：

```powershell
lamp --version
lamp status
```

安装后可以在任意目录运行 `lamp`。编辑安装依赖源码目录；移动源码后，在新目录重新执行安装命令并加上 `--force`。修改 Python 源码后重启服务即可；修改依赖或命令入口后重新安装。

## 首次配置

可以学习遥控器信号，也可以手动导入已有配置。

学习前保持灯通电，执行：

```text
lamp learn
```

按提示分别采集遥控器的开灯和关灯按键。学习使用现有配对关系，采集失败时保留原配置。重新学习前，使用 `lamp stop` 停止正在运行的服务。

已有完整配置时，执行：

```text
lamp config import <file>
```

已有两个解码模板时，也可以直接设置：

```text
lamp config set --on-template <on-template> --off-template <off-template>
```

文档中的尖括号表示待替换的参数，执行时填写实际值并去掉尖括号。`<file>` 是文件路径，`<on-template>` 和 `<off-template>` 分别是开灯、关灯模板。模板为 20 字节、04 开头的十六进制字符串，包含解码负载，省略两个校验字节。首次配置需要完整模板或配置文件。

## 启动与控制

```text
lamp start
lamp off
lamp on
lamp links
```

`lamp start` 在后台启动 HTTP 服务，并启用当前用户登录后的自启动。再次执行时显示正在运行的服务信息。关闭终端后服务继续运行。

临时启动时使用 `lamp start --no-autostart`，保留已有自启动设置。停止当前服务使用 `lamp stop`；关闭以后登录时的自启动使用 `lamp autostart off`。

工具自动选择局域网 IPv4 地址；默认尝试端口 8765，被占用时尝试后续端口并保存。启动时显示完整链接，以下用 `<host>` 和 `<port>` 表示自动填入的地址和端口：

```text
开灯链接：http://<host>:<port>/api/on
关灯链接：http://<host>:<port>/api/off
请求方法：POST
请求体：留空即可
```

接口供家庭局域网使用，能够访问电脑端口的设备可以发送控制请求。

## 接入苹果“家庭”（推荐）

使用 [Homebridge](https://homebridge.io/) 和 [homebridge-http-switch](https://github.com/homebridge-plugins/homebridge-http-switch) 插件，将 lamp 的 HTTP 接口映射为苹果“家庭”中的开关。

控制流程：苹果“家庭” → Homebridge → lamp HTTP 服务 → 蓝牙广播 → 吸顶灯。

### 安装 Homebridge

按 [Homebridge 的 Windows 安装说明](https://github.com/homebridge/homebridge/wiki/Install-Homebridge-on-Windows-10)安装 Node.js、Homebridge 和管理组件，并配置后台服务与开机自启动。

安装完成后，在 Homebridge 管理界面中安装 `homebridge-http-switch` 插件。已有配对过的实例时，沿用原数据目录和配对信息，迁移说明见下文。

### 配置 Homebridge 网络

苹果“家庭”通过 mDNS 发现 Homebridge。电脑同时有 Wi-Fi、以太网或 VPN 虚拟网卡时，指定连接家庭局域网的接口，让发现广播通过该接口发出。

Windows 多网卡环境建议在 Homebridge 管理界面的设置中：

1. 在 **Network Interfaces（网络接口）** 中，只选择连接家庭局域网的实际网卡。Wi-Fi 网卡在 Windows 上常显示为 `WLAN`；使用有线连接时选择实际的以太网接口。
2. 将 **mDNS Advertiser** 设为 **Ciao**。
3. 保存并重启 Homebridge，保留现有桥接身份和配对信息，再通过“家庭”测试开关。

更换网卡或连接方式后，更新所选接口。设置方法见 [Homebridge mDNS 与网络接口说明](https://github.com/homebridge/homebridge/wiki/mDNS-Options)。

### 导出吸顶灯配置

在安装过 lamp 的日常终端中执行：

```powershell
lamp start
lamp homebridge export
```

`lamp homebridge export` 使用运行中服务的实际端口，默认输出一个名为“吸顶灯”的配件对象。标准输出只包含 JSON，便于复制、保存或管道传递；导出时沿用现有灯控配置和发送计数。服务未运行时，命令提示先执行 `lamp start`。

复制到剪贴板可以执行：

```powershell
lamp homebridge export | Set-Clipboard
```

保存为 UTF-8 文件可以执行：

```powershell
lamp homebridge export | Set-Content -LiteralPath "<file>" -Encoding utf8
```

生成配置只需要运行中的 lamp 服务。Homebridge 程序和插件的安装按前面的说明完成，配置通过 Homebridge 管理界面或文本编辑器添加。

在 Homebridge 管理界面的配置编辑器中，将导出的对象加入 `accessories` 数组，保留已有的 `bridge`、`platforms` 和其他配件。下面是完整数组片段的示例，`<port>` 代表命令自动填入的实际端口：

```json
{
  "accessories": [
    {
      "accessory": "HTTP-SWITCH",
      "name": "吸顶灯",
      "switchType": "toggle",
      "onUrl": {
        "url": "http://127.0.0.1:<port>/api/on",
        "method": "POST"
      },
      "offUrl": {
        "url": "http://127.0.0.1:<port>/api/off",
        "method": "POST"
      }
    }
  ]
}
```

导出的单个对象放在 `accessories` 的方括号内；数组里已有对象时用逗号分隔。已有同一盏灯的条目时更新原条目的控制地址，避免重复添加。这个示例用于说明数组结构，实际填写时使用命令生成的端口。

Homebridge 和 lamp 在同一台电脑上运行时使用 `127.0.0.1`，电脑局域网 IP 变化后两个 URL 仍然可用。Homebridge 在另一台设备、虚拟机或容器中运行时，将导出结果中的主机改为能够访问 lamp 的 `<host>`，保留实际端口。

### 配对和使用

保存配置，在管理界面重启 Homebridge，或在管理员终端执行：

```powershell
hb-service.cmd restart
```

首次配对时，在 iPhone“家庭”中选择“添加配件”，扫描 Homebridge 管理界面或 `hb-service logs` 显示的配对二维码，按提示完成添加。已经添加过同一 Homebridge 桥接时，保留原配对信息，重启后查看配件即可。

配件命名为“吸顶灯”，房间在“家庭”中单独选择，例如“卧室”。添加后测试关灯和开灯，等待每次广播完成再进行下一次操作。

`toggle` 模式显示最近通过 Homebridge 设置的开关状态。通过原遥控器或 lamp CLI 操作后的实际灯状态不会自动同步到“家庭”。

### 服务与迁移

lamp 和 Homebridge 都需要保持运行。`lamp start`、`lamp stop` 和 `lamp restart` 管理灯控服务；Homebridge 的启动、停止、自启动和日志查看按[官方服务管理说明](https://github.com/homebridge/homebridge-config-ui-x/wiki/Homebridge-Service-Command)操作。

lamp 端口变化后，重新导出配置并更新原配件的两个 URL，再重启 Homebridge。

迁移已有实例时，先备份整个 Homebridge 数据目录，停止旧实例，再沿用原配置、配对信息和配件缓存。已有同一盏灯的条目时更新原条目，显示名称可以在苹果“家庭”中改为“吸顶灯”。具体备份与迁移步骤见 [Homebridge Backup and Restore](https://github.com/homebridge/homebridge/wiki/Backup-and-Restore)。

## iPhone 捷径（直接调用 HTTP）

希望直接使用快捷指令时，可以创建两个捷径，直接调用 lamp HTTP 接口。控制流程：iPhone 捷径 → lamp HTTP 服务 → 蓝牙广播 → 吸顶灯。

在“快捷指令”App 中创建“房间开灯”，添加“获取 URL 内容”，粘贴 `lamp links` 显示的开灯地址，方法选择 **POST**，请求体留空。再创建“房间关灯”，使用关灯地址。

两个捷径可以放到控制中心、快捷指令小组件，或通过 Siri 调用。首次执行时，允许捷径访问对应地址。

电脑 IP 或服务端口变化后，重新运行 `lamp links`，更新两个捷径中的地址。

## 命令

| 命令 | 行为 |
| --- | --- |
| `lamp start` | 后台启动服务并启用登录自启动；已运行时显示现有链接 |
| `lamp stop` | 停止当前服务，保留自启动设置 |
| `lamp restart` | 验证配置后重启服务，保留发送计数和自启动设置 |
| `lamp status` | 查看服务、配置路径和自启动状态 |
| `lamp on` / `lamp off` | 通过运行中的服务发送开灯、关灯指令 |
| `lamp links` | 打印完整链接、POST 方法和请求体说明 |
| `lamp homebridge export` | 输出 HTTP 开关配件 JSON，默认名称“吸顶灯”，自动使用运行中服务的端口 |
| `lamp learn` | 引导采集两个按键，默认每个扫描 30 秒 |
| `lamp config set --on-template <on-template> --off-template <off-template>` | 手动保存解码模板 |
| `lamp config set --id <remote-id>` | 修改已有模板中的六字节遥控器 ID，按模板字节顺序填写十六进制值 |
| `lamp config import <file>` | 验证并导入 JSON 配置 |
| `lamp config export <file>` | 导出配置至指定文件路径 |
| `lamp config path` | 打印配置文件绝对路径 |
| `lamp config open` | 用文本编辑器打开配置 |
| `lamp autostart on` / `lamp autostart off` | 启用、关闭登录自启动 |
| `lamp --help` / `lamp --version` | 显示帮助、版本 |

`lamp status` 查询电脑上的服务状态。灯的实际亮灭由现场观察确认。

## 配置和日志

Windows 下默认存放于 `%LOCALAPPDATA%\lamp`，也可以通过环境变量 `LAMP_HOME` 指定目录。使用 `lamp config path` 获取当前配置路径。

| 文件 | 用途 |
| --- | --- |
| `config.json` | 用户可编辑配置：协议、模板、广播时长和网络设置 |
| `state.json` | 服务保存的发送计数 |
| `service.json`、`service.lock` | 后台实例信息和单实例锁 |
| `events.log` | 自动轮转的运行日志 |
| `service.log` | 后台启动错误 |

配置示例：

```json
{
  "schema_version": 1,
  "protocol": "argrace_remote_v4",
  "manufacturer_id": 2553,
  "templates": {"on": "<on-template>", "off": "<off-template>"},
  "broadcast_seconds": 3,
  "server": {"port": 8765, "advertise_host": "auto"}
}
```

填入实际模板后保存，再执行 `lamp restart` 使配置生效。工具先验证配置，校验失败时保留原服务。

`state.json` 由服务维护，停止和重启后保留。配置导出只包含 `config.json`；备份或迁移发送计数时，还需保存 `state.json`。

## HTTP 接口

| 请求 | 返回 |
| --- | --- |
| `POST /api/on` | 发送开灯广播 |
| `POST /api/off` | 发送关灯广播 |
| `GET /health` | 服务健康信息 |

开关接口返回 JSON，`ok: true` 表示广播发送完成。GET 请求访问开关接口返回 405，访问根路径 `/` 返回 404。

`/health` 是 HTTP 路径。命令行查询状态使用 `lamp status`。

## 协议来源

协议算法改编自 [NicoIIT/ha-ble-adv 的 AgarceRemoteEncoder](https://github.com/NicoIIT/ha-ble-adv/blob/main/custom_components/ble_adv/codecs/agarce.py)，MIT 授权原文保存在 `THIRD-PARTY-LICENSE.txt`。开关指令和发送计数已通过实灯验证，其余参数沿用采集到的模板。

## 更多文档

- [故障排查](.agents/skills/lamp-setup/references/troubleshooting.md)：启动器错误、手机连接、Homebridge 未响应与重启超时、蓝牙和配置问题。
- [协议与手动配置](.agents/skills/lamp-setup/references/protocol.md)：模板格式、字段和发送计数。
- [开发约定](AGENTS.md)：开发环境、实现约束和验证命令。
- [设置与排查技能](.agents/skills/lamp-setup/SKILL.md)：供编程助手执行的配置和排查流程。
