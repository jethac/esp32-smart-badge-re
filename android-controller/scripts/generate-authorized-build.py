#!/usr/bin/env python3
"""Create a review-required exact DEX authorization receipt from one built APK."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from e87_apk import _regular_absolute, write_receipt
from e87_build import build_authorization
from e87_embed import ValidationError
from e87_surface import validate_surface


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "app/src/main/java"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--surface-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        apk = _regular_absolute(arguments.apk, "APK")
        surface = _regular_absolute(
            arguments.surface_receipt,
            "authorized surface receipt",
        )
        validate_surface(surface, SOURCE_ROOT)
        value = build_authorization(apk, surface)
        write_receipt(arguments.output, value)
    except (OSError, ValidationError) as error:
        print(f"generate-authorized-build: {error}", file=os.sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
