package net.jethachan.factory_badges.ui;

import java.util.Objects;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.model.ConnectionSnapshot;

final class MainUiPresenter implements AutoCloseable {
    enum CommandResult {
        ACCEPTED,
        SERVICE_UNAVAILABLE,
        BLUETOOTH_PERMISSION_REQUIRED,
        SYNC_START_FAILED
    }

    interface Host {
        void render(ViewState state);
        CommandResult publishState(BadgeState state);
        void requestBluetoothPermissions();
        void beginBadgeScan();
        CommandResult startForegroundSync();
        CommandResult requestSyncNow();
        CommandResult requestStopSync();
    }

    enum StatusKind {
        SERVICE_CONNECTING,
        SERVICE_UNAVAILABLE,
        SYNC_OFF,
        NO_DEVICE,
        BONDING,
        CONNECTING,
        DISCOVERING,
        VALIDATING_BUILD,
        READY,
        RETRYING,
        ERROR
    }

    enum GuidanceKind {
        WAIT_FOR_SERVICE,
        CHOOSE_BADGE,
        HOLD_SYNC_PAIR,
        WAIT_FOR_CONNECTION,
        ADJUST_AND_SYNC,
        RETRYING_AUTOMATICALLY,
        STOP_FIX_AND_RETRY
    }

    enum SyncButtonKind { START_SYNC, SYNC_NOW }

    enum ProblemKind {
        NONE,
        BLUETOOTH_PERMISSION_REQUIRED,
        BLUETOOTH_OFF,
        NO_BADGE_FOUND,
        SCAN_FAILED,
        SERVICE_UNAVAILABLE,
        SYNC_START_FAILED
    }

    static final class Environment {
        private final boolean scanPermissionGranted;
        private final boolean connectPermissionGranted;
        private final boolean notificationPermissionGranted;
        private final boolean bluetoothEnabled;
        private final boolean scanning;

        Environment(boolean scanPermissionGranted, boolean connectPermissionGranted,
                boolean notificationPermissionGranted, boolean bluetoothEnabled,
                boolean scanning) {
            this.scanPermissionGranted = scanPermissionGranted;
            this.connectPermissionGranted = connectPermissionGranted;
            this.notificationPermissionGranted = notificationPermissionGranted;
            this.bluetoothEnabled = bluetoothEnabled;
            this.scanning = scanning;
        }

        boolean scanPermissionGranted() { return scanPermissionGranted; }
        boolean connectPermissionGranted() { return connectPermissionGranted; }
        boolean notificationPermissionGranted() { return notificationPermissionGranted; }
        boolean bluetoothEnabled() { return bluetoothEnabled; }
        boolean scanning() { return scanning; }

        @Override public boolean equals(Object other) {
            if (this == other) return true;
            if (!(other instanceof Environment)) return false;
            Environment that = (Environment) other;
            return scanPermissionGranted == that.scanPermissionGranted
                    && connectPermissionGranted == that.connectPermissionGranted
                    && notificationPermissionGranted == that.notificationPermissionGranted
                    && bluetoothEnabled == that.bluetoothEnabled
                    && scanning == that.scanning;
        }

        @Override public int hashCode() {
            return Objects.hash(scanPermissionGranted, connectPermissionGranted,
                    notificationPermissionGranted, bluetoothEnabled, scanning);
        }
    }

    static final class ViewState {
        private final BadgeState state;
        private final StatusKind statusKind;
        private final GuidanceKind guidanceKind;
        private final SyncButtonKind syncButtonKind;
        private final ProblemKind localProblem;
        private final String selectedDeviceName;
        private final String selectedDeviceAddress;
        private final boolean bonded;
        private final BuildInfo buildInfo;
        private final Integer batteryPercent;
        private final UserVisibleError connectionError;
        private final Long nextReconnectDelayMs;
        private final BadgeState lastAcknowledgedState;
        private final boolean currentStateAcknowledged;
        private final boolean notificationPermissionWarning;
        private final boolean chooseBadgeButtonEnabled;
        private final boolean syncButtonEnabled;
        private final boolean stopButtonEnabled;
        private final boolean scanning;

