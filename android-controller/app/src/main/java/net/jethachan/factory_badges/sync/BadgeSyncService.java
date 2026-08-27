package net.jethachan.factory_badges.sync;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.bluetooth.BluetoothDevice;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Binder;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import java.util.ArrayList;
import java.util.List;
import net.jethachan.factory_badges.R;
import net.jethachan.factory_badges.ble.normal.NormalGattClient;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.model.ConnectionSnapshot;

final class BadgeSyncServiceRuntime {
    static final int START_NOT_STICKY_RESULT = 2;
    static final String ACTION_ENABLE =
            "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC";
    static final String ACTION_DISABLE =
            "net.jethachan.factory_badges.action.DISABLE_BADGE_SYNC";

    enum NotificationKind {
        WAITING,
        CONNECTING,
        READY,
        RETRY,
        ERROR
    }

    interface BlePoster {
        boolean post(Runnable task);
    }

    interface MainPoster {
        boolean isMainThread();
        boolean post(Runnable task);
    }

    interface ForegroundPort {
        void promote(NotificationKind kind);
        void update(NotificationKind kind);
        void stop();
    }

    interface SnapshotDelivery {
        void deliver(ConnectionSnapshot snapshot);
    }

    interface DestroyPort {
        void closeController();
        void quitBleThreadSafely();
    }

    private final Object lock = new Object();
    private final BlePoster blePoster;
    private final MainPoster mainPoster;
    private final ForegroundPort foregroundPort;

    private volatile ConnectionSnapshot latestSnapshot;
    private long lifecycleToken = 1L;
    private long foregroundGeneration = 1L;
    private long listenerToken;
    private boolean workerUnavailable;
    private boolean destroyed;
    private boolean generationExhausted;
    private boolean foregroundDesired;
    private boolean exhaustionStopPending;
    private boolean foregroundPromoted;
    private final List<Registration> listeners =
            new ArrayList<Registration>();

    private static final class MainAttempt {
        volatile boolean accepted;
    }

    private static final class Registration {
        final Object identity;
        final long token;
        final SnapshotDelivery delivery;

        Registration(
                Object identity, long token, SnapshotDelivery delivery) {
            this.identity = identity;
            this.token = token;
            this.delivery = delivery;
        }
    }

    BadgeSyncServiceRuntime(
            ConnectionSnapshot initialSnapshot,
            BlePoster blePoster,
            MainPoster mainPoster,
            ForegroundPort foregroundPort) {
        if (initialSnapshot == null) {
            throw new IllegalArgumentException("initialSnapshot must not be null");
        }
        if (blePoster == null) {
            throw new IllegalArgumentException("blePoster must not be null");
        }
        if (mainPoster == null) {
            throw new IllegalArgumentException("mainPoster must not be null");
        }
        if (foregroundPort == null) {
            throw new IllegalArgumentException("foregroundPort must not be null");
        }
        this.latestSnapshot = initialSnapshot;
        this.blePoster = blePoster;
        this.mainPoster = mainPoster;
        this.foregroundPort = foregroundPort;
    }

