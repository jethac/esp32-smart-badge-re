package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import android.bluetooth.BluetoothDevice;
import android.content.Context;
import android.os.Handler;
import java.lang.ref.Reference;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.TreeSet;
import org.junit.Test;

public final class NormalGattClientBoundaryTest {
    @Test
    public void coreSignaturesExposeNoAndroidOrMaintenanceTypes() {
        Set<Class<?>> types = new HashSet<Class<?>>();
        types.add(NormalGattClient.Core.class);
        types.addAll(Arrays.asList(NormalGattClient.Core.class.getDeclaredClasses()));
        for (Class<?> type : types) {
            for (Constructor<?> constructor : type.getDeclaredConstructors()) {
                for (Class<?> parameter : constructor.getParameterTypes()) {
                    assertPure(parameter);
                }
            }
            for (Field field : type.getDeclaredFields()) {
                assertPure(field.getType());
            }
            for (Method method : type.getDeclaredMethods()) {
                assertPure(method.getReturnType());
                for (Class<?> parameter : method.getParameterTypes()) {
                    assertPure(parameter);
                }
            }
            for (Class<?> implemented : type.getInterfaces()) {
                assertPure(implemented);
            }
        }
    }

    @Test
    public void publicFacadeSurfaceIsExact() {
        assertTrue(Modifier.isFinal(NormalGattClient.class.getModifiers()));
        Constructor<?>[] constructors = NormalGattClient.class.getDeclaredConstructors();
        assertEquals(1, constructors.length);
        assertEquals(Arrays.asList(
                        Context.class, Handler.class, NormalGattClient.Listener.class),
                Arrays.asList(constructors[0].getParameterTypes()));
        Set<String> actual = new TreeSet<String>();
        for (Method method : NormalGattClient.class.getDeclaredMethods()) {
            if (Modifier.isPublic(method.getModifiers())) {
                actual.add(signature(method));
            }
        }
        assertEquals(new TreeSet<String>(Arrays.asList(
                "close():void",
                "connect(android.bluetooth.BluetoothDevice):void",
                "disconnect():void",
                "isReady():boolean",
                "writeState(net.jethachan.factory_badges.model.BadgeState):boolean")), actual);
    }