        ViewState(BadgeState state, StatusKind statusKind, GuidanceKind guidanceKind,
                SyncButtonKind syncButtonKind, ProblemKind localProblem,
                String selectedDeviceName, String selectedDeviceAddress, boolean bonded,
                BuildInfo buildInfo, Integer batteryPercent, UserVisibleError connectionError,
                Long nextReconnectDelayMs, BadgeState lastAcknowledgedState,
                boolean currentStateAcknowledged, boolean notificationPermissionWarning,
                boolean chooseBadgeButtonEnabled, boolean syncButtonEnabled,
                boolean stopButtonEnabled, boolean scanning) {
            this.state = state;
            this.statusKind = statusKind;
            this.guidanceKind = guidanceKind;
            this.syncButtonKind = syncButtonKind;
            this.localProblem = localProblem;
            this.selectedDeviceName = selectedDeviceName;
            this.selectedDeviceAddress = selectedDeviceAddress;
            this.bonded = bonded;
            this.buildInfo = buildInfo;
            this.batteryPercent = batteryPercent;
            this.connectionError = connectionError;
            this.nextReconnectDelayMs = nextReconnectDelayMs;
            this.lastAcknowledgedState = lastAcknowledgedState;
            this.currentStateAcknowledged = currentStateAcknowledged;
            this.notificationPermissionWarning = notificationPermissionWarning;
            this.chooseBadgeButtonEnabled = chooseBadgeButtonEnabled;
            this.syncButtonEnabled = syncButtonEnabled;
            this.stopButtonEnabled = stopButtonEnabled;
            this.scanning = scanning;
        }

        int dayPercent() { return state.dayPercent(); }
        int weekPercent() { return state.weekPercent(); }
        long creditCents() { return state.creditCents(); }
        StatusKind statusKind() { return statusKind; }
        GuidanceKind guidanceKind() { return guidanceKind; }
        SyncButtonKind syncButtonKind() { return syncButtonKind; }
        ProblemKind localProblem() { return localProblem; }
        String selectedDeviceName() { return selectedDeviceName; }
        String selectedDeviceAddress() { return selectedDeviceAddress; }
        boolean bonded() { return bonded; }
        BuildInfo buildInfo() { return buildInfo; }
        Integer batteryPercent() { return batteryPercent; }
        UserVisibleError connectionError() { return connectionError; }
        Long nextReconnectDelayMs() { return nextReconnectDelayMs; }
        BadgeState lastAcknowledgedState() { return lastAcknowledgedState; }
        boolean currentStateAcknowledged() { return currentStateAcknowledged; }
        boolean notificationPermissionWarning() { return notificationPermissionWarning; }
        boolean chooseBadgeButtonEnabled() { return chooseBadgeButtonEnabled; }
        boolean syncButtonEnabled() { return syncButtonEnabled; }
        boolean stopButtonEnabled() { return stopButtonEnabled; }
        boolean scanning() { return scanning; }

        @Override public boolean equals(Object other) {
            if (this == other) return true;
            if (!(other instanceof ViewState)) return false;
            ViewState that = (ViewState) other;
            return bonded == that.bonded
                    && currentStateAcknowledged == that.currentStateAcknowledged
                    && notificationPermissionWarning == that.notificationPermissionWarning
                    && chooseBadgeButtonEnabled == that.chooseBadgeButtonEnabled
                    && syncButtonEnabled == that.syncButtonEnabled
                    && stopButtonEnabled == that.stopButtonEnabled
                    && scanning == that.scanning
                    && state.equals(that.state)
                    && statusKind == that.statusKind
                    && guidanceKind == that.guidanceKind
                    && syncButtonKind == that.syncButtonKind
                    && localProblem == that.localProblem
                    && Objects.equals(selectedDeviceName, that.selectedDeviceName)
                    && Objects.equals(selectedDeviceAddress, that.selectedDeviceAddress)
                    && Objects.equals(buildInfo, that.buildInfo)
                    && Objects.equals(batteryPercent, that.batteryPercent)
                    && Objects.equals(connectionError, that.connectionError)
                    && Objects.equals(nextReconnectDelayMs, that.nextReconnectDelayMs)
                    && Objects.equals(lastAcknowledgedState, that.lastAcknowledgedState);
        }

        @Override public int hashCode() {
            return Objects.hash(state, statusKind, guidanceKind, syncButtonKind, localProblem,
                    selectedDeviceName, selectedDeviceAddress, bonded, buildInfo, batteryPercent,
                    connectionError, nextReconnectDelayMs, lastAcknowledgedState,
                    currentStateAcknowledged, notificationPermissionWarning,
                    chooseBadgeButtonEnabled, syncButtonEnabled, stopButtonEnabled, scanning);
        }
    }

