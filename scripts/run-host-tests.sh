#!/bin/bash
set -euo pipefail

export LC_ALL=C
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
JAVA_HOME=/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64
JAVAC="$JAVA_HOME/bin/javac"
JAVA="$JAVA_HOME/bin/java"
PYTHON=/usr/bin/python3

OUT=$(mktemp -d /tmp/e87-one-shot-host-tests.XXXXXX)
case "$OUT" in
    /tmp/e87-one-shot-host-tests.*) ;;
    *) printf 'Unexpected test output path: %s\n' "$OUT" >&2; exit 1 ;;
esac
cleanup() {
    rm -rf -- "$OUT"
}
trap cleanup EXIT HUP INT TERM

find "$ROOT/src/main/java" -type f -name '*.java' \
    ! -name 'ProbeActivity.java' -print \
    | LC_ALL=C sort > "$OUT/java-sources.txt"
find "$ROOT/host-tests/src" -type f -name '*.java' -print \
    | LC_ALL=C sort >> "$OUT/java-sources.txt"

"$JAVAC" -encoding UTF-8 -source 8 -target 8 -Xlint:all,-options \
    -d "$OUT/classes" @"$OUT/java-sources.txt"
"$JAVA" -cp "$OUT/classes" com.openai.e87probe.ProbeCoreTest
"$JAVA" -cp "$OUT/classes" com.openai.e87probe.UploaderSafetyTest

cd "$ROOT"
"$PYTHON" -m unittest -v \
    host-tests/test_activity_safety.py \
    host-tests/test_build_contract.py \
    host-tests/test_generate_package_pin.py