    int onStartCommand(
            String action,
            Runnable enableMutation,
            Runnable disableMutation) {
        requireMutation(enableMutation);
        requireMutation(disableMutation);
        if (!ACTION_ENABLE.equals(action) && !ACTION_DISABLE.equals(action)) {
            return START_NOT_STICKY_RESULT;
        }
        boolean exhausted = false;
        synchronized (lock) {
            if (destroyed || workerUnavailable || generationExhausted) {
                return START_NOT_STICKY_RESULT;
            }
            if (lifecycleToken == Long.MAX_VALUE
                    || (ACTION_ENABLE.equals(action)
                    && foregroundGeneration == Long.MAX_VALUE)) {
                markGenerationExhaustedLocked();
                exhausted = true;
            }
        }
        if (exhausted) {
            requestExhaustionStop();
            return START_NOT_STICKY_RESULT;
        }

        if (ACTION_ENABLE.equals(action) && !promoteForEnableAction()) {
            return START_NOT_STICKY_RESULT;
        }
        Runnable mutation = ACTION_ENABLE.equals(action)
                ? enableMutation : disableMutation;
        if (!postOrdinaryBle(mutation)) {
            stopAfterRejectedAction();
        }
        return START_NOT_STICKY_RESULT;
    }
    void onControllerForegroundStart() {
        long generation = -1L;
        NotificationKind kind = null;
        boolean exhausted = false;
        synchronized (lock) {
            if (destroyed || workerUnavailable || generationExhausted
                    || foregroundDesired) {
                return;
            }
            long next = advanceGenerationLocked(foregroundGeneration);
            if (next < 0L) {
                exhausted = true;
            } else {
                foregroundGeneration = next;
                foregroundDesired = true;
                if (foregroundPromoted) {
                    return;
                }
                generation = foregroundGeneration;
                kind = kindFor(latestSnapshot);
            }
        }
        if (exhausted) {
            requestExhaustionStop();
            return;
        }
        final long capturedGeneration = generation;
        final NotificationKind capturedKind = kind;
        final MainAttempt attempt = new MainAttempt();
        boolean accepted = mainPoster.post(new Runnable() {
            @Override
            public void run() {
                if (!attempt.accepted) {
                    return;
                }
                synchronized (lock) {
                    if (destroyed
                            || workerUnavailable
                            || generationExhausted
                            || !foregroundDesired
                            || foregroundPromoted
                            || foregroundGeneration != capturedGeneration) {
                        return;
                    }
                    foregroundPromoted = true;
                    foregroundPort.promote(capturedKind);
                }
            }
        });
        attempt.accepted = accepted;
        if (!accepted) {
            invalidateRejectedForegroundPost(capturedGeneration, true);
        }
    }

    void onControllerForegroundStop() {
        long generation = -1L;
        boolean exhausted = false;
        synchronized (lock) {
            if (destroyed || generationExhausted || !foregroundDesired) {
                return;
            }
            long next = advanceGenerationLocked(foregroundGeneration);
            if (next < 0L) {
                exhausted = true;
            } else {
                foregroundGeneration = next;
                foregroundDesired = false;
                if (!foregroundPromoted) {
                    return;
                }
                generation = foregroundGeneration;
            }
        }
        if (exhausted) {
            requestExhaustionStop();
            return;
        }
        final long capturedGeneration = generation;
        final MainAttempt attempt = new MainAttempt();
        boolean accepted = mainPoster.post(new Runnable() {
            @Override
            public void run() {
                if (!attempt.accepted) {
                    return;
                }
                synchronized (lock) {
                    if (destroyed
                            || generationExhausted
                            || foregroundDesired
                            || !foregroundPromoted
                            || foregroundGeneration != capturedGeneration) {
                        return;
                    }
                    foregroundPromoted = false;
                    foregroundPort.stop();
                }
            }
        });
        attempt.accepted = accepted;
        if (!accepted) {
            invalidateRejectedForegroundPost(capturedGeneration, false);
        }
    }

    void onSnapshot(ConnectionSnapshot receivedSnapshot) {
        if (receivedSnapshot == null) {
            throw new IllegalArgumentException("snapshot must not be null");
        }
        latestSnapshot = receivedSnapshot;
        final long generation;
        final NotificationKind kind;
        final boolean updateForeground;
        final List<Registration> capturedListeners;
        synchronized (lock) {
            generation = foregroundGeneration;
            updateForeground = !destroyed
                    && !generationExhausted
                    && foregroundDesired;
            kind = updateForeground ? kindFor(receivedSnapshot) : null;
            capturedListeners = destroyed || generationExhausted
                    ? new ArrayList<Registration>()
                    : new ArrayList<Registration>(listeners);
        }
        if (updateForeground) {
            final MainAttempt attempt = new MainAttempt();
            boolean accepted = mainPoster.post(new Runnable() {
                @Override
                public void run() {
                    if (!attempt.accepted) {
                        return;
                    }
                    synchronized (lock) {
                        if (destroyed
                                || generationExhausted
                                || !foregroundDesired
                                || !foregroundPromoted
                                || foregroundGeneration != generation) {
                            return;
                        }
                        foregroundPort.update(kind);
                    }
                }
            });
            attempt.accepted = accepted;
            if (!accepted) {
                invalidateRejectedForegroundPost(generation, false);
            }
        }
        for (Registration registration : capturedListeners) {
            postDelivery(registration, receivedSnapshot);
        }
    }

