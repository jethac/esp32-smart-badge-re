#!/usr/bin/env python3
"""Black-box tests for the fail-closed Stage 0 link-map validator."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "firmware/tools/validate-stage0-map.py"
PRODUCTION_EVIDENCE = REPO_ROOT / "firmware/evidence/stage0/link-closure.json"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def graph_digest(rows: list[str]) -> str:
    return sha256("".join(rows).encode("ascii"))


class Stage0MapValidatorTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="e87-stage0-map-")
        self.root = Path(self.temporary.name)
        self.sdk = self.root / "sdk"
        self.toolchain = self.root / "toolchain"
        self.sdk.mkdir()
        self.toolchain.mkdir()
        self.evidence_path = self.root / "evidence.json"
        self.map_path = self.root / "sdk.map"
        self.elf_path = self.root / "sdk.elf"
        self.resolution_path = self.root / "sdk.elf.resolution.txt"
        self.object_list_path = self.root / "sdk.elf.objs.txt"
        self.app_bin_path = self.root / "app.bin"
        self.archive_bytes = {
            "cpu/br35/liba/btstack.a": b"synthetic btstack archive\n",
            "toolchain/lib/r3-large/libc.a": b"synthetic toolchain libc\n",
        }
        for path, value in self.archive_bytes.items():
            owner = self.toolchain if path.startswith("toolchain/") else self.sdk
            relative = path.removeprefix("toolchain/")
            target = owner / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        self.source_objects = [
            "objs/apps/common/update/update.c.o",
            "objs/apps/watch/e87/e87_stage0_app.c.o",
        ]
        self.graph_rows = [
            "cpu/br35/liba/btstack.a(btstack_task.c.o)\t"
            "O:objs/apps/watch/e87/e87_stage0_app.c.o\tbtstack_init\t1\n",
            "cpu/br35/liba/btstack.a(btstack_main.c.o)\t"
            "A:cpu/br35/liba/btstack.a(btstack_task.c.o)\t"
            "btstack_mem_init\t1\n",
            "TOOLCHAIN/lib/r3-large/libc.a(lib_a-memcpy.o)\t"
            "A:cpu/br35/liba/btstack.a(btstack_main.c.o)\tmemcpy\t0\n",
        ]
        self.map_bytes = self.make_map()
        self.elf_bytes = b"synthetic linked stage0 ELF\n"
        self.resolution_bytes = (
            b"objs/apps/common/update/update.c.o\n"
            b"-r=objs/apps/common/update/update.c.o,update_result_get,plx\n"
            b"objs/apps/watch/e87/e87_stage0_app.c.o\n"
            b"-r=objs/apps/watch/e87/e87_stage0_app.c.o,btstack_init,l\n"
            b"cpu/br35/liba/btstack.a.llvm.1.btstack_task.c\n"
            b"-r=cpu/br35/liba/btstack.a.llvm.1.btstack_task.c,btstack_init,pl\n"
            b"-r=cpu/br35/liba/btstack.a.llvm.1.btstack_task.c,btstack_mem_init,l\n"
            b"cpu/br35/liba/btstack.a.llvm.2.btstack_main.c\n"
            b"-r=cpu/br35/liba/btstack.a.llvm.2.btstack_main.c,btstack_mem_init,pl\n"
        )
        self.object_list_bytes = (
            " " + " ".join(self.source_objects) + "\n"
        ).encode("ascii")
        self.app_bin_bytes = b"synthetic Stage0 loadable payload\n"
        self.map_path.write_bytes(self.map_bytes)
        self.elf_path.write_bytes(self.elf_bytes)
        self.resolution_path.write_bytes(self.resolution_bytes)
        self.object_list_path.write_bytes(self.object_list_bytes)
        self.app_bin_path.write_bytes(self.app_bin_bytes)
        self.evidence = self.make_evidence()
        self.write_evidence()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_map(self) -> bytes:
        toolchain_archive = (
            self.toolchain / "lib/r3-large/libc.a"
        ).as_posix()
        return (
            "Archive member included to satisfy reference by file (symbol)\n\n"
            "cpu/br35/liba/btstack.a(btstack_task.c.o)\n"
            "  objs/apps/watch/e87/e87_stage0_app.c.o "
            "(symbol from plugin) (btstack_init)\n"
            "cpu/br35/liba/btstack.a(btstack_main.c.o)\n"
            "  btstack_task.c.o (symbol from plugin) (btstack_mem_init)\n"
            f"{toolchain_archive}(lib_a-memcpy.o)\n"
            "  btstack_main.c.o (memcpy)\n\n"
            "Discarded input sections\n\n"
            "Memory Configuration\n\n"
            "Linker script and memory map\n"
            "LOAD objs/apps/common/update/update.c.o\n"
            "LOAD objs/apps/watch/e87/e87_stage0_app.c.o\n"
            "LOAD cpu/br35/tools/sdk.elf.o\n"
            "LOAD cpu/br35/liba/btstack.a\n"
            f"LOAD {toolchain_archive}\n"
            " .update.text   0x000000000c00b838        0x4 "
            "cpu/br35/tools/sdk.elf.o\n"
            "                0x000000000c00b838                "
            "update_result_get\n"
            "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)\n"
        ).encode("ascii")

    def make_evidence(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "evidenceId": "TEST-E87-S0-LINK-CLOSURE",
            "sdkCommit": "d0167685d032d745d88fe50233302edd46941622",
            "clangVersion": "4.0.1",
            "qualificationArtifact": {
                "sourceCommit": "0" * 40,
                "buildTag": "00000000",
                "elfSha256": sha256(self.elf_bytes),
                "elfSize": len(self.elf_bytes),
                "mapSha256": sha256(self.map_bytes),
                "mapSize": len(self.map_bytes),
                "resolutionSha256": sha256(self.resolution_bytes),
                "resolutionSize": len(self.resolution_bytes),
                "objectListSha256": sha256(self.object_list_bytes),
                "objectListSize": len(self.object_list_bytes),
                "appBinSha256": sha256(self.app_bin_bytes),
                "appBinSize": len(self.app_bin_bytes),
                "linkLogSha256": "1" * 64,
                "buildMode": "VENDOR_MAKE_EXPLICIT_LINK_TARGET_NO_POST",
                "postLinkStatus": "NOT_INVOKED_BY_EXPLICIT_LINK_TARGET",
            },
            "sourceObjects": self.source_objects,
            "archives": [
                {
                    "path": path,
                    "sha256": sha256(value),
                    "role": "TEST",
                }
                for path, value in self.archive_bytes.items()
            ],
            "archiveLoadOrder": list(self.archive_bytes),
            "mapContract": {
                "archiveInclusionRowCount": len(self.graph_rows),
                "archiveInclusionRowsSha256": graph_digest(self.graph_rows),
                "btstackObjectCount": 2,
                "btstackObjectsSha256": graph_digest(self.graph_rows[:2]),
                "btctrlerObjectCount": 0,
                "btctrlerObjectsSha256": graph_digest([]),
                "requiredProvenance": [
                    {
                        "archiveMember": (
                            "cpu/br35/liba/btstack.a(btstack_task.c.o)"
                        ),
                        "referrer": (
                            "O:objs/apps/watch/e87/e87_stage0_app.c.o"
                        ),
                        "symbol": "btstack_init",
                    },
                    {
                        "archiveMember": (
                            "cpu/br35/liba/btstack.a(btstack_main.c.o)"
                        ),
                        "referrer": (
                            "A:cpu/br35/liba/btstack.a(btstack_task.c.o)"
                        ),
                        "symbol": "btstack_mem_init",
                    },
                ],
                "disabledUpdate": {
                    "sourceObject": "objs/apps/common/update/update.c.o",
                    "section": ".update.text",
                    "size": 4,
                    "symbol": "update_result_get",
                },
            },
            "policy": {
                "runtimeGatedVendorObjects": (
                    "ALLOWED_ONLY_FROM_EXACT_PINNED_BTSTACK_AND_BTCTRLR_ARCHIVES"
                ),
                "immutableBootSeamArchives": [],
                "applicationFilesystemRoute": "FORBIDDEN",
                "forbiddenArchives": ["cpu/br35/liba/media.a"],
                "forbiddenSourceObjects": [
                    "objs/apps/common/config/bt_profile_config.c.o"
                ],
            },
        }

    def write_evidence(self) -> None:
        self.evidence_path.write_text(
            json.dumps(self.evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="ascii",
        )

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--map",
                str(self.map_path),
                "--elf",
                str(self.elf_path),
                "--resolution",
                str(self.resolution_path),
                "--object-list",
                str(self.object_list_path),
                "--app-bin",
                str(self.app_bin_path),
                "--evidence",
                str(self.evidence_path),
                "--sdk-root",
                str(self.sdk),
                "--toolchain-root",
                str(self.toolchain),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def rewrite_map(self, old: bytes, new: bytes) -> None:
        self.map_bytes = self.map_path.read_bytes().replace(old, new)
        self.map_path.write_bytes(self.map_bytes)
        artifact = self.evidence["qualificationArtifact"]
        assert isinstance(artifact, dict)
        artifact["mapSha256"] = sha256(self.map_bytes)
        artifact["mapSize"] = len(self.map_bytes)
        self.write_evidence()

    def rewrite_resolution(self, old: bytes, new: bytes) -> None:
        self.resolution_bytes = self.resolution_path.read_bytes().replace(old, new)
        self.resolution_path.write_bytes(self.resolution_bytes)
        artifact = self.evidence["qualificationArtifact"]
        assert isinstance(artifact, dict)
        artifact["resolutionSha256"] = sha256(self.resolution_bytes)
        artifact["resolutionSize"] = len(self.resolution_bytes)
        self.write_evidence()

    def test_valid_exact_map_and_archive_bytes_are_accepted(self) -> None:
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stage0 link map qualified", result.stdout)

    def test_plugin_bit_is_bound_in_the_canonical_extraction_graph(self) -> None:
        self.rewrite_map(
            b"btstack_main.c.o (memcpy)\n",
            b"btstack_main.c.o (symbol from plugin) (memcpy)\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("inclusion graph", result.stderr)

    def test_raw_map_digest_is_verified_before_semantics(self) -> None:
        self.map_path.write_bytes(self.map_path.read_bytes() + b"# drift\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("map digest", result.stderr)

    def test_elf_digest_and_size_are_both_verified(self) -> None:
        self.elf_path.write_bytes(self.elf_path.read_bytes() + b"drift")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ELF", result.stderr)

    def test_resolution_object_list_and_loadable_payload_are_bound(self) -> None:
        for path, label in (
            (self.resolution_path, "resolution"),
            (self.object_list_path, "object list"),
            (self.app_bin_path, "app.bin"),
        ):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"drift")
                result = self.run_validator()
                self.assertEqual(result.returncode, 2)
                self.assertIn(label, result.stderr)
                path.write_bytes(original)

    def test_source_load_set_is_exact(self) -> None:
        self.rewrite_map(
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
            b"LOAD objs/apps/watch/ble/bt_ble.c.o\n"
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("source object", result.stderr)

    def test_archive_load_order_is_exact_and_load_is_not_extraction(self) -> None:
        self.rewrite_map(
            b"LOAD cpu/br35/liba/btstack.a\n",
            b"LOAD cpu/br35/liba/media.a\n"
            b"LOAD cpu/br35/liba/btstack.a\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("forbidden archive", result.stderr)

    def test_archive_member_inclusion_digest_is_exact(self) -> None:
        self.rewrite_map(b"btstack_main.c.o", b"gatt_profile_drift.c.o")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("inclusion graph", result.stderr)

    def test_btstack_root_provenance_is_exact(self) -> None:
        contract = self.evidence["mapContract"]
        assert isinstance(contract, dict)
        provenance = contract["requiredProvenance"]
        assert isinstance(provenance, list)
        assert isinstance(provenance[0], dict)
        provenance[0]["symbol"] = "profile_init"
        self.write_evidence()
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("provenance", result.stderr)

    def test_disabled_update_exception_is_exactly_four_bytes(self) -> None:
        self.rewrite_map(b"        0x4 ", b"       0x40 ")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled update", result.stderr)

    def test_disabled_update_owner_is_exact(self) -> None:
        self.rewrite_map(
            b"0x4 cpu/br35/tools/sdk.elf.o\n",
            b"0x4 cpu/br35/tools/rogue.elf.o\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled update", result.stderr)

    def test_disabled_update_resolution_provider_is_exact(self) -> None:
        self.rewrite_resolution(b"update_result_get,plx\n", b"update_result_get,lx\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled update provider", result.stderr)

    def test_archive_bytes_are_hash_verified(self) -> None:
        (self.sdk / "cpu/br35/liba/btstack.a").write_bytes(b"drift\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("archive digest", result.stderr)

    def test_duplicate_evidence_key_is_rejected(self) -> None:
        raw = self.evidence_path.read_text(encoding="ascii")
        self.evidence_path.write_text(
            raw.replace('{"archiveLoadOrder"', '{"schemaVersion":1,"archiveLoadOrder"'),
            encoding="ascii",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate", result.stderr)

    def test_production_evidence_pins_the_linked_e2bbef2_artifact(self) -> None:
        self.assertTrue(PRODUCTION_EVIDENCE.is_file(), PRODUCTION_EVIDENCE)
        evidence = json.loads(PRODUCTION_EVIDENCE.read_text(encoding="ascii"))
        self.assertEqual(evidence["schemaVersion"], 1)
        self.assertEqual(evidence["evidenceId"], "E87-S0-LINK-CLOSURE")
        self.assertEqual(
            evidence["sdkCommit"],
            "d0167685d032d745d88fe50233302edd46941622",
        )
        self.assertEqual(
            evidence["qualificationArtifact"],
            {
                "sourceCommit": "e2bbef2daf19837652d3b566305e86f6e980950a",
                "buildTag": "E2BBEF2D",
                "elfSha256": (
                    "5bf595efe57d8f1e397a03abf5395de0503b2fd5a06cdcad93e4ff971bf78c2a"
                ),
                "elfSize": 2596828,
                "mapSha256": (
                    "85afcbb99355559694258c13e302662d0ec91cfff465fc979342b09b511d7265"
                ),
                "mapSize": 207206,
                "resolutionSha256": (
                    "7debceead388594c38473bf31053adfc7a08053b72e246ece8aac741bdcb624d"
                ),
                "resolutionSize": 1006294,
                "objectListSha256": (
                    "c27b43fcfa8809d505cefd648aa4790710f9f23d2714a0fa311482025a978af2"
                ),
                "objectListSize": 778,
                "appBinSha256": (
                    "1ccf13fc6ebeffb6e2f3a8fb131892016558d766ad607f5a321eeedd079295d8"
                ),
                "appBinSize": 181696,
                "linkLogSha256": (
                    "60ee5c7600d757c1e3545b012ad74665ec1819fb181f169ac3beee515d95f830"
                ),
                "buildMode": "VENDOR_MAKE_EXPLICIT_LINK_TARGET_NO_POST",
                "postLinkStatus": "NOT_INVOKED_BY_EXPLICIT_LINK_TARGET",
            },
        )
        contract = evidence["mapContract"]
        self.assertEqual(contract["archiveInclusionRowCount"], 303)
        self.assertEqual(
            contract["archiveInclusionRowsSha256"],
            "5d94797fcc83b031ef37ea0ffa71608ef4f584006955b2da5001e49bc38433b5",
        )
        self.assertEqual(contract["btstackObjectCount"], 52)
        self.assertEqual(contract["btctrlerObjectCount"], 135)
        self.assertEqual(len(evidence["sourceObjects"]), 19)
        self.assertEqual(len(evidence["archives"]), 16)


if __name__ == "__main__":
    unittest.main()
