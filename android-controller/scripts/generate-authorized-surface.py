#!/usr/bin/env python3
"""Create a review-required source/class authorization receipt from one built APK."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from e87_apk import _regular_absolute, _run, write_receipt
from e87_embed import ValidationError
from e87_surface import build_surface


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "app/src/main/java"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--dexdump", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        apk = _regular_absolute(arguments.apk, "APK")
        dexdump = _regular_absolute(arguments.dexdump, "dexdump", executable=True)
        value = build_surface(
            SOURCE_ROOT,
            _run(dexdump, ["-d", os.fspath(apk)], "dexdump"),
        )
        write_receipt(arguments.output, value)
    except (OSError, ValidationError) as error:
        print(f"generate-authorized-surface: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