    ConnectionSnapshot latestSnapshot() {
        return latestSnapshot;
    }

    void addSnapshotListener(
            Object identity, SnapshotDelivery delivery) {
        if (identity == null) {
            throw new IllegalArgumentException("identity must not be null");
        }
        if (delivery == null) {
            throw new IllegalArgumentException("delivery must not be null");
        }
        requireMainThread();
        Registration registration = null;
        ConnectionSnapshot current = null;
        boolean exhausted = false;
        synchronized (lock) {
            requireListenerAvailable();
            if (registrationFor(identity) != null) {
                return;
            }
            long next = advanceGenerationLocked(listenerToken);
            if (next < 0L) {
                exhausted = true;
            } else {
                listenerToken = next;
                registration = new Registration(
                        identity, listenerToken, delivery);
                listeners.add(registration);
                current = latestSnapshot;
            }
        }
        if (exhausted) {
            requestExhaustionStop();
            throw generationExhaustedFailure();
        }
        final Registration addedRegistration = registration;
        if (!postDelivery(addedRegistration, current)) {
            synchronized (lock) {
                listeners.remove(addedRegistration);
            }
            throw new IllegalStateException("main thread is unavailable");
        }
    }

    void removeSnapshotListener(Object identity) {
        if (identity == null) {
            throw new IllegalArgumentException("identity must not be null");
        }
        requireMainThread();
        synchronized (lock) {
            requireListenerAvailable();
            Registration registration = registrationFor(identity);
            if (registration != null) {
                listeners.remove(registration);
            }
        }
    }

    void destroy(final DestroyPort destroyPort) {
        if (destroyPort == null) {
            throw new IllegalArgumentException("destroyPort must not be null");
        }
        if (!mainPoster.isMainThread()) {
            throw new IllegalStateException("destroy requires main thread");
        }
        final boolean stopForeground;
        synchronized (lock) {
            if (destroyed) {
                return;
            }
            destroyed = true;
            workerUnavailable = true;
            if (lifecycleToken < Long.MAX_VALUE) {
                lifecycleToken++;
            }
            if (foregroundGeneration < Long.MAX_VALUE) {
                foregroundGeneration++;
            }
            foregroundDesired = false;
            stopForeground = foregroundPromoted;
            foregroundPromoted = false;
            exhaustionStopPending = false;
            listeners.clear();
        }
        if (stopForeground) {
            foregroundPort.stop();
        }
        boolean accepted = blePoster.post(new Runnable() {
            @Override
            public void run() {
                try {
                    destroyPort.closeController();
                } finally {
                    destroyPort.quitBleThreadSafely();
                }
            }
        });
        if (!accepted) {
            destroyPort.quitBleThreadSafely();
        }
    }

    void postBinderMutation(Runnable mutation) {
        requireMutation(mutation);
        synchronized (lock) {
            if (generationExhausted) {
                throw generationExhaustedFailure();
            }
            if (destroyed || workerUnavailable) {
                throw workerUnavailableFailure();
            }
        }
        if (!postOrdinaryBle(mutation)) {
            synchronized (lock) {
                if (generationExhausted) {
                    throw generationExhaustedFailure();
                }
            }
            throw workerUnavailableFailure();
        }
    }

    private boolean promoteForEnableAction() {
        NotificationKind kind = null;
        boolean exhausted = false;
        synchronized (lock) {
            if (destroyed || workerUnavailable || generationExhausted) {
                return false;
            }
            if (foregroundGeneration == Long.MAX_VALUE) {
                markGenerationExhaustedLocked();
                exhausted = true;
            } else if (!foregroundDesired) {
                foregroundGeneration =
                        advanceGenerationLocked(foregroundGeneration);
                foregroundDesired = true;
            }
            if (!exhausted && foregroundPromoted) {
                return true;
            }
            if (!exhausted) {
                foregroundPromoted = true;
                kind = kindFor(latestSnapshot);
            }
        }
        if (exhausted) {
            requestExhaustionStop();
            return false;
        }
        foregroundPort.promote(kind);
        return true;
    }

