#!/bin/bash
set -euo pipefail

export LC_ALL=C

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)

JAVA_HOME=/home/jethac/.local/share/e87-dev/jdk-17/usr/lib/jvm/java-17-openjdk-amd64
ANDROID_SDK=/home/jethac/.local/share/e87-dev/android-sdk
ANDROID_JAR=/home/jethac/.local/share/e87-dev/android-sdk/platforms/android-34/android.jar
BUILD_TOOLS=/home/jethac/.local/share/e87-dev/android-sdk/build-tools/34.0.0
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"

JAVAC="$JAVA_HOME/bin/javac"
JAVA="$JAVA_HOME/bin/java"
JAR="$JAVA_HOME/bin/jar"
KEYTOOL="$JAVA_HOME/bin/keytool"
AAPT2="$BUILD_TOOLS/aapt2"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"
PYTHON=/usr/bin/python3

KEYSTORE="$ROOT/signing/debug.keystore"
ARM64_AUTH="$ROOT/vendor-lib/arm64-v8a/libjl_ota_auth.so"
ARMV7_AUTH="$ROOT/vendor-lib/armeabi-v7a/libjl_ota_auth.so"
EXPECTED_KEYSTORE_SHA256=80af017b00ff31f89f96a08f8f5066363d017b6396e8424e4caf2e7901620556
EXPECTED_ARM64_SHA256=d65dd43fb8eb284b93fcbd85c7ce4e59168f3673e28c7637ed467667e4cc5c4b
EXPECTED_ARMV7_SHA256=5e629e0e0190f745fade919bcca53a7638915b1f856537352977c8b5e0d214ce
EXPECTED_SIGNER_CERT_SHA256=c1492dba623bb541187d6db26b0559d4d0dbcf0ff2ce829317c73dab521b2ce5
EXPECTED_PACKAGE=com.openai.e87probe
EXPECTED_ACTIVITY=com.openai.e87probe.ProbeActivity
EXPECTED_LABEL="E87 One-Shot Lab Uploader"

PACKAGE_SIZE=
PACKAGE_SHA256=
PACKAGE_HEADER=
OUTPUT="$ROOT/build/e87-one-shot-lab-uploader.apk"

usage() {
    printf '%s\n' \
        "Usage: $0 --package-size BYTES --package-sha256 HEX --package-header HEX [--output APK]" \
        "" \
        "All three reviewed Qix identity values are mandatory. No package bytes are embedded."
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --package-size)
            [ "$#" -ge 2 ] || die "--package-size requires a value"
            PACKAGE_SIZE="$2"
            shift 2
            ;;
        --package-sha256)
            [ "$#" -ge 2 ] || die "--package-sha256 requires a value"
            PACKAGE_SHA256="$2"
            shift 2
            ;;
        --package-header)
            [ "$#" -ge 2 ] || die "--package-header requires a value"
            PACKAGE_HEADER="$2"
            shift 2
            ;;
        --output)
            [ "$#" -ge 2 ] || die "--output requires a value"
            OUTPUT="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

