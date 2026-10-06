---
name: lamp-setup
description: 配置、学习和排查本项目的 Argrace 蓝牙灯控、Homebridge 接入和 iPhone HTTP 捷径，使用 lamp CLI 管理配置和服务。
---

# 灯控设置

本项目通过 Argrace remote v4 蓝牙广播控制已经配对的灯，每次发送更新计数和随机种子。当前发送接口使用 Windows WinRT，需要支持 BLE 广播的适配器。

## 检查安装与配置

阅读项目 README，了解安装方式和命令。在实际使用的终端执行 `lamp --version`、`lamp status` 和 `lamp config path`，确认命令入口、服务和配置目录。

配置、计数和日志位于用户数据目录，使用 `LAMP_HOME` 可以指定同一目录。不同运行环境出现不同结果时，按[排查说明](references/troubleshooting.md)检查安装路径和数据目录。

## 配置与学习

已有配置时，先用 `lamp config export <file>` 保存一份，再导入可用配置或设置完整模板。模板格式、遥控器 ID 和协议来源见[协议参考](references/protocol.md)。

学习时先停止服务，再运行 `lamp learn`。灯保持供电，按提示依次采集开灯、关灯。流程复用现有配对关系；失败时保留旧配置。完成后启动原本需要运行的服务。

修改配置后执行 `lamp restart`，再验证开关。完整模板包含遥控器 ID 和其他参数；手动设置使用采集或已有配置中的完整数据。

## Homebridge 接入

推荐通过 Homebridge 和 `homebridge-http-switch` 接入苹果“家庭”。安装 npm 包、注册后台服务和迁移已有配对的流程见 README。

运行 `lamp start` 后使用 `lamp homebridge export`，将输出的单个 JSON 对象加入 Homebridge 配置的 `accessories` 数组。输出使用本机地址和实际端口；已有同一灯的配置时更新原条目。导出操作沿用现有配置和发送计数。

Homebridge 在另一台主机、虚拟机或容器运行时，将导出的主机改为可访问 lamp 的地址。Homebridge 的安装和服务管理使用它自己的命令。`hb-service install` 注册服务和开机自启动，`hb-service start` 启动已有服务。

配件默认命名为“吸顶灯”，房间在苹果“家庭”中单独选择。保留桥接身份和配对数据。分别确认插件加载、手机配对以及用户观察到的灯实际亮灭。

## iPhone 捷径

用 `lamp links` 获取完整开关地址。iPhone“获取 URL 内容”选择 POST，请求体留空。两个捷径可以放到控制中心或小组件。

电脑地址变化后更新捷径。测试时分别确认手机能访问服务、广播发送完成，以及灯的实际反应。

网络、广播和配置问题参见[排查说明](references/troubleshooting.md)。
