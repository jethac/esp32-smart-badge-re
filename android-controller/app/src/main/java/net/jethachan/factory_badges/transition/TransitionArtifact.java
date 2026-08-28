package net.jethachan.factory_badges.transition;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;

/** Immutable synthetic Qix header, UFW payload, and identity used by the stock sender. */
public final class TransitionArtifact {
    private static final int QIX_HEADER_LENGTH = 27;
    private static final int QIX_LENGTH_OFFSET = 13;
    private static final int SHA256_LENGTH = 32;
    private static final int BUILD_ID_LENGTH = 16;
    private static final int MAX_QIX_PAYLOAD_LENGTH = (32 * 1024 * 1024) - QIX_HEADER_LENGTH;

    private final byte[] qixHeader;
    private final byte[] ufwPayload;
    private final byte[] qixSha256;
    private final byte[] expectedBuildId;

    public TransitionArtifact(byte[] qixHeader, byte[] ufwPayload, byte[] qixSha256,
            byte[] expectedBuildId) {
        if (qixHeader == null || ufwPayload == null || qixSha256 == null
                || expectedBuildId == null) {
            throw new IllegalArgumentException("transition artifact inputs must not be null");
        }
        if (qixHeader.length != QIX_HEADER_LENGTH) {
            throw new IllegalArgumentException("Qix header must be 27 bytes");
        }
        if (ufwPayload.length == 0 || ufwPayload.length > MAX_QIX_PAYLOAD_LENGTH) {
            throw new IllegalArgumentException("UFW payload is outside the supported Qix bound");
        }
        if (qixSha256.length != SHA256_LENGTH) {
            throw new IllegalArgumentException("Qix SHA-256 must be 32 bytes");
        }
        if (expectedBuildId.length != BUILD_ID_LENGTH) {
            throw new IllegalArgumentException("expected build ID must be 16 bytes");
        }
        if (readUnsignedU32(qixHeader, QIX_LENGTH_OFFSET) != ufwPayload.length) {
            throw new IllegalArgumentException("Qix header payload length does not match UFW payload");
        }
        if (!MessageDigest.isEqual(qixSha256, sha256(qixHeader, ufwPayload))) {
            throw new IllegalArgumentException("whole-Qix SHA-256 does not match header and payload");
        }

        this.qixHeader = Arrays.copyOf(qixHeader, qixHeader.length);
        this.ufwPayload = Arrays.copyOf(ufwPayload, ufwPayload.length);
        this.qixSha256 = Arrays.copyOf(qixSha256, qixSha256.length);
        this.expectedBuildId = Arrays.copyOf(expectedBuildId, expectedBuildId.length);
    }

    public byte[] qixHeader() {
        return Arrays.copyOf(qixHeader, qixHeader.length);
    }

    public byte[] ufwPayload() {
        return Arrays.copyOf(ufwPayload, ufwPayload.length);
    }

    public byte[] qixSha256() {
        return Arrays.copyOf(qixSha256, qixSha256.length);
    }

    public byte[] expectedBuildId() {
        return Arrays.copyOf(expectedBuildId, expectedBuildId.length);
    }

    private static long readUnsignedU32(byte[] bytes, int offset) {
        return ((long) bytes[offset] & 0xFF)
                | (((long) bytes[offset + 1] & 0xFF) << 8)
                | (((long) bytes[offset + 2] & 0xFF) << 16)
                | (((long) bytes[offset + 3] & 0xFF) << 24);
    }

    private static byte[] sha256(byte[] header, byte[] payload) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(header);
            digest.update(payload);
            return digest.digest();
        } catch (NoSuchAlgorithmException failure) {
            throw new IllegalStateException("SHA-256 is unavailable", failure);
        }
    }
}
