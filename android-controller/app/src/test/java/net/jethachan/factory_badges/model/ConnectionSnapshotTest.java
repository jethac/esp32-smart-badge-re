package net.jethachan.factory_badges.model;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.protocol.BuildInfoCodec;
import org.junit.Test;

public final class ConnectionSnapshotTest {
    private static final BadgeState INITIAL = new BadgeState(0, 0, 1727);

    @Test
    public void immutableSnapshotUsesValueEqualityAndPreservesAcknowledgedState() {
        BuildInfo info = buildInfo();
        BadgeState acknowledged = new BadgeState(30, 40, 1727);
        UserVisibleError error = new UserVisibleError(
                UserVisibleError.Code.CONNECT_FAILED, 133);
        ConnectionSnapshot left = new ConnectionSnapshot(
                true, ConnectionSnapshot.Phase.RETRY_WAIT, "E87", "AA:BB",
                true, INITIAL, info, 71, acknowledged, 1234L, 1000L, error);
        ConnectionSnapshot right = new ConnectionSnapshot(
                true, ConnectionSnapshot.Phase.RETRY_WAIT, "E87", "AA:BB",
                true, INITIAL, info, 71, acknowledged, 1234L, 1000L, error);

        assertEquals(left, right);
        assertEquals(left.hashCode(), right.hashCode());
        assertEquals(acknowledged, left.lastAcknowledgedState());
        assertEquals(Long.valueOf(1234L), left.lastAcknowledgedElapsedMs());
        assertEquals(Integer.valueOf(71), left.batteryPercent());
        assertNotEquals(left, disabled());
    }

    @Test
    public void rejectsBatteryOutsidePercentageRange() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.READY,
                        "E87", "AA:BB", true, INITIAL, buildInfo(), 101,
                        null, null, null, null);
            }
        });
    }

    @Test
    public void rejectsHalfOfAcknowledgmentPairAndReadyWithoutBuildInfo() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(false, ConnectionSnapshot.Phase.DISABLED,
                        null, null, false, INITIAL, null, null,
                        INITIAL, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.READY,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, null, null);
            }
        });
    }

    @Test
    public void userVisibleErrorsHaveStableSafeValues() {
        UserVisibleError retryable = new UserVisibleError(
                UserVisibleError.Code.GATT_TIMEOUT);
        assertEquals("The badge did not respond in time.", retryable.message());
        assertTrue(retryable.retryable());
        assertEquals(-1, retryable.gattStatus());

        UserVisibleError security = new UserVisibleError(
                UserVisibleError.Code.LINK_SECURITY_FAILED, 15);
        assertEquals("The bonded link could not be secured.", security.message());
        assertFalse(security.retryable());
        assertEquals(15, security.gattStatus());
    }


    @Test
    public void exposesAllSnapshotFieldsWithoutMutableFrameworkObjects() {
        BuildInfo info = buildInfo();
        BadgeState acknowledged = new BadgeState(1, 2, 1727);
        UserVisibleError error = new UserVisibleError(
                UserVisibleError.Code.CONNECT_FAILED, 133);
        ConnectionSnapshot snapshot = new ConnectionSnapshot(
                true, ConnectionSnapshot.Phase.RETRY_WAIT, "E87", "AA:BB",
                true, INITIAL, info, 100, acknowledged, 55L, 0L, error);

        assertTrue(snapshot.syncEnabled());
        assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT, snapshot.phase());
        assertEquals("E87", snapshot.selectedDeviceName());
        assertEquals("AA:BB", snapshot.selectedDeviceAddress());
        assertTrue(snapshot.bonded());
        assertEquals(INITIAL, snapshot.currentState());
        assertEquals(info, snapshot.buildInfo());
        assertEquals(Integer.valueOf(100), snapshot.batteryPercent());
        assertEquals(acknowledged, snapshot.lastAcknowledgedState());
        assertEquals(Long.valueOf(55L), snapshot.lastAcknowledgedElapsedMs());
        assertEquals(Long.valueOf(0L), snapshot.nextReconnectDelayMs());
        assertEquals(error, snapshot.error());
    }

    @Test
    public void phaseAndSyncStateMustAgree() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.DISABLED,
                        null, null, false, INITIAL, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(false, ConnectionSnapshot.Phase.NO_DEVICE,
                        null, null, false, INITIAL, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.NO_DEVICE,
                        "E87", "AA:BB", false, INITIAL, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.CONNECTING,
                        "E87", null, false, INITIAL, null, null,
                        null, null, null, null);
            }
        });
    }

    @Test
    public void retryAndErrorPhasesRequireTheirSpecificContext() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.RETRY_WAIT,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.ERROR,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.CONNECTING,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, 1000L, null);
            }
        });
    }

    @Test
    public void validatesNullsRangesAndElapsedValues() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(false, null, null, null, false,
                        INITIAL, null, null, null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(false, ConnectionSnapshot.Phase.DISABLED,
                        null, null, false, null, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(false, ConnectionSnapshot.Phase.DISABLED,
                        null, " ", false, INITIAL, null, null,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.READY,
                        "E87", "AA:BB", false, INITIAL, buildInfo(), 50,
                        null, null, null, null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.RETRY_WAIT,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        INITIAL, -1L, 0L,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED));
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.RETRY_WAIT,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, -1L,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED));
            }
        });
    }

    @Test
    public void retryWaitAcceptsOnlyRetryableErrorsAndErrorAcceptsOnlyTerminalErrors() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.RETRY_WAIT,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, 1000L,
                        new UserVisibleError(UserVisibleError.Code.LINK_SECURITY_FAILED));
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new ConnectionSnapshot(true, ConnectionSnapshot.Phase.ERROR,
                        "E87", "AA:BB", true, INITIAL, null, null,
                        null, null, null,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED));
            }
        });
    }

    private static ConnectionSnapshot disabled() {
        return new ConnectionSnapshot(false, ConnectionSnapshot.Phase.DISABLED,
                null, null, false, INITIAL, null, null,
                null, null, null, null);
    }

    private static BuildInfo buildInfo() {
        return new BuildInfo(1, BuildInfoCodec.HARDWARE_PROFILE, 1, 0, 0, new byte[16]);
    }

    private static void expectIllegalArgument(Runnable action) {
        try {
            action.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError("expected IllegalArgumentException");
    }
}
