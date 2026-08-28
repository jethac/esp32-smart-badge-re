package net.jethachan.factory_badges.ui;

import android.content.Context;
import net.jethachan.factory_badges.transition.EmbeddedFirmwareRepository;
import net.jethachan.factory_badges.transition.TransitionArtifactProvider;

/** Prevents navigation unless the APK's embedded transition artifact is fully revalidated. */
final class MaintenanceEntryGate {
    private MaintenanceEntryGate() {}

    static boolean canEnter(Context context) {
        if (context == null) return false;
        try {
            return canEnter(new EmbeddedFirmwareRepository(context));
        } catch (RuntimeException failure) {
            return false;
        }
    }

    static boolean canEnter(TransitionArtifactProvider provider) {
        if (provider == null) return false;
        final TransitionArtifactProvider.LoadResult loaded;
        try {
            loaded = provider.load();
        } catch (RuntimeException failure) {
            return false;
        }
        return loaded != null
                && loaded.status() == TransitionArtifactProvider.Status.READY
                && loaded.artifact() != null;
    }
}
