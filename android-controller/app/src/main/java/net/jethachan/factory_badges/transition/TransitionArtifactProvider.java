package net.jethachan.factory_badges.transition;

/** Supplies only an immutable artifact that has already passed the authoritative release gate. */
public interface TransitionArtifactProvider {
    enum Status {
        READY,
        NOT_PACKAGED,
        VALIDATOR_NOT_INTEGRATED,
        INVALID_PACKAGE
    }

    final class LoadResult {
        private final Status status;
        private final TransitionArtifact artifact;

        private LoadResult(Status status, TransitionArtifact artifact) {
            this.status = status;
            this.artifact = artifact;
        }

        public static LoadResult ready(TransitionArtifact artifact) {
            if (artifact == null) {
                throw new IllegalArgumentException("validated artifact must not be null");
            }
            return new LoadResult(Status.READY, artifact);
        }

        public static LoadResult unavailable(Status status) {
            if (status == null || status == Status.READY) {
                throw new IllegalArgumentException(
                        "unavailable result requires a non-ready status");
            }
            return new LoadResult(status, null);
        }

        public Status status() {
            return status;
        }

        public TransitionArtifact artifact() {
            return artifact;
        }
    }

    LoadResult load();
}
