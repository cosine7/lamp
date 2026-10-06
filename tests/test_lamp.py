"""验证真实行为边界，所有广播使用模拟器，不影响实际灯。"""

import asyncio
import copy
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from lamp import cli, service
from lamp.controller import Controller
from lamp.protocol import decode, encode, initial_state, next_packet
from lamp.storage import (
    DEFAULT_CONFIG,
    atomic_json,
    config_path,
    file_path,
    load_config,
    read_json,
    save_config,
    service_lock,
    validate,
)

# 虚构遥控器 ID，用于测试；不包含个人配置。
ON = "040102030405160000010203040506000109ff9c"
OFF = "0401020304061600000102030405060002faff00"


def config():
    value = copy.deepcopy(DEFAULT_CONFIG)
    value["templates"] = {"on": ON, "off": OFF}
    return value


class Isolated(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LAMP_HOME": self.directory.name})
        self.environment.start()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.environment.stop)


class ProtocolTests(unittest.TestCase):
    def test_corrupt_packets_are_not_learned(self):
        packet = bytearray(encode(bytes.fromhex(ON)))
        self.assertEqual(decode(packet), bytes.fromhex(ON))
        packet[8] ^= 1
        # 重算外层校验，仍应被内层校验拒绝。
        packet[-1] = (sum(packet[:-1]) + 0x1A) & 255
        self.assertIsNone(decode(packet))
        self.assertIsNone(decode(b"\x04"))
        packet[0] = 3
        self.assertIsNone(decode(packet))

    def test_rollover_retains_unknown_fields_and_changes_seed(self):
        templates = config()["templates"]
        state = initial_state(templates)
        state.update(tx_count=255, restart_count=22)
        with patch("lamp.protocol.secrets.token_bytes", return_value=b"\x10\x20\x30\x40"):
            packet, advanced = next_packet(templates, state, "on")
        decoded = decode(packet)
        original = bytes.fromhex(ON)
        self.assertEqual(advanced["tx_count"], 0)
        self.assertEqual(advanced["restart_count"], 23)
        self.assertEqual(decoded[1:5], b"\x10\x20\x30\x40")
        self.assertEqual(decoded[7:17], original[7:17])
        self.assertEqual(decoded[18:], original[18:])
        self.assertEqual(state["tx_count"], 255)


class ConfigTests(Isolated):
    def test_manual_templates_import_export_and_invalid_import(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(
                cli.main(["config", "set", "--on-template", ON, "--off-template", OFF]), 0
            )
            exported = Path(self.directory.name) / "backup.json"
            self.assertEqual(cli.main(["config", "export", str(exported)]), 0)
            self.assertEqual(cli.main(["config", "set", "--id", "111213141516"]), 0)
            self.assertNotEqual(load_config()["templates"]["on"], ON)
            self.assertEqual(cli.main(["config", "import", str(exported)]), 0)
            self.assertEqual(load_config(), config())
            exported.write_text('{"schema_version": 99}', encoding="utf-8")
            self.assertEqual(cli.main(["config", "import", str(exported)]), 1)
            self.assertEqual(load_config(), config())

    def test_mismatched_remote_ids_rejected(self):
        value = config()
        template = bytearray.fromhex(OFF)
        template[9] ^= 1
        value["templates"]["off"] = template.hex()
        with self.assertRaises(ValueError):
            validate(value)

    def test_invalid_restart_does_not_stop_running_service(self):
        save_config(config())
        invalid = config()
        invalid["server"]["port"] = -1
        atomic_json(config_path(), invalid)
        with patch("lamp.service.stop") as stop, redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["restart"]), 1)
        stop.assert_not_called()

    def test_single_writer_lock(self):
        with service_lock():
            with self.assertRaises(RuntimeError):
                with service_lock():
                    self.fail("不应允许第二个进程持有服务锁")

    def test_failed_learning_preserves_config_and_state(self):
        save_config(config())
        atomic_json(file_path("state.json"), initial_state(config()["templates"]))
        before = config_path().read_bytes(), file_path("state.json").read_bytes()
        with (
            patch("lamp.service.running_info", return_value=None),
            patch("lamp.bluetooth.check_adapter", new_callable=AsyncMock),
            patch("lamp.bluetooth.capture", new_callable=AsyncMock) as capture,
            patch("builtins.input", return_value=""),
            redirect_stdout(io.StringIO()),
        ):
            capture.side_effect = [bytes.fromhex(ON), RuntimeError("未采集到信号")]
            with self.assertRaises(RuntimeError):
                asyncio.run(cli.learn(1))
        self.assertEqual(before, (config_path().read_bytes(), file_path("state.json").read_bytes()))


