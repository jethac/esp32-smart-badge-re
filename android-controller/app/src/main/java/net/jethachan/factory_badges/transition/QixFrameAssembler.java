package net.jethachan.factory_badges.transition;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Bounded, per-channel reassembly for Qix notification fragments. */
public final class QixFrameAssembler {
    private byte[] pending;
    private int used;

    public List<QixFrame> accept(byte[] fragment) {
        if (fragment == null) {
            throw new IllegalArgumentException("fragment must not be null");
        }
        if (fragment.length == 0) {
            return Collections.emptyList();
        }

        List<QixFrame> frames = new ArrayList<QixFrame>();
        try {
            for (byte value : fragment) {
                append(value, frames);
            }
        } catch (IllegalArgumentException failure) {
            reset();
            throw failure;
        }
        if (frames.isEmpty()) {
            return Collections.emptyList();
        }
        return Collections.unmodifiableList(frames);
    }

    public void reset() {
        pending = null;
        used = 0;
    }

    private void append(byte value, List<QixFrame> frames) {
        if (pending == null) {
            if ((value & 0xFF) != QixFrameCodec.MAGIC) {
                throw new IllegalArgumentException("Qix fragment does not start with magic");
            }
            pending = new byte[QixFrameCodec.HEADER_LENGTH];
            used = 0;
        }

        pending[used++] = value;
        if (used == QixFrameCodec.HEADER_LENGTH) {
            int payloadLength = (pending[4] & 0xFF) | ((pending[5] & 0xFF) << 8);
            int frameLength = QixFrameCodec.HEADER_LENGTH + payloadLength;
            if (frameLength > QixFrameCodec.MAX_FRAME_LENGTH) {
                throw new IllegalArgumentException("Qix frame exceeds maximum length");
            }
            pending = Arrays.copyOf(pending, frameLength);
        }
        if (used == pending.length) {
            frames.add(QixFrameCodec.decode(pending));
            reset();
        }
    }
}
