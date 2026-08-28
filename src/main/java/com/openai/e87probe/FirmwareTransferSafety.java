package com.openai.e87probe;

/**
 * Pure fail-closed decisions for the destructive portion of a fresh Qix transfer.
 */
public final class FirmwareTransferSafety {
    public enum C5Disposition {
        ACCEPT,
        DEFER,
        REJECT
    }

    private FirmwareTransferSafety() {}

    public static void requireFreshC1Offset(int offset) {
        if (offset != 0) {
            throw new IllegalArgumentException(
                    "One-shot upload requires a fresh C1 offset of zero");
        }
    }

    public static C5Disposition c5Disposition(
            boolean updateAccepted,
            boolean finalC2Started,
            boolean finalC2WriteCompleted,
            int acknowledgedOffset,
            int payloadLength) {
        if (!updateAccepted
                || payloadLength <= 0
                || acknowledgedOffset < 0
                || acknowledgedOffset > payloadLength) {
            return C5Disposition.REJECT;
        }
        if (!finalC2Started) {
            return C5Disposition.REJECT;
        }
        return finalC2WriteCompleted ? C5Disposition.ACCEPT : C5Disposition.DEFER;
    }
}
