package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

public final class StockTransitionControllerTest {
    @Test public void constructorAndPublicReferenceArgumentsRejectNullSynchronously() {
        Harness harness = new Harness(new byte[] {1, 2, 3});
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController(null, harness.driver, harness.fifo,
                        harness.scheduler, harness.timeouts, harness.listener));
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController(harness.artifact, null, harness.fifo,
                        harness.scheduler, harness.timeouts, harness.listener));
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController(harness.artifact, harness.driver, null,
                        harness.scheduler, harness.timeouts, harness.listener));
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController(harness.artifact, harness.driver,
                        harness.fifo, null, harness.timeouts, harness.listener));
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController(harness.artifact, harness.driver,
                        harness.fifo, harness.scheduler, null, harness.listener));
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController(harness.artifact, harness.driver,
                        harness.fifo, harness.scheduler, harness.timeouts, null));
        assertThrows(IllegalArgumentException.class,
                () -> new StockTransitionController.Timeouts(0, 1, 1));

        assertThrows(IllegalArgumentException.class,
                () -> harness.controller.connect(null, 6, 42));
    }

    @Test public void callbackReferenceArgumentsRejectNullBeforeTheyEnterTheFifo() {
        Harness harness = new Harness(new byte[] {1});
        assertThrows(IllegalArgumentException.class,
                () -> harness.driver.emitServicesResult(1, 1, null,
                        StockGattDriver.STATUS_SUCCESS));
        assertThrows(IllegalArgumentException.class,
                () -> harness.driver.emitServicesResult(1, 1,
                        Arrays.asList((StockGattDriver.Service) null),
                        StockGattDriver.STATUS_SUCCESS));
        assertThrows(IllegalArgumentException.class,
                () -> harness.driver.emitNotification(1, null, new byte[] {1}));
        assertThrows(IllegalArgumentException.class,
                () -> harness.driver.emitNotification(1, fd01(), null));
        assertEquals(0, harness.fifo.queuedCount());
    }

    @Test public void scanConnectAndSetupFollowCapturedProfileOrderAndVendorCccd() {
        Harness harness = new Harness(new byte[] {1, 2, 3, 4, 5});
        StockGattDriver.Peer candidate = peer("aa:bb:cc:dd:ee:ff");

        harness.controller.startScan();
        assertEquals(0, harness.driver.calls.size() - 1);
        harness.fifo.drain();
        assertEquals(Arrays.asList("setListener", "startScan"), harness.driver.calls);
        assertTrue(harness.scheduler.entries.isEmpty());

        harness.driver.emitScanResult(harness.driver.scanGeneration, harness.driver.scanToken,
                candidate);
        assertTrue(harness.listener.candidates.isEmpty());
        harness.fifo.drain();
        assertEquals(Arrays.asList(candidate), harness.listener.candidates);

        harness.controller.connect(peer("AA:BB:CC:DD:EE:FF"), 6, -1168149652);
        harness.fifo.drain();
        assertEquals(Arrays.asList("setListener", "startScan", "stopScan", "connect"),
                harness.driver.calls);
        assertEquals(100L, harness.scheduler.lastScheduled().delayMillis);

        harness.driver.emitConnectionResult(harness.driver.connectGeneration,
                harness.driver.connectToken, StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertEquals("discoverServices", last(harness.driver.calls));

        harness.driver.emitServicesResult(harness.driver.discoverGeneration,
                harness.driver.discoverToken, validServices(), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertEquals("subscribe", last(harness.driver.calls));
        assertSame(fd01(), harness.driver.subscriptionCharacteristic);
        assertEquals(StockQixUuids.CCCD, harness.driver.subscriptionDescriptor);
        assertArrayEquals(new byte[] {2, 0}, harness.driver.subscriptionValue);

        harness.driver.emitSubscriptionResult(harness.driver.subscriptionGeneration,
                harness.driver.subscriptionToken, fd01(), StockQixUuids.CCCD,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertSame(fd03(), harness.driver.subscriptionCharacteristic);
        assertArrayEquals(new byte[] {2, 0}, harness.driver.subscriptionValue);

        harness.driver.emitSubscriptionResult(harness.driver.subscriptionGeneration,
                harness.driver.subscriptionToken, fd03(), StockQixUuids.CCCD,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertEquals("requestMtu", last(harness.driver.calls));
        assertEquals(512, harness.driver.requestedMtu);

        harness.driver.emitMtuResult(harness.driver.mtuGeneration, harness.driver.mtuToken, 23,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertEquals("writeCharacteristic", last(harness.driver.calls));
        assertSame(fd02(), harness.driver.writeCharacteristic);
        assertEquals(StockGattDriver.WRITE_TYPE_DEFAULT, harness.driver.writeType);
        assertEquals(0x60, QixFrameCodec.decode(harness.driver.writeValues.get(0)).opcode());
    }

    @Test public void discoveryRejectsAnyPropertyMaskOtherThanTheCapturedExactValues() {
        Harness harness = new Harness(new byte[] {1, 2, 3});
        connectThroughDiscovery(harness);
        StockGattDriver.Characteristic wrongFd01 = new StockGattDriver.Characteristic(
                StockQixUuids.FD01, StockGattDriver.INDICATE,
                Arrays.asList(StockQixUuids.CCCD));
        StockGattDriver.Service bad = new StockGattDriver.Service(StockQixUuids.SERVICE,
                Arrays.asList(wrongFd01, fd02(), fd03()));

        harness.driver.emitServicesResult(harness.driver.discoverGeneration,
                harness.driver.discoverToken, Arrays.asList(bad), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();

        assertLastFailure(harness, StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        assertFalse(harness.listener.snapshots.isEmpty());
    }

    @Test public void finalFragmentOnlyAcknowledgesLogicalC2AndDirectC5Completes() {
        Harness harness = new Harness(new byte[] {1, 2, 3, 4, 5, 6, 7});
        driveToWaitC1(harness, 23);

        harness.driver.emitNotification(harness.driver.mtuGeneration, fd03(),
                c1(7, 0));
        harness.fifo.drain();
        int firstC2 = harness.driver.writeValues.size() - 1;
        assertEquals(20, harness.driver.writeValues.get(firstC2).length);

        harness.driver.emitCharacteristicWrite(harness.driver.writeGeneration,
                harness.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        int secondC2 = harness.driver.writeValues.size() - 1;
        assertEquals(1, harness.driver.writeValues.get(secondC2).length);
        assertEquals(StockQixTransferMachine.Phase.WRITE_C2,
                harness.controller.snapshot().phase());

        harness.driver.emitCharacteristicWrite(harness.driver.writeGeneration,
                harness.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertEquals(StockQixTransferMachine.Phase.WAIT_FINAL,
                harness.controller.snapshot().phase());

        harness.driver.emitNotification(harness.driver.mtuGeneration, fd03(), c5());
        harness.fifo.drain();
        assertEquals(1, harness.listener.completions);
        assertEquals(StockQixTransferMachine.Phase.COMPLETE,
                harness.controller.snapshot().phase());
    }

    @Test public void logicalWriteKeepsItsOriginalDeadlineAcrossPhysicalFragments() {
        Harness harness = new Harness(new byte[] {1, 2, 3, 4, 5, 6, 7});
        driveToWaitC1(harness, 23);
        harness.driver.emitNotification(harness.driver.mtuGeneration, fd03(), c1(7, 0));
        harness.fifo.drain();
        FakeScheduler.Entry logicalDeadline = harness.scheduler.lastScheduled();
        assertEquals(200L, logicalDeadline.delayMillis);

        harness.driver.emitCharacteristicWrite(harness.driver.writeGeneration,
                harness.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertFalse(logicalDeadline.cancelled);
        assertSame(logicalDeadline, harness.scheduler.lastScheduled());

        harness.scheduler.fire(logicalDeadline);
        assertTrue(harness.listener.failures.isEmpty());
        harness.fifo.drain();
        assertLastFailure(harness, StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED);
    }

    @Test public void fd02CallbackMustMatchCurrentGenerationTokenObjectAndUuid() {
        Harness harness = new Harness(new byte[] {1, 2, 3, 4, 5});
        driveToWaitC1(harness, 23);
        harness.driver.emitNotification(harness.driver.mtuGeneration, fd03(), c1(5, 0));
        harness.fifo.drain();

        StockGattDriver.Characteristic sameUuidButDifferentObject =
                new StockGattDriver.Characteristic(StockQixUuids.FD02, 0x0C,
                        Collections.<java.util.UUID>emptyList());
        harness.driver.emitCharacteristicWrite(harness.driver.writeGeneration,
                harness.driver.writeToken, sameUuidButDifferentObject,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        assertLastFailure(harness, StockQixTransferMachine.FailureCode.WRONG_CHANNEL);
    }

    @Test public void notificationPrefixBeforeLogicalWriteAckFailsAndCannotSurviveAfterAck() {
        Harness bind = new Harness(new byte[] {1, 2, 3});
        driveToBindWrite(bind, 23);
        byte[] bindFrame = bindResponse();
        bind.driver.emitNotification(bind.driver.mtuGeneration, fd01(),
                Arrays.copyOf(bindFrame, 3));
        bind.fifo.drain();
        assertLastFailure(bind, StockQixTransferMachine.FailureCode.INVALID_STATE);
        int bindFailures = bind.listener.failures.size();
        bind.driver.emitCharacteristicWrite(bind.driver.writeGeneration,
                bind.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
        bind.driver.emitNotification(bind.driver.mtuGeneration, fd01(),
                Arrays.copyOfRange(bindFrame, 3, bindFrame.length));
        bind.fifo.drain();
        assertEquals(bindFailures, bind.listener.failures.size());

        Harness c2 = new Harness(new byte[] {1, 2, 3, 4, 5});
        driveToWaitC1(c2, 23);
        c2.driver.emitNotification(c2.driver.mtuGeneration, fd03(), c1(5, 0));
        c2.fifo.drain();
        byte[] c3Frame = c3(5);
        c2.driver.emitNotification(c2.driver.mtuGeneration, fd03(),
                Arrays.copyOf(c3Frame, 3));
        c2.fifo.drain();
        assertLastFailure(c2, StockQixTransferMachine.FailureCode.INVALID_STATE);
        int c2Failures = c2.listener.failures.size();
        c2.driver.emitCharacteristicWrite(c2.driver.writeGeneration,
                c2.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
        c2.driver.emitNotification(c2.driver.mtuGeneration, fd03(),
                Arrays.copyOfRange(c3Frame, 3, c3Frame.length));
        c2.fifo.drain();
        assertEquals(c2Failures, c2.listener.failures.size());
    }

    @Test public void partialResponseDoesNotRefreshDeadlineAndTimerMutatesOnlyThroughFifo()
            throws Exception {
        Harness harness = new Harness(new byte[] {1, 2, 3});
        driveToWaitC1(harness, 23);
        FakeScheduler.Entry responseTimer = harness.scheduler.lastScheduled();
        byte[] complete = c1(3, 0);
        harness.driver.emitNotification(harness.driver.mtuGeneration, fd03(),
                Arrays.copyOf(complete, 3));
        harness.fifo.drain();
        assertSame(responseTimer, harness.scheduler.lastScheduled());
        assertTrue(harness.listener.failures.isEmpty());

        Thread timerThread = new Thread(() -> harness.scheduler.fire(responseTimer));
        timerThread.start();
        timerThread.join();
        assertTrue(harness.listener.failures.isEmpty());
        assertTrue(harness.fifo.queuedCount() > 0);
        harness.fifo.drain();
        assertLastFailure(harness, StockQixTransferMachine.FailureCode.TRANSPORT_TIMEOUT);
    }

    @Test public void staleScanCallbacksAreIgnoredAfterConnectStopsScanAndNoScanTimerExists() {
        Harness harness = new Harness(new byte[] {1, 2, 3});
        StockGattDriver.Peer peer = peer("aa:bb:cc:dd:ee:ff");
        harness.controller.startScan();
        harness.fifo.drain();
        long scanGeneration = harness.driver.scanGeneration;
        long scanToken = harness.driver.scanToken;
        harness.driver.emitScanResult(scanGeneration, scanToken, peer);
        harness.fifo.drain();
        assertTrue(harness.scheduler.entries.isEmpty());

        harness.controller.connect(peer, 6, 1);
        harness.fifo.drain();
        assertEquals("stopScan", harness.driver.calls.get(harness.driver.calls.size() - 2));
        assertEquals("connect", last(harness.driver.calls));
        assertEquals(1, harness.listener.candidates.size());
        harness.driver.emitScanResult(scanGeneration, scanToken,
                peer("11:22:33:44:55:66"));
        harness.fifo.drain();
        assertEquals(1, harness.listener.candidates.size());
    }

    @Test public void indefiniteUnfilteredScanCapsOwnedAndSurfacedCandidates() {
        Harness harness = new Harness(new byte[] {1, 2, 3});
        harness.controller.startScan();
        harness.fifo.drain();
        List<StockGattDriver.Peer> emitted = new ArrayList<StockGattDriver.Peer>();
        for (int index = 0; index <= StockTransitionController.MAX_CANDIDATES; index++) {
            StockGattDriver.Peer candidate = peer(
                    String.format("02:00:00:00:00:%02X", index));
            emitted.add(candidate);
            harness.driver.emitScanResult(
                    harness.driver.scanGeneration, harness.driver.scanToken, candidate);
        }

        harness.fifo.drain();

        assertEquals(StockTransitionController.MAX_CANDIDATES,
                harness.listener.candidates.size());
        StockGattDriver.Peer overflow = emitted.get(StockTransitionController.MAX_CANDIDATES);
        assertFalse(harness.listener.candidates.contains(overflow));

        harness.controller.connect(overflow, 6, 1);
        harness.fifo.drain();
        assertLastFailure(harness, StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    @Test public void cancelAndCloseHonorThePreAndPostC1LifecycleSplit() {
        Harness preC1 = new Harness(new byte[] {1, 2, 3});
        preC1.controller.startScan();
        preC1.fifo.drain();
        preC1.controller.cancel();
        preC1.fifo.drain();
        assertLastFailure(preC1, StockQixTransferMachine.FailureCode.CANCELLED);

        Harness postC1 = new Harness(new byte[] {1, 2, 3, 4, 5});
        driveToWaitC1(postC1, 23);
        postC1.driver.emitNotification(postC1.driver.mtuGeneration, fd03(), c1(5, 0));
        postC1.fifo.drain();
        StockQixTransferMachine.Snapshot beforeCancel = postC1.controller.snapshot();
        postC1.controller.cancel();
        postC1.fifo.drain();
        assertEquals(beforeCancel.phase(), postC1.controller.snapshot().phase());
        assertTrue(postC1.listener.failures.isEmpty());

        Harness closing = new Harness(new byte[] {1, 2, 3});
        closing.controller.startScan();
        closing.fifo.drain();
        closing.controller.close();
        closing.fifo.drain();
        int callsAfterFirstClose = closing.driver.calls.size();
        assertLastFailure(closing, StockQixTransferMachine.FailureCode.CANCELLED);
        closing.controller.close();
        closing.fifo.drain();
        assertEquals(callsAfterFirstClose, closing.driver.calls.size());
    }

    @Test public void outOfStateStartAndUnsightedPeerFailClosedExactlyOnce() {
        Harness repeated = new Harness(new byte[] {1});
        repeated.controller.startScan();
        repeated.fifo.drain();
        repeated.controller.startScan();
        repeated.fifo.drain();
        assertLastFailure(repeated, StockQixTransferMachine.FailureCode.INVALID_STATE);
        int failures = repeated.listener.failures.size();
        repeated.controller.startScan();
        repeated.fifo.drain();
        assertEquals(failures, repeated.listener.failures.size());

        Harness unsighted = new Harness(new byte[] {1});
        unsighted.controller.startScan();
        unsighted.fifo.drain();
        unsighted.controller.connect(peer("AA:BB:CC:DD:EE:FF"), 6, 1);
        unsighted.fifo.drain();
        assertLastFailure(unsighted, StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    private static void connectThroughDiscovery(Harness harness) {
        harness.controller.startScan();
        harness.fifo.drain();
        StockGattDriver.Peer candidate = peer("AA:BB:CC:DD:EE:FF");
        harness.driver.emitScanResult(harness.driver.scanGeneration, harness.driver.scanToken,
                candidate);
        harness.fifo.drain();
        harness.controller.connect(candidate, 6, 1);
        harness.fifo.drain();
        harness.driver.emitConnectionResult(harness.driver.connectGeneration,
                harness.driver.connectToken, StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
    }

    private static void driveToWaitC1(Harness harness, int mtu) {
        driveToBindWrite(harness, mtu);

        harness.driver.emitCharacteristicWrite(harness.driver.writeGeneration,
                harness.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        harness.driver.emitNotification(harness.driver.mtuGeneration, fd01(), bindResponse());
        harness.fifo.drain();
        while (harness.driver.writeValues.get(harness.driver.writeValues.size() - 1).length
                != 0 && harness.controller.snapshot().phase()
                == StockQixTransferMachine.Phase.WRITE_C0) {
            harness.driver.emitCharacteristicWrite(harness.driver.writeGeneration,
                    harness.driver.writeToken, fd02(), StockGattDriver.STATUS_SUCCESS);
            harness.fifo.drain();
        }
        assertEquals(StockQixTransferMachine.Phase.WAIT_C1, harness.controller.snapshot().phase());
    }

    private static void driveToBindWrite(Harness harness, int mtu) {
        connectThroughDiscovery(harness);
        harness.driver.emitServicesResult(harness.driver.discoverGeneration,
                harness.driver.discoverToken, validServices(), StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        harness.driver.emitSubscriptionResult(harness.driver.subscriptionGeneration,
                harness.driver.subscriptionToken, fd01(), StockQixUuids.CCCD,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        harness.driver.emitSubscriptionResult(harness.driver.subscriptionGeneration,
                harness.driver.subscriptionToken, fd03(), StockQixUuids.CCCD,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
        harness.driver.emitMtuResult(harness.driver.mtuGeneration, harness.driver.mtuToken, mtu,
                StockGattDriver.STATUS_SUCCESS);
        harness.fifo.drain();
    }

    private static List<StockGattDriver.Service> validServices() {
        return Arrays.asList(new StockGattDriver.Service(StockQixUuids.SERVICE,
                Arrays.asList(fd01(), fd02(), fd03())));
    }

    private static StockGattDriver.Characteristic fd01() {
        return Characteristics.FD01;
    }

    private static StockGattDriver.Characteristic fd02() {
        return Characteristics.FD02;
    }

    private static StockGattDriver.Characteristic fd03() {
        return Characteristics.FD03;
    }

    private static byte[] bindResponse() {
        return QixFrameCodec.encode(0x04, 0x61,
                new byte[] {0, 0, 0, 0, '1', '.', '0', 0});
    }

    private static byte[] c1(long window, long offset) {
        byte[] payload = new byte[9];
        payload[0] = 1;
        putU32(payload, 1, window);
        putU32(payload, 5, offset);
        return QixFrameCodec.encode(0x01, 0xC1, payload);
    }

    private static byte[] c5() {
        return QixFrameCodec.encode(0x01, 0xC5, new byte[] {0});
    }

    private static byte[] c3(long offset) {
        byte[] payload = new byte[5];
        putU32(payload, 1, offset);
        return QixFrameCodec.encode(0x01, 0xC3, payload);
    }

    private static void putU32(byte[] target, int offset, long value) {
        target[offset] = (byte) value;
        target[offset + 1] = (byte) (value >>> 8);
        target[offset + 2] = (byte) (value >>> 16);
        target[offset + 3] = (byte) (value >>> 24);
    }

    private static StockGattDriver.Peer peer(String address) {
        return new StockGattDriver.Peer(address, "E87", -45);
    }

    private static <T> T last(List<T> values) {
        return values.get(values.size() - 1);
    }

    private static void assertLastFailure(Harness harness,
            StockQixTransferMachine.FailureCode expected) {
        assertFalse(harness.listener.failures.isEmpty());
        assertEquals(expected, last(harness.listener.failures));
        assertEquals(StockQixTransferMachine.Phase.FAILED, harness.controller.snapshot().phase());
    }

    private static final class Characteristics {
        static final StockGattDriver.Characteristic FD01 = new StockGattDriver.Characteristic(
                StockQixUuids.FD01, 0x10, Arrays.asList(StockQixUuids.CCCD));
        static final StockGattDriver.Characteristic FD02 = new StockGattDriver.Characteristic(
                StockQixUuids.FD02, 0x0C, Collections.<java.util.UUID>emptyList());
        static final StockGattDriver.Characteristic FD03 = new StockGattDriver.Characteristic(
                StockQixUuids.FD03, 0x1A, Arrays.asList(StockQixUuids.CCCD));
    }

    private static final class Harness {
        final FifoExecutor fifo = new FifoExecutor();
        final FakeStockGattDriver driver = new FakeStockGattDriver();
        final FakeScheduler scheduler = new FakeScheduler();
        final StockTransitionController.Timeouts timeouts =
                new StockTransitionController.Timeouts(100, 200, 300);
        final RecordingListener listener = new RecordingListener();
        final TransitionArtifact artifact;
        final StockTransitionController controller;

        Harness(byte[] payload) {
            artifact = artifact(payload);
            controller = new StockTransitionController(artifact, driver, fifo, scheduler,
                    timeouts, listener);
        }
    }

    private static final class RecordingListener implements StockTransitionController.Listener {
        final List<StockGattDriver.Peer> candidates = new ArrayList<StockGattDriver.Peer>();
        final List<StockQixTransferMachine.Snapshot> snapshots =
                new ArrayList<StockQixTransferMachine.Snapshot>();
        final List<StockQixTransferMachine.FailureCode> failures =
                new ArrayList<StockQixTransferMachine.FailureCode>();
        int completions;

        @Override public void onCandidate(StockGattDriver.Peer candidate) {
            candidates.add(candidate);
        }

        @Override public void onSnapshot(StockQixTransferMachine.Snapshot snapshot) {
            snapshots.add(snapshot);
        }

        @Override public void onComplete(StockQixTransferMachine.Snapshot snapshot) {
            completions++;
        }

        @Override public void onFailed(StockQixTransferMachine.FailureCode failureCode,
                StockQixTransferMachine.Snapshot snapshot) {
            failures.add(failureCode);
        }
    }

    private static TransitionArtifact artifact(byte[] payload) {
        byte[] header = new byte[27];
        putU32(header, 13, payload.length);
        return new TransitionArtifact(header, payload, sha256(header, payload), new byte[16]);
    }

    private static byte[] sha256(byte[] header, byte[] payload) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(header);
            digest.update(payload);
            return digest.digest();
        } catch (NoSuchAlgorithmException failure) {
            throw new AssertionError(failure);
        }
    }
}
