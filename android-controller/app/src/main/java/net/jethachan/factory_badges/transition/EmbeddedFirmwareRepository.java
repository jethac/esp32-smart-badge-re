package net.jethachan.factory_badges.transition;

import android.content.Context;
import android.content.res.AssetManager;
import java.io.IOException;
import java.io.InputStream;

/** Fail-closed source of firmware bytes revalidated from the immutable APK asset tree. */
public final class EmbeddedFirmwareRepository implements TransitionArtifactProvider {
    private final TransitionArtifactValidator.AssetSource source;
    private final TransitionArtifactValidator validator;

    public EmbeddedFirmwareRepository(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("context must not be null");
        }
        Context applicationContext = context.getApplicationContext();
        if (applicationContext == null) {
            throw new IllegalArgumentException("application context must not be null");
        }
        final AssetManager assets = applicationContext.getAssets();
        if (assets == null) {
            throw new IllegalArgumentException("application assets must not be null");
        }
        source = new TransitionArtifactValidator.AssetSource() {
            @Override public String[] list(String path) throws IOException {
                return assets.list(path);
            }

            @Override public InputStream open(String path) throws IOException {
                return assets.open(path, AssetManager.ACCESS_STREAMING);
            }
        };
        validator = new TransitionArtifactValidator();
    }

    EmbeddedFirmwareRepository(TransitionArtifactValidator.AssetSource source) {
        if (source == null) {
            throw new IllegalArgumentException("asset source must not be null");
        }
        this.source = source;
        validator = new TransitionArtifactValidator();
    }

    @Override public LoadResult load() {
        try {
            return LoadResult.ready(validator.validate(source));
        } catch (TransitionArtifactValidator.MissingIndexException missing) {
            return LoadResult.unavailable(Status.NOT_PACKAGED);
        } catch (IOException | RuntimeException invalid) {
            return LoadResult.unavailable(Status.INVALID_PACKAGE);
        }
    }
}
