package net.jethachan.factory_badges.protocol;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.Arrays;
import net.jethachan.factory_badges.model.BadgeState;
import org.junit.Test;

public final class StatePacketCodecTest {
    private static final byte[] ZERO_VECTOR = bytes(0x01, 0x00, 0x00, 0x00,
            0xBF, 0x06, 0x00, 0x00);
    private static final byte[] MAX_VECTOR = bytes(0x01, 0x64, 0x64, 0x00,
            0xBF, 0x06, 0x00, 0x00);
    private static final byte[] ASYMMETRIC_VECTOR = bytes(0x01, 0x11, 0x53, 0x00,
            0xBF, 0x06, 0x00, 0x00);

    @Test
    public void encodeProducesExactBoundaryAndAsymmetricVectors() {
        assertEquals(8, StatePacketCodec.PACKET_LENGTH);
        assertArrayEquals(ZERO_VECTOR, StatePacketCodec.encode(new BadgeState(0, 0, 1727L)));
        assertArrayEquals(MAX_VECTOR, StatePacketCodec.encode(new BadgeState(100, 100, 1727L)));
        assertArrayEquals(ASYMMETRIC_VECTOR,
                StatePacketCodec.encode(new BadgeState(17, 83, 1727L)));
    }

    @Test
    public void roundTripsEveryDayWeekPairIndependently() {
        for (int day = 0; day <= 100; day++) {
            for (int week = 0; week <= 100; week++) {
                BadgeState decoded = StatePacketCodec.decode(
                        StatePacketCodec.encode(new BadgeState(day, week, 1727L)));
                assertEquals(day, decoded.dayPercent());
                assertEquals(week, decoded.weekPercent());
                assertEquals(1727L, decoded.creditCents());
            }
        }
    }

    @Test
    public void decodeRejectsNullAndEverySpecifiedWrongLength() {
        assertDecodeRejected(null);
        for (int length = 0; length <= 7; length++) {
            assertDecodeRejected(new byte[length]);
        }
        for (int length = 9; length <= 16; length++) {
            assertDecodeRejected(new byte[length]);
        }
    }

    @Test
    public void decodeRejectsEveryUnsupportedSchemaByte() {
        for (int schema = 0; schema <= 255; schema++) {
            if (schema != 1) {
                byte[] packet = validPacket();
                packet[0] = (byte) schema;
                assertDecodeRejected(packet);
            }
        }
    }

    @Test
    public void decodeRejectsEveryOutOfRangeDayAndWeekByte() {
        for (int value = 101; value <= 255; value++) {
            byte[] invalidDay = validPacket();
            invalidDay[1] = (byte) value;
            assertDecodeRejected(invalidDay);

            byte[] invalidWeek = validPacket();
            invalidWeek[2] = (byte) value;
            assertDecodeRejected(invalidWeek);
        }
    }

    @Test
    public void decodeRejectsEveryNonzeroFlagsByte() {
        for (int value = 1; value <= 255; value++) {
            byte[] packet = validPacket();
            packet[3] = (byte) value;
            assertDecodeRejected(packet);
        }
    }

    @Test
    public void decodeRejectsEveryCreditExcept1727() {
        for (int credit = 0; credit <= 0xFFFF; credit++) {
            if (credit != 1727) {
                byte[] packet = validPacket();
                packet[4] = (byte) (credit & 0xFF);
                packet[5] = (byte) ((credit >>> 8) & 0xFF);
                assertDecodeRejected(packet);
            }
        }
    }

    @Test
    public void decodeRejectsEveryNonzeroReservedByte() {
        for (int value = 1; value <= 255; value++) {
            byte[] byteSix = validPacket();
            byteSix[6] = (byte) value;
            assertDecodeRejected(byteSix);

            byte[] byteSeven = validPacket();
            byteSeven[7] = (byte) value;
            assertDecodeRejected(byteSeven);
        }
    }

    @Test
    public void badgeStateConstructorRejectsInvalidFieldsWithoutClamping() {
        assertBadgeStateRejected(-1, 0, 1727);
        assertBadgeStateRejected(101, 0, 1727);
        assertBadgeStateRejected(0, -1, 1727);
        assertBadgeStateRejected(0, 101, 1727);
        assertBadgeStateRejected(0, 0, 1726);
        assertBadgeStateRejected(0, 0, 1728);
    }

    @Test
    public void badgeStateHasValueSemanticsAndDiagnosticText() {
        BadgeState first = new BadgeState(17, 83, 1727L);
        BadgeState same = new BadgeState(17, 83, 1727L);
        BadgeState different = new BadgeState(18, 83, 1727L);

        assertEquals(first, same);
        assertEquals(first.hashCode(), same.hashCode());
        assertNotEquals(first, different);
        assertNotEquals(first, null);
        assertNotEquals(first, "state");
        assertTrue(first.toString().contains("dayPercent=17"));
        assertTrue(first.toString().contains("weekPercent=83"));
        assertTrue(first.toString().contains("creditCents=1727"));
        assertFalse(first.toString().contains("@"));
    }

    @Test
    public void encodeRejectsNull() {
        try {
            StatePacketCodec.encode(null);
            fail("null state must be rejected");
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    @Test
    public void creditAccessorUsesTheStableLongApi() throws Exception {
        assertEquals(long.class, BadgeState.class.getMethod("creditCents").getReturnType());
    }

    private static byte[] validPacket() {
        return Arrays.copyOf(ASYMMETRIC_VECTOR, ASYMMETRIC_VECTOR.length);
    }

    private static void assertDecodeRejected(byte[] packet) {
        try {
            StatePacketCodec.decode(packet);
            fail("invalid packet accepted: " + Arrays.toString(packet));
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    private static void assertBadgeStateRejected(int day, int week, long credit) {
        try {
            new BadgeState(day, week, credit);
            fail("invalid state accepted: " + day + ", " + week + ", " + credit);
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    private static byte[] bytes(int... values) {
        byte[] result = new byte[values.length];
        for (int index = 0; index < values.length; index++) {
            result[index] = (byte) values[index];
        }
        return result;
    }
}
