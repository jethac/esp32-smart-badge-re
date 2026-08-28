#!/usr/bin/env python3
"""Validate fail-closed canonical E87 button qualification evidence."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any


SDK_COMMIT = "d0167685d032d745d88fe50233302edd46941622"
SDK_TREE = "854734595be49510aca5afb89f5885e8bce6a00f"
CHIP_FAMILY = "AC707N/BR35/pi32v2"
RAW_ROOT = "firmware/board-profiles/evidence/raw"
PB07_GPIO_TOKEN = "IO_PORTB_07"
PB07_GPIO_MODE_TOKEN = "PORT_INPUT_PULLUP_100K"
PB07_PINR_PULL_MODE_ARGUMENT = 0x12
PB07_ROUTE_KIND = "DRIVER_IO2CH"
PB07_CHANNEL_TOKEN = "AD_CH_PMU_PADC0"
PB07_CHANNEL_VALUE = 0x0002030D
PB07_CHANNEL_ACCEPTANCE_RULE = "EXACT_U32_EQUALITY"
STATUS_IDENTITIES = {
    "TEST_ONLY": {
        "profile": "TEST-E87-BUTTON-V1",
        "model": "TEST-1542",
        "evidence": "firmware/board-profiles/evidence/TEST-E87-BUTTON-V1.json",
        "raw": "TEST-E87-BUTTON-V1.csv",
        "driver": (
            "firmware/board-profiles/evidence/"
            "TEST-E87-BUTTON-V1-driver.json"
        ),
        "overlay": "firmware/patches/TEST-E87-BUTTON-V1-pb07-gpadc.patch",
    },
    "CONFIRMED": {
        "profile": "E87-JD9855-R1",
        "model": "1542",
        "evidence": (
            "firmware/board-profiles/evidence/"
            "E87-JD9855-R1-pb07-v1.json"
        ),
        "raw": "E87-JD9855-R1-pb07-v1.csv",
        "driver": (
            "firmware/board-profiles/evidence/"
            "E87-JD9855-R1-pb07-driver-v1.json"
        ),
        "overlay": "firmware/patches/0002-e87-pb07-gpadc.patch",
    },
}
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
UNIT_RE = re.compile(r"^E87-1542-UNIT-[0-9]{2}$")
POSIX_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._/-]{1,256}$")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
FRESH_KINDS = {
    "FRESH_BLOCKING_PRE_OS": "E87_FRESH_BLOCKING_PRE_OS_V1",
    "FRESH_IRQ_TIMER": "E87_FRESH_IRQ_TIMER_GENERATION_V1",
}
TEMPERATURES = [-10, 0, 25, 45]
SUPPLIES = [3300, 3700, 4200]
CHARGERS = ["OFF", "ON"]
LOADS = ["IDLE", "BLE_CONNECTED", "DISPLAY_ACTIVE"]
STATES = ["NONE", "BUTTON1", "BUTTON2", "BOTH_BUTTONS"]
ALLOWED_INITIALIZERS = ["ADC", "CLOCK", "GPIO", "MONOTONIC_TIMER", "WDT"]
FORBIDDEN_INITIALIZERS = [
    "BLE",
    "CHARGER_MODE",
    "FILESYSTEM",
    "HEAP",
    "OS_SCHEDULER",
    "RCSP",
    "SYSCFG",
    "UI",
    "UPDATE",
]
CSV_HEADER = (
    "sampleId,unitId,temperatureC,supplyMillivolts,chargerState,loadState,"
    "physicalState,repeatOrdinal,rawAdc"
)


class ValidationError(Exception):
    """The evidence did not satisfy the closed contract."""


class DuplicateKey(ValidationError):
    """A JSON object repeated a key."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValidationError(f"non-finite JSON number: {value}")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValidationError(f"value cannot be canonicalized: {error}") from error
    return (text + "\n").encode("ascii")