[ -n "$PACKAGE_SIZE" ] || die "--package-size is required"
[ -n "$PACKAGE_SHA256" ] || die "--package-sha256 is required"
[ -n "$PACKAGE_HEADER" ] || die "--package-header is required"
case "$OUTPUT" in
    /*) ;;
    *) OUTPUT="$ROOT/$OUTPUT" ;;
esac
case "$OUTPUT" in
    *.apk) ;;
    *) die "--output must end in .apk" ;;
esac
[ ! -L "$OUTPUT" ] || die "refusing to overwrite a symlink output"

require_file() {
    [ -f "$1" ] || die "required file is missing: $1"
}

require_executable() {
    [ -x "$1" ] || die "required executable is missing: $1"
}

verify_sha256() {
    actual=$(sha256sum "$1" | awk '{print $1}')
    [ "$actual" = "$2" ] || die "SHA-256 mismatch for $1: $actual"
}

for executable in "$JAVAC" "$JAVA" "$JAR" "$KEYTOOL" \
        "$AAPT2" "$D8" "$ZIPALIGN" "$APKSIGNER" "$PYTHON"; do
    require_executable "$executable"
done
require_file "$ANDROID_JAR"
require_file "$KEYSTORE"
require_file "$ARM64_AUTH"
require_file "$ARMV7_AUTH"
require_file "$ROOT/src/main/AndroidManifest.xml"
require_file "$ROOT/scripts/generate-package-pin.py"

verify_sha256 "$KEYSTORE" "$EXPECTED_KEYSTORE_SHA256"
verify_sha256 "$ARM64_AUTH" "$EXPECTED_ARM64_SHA256"
verify_sha256 "$ARMV7_AUTH" "$EXPECTED_ARMV7_SHA256"

KEYSTORE_CERT=$("$KEYTOOL" -list -v \
    -keystore "$KEYSTORE" -storepass android -alias androiddebugkey \
    | awk '/SHA256:/{value=$2; gsub(":", "", value); print tolower(value); exit}')
[ "$KEYSTORE_CERT" = "$EXPECTED_SIGNER_CERT_SHA256" ] \
    || die "staged keystore certificate mismatch: $KEYSTORE_CERT"

WORK=$(mktemp -d /tmp/e87-one-shot-build.XXXXXX)
case "$WORK" in
    /tmp/e87-one-shot-build.*) ;;
    *) die "unexpected temporary build path: $WORK" ;;
esac
cleanup() {
    rm -rf -- "$WORK"
}
trap cleanup EXIT HUP INT TERM

GENERATED="$WORK/generated/com/openai/e87probe/GeneratedPackagePin.java"
CLASSES="$WORK/classes"
DEX="$WORK/dex"
ADD="$WORK/add"
AUDIT="$WORK/audit"
mkdir -p "$CLASSES" "$DEX" "$ADD/lib/arm64-v8a" "$ADD/lib/armeabi-v7a" "$AUDIT"

"$PYTHON" "$ROOT/scripts/generate-package-pin.py" \
    --size "$PACKAGE_SIZE" \
    --sha256 "$PACKAGE_SHA256" \
    --header "$PACKAGE_HEADER" \
    --output "$GENERATED"

find "$ROOT/src/main/java" -type f -name '*.java' -print \
    | LC_ALL=C sort > "$WORK/java-sources.txt"
printf '%s\n' "$GENERATED" >> "$WORK/java-sources.txt"
"$JAVAC" -encoding UTF-8 -source 8 -target 8 -Xlint:all,-options \
    -cp "$ANDROID_JAR" -d "$CLASSES" @"$WORK/java-sources.txt"

"$JAR" --create --file "$WORK/classes.jar" -C "$CLASSES" .
"$D8" --lib "$ANDROID_JAR" --min-api 31 \
    --output "$DEX" "$WORK/classes.jar"

"$AAPT2" link \
    -o "$WORK/base.apk" \
    -I "$ANDROID_JAR" \
    --manifest "$ROOT/src/main/AndroidManifest.xml" \
    --min-sdk-version 31 \
    --target-sdk-version 31 \
    --version-code 1 \
    --version-name 1.0

cp "$WORK/base.apk" "$WORK/unaligned.apk"
cp "$DEX/classes.dex" "$ADD/classes.dex"
cp "$ARM64_AUTH" "$ADD/lib/arm64-v8a/libjl_ota_auth.so"
cp "$ARMV7_AUTH" "$ADD/lib/armeabi-v7a/libjl_ota_auth.so"
"$JAR" --update --file "$WORK/unaligned.apk" \
    -C "$ADD" classes.dex \
    -C "$ADD" lib/arm64-v8a/libjl_ota_auth.so \
    -C "$ADD" lib/armeabi-v7a/libjl_ota_auth.so

"$ZIPALIGN" -p -f 4 "$WORK/unaligned.apk" "$WORK/aligned.apk"
"$APKSIGNER" sign \
    --ks "$KEYSTORE" \
    --ks-key-alias androiddebugkey \
    --ks-pass pass:android \
    --key-pass pass:android \
    --out "$WORK/signed.apk" \
    "$WORK/aligned.apk"

"$ZIPALIGN" -c -p 4 "$WORK/signed.apk"
VERIFY_OUTPUT=$("$APKSIGNER" verify --verbose --print-certs "$WORK/signed.apk")
printf '%s\n' "$VERIFY_OUTPUT"
SIGNER_CERT=$(printf '%s\n' "$VERIFY_OUTPUT" \
    | awk -F': ' '/certificate SHA-256 digest:/{print tolower($2); exit}')
[ "$SIGNER_CERT" = "$EXPECTED_SIGNER_CERT_SHA256" ] \
    || die "signed APK certificate mismatch: $SIGNER_CERT"

BADGING=$("$AAPT2" dump badging "$WORK/signed.apk")
grep -Fq "package: name='$EXPECTED_PACKAGE'" <<< "$BADGING" \
    || die "APK package identity mismatch"
grep -Fq "launchable-activity: name='$EXPECTED_ACTIVITY'" <<< "$BADGING" \
    || die "APK launchable activity mismatch"
MANIFEST_TREE=$("$AAPT2" dump xmltree "$WORK/signed.apk" --file AndroidManifest.xml)
grep -Fq "android:label(0x01010001)=\"$EXPECTED_LABEL\"" <<< "$MANIFEST_TREE" \
    || die "APK label mismatch"

ENTRIES=$("$JAR" tf "$WORK/signed.apk")
require_entry() {
    grep -Fxq "$1" <<< "$ENTRIES" \
        || die "required APK entry is missing: $1"
}
require_entry classes.dex
require_entry lib/arm64-v8a/libjl_ota_auth.so
require_entry lib/armeabi-v7a/libjl_ota_auth.so
if printf '%s\n' "$ENTRIES" \
        | grep -Eiq '(^|/)(update[.]bin|debug[.]keystore)$|[.](qix|fw)$|^assets/'; then
    die "APK contains a forbidden payload, signing key, or fallback asset"
fi

(
    cd "$AUDIT"
    "$JAR" xf "$WORK/signed.apk" \
        lib/arm64-v8a/libjl_ota_auth.so \
        lib/armeabi-v7a/libjl_ota_auth.so
)
verify_sha256 "$AUDIT/lib/arm64-v8a/libjl_ota_auth.so" "$EXPECTED_ARM64_SHA256"
verify_sha256 "$AUDIT/lib/armeabi-v7a/libjl_ota_auth.so" "$EXPECTED_ARMV7_SHA256"

OUTPUT_DIRECTORY=$(dirname -- "$OUTPUT")
mkdir -p "$OUTPUT_DIRECTORY"
install -m 0644 "$WORK/signed.apk" "$OUTPUT"
cmp -s "$WORK/signed.apk" "$OUTPUT" || die "final APK copy differs from audited APK"

APK_SHA256=$(sha256sum "$OUTPUT" | awk '{print $1}')
printf '%s\n' \
    "APK=$OUTPUT" \
    "APK_SHA256=$APK_SHA256" \
    "PACKAGE=$EXPECTED_PACKAGE" \
    "ACTIVITY=$EXPECTED_ACTIVITY" \
    "LABEL=$EXPECTED_LABEL" \
    "SIGNER_CERT_SHA256=$SIGNER_CERT"
