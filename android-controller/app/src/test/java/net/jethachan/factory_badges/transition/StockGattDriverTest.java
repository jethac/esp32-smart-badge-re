package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import org.junit.Test;

public final class StockGattDriverTest {
    @Test public void peerCanonicalizesAddressAndUsesOnlyAddressForIdentity() {
        StockGattDriver.Peer lower = new StockGattDriver.Peer(
                "aa:bb:cc:dd:ee:ff", "stock", -52);
        StockGattDriver.Peer upper = new StockGattDriver.Peer(
                "AA:BB:CC:DD:EE:FF", "renamed", -20);

        assertEquals("AA:BB:CC:DD:EE:FF", lower.address());
        assertEquals("stock", lower.displayName());
        assertEquals(-52, lower.rssi());
        assertEquals(lower, upper);
        assertEquals(lower.hashCode(), upper.hashCode());

        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Peer(null, "stock", 0));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Peer("AA:BB:CC:DD:EE:FF", null, 0));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Peer("AA:BB:CC:DD:EE", "stock", 0));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Peer("AA:BB:CC:DD:EE:GG", "stock", 0));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Peer("\uFF21\uFF21:BB:CC:DD:EE:FF", "stock", 0));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Peer("\u0660\u0660:BB:CC:DD:EE:FF", "stock", 0));
    }

    @Test public void serviceAndCharacteristicDefensivelyOwnTheirCollections() {
        UUID descriptor = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
        StockGattDriver.Characteristic characteristic = new StockGattDriver.Characteristic(
                StockQixUuids.FD01, StockGattDriver.NOTIFY, Arrays.asList(descriptor));
        List<StockGattDriver.Characteristic> mutable = new ArrayList<StockGattDriver.Characteristic>();
        mutable.add(characteristic);
        StockGattDriver.Service service = new StockGattDriver.Service(StockQixUuids.SERVICE, mutable);
        mutable.clear();

        assertEquals(1, service.characteristics().size());
        assertThrows(UnsupportedOperationException.class,
                () -> service.characteristics().add(characteristic));
        assertTrue(characteristic.hasDescriptor(descriptor));
        assertFalse(characteristic.hasDescriptor(UUID.fromString(
                "00002901-0000-1000-8000-00805f9b34fb")));
        assertThrows(IllegalArgumentException.class, () -> characteristic.hasDescriptor(null));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Service(null, Arrays.asList(characteristic)));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Service(StockQixUuids.SERVICE, null));
        assertThrows(IllegalArgumentException.class,
                () -> new StockGattDriver.Characteristic(StockQixUuids.FD01,
                        StockGattDriver.NOTIFY, null));
    }

    @Test public void constantsPinAcknowledgedWriteAndCapturedNotifyBoundary() {
        assertEquals(0, StockGattDriver.STATUS_SUCCESS);
        assertEquals(0x08, StockGattDriver.PROPERTY_WRITE);
        assertEquals(0x10, StockGattDriver.NOTIFY);
        assertEquals(0x20, StockGattDriver.INDICATE);
        assertEquals(2, StockGattDriver.WRITE_TYPE_DEFAULT);
    }

    @Test public void fakeBleHandlerQueueSeparatesAcceptanceOrderFromExecution() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        List<String> executed = new ArrayList<String>();

        assertTrue(handler.post("stopScan", () -> executed.add("stopScan")));
        assertTrue(handler.post("connect", () -> executed.add("connect")));
        assertEquals(Arrays.asList("stopScan", "connect"), handler.acceptedLabels);
        assertTrue(executed.isEmpty());
        handler.drain();
        assertEquals(Arrays.asList("stopScan", "connect"), executed);

        handler.acceptsPosts = false;
        assertFalse(handler.post("write", () -> executed.add("write")));
        assertEquals(0, handler.queuedCount());
    }

    @Test public void driverCallbacksAndValuesArePureAndDefensive() {
        byte[] value = new byte[] {2, 0};
        StockGattDriver.Characteristic characteristic = new StockGattDriver.Characteristic(
                StockQixUuids.FD01, StockGattDriver.NOTIFY, Arrays.asList(StockQixUuids.CCCD));
        FakeStockGattDriver driver = new FakeStockGattDriver();
        driver.setListener(new NoOpListener());
        driver.subscribe(3L, 4L, characteristic, StockQixUuids.CCCD, value);
        value[0] = 1;
        assertArrayEquals(new byte[] {2, 0}, driver.subscriptionValue);
    }

    private static final class NoOpListener implements StockGattDriver.Listener {
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
}
