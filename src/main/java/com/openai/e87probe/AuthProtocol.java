package com.openai.e87probe;

import java.util.Arrays;

public final class AuthProtocol {
    private static final byte[] AUTH_OK = {0x02, 0x70, 0x61, 0x73, 0x73};

    public interface Crypto {
        byte[] random();
        byte[] encrypt(byte[] input);
    }

    public enum ActionType { SEND, AUTHENTICATED, IGNORED, FAILED }

    public static final class Action {
        public final ActionType type;
        public final byte[] bytes;
        public final String detail;

        private Action(ActionType type, byte[] bytes, String detail) {
            this.type = type;
            this.bytes = bytes == null ? null : bytes.clone();
            this.detail = detail;
        }

        static Action send(byte[] bytes, String detail) {
            return new Action(ActionType.SEND, bytes, detail);
        }

        static Action of(ActionType type, String detail) {
            return new Action(type, null, detail);
        }
    }

    private enum Phase { NEW, EXPECT_DEVICE_PROOF, EXCHANGE, DONE, FAILED }

    private final Crypto crypto;
    private Phase phase = Phase.NEW;
    private byte[] random;

    public AuthProtocol(Crypto crypto) {
        if (crypto == null) throw new IllegalArgumentException("crypto is required");
        this.crypto = crypto;
    }

    public Action begin() {
        if (phase != Phase.NEW) return Action.of(ActionType.FAILED, "authentication already started");
        random = crypto.random();
        if (!isPacket(random, 17, 0x00)) {
            phase = Phase.FAILED;
            return Action.of(ActionType.FAILED, "native random auth data is invalid");
        }
        phase = Phase.EXPECT_DEVICE_PROOF;
        return Action.send(random, "random challenge");
    }

    public Action onReceive(byte[] packet) {
        if (phase == Phase.EXPECT_DEVICE_PROOF) {
            if (!isPacket(packet, 17, 0x01)) {
                return Action.of(ActionType.IGNORED, "waiting for 17-byte device proof");
            }
            byte[] expected = crypto.encrypt(random);
            if (!Arrays.equals(expected, packet)) {
                phase = Phase.FAILED;
                return Action.of(ActionType.FAILED, "device proof did not match");
            }
            phase = Phase.EXCHANGE;
            return Action.send(AUTH_OK, "phone proof accepted");
        }
        if (phase == Phase.EXCHANGE) {
            if (Arrays.equals(AUTH_OK, packet)) {
                phase = Phase.DONE;
                return Action.of(ActionType.AUTHENTICATED, "mutual authentication complete");
            }
            if (isPacket(packet, 17, 0x00)) {
                byte[] reply = crypto.encrypt(packet);
                if (!isPacket(reply, 17, 0x01)) {
                    phase = Phase.FAILED;
                    return Action.of(ActionType.FAILED, "native challenge response is invalid");
                }
                return Action.send(reply, "device challenge response");
            }
            return Action.of(ActionType.IGNORED, "waiting for device challenge or auth-ok");
        }
        if (phase == Phase.DONE) return Action.of(ActionType.AUTHENTICATED, "already authenticated");
        return Action.of(ActionType.FAILED, "authentication is not active");
    }

    private static boolean isPacket(byte[] packet, int length, int firstByte) {
        return packet != null && packet.length == length && (packet[0] & 0xFF) == firstByte;
    }
}
