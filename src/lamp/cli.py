"""用户命令入口，仅在需要时加载 Windows 接口。"""

import argparse
import asyncio
import copy
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError

from . import __version__, autostart, bluetooth, service
from .protocol import initial_state, remote_id
from .storage import (
    atomic_json,
    config_path,
    file_path,
    load_config,
    read_json,
    save_config,
    service_lock,
    validate,
)


class ChineseParser(argparse.ArgumentParser):
    """保留标准参数解析行为，使用中文帮助标题和提示。"""

    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help="显示帮助并退出")

    def format_help(self):
        return (
            super()
            .format_help()
            .replace("usage:", "用法：")
            .replace("positional arguments:", "位置参数：")
            .replace("options:", "选项：")
        )

    def format_usage(self):
        return super().format_usage().replace("usage:", "用法：")


def parser() -> argparse.ArgumentParser:
    root = ChineseParser(prog="lamp", description="房间灯：CLI 与家庭局域网 HTTP 控制")
    root.add_argument(
        "--version", action="version", version=f"lamp {__version__}", help="显示版本并退出"
    )
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in {
        "start": "启动后台 HTTP 服务，默认启用登录自启动",
        "stop": "停止服务，保留自启动设置",
        "restart": "验证配置后重启服务",
        "status": "查看服务、配置和自启动状态",
        "on": "开灯（需要服务运行）",
        "off": "关灯（需要服务运行）",
        "links": "显示 iPhone 捷径所需的链接及请求方法",
    }.items():
        sub = commands.add_parser(name, help=help_text)
        if name == "start":
            sub.add_argument("--no-autostart", action="store_true", help="本次不启用自启动")
    learn = commands.add_parser("learn", help="学习遥控器开灯、关灯信号")
    learn.add_argument("--timeout", type=float, default=30, help="每个按键的扫描秒数（默认 30）")
    config = commands.add_parser("config", help="配置管理")
    actions = config.add_subparsers(dest="operation", required=True)
    actions.add_parser("path", help="打印配置文件绝对路径")
    actions.add_parser("open", help="用文本编辑器打开配置文件")
    for name in ("import", "export"):
        sub = actions.add_parser(name, help="导入配置" if name == "import" else "导出配置")
        sub.add_argument("file", type=Path)
    setting = actions.add_parser("set", help="手动设置解码模板或已有配置里的遥控器 ID")
    setting.add_argument("--on-template", help="20 字节开灯解码模板，十六进制")
    setting.add_argument("--off-template", help="20 字节关灯解码模板，十六进制")
    setting.add_argument("--id", help="6 字节遥控器 ID，按解码模板中的字节顺序")
    setting.add_argument(
        "--manufacturer-id",
        type=lambda x: int(x, 0),
        help="厂商 ID，支持十进制或 0x 开头的十六进制",
    )
    startup = commands.add_parser("autostart", help="管理登录自启动")
    startup.add_argument("mode", choices=["on", "off"])
    homebridge = commands.add_parser("homebridge", help="导出 Homebridge 配件配置")
    bridge_actions = homebridge.add_subparsers(dest="operation", required=True)
    bridge_actions.add_parser("export", help="将吸顶灯配置输出为 JSON，使用运行中服务的端口")
    commands.add_parser("_serve", help=argparse.SUPPRESS)
    commands.add_parser("_autostart", help=argparse.SUPPRESS)
    # 内部后台命令不出现在常规帮助中。
    commands.metavar = "{start,stop,restart,status,on,off,links,learn,config,autostart,homebridge}"
    commands._choices_actions = [a for a in commands._choices_actions if not a.dest.startswith("_")]
    return root


