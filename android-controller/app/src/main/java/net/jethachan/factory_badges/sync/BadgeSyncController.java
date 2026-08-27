package net.jethachan.factory_badges.sync;

import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.model.ConnectionSnapshot;
import net.jethachan.factory_badges.protocol.BuildInfoCodec;

final class BadgeSyncController implements AutoCloseable {
    interface Client {
        void connect();
        boolean writeState(BadgeState state);
        void disconnect();
        void close();
    }

    interface ClientEvents {
        void onConnected(
                long epoch,
                Client source,
                BuildInfo info,
                Integer batteryPercent);
        void onStateWriteAcknowledged(
                long epoch,
                Client source,
                BadgeState state,
                long elapsedRealtimeMs);
        void onDisconnected(long epoch, Client source, int status);
        void onError(long epoch, Client source, UserVisibleError error);
    }

    interface ClientFactory {
        Client create(long epoch, ClientEvents events);
    }

    static final class Selection {
        private final String name;
        private final String address;
        private final boolean bonded;
        private final ClientFactory clientFactory;

        Selection(
                String name,
                String address,
                boolean bonded,
                ClientFactory clientFactory) {
            if (address == null || address.trim().isEmpty()) {
                throw new IllegalArgumentException("address must not be blank");
            }
            if (clientFactory == null) {
                throw new IllegalArgumentException("clientFactory must not be null");
            }
            this.name = name;
            this.address = address;
            this.bonded = bonded;
            this.clientFactory = clientFactory;
        }

        String name() {
            return name;
        }

        String address() {
            return address;
        }

        boolean bonded() {
            return bonded;
        }

        ClientFactory clientFactory() {
            return clientFactory;
        }
    }

    interface Scheduler {
        interface Handle {
            void cancel();
        }

        Handle schedule(long delayMs, Runnable callback);
    }

    interface ForegroundLifetime {
        void start();
        void stop();
    }

    interface SnapshotSink {
        void publish(ConnectionSnapshot snapshot);
    }

    private final ReconnectPolicy reconnectPolicy;
    private final Scheduler scheduler;
    private final ForegroundLifetime foregroundLifetime;
    private final SnapshotSink snapshotSink;

    private BadgeState currentState = new BadgeState(0, 0, 1727L);
    private ConnectionSnapshot snapshot;
    private Selection selection;
    private boolean syncEnabled;
    private boolean closed;
    private boolean foregroundActive;
    private boolean currentBonded;
    private long clientEpoch;
    private long activeClientEpoch;
    private Client activeClient;
    private BuildInfo buildInfo;
    private Integer batteryPercent;
    private BadgeState lastAcknowledgedState;
    private Long lastAcknowledgedElapsedMs;
    private Long nextReconnectDelayMs;
    private UserVisibleError error;
    private BadgeState inFlight;
    private boolean pendingWrite;
    private boolean needsReadySend;
    private long lifecycleGeneration;
    private boolean generationExhausted;
    private RetryWork activeRetry;
    private final ClientEvents clientEvents = new ClientEvents() {
        @Override
        public void onConnected(
                long epoch,
                Client source,
                BuildInfo info,
                Integer reportedBatteryPercent) {
            handleConnected(epoch, source, info, reportedBatteryPercent);
        }


        @Override
        public void onStateWriteAcknowledged(
                long epoch,
                Client source,
                BadgeState state,
                long elapsedRealtimeMs) {
            handleAcknowledged(
                    epoch, source, state, elapsedRealtimeMs);
        }

        @Override
        public void onDisconnected(long epoch, Client source, int status) {
            handleDisconnected(epoch, source, status);
        }

        @Override
        public void onError(
                long epoch,
                Client source,
                UserVisibleError reportedError) {
            handleError(epoch, source, reportedError);
        }
    };

    private static final class RetryWork {
        final long lifecycleGeneration;
        Scheduler.Handle handle;

        RetryWork(long lifecycleGeneration) {
            this.lifecycleGeneration = lifecycleGeneration;
        }
    }

    BadgeSyncController(
            ReconnectPolicy reconnectPolicy,
            Scheduler scheduler,
            ForegroundLifetime foregroundLifetime,
            SnapshotSink snapshotSink) {
        if (reconnectPolicy == null) {
            throw new IllegalArgumentException("reconnectPolicy must not be null");
        }
        if (scheduler == null) {
            throw new IllegalArgumentException("scheduler must not be null");
        }
        if (foregroundLifetime == null) {
            throw new IllegalArgumentException("foregroundLifetime must not be null");
        }
        if (snapshotSink == null) {
            throw new IllegalArgumentException("snapshotSink must not be null");
        }
        this.reconnectPolicy = reconnectPolicy;
        this.scheduler = scheduler;
        this.foregroundLifetime = foregroundLifetime;
        this.snapshotSink = snapshotSink;
        snapshot = new ConnectionSnapshot(
                false,
                ConnectionSnapshot.Phase.DISABLED,
                null,
                null,
                false,
                currentState,
                null,
                null,
                null,
                null,
                null,
                null);
        snapshotSink.publish(snapshot);
    }

