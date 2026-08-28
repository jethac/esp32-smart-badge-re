package net.jethachan.factory_badges.transition;

import android.annotation.TargetApi;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.BluetoothStatusCodes;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.os.Build;
import android.os.Handler;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executor;

/** Android-framework-only implementation of the isolated stock FD00 GATT boundary. */
public final class StockQixGattTransport implements StockGattDriver {
    private static final int FAILURE_STATUS = -1;

    private enum CommandKind {
        SCAN, CONNECT, DISCOVER, SUBSCRIBE, MTU, WRITE
    }

    private final Context applicationContext;
    private final Handler bleHandler;
    private final AdapterSeam adapter;
    private final Map<String, BluetoothDevice> scannedDevices =
            new HashMap<String, BluetoothDevice>();
    private final Map<BluetoothGattCharacteristic, StockGattDriver.Characteristic> nativeToPure =
            new IdentityHashMap<BluetoothGattCharacteristic, StockGattDriver.Characteristic>();
    private final Map<StockGattDriver.Characteristic, BluetoothGattCharacteristic> pureToNative =
            new IdentityHashMap<StockGattDriver.Characteristic, BluetoothGattCharacteristic>();
    private final Map<BluetoothGattDescriptor, DescriptorTarget> descriptorTargets =
            new IdentityHashMap<BluetoothGattDescriptor, DescriptorTarget>();
    private final BluetoothGattCallback gattCallback = new CallbackBridge();

    private volatile Listener listener;
    private BluetoothLeScanner scanner;
    private ScanCallback scanCallback;
    private BluetoothGatt gatt;
    private long sessionGeneration;
    private Command scanCommand;
    private Command connectCommand;
    private Command discoverCommand;
    private Command subscriptionCommand;
    private Command mtuCommand;
    private Command writeCommand;
    private BluetoothGattCharacteristic writeCharacteristic;
    private Characteristic writeTarget;

    public StockQixGattTransport(Context applicationContext, Handler bleHandler,
            Executor callbackExecutor) {
        if (applicationContext == null || bleHandler == null || callbackExecutor == null) {
            throw new IllegalArgumentException("transport inputs must not be null");
        }
        Context storedContext = applicationContext.getApplicationContext();
        if (storedContext == null) {
            throw new IllegalArgumentException("application context must not be null");
        }
        this.applicationContext = storedContext;
        this.bleHandler = bleHandler;
        this.adapter = new AdapterSeam(new AdapterSeam.HandlerPoster() {
            @Override public boolean post(Runnable command) {
                return StockQixGattTransport.this.bleHandler.post(command);
            }
        }, callbackExecutor);
    }

    @Override public void setListener(Listener listener) {
        if (listener == null) {
            throw new IllegalArgumentException("listener must not be null");
        }
        this.listener = listener;
    }

    @Override public boolean startScan(final long generation, final long token) {
        return postToBle(new Runnable() {
            @Override public void run() {
                startScanOnBle(generation, token);
            }
        });
    }

    @Override public void stopScan(final long generation) {
        postToBle(new Runnable() {
            @Override public void run() {
                Command previous = scanCommand;
                scanCommand = null;
                ScanCallback callback = scanCallback;
                scanCallback = null;
                BluetoothLeScanner currentScanner = scanner;
                if (previous != null) {
                    previous.complete();
                }
                if (currentScanner != null && callback != null) {
                    try {
                        currentScanner.stopScan(callback);
                    } catch (SecurityException ignored) {
                        // Teardown uses best effort; no command remains awaiting this callback.
                    }
                }
            }
        });
    }

    @Override public boolean connect(final long generation, final long token, final Peer peer) {
        if (peer == null) {
            throw new IllegalArgumentException("peer must not be null");
        }
        return postToBle(new Runnable() {
            @Override public void run() {
                connectOnBle(generation, token, peer);
            }
        });
    }

    @Override public boolean discoverServices(final long generation, final long token) {
        return postToBle(new Runnable() {
            @Override public void run() {
                discoverOnBle(generation, token);
            }
        });
    }

    @Override public boolean subscribe(final long generation, final long token,
            final Characteristic characteristic, final UUID descriptorUuid, final byte[] value) {
        if (characteristic == null || descriptorUuid == null || value == null) {
            throw new IllegalArgumentException("subscription inputs must not be null");
        }
        final byte[] copied = Arrays.copyOf(value, value.length);
        return postToBle(new Runnable() {
            @Override public void run() {
                subscribeOnBle(generation, token, characteristic, descriptorUuid, copied);
            }
        });
    }

    @Override public boolean requestMtu(final long generation, final long token, final int mtu) {
        return postToBle(new Runnable() {
            @Override public void run() {
                requestMtuOnBle(generation, token, mtu);
            }
        });
    }

    @Override public boolean writeCharacteristic(final long generation, final long token,
            final Characteristic characteristic, final byte[] value, final int writeType) {
        if (characteristic == null || value == null) {
            throw new IllegalArgumentException("write inputs must not be null");
        }
        final byte[] copied = Arrays.copyOf(value, value.length);
        return postToBle(new Runnable() {
            @Override public void run() {
                writeOnBle(generation, token, characteristic, copied, writeType);
            }
        });
    }