    private void stopAfterRejectedAction() {
        boolean stop = false;
        boolean exhausted = false;
        synchronized (lock) {
            if (generationExhausted) {
                exhausted = true;
            } else if (foregroundDesired) {
                long next = advanceGenerationLocked(foregroundGeneration);
                if (next < 0L) {
                    exhausted = true;
                } else {
                    foregroundGeneration = next;
                }
            }
            if (!exhausted) {
                foregroundDesired = false;
                stop = foregroundPromoted;
                foregroundPromoted = false;
            }
        }
        if (exhausted) {
            requestExhaustionStop();
        } else if (stop) {
            foregroundPort.stop();
        }
    }

    private boolean postOrdinaryBle(Runnable mutation) {
        long capturedToken = -1L;
        boolean exhausted = false;
        synchronized (lock) {
            if (destroyed || workerUnavailable || generationExhausted) {
                return false;
            }
            if (lifecycleToken == Long.MAX_VALUE) {
                markGenerationExhaustedLocked();
                exhausted = true;
            } else {
                capturedToken = lifecycleToken;
            }
        }
        if (exhausted) {
            requestExhaustionStop();
            return false;
        }
        final long postedToken = capturedToken;
        boolean accepted = blePoster.post(new Runnable() {
            @Override
            public void run() {
                synchronized (lock) {
                    if (destroyed
                            || workerUnavailable
                            || generationExhausted
                            || postedToken != lifecycleToken) {
                        return;
                    }
                    mutation.run();
                }
            }
        });
        if (!accepted) {
            synchronized (lock) {
                if (!destroyed
                        && !workerUnavailable
                        && !generationExhausted
                        && postedToken == lifecycleToken) {
                    workerUnavailable = true;
                    lifecycleToken =
                            advanceGenerationLocked(lifecycleToken);
                }
            }
        }
        return accepted;
    }

    private static NotificationKind kindFor(ConnectionSnapshot snapshot) {
        ConnectionSnapshot.Phase phase = snapshot.phase();
        if (phase == ConnectionSnapshot.Phase.DISABLED
                || phase == ConnectionSnapshot.Phase.NO_DEVICE) {
            return NotificationKind.WAITING;
        }
        if (phase == ConnectionSnapshot.Phase.BONDING
                || phase == ConnectionSnapshot.Phase.CONNECTING
                || phase == ConnectionSnapshot.Phase.DISCOVERING
                || phase == ConnectionSnapshot.Phase.VALIDATING_BUILD) {
            return NotificationKind.CONNECTING;
        }
        if (phase == ConnectionSnapshot.Phase.READY) {
            return NotificationKind.READY;
        }
        if (phase == ConnectionSnapshot.Phase.RETRY_WAIT) {
            return NotificationKind.RETRY;
        }
        if (phase == ConnectionSnapshot.Phase.ERROR) {
            return NotificationKind.ERROR;
        }
        throw new AssertionError("unhandled connection phase");
    }


    private boolean postDelivery(
            final Registration registration,
            final ConnectionSnapshot snapshot) {
        final MainAttempt attempt = new MainAttempt();
        boolean accepted = mainPoster.post(new Runnable() {
            @Override
            public void run() {
                if (!attempt.accepted) {
                    return;
                }
                SnapshotDelivery delivery = null;
                synchronized (lock) {
                    Registration current =
                            registrationFor(registration.identity);
                    if (!destroyed
                            && !generationExhausted
                            && current == registration
                            && current.token == registration.token) {
                        delivery = current.delivery;
                    }
                }
                if (delivery != null) {
                    delivery.deliver(snapshot);
                }
            }
        });
        attempt.accepted = accepted;
        return accepted;
    }

    private long advanceGenerationLocked(long current) {
        if (current == Long.MAX_VALUE) {
            markGenerationExhaustedLocked();
            return -1L;
        }
        return current + 1L;
    }

    private void markGenerationExhaustedLocked() {
        if (generationExhausted) {
            return;
        }
        generationExhausted = true;
        workerUnavailable = true;
        listeners.clear();
        foregroundDesired = false;
        if (foregroundPromoted) {
            exhaustionStopPending = true;
        }
    }

    private void requestExhaustionStop() {
        if (mainPoster.isMainThread()) {
            stopForegroundAfterExhaustion();
            return;
        }
        boolean shouldPost;
        synchronized (lock) {
            shouldPost = generationExhausted
                    && !destroyed
                    && exhaustionStopPending
                    && foregroundPromoted;
        }
        if (!shouldPost) {
            return;
        }
        final MainAttempt attempt = new MainAttempt();
        boolean accepted = mainPoster.post(new Runnable() {
            @Override
            public void run() {
                if (attempt.accepted) {
                    stopForegroundAfterExhaustion();
                }
            }
        });
        attempt.accepted = accepted;
    }

