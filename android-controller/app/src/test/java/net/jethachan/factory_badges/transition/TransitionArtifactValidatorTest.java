package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.junit.Test;

public final class TransitionArtifactValidatorTest {
    @Test public void exactClosedAssetTreeProducesOnlyImmutableQixArtifact() throws Exception {
        EmbeddedReleaseTestFixture source = new EmbeddedReleaseTestFixture();

        TransitionArtifact artifact = new TransitionArtifactValidator().validate(source);

        byte[] qix = source.assets.get(
                EmbeddedReleaseTestFixture.PREFIX + EmbeddedReleaseTestFixture.QIX_NAME);
        assertArrayEquals(Arrays.copyOf(qix, 27), artifact.qixHeader());
        assertArrayEquals(source.assets.get(EmbeddedReleaseTestFixture.PREFIX + "update.ufw"),
                artifact.ufwPayload());
        assertArrayEquals(EmbeddedReleaseTestFixture.sha256(qix), artifact.qixSha256());
        assertArrayEquals(hex(EmbeddedReleaseTestFixture.BUILD_ID), artifact.expectedBuildId());
        assertEquals(7, source.opens);
    }

    @Test public void closedInventoryRejectsExtraMissingAndNestedAssets() {
        EmbeddedReleaseTestFixture extra = new EmbeddedReleaseTestFixture();
        extra.assets.put("e87/extra.bin", new byte[] {1});
        assertInvalid(extra);

        EmbeddedReleaseTestFixture missing = new EmbeddedReleaseTestFixture();
        missing.assets.remove(EmbeddedReleaseTestFixture.PREFIX + "app.bin");
        assertInvalid(missing);

        EmbeddedReleaseTestFixture nested = new EmbeddedReleaseTestFixture();
        nested.assets.put(EmbeddedReleaseTestFixture.PREFIX + "other/extra.bin",
                new byte[] {1});
        assertInvalid(nested);
    }

    @Test public void everyEmbeddedByteIsLengthAndHashBound() {
        for (String name : new String[] {
                "app.bin", "jl_isd.fw", "update.ufw",
                EmbeddedReleaseTestFixture.QIX_NAME, "manifest.json", "SHA256SUMS"
        }) {
            EmbeddedReleaseTestFixture source = new EmbeddedReleaseTestFixture();
            String path = EmbeddedReleaseTestFixture.PREFIX + name;
            byte[] data = source.assets.get(path);
            source.assets.put(path, Arrays.copyOf(data, data.length + 1));
            assertInvalid(source);
        }
    }

    @Test public void canonicalSumsAndFirmwareManifestAreRecheckedAfterReceiptHashes() {
        EmbeddedReleaseTestFixture sums = new EmbeddedReleaseTestFixture();
        String sumsPath = EmbeddedReleaseTestFixture.PREFIX + "SHA256SUMS";
        sums.assets.put(sumsPath, new String(sums.assets.get(sumsPath), StandardCharsets.US_ASCII)
                .replace(" *app.bin", "  app.bin").getBytes(StandardCharsets.US_ASCII));
        sums.assets.put("e87/default-release.json", sums.receiptBytes());
        assertInvalid(sums);

        EmbeddedReleaseTestFixture manifest = new EmbeddedReleaseTestFixture();
        manifest.assets.put(EmbeddedReleaseTestFixture.PREFIX + "manifest.json",
                EmbeddedReleaseTestFixture.ascii(
                        "{\n  \"labEligible\": false,\n"
                        + "  \"schema\": \"e87-firmware-manifest-v1\"\n}\n"));
        manifest.rebuildMetadata();
        assertInvalid(manifest);
    }

    @Test public void qixHeaderCrcAndPayloadEqualityAreRecheckedAfterAllHashes() {
        EmbeddedReleaseTestFixture wrongMagic = new EmbeddedReleaseTestFixture();
        mutateQixAndRebind(wrongMagic, 0);
        assertInvalid(wrongMagic);

        EmbeddedReleaseTestFixture wrongReserved = new EmbeddedReleaseTestFixture();
        mutateQixAndRebind(wrongReserved, 20);
        assertInvalid(wrongReserved);

        EmbeddedReleaseTestFixture wrongCrc = new EmbeddedReleaseTestFixture();
        mutateQixAndRebind(wrongCrc, 25);
        assertInvalid(wrongCrc);

        EmbeddedReleaseTestFixture differentPayload = new EmbeddedReleaseTestFixture();
        differentPayload.assets.put(
                EmbeddedReleaseTestFixture.PREFIX + EmbeddedReleaseTestFixture.QIX_NAME,
                EmbeddedReleaseTestFixture.makeQix(
                        EmbeddedReleaseTestFixture.ascii("different-valid-payload")));
        differentPayload.rebuildMetadata();
        assertInvalid(differentPayload);
    }

    @Test public void nullSourceIsRejectedBeforeAnyAssetOperation() {
        assertThrows(IllegalArgumentException.class,
                () -> new TransitionArtifactValidator().validate(null));
    }

    private static void mutateQixAndRebind(EmbeddedReleaseTestFixture source, int offset) {
        String path = EmbeddedReleaseTestFixture.PREFIX + EmbeddedReleaseTestFixture.QIX_NAME;
        byte[] qix = Arrays.copyOf(source.assets.get(path), source.assets.get(path).length);
        qix[offset] ^= 1;
        source.assets.put(path, qix);
        source.rebuildMetadata();
    }

    private static void assertInvalid(EmbeddedReleaseTestFixture source) {
        assertThrows(IllegalArgumentException.class,
                () -> new TransitionArtifactValidator().validate(source));
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
