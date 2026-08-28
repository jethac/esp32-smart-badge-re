package net.jethachan.factory_badges.transition;

/** Strict encoder and decoder for the captured Qix wire frame format. */
public final class QixFrameCodec {
    static final int MAGIC = 0x9E;
    static final int HEADER_LENGTH = 6;
    static final int MAX_PAYLOAD_LENGTH = 0xFFFF;
    static final int MAX_FRAME_LENGTH = HEADER_LENGTH + MAX_PAYLOAD_LENGTH;

    private QixFrameCodec() {
    }

    public static byte[] encode(int flags, int opcode, byte[] payload) {
        QixFrame frame = new QixFrame(flags, opcode, payload);
        byte[] body = frame.payload();
        byte[] encoded = new byte[HEADER_LENGTH + body.length];
        encoded[0] = (byte) MAGIC;
        encoded[2] = (byte) frame.flags();
        encoded[3] = (byte) frame.opcode();
        encoded[4] = (byte) body.length;
        encoded[5] = (byte) (body.length >>> 8);
        System.arraycopy(body, 0, encoded, HEADER_LENGTH, body.length);
        encoded[1] = (byte) checksum(encoded);
        return encoded;
    }

    public static QixFrame decode(byte[] encoded) {
        if (encoded == null || encoded.length < HEADER_LENGTH) {
            throw new IllegalArgumentException("Qix frame is shorter than its header");
        }
        if ((encoded[0] & 0xFF) != MAGIC) {
            throw new IllegalArgumentException("Qix frame has wrong magic");
        }
        int payloadLength = (encoded[4] & 0xFF) | ((encoded[5] & 0xFF) << 8);
        if (encoded.length != HEADER_LENGTH + payloadLength) {
            throw new IllegalArgumentException("Qix frame length does not match its header");
        }
        if ((encoded[1] & 0xFF) != checksum(encoded)) {
            throw new IllegalArgumentException("Qix frame checksum does not match");
        }
        byte[] payload = new byte[payloadLength];
        System.arraycopy(encoded, HEADER_LENGTH, payload, 0, payloadLength);
        return new QixFrame(encoded[2] & 0xFF, encoded[3] & 0xFF, payload);
    }

    static int checksum(byte[] encoded) {
        int checksum = 0;
        for (int index = 2; index < encoded.length; index++) {
            checksum += encoded[index] & 0xFF;
        }
        return checksum & 0xFF;
    }
}
