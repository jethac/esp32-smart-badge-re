package net.jethachan.factory_badges.transition;

import java.io.ByteArrayOutputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Reopens and validates the complete embedded release before exposing transfer bytes. */
public final class TransitionArtifactValidator {
    private static final String INDEX_PATH = "e87/default-release.json";
    private static final int MAX_INDEX = 256 * 1024;
    private static final int MAX_TREE_DEPTH = 8;
    private static final int MAX_TREE_ENTRIES = 32;
    private static final Pattern ASSET_SEGMENT = Pattern.compile(
            "[A-Za-z0-9][A-Za-z0-9._-]*");

    public interface AssetSource {
        String[] list(String path) throws IOException;
        InputStream open(String path) throws IOException;
    }

    static final class MissingIndexException extends IOException {
        MissingIndexException(FileNotFoundException cause) {
            super(cause);
        }
    }

    public TransitionArtifact validate(AssetSource source) throws IOException {
        if (source == null) {
            throw new IllegalArgumentException("asset source must not be null");
        }
        final byte[] index;
        try {
            index = readBounded(source, INDEX_PATH, MAX_INDEX);
        } catch (FileNotFoundException missing) {
            throw new MissingIndexException(missing);
        }
        TransitionManifest manifest = TransitionManifest.parse(index);
        Set<String> expected = new HashSet<String>();
        expected.add(INDEX_PATH);
        for (TransitionManifest.FileRecord record : manifest.files()) {
            expected.add(assetPath(manifest, record));
        }
        Set<String> actual = new HashSet<String>();
        enumerate(source, "e87", 0, actual);
        if (!actual.equals(expected)) {
            throw new IllegalArgumentException("embedded E87 asset inventory is not closed");
        }

        Map<String, byte[]> byRole = new HashMap<String, byte[]>();
        for (TransitionManifest.FileRecord record : manifest.files()) {
            byte[] data = readBounded(source, assetPath(manifest, record), record.length());
            if (data.length != record.length()) {
                throw new IllegalArgumentException("embedded release length mismatch");
            }
            if (!MessageDigest.isEqual(record.sha256(), sha256(data))) {
                throw new IllegalArgumentException("embedded release hash mismatch");
            }
            byRole.put(record.role(), data);
        }
        validateSums(manifest, byRole);
        validateFirmwareManifest(byRole.get("manifest"));
        byte[] qix = byRole.get("qix");
        byte[] ufw = byRole.get("updateUfw");
        validateQix(qix, ufw, manifest.qixVersion());
        return new TransitionArtifact(
                Arrays.copyOf(qix, 27),
                ufw,
                sha256(qix),
                manifest.buildId());
    }

    private static String assetPath(
            TransitionManifest manifest, TransitionManifest.FileRecord record) {
        return "e87/" + manifest.releaseRoot() + "/" + record.filename();
    }

    private static void enumerate(
            AssetSource source, String path, int depth, Set<String> files) throws IOException {
        if (depth > MAX_TREE_DEPTH) {
            throw new IllegalArgumentException("embedded E87 asset tree is too deep");
        }
        String[] children = source.list(path);
        if (children == null) {
            throw new IllegalArgumentException("asset source returned a null directory listing");
        }
        Set<String> unique = new HashSet<String>();
        for (String child : children) {
            if (child == null || !ASSET_SEGMENT.matcher(child).matches()
                    || !unique.add(child)) {
                throw new IllegalArgumentException("embedded E87 asset name is invalid");
            }
            String nested = path + "/" + child;
            String[] descendants = source.list(nested);
            if (descendants == null) {
                throw new IllegalArgumentException("asset source returned a null listing");
            }
            if (descendants.length == 0) {
                if (!files.add(nested) || files.size() > MAX_TREE_ENTRIES) {
                    throw new IllegalArgumentException("embedded E87 asset inventory is invalid");
                }
            } else {
                enumerateKnown(source, nested, descendants, depth + 1, files);
            }
        }
    }

    private static void enumerateKnown(AssetSource source, String path, String[] children,
            int depth, Set<String> files) throws IOException {
        if (depth > MAX_TREE_DEPTH) {
            throw new IllegalArgumentException("embedded E87 asset tree is too deep");
        }
        Set<String> unique = new HashSet<String>();
        for (String child : children) {
            if (child == null || !ASSET_SEGMENT.matcher(child).matches()
                    || !unique.add(child)) {
                throw new IllegalArgumentException("embedded E87 asset name is invalid");
            }
            String nested = path + "/" + child;
            String[] descendants = source.list(nested);
            if (descendants == null) {
                throw new IllegalArgumentException("asset source returned a null listing");
            }
            if (descendants.length == 0) {
                if (!files.add(nested) || files.size() > MAX_TREE_ENTRIES) {
                    throw new IllegalArgumentException("embedded E87 asset inventory is invalid");
                }
            } else {
                enumerateKnown(source, nested, descendants, depth + 1, files);
            }
        }
    }

