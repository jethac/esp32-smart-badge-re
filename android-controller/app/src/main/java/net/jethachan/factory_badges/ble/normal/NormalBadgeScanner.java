package net.jethachan.factory_badges.ble.normal;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanRecord;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class NormalBadgeScanner implements AutoCloseable {
    public static final long SCAN_TIMEOUT_MS = 12_000L;
    public static final int MAX_CANDIDATES = 16;

    public enum Failure {
        BLUETOOTH_PERMISSION_REQUIRED,
        BLUETOOTH_OFF,
        SCAN_FAILED
    }

    public interface Listener {
        void onStarted();
        void onCandidate(BluetoothDevice device, String advertisedName,
                String address, boolean bonded);
        void onFinished(boolean foundAny);
        void onFailure(Failure failure);
    }

    interface Runtime {
        interface CallbackHandle {}
        interface ResultHandle {}
        interface Events {
            void onResult(CallbackHandle callback, ResultHandle result,
                    String address, boolean bonded, byte[] scanRecord);
            void onFailure(CallbackHandle callback, Failure failure);
        }
        boolean isOwnerThread();
        boolean nearbyPermissionsGranted();
        boolean bluetoothEnabled();
        CallbackHandle newCallback(Events events);
        boolean startScan(CallbackHandle callback);
        void stopScan(CallbackHandle callback);
        boolean post(Runnable task);
        boolean postDelayed(Runnable task, long delayMs);
        void removeCallbacks(Runnable task);
    }

    interface Output {
        void onStarted();
        void onCandidate(Runtime.ResultHandle result, Core.Candidate candidate);
        void onFinished(boolean foundAny);
        void onFailure(Failure failure);
    }

    private enum SessionState { IDLE, STARTING, ARMED, CLOSED }

    private final Object guard = new Object();
    private final Runtime runtime;
    private final Output output;
    private final Core core = new Core();
    private SessionState state = SessionState.IDLE;
    private long currentToken;
    private Runtime.CallbackHandle currentCallback;
    private Runnable currentTimeout;

    NormalBadgeScanner(Runtime runtime, Output output) {
        if (runtime == null) throw new IllegalArgumentException("runtime must not be null");
        if (output == null) throw new IllegalArgumentException("output must not be null");
        this.runtime = runtime;
        this.output = output;
    }

    public NormalBadgeScanner(Context applicationContext, Handler mainHandler,
            Listener listener) {
        this(new AndroidRuntime(applicationContext, mainHandler),
                new AndroidOutput(listener));
    }

    public void start() {
        requireOwner();
        synchronized (guard) {
            if (state == SessionState.CLOSED) {
                throw new IllegalStateException("scanner is closed");
            }
            if (state == SessionState.STARTING || state == SessionState.ARMED) return;
        }
        try {
            if (!runtime.nearbyPermissionsGranted()) {
                output.onFailure(Failure.BLUETOOTH_PERMISSION_REQUIRED);
                return;
            }
            if (!runtime.bluetoothEnabled()) {
                output.onFailure(Failure.BLUETOOTH_OFF);
                return;
            }
        } catch (SecurityException denied) {
            output.onFailure(Failure.BLUETOOTH_PERMISSION_REQUIRED);
            return;
        } catch (RuntimeException failure) {
            output.onFailure(Failure.SCAN_FAILED);
            return;
        }

        final long token = core.begin();
        final Runtime.CallbackHandle callback;
        try {
            callback = runtime.newCallback(new Runtime.Events() {
                @Override public void onResult(Runtime.CallbackHandle source,
                        Runtime.ResultHandle result, String address, boolean bonded,
                        byte[] scanRecord) {
                    receiveResult(token, callbackIdentity(source), result,
                            address, bonded, scanRecord);
                }

                @Override public void onFailure(Runtime.CallbackHandle source, Failure failure) {
                    receiveFailure(token, callbackIdentity(source), failure);
                }
            });
            if (callback == null) throw new IllegalStateException("callback unavailable");
        } catch (SecurityException denied) {
            core.cancel(token);
            output.onFailure(Failure.BLUETOOTH_PERMISSION_REQUIRED);
            return;
        } catch (RuntimeException failure) {
            core.cancel(token);
            output.onFailure(Failure.SCAN_FAILED);
            return;
        }
        final Runnable timeout = new Runnable() {
            @Override public void run() { timeout(token, callback); }
        };
        synchronized (guard) {
            currentToken = token;
            currentCallback = callback;
            currentTimeout = timeout;
            state = SessionState.STARTING;
        }

        final boolean started;
        try {
            started = runtime.startScan(callback);
        } catch (SecurityException denied) {
            if (cleanupCurrent(token, callback, SessionState.IDLE)) {
                output.onFailure(Failure.BLUETOOTH_PERMISSION_REQUIRED);
            }
            return;
        } catch (RuntimeException failure) {
            if (cleanupCurrent(token, callback, SessionState.IDLE)) {
                output.onFailure(Failure.SCAN_FAILED);
            }
            return;
        }
        if (!startingMatches(token, callback, timeout)) return;
        if (!started) {
            if (cleanupCurrent(token, callback, SessionState.IDLE)) {
                output.onFailure(Failure.SCAN_FAILED);
            }
            return;
        }

        final boolean timeoutAccepted;
        try {
            timeoutAccepted = runtime.postDelayed(timeout, SCAN_TIMEOUT_MS);
        } catch (RuntimeException failure) {
            if (cleanupCurrent(token, callback, SessionState.IDLE)) {
                output.onFailure(Failure.SCAN_FAILED);
            }
            return;
        }
        if (!timeoutAccepted) {
            if (cleanupCurrent(token, callback, SessionState.IDLE)) {
                output.onFailure(Failure.SCAN_FAILED);
            }
            return;
        }
        if (!startingMatches(token, callback, timeout)) {
            bestEffortRemove(timeout);
            return;
        }
        synchronized (guard) {
            if (!startingMatchesLocked(token, callback, timeout)) return;
            state = SessionState.ARMED;
        }
        output.onStarted();
    }

    public void stop() {
        requireOwner();
        Runtime.CallbackHandle callback;
        long token;
        synchronized (guard) {
            if (state == SessionState.CLOSED || state == SessionState.IDLE) return;
            callback = currentCallback;
            token = currentToken;
        }
        cleanupCurrent(token, callback, SessionState.IDLE);
    }

    public boolean isScanning() {
        requireOwner();
        synchronized (guard) {
            return state == SessionState.STARTING || state == SessionState.ARMED;
        }
    }

    @Override public void close() {
        requireOwner();
        cleanupAny(SessionState.CLOSED);
    }

    private static Runtime.CallbackHandle callbackIdentity(Runtime.CallbackHandle callback) {
        return callback;
    }

    private void receiveResult(final long token, final Runtime.CallbackHandle callback,
            final Runtime.ResultHandle result, final String address, final boolean bonded,
            byte[] scanRecord) {
        if (!activeMatches(token, callback)) return;
        final byte[] copied = scanRecord == null
                ? null : Arrays.copyOf(scanRecord, scanRecord.length);
        Runnable delivery = new Runnable() {
            @Override public void run() {
                Core.Candidate candidate;
                synchronized (guard) {
                    if (!armedMatchesLocked(token, callback)) return;
                    candidate = core.accept(token, address, bonded, copied);
                }
                if (candidate != null) output.onCandidate(result, candidate);
            }
        };
        try {
            if (!runtime.post(delivery)) cleanupCurrent(token, callback, SessionState.IDLE);
        } catch (RuntimeException failure) {
            cleanupCurrent(token, callback, SessionState.IDLE);
        }
    }

    private void receiveFailure(final long token, final Runtime.CallbackHandle callback,
            final Failure failure) {
        if (failure == null || !activeMatches(token, callback)) return;
        Runnable delivery = new Runnable() {
            @Override public void run() {
                if (cleanupArmed(token, callback)) output.onFailure(failure);
            }
        };
        try {
            if (!runtime.post(delivery)) cleanupCurrent(token, callback, SessionState.IDLE);
        } catch (RuntimeException postFailure) {
            cleanupCurrent(token, callback, SessionState.IDLE);
        }
    }

    private void timeout(long token, Runtime.CallbackHandle callback) {
        Core.FinishResult result;
        Cleanup cleanup;
        synchronized (guard) {
            if (!matchesLocked(token, callback)) return;
            if (state == SessionState.STARTING) {
                cleanup = invalidateLocked(SessionState.IDLE, false);
                result = null;
            } else if (state == SessionState.ARMED) {
                result = core.finish(token);
                cleanup = invalidateLocked(SessionState.IDLE, true);
            } else {
                return;
            }
        }
        performCleanup(cleanup);
        if (result != null && result.eligible()) output.onFinished(result.foundAny());
    }

    private boolean cleanupArmed(long token, Runtime.CallbackHandle callback) {
        Cleanup cleanup;
        synchronized (guard) {
            if (!armedMatchesLocked(token, callback)) return false;
            cleanup = invalidateLocked(SessionState.IDLE, false);
        }
        performCleanup(cleanup);
        return true;
    }

    private boolean cleanupCurrent(long token, Runtime.CallbackHandle callback,
            SessionState target) {
        Cleanup cleanup;
        synchronized (guard) {
            if (!matchesLocked(token, callback)
                    || (state != SessionState.STARTING && state != SessionState.ARMED)) {
                return false;
            }
            cleanup = invalidateLocked(target, false);
        }
        performCleanup(cleanup);
        return true;
    }

    private void cleanupAny(SessionState target) {
        Cleanup cleanup = null;
        synchronized (guard) {
            if (state == SessionState.CLOSED) return;
            if (state == SessionState.STARTING || state == SessionState.ARMED) {
                cleanup = invalidateLocked(target, false);
            } else {
                state = target;
            }
        }
        performCleanup(cleanup);
    }

    private Cleanup invalidateLocked(SessionState target, boolean alreadyFinished) {
        if (!alreadyFinished) core.cancel(currentToken);
        Cleanup cleanup = new Cleanup(currentCallback, currentTimeout);
        state = target;
        currentToken = 0L;
        currentCallback = null;
        currentTimeout = null;
        return cleanup;
    }

    private void performCleanup(Cleanup cleanup) {
        if (cleanup == null) return;
        bestEffortRemove(cleanup.timeout);
        try {
            runtime.stopScan(cleanup.callback);
        } catch (RuntimeException ignored) {
            // Session ownership was invalidated before platform cleanup.
        }
    }

    private void bestEffortRemove(Runnable timeout) {
        if (timeout == null) return;
        try {
            runtime.removeCallbacks(timeout);
        } catch (RuntimeException ignored) {
            // Session ownership was invalidated before platform cleanup.
        }
    }

    private boolean activeMatches(long token, Runtime.CallbackHandle callback) {
        synchronized (guard) {
            return matchesLocked(token, callback)
                    && (state == SessionState.STARTING || state == SessionState.ARMED)
                    && core.isCurrent(token);
        }
    }

    private boolean startingMatches(long token, Runtime.CallbackHandle callback,
            Runnable timeout) {
        synchronized (guard) {
            return startingMatchesLocked(token, callback, timeout);
        }
    }

    private boolean startingMatchesLocked(long token, Runtime.CallbackHandle callback,
            Runnable timeout) {
        return state == SessionState.STARTING && matchesLocked(token, callback)
                && currentTimeout == timeout && core.isCurrent(token);
    }

    private boolean armedMatchesLocked(long token, Runtime.CallbackHandle callback) {
        return state == SessionState.ARMED && matchesLocked(token, callback)
                && core.isCurrent(token);
    }

    private boolean matchesLocked(long token, Runtime.CallbackHandle callback) {
        return token > 0L && currentToken == token && currentCallback == callback;
    }

    private void requireOwner() {
        if (!runtime.isOwnerThread()) {
            throw new IllegalStateException("scanner call must run on owner thread");
        }
    }

    private static final class Cleanup {
        final Runtime.CallbackHandle callback;
        final Runnable timeout;

        Cleanup(Runtime.CallbackHandle callback, Runnable timeout) {
            this.callback = callback;
            this.timeout = timeout;
        }
    }

    private static final class AndroidRuntime implements Runtime {
        private final Context applicationContext;
        private final Handler mainHandler;

        AndroidRuntime(Context context, Handler mainHandler) {
            if (context == null) throw new IllegalArgumentException("context must not be null");
            if (mainHandler == null) {
                throw new IllegalArgumentException("mainHandler must not be null");
            }
            Context app = context.getApplicationContext();
            if (app == null) throw new IllegalArgumentException("application context unavailable");
            this.applicationContext = app;
            this.mainHandler = mainHandler;
        }

        @Override public boolean isOwnerThread() {
            return Looper.myLooper() == mainHandler.getLooper();
        }

        @Override public boolean nearbyPermissionsGranted() {
            return applicationContext.checkSelfPermission(
                    android.Manifest.permission.BLUETOOTH_SCAN)
                            == android.content.pm.PackageManager.PERMISSION_GRANTED
                    && applicationContext.checkSelfPermission(
                    android.Manifest.permission.BLUETOOTH_CONNECT)
                            == android.content.pm.PackageManager.PERMISSION_GRANTED;
        }

        @SuppressLint("MissingPermission")
        @Override public boolean bluetoothEnabled() {
            if (!nearbyPermissionsGranted()) throw new SecurityException();
            BluetoothManager manager = applicationContext.getSystemService(BluetoothManager.class);
            if (manager == null) return false;
            BluetoothAdapter adapter = manager.getAdapter();
            return adapter != null && adapter.isEnabled();
        }

        @Override public CallbackHandle newCallback(Events events) {
            if (events == null) throw new IllegalArgumentException("events must not be null");
            return new AndroidCallbackHandle(this, events);
        }

        @SuppressLint("MissingPermission")
        @Override public boolean startScan(CallbackHandle callbackHandle) {
            if (!nearbyPermissionsGranted()) throw new SecurityException();
            AndroidCallbackHandle handle = requireCallback(callbackHandle);
            BluetoothManager manager = applicationContext.getSystemService(BluetoothManager.class);
            if (manager == null) return false;
            BluetoothAdapter adapter = manager.getAdapter();
            if (adapter == null) return false;
            BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
            if (scanner == null) return false;
            List<ScanFilter> filters = Arrays.asList(new ScanFilter.Builder()
                    .setServiceUuid(new ParcelUuid(NormalUuids.SERVICE))
                    .build());
            ScanSettings settings = new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                    .build();
            ScanCallback callback = handle.callback;
            handle.scanner = scanner;
            scanner.startScan(filters, settings, callback);
            return true;
        }

        @SuppressLint("MissingPermission")
        @Override public void stopScan(CallbackHandle callbackHandle) {
            AndroidCallbackHandle handle = requireCallback(callbackHandle);
            if (!nearbyPermissionsGranted()) return;
            if (handle.scanner != null) {
                try {
                    handle.scanner.stopScan(handle.callback);
                } catch (SecurityException ignored) {
                    // Permission can be revoked after session invalidation.
                }
            }
        }

        @Override public boolean post(Runnable task) {
            return mainHandler.post(task);
        }

        @Override public boolean postDelayed(Runnable task, long delayMs) {
            return mainHandler.postDelayed(task, delayMs);
        }

        @Override public void removeCallbacks(Runnable task) {
            mainHandler.removeCallbacks(task);
        }

        @SuppressLint("MissingPermission")
        private void route(AndroidCallbackHandle handle, ScanResult result) {
            if (result == null || !nearbyPermissionsGranted()) {
                if (!nearbyPermissionsGranted()) {
                    handle.events.onFailure(handle, Failure.BLUETOOTH_PERMISSION_REQUIRED);
                }
                return;
            }
            try {
                BluetoothDevice device = result.getDevice();
                ScanRecord scanRecord = result.getScanRecord();
                if (device == null || scanRecord == null) return;
                byte[] bytes = scanRecord.getBytes();
                if (bytes == null) return;
                byte[] copied = Arrays.copyOf(bytes, bytes.length);
                String address = device.getAddress();
                boolean bonded = device.getBondState() == BluetoothDevice.BOND_BONDED;
                handle.events.onResult(handle, new AndroidResultHandle(device),
                        address, bonded, copied);
            } catch (SecurityException denied) {
                handle.events.onFailure(handle, Failure.BLUETOOTH_PERMISSION_REQUIRED);
            } catch (RuntimeException failure) {
                handle.events.onFailure(handle, Failure.SCAN_FAILED);
            }
        }

        private static AndroidCallbackHandle requireCallback(CallbackHandle callback) {
            if (!(callback instanceof AndroidCallbackHandle)) {
                throw new IllegalArgumentException("unknown callback handle");
            }
            return (AndroidCallbackHandle) callback;
        }
    }

    private static final class AndroidCallbackHandle implements Runtime.CallbackHandle {
        final AndroidRuntime owner;
        final Runtime.Events events;
        final ScanCallback callback;
        BluetoothLeScanner scanner;

        AndroidCallbackHandle(AndroidRuntime owner, Runtime.Events events) {
            this.owner = owner;
            this.events = events;
            callback = new ScanCallback() {
                @Override public void onScanResult(int callbackType, ScanResult result) {
                    owner.route(AndroidCallbackHandle.this, result);
                }

                @Override public void onBatchScanResults(List<ScanResult> results) {
                    if (results == null) return;
                    for (ScanResult result : results) {
                        owner.route(AndroidCallbackHandle.this, result);
                    }
                }

                @Override public void onScanFailed(int errorCode) {
                    events.onFailure(AndroidCallbackHandle.this, Failure.SCAN_FAILED);
                }
            };
        }
    }

    private static final class AndroidResultHandle implements Runtime.ResultHandle {
        final BluetoothDevice device;

        AndroidResultHandle(BluetoothDevice device) {
            this.device = device;
        }
    }

    private static final class AndroidOutput implements Output {
        private final Listener listener;

        AndroidOutput(Listener listener) {
            if (listener == null) throw new IllegalArgumentException("listener must not be null");
            this.listener = listener;
        }

        @Override public void onStarted() { listener.onStarted(); }

        @Override public void onCandidate(Runtime.ResultHandle result, Core.Candidate candidate) {
            if (!(result instanceof AndroidResultHandle)) {
                throw new IllegalArgumentException("unknown result handle");
            }
            BluetoothDevice device = ((AndroidResultHandle) result).device;
            listener.onCandidate(device, candidate.advertisedName(),
                    candidate.address(), candidate.bonded());
        }

        @Override public void onFinished(boolean foundAny) { listener.onFinished(foundAny); }
        @Override public void onFailure(Failure failure) { listener.onFailure(failure); }
    }

    static final class Core {
        static final class Candidate {
            private final String advertisedName;
            private final String address;
            private final boolean bonded;

            Candidate(String advertisedName, String address, boolean bonded) {
                this.advertisedName = advertisedName;
                this.address = address;
                this.bonded = bonded;
            }

            String advertisedName() { return advertisedName; }
            String address() { return address; }
            boolean bonded() { return bonded; }
        }

        static final class FinishResult {
            private final boolean eligible;
            private final boolean foundAny;

            FinishResult(boolean eligible, boolean foundAny) {
                this.eligible = eligible;
                this.foundAny = foundAny;
            }

            boolean eligible() { return eligible; }
            boolean foundAny() { return foundAny; }
        }

        private long generation;
        private long currentToken;
        private boolean current;
        private boolean exhausted;
        private boolean foundAny;
        private final Set<String> addresses = new HashSet<>();

        long begin() {
            if (exhausted || generation == Long.MAX_VALUE) {
                exhausted = true;
                current = false;
                addresses.clear();
                throw new IllegalStateException("scanner generation exhausted");
            }
            generation++;
            currentToken = generation;
            current = true;
            foundAny = false;
            addresses.clear();
            return currentToken;
        }

        Candidate accept(long sessionToken, String address, boolean bonded,
                byte[] scanRecord) {
            if (!isCurrent(sessionToken) || !canonicalAddress(address)
                    || addresses.size() >= MAX_CANDIDATES || addresses.contains(address)) {
                return null;
            }
            NormalAdvertisementParser.Match match =
                    NormalAdvertisementParser.parse(scanRecord).orElse(null);
            if (match == null) return null;
            addresses.add(address);
            foundAny = true;
            return new Candidate(match.localName(), address, bonded);
        }

        FinishResult finish(long sessionToken) {
            if (!isCurrent(sessionToken)) return new FinishResult(false, false);
            boolean capturedFoundAny = foundAny;
            current = false;
            addresses.clear();
            return new FinishResult(true, capturedFoundAny);
        }

        boolean cancel(long sessionToken) {
            if (!isCurrent(sessionToken)) return false;
            current = false;
            addresses.clear();
            return true;
        }

        boolean isCurrent(long sessionToken) {
            return !exhausted && current && sessionToken > 0L && sessionToken == currentToken;
        }

        private static boolean canonicalAddress(String address) {
            return address != null
                    && address.matches("(?i)[0-9a-f]{2}(?::[0-9a-f]{2}){5}");
        }
    }
}
