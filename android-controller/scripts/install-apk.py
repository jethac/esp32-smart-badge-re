#!/usr/bin/env python3
from e87_device import install, run


if __name__ == "__main__":
    raise SystemExit(run(install, "Audit and install an E87 controller APK on one exact serial"))
