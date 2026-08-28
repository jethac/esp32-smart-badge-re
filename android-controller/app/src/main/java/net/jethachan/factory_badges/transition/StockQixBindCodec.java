package net.jethachan.factory_badges.transition;

import java.nio.charset.StandardCharsets;

/** Capture-pinned bind request, response validation, and acknowledgement codec. */
public final class StockQixBindCodec {
    private static final int BIND_REQUEST_FLAGS = 0x02;
    private static final int BIND_REQUEST_OPCODE = 0x60;
    private static final int BIND_RESPONSE_OPCODE = 0x61;
    private static final int SUCCESS_ACK_OPCODE = 0xFF;
    private static final int VERSION_OFFSET = 4;
    private static final int MAX_VERSION_LENGTH = 10;

    private StockQixBindCodec() {
    }

    public static byte[] request(int settings, int hostId) {
        requireByte(settings, "settings");
        byte[] payload = new byte[13];
        payload[0] = (byte) settings;
        long widenedHostId = hostId;
        for (int copy = 0; copy < 2; copy++) {
            for (int index = 0; index < 6; index++) {
                payload[1 + (copy * 6) + index] = (byte) (widenedHostId >>> (index * 8));
            }
        }
        return QixFrameCodec.encode(BIND_REQUEST_FLAGS, BIND_REQUEST_OPCODE, payload);
    }

    public static BindResponse parseResponse(QixFrame frame) {
        if (frame == null || frame.opcode() != BIND_RESPONSE_OPCODE) {
            throw new IllegalArgumentException("not a Qix bind response");
        }
        byte[] payload = frame.payload();
        if (payload.length <= VERSION_OFFSET || payload[0] != 0) {
            throw new IllegalArgumentException("bind response is not successful or complete");
        }

        int versionEnd = -1;
        int limit = Math.min(payload.length, VERSION_OFFSET + MAX_VERSION_LENGTH + 1);
        for (int index = VERSION_OFFSET; index < limit; index++) {
            if (payload[index] == 0) {
                versionEnd = index;
                break;
            }
            int value = payload[index] & 0xFF;
            if (value < 0x20 || value > 0x7E) {
                throw new IllegalArgumentException("bind firmware version is not ASCII");
            }
        }
        if (versionEnd <= VERSION_OFFSET) {
            throw new IllegalArgumentException("bind firmware version is incomplete or too long");
        }
        String version = new String(payload, VERSION_OFFSET, versionEnd - VERSION_OFFSET,
                StandardCharsets.US_ASCII);
        return new BindResponse(frame.flags(), version);
    }

    public static byte[] successAck(int receivedOpcode, int serial) {
        requireByte(receivedOpcode, "received opcode");
        if (serial < 0 || serial > 15) {
            throw new IllegalArgumentException("serial must be between zero and fifteen");
        }
        return QixFrameCodec.encode((serial << 3) | 0x01, SUCCESS_ACK_OPCODE,
                new byte[] {(byte) receivedOpcode, 0});
    }

    private static void requireByte(int value, String name) {
        if (value < 0 || value > 0xFF) {
            throw new IllegalArgumentException(name + " must be an unsigned byte");
        }
    }

    public static final class BindResponse {
        private final int flags;
        private final String firmwareVersion;

        private BindResponse(int flags, String firmwareVersion) {
            this.flags = flags;
            this.firmwareVersion = firmwareVersion;
        }

        public int flags() {
            return flags;
        }

        public int serial() {
            return (flags >>> 3) & 0x0F;
        }

        public boolean requestsReply() {
            return (flags & 0x02) != 0;
        }

        public String firmwareVersion() {
            return firmwareVersion;
        }
    }
}
