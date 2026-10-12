#!/usr/bin/env python3
"""Windows BLE advertiser + Intiface Device WebSocket client.

Windows desktop proof-of-concept for the LS Intiface Bridge protocol. The
WebSocket side emulates a Lovense-compatible device; BLE output uses the
Windows Runtime BluetoothLEAdvertisementPublisher API.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import re
import sys
import time
from typing import Any

try:
    import websockets
except ImportError:  # pragma: no cover - user-facing installation error
    websockets = None


# Keep these values in sync with app/src/main/java/.../BridgeService.kt.
MANUFACTURER_ID = 0xFFF0
MANUFACTURER_PREFIX = bytes.fromhex("6D B6 43 CE 97 FE 42 7C")
BURST_INTERVAL_SECONDS = 0.250
HANDSHAKE = {
    "identifier": "LVSDevice",
    "address": "8A3D9FAC2A45",
    "version": 0,
}

VIBRATION_COMMANDS = (
    0xD5964C,
    0xD41F5D,
    0xD7846F,
    0xD60D7E,
    0xD1B20A,
    0xD03B1B,
    0xD3A029,
    0xD22938,
    0xDDDEC0,
    0xDC57D1,
)
ROTATION_COMMANDS = (
    0xA5113F,
    0xA4982E,
    0xA7031C,
    0xA68A0D,
    0xA13579,
    0xA0BC68,
    0xA3275A,
    0xA2AE4B,
    0xAD59B3,
    0xACD0A2,
)


def clamp_level(level: int) -> int:
    return max(0, min(20, level))


def lovense_level_to_index(level: int) -> int:
    """Map Lovense 0..20 into the firmware's off + 9 levels."""
    level = clamp_level(level)
    if level == 0:
        return 0
    # Matches the Kotlin bridge's truncation and rounding formula.
    return max(1, min(9, int((level / 20.0) * 8.0 + 0.5) + 1))


def manufacturer_body(encoded_command: int) -> bytes:
    return MANUFACTURER_PREFIX + bytes(
        (
            (encoded_command >> 16) & 0xFF,
            (encoded_command >> 8) & 0xFF,
            encoded_command & 0xFF,
        )
    )


def full_payload(encoded_command: int) -> bytes:
    # Company ID is little-endian in the raw BLE manufacturer-specific field.
    return MANUFACTURER_ID.to_bytes(2, "little") + manufacturer_body(encoded_command)


def parse_command_message(message: str) -> list[str]:
    """Return the same responses as the Android Lovense WebSocket shim."""
    raw = message.strip()
    if not raw:
        return ["OK;"]

    responses: list[str] = []
    for token in (part.strip() for part in re.split(r"[;\n]", raw)):
        if not token:
            continue
        command = token + ";"
        if command.startswith("DeviceType;"):
            response = "C:8A3D9FAC2A45:10;"
        elif command.startswith("Battery"):
            response = "99;"
        elif command.startswith("Status:1;"):
            response = "2;"
        elif command.startswith("AutoSwitch:") or command.startswith("RotateChange"):
            response = "OK;"
        else:
            response = "OK;"
        if response not in responses:
            responses.append(response)
    return responses or ["OK;"]


def parse_control_level(command: str, control: str) -> int:
    match = re.search(rf"{re.escape(control)}:(\d+)", command)
    return clamp_level(int(match.group(1))) if match else 0


