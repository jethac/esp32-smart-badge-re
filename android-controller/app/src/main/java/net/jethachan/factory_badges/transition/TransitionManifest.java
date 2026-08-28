package net.jethachan.factory_badges.transition;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Closed identity and content receipt for one explicitly lab-qualified firmware handoff. */
public final class TransitionManifest {
    private static final String CHIP = "AC707N";
    private static final String PROFILE = "E87-JD9855-R1";
    private static final String LAYOUT = "SINGLE_BANK";
    private static final int[] MIN_QIX_VERSION = new int[] {11, 1, 0, 4};
    private static final String[] ROLE_ORDER = new String[] {
            "appBin", "jlIsdFw", "updateUfw", "qix", "manifest", "sha256Sums"
    };
    private static final Set<String> ROOT_KEYS = setOf(
            "buildId", "chip", "files", "labEligible", "layout", "profile",
            "qixVersion", "releaseEligible", "releaseRoot", "schemaId",
            "schemaVersion", "semver");
    private static final Set<String> FILE_KEYS = setOf(
            "filename", "length", "role", "sha256");
    private static final Pattern BUILD_ID = Pattern.compile("[0-9A-F]{32}");
    private static final Pattern SHA256 = Pattern.compile("[0-9A-F]{64}");
    private static final Pattern SEMVER = Pattern.compile(
            "(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)");
    private static final Pattern BARE_FILENAME = Pattern.compile(
            "[A-Za-z0-9][A-Za-z0-9._-]*");
    private static final Pattern QIX_VERSION = Pattern.compile(
            "(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\."
            + "(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)");
    private static final long MAX_ARTIFACT = 32L * 1024L * 1024L;
    private static final long MAX_MANIFEST = 256L * 1024L;
    private static final long MAX_SHA256SUMS = 16L * 1024L;

    public static final class FileRecord {
        private final String role;
        private final String filename;
        private final int length;
        private final byte[] sha256;

        FileRecord(String role, String filename, int length, byte[] sha256) {
            this.role = role;
            this.filename = filename;
            this.length = length;
            this.sha256 = Arrays.copyOf(sha256, sha256.length);
        }

        public String role() { return role; }
        public String filename() { return filename; }
        public int length() { return length; }
        public byte[] sha256() { return Arrays.copyOf(sha256, sha256.length); }
    }

    private final String semver;
    private final String qixVersion;
    private final String releaseRoot;
    private final boolean releaseEligible;
    private final byte[] buildId;
    private final List<FileRecord> files;

    private TransitionManifest(String semver, String qixVersion, String releaseRoot,
            boolean releaseEligible, byte[] buildId, List<FileRecord> files) {
        this.semver = semver;
        this.qixVersion = qixVersion;
        this.releaseRoot = releaseRoot;
        this.releaseEligible = releaseEligible;
        this.buildId = Arrays.copyOf(buildId, buildId.length);
        this.files = Collections.unmodifiableList(new ArrayList<FileRecord>(files));
    }