    void selectDevice(Selection selection) {
        requireMutable();
        if (selection == null) {
            throw new IllegalArgumentException("selection must not be null");
        }
        if (syncEnabled) {
            preflightClientEpochOrThrow();
        }
        advanceLifecycleOrThrow();
        cancelRetry();
        Client detached = detachClient();
        closeClient(detached);
        reconnectPolicy.reset();
        buildInfo = null;
        batteryPercent = null;
        lastAcknowledgedState = null;
        lastAcknowledgedElapsedMs = null;
        nextReconnectDelayMs = null;
        error = null;
        this.selection = selection;
        currentBonded = selection.bonded();
        if (syncEnabled) {
            beginAttempt(true);
        } else {
            publish(ConnectionSnapshot.Phase.DISABLED);
        }
    }

    void setCurrentState(BadgeState state) {
        requireMutable();
        if (state == null) {
            throw new IllegalArgumentException("state must not be null");
        }
        currentState = state;
        publish(snapshot.phase());
    }

    void setSyncEnabled(boolean enabled) {
        requireMutable();
        if (syncEnabled == enabled) {
            return;
        }
        if (enabled && selection != null) {
            preflightClientEpochOrThrow();
        }
        syncEnabled = enabled;
        if (enabled) {
            foregroundActive = true;
            foregroundLifetime.start();
            if (selection == null) {
                publish(ConnectionSnapshot.Phase.NO_DEVICE);
            } else {
                beginAttempt(true);
            }
        } else {
            advanceLifecycleOrThrow();
            cancelRetry();
            Client detached = detachClient();
            closeClient(detached);
            reconnectPolicy.reset();
            nextReconnectDelayMs = null;
            error = null;
            publish(ConnectionSnapshot.Phase.DISABLED);
            if (foregroundActive) {
                foregroundActive = false;
                foregroundLifetime.stop();
            }
        }
    }

    void syncNow() {
        requireMutable();
        if (snapshot.phase() == ConnectionSnapshot.Phase.READY) {
            requestWrite();
        } else {
            needsReadySend = true;
        }
    }

    ConnectionSnapshot snapshot() {
        return snapshot;
    }

    @Override
    public void close() {
        if (closed) {
            return;
        }
        if (generationExhausted) {
            closed = true;
            return;
        }
        advanceLifecycleOrThrow();
        cancelRetry();
        Client detached = detachClient();
        closed = true;
        syncEnabled = false;
        reconnectPolicy.reset();
        nextReconnectDelayMs = null;
        error = null;
        closeClient(detached);
        publish(ConnectionSnapshot.Phase.DISABLED);
        if (foregroundActive) {
            foregroundActive = false;
            foregroundLifetime.stop();
        }
    }

    private void preflightClientEpochOrThrow() {
        if (clientEpoch == Long.MAX_VALUE) {
            exhaustGeneration();
            throw generationExhaustedException();
        }
    }

    private void beginAttempt(boolean throwOnExhaustion) {
        if (clientEpoch == Long.MAX_VALUE) {
            exhaustGeneration();
            if (throwOnExhaustion) {
                throw generationExhaustedException();
            }
            return;
        }
        clientEpoch++;
        long epoch = clientEpoch;
        needsReadySend = true;
        inFlight = null;
        pendingWrite = false;
        publish(currentBonded
                ? ConnectionSnapshot.Phase.CONNECTING
                : ConnectionSnapshot.Phase.BONDING);

        Client client;
        try {
            client = selection.clientFactory().create(epoch, clientEvents);
        } catch (RuntimeException failure) {
            handleAdapterFailure();
            return;
        }
        if (client == null) {
            handleAdapterFailure();
            return;
        }

        activeClient = client;
        activeClientEpoch = epoch;
        try {
            client.connect();
        } catch (RuntimeException failure) {
            if (clientEligible(epoch, client)
                    && (snapshot.phase() == ConnectionSnapshot.Phase.BONDING
                    || snapshot.phase() == ConnectionSnapshot.Phase.CONNECTING)) {
                Client detached = detachClient();
                closeClient(detached);
                handleAdapterFailure();
            }
        }
    }

