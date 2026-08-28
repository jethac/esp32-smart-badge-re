package com.openai.e87probe;

import java.util.Arrays;
import java.util.ArrayList;
import java.util.List;

public final class RcspProtocol {
    public static final int DATA = 0x01;
    public static final int GET_TARGET_INFO = 0x03;
    public static final int GET_SYS_INFO = 0x07;
    public static final int START_FILE_BROWSE = 0x0C;
    public static final int STOP_FILE_BROWSE = 0x0D;

    private static final byte[] PREFIX = {(byte) 0xFE, (byte) 0xDC, (byte) 0xBA};

    private RcspProtocol() {}

    public static byte[] targetInfo(int sequence) {
        return command(GET_TARGET_INFO, sequence,
                new byte[] {(byte) 0xFF, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF, 0x00});
    }

    public static byte[] storageInfo(int sequence) {
        return command(GET_SYS_INFO, sequence,
                new byte[] {(byte) 0xFF, 0x00, 0x00, 0x00, 0x04});
    }

    public static byte[] startRootBrowse(int sequence, long devHandle) {
        requireUint32("device handle", devHandle);
        byte[] parameters = new byte[14];
        parameters[0] = 0x00; // folder listing
        parameters[1] = 0x0A; // one vendor-default page of ten entries
        parameters[2] = 0x00;
        parameters[3] = 0x01; // startIndex = 1, big-endian
        putBe32(parameters, 4, devHandle);
        parameters[8] = 0x00;
        parameters[9] = 0x04; // one four-byte cluster in the path
        putBe32(parameters, 10, 0); // root cluster
        return command(START_FILE_BROWSE, sequence, parameters);
    }

    public static byte[] stopBrowseAck(int stopSequence, int reason) {
        if ((stopSequence & ~0xFF) != 0 || (reason & ~0xFF) != 0) {
            throw new IllegalArgumentException("stop sequence and reason must be uint8");
        }
        byte[] out = new byte[11];
        System.arraycopy(PREFIX, 0, out, 0, PREFIX.length);
        out[3] = 0x00; // response
        out[4] = (byte) STOP_FILE_BROWSE;
        out[5] = 0x00;
        out[6] = 0x03;
        out[7] = 0x00; // success status
        out[8] = (byte) stopSequence;
        out[9] = (byte) reason;
        out[10] = (byte) 0xEF;
        return out;
    }

    public static byte[] extractBrowseData(Frame frame) {
        if (frame == null || frame.flags != 0x80 || frame.opcode != DATA
                || frame.payload.length < 2
                || (frame.payload[1] & 0xFF) != START_FILE_BROWSE) {
            throw new IllegalArgumentException("not a no-response file-browse DataCmd");
        }
        return Arrays.copyOfRange(frame.payload, 2, frame.payload.length);
    }

    public static StopBrowseCommand extractStopBrowseCommand(Frame frame) {
        if (frame == null || frame.flags != 0xC0 || frame.opcode != STOP_FILE_BROWSE
                || frame.payload.length != 2) {
            throw new IllegalArgumentException("not a response-requesting stop-browse command");
        }
        return new StopBrowseCommand(frame.payload[0] & 0xFF, frame.payload[1] & 0xFF);
    }

    /**
     * Returns an online internal-flash handle (FLASH, FLASH2, then FLASH3), or -1.
     * The input is GET_SYS_INFO response data after RCSP status and sequence bytes.
     * Malformed or unrecognized data fails closed by returning -1.
     */
    public static long selectInternalFlashHandle(byte[] responseData) {
        return selectPreferredStorageHandle(responseData, new int[] {3, 5, 6});
    }

    /** Requires the badge app's exact online SD Card 1 record: index 2, handle 2. */
    public static long selectBadgeFilesystemHandle(byte[] responseData) {
        final List<StorageRecord> records;
        try {
            records = parseStorageRecords(responseData);
        } catch (IllegalArgumentException error) {
            return -1L;
        }
        for (StorageRecord record : records) {
            if (record.index == 2) {
                return record.online && record.handle == 0x00000002L ? record.handle : -1L;
            }
        }
        return -1L;
    }

