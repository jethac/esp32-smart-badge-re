package net.jethachan.factory_badges.ble.normal;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.BluetoothStatusCodes;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.util.Arrays;
import java.util.IdentityHashMap;
import java.util.UUID;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.protocol.BuildInfoCodec;
import net.jethachan.factory_badges.protocol.StatePacketCodec;

public final class NormalGattClient implements AutoCloseable {
    private static final int GATT_SUCCESS = 0;
    private static final int GATT_INSUFFICIENT_AUTHENTICATION = 5;
    private static final int GATT_INSUFFICIENT_ENCRYPTION = 15;
    private static final long OPERATION_TIMEOUT_MS = 10_000L;

    public interface Listener {
        void onConnected(BuildInfo info, Integer batteryPercent);

        void onStateWriteAcknowledged(
                BadgeState state, long elapsedRealtimeMs);

        void onDisconnected(int status);

        void onError(UserVisibleError error);
    }

    interface WritePort {
        void setLegacyWriteType(int writeType);

        boolean setLegacyValue(byte[] value);

        boolean writeLegacy();

        int writeModern(byte[] value, int writeType);
    }

    private final Context applicationContext;
    private final Handler bleHandler;
    private final Listener listener;
    private final Core core;
    private final BroadcastReceiver bondReceiver;

    private BluetoothDevice selectedDevice;
    private boolean receiverRegistered;
    private boolean receiverPermissionFailure;
    private boolean closed;