    @Test
    public void everyPublicFacadeMethodStartsWithBleThreadGuard() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/"
                        + "NormalGattClient.java")), StandardCharsets.UTF_8);

        for (String signature : Arrays.asList(
                "public void connect(BluetoothDevice device)",
                "public boolean writeState(BadgeState state)",
                "public void disconnect()",
                "public boolean isReady()",
                "public void close()")) {
            String body = methodBody(source, signature);
            assertTrue(signature, body.matches(
                    "(?s)^\\s*requireBleThread\\s*\\(\\s*\\)\\s*;.*"));
        }
    }

    @Test
    public void api33And34BondReceiverFlagsAllowPrivilegedBluetoothSender() {
        assertEquals(0, NormalGattClient.receiverFlagsForApi(31));
        assertEquals(0, NormalGattClient.receiverFlagsForApi(32));
        for (int sdk : new int[] {33, 34}) {
            int flags = NormalGattClient.receiverFlagsForApi(sdk);
            assertEquals(Context.RECEIVER_EXPORTED, flags);
            assertFalse(flags == Context.RECEIVER_NOT_EXPORTED);
        }
    }

    @Test
    public void weakDriverHistoryUsesIdentityAndPurgesClearedEntries() throws Exception {
        NormalGattClient.WeakIdentityHistory<EqualValue> history =
                new NormalGattClient.WeakIdentityHistory<EqualValue>();
        EqualValue first = new EqualValue();
        EqualValue equalButDistinct = new EqualValue();
        assertTrue(first.equals(equalButDistinct));

        history.add(first);
        assertTrue(history.contains(first));
        assertFalse(history.contains(equalButDistinct));

        Field entriesField = NormalGattClient.WeakIdentityHistory.class
                .getDeclaredField("entries");
        entriesField.setAccessible(true);
        Object stored = entriesField.get(history);
        assertTrue(stored instanceof Set);
        Set<?> entries = (Set<?>) stored;
        assertEquals(1, entries.size());
        Object entry = entries.iterator().next();
        assertTrue(entry instanceof Reference);
        Reference<?> reference = (Reference<?>) entry;
        reference.clear();
        assertTrue(reference.enqueue());

        assertFalse(history.contains(first));
        assertTrue(entries.isEmpty());
        history.add(equalButDistinct);
        assertTrue(history.contains(equalButDistinct));
    }

    @Test
    public void driverSlotClearsAttachmentAndRejectsReuseByIdentity() {
        NormalGattClient.DriverSlot<EqualValue> slot =
                new NormalGattClient.DriverSlot<EqualValue>();
        EqualValue first = new EqualValue();
        EqualValue equalButDistinct = new EqualValue();

        slot.attach(first);
        assertTrue(slot.matches(first));
        assertFalse(slot.matches(equalButDistinct));
        assertSame(first, slot.currentOrNull());
        assertSame(first, slot.require());
        assertSame(first, slot.closeAndTake());
        assertNull(slot.currentOrNull());
        assertFalse(slot.matches(first));
        assertNull(slot.closeAndTake());
        assertThrows(IllegalStateException.class, () -> slot.require());
        assertThrows(IllegalStateException.class,
                () -> slot.attach(equalButDistinct));
    }

    @Test
    public void addressAndCallbackSeamsRejectWrongIdentityOrGeneration() {
        assertTrue(NormalGattClient.addressesMatch("AA:BB", "AA:BB"));
        assertFalse(NormalGattClient.addressesMatch("AA:BB", "aa:bb"));
        assertFalse(NormalGattClient.addressesMatch(null, "AA:BB"));
        assertFalse(NormalGattClient.addressesMatch("AA:BB", null));

        assertTrue(NormalGattClient.callbackEligible(true, 7L, 7L));
        assertFalse(NormalGattClient.callbackEligible(false, 7L, 7L));
        assertFalse(NormalGattClient.callbackEligible(true, 7L, 8L));
        assertFalse(NormalGattClient.callbackEligible(true, 0L, 0L));
    }

    @Test
    public void adapterSourcePinsConnectionAndReadCallbackShape() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/"
                        + "NormalGattClient.java")), StandardCharsets.UTF_8);
        String compact = source.replaceAll("\\s+", " ");

        assertTrue(compact.contains(
                "device.connectGatt( applicationContext, false, callback, "
                        + "BluetoothDevice.TRANSPORT_LE, "
                        + "BluetoothDevice.PHY_LE_1M_MASK, bleHandler)"));
        assertEquals(2, occurrences(source, "public void onCharacteristicRead("));
        assertTrue(source.contains("characteristic.getValue()"));
        assertTrue(source.contains("byte[] copied = copyOrNull(value)"));
        assertTrue(compact.contains("routeOnBleThread(callbackGatt, callback)"));
        assertTrue(source.contains("Context.RECEIVER_EXPORTED"));
        assertFalse(source.contains("Context.RECEIVER_NOT_EXPORTED"));
    }

    @Test
    public void receiverApi33ConstantIsIsolatedInPrivateAnnotatedThunk() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/"
                        + "NormalGattClient.java")), StandardCharsets.UTF_8);
        String dispatcher = methodBody(
                source, "static int receiverFlagsForApi(int sdkInt)");
        String thunkSignature = "private static int receiverExportedFlagApi33()";
        String thunk = methodBody(source, thunkSignature);

        assertFalse(dispatcher.contains("Context.RECEIVER_EXPORTED"));
        assertTrue(dispatcher.contains(
                "sdkInt >= 33 ? receiverExportedFlagApi33() : 0"));
        assertEquals(1, occurrences(source, "Context.RECEIVER_EXPORTED"));
        assertTrue(source.contains(
                "@android.annotation.TargetApi(33)\n    " + thunkSignature));
        assertTrue(thunk.matches(
                "(?s)^\\s*return\\s+Context\\.RECEIVER_EXPORTED\\s*;\\s*$"));
        assertFalse(source.contains("import android.annotation.TargetApi;"));
        assertFalse(source.contains("@SuppressLint"));
        assertFalse(source.contains("@RequiresApi"));
    }

    @Test
    public void modernWriteApiIsIsolatedInPrivateAnnotatedThunk() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/"
                        + "NormalGattClient.java")), StandardCharsets.UTF_8);
        String thunkSignature = "private int writeCharacteristicApi33(";
        String thunk = methodBody(source, thunkSignature).replaceAll("\\s+", " ");
        String modern = methodBody(source, "public int writeModern(")
                .replaceAll("\\s+", " ");

        assertTrue(source.contains(
                "@android.annotation.TargetApi(33)\n        " + thunkSignature));
        assertEquals(2, occurrences(source, "writeCharacteristicApi33("));
        assertFalse(modern.contains("attachedGatt.writeCharacteristic("));
        assertTrue(modern.contains(
                "return writeCharacteristicApi33( attachedGatt, characteristic, "
                        + "copiedValue, writeType);"));
        assertTrue(thunk.contains(
                "try { return attachedGatt.writeCharacteristic( characteristic, "
                        + "copiedValue, writeType); }"));
        assertTrue(thunk.contains(
                "catch (SecurityException denied) { throw new PermissionFailure(); }"));
    }

    @Test
    public void driverCloseDetachesBeforeSwallowingOnlySecurityException()
            throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/"
                        + "NormalGattClient.java")), StandardCharsets.UTF_8);
        int driverStart = source.indexOf(
                "private final class AndroidGattDriver implements Core.GattDriver");
        assertTrue(driverStart >= 0);
        String close = methodBody(
                source.substring(driverStart), "public void close()");

        int detach = close.indexOf("slot.closeAndTake()");
        int platformClose = close.indexOf("attachedGatt.close()");
        assertTrue(detach >= 0);
        assertTrue(platformClose > detach);
        assertEquals(1, occurrences(close, "slot.closeAndTake()"));
        assertEquals(1, occurrences(close, "attachedGatt.close()"));
        assertEquals(1, occurrences(close, "catch (SecurityException ignored)"));
        assertEquals(1, occurrences(close, "catch ("));
        assertFalse(close.contains("slot.attach("));
    }

    @Test
    public void propertyAndApiHelpersChooseAcknowledgedWritePaths() {
        assertFalse(NormalGattClient.accessFromProperties(0x04).acknowledgedWritable());
        assertTrue(NormalGattClient.accessFromProperties(0x08).acknowledgedWritable());

        for (int sdk : new int[] {31, 32}) {
            RecordingWritePort legacy = new RecordingWritePort();
            byte[] input = new byte[] {1, 2};
            assertTrue(NormalGattClient.writeAcknowledgedForApi(sdk, input, legacy));
            input[0] = 99;
            assertEquals(Arrays.asList("type:2", "value", "legacy"), legacy.events);
            assertArrayEquals(new byte[] {1, 2}, legacy.received);
        }
        RecordingWritePort rejectedLegacy = new RecordingWritePort();
        rejectedLegacy.valueAccepted = false;
        assertFalse(NormalGattClient.writeAcknowledgedForApi(
                31, new byte[] {1}, rejectedLegacy));
        assertEquals(Arrays.asList("type:2", "value"), rejectedLegacy.events);

        for (int sdk : new int[] {33, 34}) {
            RecordingWritePort modern = new RecordingWritePort();
            byte[] input = new byte[] {3, 4};
            assertTrue(NormalGattClient.writeAcknowledgedForApi(sdk, input, modern));
            input[0] = 99;
            assertEquals(Arrays.asList("modern:2"), modern.events);
            assertArrayEquals(new byte[] {3, 4}, modern.received);
            RecordingWritePort rejectedModern = new RecordingWritePort();
            rejectedModern.modernStatus = 7;
            assertFalse(NormalGattClient.writeAcknowledgedForApi(
                    sdk, new byte[] {1}, rejectedModern));
        }
    }

    private static String methodBody(String source, String signature) {
        int signatureStart = source.indexOf(signature);
        assertTrue(signature, signatureStart >= 0);
        int openingBrace = source.indexOf('{', signatureStart);
        assertTrue(signature, openingBrace >= 0);
        int depth = 0;
        for (int index = openingBrace; index < source.length(); index++) {
            char current = source.charAt(index);
            if (current == '{') {
                depth++;
            } else if (current == '}') {
                depth--;
                if (depth == 0) {
                    return source.substring(openingBrace + 1, index);
                }
            }
        }
        throw new AssertionError("unterminated method: " + signature);
    }

    private static int occurrences(String text, String needle) {
        int count = 0;
        int index = 0;
        while ((index = text.indexOf(needle, index)) >= 0) {
            count++;
            index += needle.length();
        }
        return count;
    }

    private static void assertPure(Class<?> type) {
        String name = type.isArray() ? type.getComponentType().getName() : type.getName();
        assertFalse(name, name.startsWith("android."));
        assertFalse(name, name.startsWith("androidx."));
        assertFalse(name, name.startsWith("com.jieli."));
        assertFalse(name, name.startsWith("net.jethachan.factory_badges.maintenance"));
    }

    private static String signature(Method method) {
        StringBuilder text = new StringBuilder(method.getName()).append('(');
        for (int i = 0; i < method.getParameterCount(); i++) {
            if (i > 0) {
                text.append(',');
            }
            text.append(method.getParameterTypes()[i].getTypeName());
        }
        return text.append("):").append(method.getReturnType().getTypeName()).toString();
    }

    private static final class EqualValue {
        @Override public boolean equals(Object other) {
            return other instanceof EqualValue;
        }

        @Override public int hashCode() {
            return 7;
        }
    }

    private static final class RecordingWritePort implements NormalGattClient.WritePort {
        final java.util.List<String> events = new java.util.ArrayList<String>();
        byte[] received;
        boolean valueAccepted = true;
        int modernStatus;

        @Override public void setLegacyWriteType(int type) {
            events.add("type:" + type);
        }

        @Override public boolean setLegacyValue(byte[] value) {
            events.add("value");
            received = value;
            return valueAccepted;
        }

        @Override public boolean writeLegacy() {
            events.add("legacy");
            return true;
        }

        @Override public int writeModern(byte[] value, int type) {
            events.add("modern:" + type);
            received = value;
            return modernStatus;
        }
    }
}
