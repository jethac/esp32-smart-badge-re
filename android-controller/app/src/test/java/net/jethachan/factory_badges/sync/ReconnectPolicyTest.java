package net.jethachan.factory_badges.sync;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ReconnectPolicyTest {
    @Test
    public void returnsExactCappedSequenceAndCountsFailures() {
        ReconnectPolicy policy = new ReconnectPolicy();
        long[] actual = new long[8];
        for (int index = 0; index < actual.length; index++) {
            actual[index] = policy.nextDelayMs();
        }

        assertArrayEquals(new long[] {0, 1000, 2000, 4000, 8000, 15000, 15000, 15000},
                actual);
        assertEquals(8, policy.failureCount());
    }

    @Test
    public void resetRestartsAtImmediateAttempt() {
        ReconnectPolicy policy = new ReconnectPolicy();
        policy.nextDelayMs();
        policy.nextDelayMs();
        policy.reset();

        assertEquals(0, policy.failureCount());
        assertEquals(0, policy.nextDelayMs());
    }
}
