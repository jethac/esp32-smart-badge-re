package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import org.junit.Test;

public final class EmbeddedFirmwareRepositoryTest {
    @Test public void missingGeneratedIndexFailsClosedAsNotPackaged() {
        TransitionArtifactValidator.AssetSource empty =
                new TransitionArtifactValidator.AssetSource() {
                    @Override public String[] list(String path) {
                        return new String[0];
                    }

                    @Override public InputStream open(String path) throws IOException {
                        throw new FileNotFoundException(path);
                    }
                };
        EmbeddedFirmwareRepository repository = new EmbeddedFirmwareRepository(empty);

        TransitionArtifactProvider.LoadResult result = repository.load();

        assertEquals(TransitionArtifactProvider.Status.NOT_PACKAGED, result.status());
        assertNull(result.artifact());
    }

    @Test public void fullyRevalidatedEmbeddedReleaseIsReadyWithExpectedIdentity() {
        EmbeddedReleaseTestFixture source = new EmbeddedReleaseTestFixture();
        EmbeddedFirmwareRepository repository = new EmbeddedFirmwareRepository(source);

        TransitionArtifactProvider.LoadResult result = repository.load();

        assertEquals(TransitionArtifactProvider.Status.READY, result.status());
        assertNotNull(result.artifact());
        assertArrayEquals(hex(EmbeddedReleaseTestFixture.BUILD_ID),
                result.artifact().expectedBuildId());
    }

    @Test public void anyInventoryOrReadFailureNeverProducesAnArtifact() {
        EmbeddedReleaseTestFixture invalid = new EmbeddedReleaseTestFixture();
        invalid.assets.put("e87/unreferenced.bin", new byte[] {1});
        TransitionArtifactProvider.LoadResult malformed =
                new EmbeddedFirmwareRepository(invalid).load();
        assertEquals(TransitionArtifactProvider.Status.INVALID_PACKAGE, malformed.status());
        assertNull(malformed.artifact());

        TransitionArtifactValidator.AssetSource unreadable =
                new TransitionArtifactValidator.AssetSource() {
                    @Override public String[] list(String path) throws IOException {
                        throw new IOException("asset inventory unavailable");
                    }

                    @Override public InputStream open(String path) throws IOException {
                        throw new IOException("asset bytes unavailable");
                    }
                };
        TransitionArtifactProvider.LoadResult failed =
                new EmbeddedFirmwareRepository(unreadable).load();
        assertEquals(TransitionArtifactProvider.Status.INVALID_PACKAGE, failed.status());
        assertNull(failed.artifact());
    }

    @Test public void nullAssetSourceIsRejected() {
        assertThrows(IllegalArgumentException.class,
                () -> new EmbeddedFirmwareRepository(
                        (TransitionArtifactValidator.AssetSource) null));
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
