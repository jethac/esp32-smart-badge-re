package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.List;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.model.ConnectionSnapshot;
import org.junit.Test;

public final class MainUiPresenterTest {
    private static final BadgeState ZERO = state(0, 0);
    private static final BadgeState LOCAL = state(42, 73);

    // Mutation: accept a null host and fail later than construction.
    @Test public void rejectsNullHost() {
        assertThrows(IllegalArgumentException.class, () -> new MainUiPresenter(null, null));
    }

    @Test public void presenterSurfaceHasNoCreditMutationPort() throws Exception {
        for (java.lang.reflect.Method method : MainUiPresenter.class.getDeclaredMethods()) {
            assertFalse(method.toString(),
                    method.getName().toLowerCase().contains("credit"));
        }
        java.lang.reflect.Method decoder = MainUiPresenter.class.getDeclaredMethod(
                "decodeRestoredState", boolean.class, Object.class,
                boolean.class, Object.class);
        assertTrue(java.lang.reflect.Modifier.isStatic(decoder.getModifiers()));
        assertEquals(BadgeState.class, decoder.getReturnType());
    }

    // Mutation: change the cold-start state or omit the initial render.
    @Test public void coldStartRendersExactDefaultsOnce() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, null);
        assertEquals(1, host.renders.size());
        assertView(host.last(), 0, 0, MainUiPresenter.StatusKind.SERVICE_CONNECTING,
                MainUiPresenter.GuidanceKind.WAIT_FOR_SERVICE,
                MainUiPresenter.ProblemKind.NONE);
        assertEquals(1727L, p.currentState().creditCents());
    }

    // Mutation: ignore restored sliders or allow the fixed credit to vary.
    @Test public void restoredConstructionUsesExactState() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, LOCAL);
        assertEquals(LOCAL, p.currentState());
        assertEquals(42, host.last().dayPercent());
        assertEquals(73, host.last().weekPercent());
        assertEquals(1727L, host.last().creditCents());
    }

    // Mutation: coerce missing, null, wrong-type, mixed, or out-of-range Bundle values.
    @Test public void strictRestoreDecoderRejectsMalformedValuesWithoutAHost() {
        Object[][] bad = {{false, 1, true, 2}, {true, 1, false, 2}, {false, null, false, null},
                {true, null, true, 2}, {true, 1, true, null}, {true, "1", true, 2},
                {true, 1, true, "2"}, {true, 1L, true, 2}, {true, 1, true, 2L},
                {true, -1, true, 2}, {true, 1, true, -1}, {true, 101, true, 2},
                {true, 1, true, 101}};
        for (Object[] row : bad) {
            assertNull(MainUiPresenter.decodeRestoredState((Boolean) row[0], row[1],
                    (Boolean) row[2], row[3]));
        }
        assertEquals(state(0, 100),
                MainUiPresenter.decodeRestoredState(true, 0, true, 100));
        assertEquals(state(100, 0),
                MainUiPresenter.decodeRestoredState(true, 100, true, 0));
    }

    // Mutation: publish equal ViewState values or give them identity equality.
    @Test public void viewStateIsImmutableValueAndEqualRenderIsSuppressed() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, LOCAL);
        MainUiPresenter.ViewState before = p.viewState();
        p.onEnvironment(environment(true, true, true, true, false));
        MainUiPresenter.ViewState after = p.viewState();
        int count = host.renders.size();
        p.onEnvironment(environment(true, true, true, true, false));
        assertNotSame(before, after);
        assertNotEquals(before, after);
        assertEquals(after, p.viewState());
        assertEquals(after.hashCode(), p.viewState().hashCode());
        assertEquals(count, host.renders.size());
    }

    // Mutation: publish untouched default 0/0 over a surviving service state.
    @Test public void firstBindAdoptsServiceStateOnlyWhenLocalIsNotAuthoritative() {
        Host coldHost = new Host();
        MainUiPresenter cold = new MainUiPresenter(coldHost, null);
        BadgeState service = state(21, 87);
        cold.onServiceBound(disabled(service, true));
        assertEquals(service, cold.currentState());
        assertEquals(0, coldHost.published.size());

        Host restoredHost = new Host();
        MainUiPresenter restored = new MainUiPresenter(restoredHost, LOCAL);
        restored.onServiceBound(disabled(ZERO, true));
        assertEquals(LOCAL, restored.currentState());
        assertEquals(list(LOCAL), restoredHost.published);
    }

    // Mutation: publish every unbound edit or let a later snapshot overwrite local sliders.
    @Test public void preBindEditsCoalesceAndLaterSnapshotsNeverOverwrite() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, null);
        p.onDayChanged(31);
        p.onWeekChanged(62);
        assertEquals(0, host.published.size());
        p.onServiceBound(disabled(ZERO, true));
        assertEquals(list(state(31, 62)), host.published);
        p.onSnapshot(disabled(state(5, 6), true));
        assertEquals(state(31, 62), p.currentState());
    }

    // Mutation: clamp illegal percentages, scale integers, or command on equal progress.
    @Test public void sliderValuesAreExactInclusiveIntegersAndRejectOutOfRange() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, null);
        for (int value = 0; value <= 100; value++) {
            p.onDayChanged(value);
            assertEquals(value, p.currentState().dayPercent());
            assertEquals(1727L, p.currentState().creditCents());
        }
        int renders = host.renders.size();
        p.onDayChanged(100);
        assertEquals(renders, host.renders.size());
        assertThrows(IllegalArgumentException.class, () -> p.onDayChanged(-1));
        assertThrows(IllegalArgumentException.class, () -> p.onDayChanged(101));
        assertThrows(IllegalArgumentException.class, () -> p.onWeekChanged(-1));
        assertThrows(IllegalArgumentException.class, () -> p.onWeekChanged(101));
    }

    // Mutation: make a slider edit write immediately or start the foreground service.
    @Test public void boundSlidersOnlyPublishTheLatestSemanticState() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
        host.clearCommands();
        p.onDayChanged(17);
        p.onWeekChanged(29);
        assertEquals(list(state(17, 73), state(17, 29)), host.published);
        assertEquals(0, host.starts);
        assertEquals(0, host.syncs);
        assertEquals(0, host.stops);
    }

    // Mutation: accept a context-invalid/null publish result or revert the edited slider.
    @Test public void publishResultSetFailsClosedAndPreservesTheEdit() {
        for (MainUiPresenter.CommandResult result : results()) {
            Host host = new Host();
            host.publishResult = result;
            MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
            host.clearCommands();
            p.onDayChanged(18);
            assertEquals(18, p.currentState().dayPercent());
            assertEquals(result == MainUiPresenter.CommandResult.ACCEPTED
                            ? MainUiPresenter.ProblemKind.NONE
                            : MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                    p.viewState().localProblem());
        }
    }

    // Mutation: omit or conflate one phase/status/guidance mapping.
    @Test public void everySnapshotPhaseMapsExactly() {
        ConnectionSnapshot[] snapshots = {disabled(LOCAL, false), noDevice(LOCAL), bonding(LOCAL),
                preReady(ConnectionSnapshot.Phase.CONNECTING, LOCAL),
                preReady(ConnectionSnapshot.Phase.DISCOVERING, LOCAL),
                preReady(ConnectionSnapshot.Phase.VALIDATING_BUILD, LOCAL),
                ready(LOCAL, null), retry(LOCAL), terminal(LOCAL)};
        MainUiPresenter.StatusKind[] statuses = {MainUiPresenter.StatusKind.SYNC_OFF,
                MainUiPresenter.StatusKind.NO_DEVICE, MainUiPresenter.StatusKind.BONDING,
                MainUiPresenter.StatusKind.CONNECTING, MainUiPresenter.StatusKind.DISCOVERING,
                MainUiPresenter.StatusKind.VALIDATING_BUILD, MainUiPresenter.StatusKind.READY,
                MainUiPresenter.StatusKind.RETRYING, MainUiPresenter.StatusKind.ERROR};
        MainUiPresenter.GuidanceKind[] guides = {MainUiPresenter.GuidanceKind.CHOOSE_BADGE,
                MainUiPresenter.GuidanceKind.CHOOSE_BADGE,
                MainUiPresenter.GuidanceKind.HOLD_SYNC_PAIR,
                MainUiPresenter.GuidanceKind.WAIT_FOR_CONNECTION,
                MainUiPresenter.GuidanceKind.WAIT_FOR_CONNECTION,
                MainUiPresenter.GuidanceKind.WAIT_FOR_CONNECTION,
                MainUiPresenter.GuidanceKind.ADJUST_AND_SYNC,
                MainUiPresenter.GuidanceKind.RETRYING_AUTOMATICALLY,
                MainUiPresenter.GuidanceKind.STOP_FIX_AND_RETRY};
        for (int i = 0; i < snapshots.length; i++) {
            Host host = new Host();
            MainUiPresenter p = bound(host, LOCAL, snapshots[i]);
            assertEquals(statuses[i], p.viewState().statusKind());
            assertEquals(guides[i], p.viewState().guidanceKind());
        }
    }

    // Mutation: conflate normal binding/detach with actual bind failure or erase selection.
    @Test public void bindingAndFailureAreDistinctAndRetainRealSnapshot() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
        p.onServiceUnbound();
        assertView(p.viewState(), 42, 73, MainUiPresenter.StatusKind.SERVICE_CONNECTING,
                MainUiPresenter.GuidanceKind.WAIT_FOR_SERVICE,
                MainUiPresenter.ProblemKind.NONE);
        assertEquals("AA:BB:CC:DD:EE:FF", p.viewState().selectedDeviceAddress());
        p.onServiceBindFailed();
        assertEquals(MainUiPresenter.StatusKind.SERVICE_UNAVAILABLE, p.viewState().statusKind());
        assertEquals(MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                p.viewState().localProblem());
        p.onServiceBound(disabled(LOCAL, true));
        assertEquals(MainUiPresenter.ProblemKind.NONE, p.viewState().localProblem());
    }

    // Mutation: copy partial metadata or compare acknowledgment against snapshot state.
    @Test public void metadataAndAcknowledgmentAreCopiedAgainstCurrentSliders() {
        Host host = new Host();
        ConnectionSnapshot snapshot = ready(LOCAL, LOCAL);
        MainUiPresenter p = bound(host, LOCAL, snapshot);
        assertEquals("E87", p.viewState().selectedDeviceName());
        assertEquals("AA:BB:CC:DD:EE:FF", p.viewState().selectedDeviceAddress());
        assertTrue(p.viewState().bonded());
        assertSame(snapshot.buildInfo(), p.viewState().buildInfo());
        assertEquals(Integer.valueOf(64), p.viewState().batteryPercent());
        assertEquals(LOCAL, p.viewState().lastAcknowledgedState());
        assertTrue(p.viewState().currentStateAcknowledged());
        p.onDayChanged(43);
        assertFalse(p.viewState().currentStateAcknowledged());
        assertEquals(LOCAL, p.viewState().lastAcknowledgedState());
    }

    // Mutation: turn notification denial into a blocking ProblemKind.
    @Test public void notificationWarningIsIndependentAndNonBlocking() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, ready(LOCAL, null));
        host.clearCommands();
        p.onEnvironment(environment(true, true, false, true, false));
        assertTrue(p.viewState().notificationPermissionWarning());
        assertEquals(MainUiPresenter.ProblemKind.NONE, p.viewState().localProblem());
        assertTrue(p.viewState().syncButtonEnabled());
        p.onSyncPressed();
        assertEquals("publish,sync", host.order.toString());

        Host findHost = new Host();
        MainUiPresenter find = bound(findHost, LOCAL, disabled(LOCAL, false));
        findHost.clearCommands();
        find.onEnvironment(environment(true, true, false, true, false));
        find.onChooseBadgePressed();
        assertEquals(1, findHost.scans);
        assertEquals(0, findHost.permissions);
    }

    // Mutation: accept an undocumented scanner failure kind.
    @Test public void scannerProblemsAreAnExactValidatedSet() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, LOCAL);
        host.clearCommands();
        MainUiPresenter.ProblemKind[] valid = {MainUiPresenter.ProblemKind.BLUETOOTH_PERMISSION_REQUIRED,
                MainUiPresenter.ProblemKind.BLUETOOTH_OFF, MainUiPresenter.ProblemKind.SCAN_FAILED};
        for (MainUiPresenter.ProblemKind problem : valid) {
            p.onScanFailed(problem);
            assertEquals(problem, p.viewState().localProblem());
            assertEquals(0, host.commandCount());
        }
        assertThrows(IllegalArgumentException.class,
                () -> p.onScanFailed(MainUiPresenter.ProblemKind.NONE));
        assertThrows(IllegalArgumentException.class, () -> p.onScanFailed(null));
        assertEquals(0, host.commandCount());
    }

    // Mutation: enable Find while detached/scanning or cross a permission/Bluetooth gate.
    @Test public void findEnablementAndCommandGatesAreExact() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, LOCAL);
        assertFalse(p.viewState().chooseBadgeButtonEnabled());
        p.onServiceBound(disabled(LOCAL, false));
        assertTrue(p.viewState().chooseBadgeButtonEnabled());
        p.onEnvironment(environment(true, true, true, true, true));
        assertFalse(p.viewState().chooseBadgeButtonEnabled());
        p.onChooseBadgePressed();
        assertEquals(0, host.scans);
        p.onEnvironment(environment(false, true, true, true, false));
        p.onChooseBadgePressed();
        assertEquals(1, host.permissions);
        assertEquals(0, host.scans);
        p.onEnvironment(environment(true, true, true, false, false));
        p.onChooseBadgePressed();
        assertEquals(MainUiPresenter.ProblemKind.BLUETOOTH_OFF, p.viewState().localProblem());
        assertEquals(0, host.scans);
        p.onEnvironment(environment(true, true, true, true, false));
        p.onChooseBadgePressed();
        assertEquals(1, host.scans);
    }

    // Mutation: enable primary/stop in a forbidden phase or derive its label from phase.
    @Test public void buttonEnablementAndPrimaryKindFollowExactRules() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, false));
        assertFalse(p.viewState().syncButtonEnabled());
        assertFalse(p.viewState().stopButtonEnabled());
        p.onSnapshot(disabled(LOCAL, true));
        assertTrue(p.viewState().syncButtonEnabled());
        assertEquals(MainUiPresenter.SyncButtonKind.START_SYNC, p.viewState().syncButtonKind());
        p.onSnapshot(bonding(LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        p.onSnapshot(preReady(ConnectionSnapshot.Phase.CONNECTING, LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        assertTrue(p.viewState().stopButtonEnabled());
        assertEquals(MainUiPresenter.SyncButtonKind.SYNC_NOW, p.viewState().syncButtonKind());
        p.onSnapshot(preReady(ConnectionSnapshot.Phase.DISCOVERING, LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        p.onSnapshot(preReady(ConnectionSnapshot.Phase.VALIDATING_BUILD, LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        p.onSnapshot(retry(LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        p.onSnapshot(noDevice(LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        p.onSnapshot(ready(LOCAL, null));
        assertTrue(p.viewState().syncButtonEnabled());
        p.onSnapshot(terminal(LOCAL));
        assertFalse(p.viewState().syncButtonEnabled());
        assertTrue(p.viewState().stopButtonEnabled());
    }

    // Mutation: DISABLED Start also calls syncNow, reverses order, or accepts a rapid second tap.
    @Test public void disabledSyncPublishesThenStartsExactlyOnce() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
        host.clearCommands();
        p.onSyncPressed();
        p.onSyncPressed();
        assertEquals(list(LOCAL), host.published);
        assertEquals(1, host.starts);
        assertEquals(0, host.syncs);
        assertEquals("publish,start", host.order.toString());
        assertFalse(p.viewState().syncButtonEnabled());
    }

    // Mutation: READY Sync restarts foreground lifetime instead of one acknowledged write.
    @Test public void readySyncPublishesThenWritesExactlyOnce() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, ready(LOCAL, null));
        host.clearCommands();
        p.onSyncPressed();
        assertEquals(list(LOCAL), host.published);
        assertEquals(0, host.starts);
        assertEquals(1, host.syncs);
        assertEquals("publish,sync", host.order.toString());
    }

    // Mutation: continue after a rejected publish into start/sync.
    @Test public void nonAcceptedSyncPublishStopsTheSequence() {
        for (MainUiPresenter.CommandResult result : results()) {
            if (result == MainUiPresenter.CommandResult.ACCEPTED) continue;
            Host host = new Host();
            host.publishResult = result;
            MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
            host.clearCommands();
            p.onSyncPressed();
            assertEquals(0, host.starts);
            assertEquals(0, host.syncs);
            assertEquals(MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                    p.viewState().localProblem());

            Host readyHost = new Host();
            readyHost.publishResult = result;
            MainUiPresenter readyPresenter = bound(
                    readyHost, LOCAL, ready(LOCAL, null));
            readyHost.clearCommands();
            readyPresenter.onSyncPressed();
            assertEquals(0, readyHost.starts);
            assertEquals(0, readyHost.syncs);
            assertEquals(MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                    readyPresenter.viewState().localProblem());
        }
    }

    @Test public void readySyncResultSetIsExhaustiveAndFailClosed() {
        for (MainUiPresenter.CommandResult result : results()) {
            Host host = new Host();
            host.syncResult = result;
            MainUiPresenter p = bound(host, LOCAL, ready(LOCAL, null));
            host.clearCommands();
            p.onSyncPressed();
            assertEquals(1, host.syncs);
            assertEquals(0, host.starts);
            assertEquals(result == MainUiPresenter.CommandResult.ACCEPTED
                            ? MainUiPresenter.ProblemKind.NONE
                            : MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                    p.viewState().localProblem());
        }
    }

    // Mutation: accept/mis-map an invalid/null foreground start result or retain pending on failure.
    @Test public void foregroundStartResultSetIsExhaustiveAndFailClosed() {
        for (MainUiPresenter.CommandResult result : results()) {
            Host host = new Host();
            host.startResult = result;
            MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
            host.clearCommands();
            p.onSyncPressed();
            MainUiPresenter.ProblemKind expected;
            if (result == MainUiPresenter.CommandResult.ACCEPTED) {
                expected = MainUiPresenter.ProblemKind.NONE;
                assertFalse(p.viewState().syncButtonEnabled());
            } else if (result == MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED) {
                expected = MainUiPresenter.ProblemKind.BLUETOOTH_PERMISSION_REQUIRED;
                assertTrue(p.viewState().syncButtonEnabled());
            } else if (result == MainUiPresenter.CommandResult.SYNC_START_FAILED) {
                expected = MainUiPresenter.ProblemKind.SYNC_START_FAILED;
                assertTrue(p.viewState().syncButtonEnabled());
            } else {
                expected = MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE;
                assertTrue(p.viewState().syncButtonEnabled());
            }
            assertEquals(expected, p.viewState().localProblem());
        }
    }

    // Mutation: retain startPending across ordinary unbind and disable same-state rebind forever.
    @Test public void normalUnbindClearsPendingAndSameStateRebindNeedsNoCommand() {
        Host host = new Host();
        ConnectionSnapshot snapshot = disabled(LOCAL, true);
        MainUiPresenter p = bound(host, LOCAL, snapshot);
        host.clearCommands();
        p.onSyncPressed();
        assertFalse(p.viewState().syncButtonEnabled());
        p.onServiceUnbound();
        host.clearCommands();
        p.onServiceBound(snapshot);
        assertTrue(p.viewState().syncButtonEnabled());
        assertEquals(0, host.commandCount());
    }

    // Mutation: let missing nearby permission/Bluetooth cross Sync preflight.
    @Test public void syncPrerequisitesBlockBeforePublishOrServiceCommand() {
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
        host.clearCommands();
        p.onEnvironment(environment(false, true, true, true, false));
        p.onSyncPressed();
        assertEquals(1, host.permissions);
        assertEquals(0, host.published.size());
        p.onEnvironment(environment(true, true, true, false, false));
        p.onSyncPressed();
        assertEquals(0, host.published.size());
        assertEquals(0, host.starts);
    }

    // Mutation: Stop commands while disabled/unbound or accepts an invalid/null result.
    @Test public void stopOnlyCommandsWhileBoundEnabledAndFailsClosed() {
        for (MainUiPresenter.CommandResult result : results()) {
            Host host = new Host();
            host.stopResult = result;
            MainUiPresenter p = bound(host, LOCAL, ready(LOCAL, null));
            host.clearCommands();
            p.onStopPressed();
            assertEquals(1, host.stops);
            assertEquals(result == MainUiPresenter.CommandResult.ACCEPTED
                            ? MainUiPresenter.ProblemKind.NONE
                            : MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                    p.viewState().localProblem());
        }
        Host host = new Host();
        MainUiPresenter p = bound(host, LOCAL, disabled(LOCAL, true));
        host.clearCommands();
        p.onStopPressed();
        p.onServiceUnbound();
        p.onStopPressed();
        assertEquals(0, host.stops);
    }

    // Mutation: candidate failure accepts ACCEPTED/invalid results or issues a Host command.
    @Test public void candidateFailureResultSetIsExactAndCommandFree() {
        for (MainUiPresenter.CommandResult result : results()) {
            Host host = new Host();
            MainUiPresenter p = new MainUiPresenter(host, LOCAL);
            host.clearCommands();
            p.onCommandFailed(result);
            assertEquals(result == MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED
                            ? MainUiPresenter.ProblemKind.BLUETOOTH_PERMISSION_REQUIRED
                            : MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                    p.viewState().localProblem());
            assertEquals(0, host.commandCount());
        }
    }

    // Mutation: erase a retained connection error or clear a stable problem on READY.
    @Test public void recoveryClearsOnlyDocumentedTransientProblems() {
        Host host = new Host();
        ConnectionSnapshot errorSnapshot = terminal(LOCAL);
        MainUiPresenter p = bound(host, LOCAL, errorSnapshot);
        UserVisibleError error = errorSnapshot.error();
        p.onScanFailed(MainUiPresenter.ProblemKind.SCAN_FAILED);
        assertSame(error, p.viewState().connectionError());
        p.onScanEnded(true);
        assertEquals(MainUiPresenter.ProblemKind.NONE, p.viewState().localProblem());
        assertSame(error, p.viewState().connectionError());
        p.onScanEnded(false);
        p.onSnapshot(ready(LOCAL, null));
        assertEquals(MainUiPresenter.ProblemKind.NONE, p.viewState().localProblem());
        p.onCommandFailed(MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE);
        p.onSnapshot(ready(LOCAL, null));
        assertEquals(MainUiPresenter.ProblemKind.SERVICE_UNAVAILABLE,
                p.viewState().localProblem());
    }

    // Mutation: allow any event or validation after close to reach Host/state.
    @Test public void closeIsIdempotentAndEveryLaterEventIsSilent() {
        Host host = new Host();
        MainUiPresenter p = new MainUiPresenter(host, LOCAL);
        p.close();
        p.close();
        host.clearCommands();
        int renders = host.renders.size();
        p.onEnvironment(null);
        p.onServiceBinding(); p.onServiceBound(null); p.onServiceUnbound();
        p.onServiceBindFailed(); p.onSnapshot(null); p.onDayChanged(-1); p.onWeekChanged(101);
        p.onChooseBadgePressed(); p.onSyncPressed(); p.onStopPressed();
        p.onScanEnded(false); p.onScanFailed(null); p.onCommandFailed(null);
        assertEquals(LOCAL, p.currentState());
        assertEquals(renders, host.renders.size());
        assertEquals(0, host.commandCount());
    }

    private static MainUiPresenter bound(Host host, BadgeState restored,
            ConnectionSnapshot snapshot) {
        MainUiPresenter p = new MainUiPresenter(host, restored);
        p.onEnvironment(environment(true, true, true, true, false));
        p.onServiceBound(snapshot);
        return p;
    }

    private static MainUiPresenter.Environment environment(boolean scan, boolean connect,
            boolean notifications, boolean bluetooth, boolean scanning) {
        return new MainUiPresenter.Environment(scan, connect, notifications, bluetooth, scanning);
    }

    private static BadgeState state(int day, int week) {
        return new BadgeState(day, week, 1727L);
    }

    private static ConnectionSnapshot disabled(BadgeState state, boolean selected) {
        return new ConnectionSnapshot(false, ConnectionSnapshot.Phase.DISABLED,
                selected ? "E87" : null, selected ? "AA:BB:CC:DD:EE:FF" : null,
                selected, state, null, null, null, null, null, null);
    }

    private static ConnectionSnapshot noDevice(BadgeState state) {
        return new ConnectionSnapshot(true, ConnectionSnapshot.Phase.NO_DEVICE,
                null, null, false, state, null, null, null, null, null, null);
    }

    private static ConnectionSnapshot bonding(BadgeState state) {
        return new ConnectionSnapshot(true, ConnectionSnapshot.Phase.BONDING,
                "E87", "AA:BB:CC:DD:EE:FF", false, state,
                null, null, null, null, null, null);
    }

    private static ConnectionSnapshot preReady(ConnectionSnapshot.Phase phase, BadgeState state) {
        return new ConnectionSnapshot(true, phase, "E87", "AA:BB:CC:DD:EE:FF", true,
                state, null, null, null, null, null, null);
    }

    private static ConnectionSnapshot ready(BadgeState state, BadgeState acknowledged) {
        return new ConnectionSnapshot(true, ConnectionSnapshot.Phase.READY,
                "E87", "AA:BB:CC:DD:EE:FF", true, state,
                new BuildInfo(7, "E87-JD9855-R1", 1, 2, 3, new byte[16]), 64,
                acknowledged, acknowledged == null ? null : 987L, null, null);
    }

    private static ConnectionSnapshot retry(BadgeState state) {
        return new ConnectionSnapshot(true, ConnectionSnapshot.Phase.RETRY_WAIT,
                "E87", "AA:BB:CC:DD:EE:FF", true, state, null, null,
                null, null, 1501L,
                new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED, 133));
    }

    private static ConnectionSnapshot terminal(BadgeState state) {
        return new ConnectionSnapshot(true, ConnectionSnapshot.Phase.ERROR,
                "E87", "AA:BB:CC:DD:EE:FF", true, state, null, null,
                null, null, null,
                new UserVisibleError(UserVisibleError.Code.UNSUPPORTED_BADGE, 7));
    }

    private static MainUiPresenter.CommandResult[] results() {
        return new MainUiPresenter.CommandResult[] {MainUiPresenter.CommandResult.ACCEPTED,
                MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE,
                MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED,
                MainUiPresenter.CommandResult.SYNC_START_FAILED, null};
    }

    private static List<BadgeState> list(BadgeState... states) {
        List<BadgeState> result = new ArrayList<>();
        for (BadgeState state : states) result.add(state);
        return result;
    }

    private static void assertView(MainUiPresenter.ViewState view, int day, int week,
            MainUiPresenter.StatusKind status, MainUiPresenter.GuidanceKind guidance,
            MainUiPresenter.ProblemKind problem) {
        assertEquals(day, view.dayPercent());
        assertEquals(week, view.weekPercent());
        assertEquals(1727L, view.creditCents());
        assertEquals(status, view.statusKind());
        assertEquals(guidance, view.guidanceKind());
        assertEquals(problem, view.localProblem());
    }

    private static final class Host implements MainUiPresenter.Host {
        final List<MainUiPresenter.ViewState> renders = new ArrayList<>();
        final List<BadgeState> published = new ArrayList<>();
        final StringBuilder order = new StringBuilder();
        MainUiPresenter.CommandResult publishResult = MainUiPresenter.CommandResult.ACCEPTED;
        MainUiPresenter.CommandResult startResult = MainUiPresenter.CommandResult.ACCEPTED;
        MainUiPresenter.CommandResult syncResult = MainUiPresenter.CommandResult.ACCEPTED;
        MainUiPresenter.CommandResult stopResult = MainUiPresenter.CommandResult.ACCEPTED;
        int permissions;
        int scans;
        int starts;
        int syncs;
        int stops;

        @Override public void render(MainUiPresenter.ViewState state) { renders.add(state); }
        @Override public MainUiPresenter.CommandResult publishState(BadgeState state) {
            published.add(new BadgeState(state.dayPercent(), state.weekPercent(), 1727L));
            append("publish");
            return publishResult;
        }
        @Override public void requestBluetoothPermissions() { permissions++; append("permission"); }
        @Override public void beginBadgeScan() { scans++; append("scan"); }
        @Override public MainUiPresenter.CommandResult startForegroundSync() {
            starts++; append("start"); return startResult;
        }
        @Override public MainUiPresenter.CommandResult requestSyncNow() {
            syncs++; append("sync"); return syncResult;
        }
        @Override public MainUiPresenter.CommandResult requestStopSync() {
            stops++; append("stop"); return stopResult;
        }
        MainUiPresenter.ViewState last() { return renders.get(renders.size() - 1); }
        void clearCommands() {
            published.clear(); permissions = 0; scans = 0; starts = 0; syncs = 0; stops = 0;
            order.setLength(0);
        }
        int commandCount() { return published.size() + permissions + scans + starts + syncs + stops; }
        private void append(String value) {
            if (order.length() > 0) order.append(',');
            order.append(value);
        }
    }
}
