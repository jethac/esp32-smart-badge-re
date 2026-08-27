package net.jethachan.factory_badges.ble.normal;

import java.util.Optional;

public final class NormalAdvertisementParser {
    private static final int SHORTENED_LOCAL_NAME = 0x08;
    private static final int COMPLETE_LOCAL_NAME = 0x09;
    private static final int INCOMPLETE_128_BIT_UUIDS = 0x06;
    private static final int COMPLETE_128_BIT_UUIDS = 0x07;
    private static final int UUID_LENGTH = 16;
    private static final String REQUIRED_NAME = "E87";
    private static final byte[] NORMAL_SERVICE_LITTLE_ENDIAN = new byte[] {
            0x35, 0x07, (byte) 0xA7, 0x01,
            (byte) 0x9C, 0x5D, 0x0B, (byte) 0x9F,
            0x62, 0x4C, 0x1B, 0x7A,
            0x01, 0x00, 0x7D, (byte) 0xE8
    };

    private NormalAdvertisementParser() {
    }

    public static Optional<Match> parse(byte[] scanRecord) {
        if (scanRecord == null || scanRecord.length == 0) {
            return Optional.empty();
        }

        String localName = null;
        boolean hasNormalService = false;
        int offset = 0;
        while (offset < scanRecord.length) {
            int length = unsigned(scanRecord[offset]);
            offset++;
            if (length == 0) {
                break;
            }
            if (length > scanRecord.length - offset) {
                return Optional.empty();
            }

            int type = unsigned(scanRecord[offset]);
            int valueOffset = offset + 1;
            int valueLength = length - 1;
            if (type == SHORTENED_LOCAL_NAME || type == COMPLETE_LOCAL_NAME) {
                String candidate = decodeAsciiName(scanRecord, valueOffset, valueLength);
                if (candidate == null) {
                    return Optional.empty();
                }
                if (localName != null && !localName.equals(candidate)) {
                    return Optional.empty();
                }
                localName = candidate;
            } else if (type == INCOMPLETE_128_BIT_UUIDS
                    || type == COMPLETE_128_BIT_UUIDS) {
                if (valueLength == 0 || valueLength % UUID_LENGTH != 0) {
                    return Optional.empty();
                }
                for (int uuidOffset = valueOffset;
                        uuidOffset < valueOffset + valueLength;
                        uuidOffset += UUID_LENGTH) {
                    if (matchesNormalService(scanRecord, uuidOffset)) {
                        hasNormalService = true;
                    }
                }
            }
            offset += length;
        }

        if (hasNormalService && REQUIRED_NAME.equals(localName)) {
            return Optional.of(new Match(true, localName));
        }
        return Optional.empty();
    }

    private static String decodeAsciiName(byte[] bytes, int offset, int length) {
        StringBuilder result = new StringBuilder(length);
        for (int index = 0; index < length; index++) {
            int value = unsigned(bytes[offset + index]);
            if (value < 0x20 || value > 0x7E) {
                return null;
            }
            result.append((char) value);
        }
        return result.toString();
    }

    private static boolean matchesNormalService(byte[] bytes, int offset) {
        for (int index = 0; index < UUID_LENGTH; index++) {
            if (bytes[offset + index] != NORMAL_SERVICE_LITTLE_ENDIAN[index]) {
                return false;
            }
        }
        return true;
    }

    private static int unsigned(byte value) {
        return value & 0xFF;
    }

    public static final class Match {
        private final boolean normalService;
        private final String localName;

        private Match(boolean normalService, String localName) {
            this.normalService = normalService;
            this.localName = localName;
        }

        public boolean normalService() {
            return normalService;
        }

        public String localName() {
            return localName;
        }
    }
}