    private void invalidateRejectedForegroundPost(
            long capturedGeneration, boolean clearDesire) {
        boolean exhausted = false;
        synchronized (lock) {
            if (destroyed
                    || generationExhausted
                    || foregroundGeneration != capturedGeneration) {
                return;
            }
            long next = advanceGenerationLocked(foregroundGeneration);
            if (next < 0L) {
                exhausted = true;
            } else {
                foregroundGeneration = next;
                if (clearDesire) {
                    foregroundDesired = false;
                }
            }
        }
        if (exhausted) {
            requestExhaustionStop();
        }
    }

    private void stopForegroundAfterExhaustion() {
        boolean stop = false;
        synchronized (lock) {
            if (generationExhausted
                    && !destroyed
                    && exhaustionStopPending
                    && foregroundPromoted) {
                exhaustionStopPending = false;
                foregroundPromoted = false;
                stop = true;
            }
        }
        if (stop) {
            foregroundPort.stop();
        }
    }

    private Registration registrationFor(Object identity) {
        for (Registration registration : listeners) {
            if (registration.identity == identity) {
                return registration;
            }
        }
        return null;
    }

    private void requireMainThread() {
        if (!mainPoster.isMainThread()) {
            throw new IllegalStateException(
                    "snapshot listeners require main thread");
        }
    }

    private void requireListenerAvailable() {
        if (generationExhausted) {
            throw generationExhaustedFailure();
        }
        if (destroyed || workerUnavailable) {
            throw workerUnavailableFailure();
        }
    }
    private static void requireMutation(Runnable mutation) {
        if (mutation == null) {
            throw new IllegalArgumentException("mutation must not be null");
        }
    }

    private static IllegalStateException workerUnavailableFailure() {
        return new IllegalStateException("BLE worker is unavailable");
    }

    private static IllegalStateException generationExhaustedFailure() {
        return new IllegalStateException("service generation exhausted");
    }
}

public final class BadgeSyncService extends Service {
    private static final String ACTION_ENABLE =
            "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC";
    private static final String ACTION_DISABLE =
            "net.jethachan.factory_badges.action.DISABLE_BADGE_SYNC";
    private static final String CHANNEL_ID = "badge_sync";
    private static final int NOTIFICATION_ID = 3719;
    private static final String BLE_THREAD_NAME = "E87-BLE";

    public interface SnapshotListener {
        void onSnapshot(ConnectionSnapshot snapshot);
    }

    public final class LocalBinder extends Binder {
        public void selectDevice(BluetoothDevice device) {
            if (device == null) {
                throw new IllegalArgumentException("device must not be null");
            }
            final BluetoothDevice capturedDevice = device;
            final String capturedName;
            final String capturedAddress;
            final boolean capturedBonded;
            try {
                capturedName = capturedDevice.getName();
                capturedAddress = capturedDevice.getAddress();
                capturedBonded = capturedDevice.getBondState()
                        == BluetoothDevice.BOND_BONDED;
            } catch (SecurityException denied) {
                throw bluetoothPermissionFailure();
            }
            if (capturedAddress == null
                    || capturedAddress.trim().isEmpty()) {
                throw new IllegalArgumentException(
                        "device address must not be blank");
            }
            final BadgeSyncController.Selection capturedSelection =
                    new BadgeSyncController.Selection(
                            capturedName,
                            capturedAddress,
                            capturedBonded,
                            new BadgeSyncController.ClientFactory() {
                                @Override
                                public BadgeSyncController.Client create(
                                        long clientEpoch,
                                        BadgeSyncController.ClientEvents events) {
                                    return new BoundClient(
                                            capturedDevice,
                                            clientEpoch,
                                            events);
                                }
                            });
            runtime.postBinderMutation(new Runnable() {
                @Override
                public void run() {
                    controller.selectDevice(capturedSelection);
                }
            });
        }

