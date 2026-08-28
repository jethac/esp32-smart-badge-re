#!/usr/bin/env python3
from e87_device import run, verify_installed


if __name__ == "__main__":
    raise SystemExit(run(
        verify_installed,
        "Pull and re-audit the E87 controller APK on one exact serial",
    ))
