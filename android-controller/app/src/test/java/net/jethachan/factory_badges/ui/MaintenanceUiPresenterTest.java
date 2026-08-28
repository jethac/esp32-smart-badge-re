package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.List;
import net.jethachan.factory_badges.transition.StockGattDriver;
import net.jethachan.factory_badges.transition.StockQixTransferMachine;
import net.jethachan.factory_badges.transition.TransitionArtifact;
import net.jethachan.factory_badges.transition.TransitionArtifactProvider;
import org.junit.Test;

public final class MaintenanceUiPresenterTest {
    @Test public void unavailableArtifactCannotArmCreateOrScan() {
        FakeHost host = new FakeHost();
        MaintenanceUiPresenter presenter = new MaintenanceUiPresenter(
                provider(TransitionArtifactProvider.LoadResult.unavailable(
                        TransitionArtifactProvider.Status.NOT_PACKAGED)), host);

        presenter.onConfirmationChanged(true);
        presenter.onStartPressed();

        assertEquals(MaintenanceUiPresenter.Phase.ARTIFACT_UNAVAILABLE,
                presenter.viewState().phase());
        assertEquals(TransitionArtifactProvider.Status.NOT_PACKAGED,
                presenter.viewState().artifactStatus());
        assertFalse(presenter.viewState().confirmationEnabled());
        assertFalse(presenter.viewState().startEnabled());
        assertEquals(0, host.openCount);
        assertEquals(0, host.session.startScanCount);
    }

    @Test public void readyArtifactStillRequiresFreshCheckAndExplicitStart() {
        TransitionArtifact artifact = artifact();
        FakeHost host = new FakeHost();
        MaintenanceUiPresenter presenter = new MaintenanceUiPresenter(
                provider(TransitionArtifactProvider.LoadResult.ready(artifact)), host);

        assertEquals(MaintenanceUiPresenter.Phase.READY,
                presenter.viewState().phase());
        assertFalse(presenter.viewState().confirmationChecked());
        assertFalse(presenter.viewState().startEnabled());
        assertEquals(28L, presenter.viewState().qixByteLength());
        assertEquals("0102030405060708090A0B0C0D0E0F10",
                presenter.viewState().expectedBuildIdHex());
        assertEquals(0, host.openCount);

        presenter.onConfirmationChanged(true);

        assertTrue(presenter.viewState().confirmationChecked());
        assertTrue(presenter.viewState().startEnabled());
        assertEquals("checking the box must not create a session", 0, host.openCount);

        presenter.onStartPressed();

        assertEquals(1, host.openCount);
        assertSame(artifact, host.openedArtifact);
        assertEquals(1, host.session.startScanCount);
        assertEquals(MaintenanceUiPresenter.Phase.SCANNING,
                presenter.viewState().phase());
        assertFalse(presenter.viewState().confirmationChecked());
        assertFalse(presenter.viewState().startEnabled());
        assertEquals(MaintenanceUiPresenter.Phase.STARTING,
                host.stateAtOpen.phase());
        assertFalse(host.stateAtOpen.confirmationChecked());

        presenter.onStartPressed();
        assertEquals("one physical confirmation creates only one session", 1, host.openCount);
        assertEquals(1, host.session.startScanCount);
    }

    @Test public void onlySurfacedCandidateCanBeExplicitlySelected() {
        FakeHost host = startedHost();
        MaintenanceUiPresenter presenter = host.presenter;
        StockGattDriver.Peer first = peer("AA:BB:CC:DD:EE:01", "E87");
        StockGattDriver.Peer duplicate = peer("aa:bb:cc:dd:ee:01", "spoofed");
        StockGattDriver.Peer other = peer("AA:BB:CC:DD:EE:02", "other");

        host.listener.onCandidate(first);
        host.listener.onCandidate(duplicate);

        assertEquals(MaintenanceUiPresenter.Phase.CANDIDATES,
                presenter.viewState().phase());
        assertEquals(1, presenter.viewState().candidates().size());
        assertSame(first, presenter.viewState().candidates().get(0));
        assertThrows(UnsupportedOperationException.class,
                () -> presenter.viewState().candidates().add(other));

        presenter.onCandidateSelected(other);
        assertEquals(0, host.session.connectCount);

        presenter.onCandidateSelected(first);
        assertEquals(1, host.session.connectCount);
        assertSame(first, host.session.connectedPeer);
        assertEquals(MaintenanceUiPresenter.Phase.CONNECTING,
                presenter.viewState().phase());

        presenter.onCandidateSelected(first);
        assertEquals(1, host.session.connectCount);
    }