        public void setCurrentState(BadgeState state) {
            if (state == null) {
                throw new IllegalArgumentException("state must not be null");
            }
            final BadgeState capturedState = state;
            runtime.postBinderMutation(new Runnable() {
                @Override
                public void run() {
                    controller.setCurrentState(capturedState);
                }
            });
        }

        public void setSyncEnabled(boolean enabled) {
            final boolean capturedEnabled = enabled;
            runtime.postBinderMutation(new Runnable() {
                @Override
                public void run() {
                    controller.setSyncEnabled(capturedEnabled);
                }
            });
        }

        public void syncNow() {
            runtime.postBinderMutation(new Runnable() {
                @Override
                public void run() {
                    controller.syncNow();
                }
            });
        }

        public ConnectionSnapshot snapshot() {
            return runtime.latestSnapshot();
        }

        public void addSnapshotListener(final SnapshotListener listener) {
            runtime.addSnapshotListener(
                    listener,
                    new BadgeSyncServiceRuntime.SnapshotDelivery() {
                        @Override
                        public void deliver(ConnectionSnapshot snapshot) {
                            listener.onSnapshot(snapshot);
                        }
                    });
        }

        public void removeSnapshotListener(SnapshotListener listener) {
            runtime.removeSnapshotListener(listener);
        }
    }

    private final LocalBinder binder = new LocalBinder();
    private HandlerThread bleThread;
    private Handler bleHandler;
    private Handler mainHandler;
    private BadgeSyncServiceRuntime runtime;
    private BadgeSyncController controller;

