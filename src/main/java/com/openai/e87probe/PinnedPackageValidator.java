package com.openai.e87probe;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Objects;

/**
 * Loads only a regular, non-symlink file whose complete identity matches a PackagePin.
 */
public final class PinnedPackageValidator {
    private PinnedPackageValidator() {}

    public static ValidatedPackage validate(File file, PackagePin pin) {
        Objects.requireNonNull(file, "file");
        Objects.requireNonNull(pin, "pin");

        Path path = file.toPath();
        if (Files.isSymbolicLink(path)
                || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException(
                    "Pinned package input must be a regular non-symlink file");
        }

        final long actualSize;
        try {
            actualSize = Files.size(path);
        } catch (IOException exception) {
            throw invalid("Cannot inspect pinned package", exception);
        }
        if (actualSize <= PackagePin.HEADER_SIZE_BYTES
                || actualSize > PackagePin.MAX_PACKAGE_SIZE_BYTES
                || actualSize != pin.size()) {
            throw new IllegalArgumentException("Pinned package size mismatch");
        }

        byte[] packageBytes = new byte[(int) actualSize];
        try (FileInputStream input = new FileInputStream(file)) {
            int offset = 0;
            while (offset < packageBytes.length) {
                int read = input.read(packageBytes, offset, packageBytes.length - offset);
                if (read < 0) {
                    throw new IllegalArgumentException("Pinned package was truncated while reading");
                }
                offset += read;
            }
            if (input.read() != -1) {
                throw new IllegalArgumentException("Pinned package grew while reading");
            }
        } catch (IOException exception) {
            throw invalid("Cannot read pinned package", exception);
        }

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

    private static IllegalArgumentException invalid(String message, Exception cause) {
        return new IllegalArgumentException(message, cause);
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