def ensure_ascii_tree(value: object, label: str) -> None:
    if isinstance(value, str):
        if not value.isascii():
            raise ValidationError(f"{label}: non-ASCII string")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            ensure_ascii_tree(item, f"{label}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii():
                raise ValidationError(f"{label}: non-ASCII object key")
            ensure_ascii_tree(item, f"{label}.{key}")


def decode_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except DuplicateKey:
        raise
    except (UnicodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValidationError(f"{label}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValidationError(f"{label}: root must be an object")
    ensure_ascii_tree(value, label)
    return value


def exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{label}: must be an object")
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ValidationError(f"{label}: missing key {missing[0]}")
    if unknown:
        raise ValidationError(f"{label}: unknown key {unknown[0]}")
    return value


def string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        raise ValidationError(f"{label}: must be an ASCII string")
    return value


def exact_string(value: object, expected: str, label: str) -> str:
    actual = string(value, label)
    if actual != expected:
        raise ValidationError(f"{label}: unexpected value")
    return actual


def integer(value: object, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ValidationError(
            f"{label}: must be an integer in {minimum}..{maximum}"
        )
    return value


def digest(value: object, label: str) -> str:
    result = string(value, label)
    if DIGEST_RE.fullmatch(result) is None:
        raise ValidationError(f"{label}: must be lowercase 64-hex")
    return result


def empty_or_digest(value: object, label: str) -> str:
    result = string(value, label)
    if result and DIGEST_RE.fullmatch(result) is None:
        raise ValidationError(f"{label}: must be empty or lowercase 64-hex")
    return result


def commit(value: object, label: str) -> str:
    result = string(value, label)
    if COMMIT_RE.fullmatch(result) is None:
        raise ValidationError(f"{label}: must be lowercase 40-hex")
    return result


def enum(value: object, allowed: set[str], label: str) -> str:
    result = string(value, label)
    if result not in allowed:
        raise ValidationError(f"{label}: unsupported enum")
    return result


def exact_array(value: object, expected: list[object], label: str) -> list[object]:
    if (
        not isinstance(value, list)
        or len(value) != len(expected)
        or any(type(actual) is not type(wanted) for actual, wanted in zip(value, expected))
        or value != expected
    ):
        raise ValidationError(f"{label}: vector differs from canonical order")
    return value


def no_symlink_absolute(path: Path, label: str) -> None:
    cursor = Path(path.anchor)
    for component in path.parts[1:]:
        cursor /= component
        try:
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValidationError(f"{label}: symlink component")
        except FileNotFoundError as error:
            raise ValidationError(f"{label}: missing component") from error


def canonical_repository_root(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path) != value:
        raise ValidationError("repository root must be an absolute canonical path")
    no_symlink_absolute(path, "repository root")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValidationError("repository root does not exist") from error
    if path != resolved or not resolved.is_dir():
        raise ValidationError("repository root must resolve to itself as a directory")
    return resolved


def validate_relative(value: object, label: str, maximum: int | None = None) -> str:
    result = string(value, label)
    if not result or (maximum is not None and len(result.encode("ascii")) > maximum):
        raise ValidationError(f"{label}: empty or too long")
    if (
        "\x00" in result
        or "\\" in result
        or result.startswith(("/", "//"))
        or DRIVE_RE.match(result)
        or "//" in result
    ):
        raise ValidationError(f"{label}: noncanonical relative path")
    parts = result.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValidationError(f"{label}: forbidden path component")
    if str(PurePosixPath(result)) != result:
        raise ValidationError(f"{label}: noncanonical POSIX spelling")
    return result


def resolve_owned(
    owner: Path,
    spelling: object,
    label: str,
    *,
    directory: bool,
) -> Path:
    relative = validate_relative(spelling, label)
    candidate = owner.joinpath(*relative.split("/"))
    cursor = owner
    for component in relative.split("/"):
        cursor /= component
        try:
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValidationError(f"{label}: symlink component")
        except FileNotFoundError as error:
            raise ValidationError(f"{label}: missing target") from error
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"{label}: cannot resolve target") from error
    try:
        if os.path.commonpath((str(owner), str(resolved))) != str(owner):
            raise ValidationError(f"{label}: target escapes owning root")
    except ValueError as error:
        raise ValidationError(f"{label}: target is on another path domain") from error
    mode = resolved.stat().st_mode
    if directory:
        if not stat.S_ISDIR(mode):
            raise ValidationError(f"{label}: target is not a directory")
    elif not stat.S_ISREG(mode):
        raise ValidationError(f"{label}: target is not a regular file")
    return resolved


def read_regular(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValidationError(f"{label}: cannot read file") from error


def validate_capture(
    value: object,
    status: str,
    identity: dict[str, str],
) -> dict[str, Any]:
    capture = exact_keys(
        value,
        {
            "captureVectorId",
            "rawCsvPath",
            "rawCsvSha256",
            "fixtureId",
            "fixtureToolName",
            "fixtureToolVersion",
            "fixtureToolSha256",
            "unitsTested",
            "unitIds",
            "temperaturesC",
            "supplyMillivolts",
            "chargerStates",
            "loadStates",
            "repeatCount",
            "notes",
        },
        "capture",
    )
    vector_id = string(capture["captureVectorId"], "capture.captureVectorId")
    if status == "CONFIRMED":
        exact_string(
            vector_id,
            "E87-1542-PB07-CAPTURE-V1",
            "capture.captureVectorId",
        )
    elif IDENTIFIER_RE.fullmatch(vector_id) is None:
        raise ValidationError("capture.captureVectorId: invalid identifier")
    exact_string(capture["rawCsvPath"], identity["raw"], "capture.rawCsvPath")
    digest(capture["rawCsvSha256"], "capture.rawCsvSha256")
    for key in ("fixtureId", "fixtureToolName", "fixtureToolVersion"):
        if IDENTIFIER_RE.fullmatch(string(capture[key], f"capture.{key}")) is None:
            raise ValidationError(f"capture.{key}: invalid identifier")
    digest(capture["fixtureToolSha256"], "capture.fixtureToolSha256")
    units = integer(capture["unitsTested"], 3, 32, "capture.unitsTested")
    unit_ids = capture["unitIds"]
    if (
        not isinstance(unit_ids, list)
        or len(unit_ids) != units
        or any(not isinstance(item, str) or UNIT_RE.fullmatch(item) is None for item in unit_ids)
        or len(set(unit_ids)) != len(unit_ids)
        or unit_ids != sorted(unit_ids)
    ):
        raise ValidationError("capture.unitIds: invalid sorted unit vector")
    exact_array(capture["temperaturesC"], TEMPERATURES, "capture.temperaturesC")
    exact_array(capture["supplyMillivolts"], SUPPLIES, "capture.supplyMillivolts")
    exact_array(capture["chargerStates"], CHARGERS, "capture.chargerStates")
    exact_array(capture["loadStates"], LOADS, "capture.loadStates")
    integer(capture["repeatCount"], 30, 65535, "capture.repeatCount")
    notes = string(capture["notes"], "capture.notes")
    if len(notes) > 512 or any(ord(character) < 32 or ord(character) > 126 for character in notes):
        raise ValidationError("capture.notes: must be printable ASCII up to 512 bytes")
    return capture


def validate_adc(value: object, status: str) -> dict[str, Any]:
    adc = exact_keys(
        value,
        {
            "gpioToken",
            "gpioSplitToken",
            "gpioModeToken",
            "gpioFunctionToken",
            "routeKind",
            "routeStatus",
            "channelToken",
            "channelValue",
            "channelAcceptanceRule",
            "adcMaximum",
            "resolutionBits",
            "referenceMillivolts",
            "samplePeriodMs",
            "sampleLatenessMs",
            "stableSampleCount",
            "minimumGuardCodes",
            "freshSampleKind",
            "freshSampleStatus",
            "freshSampleHook",
            "freshSampleEvidenceSha256",
            "cachedSentinel",
        },
        "adc",
    )
    exact_string(adc["gpioToken"], PB07_GPIO_TOKEN, "adc.gpioToken")
    exact_string(adc["gpioSplitToken"], "IO_PORT_SPILT", "adc.gpioSplitToken")
    exact_string(
        adc["gpioModeToken"], PB07_GPIO_MODE_TOKEN, "adc.gpioModeToken"
    )
    exact_string(adc["gpioFunctionToken"], "PORT_FUNC_GPADC", "adc.gpioFunctionToken")
    exact_string(adc["routeKind"], PB07_ROUTE_KIND, "adc.routeKind")
    exact_string(adc["routeStatus"], status, "adc.routeStatus")
    exact_string(adc["channelToken"], PB07_CHANNEL_TOKEN, "adc.channelToken")
    integer(
        adc["channelValue"],
        PB07_CHANNEL_VALUE,
        PB07_CHANNEL_VALUE,
        "adc.channelValue",
    )
    exact_string(
        adc["channelAcceptanceRule"],
        PB07_CHANNEL_ACCEPTANCE_RULE,
        "adc.channelAcceptanceRule",
    )
    bits = integer(adc["resolutionBits"], 8, 15, "adc.resolutionBits")
    maximum = integer(adc["adcMaximum"], 255, 32767, "adc.adcMaximum")
    if maximum != (1 << bits) - 1:
        raise ValidationError("adc.adcMaximum: inconsistent with resolution")
    integer(adc["referenceMillivolts"], 1000, 5000, "adc.referenceMillivolts")
    period = integer(adc["samplePeriodMs"], 10, 1000, "adc.samplePeriodMs")
    if period % 10:
        raise ValidationError("adc.samplePeriodMs: must be divisible by 10")
    integer(
        adc["sampleLatenessMs"],
        0,
        min(period, 100),
        "adc.sampleLatenessMs",
    )
    integer(adc["stableSampleCount"], 2, 16, "adc.stableSampleCount")
    integer(
        adc["minimumGuardCodes"],
        1,
        min(maximum, 1024),
        "adc.minimumGuardCodes",
    )
    fresh = enum(adc["freshSampleKind"], set(FRESH_KINDS), "adc.freshSampleKind")
    exact_string(adc["freshSampleStatus"], status, "adc.freshSampleStatus")
    exact_string(adc["freshSampleHook"], FRESH_KINDS[fresh], "adc.freshSampleHook")
    digest(adc["freshSampleEvidenceSha256"], "adc.freshSampleEvidenceSha256")
    sentinel = integer(adc["cachedSentinel"], 65535, 65535, "adc.cachedSentinel")
    if maximum >= sentinel:
        raise ValidationError("adc.adcMaximum: must be below cached sentinel")
    return adc


def validate_windows(value: object, adc: dict[str, Any]) -> dict[str, Any]:
    windows = exact_keys(
        value,
        {"none", "button1", "button2", "bothButtons"},
        "windows",
    )
    ordered: list[tuple[int, int]] = []
    for name in ("none", "button1", "button2", "bothButtons"):
        window = exact_keys(
            windows[name],
            {"minimumInclusive", "maximumInclusive"},
            f"windows.{name}",
        )
        minimum = integer(
            window["minimumInclusive"],
            0,
            adc["adcMaximum"],
            f"windows.{name}.minimumInclusive",
        )
        maximum = integer(
            window["maximumInclusive"],
            0,
            adc["adcMaximum"],
            f"windows.{name}.maximumInclusive",
        )
        if minimum > maximum:
            raise ValidationError(f"windows.{name}: inverted window")
        ordered.append((minimum, maximum))
    ordered.sort(key=lambda item: item[0])
    for previous, following in zip(ordered, ordered[1:]):
        gap = following[0] - previous[1] - 1
        if previous[1] + 1 >= following[0] or gap < adc["minimumGuardCodes"]:
            raise ValidationError("windows: overlap, touch, or insufficient guard")
    return windows


def validate_pinr(value: object, status: str) -> None:
    pinr = exact_keys(
        value,
        {
            "status",
            "gpioToken",
            "activeLevel",
            "pullModeToken",
            "pullEnableArgument",
            "releaseArgument",
            "holdSeconds",
            "compatibleTriggerSet",
            "observedResetCause",
            "evidenceSha256",
            "commandAcceptanceRule",
        },
        "pinr",
    )
    exact_string(pinr["status"], status, "pinr.status")
    exact_string(pinr["gpioToken"], PB07_GPIO_TOKEN, "pinr.gpioToken")
    integer(pinr["activeLevel"], 0, 1, "pinr.activeLevel")
    exact_string(
        pinr["pullModeToken"],
        PB07_GPIO_MODE_TOKEN,
        "pinr.pullModeToken",
    )
    integer(
        pinr["pullEnableArgument"],
        PB07_PINR_PULL_MODE_ARGUMENT,
        PB07_PINR_PULL_MODE_ARGUMENT,
        "pinr.pullEnableArgument",
    )
    integer(pinr["releaseArgument"], 0, 1, "pinr.releaseArgument")
    integer(pinr["holdSeconds"], 16, 16, "pinr.holdSeconds")
    triggers = pinr["compatibleTriggerSet"]
    allowed_order = ["BOTH_BUTTONS", "BUTTON1", "BUTTON2"]
    if (
        not isinstance(triggers, list)
        or not triggers
        or any(not isinstance(item, str) or item not in allowed_order for item in triggers)
        or len(set(triggers)) != len(triggers)
        or triggers != sorted(triggers)
        or "BUTTON1" not in triggers
        or "NONE" in triggers
    ):
        raise ValidationError("pinr.compatibleTriggerSet: invalid trigger subset")
    exact_string(pinr["observedResetCause"], "P33_PPINR_RST", "pinr.observedResetCause")
    digest(pinr["evidenceSha256"], "pinr.evidenceSha256")
    exact_string(
        pinr["commandAcceptanceRule"],
        "VOID_CALL_ISSUED_AFTER_QUALIFICATION",
        "pinr.commandAcceptanceRule",
    )


def validate_startup(value: object, status: str, adc: dict[str, Any]) -> None:
    startup = exact_keys(
        value,
        {
            "status",
            "resetCauseReadyHook",
            "timingKind",
            "freshSampleReadyHook",
            "allowedPreRouteInitializers",
            "forbiddenPreRouteInitializers",
            "resetRecorderOwner",
            "evidenceSha256",
            "sourceIdentity",
        },
        "startup",
    )
    exact_string(startup["status"], status, "startup.status")
    exact_string(
        startup["resetCauseReadyHook"],
        "E87_RESET_CAUSE_READY_AFTER_POWER_EARLY_V1",
        "startup.resetCauseReadyHook",
    )
    exact_string(startup["timingKind"], adc["freshSampleKind"], "startup.timingKind")
    exact_string(
        startup["freshSampleReadyHook"],
        adc["freshSampleHook"],
        "startup.freshSampleReadyHook",
    )
    exact_array(
        startup["allowedPreRouteInitializers"],
        ALLOWED_INITIALIZERS,
        "startup.allowedPreRouteInitializers",
    )
    exact_array(
        startup["forbiddenPreRouteInitializers"],
        FORBIDDEN_INITIALIZERS,
        "startup.forbiddenPreRouteInitializers",
    )
    exact_string(
        startup["resetRecorderOwner"],
        "e87_br35_button_record_reset_cause_early",
        "startup.resetRecorderOwner",
    )
    digest(startup["evidenceSha256"], "startup.evidenceSha256")
    digest(startup["sourceIdentity"], "startup.sourceIdentity")


def validate_driver_root(
    value: object,
    status: str,
    identity: dict[str, str],
) -> dict[str, Any]:
    driver = exact_keys(
        value,
        {
            "status",
            "supportCommit",
            "supportTree",
            "evidencePath",
            "evidenceSha256",
            "overlayPath",
            "overlaySha256",
            "internalSignalQualificationSha256",
        },
        "driver",
    )
    exact_string(driver["status"], status, "driver.status")
    commit(driver["supportCommit"], "driver.supportCommit")
    commit(driver["supportTree"], "driver.supportTree")
    exact_string(driver["evidencePath"], identity["driver"], "driver.evidencePath")
    digest(driver["evidenceSha256"], "driver.evidenceSha256")
    exact_string(driver["overlayPath"], "", "driver.overlayPath")
    exact_string(driver["overlaySha256"], "", "driver.overlaySha256")
    exact_string(
        driver["internalSignalQualificationSha256"],
        "",
        "driver.internalSignalQualificationSha256",
    )
    return driver


def validate_qualification(
    value: object,
    adc: dict[str, Any],
) -> None:
    qualification = exact_keys(
        value,
        {
            "archivePath",
            "archiveSha256",
            "memberPath",
            "memberSha256",
            "llvmDisassemblySha256",
            "routeReturnKind",
            "unsupportedRouteValueKind",
            "cachedSentinel",
            "freshConversionKind",
            "freshConversionHook",
            "freshConversionEvidenceSha256",
            "rollbackKind",
            "rollbackEvidenceSha256",
            "hardwareQualificationSha256",
        },
        "driver projection qualification",
    )
    for key in ("archivePath", "memberPath"):
        identifier = validate_relative(qualification[key], f"qualification.{key}", 256)
        if POSIX_IDENTIFIER_RE.fullmatch(identifier) is None:
            raise ValidationError(f"qualification.{key}: invalid identifier")
    for key in ("archiveSha256", "memberSha256", "llvmDisassemblySha256"):
        digest(qualification[key], f"qualification.{key}")
    exact_string(
        qualification["routeReturnKind"],
        "U32_CHANNEL_OR_UINT32_MAX",
        "qualification.routeReturnKind",
    )
    exact_string(
        qualification["unsupportedRouteValueKind"],
        "UINT32_MAX",
        "qualification.unsupportedRouteValueKind",
    )
    integer(
        qualification["cachedSentinel"],
        adc["cachedSentinel"],
        adc["cachedSentinel"],
        "qualification.cachedSentinel",
    )
    exact_string(
        qualification["freshConversionKind"],
        adc["freshSampleKind"],
        "qualification.freshConversionKind",
    )
    exact_string(
        qualification["freshConversionHook"],
        adc["freshSampleHook"],
        "qualification.freshConversionHook",
    )
    exact_string(
        qualification["freshConversionEvidenceSha256"],
        adc["freshSampleEvidenceSha256"],
        "qualification.freshConversionEvidenceSha256",
    )
    exact_string(
        qualification["rollbackKind"],
        "ADC_DELETE_DISABLE_FUNCTION_RESTORE_MODE",
        "qualification.rollbackKind",
    )
    digest(qualification["rollbackEvidenceSha256"], "qualification.rollbackEvidenceSha256")
    digest(
        qualification["hardwareQualificationSha256"],
        "qualification.hardwareQualificationSha256",
    )


def validate_projection(
    raw: bytes,
    root_status: str,
    identity: dict[str, str],
    sdk: dict[str, Any],
    adc: dict[str, Any],
    driver: dict[str, Any],
) -> dict[str, Any]:
    projection = decode_json(raw, "driver projection")
    exact_keys(
        projection,
        {
            "schema",
            "status",
            "sdkCommit",
            "sdkTree",
            "gpioToken",
            "gpioSplitToken",
            "gpioModeToken",
            "gpioFunctionToken",
            "routeKind",
            "routeStatus",
            "channelToken",
            "channelValue",
            "channelAcceptanceRule",
            "freshSampleKind",
            "freshSampleStatus",
            "freshSampleHook",
            "freshSampleEvidenceSha256",
            "cachedSentinel",
            "overlayPath",
            "overlaySha256",
            "internalSignalQualificationSha256",
            "qualification",
        },
        "driver projection",
    )
    if canonical(projection) != raw:
        raise ValidationError("driver projection: bytes are not canonical")
    exact_string(
        projection["schema"],
        "e87-button-driver-projection-v1",
        "driver projection schema",
    )
    exact_string(projection["status"], root_status, "driver projection status")
    exact_string(projection["sdkCommit"], sdk["commit"], "projection.sdkCommit")
    exact_string(projection["sdkTree"], sdk["tree"], "projection.sdkTree")
    for key in (
        "gpioToken",
        "gpioSplitToken",
        "gpioModeToken",
        "gpioFunctionToken",
        "routeKind",
        "routeStatus",
        "channelToken",
        "channelValue",
        "channelAcceptanceRule",
        "freshSampleKind",
        "freshSampleStatus",
        "freshSampleHook",
        "freshSampleEvidenceSha256",
        "cachedSentinel",
    ):
        if type(projection[key]) is not type(adc[key]) or projection[key] != adc[key]:
            raise ValidationError(f"projection.{key}: root ADC cross-link mismatch")
    for key in (
        "overlayPath",
        "overlaySha256",
        "internalSignalQualificationSha256",
    ):
        if projection[key] != driver[key]:
            raise ValidationError(f"projection.{key}: root driver cross-link mismatch")
    exact_string(projection["routeStatus"], root_status, "projection.routeStatus")
    exact_string(
        projection["freshSampleStatus"],
        root_status,
        "projection.freshSampleStatus",
    )
    validate_qualification(projection["qualification"], adc)
    return projection


def validate_csv(
    raw: bytes,
    capture: dict[str, Any],
    adc: dict[str, Any],
    windows: dict[str, Any],
) -> None:
    if (
        not raw
        or raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in raw
        or not raw.endswith(b"\n")
        or raw.endswith(b"\n\n")
        or b'"' in raw
        or any(byte != 10 and (byte < 32 or byte > 126) for byte in raw)
    ):
        raise ValidationError("raw CSV: invalid byte encoding or line form")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as error:
        raise ValidationError("raw CSV: non-ASCII bytes") from error
    if not lines or lines[0] != CSV_HEADER:
        raise ValidationError("raw CSV: wrong header")
    rows = lines[1:]
    expected_count = (
        len(capture["unitIds"])
        * len(TEMPERATURES)
        * len(SUPPLIES)
        * len(CHARGERS)
        * len(LOADS)
        * len(STATES)
        * capture["repeatCount"]
    )
    if len(rows) != expected_count:
        raise ValidationError("raw CSV: wrong Cartesian row count")
    state_window = {
        "NONE": windows["none"],
        "BUTTON1": windows["button1"],
        "BUTTON2": windows["button2"],
        "BOTH_BUTTONS": windows["bothButtons"],
    }
    products = itertools.product(
        capture["unitIds"],
        TEMPERATURES,
        SUPPLIES,
        CHARGERS,
        LOADS,
        STATES,
        range(1, capture["repeatCount"] + 1),
    )
    for sample_id, (line, expected) in enumerate(zip(rows, products), 1):
        fields = line.split(",")
        if len(fields) != 9 or any(" " in field or "\t" in field for field in fields):
            raise ValidationError(f"raw CSV row {sample_id}: wrong field form")
        unit, temperature, supply, charger, load, state, ordinal = expected
        expected_prefix = [
            str(sample_id),
            unit,
            str(temperature),
            str(supply),
            charger,
            load,
            state,
            str(ordinal),
        ]
        if fields[:8] != expected_prefix:
            raise ValidationError(f"raw CSV row {sample_id}: wrong Cartesian order")
        raw_token = fields[8]
        if re.fullmatch(r"0|[1-9][0-9]*", raw_token) is None:
            raise ValidationError(f"raw CSV row {sample_id}: noncanonical ADC integer")
        raw_adc = int(raw_token)
        if raw_adc > adc["adcMaximum"] or raw_adc == adc["cachedSentinel"]:
            raise ValidationError(f"raw CSV row {sample_id}: ADC outside domain")
        selected = state_window[state]
        if not selected["minimumInclusive"] <= raw_adc <= selected["maximumInclusive"]:
            raise ValidationError(f"raw CSV row {sample_id}: ADC outside physical window")


def validate_document(
    repository_root: Path,
    evidence_spelling: str,
    raw_root_spelling: str,
    required_profile: str,
    required_status: str,
) -> str:
    if required_status not in STATUS_IDENTITIES:
        raise ValidationError("require-status must be exactly TEST_ONLY or CONFIRMED")
    identity = STATUS_IDENTITIES[required_status]
    if required_profile != identity["profile"]:
        raise ValidationError("required profile does not match status namespace")
    if evidence_spelling != identity["evidence"]:
        raise ValidationError("evidence path does not match status namespace")
    if raw_root_spelling != RAW_ROOT:
        raise ValidationError("raw-root path does not match canonical namespace")

    evidence_path = resolve_owned(
        repository_root, evidence_spelling, "evidence", directory=False
    )
    raw_root_path = resolve_owned(
        repository_root, raw_root_spelling, "raw root", directory=True
    )
    evidence_raw = read_regular(evidence_path, "evidence")
    root = decode_json(evidence_raw, "evidence")
    exact_keys(
        root,
        {
            "schema",
            "status",
            "profileId",
            "physicalModel",
            "chipFamily",
            "sdk",
            "capture",
            "adc",
            "windows",
            "physicalMapping",
            "pinr",
            "startup",
            "driver",
            "canonicalDigestSha256",
        },
        "evidence",
    )
    canonical_digest = digest(root["canonicalDigestSha256"], "canonicalDigestSha256")
    without_digest = dict(root)
    without_digest.pop("canonicalDigestSha256")
    if sha256(canonical(without_digest)) != canonical_digest:
        raise ValidationError("evidence: canonical digest mismatch")
    if canonical(root) != evidence_raw:
        raise ValidationError("evidence: bytes are not canonical")

    exact_string(root["schema"], "e87-button-evidence-v1", "schema")
    exact_string(root["status"], required_status, "status")
    exact_string(root["profileId"], identity["profile"], "profileId")
    exact_string(root["physicalModel"], identity["model"], "physicalModel")
    exact_string(root["chipFamily"], CHIP_FAMILY, "chipFamily")
    sdk = exact_keys(root["sdk"], {"commit", "tree"}, "sdk")
    exact_string(sdk["commit"], SDK_COMMIT, "sdk.commit")
    exact_string(sdk["tree"], SDK_TREE, "sdk.tree")
    commit(sdk["commit"], "sdk.commit")
    commit(sdk["tree"], "sdk.tree")
    capture = validate_capture(root["capture"], required_status, identity)
    adc = validate_adc(root["adc"], required_status)
    windows = validate_windows(root["windows"], adc)
    mapping = exact_keys(
        root["physicalMapping"],
        {"syncPair", "sleep", "simultaneous"},
        "physicalMapping",
    )
    exact_string(mapping["syncPair"], "BUTTON1", "physicalMapping.syncPair")
    exact_string(mapping["sleep"], "BUTTON2", "physicalMapping.sleep")
    exact_string(
        mapping["simultaneous"],
        "AMBIGUOUS",
        "physicalMapping.simultaneous",
    )
    validate_pinr(root["pinr"], required_status)
    validate_startup(root["startup"], required_status, adc)
    driver = validate_driver_root(root["driver"], required_status, identity)

    raw_csv_path = resolve_owned(
        raw_root_path, capture["rawCsvPath"], "raw CSV", directory=False
    )
    driver_path = resolve_owned(
        repository_root, driver["evidencePath"], "driver evidence", directory=False
    )
    resolved_files = {evidence_path, raw_csv_path, driver_path}
    if len(resolved_files) != 3:
        raise ValidationError("evidence paths resolve to duplicate targets")
    raw_csv = read_regular(raw_csv_path, "raw CSV")
    if sha256(raw_csv) != capture["rawCsvSha256"]:
        raise ValidationError("raw CSV: digest mismatch")
    driver_raw = read_regular(driver_path, "driver evidence")
    if sha256(driver_raw) != driver["evidenceSha256"]:
        raise ValidationError("driver evidence: digest mismatch")

    validate_projection(
        driver_raw,
        required_status,
        identity,
        sdk,
        adc,
        driver,
    )
    validate_csv(raw_csv, capture, adc, windows)
    return canonical_digest


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--require-profile", required=True)
    parser.add_argument("--require-status", required=True)
    parser.add_argument("--print-digest", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        repository_root = canonical_repository_root(arguments.repository_root)
        result = validate_document(
            repository_root,
            arguments.evidence,
            arguments.raw_root,
            arguments.require_profile,
            arguments.require_status,
        )
    except (ValidationError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if arguments.print_digest:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