    public static TransitionManifest parse(byte[] canonicalJson) {
        Map<String, Object> root = CanonicalJson.parseCanonicalObject(canonicalJson);
        requireExactKeys(root, ROOT_KEYS, "handoff receipt");
        if (!"e87-android-embed-v1".equals(string(root, "schemaId"))
                || integer(root, "schemaVersion") != 1L) {
            throw new IllegalArgumentException("unsupported handoff receipt schema");
        }
        if (!CHIP.equals(string(root, "chip"))) {
            throw new IllegalArgumentException("handoff chip is not AC707N");
        }
        if (!PROFILE.equals(string(root, "profile"))) {
            throw new IllegalArgumentException("handoff profile is not E87-JD9855-R1");
        }
        if (!LAYOUT.equals(string(root, "layout"))) {
            throw new IllegalArgumentException("handoff layout is not SINGLE_BANK");
        }
        String qixVersion = string(root, "qixVersion");
        requireSupportedQixVersion(qixVersion);
        if (!bool(root, "labEligible")) {
            throw new IllegalArgumentException("handoff is not explicitly lab eligible");
        }
        boolean releaseEligible = bool(root, "releaseEligible");
        String semver = string(root, "semver");
        Matcher semverMatch = SEMVER.matcher(semver);
        if (!semverMatch.matches()) {
            throw new IllegalArgumentException("handoff semver is not canonical");
        }
        for (int index = 1; index <= 3; index++) {
            if (Integer.parseInt(semverMatch.group(index)) > 255) {
                throw new IllegalArgumentException("handoff semver exceeds build-info bytes");
            }
        }
        String buildIdHex = string(root, "buildId");
        if (!BUILD_ID.matcher(buildIdHex).matches()) {
            throw new IllegalArgumentException("handoff build ID is not canonical");
        }
        String releaseRoot = string(root, "releaseRoot");
        if (!(PROFILE + "/" + semver + "/" + buildIdHex).equals(releaseRoot)) {
            throw new IllegalArgumentException("handoff release root differs from identity");
        }

        Object filesValue = root.get("files");
        if (!(filesValue instanceof List)) {
            throw new IllegalArgumentException("handoff files must be an array");
        }
        @SuppressWarnings("unchecked")
        List<Object> fileValues = (List<Object>) filesValue;
        if (fileValues.size() != ROLE_ORDER.length) {
            throw new IllegalArgumentException("handoff must have exactly six files");
        }
        List<FileRecord> records = new ArrayList<FileRecord>(ROLE_ORDER.length);
        for (int index = 0; index < ROLE_ORDER.length; index++) {
            Object value = fileValues.get(index);
            if (!(value instanceof Map)) {
                throw new IllegalArgumentException("handoff file record must be an object");
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> record = (Map<String, Object>) value;
            requireExactKeys(record, FILE_KEYS, "handoff file record");
            String role = string(record, "role");
            if (!ROLE_ORDER[index].equals(role)) {
                throw new IllegalArgumentException("handoff file role order is invalid");
            }
            String filename = string(record, "filename");
            if (!BARE_FILENAME.matcher(filename).matches()) {
                throw new IllegalArgumentException("handoff filename is not bare");
            }
            requireRoleFilename(role, filename, buildIdHex, qixVersion);
            long length = integer(record, "length");
            long cap = "manifest".equals(role) ? MAX_MANIFEST
                    : ("sha256Sums".equals(role) ? MAX_SHA256SUMS : MAX_ARTIFACT);
            if (length <= 0L || length > cap) {
                throw new IllegalArgumentException("handoff file length is invalid");
            }
            String digest = string(record, "sha256");
            if (!SHA256.matcher(digest).matches()) {
                throw new IllegalArgumentException("handoff SHA-256 is not canonical");
            }
            records.add(new FileRecord(role, filename, (int) length, decodeHex(digest)));
        }
        return new TransitionManifest(
                semver, qixVersion, releaseRoot, releaseEligible,
                decodeHex(buildIdHex), records);
    }

    public String chip() { return CHIP; }
    public String profile() { return PROFILE; }
    public String layout() { return LAYOUT; }
    public String qixVersion() { return qixVersion; }
    public String semver() { return semver; }
    public String releaseRoot() { return releaseRoot; }
    public boolean releaseEligible() { return releaseEligible; }
    public byte[] buildId() { return Arrays.copyOf(buildId, buildId.length); }
    public List<FileRecord> files() { return files; }

    FileRecord file(String role) {
        for (FileRecord record : files) {
            if (record.role.equals(role)) return record;
        }
        throw new IllegalArgumentException("unknown handoff file role");
    }

    private static void requireRoleFilename(
            String role, String filename, String buildId, String qixVersion) {
        String expected = null;
        if ("appBin".equals(role)) expected = "app.bin";
        if ("jlIsdFw".equals(role)) expected = "jl_isd.fw";
        if ("updateUfw".equals(role)) expected = "update.ufw";
        if ("manifest".equals(role)) expected = "manifest.json";
        if ("sha256Sums".equals(role)) expected = "SHA256SUMS";
        if (expected != null && !expected.equals(filename)) {
            throw new IllegalArgumentException("handoff role has an unexpected filename");
        }
        if ("qix".equals(role)) {
            String stem = "E87-" + qixVersion + "-";
            if (!(filename.equals(stem + buildId.substring(0, 8) + ".qix")
                    || filename.equals(stem + buildId + ".qix"))) {
                throw new IllegalArgumentException("Qix filename differs from build identity");
            }
        }
    }

    private static void requireSupportedQixVersion(String value) {
        Matcher match = QIX_VERSION.matcher(value);
        if (!match.matches() || value.length() > 10) {
            throw new IllegalArgumentException("handoff Qix version is not canonical");
        }
        int[] parts = new int[4];
        for (int index = 0; index < parts.length; index++) {
            try {
                parts[index] = Integer.parseInt(match.group(index + 1));
            } catch (NumberFormatException error) {
                throw new IllegalArgumentException("handoff Qix version component is invalid", error);
            }
            if (parts[index] > 255) {
                throw new IllegalArgumentException("handoff Qix version component exceeds byte");
            }
        }
        for (int index = 0; index < parts.length; index++) {
            if (parts[index] > MIN_QIX_VERSION[index]) return;
            if (parts[index] < MIN_QIX_VERSION[index]) {
                throw new IllegalArgumentException(
                        "handoff Qix version is not newer than sacrificial 11.1.0.3");
            }
        }
    }

    private static String string(Map<String, Object> value, String key) {
        Object item = value.get(key);
        if (!(item instanceof String)) {
            throw new IllegalArgumentException(key + " must be a string");
        }
        return (String) item;
    }

    private static long integer(Map<String, Object> value, String key) {
        Object item = value.get(key);
        if (!(item instanceof Long)) {
            throw new IllegalArgumentException(key + " must be an integer");
        }
        return ((Long) item).longValue();
    }

    private static boolean bool(Map<String, Object> value, String key) {
        Object item = value.get(key);
        if (!(item instanceof Boolean)) {
            throw new IllegalArgumentException(key + " must be boolean");
        }
        return ((Boolean) item).booleanValue();
    }

    private static void requireExactKeys(
            Map<String, Object> value, Set<String> keys, String label) {
        if (!value.keySet().equals(keys)) {
            throw new IllegalArgumentException(label + " keys are not closed");
        }
    }

    private static byte[] decodeHex(String value) {
        byte[] result = new byte[value.length() / 2];
        for (int index = 0; index < result.length; index++) {
            result[index] = (byte) Integer.parseInt(
                    value.substring(index * 2, index * 2 + 2), 16);
        }
        return result;
    }

    private static Set<String> setOf(String... values) {
        return Collections.unmodifiableSet(new HashSet<String>(Arrays.asList(values)));
    }
}
