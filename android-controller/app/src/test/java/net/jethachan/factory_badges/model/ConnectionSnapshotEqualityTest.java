package net.jethachan.factory_badges.model;

import static org.junit.Assert.assertNotEquals;

import java.lang.reflect.Field;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.protocol.BuildInfoCodec;
import org.junit.Test;

public final class ConnectionSnapshotEqualityTest {
    private static final BadgeState CURRENT = new BadgeState(10, 20, 1727);
    private static final BadgeState OTHER_STATE = new BadgeState(11, 20, 1727);

    @Test
    public void equalityAndHashDetectEachIndependentlyVariableField() {
        assertDifferent(connecting(ConnectionSnapshot.Phase.CONNECTING),
                connecting(ConnectionSnapshot.Phase.DISCOVERING));

        assertDifferent(disabled("E87", "AA:BB", false, CURRENT,
                        null, null, null, null),
                disabled("E87-ALT", "AA:BB", false, CURRENT,
                        null, null, null, null));
        assertDifferent(disabled("E87", "AA:BB", false, CURRENT,
                        null, null, null, null),
                disabled("E87", "CC:DD", false, CURRENT,
                        null, null, null, null));
        assertDifferent(disabled("E87", "AA:BB", false, CURRENT,
                        null, null, null, null),
                disabled("E87", "AA:BB", true, CURRENT,
                        null, null, null, null));
        assertDifferent(disabled("E87", "AA:BB", false, CURRENT,
                        null, null, null, null),
                disabled("E87", "AA:BB", false, OTHER_STATE,
                        null, null, null, null));

        assertDifferent(disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), null, null, null),
                disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(2), null, null, null));
        assertDifferent(disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), 50, null, null),
                disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), 51, null, null));
        assertDifferent(disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), null, CURRENT, 10L),
                disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), null, OTHER_STATE, 10L));
        assertDifferent(disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), null, CURRENT, 10L),
                disabled("E87", "AA:BB", true, CURRENT,
                        buildInfo(1), null, CURRENT, 11L));

        assertDifferent(retry(1000L,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133)),
                retry(2000L,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133)));
        assertDifferent(retry(1000L,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133)),
                retry(1000L,
                        new UserVisibleError(UserVisibleError.Code.GATT_TIMEOUT, 133)));
    }

    @Test
    public void equalityIncludesSyncFlagEvenThoughConstructorCouplesItToPhase()
            throws Exception {
        ConnectionSnapshot disabled = disabled(
                null, null, false, CURRENT, null, null, null, null);
        ConnectionSnapshot corruptedCopy = disabled(
                null, null, false, CURRENT, null, null, null, null);
        Field syncEnabled = ConnectionSnapshot.class.getDeclaredField("syncEnabled");
        syncEnabled.setAccessible(true);
        syncEnabled.setBoolean(corruptedCopy, true);

        assertDifferent(disabled, corruptedCopy);
    }

    private static ConnectionSnapshot connecting(ConnectionSnapshot.Phase phase) {
        return new ConnectionSnapshot(
                true, phase, "E87", "AA:BB", true, CURRENT,
                null, null, null, null, null, null);
    }

    private static ConnectionSnapshot disabled(
            String name,
            String address,
            boolean bonded,
            BadgeState current,
            BuildInfo buildInfo,
            Integer battery,
            BadgeState acknowledged,
            Long acknowledgedMs) {
        return new ConnectionSnapshot(
                false, ConnectionSnapshot.Phase.DISABLED,
                name, address, bonded, current, buildInfo, battery,
                acknowledged, acknowledgedMs, null, null);
    }

    private static ConnectionSnapshot retry(Long delay, UserVisibleError error) {
        return new ConnectionSnapshot(
                true, ConnectionSnapshot.Phase.RETRY_WAIT,
                "E87", "AA:BB", true, CURRENT, buildInfo(1), 50,
                CURRENT, 8L, delay, error);
    }

    private static BuildInfo buildInfo(int major) {
        return new BuildInfo(
                BuildInfoCodec.CAPABILITY_SEMANTIC_METRICS,
                BuildInfoCodec.HARDWARE_PROFILE,
                major, 0, 0, new byte[16]);
    }

    private static void assertDifferent(
            ConnectionSnapshot left, ConnectionSnapshot right) {
        assertNotEquals(left, right);
        assertNotEquals(right, left);
        assertNotEquals(left.hashCode(), right.hashCode());
    }
}
