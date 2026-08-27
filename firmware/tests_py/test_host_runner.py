#!/usr/bin/env python3
"""Integration tests for the portable E87 firmware host-test runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "firmware" / "tools" / "test-host.py"
HOST_CC = os.environ.get("E87_HOST_CC", "/usr/bin/gcc-11")
TEST_ROOT = REPO_ROOT / "firmware" / ".host-build" / "python-tests"
COMPILER_SHA256 = "821af3c74506283c179ca413bb33e6b528805a4dd8a5c09df125e5ad560a9e89"


class HostRunnerIntegrationTest(unittest.TestCase):
    """Exercise the real runner through its command-line boundary."""

    def setUp(self) -> None:
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=TEST_ROOT))
        self.build_root = self.root / "build"
        self.build_root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    @classmethod
    def tearDownClass(cls) -> None:
        for candidate in (TEST_ROOT, REPO_ROOT / "firmware" / ".host-build"):
            try:
                candidate.rmdir()
            except (FileNotFoundError, OSError):
                pass

    def relative(self, path: Path) -> str:
        return path.relative_to(REPO_ROOT).as_posix()

    def run_runner(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["LC_ALL"] = "C"
        environment["TZ"] = "UTC"
        return subprocess.run(
            [sys.executable, str(RUNNER), *arguments],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
        )

    def harness_arguments(self, reproducible: bool = False) -> list[str]:
        result = [
            "--suite",
            "harness",
            "--cc",
            HOST_CC,
            "--require-compiler-sha256",
            COMPILER_SHA256,
            "--build-root",
            self.relative(self.build_root),
        ]
        if reproducible:
            result.append("--verify-reproducible")
        return result

    def make_spy_compiler(self) -> tuple[str, Path]:
        marker = self.root / "compiler-was-invoked"
        compiler = self.root / "spy-compiler"
        compiler.write_text(
            "#!/bin/sh\n"
            f"printf invoked > '{marker.as_posix()}'\n"
            f"exec '{HOST_CC}' \"$@\"\n",
            encoding="utf-8",
        )
        compiler.chmod(compiler.stat().st_mode | stat.S_IXUSR)
        return str(compiler), marker

    def write_manifest(self, value: dict[str, object], name: str) -> str:
        path = self.root / name
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.relative(path)

    def write_raw_manifest(self, value: str, name: str) -> str:
        path = self.root / name
        path.write_text(value, encoding="utf-8")
        return self.relative(path)

    def assert_manifest_rejected_without_compiler(
        self, manifest: str, diagnostic: str
    ) -> None:
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "harness",
            "--manifest",
            manifest,
            "--cc",
            compiler,
            "--build-root",
            self.relative(self.build_root),
        )
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("manifest", result.stderr.lower())
        self.assertIn(diagnostic, result.stderr.lower())
        self.assertFalse(marker.exists(), "invalid manifest invoked compiler")
        self.assertEqual([], list(self.build_root.rglob("receipt.json")))

    @staticmethod
    def valid_manifest() -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "includeDirectories": [
                "firmware/host",
                "firmware/overlay/SDK/apps/watch/include",
            ],
            "suites": {
                "harness": [
                    {
                        "name": "buffer-budget",
                        "test": "firmware/host/test_harness.c",
                        "sources": [],
                    }
                ]
            },
        }

    def test_harness_suite_compiles_runs_and_reports_exact_input_set(self) -> None:
        # Break caught: omitting an input, silently adding SDK code, or not running C.
        result = self.run_runner(*self.harness_arguments())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stderr)
        self.assertIn("RUN buffer-budget::display_geometry\n", result.stdout)
        self.assertIn(
            "PASS buffer-budget::strip_buffer_budget assertions=5\n", result.stdout
        )
        self.assertIn(
            "SUMMARY buffer-budget tests=2 passed=2 failed=0 assertions=8\n",
            result.stdout,
        )
        receipts = list(self.build_root.rglob("receipt.json"))
        self.assertEqual(1, len(receipts), receipts)
        raw = receipts[0].read_text(encoding="utf-8")
        receipt = json.loads(raw)
        self.assertEqual(json.dumps(receipt, indent=2, sort_keys=True) + "\n", raw)
        self.assertEqual(
            [{"case": "buffer-budget", "suite": "harness"}],
            receipt["requestedCases"],
        )
        self.assertEqual(
            ["firmware/host/test_main.c", "firmware/host/test_harness.c"],
            [entry["path"] for entry in receipt["sources"]],
        )
        self.assertEqual(
            [
                "firmware/host/test_support.h",
                "firmware/overlay/SDK/apps/watch/include/e87/e87_types.h",
            ],
            [entry["path"] for entry in receipt["headers"]],
        )
        self.assertIn("-DE87_HOST_TEST=1", receipt["compileArguments"])
        self.assertEqual(0, receipt["process"]["exitStatus"])

    def test_unknown_suite_is_rejected_before_compiler_lookup(self) -> None:
        # Break caught: resolving or running a compiler before request validation.
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "does-not-exist",
            "--cc",
            compiler,
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("unknown suite", result.stderr.lower())
        self.assertFalse(marker.exists())
        self.assertEqual([], list(self.build_root.rglob("receipt.json")))

    def test_manifest_traversal_is_rejected_before_compiler_lookup(self) -> None:
        # Break caught: normalizing '..' into an out-of-repository compiler input.
        manifest = self.valid_manifest()
        suites = manifest["suites"]
        assert isinstance(suites, dict)
        cases = suites["harness"]
        assert isinstance(cases, list)
        cases[0]["test"] = "../outside.c"
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "harness",
            "--manifest",
            self.write_manifest(manifest, "traversal.json"),
            "--cc",
            compiler,
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("manifest", result.stderr.lower())
        self.assertIn("traversal", result.stderr.lower())
        self.assertFalse(marker.exists())

    def test_wrong_required_digest_is_rejected_before_compiler_execution(self) -> None:
        # Break caught: invoking an executable whose bytes do not match the pin.
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "harness",
            "--cc",
            compiler,
            "--require-compiler-sha256",
            "0" * 64,
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("compiler sha-256 mismatch", result.stderr.lower())
        self.assertFalse(marker.exists())
        self.assertEqual([], list(self.build_root.rglob("receipt.json")))

    def test_explicit_failing_c_fixture_returns_exit_one(self) -> None:
        # Break caught: treating a real failed C assertion as a successful run.
        result = self.run_runner(
            "--suite",
            "harness-failure",
            "--manifest",
            "firmware/host/fixtures/failing-suites.json",
            "--cc",
            HOST_CC,
            "--require-compiler-sha256",
            COMPILER_SHA256,
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("FAIL expected-failure::intentional_failure", result.stdout)
        self.assertIn("expression=UINT32_C(2) expected=1 actual=2 assertions=1", result.stdout)
        self.assertIn("FAIL expected-failure::zero_assertions", result.stdout)
        self.assertIn("expression=at least one assertion expected=1 actual=0", result.stdout)
        self.assertIn(
            "SUMMARY expected-failure tests=2 passed=0 failed=2 assertions=1",
            result.stdout,
        )

    def test_reproducibility_mode_builds_twice_and_compares(self) -> None:
        # Break caught: claiming reproducibility after one build or unequal evidence.
        result = self.run_runner(*self.harness_arguments(reproducible=True))

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("REPRODUCIBLE harness/buffer-budget", result.stdout)
        receipts = sorted(self.build_root.rglob("receipt.json"))
        executables = sorted(self.build_root.rglob("host-test"))
        self.assertEqual(2, len(receipts), receipts)
        self.assertEqual(2, len(executables), executables)
        self.assertEqual(executables[0].read_bytes(), executables[1].read_bytes())
        first, second = [json.loads(path.read_text(encoding="utf-8")) for path in receipts]
        self.assertEqual(first["executable"]["sha256"], second["executable"]["sha256"])
        self.assertEqual(first["compileArguments"], second["compileArguments"])
        self.assertEqual("BUILD/host-test", first["compileArguments"][-1])
        self.assertNotIn("invocation-", " ".join(first["compileArguments"]))
        self.assertEqual(first["process"], second["process"])

    def test_list_validates_without_invoking_compiler(self) -> None:
        # Break caught: --list compiling code or exposing fixture-only entries.
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "all",
            "--list",
            "--cc",
            compiler,
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("harness\n", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual([], list(self.build_root.rglob("receipt.json")))

    def test_manifest_schema_errors_fail_before_compiler_lookup(self) -> None:
        # Break caught: permissive parsing of unknown keys or wrong JSON types.
        cases: list[tuple[str, dict[str, object], str]] = []
        unknown = self.valid_manifest()
        unknown["unexpected"] = True
        cases.append(("unknown", unknown, "unknown key"))
        schema = self.valid_manifest()
        schema["schemaVersion"] = "1"
        cases.append(("schema", schema, "schemaversion"))
        includes = self.valid_manifest()
        includes["includeDirectories"] = "firmware/host"
        cases.append(("includes", includes, "includedirectories"))
        suites = self.valid_manifest()
        suites["suites"] = []
        cases.append(("suites", suites, "suites"))
        case_key = self.valid_manifest()
        case_key["suites"]["harness"][0]["extra"] = True
        cases.append(("case-key", case_key, "unknown key"))
        sources = self.valid_manifest()
        sources["suites"]["harness"][0]["sources"] = "none"
        cases.append(("sources", sources, "sources"))
        for index, (name, manifest, diagnostic) in enumerate(cases):
            with self.subTest(name=name):
                self.assert_manifest_rejected_without_compiler(
                    self.write_manifest(manifest, f"schema-{index}.json"),
                    diagnostic,
                )

    def test_duplicate_json_keys_fail_before_compiler_lookup(self) -> None:
        # Break caught: JSON parsing that silently lets a later key override a pin.
        raw = (
            '{"schemaVersion":1,"schemaVersion":1,'
            '"includeDirectories":["firmware/host"],"suites":{}}\n'
        )
        self.assert_manifest_rejected_without_compiler(
            self.write_raw_manifest(raw, "duplicate.json"), "duplicate"
        )

    def test_reserved_empty_and_duplicate_declarations_fail_closed(self) -> None:
        # Break caught: ambiguous suite/case/include/test declarations.
        reserved = self.valid_manifest()
        reserved["suites"] = {"all": reserved["suites"]["harness"]}
        empty_suite = self.valid_manifest()
        empty_suite["suites"] = {"": empty_suite["suites"]["harness"]}
        duplicate_include = self.valid_manifest()
        duplicate_include["includeDirectories"] = [
            "firmware/host",
            "firmware/host",
        ]
        duplicate_case = self.valid_manifest()
        duplicate_case["suites"]["harness"].append(
            {
                "name": "buffer-budget",
                "test": "firmware/host/fixtures/test_expected_failure.c",
                "sources": [],
            }
        )
        duplicate_test = self.valid_manifest()
        duplicate_test["suites"]["harness"].append(
            {
                "name": "different-name",
                "test": "firmware/host/test_harness.c",
                "sources": [],
            }
        )
        cases = [
            (reserved, "reserved"),
            (empty_suite, "nonempty"),
            (duplicate_include, "duplicate include"),
            (duplicate_case, "duplicate case"),
            (duplicate_test, "duplicate test"),
        ]
        for index, (manifest, diagnostic) in enumerate(cases):
            with self.subTest(index=index):
                self.assert_manifest_rejected_without_compiler(
                    self.write_manifest(manifest, f"duplicate-{index}.json"),
                    diagnostic,
                )

    def test_path_syntax_attacks_fail_before_compiler_lookup(self) -> None:
        # Break caught: traversal, glob, response-file, NUL, or shell-like input.
        bad_paths = [
            "/tmp/test_escape.c",
            "C:/test_escape.c",
            "firmware//host/test_harness.c",
            "firmware/./host/test_harness.c",
            "firmware/../host/test_harness.c",
            "firmware/host/test_*.c",
            "@firmware/host/test_harness.c",
            "firmware/host/test_harness.c;true",
            "firmware/host/test_harness.c\x00ignored",
        ]
        for index, bad_path in enumerate(bad_paths):
            with self.subTest(path=bad_path):
                manifest = self.valid_manifest()
                manifest["suites"]["harness"][0]["test"] = bad_path
                self.assert_manifest_rejected_without_compiler(
                    self.write_manifest(manifest, f"path-{index}.json"), "path"
                )

    def test_test_source_and_include_allowlists_fail_closed(self) -> None:
        # Break caught: compiling arbitrary repository or binary-like inputs.
        mutations = [
            ("test", "firmware/host/harness.c", "allowlist"),
            ("test", "firmware/host/test_harness.o", "extension"),
            ("test", "firmware/generated/test_harness.c", "allowlist"),
            ("source", "firmware/host/test_harness.c", "allowlist"),
            ("source", "firmware/generated/production.o", "extension"),
            ("include", "firmware/overlay/SDK/apps/watch/e87", "allowlist"),
            ("test", "firmware/host/test_missing.c", "missing"),
        ]
        for index, (kind, value, diagnostic) in enumerate(mutations):
            with self.subTest(kind=kind, value=value):
                manifest = self.valid_manifest()
                if kind == "test":
                    manifest["suites"]["harness"][0]["test"] = value
                elif kind == "source":
                    manifest["suites"]["harness"][0]["sources"] = [value]
                else:
                    manifest["includeDirectories"] = [value]
                self.assert_manifest_rejected_without_compiler(
                    self.write_manifest(manifest, f"allowlist-{index}.json"),
                    diagnostic,
                )

    def test_symlinked_manifest_fails_before_compiler_lookup(self) -> None:
        # Break caught: an in-repository spelling that follows a symlinked input.
        link = self.root / "linked-manifest.json"
        os.symlink(REPO_ROOT / "firmware" / "host" / "suites.json", link)
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "harness",
            "--manifest",
            self.relative(link),
            "--cc",
            compiler,
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(marker.exists())

    def test_build_root_outside_reserved_tree_is_rejected(self) -> None:
        # Break caught: writing or cleaning output outside firmware/.host-build.
        external = Path(tempfile.gettempdir()) / "e87-host-runner-outside"
        if external.exists():
            self.fail(f"test precondition path already exists: {external}")
        result = self.run_runner(
            "--suite",
            "harness",
            "--cc",
            HOST_CC,
            "--build-root",
            str(external),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("build root", result.stderr.lower())
        self.assertFalse(external.exists())

    def test_compiler_value_is_one_executable_not_a_shell_fragment(self) -> None:
        # Break caught: interpreting --cc as a command line through a shell.
        result = self.run_runner(
            "--suite",
            "harness",
            "--cc",
            f"{HOST_CC} --version",
            "--build-root",
            self.relative(self.build_root),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("compiler", result.stderr.lower())
        self.assertEqual([], list(self.build_root.rglob("receipt.json")))

    def test_suite_and_case_names_cannot_escape_build_tree(self) -> None:
        # Break caught: suite/case names becoming traversal-capable output paths.
        suite_name = self.valid_manifest()
        suite_name["suites"] = {
            "../escape": suite_name["suites"]["harness"],
        }
        case_name = self.valid_manifest()
        case_name["suites"]["harness"][0]["name"] = "../../escape"
        for index, manifest in enumerate((suite_name, case_name)):
            with self.subTest(index=index):
                self.assert_manifest_rejected_without_compiler(
                    self.write_manifest(manifest, f"name-{index}.json"), "name"
                )

    def test_symlinked_build_root_is_rejected_before_compiler_execution(self) -> None:
        # Break caught: resolving away a symlink before checking the caller path.
        real_build = self.root / "real-build"
        real_build.mkdir()
        linked_build = self.root / "linked-build"
        os.symlink(real_build, linked_build)
        compiler, marker = self.make_spy_compiler()
        result = self.run_runner(
            "--suite",
            "harness",
            "--cc",
            compiler,
            "--build-root",
            self.relative(linked_build),
        )

        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("build root", result.stderr.lower())
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(marker.exists())

    def test_duplicate_source_entries_fail_before_compiler_lookup(self) -> None:
        # Break caught: compiling the same production translation unit twice.
        fake_root = REPO_ROOT / "firmware" / "host" / "fakes"
        fake_root.mkdir(parents=True, exist_ok=True)
        source = fake_root / "duplicate_source_fixture.c"
        source.write_text("int e87_duplicate_source_fixture;\n", encoding="utf-8")
        try:
            manifest = self.valid_manifest()
            source_spelling = self.relative(source)
            manifest["suites"]["harness"][0]["sources"] = [
                source_spelling,
                source_spelling,
            ]
            self.assert_manifest_rejected_without_compiler(
                self.write_manifest(manifest, "duplicate-source.json"),
                "duplicate source",
            )
        finally:
            source.unlink(missing_ok=True)
            try:
                fake_root.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
