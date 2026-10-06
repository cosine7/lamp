"""标准库 HTTP 服务及后台进程的启动、停止管理。"""

import asyncio
import ipaddress
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from . import __version__, bluetooth
from .controller import Controller
from .storage import atomic_json, data_dir, file_path, load_config, read_json, service_lock


def local_address() -> str:
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    # 只选家庭局域网的 RFC 1918 地址，排除 VPN 常用的 198.18.0.0/15 等地址。
    networks = tuple(
        ipaddress.ip_network(n) for n in ("192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12")
    )
    for candidate in candidates:
        address = ipaddress.ip_address(candidate)
        if any(address in network for network in networks):
            return candidate
    raise RuntimeError("未找到局域网 IPv4 地址；请联网或设置 server.advertise_host")


def request(info: dict, path: str, method: str = "GET", timeout: float = 2) -> dict:
    query = Request(
        f"http://127.0.0.1:{info['port']}{path}",
        data=b"" if method == "POST" else None,
        method=method,
        headers={"X-Lamp-Instance": info["instance"]},
    )
    # 本机管理请求直接连接，不经过用户的 HTTP 代理。
    try:
        with build_opener(ProxyHandler({})).open(query, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            message = json.load(exc).get("error", str(exc))
        except (ValueError, AttributeError):
            message = str(exc)
        raise RuntimeError(message) from exc


def running_info() -> dict | None:
    try:
        info = read_json(file_path("service.json"))
        health = request(info, "/health")
        if health.get("instance") == info["instance"] and health.get("pid") == info["pid"]:
            return info
    except (OSError, ValueError, KeyError, RuntimeError, URLError):
        pass
    return None


def require_running() -> dict:
    if info := running_info():
        return info
    raise RuntimeError("服务未启动，请先运行 lamp start")


def spawn() -> dict:
    if info := running_info():
        return info
    config = load_config()
    bluetooth.require_windows()
    asyncio.run(bluetooth.check_adapter())
    data_dir().mkdir(parents=True, exist_ok=True)
    log = file_path("service.log")
    executable = sys.executable
    if sys.platform == "win32":
        windowless = os.path.join(os.path.dirname(executable), "pythonw.exe")
        if os.path.isfile(windowless):
            executable = windowless
    with log.open("ab", buffering=0) as stream:
        child = subprocess.Popen(
            [executable, "-m", "lamp", "_serve"],
            cwd=data_dir(),
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=stream,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            start_new_session=sys.platform != "win32",
        )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if info := running_info():
            return info
        if child.poll() is not None:
            # 同时启动的另一个后台进程可能已经获得服务锁。
            if info := running_info():
                return info
            break
        time.sleep(0.15)
    if child.poll() is None:
        child.terminate()
        child.wait(timeout=5)
    raise RuntimeError(f"服务未能启动，请查看日志：{log}（配置端口：{config['server']['port']}）")


def stop() -> bool:
    info = running_info()
    if info is None:
        return False
    request(info, "/_stop", "POST")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if running_info() is None:
            # 等待进程释放服务锁，再允许重启。
            try:
                with service_lock():
                    return True
            except RuntimeError:
                pass
        time.sleep(0.15)
    raise RuntimeError("服务仍在结束当前请求，请稍后再检查 lamp status")


def links(info: dict) -> None:
    print(f"开灯链接：{info['url']}/api/on")
    print(f"关灯链接：{info['url']}/api/off")
    print("请求方法：POST")
    print("请求体：留空即可")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32":
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(config: dict, controller, loop, stopping: asyncio.Event, info: dict) -> Server:
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, status: int, value: dict) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def log_message(self, format, *args):
            logging.info(
                "HTTP 请求 方法=%s 客户端=%s 状态码=%s",
                self.command,
                self.client_address[0],
                args[1] if len(args) > 1 else "-",
            )

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/health":
                self.reply(
                    200,
                    {
                        "ok": True,
                        "version": __version__,
                        "pid": info["pid"],
                        "instance": info["instance"],
                    },
                )
            elif path in ("/api/on", "/api/off"):
                self.reply(405, {"error": "请使用 POST"})
            else:
                self.reply(404, {"error": "接口不存在"})

        def do_POST(self):
            path = urlsplit(self.path).path
            instance = self.headers.get("X-Lamp-Instance")
            if instance is not None and instance != info["instance"]:
                self.reply(409, {"error": "服务实例已变化，请重新查询 lamp status"})
                return
            if path == "/_stop":
                if self.client_address[0] != "127.0.0.1" or instance != info["instance"]:
                    self.reply(403, {"error": "仅允许本机管理服务"})
                    return
                self.reply(200, {"ok": True})
                loop.call_soon_threadsafe(stopping.set)
                return
            if path not in ("/api/on", "/api/off"):
                self.reply(404, {"error": "接口不存在"})
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host', '')}":
                self.reply(403, {"error": "不接受跨站网页请求"})
                return
            action = path.rsplit("/", 1)[-1]
            future = asyncio.run_coroutine_threadsafe(controller.send(action), loop)
            try:
                self.reply(200, future.result(timeout=20))
            except Exception as exc:
                future.cancel()
                logging.error("发送失败 动作=%s 错误=%s", action, exc)
                self.reply(503, {"error": str(exc) or "发送超时"})

    port = config["server"]["port"]
    last_error = None
    for candidate in range(port, min(port + 20, 65536)):
        try:
            server = Server(("0.0.0.0", candidate), Handler)
            info["port"] = server.server_address[1]
            return server
        except OSError as exc:
            if exc.errno not in (13, 48, 98, 10048) and getattr(exc, "winerror", None) not in (
                10013,
                10048,
            ):
                raise
            last_error = exc
    raise RuntimeError("未找到可用端口") from last_error


async def serve() -> None:
    bluetooth.require_windows()
    with service_lock():
        config = load_config()
        await bluetooth.check_adapter()
        controller = Controller(config)
        loop = asyncio.get_running_loop()
        stopping = asyncio.Event()
        info = {"pid": os.getpid(), "instance": uuid.uuid4().hex, "config": config}
        host = config["server"]["advertise_host"]
        if host == "auto":
            host = local_address()
        server = create_server(config, controller, loop, stopping, info)
        info["url"] = f"http://{host}:{info['port']}"
        if info["port"] != config["server"]["port"]:
            config["server"]["port"] = info["port"]
            atomic_json(file_path("config.json"), config)
        atomic_json(file_path("service.json"), info)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logging.info("服务已启动 PID=%s 端口=%s", info["pid"], info["port"])
        try:
            await stopping.wait()
        finally:
            await asyncio.to_thread(server.shutdown)
            # 先停止接收请求，再等待已经排队的发送完成。
            async with controller.lock:
                pass
            server.server_close()
            file_path("service.json").unlink(missing_ok=True)
            logging.info("服务已停止")


def run_foreground() -> None:
    from logging.handlers import RotatingFileHandler

    data_dir().mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        file_path("events.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(serve())
