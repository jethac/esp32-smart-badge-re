#!/usr/bin/env python3
"""Exact lock and local-identity contracts for Stage 0-H S0-1."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
LOCK_ROOT = ROOT / "firmware/locks"
VALIDATOR = ROOT / "firmware/tools/validate-stage0.py"


TOOLCHAIN = {
    "archive": {
        "filename": "jieli-linux-toolchains-20250805.1.tar.xz",
        "sha256": "F686586BCFB45E0F0BB27FD2B39C7A7F313CB4F0E88A66A14DA621FFA8225958",
    },
    "hostTools": {
        "env": {"path": "/usr/bin/env", "sha256": "85036540673319C6C2F54233FD2B9E45A8A71246B51CC96C4E6AB8EE6C419EB0", "version": "8.32"},
        "gcc": {"path": "/usr/bin/gcc-11", "sha256": "821AF3C74506283C179CA413BB33E6B528805A4DD8A5C09DF125E5AD560A9E89", "version": "11.4.0"},
        "git": {"path": "/usr/bin/git", "sha256": "587EF21868C948B883993E23209B86A72A6DDC06AAB1545C697FFC31075ACD4A", "version": "2.34.1"},
        "ld": {"path": "/usr/bin/x86_64-linux-gnu-ld.bfd", "sha256": "58937FC20C21E147883B4FDAA0FC7438A8E8F2BB886CFCAA4896100CA91139E7", "version": "2.38"},
        "make": {"path": "/usr/bin/make", "sha256": "92F646030615CD98490A68A94C0AEFD87B552BE3158B941C02E43B0BFDB576DB", "version": "4.3"},
        "python": {"path": "/usr/bin/python3.11", "sha256": "C4B3F4386C93758043A4E772574BFBD6B0E5E4CE8D50AF17F6FFEEB4B1A6BE5B", "version": "3.11.15"},
        "python3": {"path": "/usr/bin/python3", "resolvedPath": "/usr/bin/python3.10", "sha256": "7D51CD6B48B521277F5CAA4610A82126E315FA2BE4DF069823A8B1EEB5BD4A86", "symlinkTarget": "python3.10", "version": "3.10.12"},
    },
    "runtime": {
        "controlledPathTemplate": "${TOOL_ROOT}/pi32v2/bin:/home/jethac/.local/share/e87-dev/jieli-post-build:/usr/bin:/bin",
        "elfInterpreter": {"path": "/lib64/ld-linux-x86-64.so.2", "sha256": "8D06F393F4A93BCF9B81145A259524D66A95522A646BF8D7E05B6FFDF2E63DCC"},
    },
    "schema": "e87-stage0-toolchain-lock-v1",
    "sdk": {"commit": "d0167685d032d745d88fe50233302edd46941622", "tree": "854734595be49510aca5afb89f5885e8bce6a00f"},
    "target": {"architecture": "pi32v2", "chip": "AC707N", "cpu": "r3", "entryAddress": "0x0C000100", "family": "BR35"},
    "tools": {
        "ar": {"byteLength": 744888, "installRelativePath": "pi32v2/bin/ar", "mode": "0755", "sha256": "CAD18239D47EE1439DBE1D2C2892D4C4BDB868BEF68F08242766DF7AE333A84C"},
        "clang": {"installRelativePath": "common/bin/clang", "sha256": "42B94F9E11140B0FCAB8F807B2872AD245B8EECA03A2D792F8706C5A3A35D34C"},
        "ld": {"installRelativePath": "pi32v2/bin/ld", "sha256": "FD61AFF15616BB6F6B58FD2E9EDE7AF741C7BF05FACB3E0CB3D3C9817C268FD9"},
        "linkVersion": {"byteLength": 2121360, "installRelativePath": "pi32v2/bin/link-version", "mode": "0755", "resolvedInstallRelativePath": "common/bin/link-version", "sha256": "3129FCC8FCCD70F7B229026CB9ACB324A616F5D19953E5ED5D14BEF35BF81D56", "symlinkTarget": "../../common/bin/link-version"},
        "llvmGold": {"byteLength": 17646856, "installRelativePath": "pi32v2/bin/LLVMgold.so", "mode": "0755", "resolvedInstallRelativePath": "common/bin/LLVMgold.so", "sha256": "B91F4509C885DB84B0FA09C06C6E43F773DB9E47593C86FCF92BDFB65CEF2120", "symlinkTarget": "../../common/bin/LLVMgold.so"},
        "ltoAr": {"byteLength": 524, "installRelativePath": "pi32v2/bin/lto-ar", "mode": "0755", "resolvedInstallRelativePath": "common/bin/lto-ar", "sha256": "4F8470410C9DFF9059FF595A2206257EAE505D9FE4C7EE5926C3119262E99E68", "symlinkTarget": "../../common/bin/lto-ar"},
        "ltoWrapper": {"byteLength": 2097, "installRelativePath": "pi32v2/bin/lto-wrapper", "mode": "0775", "resolvedInstallRelativePath": "common/bin/lto-wrapper", "sha256": "777F7A173E9E1B801C73945DE3D5888708F278E7B5242AFE8B277ABE1761BC0E", "symlinkTarget": "../../common/bin/lto-wrapper"},
        "nm": {"installRelativePath": "pi32v2/bin/nm", "sha256": "32BEE027A324BD4D561079C943D94C53FECE2BFB7F1E12B5D7CE7CC7737C6CE4"},
        "objcopy": {"installRelativePath": "common/bin/objcopy", "sha256": "A941EAB0DD62D51DA635BE7834FC34D4765DBF421D00599F3A5081D42D416502"},
        "objdump": {"installRelativePath": "common/bin/objdump", "sha256": "CFFC304E1A9BE5DAC22984A6AD48E81EF82B17166FD8864C251CF635C9663B73"},
        "objsizedump": {"installRelativePath": "common/bin/objsizedump", "sha256": "07AC5172C736EB6A8662413CFBDA9B964D025635FB6C4A71985F2B4965DFC44D"},
        "strip": {"installRelativePath": "pi32v2/bin/strip", "sha256": "60906528ABA3115D2E4DF838B3B6C4166714F2C476EBC7037177B40E04DCF459"},
    },
}

PACKAGING = {
    "archive": {"filename": "jieli-linux-post-build-tools-20260728.1.tar.xz", "sha256": "F4A458738C5EEC32E78377C76B346BCAC1CD515B03EDA2B7EB11AB183298A858"},
    "isdArgv": ["-tonorflash", "-dev", "br35", "-boot", "0x102600", "-div8", "-wait", "300", "-uboot", "uboot.boot", "-app", "app.bin", "-res", "cfg_tool.bin", "p11_code.bin", "stream.bin", "config.dat", "-flash-params", "flash_params_v3.bin", "-output-fw", "jl_isd.fw", "-output-ufw", "update.ufw"],
    "nativeOutputs": ["jl_isd.bin", "jl_isd.fw", "update.ufw"],
    "qix": {"headerBytes": 27, "magicHex": "BCAF01", "payloadCrc": "CRC16_CCITT_FALSE", "payloadCrcSeed": 65535, "version": "11.1.0.3"},
    "schema": "e87-stage0-packaging-lock-v1",
    "tools": {
        "fwAdd": {"installRelativePath": "fw_add", "invocation": "FORBIDDEN", "sha256": "E79DA301B6B47233B1466BF8DAA64D8DCCB72A239BEC3C83F634469131ACA16C"},
        "isdDownload": {"build": "c45787bd64f17e6756779a37cf5266b940f9d175", "installRelativePath": "isd_download", "sha256": "11849221C3E5E89D31E6FCEF52FE1DB28C2C5D322CDB919E954CCA2A5043EF87", "version": "4.2.79"},
        "ufwMaker": {"installRelativePath": "ufw_maker", "sha256": "039D761CA4170F1E5658B868C963E8D43651000368BE55E892CD0BD941B553C6", "version": "1.1.14"},
    },
    "ufwMakerArgv": ["--fw", "jl_isd.fw", "--output", "independently-made.ufw"],
}

REFERENCE_FILES = {
    "canonical-jl-unpack/files/app.bin": {"byteLength": 995584, "role": "GOLDEN_APP_ONLY", "sha256": "A38B77E27B1DC73CAE0FBD8A7C4E3A04C64FF393FB4F27BC92A7578336BE0147"},
    "canonical-jl-unpack/files/cfg_tool.bin": {"byteLength": 180, "role": "PACKAGE_RESOURCE", "sha256": "CEC4551FA08F3ED70225095ACBD6CD5584E5EAB9CA418ED37F27102F66CD6833"},
    "canonical-jl-unpack/files/config.dat": {"byteLength": 352, "role": "PACKAGE_RESOURCE", "sha256": "29EA517C67EB53D76D2ABE2C867C8F5A797C87ED506F1C7F2E7F2133782D75C4"},
    "canonical-jl-unpack/files/p11_code.bin": {"byteLength": 10536, "role": "PACKAGE_RESOURCE", "sha256": "E23867E2E411BB8713CB5E698BA4BDBCD63F062E9C0381CCBA6B122D5F222FED"},
    "canonical-jl-unpack/files/stream.bin": {"byteLength": 4426, "role": "PACKAGE_RESOURCE", "sha256": "F1422559A23576C05591FDF1A51C5B011BEC3F6D753217B7E450CE3D43C22553"},
    "canonical-jl-unpack/top/uboot.boot": {"byteLength": 3551, "role": "PACKAGE_BOOT", "sha256": "1858B5FB78E35F0E13D17905AA9B582B74EA1546661550C9EA7E3913D809BD39"},
    "container/payload.ufw": {"byteLength": 1080360, "role": "GOLDEN_UFW_ONLY", "sha256": "ECDFAA06377A00056ADB15D3486A4B059ACDE762C0F4A2BC8DCE43E0D120A80B"},
    "items/03_params_flash.bin": {"byteLength": 2420, "role": "PACKAGE_FLASH_PARAMS", "sha256": "7E27AE860FFFE505813057AC481AD7AA262574718E6C50E9F4420EED0696B6F7"},
    "items/04_isd_config.ini": {"byteLength": 1657, "role": "PACKAGE_PLAINTEXT_INI", "sha256": "CEC1973E50FB7A3D74D04D6340C671A443D50C538C272E1B14567C71F9AED47A"},
    "items/06_ota.bin": {"byteLength": 23688, "role": "PACKAGE_OTA", "sha256": "91662F33DD1DC7C7DF0134876F697F0ADA0B63923890E7F60D0A063D6D19E2A9"},
    "manifest.json": {"byteLength": 18797, "role": "REFERENCE_MANIFEST", "sha256": "01FBB801B9C408F6BE2F885A92DDC561151FB4A70450F37F39C6C56F25222678"},
}

MODEL1552 = {
    "jieliNewFirmware": {"chipKey": "0x9847", "entryAddress": "0x0C000100", "format": "jl-new-fw", "referenceToolCommit": "0a5b12db0ef38f3042acffbe2452730a37fd2405"},
    "qixGolden": {"payloadCrc16": "0xB501", "sha256": "14484147053903F879D0C24ACBAB6A564F5CC8F039CACCBB30821012DF645D32", "size": 1080387, "version": "11.1.0.2"},
    "referenceFiles": REFERENCE_FILES,
    "resetPolicy": {"disabledLine": "RESET = PB07_00_0;", "inputRelativePath": "items/04_isd_config.ini", "requiredInputLine": "RESET = PB07_08_0;", "refusedBinaryPropertyPath": "canonical-jl-unpack/top/isd_config.ini"},
    "schema": "e87-stage0-model1552-package-lock-v1",
    "sdkLoader": {"byteLength": 27328, "sdkRelativePath": "SDK/cpu/br35/tools/br35loader.bin", "sha256": "1295A01D5A89AD42E9EDA6B87ACFE7D543AB68293D4087C3DDA9BF9AB472DAE1"},
    "ufwGolden": {"chip": "AC707N", "formatVersion": 4, "memberNames": ["flash.bin", "info.log", "uboot.version", "params_flash.bin", "isd_config.ini", "v_ota.bin", "ota.bin", "farg.cfg", "blimit.bin", "tail.bin"]},
}


EXPECTED = {
    "model1552-package.lock.json": MODEL1552,
    "packaging.lock.json": PACKAGING,
    "toolchain.lock.json": TOOLCHAIN,
}

EXPECTED_SHA256_PATHS = {
    "model1552-package.lock.json": frozenset({
        ("qixGolden", "sha256"),
        ("referenceFiles", "canonical-jl-unpack/files/app.bin", "sha256"),
        ("referenceFiles", "canonical-jl-unpack/files/cfg_tool.bin", "sha256"),
        ("referenceFiles", "canonical-jl-unpack/files/config.dat", "sha256"),
        ("referenceFiles", "canonical-jl-unpack/files/p11_code.bin", "sha256"),
        ("referenceFiles", "canonical-jl-unpack/files/stream.bin", "sha256"),
        ("referenceFiles", "canonical-jl-unpack/top/uboot.boot", "sha256"),
        ("referenceFiles", "container/payload.ufw", "sha256"),
        ("referenceFiles", "items/03_params_flash.bin", "sha256"),
        ("referenceFiles", "items/04_isd_config.ini", "sha256"),
        ("referenceFiles", "items/06_ota.bin", "sha256"),
        ("referenceFiles", "manifest.json", "sha256"),
        ("sdkLoader", "sha256"),
    }),
    "packaging.lock.json": frozenset({
        ("archive", "sha256"),
        ("tools", "fwAdd", "sha256"),
        ("tools", "isdDownload", "sha256"),
        ("tools", "ufwMaker", "sha256"),
    }),
    "toolchain.lock.json": frozenset({
        ("archive", "sha256"),
        ("hostTools", "env", "sha256"),
        ("hostTools", "gcc", "sha256"),
        ("hostTools", "git", "sha256"),
        ("hostTools", "ld", "sha256"),
        ("hostTools", "make", "sha256"),
        ("hostTools", "python", "sha256"),
        ("hostTools", "python3", "sha256"),
        ("runtime", "elfInterpreter", "sha256"),
        ("tools", "ar", "sha256"),
        ("tools", "clang", "sha256"),
        ("tools", "ld", "sha256"),
        ("tools", "linkVersion", "sha256"),
        ("tools", "llvmGold", "sha256"),
        ("tools", "ltoAr", "sha256"),
        ("tools", "ltoWrapper", "sha256"),
        ("tools", "nm", "sha256"),
        ("tools", "objcopy", "sha256"),
        ("tools", "objdump", "sha256"),
        ("tools", "objsizedump", "sha256"),
        ("tools", "strip", "sha256"),
    }),
}


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("ascii")


def load_validator():
    spec = importlib.util.spec_from_file_location("e87_stage0_validate", VALIDATOR)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load Stage 0 validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Stage0LockTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator()

    def test_three_new_locks_are_exact_canonical_ascii_and_existing_sdk_lock_is_untouched(self):
        self.assertEqual((LOCK_ROOT / "sdk.lock.json").read_bytes().__len__(), 412)
        import hashlib
        self.assertEqual(hashlib.sha256((LOCK_ROOT / "sdk.lock.json").read_bytes()).hexdigest(), "82349102760c0a9d5a06297b0309dabbf724be954adbd19554e895d20da3698a")
        for filename, expected in EXPECTED.items():
            with self.subTest(filename=filename):
                raw = (LOCK_ROOT / filename).read_bytes()
                self.assertEqual(raw, canonical(expected))
                self.assertEqual(json.loads(raw), expected)
                if filename == "toolchain.lock.json":
                    allowed = expected["runtime"]["controlledPathTemplate"].encode("ascii")
                    self.assertEqual(raw.count(b"/home/jethac"), 1)
                    self.assertIn(allowed, raw)
                    self.assertNotIn(b"/home/jethac", raw.replace(allowed, b"${CONTROLLED_PATH}"))
                else:
                    self.assertNotIn(b"/home/jethac", raw)

    def test_validator_loads_exact_three_lock_projection(self):
        loaded = self.validator.load_stage0_locks(ROOT)
        self.assertEqual(loaded, EXPECTED)

    def test_toolchain_lock_pins_every_host_sdk_target_archive_and_executable_identity(self):
        lock = EXPECTED["toolchain.lock.json"]
        self.assertEqual(set(lock), {"archive", "hostTools", "runtime", "schema", "sdk", "target", "tools"})
        self.assertEqual(set(lock["hostTools"]), {"env", "gcc", "git", "ld", "make", "python", "python3"})
        self.assertEqual(set(lock["tools"]), {"ar", "clang", "ld", "linkVersion", "llvmGold", "ltoAr", "ltoWrapper", "nm", "objcopy", "objdump", "objsizedump", "strip"})
        self.assertEqual(lock["target"], {"architecture": "pi32v2", "chip": "AC707N", "cpu": "r3", "entryAddress": "0x0C000100", "family": "BR35"})

    def test_toolchain_lock_pins_actual_python310_lto_route_and_interpreter(self):
        lock = EXPECTED["toolchain.lock.json"]
        self.assertEqual(lock["runtime"], {
            "controlledPathTemplate": "${TOOL_ROOT}/pi32v2/bin:/home/jethac/.local/share/e87-dev/jieli-post-build:/usr/bin:/bin",
            "elfInterpreter": {"path": "/lib64/ld-linux-x86-64.so.2", "sha256": "8D06F393F4A93BCF9B81145A259524D66A95522A646BF8D7E05B6FFDF2E63DCC"},
        })
        self.assertEqual(lock["hostTools"]["python3"]["symlinkTarget"], "python3.10")
        self.assertEqual(lock["hostTools"]["python3"]["resolvedPath"], "/usr/bin/python3.10")
        for name in ("ltoWrapper", "ltoAr", "llvmGold", "linkVersion"):
            record = lock["tools"][name]
            self.assertEqual(set(record), {"byteLength", "installRelativePath", "mode", "resolvedInstallRelativePath", "sha256", "symlinkTarget"})
            self.assertTrue(record["installRelativePath"].startswith("pi32v2/bin/"))
            self.assertTrue(record["resolvedInstallRelativePath"].startswith("common/bin/"))

    def test_lock_document_schema_exhaustively_rejects_bad_sha256_grammar_at_every_literal_path(self):
        validate_document = self.validator.validate_lock_document

        def sha256_paths(value, location=()):
            result = set()
            if isinstance(value, dict):
                for key, item in value.items():
                    child = location + (key,)
                    if key == "sha256" or key.endswith("Sha256"):
                        result.add(child)
                    result.update(sha256_paths(item, child))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    result.update(sha256_paths(item, location + (index,)))
            return frozenset(result)

        def replace_path(value, path, replacement):
            changed = copy.deepcopy(value)
            cursor = changed
            for component in path[:-1]:
                cursor = cursor[component]
            cursor[path[-1]] = replacement
            return changed

        bad_values = {
            "length-62": "A" * 62,
            "length-63": "A" * 63,
            "length-65": "A" * 65,
            "lowercase": "a" * 64,
            "nonhex": "G" * 64,
        }

        for filename, expected in EXPECTED.items():
            with self.subTest(filename=filename):
                parsed = json.loads(canonical(expected))
                actual_paths = sha256_paths(parsed)
                self.assertTrue(actual_paths)
                self.assertEqual(actual_paths, EXPECTED_SHA256_PATHS[filename])
                validate_document(filename, parsed)
                for path in sorted(actual_paths):
                    for grammar, replacement in bad_values.items():
                        with self.subTest(
                            filename=filename,
                            path=".".join(str(part) for part in path),
                            grammar=grammar,
                        ):
                            with self.assertRaisesRegex(ValueError, "sha256"):
                                validate_document(
                                    filename,
                                    replace_path(parsed, path, replacement),
                                )

    def test_outer_identity_and_cli_loader_invoke_document_schema_in_the_required_order(self):
        validate_document = self.validator.validate_lock_document

        drifted = copy.deepcopy(PACKAGING)
        drifted["ufwMakerArgv"][0] = "--not-fw"
        with mock.patch.object(
            self.validator,
            "validate_lock_document",
            wraps=validate_document,
        ) as document_spy:
            with self.assertRaisesRegex(ValueError, "lock value drift"):
                self.validator.validate_lock("packaging.lock.json", drifted)
            document_spy.assert_not_called()

        with mock.patch.object(
            self.validator,
            "validate_lock_document",
            wraps=validate_document,
        ) as document_spy:
            for filename in sorted(EXPECTED):
                self.validator.validate_lock(filename, EXPECTED[filename])
            self.assertEqual(
                document_spy.call_args_list,
                [mock.call(filename, EXPECTED[filename]) for filename in sorted(EXPECTED)],
            )

        with mock.patch.object(
            self.validator,
            "validate_lock_document",
            wraps=validate_document,
        ) as document_spy:
            self.assertEqual(
                self.validator.main(["--repository-root", str(ROOT)]),
                0,
            )
            self.assertEqual(
                document_spy.call_args_list,
                [mock.call(filename, EXPECTED[filename]) for filename in sorted(EXPECTED)],
            )

    def test_packaging_lock_pins_exact_safe_argv_and_fw_add_is_forbidden(self):
        lock = EXPECTED["packaging.lock.json"]
        self.assertEqual(lock["nativeOutputs"], ["jl_isd.bin", "jl_isd.fw", "update.ufw"])
        self.assertEqual(lock["tools"]["fwAdd"]["invocation"], "FORBIDDEN")
        command = lock["isdArgv"]
        self.assertNotIn("-format", command)
        self.assertNotIn("-key", command)
        self.assertNotIn("-efuse", command)
        self.assertEqual(command[-4:], ["-output-fw", "jl_isd.fw", "-output-ufw", "update.ufw"])

    def test_model_lock_pins_exact_eleven_reference_members_and_refuses_binary_property_ini(self):
        lock = EXPECTED["model1552-package.lock.json"]
        self.assertEqual(len(lock["referenceFiles"]), 11)
        self.assertEqual(lock["resetPolicy"]["inputRelativePath"], "items/04_isd_config.ini")
        self.assertEqual(lock["resetPolicy"]["refusedBinaryPropertyPath"], "canonical-jl-unpack/top/isd_config.ini")
        self.assertNotIn(lock["resetPolicy"]["refusedBinaryPropertyPath"], lock["referenceFiles"])

    def test_every_lock_fails_closed_on_unknown_missing_wrong_type_and_identity_drift(self):
        mutations = []
        for filename, expected in EXPECTED.items():
            unknown = copy.deepcopy(expected)
            unknown["unknown"] = 1
            mutations.append((filename, unknown))
            missing = copy.deepcopy(expected)
            missing.pop("schema")
            mutations.append((filename, missing))
        wrong_digest = copy.deepcopy(TOOLCHAIN)
        wrong_digest["tools"]["clang"]["sha256"] = "0" * 64
        mutations.append(("toolchain.lock.json", wrong_digest))
        wrong_bool = copy.deepcopy(MODEL1552)
        wrong_bool["referenceFiles"]["manifest.json"]["byteLength"] = True
        mutations.append(("model1552-package.lock.json", wrong_bool))
        wrong_ini = copy.deepcopy(MODEL1552)
        wrong_ini["resetPolicy"]["inputRelativePath"] = "canonical-jl-unpack/top/isd_config.ini"
        mutations.append(("model1552-package.lock.json", wrong_ini))
        forbidden = copy.deepcopy(PACKAGING)
        forbidden["isdArgv"].append("-format")
        mutations.append(("packaging.lock.json", forbidden))
        nested_unknown = copy.deepcopy(TOOLCHAIN)
        nested_unknown["tools"]["clang"]["unknown"] = "x"
        mutations.append(("toolchain.lock.json", nested_unknown))
        nested_missing = copy.deepcopy(PACKAGING)
        nested_missing["tools"]["isdDownload"].pop("sha256")
        mutations.append(("packaging.lock.json", nested_missing))
        nested_type = copy.deepcopy(MODEL1552)
        nested_type["qixGolden"]["size"] = "1080387"
        mutations.append(("model1552-package.lock.json", nested_type))
        lowercase = copy.deepcopy(MODEL1552)
        lowercase["referenceFiles"]["manifest.json"]["sha256"] = lowercase["referenceFiles"]["manifest.json"]["sha256"].lower()
        mutations.append(("model1552-package.lock.json", lowercase))
        for filename, value in mutations:
            with self.subTest(filename=filename, mutation=value):
                with self.assertRaises(ValueError):
                    self.validator.validate_lock(filename, value)

    def test_loader_rejects_duplicate_keys_noncanonical_bytes_and_nested_file_drift(self):
        with tempfile.TemporaryDirectory(prefix="e87-lock-test-") as temp:
            root = Path(temp)
            duplicate = root / "duplicate.json"
            duplicate.write_bytes(b'{"schema":"x","schema":"y"}\n')
            with self.assertRaises(ValueError):
                self.validator.load_closed_json(duplicate)
            noncanonical = root / "noncanonical.json"
            noncanonical.write_bytes(b'{"z":1, "a":2}\n')
            with self.assertRaises(ValueError):
                self.validator.load_closed_json(noncanonical)

            repository = root / "repository"
            lock_root = repository / "firmware/locks"
            lock_root.mkdir(parents=True)
            for filename, expected in EXPECTED.items():
                (lock_root / filename).write_bytes(canonical(expected))
            self.assertEqual(self.validator.load_stage0_locks(repository), EXPECTED)
            mutated = copy.deepcopy(TOOLCHAIN)
            mutated["hostTools"]["python"]["version"] = "3.11.14"
            (lock_root / "toolchain.lock.json").write_bytes(canonical(mutated))
            with self.assertRaises(ValueError):
                self.validator.load_stage0_locks(repository)


if __name__ == "__main__":
    unittest.main()
