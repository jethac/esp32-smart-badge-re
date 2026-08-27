package net.jethachan.factory_badges.sync;

public final class ReconnectPolicy {
    private static final long[] DELAYS_MS =
            new long[] {0L, 1000L, 2000L, 4000L, 8000L, 15000L};

    private int failureCount;

    public long nextDelayMs() {
        int index = Math.min(failureCount, DELAYS_MS.length - 1);
        if (failureCount < Integer.MAX_VALUE) {
            failureCount++;
        }
        return DELAYS_MS[index];
    }

    public void reset() {
        failureCount = 0;
    }

    public int failureCount() {
        return failureCount;
    }
}