    @Test public void progressControlsCancellationAndTransportAcceptanceIsProvisional() {
        FakeHost host = startedHost();
        MaintenanceUiPresenter presenter = host.presenter;
        StockGattDriver.Peer first = peer("AA:BB:CC:DD:EE:01", "E87");
        host.listener.onCandidate(first);
        presenter.onCandidateSelected(first);

        host.listener.onProgress(256L, 1024L, true);

        assertEquals(MaintenanceUiPresenter.Phase.TRANSFERRING,
                presenter.viewState().phase());
        assertEquals(256L, presenter.viewState().acknowledgedBytes());
        assertEquals(1024L, presenter.viewState().totalBytes());
        assertEquals(25, presenter.viewState().progressPercent());
        assertTrue(presenter.viewState().cancelEnabled());

        presenter.onCancelPressed();
        assertEquals(1, host.session.cancelCount);

        host.listener.onProgress(1024L, 1024L, false);
        host.listener.onAccepted();

        assertEquals(MaintenanceUiPresenter.Phase.WAITING_FOR_CUSTOM_FIRMWARE,
                presenter.viewState().phase());
        assertTrue(presenter.viewState().transportAcceptanceIsProvisional());
        assertFalse(presenter.viewState().cancelEnabled());
        assertFalse(presenter.viewState().startEnabled());
    }

    @Test public void sessionFailureIsStickyAndClosesTheSessionOnce() {
        FakeHost host = startedHost();
        MaintenanceUiPresenter presenter = host.presenter;

        host.listener.onFailed(StockQixTransferMachine.FailureCode.TRANSPORT_TIMEOUT);

        assertEquals(MaintenanceUiPresenter.Phase.FAILED,
                presenter.viewState().phase());
        assertEquals(StockQixTransferMachine.FailureCode.TRANSPORT_TIMEOUT,
                presenter.viewState().failureCode());
        assertEquals(1, host.session.closeCount);
        assertFalse(presenter.viewState().confirmationEnabled());
        assertFalse(presenter.viewState().startEnabled());

        host.listener.onFailed(StockQixTransferMachine.FailureCode.WRONG_OPCODE);
        presenter.onConfirmationChanged(true);
        presenter.onStartPressed();
        assertEquals(1, host.session.closeCount);
        assertEquals(1, host.openCount);
        assertEquals(StockQixTransferMachine.FailureCode.TRANSPORT_TIMEOUT,
                presenter.viewState().failureCode());
    }

    @Test public void providerAndSessionFactoryExceptionsFailClosedBeforeScanning() {
        FakeHost providerHost = new FakeHost();
        MaintenanceUiPresenter providerFailure = new MaintenanceUiPresenter(
                new TransitionArtifactProvider() {
                    @Override public LoadResult load() {
                        throw new IllegalStateException("provider failed");
                    }
                }, providerHost);
        assertEquals(MaintenanceUiPresenter.Phase.ARTIFACT_UNAVAILABLE,
                providerFailure.viewState().phase());
        assertEquals(TransitionArtifactProvider.Status.INVALID_PACKAGE,
                providerFailure.viewState().artifactStatus());
        assertEquals(0, providerHost.openCount);

        FakeHost sessionHost = new FakeHost();
        sessionHost.openFailure = new IllegalStateException("session failed");
        MaintenanceUiPresenter sessionFailure = new MaintenanceUiPresenter(
                provider(TransitionArtifactProvider.LoadResult.ready(artifact())), sessionHost);
        sessionFailure.onConfirmationChanged(true);
        sessionFailure.onStartPressed();

        assertEquals(MaintenanceUiPresenter.Phase.FAILED,
                sessionFailure.viewState().phase());
        assertEquals(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED,
                sessionFailure.viewState().failureCode());
        assertEquals(0, sessionHost.session.startScanCount);
    }

