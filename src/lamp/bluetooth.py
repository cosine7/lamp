"""系统蓝牙接口，目前仅支持 Windows WinRT。"""

import asyncio
import sys


def require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("当前蓝牙发送和自启动仅支持 Windows；其他平台尚未适配")


async def check_adapter() -> None:
    require_windows()
    from winrt.windows.devices.bluetooth import BluetoothAdapter

    adapter = await BluetoothAdapter.get_default_async()
    if adapter is None or not adapter.is_peripheral_role_supported:
        raise RuntimeError("未找到支持 BLE 广播的蓝牙适配器，请检查蓝牙是否打开")
    radio = await adapter.get_radio_async()
    if radio is None or radio.state.name != "ON":
        raise RuntimeError("蓝牙未打开，请在 Windows 设置中打开蓝牙")


async def publish(packet: bytes, manufacturer_id: int, seconds: float) -> None:
    require_windows()
    from winrt.windows.devices.bluetooth.advertisement import (
        BluetoothLEAdvertisementPublisher,
        BluetoothLEManufacturerData,
    )
    from winrt.windows.storage.streams import DataWriter

    publisher = BluetoothLEAdvertisementPublisher()
    writer = DataWriter()
    writer.write_bytes(packet)
    publisher.advertisement.manufacturer_data.append(
        BluetoothLEManufacturerData(manufacturer_id, writer.detach_buffer())
    )
    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def changed(sender, args):
        def complete():
            if ready.done():
                return
            if args.status.name == "STARTED":
                ready.set_result(None)
            elif args.status.name == "ABORTED":
                ready.set_exception(RuntimeError(f"蓝牙广播失败：{args.error.name}"))

        loop.call_soon_threadsafe(complete)

    token = publisher.add_status_changed(changed)
    try:
        publisher.start()
        await asyncio.wait_for(ready, timeout=8)
        await asyncio.sleep(seconds)
        if publisher.status.name == "ABORTED":
            raise RuntimeError("蓝牙广播中途停止，请检查蓝牙状态")
    finally:
        publisher.stop()
        await asyncio.sleep(0.3)
        publisher.remove_status_changed(token)
        writer.close()


async def capture(action: str, manufacturer_id: int, seconds: float, identity: str | None) -> bytes:
    require_windows()
    from bleak import BleakScanner

    from .protocol import COMMANDS, decode, remote_id

    loop = asyncio.get_running_loop()
    found = loop.create_future()

    def seen(device, advertisement):
        packet = advertisement.manufacturer_data.get(manufacturer_id)
        template = decode(packet) if packet else None
        if template is None or template[16] != COMMANDS[action]:
            return
        if identity and remote_id(template) != identity:
            return
        if not found.done():
            found.set_result(template)

    async with BleakScanner(detection_callback=seen):
        print(f"扫描已开始，请现在按遥控器的{'开灯' if action == 'on' else '关灯'}键。", flush=True)
        try:
            return await asyncio.wait_for(found, seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "未采集到符合协议的信号；原配置未覆盖，可用 config set/import"
            ) from exc
