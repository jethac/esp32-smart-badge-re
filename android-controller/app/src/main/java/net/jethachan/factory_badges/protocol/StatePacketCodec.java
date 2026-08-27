package net.jethachan.factory_badges.protocol;

import net.jethachan.factory_badges.model.BadgeState;

public final class StatePacketCodec {
    public static final int PACKET_LENGTH = 8;
    private static final int SCHEMA_V1 = 1;
    private static final int REQUIRED_CREDIT_CENTS = 1727;

    private StatePacketCodec() {
    }

    public static byte[] encode(BadgeState state) {
        if (state == null) {
            throw new IllegalArgumentException("state must not be null");
        }
        byte[] packet = new byte[PACKET_LENGTH];
        packet[0] = SCHEMA_V1;
        packet[1] = (byte) state.dayPercent();
        packet[2] = (byte) state.weekPercent();
        packet[4] = (byte) (state.creditCents() & 0xFFL);
        packet[5] = (byte) ((state.creditCents() >>> 8) & 0xFFL);
        return packet;
    }

    public static BadgeState decode(byte[] packet) {
        if (packet == null || packet.length != PACKET_LENGTH) {
            throw new IllegalArgumentException("state packet must contain exactly 8 bytes");
        }

        int schema = unsigned(packet[0]);
        int dayPercent = unsigned(packet[1]);
        int weekPercent = unsigned(packet[2]);
        int flags = unsigned(packet[3]);
        int creditCents = unsigned(packet[4]) | (unsigned(packet[5]) << 8);
        int reservedSix = unsigned(packet[6]);
        int reservedSeven = unsigned(packet[7]);

        if (schema != SCHEMA_V1) {
            throw new IllegalArgumentException("unsupported state schema");
        }
        if (dayPercent > 100 || weekPercent > 100) {
            throw new IllegalArgumentException("percentages must be in 0..100");
        }
        if (flags != 0) {
            throw new IllegalArgumentException("flags byte must be zero");
        }
        if (creditCents != REQUIRED_CREDIT_CENTS) {
            throw new IllegalArgumentException("credit cents must be 1727");
        }
        if (reservedSix != 0 || reservedSeven != 0) {
            throw new IllegalArgumentException("reserved bytes must be zero");
        }

        return new BadgeState(dayPercent, weekPercent, creditCents);
    }

    private static int unsigned(byte value) {
        return value & 0xFF;
    }
}