    private static long selectPreferredStorageHandle(byte[] responseData,
                                                      int[] preferredIndices) {
        final List<StorageRecord> records;
        try {
            records = parseStorageRecords(responseData);
        } catch (IllegalArgumentException error) {
            return -1L;
        }
        for (int preferredIndex : preferredIndices) {
            for (StorageRecord record : records) {
                if (record.index == preferredIndex && record.online) {
                    return record.handle;
                }
            }
        }
        return -1L;
    }

    private static List<StorageRecord> parseStorageRecords(byte[] responseData) {
        if (responseData == null || responseData.length < 2
                || responseData[0] != (byte) 0xFF) {
            throw new IllegalArgumentException("malformed storage response");
        }
        List<StorageRecord> records = new ArrayList<>();
        boolean[] seenIndices = new boolean[256];
        int cursor = 1;
        while (cursor < responseData.length) {
            int length = responseData[cursor] & 0xFF;
            int attributeEnd = cursor + 1 + length;
            if (length < 1 || attributeEnd > responseData.length) {
                throw new IllegalArgumentException("malformed storage attribute");
            }
            int type = responseData[cursor + 1] & 0xFF;
            if (type == 2) {
                parseStorageAttribute(responseData, cursor + 2, length - 1,
                        records, seenIndices);
            }
            cursor = attributeEnd;
        }
        return records;
    }

    private static void parseStorageAttribute(byte[] bytes, int offset, int length,
                                              List<StorageRecord> records,
                                              boolean[] seenIndices) {
        if (length < 1) throw new IllegalArgumentException("empty storage attribute");
        if (bytes[offset] != (byte) 0xFF) {
            if (length != 21 && length != 25) {
                throw new IllegalArgumentException("unknown legacy storage layout");
            }
            int[] indices = length == 25
                    ? new int[] {0, 1, 2, 3, 5, 6}
                    : new int[] {0, 1, 2, 3, 5};
            int onlineMask = bytes[offset] & 0xFF;
            int knownMask = 0;
            for (int slot = 0; slot < indices.length; slot++) {
                int index = indices[slot];
                knownMask |= 1 << index;
                boolean online = (onlineMask & (1 << index)) != 0;
                long handle = readBe32(bytes, offset + 1 + slot * 4);
                addStorageRecord(records, seenIndices, index, online, handle);
            }
            if ((onlineMask & ~knownMask) != 0) {
                throw new IllegalArgumentException("legacy storage mask names unknown index");
            }
            return;
        }

        if (length < 2 || (bytes[offset + 1] & 0xFF) != 0) {
            throw new IllegalArgumentException("unsupported versioned storage layout");
        }
        int end = offset + length;
        int cursor = offset + 2;
        while (cursor < end) {
            int ltvLength = bytes[cursor] & 0xFF;
            int ltvEnd = cursor + 1 + ltvLength;
            if (ltvLength < 1 || ltvEnd > end) {
                throw new IllegalArgumentException("malformed versioned storage LTV");
            }
            int type = bytes[cursor + 1] & 0xFF;
            if (type == 1) {
                int recordCursor = cursor + 2;
                while (recordCursor < ltvEnd) {
                    if (ltvEnd - recordCursor < 2) {
                        throw new IllegalArgumentException("truncated storage record");
                    }
                    int onlineValue = bytes[recordCursor] & 0xFF;
                    int index = bytes[recordCursor + 1] & 0xFF;
                    if (onlineValue != 0 && onlineValue != 1) {
                        throw new IllegalArgumentException("invalid storage online flag");
                    }
                    boolean online = onlineValue == 1;
                    recordCursor += 2;
                    long handle = -1L;
                    if (online) {
                        if (ltvEnd - recordCursor < 4) {
                            throw new IllegalArgumentException("truncated online storage handle");
                        }
                        handle = readBe32(bytes, recordCursor);
                        recordCursor += 4;
                    }
                    addStorageRecord(records, seenIndices, index, online, handle);
                }
            }
            cursor = ltvEnd;
        }
    }

    private static void addStorageRecord(List<StorageRecord> records,
                                         boolean[] seenIndices, int index,
                                         boolean online, long handle) {
        if (seenIndices[index]) {
            throw new IllegalArgumentException("duplicate storage index " + index);
        }
        seenIndices[index] = true;
        records.add(new StorageRecord(index, online, handle));
    }

