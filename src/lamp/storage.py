"""用户配置、独立发送计数及单实例服务锁。"""

import copy
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .protocol import COMMANDS, remote_id

DEFAULT_CONFIG = {
    "schema_version": 1,
    "protocol": "argrace_remote_v4",
    "manufacturer_id": 2553,
    "templates": {},
    "broadcast_seconds": 3,
    "server": {"port": 8765, "advertise_host": "auto"},
}


def data_dir() -> Path:
    if override := os.environ.get("LAMP_HOME"):
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "lamp"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/lamp"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lamp"


def file_path(name: str) -> Path:
    return data_dir() / name


def read_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return result


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def config_path() -> Path:
    path = file_path("config.json")
    if not path.exists():
        atomic_json(path, copy.deepcopy(DEFAULT_CONFIG))
    return path


def validate(config: dict, *, require_templates: bool = True) -> dict:
    if config.get("schema_version") != 1 or config.get("protocol") != "argrace_remote_v4":
        raise ValueError("仅支持 schema_version=1 和 protocol=argrace_remote_v4")
    manufacturer = config.get("manufacturer_id")
    if type(manufacturer) is not int or not 0 <= manufacturer <= 65535:
        raise ValueError("manufacturer_id 必须是 0～65535 的整数")
    duration = config.get("broadcast_seconds")
    if type(duration) not in (int, float) or not 0.5 <= duration <= 5:
        raise ValueError("broadcast_seconds 必须在 0.5～5 秒之间")
    server = config.get("server")
    if not isinstance(server, dict):
        raise ValueError("缺少 server 配置")
    port = server.get("port")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("server.port 必须是 1024～65535 的整数")
    host = server.get("advertise_host")
    if not isinstance(host, str) or not host or any(c in host for c in "/: \r\n"):
        raise ValueError("server.advertise_host 必须是 auto、IPv4 地址或主机名")
    templates = config.get("templates")
    if not isinstance(templates, dict):
        raise ValueError("templates 必须是对象")
    if not templates and not require_templates:
        return config
    decoded = {}
    for action, command in COMMANDS.items():
        try:
            template = bytes.fromhex(templates[action])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"缺少或无效的 templates.{action}；运行 lamp learn 或 config set"
            ) from exc
        if len(template) != 20 or template[0] != 4 or template[16] != command:
            raise ValueError(f"templates.{action} 必须是 04 开头、正确命令的 20 字节解码模板")
        decoded[action] = template
    if remote_id(decoded["on"]) != remote_id(decoded["off"]):
        raise ValueError("开灯、关灯模板的遥控器 ID 必须一致")
    return config


def load_config(*, require_templates: bool = True) -> dict:
    return validate(read_json(config_path()), require_templates=require_templates)


def save_config(config: dict) -> None:
    validate(config)
    atomic_json(config_path(), config)


def validate_state(state: dict, identity: str) -> dict:
    if state.get("remote_id") != identity:
        raise ValueError("计数状态属于另一个遥控器")
    try:
        values = [state["tx_count"], state["restart_count"]]
        values.extend(state["button_counts"][a] for a in COMMANDS)
    except (KeyError, TypeError) as exc:
        raise ValueError("计数状态不完整") from exc
    if any(type(n) is not int or not 0 <= n <= 255 for n in values):
        raise ValueError("计数状态必须是 0～255 的整数")
    return state


@contextmanager
def service_lock():
    path = file_path("service.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("已有 lamp 服务或学习流程运行") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
