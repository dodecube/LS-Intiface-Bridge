# Windows PC bridge (experimental)

This is a Windows proof-of-concept that replaces the Android phone as the BLE advertiser. It connects to Intiface Central's **Device WebSocket Server** as `LVSDevice`, then publishes the same Love Spouse/MuSe-style manufacturer-data packets using Windows' Bluetooth LE advertisement API.

> **Hardware warning:** the USB adapter and its Windows driver must support BLE advertising/peripheral role. A dongle that can only scan/connect is not enough. The Windows publisher API also cannot update an active advertising set in the same way Android does, so this prototype stops and restarts advertising when a command changes. That may add gaps, especially when vibration and rotation are alternating. This has not been tested against the FODRK AN001 or the user's adapter.

## Requirements

- Windows 10 or 11.
- 64-bit Python 3.11 recommended.
- A BLE adapter whose Windows driver exposes BLE advertising.
- Intiface Central with **Device Websocket Server** enabled, a `lovense` WebSocket device named `LVSDevice`, and the Engine running.

The PC bridge connects locally to `ws://127.0.0.1:54817` by default. Stop the Android bridge before starting this program so both do not try to register as the same virtual device.

## Install Python packages

Open PowerShell in this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, you can skip activation and use the virtual environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Test BLE without Intiface

Keep the toy powered on and close the Love Spouse phone app. Then run:

```powershell
python bridge.py --test-vibration 20 --test-seconds 10
```

The program should report a Windows publisher state such as `STARTED`. If it reports `ABORTED` or cannot start, check that Bluetooth is on and that the selected adapter/driver supports BLE advertising. The test only proves that Windows accepted the advertisement; the toy still needs to accept this packet protocol.

You can test rotation similarly:

```powershell
python bridge.py --test-rotation 20 --test-seconds 10
```

## Connect to Intiface Central

With Intiface Central's Engine running and `LVSDevice` configured, run:

```powershell
python bridge.py
```

Or provide a different Device WebSocket Server URL:

```powershell
python bridge.py --url ws://127.0.0.1:54817
```

Game integrations/Buttplug clients still connect to the **normal** Intiface server (usually `ws://localhost:12345`). This bridge connects to the separate Device WebSocket Server (`54817`).

Press `Ctrl+C` to stop. The program replies to the Lovense handshake and supports vibration, rotation, battery/status queries, and stop commands.

## Important limitations

- The Windows publisher uses the system-selected Bluetooth radio; this prototype does not choose between multiple adapters.
- Windows does not expose all Android advertising parameters, including the same connectable/scannable and transmit-power controls.
- Payload changes require stopping and recreating the publisher. If the toy misses commands or simultaneous channels behave poorly, the adapter/Windows API may be the cause.
- This PC prototype is not a verified replacement yet. The Android implementation remains the known-good reference for the packet format; test this on the target PC and toy before relying on it.
