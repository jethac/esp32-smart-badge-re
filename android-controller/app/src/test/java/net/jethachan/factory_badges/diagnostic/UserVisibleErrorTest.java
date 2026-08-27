package net.jethachan.factory_badges.diagnostic;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class UserVisibleErrorTest {
    @Test
    public void everyCodeHasStableSafeMessageAndRetryClassification() {
        assertError(UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING,
                "Bluetooth permission is required.", false);
        assertError(UserVisibleError.Code.BLUETOOTH_DISABLED,
                "Bluetooth is turned off.", false);
        assertError(UserVisibleError.Code.BOND_START_FAILED,
                "Pairing could not be started.", false);
        assertError(UserVisibleError.Code.BOND_FAILED,
                "Pairing did not complete.", false);
        assertError(UserVisibleError.Code.BOND_LOST,
                "The badge is no longer paired.", false);
        assertError(UserVisibleError.Code.CONNECT_FAILED,
                "Could not connect to the badge.", true);
        assertError(UserVisibleError.Code.SERVICE_DISCOVERY_FAILED,
                "Could not inspect the badge services.", true);
        assertError(UserVisibleError.Code.REQUIRED_SERVICE_MISSING,
                "This badge does not expose the metrics service.", false);
        assertError(UserVisibleError.Code.REQUIRED_CHARACTERISTIC_MISSING,
                "This badge does not expose the required metrics controls.", false);
        assertError(UserVisibleError.Code.LINK_SECURITY_FAILED,
                "The bonded link could not be secured.", false);
        assertError(UserVisibleError.Code.BUILD_INFO_INVALID,
                "The badge returned invalid build information.", false);
        assertError(UserVisibleError.Code.UNSUPPORTED_BADGE,
                "This badge hardware or firmware is not supported.", false);
        assertError(UserVisibleError.Code.GATT_TIMEOUT,
                "The badge did not respond in time.", true);
        assertError(UserVisibleError.Code.STATE_WRITE_FAILED,
                "The badge did not accept the metrics update.", true);
        assertEquals(14, UserVisibleError.Code.values().length);
    }

    @Test
    public void valueEqualityIncludesCodeAndNumericGattStatus() {
        UserVisibleError left =
                new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133);
        UserVisibleError equal =
                new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133);
        UserVisibleError otherStatus =
                new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 8);

        assertEquals(left, equal);
        assertEquals(left.hashCode(), equal.hashCode());
        assertNotEquals(left, otherStatus);
        assertEquals(133, left.gattStatus());
    }

    @Test
    public void absentGattStatusIsMinusOne() {
        UserVisibleError error =
                new UserVisibleError(UserVisibleError.Code.GATT_TIMEOUT);

        assertEquals(-1, error.gattStatus());
        assertTrue(error.retryable());
    }

    @Test
    public void rejectsNullCodeAndStatusBelowAbsentSentinel() {
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new UserVisibleError(null);
            }
        });
        expectIllegalArgument(new Runnable() {
            @Override public void run() {
                new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, -2);
            }
        });
    }

    private static void assertError(UserVisibleError.Code code, String message,
            boolean retryable) {
        UserVisibleError error = new UserVisibleError(code);
        assertEquals(code, error.code());
        assertEquals(message, error.message());
        assertEquals(retryable, error.retryable());
        assertEquals(-1, error.gattStatus());
        if (retryable) {
            assertTrue(error.retryable());
        } else {
            assertFalse(error.retryable());
        }
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
