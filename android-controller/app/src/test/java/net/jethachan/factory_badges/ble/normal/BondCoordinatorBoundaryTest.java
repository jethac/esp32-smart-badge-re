package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import org.junit.Test;

public final class BondCoordinatorBoundaryTest {
    @Test
    public void everyStartFailureReportsItsExactGeneration() {
        RecordingListener listener = new RecordingListener();

        new BondCoordinator(new FakePort(null, null, true), listener)
                .ensureBonded(21);
        new BondCoordinator(new FakePort(
                BondCoordinator.BondState.NONE,
                new SecurityException("not user visible"), true), listener)
                .ensureBonded(22);
        new BondCoordinator(new FakePort(
                BondCoordinator.BondState.NONE, null, false), listener)
                .ensureBonded(23);
        FakePort createThrows = new FakePort(
                BondCoordinator.BondState.NONE, null, true);
        createThrows.createFailure = new IllegalStateException("not user visible");
        new BondCoordinator(createThrows, listener).ensureBonded(24);

        assertEquals(listOf(21L, 22L, 23L, 24L), listener.failedGenerations);
        assertEquals(4, listener.errors.size());
        for (UserVisibleError error : listener.errors) {
            assertEquals(UserVisibleError.Code.BOND_START_FAILED, error.code());
        }
    }

    @Test
    public void productionSourceContainsNoBondRemovalOrReflectionEscapeHatch()
            throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/"
                        + "BondCoordinator.java")), StandardCharsets.UTF_8);

        assertFalse(source.contains("removeBond"));
        assertFalse(source.contains("remove_bond"));
        assertFalse(source.contains("getDeclaredMethod"));
        assertFalse(source.contains("getMethod("));
        assertFalse(source.contains("java.lang.reflect"));
    }

    private static List<Long> listOf(Long... values) {
        List<Long> result = new ArrayList<Long>();
        for (Long value : values) {
            result.add(value);
        }
        return result;
    }

    private static final class FakePort implements BondCoordinator.Port {
        final BondCoordinator.BondState state;
        final RuntimeException stateFailure;
        final boolean createResult;
        RuntimeException createFailure;

        FakePort(BondCoordinator.BondState state,
                RuntimeException stateFailure, boolean createResult) {
            this.state = state;
            this.stateFailure = stateFailure;
            this.createResult = createResult;
        }

        @Override public BondCoordinator.BondState currentState() {
            if (stateFailure != null) {
                throw stateFailure;
            }
            return state;
        }

        @Override public boolean createBond() {
            if (createFailure != null) {
                throw createFailure;
            }
            return createResult;
        }
    }

    private static final class RecordingListener implements BondCoordinator.Listener {
        final List<Long> failedGenerations = new ArrayList<Long>();
        final List<UserVisibleError> errors = new ArrayList<UserVisibleError>();

        @Override public void onBonded(long generation) {
        }

        @Override public void onBondFailed(long generation, UserVisibleError error) {
            failedGenerations.add(Long.valueOf(generation));
            errors.add(error);
        }
    }
}
