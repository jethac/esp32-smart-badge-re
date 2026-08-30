package com.openai.e87probe;

import java.util.Objects;

/**
 * Pure one-shot gate between explicit operator confirmation and Android side effects.
 */
public final class UploadStartCoordinator {
    public interface Host {
        String freezeSelectedAddress();
        boolean validatePinnedPackage();
        boolean bluetoothPermissionsGranted();
        void startExactAddressScan();
    }

    public enum Result {
        NOT_CONFIRMED,
        NO_EXACT_SELECTION,
        VALIDATION_FAILED,
        SCAN_STARTED,
        PERMISSION_DENIED,
        ALREADY_CONSUMED
    }

    private enum State {
        READY,
        FINISHED
    }

    private final Host host;
    private State state = State.READY;
    private boolean receiveModeConfirmed;

    public UploadStartCoordinator(Host host) {
        this.host = Objects.requireNonNull(host, "host");
    }

    public void setReceiveModeConfirmed(boolean confirmed) {
        if (state == State.READY) {
            receiveModeConfirmed = confirmed;
        }
    }

    public boolean isStartEnabled() {
        return state == State.READY && receiveModeConfirmed;
    }

    public Result start() {
        if (state != State.READY) {
            return Result.ALREADY_CONSUMED;
        }
        if (!receiveModeConfirmed) {
            return Result.NOT_CONFIRMED;
        }

        // Consume before the first host call so re-entrancy and exceptions fail closed.
        state = State.FINISHED;
        if (host.freezeSelectedAddress() == null) {
            return Result.NO_EXACT_SELECTION;
        }
        if (!host.validatePinnedPackage()) {
            return Result.VALIDATION_FAILED;
        }
        if (!host.bluetoothPermissionsGranted()) {
            return Result.PERMISSION_DENIED;
        }
        host.startExactAddressScan();
        return Result.SCAN_STARTED;
    }
}
