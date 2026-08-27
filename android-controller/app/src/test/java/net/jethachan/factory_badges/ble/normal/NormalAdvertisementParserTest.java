package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.Arrays;
import java.util.Optional;
import java.util.Random;
import java.util.UUID;
import org.junit.Test;

public final class NormalAdvertisementParserTest {
    private static final byte[] NORMAL_UUID_LE = bytes(
            0x35, 0x07, 0xA7, 0x01, 0x9C, 0x5D, 0x0B, 0x9F,
            0x62, 0x4C, 0x1B, 0x7A, 0x01, 0x00, 0x7D, 0xE8);
    private static final byte[] NORMAL_UUID_NETWORK_ORDER = bytes(
            0xE8, 0x7D, 0x00, 0x01, 0x7A, 0x1B, 0x4C, 0x62,
            0x9F, 0x0B, 0x5D, 0x9C, 0x01, 0xA7, 0x07, 0x35);
    private static final byte[] OTHER_UUID_LE = bytes(
            0x78, 0x56, 0x34, 0x12, 0xF0, 0xDE, 0xBC, 0x9A,
            0x78, 0x56, 0x34, 0x12, 0xF0, 0xDE, 0xBC, 0x9A);

    @Test
    public void uuidConstantsMatchTheNormalAndBatteryGattContract() {
        assertEquals(UUID.fromString("e87d0001-7a1b-4c62-9f0b-5d9c01a70735"),
                NormalUuids.SERVICE);
        assertEquals(UUID.fromString("e87d0002-7a1b-4c62-9f0b-5d9c01a70735"),
                NormalUuids.SEMANTIC_STATE);
        assertEquals(UUID.fromString("e87d0003-7a1b-4c62-9f0b-5d9c01a70735"),
                NormalUuids.BUILD_INFO);
        assertEquals(UUID.fromString("0000180f-0000-1000-8000-00805f9b34fb"),
                NormalUuids.BATTERY_SERVICE);
        assertEquals(UUID.fromString("00002a19-0000-1000-8000-00805f9b34fb"),
                NormalUuids.BATTERY_LEVEL);
    }

    @Test
    public void acceptsExactNameAndSingleNormalUuidInCompleteList() {
        Optional<NormalAdvertisementParser.Match> parsed = NormalAdvertisementParser.parse(
                record(name(0x09, "E87"), ad(0x07, NORMAL_UUID_LE)));

        assertTrue(parsed.isPresent());
        assertTrue(parsed.get().normalService());
        assertEquals("E87", parsed.get().localName());
    }

    @Test
    public void findsNormalUuidInEitherPositionAndEitherListType() {
        assertMatch(record(name(0x09, "E87"),
                ad(0x07, concat(NORMAL_UUID_LE, OTHER_UUID_LE))));
        assertMatch(record(name(0x09, "E87"),
                ad(0x06, concat(OTHER_UUID_LE, NORMAL_UUID_LE))));
    }

    @Test
    public void acceptsShortenedNameAndSkipsUnknownWellFormedStructures() {
        assertMatch(record(
                ad(0xFF, bytes(0xD6, 0x05, 0x01)),
                name(0x08, "E87"),
                ad(0x07, NORMAL_UUID_LE),
                ad(0x16, bytes(0x01, 0x02))));
    }

