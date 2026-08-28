package net.jethachan.factory_badges.transition;

import android.content.Context;
import android.content.res.AssetManager;
import java.io.IOException;

/**
 * Fail-closed seam for the generated embedded release.
 *
 * <p>The current build intentionally contains no release. Even if a canonical index appears,
 * bytes remain unavailable until the authoritative package validators are integrated here.
 */
public final class EmbeddedFirmwareRepository implements TransitionArtifactProvider {
    private static final String ASSET_DIRECTORY = "e87";
    private static final String INDEX_FILENAME = "default-release.json";

    interface IndexProbe {
        boolean canonicalIndexPresent() throws IOException;
    }

    private final IndexProbe indexProbe;

    public EmbeddedFirmwareRepository(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("context must not be null");
        }
        Context applicationContext = context.getApplicationContext();
        if (applicationContext == null) {
            throw new IllegalArgumentException("application context must not be null");
        }
        final AssetManager assets = applicationContext.getAssets();
        indexProbe = new IndexProbe() {
            @Override public boolean canonicalIndexPresent() throws IOException {
                String[] names = assets.list(ASSET_DIRECTORY);
                if (names == null) return false;
                for (String name : names) {
                    if (INDEX_FILENAME.equals(name)) return true;
                }
                return false;
            }
        };
    }

    EmbeddedFirmwareRepository(IndexProbe indexProbe) {
        if (indexProbe == null) {
            throw new IllegalArgumentException("index probe must not be null");
        }
        this.indexProbe = indexProbe;
    }

    @Override public LoadResult load() {
        final boolean present;
        try {
            present = indexProbe.canonicalIndexPresent();
        } catch (IOException | RuntimeException failure) {
            return LoadResult.unavailable(Status.INVALID_PACKAGE);
        }
        return LoadResult.unavailable(present
                ? Status.VALIDATOR_NOT_INTEGRATED : Status.NOT_PACKAGED);
    }
}
