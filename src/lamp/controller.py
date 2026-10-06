import asyncio
import logging

from . import bluetooth
from .protocol import initial_state, next_packet, remote_id
from .storage import atomic_json, file_path, read_json, validate_state


class Controller:
    def __init__(self, config: dict):
        self.config = config
        self.lock = asyncio.Lock()
        path = file_path("state.json")
        identity = remote_id(bytes.fromhex(config["templates"]["on"]))
        if path.exists():
            state = read_json(path)
            if state.get("remote_id") == identity:
                self.state = validate_state(state, identity)
            else:
                self.state = initial_state(config["templates"])
        else:
            self.state = initial_state(config["templates"])

    async def send(self, action: str) -> dict:
        async with self.lock:
            packet, state = next_packet(self.config["templates"], self.state, action)
            # 广播前先保存计数；发送失败也消耗本次计数，避免重复使用。
            atomic_json(file_path("state.json"), state)
            self.state = state
            await bluetooth.publish(
                packet, self.config["manufacturer_id"], self.config["broadcast_seconds"]
            )
            logging.info("广播已发送 动作=%s", action)
            return {
                "ok": True,
                "action": action,
                "message": "已发送开灯指令" if action == "on" else "已发送关灯指令",
            }
