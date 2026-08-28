package net.jethachan.factory_badges.transition;

import java.util.Arrays;

/** Immutable logical Qix frame, excluding the wire magic and checksum bytes. */
public final class QixFrame {
    private final int flags;
    private final int opcode;
    private final byte[] payload;

    public QixFrame(int flags, int opcode, byte[] payload) {
        if (flags < 0 || flags > 0xFF) {
            throw new IllegalArgumentException("flags must be an unsigned byte");
        }
        if (opcode < 0 || opcode > 0xFF) {
            throw new IllegalArgumentException("opcode must be an unsigned byte");
        }
        if (payload == null || payload.length > 0xFFFF) {
            throw new IllegalArgumentException("payload must contain at most 65535 bytes");
        }
        this.flags = flags;
        this.opcode = opcode;
        this.payload = Arrays.copyOf(payload, payload.length);
    }

    public int flags() {
        return flags;
    }

    public int opcode() {
        return opcode;
    }

    public byte[] payload() {
        return Arrays.copyOf(payload, payload.length);
    }
}
