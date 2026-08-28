package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.os.Handler;
import java.lang.reflect.Constructor;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.Executor;
import org.junit.Test;

public final class StockQixGattTransportTest {
    @Test public void transportIsFinalAndExposesOnlyTheApprovedPublicConstructor() {
        assertTrue(Modifier.isFinal(StockQixGattTransport.class.getModifiers()));
        assertTrue(StockGattDriver.class.isAssignableFrom(StockQixGattTransport.class));
        Constructor<?>[] constructors = StockQixGattTransport.class.getDeclaredConstructors();
        assertEquals(1, constructors.length);
        assertTrue(Modifier.isPublic(constructors[0].getModifiers()));
        assertEquals(Arrays.asList(Context.class, Handler.class, Executor.class),
                Arrays.asList(constructors[0].getParameterTypes()));
    }

    @Test public void transportSourcePinsBleHandlerAcceptanceAndExactAndroidBranches()
            throws Exception {
        String source = transitionSource("StockQixGattTransport.java");
        String compact = source.replaceAll("\\s+", " ");

        assertTrue(compact.contains("bleHandler.post("));
        assertTrue(compact.contains("BluetoothDevice.TRANSPORT_LE"));
        assertTrue(compact.contains("BluetoothDevice.PHY_LE_1M_MASK"));
        assertTrue(compact.contains("bleHandler)"));
        assertTrue(source.contains("setCharacteristicNotification"));
        assertTrue(source.contains("new byte[] {2, 0}"));
        assertFalse(source.contains("ENABLE_NOTIFICATION_VALUE"));
        assertTrue(source.contains("setLegacyValue"));
        assertTrue(source.contains("writeLegacyDescriptor"));
        assertTrue(source.contains("current.writeDescriptor("));
        assertTrue(source.contains("writeDescriptorApi33"));
        assertTrue(source.contains("BluetoothStatusCodes.SUCCESS"));
        assertTrue(source.contains("nativeCharacteristic.setValue(value)"));
        assertTrue(source.contains("writeLegacyCharacteristic"));
        assertTrue(source.contains("writeCharacteristicApi33"));
        assertTrue(source.contains("Arrays.copyOf"));
        assertTrue(source.contains("onDescriptorWrite"));
        assertTrue(source.contains("onCharacteristicChanged"));
        assertTrue(source.contains("adapter.attemptPlatformStart"));
        assertTrue(source.contains("adapter.startSubscription"));
        assertTrue(source.contains("adapter.startWrite"));
        assertTrue(source.contains("adapter.deliverExactFd02Write"));
        assertTrue(source.contains("adapter.deliverNotification"));
    }

    @Test public void androidImportsAreConfinedToTransportAndNoNormalOrAarTypesLeakIn()
            throws Exception {
        String transport = transitionSource("StockQixGattTransport.java");
        assertTrue(transport.contains("import android.bluetooth"));
        assertFalse(transport.contains("ble.normal"));
        assertFalse(transport.contains("BluetoothOTAManager"));
        assertFalse(transport.contains("com.jieli"));

        for (String pure : Arrays.asList("StockGattDriver.java",
                "StockTransitionController.java")) {
            String source = transitionSource(pure);
            assertFalse(pure, source.contains("import android."));
            assertFalse(pure, source.contains("ble.normal"));
            assertFalse(pure, source.contains("BluetoothOTAManager"));
            assertFalse(pure, source.contains("com.jieli"));
        }
    }

