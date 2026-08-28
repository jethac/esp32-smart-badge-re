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
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
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
        setValueFalse.legacySetValueOutcome = Outcome.FALSE;
        assertNull(seam.startSubscription(32, setValueFalse, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable", "descriptor", "setValue"), setValueFalse.calls);

        FakeSubscriptionPort modernNonSuccess = new FakeSubscriptionPort();
        modernNonSuccess.modernWriteOutcome = Outcome.FALSE;
        assertNull(seam.startSubscription(33, modernNonSuccess, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable", "descriptor", "writeModern"),
                modernNonSuccess.calls);

        FakeSubscriptionPort denied = new FakeSubscriptionPort();
        denied.localEnableOutcome = Outcome.SECURITY;
        assertNull(seam.startSubscription(32, denied, new byte[] {2, 0}));
        assertEquals(Arrays.asList("enable"), denied.calls);
    }

    @Test public void adapterSeamPinsWriteBranchesAndExactCopiedCallbackIdentity() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);
        FakeWritePort legacy = new FakeWritePort();
        legacy.legacySetValueOutcome = Outcome.FALSE;
        assertFalse(seam.startWrite(32, legacy, new byte[] {9, 8},
                StockGattDriver.WRITE_TYPE_DEFAULT));
        assertEquals(Arrays.asList("setType", "setValue"), legacy.calls);

        FakeWritePort modern = new FakeWritePort();
        modern.modernWriteOutcome = Outcome.FALSE;
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

    @Test public void adapterSeamDeliversEveryStartFailureExactlyOnceAndSuppressesSuccess() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);

        assertStartFailure(seam, fifo, StockQixGattTransport.AdapterSeam.TaggedKind.SCAN,
                Outcome.FALSE);
        assertStartFailure(seam, fifo, StockQixGattTransport.AdapterSeam.TaggedKind.CONNECT,
                Outcome.FALSE);
        assertStartFailure(seam, fifo, StockQixGattTransport.AdapterSeam.TaggedKind.DISCOVER,
                Outcome.RUNTIME);
        assertStartFailure(seam, fifo, StockQixGattTransport.AdapterSeam.TaggedKind.MTU,
                Outcome.SECURITY);
    }

    @Test public void adapterSeamTagsEverySubscriptionImmediateFailureExactlyOnce() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);

        FakeSubscriptionPort enableFalse = new FakeSubscriptionPort();
        enableFalse.localEnableOutcome = Outcome.FALSE;
        assertSubscriptionFailure(seam, fifo, 32, enableFalse,
                Arrays.asList("enable"));

        FakeSubscriptionPort enableSecurity = new FakeSubscriptionPort();
        enableSecurity.localEnableOutcome = Outcome.SECURITY;
        assertSubscriptionFailure(seam, fifo, 32, enableSecurity,
                Arrays.asList("enable"));

        FakeSubscriptionPort enableRuntime = new FakeSubscriptionPort();
        enableRuntime.localEnableOutcome = Outcome.RUNTIME;
        assertSubscriptionFailure(seam, fifo, 32, enableRuntime,
                Arrays.asList("enable"));

        FakeSubscriptionPort nullDescriptor = new FakeSubscriptionPort();
        nullDescriptor.returnNullDescriptor = true;
        assertSubscriptionFailure(seam, fifo, 32, nullDescriptor,
                Arrays.asList("enable", "descriptor"));

        FakeSubscriptionPort legacySetValueFalse = new FakeSubscriptionPort();
        legacySetValueFalse.legacySetValueOutcome = Outcome.FALSE;
        assertSubscriptionFailure(seam, fifo, 32, legacySetValueFalse,
                Arrays.asList("enable", "descriptor", "setValue"));

        FakeSubscriptionPort legacySetValueRuntime = new FakeSubscriptionPort();
        legacySetValueRuntime.legacySetValueOutcome = Outcome.RUNTIME;
        assertSubscriptionFailure(seam, fifo, 32, legacySetValueRuntime,
                Arrays.asList("enable", "descriptor", "setValue"));

        FakeSubscriptionPort legacyWriteFalse = new FakeSubscriptionPort();
        legacyWriteFalse.legacyWriteOutcome = Outcome.FALSE;
        assertSubscriptionFailure(seam, fifo, 32, legacyWriteFalse,
                Arrays.asList("enable", "descriptor", "setValue", "writeLegacy"));

        FakeSubscriptionPort legacyWriteSecurity = new FakeSubscriptionPort();
        legacyWriteSecurity.legacyWriteOutcome = Outcome.SECURITY;
        assertSubscriptionFailure(seam, fifo, 32, legacyWriteSecurity,
                Arrays.asList("enable", "descriptor", "setValue", "writeLegacy"));

        FakeSubscriptionPort legacyWriteRuntime = new FakeSubscriptionPort();
        legacyWriteRuntime.legacyWriteOutcome = Outcome.RUNTIME;
        assertSubscriptionFailure(seam, fifo, 32, legacyWriteRuntime,
                Arrays.asList("enable", "descriptor", "setValue", "writeLegacy"));

        FakeSubscriptionPort modernWriteFalse = new FakeSubscriptionPort();
        modernWriteFalse.modernWriteOutcome = Outcome.FALSE;
        assertSubscriptionFailure(seam, fifo, 33, modernWriteFalse,
                Arrays.asList("enable", "descriptor", "writeModern"));

        FakeSubscriptionPort modernWriteSecurity = new FakeSubscriptionPort();
        modernWriteSecurity.modernWriteOutcome = Outcome.SECURITY;
        assertSubscriptionFailure(seam, fifo, 33, modernWriteSecurity,
                Arrays.asList("enable", "descriptor", "writeModern"));

        FakeSubscriptionPort modernWriteRuntime = new FakeSubscriptionPort();
        modernWriteRuntime.modernWriteOutcome = Outcome.RUNTIME;
        assertSubscriptionFailure(seam, fifo, 33, modernWriteRuntime,
                Arrays.asList("enable", "descriptor", "writeModern"));
    }

    @Test public void adapterSeamTagsEveryWriteImmediateFailureExactlyOnce() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);

        FakeWritePort legacySetValueFalse = new FakeWritePort();
        legacySetValueFalse.legacySetValueOutcome = Outcome.FALSE;
        assertWriteFailure(seam, fifo, 32, legacySetValueFalse,
                Arrays.asList("setType", "setValue"));

        FakeWritePort legacySetValueRuntime = new FakeWritePort();
        legacySetValueRuntime.legacySetValueOutcome = Outcome.RUNTIME;
        assertWriteFailure(seam, fifo, 32, legacySetValueRuntime,
                Arrays.asList("setType", "setValue"));

        FakeWritePort legacyWriteFalse = new FakeWritePort();
        legacyWriteFalse.legacyWriteOutcome = Outcome.FALSE;
        assertWriteFailure(seam, fifo, 32, legacyWriteFalse,
                Arrays.asList("setType", "setValue", "writeLegacy"));

        FakeWritePort legacyWriteSecurity = new FakeWritePort();
        legacyWriteSecurity.legacyWriteOutcome = Outcome.SECURITY;
        assertWriteFailure(seam, fifo, 32, legacyWriteSecurity,
                Arrays.asList("setType", "setValue", "writeLegacy"));

        FakeWritePort legacyWriteRuntime = new FakeWritePort();
        legacyWriteRuntime.legacyWriteOutcome = Outcome.RUNTIME;
        assertWriteFailure(seam, fifo, 32, legacyWriteRuntime,
                Arrays.asList("setType", "setValue", "writeLegacy"));

        FakeWritePort modernWriteFalse = new FakeWritePort();
        modernWriteFalse.modernWriteOutcome = Outcome.FALSE;
        assertWriteFailure(seam, fifo, 33, modernWriteFalse,
                Arrays.asList("writeModern"));

        FakeWritePort modernWriteSecurity = new FakeWritePort();
        modernWriteSecurity.modernWriteOutcome = Outcome.SECURITY;
        assertWriteFailure(seam, fifo, 33, modernWriteSecurity,
                Arrays.asList("writeModern"));

        FakeWritePort modernWriteRuntime = new FakeWritePort();
        modernWriteRuntime.modernWriteOutcome = Outcome.RUNTIME;
        assertWriteFailure(seam, fifo, 33, modernWriteRuntime,
                Arrays.asList("writeModern"));
    }

    @Test public void adapterSeamRoutesWorkerCallsToDesignatedThreadsInFifoOrder()
            throws Exception {
        ThreadRecordingHandler handler = new ThreadRecordingHandler();
        final List<String> handlerOrder = Collections.synchronizedList(new ArrayList<String>());
        final List<String> callbackOrder = Collections.synchronizedList(new ArrayList<String>());
        final List<String> handlerThreads = Collections.synchronizedList(new ArrayList<String>());
        final List<String> callbackThreads = Collections.synchronizedList(new ArrayList<String>());
        final List<Boolean> accepted = Collections.synchronizedList(new ArrayList<Boolean>());
        final CountDownLatch callbacks = new CountDownLatch(2);
        ExecutorService fifo = Executors.newSingleThreadExecutor(new ThreadFactory() {
            @Override public Thread newThread(Runnable runnable) {
                return new Thread(runnable, "designated-fifo");
            }
        });
        try {
            final StockQixGattTransport.AdapterSeam seam =
                    new StockQixGattTransport.AdapterSeam(handler, fifo);
            Thread worker = new Thread(new Runnable() {
                @Override public void run() {
                    accepted.add(seam.postToBle(threadedCommand(seam, "first", handlerOrder,
                            callbackOrder, handlerThreads, callbackThreads, callbacks)));
                    accepted.add(seam.postToBle(threadedCommand(seam, "second", handlerOrder,
                            callbackOrder, handlerThreads, callbackThreads, callbacks)));
                }
            }, "worker-caller");
            worker.start();
            worker.join();
            assertEquals(Arrays.asList(true, true), accepted);
            assertTrue(handlerOrder.isEmpty());
            assertTrue(callbackOrder.isEmpty());

            Thread bleHandlerThread = new Thread(new Runnable() {
                @Override public void run() {
                    handler.drain();
                }
            }, "designated-ble-handler");
            bleHandlerThread.start();
            bleHandlerThread.join();
            assertTrue(callbacks.await(5, TimeUnit.SECONDS));

            assertEquals(Arrays.asList("first", "second"), handlerOrder);
            assertEquals(Arrays.asList("first", "second"), callbackOrder);
            assertEquals(Arrays.asList("designated-ble-handler", "designated-ble-handler"),
                    handlerThreads);
            assertEquals(Arrays.asList("designated-fifo", "designated-fifo"), callbackThreads);
        } finally {
            fifo.shutdownNow();
            assertTrue(fifo.awaitTermination(5, TimeUnit.SECONDS));
        }
    }

    @Test public void adapterSeamCopiesBothNotificationOverloadsBeforeFifoDelivery() {
        FakeBleHandlerQueue handler = new FakeBleHandlerQueue();
        FifoExecutor fifo = new FifoExecutor();
        StockQixGattTransport.AdapterSeam seam = seam(handler, fifo);
        RecordingDriverListener listener = new RecordingDriverListener();
        StockQixGattTransport.AdapterSeam.ListenerSupplier supplier = supplier(listener);

        byte[] api33Source = new byte[] {1, 2, 3};
        byte[] api33Value = seam.copyApi33Notification(api33Source);
        api33Source[0] = 9;
        seam.deliverNotification(supplier, 7, fd03(), api33Value);
        api33Value[1] = 9;

        final byte[] legacySource = new byte[] {4, 5, 6};
        byte[] legacyValue = seam.copyLegacyNotification(
                new StockQixGattTransport.AdapterSeam.LegacyValueSource() {
                    @Override public byte[] value() {
                        return legacySource;
                    }
                });
        legacySource[0] = 9;
        seam.deliverNotification(supplier, 7, fd03(), legacyValue);
        legacyValue[1] = 9;

        assertTrue(listener.notifications.isEmpty());
        fifo.drain();
        assertEquals(2, listener.notifications.size());
        assertArrayEquals(new byte[] {1, 2, 3}, listener.notifications.get(0));
        assertArrayEquals(new byte[] {4, 5, 6}, listener.notifications.get(1));
    }

    private static void assertStartFailure(StockQixGattTransport.AdapterSeam seam,
            FifoExecutor fifo, StockQixGattTransport.AdapterSeam.TaggedKind kind,
            final Outcome outcome) {
        RecordingDriverListener listener = new RecordingDriverListener();
        StockQixGattTransport.AdapterSeam.CompletionGate gate =
                new StockQixGattTransport.AdapterSeam.CompletionGate();
        StockQixGattTransport.AdapterSeam.CallbackTag tag = tag(kind);
        assertFalse(seam.attemptPlatformStartOrDeliver(
                new StockQixGattTransport.AdapterSeam.PlatformStart() {
                    @Override public boolean start() {
                        return result(outcome);
                    }
                }, gate, supplier(listener), tag));
        assertTrue(listener.tagged.isEmpty());
        fifo.drain();
        assertOnlyFailure(listener, tag);
        assertFalse(seam.deliverTaggedResult(gate, supplier(listener), tag,
                StockGattDriver.STATUS_SUCCESS));
        fifo.drain();
        assertOnlyFailure(listener, tag);
    }

    private static void assertSubscriptionFailure(StockQixGattTransport.AdapterSeam seam,
            FifoExecutor fifo, int sdkInt, FakeSubscriptionPort port, List<String> expectedCalls) {
        RecordingDriverListener listener = new RecordingDriverListener();
        StockQixGattTransport.AdapterSeam.CompletionGate gate =
                new StockQixGattTransport.AdapterSeam.CompletionGate();
        StockQixGattTransport.AdapterSeam.CallbackTag tag = tag(
                StockQixGattTransport.AdapterSeam.TaggedKind.SUBSCRIBE);
        assertNull(seam.startSubscriptionOrDeliver(sdkInt, port, new byte[] {2, 0}, gate,
                supplier(listener), tag));
        assertEquals(expectedCalls, port.calls);
        assertTrue(listener.tagged.isEmpty());
        fifo.drain();
        assertOnlyFailure(listener, tag);
        assertFalse(seam.deliverTaggedResult(gate, supplier(listener), tag,
                StockGattDriver.STATUS_SUCCESS));
        fifo.drain();
        assertOnlyFailure(listener, tag);
    }

    private static void assertWriteFailure(StockQixGattTransport.AdapterSeam seam,
            FifoExecutor fifo, int sdkInt, FakeWritePort port, List<String> expectedCalls) {
        RecordingDriverListener listener = new RecordingDriverListener();
        StockQixGattTransport.AdapterSeam.CompletionGate gate =
                new StockQixGattTransport.AdapterSeam.CompletionGate();
        StockQixGattTransport.AdapterSeam.CallbackTag tag = tag(
                StockQixGattTransport.AdapterSeam.TaggedKind.WRITE);
        assertFalse(seam.startWriteOrDeliver(sdkInt, port, new byte[] {9, 8},
                StockGattDriver.WRITE_TYPE_DEFAULT, gate, supplier(listener), tag));
        assertEquals(expectedCalls, port.calls);
        assertTrue(listener.tagged.isEmpty());
        fifo.drain();
        assertOnlyFailure(listener, tag);
        assertFalse(seam.deliverTaggedResult(gate, supplier(listener), tag,
                StockGattDriver.STATUS_SUCCESS));
        fifo.drain();
        assertOnlyFailure(listener, tag);
    }

    private static void assertOnlyFailure(RecordingDriverListener listener,
            StockQixGattTransport.AdapterSeam.CallbackTag tag) {
        assertEquals(1, listener.tagged.size());
        TaggedEvent event = listener.tagged.get(0);
        assertEquals(tag.kind(), event.kind);
        assertEquals(tag.generation(), event.generation);
        assertEquals(tag.token(), event.token);
        assertEquals(-1, event.status);
    }

    private static StockQixGattTransport.AdapterSeam.CallbackTag tag(
            StockQixGattTransport.AdapterSeam.TaggedKind kind) {
        switch (kind) {
            case SCAN:
                return StockQixGattTransport.AdapterSeam.CallbackTag.scan(11, 21);
            case CONNECT:
                return StockQixGattTransport.AdapterSeam.CallbackTag.connect(12, 22);
            case DISCOVER:
                return StockQixGattTransport.AdapterSeam.CallbackTag.discover(13, 23);
            case SUBSCRIBE:
                return StockQixGattTransport.AdapterSeam.CallbackTag.subscription(14, 24,
                        fd01(), StockQixUuids.CCCD);
            case MTU:
                return StockQixGattTransport.AdapterSeam.CallbackTag.mtu(15, 25, 512);
            case WRITE:
                return StockQixGattTransport.AdapterSeam.CallbackTag.write(16, 26, fd02());
            default:
                throw new AssertionError(kind);
        }
    }

    private static StockQixGattTransport.AdapterSeam.ListenerSupplier supplier(
            final RecordingDriverListener listener) {
        return new StockQixGattTransport.AdapterSeam.ListenerSupplier() {
            @Override public StockGattDriver.Listener current() {
                return listener;
            }
        };
    }

    private static Runnable threadedCommand(final StockQixGattTransport.AdapterSeam seam,
            final String name, final List<String> handlerOrder, final List<String> callbackOrder,
            final List<String> handlerThreads, final List<String> callbackThreads,
            final CountDownLatch callbacks) {
        return new Runnable() {
            @Override public void run() {
                handlerOrder.add(name);
                handlerThreads.add(Thread.currentThread().getName());
                seam.postToCallback(new Runnable() {
                    @Override public void run() {
                        callbackOrder.add(name);
                        callbackThreads.add(Thread.currentThread().getName());
                        callbacks.countDown();
                    }
                });
            }
        };
    }

    private static boolean result(Outcome outcome) {
        switch (outcome) {
            case SUCCESS:
                return true;
            case FALSE:
                return false;
            case SECURITY:
                throw new SecurityException("denied");
            case RUNTIME:
                throw new IllegalStateException("platform failed");
            default:
                throw new AssertionError(outcome);
        }
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

    private static StockGattDriver.Characteristic fd01() {
        return new StockGattDriver.Characteristic(StockQixUuids.FD01, StockGattDriver.NOTIFY,
                Arrays.asList(StockQixUuids.CCCD));
    }

    private static StockGattDriver.Characteristic fd02() {
        return new StockGattDriver.Characteristic(StockQixUuids.FD02, 0x0C,
                Collections.<UUID>emptyList());
    }

    private static StockGattDriver.Characteristic fd03() {
        return new StockGattDriver.Characteristic(StockQixUuids.FD03, 0x1A,
                Arrays.asList(StockQixUuids.CCCD));
    }

    private enum Outcome {
        SUCCESS, FALSE, SECURITY, RUNTIME
    }

    private static final class ThreadRecordingHandler
            implements StockQixGattTransport.AdapterSeam.HandlerPoster {
        private final ArrayDeque<Runnable> commands = new ArrayDeque<Runnable>();

        @Override public synchronized boolean post(Runnable command) {
            commands.addLast(command);
            return true;
        }

        void drain() {
            while (true) {
                final Runnable command;
                synchronized (this) {
                    if (commands.isEmpty()) {
                        return;
                    }
                    command = commands.removeFirst();
                }
                command.run();
            }
        }
    }

    private static final class FakeSubscriptionPort
            implements StockQixGattTransport.AdapterSeam.SubscriptionPort {
        final Object descriptor = new Object();
        final List<String> calls = new ArrayList<String>();
        boolean returnNullDescriptor;
        Outcome localEnableOutcome = Outcome.SUCCESS;
        Outcome legacySetValueOutcome = Outcome.SUCCESS;
        Outcome legacyWriteOutcome = Outcome.SUCCESS;
        Outcome modernWriteOutcome = Outcome.SUCCESS;
        byte[] legacyValue;

        @Override public boolean setCharacteristicNotification() {
            calls.add("enable");
            return result(localEnableOutcome);
        }

        @Override public Object findDescriptor() {
            calls.add("descriptor");
            return returnNullDescriptor ? null : descriptor;
        }

        @Override public boolean setLegacyValue(Object target, byte[] value) {
            calls.add("setValue");
            legacyValue = Arrays.copyOf(value, value.length);
            return result(legacySetValueOutcome);
        }

        @Override public boolean writeLegacyDescriptor(Object target) {
            calls.add("writeLegacy");
            return result(legacyWriteOutcome);
        }

        @Override public boolean writeModernDescriptor(Object target, byte[] value) {
            calls.add("writeModern");
            return result(modernWriteOutcome);
        }
    }

    private static final class FakeWritePort
            implements StockQixGattTransport.AdapterSeam.WritePort {
        final List<String> calls = new ArrayList<String>();
        Outcome writeTypeOutcome = Outcome.SUCCESS;
        Outcome legacySetValueOutcome = Outcome.SUCCESS;
        Outcome legacyWriteOutcome = Outcome.SUCCESS;
        Outcome modernWriteOutcome = Outcome.SUCCESS;

        @Override public boolean setWriteType(int writeType) {
            calls.add("setType");
            return result(writeTypeOutcome);
        }

        @Override public boolean setLegacyValue(byte[] value) {
            calls.add("setValue");
            return result(legacySetValueOutcome);
        }

        @Override public boolean writeLegacyCharacteristic() {
            calls.add("writeLegacy");
            return result(legacyWriteOutcome);
        }

        @Override public boolean writeModernCharacteristic(byte[] value, int writeType) {
            calls.add("writeModern");
            return result(modernWriteOutcome);
        }
    }

    private static final class RecordingDriverListener implements StockGattDriver.Listener {
        final List<StockGattDriver.Characteristic> writes =
                new ArrayList<StockGattDriver.Characteristic>();
        final List<byte[]> notifications = new ArrayList<byte[]>();
        final List<TaggedEvent> tagged = new ArrayList<TaggedEvent>();

        @Override public void onScanResult(long generation, long token, StockGattDriver.Peer peer) {
        }

        @Override public void onScanFailed(long generation, long token, int status) {
            tagged.add(new TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind.SCAN,
                    generation, token, status));
        }

        @Override public void onConnectionResult(long generation, long token, int status) {
            tagged.add(new TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind.CONNECT,
                    generation, token, status));
        }

        @Override public void onDisconnected(long generation, int status) {
        }

        @Override public void onServicesResult(long generation, long token,
                List<StockGattDriver.Service> services, int status) {
            tagged.add(new TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind.DISCOVER,
                    generation, token, status));
        }

        @Override public void onSubscriptionResult(long generation, long token,
                StockGattDriver.Characteristic characteristic, UUID descriptorUuid, int status) {
            tagged.add(new TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind.SUBSCRIBE,
                    generation, token, status));
        }

        @Override public void onMtuResult(long generation, long token, int mtu, int status) {
            tagged.add(new TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind.MTU,
                    generation, token, status));
        }

        @Override public void onCharacteristicWrite(long generation, long token,
                StockGattDriver.Characteristic characteristic, int status) {
            writes.add(characteristic);
            tagged.add(new TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind.WRITE,
                    generation, token, status));
        }

        @Override public void onNotification(long generation,
                StockGattDriver.Characteristic characteristic, byte[] value) {
            notifications.add(Arrays.copyOf(value, value.length));
        }
    }

    private static final class TaggedEvent {
        final StockQixGattTransport.AdapterSeam.TaggedKind kind;
        final long generation;
        final long token;
        final int status;

        TaggedEvent(StockQixGattTransport.AdapterSeam.TaggedKind kind, long generation,
                long token, int status) {
            this.kind = kind;
            this.generation = generation;
            this.token = token;
            this.status = status;
        }
    }

    private static String transitionSource(String name) throws Exception {
        return new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/transition/" + name)),
                StandardCharsets.UTF_8);
    }
}