    public static Intent enableIntent(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("context must not be null");
        }
        return new Intent(context, BadgeSyncService.class)
                .setAction(ACTION_ENABLE);
    }

    public static Intent disableIntent(Context context) {
        if (context == null) {
            throw new IllegalArgumentException("context must not be null");
        }
        return new Intent(context, BadgeSyncService.class)
                .setAction(ACTION_DISABLE);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        bleThread = new HandlerThread(BLE_THREAD_NAME);
        bleThread.start();
        bleHandler = new Handler(bleThread.getLooper());
        mainHandler = new Handler(Looper.getMainLooper());

        ConnectionSnapshot initialSnapshot = new ConnectionSnapshot(
                false,
                ConnectionSnapshot.Phase.DISABLED,
                null,
                null,
                false,
                new BadgeState(0, 0, 1727L),
                null,
                null,
                null,
                null,
                null,
                null);
        runtime = new BadgeSyncServiceRuntime(
                initialSnapshot,
                bleHandler::post,
                new BadgeSyncServiceRuntime.MainPoster() {
                    @Override
                    public boolean isMainThread() {
                        return Looper.myLooper() == Looper.getMainLooper();
                    }

                    @Override
                    public boolean post(Runnable task) {
                        return mainHandler.post(task);
                    }
                },
                new BadgeSyncServiceRuntime.ForegroundPort() {
                    @Override
                    public void promote(
                            BadgeSyncServiceRuntime.NotificationKind kind) {
                        createNotificationChannel();
                        startForeground(
                                NOTIFICATION_ID,
                                buildNotification(kind),
                                ServiceInfo
                                        .FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
                    }

                    @Override
                    public void update(
                            BadgeSyncServiceRuntime.NotificationKind kind) {
                        notificationManager().notify(
                                NOTIFICATION_ID,
                                buildNotification(kind));
                    }

                    @Override
                    public void stop() {
                        stopForeground(STOP_FOREGROUND_REMOVE);
                        stopSelf();
                    }
                });
        controller = new BadgeSyncController(
                new ReconnectPolicy(),
                new BleScheduler(),
                new BadgeSyncController.ForegroundLifetime() {
                    @Override
                    public void start() {
                        runtime.onControllerForegroundStart();
                    }

                    @Override
                    public void stop() {
                        runtime.onControllerForegroundStop();
                    }
                },
                new BadgeSyncController.SnapshotSink() {
                    @Override
                    public void publish(ConnectionSnapshot snapshot) {
                        runtime.onSnapshot(snapshot);
                    }
                });
    }

    @Override
    public IBinder onBind(Intent intent) {
        return binder;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        return runtime.onStartCommand(
                action,
                new Runnable() {
                    @Override
                    public void run() {
                        controller.setSyncEnabled(true);
                    }
                },
                new Runnable() {
                    @Override
                    public void run() {
                        controller.setSyncEnabled(false);
                    }
                });
    }

    @Override
    public void onDestroy() {
        final BadgeSyncController capturedController = controller;
        final HandlerThread capturedBleThread = bleThread;
        runtime.destroy(new BadgeSyncServiceRuntime.DestroyPort() {
            @Override
            public void closeController() {
                capturedController.close();
            }

            @Override
            public void quitBleThreadSafely() {
                capturedBleThread.quitSafely();
            }
        });
        super.onDestroy();
    }

    private NotificationManager notificationManager() {
        return getSystemService(NotificationManager.class);
    }

    private void createNotificationChannel() {
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.badge_sync_channel_name),
                NotificationManager.IMPORTANCE_LOW);
        notificationManager().createNotificationChannel(channel);
    }

    private Notification buildNotification(
            BadgeSyncServiceRuntime.NotificationKind kind) {
        if (kind == null) {
            throw new IllegalArgumentException(
                    "notification kind must not be null");
        }
        int textResource;
        switch (kind) {
            case WAITING:
                textResource = R.string.badge_sync_notification_waiting;
                break;
            case CONNECTING:
                textResource = R.string.badge_sync_notification_connecting;
                break;
            case READY:
                textResource = R.string.badge_sync_notification_ready;
                break;
            case RETRY:
                textResource = R.string.badge_sync_notification_retry;
                break;
            case ERROR:
                textResource = R.string.badge_sync_notification_error;
                break;
            default:
                throw new AssertionError("unhandled notification kind");
        }
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_badge_sync)
                .setContentTitle(getString(
                        R.string.badge_sync_notification_title))
                .setContentText(getString(textResource))
                .setOngoing(true)
                .build();
    }

    private final class BleScheduler
            implements BadgeSyncController.Scheduler {
        @Override
        public Handle schedule(long delayMs, final Runnable callback) {
            if (!bleHandler.postDelayed(callback, delayMs)) {
                return null;
            }
            return new Handle() {
                private boolean cancelled;

                @Override
                public void cancel() {
                    if (cancelled) {
                        return;
                    }
                    cancelled = true;
                    bleHandler.removeCallbacks(callback);
                }
            };
        }
    }

    private final class BoundClient
            implements BadgeSyncController.Client, NormalGattClient.Listener {
        private final BluetoothDevice boundDevice;
        private final long clientEpoch;
        private final BadgeSyncController.ClientEvents clientEvents;
        private final NormalGattClient normalGattClient;
        private boolean disconnected;
        private boolean closed;

        BoundClient(
                BluetoothDevice boundDevice,
                long clientEpoch,
                BadgeSyncController.ClientEvents clientEvents) {
            this.boundDevice = boundDevice;
            this.clientEpoch = clientEpoch;
            this.clientEvents = clientEvents;
            normalGattClient = new NormalGattClient(
                    BadgeSyncService.this.getApplicationContext(),
                    bleHandler,
                    this);
        }

        @Override
        public void connect() {
            normalGattClient.connect(boundDevice);
        }

        @Override
        public boolean writeState(BadgeState state) {
            return normalGattClient.writeState(state);
        }

        @Override
        public void disconnect() {
            if (disconnected || closed) {
                return;
            }
            disconnected = true;
            normalGattClient.disconnect();
        }

        @Override
        public void close() {
            if (closed) {
                return;
            }
            closed = true;
            normalGattClient.close();
        }

        @Override
        public void onConnected(BuildInfo info, Integer batteryPercent) {
            clientEvents.onConnected(
                    clientEpoch, this, info, batteryPercent);
        }

        @Override
        public void onStateWriteAcknowledged(
                BadgeState state, long elapsedRealtimeMs) {
            clientEvents.onStateWriteAcknowledged(
                    clientEpoch, this, state, elapsedRealtimeMs);
        }

        @Override
        public void onDisconnected(int status) {
            clientEvents.onDisconnected(clientEpoch, this, status);
        }

        @Override
        public void onError(UserVisibleError error) {
            clientEvents.onError(clientEpoch, this, error);
        }
    }

    private static IllegalStateException bluetoothPermissionFailure() {
        return new IllegalStateException(
                new UserVisibleError(
                        UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING)
                        .message());
    }
}
