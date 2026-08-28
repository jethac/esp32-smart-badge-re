package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public final class StockHostIdentityTest {
    @Test public void languageAndClockBitsMatchCapturedQixSettingsContract() {
        assertEquals(0x06, StockHostIdentity.derive("en", false, fields()).settings());
        assertEquals(0x02, StockHostIdentity.derive("en", true, fields()).settings());
        assertEquals(0x04, StockHostIdentity.derive("zh", false, fields()).settings());
        assertEquals(0x00, StockHostIdentity.derive("zh", true, fields()).settings());
    }

    @Test public void hostIdUsesAllFourteenBuildFieldLengthsWithoutHardcodingDevice() {
        StockHostIdentity identity = StockHostIdentity.derive("en", false, fields());

        assertEquals(1136684095, identity.hostId());
    }

    @Test public void malformedIdentityInputsAreRejected() {
        assertThrows(IllegalArgumentException.class,
                () -> StockHostIdentity.derive(null, false, fields()));
        assertThrows(IllegalArgumentException.class,
                () -> StockHostIdentity.derive("en", false, new String[13]));
        String[] withNull = fields();
        withNull[7] = null;
        assertThrows(IllegalArgumentException.class,
                () -> StockHostIdentity.derive("en", false, withNull));
    }

    private static String[] fields() {
        return new String[] {
                "1", "22", "333", "4444", "55555", "666666", "7777777",
                "88888888", "999999999", "0000000000", "11111111111",
                "222222222222", "3333333333333", "44444444444444"
        };
    }
}