    private void handleConnected(
            long epoch,
            Client source,
            BuildInfo info,
            Integer reportedBatteryPercent) {
        if (!clientEligible(epoch, source)
                || (snapshot.phase() != ConnectionSnapshot.Phase.BONDING
                && snapshot.phase() != ConnectionSnapshot.Phase.CONNECTING)) {
            return;
        }
        currentBonded = true;
        if (info == null) {
            terminalize(new UserVisibleError(
                    UserVisibleError.Code.BUILD_INFO_INVALID));
            return;
        }
        if ((info.capabilities()
                & BuildInfoCodec.CAPABILITY_SEMANTIC_METRICS) == 0) {
            terminalize(new UserVisibleError(
                    UserVisibleError.Code.UNSUPPORTED_BADGE));
            return;
        }

        buildInfo = info;
        batteryPercent = normalizeBattery(reportedBatteryPercent);
        error = null;
        nextReconnectDelayMs = null;
        reconnectPolicy.reset();
        needsReadySend = false;
        publish(ConnectionSnapshot.Phase.READY);
        requestWrite();
    }

    private void handleAcknowledged(
            long epoch,
            Client source,
            BadgeState state,
            long elapsedRealtimeMs) {
        if (!clientEligible(epoch, source)
                || snapshot.phase() != ConnectionSnapshot.Phase.READY
                || inFlight == null
                || state == null
                || !inFlight.equals(state)
                || elapsedRealtimeMs < 0L) {
            return;
        }
        inFlight = null;
        lastAcknowledgedState = state;
        lastAcknowledgedElapsedMs = Long.valueOf(elapsedRealtimeMs);
        boolean sendPending = pendingWrite;
        pendingWrite = false;
        publish(ConnectionSnapshot.Phase.READY);
        if (sendPending) {
            requestWrite();
        }
    }

    private void handleDisconnected(long epoch, Client source, int status) {
        if (!clientEligible(epoch, source)) {
            return;
        }
        currentBonded = true;
        UserVisibleError disconnectedError = status < 0
                ? new UserVisibleError(UserVisibleError.Code.CONNECT_FAILED)
                : new UserVisibleError(
                        UserVisibleError.Code.CONNECT_FAILED, status);
        enterRetry(disconnectedError);
    }

    private void handleError(
            long epoch,
            Client source,
            UserVisibleError reportedError) {
        if (!clientEligible(epoch, source) || reportedError == null) {
            return;
        }
        inferBond(reportedError.code());
        if (reportedError.retryable()) {
            enterRetry(reportedError);
        } else {
            terminalize(reportedError);
        }
    }

    private void requestWrite() {
        if (snapshot.phase() != ConnectionSnapshot.Phase.READY
                || activeClient == null) {
            needsReadySend = true;
            return;
        }
        if (inFlight != null) {
            pendingWrite = true;
            return;
        }

        Client client = activeClient;
        long epoch = activeClientEpoch;
        BadgeState requested = currentState;
        inFlight = requested;
        boolean accepted;
        try {
            accepted = client.writeState(requested);
        } catch (RuntimeException failure) {
            accepted = false;
        }
        if (!clientEligible(epoch, client) || inFlight != requested) {
            return;
        }
        if (!accepted) {
            enterRetry(new UserVisibleError(
                    UserVisibleError.Code.STATE_WRITE_FAILED));
        }
    }

    private void enterRetry(UserVisibleError retryError) {
        Client detached = detachClient();
        closeClient(detached);
        currentBonded = true;
        error = retryError;
        nextReconnectDelayMs = Long.valueOf(reconnectPolicy.nextDelayMs());
        publish(ConnectionSnapshot.Phase.RETRY_WAIT);
        scheduleRetry(nextReconnectDelayMs.longValue());
    }

    private void scheduleRetry(long delayMs) {
        final RetryWork work = new RetryWork(lifecycleGeneration);
        activeRetry = work;
        Scheduler.Handle handle = scheduler.schedule(delayMs, new Runnable() {
            @Override
            public void run() {
                runRetry(work);
            }
        });
        work.handle = handle;
        if (handle == null) {
            activeRetry = null;
            terminalize(new UserVisibleError(
                    UserVisibleError.Code.CONNECT_FAILED));
        }
    }

    private void runRetry(RetryWork work) {
        if (closed
                || generationExhausted
                || !syncEnabled
                || selection == null
                || activeRetry != work
                || work.handle == null
                || work.lifecycleGeneration != lifecycleGeneration) {
            return;
        }
        activeRetry = null;
        error = null;
        nextReconnectDelayMs = null;
        buildInfo = null;
        batteryPercent = null;
        beginAttempt(false);
    }

    private void handleAdapterFailure() {
        if (currentBonded) {
            enterRetry(new UserVisibleError(
                    UserVisibleError.Code.CONNECT_FAILED));
        } else {
            terminalize(new UserVisibleError(
                    UserVisibleError.Code.BOND_START_FAILED));
        }
    }

