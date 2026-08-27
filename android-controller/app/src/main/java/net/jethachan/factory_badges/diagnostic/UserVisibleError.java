package net.jethachan.factory_badges.diagnostic;

public final class UserVisibleError {
    public enum Code {
        BLUETOOTH_PERMISSION_MISSING,
        BLUETOOTH_DISABLED,
        BOND_START_FAILED,
        BOND_FAILED,
        BOND_LOST,
        CONNECT_FAILED,
        SERVICE_DISCOVERY_FAILED,
        REQUIRED_SERVICE_MISSING,
        REQUIRED_CHARACTERISTIC_MISSING,
        LINK_SECURITY_FAILED,
        BUILD_INFO_INVALID,
        UNSUPPORTED_BADGE,
        GATT_TIMEOUT,
        STATE_WRITE_FAILED
    }

    private final Code code;
    private final String message;
    private final boolean retryable;
    private final int gattStatus;

    public UserVisibleError(Code code) {
        this(code, -1);
    }

    public UserVisibleError(Code code, int gattStatus) {
        if (code == null) {
            throw new IllegalArgumentException("code must not be null");
        }
        if (gattStatus < -1) {
            throw new IllegalArgumentException("gattStatus must be -1 or nonnegative");
        }
        this.code = code;
        this.message = messageFor(code);
        this.retryable = isRetryable(code);
        this.gattStatus = gattStatus;
    }

    public Code code() {
        return code;
    }

    public String message() {
        return message;
    }

    public boolean retryable() {
        return retryable;
    }

    public int gattStatus() {
        return gattStatus;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof UserVisibleError)) {
            return false;
        }
        UserVisibleError that = (UserVisibleError) other;
        return code == that.code && gattStatus == that.gattStatus;
    }

    @Override
    public int hashCode() {
        return 31 * code.hashCode() + gattStatus;
    }

    private static boolean isRetryable(Code code) {
        switch (code) {
            case CONNECT_FAILED:
            case SERVICE_DISCOVERY_FAILED:
            case GATT_TIMEOUT:
            case STATE_WRITE_FAILED:
                return true;
            default:
                return false;
        }
    }

    private static String messageFor(Code code) {
        switch (code) {
            case BLUETOOTH_PERMISSION_MISSING:
                return "Bluetooth permission is required.";
            case BLUETOOTH_DISABLED:
                return "Bluetooth is turned off.";
            case BOND_START_FAILED:
                return "Pairing could not be started.";
            case BOND_FAILED:
                return "Pairing did not complete.";
            case BOND_LOST:
                return "The badge is no longer paired.";
            case CONNECT_FAILED:
                return "Could not connect to the badge.";
            case SERVICE_DISCOVERY_FAILED:
                return "Could not inspect the badge services.";
            case REQUIRED_SERVICE_MISSING:
                return "This badge does not expose the metrics service.";
            case REQUIRED_CHARACTERISTIC_MISSING:
                return "This badge does not expose the required metrics controls.";
            case LINK_SECURITY_FAILED:
                return "The bonded link could not be secured.";
            case BUILD_INFO_INVALID:
                return "The badge returned invalid build information.";
            case UNSUPPORTED_BADGE:
                return "This badge hardware or firmware is not supported.";
            case GATT_TIMEOUT:
                return "The badge did not respond in time.";
            case STATE_WRITE_FAILED:
                return "The badge did not accept the metrics update.";
            default:
                throw new AssertionError("unhandled user-visible error code");
        }
    }
}