    public NormalGattClient(
            Context applicationContext,
            Handler bleHandler,
            Listener listener) {
        if (applicationContext == null) {
            throw new IllegalArgumentException("applicationContext must not be null");
        }
        if (bleHandler == null) {
            throw new IllegalArgumentException("bleHandler must not be null");
        }
        if (listener == null) {
            throw new IllegalArgumentException("listener must not be null");
        }
        Context storedContext = applicationContext.getApplicationContext();
        if (storedContext == null) {
            throw new IllegalArgumentException(
                    "applicationContext.getApplicationContext() must not be null");
        }
        this.applicationContext = storedContext;
        this.bleHandler = bleHandler;
        this.listener = listener;
        this.core = new Core(
                new AndroidBondPort(),
                new Core.Connector() {
                    @Override
                    public Core.GattDriver connect(long generation) {
                        return connectGatt(generation);
                    }
                },
                new HandlerScheduler(),
                new Core.Clock() {
                    @Override
                    public long elapsedRealtimeMs() {
                        return SystemClock.elapsedRealtime();
                    }
                },
                listener);
        this.bondReceiver = new BondReceiver();
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                this.applicationContext.registerReceiver(
                        bondReceiver,
                        new IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED),
                        null,
                        bleHandler,
                        Context.RECEIVER_NOT_EXPORTED);
            } else {
                this.applicationContext.registerReceiver(
                        bondReceiver,
                        new IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED),
                        null,
                        bleHandler);
            }
            receiverRegistered = true;
        } catch (SecurityException denied) {
            receiverPermissionFailure = true;
        }
    }

    public void connect(BluetoothDevice device) {
        requireBleThread();
        requireOpen();
        if (device == null) {
            throw new IllegalArgumentException("device must not be null");
        }

        core.disconnect();
        selectedDevice = device;
        UserVisibleError preflightError = connectionPreflight();
        if (preflightError != null) {
            listener.onError(preflightError);
            return;
        }
        core.connect();
    }

    public boolean writeState(BadgeState state) {
        requireBleThread();
        requireOpen();
        if (state == null) {
            throw new IllegalArgumentException("state must not be null");
        }
        return core.writeState(state);
    }

    public void disconnect() {
        requireBleThread();
        if (closed) {
            return;
        }
        core.disconnect();
        selectedDevice = null;
    }

    public boolean isReady() {
        requireBleThread();
        return !closed && core.isReady();
    }

    @Override
    public void close() {
        requireBleThread();
        if (closed) {
            return;
        }
        closed = true;
        core.close();
        selectedDevice = null;
        if (receiverRegistered) {
            receiverRegistered = false;
            try {
                applicationContext.unregisterReceiver(bondReceiver);
            } catch (IllegalArgumentException ignored) {
                // A concurrently torn-down Context must not make close non-idempotent.
            }
        }
    }

    static Core.CharacteristicAccess accessFromProperties(int properties) {
        return new Core.CharacteristicAccess(
                (properties & BluetoothGattCharacteristic.PROPERTY_READ) != 0,
                (properties & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0);
    }

    static boolean writeAcknowledgedForApi(
            int sdkInt, byte[] value, WritePort port) {
        if (sdkInt < 31) {
            throw new IllegalArgumentException("sdkInt must be at least 31");
        }
        if (value == null) {
            throw new IllegalArgumentException("value must not be null");
        }
        if (port == null) {
            throw new IllegalArgumentException("port must not be null");
        }
        byte[] copy = Arrays.copyOf(value, value.length);
        int writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT;
        if (sdkInt >= 33) {
            return port.writeModern(copy, writeType) == BluetoothStatusCodes.SUCCESS;
        }
        port.setLegacyWriteType(writeType);
        if (!port.setLegacyValue(copy)) {
            return false;
        }
        return port.writeLegacy();
    }

    private void requireBleThread() {
        if (Looper.myLooper() != bleHandler.getLooper()) {
            throw new IllegalStateException(
                    "NormalGattClient calls must run on the supplied BLE Handler looper");
        }
    }

    private void requireOpen() {
        if (closed) {
            throw new IllegalStateException("NormalGattClient is closed");
        }
    }

    private UserVisibleError connectionPreflight() {
        try {
            if (receiverPermissionFailure) {
                return new UserVisibleError(
                        UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING);
            }
            if (applicationContext.checkSelfPermission(
                    Manifest.permission.BLUETOOTH_CONNECT)
                    != PackageManager.PERMISSION_GRANTED) {
                return new UserVisibleError(
                        UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING);
            }
            BluetoothManager manager = (BluetoothManager) applicationContext
                    .getSystemService(Context.BLUETOOTH_SERVICE);
            BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
            if (adapter == null || !adapter.isEnabled()) {
                return new UserVisibleError(UserVisibleError.Code.BLUETOOTH_DISABLED);
            }
            return null;
        } catch (SecurityException denied) {
            return new UserVisibleError(
                    UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING);
        }
    }

    private Core.GattDriver connectGatt(long generation) {
        BluetoothDevice device = selectedDevice;
        if (device == null) {
            return null;
        }
        AndroidGattDriver driver = new AndroidGattDriver();
        CallbackBridge callback = new CallbackBridge(generation, driver);
        try {
            BluetoothGatt gatt = device.connectGatt(
                    applicationContext,
                    false,
                    callback,
                    BluetoothDevice.TRANSPORT_LE,
                    BluetoothDevice.PHY_LE_1M_MASK,
                    bleHandler);
            if (gatt == null) {
                return null;
            }
            driver.attach(gatt);
            return driver;
        } catch (SecurityException denied) {
            throw new PermissionFailure();
        }
    }

    private static BondCoordinator.BondState bondState(int state) {
        if (state == BluetoothDevice.BOND_BONDED) {
            return BondCoordinator.BondState.BONDED;
        }
        if (state == BluetoothDevice.BOND_BONDING) {
            return BondCoordinator.BondState.BONDING;
        }
        if (state == BluetoothDevice.BOND_NONE) {
            return BondCoordinator.BondState.NONE;
        }
        return null;
    }

    private static byte[] copyOrNull(byte[] value) {
        return value == null ? null : Arrays.copyOf(value, value.length);
    }

    private static int safeStatus(int status) {
        return status < 0 ? -1 : status;
    }

    private static final class PermissionFailure extends RuntimeException {
        private static final long serialVersionUID = 1L;
    }

    static final class Core implements BondCoordinator.Listener {
        interface Connector {
            GattDriver connect(long generation);
        }

        interface Clock {
            long elapsedRealtimeMs();
        }

        interface ServiceTable {
            boolean hasService(UUID serviceUuid);

            CharacteristicAccess characteristic(
                    UUID serviceUuid, UUID characteristicUuid);
        }

        static final class CharacteristicAccess {
            private final boolean readable;
            private final boolean acknowledgedWritable;

            CharacteristicAccess(
                    boolean readable, boolean acknowledgedWritable) {
                this.readable = readable;
                this.acknowledgedWritable = acknowledgedWritable;
            }

            boolean readable() {
                return readable;
            }

            boolean acknowledgedWritable() {
                return acknowledgedWritable;
            }
        }

        interface GattDriver extends GattOperationQueue.Driver {
            boolean discoverServices();

            ServiceTable serviceTable();

            boolean read(UUID serviceUuid, UUID characteristicUuid);

            boolean writeAcknowledged(
                    UUID serviceUuid,
                    UUID characteristicUuid,
                    byte[] value);

            void disconnect();

            void close();
        }

        private enum Phase {
            IDLE,
            BONDING,
            CONNECTING,
            DISCOVERING,
            VALIDATING_BUILD,
            READING_BATTERY,
            READY
        }

        private enum OperationKind {
            BUILD,
            BATTERY,
            STATE
        }

        private final Connector connector;
        private final GattOperationQueue.Scheduler scheduler;
        private final Clock clock;
        private final Listener listener;
        private final BondCoordinator bondCoordinator;
        private final IdentityHashMap<GattDriver, Boolean> usedDrivers =
                new IdentityHashMap<GattDriver, Boolean>();

        private long generationCounter;
        private long activeGeneration;
        private long nextToken;
        private GattDriver activeDriver;
        private GattOperationQueue queue;
        private QueueOperation expectedOperation;
        private Phase phase = Phase.IDLE;
        private BuildInfo buildInfo;
        private boolean batteryUsable;
        private boolean bondPermissionFailure;
        private BadgeState activeWriteState;
        private boolean closed;

        Core(
                BondCoordinator.Port bondPort,
                Connector connector,
                GattOperationQueue.Scheduler scheduler,
                Clock clock,
                Listener listener) {
            if (bondPort == null) {
                throw new IllegalArgumentException("bondPort must not be null");
            }
            if (connector == null) {
                throw new IllegalArgumentException("connector must not be null");
            }
            if (scheduler == null) {
                throw new IllegalArgumentException("scheduler must not be null");
            }
            if (clock == null) {
                throw new IllegalArgumentException("clock must not be null");
            }
            if (listener == null) {
                throw new IllegalArgumentException("listener must not be null");
            }
            this.connector = connector;
            this.scheduler = scheduler;
            this.clock = clock;
            this.listener = listener;
            this.bondCoordinator = new BondCoordinator(
                    new BondCoordinator.Port() {
                        @Override
                        public BondCoordinator.BondState currentState() {
                            try {
                                return bondPort.currentState();
                            } catch (PermissionFailure | SecurityException denied) {
                                bondPermissionFailure = true;
                                return null;
                            }
                        }

                        @Override
                        public boolean createBond() {
                            try {
                                return bondPort.createBond();
                            } catch (PermissionFailure | SecurityException denied) {
                                bondPermissionFailure = true;
                                return false;
                            }
                        }
                    },
                    this);
        }

        long connect() {
            if (closed) {
                throw new IllegalStateException("core is closed");
            }
            teardownActive();
            bondPermissionFailure = false;
            if (generationCounter == Long.MAX_VALUE) {
                throw new IllegalStateException("GATT generation exhausted");
            }
            long generation = ++generationCounter;
            activeGeneration = generation;
            phase = Phase.BONDING;
            bondCoordinator.ensureBonded(generation);
            return generation;
        }

        void onBondStateChanged(
                long generation,
                BondCoordinator.BondState previous,
                BondCoordinator.BondState current) {
            requirePositive(generation);
            if (previous == null || current == null) {
                throw new IllegalArgumentException("bond states must not be null");
            }
            bondCoordinator.onBondStateChanged(generation, previous, current);
        }

        @Override
        public void onBonded(long generation) {
            requirePositive(generation);
            if (generation != activeGeneration
                    || phase != Phase.BONDING
                    || activeDriver != null) {
                return;
            }

            GattDriver driver;
            try {
                driver = connector.connect(generation);
            } catch (PermissionFailure denied) {
                if (awaitingConnector(generation)) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING));
                }
                return;
            } catch (RuntimeException failure) {
                if (awaitingConnector(generation)) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.CONNECT_FAILED));
                }
                return;
            }
            if (!awaitingConnector(generation)) {
                closeUnusedDriver(driver);
                return;
            }
            if (driver == null || usedDrivers.containsKey(driver)) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.CONNECT_FAILED));
                return;
            }
            usedDrivers.put(driver, Boolean.TRUE);
            activeDriver = driver;
            queue = new GattOperationQueue(driver, scheduler);
            nextToken = 1L;
            phase = Phase.CONNECTING;
        }

        @Override
        public void onBondFailed(long generation, UserVisibleError error) {
            requirePositive(generation);
            if (error == null) {
                throw new IllegalArgumentException("error must not be null");
            }
            if (generation == activeGeneration && phase == Phase.BONDING) {
                UserVisibleError reported = bondPermissionFailure
                        ? new UserVisibleError(
                                UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING)
                        : error;
                bondPermissionFailure = false;
                terminalError(reported);
            }
        }

        void onConnectionStateChanged(
                long generation,
                GattDriver source,
                int status,
                boolean connected) {
            requireCallback(generation, source);
            if (!matchesActive(generation, source)) {
                return;
            }

            if (!connected) {
                if (phase == Phase.CONNECTING) {
                    terminalError(error(
                            UserVisibleError.Code.CONNECT_FAILED, status));
                } else {
                    terminalDisconnect(status);
                }
                return;
            }
            if (phase != Phase.CONNECTING) {
                return;
            }
            if (status != GATT_SUCCESS) {
                terminalError(error(
                        UserVisibleError.Code.CONNECT_FAILED, status));
                return;
            }

            phase = Phase.DISCOVERING;
            boolean started;
            try {
                started = source.discoverServices();
            } catch (PermissionFailure denied) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING));
                return;
            } catch (RuntimeException failure) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
                return;
            }
            if (matchesActive(generation, source)
                    && phase == Phase.DISCOVERING
                    && !started) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
            }
        }

        void onServicesDiscovered(
                long generation, GattDriver source, int status) {
            requireCallback(generation, source);
            if (!matchesActive(generation, source)
                    || phase != Phase.DISCOVERING) {
                return;
            }
            if (status != GATT_SUCCESS) {
                terminalError(error(
                        UserVisibleError.Code.SERVICE_DISCOVERY_FAILED, status));
                return;
            }

            ServiceTable table;
            try {
                table = source.serviceTable();
                if (table == null) {
                    throw new IllegalStateException("null service table");
                }
                if (!table.hasService(NormalUuids.SERVICE)) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.REQUIRED_SERVICE_MISSING));
                    return;
                }
                CharacteristicAccess build = table.characteristic(
                        NormalUuids.SERVICE, NormalUuids.BUILD_INFO);
                if (build == null) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.REQUIRED_CHARACTERISTIC_MISSING));
                    return;
                }
                if (!build.readable()) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.UNSUPPORTED_BADGE));
                    return;
                }
                CharacteristicAccess state = table.characteristic(
                        NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE);
                if (state == null) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.REQUIRED_CHARACTERISTIC_MISSING));
                    return;
                }
                if (!state.acknowledgedWritable()) {
                    terminalError(new UserVisibleError(
                            UserVisibleError.Code.UNSUPPORTED_BADGE));
                    return;
                }
                batteryUsable = false;
                if (table.hasService(NormalUuids.BATTERY_SERVICE)) {
                    CharacteristicAccess battery = table.characteristic(
                            NormalUuids.BATTERY_SERVICE, NormalUuids.BATTERY_LEVEL);
                    batteryUsable = battery != null && battery.readable();
                }
            } catch (PermissionFailure denied) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING));
                return;
            } catch (RuntimeException failure) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.SERVICE_DISCOVERY_FAILED));
                return;
            }

            phase = Phase.VALIDATING_BUILD;
            enqueueRead(
                    OperationKind.BUILD,
                    NormalUuids.SERVICE,
                    NormalUuids.BUILD_INFO);
        }

        void onCharacteristicRead(
                long generation,
                GattDriver source,
                UUID serviceUuid,
                UUID characteristicUuid,
                byte[] value,
                int status) {
            requireCallback(generation, source);
            QueueOperation operation = expectedOperation;
            if (!eligible(
                    generation,
                    source,
                    OperationKind.BUILD,
                    OperationKind.BATTERY,
                    serviceUuid,
                    characteristicUuid,
                    operation)) {
                return;
            }
            operation.readValue = copyOrNull(value);
            queue.complete(operation.token, status);
        }

        void onCharacteristicWrite(
                long generation,
                GattDriver source,
                UUID serviceUuid,
                UUID characteristicUuid,
                int status) {
            requireCallback(generation, source);
            QueueOperation operation = expectedOperation;
            if (!eligible(
                    generation,
                    source,
                    OperationKind.STATE,
                    null,
                    serviceUuid,
                    characteristicUuid,
                    operation)) {
                return;
            }
            queue.complete(operation.token, status);
        }

        boolean writeState(BadgeState state) {
            if (state == null) {
                throw new IllegalArgumentException("state must not be null");
            }
            if (closed) {
                throw new IllegalStateException("core is closed");
            }
            if (phase != Phase.READY
                    || activeDriver == null
                    || queue == null
                    || activeWriteState != null
                    || expectedOperation != null) {
                return false;
            }

            byte[] packet = StatePacketCodec.encode(state);
            activeWriteState = state;
            QueueOperation operation = new WriteOperation(
                    activeGeneration,
                    activeDriver,
                    takeToken(),
                    state,
                    packet);
            queue.enqueue(operation);
            return true;
        }

        void disconnect() {
            teardownActive();
        }

        boolean isReady() {
            return !closed && phase == Phase.READY && activeGeneration > 0;
        }

        long activeGeneration() {
            return activeGeneration;
        }

        void close() {
            if (closed) {
                return;
            }
            closed = true;
            teardownActive();
        }

        private void enqueueRead(
                OperationKind kind, UUID serviceUuid, UUID characteristicUuid) {
            QueueOperation operation = new ReadOperation(
                    activeGeneration,
                    activeDriver,
                    takeToken(),
                    kind,
                    serviceUuid,
                    characteristicUuid);
            queue.enqueue(operation);
        }

        private long takeToken() {
            if (nextToken <= 0 || nextToken == Long.MAX_VALUE) {
                throw new IllegalStateException("GATT token exhausted");
            }
            return nextToken++;
        }

        private boolean eligible(
                long generation,
                GattDriver source,
                OperationKind firstKind,
                OperationKind secondKind,
                UUID serviceUuid,
                UUID characteristicUuid,
                QueueOperation operation) {
            if (!matchesActive(generation, source)
                    || operation == null
                    || (operation.kind != firstKind
                            && operation.kind != secondKind)
                    || !operation.serviceUuid.equals(serviceUuid)
                    || !operation.characteristicUuid.equals(characteristicUuid)
                    || queue == null
                    || queue.activeToken() != operation.token) {
                return false;
            }
            return (operation.kind == OperationKind.BUILD
                            && phase == Phase.VALIDATING_BUILD)
                    || (operation.kind == OperationKind.BATTERY
                            && phase == Phase.READING_BATTERY)
                    || (operation.kind == OperationKind.STATE
                            && phase == Phase.READY
                            && activeWriteState != null);
        }

        private void beginExpected(QueueOperation operation) {
            if (!operationOwned(operation)
                    || expectedOperation != null
                    || queue.activeToken() != operation.token) {
                throw new IllegalStateException("unexpected GATT operation start");
            }
            expectedOperation = operation;
        }

        private void handleCompletion(QueueOperation operation, int status) {
            if (!operationOwned(operation)
                    || expectedOperation != operation) {
                return;
            }
            expectedOperation = null;
            if (operation.kind == OperationKind.BUILD) {
                completeBuild(operation.readValue, status);
            } else if (operation.kind == OperationKind.BATTERY) {
                completeBattery(operation.readValue, status);
            } else {
                completeState(operation.state, status);
            }
        }

        private void handleFailure(
                QueueOperation operation, Throwable cause) {
            if (!operationOwned(operation)
                    || expectedOperation != operation) {
                return;
            }
            expectedOperation = null;
            if (cause instanceof PermissionFailure) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING));
            } else if (operation.kind == OperationKind.BATTERY) {
                publishReady(null);
            } else if (cause instanceof GattOperationQueue.TimeoutFailure) {
                activeWriteState = null;
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.GATT_TIMEOUT));
            } else if (operation.kind == OperationKind.STATE) {
                activeWriteState = null;
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.STATE_WRITE_FAILED));
            } else {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.CONNECT_FAILED));
            }
        }

        private void completeBuild(byte[] value, int status) {
            if (status == GATT_INSUFFICIENT_AUTHENTICATION
                    || status == GATT_INSUFFICIENT_ENCRYPTION) {
                terminalError(error(
                        UserVisibleError.Code.LINK_SECURITY_FAILED, status));
                return;
            }
            if (status != GATT_SUCCESS) {
                terminalError(error(
                        UserVisibleError.Code.CONNECT_FAILED, status));
                return;
            }

            BuildInfo decoded;
            try {
                decoded = BuildInfoCodec.decode(value);
            } catch (IllegalArgumentException malformed) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.BUILD_INFO_INVALID));
                return;
            }
            if ((decoded.capabilities()
                    & BuildInfoCodec.CAPABILITY_SEMANTIC_METRICS) == 0) {
                terminalError(new UserVisibleError(
                        UserVisibleError.Code.UNSUPPORTED_BADGE));
                return;
            }
            buildInfo = decoded;
            if (batteryUsable) {
                phase = Phase.READING_BATTERY;
                enqueueRead(
                        OperationKind.BATTERY,
                        NormalUuids.BATTERY_SERVICE,
                        NormalUuids.BATTERY_LEVEL);
            } else {
                publishReady(null);
            }
        }

        private void completeBattery(byte[] value, int status) {
            Integer percent = null;
            if (status == GATT_SUCCESS
                    && value != null
                    && value.length == 1) {
                int candidate = value[0] & 0xFF;
                if (candidate <= 100) {
                    percent = Integer.valueOf(candidate);
                }
            }
            publishReady(percent);
        }

        private void publishReady(Integer batteryPercent) {
            if (activeGeneration <= 0
                    || activeDriver == null
                    || buildInfo == null) {
                return;
            }
            phase = Phase.READY;
            listener.onConnected(buildInfo, batteryPercent);
        }

        private void completeState(BadgeState state, int status) {
            activeWriteState = null;
            if (status == GATT_SUCCESS) {
                long acknowledgedAt = clock.elapsedRealtimeMs();
                listener.onStateWriteAcknowledged(state, acknowledgedAt);
            } else if (status == GATT_INSUFFICIENT_AUTHENTICATION
                    || status == GATT_INSUFFICIENT_ENCRYPTION) {
                terminalError(error(
                        UserVisibleError.Code.LINK_SECURITY_FAILED, status));
            } else {
                terminalError(error(
                        UserVisibleError.Code.STATE_WRITE_FAILED, status));
            }
        }

        private boolean awaitingConnector(long generation) {
            return generation == activeGeneration
                    && phase == Phase.BONDING
                    && activeDriver == null;
        }

        private void closeUnusedDriver(GattDriver driver) {
            if (driver == null || driver == activeDriver) {
                return;
            }
            usedDrivers.put(driver, Boolean.TRUE);
            try {
                driver.disconnect();
            } catch (RuntimeException ignored) {
                // The driver never became eligible for callbacks.
            }
            try {
                driver.close();
            } catch (RuntimeException ignored) {
                // The owning generation has already been invalidated.
            }
        }

        private boolean operationOwned(QueueOperation operation) {
            return operation.generation == activeGeneration
                    && operation.driver == activeDriver
                    && queue != null;
        }

        private boolean matchesActive(long generation, GattDriver source) {
            return generation == activeGeneration
                    && source == activeDriver
                    && activeGeneration > 0;
        }

        private void terminalError(UserVisibleError error) {
            if (activeGeneration <= 0) {
                return;
            }
            teardownActive();
            listener.onError(error);
        }

        private void terminalDisconnect(int status) {
            if (activeGeneration <= 0) {
                return;
            }
            teardownActive();
            listener.onDisconnected(status);
        }

        private void teardownActive() {
            long generation = activeGeneration;
            GattOperationQueue doomedQueue = queue;
            GattDriver doomedDriver = activeDriver;

            activeGeneration = 0L;
            queue = null;
            activeDriver = null;
            expectedOperation = null;
            activeWriteState = null;
            buildInfo = null;
            batteryUsable = false;
            nextToken = 0L;
            phase = Phase.IDLE;

            if (generation > 0) {
                bondCoordinator.cancel(generation);
            }
            if (doomedQueue != null) {
                try {
                    doomedQueue.failAll(new TeardownFailure());
                } catch (RuntimeException ignored) {
                    // Generation invalidation makes queued callbacks ineligible.
                }
            }
            if (doomedDriver != null) {
                try {
                    doomedDriver.disconnect();
                } catch (RuntimeException ignored) {
                    // Teardown continues to close the exact driver.
                }
                try {
                    doomedDriver.close();
                } catch (RuntimeException ignored) {
                    // The generation is already invalid.
                }
            }
        }

        private static UserVisibleError error(
                UserVisibleError.Code code, int status) {
            return new UserVisibleError(code, safeStatus(status));
        }

        private static void requirePositive(long generation) {
            if (generation <= 0) {
                throw new IllegalArgumentException(
                        "callback generation must be positive");
            }
        }

        private static void requireCallback(
                long generation, GattDriver source) {
            requirePositive(generation);
            if (source == null) {
                throw new IllegalArgumentException(
                        "callback source must not be null");
            }
        }

        private abstract class QueueOperation
                implements GattOperationQueue.Operation {
            final long generation;
            final GattDriver driver;
            final long token;
            final OperationKind kind;
            final UUID serviceUuid;
            final UUID characteristicUuid;
            final BadgeState state;
            byte[] readValue;

            QueueOperation(
                    long generation,
                    GattDriver driver,
                    long token,
                    OperationKind kind,
                    UUID serviceUuid,
                    UUID characteristicUuid,
                    BadgeState state) {
                this.generation = generation;
                this.driver = driver;
                this.token = token;
                this.kind = kind;
                this.serviceUuid = serviceUuid;
                this.characteristicUuid = characteristicUuid;
                this.state = state;
            }

            @Override
            public long token() {
                return token;
            }

            @Override
            public long timeoutMs() {
                return OPERATION_TIMEOUT_MS;
            }

            @Override
            public final boolean start(GattOperationQueue.Driver queueDriver) {
                if (queueDriver != driver) {
                    return false;
                }
                beginExpected(this);
                return startGatt();
            }

            abstract boolean startGatt();

            @Override
            public void onComplete(int status) {
                handleCompletion(this, status);
            }

            @Override
            public void onFailure(Throwable cause) {
                handleFailure(this, cause);
            }
        }

        private final class ReadOperation extends QueueOperation {
            ReadOperation(
                    long generation,
                    GattDriver driver,
                    long token,
                    OperationKind kind,
                    UUID serviceUuid,
                    UUID characteristicUuid) {
                super(
                        generation,
                        driver,
                        token,
                        kind,
                        serviceUuid,
                        characteristicUuid,
                        null);
            }

            @Override
            boolean startGatt() {
                return driver.read(serviceUuid, characteristicUuid);
            }
        }

        private final class WriteOperation extends QueueOperation {
            private final byte[] payload;

            WriteOperation(
                    long generation,
                    GattDriver driver,
                    long token,
                    BadgeState state,
                    byte[] payload) {
                super(
                        generation,
                        driver,
                        token,
                        OperationKind.STATE,
                        NormalUuids.SERVICE,
                        NormalUuids.SEMANTIC_STATE,
                        state);
                this.payload = Arrays.copyOf(payload, payload.length);
            }

            @Override
            boolean startGatt() {
                return driver.writeAcknowledged(
                        serviceUuid,
                        characteristicUuid,
                        Arrays.copyOf(payload, payload.length));
            }
        }

        private static final class TeardownFailure extends RuntimeException {
            private static final long serialVersionUID = 1L;
        }
    }

    private final class AndroidBondPort implements BondCoordinator.Port {
        @Override
        public BondCoordinator.BondState currentState() {
            BluetoothDevice device = selectedDevice;
            if (device == null) {
                throw new IllegalStateException("no selected device");
            }
            try {
                BondCoordinator.BondState state = bondState(device.getBondState());
                if (state == null) {
                    throw new IllegalStateException("unknown bond state");
                }
                return state;
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }

        @Override
        public boolean createBond() {
            BluetoothDevice device = selectedDevice;
            if (device == null) {
                return false;
            }
            try {
                return device.createBond();
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }
    }

    private final class HandlerScheduler
            implements GattOperationQueue.Scheduler {
        @Override
        public GattOperationQueue.TimeoutHandle schedule(
                long timeoutMs, Runnable callback) {
            if (callback == null) {
                throw new IllegalArgumentException("callback must not be null");
            }
            HandlerTimeout timeout = new HandlerTimeout(callback);
            if (!bleHandler.postDelayed(timeout, timeoutMs)) {
                throw new IllegalStateException("BLE Handler rejected timeout");
            }
            return timeout;
        }
    }

    private final class HandlerTimeout
            implements Runnable, GattOperationQueue.TimeoutHandle {
        private final Runnable callback;
        private boolean cancelled;

        HandlerTimeout(Runnable callback) {
            this.callback = callback;
        }

        @Override
        public void run() {
            if (!cancelled) {
                callback.run();
            }
        }

        @Override
        public void cancel() {
            if (cancelled) {
                return;
            }
            cancelled = true;
            bleHandler.removeCallbacks(this);
        }
    }

    private final class BondReceiver extends BroadcastReceiver {
        @Override
        @SuppressWarnings("deprecation")
        public void onReceive(Context context, Intent intent) {
            if (intent == null
                    || !BluetoothDevice.ACTION_BOND_STATE_CHANGED.equals(
                            intent.getAction())) {
                return;
            }
            BluetoothDevice changedDevice;
            if (Build.VERSION.SDK_INT >= 33) {
                changedDevice = intent.getParcelableExtra(
                        BluetoothDevice.EXTRA_DEVICE, BluetoothDevice.class);
            } else {
                changedDevice = intent.getParcelableExtra(
                        BluetoothDevice.EXTRA_DEVICE);
            }
            BluetoothDevice selected = selectedDevice;
            if (changedDevice == null || selected == null) {
                return;
            }
            try {
                if (!selected.getAddress().equals(changedDevice.getAddress())) {
                    return;
                }
            } catch (SecurityException denied) {
                long generation = core.activeGeneration();
                if (generation > 0) {
                    core.onBondFailed(
                            generation,
                            new UserVisibleError(
                                    UserVisibleError.Code
                                            .BLUETOOTH_PERMISSION_MISSING));
                }
                return;
            }

            BondCoordinator.BondState current = bondState(intent.getIntExtra(
                    BluetoothDevice.EXTRA_BOND_STATE, Integer.MIN_VALUE));
            BondCoordinator.BondState previous = bondState(intent.getIntExtra(
                    BluetoothDevice.EXTRA_PREVIOUS_BOND_STATE,
                    Integer.MIN_VALUE));
            long generation = core.activeGeneration();
            if (generation > 0 && current != null && previous != null) {
                core.onBondStateChanged(generation, previous, current);
            }
        }
    }

    private final class AndroidGattDriver implements Core.GattDriver {
        private BluetoothGatt gatt;
        private boolean closed;

        void attach(BluetoothGatt attachedGatt) {
            if (attachedGatt == null) {
                throw new IllegalArgumentException("gatt must not be null");
            }
            if (gatt != null) {
                throw new IllegalStateException("gatt already attached");
            }
            gatt = attachedGatt;
        }

        boolean matches(BluetoothGatt callbackGatt) {
            return callbackGatt != null && callbackGatt == gatt;
        }

        @Override
        public boolean discoverServices() {
            BluetoothGatt attachedGatt = requireGatt();
            try {
                return attachedGatt.discoverServices();
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }

        @Override
        public Core.ServiceTable serviceTable() {
            return new AndroidServiceTable(requireGatt());
        }

        @Override
        public boolean read(UUID serviceUuid, UUID characteristicUuid) {
            BluetoothGatt attachedGatt = requireGatt();
            try {
                BluetoothGattService service =
                        attachedGatt.getService(serviceUuid);
                BluetoothGattCharacteristic characteristic = service == null
                        ? null
                        : service.getCharacteristic(characteristicUuid);
                return characteristic != null
                        && attachedGatt.readCharacteristic(characteristic);
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }

        @Override
        @SuppressWarnings("deprecation")
        public boolean writeAcknowledged(
                UUID serviceUuid,
                UUID characteristicUuid,
                byte[] value) {
            if (value == null) {
                throw new IllegalArgumentException("value must not be null");
            }
            final BluetoothGatt attachedGatt = requireGatt();
            final BluetoothGattService service;
            final BluetoothGattCharacteristic characteristic;
            try {
                service = attachedGatt.getService(serviceUuid);
                characteristic = service == null
                        ? null
                        : service.getCharacteristic(characteristicUuid);
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
            if (characteristic == null) {
                return false;
            }

            try {
                return writeAcknowledgedForApi(
                        Build.VERSION.SDK_INT,
                        value,
                        new WritePort() {
                            private boolean valueAccepted = true;

                            @Override
                            public void setLegacyWriteType(int writeType) {
                                characteristic.setWriteType(writeType);
                            }

                            @Override
                            public boolean setLegacyValue(byte[] copiedValue) {
                                valueAccepted =
                                        characteristic.setValue(copiedValue);
                                return valueAccepted;
                            }

                            @Override
                            public boolean writeLegacy() {
                                return valueAccepted
                                        && attachedGatt.writeCharacteristic(
                                                characteristic);
                            }

                            @Override
                            public int writeModern(
                                    byte[] copiedValue, int writeType) {
                                return attachedGatt.writeCharacteristic(
                                        characteristic,
                                        copiedValue,
                                        writeType);
                            }
                        });
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }

        @Override
        public void disconnect() {
            BluetoothGatt attachedGatt = gatt;
            if (attachedGatt == null || closed) {
                return;
            }
            try {
                attachedGatt.disconnect();
            } catch (SecurityException ignored) {
                // Intentional teardown has no listener event.
            }
        }

        @Override
        public void close() {
            if (closed) {
                return;
            }
            closed = true;
            BluetoothGatt attachedGatt = gatt;
            if (attachedGatt != null) {
                attachedGatt.close();
            }
        }

        private BluetoothGatt requireGatt() {
            if (gatt == null || closed) {
                throw new IllegalStateException("GATT is unavailable");
            }
            return gatt;
        }
    }

    private static final class AndroidServiceTable
            implements Core.ServiceTable {
        private final BluetoothGatt gatt;

        AndroidServiceTable(BluetoothGatt gatt) {
            this.gatt = gatt;
        }

        @Override
        public boolean hasService(UUID serviceUuid) {
            try {
                return gatt.getService(serviceUuid) != null;
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }

        @Override
        public Core.CharacteristicAccess characteristic(
                UUID serviceUuid, UUID characteristicUuid) {
            try {
                BluetoothGattService service = gatt.getService(serviceUuid);
                BluetoothGattCharacteristic characteristic = service == null
                        ? null
                        : service.getCharacteristic(characteristicUuid);
                return characteristic == null
                        ? null
                        : accessFromProperties(characteristic.getProperties());
            } catch (SecurityException denied) {
                throw new PermissionFailure();
            }
        }
    }

    private final class CallbackBridge extends BluetoothGattCallback {
        private final long generation;
        private final AndroidGattDriver driver;

        CallbackBridge(long generation, AndroidGattDriver driver) {
            this.generation = generation;
            this.driver = driver;
        }

        @Override
        public void onConnectionStateChange(
                BluetoothGatt callbackGatt, int status, int newState) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                route(callbackGatt, new Runnable() {
                    @Override
                    public void run() {
                        core.onConnectionStateChanged(
                                generation, driver, status, true);
                    }
                });
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                route(callbackGatt, new Runnable() {
                    @Override
                    public void run() {
                        core.onConnectionStateChanged(
                                generation, driver, status, false);
                    }
                });
            }
        }

        @Override
        public void onServicesDiscovered(
                BluetoothGatt callbackGatt, int status) {
            route(callbackGatt, new Runnable() {
                @Override
                public void run() {
                    core.onServicesDiscovered(generation, driver, status);
                }
            });
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onCharacteristicRead(
                BluetoothGatt callbackGatt,
                BluetoothGattCharacteristic characteristic,
                int status) {
            byte[] copied = copyOrNull(
                    characteristic == null ? null : characteristic.getValue());
            handleCharacteristicRead(
                    callbackGatt, characteristic, copied, status);
        }

        @Override
        public void onCharacteristicRead(
                BluetoothGatt callbackGatt,
                BluetoothGattCharacteristic characteristic,
                byte[] value,
                int status) {
            byte[] copied = copyOrNull(value);
            handleCharacteristicRead(
                    callbackGatt, characteristic, copied, status);
        }

        @Override
        public void onCharacteristicWrite(
                BluetoothGatt callbackGatt,
                BluetoothGattCharacteristic characteristic,
                int status) {
            UUID serviceUuid = serviceUuid(characteristic);
            UUID characteristicUuid =
                    characteristic == null ? null : characteristic.getUuid();
            route(callbackGatt, new Runnable() {
                @Override
                public void run() {
                    core.onCharacteristicWrite(
                            generation,
                            driver,
                            serviceUuid,
                            characteristicUuid,
                            status);
                }
            });
        }

        private void handleCharacteristicRead(
                BluetoothGatt callbackGatt,
                BluetoothGattCharacteristic characteristic,
                byte[] copiedValue,
                int status) {
            UUID serviceUuid = serviceUuid(characteristic);
            UUID characteristicUuid =
                    characteristic == null ? null : characteristic.getUuid();
            route(callbackGatt, new Runnable() {
                @Override
                public void run() {
                    core.onCharacteristicRead(
                            generation,
                            driver,
                            serviceUuid,
                            characteristicUuid,
                            copiedValue,
                            status);
                }
            });
        }

        private UUID serviceUuid(
                BluetoothGattCharacteristic characteristic) {
            BluetoothGattService service =
                    characteristic == null ? null : characteristic.getService();
            return service == null ? null : service.getUuid();
        }

        private void route(BluetoothGatt callbackGatt, Runnable callback) {
            if (!driver.matches(callbackGatt)) {
                closeStaleDriver();
                return;
            }
            if (Looper.myLooper() == bleHandler.getLooper()) {
                routeOnBleThread(callback);
            } else if (!bleHandler.post(new Runnable() {
                @Override
                public void run() {
                    routeOnBleThread(callback);
                }
            })) {
                driver.close();
            }
        }

        private void routeOnBleThread(Runnable callback) {
            if (generation != core.activeGeneration()) {
                driver.close();
                return;
            }
            callback.run();
        }

        private void closeStaleDriver() {
            if (Looper.myLooper() == bleHandler.getLooper()) {
                driver.close();
            } else {
                bleHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        driver.close();
                    }
                });
            }
        }
    }
}
