package com.openai.e87probe;

import java.util.Objects;

/**
 * Pure one-shot gate between explicit operator confirmation and Android side effects.
 */
public final class UploadStartCoordinator {
    public interface Host {
        boolean validatePinnedPackage();
        boolean bluetoothPermissionsGranted();
        void requestBluetoothPermissions();
        void startExactAddressScan();
    }

    public enum Result {
        NOT_CONFIRMED,
        VALIDATION_FAILED,
        PERMISSION_REQUESTED,
        SCAN_STARTED,
        PERMISSION_DENIED,
        ALREADY_CONSUMED
    }

    private enum State {
        READY,
        AWAITING_PERMISSION,
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
        if (!host.validatePinnedPackage()) {
            return Result.VALIDATION_FAILED;
        }
        if (host.bluetoothPermissionsGranted()) {
            host.startExactAddressScan();
            return Result.SCAN_STARTED;
        }

        state = State.AWAITING_PERMISSION;
        host.requestBluetoothPermissions();
        return Result.PERMISSION_REQUESTED;
    }

    public Result onPermissionResult(boolean granted) {
        if (state != State.AWAITING_PERMISSION) {
            return Result.ALREADY_CONSUMED;
        }
        state = State.FINISHED;
        if (!granted) {
            return Result.PERMISSION_DENIED;
        }
        host.startExactAddressScan();
        return Result.SCAN_STARTED;
    }
}
