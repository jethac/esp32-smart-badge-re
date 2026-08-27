package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertEquals;

import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import org.junit.Test;

public final class BondCoordinatorTest {
    @Test
    public void alreadyBondedCompletesSynchronouslyExactlyOnce() {
        FakePort port = new FakePort(BondCoordinator.BondState.BONDED);
        RecordingListener listener = new RecordingListener();
        BondCoordinator coordinator = new BondCoordinator(port, listener);

        coordinator.ensureBonded(1);
        coordinator.onBondStateChanged(1, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.BONDED);

        assertEquals(BondCoordinator.State.BONDED, coordinator.state());
        assertEquals(0, port.createCalls);
        assertEquals(listOf(1L), listener.bonded);
        assertEquals(0, listener.errors.size());
    }

    @Test
    public void existingBondingWaitsWithoutStartingAnotherRequest() {
        FakePort port = new FakePort(BondCoordinator.BondState.BONDING);
        RecordingListener listener = new RecordingListener();
        BondCoordinator coordinator = new BondCoordinator(port, listener);

        coordinator.ensureBonded(2);

        assertEquals(BondCoordinator.State.WAITING, coordinator.state());
        assertEquals(0, port.createCalls);
    }

    @Test
    public void noneStartsOneBondAndCompletesOnMatchingEvent() {
        FakePort port = new FakePort(BondCoordinator.BondState.NONE);
        RecordingListener listener = new RecordingListener();
        BondCoordinator coordinator = new BondCoordinator(port, listener);

        coordinator.ensureBonded(3);
        coordinator.onBondStateChanged(99, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.BONDED);
        coordinator.onBondStateChanged(3, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.BONDED);

        assertEquals(1, port.createCalls);
        assertEquals(listOf(3L), listener.bonded);
    }

    @Test
    public void falseOrThrowingBondStartReportsOneSafeFailure() {
        FakePort falsePort = new FakePort(BondCoordinator.BondState.NONE);
        falsePort.createResult = false;
        RecordingListener first = new RecordingListener();
        BondCoordinator falseCoordinator = new BondCoordinator(falsePort, first);
        falseCoordinator.ensureBonded(4);

        FakePort throwingPort = new FakePort(BondCoordinator.BondState.NONE);
        throwingPort.failure = new SecurityException("secret exception text");
        RecordingListener second = new RecordingListener();
        BondCoordinator throwingCoordinator = new BondCoordinator(throwingPort, second);
        throwingCoordinator.ensureBonded(5);

        assertEquals(UserVisibleError.Code.BOND_START_FAILED, first.errors.get(0).code());
        assertEquals(UserVisibleError.Code.BOND_START_FAILED, second.errors.get(0).code());
        assertEquals(first.errors.get(0).message(), second.errors.get(0).message());
    }

    @Test
    public void failedAndLostBondsAreDistinctAndDuplicateEventsAreIgnored() {
        FakePort port = new FakePort(BondCoordinator.BondState.BONDING);
        RecordingListener listener = new RecordingListener();
        BondCoordinator coordinator = new BondCoordinator(port, listener);
        coordinator.ensureBonded(6);
        coordinator.onBondStateChanged(6, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.NONE);
        coordinator.onBondStateChanged(6, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.NONE);
        assertEquals(1, listener.errors.size());
        assertEquals(UserVisibleError.Code.BOND_FAILED, listener.errors.get(0).code());

        FakePort bondedPort = new FakePort(BondCoordinator.BondState.BONDED);
        RecordingListener lostListener = new RecordingListener();
        BondCoordinator bonded = new BondCoordinator(bondedPort, lostListener);
        bonded.ensureBonded(7);
        bonded.onBondStateChanged(7, BondCoordinator.BondState.BONDED,
                BondCoordinator.BondState.NONE);
        bonded.onBondStateChanged(7, BondCoordinator.BondState.BONDED,
                BondCoordinator.BondState.NONE);
        assertEquals(1, lostListener.errors.size());
        assertEquals(UserVisibleError.Code.BOND_LOST, lostListener.errors.get(0).code());
    }