class WindowsBleAdvertiser:
    """Publishes legacy BLE manufacturer data through Windows WinRT.

    Windows' public publisher API does not expose the Android AdvertisingSet
    data-update call. To change a command this prototype stops the current
    publisher and starts a new one. This is the main hardware/latency risk,
    especially when both command channels alternate every 250 ms.
    """

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise RuntimeError("The PC BLE publisher currently requires Windows 10/11.")
        try:
            from winrt.windows.devices.bluetooth.advertisement import (
                BluetoothLEAdvertisement,
                BluetoothLEAdvertisementPublisher,
                BluetoothLEAdvertisementPublisherStatus,
                BluetoothLEManufacturerData,
            )
            from winrt.windows.storage.streams import DataWriter
        except ImportError as exc:
            raise RuntimeError(
                "Windows BLE packages are missing. Install pc_bridge/requirements.txt."
            ) from exc

        self._Advertisement = BluetoothLEAdvertisement
        self._Publisher = BluetoothLEAdvertisementPublisher
        self._PublisherStatus = BluetoothLEAdvertisementPublisherStatus
        self._ManufacturerData = BluetoothLEManufacturerData
        self._DataWriter = DataWriter
        self._publisher: Any | None = None
        self._status_handler: Any | None = None
        self._payload: bytes | None = None
        self._last_error_payload: bytes | None = None

    @staticmethod
    def _status_name(status: Any) -> str:
        return getattr(status, "name", str(status))

    def _make_publisher(self, body: bytes) -> Any:
        writer = self._DataWriter()
        writer.write_bytes(bytearray(body))
        manufacturer = self._ManufacturerData(MANUFACTURER_ID, writer.detach_buffer())

        advertisement = self._Advertisement()
        advertisement.manufacturer_data.append(manufacturer)
        publisher = self._Publisher(advertisement)
        # The toy protocol uses legacy-size packets, not extended advertising.
        publisher.use_extended_advertisement = False

        def on_status_changed(_sender: Any, args: Any) -> None:
            status = args.status
            status_name = self._status_name(status)
            if status == self._PublisherStatus.STARTED:
                tx_power = args.selected_transmit_power_level_in_dbm
                suffix = f", tx={tx_power} dBm" if tx_power is not None else ""
                print(f"[BLE] Windows publisher started{suffix}", flush=True)
            elif status == self._PublisherStatus.ABORTED:
                print(
                    f"[BLE] Windows publisher aborted: error={args.error}",
                    flush=True,
                )
            elif status == self._PublisherStatus.STOPPED:
                print("[BLE] Windows publisher stopped", flush=True)
            elif status == self._PublisherStatus.WAITING:
                print("[BLE] Windows publisher waiting for adapter", flush=True)
            else:
                print(f"[BLE] Windows publisher status: {status_name}", flush=True)

        self._status_handler = on_status_changed
        publisher.add_status_changed(on_status_changed)
        return publisher

    async def stop(self) -> None:
        publisher = self._publisher
        self._publisher = None
        self._payload = None
        if publisher is None:
            return
        try:
            publisher.stop()
            # WinRT reports STOPPED asynchronously. Give the controller a
            # short window to release the old advertisement before restarting.
            deadline = time.monotonic() + 0.6
            while time.monotonic() < deadline:
                if publisher.status == self._PublisherStatus.STOPPED:
                    break
                await asyncio.sleep(0.025)
        except Exception as exc:  # stop should not prevent process shutdown
            print(f"[BLE] Error stopping Windows publisher: {exc}", flush=True)

    async def set_payload(self, body: bytes) -> bool:
        if self._publisher is not None and self._payload == body:
            return True

        await self.stop()
        try:
            publisher = self._make_publisher(body)
            publisher.start()
            self._publisher = publisher
            self._payload = body

            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                status = publisher.status
                if status == self._PublisherStatus.STARTED:
                    self._last_error_payload = None
                    return True
                if status == self._PublisherStatus.ABORTED:
                    if self._last_error_payload != body:
                        print(
                            "[BLE] Adapter rejected the advertisement. "
                            "Check that the Windows Bluetooth radio supports LE advertising.",
                            flush=True,
                        )
                        self._last_error_payload = body
                    self._publisher = None
                    self._payload = None
                    return False
                await asyncio.sleep(0.05)

            status = publisher.status
            if status == self._PublisherStatus.STARTED:
                return True
            if self._last_error_payload != body:
                print(
                    f"[BLE] Publisher did not start (status={self._status_name(status)}). "
                    "Check the adapter and Windows Bluetooth settings.",
                    flush=True,
                )
                self._last_error_payload = body
            self._publisher = None
            self._payload = None
            return False
        except Exception as exc:
            self._publisher = None
            self._payload = None
            if self._last_error_payload != body:
                print(f"[BLE] Failed to publish advertisement: {exc}", flush=True)
                self._last_error_payload = body
            return False


