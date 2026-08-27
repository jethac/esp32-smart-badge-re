package net.jethachan.factory_badges.model;

import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.protocol.BuildInfoCodec;
import org.junit.Test;

public final class ConnectionSnapshotInvariantTest {
    private static final BadgeState CURRENT = new BadgeState(0, 0, 1727);

    @Test
    public void noDeviceHasNoSelectionBondOrConnectionMetadata() {
        snapshot(ConnectionSnapshot.Phase.NO_DEVICE, null, null,
                false, null, null, null, null, null, null);

        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.NO_DEVICE, "E87", "AA:BB",
                        false, null, null, null, null, null, null);
            }
        });
        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.NO_DEVICE, null, null,
                        true, null, null, null, null, null, null);
            }
        });
        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.NO_DEVICE, null, null,
                        false, buildInfo(1), null, null, null, null, null);
            }
        });
        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.NO_DEVICE, null, null,
                        false, buildInfo(1), 50, null, null, null, null);
            }
        });
    }

    @Test
    public void bondingHasSelectedDeviceButNoBondOrValidatedMetadata() {
        snapshot(ConnectionSnapshot.Phase.BONDING, "E87", "AA:BB",
                false, null, null, null, null, null, null);

        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.BONDING, "E87", "AA:BB",
                        true, null, null, null, null, null, null);
            }
        });
        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.BONDING, "E87", "AA:BB",
                        false, buildInfo(1), null, null, null, null, null);
            }
        });
    }

    @Test
    public void connectedPreReadyPhasesRequireBondAndRejectValidatedMetadata() {
        final ConnectionSnapshot.Phase[] phases = new ConnectionSnapshot.Phase[] {
                ConnectionSnapshot.Phase.CONNECTING,
                ConnectionSnapshot.Phase.DISCOVERING,
                ConnectionSnapshot.Phase.VALIDATING_BUILD
        };
        for (final ConnectionSnapshot.Phase phase : phases) {
            snapshot(phase, "E87", "AA:BB",
                    true, null, null, null, null, null, null);
            reject(new Factory() {
                @Override public ConnectionSnapshot create() {
                    return snapshot(phase, "E87", "AA:BB",
                            false, null, null, null, null, null, null);
                }
            });
            reject(new Factory() {
                @Override public ConnectionSnapshot create() {
                    return snapshot(phase, "E87", "AA:BB",
                            true, buildInfo(1), null, null, null, null, null);
                }
            });
            reject(new Factory() {
                @Override public ConnectionSnapshot create() {
                    return snapshot(phase, "E87", "AA:BB",
                            true, buildInfo(1), 60, null, null, null, null);
                }
            });
        }
    }

    @Test
    public void batteryAlwaysRequiresValidatedBuildInfo() {
        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return new ConnectionSnapshot(
                        false, ConnectionSnapshot.Phase.DISABLED,
                        "E87", "AA:BB", true, CURRENT, null, 75,
                        null, null, null, null);
            }
        });
    }

    @Test
    public void metadataNeverExistsWithoutSelectedDeviceAddress() {
        reject(disabledWithoutAddress("E87", false, null, null, null, null));
        reject(disabledWithoutAddress(null, true, null, null, null, null));
        reject(disabledWithoutAddress(null, false, buildInfo(1), null, null, null));
        reject(disabledWithoutAddress(null, false, buildInfo(1), 50, null, null));
        reject(disabledWithoutAddress(null, false, null, null, CURRENT, 4L));
    }

    @Test
    public void retryWaitModelsBondedDisconnectWithOrWithoutPriorMetadata() {
        UserVisibleError error =
                new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133);
        snapshot(ConnectionSnapshot.Phase.RETRY_WAIT, "E87", "AA:BB",
                true, null, null, null, null, 0L, error);
        snapshot(ConnectionSnapshot.Phase.RETRY_WAIT, "E87", "AA:BB",
                true, buildInfo(1), 88, CURRENT, 25L, 1000L, error);

        reject(new Factory() {
            @Override public ConnectionSnapshot create() {
                return snapshot(ConnectionSnapshot.Phase.RETRY_WAIT, "E87", "AA:BB",
                        false, null, null, null, null, 0L,
                        new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED));
            }
        });
    }

    @Test
    public void terminalErrorMayRepresentFailureBeforeOrAfterBuildValidation() {
        snapshot(ConnectionSnapshot.Phase.ERROR, "E87", "AA:BB",
                false, null, null, null, null, null,
                new UserVisibleError(UserVisibleError.Code.BOND_FAILED));
        snapshot(ConnectionSnapshot.Phase.ERROR, "E87", "AA:BB",
                true, buildInfo(1), 90, CURRENT, 99L, null,
                new UserVisibleError(UserVisibleError.Code.LINK_SECURITY_FAILED, 15));
    }

    @Test
    public void disabledMayRetainSelectedDeviceAndLastValidatedValues() {
        new ConnectionSnapshot(
                false, ConnectionSnapshot.Phase.DISABLED,
                "E87", "AA:BB", true, CURRENT, buildInfo(1), 67,
                CURRENT, 123L, null, null);
    }

    private static Factory disabledWithoutAddress(
            final String name,
            final boolean bonded,
            final BuildInfo buildInfo,
            final Integer battery,
            final BadgeState acknowledged,
            final Long acknowledgedMs) {
        return new Factory() {
            @Override public ConnectionSnapshot create() {
                return new ConnectionSnapshot(
                        false, ConnectionSnapshot.Phase.DISABLED,
                        name, null, bonded, CURRENT, buildInfo, battery,
                        acknowledged, acknowledgedMs, null, null);
            }
        };
    }

    private static ConnectionSnapshot snapshot(
            ConnectionSnapshot.Phase phase,
            String name,
            String address,
            boolean bonded,
            BuildInfo buildInfo,
            Integer battery,
            BadgeState acknowledged,
            Long acknowledgedMs,
            Long reconnectDelay,
            UserVisibleError error) {
        return new ConnectionSnapshot(
                true, phase, name, address, bonded, CURRENT, buildInfo, battery,
                acknowledged, acknowledgedMs, reconnectDelay, error);
    }

    private static BuildInfo buildInfo(int major) {
        return new BuildInfo(
                BuildInfoCodec.CAPABILITY_SEMANTIC_METRICS,
                BuildInfoCodec.HARDWARE_PROFILE,
                major, 0, 0, new byte[16]);
    }

    private static void reject(Factory factory) {
        try {
            factory.create();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError("expected impossible snapshot to be rejected");
    }

    private interface Factory {
        ConnectionSnapshot create();
    }
}