    private final Host host;
    private BadgeState currentState;
    private ConnectionSnapshot snapshot;
    private Environment environment = new Environment(false, false, false, false, false);
    private ViewState viewState;
    private ProblemKind localProblem = ProblemKind.NONE;
    private boolean bound;
    private boolean bindFailure;
    private boolean localAuthoritative;
    private boolean successfulBindSeen;
    private boolean startPending;
    private boolean closed;

    MainUiPresenter(Host host, BadgeState restoredStateOrNull) {
        if (host == null) throw new IllegalArgumentException("host must not be null");
        this.host = host;
        currentState = restoredStateOrNull == null
                ? new BadgeState(0, 0, 1727L) : restoredStateOrNull;
        localAuthoritative = restoredStateOrNull != null;
        snapshot = disabledSnapshot(currentState);
        publishView();
    }

    static BadgeState decodeRestoredState(boolean dayPresent, Object dayValue,
            boolean weekPresent, Object weekValue) {
        if (!dayPresent || !weekPresent
                || !(dayValue instanceof Integer) || !(weekValue instanceof Integer)) {
            return null;
        }
        int day = ((Integer) dayValue).intValue();
        int week = ((Integer) weekValue).intValue();
        if (day < 0 || day > 100 || week < 0 || week > 100) return null;
        return new BadgeState(day, week, 1727L);
    }

    void onEnvironment(Environment updated) {
        if (closed) return;
        if (updated == null) throw new IllegalArgumentException("environment must not be null");
        environment = updated;
        if (localProblem == ProblemKind.BLUETOOTH_PERMISSION_REQUIRED
                && updated.scanPermissionGranted() && updated.connectPermissionGranted()) {
            localProblem = ProblemKind.NONE;
        } else if (localProblem == ProblemKind.BLUETOOTH_OFF && updated.bluetoothEnabled()) {
            localProblem = ProblemKind.NONE;
        }
        publishView();
    }

    void onServiceBinding() {
        if (closed) return;
        bound = false;
        startPending = false;
        bindFailure = false;
        localProblem = ProblemKind.NONE;
        publishView();
    }

    void onServiceBound(ConnectionSnapshot updated) {
        if (closed) return;
        requireSnapshot(updated);
        bound = true;
        snapshot = updated;
        if (updated.syncEnabled()) startPending = false;
        if (bindFailure) {
            bindFailure = false;
            if (localProblem == ProblemKind.SERVICE_UNAVAILABLE) {
                localProblem = ProblemKind.NONE;
            }
        }
        if (!successfulBindSeen && !localAuthoritative) {
            currentState = updated.currentState();
        } else if (!currentState.equals(updated.currentState())) {
            mapPublishResult(host.publishState(currentState));
        }
        successfulBindSeen = true;
        localAuthoritative = true;
        clearReadyTransient(updated);
        publishView();
    }

    void onServiceUnbound() {
        if (closed) return;
        bound = false;
        startPending = false;
        bindFailure = false;
        localProblem = ProblemKind.NONE;
        publishView();
    }

    void onServiceBindFailed() {
        if (closed) return;
        bound = false;
        startPending = false;
        bindFailure = true;
        localProblem = ProblemKind.SERVICE_UNAVAILABLE;
        publishView();
    }

    void onSnapshot(ConnectionSnapshot updated) {
        if (closed) return;
        requireSnapshot(updated);
        snapshot = updated;
        if (updated.syncEnabled()) startPending = false;
        clearReadyTransient(updated);
        publishView();
    }

    void onDayChanged(int percent) {
        if (closed) return;
        requirePercent(percent);
        if (percent == currentState.dayPercent()) return;
        currentState = new BadgeState(percent, currentState.weekPercent(), 1727L);
        localAuthoritative = true;
        publishView();
        if (bound) {
            mapPublishResult(host.publishState(currentState));
            publishView();
        }
    }

    void onWeekChanged(int percent) {
        if (closed) return;
        requirePercent(percent);
        if (percent == currentState.weekPercent()) return;
        currentState = new BadgeState(currentState.dayPercent(), percent, 1727L);
        localAuthoritative = true;
        publishView();
        if (bound) {
            mapPublishResult(host.publishState(currentState));
            publishView();
        }
    }