    @Test
    public void completeNameMayRepeatOnlyAnIdenticalShortenedName() {
        assertMatch(record(name(0x08, "E87"), name(0x09, "E87"),
                ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x08, "E8"), name(0x09, "E87"),
                ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "E87"), name(0x08, "E88"),
                ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "NOT E87"), name(0x09, "E87"),
                ad(0x07, NORMAL_UUID_LE)));
    }

    @Test
    public void zeroLengthTerminatesRecordWithoutInspectingTrailingGarbage() {
        byte[] validPrefix = record(name(0x09, "E87"), ad(0x07, NORMAL_UUID_LE));
        assertMatch(concat(validPrefix, bytes(0x00, 0x7F, 0x07)));
        assertNoMatch(concat(name(0x09, "E87"), bytes(0x00),
                ad(0x07, NORMAL_UUID_LE)));
    }

    @Test
    public void rejectsMissingWrongAndUpdateIdentities() {
        assertNoMatch(record(name(0x09, "E87")));
        assertNoMatch(record(ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "E87 UPDATE"), ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "e87_update"), ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "E87_LE_UPDATE"), ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "E87 PRO"), ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x09, "E87"), ad(0x07, OTHER_UUID_LE)));
        assertNoMatch(record(name(0x09, "E87"), ad(0x03, bytes(0x00, 0xAE))));
    }

    @Test
    public void rejectsNetworkOrderUuidRatherThanGuessingEndianness() {
        assertNoMatch(record(name(0x09, "E87"),
                ad(0x07, NORMAL_UUID_NETWORK_ORDER)));
        assertMatch(record(name(0x09, "E87"), ad(0x07, NORMAL_UUID_LE)));
    }

    @Test
    public void rejectsEverySingleBytePerturbationOfNormalUuid() {
        for (int index = 0; index < NORMAL_UUID_LE.length; index++) {
            byte[] perturbed = Arrays.copyOf(NORMAL_UUID_LE, NORMAL_UUID_LE.length);
            perturbed[index] ^= 0x01;
            assertNoMatch(record(
                    name(0x09, "E87"),
                    ad(0x07, perturbed)));
        }
    }

    @Test
    public void rejectsNullEmptyTruncatedAndOverlongStructures() {
        assertNoMatch(null);
        assertNoMatch(new byte[0]);
        assertNoMatch(bytes(0x02, 0x09));
        assertNoMatch(bytes(0x7F, 0x09, 'E', '8', '7'));
        assertNoMatch(concat(name(0x09, "E87"), bytes(0x11, 0x07),
                Arrays.copyOf(NORMAL_UUID_LE, 15)));
        assertNoMatch(concat(name(0x09, "E87"), bytes(0x12, 0x07),
                NORMAL_UUID_LE));
    }

    @Test
    public void rejectsConflictingOrMalformedTailAfterValidIdentityPrefix() {
        byte[] validIdentity = record(
                name(0x09, "E87"),
                ad(0x07, NORMAL_UUID_LE));

        assertNoMatch(concat(
                validIdentity,
                name(0x08, "E88")));
        assertNoMatch(concat(
                validIdentity,
                bytes(0x04, 0xFF, 0x01)));
    }

    @Test
    public void rejectsNonMultipleUuidListLengthsAtBoundaries() {
        int[] invalidLengths = new int[] {1, 15, 17, 31, 33};
        for (int uuidBytes : invalidLengths) {
            assertNoMatch(record(name(0x09, "E87"), ad(0x07, new byte[uuidBytes])));
        }
        assertNoMatch(record(name(0x09, "E87"), ad(0x07, new byte[0])));
        assertMatch(record(name(0x09, "E87"),
                ad(0x07, concat(OTHER_UUID_LE, NORMAL_UUID_LE))));
    }

    @Test
    public void rejectsMalformedNonAsciiAndConflictingNames() {
        assertNoMatch(record(ad(0x09, bytes('E', '8', 0x80)),
                ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(ad(0x08, bytes('E', '8', '7')),
                ad(0x09, bytes('E', '8', 0xFF)), ad(0x07, NORMAL_UUID_LE)));
        assertNoMatch(record(name(0x08, "E87"), name(0x08, "E88"),
                ad(0x07, NORMAL_UUID_LE)));
    }

    @Test
    public void neverThrowsForDeterministicUntrustedByteArrays() {
        Random random = new Random(0xE87L);
        for (int length = 0; length <= 256; length++) {
            byte[] input = new byte[length];
            random.nextBytes(input);
            try {
                NormalAdvertisementParser.parse(input);
            } catch (RuntimeException failure) {
                fail("parser threw for length " + length + ": " + failure);
            }
        }
    }

    private static void assertMatch(byte[] scanRecord) {
        Optional<NormalAdvertisementParser.Match> parsed =
                NormalAdvertisementParser.parse(scanRecord);
        assertTrue("expected match: " + Arrays.toString(scanRecord), parsed.isPresent());
        assertEquals("E87", parsed.get().localName());
        assertTrue(parsed.get().normalService());
    }

    private static void assertNoMatch(byte[] scanRecord) {
        assertFalse("unexpected match: " + Arrays.toString(scanRecord),
                NormalAdvertisementParser.parse(scanRecord).isPresent());
    }

    private static byte[] name(int type, String value) {
        byte[] ascii = new byte[value.length()];
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character > 0x7F) {
                throw new IllegalArgumentException("test names must be ASCII");
            }
            ascii[index] = (byte) character;
        }
        return ad(type, ascii);
    }

    private static byte[] ad(int type, byte[] value) {
        if (value.length > 254) {
            throw new IllegalArgumentException("test AD value too long");
        }
        byte[] result = new byte[value.length + 2];
        result[0] = (byte) (value.length + 1);
        result[1] = (byte) type;
        System.arraycopy(value, 0, result, 2, value.length);
        return result;
    }

    private static byte[] record(byte[]... structures) {
        return concat(structures);
    }

    private static byte[] concat(byte[]... parts) {
        int length = 0;
        for (byte[] part : parts) {
            length += part.length;
        }
        byte[] result = new byte[length];
        int offset = 0;
        for (byte[] part : parts) {
            System.arraycopy(part, 0, result, offset, part.length);
            offset += part.length;
        }
        return result;
    }

    private static byte[] bytes(int... values) {
        byte[] result = new byte[values.length];
        for (int index = 0; index < values.length; index++) {
            result[index] = (byte) values[index];
        }
        return result;
    }
}
