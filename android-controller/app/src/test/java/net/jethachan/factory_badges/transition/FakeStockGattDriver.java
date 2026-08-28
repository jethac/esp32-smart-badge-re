package net.jethachan.factory_badges.transition;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

/** Deterministic test driver that records commands and injects tagged asynchronous callbacks. */
final class FakeStockGattDriver implements StockGattDriver {
    final List<String> calls = new ArrayList<String>();
    final List<byte[]> writeValues = new ArrayList<byte[]>();
    final List<Long> writeTokens = new ArrayList<Long>();
    final List<Characteristic> writeCharacteristics = new ArrayList<Characteristic>();

    boolean startScanAccepted = true;
    boolean connectAccepted = true;
    boolean discoverAccepted = true;
    boolean subscribeAccepted = true;
    boolean mtuAccepted = true;
    boolean writeAccepted = true;

    Listener listener;
    long scanGeneration;
    long scanToken;
    long connectGeneration;
    long connectToken;
    Peer connectPeer;
    long discoverGeneration;
    long discoverToken;
    long subscriptionGeneration;
    long subscriptionToken;
    Characteristic subscriptionCharacteristic;
    UUID subscriptionDescriptor;
    byte[] subscriptionValue;
    long mtuGeneration;
    long mtuToken;
    int requestedMtu;
    long writeGeneration;
    long writeToken;
    Characteristic writeCharacteristic;
    int writeType;
    long stoppedScanGeneration;
    long disconnectedGeneration;
    int closeCalls;

    @Override public void setListener(Listener listener) {
        if (listener == null) {
            throw new IllegalArgumentException("listener must not be null");
        }
        this.listener = listener;
        calls.add("setListener");
    }

    @Override public boolean startScan(long generation, long token) {
        calls.add("startScan");
        scanGeneration = generation;
        scanToken = token;
        return startScanAccepted;
    }

    @Override public void stopScan(long generation) {
        calls.add("stopScan");
        stoppedScanGeneration = generation;
    }

    @Override public boolean connect(long generation, long token, Peer peer) {
        calls.add("connect");
        connectGeneration = generation;
        connectToken = token;
        connectPeer = peer;
        return connectAccepted;
    }

    @Override public boolean discoverServices(long generation, long token) {
        calls.add("discoverServices");
        discoverGeneration = generation;
        discoverToken = token;
        return discoverAccepted;
    }

    @Override public boolean subscribe(long generation, long token, Characteristic characteristic,
            UUID descriptorUuid, byte[] value) {
        calls.add("subscribe");
        subscriptionGeneration = generation;
        subscriptionToken = token;
        subscriptionCharacteristic = characteristic;
        subscriptionDescriptor = descriptorUuid;
        subscriptionValue = Arrays.copyOf(value, value.length);
        return subscribeAccepted;
    }

    @Override public boolean requestMtu(long generation, long token, int mtu) {
        calls.add("requestMtu");
        mtuGeneration = generation;
        mtuToken = token;
        requestedMtu = mtu;
        return mtuAccepted;
    }

    @Override public boolean writeCharacteristic(long generation, long token,
            Characteristic characteristic, byte[] value, int writeType) {
        calls.add("writeCharacteristic");
        writeGeneration = generation;
        writeToken = token;
        writeCharacteristic = characteristic;
        this.writeType = writeType;
        writeCharacteristics.add(characteristic);
        writeTokens.add(token);
        writeValues.add(Arrays.copyOf(value, value.length));
        return writeAccepted;
    }

    @Override public void disconnect(long generation) {
        calls.add("disconnect");
        disconnectedGeneration = generation;
    }

    @Override public void close() {
        calls.add("close");
        closeCalls++;
    }

    void emitScanResult(long generation, long token, Peer peer) {
        requireListener().onScanResult(generation, token, peer);
    }

    void emitScanFailed(long generation, long token, int status) {
        requireListener().onScanFailed(generation, token, status);
    }

    void emitConnectionResult(long generation, long token, int status) {
        requireListener().onConnectionResult(generation, token, status);
    }

    void emitDisconnected(long generation, int status) {
        requireListener().onDisconnected(generation, status);
    }

    void emitServicesResult(long generation, long token, List<Service> services, int status) {
        requireListener().onServicesResult(generation, token, services, status);
    }

    void emitSubscriptionResult(long generation, long token, Characteristic characteristic,
            UUID descriptorUuid, int status) {
        requireListener().onSubscriptionResult(generation, token, characteristic,
                descriptorUuid, status);
    }

    void emitMtuResult(long generation, long token, int mtu, int status) {
        requireListener().onMtuResult(generation, token, mtu, status);
    }

    void emitCharacteristicWrite(long generation, long token, Characteristic characteristic,
            int status) {
        requireListener().onCharacteristicWrite(generation, token, characteristic, status);
    }

    void emitNotification(long generation, Characteristic characteristic, byte[] value) {
        requireListener().onNotification(generation, characteristic, value);
    }

    private Listener requireListener() {
        if (listener == null) {
            throw new IllegalStateException("listener was not registered");
        }
        return listener;
    }
}