    void onChooseBadgePressed() {
        if (closed) return;
        if (!bound) {
            localProblem = ProblemKind.SERVICE_UNAVAILABLE;
            publishView();
            return;
        }
        if (!nearbyGranted()) {
            localProblem = ProblemKind.BLUETOOTH_PERMISSION_REQUIRED;
            publishView();
            host.requestBluetoothPermissions();
            return;
        }
        if (!environment.bluetoothEnabled()) {
            localProblem = ProblemKind.BLUETOOTH_OFF;
            publishView();
            return;
        }
        if (environment.scanning()) return;
        if (localProblem == ProblemKind.BLUETOOTH_PERMISSION_REQUIRED
                || localProblem == ProblemKind.BLUETOOTH_OFF
                || localProblem == ProblemKind.NO_BADGE_FOUND
                || localProblem == ProblemKind.SCAN_FAILED) {
            localProblem = ProblemKind.NONE;
            publishView();
        }
        host.beginBadgeScan();
    }

    void onSyncPressed() {
        if (closed || !syncButtonEligible()) return;
        if (!nearbyGranted()) {
            localProblem = ProblemKind.BLUETOOTH_PERMISSION_REQUIRED;
            publishView();
            host.requestBluetoothPermissions();
            return;
        }
        if (!environment.bluetoothEnabled()) {
            localProblem = ProblemKind.BLUETOOTH_OFF;
            publishView();
            return;
        }
        if (localProblem == ProblemKind.SYNC_START_FAILED) {
            localProblem = ProblemKind.NONE;
            publishView();
        }
        if (!mapPublishResult(host.publishState(currentState))) {
            publishView();
            return;
        }
        if (snapshot.phase() == ConnectionSnapshot.Phase.DISABLED) {
            startPending = true;
            publishView();
            CommandResult result = host.startForegroundSync();
            if (!validStart(result)) {
                startPending = false;
                mapStartResult(result);
                publishView();
            }
        } else {
            mapSimpleResult(host.requestSyncNow());
            publishView();
        }
    }

    void onStopPressed() {
        if (closed || !bound || !snapshot.syncEnabled()) return;
        mapSimpleResult(host.requestStopSync());
        publishView();
    }

    void onScanEnded(boolean foundAny) {
        if (closed) return;
        if (!foundAny) {
            localProblem = ProblemKind.NO_BADGE_FOUND;
        } else if (localProblem == ProblemKind.NO_BADGE_FOUND
                || localProblem == ProblemKind.SCAN_FAILED) {
            localProblem = ProblemKind.NONE;
        }
        publishView();
    }

    void onScanFailed(ProblemKind problem) {
        if (closed) return;
        if (problem != ProblemKind.BLUETOOTH_PERMISSION_REQUIRED
                && problem != ProblemKind.BLUETOOTH_OFF
                && problem != ProblemKind.SCAN_FAILED) {
            throw new IllegalArgumentException("invalid scanner problem");
        }
        localProblem = problem;
        publishView();
    }

    void onCommandFailed(CommandResult result) {
        if (closed) return;
        localProblem = result == CommandResult.BLUETOOTH_PERMISSION_REQUIRED
                ? ProblemKind.BLUETOOTH_PERMISSION_REQUIRED
                : ProblemKind.SERVICE_UNAVAILABLE;
        publishView();
    }

    BadgeState currentState() { return currentState; }
    ViewState viewState() { return viewState; }

    @Override public void close() { closed = true; }

    private boolean nearbyGranted() {
        return environment.scanPermissionGranted() && environment.connectPermissionGranted();
    }

    private boolean syncButtonEligible() {
        ConnectionSnapshot.Phase phase = snapshot.phase();
        return bound && !startPending && snapshot.selectedDeviceAddress() != null
                && (phase == ConnectionSnapshot.Phase.DISABLED
                        || phase == ConnectionSnapshot.Phase.READY);
    }

    private boolean mapPublishResult(CommandResult result) {
        if (result == CommandResult.ACCEPTED) return true;
        localProblem = ProblemKind.SERVICE_UNAVAILABLE;
        return false;
    }

    private void mapSimpleResult(CommandResult result) {
        if (result != CommandResult.ACCEPTED) {
            localProblem = ProblemKind.SERVICE_UNAVAILABLE;
        }
    }

    private boolean validStart(CommandResult result) {
        return result == CommandResult.ACCEPTED;
    }

