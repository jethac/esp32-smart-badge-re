package net.jethachan.factory_badges.ble.normal;

import net.jethachan.factory_badges.diagnostic.UserVisibleError;

public final class BondCoordinator {
    public enum BondState {
        NONE,
        BONDING,
        BONDED
    }

    public enum State {
        IDLE,
        WAITING,
        BONDED,
        FAILED
    }

    public interface Port {
        BondState currentState();

        boolean createBond();
    }

    public interface Listener {
        void onBonded(long generation);

        void onBondFailed(long generation, UserVisibleError error);
    }

    private final Port port;
    private final Listener listener;

    private long activeGeneration;
    private State state = State.IDLE;
    private boolean bondedReported;
    private boolean failureReported;

    public BondCoordinator(Port port, Listener listener) {
        if (port == null) {
            throw new IllegalArgumentException("port must not be null");
        }
        if (listener == null) {
            throw new IllegalArgumentException("listener must not be null");
        }
        this.port = port;
        this.listener = listener;
    }

    public void ensureBonded(long generation) {
        requirePositive(generation);
        if (generation == activeGeneration && state != State.IDLE) {
            return;
        }

        activeGeneration = generation;
        state = State.IDLE;
        bondedReported = false;
        failureReported = false;

        BondState current;
        try {
            current = port.currentState();
        } catch (RuntimeException failure) {
            fail(generation, UserVisibleError.Code.BOND_START_FAILED);
            return;
        }
        if (current == null) {
            fail(generation, UserVisibleError.Code.BOND_START_FAILED);
            return;
        }

        switch (current) {
            case BONDED:
                reportBonded(generation);
                return;
            case BONDING:
                state = State.WAITING;
                return;
            case NONE:
                state = State.WAITING;
                startBond(generation);
                return;
            default:
                throw new AssertionError("unhandled bond state");
        }
    }

    public void onBondStateChanged(
            long generation, BondState previous, BondState current) {
        requirePositive(generation);
        if (previous == null || current == null) {
            throw new IllegalArgumentException("bond states must not be null");
        }
        if (generation != activeGeneration || state == State.IDLE || failureReported) {
            return;
        }

        if (current == BondState.BONDED) {
            reportBonded(generation);
        } else if (previous == BondState.BONDED && current == BondState.NONE) {
            fail(generation, UserVisibleError.Code.BOND_LOST);
        } else if (previous == BondState.BONDING && current == BondState.NONE
                && state == State.WAITING) {
            fail(generation, UserVisibleError.Code.BOND_FAILED);
        }
    }

    public void cancel(long generation) {
        requirePositive(generation);
        if (generation != activeGeneration) {
            return;
        }
        activeGeneration = 0L;
        state = State.IDLE;
        bondedReported = false;
        failureReported = false;
    }

    public State state() {
        return state;
    }

    private void startBond(long generation) {
        boolean started;
        try {
            started = port.createBond();
        } catch (RuntimeException failure) {
            fail(generation, UserVisibleError.Code.BOND_START_FAILED);
            return;
        }
        if (!started) {
            fail(generation, UserVisibleError.Code.BOND_START_FAILED);
        }
    }

    private void reportBonded(long generation) {
        if (generation != activeGeneration || bondedReported || failureReported) {
            return;
        }
        bondedReported = true;
        state = State.BONDED;
        listener.onBonded(generation);
    }

    private void fail(long generation, UserVisibleError.Code code) {
        if (generation != activeGeneration || failureReported) {
            return;
        }
        failureReported = true;
        state = State.FAILED;
        listener.onBondFailed(generation, new UserVisibleError(code));
    }

    private static void requirePositive(long generation) {
        if (generation <= 0L) {
            throw new IllegalArgumentException("generation must be positive");
        }
    }
}
