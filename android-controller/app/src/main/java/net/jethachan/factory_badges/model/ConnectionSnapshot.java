package net.jethachan.factory_badges.model;

import java.util.Objects;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;

public final class ConnectionSnapshot {
    public enum Phase {
        DISABLED,
        NO_DEVICE,
        BONDING,
        CONNECTING,
        DISCOVERING,
        VALIDATING_BUILD,
        READY,
        RETRY_WAIT,
        ERROR
    }

    private final boolean syncEnabled;
    private final Phase phase;
    private final String selectedDeviceName;
    private final String selectedDeviceAddress;
    private final boolean bonded;
    private final BadgeState currentState;
    private final BuildInfo buildInfo;
    private final Integer batteryPercent;
    private final BadgeState lastAcknowledgedState;
    private final Long lastAcknowledgedElapsedMs;
    private final Long nextReconnectDelayMs;
    private final UserVisibleError error;

    public ConnectionSnapshot(
            boolean syncEnabled,
            Phase phase,
            String selectedDeviceName,
            String selectedDeviceAddress,
            boolean bonded,
            BadgeState currentState,
            BuildInfo buildInfo,
            Integer batteryPercent,
            BadgeState lastAcknowledgedState,
            Long lastAcknowledgedElapsedMs,
            Long nextReconnectDelayMs,
            UserVisibleError error) {
        if (phase == null) {
            throw new IllegalArgumentException("phase must not be null");
        }
        if (currentState == null) {
            throw new IllegalArgumentException("currentState must not be null");
        }
        if (selectedDeviceAddress != null && selectedDeviceAddress.trim().isEmpty()) {
            throw new IllegalArgumentException("selectedDeviceAddress must not be blank");
        }
        if (batteryPercent != null
                && (batteryPercent.intValue() < 0 || batteryPercent.intValue() > 100)) {
            throw new IllegalArgumentException("batteryPercent must be in 0..100");
        }
        if ((lastAcknowledgedState == null) != (lastAcknowledgedElapsedMs == null)) {
            throw new IllegalArgumentException(
                    "acknowledged state and elapsed time must both be present or absent");
        }
        if (lastAcknowledgedElapsedMs != null
                && lastAcknowledgedElapsedMs.longValue() < 0L) {
            throw new IllegalArgumentException(
                    "lastAcknowledgedElapsedMs must be nonnegative");
        }
        if (nextReconnectDelayMs != null && nextReconnectDelayMs.longValue() < 0L) {
            throw new IllegalArgumentException("nextReconnectDelayMs must be nonnegative");
        }

        validatePhase(syncEnabled, phase, selectedDeviceName, selectedDeviceAddress,
                bonded, buildInfo, nextReconnectDelayMs, error);

        this.syncEnabled = syncEnabled;
        this.phase = phase;
        this.selectedDeviceName = selectedDeviceName;
        this.selectedDeviceAddress = selectedDeviceAddress;
        this.bonded = bonded;
        this.currentState = currentState;
        this.buildInfo = buildInfo;
        this.batteryPercent = batteryPercent;
        this.lastAcknowledgedState = lastAcknowledgedState;
        this.lastAcknowledgedElapsedMs = lastAcknowledgedElapsedMs;
        this.nextReconnectDelayMs = nextReconnectDelayMs;
        this.error = error;
    }

    public boolean syncEnabled() {
        return syncEnabled;
    }

    public Phase phase() {
        return phase;
    }

    public String selectedDeviceName() {
        return selectedDeviceName;
    }

    public String selectedDeviceAddress() {
        return selectedDeviceAddress;
    }

    public boolean bonded() {
        return bonded;
    }

    public BadgeState currentState() {
        return currentState;
    }

    public BuildInfo buildInfo() {
        return buildInfo;
    }

    public Integer batteryPercent() {
        return batteryPercent;
    }

    public BadgeState lastAcknowledgedState() {
        return lastAcknowledgedState;
    }

    public Long lastAcknowledgedElapsedMs() {
        return lastAcknowledgedElapsedMs;
    }

    public Long nextReconnectDelayMs() {
        return nextReconnectDelayMs;
    }

    public UserVisibleError error() {
        return error;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof ConnectionSnapshot)) {
            return false;
        }
        ConnectionSnapshot that = (ConnectionSnapshot) other;
        return syncEnabled == that.syncEnabled
                && bonded == that.bonded
                && phase == that.phase
                && Objects.equals(selectedDeviceName, that.selectedDeviceName)
                && Objects.equals(selectedDeviceAddress, that.selectedDeviceAddress)
                && currentState.equals(that.currentState)
                && Objects.equals(buildInfo, that.buildInfo)
                && Objects.equals(batteryPercent, that.batteryPercent)
                && Objects.equals(lastAcknowledgedState, that.lastAcknowledgedState)
                && Objects.equals(lastAcknowledgedElapsedMs, that.lastAcknowledgedElapsedMs)
                && Objects.equals(nextReconnectDelayMs, that.nextReconnectDelayMs)
                && Objects.equals(error, that.error);
    }

    @Override
    public int hashCode() {
        return Objects.hash(Boolean.valueOf(syncEnabled), phase, selectedDeviceName,
                selectedDeviceAddress, Boolean.valueOf(bonded), currentState, buildInfo,
                batteryPercent, lastAcknowledgedState, lastAcknowledgedElapsedMs,
                nextReconnectDelayMs, error);
    }

    private static void validatePhase(
            boolean syncEnabled,
            Phase phase,
            String selectedDeviceName,
            String selectedDeviceAddress,
            boolean bonded,
            BuildInfo buildInfo,
            Long nextReconnectDelayMs,
            UserVisibleError error) {
        if (phase == Phase.DISABLED) {
            if (syncEnabled) {
                throw new IllegalArgumentException("DISABLED phase requires sync disabled");
            }
        } else if (!syncEnabled) {
            throw new IllegalArgumentException("enabled phase requires sync enabled");
        }

        if (phase == Phase.NO_DEVICE) {
            if (selectedDeviceName != null || selectedDeviceAddress != null) {
                throw new IllegalArgumentException("NO_DEVICE phase cannot select a device");
            }
        } else if (phase != Phase.DISABLED && selectedDeviceAddress == null) {
            throw new IllegalArgumentException("enabled device phase requires an address");
        }

        if (phase == Phase.READY) {
            if (!bonded || buildInfo == null) {
                throw new IllegalArgumentException(
                        "READY phase requires a bond and validated build info");
            }
            if (error != null || nextReconnectDelayMs != null) {
                throw new IllegalArgumentException(
                        "READY phase cannot contain retry or error state");
            }
        } else if (phase == Phase.RETRY_WAIT) {
            if (nextReconnectDelayMs == null
                    || (error != null && !error.retryable())) {
                throw new IllegalArgumentException(
                        "RETRY_WAIT phase requires a reconnect delay");
            }
        } else if (phase == Phase.ERROR) {
            if (error == null || error.retryable() || nextReconnectDelayMs != null) {
                throw new IllegalArgumentException(
                        "ERROR phase requires only a terminal error");
            }
        } else if (error != null || nextReconnectDelayMs != null) {
            throw new IllegalArgumentException(
                    "retry and error fields do not belong to this phase");
        }
    }
}
