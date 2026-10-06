# 开发约定

这是自用的 Python 灯控工具，功能包括开灯、关灯、CLI 和局域网 HTTP 服务。HTTP 使用 Python 标准库，功能扩展按用户需求确定。

## 实现约束

- 蓝牙发送和登录自启动目前支持 Windows，系统接口集中在 `bluetooth.py` 和 `autostart.py`。新增平台时适配对应接口并验证实际运行。
- 协议为 Argrace remote v4。修改协议实现时，保留尚未确定含义的模板字段。其他灯的兼容性通过协议检查和实际测试确认。
- 用户配置、发送计数、日志和实例信息存放在 `LAMP_HOME` 或用户数据目录。源码和自动测试使用虚构数据；真实遥控器 ID、广播记录和个人配置保存在仓库之外。
- 串行发送指令，广播前保存新计数。停止和重启服务保留计数。先验证配置，再停止运行中的服务；验证失败时保留原服务。
- 公开接口为 `POST /api/on` 和 `POST /api/off`，使用可读路径。GET 访问开关接口返回 405。
- `lamp start` 默认启用当前用户登录后的自启动。`lamp stop` 关闭当前进程并保留自启动设置；`lamp autostart off` 取消自启动。
- `lamp homebridge export` 只输出单个 HTTP 配件 JSON，使用运行中服务的实际端口和本机地址。Homebridge 的安装、配置合并和服务管理由用户独立执行。
- 保留协议来源与第三方 MIT 许可原文。

## 文档和示例

文档、代码注释、函数说明和命令行提示使用中文，标识符和第三方 API 保留原名。

说明具体功能、操作步骤、已验证行为和维护要求。协议尚未确定的字段写明处理方式，例如“沿用采集模板”。

可变参数使用英文尖括号占位符，如 `<host>`、`<port>`、`<on-template>`、`<remote-id>`、`<file>`。固定值按原样展示。文档地址使用占位符，CLI 输出实际地址供用户复制。

## 安装与验证

开发使用 `uv sync`。全局安装在日常使用的外部 PowerShell 中运行：

```text
uv tool install --python 3.12 --editable .
uv tool update-shell
```

安装后从日常终端验证 `lamp --version` 和 `lamp status`。某些安装环境的用户目录重定向问题参见 README 的故障排查。迁移安装环境时，确认配置目录、计数和自启动入口仍指向同一套数据。

有实际行为变化的修改使用以下检查：

```text
uv run python -m unittest discover -s tests -v
uv run ruff check .
```

自动测试隔离 `LAMP_HOME`，模拟蓝牙操作。真实广播验证使用通电的灯，分别记录广播完成与用户观察到的结果。学习流程复用已有配对关系。

设置、学习或排查灯控时，阅读 `.agents/skills/lamp-setup/SKILL.md`。
