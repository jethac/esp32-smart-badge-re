package com.openai.e87probe;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

final class QixFactoryMemoryRead {
    static final UUID SERVICE = UUID.fromString(
            "c2e6fd00-e966-1000-8000-bef9c223df6a");
    static final UUID FD01 = UUID.fromString(
            "c2e6fd01-e966-1000-8000-bef9c223df6a");
    static final UUID FD02 = UUID.fromString(
            "c2e6fd02-e966-1000-8000-bef9c223df6a");
    static final UUID FD03 = UUID.fromString(
            "c2e6fd03-e966-1000-8000-bef9c223df6a");

    private static final byte[] MEMORY_PAYLOAD = Hex.decode("000200001000");

    private QixFactoryMemoryRead() {
    }

    static byte[] request() {
        return request(0);
    }

    static byte[] request(int serial) {
        if (serial < 0 || serial > 15) throw new IllegalArgumentException("serial");
        int flag = 0x80 | (serial << 3) | 0x02;
        return frame(flag, 0xA9, MEMORY_PAYLOAD);
    }

    static byte[] bindRequest(int settings, int hostId) {
        byte[] payload = new byte[13];
        payload[0] = (byte) settings;
        long widenedHostId = hostId;
        for (int copy = 0; copy < 2; copy++) {
            for (int index = 0; index < 6; index++) {
                payload[1 + (copy * 6) + index] =
                        (byte) (widenedHostId >> (index * 8));
            }
        }
        return frame(0x02, 0x60, payload);
    }

    static boolean isSuccessfulBindResponse(byte[] frame) {
        if (frame == null || frame.length < 7 || (frame[0] & 0xFF) != 0x9E
                || (frame[3] & 0xFF) != 0x61) return false;
        int payloadLength = (frame[4] & 0xFF) | ((frame[5] & 0xFF) << 8);
        return payloadLength >= 1 && frame.length >= payloadLength + 6 && frame[6] == 0;
    }

    static boolean requestsResponse(byte[] frame) {
        return frame != null && frame.length >= 3 && (frame[0] & 0xFF) == 0x9E
                && (frame[2] & 0x02) != 0;
    }

    static String bindFirmwareVersion(byte[] frame) {
        if (!isSuccessfulBindResponse(frame)) {
            throw new IllegalArgumentException("not a successful Qix bind response");
        }
        int payloadLength = (frame[4] & 0xFF) | ((frame[5] & 0xFF) << 8);
        if (payloadLength < 14 || frame.length != payloadLength + 6) {
            throw new IllegalArgumentException("bind response has no complete firmware field");
        }
        int checksum = 0;
        for (int index = 2; index < frame.length; index++) {
            checksum += frame[index] & 0xFF;
        }
        if ((frame[1] & 0xFF) != (checksum & 0xFF)) {
            throw new IllegalArgumentException("bind response checksum mismatch");
        }
        int start = 10;
        int end = start;
        while (end < start + 10 && frame[end] != 0) end++;
        return new String(frame, start, end - start, StandardCharsets.US_ASCII);
    }

    static byte[] successResponse(int receivedOpcode, int serial) {
        if (serial < 0 || serial > 15) throw new IllegalArgumentException("serial");
        return frame((serial << 3) | 0x01, 0xFF,
                new byte[] {(byte) receivedOpcode, 0});
    }

    private static byte[] frame(int flag, int opcode, byte[] payload) {
        byte[] frame = new byte[payload.length + 6];
        frame[0] = (byte) 0x9E;
        frame[2] = (byte) flag;
        frame[3] = (byte) opcode;
        frame[4] = (byte) payload.length;
        frame[5] = (byte) (payload.length >> 8);
        System.arraycopy(payload, 0, frame, 6, payload.length);
        int checksum = 0;
        for (int index = 2; index < frame.length; index++) {
            checksum += frame[index] & 0xFF;
        }
        frame[1] = (byte) checksum;
        return frame;
    }

    static String channelName(UUID characteristicUuid) {
        if (FD01.equals(characteristicUuid)) return "fd01";
        if (FD03.equals(characteristicUuid)) return "fd03";
        return null;
    }
}
