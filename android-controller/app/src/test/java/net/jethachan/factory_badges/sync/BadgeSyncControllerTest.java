package net.jethachan.factory_badges.sync;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.ConnectionSnapshot;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BuildInfo;
import org.junit.Test;

public final class BadgeSyncControllerTest {
    // Mutation caught: the controller accepts null dependencies.
    @Test
    public void constructorRejectsNullPorts() {
        ReconnectPolicy policy = new ReconnectPolicy();
        Scheduler scheduler = new Scheduler();
        Foreground foreground = new Foreground();
        Sink sink = new Sink();
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController(null, scheduler, foreground, sink));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController(policy, null, foreground, sink));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController(policy, scheduler, null, sink));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController(policy, scheduler, foreground, null));
    }

    // Mutation caught: the initial state or initial publication differs from the protocol default.
    @Test
    public void initialSnapshotIsExactAndPublishedOnce() {
        Sink sink = new Sink();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), sink);
        ConnectionSnapshot snapshot = controller.snapshot();
        assertFalse(snapshot.syncEnabled());
        assertEquals(ConnectionSnapshot.Phase.DISABLED, snapshot.phase());
        assertEquals(new BadgeState(0, 0, 1727L), snapshot.currentState());
        assertNull(snapshot.selectedDeviceAddress());
        assertEquals(1, sink.values.size());
        assertEquals(snapshot, sink.values.get(0));
    }

    // Mutation caught: enable without selection fails to enter NO_DEVICE or duplicate foreground.
    @Test
    public void enableWithoutSelectionStartsForegroundOnce() {
        Foreground foreground = new Foreground();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), foreground, new Sink());
        controller.setSyncEnabled(true);
        controller.setSyncEnabled(true);
        assertEquals(1, foreground.starts);
        assertEquals(ConnectionSnapshot.Phase.NO_DEVICE, controller.snapshot().phase());
    }

    // Mutation caught: Selection accepts a missing factory or an unusable address.
    @Test
    public void selectionRejectsNullFactoryAndBlankAddress() {
        RecordingFactory factory = new RecordingFactory();
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController.Selection(null, null, true, factory));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController.Selection(null, "  ", true, factory));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncController.Selection(
                        null, "AA:BB:CC:DD:EE:01", true, null));
    }

    // Mutation caught: selecting while disabled eagerly creates or connects a client.
    @Test
    public void selectionWhileDisabledPublishesSelectionWithoutClient() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                "E87", "AA:BB:CC:DD:EE:01", true, factory));

        ConnectionSnapshot snapshot = controller.snapshot();
        assertEquals(ConnectionSnapshot.Phase.DISABLED, snapshot.phase());
        assertEquals("E87", snapshot.selectedDeviceName());
        assertEquals("AA:BB:CC:DD:EE:01", snapshot.selectedDeviceAddress());
        assertTrue(snapshot.bonded());
        assertTrue(factory.clients.isEmpty());
    }

    // Mutation caught: enabling a bonded selection fails to create a fresh connecting client.
    @Test
    public void enablingBondedSelectionCreatesConnectingClient() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                "E87", "AA:BB:CC:DD:EE:02", true, factory));

        controller.setSyncEnabled(true);

        assertEquals(1, factory.clients.size());
        assertEquals(Long.valueOf(1L), factory.epochs.get(0));
        assertEquals(1, factory.clients.get(0).connects);
        assertEquals(ConnectionSnapshot.Phase.CONNECTING, controller.snapshot().phase());
        assertTrue(controller.snapshot().bonded());
    }

    // Mutation caught: an unbonded selection incorrectly claims a completed bond.
    @Test
    public void enablingUnbondedSelectionPublishesBonding() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:03", false, factory));

        controller.setSyncEnabled(true);

        assertEquals(ConnectionSnapshot.Phase.BONDING, controller.snapshot().phase());
        assertFalse(controller.snapshot().bonded());
        assertEquals(1, factory.clients.get(0).connects);
    }

    // Mutation caught: READY or a semantic write occurs before a validated onConnected callback.
    @Test
    public void semanticConnectedPublishesReadyBeforeMandatoryLatestWrite() {
        List<String> order = new ArrayList<String>();
        RecordingFactory factory = new RecordingFactory(order);
        Sink sink = new Sink(order);
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), sink);
        controller.selectDevice(new BadgeSyncController.Selection(
                "E87", "AA:BB:CC:DD:EE:10", true, factory));
        controller.setCurrentState(new BadgeState(23, 67, 1727L));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        assertTrue(client.writes.isEmpty());

        BuildInfo info = semanticBuild();
        client.emitConnected(info, Integer.valueOf(42));

        ConnectionSnapshot snapshot = controller.snapshot();
        assertEquals(ConnectionSnapshot.Phase.READY, snapshot.phase());
        assertEquals(info, snapshot.buildInfo());
        assertEquals(Integer.valueOf(42), snapshot.batteryPercent());
        assertEquals(1, client.writes.size());
        assertEquals(new BadgeState(23, 67, 1727L), client.writes.get(0));
        assertTrue(order.indexOf("snapshot:READY") < order.indexOf("write"));

        client.emitConnected(info, Integer.valueOf(42));
        assertEquals(1, client.writes.size());
    }

    // Mutation caught: a null or non-semantic build is allowed to write or reconnect.
    @Test
    public void invalidBuildsTerminalizeWithoutWriting() {
        RecordingFactory nullFactory = new RecordingFactory();
        BadgeSyncController nullController = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        nullController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:11", true, nullFactory));
        nullController.setSyncEnabled(true);
        RecordingClient nullClient = nullFactory.clients.get(0);
        nullClient.emitConnected(null, Integer.valueOf(50));
        assertEquals(ConnectionSnapshot.Phase.ERROR, nullController.snapshot().phase());
        assertEquals(UserVisibleError.Code.BUILD_INFO_INVALID,
                nullController.snapshot().error().code());
        assertTrue(nullClient.writes.isEmpty());
        assertEquals(1, nullClient.closes);

        RecordingFactory unsupportedFactory = new RecordingFactory();
        BadgeSyncController unsupportedController = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        unsupportedController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:12", true, unsupportedFactory));
        unsupportedController.setSyncEnabled(true);
        RecordingClient unsupportedClient = unsupportedFactory.clients.get(0);
        unsupportedClient.emitConnected(buildWithCapabilities(0), Integer.valueOf(50));
        assertEquals(ConnectionSnapshot.Phase.ERROR,
                unsupportedController.snapshot().phase());
        assertEquals(UserVisibleError.Code.UNSUPPORTED_BADGE,
                unsupportedController.snapshot().error().code());
        assertTrue(unsupportedClient.writes.isEmpty());
        assertEquals(1, unsupportedClient.closes);
    }

    // Mutation caught: rejected onConnected leaves an already-passed bond false.
    @Test
    public void rejectedConnectedBuildStillInfersBondFromUnbondedSelection() {
        BuildInfo[] reports = new BuildInfo[] {
            null,
            buildWithCapabilities(0)
        };
        UserVisibleError.Code[] expectedCodes =
                new UserVisibleError.Code[] {
                    UserVisibleError.Code.BUILD_INFO_INVALID,
                    UserVisibleError.Code.UNSUPPORTED_BADGE
                };
        for (int index = 0; index < reports.length; index++) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:55", false, factory));
            controller.setSyncEnabled(true);
            RecordingClient client = factory.clients.get(0);

            client.emitConnected(reports[index], Integer.valueOf(50));

            assertEquals(ConnectionSnapshot.Phase.ERROR,
                    controller.snapshot().phase());
            assertTrue(controller.snapshot().bonded());
            assertEquals(expectedCodes[index],
                    controller.snapshot().error().code());
            assertNull(controller.snapshot().buildInfo());
            assertNull(controller.snapshot().batteryPercent());
            assertTrue(client.writes.isEmpty());
            assertEquals(1, client.disconnects);
            assertEquals(1, client.closes);
            assertTrue(scheduler.tasks.isEmpty());
        }
    }

    // Mutation caught: explicit Sync queues more than one stale-state follow-up write.
    @Test
    public void explicitSyncCoalescesOnePendingLatestState() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:13", true, factory));
        controller.setCurrentState(new BadgeState(10, 20, 1727L));
        controller.syncNow();
        controller.syncNow();
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        client.emitConnected(semanticBuild(), Integer.valueOf(100));
        assertEquals(1, client.writes.size());
        assertEquals(new BadgeState(10, 20, 1727L), client.writes.get(0));
        client.emitAcknowledged(new BadgeState(10, 20, 1727L), 17L);

        controller.setCurrentState(new BadgeState(30, 40, 1727L));
        assertEquals(1, client.writes.size());
        controller.syncNow();
        controller.syncNow();
        controller.syncNow();
        assertEquals(2, client.writes.size());
        assertEquals(new BadgeState(30, 40, 1727L), client.writes.get(1));

        controller.setCurrentState(new BadgeState(70, 80, 1727L));
        client.emitAcknowledged(new BadgeState(30, 40, 1727L), 123L);

        assertEquals(3, client.writes.size());
        assertEquals(new BadgeState(70, 80, 1727L), client.writes.get(2));
        assertEquals(new BadgeState(30, 40, 1727L),
                controller.snapshot().lastAcknowledgedState());
        assertEquals(Long.valueOf(123L),
                controller.snapshot().lastAcknowledgedElapsedMs());
    }

    // Mutation caught: an out-of-range optional battery is retained in READY.
    @Test
    public void connectedNormalizesInvalidBatteryToAbsent() {
        int[] invalidValues = new int[] {-1, 101};
        for (int invalidValue : invalidValues) {
            RecordingFactory factory = new RecordingFactory();
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), new Scheduler(),
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:14", true, factory));
            controller.setSyncEnabled(true);
            factory.clients.get(0).emitConnected(
                    semanticBuild(), Integer.valueOf(invalidValue));
            assertEquals(ConnectionSnapshot.Phase.READY,
                    controller.snapshot().phase());
            assertEquals(semanticBuild(), controller.snapshot().buildInfo());
            assertNull(controller.snapshot().batteryPercent());
        }
    }

    // Mutation caught: raw status 5 is misclassified as terminal link security.
    @Test
    public void rawDisconnectFiveSchedulesZeroThenCreatesFreshClient() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:20", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient failed = factory.clients.get(0);

        failed.emitDisconnected(5);

        assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                controller.snapshot().phase());
        assertEquals(UserVisibleError.Code.CONNECT_FAILED,
                controller.snapshot().error().code());
        assertEquals(5, controller.snapshot().error().gattStatus());
        assertEquals(Long.valueOf(0L), controller.snapshot().nextReconnectDelayMs());
        assertEquals(1, failed.disconnects);
        assertEquals(1, failed.closes);
        assertEquals(1, scheduler.tasks.size());
        assertEquals(1, factory.clients.size());

        scheduler.runNext();

        assertEquals(2, factory.clients.size());
        assertEquals(Long.valueOf(2L), factory.epochs.get(1));
        assertTrue(factory.clients.get(1) != failed);
        assertEquals(ConnectionSnapshot.Phase.CONNECTING,
                controller.snapshot().phase());
    }

    // Mutation caught: retry backoff resets or consumes a delay more than once per loss.
    @Test
    public void retryBackoffIsExactAndReadyResetsIt() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:21", true, factory));
        controller.setSyncEnabled(true);
        long[] expected = new long[] {
            0L, 1000L, 2000L, 4000L, 8000L, 15000L, 15000L
        };

        for (int index = 0; index < expected.length; index++) {
            RecordingClient current = factory.clients.get(factory.clients.size() - 1);
            current.emitDisconnected(133);
            assertEquals(Long.valueOf(expected[index]),
                    controller.snapshot().nextReconnectDelayMs());
            scheduler.runNext();
        }

        RecordingClient ready = factory.clients.get(factory.clients.size() - 1);
        ready.emitConnected(semanticBuild(), Integer.valueOf(0));
        assertEquals(ConnectionSnapshot.Phase.READY, controller.snapshot().phase());
        ready.emitDisconnected(15);
        assertEquals(Long.valueOf(0L), controller.snapshot().nextReconnectDelayMs());
    }

    // Mutation caught: explicit LINK_SECURITY_FAILED or BOND_LOST starts reconnecting.
    @Test
    public void explicitTerminalErrorsCloseWithoutRetry() {
        UserVisibleError.Code[] codes = new UserVisibleError.Code[] {
            UserVisibleError.Code.LINK_SECURITY_FAILED,
            UserVisibleError.Code.BOND_LOST,
            UserVisibleError.Code.BUILD_INFO_INVALID,
            UserVisibleError.Code.UNSUPPORTED_BADGE
        };
        for (int index = 0; index < codes.length; index++) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:22", true, factory));
            controller.setSyncEnabled(true);
            RecordingClient client = factory.clients.get(0);

            client.emitError(new UserVisibleError(codes[index]));

            assertEquals(ConnectionSnapshot.Phase.ERROR, controller.snapshot().phase());
            assertEquals(codes[index], controller.snapshot().error().code());
            assertEquals(1, client.closes);
            assertTrue(scheduler.tasks.isEmpty());
        }
    }

    // Mutation caught: disabling fails to cancel and gate an already queued retry.
    @Test
    public void disableCancelsRetryAndHostileStaleTimerIsSilent() {
        Scheduler scheduler = new Scheduler();
        Foreground foreground = new Foreground();
        RecordingFactory factory = new RecordingFactory();
        Sink sink = new Sink();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, foreground, sink);
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:23", true, factory));
        controller.setSyncEnabled(true);
        factory.clients.get(0).emitDisconnected(19);
        Scheduler.Task retry = scheduler.tasks.get(0);

        controller.setSyncEnabled(false);
        ConnectionSnapshot disabled = controller.snapshot();
        int publicationCount = sink.values.size();
        scheduler.runIgnoringCancellation(retry);

        assertTrue(retry.canceled);
        assertSame(disabled, controller.snapshot());
        assertEquals(publicationCount, sink.values.size());
        assertEquals(1, factory.clients.size());
        assertEquals(1, foreground.stops);
        assertNull(disabled.nextReconnectDelayMs());
        assertNull(disabled.error());
    }

    // Mutation caught: a rejected semantic write remains READY instead of reconnecting.
    @Test
    public void rejectedWriteSchedulesStateWriteFailureRetry() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:24", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        client.acceptWrite = false;

        client.emitConnected(semanticBuild(), Integer.valueOf(33));

        assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                controller.snapshot().phase());
        assertEquals(UserVisibleError.Code.STATE_WRITE_FAILED,
                controller.snapshot().error().code());
        assertEquals(Long.valueOf(0L), controller.snapshot().nextReconnectDelayMs());
        assertEquals(1, client.disconnects);
        assertEquals(1, client.closes);
    }

    // Mutation caught: an acknowledgment from the wrong epoch/source/state/time is accepted.
    @Test
    public void onlyExactCurrentInFlightAcknowledgmentIsAccepted() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:25", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        BadgeState sent = new BadgeState(0, 0, 1727L);
        client.emitConnected(semanticBuild(), null);
        RecordingClient wrong = new RecordingClient(
                client.epoch, client.events, new ArrayList<String>());

        client.events.onStateWriteAcknowledged(
                client.epoch + 1L, client, sent, 1L);
        client.events.onStateWriteAcknowledged(
                client.epoch, wrong, sent, 1L);
        client.emitAcknowledged(new BadgeState(1, 0, 1727L), 1L);
        client.emitAcknowledged(sent, -1L);
        assertNull(controller.snapshot().lastAcknowledgedState());

        client.emitAcknowledged(sent, 77L);
        assertEquals(sent, controller.snapshot().lastAcknowledgedState());
        assertEquals(Long.valueOf(77L),
                controller.snapshot().lastAcknowledgedElapsedMs());
        int writeCount = client.writes.size();
        client.emitAcknowledged(sent, 88L);
        assertEquals(Long.valueOf(77L),
                controller.snapshot().lastAcknowledgedElapsedMs());
        assertEquals(writeCount, client.writes.size());
    }
    // Mutation caught: acknowledgment records the sent object instead of callback state.
    @Test
    public void acknowledgmentRecordsTheEqualCallbackStateObject() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:26", true, factory));
        BadgeState sent = new BadgeState(7, 8, 1727L);
        controller.setCurrentState(sent);
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        client.emitConnected(semanticBuild(), null);

        BadgeState callbackState = new BadgeState(7, 8, 1727L);
        assertTrue(callbackState != sent);
        assertEquals(sent, callbackState);
        client.emitAcknowledged(callbackState, 91L);

        assertSame(callbackState,
                controller.snapshot().lastAcknowledgedState());
        assertEquals(Long.valueOf(91L),
                controller.snapshot().lastAcknowledgedElapsedMs());
    }

    // Mutation caught: bonded adapter failures reset backoff or reuse a failed attempt.
    @Test
    public void bondedFactoryAndConnectFailuresKeepFreshBackoffSequence() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        factory.enqueue(RecordingFactory.NULL_CLIENT);
        factory.enqueue(RecordingFactory.FACTORY_THROW);
        factory.enqueue(RecordingFactory.CONNECT_THROW);
        factory.enqueue(RecordingFactory.CLIENT);
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:30", true, factory));

        controller.setSyncEnabled(true);
        assertEquals(Long.valueOf(0L), controller.snapshot().nextReconnectDelayMs());
        scheduler.runNext();
        assertEquals(Long.valueOf(1000L), controller.snapshot().nextReconnectDelayMs());
        scheduler.runNext();
        assertEquals(Long.valueOf(2000L), controller.snapshot().nextReconnectDelayMs());
        assertEquals(1, factory.clients.get(0).disconnects);
        assertEquals(1, factory.clients.get(0).closes);
        scheduler.runNext();

        assertEquals(ConnectionSnapshot.Phase.CONNECTING,
                controller.snapshot().phase());
        assertEquals(4, factory.epochs.size());
        assertEquals(Long.valueOf(1L), factory.epochs.get(0));
        assertEquals(Long.valueOf(2L), factory.epochs.get(1));
        assertEquals(Long.valueOf(3L), factory.epochs.get(2));
        assertEquals(Long.valueOf(4L), factory.epochs.get(3));
        assertEquals(2, factory.clients.size());
    }

    // Mutation caught: an unbonded factory/connect failure is incorrectly retried.
    @Test
    public void unbondedAdapterFailuresTerminalizeAsBondStartFailed() {
        int[] outcomes = new int[] {
            RecordingFactory.NULL_CLIENT,
            RecordingFactory.FACTORY_THROW,
            RecordingFactory.CONNECT_THROW
        };
        for (int outcome : outcomes) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            factory.enqueue(outcome);
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:31", false, factory));

            controller.setSyncEnabled(true);

            assertEquals(ConnectionSnapshot.Phase.ERROR, controller.snapshot().phase());
            assertEquals(UserVisibleError.Code.BOND_START_FAILED,
                    controller.snapshot().error().code());
            assertTrue(scheduler.tasks.isEmpty());
            if (outcome == RecordingFactory.CONNECT_THROW) {
                assertEquals(1, factory.clients.get(0).closes);
            } else {
                assertTrue(factory.clients.isEmpty());
            }
        }
    }

    // Mutation caught: retry-time factory classification reuses immutable Selection.bonded.
    @Test
    public void retryFactoryFailureUsesCurrentInferredBond() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        factory.enqueue(RecordingFactory.CLIENT);
        factory.enqueue(RecordingFactory.NULL_CLIENT);
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:32", false, factory));
        controller.setSyncEnabled(true);

        factory.clients.get(0).emitError(new UserVisibleError(
                UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
        assertEquals(Long.valueOf(0L), controller.snapshot().nextReconnectDelayMs());
        scheduler.runNext();

        assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                controller.snapshot().phase());
        assertEquals(UserVisibleError.Code.CONNECT_FAILED,
                controller.snapshot().error().code());
        assertEquals(Long.valueOf(1000L), controller.snapshot().nextReconnectDelayMs());
    }

    // Mutation caught: inferred bond is ignored for retry factory/connect exceptions.
    @Test
    public void retryThrowsUseCurrentInferredBondAfterUnbondedSelection() {
        int[] retryFailures = new int[] {
            RecordingFactory.FACTORY_THROW,
            RecordingFactory.CONNECT_THROW
        };
        for (int retryFailure : retryFailures) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            factory.enqueue(RecordingFactory.CLIENT);
            factory.enqueue(retryFailure);
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:57", false, factory));
            controller.setSyncEnabled(true);
            factory.clients.get(0).emitError(new UserVisibleError(
                    UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
            assertTrue(controller.snapshot().bonded());
            assertEquals(Long.valueOf(0L),
                    controller.snapshot().nextReconnectDelayMs());

            scheduler.runNext();

            assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                    controller.snapshot().phase());
            assertTrue(controller.snapshot().bonded());
            assertEquals(UserVisibleError.Code.CONNECT_FAILED,
                    controller.snapshot().error().code());
            assertEquals(Long.valueOf(1000L),
                    controller.snapshot().nextReconnectDelayMs());
            assertEquals(2, factory.epochs.size());
            if (retryFailure == RecordingFactory.FACTORY_THROW) {
                assertEquals(1, factory.clients.size());
            } else {
                assertEquals(2, factory.clients.size());
                assertEquals(1, factory.clients.get(1).disconnects);
                assertEquals(1, factory.clients.get(1).closes);
            }
        }
    }

    // Mutation caught: create-time callbacks or reentrant connect results are overwritten.
    @Test
    public void factoryCallbackIsIgnoredAndConnectCallbacksWinReentrantly() {
        RecordingFactory createFactory = new RecordingFactory();
        createFactory.enqueue(RecordingFactory.CREATE_DISCONNECT);
        Scheduler createScheduler = new Scheduler();
        BadgeSyncController createController = new BadgeSyncController(
                new ReconnectPolicy(), createScheduler, new Foreground(), new Sink());
        createController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:33", true, createFactory));
        createController.setSyncEnabled(true);
        assertEquals(ConnectionSnapshot.Phase.CONNECTING,
                createController.snapshot().phase());
        assertTrue(createScheduler.tasks.isEmpty());

        RecordingFactory connectedFactory = new RecordingFactory();
        connectedFactory.enqueue(RecordingFactory.CONNECT_CONNECTED);
        BadgeSyncController connectedController = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        connectedController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:34", true, connectedFactory));
        connectedController.setSyncEnabled(true);
        assertEquals(ConnectionSnapshot.Phase.READY,
                connectedController.snapshot().phase());
        assertEquals(1, connectedFactory.clients.get(0).writes.size());

        int[] outcomes = new int[] {
            RecordingFactory.CONNECT_RETRY_ERROR,
            RecordingFactory.CONNECT_DISCONNECTED,
            RecordingFactory.CONNECT_TERMINAL_ERROR
        };
        ConnectionSnapshot.Phase[] phases = new ConnectionSnapshot.Phase[] {
            ConnectionSnapshot.Phase.RETRY_WAIT,
            ConnectionSnapshot.Phase.RETRY_WAIT,
            ConnectionSnapshot.Phase.ERROR
        };
        for (int index = 0; index < outcomes.length; index++) {
            RecordingFactory factory = new RecordingFactory();
            factory.enqueue(outcomes[index]);
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:35", true, factory));
            controller.setSyncEnabled(true);
            assertEquals(phases[index], controller.snapshot().phase());
            assertEquals(1, factory.clients.get(0).closes);
        }
    }

    // Mutation caught: a RuntimeException from writeState escapes or remains READY.
    @Test
    public void throwingWriteSchedulesStateWriteFailure() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:36", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        client.throwWrite = true;

        client.emitConnected(semanticBuild(), null);

        assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                controller.snapshot().phase());
        assertEquals(UserVisibleError.Code.STATE_WRITE_FAILED,
                controller.snapshot().error().code());
        assertEquals(1, client.closes);
    }

    // Mutation caught: same-address replacement retains old metadata/client/backoff.
    @Test
    public void sameAddressReplacementClosesOldAndClearsMetadata() {
        RecordingFactory firstFactory = new RecordingFactory();
        RecordingFactory replacementFactory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                "old", "AA:BB:CC:DD:EE:40", true, firstFactory));
        controller.setSyncEnabled(true);
        RecordingClient old = firstFactory.clients.get(0);
        old.emitConnected(semanticBuild(), Integer.valueOf(37));
        old.emitAcknowledged(new BadgeState(0, 0, 1727L), 90L);
        BadgeState latest = new BadgeState(73, 19, 1727L);
        controller.setCurrentState(latest);

        controller.selectDevice(new BadgeSyncController.Selection(
                "new", "AA:BB:CC:DD:EE:40", true, replacementFactory));

        assertEquals(1, old.disconnects);
        assertEquals(1, old.closes);
        assertEquals(1, replacementFactory.clients.size());
        assertEquals(Long.valueOf(2L), replacementFactory.epochs.get(0));
        assertEquals(ConnectionSnapshot.Phase.CONNECTING,
                controller.snapshot().phase());
        assertEquals("new", controller.snapshot().selectedDeviceName());
        assertSame(latest, controller.snapshot().currentState());
        assertNull(controller.snapshot().buildInfo());
        assertNull(controller.snapshot().batteryPercent());
        assertNull(controller.snapshot().lastAcknowledgedState());
        assertNull(controller.snapshot().lastAcknowledgedElapsedMs());
        assertNull(controller.snapshot().error());
        assertNull(controller.snapshot().nextReconnectDelayMs());
    }

    // Mutation caught: disable discards retained validated/ack metadata or leaves work active.
    @Test
    public void disableRetainsCompletedMetadataAndClosesActiveAttempt() {
        Foreground foreground = new Foreground();
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), foreground, new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                "E87", "AA:BB:CC:DD:EE:41", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        BuildInfo info = semanticBuild();
        client.emitConnected(info, Integer.valueOf(100));
        BadgeState sent = new BadgeState(0, 0, 1727L);
        client.emitAcknowledged(sent, 44L);

        controller.setSyncEnabled(false);
        controller.setSyncEnabled(false);

        ConnectionSnapshot snapshot = controller.snapshot();
        assertEquals(ConnectionSnapshot.Phase.DISABLED, snapshot.phase());
        assertEquals(info, snapshot.buildInfo());
        assertEquals(Integer.valueOf(100), snapshot.batteryPercent());
        assertEquals(sent, snapshot.lastAcknowledgedState());
        assertEquals(Long.valueOf(44L), snapshot.lastAcknowledgedElapsedMs());
        assertNull(snapshot.error());
        assertNull(snapshot.nextReconnectDelayMs());
        assertEquals(1, client.disconnects);
        assertEquals(1, client.closes);
        assertEquals(1, foreground.stops);
    }

    // Mutation caught: close is non-idempotent or post-close mutators call ports.
    @Test
    public void closeIsIdempotentAndMutatorsRejectWithStableText() {
        Foreground foreground = new Foreground();
        RecordingFactory factory = new RecordingFactory();
        Sink sink = new Sink();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), foreground, sink);
        BadgeSyncController.Selection selection =
                new BadgeSyncController.Selection(
                        null, "AA:BB:CC:DD:EE:42", true, factory);
        controller.selectDevice(selection);
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        client.callbackDuringClose = true;

        controller.close();
        ConnectionSnapshot finalSnapshot = controller.snapshot();
        int publications = sink.values.size();
        controller.close();
        client.emitConnected(semanticBuild(), Integer.valueOf(50));
        client.emitAcknowledged(new BadgeState(0, 0, 1727L), 5L);
        client.emitDisconnected(5);
        client.emitError(new UserVisibleError(
                UserVisibleError.Code.GATT_TIMEOUT));

        assertEquals(ConnectionSnapshot.Phase.DISABLED, finalSnapshot.phase());
        assertSame(finalSnapshot, controller.snapshot());
        assertEquals(1, client.closes);
        assertEquals(1, foreground.stops);
        assertEquals(publications, sink.values.size());
        IllegalStateException selectError = assertThrows(
                IllegalStateException.class,
                () -> controller.selectDevice(selection));
        IllegalStateException stateError = assertThrows(
                IllegalStateException.class,
                () -> controller.setCurrentState(new BadgeState(1, 2, 1727L)));
        IllegalStateException enableError = assertThrows(
                IllegalStateException.class,
                () -> controller.setSyncEnabled(true));
        IllegalStateException syncError = assertThrows(
                IllegalStateException.class, controller::syncNow);
        assertEquals("controller is closed", selectError.getMessage());
        assertEquals("controller is closed", stateError.getMessage());
        assertEquals("controller is closed", enableError.getMessage());
        assertEquals("controller is closed", syncError.getMessage());
        assertEquals(1, factory.clients.size());
    }

    // Mutation caught: disconnect during a write loses the latest desired READY resend.
    @Test
    public void disconnectDuringWriteNextReadySendsLatestOnce() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:43", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient first = factory.clients.get(0);
        first.emitConnected(semanticBuild(), null);
        controller.setCurrentState(new BadgeState(88, 99, 1727L));

        first.emitDisconnected(8);
        scheduler.runNext();
        RecordingClient second = factory.clients.get(1);
        second.emitConnected(semanticBuild(), null);

        assertEquals(1, first.writes.size());
        assertEquals(1, second.writes.size());
        assertEquals(new BadgeState(88, 99, 1727L), second.writes.get(0));
    }

    // Mutation caught: slider changes alone create pending writes or equal Sync cannot resend.
    @Test
    public void stateChangesDoNotQueueButEqualExplicitSyncResends() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:44", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        BadgeState initial = new BadgeState(0, 0, 1727L);
        client.emitConnected(semanticBuild(), null);
        client.emitAcknowledged(initial, 1L);

        BadgeState changed = new BadgeState(12, 34, 1727L);
        controller.setCurrentState(changed);
        assertEquals(1, client.writes.size());
        controller.syncNow();
        assertEquals(2, client.writes.size());
        client.emitAcknowledged(changed, 2L);
        assertEquals(2, client.writes.size());
        controller.syncNow();
        assertEquals(3, client.writes.size());
        assertEquals(changed, client.writes.get(2));
    }

    // Mutation caught: lifecycleGeneration wraps and ordinary work continues.
    @Test
    public void lifecycleGenerationExhaustionFailsClosedPermanently()
            throws Exception {
        Foreground foreground = new Foreground();
        RecordingFactory firstFactory = new RecordingFactory();
        RecordingFactory replacementFactory = new RecordingFactory();
        Sink sink = new Sink();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(), foreground, sink);
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:45", true, firstFactory));
        controller.setSyncEnabled(true);
        RecordingClient active = firstFactory.clients.get(0);
        ConnectionSnapshot before = controller.snapshot();
        int publications = sink.values.size();
        setLongField(controller, "lifecycleGeneration", Long.MAX_VALUE);

        IllegalStateException error = assertThrows(
                IllegalStateException.class,
                () -> controller.selectDevice(new BadgeSyncController.Selection(
                        null, "AA:BB:CC:DD:EE:46", true, replacementFactory)));

        assertEquals("controller generation exhausted", error.getMessage());
        assertEquals(1, active.closes);
        assertEquals(1, foreground.stops);
        assertTrue(replacementFactory.clients.isEmpty());
        assertSame(before, controller.snapshot());
        assertEquals(publications, sink.values.size());
        active.emitConnected(semanticBuild(), null);
        assertSame(before, controller.snapshot());
        IllegalStateException later = assertThrows(
                IllegalStateException.class, controller::syncNow);
        assertEquals("controller generation exhausted", later.getMessage());
    }

    // Mutation caught: clientEpoch wraps on a synchronous or retry attempt.
    @Test
    public void clientEpochExhaustionFailsClosedSyncAndAsync()
            throws Exception {
        Scheduler syncScheduler = new Scheduler();
        Foreground syncForeground = new Foreground();
        RecordingFactory syncFactory = new RecordingFactory();
        Sink syncSink = new Sink();
        BadgeSyncController syncController = new BadgeSyncController(
                new ReconnectPolicy(), syncScheduler,
                syncForeground, syncSink);
        syncController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:47", true, syncFactory));
        ConnectionSnapshot syncBefore = syncController.snapshot();
        int syncPublications = syncSink.values.size();
        setLongField(syncController, "clientEpoch", Long.MAX_VALUE);

        IllegalStateException syncError = assertThrows(
                IllegalStateException.class,
                () -> syncController.setSyncEnabled(true));
        assertEquals("controller generation exhausted", syncError.getMessage());
        assertTrue(syncFactory.epochs.isEmpty());
        assertTrue(syncFactory.clients.isEmpty());
        assertTrue(syncScheduler.tasks.isEmpty());
        assertEquals(0, syncForeground.starts);
        assertEquals(0, syncForeground.stops);
        assertSame(syncBefore, syncController.snapshot());
        assertEquals(syncPublications, syncSink.values.size());

        Scheduler scheduler = new Scheduler();
        Foreground asyncForeground = new Foreground();
        RecordingFactory asyncFactory = new RecordingFactory();
        BadgeSyncController asyncController = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, asyncForeground, new Sink());
        asyncController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:48", true, asyncFactory));
        asyncController.setSyncEnabled(true);
        asyncFactory.clients.get(0).emitDisconnected(7);
        ConnectionSnapshot before = asyncController.snapshot();
        setLongField(asyncController, "clientEpoch", Long.MAX_VALUE);

        scheduler.runNext();

        assertEquals(1, asyncFactory.clients.size());
        assertEquals(1, asyncForeground.stops);
        assertSame(before, asyncController.snapshot());
        IllegalStateException later = assertThrows(
                IllegalStateException.class, asyncController::syncNow);
        assertEquals("controller generation exhausted", later.getMessage());
    }


    // Mutation caught: reentrant write callbacks double-fail or resurrect in-flight work.
    @Test
    public void reentrantWriteAcknowledgmentAndErrorEachWinOnce() {
        Scheduler acknowledgedScheduler = new Scheduler();
        RecordingFactory acknowledgedFactory = new RecordingFactory();
        BadgeSyncController acknowledgedController = new BadgeSyncController(
                new ReconnectPolicy(), acknowledgedScheduler,
                new Foreground(), new Sink());
        acknowledgedController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:49", true, acknowledgedFactory));
        acknowledgedController.setCurrentState(new BadgeState(11, 22, 1727L));
        acknowledgedController.setSyncEnabled(true);
        RecordingClient acknowledgedClient =
                acknowledgedFactory.clients.get(0);
        acknowledgedClient.acknowledgeDuringWrite = true;

        acknowledgedClient.emitConnected(semanticBuild(), null);

        assertEquals(ConnectionSnapshot.Phase.READY,
                acknowledgedController.snapshot().phase());
        assertEquals(new BadgeState(11, 22, 1727L),
                acknowledgedController.snapshot().lastAcknowledgedState());
        assertEquals(Long.valueOf(51L),
                acknowledgedController.snapshot().lastAcknowledgedElapsedMs());
        assertEquals(1, acknowledgedClient.writes.size());
        assertEquals(0, acknowledgedClient.closes);
        assertTrue(acknowledgedScheduler.tasks.isEmpty());

        Scheduler failedScheduler = new Scheduler();
        RecordingFactory failedFactory = new RecordingFactory();
        BadgeSyncController failedController = new BadgeSyncController(
                new ReconnectPolicy(), failedScheduler,
                new Foreground(), new Sink());
        failedController.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:4A", true, failedFactory));
        failedController.setSyncEnabled(true);
        RecordingClient failedClient = failedFactory.clients.get(0);
        failedClient.errorDuringWrite = new UserVisibleError(
                UserVisibleError.Code.GATT_TIMEOUT);
        failedClient.acceptWrite = false;

        failedClient.emitConnected(semanticBuild(), null);

        assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                failedController.snapshot().phase());
        assertEquals(UserVisibleError.Code.GATT_TIMEOUT,
                failedController.snapshot().error().code());
        assertEquals(1, failedClient.writes.size());
        assertEquals(1, failedClient.disconnects);
        assertEquals(1, failedClient.closes);
        assertEquals(1, failedScheduler.tasks.size());
        failedClient.emitDisconnected(133);
        assertEquals(1, failedScheduler.tasks.size());
    }

    // Mutation caught: old, wrong-source, or close-time callbacks alter the new lifecycle.
    @Test
    public void staleWrongSourceAndCloseTimeCallbacksAreSilent() {
        Scheduler scheduler = new Scheduler();
        Foreground foreground = new Foreground();
        List<String> order = new ArrayList<String>();
        Sink sink = new Sink(order);
        RecordingFactory firstFactory = new RecordingFactory(order);
        RecordingFactory secondFactory = new RecordingFactory(order);
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, foreground, sink);
        controller.selectDevice(new BadgeSyncController.Selection(
                "first", "AA:BB:CC:DD:EE:4B", true, firstFactory));
        controller.setSyncEnabled(true);
        RecordingClient oldClient = firstFactory.clients.get(0);
        oldClient.emitConnected(semanticBuild(), Integer.valueOf(10));
        oldClient.emitAcknowledged(new BadgeState(0, 0, 1727L), 3L);
        oldClient.callbackDuringClose = true;
        order.clear();

        controller.selectDevice(new BadgeSyncController.Selection(
                "second", "AA:BB:CC:DD:EE:4C", true, secondFactory));

        assertEquals(4, order.size());
        assertEquals("disconnect", order.get(0));
        assertEquals("close", order.get(1));
        assertEquals("snapshot:CONNECTING", order.get(2));
        assertEquals("connect", order.get(3));
        RecordingClient current = secondFactory.clients.get(0);
        ConnectionSnapshot replacement = controller.snapshot();
        int publications = sink.values.size();
        oldClient.emitConnected(semanticBuild(), Integer.valueOf(99));
        oldClient.emitAcknowledged(new BadgeState(0, 0, 1727L), 4L);
        oldClient.emitDisconnected(5);
        oldClient.emitError(new UserVisibleError(
                UserVisibleError.Code.GATT_TIMEOUT));
        current.events.onConnected(
                current.epoch, oldClient, semanticBuild(), Integer.valueOf(88));
        current.events.onError(
                current.epoch, oldClient, new UserVisibleError(
                        UserVisibleError.Code.LINK_SECURITY_FAILED));

        assertSame(replacement, controller.snapshot());
        assertEquals(publications, sink.values.size());
        assertEquals(1, secondFactory.clients.size());
        assertEquals(0, current.closes);
        assertEquals(1, foreground.starts);
        assertEquals(0, foreground.stops);
        assertTrue(scheduler.tasks.isEmpty());

        current.emitConnected(semanticBuild(), Integer.valueOf(27));
        assertEquals(ConnectionSnapshot.Phase.READY,
                controller.snapshot().phase());
        assertEquals(1, current.writes.size());
        current.callbackDuringClose = true;
        current.emitError(new UserVisibleError(
                UserVisibleError.Code.LINK_SECURITY_FAILED));
        assertEquals(ConnectionSnapshot.Phase.ERROR,
                controller.snapshot().phase());
        assertEquals(UserVisibleError.Code.LINK_SECURITY_FAILED,
                controller.snapshot().error().code());
        assertEquals(1, current.closes);
        assertEquals(1, current.writes.size());
        assertTrue(scheduler.tasks.isEmpty());
    }

    // Mutation caught: replacement or disable fails to reset and gate old backoff.
    @Test
    public void replacementAndDisableResetBackoffToZero() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory firstFactory = new RecordingFactory();
        RecordingFactory replacementFactory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:4D", true, firstFactory));
        controller.setSyncEnabled(true);
        firstFactory.clients.get(0).emitDisconnected(1);
        scheduler.runNext();
        firstFactory.clients.get(1).emitDisconnected(2);
        assertEquals(Long.valueOf(1000L),
                controller.snapshot().nextReconnectDelayMs());
        Scheduler.Task oldRetry = scheduler.tasks.get(1);

        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:4D", true, replacementFactory));

        assertTrue(oldRetry.canceled);
        assertEquals(1, replacementFactory.clients.size());
        scheduler.runIgnoringCancellation(oldRetry);
        assertEquals(1, replacementFactory.clients.size());
        replacementFactory.clients.get(0).emitDisconnected(3);
        assertEquals(Long.valueOf(0L),
                controller.snapshot().nextReconnectDelayMs());

        controller.setSyncEnabled(false);
        assertEquals(ConnectionSnapshot.Phase.DISABLED,
                controller.snapshot().phase());
        assertNull(controller.snapshot().nextReconnectDelayMs());
        assertNull(controller.snapshot().error());
        controller.setSyncEnabled(true);
        assertEquals(2, replacementFactory.clients.size());
        replacementFactory.clients.get(1).emitDisconnected(4);
        assertEquals(Long.valueOf(0L),
                controller.snapshot().nextReconnectDelayMs());
    }


    // Mutation caught: any explicit error uses the wrong retry or bond-inference branch.
    @Test
    public void everyExplicitErrorHasExactRetryAndBondSemantics() {
        UserVisibleError.Code[] codes = new UserVisibleError.Code[] {
            UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING,
            UserVisibleError.Code.BLUETOOTH_DISABLED,
            UserVisibleError.Code.BOND_START_FAILED,
            UserVisibleError.Code.BOND_FAILED,
            UserVisibleError.Code.BOND_LOST,
            UserVisibleError.Code.CONNECT_FAILED,
            UserVisibleError.Code.SERVICE_DISCOVERY_FAILED,
            UserVisibleError.Code.REQUIRED_SERVICE_MISSING,
            UserVisibleError.Code.REQUIRED_CHARACTERISTIC_MISSING,
            UserVisibleError.Code.LINK_SECURITY_FAILED,
            UserVisibleError.Code.BUILD_INFO_INVALID,
            UserVisibleError.Code.UNSUPPORTED_BADGE,
            UserVisibleError.Code.GATT_TIMEOUT,
            UserVisibleError.Code.STATE_WRITE_FAILED
        };
        boolean[] initiallyBonded = new boolean[] {
            false, true, true, true, true, false, false,
            false, false, false, false, false, false, false
        };
        boolean[] expectedBonded = new boolean[] {
            false, true, false, false, false, true, true,
            true, true, true, true, true, true, true
        };
        boolean[] expectedRetry = new boolean[] {
            false, false, false, false, false, true, true,
            false, false, false, false, false, true, true
        };
        assertEquals(UserVisibleError.Code.values().length, codes.length);

        for (int index = 0; index < codes.length; index++) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:4E",
                    initiallyBonded[index], factory));
            controller.setSyncEnabled(true);
            RecordingClient client = factory.clients.get(0);
            UserVisibleError reported =
                    new UserVisibleError(codes[index], 77);

            client.emitError(reported);

            ConnectionSnapshot snapshot = controller.snapshot();
            assertEquals(expectedRetry[index]
                            ? ConnectionSnapshot.Phase.RETRY_WAIT
                            : ConnectionSnapshot.Phase.ERROR,
                    snapshot.phase());
            assertEquals(expectedBonded[index], snapshot.bonded());
            assertSame(reported, snapshot.error());
            assertEquals(expectedRetry[index]
                            ? Long.valueOf(0L) : null,
                    snapshot.nextReconnectDelayMs());
            assertEquals(expectedRetry[index] ? 1 : 0,
                    scheduler.tasks.size());
            assertEquals(1, client.disconnects);
            assertEquals(1, client.closes);

            controller.setSyncEnabled(false);
            assertEquals(ConnectionSnapshot.Phase.DISABLED,
                    controller.snapshot().phase());
            assertNull(controller.snapshot().error());
            assertNull(controller.snapshot().nextReconnectDelayMs());
        }
    }

    // Mutation caught: a publication fabricates phases or violates the exact phase matrix.
    @Test
    public void everyPublishedSnapshotObeysTheControllerPhaseMatrix() {
        Scheduler scheduler = new Scheduler();
        RecordingFactory factory = new RecordingFactory();
        Sink sink = new Sink();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), scheduler, new Foreground(), sink);
        controller.setSyncEnabled(true);
        controller.selectDevice(new BadgeSyncController.Selection(
                "E87", "AA:BB:CC:DD:EE:4F", false, factory));
        factory.clients.get(0).emitError(new UserVisibleError(
                UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
        scheduler.runNext();
        RecordingClient ready = factory.clients.get(1);
        ready.emitConnected(semanticBuild(), Integer.valueOf(0));
        ready.emitAcknowledged(new BadgeState(0, 0, 1727L), 6L);
        controller.setCurrentState(new BadgeState(55, 66, 1727L));
        ready.emitDisconnected(-1);
        scheduler.runNext();
        factory.clients.get(2).emitError(new UserVisibleError(
                UserVisibleError.Code.REQUIRED_SERVICE_MISSING));
        controller.setSyncEnabled(false);

        ConnectionSnapshot.Phase[] expectedPhases =
                new ConnectionSnapshot.Phase[] {
                    ConnectionSnapshot.Phase.DISABLED,
                    ConnectionSnapshot.Phase.NO_DEVICE,
                    ConnectionSnapshot.Phase.BONDING,
                    ConnectionSnapshot.Phase.RETRY_WAIT,
                    ConnectionSnapshot.Phase.CONNECTING,
                    ConnectionSnapshot.Phase.READY,
                    ConnectionSnapshot.Phase.READY,
                    ConnectionSnapshot.Phase.READY,
                    ConnectionSnapshot.Phase.RETRY_WAIT,
                    ConnectionSnapshot.Phase.CONNECTING,
                    ConnectionSnapshot.Phase.ERROR,
                    ConnectionSnapshot.Phase.DISABLED
                };
        assertEquals(expectedPhases.length, sink.values.size());
        for (int index = 0; index < expectedPhases.length; index++) {
            ConnectionSnapshot value = sink.values.get(index);
            assertEquals(expectedPhases[index], value.phase());
            assertControllerSnapshotInvariant(value);
            assertTrue(value.phase()
                    != ConnectionSnapshot.Phase.DISCOVERING);
            assertTrue(value.phase()
                    != ConnectionSnapshot.Phase.VALIDATING_BUILD);
        }
        assertEquals(semanticBuild(), sink.values.get(8).buildInfo());
        assertEquals(Integer.valueOf(0),
                sink.values.get(8).batteryPercent());
        assertNull(sink.values.get(9).buildInfo());
        assertNull(sink.values.get(9).batteryPercent());
    }


    private static void assertControllerSnapshotInvariant(
            ConnectionSnapshot value) {
        assertTrue(value.currentState() != null);
        assertEquals(value.lastAcknowledgedState() == null,
                value.lastAcknowledgedElapsedMs() == null);
        if (value.batteryPercent() != null) {
            assertTrue(value.buildInfo() != null);
            assertTrue(value.batteryPercent().intValue() >= 0);
            assertTrue(value.batteryPercent().intValue() <= 100);
        }

        switch (value.phase()) {
            case DISABLED:
                assertFalse(value.syncEnabled());
                assertNull(value.error());
                assertNull(value.nextReconnectDelayMs());
                return;
            case NO_DEVICE:
                assertTrue(value.syncEnabled());
                assertNull(value.selectedDeviceName());
                assertNull(value.selectedDeviceAddress());
                assertFalse(value.bonded());
                assertNull(value.buildInfo());
                assertNull(value.batteryPercent());
                assertNull(value.error());
                assertNull(value.nextReconnectDelayMs());
                return;
            case BONDING:
                assertTrue(value.syncEnabled());
                assertTrue(value.selectedDeviceAddress() != null);
                assertFalse(value.bonded());
                assertNull(value.buildInfo());
                assertNull(value.batteryPercent());
                assertNull(value.error());
                assertNull(value.nextReconnectDelayMs());
                return;
            case CONNECTING:
            case DISCOVERING:
            case VALIDATING_BUILD:
                assertTrue(value.syncEnabled());
                assertTrue(value.selectedDeviceAddress() != null);
                assertTrue(value.bonded());
                assertNull(value.buildInfo());
                assertNull(value.batteryPercent());
                assertNull(value.error());
                assertNull(value.nextReconnectDelayMs());
                return;
            case READY:
                assertTrue(value.syncEnabled());
                assertTrue(value.selectedDeviceAddress() != null);
                assertTrue(value.bonded());
                assertTrue(value.buildInfo() != null);
                assertNull(value.error());
                assertNull(value.nextReconnectDelayMs());
                return;
            case RETRY_WAIT:
                assertTrue(value.syncEnabled());
                assertTrue(value.selectedDeviceAddress() != null);
                assertTrue(value.bonded());
                assertTrue(value.nextReconnectDelayMs() != null);
                if (value.error() != null) {
                    assertTrue(value.error().retryable());
                }
                return;
            case ERROR:
                assertTrue(value.syncEnabled());
                assertTrue(value.selectedDeviceAddress() != null);
                assertTrue(value.error() != null);
                assertFalse(value.error().retryable());
                assertNull(value.nextReconnectDelayMs());
                return;
            default:
                throw new AssertionError("unhandled controller phase");
        }
    }

    // Mutation caught: raw status 5/15 becomes security failure or loses its literal status.
    @Test
    public void rawDisconnectStatusesRetryWhileExplicitSecurityFiveAndFifteenStop() {
        int[] rawStatuses = new int[] {-1, 5, 15, 133};
        int[] expectedGattStatuses = new int[] {-1, 5, 15, 133};
        for (int index = 0; index < rawStatuses.length; index++) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:50", true, factory));
            controller.setSyncEnabled(true);

            factory.clients.get(0).emitDisconnected(rawStatuses[index]);

            assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                    controller.snapshot().phase());
            assertEquals(UserVisibleError.Code.CONNECT_FAILED,
                    controller.snapshot().error().code());
            assertEquals(expectedGattStatuses[index],
                    controller.snapshot().error().gattStatus());
            assertEquals(Long.valueOf(0L),
                    controller.snapshot().nextReconnectDelayMs());
            assertEquals(1, scheduler.tasks.size());
            assertEquals(1, factory.clients.size());
            scheduler.runNext();
            assertEquals(2, factory.clients.size());
            assertEquals(ConnectionSnapshot.Phase.CONNECTING,
                    controller.snapshot().phase());
        }

        int[] securityStatuses = new int[] {5, 15};
        for (int securityStatus : securityStatuses) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:51", true, factory));
            controller.setSyncEnabled(true);
            RecordingClient client = factory.clients.get(0);
            UserVisibleError securityFailure = new UserVisibleError(
                    UserVisibleError.Code.LINK_SECURITY_FAILED,
                    securityStatus);

            client.emitError(securityFailure);

            assertEquals(ConnectionSnapshot.Phase.ERROR,
                    controller.snapshot().phase());
            assertSame(securityFailure, controller.snapshot().error());
            assertEquals(1, client.disconnects);
            assertEquals(1, client.closes);
            assertTrue(client.writes.isEmpty());
            assertTrue(scheduler.tasks.isEmpty());
        }
    }

    // Mutation caught: one adapter failure mode resets backoff or reuses its returned client.
    @Test
    public void eachBondedAdapterFailureModeRepeatsThroughExactBackoff() {
        int[] failureModes = new int[] {
            RecordingFactory.NULL_CLIENT,
            RecordingFactory.FACTORY_THROW,
            RecordingFactory.CONNECT_THROW
        };
        long[] delays = new long[] {0L, 1000L, 2000L};
        for (int failureMode : failureModes) {
            Scheduler scheduler = new Scheduler();
            RecordingFactory factory = new RecordingFactory();
            factory.enqueue(failureMode);
            factory.enqueue(failureMode);
            factory.enqueue(failureMode);
            factory.enqueue(RecordingFactory.CONNECT_CONNECTED);
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), new Sink());
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:52", true, factory));

            controller.setSyncEnabled(true);
            for (long expectedDelay : delays) {
                assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                        controller.snapshot().phase());
                assertEquals(Long.valueOf(expectedDelay),
                        controller.snapshot().nextReconnectDelayMs());
                scheduler.runNext();
            }

            assertEquals(ConnectionSnapshot.Phase.READY,
                    controller.snapshot().phase());
            assertEquals(4, factory.epochs.size());
            assertEquals(Long.valueOf(1L), factory.epochs.get(0));
            assertEquals(Long.valueOf(2L), factory.epochs.get(1));
            assertEquals(Long.valueOf(3L), factory.epochs.get(2));
            assertEquals(Long.valueOf(4L), factory.epochs.get(3));
            RecordingClient ready =
                    factory.clients.get(factory.clients.size() - 1);
            assertEquals(1, ready.writes.size());
            assertEquals(0, ready.closes);
            for (int index = 0;
                    index < factory.clients.size() - 1; index++) {
                RecordingClient failed = factory.clients.get(index);
                assertEquals(1, failed.connects);
                assertEquals(1, failed.disconnects);
                assertEquals(1, failed.closes);
            }
        }
    }

    // Mutation caught: disconnected Sync duplicates READY or an active slider queues a write.
    @Test
    public void disconnectedSyncAndActiveStateChangesCoalesceExactly() {
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(),
                new Foreground(), new Sink());
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:53", true, factory));
        controller.syncNow();
        controller.setCurrentState(new BadgeState(10, 20, 1727L));
        controller.syncNow();
        controller.setCurrentState(new BadgeState(30, 40, 1727L));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        controller.syncNow();
        controller.setCurrentState(new BadgeState(50, 60, 1727L));

        client.emitConnected(semanticBuild(), null);

        assertEquals(1, client.writes.size());
        BadgeState first = new BadgeState(50, 60, 1727L);
        assertEquals(first, client.writes.get(0));
        BadgeState newest = new BadgeState(70, 80, 1727L);
        controller.setCurrentState(newest);
        client.emitAcknowledged(first, 71L);
        assertEquals(1, client.writes.size());
        assertEquals(first,
                controller.snapshot().lastAcknowledgedState());
        controller.syncNow();
        assertEquals(2, client.writes.size());
        assertSame(newest, client.writes.get(1));
    }

    // Mutation caught: asynchronous terminal generation exhaustion escapes or publishes.
    @Test
    public void terminalCallbackAtMaxLifecycleGenerationIsContained()
            throws Exception {
        Foreground foreground = new Foreground();
        Sink sink = new Sink();
        RecordingFactory factory = new RecordingFactory();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(),
                foreground, sink);
        controller.selectDevice(new BadgeSyncController.Selection(
                null, "AA:BB:CC:DD:EE:54", true, factory));
        controller.setSyncEnabled(true);
        RecordingClient client = factory.clients.get(0);
        ConnectionSnapshot before = controller.snapshot();
        int publications = sink.values.size();
        setLongField(controller, "lifecycleGeneration", Long.MAX_VALUE);
        client.callbackDuringClose = true;

        client.emitError(new UserVisibleError(
                UserVisibleError.Code.LINK_SECURITY_FAILED));

        assertSame(before, controller.snapshot());
        assertEquals(publications, sink.values.size());
        assertEquals(1, client.disconnects);
        assertEquals(1, client.closes);
        assertEquals(1, foreground.stops);
        client.emitDisconnected(5);
        assertSame(before, controller.snapshot());
        IllegalStateException error = assertThrows(
                IllegalStateException.class, controller::syncNow);
        assertEquals("controller generation exhausted",
                error.getMessage());
    }

    // Mutation caught: null public values mutate or call a controller port.
    @Test
    public void nullMutatorValuesAreRejectedWithoutObservableChange() {
        Sink sink = new Sink();
        BadgeSyncController controller = new BadgeSyncController(
                new ReconnectPolicy(), new Scheduler(),
                new Foreground(), sink);
        ConnectionSnapshot before = controller.snapshot();

        assertThrows(IllegalArgumentException.class,
                () -> controller.selectDevice(null));
        assertThrows(IllegalArgumentException.class,
                () -> controller.setCurrentState(null));

        assertSame(before, controller.snapshot());
        assertEquals(1, sink.values.size());
    }


    // Mutation caught: a retry-time adapter failure resurrects prior-client build metadata.
    @Test
    public void retryAttemptClearsBuildBeforeFactoryOrConnectFailure() {
        int[] failures = new int[] {
            RecordingFactory.FACTORY_THROW,
            RecordingFactory.CONNECT_THROW
        };
        for (int failure : failures) {
            Scheduler scheduler = new Scheduler();
            Sink sink = new Sink();
            RecordingFactory factory = new RecordingFactory();
            factory.enqueue(RecordingFactory.CLIENT);
            factory.enqueue(failure);
            BadgeSyncController controller = new BadgeSyncController(
                    new ReconnectPolicy(), scheduler,
                    new Foreground(), sink);
            controller.selectDevice(new BadgeSyncController.Selection(
                    null, "AA:BB:CC:DD:EE:56", true, factory));
            controller.setSyncEnabled(true);
            RecordingClient ready = factory.clients.get(0);
            BuildInfo priorBuild = semanticBuild();
            ready.emitConnected(priorBuild, Integer.valueOf(63));
            ready.emitDisconnected(133);
            assertEquals(priorBuild, controller.snapshot().buildInfo());
            assertEquals(Integer.valueOf(63),
                    controller.snapshot().batteryPercent());

            scheduler.runNext();

            ConnectionSnapshot retry = controller.snapshot();
            assertEquals(ConnectionSnapshot.Phase.CONNECTING,
                    sink.values.get(sink.values.size() - 2).phase());
            assertNull(sink.values.get(
                    sink.values.size() - 2).buildInfo());
            assertNull(sink.values.get(
                    sink.values.size() - 2).batteryPercent());
            assertEquals(ConnectionSnapshot.Phase.RETRY_WAIT,
                    retry.phase());
            assertEquals(UserVisibleError.Code.CONNECT_FAILED,
                    retry.error().code());
            assertEquals(Long.valueOf(1000L),
                    retry.nextReconnectDelayMs());
            assertNull(retry.buildInfo());
            assertNull(retry.batteryPercent());
            if (failure == RecordingFactory.FACTORY_THROW) {
                assertEquals(1, factory.clients.size());
            } else {
                assertEquals(2, factory.clients.size());
                assertEquals(1, factory.clients.get(1).disconnects);
                assertEquals(1, factory.clients.get(1).closes);
            }
        }
    }

    private static void setLongField(
            BadgeSyncController controller, String name, long value)
            throws Exception {
        Field field = BadgeSyncController.class.getDeclaredField(name);
        field.setAccessible(true);
        field.setLong(controller, value);
    }

    private static BuildInfo semanticBuild() {
        return buildWithCapabilities(0x01);
    }

    private static BuildInfo buildWithCapabilities(int capabilities) {
        return new BuildInfo(
                capabilities,
                "E87-JD9855-R1",
                1, 2, 3,
                new byte[16]);
    }
    private static final class Scheduler
            implements BadgeSyncController.Scheduler {
        final List<Task> tasks = new ArrayList<Task>();

        @Override
        public Handle schedule(long delayMs, Runnable callback) {
            Task task = new Task(delayMs, callback);
            tasks.add(task);
            return task;
        }

        void runNext() {
            for (Task task : tasks) {
                if (!task.canceled && !task.fired) {
                    task.fired = true;
                    task.callback.run();
                    return;
                }
            }
            throw new AssertionError("no runnable scheduled task");
        }

        void runIgnoringCancellation(Task task) {
            if (task.fired) {
                throw new AssertionError("task already fired");
            }
            task.fired = true;
            task.callback.run();
        }

        static final class Task implements Handle {
            final long delayMs;
            final Runnable callback;
            boolean canceled;
            boolean fired;

            Task(long delayMs, Runnable callback) {
                this.delayMs = delayMs;
                this.callback = callback;
            }

            @Override
            public void cancel() {
                canceled = true;
            }
        }
    }

    private static final class RecordingFactory
            implements BadgeSyncController.ClientFactory {
        static final int CLIENT = 0;
        static final int NULL_CLIENT = 1;
        static final int FACTORY_THROW = 2;
        static final int CONNECT_THROW = 3;
        static final int CREATE_DISCONNECT = 4;
        static final int CONNECT_CONNECTED = 5;
        static final int CONNECT_RETRY_ERROR = 6;
        static final int CONNECT_TERMINAL_ERROR = 7;
        static final int CONNECT_DISCONNECTED = 8;

        final List<RecordingClient> clients = new ArrayList<RecordingClient>();
        final List<Long> epochs = new ArrayList<Long>();
        final List<Integer> outcomes = new ArrayList<Integer>();
        private final List<String> order;

        RecordingFactory() {
            this(new ArrayList<String>());
        }

        RecordingFactory(List<String> order) {
            this.order = order;
        }

        void enqueue(int outcome) {
            outcomes.add(Integer.valueOf(outcome));
        }

        @Override
        public BadgeSyncController.Client create(
                long epoch, BadgeSyncController.ClientEvents events) {
            epochs.add(Long.valueOf(epoch));
            int outcome = outcomes.isEmpty()
                    ? CLIENT : outcomes.remove(0).intValue();
            if (outcome == FACTORY_THROW) {
                throw new IllegalStateException("factory detail must stay hidden");
            }
            if (outcome == NULL_CLIENT) {
                return null;
            }
            RecordingClient client =
                    new RecordingClient(epoch, events, order);
            client.connectMode = outcome;
            clients.add(client);
            if (outcome == CREATE_DISCONNECT) {
                events.onDisconnected(epoch, client, 61);
            }
            return client;
        }
    }

    private static final class RecordingClient
            implements BadgeSyncController.Client {
        final long epoch;
        final BadgeSyncController.ClientEvents events;
        final List<String> order;
        int connects;
        int disconnects;
        int closes;
        int connectMode;
        boolean acceptWrite = true;
        boolean throwWrite;
        boolean acknowledgeDuringWrite;
        UserVisibleError errorDuringWrite;
        boolean callbackDuringClose;
        final List<BadgeState> writes = new ArrayList<BadgeState>();

        RecordingClient(
                long epoch,
                BadgeSyncController.ClientEvents events,
                List<String> order) {
            this.epoch = epoch;
            this.events = events;
            this.order = order;
        }

        @Override
        public void connect() {
            connects++;
            order.add("connect");
            if (connectMode == RecordingFactory.CONNECT_THROW) {
                throw new IllegalStateException("connect detail must stay hidden");
            }
            if (connectMode == RecordingFactory.CONNECT_CONNECTED) {
                emitConnected(semanticBuild(), Integer.valueOf(44));
            } else if (connectMode == RecordingFactory.CONNECT_RETRY_ERROR) {
                emitError(new UserVisibleError(
                        UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
            } else if (connectMode
                    == RecordingFactory.CONNECT_TERMINAL_ERROR) {
                emitError(new UserVisibleError(
                        UserVisibleError.Code.LINK_SECURITY_FAILED));
            } else if (connectMode
                    == RecordingFactory.CONNECT_DISCONNECTED) {
                emitDisconnected(15);
            }
        }

        @Override
        public boolean writeState(BadgeState state) {
            writes.add(state);
            order.add("write");
            if (throwWrite) {
                throw new IllegalStateException(
                        "write detail must stay hidden");
            }
            if (acknowledgeDuringWrite) {
                events.onStateWriteAcknowledged(
                        epoch, this, state, 51L);
            }
            if (errorDuringWrite != null) {
                events.onError(epoch, this, errorDuringWrite);
            }
            return acceptWrite;
        }

        @Override
        public void disconnect() {
            disconnects++;
            order.add("disconnect");
        }

        @Override
        public void close() {
            closes++;
            order.add("close");
            if (callbackDuringClose) {
                events.onConnected(epoch, this, semanticBuild(), null);
            }
        }

        void emitConnected(BuildInfo info, Integer batteryPercent) {
            events.onConnected(epoch, this, info, batteryPercent);
        }

        void emitAcknowledged(BadgeState state, long elapsedRealtimeMs) {
            events.onStateWriteAcknowledged(
                    epoch, this, state, elapsedRealtimeMs);
        }

        void emitDisconnected(int status) {
            events.onDisconnected(epoch, this, status);
        }

        void emitError(UserVisibleError error) {
            events.onError(epoch, this, error);
        }
    }

    private static final class Foreground
            implements BadgeSyncController.ForegroundLifetime {
        int starts;
        int stops;
        boolean active;

        @Override public void start() {
            if (active) {
                throw new AssertionError("duplicate foreground start");
            }
            active = true;
            starts++;
        }

        @Override public void stop() {
            if (!active) {
                throw new AssertionError("foreground stop while inactive");
            }
            active = false;
            stops++;
        }
    }

    private static final class Sink
            implements BadgeSyncController.SnapshotSink {
        final List<ConnectionSnapshot> values =
                new ArrayList<ConnectionSnapshot>();
        private final List<String> order;

        Sink() {
            this(new ArrayList<String>());
        }

        Sink(List<String> order) {
            this.order = order;
        }

        @Override public void publish(ConnectionSnapshot snapshot) {
            values.add(snapshot);
            order.add("snapshot:" + snapshot.phase().name());
        }
    }

}
