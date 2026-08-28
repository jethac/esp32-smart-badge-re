package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;

import java.io.IOException;
import org.junit.Test;

public final class EmbeddedFirmwareRepositoryTest {
    @Test public void missingGeneratedIndexFailsClosedAsNotPackaged() {
        EmbeddedFirmwareRepository repository =
                new EmbeddedFirmwareRepository(() -> false);

        TransitionArtifactProvider.LoadResult result = repository.load();

        assertEquals(TransitionArtifactProvider.Status.NOT_PACKAGED, result.status());
        assertNull(result.artifact());
    }

    @Test public void indexPresenceCannotBypassUnavailableAuthoritativeValidators() {
        EmbeddedFirmwareRepository repository =
                new EmbeddedFirmwareRepository(() -> true);

        TransitionArtifactProvider.LoadResult result = repository.load();

        assertEquals(TransitionArtifactProvider.Status.VALIDATOR_NOT_INTEGRATED,
                result.status());
        assertNull(result.artifact());
    }

    @Test public void assetInventoryFailureNeverProducesAnArtifact() {
        EmbeddedFirmwareRepository repository = new EmbeddedFirmwareRepository(
                new EmbeddedFirmwareRepository.IndexProbe() {
                    @Override public boolean canonicalIndexPresent() throws IOException {
                        throw new IOException("asset inventory unavailable");
                    }
                });

        TransitionArtifactProvider.LoadResult result = repository.load();

        assertEquals(TransitionArtifactProvider.Status.INVALID_PACKAGE, result.status());
        assertNull(result.artifact());
    }

    @Test public void nullProbeIsRejected() {
        assertThrows(IllegalArgumentException.class,
                () -> new EmbeddedFirmwareRepository(
                        (EmbeddedFirmwareRepository.IndexProbe) null));
    }
}