    @Override public void disconnect(final long generation) {
        postToBle(new Runnable() {
            @Override public void run() {
                BluetoothGatt current = gatt;
                if (current != null) {
                    try {
                        current.disconnect();
                    } catch (SecurityException ignored) {
                        // Controller has already selected terminal failure semantics.
                    }
                }
            }
        });
    }

    @Override public void close() {
        postToBle(new Runnable() {
            @Override public void run() {
                stopScannerOnBle();
                clearPendingCommands();
                BluetoothGatt current = gatt;
                gatt = null;
                nativeToPure.clear();
                pureToNative.clear();
                descriptorTargets.clear();
                writeCharacteristic = null;
                writeTarget = null;
                if (current != null) {
                    try {
                        current.disconnect();
                    } catch (SecurityException ignored) {
                        // Best-effort close.
                    }
                    try {
                        current.close();
                    } catch (SecurityException ignored) {
                        // Best-effort close.
                    }
                }
            }
        });
    }

    private boolean postToBle(Runnable command) {
        return adapter.postToBle(command);
    }

    private AdapterSeam.ListenerSupplier listenerSupplier() {
        return new AdapterSeam.ListenerSupplier() {
            @Override public Listener current() {
                return listener;
            }
        };
    }

    private void startScanOnBle(long generation, long token) {
        final Command command = new Command(generation, token, CommandKind.SCAN);
        scanCommand = command;
        scannedDevices.clear();
        boolean started = adapter.attemptPlatformStartOrDeliver(new AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                BluetoothAdapter bluetoothAdapter = bluetoothAdapter();
                BluetoothLeScanner currentScanner = bluetoothAdapter == null ? null
                        : bluetoothAdapter.getBluetoothLeScanner();
                if (currentScanner == null) {
                    return false;
                }
                ScanCallback callback = new ScanBridge(command);
                scanner = currentScanner;
                scanCallback = callback;
                try {
                    currentScanner.startScan(Collections.<ScanFilter>emptyList(),
                            new ScanSettings.Builder().build(), callback);
                    return true;
                } catch (SecurityException denied) {
                    return false;
                }
            }
        }, command.completion, listenerSupplier(),
                AdapterSeam.CallbackTag.scan(command.generation, command.token));
        if (!started) {
            scanCommand = null;
        }
    }

    private void connectOnBle(long generation, long token, Peer peer) {
        final Command command = new Command(generation, token, CommandKind.CONNECT);
        connectCommand = command;
        boolean started = adapter.attemptPlatformStartOrDeliver(new AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                BluetoothDevice device = scannedDevices.get(peer.address());
                if (device == null) {
                    BluetoothAdapter bluetoothAdapter = bluetoothAdapter();
                    device = bluetoothAdapter == null ? null
                            : bluetoothAdapter.getRemoteDevice(peer.address());
                }
                if (device == null) {
                    return false;
                }
                final BluetoothGatt opened;
                try {
                    opened = device.connectGatt(applicationContext, false, gattCallback,
                            BluetoothDevice.TRANSPORT_LE, BluetoothDevice.PHY_LE_1M_MASK,
                            bleHandler);
                } catch (SecurityException denied) {
                    return false;
                }
                if (opened == null) {
                    return false;
                }
                gatt = opened;
                sessionGeneration = generation;
                nativeToPure.clear();
                pureToNative.clear();
                descriptorTargets.clear();
                return true;
            }
        }, command.completion, listenerSupplier(),
                AdapterSeam.CallbackTag.connect(command.generation, command.token));
        if (!started) {
            connectCommand = null;
        }
    }

    private void discoverOnBle(long generation, long token) {
        final Command command = new Command(generation, token, CommandKind.DISCOVER);
        discoverCommand = command;
        boolean started = adapter.attemptPlatformStartOrDeliver(new AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                BluetoothGatt current = gatt;
                try {
                    return current != null && current.discoverServices();
                } catch (SecurityException denied) {
                    return false;
                }
            }
        }, command.completion, listenerSupplier(),
                AdapterSeam.CallbackTag.discover(command.generation, command.token));
        if (!started) {
            discoverCommand = null;
        }
    }

    @SuppressWarnings("deprecation")
    private void subscribeOnBle(long generation, long token, Characteristic characteristic,
            UUID descriptorUuid, byte[] copy) {
        final Command command = new Command(generation, token, CommandKind.SUBSCRIBE);
        subscriptionCommand = command;
        final BluetoothGatt current = gatt;
        final BluetoothGattCharacteristic nativeCharacteristic = pureToNative.get(characteristic);
        Object startedDescriptor = adapter.startSubscriptionOrDeliver(Build.VERSION.SDK_INT,
                new AdapterSeam.SubscriptionPort() {
                    @Override public boolean setCharacteristicNotification() {
                        try {
                            return current != null && nativeCharacteristic != null
                                    && current.setCharacteristicNotification(
                                            nativeCharacteristic, true);
                        } catch (SecurityException denied) {
                            return false;
                        }
                    }

                    @Override public Object findDescriptor() {
                        return nativeCharacteristic == null ? null
                                : nativeCharacteristic.getDescriptor(descriptorUuid);
                    }

                    @Override public boolean setLegacyValue(Object descriptor, byte[] value) {
                        return ((BluetoothGattDescriptor) descriptor).setValue(value);
                    }

                    @Override public boolean writeLegacyDescriptor(Object descriptor) {
                        try {
                            return current != null && current.writeDescriptor(
                                    (BluetoothGattDescriptor) descriptor);
                        } catch (SecurityException denied) {
                            return false;
                        }
                    }

                    @Override public boolean writeModernDescriptor(Object descriptor, byte[] value) {
                        return current != null && writeDescriptorApi33(current,
                                (BluetoothGattDescriptor) descriptor, value);
                    }
                }, copy, command.completion, listenerSupplier(),
                AdapterSeam.CallbackTag.subscription(command.generation, command.token,
                        characteristic, descriptorUuid));
        if (!(startedDescriptor instanceof BluetoothGattDescriptor)) {
            subscriptionCommand = null;
            return;
        }
        descriptorTargets.put((BluetoothGattDescriptor) startedDescriptor,
                new DescriptorTarget(command, characteristic, descriptorUuid));
    }

    private void requestMtuOnBle(long generation, long token, int mtu) {
        final Command command = new Command(generation, token, CommandKind.MTU);
        mtuCommand = command;
        boolean started = adapter.attemptPlatformStartOrDeliver(new AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                BluetoothGatt current = gatt;
                try {
                    return current != null && current.requestMtu(mtu);
                } catch (SecurityException denied) {
                    return false;
                }
            }
        }, command.completion, listenerSupplier(),
                AdapterSeam.CallbackTag.mtu(command.generation, command.token, mtu));
        if (!started) {
            mtuCommand = null;
        }
    }

    @SuppressWarnings("deprecation")
    private void writeOnBle(long generation, long token, Characteristic characteristic,
            byte[] copy, int writeType) {
        final Command command = new Command(generation, token, CommandKind.WRITE);
        writeCommand = command;
        final BluetoothGatt current = gatt;
        final BluetoothGattCharacteristic nativeCharacteristic = pureToNative.get(characteristic);
        if (current == null || nativeCharacteristic == null) {
            adapter.deliverTaggedResult(command.completion, listenerSupplier(),
                    AdapterSeam.CallbackTag.write(command.generation, command.token,
                            characteristic), FAILURE_STATUS);
            writeCommand = null;
            writeTarget = null;
            writeCharacteristic = null;
            return;
        }
        writeCharacteristic = nativeCharacteristic;
        writeTarget = characteristic;
        boolean started = adapter.startWriteOrDeliver(Build.VERSION.SDK_INT,
                new AdapterSeam.WritePort() {
            @Override public boolean setWriteType(int requestedWriteType) {
                nativeCharacteristic.setWriteType(requestedWriteType);
                return true;
            }

            @Override public boolean setLegacyValue(byte[] value) {
                return nativeCharacteristic.setValue(value);
            }

            @Override public boolean writeLegacyCharacteristic() {
                try {
                    return current.writeCharacteristic(nativeCharacteristic);
                } catch (SecurityException denied) {
                    return false;
                }
            }

            @Override public boolean writeModernCharacteristic(byte[] value,
                    int requestedWriteType) {
                return writeCharacteristicApi33(current, nativeCharacteristic, value,
                        requestedWriteType);
            }
        }, copy, writeType, command.completion, listenerSupplier(),
                AdapterSeam.CallbackTag.write(command.generation, command.token,
                        characteristic));
        if (!started) {
            writeCommand = null;
            writeTarget = null;
            writeCharacteristic = null;
        }
    }

    @TargetApi(33)
    private static boolean writeDescriptorApi33(BluetoothGatt gatt, BluetoothGattDescriptor descriptor,
            byte[] copy) {
        try {
            return gatt.writeDescriptor(descriptor, copy) == BluetoothStatusCodes.SUCCESS;
        } catch (SecurityException denied) {
            return false;
        }
    }

    @TargetApi(33)
    private static boolean writeCharacteristicApi33(BluetoothGatt gatt,
            BluetoothGattCharacteristic characteristic, byte[] copy, int writeType) {
        try {
            return gatt.writeCharacteristic(characteristic, copy, writeType)
                    == BluetoothStatusCodes.SUCCESS;
        } catch (SecurityException denied) {
            return false;
        }
    }

    private BluetoothAdapter bluetoothAdapter() {
        BluetoothManager manager = (BluetoothManager) applicationContext.getSystemService(
                Context.BLUETOOTH_SERVICE);
        return manager == null ? null : manager.getAdapter();
    }

    private void onScanResultOnBle(Command command, ScanResult result) {
        if (command != scanCommand || command.isCompleted() || result == null) {
            return;
        }
        try {
            BluetoothDevice device = result.getDevice();
            if (device == null) {
                return;
            }
            String address = device.getAddress();
            if (address == null) {
                return;
            }
            String name = device.getName();
            Peer peer = new Peer(address, name == null ? "" : name, result.getRssi());
            if (!recordScannedDevice(scannedDevices, peer.address(), device)) {
                return;
            }
            postCallback(new Runnable() {
                @Override public void run() {
                    Listener current = listener;
                    if (current != null && command == scanCommand && !command.isCompleted()) {
                        current.onScanResult(command.generation, command.token, peer);
                    }
                }
            });
        } catch (SecurityException ignored) {
            scanFailure(command, FAILURE_STATUS);
        } catch (RuntimeException ignored) {
            scanFailure(command, FAILURE_STATUS);
        }
    }

    static <T> boolean recordScannedDevice(Map<String, T> devices, String address, T device) {
        if (devices == null || address == null || device == null) {
            throw new IllegalArgumentException("scan registry inputs must not be null");
        }
        if (!devices.containsKey(address)
                && devices.size() >= StockTransitionController.MAX_CANDIDATES) {
            return false;
        }
        devices.put(address, device);
        return true;
    }

    private void onScanFailureOnBle(final Command command, final int status) {
        scanFailure(command, status);
    }

    private void onConnectionStateChangeOnBle(final BluetoothGatt callbackGatt, int status,
            int newState) {
        if (callbackGatt != gatt) {
            return;
        }
        Command command = connectCommand;
        if (command != null && !command.isCompleted()) {
            if (status == StockGattDriver.STATUS_SUCCESS
                    && newState == BluetoothProfile.STATE_CONNECTED) {
                connectCommand = null;
                if (command.complete()) {
                    postCallback(new Runnable() {
                        @Override public void run() {
                            Listener current = listener;
                            if (current != null) {
                                current.onConnectionResult(command.generation, command.token,
                                        StockGattDriver.STATUS_SUCCESS);
                            }
                        }
                    });
                }
            } else if (status != StockGattDriver.STATUS_SUCCESS
                    || newState == BluetoothProfile.STATE_DISCONNECTED) {
                connectionFailure(command, status == StockGattDriver.STATUS_SUCCESS
                        ? FAILURE_STATUS : status);
            }
        }
        if (newState == BluetoothProfile.STATE_DISCONNECTED) {
            final long disconnectedGeneration = sessionGeneration;
            postCallback(new Runnable() {
                @Override public void run() {
                    Listener current = listener;
                    if (current != null) {
                        current.onDisconnected(disconnectedGeneration, status);
                    }
                }
            });
        }
    }

    private void onServicesDiscoveredOnBle(final BluetoothGatt callbackGatt, final int status) {
        if (callbackGatt != gatt || discoverCommand == null) {
            return;
        }
        final Command command = discoverCommand;
        discoverCommand = null;
        if (!command.complete()) {
            return;
        }
        final List<Service> services;
        if (status == StockGattDriver.STATUS_SUCCESS) {
            try {
                services = convertServices(callbackGatt.getServices());
            } catch (SecurityException denied) {
                postServices(command, Collections.<Service>emptyList(), FAILURE_STATUS);
                return;
            } catch (RuntimeException failed) {
                postServices(command, Collections.<Service>emptyList(), FAILURE_STATUS);
                return;
            }
        } else {
            services = Collections.emptyList();
        }
        postServices(command, services, status);
    }

    private void onDescriptorWriteOnBle(BluetoothGatt callbackGatt,
            BluetoothGattDescriptor descriptor, final int status) {
        if (callbackGatt != gatt || descriptor == null) {
            return;
        }
        DescriptorTarget target = descriptorTargets.remove(descriptor);
        if (target == null || target.command != subscriptionCommand) {
            return;
        }
        final Command command = target.command;
        subscriptionCommand = null;
        if (!command.complete()) {
            return;
        }
        final Characteristic characteristic = target.characteristic;
        final UUID descriptorUuid = target.descriptorUuid;
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onSubscriptionResult(command.generation, command.token,
                            characteristic, descriptorUuid, status);
                }
            }
        });
    }

    private void onMtuChangedOnBle(BluetoothGatt callbackGatt, final int mtu, final int status) {
        if (callbackGatt != gatt || mtuCommand == null) {
            return;
        }
        final Command command = mtuCommand;
        mtuCommand = null;
        if (!command.complete()) {
            return;
        }
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onMtuResult(command.generation, command.token, mtu, status);
                }
            }
        });
    }

    private void onCharacteristicWriteOnBle(BluetoothGatt callbackGatt,
            BluetoothGattCharacteristic characteristic, final int status) {
        if (callbackGatt != gatt || characteristic != writeCharacteristic || writeCommand == null) {
            return;
        }
        final Command command = writeCommand;
        final Characteristic pure = nativeToPure.get(characteristic);
        final Characteristic expected = writeTarget;
        if (pure == null || pure != expected || !StockQixUuids.FD02.equals(pure.uuid())) {
            return;
        }
        writeCommand = null;
        writeCharacteristic = null;
        writeTarget = null;
        adapter.deliverExactFd02Write(command.completion,
                new AdapterSeam.ListenerSupplier() {
                    @Override public Listener current() {
                        return listener;
                    }
                }, command.generation, command.token, expected, pure, status);
    }

    private void onCharacteristicChangedOnBle(BluetoothGatt callbackGatt,
            BluetoothGattCharacteristic characteristic, byte[] value) {
        if (callbackGatt != gatt || characteristic == null || value == null) {
            return;
        }
        final Characteristic pure = nativeToPure.get(characteristic);
        if (pure == null) {
            return;
        }
        adapter.deliverNotification(new AdapterSeam.ListenerSupplier() {
            @Override public Listener current() {
                return listener;
            }
        }, sessionGeneration, pure, value);
    }

    private List<Service> convertServices(List<BluetoothGattService> nativeServices) {
        if (nativeServices == null) {
            return Collections.emptyList();
        }
        nativeToPure.clear();
        pureToNative.clear();
        List<Service> converted = new ArrayList<Service>(nativeServices.size());
        for (BluetoothGattService nativeService : nativeServices) {
            if (nativeService == null || nativeService.getUuid() == null) {
                continue;
            }
            List<Characteristic> convertedCharacteristics = new ArrayList<Characteristic>();
            List<BluetoothGattCharacteristic> nativeCharacteristics = nativeService.getCharacteristics();
            if (nativeCharacteristics != null) {
                for (BluetoothGattCharacteristic nativeCharacteristic : nativeCharacteristics) {
                    if (nativeCharacteristic == null || nativeCharacteristic.getUuid() == null) {
                        continue;
                    }
                    List<UUID> descriptorUuids = new ArrayList<UUID>();
                    List<BluetoothGattDescriptor> descriptors = nativeCharacteristic.getDescriptors();
                    if (descriptors != null) {
                        for (BluetoothGattDescriptor descriptor : descriptors) {
                            if (descriptor != null && descriptor.getUuid() != null) {
                                descriptorUuids.add(descriptor.getUuid());
                            }
                        }
                    }
                    Characteristic pure = new Characteristic(nativeCharacteristic.getUuid(),
                            nativeCharacteristic.getProperties(), descriptorUuids);
                    convertedCharacteristics.add(pure);
                    nativeToPure.put(nativeCharacteristic, pure);
                    pureToNative.put(pure, nativeCharacteristic);
                }
            }
            converted.add(new Service(nativeService.getUuid(), convertedCharacteristics));
        }
        return Collections.unmodifiableList(converted);
    }

    private void scanFailure(final Command command, final int status) {
        if (command != scanCommand || !command.complete()) {
            return;
        }
        scanCommand = null;
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onScanFailed(command.generation, command.token, status);
                }
            }
        });
    }

    private void connectionFailure(final Command command, final int status) {
        if (command != connectCommand || !command.complete()) {
            return;
        }
        connectCommand = null;
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onConnectionResult(command.generation, command.token, status);
                }
            }
        });
    }

    private void servicesFailure(final Command command, final int status) {
        if (command != discoverCommand || !command.complete()) {
            return;
        }
        discoverCommand = null;
        postServices(command, Collections.<Service>emptyList(), status);
    }

    private void subscriptionFailure(final Command command, final Characteristic characteristic,
            final UUID descriptorUuid, final int status) {
        if (command != subscriptionCommand || !command.complete()) {
            return;
        }
        subscriptionCommand = null;
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onSubscriptionResult(command.generation, command.token,
                            characteristic, descriptorUuid, status);
                }
            }
        });
    }

    private void mtuFailure(final Command command, final int mtu, final int status) {
        if (command != mtuCommand || !command.complete()) {
            return;
        }
        mtuCommand = null;
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onMtuResult(command.generation, command.token, mtu, status);
                }
            }
        });
    }

    private void writeFailure(final Command command, final Characteristic characteristic,
            final int status) {
        if (command != writeCommand || !command.complete()) {
            return;
        }
        writeCommand = null;
        writeTarget = null;
        writeCharacteristic = null;
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onCharacteristicWrite(command.generation, command.token,
                            characteristic, status);
                }
            }
        });
    }

    private void postServices(final Command command, final List<Service> services,
            final int status) {
        postCallback(new Runnable() {
            @Override public void run() {
                Listener current = listener;
                if (current != null) {
                    current.onServicesResult(command.generation, command.token, services, status);
                }
            }
        });
    }

    private void postCallback(Runnable callback) {
        adapter.postToCallback(callback);
    }

    private void stopScannerOnBle() {
        Command previous = scanCommand;
        scanCommand = null;
        ScanCallback callback = scanCallback;
        scanCallback = null;
        BluetoothLeScanner currentScanner = scanner;
        if (previous != null) {
            previous.complete();
        }
        if (currentScanner != null && callback != null) {
            try {
                currentScanner.stopScan(callback);
            } catch (SecurityException ignored) {
                // Best-effort close.
            }
        }
    }

    private void clearPendingCommands() {
        complete(scanCommand);
        complete(connectCommand);
        complete(discoverCommand);
        complete(subscriptionCommand);
        complete(mtuCommand);
        complete(writeCommand);
        scanCommand = null;
        connectCommand = null;
        discoverCommand = null;
        subscriptionCommand = null;
        mtuCommand = null;
        writeCommand = null;
        writeCharacteristic = null;
        writeTarget = null;
    }

    private static void complete(Command command) {
        if (command != null) {
            command.complete();
        }
    }

    private final class ScanBridge extends ScanCallback {
        private final Command command;

        ScanBridge(Command command) {
            this.command = command;
        }

        @Override public void onScanResult(int callbackType, final ScanResult result) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onScanResultOnBle(command, result);
                }
            });
        }

        @Override public void onScanFailed(final int errorCode) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onScanFailureOnBle(command, errorCode);
                }
            });
        }
    }

    private final class CallbackBridge extends BluetoothGattCallback {
        @Override public void onConnectionStateChange(final BluetoothGatt callbackGatt,
                final int status, final int newState) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onConnectionStateChangeOnBle(callbackGatt, status, newState);
                }
            });
        }

        @Override public void onServicesDiscovered(final BluetoothGatt callbackGatt,
                final int status) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onServicesDiscoveredOnBle(callbackGatt, status);
                }
            });
        }

        @Override public void onDescriptorWrite(final BluetoothGatt callbackGatt,
                final BluetoothGattDescriptor descriptor, final int status) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onDescriptorWriteOnBle(callbackGatt, descriptor, status);
                }
            });
        }

        @Override public void onMtuChanged(final BluetoothGatt callbackGatt, final int mtu,
                final int status) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onMtuChangedOnBle(callbackGatt, mtu, status);
                }
            });
        }

        @Override public void onCharacteristicWrite(final BluetoothGatt callbackGatt,
                final BluetoothGattCharacteristic characteristic, final int status) {
            postToBle(new Runnable() {
                @Override public void run() {
                    onCharacteristicWriteOnBle(callbackGatt, characteristic, status);
                }
            });
        }

        @Override public void onCharacteristicChanged(final BluetoothGatt callbackGatt,
                final BluetoothGattCharacteristic characteristic, final byte[] value) {
            final byte[] copied = adapter.copyApi33Notification(value);
            postToBle(new Runnable() {
                @Override public void run() {
                    onCharacteristicChangedOnBle(callbackGatt, characteristic, copied);
                }
            });
        }

        @SuppressWarnings("deprecation")
        @Override public void onCharacteristicChanged(final BluetoothGatt callbackGatt,
                final BluetoothGattCharacteristic characteristic) {
            final byte[] copied = adapter.copyLegacyNotification(
                    new AdapterSeam.LegacyValueSource() {
                        @Override public byte[] value() {
                            return characteristic == null ? null : characteristic.getValue();
                        }
                    });
            postToBle(new Runnable() {
                @Override public void run() {
                    onCharacteristicChangedOnBle(callbackGatt, characteristic, copied);
                }
            });
        }
    }

    /**
     * Small Android-final-class seam shared by the framework adapter and its unit tests.
     *
     * <p>It owns only handler acceptance, callback dispatch, and the branch ordering whose
     * Android framework objects cannot be constructed in local unit tests. Android calls remain
     * in this enclosing transport.
     */
    static final class AdapterSeam {
        enum TaggedKind {
            SCAN, CONNECT, DISCOVER, SUBSCRIBE, MTU, WRITE
        }

        interface HandlerPoster {
            boolean post(Runnable command);
        }

        interface PlatformStart {
            boolean start();
        }

        interface SubscriptionPort {
            boolean setCharacteristicNotification();
            Object findDescriptor();
            boolean setLegacyValue(Object descriptor, byte[] value);
            boolean writeLegacyDescriptor(Object descriptor);
            boolean writeModernDescriptor(Object descriptor, byte[] value);
        }

        interface WritePort {
            boolean setWriteType(int writeType);
            boolean setLegacyValue(byte[] value);
            boolean writeLegacyCharacteristic();
            boolean writeModernCharacteristic(byte[] value, int writeType);
        }

        interface ListenerSupplier {
            StockGattDriver.Listener current();
        }

        interface LegacyValueSource {
            byte[] value();
        }

        static final class CallbackTag {
            private final TaggedKind kind;
            private final long generation;
            private final long token;
            private final StockGattDriver.Characteristic characteristic;
            private final UUID descriptorUuid;
            private final int mtu;

            private CallbackTag(TaggedKind kind, long generation, long token,
                    StockGattDriver.Characteristic characteristic, UUID descriptorUuid, int mtu) {
                this.kind = kind;
                this.generation = generation;
                this.token = token;
                this.characteristic = characteristic;
                this.descriptorUuid = descriptorUuid;
                this.mtu = mtu;
            }

            static CallbackTag scan(long generation, long token) {
                return new CallbackTag(TaggedKind.SCAN, generation, token, null, null, 0);
            }

            static CallbackTag connect(long generation, long token) {
                return new CallbackTag(TaggedKind.CONNECT, generation, token, null, null, 0);
            }

            static CallbackTag discover(long generation, long token) {
                return new CallbackTag(TaggedKind.DISCOVER, generation, token, null, null, 0);
            }

            static CallbackTag subscription(long generation, long token,
                    StockGattDriver.Characteristic characteristic, UUID descriptorUuid) {
                if (characteristic == null || descriptorUuid == null) {
                    throw new IllegalArgumentException("subscription callback tag must be complete");
                }
                return new CallbackTag(TaggedKind.SUBSCRIBE, generation, token, characteristic,
                        descriptorUuid, 0);
            }

            static CallbackTag mtu(long generation, long token, int mtu) {
                return new CallbackTag(TaggedKind.MTU, generation, token, null, null, mtu);
            }

            static CallbackTag write(long generation, long token,
                    StockGattDriver.Characteristic characteristic) {
                if (characteristic == null) {
                    throw new IllegalArgumentException("write callback tag needs characteristic");
                }
                return new CallbackTag(TaggedKind.WRITE, generation, token, characteristic,
                        null, 0);
            }

            TaggedKind kind() {
                return kind;
            }

            long generation() {
                return generation;
            }

            long token() {
                return token;
            }
        }

        static final class CompletionGate {
            private boolean completed;

            synchronized boolean claim() {
                if (completed) {
                    return false;
                }
                completed = true;
                return true;
            }

            synchronized boolean isClaimed() {
                return completed;
            }
        }

        private static final byte[] VENDOR_CCCD_VALUE = new byte[] {2, 0};

        private final HandlerPoster handlerPoster;
        private final Executor callbackExecutor;

        AdapterSeam(HandlerPoster handlerPoster, Executor callbackExecutor) {
            if (handlerPoster == null || callbackExecutor == null) {
                throw new IllegalArgumentException("adapter seam inputs must not be null");
            }
            this.handlerPoster = handlerPoster;
            this.callbackExecutor = callbackExecutor;
        }

        boolean postToBle(Runnable command) {
            if (command == null) {
                throw new IllegalArgumentException("BLE command must not be null");
            }
            try {
                return handlerPoster.post(command);
            } catch (RuntimeException rejected) {
                return false;
            }
        }

        void postToCallback(Runnable callback) {
            if (callback == null) {
                throw new IllegalArgumentException("callback must not be null");
            }
            try {
                callbackExecutor.execute(callback);
            } catch (RuntimeException ignored) {
                // Never call a driver listener inline when its shared FIFO is closed.
            }
        }

        boolean attemptPlatformStart(PlatformStart start) {
            if (start == null) {
                throw new IllegalArgumentException("platform start must not be null");
            }
            try {
                return start.start();
            } catch (SecurityException denied) {
                return false;
            } catch (RuntimeException failed) {
                return false;
            }
        }

        boolean attemptPlatformStartOrDeliver(PlatformStart start, CompletionGate completion,
                ListenerSupplier listenerSupplier, CallbackTag tag) {
            if (completion == null || listenerSupplier == null || tag == null) {
                throw new IllegalArgumentException("platform callback inputs must not be null");
            }
            if (attemptPlatformStart(start)) {
                return true;
            }
            deliverTaggedResult(completion, listenerSupplier, tag, FAILURE_STATUS);
            return false;
        }

        Object startSubscription(int sdkInt, SubscriptionPort port, byte[] requestedValue) {
            if (port == null || requestedValue == null) {
                throw new IllegalArgumentException("subscription inputs must not be null");
            }
            if (!Arrays.equals(VENDOR_CCCD_VALUE, requestedValue)) {
                return null;
            }
            try {
                if (!port.setCharacteristicNotification()) {
                    return null;
                }
                Object descriptor = port.findDescriptor();
                if (descriptor == null) {
                    return null;
                }
                byte[] copy = Arrays.copyOf(VENDOR_CCCD_VALUE, VENDOR_CCCD_VALUE.length);
                if (sdkInt >= 33) {
                    return port.writeModernDescriptor(descriptor, copy) ? descriptor : null;
                }
                if (!port.setLegacyValue(descriptor, copy)) {
                    return null;
                }
                return port.writeLegacyDescriptor(descriptor) ? descriptor : null;
            } catch (SecurityException denied) {
                return null;
            } catch (RuntimeException failed) {
                return null;
            }
        }

        Object startSubscriptionOrDeliver(int sdkInt, SubscriptionPort port, byte[] requestedValue,
                CompletionGate completion, ListenerSupplier listenerSupplier, CallbackTag tag) {
            if (completion == null || listenerSupplier == null || tag == null) {
                throw new IllegalArgumentException("subscription callback inputs must not be null");
            }
            Object descriptor = startSubscription(sdkInt, port, requestedValue);
            if (descriptor != null) {
                return descriptor;
            }
            deliverTaggedResult(completion, listenerSupplier, tag, FAILURE_STATUS);
            return null;
        }

        boolean startWrite(int sdkInt, WritePort port, byte[] value, int writeType) {
            if (port == null || value == null) {
                throw new IllegalArgumentException("write inputs must not be null");
            }
            byte[] copy = Arrays.copyOf(value, value.length);
            try {
                if (sdkInt >= 33) {
                    return port.writeModernCharacteristic(copy, writeType);
                }
                if (!port.setWriteType(writeType) || !port.setLegacyValue(copy)) {
                    return false;
                }
                return port.writeLegacyCharacteristic();
            } catch (SecurityException denied) {
                return false;
            } catch (RuntimeException failed) {
                return false;
            }
        }

        boolean startWriteOrDeliver(int sdkInt, WritePort port, byte[] value, int writeType,
                CompletionGate completion, ListenerSupplier listenerSupplier, CallbackTag tag) {
            if (completion == null || listenerSupplier == null || tag == null) {
                throw new IllegalArgumentException("write callback inputs must not be null");
            }
            if (startWrite(sdkInt, port, value, writeType)) {
                return true;
            }
            deliverTaggedResult(completion, listenerSupplier, tag, FAILURE_STATUS);
            return false;
        }

        boolean deliverTaggedResult(final CompletionGate completion,
                final ListenerSupplier listenerSupplier, final CallbackTag tag, final int status) {
            if (completion == null || listenerSupplier == null || tag == null) {
                throw new IllegalArgumentException("tagged callback inputs must not be null");
            }
            if (!completion.claim()) {
                return false;
            }
            postToCallback(new Runnable() {
                @Override public void run() {
                    StockGattDriver.Listener current = listenerSupplier.current();
                    if (current == null) {
                        return;
                    }
                    switch (tag.kind) {
                        case SCAN:
                            current.onScanFailed(tag.generation, tag.token, status);
                            return;
                        case CONNECT:
                            current.onConnectionResult(tag.generation, tag.token, status);
                            return;
                        case DISCOVER:
                            current.onServicesResult(tag.generation, tag.token,
                                    Collections.<StockGattDriver.Service>emptyList(), status);
                            return;
                        case SUBSCRIBE:
                            current.onSubscriptionResult(tag.generation, tag.token,
                                    tag.characteristic, tag.descriptorUuid, status);
                            return;
                        case MTU:
                            current.onMtuResult(tag.generation, tag.token, tag.mtu, status);
                            return;
                        case WRITE:
                            current.onCharacteristicWrite(tag.generation, tag.token,
                                    tag.characteristic, status);
                            return;
                        default:
                            throw new AssertionError(tag.kind);
                    }
                }
            });
            return true;
        }

        byte[] copyApi33Notification(byte[] value) {
            return copyNotification(value);
        }

        byte[] copyLegacyNotification(LegacyValueSource source) {
            if (source == null) {
                throw new IllegalArgumentException("legacy notification source must not be null");
            }
            return copyNotification(source.value());
        }

        private static byte[] copyNotification(byte[] value) {
            return value == null ? null : Arrays.copyOf(value, value.length);
        }

        void deliverExactFd02Write(final CompletionGate completion,
                final ListenerSupplier listenerSupplier, final long generation, final long token,
                final Characteristic expected, final Characteristic actual, final int status) {
            if (completion == null || listenerSupplier == null) {
                throw new IllegalArgumentException("write completion inputs must not be null");
            }
            if (expected != actual || actual == null || !StockQixUuids.FD02.equals(actual.uuid())
                    || !completion.claim()) {
                return;
            }
            postToCallback(new Runnable() {
                @Override public void run() {
                    StockGattDriver.Listener current = listenerSupplier.current();
                    if (current != null) {
                        current.onCharacteristicWrite(generation, token, actual, status);
                    }
                }
            });
        }

        void deliverNotification(final ListenerSupplier listenerSupplier, final long generation,
                final Characteristic characteristic, byte[] value) {
            if (listenerSupplier == null || characteristic == null || value == null) {
                throw new IllegalArgumentException("notification inputs must not be null");
            }
            final byte[] copied = Arrays.copyOf(value, value.length);
            postToCallback(new Runnable() {
                @Override public void run() {
                    StockGattDriver.Listener current = listenerSupplier.current();
                    if (current != null) {
                        current.onNotification(generation, characteristic, copied);
                    }
                }
            });
        }
    }

    private static final class Command {
        final long generation;
        final long token;
        final CommandKind kind;
        final AdapterSeam.CompletionGate completion = new AdapterSeam.CompletionGate();

        Command(long generation, long token, CommandKind kind) {
            this.generation = generation;
            this.token = token;
            this.kind = kind;
        }

        synchronized boolean complete() {
            return completion.claim();
        }

        boolean isCompleted() {
            return completion.isClaimed();
        }
    }

    private static final class DescriptorTarget {
        final Command command;
        final Characteristic characteristic;
        final UUID descriptorUuid;

        DescriptorTarget(Command command, Characteristic characteristic, UUID descriptorUuid) {
            this.command = command;
            this.characteristic = characteristic;
            this.descriptorUuid = descriptorUuid;
        }
    }
}
