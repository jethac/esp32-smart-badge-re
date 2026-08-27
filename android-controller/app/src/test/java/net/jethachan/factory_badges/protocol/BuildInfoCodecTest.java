package net.jethachan.factory_badges.protocol;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.Arrays;
import net.jethachan.factory_badges.model.BuildInfo;
import org.junit.Test;

public final class BuildInfoCodecTest {
    private static final String PROFILE = "E87-JD9855-R1";
    private static final byte[] BUILD_ID = bytes(
            0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
            0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F);
    private static final byte[] EXACT_RECORD = bytes(
            0x01, 0x07,
            0x45, 0x38, 0x37, 0x2D, 0x4A, 0x44, 0x39, 0x38,
            0x35, 0x35, 0x2D, 0x52, 0x31, 0x00, 0x00, 0x00,
            0x80, 0xC8, 0xFF, 0x00,
            0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
            0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
            0x00, 0x00);

    @Test
    public void encodeUsesExactFortyByteLayoutAndNulPadding() {
        BuildInfo info = new BuildInfo(7, PROFILE, 128, 200, 255, BUILD_ID);

        byte[] encoded = BuildInfoCodec.encode(info);

        assertEquals(40, BuildInfoCodec.RECORD_LENGTH);
        assertEquals(40, encoded.length);
        assertArrayEquals(EXACT_RECORD, encoded);
        assertEquals(0, encoded[15]);
        assertEquals(0, encoded[16]);
        assertEquals(0, encoded[17]);
    }

    @Test
    public void decodeTreatsSemanticVersionAsUnsignedAndRoundTrips() {
        BuildInfo decoded = BuildInfoCodec.decode(EXACT_RECORD);

        assertEquals(7, decoded.capabilities());
        assertEquals(PROFILE, decoded.hardwareProfile());
        assertEquals(128, decoded.major());
        assertEquals(200, decoded.minor());
        assertEquals(255, decoded.patch());
        assertArrayEquals(BUILD_ID, decoded.buildId());
        assertEquals(decoded, BuildInfoCodec.decode(BuildInfoCodec.encode(decoded)));
    }

    @Test
    public void capabilityNamesMapToTheirProtocolBits() {
        assertEquals(0x01, BuildInfoCodec.CAPABILITY_SEMANTIC_METRICS);
        assertEquals(0x02, BuildInfoCodec.CAPABILITY_BATTERY_SERVICE);
        assertEquals(0x04, BuildInfoCodec.CAPABILITY_PHYSICALLY_GATED_RCSP);
    }

    @Test
    public void decodeAcceptsEveryAllowedCapabilityCombination() {
        for (int capabilities = 0; capabilities <= 7; capabilities++) {
            byte[] record = validRecord();
            record[1] = (byte) capabilities;
            assertEquals(capabilities, BuildInfoCodec.decode(record).capabilities());
        }
    }

    @Test
    public void decodeRejectsEveryUnknownCapabilityBitPattern() {
        for (int capabilities = 8; capabilities <= 255; capabilities++) {
            byte[] record = validRecord();
            record[1] = (byte) capabilities;
            assertDecodeRejected(record);
        }
    }

    @Test
    public void decodeRejectsNullAndEveryWrongLengthThroughEighty() {
        assertDecodeRejected(null);
        for (int length = 0; length <= 80; length++) {
            if (length != 40) {
                assertDecodeRejected(new byte[length]);
            }
        }
    }

    @Test
    public void decodeRejectsEveryUnsupportedSchemaByte() {
        for (int schema = 0; schema <= 255; schema++) {
            if (schema != 1) {
                byte[] record = validRecord();
                record[0] = (byte) schema;
                assertDecodeRejected(record);
            }
        }
    }

    @Test
    public void decodeRejectsEveryNonAsciiProfileByte() {
        for (int value = 128; value <= 255; value++) {
            byte[] record = validRecord();
            record[2] = (byte) value;
            assertDecodeRejected(record);
        }
    }

    @Test
    public void decodeRejectsEmbeddedNulAndNonzeroDataAfterTerminator() {
        byte[] embeddedNul = validRecord();
        embeddedNul[5] = 0;
        assertDecodeRejected(embeddedNul);

        for (int paddingOffset = 15; paddingOffset <= 17; paddingOffset++) {
            byte[] nonzeroPadding = validRecord();
            nonzeroPadding[paddingOffset] = 1;
            assertDecodeRejected(nonzeroPadding);
        }
    }

    @Test
    public void decodeRejectsWrongHardwareProfile() {
        byte[] wrongProfile = validRecord();
        wrongProfile[2] = 'F';
        assertDecodeRejected(wrongProfile);
    }

    @Test
    public void decodeRejectsEveryNonzeroReservedByte() {
        int[] reservedOffsets = new int[] {21, 38, 39};
        for (int offset : reservedOffsets) {
            for (int value = 1; value <= 255; value++) {
                byte[] record = validRecord();
                record[offset] = (byte) value;
                assertDecodeRejected(record);
            }
        }
    }

    @Test
    public void buildInfoDefensivelyCopiesBuildIdInBothDirections() {
        byte[] constructorInput = Arrays.copyOf(BUILD_ID, BUILD_ID.length);
        BuildInfo info = new BuildInfo(7, PROFILE, 1, 2, 3, constructorInput);

        constructorInput[0] = 99;
        assertEquals(0, info.buildId()[0]);

        byte[] accessorResult = info.buildId();
        accessorResult[1] = 99;
        assertEquals(1, info.buildId()[1]);
    }