    @Test public void adapterSeamSeparatesHandlerAndFifoAndConvertsStartFailures() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);
        final List<String> calls = new ArrayList<String>();

        assertTrue(seam.postToBle(new Runnable() {
            @Override public void run() {
                calls.add("platform");
                seam.postToCallback(new Runnable() {
                    @Override public void run() {
                        calls.add("listener");
                    }
                });
            }
        }));
        assertTrue(calls.isEmpty());
        handler.drain();
        assertEquals(Arrays.asList("platform"), calls);
        fifo.drain();
        assertEquals(Arrays.asList("platform", "listener"), calls);

        assertFalse(seam.attemptPlatformStart(new StockQixGattTransport.AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                return false;
            }
        }));
        assertFalse(seam.attemptPlatformStart(new StockQixGattTransport.AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                throw new SecurityException("denied");
            }
        }));
        assertFalse(seam.attemptPlatformStart(new StockQixGattTransport.AdapterSeam.PlatformStart() {
            @Override public boolean start() {
                throw new IllegalStateException("platform failed");
            }
        }));
    }

    @Test public void adapterSeamPinsDescriptorOrderFailureBranchesAndDefensiveCopies() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);
        FakeSubscriptionPort legacy = new FakeSubscriptionPort();
        byte[] desired = new byte[] {2, 0};

        assertSame(legacy.descriptor, seam.startSubscription(32, legacy, desired));
        desired[0] = 1;
        assertEquals(Arrays.asList("enable", "descriptor", "setValue", "writeLegacy"),
                legacy.calls);
        assertArrayEquals(new byte[] {2, 0}, legacy.legacyValue);

        FakeSubscriptionPort nullDescriptor = new FakeSubscriptionPort();
        nullDescriptor.returnNullDescriptor = true;
        assertNull(seam.startSubscription(32, nullDescriptor, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable", "descriptor"), nullDescriptor.calls);

        FakeSubscriptionPort setValueFalse = new FakeSubscriptionPort();
        setValueFalse.legacySetValueResult = false;
        assertNull(seam.startSubscription(32, setValueFalse, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable", "descriptor", "setValue"), setValueFalse.calls);

        FakeSubscriptionPort modernNonSuccess = new FakeSubscriptionPort();
        modernNonSuccess.modernWriteResult = false;
        assertNull(seam.startSubscription(33, modernNonSuccess, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable", "descriptor", "writeModern"),
                modernNonSuccess.calls);

        FakeSubscriptionPort denied = new FakeSubscriptionPort();
        denied.throwSecurityOnEnable = true;
        assertNull(seam.startSubscription(32, denied, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable"), denied.calls);
    }

    @Test public void adapterSeamPinsWriteBranchesAndExactCopiedCallbackIdentity() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);
        FakeWritePort legacy = new FakeWritePort();
        legacy.legacySetValueResult = false;
        assertFalse(seam.startWrite(32, legacy, new byte[] {9, 8},
                StockGattDriver.WRITE_TYPE_DEFAULT));
        assertEquals(Arrays.asList("setType", "setValue"), legacy.calls);

        FakeWritePort modern = new FakeWritePort();
        modern.modernWriteResult = false;
        assertFalse(seam.startWrite(33, modern, new byte[] {9, 8},
                StockGattDriver.WRITE_TYPE_DEFAULT));
        assertEquals(Arrays.asList("writeModern"), modern.calls);

        RecordingDriverListener listener = new RecordingDriverListener();
        StockQixGattTransport.AdapterSeam.ListenerSupplier supplier =
                new StockQixGattTransport.AdapterSeam.ListenerSupplier() {
                    @Override public StockGattDriver.Listener current() {
                        return listener;
                    }
                };
        StockQixGattTransport.AdapterSeam.CompletionGate gate =
                new StockQixGattTransport.AdapterSeam.CompletionGate();
        StockGattDriver.Characteristic expected = new StockGattDriver.Characteristic(
                StockQixUuids.FD02, 0x0C, Arrays.<UUID>asList());
        StockGattDriver.Characteristic sameUuidDifferentObject =
                new StockGattDriver.Characteristic(StockQixUuids.FD02, 0x0C,
                        Arrays.<UUID>asList());

        seam.deliverExactFd02Write(gate, supplier, 7, 8, expected,
                sameUuidDifferentObject, StockGattDriver.STATUS_SUCCESS);
        fifo.drain();
        assertTrue(listener.writes.isEmpty());

        seam.deliverExactFd02Write(gate, supplier, 7, 8, expected, expected,
                StockGattDriver.STATUS_SUCCESS);
        assertTrue(listener.writes.isEmpty());
        fifo.drain();
        assertEquals(1, listener.writes.size());
        assertSame(expected, listener.writes.get(0));
        seam.deliverExactFd02Write(gate, supplier, 7, 8, expected, expected,
                StockGattDriver.STATUS_SUCCESS);
        fifo.drain();
        assertEquals(1, listener.writes.size());

        byte[] notification = new byte[] {4, 5, 6};
        seam.deliverNotification(supplier, 7, expected, notification);
        notification[0] = 99;
        assertTrue(listener.notifications.isEmpty());
        fifo.drain();
        assertArrayEquals(new byte[] {4, 5, 6}, listener.notifications.get(0));
    }

    private static StockQixGattTransport.AdapterSeam seam(final FakeBleHandlerQueue handler,
            FifoExecutor fifo) {
        return new StockQixGattTransport.AdapterSeam(
                new StockQixGattTransport.AdapterSeam.HandlerPoster() {
                    @Override public boolean post(Runnable command) {
                        return handler.post("transport", command);
                    }
                }, fifo);
    }

    private static final class FakeSubscriptionPort
            implements StockQixGattTransport.AdapterSeam.SubscriptionPort {
        final Object descriptor = new Object();
        final List<String> calls = new ArrayList<String>();
        boolean returnNullDescriptor;
        boolean legacySetValueResult = true;
        boolean modernWriteResult = true;
        boolean throwSecurityOnEnable;
        byte[] legacyValue;

        @Override public boolean setCharacteristicNotification() {
            calls.add("enable");
            if (throwSecurityOnEnable) {
                throw new SecurityException("denied");
            }
            return true;
        }

        @Override public Object findDescriptor() {
            calls.add("descriptor");
            return returnNullDescriptor ? null : descriptor;
        }

        @Override public boolean setLegacyValue(Object target, byte[] value) {
            calls.add("setValue");
            legacyValue = Arrays.copyOf(value, value.length);
            return legacySetValueResult;
        }

        @Override public boolean writeLegacyDescriptor(Object target) {
            calls.add("writeLegacy");
            return true;
        }

        @Override public boolean writeModernDescriptor(Object target, byte[] value) {
            calls.add("writeModern");
            return modernWriteResult;
        }
    }

    private static final class FakeWritePort
            implements StockQixGattTransport.AdapterSeam.WritePort {
        final List<String> calls = new ArrayList<String>();
        boolean legacySetValueResult = true;
        boolean modernWriteResult = true;

        @Override public boolean setWriteType(int writeType) {
            calls.add("setType");
            return true;
        }

        @Override public boolean setLegacyValue(byte[] value) {
            calls.add("setValue");
            return legacySetValueResult;
        }

        @Override public boolean writeLegacyCharacteristic() {
            calls.add("writeLegacy");
            return true;
        }

        @Override public boolean writeModernCharacteristic(byte[] value, int writeType) {
            calls.add("writeModern");
            return modernWriteResult;
        }
    }

    private static final class RecordingDriverListener implements StockGattDriver.Listener {
        final List<StockGattDriver.Characteristic> writes =
                new ArrayList<StockGattDriver.Characteristic>();
        final List<byte[]> notifications = new ArrayList<byte[]>();

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
            writes.add(characteristic);
        }

        @Override public void onNotification(long generation,
                StockGattDriver.Characteristic characteristic, byte[] value) {
            notifications.add(Arrays.copyOf(value, value.length));
        }
    }

    private static String transitionSource(String name) throws Exception {
        return new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/transition/" + name)),
                StandardCharsets.UTF_8);
    }
}
