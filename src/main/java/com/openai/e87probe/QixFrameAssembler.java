package com.openai.e87probe;

import java.util.Arrays;

final class QixFrameAssembler {
    private byte[] pending;
    private int used;

    byte[] append(byte[] chunk) {
        if (chunk == null || chunk.length == 0) return null;
        if (pending == null) {
            if (chunk.length < 6 || (chunk[0] & 0xFF) != 0x9E) return null;
            int payloadLength = (chunk[4] & 0xFF) | ((chunk[5] & 0xFF) << 8);
            int expected = payloadLength + 6;
            if (chunk.length >= expected) return Arrays.copyOf(chunk, expected);
            pending = new byte[expected];
            System.arraycopy(chunk, 0, pending, 0, chunk.length);
            used = chunk.length;
            return null;
        }

        int copied = Math.min(chunk.length, pending.length - used);
        System.arraycopy(chunk, 0, pending, used, copied);
        used += copied;
        if (used < pending.length) return null;
        byte[] complete = pending;
        pending = null;
        used = 0;
        return complete;
    }
}