    private void mapStartResult(CommandResult result) {
        if (result == CommandResult.BLUETOOTH_PERMISSION_REQUIRED) {
            localProblem = ProblemKind.BLUETOOTH_PERMISSION_REQUIRED;
        } else if (result == CommandResult.SYNC_START_FAILED) {
            localProblem = ProblemKind.SYNC_START_FAILED;
        } else {
            localProblem = ProblemKind.SERVICE_UNAVAILABLE;
        }
    }

    private void clearReadyTransient(ConnectionSnapshot updated) {
        if (updated.phase() == ConnectionSnapshot.Phase.READY
                && (localProblem == ProblemKind.NO_BADGE_FOUND
                        || localProblem == ProblemKind.SCAN_FAILED
                        || localProblem == ProblemKind.SYNC_START_FAILED)) {
            localProblem = ProblemKind.NONE;
        }
    }

    private void publishView() {
        StatusKind status;
        GuidanceKind guidance;
        if (!bound) {
            status = bindFailure ? StatusKind.SERVICE_UNAVAILABLE : StatusKind.SERVICE_CONNECTING;
            guidance = GuidanceKind.WAIT_FOR_SERVICE;
        } else {
            status = statusFor(snapshot.phase());
            guidance = guidanceFor(snapshot);
        }
        SyncButtonKind buttonKind = snapshot.syncEnabled()
                ? SyncButtonKind.SYNC_NOW : SyncButtonKind.START_SYNC;
        BadgeState acknowledged = snapshot.lastAcknowledgedState();
        ViewState next = new ViewState(currentState, status, guidance, buttonKind, localProblem,
                snapshot.selectedDeviceName(), snapshot.selectedDeviceAddress(), snapshot.bonded(),
                snapshot.buildInfo(), snapshot.batteryPercent(), snapshot.error(),
                snapshot.nextReconnectDelayMs(), acknowledged,
                acknowledged != null && acknowledged.equals(currentState),
                !environment.notificationPermissionGranted(),
                bound && !environment.scanning(), syncButtonEligible(),
                bound && snapshot.syncEnabled(), environment.scanning());
        if (!next.equals(viewState)) {
            viewState = next;
            host.render(next);
        }
    }

    private static StatusKind statusFor(ConnectionSnapshot.Phase phase) {
        switch (phase) {
            case DISABLED:
                return StatusKind.SYNC_OFF;
            case NO_DEVICE:
                return StatusKind.NO_DEVICE;
            case BONDING:
                return StatusKind.BONDING;
            case CONNECTING:
                return StatusKind.CONNECTING;
            case DISCOVERING:
                return StatusKind.DISCOVERING;
            case VALIDATING_BUILD:
                return StatusKind.VALIDATING_BUILD;
            case READY:
                return StatusKind.READY;
            case RETRY_WAIT:
                return StatusKind.RETRYING;
            case ERROR:
                return StatusKind.ERROR;
            default:
                throw new AssertionError("unhandled phase");
        }
    }

    private static GuidanceKind guidanceFor(ConnectionSnapshot value) {
        switch (value.phase()) {
            case DISABLED:
                return value.selectedDeviceAddress() == null
                        ? GuidanceKind.CHOOSE_BADGE : GuidanceKind.ADJUST_AND_SYNC;
            case NO_DEVICE:
                return GuidanceKind.CHOOSE_BADGE;
            case BONDING:
                return GuidanceKind.HOLD_SYNC_PAIR;
            case CONNECTING:
            case DISCOVERING:
            case VALIDATING_BUILD:
                return GuidanceKind.WAIT_FOR_CONNECTION;
            case READY:
                return GuidanceKind.ADJUST_AND_SYNC;
            case RETRY_WAIT:
                return GuidanceKind.RETRYING_AUTOMATICALLY;
            case ERROR:
                return GuidanceKind.STOP_FIX_AND_RETRY;
            default:
                throw new AssertionError("unhandled phase");
        }
    }

    private static void requireSnapshot(ConnectionSnapshot value) {
        if (value == null) throw new IllegalArgumentException("snapshot must not be null");
    }

    private static void requirePercent(int value) {
        if (value < 0 || value > 100) {
            throw new IllegalArgumentException("percent must be in 0..100");
        }
    }

    private static ConnectionSnapshot disabledSnapshot(BadgeState state) {
        return new ConnectionSnapshot(false, ConnectionSnapshot.Phase.DISABLED,
                null, null, false, state, null, null, null, null, null, null);
    }
}
