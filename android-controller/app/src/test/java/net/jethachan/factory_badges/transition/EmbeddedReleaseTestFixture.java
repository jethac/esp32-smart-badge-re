package net.jethachan.factory_badges.transition;

import java.io.ByteArrayInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class EmbeddedReleaseTestFixture implements TransitionArtifactValidator.AssetSource {
    static final String BUILD_ID = "00112233445566778899AABBCCDDEEFF";
    static final String QIX_NAME = "E87-11.1.0.4-00112233.qix";
    static final String RELEASE_ROOT = "E87-JD9855-R1/0.1.0/" + BUILD_ID;
    static final String PREFIX = "e87/" + RELEASE_ROOT + "/";

    private static final String[][] ROLES = new String[][] {
            {"appBin", "app.bin"},
            {"jlIsdFw", "jl_isd.fw"},
            {"updateUfw", "update.ufw"},
            {"qix", QIX_NAME},
            {"manifest", "manifest.json"},
            {"sha256Sums", "SHA256SUMS"}
    };

    final Map<String, byte[]> assets = new LinkedHashMap<String, byte[]>();
    int opens;

    EmbeddedReleaseTestFixture() {
        assets.put(PREFIX + "app.bin", ascii("APP\u0000qualified-build\u0001"));
        assets.put(PREFIX + "jl_isd.fw", ascii("JLFW\u0000qualified-container\u0002"));
        byte[] ufw = ascii("UFW4\u0000qualified-update\u0003");
        assets.put(PREFIX + "update.ufw", ufw);
        assets.put(PREFIX + QIX_NAME, makeQix(ufw));
        assets.put(PREFIX + "manifest.json", ascii(
                "{\n"
                + "  \"labEligible\": true,\n"
                + "  \"schema\": \"e87-firmware-manifest-v1\"\n"
                + "}\n"));
        rebuildMetadata();
    }

    void rebuildMetadata() {
        List<String> sumsNames = new ArrayList<String>(Arrays.asList(
                QIX_NAME, "app.bin", "jl_isd.fw", "manifest.json", "update.ufw"));
        Collections.sort(sumsNames);
        StringBuilder sums = new StringBuilder();
        for (String name : sumsNames) {
            sums.append(hex(sha256(assets.get(PREFIX + name)))).append(" *")
                    .append(name).append('\n');
        }
        assets.put(PREFIX + "SHA256SUMS", ascii(sums.toString()));
        assets.put("e87/default-release.json", receiptBytes());
    }

    byte[] receiptBytes() {
        StringBuilder json = new StringBuilder();
        json.append("{\n")
                .append("  \"buildId\": \"").append(BUILD_ID).append("\",\n")
                .append("  \"chip\": \"AC707N\",\n")
                .append("  \"files\": [\n");
        for (int index = 0; index < ROLES.length; index++) {
            String role = ROLES[index][0];
            String filename = ROLES[index][1];
            byte[] data = assets.get(PREFIX + filename);
            json.append("    {\n")
                    .append("      \"filename\": \"").append(filename).append("\",\n")
                    .append("      \"length\": ").append(data.length).append(",\n")
                    .append("      \"role\": \"").append(role).append("\",\n")
                    .append("      \"sha256\": \"").append(hex(sha256(data))).append("\"\n")
                    .append("    }");
            json.append(index + 1 == ROLES.length ? "\n" : ",\n");
        }
        json.append("  ],\n")
                .append("  \"labEligible\": true,\n")
                .append("  \"layout\": \"SINGLE_BANK\",\n")
                .append("  \"profile\": \"E87-JD9855-R1\",\n")
                .append("  \"qixVersion\": \"11.1.0.4\",\n")
                .append("  \"releaseEligible\": false,\n")
                .append("  \"releaseRoot\": \"").append(RELEASE_ROOT).append("\",\n")
                .append("  \"schemaId\": \"e87-android-embed-v1\",\n")
                .append("  \"schemaVersion\": 1,\n")
                .append("  \"semver\": \"0.1.0\"\n")
                .append("}\n");
        return ascii(json.toString());
    }

    @Override public String[] list(String path) {
        String prefix = path.isEmpty() ? "" : path + "/";
        Set<String> children = new LinkedHashSet<String>();
        for (String name : assets.keySet()) {
            if (!name.startsWith(prefix)) continue;
            String remainder = name.substring(prefix.length());
            int slash = remainder.indexOf('/');
            children.add(slash < 0 ? remainder : remainder.substring(0, slash));
        }
        return children.toArray(new String[children.size()]);
    }

    @Override public InputStream open(String path) throws IOException {
        opens++;
        byte[] data = assets.get(path);
        if (data == null) throw new FileNotFoundException(path);
        return new ByteArrayInputStream(data);
    }

    static byte[] makeQix(byte[] payload) {
        byte[] header = new byte[27];
        header[0] = (byte) 0xBC;
        header[1] = (byte) 0xAF;
        header[2] = 1;
        byte[] version = ascii("11.1.0.4");
        System.arraycopy(version, 0, header, 3, version.length);
        putU32(header, 13, payload.length);
        int crc = crc16(payload);
        header[25] = (byte) crc;
        header[26] = (byte) (crc >>> 8);
        byte[] qix = Arrays.copyOf(header, header.length + payload.length);
        System.arraycopy(payload, 0, qix, header.length, payload.length);
        return qix;
    }

    static byte[] ascii(String value) {
        return value.getBytes(StandardCharsets.US_ASCII);
    }

    static byte[] sha256(byte[] data) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(data);
        } catch (NoSuchAlgorithmException failure) {
            throw new AssertionError(failure);
        }
    }

    static String hex(byte[] data) {
        char[] digits = "0123456789ABCDEF".toCharArray();
        char[] result = new char[data.length * 2];
        for (int index = 0; index < data.length; index++) {
            int value = data[index] & 0xFF;
            result[index * 2] = digits[value >>> 4];
            result[index * 2 + 1] = digits[value & 0x0F];
        }
        return new String(result);
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

    private static void putU32(byte[] data, int offset, int value) {
        data[offset] = (byte) value;
        data[offset + 1] = (byte) (value >>> 8);
        data[offset + 2] = (byte) (value >>> 16);
        data[offset + 3] = (byte) (value >>> 24);
    }
}
