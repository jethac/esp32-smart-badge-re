package net.jethachan.factory_badges.ui;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import net.jethachan.factory_badges.transition.StockGattDriver;
import net.jethachan.factory_badges.transition.StockQixTransferMachine;
import net.jethachan.factory_badges.transition.TransitionArtifact;
import net.jethachan.factory_badges.transition.TransitionArtifactProvider;

/** Pure state and physical-gate coordinator for the one-time stock transition screen. */
final class MaintenanceUiPresenter implements AutoCloseable {
    enum Phase {
        ARTIFACT_UNAVAILABLE,
        READY,
        STARTING,
        SCANNING,
        CANDIDATES,
        CONNECTING,
        TRANSFERRING,
        WAITING_FOR_CUSTOM_FIRMWARE,
        FAILED,
        CLOSED
    }

    interface Session extends AutoCloseable {
        void startScan();
        void connect(StockGattDriver.Peer peer);
        void cancel();
        @Override void close();
    }

    interface Listener {
        void onCandidate(StockGattDriver.Peer candidate);
        void onProgress(long acknowledgedBytes, long totalBytes, boolean mayCancel);
        void onAccepted();
        void onFailed(StockQixTransferMachine.FailureCode failureCode);
    }

    interface Host {
        void render(ViewState state);
        Session openSession(TransitionArtifact artifact, Listener listener);
    }

    static final class ViewState {
        private final Phase phase;
        private final TransitionArtifactProvider.Status artifactStatus;
        private final boolean confirmationChecked;
        private final boolean confirmationEnabled;
        private final boolean startEnabled;
        private final boolean cancelEnabled;
        private final long qixByteLength;
        private final String expectedBuildIdHex;
        private final List<StockGattDriver.Peer> candidates;
        private final long acknowledgedBytes;
        private final long totalBytes;
        private final int progressPercent;
        private final StockQixTransferMachine.FailureCode failureCode;

        ViewState(Phase phase, TransitionArtifactProvider.Status artifactStatus,
                boolean confirmationChecked, boolean confirmationEnabled,
                boolean startEnabled, boolean cancelEnabled, long qixByteLength,
                String expectedBuildIdHex, List<StockGattDriver.Peer> candidates,
                long acknowledgedBytes, long totalBytes, int progressPercent,
                StockQixTransferMachine.FailureCode failureCode) {
            this.phase = phase;
            this.artifactStatus = artifactStatus;
            this.confirmationChecked = confirmationChecked;
            this.confirmationEnabled = confirmationEnabled;
            this.startEnabled = startEnabled;
            this.cancelEnabled = cancelEnabled;
            this.qixByteLength = qixByteLength;
            this.expectedBuildIdHex = expectedBuildIdHex;
            this.candidates = Collections.unmodifiableList(
                    new ArrayList<StockGattDriver.Peer>(candidates));
            this.acknowledgedBytes = acknowledgedBytes;
            this.totalBytes = totalBytes;
            this.progressPercent = progressPercent;
            this.failureCode = failureCode;
        }

        Phase phase() { return phase; }
        TransitionArtifactProvider.Status artifactStatus() { return artifactStatus; }
        boolean confirmationChecked() { return confirmationChecked; }
        boolean confirmationEnabled() { return confirmationEnabled; }
        boolean startEnabled() { return startEnabled; }
        boolean cancelEnabled() { return cancelEnabled; }
        long qixByteLength() { return qixByteLength; }
        String expectedBuildIdHex() { return expectedBuildIdHex; }
        List<StockGattDriver.Peer> candidates() { return candidates; }
        long acknowledgedBytes() { return acknowledgedBytes; }
        long totalBytes() { return totalBytes; }
        int progressPercent() { return progressPercent; }
        StockQixTransferMachine.FailureCode failureCode() { return failureCode; }
        boolean transportAcceptanceIsProvisional() {
            return phase == Phase.WAITING_FOR_CUSTOM_FIRMWARE;
        }
    }

    private final Host host;
    private final Listener listener = new SessionListener();
    private final Set<StockGattDriver.Peer> candidates =
            new LinkedHashSet<StockGattDriver.Peer>();

    private TransitionArtifactProvider.Status artifactStatus;
    private TransitionArtifact artifact;
    private Session session;
    private Phase phase;
    private boolean confirmationChecked;
    private boolean mayCancel;
    private long acknowledgedBytes;
    private long totalBytes;
    private StockQixTransferMachine.FailureCode failureCode =
            StockQixTransferMachine.FailureCode.NONE;
    private ViewState viewState;

    MaintenanceUiPresenter(TransitionArtifactProvider provider, Host host) {
        if (provider == null || host == null) {
            throw new IllegalArgumentException("presenter ports must not be null");
        }
        this.host = host;
        TransitionArtifactProvider.LoadResult loaded;
        try {
            loaded = provider.load();
        } catch (RuntimeException failure) {
            loaded = TransitionArtifactProvider.LoadResult.unavailable(
                    TransitionArtifactProvider.Status.INVALID_PACKAGE);
        }
        if (loaded == null) {
            throw new IllegalArgumentException("artifact provider returned null");
        }
        artifactStatus = loaded.status();
        artifact = loaded.artifact();
        if (artifactStatus == TransitionArtifactProvider.Status.READY && artifact != null) {
            phase = Phase.READY;
            totalBytes = artifact.ufwPayload().length;
        } else {
            artifact = null;
            phase = Phase.ARTIFACT_UNAVAILABLE;
        }
        publish();
    }

