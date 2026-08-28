package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public final class TransitionArtifactProviderTest {
    @Test public void readyResultCarriesOnlyTheImmutableValidatedArtifact() {
        TransitionArtifact artifact = TestTransitionArtifact.create();

        TransitionArtifactProvider.LoadResult result =
                TransitionArtifactProvider.LoadResult.ready(artifact);

        assertEquals(TransitionArtifactProvider.Status.READY, result.status());
        assertSame(artifact, result.artifact());
    }

    @Test public void everyUnavailableStatusCarriesNoArtifact() {
        for (TransitionArtifactProvider.Status status :
                TransitionArtifactProvider.Status.values()) {
            if (status == TransitionArtifactProvider.Status.READY) continue;

            TransitionArtifactProvider.LoadResult result =
                    TransitionArtifactProvider.LoadResult.unavailable(status);

            assertEquals(status, result.status());
            assertNull(result.artifact());
        }
    }

    @Test public void resultFactoriesRejectContradictoryOrNullInputs() {
        assertThrows(IllegalArgumentException.class,
                () -> TransitionArtifactProvider.LoadResult.ready(null));
        assertThrows(IllegalArgumentException.class,
                () -> TransitionArtifactProvider.LoadResult.unavailable(null));
        assertThrows(IllegalArgumentException.class,
                () -> TransitionArtifactProvider.LoadResult.unavailable(
                        TransitionArtifactProvider.Status.READY));
    }
}
