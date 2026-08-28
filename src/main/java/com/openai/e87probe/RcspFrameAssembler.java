package com.openai.e87probe;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class RcspFrameAssembler {
    private static final byte[] PREFIX = {(byte) 0xFE, (byte) 0xDC, (byte) 0xBA};
    private final int maxFrameBytes;
    private byte[] buffered = new byte[0];

    public RcspFrameAssembler(int maxFrameBytes) {
        if (maxFrameBytes < 8) throw new IllegalArgumentException("maxFrameBytes must be >= 8");
        this.maxFrameBytes = maxFrameBytes;
    }

    public List<byte[]> offer(byte[] chunk) {
        if (chunk == null || chunk.length == 0) return new ArrayList<>();
        byte[] joined = Arrays.copyOf(buffered, buffered.length + chunk.length);
        System.arraycopy(chunk, 0, joined, buffered.length, chunk.length);
        buffered = joined;

        List<byte[]> frames = new ArrayList<>();
        while (true) {
            int prefix = findPrefix(buffered);
            if (prefix < 0) {
                preservePartialPrefix();
                return frames;
            }
            if (prefix > 0) buffered = Arrays.copyOfRange(buffered, prefix, buffered.length);
            if (buffered.length < 7) return frames;

            int payloadLength = ((buffered[5] & 0xFF) << 8) | (buffered[6] & 0xFF);
            int totalLength = payloadLength + 8;
            if (totalLength > maxFrameBytes) {
                buffered = Arrays.copyOfRange(buffered, 1, buffered.length);
                continue;
            }
            if (buffered.length < totalLength) return frames;
            if (buffered[totalLength - 1] != (byte) 0xEF) {
                buffered = Arrays.copyOfRange(buffered, 1, buffered.length);
                continue;
            }
            frames.add(Arrays.copyOfRange(buffered, 0, totalLength));
            buffered = Arrays.copyOfRange(buffered, totalLength, buffered.length);
        }
    }

    private static int findPrefix(byte[] data) {
        for (int i = 0; i <= data.length - PREFIX.length; i++) {
            if (data[i] == PREFIX[0] && data[i + 1] == PREFIX[1] && data[i + 2] == PREFIX[2]) {
                return i;
            }
        }
        return -1;
    }

    private void preservePartialPrefix() {
        if (buffered.length >= 2
                && buffered[buffered.length - 2] == PREFIX[0]
                && buffered[buffered.length - 1] == PREFIX[1]) {
            buffered = Arrays.copyOfRange(buffered, buffered.length - 2, buffered.length);
        } else if (buffered.length >= 1 && buffered[buffered.length - 1] == PREFIX[0]) {
            buffered = Arrays.copyOfRange(buffered, buffered.length - 1, buffered.length);
        } else {
            buffered = new byte[0];
        }
    }
}
