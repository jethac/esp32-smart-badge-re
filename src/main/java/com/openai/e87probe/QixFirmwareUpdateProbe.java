package com.openai.e87probe;

final class QixFirmwareUpdateProbe {
    static final class UpdateRequest {
        final int state;
        final int allowedLength;
        final int offset;

        UpdateRequest(int state, int allowedLength, int offset) {
            this.state = state;
            this.allowedLength = allowedLength;
            this.offset = offset;
        }
    }

    static final class DataResponse {
        final int result;
        final int nextOffset;

        DataResponse(int result, int nextOffset) {
            this.result = result;
            this.nextOffset = nextOffset;
        }
    }

    private QixFirmwareUpdateProbe() {
    }

    static byte[] start(byte[] header) {
        if (header == null || header.length != 27) {
            throw new IllegalArgumentException("Qix update header must be 27 bytes");
        }
        return frame(0xC0, header, 0);
    }

    static byte[] dataBlock(byte[] updateData, int offset, int length, int serial) {
        if (updateData == null || offset < 0 || length <= 0
                || offset > updateData.length || length > updateData.length - offset) {
            throw new IllegalArgumentException("invalid Qix update-data slice");
        }
        if (serial < 0 || serial > 15) {
            throw new IllegalArgumentException("Qix serial must be between zero and fifteen");
        }
        byte[] payload = new byte[length + 8];
        putLittleEndianInt(payload, 0, length);
        putLittleEndianInt(payload, 4, offset);
        System.arraycopy(updateData, offset, payload, 8, length);
        return frame(0xC2, payload, serial);
    }

    static UpdateRequest parseUpdateRequest(byte[] frame) {
        validateFrame(frame, 0xC1, 9);
        return new UpdateRequest(frame[6] & 0xFF, littleEndianInt(frame, 7),
                littleEndianInt(frame, 11));
    }

    static DataResponse parseDataResponse(byte[] frame) {
        validateFrame(frame, 0xC3, 5);
        return new DataResponse(frame[6] & 0xFF, littleEndianInt(frame, 7));
    }

    static int parseUpdateResult(byte[] frame) {
        validateFrame(frame, 0xC5, 1);
        return frame[6] & 0xFF;
    }

    private static byte[] frame(int opcode, byte[] payload, int serial) {
        byte[] frame = new byte[payload.length + 6];
        frame[0] = (byte) 0x9E;
        frame[2] = (byte) (1 | (serial << 3) | (frame.length > 20 ? 4 : 0));
        frame[3] = (byte) opcode;
        frame[4] = (byte) payload.length;
        frame[5] = (byte) (payload.length >>> 8);
        System.arraycopy(payload, 0, frame, 6, payload.length);
        int checksum = 0;
        for (int index = 2; index < frame.length; index++) {
            checksum += frame[index] & 0xFF;
        }
        frame[1] = (byte) checksum;
        return frame;
    }

    private static void validateFrame(byte[] frame, int opcode, int payloadLength) {
        if (frame == null || frame.length != payloadLength + 6
                || (frame[0] & 0xFF) != 0x9E
                || (frame[3] & 0xFF) != opcode
                || (frame[4] & 0xFF) != (payloadLength & 0xFF)
                || (frame[5] & 0xFF) != (payloadLength >>> 8)) {
            throw new IllegalArgumentException("not the expected Qix update frame");
        }
        int checksum = 0;
        for (int index = 2; index < frame.length; index++) {
            checksum += frame[index] & 0xFF;
        }
        if ((frame[1] & 0xFF) != (checksum & 0xFF)) {
            throw new IllegalArgumentException("invalid Qix frame checksum");
        }
    }

    private static void putLittleEndianInt(byte[] bytes, int offset, int value) {
        bytes[offset] = (byte) value;
        bytes[offset + 1] = (byte) (value >>> 8);
        bytes[offset + 2] = (byte) (value >>> 16);
        bytes[offset + 3] = (byte) (value >>> 24);
    }

    private static int littleEndianInt(byte[] bytes, int offset) {
        return (bytes[offset] & 0xFF)
                | ((bytes[offset + 1] & 0xFF) << 8)
                | ((bytes[offset + 2] & 0xFF) << 16)
                | ((bytes[offset + 3] & 0xFF) << 24);
    }
}
