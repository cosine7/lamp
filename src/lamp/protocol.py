"""Argrace remote v4 协议，白化算法参考 NicoIIT/ha-ble-adv（MIT 授权）。

参见 THIRD-PARTY-LICENSE.txt。模板包含前缀，不含校验字节。
"""

import secrets

MATRIX = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0x5A, 0xA5, 0xA5, 0x5A])
COMMANDS = {"on": 1, "off": 2}


def _crypt(payload: bytes, seed: bytes) -> bytes:
    pivot = seed + seed[::-1]
    return bytes(x ^ pivot[i % 8] ^ MATRIX[i % 8] for i, x in enumerate(payload))


def encode(template: bytes) -> bytes:
    if len(template) != 20 or template[0] != 4:
        raise ValueError("需要 20 字节的 Argrace remote v4 解码模板（04 开头）")
    plain = template[5:] + bytes([sum(template[5:]) & 255])
    packet = template[:5] + _crypt(plain, template[1:5])
    return packet + bytes([(sum(packet) + 0x1A) & 255])


def decode(packet: bytes) -> bytes | None:
    if len(packet) != 22 or packet[0] != 4:
        return None
    if packet[-1] != (sum(packet[:-1]) + 0x1A) & 255:
        return None
    plain = _crypt(packet[5:-1], packet[1:5])
    if plain[-1] != sum(plain[:-1]) & 255:
        return None
    return packet[:5] + plain[:-1]


def remote_id(template: bytes) -> str:
    return template[9:15].hex()


def initial_state(templates: dict[str, str]) -> dict:
    on, off = (bytes.fromhex(templates[a]) for a in COMMANDS)
    # 学习流程最后采集关灯；迁移的运行状态可以替换这些初始计数。
    return {
        "remote_id": remote_id(on),
        "tx_count": off[5],
        "restart_count": off[6],
        "button_counts": {"on": on[17], "off": off[17]},
    }


def next_packet(templates: dict[str, str], state: dict, action: str) -> tuple[bytes, dict]:
    template = bytearray.fromhex(templates[action])
    tx_count = (state["tx_count"] + 1) & 255
    new_state = {
        **state,
        "tx_count": tx_count,
        "restart_count": (state["restart_count"] + (tx_count == 0)) & 255,
        "button_counts": dict(state["button_counts"]),
    }
    new_state["button_counts"][action] = (state["button_counts"][action] + 1) & 255
    template[1:5] = secrets.token_bytes(4)
    template[5] = new_state["tx_count"]
    template[6] = new_state["restart_count"]
    template[17] = new_state["button_counts"][action]
    return encode(template), new_state
