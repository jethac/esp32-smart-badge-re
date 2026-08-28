# E87 Qix factory memory-read probe

This throwaway Android 12 probe opens one BLE connection to an exact E87 MAC,
discovers Qix service `c2e6fd00-e966-1000-8000-bef9c223df6a`, subscribes to
both FD01 and FD03 in sequence, then writes exactly one request to FD03:

```text
9E4382A90600000200001000
```

It records notifications for 30 seconds or until the badge disconnects. Each
notification is preserved separately as `rx-NNNNNN-fd01.bin` or
`rx-NNNNNN-fd03.bin`, and each channel is also concatenated into
`fd01-notifications.bin` or `fd03-notifications.bin`. The run directory also
contains the transmitted request, discovered GATT layout, capture summary, and
timestamped `probe.log`. A reset or disconnect after the request is treated as
a completed capture so the evidence is retained.

Build and run against the Redmi 9T and current badge:

```powershell
.\run-host-tests.ps1
.\build.ps1
.\install-and-run.ps1 -Serial b202e7b70221 -Mac 46:83:00:01:8A:E9
```

Inspect live output:

```powershell
adb -s b202e7b70221 logcat -s E87Probe:I '*:S'
```

Pull every unique run directory after completion:

```powershell
adb -s b202e7b70221 pull /sdcard/Android/data/com.openai.e87probe/files .\captured
```

The APK build remains offline and dependency-free. It compiles against API 34
while declaring `minSdkVersion=31` and `targetSdkVersion=31`.