def config_command(args) -> None:
    if args.operation == "path":
        print(config_path())
        return
    if args.operation == "open":
        path = config_path()
        if sys.platform == "win32":
            subprocess.Popen(["notepad.exe", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-t", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        print(path)
        return
    if args.operation == "export":
        destination = args.file.expanduser().resolve()
        if destination in (file_path("state.json"), file_path("service.json")):
            raise ValueError("导出目标不能覆盖运行状态文件")
        atomic_json(destination, load_config())
        print(f"配置已导出：{destination}（不含运行计数）")
        return
    if args.operation == "import":
        config = validate(read_json(args.file.expanduser()))
    else:
        config = load_config(require_templates=False)
        changes = (args.on_template, args.off_template, args.id, args.manufacturer_id)
        if all(value is None for value in changes):
            raise ValueError("请提供 --on-template/--off-template、--id 或 --manufacturer-id")
        for action in ("on", "off"):
            value = getattr(args, action + "_template")
            if value is not None:
                config["templates"][action] = bytes.fromhex(value).hex()
        if args.id:
            identity = bytes.fromhex(args.id.replace(":", ""))
            if len(identity) != 6:
                raise ValueError("--id 必须是 6 字节十六进制，按模板里的字节顺序")
            for action in ("on", "off"):
                if action not in config["templates"]:
                    raise ValueError("首次设置需要两个完整模板；仅 ID 不能替代未知的协议参数")
                template = bytearray.fromhex(config["templates"][action])
                template[9:15] = identity
                config["templates"][action] = template.hex()
        if args.manufacturer_id is not None:
            config["manufacturer_id"] = args.manufacturer_id
    save_config(config)
    print(f"配置已保存：{config_path()}")
    print("服务运行时请执行 lamp restart，使配置生效。")


async def learn(timeout: float) -> None:
    if not 1 <= timeout <= 300:
        raise ValueError("--timeout 必须在 1～300 秒之间")
    if service.running_info():
        raise RuntimeError("请先 lamp stop，再学习；完成后 lamp start")
    with service_lock():
        config = load_config(require_templates=False)
        await bluetooth.check_adapter()
        templates = {}
        identity = None
        for action in ("on", "off"):
            label = "开灯" if action == "on" else "关灯"
            await asyncio.to_thread(input, f"准备采集{label}。先按回车，然后按遥控器{label}键：")
            template = await bluetooth.capture(action, config["manufacturer_id"], timeout, identity)
            identity = remote_id(template)
            templates[action] = template.hex()
            print(f"已采集{label}，遥控器 ID：{identity}")
        config["templates"] = templates
        validate(config)
        save_config(config)
        atomic_json(file_path("state.json"), initial_state(templates))
        print(f"学习完成，配置已保存：{config_path()}\n运行 lamp start 启动服务。")


def export_homebridge() -> None:
    """输出单个 HTTP 开关配件，使用本机地址和正在运行的服务端口。"""
    info = service.require_running()
    base = f"http://127.0.0.1:{info['port']}"
    accessory = {
        "accessory": "HTTP-SWITCH",
        "name": "吸顶灯",
        "switchType": "toggle",
        "onUrl": {"url": f"{base}/api/on", "method": "POST"},
        "offUrl": {"url": f"{base}/api/off", "method": "POST"},
    }
    # 标准输出只包含 JSON，便于管道、重定向和复制。
    print(json.dumps(accessory, ensure_ascii=False, indent=2))


def dispatch(args) -> None:
    command = args.command
    if command == "config":
        config_command(args)
    elif command == "learn":
        asyncio.run(learn(args.timeout))
    elif command == "homebridge":
        export_homebridge()
    elif command == "start":
        info = service.spawn()
        if not args.no_autostart:
            autostart.set_enabled(True)
        print(f"服务已启动（PID {info['pid']}）。")
        print(f"登录自启动：{'已启用' if autostart.enabled() else '未启用'}")
        service.links(info)
    elif command == "stop":
        print("服务已停止。" if service.stop() else "服务没有运行。")
        print("自启动设置保留；可用 lamp autostart off 关闭。")
    elif command == "restart":
        # 先验证修改后的配置和适配器，再停止运行中的服务。
        load_config()
        asyncio.run(bluetooth.check_adapter())
        old = service.running_info()
        backup = copy.deepcopy(old["config"]) if old else None
        service.stop()
        try:
            info = service.spawn()
        except Exception:
            if backup:
                # 保留失败的新配置供修复，同时恢复上次运行的配置。
                atomic_json(file_path("config.failed.json"), load_config())
                save_config(backup)
                service.spawn()
                print("新配置启动失败，已恢复原服务；修改保存在 config.failed.json。")
            raise
        print(f"服务已重启（PID {info['pid']}）。")
        service.links(info)
    elif command == "status":
        info = service.running_info()
        print(f"服务：{'运行中（PID ' + str(info['pid']) + '）' if info else '未运行'}")
        print(f"登录自启动：{'已启用' if autostart.enabled() else '未启用'}")
        print(f"配置文件：{config_path()}")
        print(f"日志文件：{file_path('events.log')}")
        try:
            config = load_config()
            identity = remote_id(bytes.fromhex(config["templates"]["on"]))
            print(f"遥控器 ID：{identity}")
            if info and info["config"] != config:
                print("配置有修改，执行 lamp restart 后生效。")
        except ValueError as exc:
            print(f"配置待完善：{exc}")
        if info:
            service.links(info)
        print("状态表示服务状态；不代表灯的实际亮灭。")
    elif command in ("on", "off"):
        info = service.require_running()
        print(service.request(info, f"/api/{command}", "POST", timeout=25)["message"])
    elif command == "links":
        service.links(service.require_running())
    elif command == "autostart":
        autostart.set_enabled(args.mode == "on")
        print("登录自启动已启用。" if args.mode == "on" else "登录自启动已关闭。")
    elif command == "_serve":
        service.run_foreground()
    elif command == "_autostart":
        # 登录后 Wi-Fi 和蓝牙适配器可能需要时间初始化。
        for attempt in range(12):
            try:
                service.spawn()
                return
            except (OSError, ValueError, RuntimeError):
                time.sleep(5)
        raise RuntimeError("登录自启动失败，请查看 lamp status 和 service.log")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    # pythonw 没有控制台输出，将启动错误保存在用户日志中。
    stream = None
    if sys.stdout is None or sys.stderr is None:
        file_path("service.log").parent.mkdir(parents=True, exist_ok=True)
        stream = file_path("service.log").open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    try:
        dispatch(args)
        return 0
    except (OSError, ValueError, RuntimeError, URLError, ImportError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("操作已取消。", file=sys.stderr)
        return 130
    finally:
        if stream:
            stream.flush()