    ViewState viewState() {
        return viewState;
    }

    void onConfirmationChanged(boolean checked) {
        if (phase != Phase.READY && phase != Phase.CANDIDATES) return;
        if (confirmationChecked == checked) return;
        confirmationChecked = checked;
        publish();
    }

    void onStartPressed() {
        if (phase != Phase.READY || !confirmationChecked || artifact == null) return;
        confirmationChecked = false;
        phase = Phase.STARTING;
        publish();

        final Session opened;
        try {
            opened = host.openSession(artifact, listener);
        } catch (RuntimeException failure) {
            fail(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        if (opened == null) {
            fail(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        session = opened;
        mayCancel = true;
        phase = Phase.SCANNING;
        publish();
        try {
            opened.startScan();
        } catch (RuntimeException failure) {
            fail(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        }
    }

    void onCandidateSelected(StockGattDriver.Peer peer) {
        if (peer == null) throw new IllegalArgumentException("peer must not be null");
        if (phase != Phase.CANDIDATES || session == null || !confirmationChecked
                || !candidates.contains(peer)) {
            return;
        }
        confirmationChecked = false;
        phase = Phase.CONNECTING;
        publish();
        try {
            session.connect(peer);
        } catch (RuntimeException failure) {
            fail(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        }
    }

    void onCancelPressed() {
        if (session == null || !mayCancel || !activePhase()) return;
        mayCancel = false;
        publish();
        try {
            session.cancel();
        } catch (RuntimeException failure) {
            fail(StockQixTransferMachine.FailureCode.CANCELLED);
        }
    }

    @Override public void close() {
        if (phase == Phase.CLOSED) return;
        phase = Phase.CLOSED;
        confirmationChecked = false;
        mayCancel = false;
        candidates.clear();
        Session doomed = session;
        session = null;
        closeSession(doomed);
        publish();
    }

    private boolean activePhase() {
        return phase == Phase.SCANNING || phase == Phase.CANDIDATES
                || phase == Phase.CONNECTING || phase == Phase.TRANSFERRING;
    }

    private void fail(StockQixTransferMachine.FailureCode code) {
        if (phase == Phase.CLOSED || phase == Phase.FAILED
                || phase == Phase.WAITING_FOR_CUSTOM_FIRMWARE) {
            return;
        }
        phase = Phase.FAILED;
        failureCode = code == null
                ? StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED : code;
        confirmationChecked = false;
        mayCancel = false;
        candidates.clear();
        Session doomed = session;
        session = null;
        closeSession(doomed);
        publish();
    }

    private void accepted() {
        if (!activePhase()) return;
        phase = Phase.WAITING_FOR_CUSTOM_FIRMWARE;
        confirmationChecked = false;
        mayCancel = false;
        candidates.clear();
        Session doomed = session;
        session = null;
        closeSession(doomed);
        publish();
    }

    private void closeSession(Session doomed) {
        if (doomed == null) return;
        try {
            doomed.close();
        } catch (RuntimeException ignored) {
            // The state is already fail-closed; cleanup remains best effort.
        }
    }

    private void publish() {
        boolean ready = phase == Phase.READY && artifact != null;
        boolean candidateGate = phase == Phase.CANDIDATES && session != null;
        boolean confirmationAvailable = ready || candidateGate;
        long qixLength = artifact == null ? 0L
                : (long) artifact.qixHeader().length + artifact.ufwPayload().length;
        String buildId = artifact == null ? null : hex(artifact.expectedBuildId());
        int progress = totalBytes <= 0L ? 0
                : (int) ((acknowledgedBytes * 100L) / totalBytes);
        viewState = new ViewState(
                phase,
                artifactStatus,
                confirmationAvailable && confirmationChecked,
                confirmationAvailable,
                ready && confirmationChecked,
                session != null && mayCancel && activePhase(),
                qixLength,
                buildId,
                new ArrayList<StockGattDriver.Peer>(candidates),
                acknowledgedBytes,
                totalBytes,
                progress,
                failureCode);
        host.render(viewState);
    }

    private static String hex(byte[] bytes) {
        char[] digits = "0123456789ABCDEF".toCharArray();
        char[] encoded = new char[bytes.length * 2];
        for (int index = 0; index < bytes.length; index++) {
            int value = bytes[index] & 0xFF;
            encoded[index * 2] = digits[value >>> 4];
            encoded[index * 2 + 1] = digits[value & 0x0F];
        }
        return new String(encoded);
    }

    private final class SessionListener implements Listener {
        @Override public void onCandidate(StockGattDriver.Peer candidate) {
            if ((phase != Phase.SCANNING && phase != Phase.CANDIDATES)
                    || candidate == null || session == null) {
                return;
            }
            if (candidates.add(candidate)) {
                phase = Phase.CANDIDATES;
                publish();
            }
        }

        @Override public void onProgress(
                long acknowledged, long total, boolean reportedMayCancel) {
            if (!activePhase() || session == null) return;
            if (total <= 0L || acknowledged < 0L || acknowledged > total) {
                fail(StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
                return;
            }
            acknowledgedBytes = acknowledged;
            totalBytes = total;
            mayCancel = reportedMayCancel;
            phase = Phase.TRANSFERRING;
            publish();
        }

        @Override public void onAccepted() {
            accepted();
        }

        @Override public void onFailed(StockQixTransferMachine.FailureCode code) {
            fail(code);
        }
    }
}
