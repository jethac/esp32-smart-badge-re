package com.openai.e87probe;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Objects;

/**
 * Validates one immutable package snapshot against a PackagePin.
 */
public final class PinnedPackageValidator {
    private PinnedPackageValidator() {}

    public static ValidatedPackage validate(byte[] packageBytes, PackagePin pin) {
        Objects.requireNonNull(packageBytes, "packageBytes");
        Objects.requireNonNull(pin, "pin");
        if (packageBytes.length <= PackagePin.HEADER_SIZE_BYTES
                || packageBytes.length > PackagePin.MAX_PACKAGE_SIZE_BYTES
                || packageBytes.length != pin.size()) {
            throw new IllegalArgumentException("Pinned package snapshot size mismatch");
        }

        // Break caller aliasing before hashing or returning any derived view.
        packageBytes = Arrays.copyOf(packageBytes, packageBytes.length);
        String actualSha256;
        try {
            actualSha256 =
                    Hex.encode(MessageDigest.getInstance("SHA-256").digest(packageBytes));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
        if (!pin.sha256().equals(actualSha256)) {
            throw new IllegalArgumentException("Pinned package SHA-256 mismatch");
        }

        byte[] header =
                Arrays.copyOfRange(packageBytes, 0, PackagePin.HEADER_SIZE_BYTES);
        if (!Arrays.equals(pin.header(), header)) {
            throw new IllegalArgumentException("Pinned package 27-byte header mismatch");
        }
        long declaredPayloadLength =
                ((long) header[13] & 0xFF)
                        | (((long) header[14] & 0xFF) << 8)
                        | (((long) header[15] & 0xFF) << 16)
                        | (((long) header[16] & 0xFF) << 24);
        if (declaredPayloadLength
                != packageBytes.length - PackagePin.HEADER_SIZE_BYTES) {
            throw new IllegalArgumentException("Package header length declaration mismatch");
        }

        byte[] payload =
                Arrays.copyOfRange(
                        packageBytes, PackagePin.HEADER_SIZE_BYTES, packageBytes.length);
        return new ValidatedPackage(header, payload, actualSha256);
    }


    public static final class ValidatedPackage {
        private final byte[] header;
        private final byte[] payload;
        private final String sha256;

        private ValidatedPackage(byte[] header, byte[] payload, String sha256) {
            this.header = Arrays.copyOf(header, header.length);
            this.payload = Arrays.copyOf(payload, payload.length);
            this.sha256 = sha256;
        }

        public byte[] header() {
            return Arrays.copyOf(header, header.length);
        }

        public byte[] payload() {
            return Arrays.copyOf(payload, payload.length);
        }

        public String sha256() {
            return sha256;
        }
    }
}
