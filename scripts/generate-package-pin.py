#!/usr/bin/python3
import argparse
import re
from pathlib import Path


HEADER_SIZE_BYTES = 27
MAX_PACKAGE_SIZE_BYTES = 32 * 1024 * 1024
HEX_64 = re.compile(r"[0-9A-Fa-f]{64}")
HEX_54 = re.compile(r"[0-9A-Fa-f]{54}")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate the required immutable identity for one reviewed Qix package."
    )
    parser.add_argument("--size", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--header", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def fail(message):
    raise SystemExit(message)


def main():
    arguments = parse_arguments()
    try:
        size = int(arguments.size, 10)
    except ValueError:
        fail("size must be a base-10 integer")
    if size <= HEADER_SIZE_BYTES or size > MAX_PACKAGE_SIZE_BYTES:
        fail("size must be greater than 27 bytes and no greater than 32 MiB")
    if HEX_64.fullmatch(arguments.sha256) is None:
        fail("sha256 must be exactly 64 hexadecimal digits")
    if HEX_54.fullmatch(arguments.header) is None:
        fail("header must be exactly 27 bytes encoded as 54 hexadecimal digits")

    sha256 = arguments.sha256.upper()
    header_hex = arguments.header.upper()
    header = bytes.fromhex(header_hex)
    declared_payload_length = int.from_bytes(header[13:17], "little")
    if declared_payload_length != size - HEADER_SIZE_BYTES:
        fail("header declared payload length does not match size minus 27")

    source_lines = [
        "package com.openai.e87probe;",
        "",
        "/** Generated at build time from mandatory reviewed package pins. */",
        "public final class GeneratedPackagePin {",
        "    private GeneratedPackagePin() {}",
        "",
        "    public static PackagePin create() {",
        f'        return new PackagePin({size}, "{sha256}",',
        f'                Hex.decode("{header_hex}"));',
        "    }",
        "}",
    ]
    source = chr(10).join(source_lines) + chr(10)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(source, encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