    @Test public void closeIsIdempotentAndSilencesLateCallbacks() {
        FakeHost host = startedHost();
        MaintenanceUiPresenter presenter = host.presenter;

        presenter.close();
        presenter.close();
        host.listener.onCandidate(peer("AA:BB:CC:DD:EE:01", "E87"));
        host.listener.onAccepted();

        assertEquals(MaintenanceUiPresenter.Phase.CLOSED,
                presenter.viewState().phase());
        assertEquals(1, host.session.closeCount);
        assertTrue(presenter.viewState().candidates().isEmpty());
    }

    @Test public void constructorRejectsNullPortsAndNullProviderResult() {
        FakeHost host = new FakeHost();
        assertThrows(IllegalArgumentException.class,
                () -> new MaintenanceUiPresenter(null, host));
        assertThrows(IllegalArgumentException.class,
                () -> new MaintenanceUiPresenter(provider(null), host));
        assertThrows(IllegalArgumentException.class,
                () -> new MaintenanceUiPresenter(
                        provider(TransitionArtifactProvider.LoadResult.ready(artifact())), null));
    }

    private static FakeHost startedHost() {
        FakeHost host = new FakeHost();
        MaintenanceUiPresenter presenter = new MaintenanceUiPresenter(
                provider(TransitionArtifactProvider.LoadResult.ready(artifact())), host);
        host.presenter = presenter;
        presenter.onConfirmationChanged(true);
        presenter.onStartPressed();
        return host;
    }

    private static TransitionArtifactProvider provider(
            final TransitionArtifactProvider.LoadResult result) {
        return new TransitionArtifactProvider() {
            @Override public LoadResult load() { return result; }
        };
    }

    private static StockGattDriver.Peer peer(String address, String name) {
        return new StockGattDriver.Peer(address, name, -50);
    }

    private static TransitionArtifact artifact() {
        byte[] header = new byte[27];
        header[13] = 1;
        byte[] payload = new byte[] {0x2A};
        byte[] sha256 = new byte[] {
                (byte) 0xF3, (byte) 0xAE, (byte) 0xFF, 0x3E,
                0x22, (byte) 0x95, (byte) 0xC0, 0x6A,
                0x4F, 0x79, 0x0C, 0x1C,
                (byte) 0xEC, 0x3F, 0x1C, 0x3F,
                0x35, 0x61, (byte) 0xD3, (byte) 0xF6,
                (byte) 0x8F, (byte) 0x95, 0x2F, 0x00,
                0x32, 0x72, (byte) 0xBF, 0x7E,
                0x60, 0x40, (byte) 0xD5, (byte) 0xE2
        };
        byte[] buildId = new byte[16];
        for (int index = 0; index < buildId.length; index++) {
            buildId[index] = (byte) (index + 1);
        }
        return new TransitionArtifact(header, payload, sha256, buildId);
    }

    private static final class FakeHost implements MaintenanceUiPresenter.Host {
        int openCount;
        TransitionArtifact openedArtifact;
        MaintenanceUiPresenter.ViewState latest;
        MaintenanceUiPresenter.ViewState stateAtOpen;
        MaintenanceUiPresenter.Listener listener;
        MaintenanceUiPresenter presenter;
        final FakeSession session = new FakeSession();
        RuntimeException openFailure;

        @Override public void render(MaintenanceUiPresenter.ViewState state) {
            latest = state;
        }

        @Override public MaintenanceUiPresenter.Session openSession(
                TransitionArtifact artifact, MaintenanceUiPresenter.Listener suppliedListener) {
            openCount++;
            openedArtifact = artifact;
            listener = suppliedListener;
            stateAtOpen = latest;
            if (openFailure != null) throw openFailure;
            return session;
        }
    }

    private static final class FakeSession implements MaintenanceUiPresenter.Session {
        int startScanCount;
        int connectCount;
        int cancelCount;
        int closeCount;
        StockGattDriver.Peer connectedPeer;

        @Override public void startScan() { startScanCount++; }

        @Override public void connect(StockGattDriver.Peer peer) {
            connectCount++;
            connectedPeer = peer;
        }

        @Override public void cancel() { cancelCount++; }

        @Override public void close() { closeCount++; }
    }
}