    private static final class StorageRecord {
        final int index;
        final boolean online;
        final long handle;

        StorageRecord(int index, boolean online, long handle) {
            this.index = index;
            this.online = online;
            this.handle = handle;
        }
    }

    private static void requireUint32(String label, long value) {
        if (value < 0 || value > 0xFFFFFFFFL) {
            throw new IllegalArgumentException(label + " outside uint32: " + value);
        }
    }

    private static void putBe32(byte[] destination, int offset, long value) {
        destination[offset] = (byte) (value >>> 24);
        destination[offset + 1] = (byte) (value >>> 16);
        destination[offset + 2] = (byte) (value >>> 8);
        destination[offset + 3] = (byte) value;
    }

    private static long readBe32(byte[] source, int offset) {
        return ((long) (source[offset] & 0xFF) << 24)
                | ((long) (source[offset + 1] & 0xFF) << 16)
                | ((long) (source[offset + 2] & 0xFF) << 8)
                | (long) (source[offset + 3] & 0xFF);
    }

    public static byte[] command(int opcode, int sequence, byte[] parameters) {
        if ((opcode & ~0xFF) != 0 || (sequence & ~0xFF) != 0) {
            throw new IllegalArgumentException("opcode and sequence must be uint8");
        }
        if (parameters == null || parameters.length > 0xFFFE) {
            throw new IllegalArgumentException("invalid parameter length");
        }
        int payloadLength = 1 + parameters.length;
        byte[] out = new byte[payloadLength + 8];
        System.arraycopy(PREFIX, 0, out, 0, PREFIX.length);
        out[3] = (byte) 0xC0; // command + response requested
        out[4] = (byte) opcode;
        out[5] = (byte) (payloadLength >>> 8);
        out[6] = (byte) payloadLength;
        out[7] = (byte) sequence;
        System.arraycopy(parameters, 0, out, 8, parameters.length);
        out[out.length - 1] = (byte) 0xEF;
        return out;
    }

    public static Frame parse(byte[] raw) {
        if (raw == null || raw.length < 8) throw new IllegalArgumentException("frame too short");
        if (raw[0] != PREFIX[0] || raw[1] != PREFIX[1] || raw[2] != PREFIX[2]) {
            throw new IllegalArgumentException("bad RCSP prefix");
        }
        int payloadLength = ((raw[5] & 0xFF) << 8) | (raw[6] & 0xFF);
        if (raw.length != payloadLength + 8) throw new IllegalArgumentException("length mismatch");
        if (raw[raw.length - 1] != (byte) 0xEF) throw new IllegalArgumentException("bad RCSP suffix");
        int flags = raw[3] & 0xFF;
        if (flags != 0x00 && flags != 0x80 && flags != 0xC0) {
            throw new IllegalArgumentException("unsupported RCSP flags");
        }
        if (flags == 0x00 && payloadLength < 2) {
            throw new IllegalArgumentException("response payload is shorter than status and sequence");
        }
        return new Frame(flags, raw[4] & 0xFF,
                Arrays.copyOfRange(raw, 7, raw.length - 1), raw.clone());
    }

    public static final class Frame {
        public final int flags;
        public final int opcode;
        public final byte[] payload;
        public final byte[] raw;

        private Frame(int flags, int opcode, byte[] payload, byte[] raw) {
            this.flags = flags;
            this.opcode = opcode;
            this.payload = payload;
            this.raw = raw;
        }

        public boolean isResponse() {
            return flags == 0x00;
        }

        public int status() {
            requireResponsePayload();
            return payload[0] & 0xFF;
        }

        public int sequence() {
            requireResponsePayload();
            return payload[1] & 0xFF;
        }

        public byte[] data() {
            requireResponsePayload();
            return Arrays.copyOfRange(payload, 2, payload.length);
        }

        private void requireResponsePayload() {
            if (!isResponse() || payload.length < 2) {
                throw new IllegalStateException("not a complete response packet");
            }
        }
    }

    public static final class StopBrowseCommand {
        public final int sequence;
        public final int reason;

        private StopBrowseCommand(int sequence, int reason) {
            this.sequence = sequence;
            this.reason = reason;
        }
    }
}
