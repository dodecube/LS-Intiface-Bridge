# LS Intiface Bridge

Android bridge app for controlling Love Spouse / MuSe style devices from Intiface Central.

The app connects to Intiface Central's Device Websocket Server as a Lovense-compatible websocket device, receives vibration commands, and emits Love Spouse BLE legacy advertising packets from the Android device.

## Requirements

- Android 11 (API 30) or newer.
- Android device with BLE advertising support.
- Intiface Central running on Windows.
- Windows PC and Android device on the same network.
- Windows firewall allowing Intiface Central's Device Websocket Server port.

## Intiface Central Setup

Keep Intiface Central's normal Buttplug server and Device Websocket Server on separate ports.

Recommended layout:

```text
Intiface BP server:          ws://0.0.0.0:12345
Device Websocket Server:  ws://0.0.0.0:54817
```

In Intiface Central, add a websocket device:

```text
Protocol: lovense
Name:     LVSDevice
```

If the UI does not expose the name field, configure the user device config with a Lovense websocket entry named `LVSDevice`.

```json
{
  "version": {
    "major": 5,
    "minor": 5
  },
  "user_configs": {
    "protocols": {
      "lovense": {
        "communication": [
          {
            "websocket": {
              "name": "LVSDevice"
            }
          }
        ],
        "configurations": []
      }
    },
    "devices": []
  }
}
```

## Android App Usage

1. Build and install the debug APK.
2. On Android 11, Bluetooth permissions are granted at install time; make sure Bluetooth is turned on.
3. On Android 12 or newer, grant the requested Nearby Devices permissions.
4. On Android 13 or newer, notification permission is optional. Denying it does not prevent the bridge from running, though Android may show its foreground-service notification in a less visible place.
5. Enter the Device Websocket Server URL, for example:

```text
ws://192.168.0.2:54817
```

6. Press `Start`.
7. Start scanning in the Intiface client.

The app stores the last websocket URL. While running, it uses a foreground notification with a `Stop` action.

The test sliders send local BLE advertising levels without waiting for Intiface commands.

## BLE Payload

The bridge uses Android's Bluetooth LE advertiser with legacy, connectable, scannable advertising.

```text
Manufacturer ID: 0xFFF0
Prefix:          6D B6 43 CE 97 FE 42 7C
```

Lovense levels `0..20` are mapped to the original Love Spouse/MuSe command table from the ESP32 firmware.

## Development and APK build

### Build with Android Studio

1. Install Android Studio with **JDK 17** and Android SDK Platform **35**. Android Studio's bundled JDK 17 is suitable.
2. Open the repository root (the folder containing `settings.gradle.kts`) in Android Studio and allow Gradle sync to finish.
3. Select **Build > Build Bundle(s) / APK(s) > Build APK(s)**.
4. Android Studio will show a link to the generated APK. It is also written to:

   ```text
   app/build/outputs/apk/debug/app-debug.apk
   ```

### Build from a terminal

The first build needs internet access to download Gradle and dependencies, plus an installed Android SDK Platform 35. Use JDK 17 to run the build.

Linux/macOS:

```bash
./gradlew :app:assembleDebug
```

Windows PowerShell:

```powershell
.\gradlew.bat :app:assembleDebug
```

The resulting debug APK is signed with Android's debug key and can be installed for testing. It is not a Play Store release; publishing a release APK requires configuring a private signing key.

## Experimental Windows PC bridge

A Windows/Python prototype that publishes the same BLE packets directly from a PC Bluetooth adapter is available in [`pc_bridge/`](pc_bridge/README.md). It is experimental: the adapter/driver must support BLE advertising, and Windows may introduce advertising gaps while commands change. The Android app remains the reference implementation until the PC version is tested with the target adapter and toy.

## Source files

```text
app/src/main/java/kr/glora/lsintifacebridge/MainActivity.kt
app/src/main/java/kr/glora/lsintifacebridge/BridgeService.kt
```
