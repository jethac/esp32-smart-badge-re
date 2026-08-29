#!/usr/bin/env python3
"""Black-box tests for the fail-closed full-substrate link validator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "firmware/tools/validate-full-map.py"
PRODUCTION_EVIDENCE = REPO_ROOT / "firmware/evidence/full/link-closure.json"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def graph_digest(rows: list[str]) -> str:
    return sha256("".join(rows).encode("ascii"))


class FullMapValidatorTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="e87-full-map-")
        self.root = Path(self.temporary.name)
        self.sdk = self.root / "sdk"
        self.toolchain = self.root / "toolchain"
        self.sdk.mkdir()
        self.toolchain.mkdir()
        self.evidence_path = self.root / "evidence.json"
        self.map_path = self.root / "sdk.map"
        self.elf_path = self.root / "sdk.elf"
        self.lto_object_path = self.root / "sdk.elf.o"
        self.resolution_path = self.root / "sdk.elf.resolution.txt"
        self.object_list_path = self.root / "sdk.elf.objs.txt"
        self.link_log_path = self.root / "link.log"
        self.archive_bytes = {
            "cpu/br35/liba/cpu.a": b"synthetic CPU archive\n",
            "cpu/br35/liba/fs.a": b"synthetic filesystem archive\n",
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
            "objs/apps/watch/app_main.c.o",
            "objs/apps/watch/e87/e87_app.c.o",
            "objs/cpu/br35/setup.c.o",
        ]
        self.graph_rows = [
            "cpu/br35/liba/cpu.a(wdt_p33.c.o)\t"
            "O:objs/apps/watch/app_main.c.o\twdt_init\t1\n",
            "cpu/br35/liba/fs.a(sdfile.c.o)\t"
            "O:objs/cpu/br35/setup.c.o\tsdfile_init\t1\n",
            "TOOLCHAIN/lib/r3-large/libc.a(lib_a-memcpy.o)\t"
            "O:cpu/br35/tools/sdk.elf.o\tmemcpy\t0\n",
        ]
        self.map_bytes = self.make_map()
        self.elf_bytes = b"synthetic linked full-substrate ELF\n"
        self.lto_object_bytes = b"synthetic generated full-substrate LTO object\n"
        self.resolution_bytes = (
            b"objs/apps/common/update/update.c.o\n"
            b"-r=objs/apps/common/update/update.c.o,update_result_get,plx\n"
            b"objs/apps/watch/app_main.c.o\n"
            b"-r=objs/apps/watch/app_main.c.o,app_main,pl\n"
            b"-r=objs/apps/watch/app_main.c.o,e87_app_start,l\n"
            b"-r=objs/apps/watch/app_main.c.o,e87_app_dispatch_forever,l\n"
            b"objs/apps/watch/e87/e87_app.c.o\n"
            b"-r=objs/apps/watch/e87/e87_app.c.o,e87_app_start,pl\n"
            b"-r=objs/apps/watch/e87/e87_app.c.o,e87_app_dispatch_forever,pl\n"
            b"objs/cpu/br35/setup.c.o\n"
            b"-r=objs/cpu/br35/setup.c.o,app_main,l\n"
            b"cpu/br35/liba/cpu.a.llvm.1.wdt_p33.c\n"
            b"-r=cpu/br35/liba/cpu.a.llvm.1.wdt_p33.c,wdt_init,pl\n"
            b"cpu/br35/liba/fs.a.llvm.1.sdfile.c\n"
            b"-r=cpu/br35/liba/fs.a.llvm.1.sdfile.c,sdfile_init,pl\n"
        )
        self.object_list_bytes = (
            " " + " ".join(self.source_objects) + "\n"
        ).encode("ascii")
        self.link_log_bytes = b"+PRE-BUILD\n+LINK cpu/br35/tools/sdk.elf\n"
        self.map_path.write_bytes(self.map_bytes)
        self.elf_path.write_bytes(self.elf_bytes)
        self.lto_object_path.write_bytes(self.lto_object_bytes)
        self.resolution_path.write_bytes(self.resolution_bytes)
        self.object_list_path.write_bytes(self.object_list_bytes)
        self.link_log_path.write_bytes(self.link_log_bytes)
        self.evidence = self.make_evidence()
        self.write_evidence()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_map(self) -> bytes:
        toolchain_archive = (self.toolchain / "lib/r3-large/libc.a").as_posix()
        return (
            "Archive member included to satisfy reference by file (symbol)\n\n"
            "cpu/br35/liba/cpu.a(wdt_p33.c.o)\n"
            "  objs/apps/watch/app_main.c.o (symbol from plugin) (wdt_init)\n"
            "cpu/br35/liba/fs.a(sdfile.c.o)\n"
            "  objs/cpu/br35/setup.c.o (symbol from plugin) (sdfile_init)\n"
            f"{toolchain_archive}(lib_a-memcpy.o)\n"
            "  cpu/br35/tools/sdk.elf.o (memcpy)\n\n"
            "Discarded input sections\n"
            "                0x000000000c001234 btstack_init\n\n"
            "Memory Configuration\n\n"
            "Linker script and memory map\n"
            "                0x000000000010054c RAM_LIMIT_L = 0x10054c\n"
            "                0x0000000000137000 _RAM_LIMIT_H = 0x137000\n"
            "                0x0000000000136e00 UPDATA_BEG = 0x136e00\n"
            "                0x0000000000000000 PSRAM_SIZE = 0x0\n"
            "                0x0000000000120000 _HEAP_BEGIN = .\n"
            "                0x0000000000130e00 _HEAP_END = .\n"
            "                0x0000000000130e00 _E87_LCD_RESERVED_START = .\n"
            "                0x0000000000130e00 _E87_LCD_BUFFER_START = .\n"
            "                0x0000000000136260 _E87_LCD_BUFFER_END = .\n"
            "                0x0000000000136e00 _E87_LCD_RESERVED_END = .\n"
            "                0x000000000c001000 _initcall_begin = .\n"
            "                0x000000000c001000 _initcall_end = .\n"
            "                0x000000000c001000 _early_initcall_begin = .\n"
            "                0x000000000c001000 _early_initcall_end = .\n"
            "                0x000000000c001000 _late_initcall_begin = .\n"
            "                0x000000000c001000 _late_initcall_end = .\n"
            "                0x000000000c001000 _platform_initcall_begin = .\n"
            "                0x000000000c001000 _platform_initcall_end = .\n"
            "                0x000000000c001000 _module_initcall_begin = .\n"
            "                0x000000000c001000 _module_initcall_end = .\n"
            "                0x000000000c001000 platform_uninitcall_begin = .\n"
            "                0x000000000c001000 platform_uninitcall_end = .\n"
            "                0x000000000c000100 CODE_BEG = 0xc000100\n"
            "LOAD objs/apps/common/update/update.c.o\n"
            "LOAD cpu/br35/tools/sdk.elf.o\n"
            "LOAD objs/apps/watch/app_main.c.o\n"
            "LOAD objs/apps/watch/e87/e87_app.c.o\n"
            "LOAD objs/cpu/br35/setup.c.o\n"
            "LOAD cpu/br35/liba/cpu.a\n"
            "LOAD cpu/br35/liba/fs.a\n"
            f"LOAD {toolchain_archive}\n"
            " .update.text   0x000000000c00b838        0x4 "
            "cpu/br35/tools/sdk.elf.o\n"
            "                0x000000000c00b838 update_result_get\n"
            "OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)\n"
        ).encode("ascii")

    def make_evidence(self) -> dict[str, object]:
        return {
            "schemaVersion": 2,
            "qualificationIdentity": "FULL_RUNTIME_NORMAL_BLE",
            "qualificationState": "TEST",
            "evidenceId": "TEST-E87-FULL-RUNTIME-NORMAL-BLE-LINK-CLOSURE",
            "sdkCommit": "d0167685d032d745d88fe50233302edd46941622",
            "clangVersion": "4.0.1",
            "qualificationArtifact": {
                "sourceCommit": "0" * 40,
                "elfSha256": sha256(self.elf_bytes),
                "elfSize": len(self.elf_bytes),
                "ltoObjectSha256": sha256(self.lto_object_bytes),
                "ltoObjectSize": len(self.lto_object_bytes),
                "mapSha256": sha256(self.map_bytes),
                "mapSize": len(self.map_bytes),
                "resolutionSha256": sha256(self.resolution_bytes),
                "resolutionSize": len(self.resolution_bytes),
                "objectListSha256": sha256(self.object_list_bytes),
                "objectListSize": len(self.object_list_bytes),
                "linkLogSha256": sha256(self.link_log_bytes),
                "linkLogSize": len(self.link_log_bytes),
                "buildMode": "VENDOR_MAKE_EXPLICIT_LINK_TARGET_NO_POST",
                "postLinkStatus": "NOT_INVOKED_BY_EXPLICIT_LINK_TARGET",
            },
            "sourceObjects": self.source_objects,
            "archives": [
                {"path": path, "sha256": sha256(value), "role": "TEST"}
                for path, value in self.archive_bytes.items()
            ],
            "archiveLoadOrder": list(self.archive_bytes),
            "memory": {
                "entry": 0xC000100,
                "ramLow": 0x10054C,
                "ramTop": 0x137000,
                "updateStart": 0x136E00,
                "heapEnd": 0x130E00,
                "reservedStart": 0x130E00,
                "bufferStart": 0x130E00,
                "bufferEnd": 0x136260,
                "reservedEnd": 0x136E00,
                "reservedBytes": 0x6000,
                "bufferBytes": 0x5460,
                "slackBytes": 0xBA0,
                "minimumHeapBytes": 0x8000,
                "psramBytes": 0,
            },
            "mapContract": {
                "archiveInclusionRowCount": len(self.graph_rows),
                "archiveInclusionRowsSha256": graph_digest(self.graph_rows),
                "requiredProvenance": [
                    {
                        "archiveMember": "cpu/br35/liba/cpu.a(wdt_p33.c.o)",
                        "referrer": "O:objs/apps/watch/app_main.c.o",
                        "symbol": "wdt_init",
                    },
                    {
                        "archiveMember": "cpu/br35/liba/fs.a(sdfile.c.o)",
                        "referrer": "O:objs/cpu/br35/setup.c.o",
                        "symbol": "sdfile_init",
                    },
                ],
                "requiredResolution": [
                    {
                        "requester": "objs/cpu/br35/setup.c.o",
                        "provider": "objs/apps/watch/app_main.c.o",
                        "symbol": "app_main",
                    },
                    {
                        "requester": "objs/apps/watch/app_main.c.o",
                        "provider": "objs/apps/watch/e87/e87_app.c.o",
                        "symbol": "e87_app_start",
                    },
                    {
                        "requester": "objs/apps/watch/app_main.c.o",
                        "provider": "objs/apps/watch/e87/e87_app.c.o",
                        "symbol": "e87_app_dispatch_forever",
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
                "genericInitcalls": [],
                "immutableBootSeamArchives": ["cpu/br35/liba/fs.a"],
                "applicationFilesystemRoute": "IMMUTABLE_SETUP_ARCH_ONLY",
                "forbiddenArchives": ["cpu/br35/liba/btstack.a"],
                "forbiddenSourceObjects": [
                    "objs/apps/watch/message/adapter/btstack.c.o"
                ],
                "forbiddenSymbols": [
                    "do_initcall",
                    "btstack_init",
                    "lcd_init",
                    "rcsp_init",
                    "charge_start",
                    "update_mode_api_v2",
                ],
            },
        }

    def write_evidence(self) -> None:
        self.evidence_path.write_text(
            json.dumps(self.evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="ascii",
        )

    def run_validator(
        self, *, test_only: bool = True
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(VALIDATOR),
            "--map",
            str(self.map_path),
            "--elf",
            str(self.elf_path),
            "--lto-object",
            str(self.lto_object_path),
            "--resolution",
            str(self.resolution_path),
            "--object-list",
            str(self.object_list_path),
            "--link-log",
            str(self.link_log_path),
            "--evidence",
            str(self.evidence_path),
            "--sdk-root",
            str(self.sdk),
            "--toolchain-root",
            str(self.toolchain),
        ]
        if test_only:
            command.append("--test-only-accept-untrusted-evidence")
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_generator(self, output: Path) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable, str(VALIDATOR), "--generate-candidate",
            "--source-commit", "08981f1ae224f62d8321194965bab3cdb79ad884",
            "--output", str(output), "--map", str(self.map_path),
            "--elf", str(self.elf_path), "--lto-object", str(self.lto_object_path),
            "--resolution", str(self.resolution_path),
            "--object-list", str(self.object_list_path), "--link-log", str(self.link_log_path),
            "--evidence", str(self.evidence_path), "--sdk-root", str(self.sdk),
            "--toolchain-root", str(self.toolchain),
        ]
        return subprocess.run(command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False)

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

    def test_valid_exact_artifacts_and_archive_bytes_are_accepted(self) -> None:
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("full runtime + normal BLE link qualified", result.stdout)

    def test_candidate_generation_rejects_incomplete_normal_ble_before_emission(self) -> None:
        output = self.root / "candidate.json"
        result = self.run_generator(output)
        self.assertEqual(result.returncode, 2)
        self.assertIn("normal BLE source closure is incomplete", result.stderr)
        self.assertFalse(output.exists())

    def test_qualification_identity_mutation_is_rejected(self) -> None:
        self.evidence["qualificationIdentity"] = "FULL_RUNTIME_CLASSIC_BT"
        self.write_evidence()
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("qualificationIdentity", result.stderr)

    def test_default_mode_authenticates_evidence_before_artifacts(self) -> None:
        result = self.run_validator(test_only=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("committed production evidence", result.stderr)
        self.assertNotIn("map digest", result.stderr)

    def test_committed_legacy_pin_cannot_qualify_the_combined_runtime(self) -> None:
        self.evidence_path.write_bytes(PRODUCTION_EVIDENCE.read_bytes())
        result = self.run_validator(test_only=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("committed production evidence", result.stderr)

    def test_test_only_mode_requires_the_exact_test_evidence_id(self) -> None:
        self.evidence["evidenceId"] = "E87-FULL-RUNTIME-NORMAL-BLE-LINK-CLOSURE"
        self.write_evidence()
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("exact test or candidate evidence ID", result.stderr)

    def test_raw_map_digest_is_verified_before_semantics(self) -> None:
        self.map_path.write_bytes(self.map_path.read_bytes() + b"# drift\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("map digest", result.stderr)

    def test_every_nonmap_qualification_artifact_is_bound(self) -> None:
        for path, label in (
            (self.elf_path, "ELF"),
            (self.lto_object_path, "LTO object"),
            (self.resolution_path, "resolution"),
            (self.object_list_path, "object list"),
            (self.link_log_path, "link log"),
        ):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_bytes(original + b"drift")
                result = self.run_validator()
                self.assertEqual(result.returncode, 2)
                self.assertIn(label, result.stderr)
                path.write_bytes(original)

    def test_source_and_generated_object_loads_are_closed(self) -> None:
        self.rewrite_map(
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
            b"LOAD objs/apps/watch/ble/bt_ble.c.o\n"
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("source object", result.stderr)

    def test_generated_lto_object_is_loaded_exactly_once(self) -> None:
        self.rewrite_map(
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
            b"LOAD cpu/br35/tools/sdk.elf.o\n"
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("generated object", result.stderr)

    def test_malformed_load_record_is_rejected(self) -> None:
        self.rewrite_map(
            b"LOAD cpu/br35/tools/sdk.elf.o\n",
            b" LOAD cpu/br35/tools/sdk.elf.o\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("malformed LOAD", result.stderr)

    def test_map_boundaries_must_each_appear_exactly_once(self) -> None:
        self.rewrite_map(
            b"Discarded input sections\n",
            b"Discarded input sections\n\nDiscarded input sections\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("discarded-sections boundary", result.stderr)

    def test_archive_load_order_is_exact(self) -> None:
        self.rewrite_map(
            b"LOAD cpu/br35/liba/cpu.a\n",
            b"LOAD cpu/br35/liba/btstack.a\nLOAD cpu/br35/liba/cpu.a\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("forbidden archive", result.stderr)

    def test_archive_bytes_are_exact(self) -> None:
        (self.sdk / "cpu/br35/liba/cpu.a").write_bytes(b"drift\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("archive digest", result.stderr)

    def test_archive_inclusion_graph_and_plugin_bit_are_exact(self) -> None:
        self.rewrite_map(
            b"cpu/br35/tools/sdk.elf.o (memcpy)\n",
            b"cpu/br35/tools/sdk.elf.o (symbol from plugin) (memcpy)\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("inclusion graph", result.stderr)

    def test_required_archive_provenance_is_exact(self) -> None:
        contract = self.evidence["mapContract"]
        assert isinstance(contract, dict)
        provenance = contract["requiredProvenance"]
        assert isinstance(provenance, list) and isinstance(provenance[0], dict)
        provenance[0]["symbol"] = "profile_init"
        self.write_evidence()
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("provenance", result.stderr)

    def test_required_shell_resolution_edges_are_exact(self) -> None:
        self.rewrite_resolution(b"e87_app_start,pl\n", b"e87_app_start,l\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("resolution provider", result.stderr)

    def test_disabled_update_size_is_exact(self) -> None:
        self.rewrite_map(b"        0x4 ", b"       0x40 ")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled update", result.stderr)

    def test_disabled_update_must_be_in_the_live_map(self) -> None:
        record = (
            b" .update.text   0x000000000c00b838        0x4 "
            b"cpu/br35/tools/sdk.elf.o\n"
            b"                0x000000000c00b838 update_result_get\n"
        )
        self.rewrite_map(
            b"Discarded input sections\n",
            b"Discarded input sections\n" + record,
        )
        self.rewrite_map(record + b"OUTPUT(", b"OUTPUT(")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled update", result.stderr)

    def test_disabled_update_provider_is_exact(self) -> None:
        self.rewrite_resolution(b"update_result_get,plx\n", b"update_result_get,lx\n")
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("disabled update provider", result.stderr)

    def test_every_memory_boundary_is_exact(self) -> None:
        cases = (
            (b"0x000000000010054c RAM_LIMIT_L", b"0x0000000000100550 RAM_LIMIT_L"),
            (b"0x0000000000137000 _RAM_LIMIT_H", b"0x0000000000137100 _RAM_LIMIT_H"),
            (b"0x0000000000136e00 UPDATA_BEG", b"0x0000000000136d00 UPDATA_BEG"),
            (b"0x0000000000130e00 _E87_LCD_RESERVED_START", b"0x0000000000130e04 _E87_LCD_RESERVED_START"),
            (b"0x0000000000136260 _E87_LCD_BUFFER_END", b"0x0000000000136264 _E87_LCD_BUFFER_END"),
            (b"0x000000000c000100 CODE_BEG", b"0x000000000c000104 CODE_BEG"),
        )
        for old, new in cases:
            with self.subTest(old=old):
                original_map = self.map_bytes
                original_evidence = json.loads(json.dumps(self.evidence))
                self.rewrite_map(old, new)
                result = self.run_validator()
                self.assertEqual(result.returncode, 2)
                self.assertIn("memory", result.stderr)
                self.map_bytes = original_map
                self.map_path.write_bytes(original_map)
                self.evidence = original_evidence
                self.write_evidence()

    def test_heap_floor_is_exact(self) -> None:
        self.rewrite_map(
            b"0x0000000000120000 _HEAP_BEGIN",
            b"0x0000000000129000 _HEAP_BEGIN",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("heap", result.stderr)

    def test_psram_must_remain_absent(self) -> None:
        self.rewrite_map(
            b"0x0000000000000000 PSRAM_SIZE",
            b"0x0000000000001000 PSRAM_SIZE",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("PSRAM", result.stderr)

    def test_every_generic_initcall_range_is_empty(self) -> None:
        for symbol in (
            b"_initcall_end",
            b"_early_initcall_end",
            b"_late_initcall_end",
            b"_platform_initcall_end",
            b"_module_initcall_end",
            b"platform_uninitcall_end",
        ):
            with self.subTest(symbol=symbol):
                original_map = self.map_bytes
                original_evidence = json.loads(json.dumps(self.evidence))
                self.rewrite_map(
                    b"0x000000000c001000 " + symbol,
                    b"0x000000000c001004 " + symbol,
                )
                result = self.run_validator()
                self.assertEqual(result.returncode, 2)
                self.assertIn("initcall", result.stderr)
                self.map_bytes = original_map
                self.map_path.write_bytes(original_map)
                self.evidence = original_evidence
                self.write_evidence()

    def test_only_live_forbidden_symbols_fail(self) -> None:
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.rewrite_map(
            b"OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)\n",
            b"                0x000000000c001234 btstack_init\n"
            b"OUTPUT(cpu/br35/tools/sdk.elf elf32-pi32v2)\n",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("forbidden symbol", result.stderr)

    def test_duplicate_keys_and_nonempty_initcall_allowlist_fail(self) -> None:
        raw = self.evidence_path.read_text(encoding="ascii")
        self.evidence_path.write_text(
            raw.replace('{"archiveLoadOrder"', '{"schemaVersion":1,"archiveLoadOrder"'),
            encoding="ascii",
        )
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate", result.stderr)
        self.write_evidence()
        policy = self.evidence["policy"]
        assert isinstance(policy, dict)
        policy["genericInitcalls"] = ["do_initcall"]
        self.write_evidence()
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("generic initcall", result.stderr)

    def test_production_evidence_requires_combined_runtime_repin(self) -> None:
        self.assertTrue(PRODUCTION_EVIDENCE.is_file(), PRODUCTION_EVIDENCE)
        evidence = json.loads(PRODUCTION_EVIDENCE.read_text(encoding="ascii"))
        self.assertEqual(evidence["schemaVersion"], 2)
        self.assertEqual(evidence["qualificationIdentity"], "FULL_RUNTIME_NORMAL_BLE")
        self.assertEqual(evidence["qualificationState"], "LEGACY_PIN_REPIN_REQUIRED")
        self.assertEqual(evidence["evidenceId"], "E87-FULL-RUNTIME-NORMAL-BLE-LINK-CLOSURE")
        self.assertEqual(
            evidence["sdkCommit"],
            "d0167685d032d745d88fe50233302edd46941622",
        )
        self.assertEqual(
            evidence["qualificationArtifact"],
            {
                "sourceCommit": "fd9fb68d1818edfaee59cd55810702efd31ef5ab",
                "elfSha256": "eedc16ebe58cc94779f0f55b7b89a3da483a21c1d82787e5b17133209be59369",
                "elfSize": 621584,
                "ltoObjectSha256": "3ca10860c050ee7d48e051c0cc0a982ca47bf5caa0a8dd9981274d6de1575408",
                "ltoObjectSize": 913924,
                "mapSha256": "fb0c77d10b51736445b49fe737109e91fa3b469e8368c34912c9d0a95294e0bc",
                "mapSize": 154711,
                "resolutionSha256": "b293769275d65d68658bbbab871d17bc32a2ef1d9a3023fb9f21228dc3b06c96",
                "resolutionSize": 215051,
                "objectListSha256": "8baf0281dc3cd31d2078657a35d411b6fd3828cc936056c8a188ba8739e13f97",
                "objectListSize": 558,
                "linkLogSha256": "974af9ac8fa4253b0bc5931460af66d0a19451bb7906977b88176d73bfea551c",
                "linkLogSize": 1122,
                "buildMode": "VENDOR_MAKE_EXPLICIT_LINK_TARGET_NO_POST",
                "postLinkStatus": "NOT_INVOKED_BY_EXPLICIT_LINK_TARGET",
            },
        )
        self.assertEqual(len(evidence["sourceObjects"]), 14)
        self.assertEqual(len(evidence["archives"]), 11)
        self.assertEqual(len(evidence["archiveLoadOrder"]), 12)
        self.assertEqual(evidence["mapContract"]["archiveInclusionRowCount"], 102)
        self.assertEqual(
            evidence["mapContract"]["archiveInclusionRowsSha256"],
            "52cd79e5598589f471c4ae548cb0281b2a4bda7472f12d1bf9a4718018b6e1c9",
        )
        self.assertEqual(len(evidence["mapContract"]["requiredResolution"]), 3)


if __name__ == "__main__":
    unittest.main()