class BridgeController:
    def __init__(self, advertiser: WindowsBleAdvertiser) -> None:
        self.advertiser = advertiser
        self.vibration_level = 0
        self.rotation_level = 0
        self.target_vibe_index = 0
        self.target_rotate_index = 0
        self.active_channel = "none"
        self.vibe_stop_sent = True
        self.rotate_stop_sent = True
        self.current_level = 0
        self.current_payload: bytes | None = None

    def set_vibration(self, level: int) -> None:
        self.vibration_level = clamp_level(level)
        self.target_vibe_index = lovense_level_to_index(self.vibration_level)
        if self.target_vibe_index > 0:
            self.vibe_stop_sent = False
        print(f"[WS] Vibrate={self.vibration_level} -> L{self.target_vibe_index}", flush=True)

    def set_rotation(self, level: int) -> None:
        self.rotation_level = clamp_level(level)
        self.target_rotate_index = lovense_level_to_index(self.rotation_level)
        if self.target_rotate_index > 0:
            self.rotate_stop_sent = False
        print(f"[WS] Rotate={self.rotation_level} -> L{self.target_rotate_index}", flush=True)

    def power_off(self) -> None:
        self.vibration_level = 0
        self.rotation_level = 0
        self.target_vibe_index = 0
        self.target_rotate_index = 0

    async def _apply(self, channel: str, encoded_command: int, level_index: int) -> None:
        channel_changed = self.active_channel != channel
        self.active_channel = channel
        self.current_level = level_index
        body = manufacturer_body(encoded_command)
        payload = full_payload(encoded_command)
        if self.current_payload != payload or channel_changed:
            label = "Vib" if channel == "vibration" else "Rot"
            print(
                f"[BLE] {label} -> L{level_index}: {payload.hex(' ').upper()} "
                f"[V:{self.target_vibe_index},R:{self.target_rotate_index}]",
                flush=True,
            )
        self.current_payload = payload
        await self.advertiser.set_payload(body)

    async def tick(self) -> None:
        vibe_active = self.target_vibe_index > 0
        rotate_active = self.target_rotate_index > 0

        if vibe_active and rotate_active:
            next_channel = "rotation" if self.active_channel == "vibration" else "vibration"
            if next_channel == "vibration":
                await self._apply(
                    "vibration",
                    VIBRATION_COMMANDS[self.target_vibe_index],
                    self.target_vibe_index,
                )
            else:
                await self._apply(
                    "rotation",
                    ROTATION_COMMANDS[self.target_rotate_index],
                    self.target_rotate_index,
                )
        elif vibe_active:
            if not self.rotate_stop_sent:
                self.rotate_stop_sent = True
                await self._apply("rotation", ROTATION_COMMANDS[0], 0)
            else:
                await self._apply(
                    "vibration",
                    VIBRATION_COMMANDS[self.target_vibe_index],
                    self.target_vibe_index,
                )
        elif rotate_active:
            if not self.vibe_stop_sent:
                self.vibe_stop_sent = True
                await self._apply("vibration", VIBRATION_COMMANDS[0], 0)
            else:
                await self._apply(
                    "rotation",
                    ROTATION_COMMANDS[self.target_rotate_index],
                    self.target_rotate_index,
                )
        elif not self.vibe_stop_sent:
            self.vibe_stop_sent = True
            await self._apply("vibration", VIBRATION_COMMANDS[0], 0)
        elif not self.rotate_stop_sent:
            self.rotate_stop_sent = True
            await self._apply("rotation", ROTATION_COMMANDS[0], 0)
        else:
            self.active_channel = "none"
            self.current_level = 0
            self.current_payload = None
            await self.advertiser.stop()

    async def scheduler(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(BURST_INTERVAL_SECONDS)

    def process_message(self, text: str) -> str:
        raw = text.strip()
        tokens = [part.strip() for part in re.split(r"[;\n]", raw) if part.strip()]
        responses: list[str] = []
        for token in tokens:
            command = token + ";"
            response = parse_command_message(command)[0]
            if command.startswith("Vibrate:"):
                self.set_vibration(parse_control_level(command, "Vibrate"))
            elif command.startswith("Rotate:"):
                self.set_rotation(parse_control_level(command, "Rotate"))
            elif command.startswith("PowerOff") or command.startswith("StopDevice"):
                self.power_off()
            if response not in responses:
                responses.append(response)
        return "".join(responses) if responses else "OK;"


async def send_test(advertiser: WindowsBleAdvertiser, vibe: int, rotate: int, seconds: float) -> None:
    controller = BridgeController(advertiser)
    if vibe:
        controller.set_vibration(vibe)
    if rotate:
        controller.set_rotation(rotate)
    scheduler = asyncio.create_task(controller.scheduler())
    print(f"Test advertising for {seconds:g}s; press Ctrl+C to stop.", flush=True)
    try:
        await asyncio.sleep(seconds)
    finally:
        controller.power_off()
        # The firmware needs one zero command per channel before advertising
        # can safely stop.
        await asyncio.sleep(0.65)
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)
        await advertiser.stop()