    private static byte[] readBounded(AssetSource source, String path, int cap)
            throws IOException {
        try (InputStream stream = source.open(path)) {
            if (stream == null) {
                throw new IllegalArgumentException("asset source returned null stream");
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream(Math.min(cap, 8192));
            byte[] buffer = new byte[8192];
            int total = 0;
            while (true) {
                int count = stream.read(buffer);
                if (count < 0) break;
                if (count == 0) {
                    int single = stream.read();
                    if (single < 0) break;
                    if (++total > cap) throw new IllegalArgumentException("asset exceeds cap");
                    output.write(single);
                    continue;
                }
                total += count;
                if (total > cap) throw new IllegalArgumentException("asset exceeds cap");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }

    private static void validateSums(
            TransitionManifest manifest, Map<String, byte[]> byRole) {
        List<String> names = new ArrayList<String>();
        Map<String, byte[]> byName = new HashMap<String, byte[]>();
        for (TransitionManifest.FileRecord record : manifest.files()) {
            if (!"sha256Sums".equals(record.role())) {
                names.add(record.filename());
                byName.put(record.filename(), byRole.get(record.role()));
            }
        }
        Collections.sort(names);
        StringBuilder expected = new StringBuilder();
        for (String name : names) {
            expected.append(hex(sha256(byName.get(name)))).append(" *")
                    .append(name).append('\n');
        }
        if (!Arrays.equals(expected.toString().getBytes(StandardCharsets.US_ASCII),
                byRole.get("sha256Sums"))) {
            throw new IllegalArgumentException("embedded SHA256SUMS is noncanonical");
        }
    }

    private static void validateFirmwareManifest(byte[] data) {
        Map<String, Object> manifest = CanonicalJson.parseCanonicalObject(data);
        Object schema = manifest.get("schema");
        if (!(schema instanceof String) || ((String) schema).isEmpty()) {
            throw new IllegalArgumentException("firmware manifest has no schema identity");
        }
        if (manifest.containsKey("labEligible")
                && !Boolean.TRUE.equals(manifest.get("labEligible"))) {
            throw new IllegalArgumentException("firmware manifest contradicts lab eligibility");
        }
    }

    private static void validateQix(byte[] qix, byte[] ufw, String expectedVersion) {
        if (qix == null || qix.length < 27 || ufw == null || ufw.length == 0) {
            throw new IllegalArgumentException("Qix header or payload is missing");
        }
        if ((qix[0] & 0xFF) != 0xBC || (qix[1] & 0xFF) != 0xAF
                || (qix[2] & 0xFF) != 1) {
            throw new IllegalArgumentException("Qix magic or type is invalid");
        }
        int end = 3;
        while (end < 13 && qix[end] != 0) end++;
        if (end == 3) throw new IllegalArgumentException("Qix version is empty");
        for (int index = end; index < 13; index++) {
            if (qix[index] != 0) {
                throw new IllegalArgumentException("Qix version padding is noncanonical");
            }
        }
        String version = new String(qix, 3, end - 3, StandardCharsets.US_ASCII);
        if (!expectedVersion.equals(version)) {
            throw new IllegalArgumentException("Qix version differs from handoff");
        }
        for (int index = 17; index < 25; index++) {
            if (qix[index] != 0) {
                throw new IllegalArgumentException("Qix reserved bytes are nonzero");
            }
        }
        long declared = unsignedU32(qix, 13);
        if (declared != qix.length - 27L || declared != ufw.length) {
            throw new IllegalArgumentException("Qix payload length is invalid");
        }
        byte[] payload = Arrays.copyOfRange(qix, 27, qix.length);
        int storedCrc = (qix[25] & 0xFF) | ((qix[26] & 0xFF) << 8);
        if (storedCrc != crc16(payload)) {
            throw new IllegalArgumentException("Qix payload CRC is invalid");
        }
        if (!Arrays.equals(payload, ufw)) {
            throw new IllegalArgumentException("Qix payload differs from update.ufw");
        }
    }

    private static long unsignedU32(byte[] data, int offset) {
        return ((long) data[offset] & 0xFFL)
                | (((long) data[offset + 1] & 0xFFL) << 8)
                | (((long) data[offset + 2] & 0xFFL) << 16)
                | (((long) data[offset + 3] & 0xFFL) << 24);
    }

    private static int crc16(byte[] data) {
        int crc = 0xFFFF;
        for (byte item : data) {
            crc ^= (item & 0xFF) << 8;
            for (int bit = 0; bit < 8; bit++) {
                crc = ((crc << 1) ^ ((crc & 0x8000) == 0 ? 0 : 0x1021)) & 0xFFFF;
            }
        }
        return crc;
    }

    private static byte[] sha256(byte[] data) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(data);
        } catch (NoSuchAlgorithmException failure) {
            throw new IllegalStateException("SHA-256 is unavailable", failure);
        }
    }

    private static String hex(byte[] data) {
        char[] digits = "0123456789ABCDEF".toCharArray();
        char[] result = new char[data.length * 2];
        for (int index = 0; index < data.length; index++) {
            int value = data[index] & 0xFF;
            result[index * 2] = digits[value >>> 4];
            result[index * 2 + 1] = digits[value & 0x0F];
        }
        return new String(result);
    }
}