    @Test
    public void cancelInvalidatesGeneration() {
        FakePort port = new FakePort(BondCoordinator.BondState.BONDING);
        RecordingListener listener = new RecordingListener();
        BondCoordinator coordinator = new BondCoordinator(port, listener);
        coordinator.ensureBonded(8);
        coordinator.cancel(8);
        coordinator.onBondStateChanged(8, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.BONDED);

        assertEquals(BondCoordinator.State.IDLE, coordinator.state());
        assertEquals(0, listener.bonded.size());
    }


    @Test
    public void duplicateEnsureForActiveGenerationCreatesBondOnlyOnce() {
        FakePort port = new FakePort(BondCoordinator.BondState.NONE);
        BondCoordinator coordinator = new BondCoordinator(port, new RecordingListener());

        coordinator.ensureBonded(9);
        coordinator.ensureBonded(9);

        assertEquals(1, port.createCalls);
        assertEquals(BondCoordinator.State.WAITING, coordinator.state());
    }

    @Test
    public void staleCancelDoesNotInvalidateCurrentGeneration() {
        FakePort port = new FakePort(BondCoordinator.BondState.BONDING);
        RecordingListener listener = new RecordingListener();
        BondCoordinator coordinator = new BondCoordinator(port, listener);

        coordinator.ensureBonded(10);
        coordinator.cancel(11);
        coordinator.onBondStateChanged(10, BondCoordinator.BondState.BONDING,
                BondCoordinator.BondState.BONDED);

        assertEquals(listOf(10L), listener.bonded);
    }

    @Test
    public void constructorAndAllGenerationInputsAreValidated() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new BondCoordinator(null, new RecordingListener());
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new BondCoordinator(new FakePort(BondCoordinator.BondState.NONE), null);
            }
        });

        final BondCoordinator coordinator = new BondCoordinator(
                new FakePort(BondCoordinator.BondState.NONE), new RecordingListener());
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                coordinator.ensureBonded(0);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                coordinator.onBondStateChanged(-1, BondCoordinator.BondState.NONE,
                        BondCoordinator.BondState.BONDED);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                coordinator.cancel(0);
            }
        });
    }

    @Test
    public void publicSurfaceContainsNoBondRemovalCapability() {
        Set<String> coordinatorMethods = methodNames(BondCoordinator.class.getDeclaredMethods());
        Set<String> portMethods = methodNames(BondCoordinator.Port.class.getDeclaredMethods());

        assertEquals(setOf("ensureBonded", "onBondStateChanged", "cancel", "state"),
                coordinatorMethods);
        assertEquals(setOf("currentState", "createBond"), portMethods);
    }


    private static Set<String> methodNames(Method[] methods) {
        Set<String> names = new HashSet<String>();
        for (Method method : methods) {
            if (Modifier.isPublic(method.getModifiers()) && !method.isSynthetic()) {
                names.add(method.getName());
            }
        }
        return names;
    }

    private static Set<String> setOf(String... values) {
        Set<String> result = new HashSet<String>();
        for (String value : values) {
            result.add(value);
        }
        return result;
    }

    private static void expectIllegalArgument(Runnable action) {
        try {
            action.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError("expected IllegalArgumentException");
    }

    private static List<Long> listOf(long value) {
        List<Long> result = new ArrayList<Long>();
        result.add(Long.valueOf(value));
        return result;
    }

    private static final class FakePort implements BondCoordinator.Port {
        BondCoordinator.BondState state;
        boolean createResult = true;
        RuntimeException failure;
        int createCalls;

        FakePort(BondCoordinator.BondState state) {
            this.state = state;
        }

        @Override public BondCoordinator.BondState currentState() {
            return state;
        }

        @Override public boolean createBond() {
            createCalls++;
            if (failure != null) {
                throw failure;
            }
            return createResult;
        }
    }

    private static final class RecordingListener implements BondCoordinator.Listener {
        final List<Long> bonded = new ArrayList<Long>();
        final List<UserVisibleError> errors = new ArrayList<UserVisibleError>();

        @Override public void onBonded(long generation) {
            bonded.add(Long.valueOf(generation));
        }

        @Override public void onBondFailed(long generation, UserVisibleError error) {
            errors.add(error);
        }
    }
}