    private void terminalize(UserVisibleError terminalError) {
        if (!tryAdvanceLifecycle()) {
            return;
        }
        cancelRetry();
        Client detached = detachClient();
        error = terminalError;
        nextReconnectDelayMs = null;
        closeClient(detached);
        publish(ConnectionSnapshot.Phase.ERROR);
    }

    private void inferBond(UserVisibleError.Code code) {
        switch (code) {
            case BOND_START_FAILED:
            case BOND_FAILED:
            case BOND_LOST:
                currentBonded = false;
                return;
            case BLUETOOTH_PERMISSION_MISSING:
            case BLUETOOTH_DISABLED:
                return;
            default:
                currentBonded = true;
        }
    }

    private void advanceLifecycleOrThrow() {
        if (!tryAdvanceLifecycle()) {
            throw generationExhaustedException();
        }
    }

    private boolean tryAdvanceLifecycle() {
        if (generationExhausted) {
            return false;
        }
        if (lifecycleGeneration == Long.MAX_VALUE) {
            exhaustGeneration();
            return false;
        }
        lifecycleGeneration++;
        return true;
    }

    private void exhaustGeneration() {
        if (generationExhausted) {
            return;
        }
        generationExhausted = true;
        syncEnabled = false;
        cancelRetry();
        Client detached = detachClient();
        error = null;
        nextReconnectDelayMs = null;
        closeClient(detached);
        if (foregroundActive) {
            foregroundActive = false;
            foregroundLifetime.stop();
        }
    }

    private static IllegalStateException generationExhaustedException() {
        return new IllegalStateException("controller generation exhausted");
    }

    private void cancelRetry() {
        RetryWork retry = activeRetry;
        activeRetry = null;
        if (retry != null && retry.handle != null) {
            retry.handle.cancel();
        }
    }

    private Client detachClient() {
        Client detached = activeClient;
        activeClient = null;
        activeClientEpoch = 0L;
        inFlight = null;
        pendingWrite = false;
        needsReadySend = false;
        return detached;
    }

    private static void closeClient(Client client) {
        if (client == null) {
            return;
        }
        try {
            client.disconnect();
        } catch (RuntimeException ignored) {
            // Teardown must still close a partially failed adapter.
        }
        try {
            client.close();
        } catch (RuntimeException ignored) {
            // Adapter exceptions never escape the pure state machine.
        }
    }


    private boolean clientEligible(long epoch, Client source) {
        return !closed
                && !generationExhausted
                && syncEnabled
                && epoch > 0L
                && epoch == activeClientEpoch
                && source == activeClient;
    }

    private static Integer normalizeBattery(Integer value) {
        if (value == null
                || value.intValue() < 0
                || value.intValue() > 100) {
            return null;
        }
        return value;
    }



    private void publish(ConnectionSnapshot.Phase phase) {
        String name = selection == null ? null : selection.name();
        String address = selection == null ? null : selection.address();
        boolean bonded = selection != null && currentBonded;
        if (phase == ConnectionSnapshot.Phase.NO_DEVICE) {
            name = null;
            address = null;
            bonded = false;
        }
        boolean canShowBuild = phase == ConnectionSnapshot.Phase.DISABLED
                || phase == ConnectionSnapshot.Phase.READY
                || phase == ConnectionSnapshot.Phase.RETRY_WAIT
                || phase == ConnectionSnapshot.Phase.ERROR;
        BuildInfo visibleBuild = canShowBuild ? buildInfo : null;
        Integer visibleBattery = visibleBuild == null ? null : batteryPercent;
        BadgeState visibleAcknowledgedState =
                address == null ? null : lastAcknowledgedState;
        Long visibleAcknowledgedElapsedMs =
                address == null ? null : lastAcknowledgedElapsedMs;
        Long visibleDelay = phase == ConnectionSnapshot.Phase.RETRY_WAIT
                ? nextReconnectDelayMs : null;
        UserVisibleError visibleError =
                phase == ConnectionSnapshot.Phase.RETRY_WAIT
                        || phase == ConnectionSnapshot.Phase.ERROR
                ? error : null;
        ConnectionSnapshot next = new ConnectionSnapshot(
                syncEnabled,
                phase,
                name,
                address,
                bonded,
                currentState,
                visibleBuild,
                visibleBattery,
                visibleAcknowledgedState,
                visibleAcknowledgedElapsedMs,
                visibleDelay,
                visibleError);
        if (!next.equals(snapshot)) {
            snapshot = next;
            snapshotSink.publish(next);
        }
    }

    private void requireMutable() {
        if (generationExhausted) {
            throw generationExhaustedException();
        }
        if (closed) {
            throw new IllegalStateException("controller is closed");
        }
    }
}
