package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;

import java.nio.charset.StandardCharsets;
import org.junit.Test;

public final class TransitionManifestTest {
    @Test public void canonicalClosedReceiptExposesExactQualifiedIdentityAndFiles() {
        EmbeddedReleaseTestFixture fixture = new EmbeddedReleaseTestFixture();

        TransitionManifest manifest = TransitionManifest.parse(fixture.receiptBytes());

        assertEquals("AC707N", manifest.chip());
        assertEquals("E87-JD9855-R1", manifest.profile());
        assertEquals("SINGLE_BANK", manifest.layout());
        assertEquals("0.1.0", manifest.semver());
        assertEquals("11.1.0.4", manifest.qixVersion());
        assertEquals(EmbeddedReleaseTestFixture.RELEASE_ROOT, manifest.releaseRoot());
        assertArrayEquals(hex(EmbeddedReleaseTestFixture.BUILD_ID), manifest.buildId());
        assertEquals(6, manifest.files().size());
        assertEquals("qix", manifest.files().get(3).role());
        assertEquals(EmbeddedReleaseTestFixture.QIX_NAME,
                manifest.files().get(3).filename());
        assertFalse(manifest.releaseEligible());
    }

    @Test public void parserRejectsNoncanonicalDuplicateUnknownAndTrailingJson() {
        EmbeddedReleaseTestFixture fixture = new EmbeddedReleaseTestFixture();
        String valid = new String(fixture.receiptBytes(), StandardCharsets.US_ASCII);
        String[] malformed = new String[] {
                valid.replace("  \"chip\": \"AC707N\",\n", "  \"chip\": \"AC707N\",\n"
                        + "  \"chip\": \"AC707N\",\n"),
                valid.replace("  \"chip\": \"AC707N\",\n", "  \"chip\": \"AC707N\",\n"
                        + "  \"unknown\": true,\n"),
                valid.substring(0, valid.length() - 1),
                valid + " ",
                valid.replace("  \"schemaVersion\": 1,", "  \"schemaVersion\": 1.0,"),
        };
        for (String candidate : malformed) {
            assertThrows(IllegalArgumentException.class,
                    () -> TransitionManifest.parse(
                            candidate.getBytes(StandardCharsets.US_ASCII)));
        }
    }

    @Test public void parserRejectsEveryTargetOrEligibilityIdentityMutation() {
        EmbeddedReleaseTestFixture fixture = new EmbeddedReleaseTestFixture();
        String valid = new String(fixture.receiptBytes(), StandardCharsets.US_ASCII);
        String[] malformed = new String[] {
                valid.replace("\"AC707N\"", "\"AC697N\""),
                valid.replace("\"E87-JD9855-R1\"", "\"E87-1542-STAGE0-H\""),
                valid.replace("\"SINGLE_BANK\"", "\"DUAL_BANK\""),
                valid.replace("\"labEligible\": true", "\"labEligible\": false"),
                valid.replace(EmbeddedReleaseTestFixture.BUILD_ID,
                        EmbeddedReleaseTestFixture.BUILD_ID.toLowerCase()),
                valid.replace("\"qixVersion\": \"11.1.0.4\"",
                        "\"qixVersion\": \"11.1.0.2\""),
                valid.replace("\"semver\": \"0.1.0\"", "\"semver\": \"01.1.0\""),
        };
        for (String candidate : malformed) {
            assertThrows(IllegalArgumentException.class,
                    () -> TransitionManifest.parse(
                            candidate.getBytes(StandardCharsets.US_ASCII)));
        }
    }

    @Test public void returnedBuildIdAndCollectionsCannotMutateManifest() {
        TransitionManifest manifest = TransitionManifest.parse(
                new EmbeddedReleaseTestFixture().receiptBytes());
        byte[] buildId = manifest.buildId();
        buildId[0] ^= 0x7F;
        assertArrayEquals(hex(EmbeddedReleaseTestFixture.BUILD_ID), manifest.buildId());
        assertThrows(UnsupportedOperationException.class,
                () -> manifest.files().clear());
    }

    @Test public void receiptSuppliedFutureQixVersionIsAcceptedButConsumedFloorIsNot() {
        EmbeddedReleaseTestFixture fixture = new EmbeddedReleaseTestFixture();
        String valid = new String(fixture.receiptBytes(), StandardCharsets.US_ASCII);

        TransitionManifest future = TransitionManifest.parse(
                valid.replace("11.1.0.4", "11.1.0.5")
                        .getBytes(StandardCharsets.US_ASCII));

        assertEquals("11.1.0.5", future.qixVersion());
        assertThrows(IllegalArgumentException.class,
                () -> TransitionManifest.parse(
                        valid.replace("11.1.0.4", "11.1.0.3")
                                .getBytes(StandardCharsets.US_ASCII)));
    }

    private static byte[] hex(String value) {
        byte[] result = new byte[value.length() / 2];
        for (int index = 0; index < result.length; index++) {
            result[index] = (byte) Integer.parseInt(
                    value.substring(index * 2, index * 2 + 2), 16);
        }
        return result;
    }
}
