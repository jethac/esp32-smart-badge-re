#!/usr/bin/env python3
"""Black-box contract tests for the canonical E87 button-evidence validator."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "firmware" / "tools" / "validate-button-evidence.py"
PYTHON = Path("/usr/bin/python3.11")
SDK_COMMIT = "d0167685d032d745d88fe50233302edd46941622"
SDK_TREE = "854734595be49510aca5afb89f5885e8bce6a00f"
EVIDENCE_PATH = "firmware/board-profiles/evidence/TEST-E87-BUTTON-V1.json"
RAW_ROOT_PATH = "firmware/board-profiles/evidence/raw"
RAW_CSV_PATH = "TEST-E87-BUTTON-V1.csv"
DRIVER_PATH = (
    "firmware/board-profiles/evidence/TEST-E87-BUTTON-V1-driver.json"
)
OVERLAY_PATH = "firmware/patches/TEST-E87-BUTTON-V1-pb08-gpadc.patch"
STATES = ["NONE", "BUTTON1", "BUTTON2", "BOTH_BUTTONS"]
TEMPERATURES = [-10, 0, 25, 45]
SUPPLIES = [3300, 3700, 4200]
CHARGERS = ["OFF", "ON"]
LOADS = ["IDLE", "BLE_CONNECTED", "DISPLAY_ACTIVE"]
UNITS = ["E87-1542-UNIT-01", "E87-1542-UNIT-02", "E87-1542-UNIT-03"]
CSV_HEADER = (
    "sampleId,unitId,temperatureC,supplyMillivolts,chargerState,loadState,"
    "physicalState,repeatOrdinal,rawAdc\n"
)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_label(label: str) -> str:
    return digest_bytes((label + "\n").encode("ascii"))


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


def nested_get(root: dict[str, object], path: tuple[str, ...]) -> object:
    value: object = root
    for key in path:
        assert isinstance(value, dict)
        value = value[key]
    return value


def nested_set(root: dict[str, object], path: tuple[str, ...], value: object) -> None:
    owner: object = root
    for key in path[:-1]:
        assert isinstance(owner, dict)
        owner = owner[key]
    assert isinstance(owner, dict)
    owner[path[-1]] = value


class ButtonEvidenceValidatorTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="e87-button-evidence-")
        self.repository = Path(self.temporary.name) / "repository"
        self.repository.mkdir()
        (self.repository / "firmware/board-profiles/evidence/raw").mkdir(
            parents=True
        )
        (self.repository / "firmware/patches").mkdir(parents=True)
        self.evidence_file = self.repository / EVIDENCE_PATH
        self.driver_file = self.repository / DRIVER_PATH
        self.raw_file = self.repository / RAW_ROOT_PATH / RAW_CSV_PATH
        self.overlay_file = self.repository / OVERLAY_PATH
        self.raw_bytes = self.make_csv()
        self.raw_file.write_bytes(self.raw_bytes)
        self.overlay_file.write_bytes(b"TEST_ONLY reviewed overlay bytes\n")
        self.reset_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def make_csv() -> bytes:
        raw_for_state = {
            "NONE": 150,
            "BUTTON1": 350,
            "BUTTON2": 550,
            "BOTH_BUTTONS": 750,
        }
        rows = [CSV_HEADER]
        sample_id = 1
        for unit, temperature, supply, charger, load, state, ordinal in itertools.product(
            UNITS,
            TEMPERATURES,
            SUPPLIES,
            CHARGERS,
            LOADS,
            STATES,
            range(1, 31),
        ):
            rows.append(
                f"{sample_id},{unit},{temperature},{supply},{charger},{load},"
                f"{state},{ordinal},{raw_for_state[state]}\n"
            )
            sample_id += 1
        return "".join(rows).encode("ascii")

    def reset_fixture(
        self,
        route: str = "DRIVER_IO2CH",
        fresh: str = "FRESH_BLOCKING_PRE_OS",
    ) -> None:
        if hasattr(self, "evidence"):
            del self.evidence
        if self.driver_file.is_symlink() or self.driver_file.is_file():
            self.driver_file.unlink()
        elif self.driver_file.exists():
            shutil.rmtree(self.driver_file)
        if not self.raw_file.exists():
            self.raw_file.parent.mkdir(parents=True, exist_ok=True)
            self.raw_file.write_bytes(self.raw_bytes)
        fresh_hook = {
            "FRESH_BLOCKING_PRE_OS": "E87_FRESH_BLOCKING_PRE_OS_V1",
            "FRESH_IRQ_TIMER": "E87_FRESH_IRQ_TIMER_GENERATION_V1",
        }[fresh]
        overlay_path = OVERLAY_PATH if route == "REVIEWED_DRIVER_OVERLAY" else ""
        overlay_sha = (
            digest_bytes(self.overlay_file.read_bytes())
            if route == "REVIEWED_DRIVER_OVERLAY"
            else ""
        )
        internal_sha = (
            digest_label("internal signal qualification")
            if route == "INTERNAL_SIGNAL_QUALIFIED"
            else ""
        )
        route_return = (
            "VOID_CALL_ISSUED_AFTER_QUALIFICATION"
            if route == "INTERNAL_SIGNAL_QUALIFIED"
            else "U32_CHANNEL_OR_UINT32_MAX"
        )
        unsupported = (
            "NOT_APPLICABLE_VOID"
            if route == "INTERNAL_SIGNAL_QUALIFIED"
            else "UINT32_MAX"
        )
        rollback = (
            "ADC_DELETE_INTERNAL_SIGNAL_REVERSE_DISABLE_FUNCTION_RESTORE_MODE"
            if route == "INTERNAL_SIGNAL_QUALIFIED"
            else "ADC_DELETE_DISABLE_FUNCTION_RESTORE_MODE"
        )
        fresh_evidence = digest_label(f"fresh {fresh}")
        self.projection: dict[str, object] = {
            "schema": "e87-button-driver-projection-v1",
            "status": "TEST_ONLY",
            "sdkCommit": SDK_COMMIT,
            "sdkTree": SDK_TREE,
            "gpioToken": "IO_PORTB_08",
            "gpioSplitToken": "IO_PORT_SPILT",
            "gpioModeToken": "PORT_INPUT_PULLUP_10K",
            "gpioFunctionToken": "PORT_FUNC_GPADC",
            "routeKind": route,
            "routeStatus": "TEST_ONLY",
            "channelToken": "AD_CH_PB8",
            "freshSampleKind": fresh,
            "freshSampleStatus": "TEST_ONLY",
            "freshSampleHook": fresh_hook,
            "freshSampleEvidenceSha256": fresh_evidence,
            "cachedSentinel": 65535,
            "overlayPath": overlay_path,
            "overlaySha256": overlay_sha,
            "internalSignalQualificationSha256": internal_sha,
            "qualification": {
                "archivePath": "cpu/br35/liba/adc.a",
                "archiveSha256": digest_label("archive"),
                "memberPath": "adc/adc_driver.o",
                "memberSha256": digest_label("member"),
                "llvmDisassemblySha256": digest_label("disassembly"),
                "routeReturnKind": route_return,
                "unsupportedRouteValueKind": unsupported,
                "cachedSentinel": 65535,
                "freshConversionKind": fresh,
                "freshConversionHook": fresh_hook,
                "freshConversionEvidenceSha256": fresh_evidence,
                "rollbackKind": rollback,
                "rollbackEvidenceSha256": digest_label("rollback"),
                "hardwareQualificationSha256": digest_label("hardware"),
            },
        }
        self.write_projection()
        self.evidence: dict[str, object] = {
            "schema": "e87-button-evidence-v1",
            "status": "TEST_ONLY",
            "profileId": "TEST-E87-BUTTON-V1",
            "physicalModel": "TEST-1542",
            "chipFamily": "AC707N/BR35/pi32v2",
            "sdk": {"commit": SDK_COMMIT, "tree": SDK_TREE},
            "capture": {
                "captureVectorId": "TEST-E87-BUTTON-CAPTURE-V1",
                "rawCsvPath": RAW_CSV_PATH,
                "rawCsvSha256": digest_bytes(self.raw_file.read_bytes()),
                "fixtureId": "TEST-FIXTURE-1",
                "fixtureToolName": "e87-fixture",
                "fixtureToolVersion": "1.0.0",
                "fixtureToolSha256": digest_label("fixture tool"),
                "unitsTested": 3,
                "unitIds": list(UNITS),
                "temperaturesC": list(TEMPERATURES),
                "supplyMillivolts": list(SUPPLIES),
                "chargerStates": list(CHARGERS),
                "loadStates": list(LOADS),
                "repeatCount": 30,
                "notes": "",
            },
            "adc": {
                "gpioToken": "IO_PORTB_08",
                "gpioSplitToken": "IO_PORT_SPILT",
                "gpioModeToken": "PORT_INPUT_PULLUP_10K",
                "gpioFunctionToken": "PORT_FUNC_GPADC",
                "routeKind": route,
                "routeStatus": "TEST_ONLY",
                "channelToken": "AD_CH_PB8",
                "adcMaximum": 1023,
                "resolutionBits": 10,
                "referenceMillivolts": 3300,
                "samplePeriodMs": 10,
                "sampleLatenessMs": 0,
                "stableSampleCount": 2,
                "minimumGuardCodes": 1,
                "freshSampleKind": fresh,
                "freshSampleStatus": "TEST_ONLY",
                "freshSampleHook": fresh_hook,
                "freshSampleEvidenceSha256": fresh_evidence,
                "cachedSentinel": 65535,
            },
            "windows": {
                "none": {"minimumInclusive": 100, "maximumInclusive": 199},
                "button1": {"minimumInclusive": 300, "maximumInclusive": 399},
                "button2": {"minimumInclusive": 500, "maximumInclusive": 599},
                "bothButtons": {
                    "minimumInclusive": 700,
                    "maximumInclusive": 799,
                },
            },
            "physicalMapping": {
                "syncPair": "BUTTON1",
                "sleep": "BUTTON2",
                "simultaneous": "AMBIGUOUS",
            },
            "pinr": {
                "status": "TEST_ONLY",
                "gpioToken": "IO_PORTB_08",
                "activeLevel": 0,
                "pullModeToken": "PORT_INPUT_PULLUP_10K",
                "pullEnableArgument": 1,
                "releaseArgument": 1,
                "holdSeconds": 16,
                "compatibleTriggerSet": ["BUTTON1"],
                "observedResetCause": "P33_PPINR_RST",
                "evidenceSha256": digest_label("pinr"),
                "commandAcceptanceRule": "VOID_CALL_ISSUED_AFTER_QUALIFICATION",
            },
            "startup": {
                "status": "TEST_ONLY",
                "resetCauseReadyHook": "E87_RESET_CAUSE_READY_AFTER_POWER_EARLY_V1",
                "timingKind": fresh,
                "freshSampleReadyHook": fresh_hook,
                "allowedPreRouteInitializers": [
                    "ADC",
                    "CLOCK",
                    "GPIO",
                    "MONOTONIC_TIMER",
                    "WDT",
                ],
                "forbiddenPreRouteInitializers": [
                    "BLE",
                    "CHARGER_MODE",
                    "FILESYSTEM",
                    "HEAP",
                    "OS_SCHEDULER",
                    "RCSP",
                    "SYSCFG",
                    "UI",
                    "UPDATE",
                ],
                "resetRecorderOwner": "e87_br35_button_record_reset_cause_early",
                "evidenceSha256": digest_label("startup"),
                "sourceIdentity": digest_label("startup source"),
            },
            "driver": {
                "status": "TEST_ONLY",
                "supportCommit": "1" * 40,
                "supportTree": "2" * 40,
                "evidencePath": DRIVER_PATH,
                "evidenceSha256": digest_bytes(self.driver_file.read_bytes()),
                "overlayPath": overlay_path,
                "overlaySha256": overlay_sha,
                "internalSignalQualificationSha256": internal_sha,
            },
            "canonicalDigestSha256": "0" * 64,
        }
        self.write_evidence()

    def write_projection(self, raw: bytes | None = None) -> None:
        self.driver_file.parent.mkdir(parents=True, exist_ok=True)
        self.driver_file.write_bytes(canonical(self.projection) if raw is None else raw)
        if hasattr(self, "evidence"):
            driver = self.evidence["driver"]
            assert isinstance(driver, dict)
            driver["evidenceSha256"] = digest_bytes(self.driver_file.read_bytes())

    def write_evidence(self, raw: bytes | None = None) -> None:
        if raw is not None:
            self.evidence_file.write_bytes(raw)
            return
        without_digest = copy.deepcopy(self.evidence)
        without_digest.pop("canonicalDigestSha256")
        self.evidence["canonicalDigestSha256"] = digest_bytes(
            canonical(without_digest)
        )
        self.evidence_file.write_bytes(canonical(self.evidence))

    def relink_projection(self) -> None:
        self.write_projection()
        self.write_evidence()

    def relink_raw(self) -> None:
        capture = self.evidence["capture"]
        assert isinstance(capture, dict)
        capture["rawCsvSha256"] = digest_bytes(self.raw_file.read_bytes())
        self.write_evidence()

    def run_validator(
        self,
        *,
        repository_root: str | None = None,
        evidence: str = EVIDENCE_PATH,
        raw_root: str = RAW_ROOT_PATH,
        profile: str = "TEST-E87-BUTTON-V1",
        status: str = "TEST_ONLY",
        print_digest: bool = True,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            str(PYTHON),
            str(VALIDATOR),
            "--repository-root",
            repository_root if repository_root is not None else str(self.repository),
            "--evidence",
            evidence,
            "--raw-root",
            raw_root,
            "--require-profile",
            profile,
            "--require-status",
            status,
        ]
        if print_digest:
            command.append("--print-digest")
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_rejected(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(2, result.returncode, (result.stdout, result.stderr))
        self.assertEqual("", result.stdout)

    def test_valid_canonical_minimum_vectors_all_routes_and_freshness(self) -> None:
        for route, fresh in itertools.product(
            [
                "DRIVER_IO2CH",
                "REVIEWED_DRIVER_OVERLAY",
                "INTERNAL_SIGNAL_QUALIFIED",
            ],
            ["FRESH_BLOCKING_PRE_OS", "FRESH_IRQ_TIMER"],
        ):
            with self.subTest(route=route, fresh=fresh):
                self.reset_fixture(route, fresh)
                first = self.run_validator()
                second = self.run_validator()
                expected = self.evidence["canonicalDigestSha256"] + "\n"
                self.assertEqual(0, first.returncode, first.stderr)
                self.assertEqual(expected, first.stdout)
                self.assertEqual(first.stdout, second.stdout)
                self.assertEqual(b"{", self.evidence_file.read_bytes()[:1])
                adc = self.evidence["adc"]
                windows = self.evidence["windows"]
                assert isinstance(adc, dict) and isinstance(windows, dict)
                self.assertEqual(1023, adc["adcMaximum"])
                self.assertEqual(2, adc["stableSampleCount"])
                ordered = sorted(
                    (
                        value["minimumInclusive"],
                        value["maximumInclusive"],
                    )
                    for value in windows.values()
                    if isinstance(value, dict)
                )
                self.assertTrue(
                    all(
                        right[0] - left[1] - 1 >= adc["minimumGuardCodes"]
                        for left, right in zip(ordered, ordered[1:])
                    )
                )

    def test_every_root_and_nested_object_rejects_missing_or_unknown_key(self) -> None:
        object_paths = [
            (),
            ("sdk",),
            ("capture",),
            ("adc",),
            ("windows",),
            ("windows", "none"),
            ("physicalMapping",),
            ("pinr",),
            ("startup",),
            ("driver",),
        ]
        for object_path in object_paths:
            self.reset_fixture()
            owner = nested_get(self.evidence, object_path) if object_path else self.evidence
            assert isinstance(owner, dict)
            for key in list(owner):
                with self.subTest(path=object_path, missing=key):
                    self.reset_fixture()
                    target = (
                        nested_get(self.evidence, object_path)
                        if object_path
                        else self.evidence
                    )
                    assert isinstance(target, dict)
                    del target[key]
                    if object_path == () and key == "canonicalDigestSha256":
                        self.evidence_file.write_bytes(canonical(self.evidence))
                    else:
                        self.write_evidence()
                    self.assert_rejected(self.run_validator())
            with self.subTest(path=object_path, unknown=True):
                self.reset_fixture()
                target = (
                    nested_get(self.evidence, object_path)
                    if object_path
                    else self.evidence
                )
                assert isinstance(target, dict)
                target["unexpectedField"] = "unexpected"
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_projection_and_qualification_exact_keys(self) -> None:
        for object_path in [(), ("qualification",)]:
            self.reset_fixture()
            owner = (
                nested_get(self.projection, object_path)
                if object_path
                else self.projection
            )
            assert isinstance(owner, dict)
            for key in list(owner):
                with self.subTest(path=object_path, missing=key):
                    self.reset_fixture()
                    target = (
                        nested_get(self.projection, object_path)
                        if object_path
                        else self.projection
                    )
                    assert isinstance(target, dict)
                    del target[key]
                    self.relink_projection()
                    self.assert_rejected(self.run_validator())
            with self.subTest(path=object_path, unknown=True):
                self.reset_fixture()
                target = (
                    nested_get(self.projection, object_path)
                    if object_path
                    else self.projection
                )
                assert isinstance(target, dict)
                target["unexpectedField"] = "unexpected"
                self.relink_projection()
                self.assert_rejected(self.run_validator())

    def test_duplicate_keys_fail_in_root_projection_and_qualification(self) -> None:
        root_raw = self.evidence_file.read_bytes()
        duplicate_root = b'{"schema":"e87-button-evidence-v1",' + root_raw[1:]
        self.write_evidence(duplicate_root)
        self.assert_rejected(self.run_validator())

        self.reset_fixture()
        projection_raw = self.driver_file.read_bytes()
        duplicate_projection = (
            b'{"schema":"e87-button-driver-projection-v1",' + projection_raw[1:]
        )
        self.write_projection(duplicate_projection)
        self.write_evidence()
        self.assert_rejected(self.run_validator())

        self.reset_fixture()
        projection_text = self.driver_file.read_text("ascii")
        marker = '"qualification":{'
        duplicate_qualification = projection_text.replace(
            marker, marker + '"archivePath":"cpu/br35/liba/adc.a",', 1
        ).encode("ascii")
        self.write_projection(duplicate_qualification)
        self.write_evidence()
        self.assert_rejected(self.run_validator())

    def test_noncanonical_json_forms_and_digest_fail_closed(self) -> None:
        canonical_root = self.evidence_file.read_bytes()
        insertion_order_root = (
            json.dumps(self.evidence, ensure_ascii=True, separators=(",", ":"))
            + "\n"
        ).encode("ascii")
        variants = [
            canonical_root[:-1],
            canonical_root + b"\n",
            canonical_root.replace(b":", b": ", 1),
            insertion_order_root,
            canonical_root.replace(b"\n", b"\r\n"),
        ]
        for index, raw in enumerate(variants):
            with self.subTest(root_variant=index):
                self.reset_fixture()
                self.write_evidence(raw)
                self.assert_rejected(self.run_validator())
        self.reset_fixture()
        self.evidence["canonicalDigestSha256"] = "f" * 64
        self.evidence_file.write_bytes(canonical(self.evidence))
        self.assert_rejected(self.run_validator())

        insertion_order_projection = (
            json.dumps(self.projection, ensure_ascii=True, separators=(",", ":"))
            + "\n"
        ).encode("ascii")
        for index, raw in enumerate(
            [
                self.driver_file.read_bytes()[:-1],
                self.driver_file.read_bytes() + b"\n",
                self.driver_file.read_bytes().replace(b":", b": ", 1),
                insertion_order_projection,
                self.driver_file.read_bytes().replace(b"\n", b"\r\n"),
            ]
        ):
            with self.subTest(projection_variant=index):
                self.reset_fixture()
                self.write_projection(raw)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_every_root_nested_projection_and_qualification_field_rejects_wrong_type(self) -> None:
        root_object_paths = [
            (),
            ("sdk",),
            ("capture",),
            ("adc",),
            ("windows",),
            ("windows", "none"),
            ("windows", "button1"),
            ("windows", "button2"),
            ("windows", "bothButtons"),
            ("physicalMapping",),
            ("pinr",),
            ("startup",),
            ("driver",),
        ]

        def wrong_type(value: object) -> object:
            if type(value) is int:
                return True
            if isinstance(value, str):
                return []
            if isinstance(value, list):
                return {}
            if isinstance(value, dict):
                return []
            return None

        for object_path in root_object_paths:
            self.reset_fixture()
            owner = nested_get(self.evidence, object_path) if object_path else self.evidence
            assert isinstance(owner, dict)
            for key in list(owner):
                with self.subTest(domain="root", path=object_path, key=key):
                    self.reset_fixture()
                    target = (
                        nested_get(self.evidence, object_path)
                        if object_path
                        else self.evidence
                    )
                    assert isinstance(target, dict)
                    target[key] = wrong_type(target[key])
                    if object_path == () and key == "canonicalDigestSha256":
                        self.evidence_file.write_bytes(canonical(self.evidence))
                    else:
                        self.write_evidence()
                    self.assert_rejected(self.run_validator())

        for object_path in [(), ("qualification",)]:
            self.reset_fixture()
            owner = (
                nested_get(self.projection, object_path)
                if object_path
                else self.projection
            )
            assert isinstance(owner, dict)
            for key in list(owner):
                with self.subTest(domain="projection", path=object_path, key=key):
                    self.reset_fixture()
                    target = (
                        nested_get(self.projection, object_path)
                        if object_path
                        else self.projection
                    )
                    assert isinstance(target, dict)
                    target[key] = wrong_type(target[key])
                    self.relink_projection()
                    self.assert_rejected(self.run_validator())

    def test_scalar_type_float_boolean_nonascii_and_exact_identity_mutations(self) -> None:
        mutations = [
            (("physicalModel",), "1552"),
            (("physicalModel",), 1542),
            (("chipFamily",), "BR35"),
            (("profileId",), "TEST-É87"),
            (("adc", "adcMaximum"), True),
            (("adc", "referenceMillivolts"), 3300.0),
            (("capture", "unitsTested"), False),
            (("pinr", "activeLevel"), True),
            (("sdk", "commit"), SDK_COMMIT.upper()),
            (("sdk", "tree"), "0" * 39),
            (("schema",), "e87-button-evidence-v2"),
            (("status",), "CONFIRMED"),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.reset_fixture()
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_capture_vectors_ranges_identifiers_and_orders_are_exact(self) -> None:
        mutations = [
            (("capture", "unitsTested"), 2),
            (("capture", "unitsTested"), 33),
            (("capture", "repeatCount"), 29),
            (("capture", "repeatCount"), 65536),
            (("capture", "temperaturesC"), [-10, 0, 25, 44]),
            (("capture", "temperaturesC"), [0, -10, 25, 45]),
            (("capture", "temperaturesC"), [-10, False, 25, 45]),
            (("capture", "supplyMillivolts"), [3300, 4200, 3700]),
            (("capture", "supplyMillivolts"), [3300.0, 3700, 4200]),
            (("capture", "chargerStates"), ["ON", "OFF"]),
            (("capture", "loadStates"), ["IDLE", "DISPLAY_ACTIVE", "BLE_CONNECTED"]),
            (("capture", "unitIds"), [UNITS[0], UNITS[0], UNITS[2]]),
            (("capture", "unitIds"), [UNITS[1], UNITS[0], UNITS[2]]),
            (("capture", "fixtureId"), ""),
            (("capture", "fixtureToolName"), "bad tool"),
            (("capture", "fixtureToolVersion"), "x" * 65),
            (("capture", "fixtureToolSha256"), "A" * 64),
            (("capture", "notes"), "\n"),
            (("capture", "notes"), "x" * 513),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.reset_fixture()
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_adc_numeric_minima_adjacent_values_enums_and_fixed_tokens(self) -> None:
        mutations = [
            (("adc", "gpioToken"), "IO_PORTB_07"),
            (("adc", "gpioSplitToken"), "IO_PORT_SPLIT"),
            (("adc", "gpioModeToken"), "PORT_OUTPUT_LOW"),
            (("adc", "gpioFunctionToken"), "PORT_FUNC_UART"),
            (("adc", "routeKind"), "CACHED_ONLY"),
            (("adc", "routeStatus"), "UNCONFIRMED"),
            (("adc", "channelToken"), "bad-channel"),
            (("adc", "resolutionBits"), 7),
            (("adc", "resolutionBits"), 16),
            (("adc", "adcMaximum"), 1022),
            (("adc", "referenceMillivolts"), 999),
            (("adc", "referenceMillivolts"), 5001),
            (("adc", "samplePeriodMs"), 9),
            (("adc", "samplePeriodMs"), 11),
            (("adc", "samplePeriodMs"), 1010),
            (("adc", "sampleLatenessMs"), -1),
            (("adc", "sampleLatenessMs"), 11),
            (("adc", "stableSampleCount"), 1),
            (("adc", "stableSampleCount"), 17),
            (("adc", "minimumGuardCodes"), 0),
            (("adc", "minimumGuardCodes"), 1025),
            (("adc", "freshSampleKind"), "CACHED_ONLY"),
            (("adc", "freshSampleStatus"), "UNCONFIRMED"),
            (("adc", "freshSampleHook"), "adc_get_value"),
            (("adc", "freshSampleEvidenceSha256"), "a" * 63),
            (("adc", "cachedSentinel"), 65534),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.reset_fixture()
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_window_inversion_overlap_touch_gap_outer_and_missing_both_fail(self) -> None:
        mutations = [
            (("windows", "none", "minimumInclusive"), 200),
            (("windows", "button1", "minimumInclusive"), 199),
            (("windows", "button1", "minimumInclusive"), 200),
            (("adc", "minimumGuardCodes"), 101),
            (("windows", "bothButtons", "maximumInclusive"), 1024),
            (("windows", "bothButtons", "maximumInclusive"), -1),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.reset_fixture()
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())
        self.reset_fixture()
        windows = self.evidence["windows"]
        assert isinstance(windows, dict)
        del windows["bothButtons"]
        self.write_evidence()
        self.assert_rejected(self.run_validator())

    def test_exact_one_code_deliberate_gap_is_valid(self) -> None:
        windows = self.evidence["windows"]
        assert isinstance(windows, dict)
        button1 = windows["button1"]
        assert isinstance(button1, dict)
        button1["minimumInclusive"] = 201
        self.write_evidence()
        result = self.run_validator()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_physical_mapping_pinr_startup_and_controller_vectors_are_pinned(self) -> None:
        mutations = [
            (("physicalMapping", "syncPair"), "BUTTON2"),
            (("physicalMapping", "sleep"), "BUTTON1"),
            (("physicalMapping", "simultaneous"), "CHORD"),
            (("pinr", "status"), "UNCONFIRMED"),
            (("pinr", "gpioToken"), "IO_PORTB_07"),
            (("pinr", "activeLevel"), 2),
            (("pinr", "pullModeToken"), "PORT_OUTPUT_LOW"),
            (("pinr", "pullEnableArgument"), -1),
            (("pinr", "pullEnableArgument"), 256),
            (("pinr", "releaseArgument"), 2),
            (("pinr", "holdSeconds"), 15),
            (("pinr", "compatibleTriggerSet"), []),
            (("pinr", "compatibleTriggerSet"), ["BUTTON2"]),
            (("pinr", "compatibleTriggerSet"), ["BUTTON1", "BUTTON1"]),
            (("pinr", "compatibleTriggerSet"), ["BUTTON2", "BUTTON1"]),
            (("pinr", "compatibleTriggerSet"), ["NONE", "BUTTON1"]),
            (("pinr", "observedResetCause"), "POWER_ON_RESET"),
            (("pinr", "commandAcceptanceRule"), "RETURN_ZERO"),
            (("startup", "status"), "UNCONFIRMED"),
            (("startup", "resetCauseReadyHook"), "boot_power_init"),
            (("startup", "timingKind"), "FRESH_IRQ_TIMER"),
            (("startup", "freshSampleReadyHook"), "adc_get_value"),
            (("startup", "allowedPreRouteInitializers"), ["ADC", "GPIO"]),
            (("startup", "forbiddenPreRouteInitializers"), ["UI"]),
            (("startup", "resetRecorderOwner"), "power_early_flowing"),
            (("startup", "evidenceSha256"), "b" * 65),
            (("startup", "sourceIdentity"), "B" * 64),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                self.reset_fixture()
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_driver_root_route_specific_fields_and_types_fail_closed(self) -> None:
        mutations = [
            (("driver", "status"), "CONFIRMED"),
            (("driver", "supportCommit"), "a" * 39),
            (("driver", "supportTree"), "A" * 40),
            (("driver", "evidenceSha256"), "0" * 64),
        ]
        for path, value in mutations:
            with self.subTest(path=path):
                self.reset_fixture()
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

        for route, path, value in [
            ("DRIVER_IO2CH", "overlayPath", OVERLAY_PATH),
            ("DRIVER_IO2CH", "internalSignalQualificationSha256", digest_label("x")),
            ("REVIEWED_DRIVER_OVERLAY", "overlayPath", ""),
            ("REVIEWED_DRIVER_OVERLAY", "overlaySha256", ""),
            ("REVIEWED_DRIVER_OVERLAY", "internalSignalQualificationSha256", digest_label("x")),
            ("INTERNAL_SIGNAL_QUALIFIED", "overlayPath", OVERLAY_PATH),
            ("INTERNAL_SIGNAL_QUALIFIED", "internalSignalQualificationSha256", ""),
        ]:
            with self.subTest(route=route, path=path):
                self.reset_fixture(route)
                driver = self.evidence["driver"]
                assert isinstance(driver, dict)
                driver[path] = value
                self.projection[path] = value
                if path == "overlayPath" and value:
                    overlay_sha = digest_bytes(self.overlay_file.read_bytes())
                    driver["overlaySha256"] = overlay_sha
                    self.projection["overlaySha256"] = overlay_sha
                self.relink_projection()
                self.assert_rejected(self.run_validator())

    def test_projection_semantic_cross_links_reject_after_all_digests_are_fresh(self) -> None:
        mutations = [
            ("sdkCommit", "3" * 40),
            ("sdkTree", "4" * 40),
            ("gpioToken", "IO_PORTB_07"),
            ("gpioSplitToken", "IO_PORT_SPLIT"),
            ("gpioModeToken", "PORT_INPUT_PULLDOWN_10K"),
            ("gpioFunctionToken", "PORT_FUNC_UART"),
            ("routeKind", "REVIEWED_DRIVER_OVERLAY"),
            ("routeStatus", "CONFIRMED"),
            ("channelToken", "AD_CH_OTHER"),
            ("freshSampleKind", "FRESH_IRQ_TIMER"),
            ("freshSampleStatus", "CONFIRMED"),
            ("freshSampleHook", "E87_FRESH_IRQ_TIMER_GENERATION_V1"),
            ("freshSampleEvidenceSha256", digest_label("other fresh")),
            ("cachedSentinel", 65534),
            ("overlayPath", OVERLAY_PATH),
            ("overlaySha256", digest_label("other overlay")),
            ("internalSignalQualificationSha256", digest_label("internal")),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                self.reset_fixture()
                self.projection[key] = value
                self.relink_projection()
                self.assert_rejected(self.run_validator())

    def test_projection_schema_status_namespace_canonicality_hash_and_paths(self) -> None:
        for key, value in [
            ("schema", "e87-button-driver-projection-v2"),
            ("status", "CONFIRMED"),
            ("cachedSentinel", True),
            ("cachedSentinel", 65535.0),
            ("channelToken", "Å"),
        ]:
            with self.subTest(key=key, value=value):
                self.reset_fixture()
                self.projection[key] = value
                self.relink_projection()
                self.assert_rejected(self.run_validator())

        self.reset_fixture()
        self.driver_file.write_bytes(self.driver_file.read_bytes() + b"x")
        self.assert_rejected(self.run_validator())

        for bad_path in [
            "firmware/board-profiles/evidence/E87-JD9855-R1-pb08-driver-v1.json",
            "../driver.json",
            "/tmp/driver.json",
            "C:/driver.json",
            "firmware\\driver.json",
            "firmware/./driver.json",
            "firmware//driver.json",
        ]:
            with self.subTest(path=bad_path):
                self.reset_fixture()
                driver = self.evidence["driver"]
                assert isinstance(driver, dict)
                driver["evidencePath"] = bad_path
                self.write_evidence()
                self.assert_rejected(self.run_validator())

    def test_qualification_types_identifiers_and_digest_shapes(self) -> None:
        bad_identifiers = [
            "",
            "/absolute/archive.a",
            "C:/archive.a",
            "\\\\server\\archive.a",
            "cpu\\archive.a",
            "cpu/./archive.a",
            "cpu/../archive.a",
            "cpu//archive.a",
            "cpu/archive?.a",
            "x" * 257,
        ]
        for key in ["archivePath", "memberPath"]:
            for value in bad_identifiers:
                with self.subTest(key=key, value=value):
                    self.reset_fixture()
                    qualification = self.projection["qualification"]
                    assert isinstance(qualification, dict)
                    qualification[key] = value
                    self.relink_projection()
                    self.assert_rejected(self.run_validator())

        digest_keys = [
            "archiveSha256",
            "memberSha256",
            "llvmDisassemblySha256",
            "freshConversionEvidenceSha256",
            "rollbackEvidenceSha256",
            "hardwareQualificationSha256",
        ]
        for key, value in itertools.product(
            digest_keys, ["", "a" * 63, "a" * 65, "A" * 64, 7, True]
        ):
            with self.subTest(key=key, value=value):
                self.reset_fixture()
                qualification = self.projection["qualification"]
                assert isinstance(qualification, dict)
                qualification[key] = value
                self.relink_projection()
                self.assert_rejected(self.run_validator())

        for key, value in [
            ("archivePath", 7),
            ("memberPath", True),
            ("routeReturnKind", 7),
            ("unsupportedRouteValueKind", False),
            ("cachedSentinel", True),
            ("cachedSentinel", 65535.0),
            ("freshConversionKind", 7),
            ("freshConversionHook", False),
            ("rollbackKind", 7),
        ]:
            with self.subTest(key=key, value=value):
                self.reset_fixture()
                qualification = self.projection["qualification"]
                assert isinstance(qualification, dict)
                qualification[key] = value
                self.relink_projection()
                self.assert_rejected(self.run_validator())

    def test_qualification_route_selected_enums_for_every_wrong_route(self) -> None:
        route_expectations = {
            "DRIVER_IO2CH": (
                "U32_CHANNEL_OR_UINT32_MAX",
                "UINT32_MAX",
                "ADC_DELETE_DISABLE_FUNCTION_RESTORE_MODE",
            ),
            "REVIEWED_DRIVER_OVERLAY": (
                "U32_CHANNEL_OR_UINT32_MAX",
                "UINT32_MAX",
                "ADC_DELETE_DISABLE_FUNCTION_RESTORE_MODE",
            ),
            "INTERNAL_SIGNAL_QUALIFIED": (
                "VOID_CALL_ISSUED_AFTER_QUALIFICATION",
                "NOT_APPLICABLE_VOID",
                "ADC_DELETE_INTERNAL_SIGNAL_REVERSE_DISABLE_FUNCTION_RESTORE_MODE",
            ),
        }
        all_values = list(route_expectations.values())
        keys = ["routeReturnKind", "unsupportedRouteValueKind", "rollbackKind"]
        for route, expected in route_expectations.items():
            for index, key in enumerate(keys):
                wrong_values = {values[index] for values in all_values} - {expected[index]}
                wrong_values.add("WRONG_ENUM")
                for value in wrong_values:
                    with self.subTest(route=route, key=key, value=value):
                        self.reset_fixture(route)
                        qualification = self.projection["qualification"]
                        assert isinstance(qualification, dict)
                        qualification[key] = value
                        self.relink_projection()
                        self.assert_rejected(self.run_validator())

    def test_qualification_cross_links_are_semantic_not_stale_hash_failures(self) -> None:
        mutations = [
            ("cachedSentinel", 65534),
            ("freshConversionKind", "FRESH_IRQ_TIMER"),
            ("freshConversionHook", "E87_FRESH_IRQ_TIMER_GENERATION_V1"),
            ("freshConversionEvidenceSha256", digest_label("different fresh")),
        ]
        for key, value in mutations:
            with self.subTest(key=key):
                self.reset_fixture()
                qualification = self.projection["qualification"]
                assert isinstance(qualification, dict)
                qualification[key] = value
                self.relink_projection()
                self.assert_rejected(self.run_validator())
        self.reset_fixture()
        self.assert_rejected(self.run_validator(status="CONFIRMED"))

    def test_csv_exact_cartesian_header_order_domains_and_hash(self) -> None:
        lines = self.raw_bytes.splitlines(keepends=True)
        variants = [
            b"wrong," + self.raw_bytes,
            self.raw_bytes.replace(b"\n", b"\r\n", 1),
            self.raw_bytes + b"\n",
            self.raw_bytes.replace(b",150\n", b",\"150\"\n", 1),
            self.raw_bytes.replace(b",150\n", b", 150\n", 1),
            self.raw_bytes.replace(b",1,150\n", b",01,150\n", 1),
            b"".join([lines[0], lines[2], lines[1], *lines[3:]]),
            b"".join([lines[0], *lines[2:]]),
            self.raw_bytes.replace(b",BOTH_BUTTONS,1,750\n", b",BUTTON2,1,750\n", 1),
            self.raw_bytes.replace(b",NONE,1,150\n", b",NONE,1,350\n", 1),
            self.raw_bytes.replace(b"1,E87-", b"2,E87-", 1),
            self.raw_bytes.replace(b",150\n", b",65535\n", 1),
            self.raw_bytes.replace(b",150\n", b",1024\n", 1),
        ]
        for index, raw in enumerate(variants):
            with self.subTest(variant=index):
                self.reset_fixture()
                self.raw_file.write_bytes(raw)
                self.relink_raw()
                self.assert_rejected(self.run_validator())

        self.reset_fixture()
        self.raw_file.write_bytes(self.raw_bytes + b"x")
        self.assert_rejected(self.run_validator())

    def test_repository_and_cli_path_namespaces_reject_noncanonical_inputs(self) -> None:
        bad_cli = [
            {"repository_root": "repository", "cwd": self.repository.parent},
            {"repository_root": str(self.repository / ".." / "repository")},
            {"evidence": "TEST-E87-BUTTON-V1.json"},
            {"evidence": "firmware/board-profiles/evidence/E87-JD9855-R1-pb08-v1.json"},
            {"raw_root": "raw"},
            {"evidence": "/tmp/evidence.json"},
            {"evidence": "C:/evidence.json"},
            {"evidence": "firmware\\evidence.json"},
            {"evidence": "firmware/./evidence.json"},
            {"evidence": "firmware/../evidence.json"},
            {"evidence": "firmware//evidence.json"},
            {"raw_root": "/tmp/raw"},
            {"raw_root": "C:/raw"},
            {"raw_root": "firmware\\raw"},
            {"raw_root": "firmware/./raw"},
            {"raw_root": "firmware/../raw"},
            {"raw_root": "firmware//raw"},
            {"profile": "E87-JD9855-R1"},
            {"status": "TEST_ONLY_OR_CONFIRMED"},
        ]
        for kwargs in bad_cli:
            with self.subTest(kwargs=kwargs):
                self.assert_rejected(self.run_validator(**kwargs))

        alias = self.repository.parent / "repository-alias"
        alias.symlink_to(self.repository, target_is_directory=True)
        self.assert_rejected(self.run_validator(repository_root=str(alias)))

    def test_json_paths_reject_bad_spelling_type_missing_nonregular_and_symlink(self) -> None:
        for path, value in [
            (("capture", "rawCsvPath"), "../raw.csv"),
            (("capture", "rawCsvPath"), "/tmp/raw.csv"),
            (("capture", "rawCsvPath"), "C:/raw.csv"),
            (("capture", "rawCsvPath"), "sub\\raw.csv"),
            (("capture", "rawCsvPath"), "sub/./raw.csv"),
            (("capture", "rawCsvPath"), "sub//raw.csv"),
            (("driver", "overlayPath"), "../overlay.patch"),
        ]:
            with self.subTest(path=path, value=value):
                self.reset_fixture("REVIEWED_DRIVER_OVERLAY")
                nested_set(self.evidence, path, value)
                self.write_evidence()
                self.assert_rejected(self.run_validator())

        self.reset_fixture()
        self.raw_file.unlink()
        self.assert_rejected(self.run_validator())

        self.reset_fixture()
        self.driver_file.unlink()
        self.driver_file.mkdir()
        self.assert_rejected(self.run_validator())

        self.reset_fixture("REVIEWED_DRIVER_OVERLAY")
        self.overlay_file.unlink()
        self.overlay_file.mkdir()
        self.assert_rejected(self.run_validator())

        self.reset_fixture()
        outside = self.repository.parent / "outside.csv"
        outside.write_bytes(self.raw_bytes)
        self.raw_file.unlink()
        self.raw_file.symlink_to(outside)
        self.assert_rejected(self.run_validator())

        self.raw_file.unlink()
        self.raw_file.write_bytes(self.raw_bytes)
        self.reset_fixture()
        outside_driver = self.repository.parent / "outside-driver.json"
        outside_driver.write_bytes(self.driver_file.read_bytes())
        self.driver_file.unlink()
        self.driver_file.symlink_to(outside_driver)
        driver = self.evidence["driver"]
        assert isinstance(driver, dict)
        driver["evidenceSha256"] = digest_bytes(outside_driver.read_bytes())
        self.write_evidence()
        self.assert_rejected(self.run_validator())

    def test_wrong_namespace_paths_never_fall_back_to_cwd(self) -> None:
        cwd = self.repository.parent / "attacker-cwd"
        cwd.mkdir()
        (cwd / RAW_CSV_PATH).write_bytes(self.raw_bytes)
        (cwd / "driver.json").write_bytes(self.driver_file.read_bytes())
        self.assert_rejected(
            self.run_validator(
                evidence=RAW_CSV_PATH,
                raw_root=".",
                cwd=cwd,
            )
        )


if __name__ == "__main__":
    unittest.main()
