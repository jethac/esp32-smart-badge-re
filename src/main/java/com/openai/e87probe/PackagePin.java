package com.openai.e87probe;

import java.util.Arrays;

/**
 * Immutable compile-time identity for the single reviewed update package.
 */
public final class PackagePin {
    public static final int HEADER_SIZE_BYTES = 27;
    public static final int MAX_PACKAGE_SIZE_BYTES = 32 * 1024 * 1024;

    private final int size;
    private final String sha256;
    private final byte[] header;

    public PackagePin(int size, String sha256, byte[] header) {
        if (size <= HEADER_SIZE_BYTES || size > MAX_PACKAGE_SIZE_BYTES) {
            throw new IllegalArgumentException("Pinned package size is outside safe bounds");
        }
        if (sha256 == null || !sha256.matches("[0-9A-F]{64}")) {
            throw new IllegalArgumentException(
                    "Pinned SHA-256 must be exactly 64 uppercase hexadecimal digits");
        }
        if (header == null || header.length != HEADER_SIZE_BYTES) {
            throw new IllegalArgumentException("Pinned package header must be exactly 27 bytes");
        }

        long declaredPayloadLength =
                ((long) header[13] & 0xFF)
                        | (((long) header[14] & 0xFF) << 8)
                        | (((long) header[15] & 0xFF) << 16)
                        | (((long) header[16] & 0xFF) << 24);
        if (declaredPayloadLength != size - HEADER_SIZE_BYTES) {
            throw new IllegalArgumentException(
                    "Pinned header length does not match pinned package size");
        }

        this.size = size;
        this.sha256 = sha256;
        this.header = Arrays.copyOf(header, header.length);
    }

    public int size() {
        return size;
    }

    public String sha256() {
        return sha256;
    }

    public byte[] header() {
        return Arrays.copyOf(header, header.length);
    }
}
