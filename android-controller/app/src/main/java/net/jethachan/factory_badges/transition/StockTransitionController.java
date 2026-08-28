package net.jethachan.factory_badges.transition;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Executor;

/**
 * FIFO-confined controller for the isolated stock FD00 Qix transfer.
 *
 * <p>All mutable controller state is accessed only from the supplied serial FIFO executor. The
 * reducer remains pure; this class owns only setup sequencing, GATT fragmentation, and timeout
 * ingress.
 */
public final class StockTransitionController {
    public static final int MAX_CANDIDATES = 16;

    public interface Scheduler {
        interface Handle {
            void cancel();
        }

        Handle schedule(long delayMillis, Runnable runnable);
    }

    public static final class Timeouts {
        private final long setupMillis;
        private final long writeMillis;
        private final long responseMillis;

        public Timeouts(long setupMillis, long writeMillis, long responseMillis) {
            if (setupMillis <= 0 || writeMillis <= 0 || responseMillis <= 0) {
                throw new IllegalArgumentException("all timeout values must be positive");
            }
            this.setupMillis = setupMillis;
            this.writeMillis = writeMillis;
            this.responseMillis = responseMillis;
        }

        public long setupMillis() {
            return setupMillis;
        }

        public long writeMillis() {
            return writeMillis;
        }

        public long responseMillis() {
            return responseMillis;
        }
    }

    public interface Listener {
        void onCandidate(StockGattDriver.Peer candidate);
        void onSnapshot(StockQixTransferMachine.Snapshot snapshot);
        void onComplete(StockQixTransferMachine.Snapshot snapshot);
        void onFailed(StockQixTransferMachine.FailureCode failureCode,
                StockQixTransferMachine.Snapshot snapshot);
    }

    private enum State {
        IDLE, SCANNING, CONNECTING, DISCOVERING, SUB_FD01, SUB_FD03, REQUESTING_MTU,
        DRIVING, TERMINAL
    }

    private enum CallbackKind {
        NONE, SCAN, CONNECT, DISCOVER, SUB_FD01, SUB_FD03, MTU, WRITE, WAIT_FD01, WAIT_FD03
    }

    private enum TimeoutKind {
        SETUP, WRITE, RESPONSE
    }

    private static final long NO_TOKEN = 0L;
    private static final int REQUESTED_MTU = 512;
    private static final byte[] VENDOR_CCCD_VALUE = new byte[] {2, 0};

    private final StockQixTransferMachine machine;
    private final StockGattDriver driver;
    private final Executor fifoExecutor;
    private final Scheduler scheduler;
    private final Timeouts timeouts;
    private final Listener listener;
    private final StockGattDriver.Listener driverListener = new DriverListener();
    private final StockGattDriver.Listener noOpDriverListener = new NoOpDriverListener();
    private final Set<StockGattDriver.Peer> candidates =
            new LinkedHashSet<StockGattDriver.Peer>();
    private final QixFrameAssembler fd01Assembler = new QixFrameAssembler();
    private final QixFrameAssembler fd03Assembler = new QixFrameAssembler();

    private volatile StockQixTransferMachine.Snapshot latestSnapshot;

    private State state = State.IDLE;
    private CallbackKind expectedKind = CallbackKind.NONE;
    private long generation;
    private long expectedToken = NO_TOKEN;
    private long nextToken;
    private TimerRegistration activeTimer;
    private boolean scanActive;
    private StockGattDriver.Characteristic fd01;
    private StockGattDriver.Characteristic fd02;
    private StockGattDriver.Characteristic fd03;
    private int negotiatedMtu = 23;
    private byte[] logicalFrame;
    private int logicalOffset;
    private int currentFragmentLength;
    private boolean currentFragmentFinal;
    private StockGattDriver.Characteristic expectedSubscriptionCharacteristic;

    public StockTransitionController(TransitionArtifact artifact, StockGattDriver driver,
            Executor fifoExecutor, Scheduler scheduler, Timeouts timeouts, Listener listener) {
        if (artifact == null || driver == null || fifoExecutor == null || scheduler == null
                || timeouts == null || listener == null) {
            throw new IllegalArgumentException("controller inputs must not be null");
        }
        this.machine = new StockQixTransferMachine(artifact);
        this.driver = driver;
        this.fifoExecutor = fifoExecutor;
        this.scheduler = scheduler;
        this.timeouts = timeouts;
        this.listener = listener;
        latestSnapshot = machine.snapshot();
        driver.setListener(driverListener);
    }