class HomebridgeTests(Isolated):
    def test_export_uses_live_port_and_preserves_private_data(self):
        save_config(config())
        atomic_json(file_path("state.json"), initial_state(config()["templates"]))
        before = config_path().read_bytes(), file_path("state.json").read_bytes()
        output, errors = io.StringIO(), io.StringIO()
        info = {"port": 8766, "url": "http://192.168.1.20:8766", "config": config()}
        with (
            patch("lamp.service.running_info", return_value=info),
            patch("lamp.service.spawn") as spawn,
            patch("lamp.bluetooth.publish") as publish,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            self.assertEqual(cli.main(["homebridge", "export"]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["name"], "吸顶灯")
        self.assertEqual(value["accessory"], "HTTP-SWITCH")
        self.assertEqual(value["switchType"], "toggle")
        for action in ("on", "off"):
            self.assertEqual(
                value[f"{action}Url"],
                {"url": f"http://127.0.0.1:8766/api/{action}", "method": "POST"},
            )
        self.assertNotIn("templates", output.getvalue())
        self.assertNotIn("remote_id", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(before, (config_path().read_bytes(), file_path("state.json").read_bytes()))
        spawn.assert_not_called()
        publish.assert_not_called()

    def test_export_without_running_service_has_empty_stdout(self):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch("lamp.service.running_info", return_value=None),
            patch("lamp.service.spawn") as spawn,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            self.assertEqual(cli.main(["homebridge", "export"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("lamp start", errors.getvalue())
        spawn.assert_not_called()


class ControllerTests(Isolated):
    def test_commands_are_serialized_and_failed_send_consumes_counter(self):
        async def scenario():
            controller = Controller(config())
            active = 0
            packets = []

            async def publish(packet, *_):
                nonlocal active
                self.assertEqual(active, 0)
                active += 1
                # 发布回调运行时，磁盘计数必须已经更新。
                self.assertEqual(read_json(file_path("state.json"))["tx_count"], decode(packet)[5])
                await asyncio.sleep(0.01)
                packets.append(packet)
                active -= 1

            with patch("lamp.bluetooth.publish", side_effect=publish):
                await asyncio.gather(controller.send("off"), controller.send("on"))
            self.assertNotEqual(packets[0], packets[1])
            after = read_json(file_path("state.json"))
            self.assertEqual(Controller(config()).state, after)
            with patch("lamp.bluetooth.publish", side_effect=RuntimeError("模拟广播失败")):
                with self.assertRaises(RuntimeError):
                    await controller.send("on")
            self.assertEqual(
                read_json(file_path("state.json"))["tx_count"], (after["tx_count"] + 1) & 255
            )

        asyncio.run(scenario())


class HttpTests(unittest.TestCase):
    def test_vpn_benchmark_address_is_not_advertised_to_phone(self):
        with (
            patch("lamp.service.socket.socket") as probe,
            patch(
                "lamp.service.socket.gethostbyname_ex",
                return_value=("computer", [], ["198.18.0.1", "169.254.10.20", "192.168.0.17"]),
            ),
        ):
            probe.return_value.__enter__.return_value.getsockname.return_value = ("198.18.0.1", 1)
            self.assertEqual(service.local_address(), "192.168.0.17")

    def test_readable_post_routes_and_get_never_controls_light(self):
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever)
        loop_thread.start()
        stopping = asyncio.Event()
        controller = AsyncMock()
        controller.send.return_value = {"ok": True, "message": "广播完成"}
        info = {"instance": "test-instance", "pid": 123}
        # 让系统分配测试端口，避免干扰实际服务。
        value = config()
        value["server"]["port"] = 0
        server = service.create_server(value, controller, loop, stopping, info)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        opener = build_opener(ProxyHandler({}))

        def call(path, method="GET", headers=None):
            query = Request(
                f"http://127.0.0.1:{info['port']}{path}",
                method=method,
                data=b"" if method == "POST" else None,
                headers=headers or {},
            )
            try:
                with opener.open(query, timeout=3) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                return exc.code, json.load(exc)

        try:
            self.assertEqual(call("/health")[0], 200)
            self.assertEqual(call("/api/on")[0], 405)
            self.assertEqual(call("/")[0], 404)
            self.assertEqual(call("/_stop", "POST")[0], 403)
            self.assertEqual(call("/api/off", "POST", {"Origin": "https://example.org"})[0], 403)
            controller.send.assert_not_called()
            self.assertEqual(call("/api/off", "POST")[0], 200)
            self.assertEqual(call("/api/on", "POST")[0], 200)
            self.assertEqual(controller.send.await_args_list[0].args, ("off",))
            self.assertEqual(controller.send.await_args_list[1].args, ("on",))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join()
            loop.close()

    def test_occupied_port_selects_another_port(self):
        with socket.socket() as occupied:
            occupied.bind(("0.0.0.0", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            value = config()
            value["server"]["port"] = port
            info = {}
            server = service.create_server(value, None, None, None, info)
            try:
                self.assertGreater(info["port"], port)
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()