async def websocket_session(url: str, advertiser: WindowsBleAdvertiser) -> None:
    controller = BridgeController(advertiser)
    async with websockets.connect(
        url,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        max_size=64 * 1024,
    ) as socket:
        await socket.send(json.dumps(HANDSHAKE, separators=(",", ":")))
        print(f"[WS] Connected to {url}", flush=True)
        print("[WS] Handshake sent as LVSDevice", flush=True)

        scheduler = asyncio.create_task(controller.scheduler())
        try:
            async for message in socket:
                is_binary = isinstance(message, bytes)
                text = message.decode("utf-8", errors="replace") if is_binary else message
                print(f"[WS] <- {text.strip()}", flush=True)
                response = controller.process_message(text)
                await socket.send(response.encode("utf-8") if is_binary else response)
                print(f"[WS] -> {response}", flush=True)
        finally:
            controller.power_off()
            await asyncio.sleep(0.65)
            scheduler.cancel()
            await asyncio.gather(scheduler, return_exceptions=True)
            await advertiser.stop()


async def run_client(url: str, advertiser: WindowsBleAdvertiser) -> None:
    while True:
        try:
            await websocket_session(url, advertiser)
            print("[WS] Server closed the connection; reconnecting in 3 seconds", flush=True)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[WS] Connection failed: {exc}", flush=True)
            await advertiser.stop()
            print("[WS] Retrying in 3 seconds (Ctrl+C to exit)", flush=True)
        await asyncio.sleep(3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Windows BLE/Intiface bridge for Love Spouse and MuSe-style toys."
    )
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:54817",
        help="Intiface Device WebSocket Server URL (default: ws://127.0.0.1:54817)",
    )
    parser.add_argument(
        "--test-vibration",
        type=int,
        metavar="0..20",
        help="Transmit a local vibration test instead of connecting to Intiface.",
    )
    parser.add_argument(
        "--test-rotation",
        type=int,
        metavar="0..20",
        help="Transmit a local rotation test instead of connecting to Intiface.",
    )
    parser.add_argument(
        "--test-seconds",
        type=float,
        default=10.0,
        help="How long the local test runs (default: 10 seconds).",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    if platform.system() != "Windows":
        raise RuntimeError("This PC prototype currently supports Windows 10/11 only.")
    if websockets is None:
        raise RuntimeError("Missing dependency. Run: python -m pip install -r requirements.txt")

    advertiser = WindowsBleAdvertiser()
    if args.test_vibration is not None or args.test_rotation is not None:
        await send_test(
            advertiser,
            clamp_level(args.test_vibration or 0),
            clamp_level(args.test_rotation or 0),
            max(1.0, args.test_seconds),
        )
    else:
        await run_client(args.url, advertiser)


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