    public void startScan() {
        enqueue(new Runnable() {
            @Override public void run() {
                startScanOnFifo();
            }
        });
    }

    public void connect(final StockGattDriver.Peer peer, final int settings, final int hostId) {
        if (peer == null) {
            throw new IllegalArgumentException("peer must not be null");
        }
        enqueue(new Runnable() {
            @Override public void run() {
                connectOnFifo(peer, settings, hostId);
            }
        });
    }

    public void cancel() {
        enqueue(new Runnable() {
            @Override public void run() {
                if (state == State.TERMINAL || !machine.snapshot().mayCancel()) {
                    return;
                }
                failTransport(StockQixTransferMachine.FailureCode.CANCELLED);
            }
        });
    }

    public void close() {
        enqueue(new Runnable() {
            @Override public void run() {
                if (state == State.TERMINAL) {
                    return;
                }
                failTransport(machine.snapshot().mayCancel()
                        ? StockQixTransferMachine.FailureCode.CANCELLED
                        : StockQixTransferMachine.FailureCode.FAILED_RECONNECT_REQUIRED);
            }
        });
    }

    public StockQixTransferMachine.Snapshot snapshot() {
        return latestSnapshot;
    }

    private void startScanOnFifo() {
        if (state == State.TERMINAL) {
            return;
        }
        if (state != State.IDLE) {
            failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
            return;
        }
        generation++;
        candidates.clear();
        fd01Assembler.reset();
        fd03Assembler.reset();
        scanActive = true;
        state = State.SCANNING;
        long token = nextToken();
        expect(CallbackKind.SCAN, token);
        boolean accepted;
        try {
            accepted = driver.startScan(generation, token);
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!accepted) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        }
    }

    private void connectOnFifo(StockGattDriver.Peer peer, int settings, int hostId) {
        if (state == State.TERMINAL) {
            return;
        }
        if (state != State.SCANNING || !candidates.contains(peer)) {
            failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
            return;
        }
        clearExpected();
        scanActive = false;
        try {
            driver.stopScan(generation);
        } catch (RuntimeException ignored) {
            // A best-effort scan stop must not leave a later GATT connect unordered.
        }
        state = State.CONNECTING;
        long token = nextToken();
        expect(CallbackKind.CONNECT, token);
        boolean accepted;
        try {
            accepted = driver.connect(generation, token, peer);
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!accepted) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        armTimer(timeouts.setupMillis(), TimeoutKind.SETUP);
        pendingSettings = settings;
        pendingHostId = hostId;
    }

    private int pendingSettings;
    private int pendingHostId;

    private void onConnectionResult(long callbackGeneration, long token, int status) {
        if (!matches(callbackGeneration, token, CallbackKind.CONNECT)) {
            return;
        }
        clearExpected();
        if (status != StockGattDriver.STATUS_SUCCESS) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        state = State.DISCOVERING;
        issueDiscoverServices();
    }

    private void issueDiscoverServices() {
        long token = nextToken();
        expect(CallbackKind.DISCOVER, token);
        boolean accepted;
        try {
            accepted = driver.discoverServices(generation, token);
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!accepted) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        armTimer(timeouts.setupMillis(), TimeoutKind.SETUP);
    }

    private void onServicesResult(long callbackGeneration, long token,
            List<StockGattDriver.Service> services, int status) {
        if (!matches(callbackGeneration, token, CallbackKind.DISCOVER)) {
            return;
        }
        clearExpected();
        if (status != StockGattDriver.STATUS_SUCCESS || !selectCapturedProfile(services)) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        state = State.SUB_FD01;
        issueSubscription(fd01, CallbackKind.SUB_FD01);
    }

    private void issueSubscription(StockGattDriver.Characteristic characteristic,
            CallbackKind kind) {
        expectedSubscriptionCharacteristic = characteristic;
        long token = nextToken();
        expect(kind, token);
        boolean accepted;
        try {
            accepted = driver.subscribe(generation, token, characteristic, StockQixUuids.CCCD,
                    Arrays.copyOf(VENDOR_CCCD_VALUE, VENDOR_CCCD_VALUE.length));
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!accepted) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        armTimer(timeouts.setupMillis(), TimeoutKind.SETUP);
    }

    private void onSubscriptionResult(long callbackGeneration, long token,
            StockGattDriver.Characteristic characteristic, UUID descriptorUuid, int status) {
        if (!matches(callbackGeneration, token, expectedKind)) {
            return;
        }
        CallbackKind currentKind = expectedKind;
        if ((currentKind != CallbackKind.SUB_FD01 && currentKind != CallbackKind.SUB_FD03)
                || characteristic != expectedSubscriptionCharacteristic
                || !StockQixUuids.CCCD.equals(descriptorUuid)) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        clearExpected();
        if (status != StockGattDriver.STATUS_SUCCESS) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        if (currentKind == CallbackKind.SUB_FD01) {
            state = State.SUB_FD03;
            issueSubscription(fd03, CallbackKind.SUB_FD03);
        } else {
            state = State.REQUESTING_MTU;
            issueMtuRequest();
        }
    }

    private void issueMtuRequest() {
        long token = nextToken();
        expect(CallbackKind.MTU, token);
        boolean accepted;
        try {
            accepted = driver.requestMtu(generation, token, REQUESTED_MTU);
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!accepted) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        armTimer(timeouts.setupMillis(), TimeoutKind.SETUP);
    }

    private void onMtuResult(long callbackGeneration, long token, int mtu, int status) {
        if (!matches(callbackGeneration, token, CallbackKind.MTU)) {
            return;
        }
        clearExpected();
        if (status != StockGattDriver.STATUS_SUCCESS || mtu < 23) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            return;
        }
        negotiatedMtu = mtu;
        state = State.DRIVING;
        applyAction(machine.start(pendingSettings, pendingHostId));
    }

    private void onCharacteristicWrite(long callbackGeneration, long token,
            StockGattDriver.Characteristic characteristic, int status) {
        if (state == State.TERMINAL) {
            return;
        }
        if (callbackGeneration != generation || token != expectedToken
                || expectedKind != CallbackKind.WRITE) {
            return;
        }
        if (characteristic != fd02 || !StockQixUuids.FD02.equals(characteristic.uuid())) {
            failProtocol(StockQixTransferMachine.FailureCode.WRONG_CHANNEL);
            return;
        }
        if (status != StockGattDriver.STATUS_SUCCESS) {
            clearExpected();
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED);
            return;
        }
        if (currentFragmentFinal) {
            clearExpected();
            logicalFrame = null;
            logicalOffset = 0;
            currentFragmentLength = 0;
            currentFragmentFinal = false;
            applyAction(machine.onFd02WriteAcknowledged());
            return;
        }
        clearExpectedRetainingWriteDeadline();
        logicalOffset += currentFragmentLength;
        sendNextPhysicalFragment();
    }

    private void onNotification(long callbackGeneration,
            StockGattDriver.Characteristic characteristic, byte[] value) {
        if (state == State.TERMINAL || callbackGeneration != generation) {
            return;
        }
        final List<QixFrame> frames;
        final boolean isFd01 = StockQixUuids.FD01.equals(characteristic.uuid());
        final boolean isFd03 = StockQixUuids.FD03.equals(characteristic.uuid());
        if (!isFd01 && !isFd03) {
            failProtocol(StockQixTransferMachine.FailureCode.WRONG_CHANNEL);
            return;
        }
        if (expectedKind == CallbackKind.WRITE) {
            // A logical FD02 frame remains unacknowledged until its final physical callback.
            // Do not buffer an early prefix that could otherwise become a valid response later.
            fd01Assembler.reset();
            fd03Assembler.reset();
            failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
            return;
        }
        try {
            frames = isFd01 ? fd01Assembler.accept(value) : fd03Assembler.accept(value);
        } catch (IllegalArgumentException malformed) {
            failProtocol(StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
            return;
        }
        for (QixFrame frame : frames) {
            StockQixTransferMachine.Action action = isFd01
                    ? machine.onFd01(frame) : machine.onFd03(frame);
            clearExpected();
            applyAction(action);
            if (state == State.TERMINAL) {
                return;
            }
        }
    }

    private void onDisconnected(long callbackGeneration, int status) {
        if (state == State.TERMINAL || callbackGeneration != generation) {
            return;
        }
        if (state == State.DRIVING) {
            failTransport(machine.snapshot().mayCancel()
                    ? StockQixTransferMachine.FailureCode.TRANSPORT_DISCONNECTED
                    : StockQixTransferMachine.FailureCode.FAILED_RECONNECT_REQUIRED);
        } else {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        }
    }

    private void applyAction(StockQixTransferMachine.Action action) {
        if (action == null) {
            failProtocol(StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
            return;
        }
        publishSnapshot();
        if (action instanceof StockQixTransferMachine.SendFd02) {
            if (state != State.DRIVING) {
                failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
                return;
            }
            sendLogicalFrame(((StockQixTransferMachine.SendFd02) action).frame());
            return;
        }
        if (action instanceof StockQixTransferMachine.AwaitFd01) {
            awaitResponse(CallbackKind.WAIT_FD01);
            return;
        }
        if (action instanceof StockQixTransferMachine.AwaitFd03) {
            awaitResponse(CallbackKind.WAIT_FD03);
            return;
        }
        if (action instanceof StockQixTransferMachine.Complete) {
            listener.onComplete(latestSnapshot);
            teardown();
            return;
        }
        if (action instanceof StockQixTransferMachine.Failed) {
            StockQixTransferMachine.Failed failed = (StockQixTransferMachine.Failed) action;
            listener.onFailed(failed.failureCode(), latestSnapshot);
            teardown();
            return;
        }
        failProtocol(StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
    }

    private void sendLogicalFrame(byte[] frame) {
        if (frame == null || fd02 == null) {
            failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
            return;
        }
        logicalFrame = Arrays.copyOf(frame, frame.length);
        logicalOffset = 0;
        sendNextPhysicalFragment();
    }

    private void sendNextPhysicalFragment() {
        if (logicalFrame == null || logicalOffset < 0 || logicalOffset >= logicalFrame.length) {
            failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
            return;
        }
        int maximumFragment = Math.max(20, negotiatedMtu - 6);
        currentFragmentLength = Math.min(maximumFragment, logicalFrame.length - logicalOffset);
        currentFragmentFinal = logicalOffset + currentFragmentLength == logicalFrame.length;
        byte[] fragment = Arrays.copyOfRange(logicalFrame, logicalOffset,
                logicalOffset + currentFragmentLength);
        long token = nextToken();
        expect(CallbackKind.WRITE, token);
        boolean accepted;
        try {
            accepted = driver.writeCharacteristic(generation, token, fd02, fragment,
                    StockGattDriver.WRITE_TYPE_DEFAULT);
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!accepted) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED);
            return;
        }
        if (activeTimer == null) {
            armTimer(timeouts.writeMillis(), TimeoutKind.WRITE);
        } else if (activeTimer.kind == TimeoutKind.WRITE) {
            activeTimer.token = token;
        } else {
            failProtocol(StockQixTransferMachine.FailureCode.INVALID_STATE);
        }
    }

    private void awaitResponse(CallbackKind kind) {
        long token = nextToken();
        expect(kind, token);
        armTimer(timeouts.responseMillis(), TimeoutKind.RESPONSE);
    }

    private void failProtocol(StockQixTransferMachine.FailureCode failureCode) {
        if (state == State.TERMINAL) {
            return;
        }
        applyAction(machine.onProtocolFailed(failureCode));
    }

    private void failTransport(StockQixTransferMachine.FailureCode failureCode) {
        if (state == State.TERMINAL) {
            return;
        }
        applyAction(machine.onTransportFailed(failureCode));
    }

    private void publishSnapshot() {
        latestSnapshot = machine.snapshot();
        listener.onSnapshot(latestSnapshot);
    }

    private void expect(CallbackKind kind, long token) {
        expectedKind = kind;
        expectedToken = token;
    }

    private boolean matches(long callbackGeneration, long token, CallbackKind kind) {
        return state != State.TERMINAL && callbackGeneration == generation && token == expectedToken
                && expectedKind == kind;
    }

    private long nextToken() {
        nextToken++;
        if (nextToken == NO_TOKEN) {
            nextToken++;
        }
        return nextToken;
    }

    private void clearExpected() {
        cancelTimer();
        expectedKind = CallbackKind.NONE;
        expectedToken = NO_TOKEN;
        expectedSubscriptionCharacteristic = null;
    }

    private void clearExpectedRetainingWriteDeadline() {
        expectedKind = CallbackKind.NONE;
        expectedToken = NO_TOKEN;
        expectedSubscriptionCharacteristic = null;
    }

    private void armTimer(long delayMillis, TimeoutKind kind) {
        final TimerRegistration timer = new TimerRegistration(generation, expectedToken, state,
                expectedKind, kind);
        activeTimer = timer;
        try {
            timer.handle = scheduler.schedule(delayMillis, new Runnable() {
                @Override public void run() {
                    enqueue(new Runnable() {
                        @Override public void run() {
                            onTimer(timer);
                        }
                    });
                }
            });
            if (timer.handle == null) {
                activeTimer = null;
                failTransport(kind == TimeoutKind.WRITE
                        ? StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED
                        : StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
            }
        } catch (RuntimeException failure) {
            activeTimer = null;
            failTransport(kind == TimeoutKind.WRITE
                    ? StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED
                    : StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        }
    }

    private void onTimer(TimerRegistration timer) {
        if (state == State.TERMINAL || timer == null || activeTimer != timer
                || timer.handle == null || timer.generation != generation
                || timer.token != expectedToken || timer.state != state
                || timer.callbackKind != expectedKind) {
            return;
        }
        activeTimer = null;
        if (timer.kind == TimeoutKind.SETUP) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
        } else if (timer.kind == TimeoutKind.WRITE) {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED);
        } else {
            failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_TIMEOUT);
        }
    }

    private void cancelTimer() {
        TimerRegistration timer = activeTimer;
        activeTimer = null;
        if (timer != null && timer.handle != null) {
            timer.handle.cancel();
        }
    }

    private boolean selectCapturedProfile(List<StockGattDriver.Service> services) {
        StockGattDriver.Service targetService = null;
        int serviceCount = 0;
        for (StockGattDriver.Service service : services) {
            if (StockQixUuids.SERVICE.equals(service.uuid())) {
                targetService = service;
                serviceCount++;
            }
        }
        if (serviceCount != 1) {
            return false;
        }
        StockGattDriver.Characteristic selectedFd01 = null;
        StockGattDriver.Characteristic selectedFd02 = null;
        StockGattDriver.Characteristic selectedFd03 = null;
        int fd01Count = 0;
        int fd02Count = 0;
        int fd03Count = 0;
        for (StockGattDriver.Characteristic characteristic : targetService.characteristics()) {
            UUID uuid = characteristic.uuid();
            if (StockQixUuids.FD01.equals(uuid)) {
                selectedFd01 = characteristic;
                fd01Count++;
            } else if (StockQixUuids.FD02.equals(uuid)) {
                selectedFd02 = characteristic;
                fd02Count++;
            } else if (StockQixUuids.FD03.equals(uuid)) {
                selectedFd03 = characteristic;
                fd03Count++;
            }
        }
        if (fd01Count != 1 || fd02Count != 1 || fd03Count != 1
                || selectedFd01.properties() != 0x10 || selectedFd02.properties() != 0x0C
                || selectedFd03.properties() != 0x1A
                || !selectedFd01.hasDescriptor(StockQixUuids.CCCD)
                || !selectedFd03.hasDescriptor(StockQixUuids.CCCD)) {
            return false;
        }
        fd01 = selectedFd01;
        fd02 = selectedFd02;
        fd03 = selectedFd03;
        return true;
    }

    private void teardown() {
        if (state == State.TERMINAL) {
            return;
        }
        long oldGeneration = generation;
        boolean stopScan = scanActive;
        clearExpected();
        scanActive = false;
        candidates.clear();
        fd01Assembler.reset();
        fd03Assembler.reset();
        logicalFrame = null;
        state = State.TERMINAL;
        generation++;
        if (stopScan) {
            try {
                driver.stopScan(oldGeneration);
            } catch (RuntimeException ignored) {
                // Best-effort terminal teardown.
            }
        }
        try {
            driver.setListener(noOpDriverListener);
        } catch (RuntimeException ignored) {
            // The current listener must never be replaced with null during teardown.
        }
        try {
            driver.disconnect(oldGeneration);
        } catch (RuntimeException ignored) {
            // Best-effort terminal teardown.
        }
        try {
            driver.close();
        } catch (RuntimeException ignored) {
            // Best-effort terminal teardown.
        }
    }

    private void enqueue(Runnable task) {
        fifoExecutor.execute(task);
    }

    private final class DriverListener implements StockGattDriver.Listener {
        @Override public void onScanResult(final long callbackGeneration, final long token,
                final StockGattDriver.Peer peer) {
            if (peer == null) {
                throw new IllegalArgumentException("scan peer must not be null");
            }
            enqueue(new Runnable() {
                @Override public void run() {
                    if (!matches(callbackGeneration, token, CallbackKind.SCAN)) {
                        return;
                    }
                    if (!candidates.contains(peer) && candidates.size() >= MAX_CANDIDATES) {
                        return;
                    }
                    if (candidates.add(peer)) {
                        listener.onCandidate(peer);
                    }
                }
            });
        }

        @Override public void onScanFailed(final long callbackGeneration, final long token,
                final int status) {
            enqueue(new Runnable() {
                @Override public void run() {
                    if (matches(callbackGeneration, token, CallbackKind.SCAN)) {
                        failTransport(StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED);
                    }
                }
            });
        }

        @Override public void onConnectionResult(final long callbackGeneration, final long token,
                final int status) {
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onConnectionResult(callbackGeneration, token,
                            status);
                }
            });
        }

        @Override public void onDisconnected(final long callbackGeneration, final int status) {
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onDisconnected(callbackGeneration, status);
                }
            });
        }

        @Override public void onServicesResult(final long callbackGeneration, final long token,
                List<StockGattDriver.Service> services, final int status) {
            if (services == null) {
                throw new IllegalArgumentException("services must not be null");
            }
            for (StockGattDriver.Service service : services) {
                if (service == null) {
                    throw new IllegalArgumentException("services must not contain null");
                }
            }
            final List<StockGattDriver.Service> copied = Collections.unmodifiableList(
                    new ArrayList<StockGattDriver.Service>(services));
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onServicesResult(callbackGeneration, token,
                            copied, status);
                }
            });
        }

        @Override public void onSubscriptionResult(final long callbackGeneration, final long token,
                final StockGattDriver.Characteristic characteristic, final UUID descriptorUuid,
                final int status) {
            if (characteristic == null || descriptorUuid == null) {
                throw new IllegalArgumentException("subscription callback values must not be null");
            }
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onSubscriptionResult(callbackGeneration, token,
                            characteristic, descriptorUuid, status);
                }
            });
        }

        @Override public void onMtuResult(final long callbackGeneration, final long token,
                final int mtu, final int status) {
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onMtuResult(callbackGeneration, token, mtu,
                            status);
                }
            });
        }

        @Override public void onCharacteristicWrite(final long callbackGeneration,
                final long token, final StockGattDriver.Characteristic characteristic,
                final int status) {
            if (characteristic == null) {
                throw new IllegalArgumentException("write characteristic must not be null");
            }
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onCharacteristicWrite(callbackGeneration, token,
                            characteristic, status);
                }
            });
        }

        @Override public void onNotification(final long callbackGeneration,
                final StockGattDriver.Characteristic characteristic, byte[] value) {
            if (characteristic == null || value == null) {
                throw new IllegalArgumentException("notification values must not be null");
            }
            final byte[] copied = Arrays.copyOf(value, value.length);
            enqueue(new Runnable() {
                @Override public void run() {
                    StockTransitionController.this.onNotification(callbackGeneration,
                            characteristic, copied);
                }
            });
        }
    }

    private static final class NoOpDriverListener implements StockGattDriver.Listener {
        @Override public void onScanResult(long generation, long token, StockGattDriver.Peer peer) {
        }

        @Override public void onScanFailed(long generation, long token, int status) {
        }

        @Override public void onConnectionResult(long generation, long token, int status) {
        }

        @Override public void onDisconnected(long generation, int status) {
        }

        @Override public void onServicesResult(long generation, long token,
                List<StockGattDriver.Service> services, int status) {
        }

        @Override public void onSubscriptionResult(long generation, long token,
                StockGattDriver.Characteristic characteristic, UUID descriptorUuid, int status) {
        }

        @Override public void onMtuResult(long generation, long token, int mtu, int status) {
        }

        @Override public void onCharacteristicWrite(long generation, long token,
                StockGattDriver.Characteristic characteristic, int status) {
        }

        @Override public void onNotification(long generation,
                StockGattDriver.Characteristic characteristic, byte[] value) {
        }
    }

    private static final class TimerRegistration {
        final long generation;
        long token;
        final State state;
        final CallbackKind callbackKind;
        final TimeoutKind kind;
        Scheduler.Handle handle;

        TimerRegistration(long generation, long token, State state, CallbackKind callbackKind,
                TimeoutKind kind) {
            this.generation = generation;
            this.token = token;
            this.state = state;
            this.callbackKind = callbackKind;
            this.kind = kind;
        }
    }
}