    @Test
    public void buildInfoHasContentBasedValueSemantics() {
        BuildInfo first = new BuildInfo(7, PROFILE, 1, 2, 3, BUILD_ID);
        BuildInfo same = new BuildInfo(7, PROFILE, 1, 2, 3,
                Arrays.copyOf(BUILD_ID, BUILD_ID.length));
        byte[] differentId = Arrays.copyOf(BUILD_ID, BUILD_ID.length);
        differentId[15] = 99;
        BuildInfo different = new BuildInfo(7, PROFILE, 1, 2, 3, differentId);

        assertEquals(first, same);
        assertEquals(first.hashCode(), same.hashCode());
        assertNotEquals(first, different);
        assertNotEquals(first, null);
        assertNotEquals(first, "build");
    }

    @Test
    public void buildInfoConstructorRejectsMalformedFields() {
        assertBuildInfoRejected(-1, PROFILE, 1, 2, 3, BUILD_ID);
        assertBuildInfoRejected(8, PROFILE, 1, 2, 3, BUILD_ID);
        assertBuildInfoRejected(7, null, 1, 2, 3, BUILD_ID);
        assertBuildInfoRejected(7, "E87-JD9855-R2", 1, 2, 3, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, -1, 2, 3, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, 256, 2, 3, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, 1, -1, 3, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, 1, 256, 3, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, 1, 2, -1, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, 1, 2, 256, BUILD_ID);
        assertBuildInfoRejected(7, PROFILE, 1, 2, 3, null);
        assertBuildInfoRejected(7, PROFILE, 1, 2, 3, new byte[15]);
        assertBuildInfoRejected(7, PROFILE, 1, 2, 3, new byte[17]);
    }

    @Test
    public void encodeRejectsNull() {
        try {
            BuildInfoCodec.encode(null);
            fail("null build info must be rejected");
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    @Test
    public void matchesExpectedRequiresEveryFieldToMatch() {
        BuildInfo actual = new BuildInfo(7, PROFILE, 128, 200, 255, BUILD_ID);

        assertTrue(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(6, PROFILE, 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, "E87-JD9855-R2", 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 127, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 199, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 200, 254, BUILD_ID)));
        byte[] differentId = Arrays.copyOf(BUILD_ID, BUILD_ID.length);
        differentId[15] = 99;
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 200, 255, differentId)));
    }

    @Test
    public void matchesExpectedFailsSafelyForNullAndMalformedExpectedData() {
        BuildInfo actual = new BuildInfo(7, PROFILE, 128, 200, 255, BUILD_ID);

        assertFalse(BuildInfoCodec.matchesExpected(null,
                expected(7, PROFILE, 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual, null));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(-1, PROFILE, 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(8, PROFILE, 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, null, 128, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, -1, 200, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 256, 255, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 200, -1, BUILD_ID)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 200, 255, null)));
        assertFalse(BuildInfoCodec.matchesExpected(actual,
                expected(7, PROFILE, 128, 200, 255, new byte[15])));
        assertFalse(BuildInfoCodec.matchesExpected(actual, new ThrowingExpectedBuild()));
    }

    private static ExpectedFixture expected(int capabilities, String profile, int major,
            int minor, int patch, byte[] buildId) {
        return new ExpectedFixture(capabilities, profile, major, minor, patch, buildId);
    }

    private static byte[] validRecord() {
        return Arrays.copyOf(EXACT_RECORD, EXACT_RECORD.length);
    }

    private static void assertDecodeRejected(byte[] record) {
        try {
            BuildInfoCodec.decode(record);
            fail("invalid build info accepted: " + Arrays.toString(record));
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    private static void assertBuildInfoRejected(int capabilities, String profile, int major,
            int minor, int patch, byte[] buildId) {
        try {
            new BuildInfo(capabilities, profile, major, minor, patch, buildId);
            fail("invalid BuildInfo accepted");
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

    private static final class ExpectedFixture implements BuildInfoCodec.ExpectedBuild {
        private final int capabilities;
        private final String profile;
        private final int major;
        private final int minor;
        private final int patch;
        private final byte[] buildId;

        ExpectedFixture(int capabilities, String profile, int major, int minor, int patch,
                byte[] buildId) {
            this.capabilities = capabilities;
            this.profile = profile;
            this.major = major;
            this.minor = minor;
            this.patch = patch;
            this.buildId = buildId == null ? null : Arrays.copyOf(buildId, buildId.length);
        }

        @Override
        public int capabilities() {
            return capabilities;
        }

        @Override
        public String hardwareProfile() {
            return profile;
        }

        @Override
        public int major() {
            return major;
        }

        @Override
        public int minor() {
            return minor;
        }

        @Override
        public int patch() {
            return patch;
        }

        @Override
        public byte[] buildId() {
            return buildId == null ? null : Arrays.copyOf(buildId, buildId.length);
        }
    }

    private static final class ThrowingExpectedBuild implements BuildInfoCodec.ExpectedBuild {
        @Override
        public int capabilities() {
            throw new IllegalStateException("broken expected manifest");
        }

        @Override
        public String hardwareProfile() {
            return PROFILE;
        }

        @Override
        public int major() {
            return 128;
        }

        @Override
        public int minor() {
            return 200;
        }

        @Override
        public int patch() {
            return 255;
        }

        @Override
        public byte[] buildId() {
            return Arrays.copyOf(BUILD_ID, BUILD_ID.length);
        }
    }
}
