#!/usr/bin/env python3
"""Fetch the one new transient source, or verify all inputs offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_LOCK = ROOT / "firmware/assets/asset-lock.json"
LOCK = ROOT / "firmware/assets/transient-asset-lock.json"
BASE_LOCK_SHA = "7832996bc29c95c2a4374280cc4014af322d840b98b97fb29006399a6a774b2b"
SOURCES = {
    "bolt": {
        "byteLength": 335,
        "destination": "firmware/assets/sources/bolt.svg",
        "license": "Apache-2.0",
        "repository": "google/material-design-icons",
        "sha256": "13195a03d22906ca3c7a78fc6e104cb269b98ddac7dca96c424fadc623c33f3c",
        "upstreamCommit": "e083cc60a0828fdd3b404cea0cb8a5b900e9c23e",
        "upstreamPath": "symbols/web/bolt/materialsymbolsrounded/bolt_24px.svg",
    },
    "roboto": {
        "byteLength": 488584,
        "destination": "firmware/assets/sources/Roboto[wdth,wght].ttf",
        "license": "OFL-1.1",
        "sha256": "d7598e12c5dbef095ff8272cfc55da0250bd07fbdecbac8a530b9b277872a134",
    },
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) +
            "\n").encode()


def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_record(name: str, data: bytes) -> None:
    record = SOURCES[name]
    if (len(data), sha(data)) != (record["byteLength"], record["sha256"]):
        raise SystemExit("transient source identity mismatch: " + name)


def load_base_lock() -> dict:
    raw = BASE_LOCK.read_bytes()
    if sha(raw) != BASE_LOCK_SHA:
        raise SystemExit("reviewed base asset lock identity changed")
    value = json.loads(raw)
    if raw != canonical(value):
        raise SystemExit("reviewed base asset lock is noncanonical")
    base_roboto = value["sources"]["roboto"]
    for field in ("byteLength", "destination", "sha256"):
        if base_roboto[field] != SOURCES["roboto"][field]:
            raise SystemExit("Roboto identity differs from reviewed base lock")
    return value


def build_lock() -> bytes:
    base = load_base_lock()
    return canonical({
        "baseAssetLockSha256": BASE_LOCK_SHA,
        "runtimeReference": base["runtime"]["finalReference"],
        "schemaVersion": 1,
        "sources": SOURCES,
    })


def source_url(record: dict) -> str:
    return "https://raw.githubusercontent.com/{}/{}/{}".format(
        record["repository"],
        record["upstreamCommit"],
        record["upstreamPath"],
    )


def write() -> None:
    record = SOURCES["bolt"]
    request = urllib.request.Request(
        source_url(record),
        headers={"User-Agent": "e87-transient-source-bootstrap/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        bolt = response.read(record["byteLength"] + 1)
    verify_record("bolt", bolt)
    verify_record(
        "roboto", (ROOT / SOURCES["roboto"]["destination"]).read_bytes())
    atomic(ROOT / record["destination"], bolt)
    atomic(LOCK, build_lock())


def check() -> None:
    if LOCK.read_bytes() != build_lock():
        raise SystemExit("transient asset lock differs from canonical bytes")
    for name, record in SOURCES.items():
        verify_record(name, (ROOT / record["destination"]).read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    write() if arguments.write else check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
