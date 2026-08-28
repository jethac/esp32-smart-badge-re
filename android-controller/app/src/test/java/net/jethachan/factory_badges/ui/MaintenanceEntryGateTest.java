package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.security.MessageDigest;
import net.jethachan.factory_badges.transition.TransitionArtifact;
import net.jethachan.factory_badges.transition.TransitionArtifactProvider;
import org.junit.Test;

public final class MaintenanceEntryGateTest {
    @Test public void onlyAReadyNonNullArtifactCanEnterMaintenance() throws Exception {
        TransitionArtifact artifact = artifact();

        assertTrue(MaintenanceEntryGate.canEnter(
                () -> TransitionArtifactProvider.LoadResult.ready(artifact)));
        assertFalse(MaintenanceEntryGate.canEnter(
                () -> TransitionArtifactProvider.LoadResult.unavailable(
                        TransitionArtifactProvider.Status.NOT_PACKAGED)));
        assertFalse(MaintenanceEntryGate.canEnter(
                () -> TransitionArtifactProvider.LoadResult.unavailable(
                        TransitionArtifactProvider.Status.INVALID_PACKAGE)));
        assertFalse(MaintenanceEntryGate.canEnter(() -> null));
        assertFalse(MaintenanceEntryGate.canEnter(() -> {
            throw new IllegalStateException("invalid embedded package");
        }));
    }

    @Test public void nullProviderFailsClosed() {
        assertFalse(MaintenanceEntryGate.canEnter(
                (TransitionArtifactProvider) null));
    }

    private static TransitionArtifact artifact() throws Exception {
        byte[] header = new byte[27];
        header[13] = 1;
        byte[] payload = new byte[] {7};
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        digest.update(header);
        digest.update(payload);
        return new TransitionArtifact(header, payload, digest.digest(), new byte[16]);
    }
}
