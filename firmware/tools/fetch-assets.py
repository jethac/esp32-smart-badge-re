#!/usr/bin/env python3
"""One-shot immutable source bootstrap and strictly offline verifier."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUAL = Path("/home/jethac/.local/share/e87-dev/asset-toolchain-qualification")
RECEIPT_SHA = "41d577c0ab31fbbc8903bfcf845d7619052548da38c6d762c9f877925e5b2cec"
RUNTIME = "127.0.0.1:5001/e87/asset-runtime@sha256:859689ef25f6940e22a5ea2427471596b42bb628bc8d308b5d3334721784d0ea"
WHEEL_TREE_SHA = "63ec949440b97db33b2c22e6f29b86bd8e2bd6fcbdbf6b11f3adbc1d3e32dc89"

SOURCES = {
    "date_range": {"byteLength": 694, "destination": "firmware/assets/sources/date_range.svg", "sha256": "342ef493b1d94132215ab4f25d90cbab34b448a39f50db1e929317ce8f28ab04", "upstreamCommit": "e083cc60a0828fdd3b404cea0cb8a5b900e9c23e", "upstreamPath": "symbols/web/date_range/materialsymbolsrounded/date_range_24px.svg", "repository": "google/material-design-icons"},
    "devin": {"byteLength": 9266, "canonicalSource": "assets/icons/devin.svg", "destination": "firmware/assets/sources/devin.svg", "sha256": "0b77af4a730199892f15d99e9b812a39452554089811e46d925e62c09e09a4a9", "tracedFrom": "jethac/factory@2720aaf58a9d86a5142fd86dfb05ecb39d31364d", "upstreamCommit": "3feec00b8a9aa8c6874ca92477e4ed43098e3b84", "upstreamPath": "assets/icons/devin.svg", "repository": "jethac/factory-smartscreen", "gitBlob": "0a11af513a7d208c2c49f33ab2d2d38fd4aefe90", "permissionStatus": "unverified"},
    "material_license": {"byteLength": 11357, "destination": "firmware/assets/licenses/material-design-icons-LICENSE", "sha256": "58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd", "upstreamCommit": "e083cc60a0828fdd3b404cea0cb8a5b900e9c23e", "upstreamPath": "LICENSE", "repository": "google/material-design-icons", "license": "Apache-2.0"},
    "roboto": {"byteLength": 488584, "destination": "firmware/assets/sources/Roboto[wdth,wght].ttf", "sha256": "d7598e12c5dbef095ff8272cfc55da0250bd07fbdecbac8a530b9b277872a134", "upstreamCommit": "6a003b5eb672dc8bf5bff5937cf5863f8b175445", "upstreamPath": "ofl/roboto/Roboto[wdth,wght].ttf", "repository": "google/fonts"},
    "roboto_license": {"byteLength": 4394, "destination": "firmware/assets/licenses/Roboto-OFL.txt", "sha256": "061402327a96aadb0bfb694a960ed289ecd38d383e396243831ab81feb109c41", "upstreamCommit": "6a003b5eb672dc8bf5bff5937cf5863f8b175445", "upstreamPath": "ofl/roboto/OFL.txt", "repository": "google/fonts", "license": "OFL-1.1"},
    "today": {"byteLength": 472, "destination": "firmware/assets/sources/today.svg", "sha256": "c2aa056cc2353ce349bea6657053370dfbbd38dd96c0e52217615aaf02a1fa04", "upstreamCommit": "e083cc60a0828fdd3b404cea0cb8a5b900e9c23e", "upstreamPath": "symbols/web/today/materialsymbolsrounded/today_24px.svg", "repository": "google/material-design-icons"},
}
WHEELS = [
    ("cairocffi-1.7.1-py3-none-any.whl",75611,"9803a0e11f6c962f3b0ae2ec8ba6ae45e957a146a004697a1ac1bbf16b073b3f",["py3","none","any"]),
    ("cairosvg-2.9.0-py3-none-any.whl",45962,"4b82d07d145377dffdfc19d9791bd5fb65539bb4da0adecf0bdbd9cd4ffd7c68",["py3","none","any"]),
    ("cffi-1.17.1-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",467242,"610faea79c43e44c71e1ec53a554553fa22321b65fae24889706c0a84d4ad86d",["cp311","cp311","manylinux_2_17_x86_64.manylinux2014_x86_64"]),
    ("cssselect2-0.8.0-py3-none-any.whl",15454,"46fc70ebc41ced7a32cd42d58b1884d72ade23d21e5a4eaaf022401c13f0e76e",["py3","none","any"]),
    ("defusedxml-0.7.1-py2.py3-none-any.whl",25604,"a352e7e428770286cc899e2542b6cdaedb2b4953ff269a210103ec58f6198a61",["py2.py3","none","any"]),
    ("fonttools-4.63.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl",5082308,"d76ac49f929aecaf82d83250b8347e099d7aecba0f4726c1d9b6df3b8bb5fe18",["cp311","cp311","manylinux2014_x86_64.manylinux_2_17_x86_64"]),
    ("pillow-12.2.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",7079655,"e74473c875d78b8e9d5da2a70f7099549f9eb37ded4e2f6a463e60125bccd176",["cp311","cp311","manylinux_2_27_x86_64.manylinux_2_28_x86_64"]),
    ("pycparser-2.22-py3-none-any.whl",117552,"c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc",["py3","none","any"]),
    ("tinycss2-1.4.0-py3-none-any.whl",26610,"3a49cf47b7675da0b15d0c6e1df8df4ebd96e9394bb905a5775adb0d884c5289",["py3","none","any"]),
    ("webencodings-0.5.1-py2.py3-none-any.whl",11774,"a0af1213f3c2226497a97e2b3aa01a7e4bee4f403f95be16fc9acd2947514a78",["py2.py3","none","any"]),
]

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def blob(data: bytes) -> str:
    return hashlib.sha1(("blob %d\0" % len(data)).encode() + data).hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()

def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def verify_record(name: str, data: bytes) -> None:
    item = SOURCES[name]
    if len(data) != item["byteLength"] or sha(data) != item["sha256"]:
        raise SystemExit("source identity mismatch: " + name)
    if name == "devin" and blob(data) != item["gitBlob"]:
        raise SystemExit("canonical Devin Git blob mismatch")

def source_url(item: dict) -> str:
    return "https://raw.githubusercontent.com/{}/{}/{}".format(item["repository"], item["upstreamCommit"], item["upstreamPath"])

def build_lock() -> bytes:
    receipts = [(QUAL / name).read_bytes() for name in ("final-qualification-1.json","final-qualification-2.json","final-qualification-fresh.json")]
    if any(sha(raw) != RECEIPT_SHA for raw in receipts) or not (receipts[0] == receipts[1] == receipts[2]):
        raise SystemExit("qualification receipt mismatch")
    if (QUAL / "runtime-reference.txt").read_text().strip() != RUNTIME:
        raise SystemExit("runtime reference mismatch")
    qualification = json.loads(receipts[0])
    lock = {
        "runtime": {
            "embeddedBasisProjectionSha256": "99ed080d4fbead189c0f7a4926f46aedd2241b29dd971f23041ab05c16ed0efe",
            "embeddedQualificationSha256": "d7740ab65ba5a9a1137877a57c93b27e0cd1c3803e723a065e72dfbfc647f174",
            "finalQualificationSha256": RECEIPT_SHA,
            "finalReference": RUNTIME,
            "qualification": qualification,
        },
        "schemaVersion": 1,
        "sources": SOURCES,
        "wheelhouse": {
            "members": [{"byteLength": size, "filename": name, "sha256": digest, "tags": tags} for name,size,digest,tags in WHEELS],
            "treeSha256": WHEEL_TREE_SHA,
        },
    }
    return canonical(lock)

def write() -> None:
    canonical_devin = (ROOT / "assets/icons/devin.svg").read_bytes()
    verify_record("devin", canonical_devin)
    atomic(ROOT / SOURCES["devin"]["destination"], canonical_devin)
    for name, item in SOURCES.items():
        if name == "devin":
            continue
        request = urllib.request.Request(source_url(item), headers={"User-Agent": "e87-task4-source-bootstrap/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(item["byteLength"] + 1)
        verify_record(name, data)
        atomic(ROOT / item["destination"], data)
    atomic(ROOT / "firmware/assets/asset-lock.json", build_lock())

def check() -> None:
    lock_path = ROOT / "firmware/assets/asset-lock.json"
    raw_lock = lock_path.read_bytes()
    if raw_lock != build_lock():
        raise SystemExit("asset lock differs from qualified canonical bytes")
    for name, item in SOURCES.items():
        data = (ROOT / item["destination"]).read_bytes()
        verify_record(name, data)
    canonical_devin = (ROOT / "assets/icons/devin.svg").read_bytes()
    compiled_devin = (ROOT / SOURCES["devin"]["destination"]).read_bytes()
    if canonical_devin != compiled_devin:
        raise SystemExit("canonical and compiled Devin differ")

def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--check", action="store_true")
    args = parser.parse_args()
    write() if args.write else check()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
