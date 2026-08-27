package net.jethachan.factory_badges.sync;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import android.app.Service;
import android.bluetooth.BluetoothDevice;
import android.content.Context;
import android.content.Intent;
import android.os.IBinder;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Pattern;
import javax.xml.parsers.DocumentBuilderFactory;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.ConnectionSnapshot;
import org.junit.Test;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

public final class BadgeSyncServiceBoundaryTest {
    private static final String SOURCE_PATH =
            "app/src/main/java/net/jethachan/factory_badges/sync/"
                    + "BadgeSyncService.java";

    // Mutation caught: the Android adapter exposes the wrong class/lifecycle surface.
    @Test
    public void serviceAndBinderPublicSurfacesAreExact() {
        assertTrue(Service.class.isAssignableFrom(BadgeSyncService.class));
        assertTrue(Modifier.isFinal(BadgeSyncService.class.getModifiers()));
        assertEquals(Service.START_NOT_STICKY,
                BadgeSyncServiceRuntime.START_NOT_STICKY_RESULT);

        Set<String> serviceMethods = publicDeclaredMethods(BadgeSyncService.class);
        assertEquals(new TreeSet<String>(Arrays.asList(
                "disableIntent(android.content.Context):android.content.Intent",
                "enableIntent(android.content.Context):android.content.Intent",
                "onBind(android.content.Intent):android.os.IBinder",
                "onCreate():void",
                "onDestroy():void",
                "onStartCommand(android.content.Intent,int,int):int")),
                serviceMethods);

        assertTrue(Modifier.isPublic(
                BadgeSyncService.SnapshotListener.class.getModifiers()));
        assertEquals(new TreeSet<String>(Arrays.asList(
                        "onSnapshot(net.jethachan.factory_badges.model."
                                + "ConnectionSnapshot):void")),
                publicDeclaredMethods(BadgeSyncService.SnapshotListener.class));

        assertTrue(Modifier.isPublic(
                BadgeSyncService.LocalBinder.class.getModifiers()));
        Set<String> binderMethods =
                publicDeclaredMethods(BadgeSyncService.LocalBinder.class);
        assertEquals(new TreeSet<String>(Arrays.asList(
                "addSnapshotListener(net.jethachan.factory_badges.sync."
                        + "BadgeSyncService$SnapshotListener):void",
                "removeSnapshotListener(net.jethachan.factory_badges.sync."
                        + "BadgeSyncService$SnapshotListener):void",
                "selectDevice(android.bluetooth.BluetoothDevice):void",
                "setCurrentState(net.jethachan.factory_badges.model.BadgeState):void",
                "setSyncEnabled(boolean):void",
                "snapshot():net.jethachan.factory_badges.model.ConnectionSnapshot",
                "syncNow():void")), binderMethods);
    }

    // Mutation caught: pure controller/runtime policy gains an Android dependency.
    @Test
    public void controllerAndRuntimeStayFinalNonpublicAndPure() {
        assertTrue(Modifier.isFinal(BadgeSyncController.class.getModifiers()));
        assertFalse(Modifier.isPublic(BadgeSyncController.class.getModifiers()));
        assertTrue(Modifier.isFinal(
                BadgeSyncServiceRuntime.class.getModifiers()));
        assertFalse(Modifier.isPublic(
                BadgeSyncServiceRuntime.class.getModifiers()));
        assertPureClosure(BadgeSyncController.class);
        assertPureClosure(BadgeSyncServiceRuntime.class);

        assertEquals(1,
                BadgeSyncServiceRuntime.class.getDeclaredConstructors().length);
        Constructor<?> constructor =
                BadgeSyncServiceRuntime.class.getDeclaredConstructors()[0];
        assertEquals(Arrays.asList(
                        ConnectionSnapshot.class,
                        BadgeSyncServiceRuntime.BlePoster.class,
                        BadgeSyncServiceRuntime.MainPoster.class,
                        BadgeSyncServiceRuntime.ForegroundPort.class),
                Arrays.asList(constructor.getParameterTypes()));
        assertEquals(new TreeSet<String>(Arrays.asList(
                        "addSnapshotListener(java.lang.Object,"
                                + "net.jethachan.factory_badges.sync."
                                + "BadgeSyncServiceRuntime$SnapshotDelivery):void",
                        "destroy(net.jethachan.factory_badges.sync."
                                + "BadgeSyncServiceRuntime$DestroyPort):void",
                        "latestSnapshot():net.jethachan.factory_badges.model."
                                + "ConnectionSnapshot",
                        "onControllerForegroundStart():void",
                        "onControllerForegroundStop():void",
                        "onSnapshot(net.jethachan.factory_badges.model."
                                + "ConnectionSnapshot):void",
                        "onStartCommand(java.lang.String,java.lang.Runnable,"
                                + "java.lang.Runnable):int",
                        "postBinderMutation(java.lang.Runnable):void",
                        "removeSnapshotListener(java.lang.Object):void")),
                nonPrivateDeclaredMethods(BadgeSyncServiceRuntime.class));

        Set<String> runtimeFields = new TreeSet<String>();
        for (Field field : BadgeSyncServiceRuntime.class.getDeclaredFields()) {
            runtimeFields.add(
                    Modifier.toString(field.getModifiers())
                            + ":" + field.getType().getTypeName()
                            + ":" + field.getName());
        }
        assertEquals(new TreeSet<String>(Arrays.asList(
                        "private static final:java.lang.String:ACTION_DISABLE",
                        "private static final:java.lang.String:ACTION_ENABLE",
                        "static final:int:START_NOT_STICKY_RESULT",
                        "private final:java.lang.Object:lock",
                        "private final:java.util.List:listeners",
                        "private final:net.jethachan.factory_badges.sync."
                                + "BadgeSyncServiceRuntime$BlePoster:blePoster",
                        "private final:net.jethachan.factory_badges.sync."
                                + "BadgeSyncServiceRuntime$ForegroundPort:"
                                + "foregroundPort",
                        "private final:net.jethachan.factory_badges.sync."
                                + "BadgeSyncServiceRuntime$MainPoster:mainPoster",
                        "private volatile:net.jethachan.factory_badges.model."
                                + "ConnectionSnapshot:latestSnapshot",
                        "private:long:foregroundGeneration",
                        "private:long:lifecycleToken",
                        "private:long:listenerToken",
                        "private:boolean:destroyed",
                        "private:boolean:exhaustionStopPending",
                        "private:boolean:foregroundDesired",
                        "private:boolean:foregroundPromoted",
                        "private:boolean:generationExhausted",
                        "private:boolean:workerUnavailable")),
                runtimeFields);
    }

    // Mutation caught: service policy storage or a listener registry escapes runtime.
    @Test
    public void serviceOwnsExactlyOneRuntimeAndNoPolicyCollection() {
        int runtimeOwners = 0;
        for (Field field : BadgeSyncService.class.getDeclaredFields()) {
            if (field.getType() == BadgeSyncServiceRuntime.class) {
                runtimeOwners++;
            }
            assertFalse(field.getName(),
                    Collection.class.isAssignableFrom(field.getType()));
            assertFalse(field.getName(),
                    Map.class.isAssignableFrom(field.getType()));
            assertFalse(field.getName(),
                    field.getType() == BadgeSyncService.SnapshotListener.class);
            String name = field.getName().toLowerCase();
            assertFalse(name, name.contains("listenerregistry"));
            assertFalse(name, name.contains("retrycounter"));
            assertFalse(name, name.contains("lifecycletoken"));
            assertFalse(name, name.contains("foregroundgeneration"));
        }
        assertEquals(1, runtimeOwners);
    }

    // Mutation caught: production import allowlists drift into Android/persistence/UI.
    @Test
    public void controllerAndServiceImportsAreExact() throws Exception {
        String controller = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/sync/"
                        + "BadgeSyncController.java")), StandardCharsets.UTF_8);
        assertEquals(new TreeSet<String>(Arrays.asList(
                        "net.jethachan.factory_badges.diagnostic.UserVisibleError",
                        "net.jethachan.factory_badges.model.BadgeState",
                        "net.jethachan.factory_badges.model.BuildInfo",
                        "net.jethachan.factory_badges.model.ConnectionSnapshot",
                        "net.jethachan.factory_badges.protocol.BuildInfoCodec")),
                imports(controller));

        String service = source();
        Set<String> androidImports = new TreeSet<String>();
        Set<String> projectImports = new TreeSet<String>();
        for (String imported : imports(service)) {
            if (imported.startsWith("android.")) {
                androidImports.add(imported);
            } else if (imported.startsWith(
                    "net.jethachan.factory_badges.")) {
                projectImports.add(imported);
            }
        }
        assertEquals(new TreeSet<String>(Arrays.asList(
                        "android.app.Notification",
                        "android.app.NotificationChannel",
                        "android.app.NotificationManager",
                        "android.app.Service",
                        "android.bluetooth.BluetoothDevice",
                        "android.content.Context",
                        "android.content.Intent",
                        "android.content.pm.ServiceInfo",
                        "android.os.Binder",
                        "android.os.Handler",
                        "android.os.HandlerThread",
                        "android.os.IBinder",
                        "android.os.Looper")),
                androidImports);
        assertEquals(new TreeSet<String>(Arrays.asList(
                        "net.jethachan.factory_badges.R",
                        "net.jethachan.factory_badges.ble.normal.NormalGattClient",
                        "net.jethachan.factory_badges.diagnostic.UserVisibleError",
                        "net.jethachan.factory_badges.model.BadgeState",
                        "net.jethachan.factory_badges.model.BuildInfo",
                        "net.jethachan.factory_badges.model.ConnectionSnapshot")),
                projectImports);
        for (String forbidden : Arrays.asList(
                "androidx.", "com.jieli.", ".maintenance.",
                "retrofit", "webview", "flutter", ".network.",
                ".graphics.", ".storage.", ".firmware.")) {
            assertFalse(forbidden,
                    service.toLowerCase().contains(forbidden.toLowerCase()));
        }
    }

    // Mutation caught: Android imports are referenced inside the pure runtime body.
    @Test
    public void runtimeSourceBodyIsMechanicallyAndroidFree() throws Exception {
        String service = source();
        String runtime = typeBody(service,
                "final class BadgeSyncServiceRuntime");
        assertFalse(runtime.contains("android."));
        assertFalse(runtime.contains("androidx."));
        for (String imported : imports(service)) {
            if (!imported.startsWith("android.")) {
                continue;
            }
            String simpleName =
                    imported.substring(imported.lastIndexOf('.') + 1);
            assertFalse(simpleName,
                    Pattern.compile("\\b" + Pattern.quote(simpleName)
                                    + "\\b")
                            .matcher(runtime).find());
        }
    }

    // Mutation caught: the source extractor is fooled by braces in comments/strings.
    @Test
    public void sourceExtractorBalancesOnlyCodeBraces() {
        String fixture = "final class Sample /* { ignored */ {\n"
                + "String text = \"} ignored\"; // } ignored\n"
                + "void nested() { char brace = '{'; }\n"
                + "} int outside;";
        String body = typeBody(fixture, "final class Sample");
        assertTrue(body.contains("void nested()"));
        assertFalse(body.contains("outside"));
    }

    // Mutation caught: an Intent helper becomes implicit, shared, or cross-wired.
    @Test
    public void intentHelpersAreFreshExplicitAndUseExactActions() throws Exception {
        String source = source();
        assertTrue(source.contains(
                "private static final String ACTION_ENABLE =\n"
                        + "            \"net.jethachan.factory_badges.action."
                        + "ENABLE_BADGE_SYNC\";"));
        assertTrue(source.contains(
                "private static final String ACTION_DISABLE =\n"
                        + "            \"net.jethachan.factory_badges.action."
                        + "DISABLE_BADGE_SYNC\";"));

        String enable = methodBody(
                source, "public static Intent enableIntent(Context context)");
        String disable = methodBody(
                source, "public static Intent disableIntent(Context context)");
        assertEquals(1, occurrences(enable,
                "new Intent(context, BadgeSyncService.class)"));
        assertEquals(1, occurrences(disable,
                "new Intent(context, BadgeSyncService.class)"));
        assertTrue(enable.contains(".setAction(ACTION_ENABLE)"));
        assertFalse(enable.contains("ACTION_DISABLE"));
        assertTrue(disable.contains(".setAction(ACTION_DISABLE)"));
        assertFalse(disable.contains("ACTION_ENABLE"));
        assertTrue(enable.contains("context == null"));
        assertTrue(disable.contains("context == null"));
    }

    // Mutation caught: start actions bypass runtime or swap enable/disable polarity.
    @Test
    public void startCommandDelegatesExactPolarityAndReturnsRuntimeResult()
            throws Exception {
        String body = methodBody(source(),
                "public int onStartCommand(Intent intent, int flags, int startId)");
        int runtimeCall = body.indexOf("return runtime.onStartCommand(");
        int enable = body.indexOf("controller.setSyncEnabled(true)");
        int disable = body.indexOf("controller.setSyncEnabled(false)");
        assertTrue(runtimeCall >= 0);
        assertTrue(enable > runtimeCall);
        assertTrue(disable > enable);
        assertEquals(1, occurrences(body, "controller.setSyncEnabled(true)"));
        assertEquals(1, occurrences(body, "controller.setSyncEnabled(false)"));
        assertTrue(body.contains("intent == null ? null : intent.getAction()"));
        assertFalse(body.contains("START_STICKY"));
    }

    // Mutation caught: a binder mutator routes directly or to a different controller call.
    @Test
    public void binderMutatorsUseGuardedSameNamedControllerCalls()
            throws Exception {
        String binder = typeBody(source(),
                "public final class LocalBinder extends Binder");
        assertBinderRoute(binder,
                "public void selectDevice(BluetoothDevice device)",
                "controller.selectDevice(capturedSelection)");
        assertBinderRoute(binder,
                "public void setCurrentState(BadgeState state)",
                "controller.setCurrentState(capturedState)");
        assertBinderRoute(binder,
                "public void setSyncEnabled(boolean enabled)",
                "controller.setSyncEnabled(capturedEnabled)");
        assertBinderRoute(binder,
                "public void syncNow()",
                "controller.syncNow()");
        String snapshot = methodBody(
                binder, "public ConnectionSnapshot snapshot()");
        assertTrue(snapshot.contains("return runtime.latestSnapshot()"));
    }

    // Mutation caught: foreground notification resources drift or disappear.
    @Test
    public void adapterReferencesEveryExactForegroundResource() throws Exception {
        String source = source();
        for (String resource : Arrays.asList(
                "R.drawable.ic_stat_badge_sync",
                "R.string.badge_sync_channel_name",
                "R.string.badge_sync_notification_title",
                "R.string.badge_sync_notification_waiting",
                "R.string.badge_sync_notification_connecting",
                "R.string.badge_sync_notification_ready",
                "R.string.badge_sync_notification_retry",
                "R.string.badge_sync_notification_error")) {
            assertTrue(resource, source.contains(resource));
        }
        assertTrue(source.contains("private static final int NOTIFICATION_ID = 3719;"));
        assertTrue(source.contains(
                "private static final String CHANNEL_ID = \"badge_sync\";"));
    }

    // Mutation caught: foreground code remaps snapshots or omits Android stop order.
    @Test
    public void foregroundPortUsesOnlyRuntimeKindAndExactLifecycleCalls()
            throws Exception {
        String service = source();
        String foreground = typeBody(service,
                "new BadgeSyncServiceRuntime.ForegroundPort()");
        String promote = methodBody(foreground, "public void promote(");
        String update = methodBody(foreground, "public void update(");
        String stop = methodBody(foreground, "public void stop()");

        assertTrue(promote.contains("createNotificationChannel()"));
        assertTrue(promote.contains("buildNotification(kind)"));
        assertTrue(promote.contains("startForeground("));
        assertTrue(promote.contains("NOTIFICATION_ID"));
        assertTrue(promote.contains(
                "FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE"));
        assertTrue(update.contains(
                "notificationManager().notify("));
        assertTrue(update.contains("NOTIFICATION_ID"));
        assertTrue(update.contains("buildNotification(kind)"));
        assertFalse(foreground.contains("latestSnapshot"));
        assertFalse(foreground.contains("ConnectionSnapshot"));
        assertFalse(foreground.contains(".Phase"));

        int remove = stop.indexOf(
                "stopForeground(STOP_FOREGROUND_REMOVE)");
        int stopSelf = stop.indexOf("stopSelf()");
        assertTrue(remove >= 0);
        assertTrue(stopSelf > remove);

        String notification = methodBody(service,
                "private Notification buildNotification(");
        for (String kind : Arrays.asList(
                "WAITING", "CONNECTING", "READY", "RETRY", "ERROR")) {
            assertEquals(kind, 1,
                    occurrences(notification, "case " + kind + ":"));
        }
        assertTrue(notification.contains(
                ".setSmallIcon(R.drawable.ic_stat_badge_sync)"));
        assertTrue(notification.contains(".setOngoing(true)"));
        assertFalse(notification.contains("latestSnapshot"));
        assertFalse(notification.contains("ConnectionSnapshot"));
        assertFalse(notification.contains("PendingIntent"));
    }

    // Mutation caught: Bluetooth selection is read after queueing or loses permission shape.
    @Test
    public void binderCapturesSelectionAndUsesListenerIdentityThroughRuntime()
            throws Exception {
        String service = source();
        String binder = typeBody(service,
                "public final class LocalBinder extends Binder");
        String select = methodBody(
                binder, "public void selectDevice(BluetoothDevice device)");
        int name = select.indexOf("capturedDevice.getName()");
        int address = select.indexOf("capturedDevice.getAddress()");
        int bond = select.indexOf("capturedDevice.getBondState()");
        int selection = select.indexOf(
                "final BadgeSyncController.Selection capturedSelection");
        int post = select.indexOf("runtime.postBinderMutation(");
        assertTrue(name >= 0);
        assertTrue(address > name);
        assertTrue(bond > address);
        assertTrue(selection > bond);
        assertTrue(post > selection);
        assertTrue(select.contains("BluetoothDevice.BOND_BONDED"));
        assertTrue(select.contains("catch (SecurityException denied)"));
        assertTrue(select.contains("throw bluetoothPermissionFailure()"));
        assertTrue(select.contains("new BoundClient("));

        String add = methodBody(binder,
                "public void addSnapshotListener(");
        assertTrue(add.contains("runtime.addSnapshotListener("));
        assertTrue(add.contains("listener,"));
        assertEquals(1, occurrences(add, "listener.onSnapshot(snapshot)"));
        assertFalse(add.contains("Handler"));
        String remove = methodBody(binder,
                "public void removeSnapshotListener(");
        assertTrue(remove.contains(
                "runtime.removeSnapshotListener(listener)"));
        assertFalse(remove.contains("Handler"));
    }

    // Mutation caught: a GATT callback substitutes epoch/source or adds reconnect policy.
    @Test
    public void boundClientIsOneShotMechanicalGattAdapter() throws Exception {
        String service = source();
        String bound = typeBody(service,
                "private final class BoundClient");
        assertTrue(service.replaceAll("\\s+", " ").contains(
                "private final class BoundClient implements "
                        + "BadgeSyncController.Client, "
                        + "NormalGattClient.Listener"));
        assertEquals(1, occurrences(service, "new NormalGattClient("));
        String constructor = methodBody(bound, "BoundClient(");
        assertTrue(constructor.contains(
                "BadgeSyncService.this.getApplicationContext()"));
        assertTrue(constructor.contains("bleHandler"));
        assertTrue(constructor.contains("this"));

        assertTrue(methodBody(bound, "public void connect()")
                .contains("normalGattClient.connect(boundDevice)"));
        assertTrue(methodBody(bound, "public boolean writeState(")
                .contains("return normalGattClient.writeState(state)"));
        assertEquals(1, occurrences(
                methodBody(bound, "public void disconnect()"),
                "normalGattClient.disconnect()"));
        assertEquals(1, occurrences(
                methodBody(bound, "public void close()"),
                "normalGattClient.close()"));

        assertCallback(bound, "public void onConnected(",
                "clientEvents.onConnected(");
        assertCallback(bound, "public void onStateWriteAcknowledged(",
                "clientEvents.onStateWriteAcknowledged(");
        assertCallback(bound, "public void onDisconnected(",
                "clientEvents.onDisconnected(");
        assertCallback(bound, "public void onError(",
                "clientEvents.onError(");
        for (String forbidden : Arrays.asList(
                "ReconnectPolicy", "postDelayed", "ConnectionSnapshot",
                "BuildInfoCodec", "GattStatus", "coalesc")) {
            assertFalse(forbidden, bound.contains(forbidden));
        }
    }

    // Mutation caught: service queues close/quit itself or reverses destroy ownership.
    @Test
    public void destroyUsesRuntimeOwnedSingleCleanupPath() throws Exception {
        String body = methodBody(source(), "public void onDestroy()");
        int runtimeDestroy = body.indexOf("runtime.destroy(");
        int close = body.indexOf("capturedController.close()");
        int quit = body.indexOf("capturedBleThread.quitSafely()");
        int parent = body.indexOf("super.onDestroy()");
        assertTrue(runtimeDestroy >= 0);
        assertTrue(close > runtimeDestroy);
        assertTrue(quit > close);
        assertTrue(parent > quit);
        assertEquals(1, occurrences(body, "runtime.destroy("));
        assertEquals(1, occurrences(body, "capturedController.close()"));
        assertEquals(1, occurrences(body, "capturedBleThread.quitSafely()"));
        assertFalse(body.contains("bleHandler.post"));
    }

    // Mutation caught: public adapter surface leaks raw transport or mutable policy types.
    @Test
    public void publicApiLeaksNoRawTransportCollectionOrMaintenanceType() {
        assertEquals(android.os.Binder.class,
                BadgeSyncService.LocalBinder.class.getSuperclass());
        Set<Class<?>> exposed = new HashSet<Class<?>>();
        exposed.add(BadgeSyncService.class);
        exposed.add(BadgeSyncService.LocalBinder.class);
        exposed.add(BadgeSyncService.SnapshotListener.class);
        for (Class<?> type : exposed) {
            for (Method method : type.getDeclaredMethods()) {
                if (!Modifier.isPublic(method.getModifiers())) {
                    continue;
                }
                assertSafePublicType(method.getReturnType());
                for (Class<?> parameter : method.getParameterTypes()) {
                    assertSafePublicType(parameter);
                }
            }
        }
    }

    // Mutation caught: handler/thread wiring bypasses the runtime adapters.
    @Test
    public void createSynchronouslyWiresExactBleAndMainAdapters()
            throws Exception {
        String service = source();
        assertTrue(service.contains(
                "private static final String BLE_THREAD_NAME = \"E87-BLE\";"));
        String create = methodBody(service, "public void onCreate()");
        int thread = create.indexOf("new HandlerThread(BLE_THREAD_NAME)");
        int start = create.indexOf("bleThread.start()");
        int ble = create.indexOf("new Handler(bleThread.getLooper())");
        int main = create.indexOf("new Handler(Looper.getMainLooper())");
        int runtime = create.indexOf("new BadgeSyncServiceRuntime(");
        int controller = create.indexOf("new BadgeSyncController(");
        assertTrue(thread >= 0);
        assertTrue(start > thread);
        assertTrue(ble > start);
        assertTrue(main > ble);
        assertTrue(runtime > main);
        assertTrue(controller > runtime);
        assertTrue(create.contains("bleHandler::post"));
        assertTrue(create.contains(
                "Looper.myLooper() == Looper.getMainLooper()"));
        assertTrue(create.contains("return mainHandler.post(task)"));
        assertTrue(create.contains("runtime.onControllerForegroundStart()"));
        assertTrue(create.contains("runtime.onControllerForegroundStop()"));
        assertTrue(create.contains("runtime.onSnapshot(snapshot)"));
    }

    // Mutation caught: a rejected delayed post returns null or an active handle.
    @Test
    public void bleSchedulerAlwaysReturnsAnInertHandleWhenRejected()
            throws Exception {
        String scheduler = typeBody(
                source(), "private final class BleScheduler");
        String schedule = methodBody(
                scheduler, "public Handle schedule(");
        assertEquals(1, occurrences(
                schedule, "bleHandler.postDelayed(callback, delayMs)"));
        assertTrue(schedule.contains("final boolean accepted ="));
        assertFalse(schedule.contains("return null"));
        assertTrue(schedule.contains("return new Handle()"));
        assertTrue(schedule.contains(
                "private boolean cancelled = !accepted;"));

        String cancel = methodBody(schedule, "public void cancel()");
        assertTrue(cancel.contains("if (cancelled)"));
        assertEquals(1, occurrences(
                cancel, "bleHandler.removeCallbacks(callback)"));
    }

    // Mutation caught: notification resource names or bytes drift from the contract.
    @Test
    public void foregroundResourcesAreExact() throws Exception {
        assertNotificationStrings(
                "app/src/main/res/values/strings.xml");

        String drawable = readNormalized(
                "app/src/main/res/drawable/ic_stat_badge_sync.xml");
        assertEquals(
                "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
                + "<vector xmlns:android=\"http://schemas.android.com/apk/res/android\"\n"
                + "    android:width=\"24dp\"\n"
                + "    android:height=\"24dp\"\n"
                + "    android:viewportWidth=\"24\"\n"
                + "    android:viewportHeight=\"24\">\n"
                + "    <path\n"
                + "        android:fillColor=\"#FFFFFFFF\"\n"
                + "        android:pathData=\"M12,4V1L8,5l4,4V6c3.31,0 6,2.69 6,6 "
                + "0,1.01 -0.25,1.97 -0.7,2.8l1.46,1.46C19.54,15.03 "
                + "20,13.57 20,12c0,-4.42 -3.58,-8 -8,-8zM6.7,9.2L5.24,7.74"
                + "C4.46,8.97 4,10.43 4,12c0,4.42 3.58,8 8,8v3l4,-4 -4,-4v3"
                + "c-3.31,0 -6,-2.69 -6,-6 0,-1.01 0.25,-1.97 0.7,-2.8z\" />\n"
                + "</vector>\n",
                drawable);
    }

    private static void assertNotificationStrings(String path) throws Exception {
        String[] names = {
                "badge_sync_channel_name",
                "badge_sync_notification_title",
                "badge_sync_notification_waiting",
                "badge_sync_notification_connecting",
                "badge_sync_notification_ready",
                "badge_sync_notification_retry",
                "badge_sync_notification_error"
        };
        String[] values = {
                "Badge sync",
                "Badge sync active",
                "Waiting for a badge",
                "Connecting to badge",
                "Badge connected",
                "Reconnecting to badge",
                "Badge sync needs attention"
        };
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        NodeList strings = factory.newDocumentBuilder()
                .parse(Paths.get(path).toFile())
                .getElementsByTagName("string");

        for (String name : names) {
            int count = 0;
            for (int index = 0; index < strings.getLength(); index++) {
                Element element = (Element) strings.item(index);
                if (name.equals(element.getAttribute("name"))) count++;
            }
            assertEquals(name, 1, count);
        }

        Map<String, String> actual = new LinkedHashMap<String, String>();
        for (int index = 0; index < strings.getLength(); index++) {
            Element element = (Element) strings.item(index);
            actual.put(element.getAttribute("name"), element.getTextContent());
        }
        for (int index = 0; index < names.length; index++) {
            assertEquals(names[index], values[index], actual.get(names[index]));
        }
    }

    private static void assertCallback(
            String bound, String signature, String call) {
        String body = methodBody(bound, signature);
        assertEquals(signature, 1, occurrences(body, call));
        assertTrue(signature, body.contains("clientEpoch, this"));
    }

    private static void assertSafePublicType(Class<?> rawType) {
        Class<?> type = rawType;
        while (type.isArray()) {
            type = type.getComponentType();
        }
        String name = type.getName().toLowerCase();
        for (String forbidden : Arrays.asList(
                "bluetoothgatt", "java.util.", "image", "network",
                "firmware", "maintenance", "com.jieli")) {
            assertFalse(type.getName(), name.contains(forbidden));
        }
    }

    private static String readNormalized(String path) throws Exception {
        return new String(Files.readAllBytes(Paths.get(path)),
                StandardCharsets.UTF_8).replace("\r\n", "\n");
    }

    private static void assertBinderRoute(
            String binder, String signature, String controllerCall) {
        String body = methodBody(binder, signature);
        int post = body.indexOf("runtime.postBinderMutation(");
        int call = body.indexOf(controllerCall);
        assertTrue(signature, post >= 0);
        assertTrue(signature, call > post);
        assertEquals(signature, 1, occurrences(body, controllerCall));
        for (String method : Arrays.asList(
                "selectDevice(", "setCurrentState(", "setSyncEnabled(", "syncNow(")) {
            if (!controllerCall.contains(method)) {
                assertFalse(signature, body.contains("controller." + method));
            }
        }
    }

    private static void assertPureClosure(Class<?> root) {
        Set<Class<?>> types = new HashSet<Class<?>>();
        collectNestedTypes(root, types);
        for (Class<?> type : types) {
            assertPure(type);
            for (Class<?> implemented : type.getInterfaces()) {
                assertPure(implemented);
            }
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
        }
    }

    private static void collectNestedTypes(
            Class<?> type, Set<Class<?>> collected) {
        if (!collected.add(type)) {
            return;
        }
        for (Class<?> nested : type.getDeclaredClasses()) {
            collectNestedTypes(nested, collected);
        }
    }

    private static void assertPure(Class<?> rawType) {
        Class<?> type = rawType;
        while (type.isArray()) {
            type = type.getComponentType();
        }
        String name = type.getName();
        assertFalse(name, name.startsWith("android."));
        assertFalse(name, name.startsWith("androidx."));
        assertFalse(name, name.startsWith("com.jieli."));
        assertFalse(name,
                name.startsWith("net.jethachan.factory_badges.maintenance"));
    }

    private static Set<String> nonPrivateDeclaredMethods(Class<?> type) {
        Set<String> result = new TreeSet<String>();
        for (Method method : type.getDeclaredMethods()) {
            if (!Modifier.isPrivate(method.getModifiers())
                    && !method.isSynthetic()) {
                result.add(signature(method));
            }
        }
        return result;
    }

    private static Set<String> imports(String source) {
        Set<String> result = new TreeSet<String>();
        for (String line : source.split("\\r?\\n")) {
            String trimmed = line.trim();
            if (trimmed.startsWith("import ")
                    && trimmed.endsWith(";")
                    && !trimmed.startsWith("import static ")) {
                result.add(trimmed.substring(
                        "import ".length(), trimmed.length() - 1));
            }
        }
        return result;
    }

    private static Set<String> publicDeclaredMethods(Class<?> type) {
        Set<String> result = new TreeSet<String>();
        for (Method method : type.getDeclaredMethods()) {
            if (Modifier.isPublic(method.getModifiers()) && !method.isSynthetic()) {
                result.add(signature(method));
            }
        }
        return result;
    }

    private static String signature(Method method) {
        StringBuilder text = new StringBuilder(method.getName()).append('(');
        Class<?>[] parameters = method.getParameterTypes();
        for (int index = 0; index < parameters.length; index++) {
            if (index > 0) {
                text.append(',');
            }
            text.append(parameters[index].getTypeName());
        }
        return text.append("):")
                .append(method.getReturnType().getTypeName()).toString();
    }

    private static String source() throws Exception {
        return new String(Files.readAllBytes(Paths.get(SOURCE_PATH)),
                StandardCharsets.UTF_8);
    }

    private static String methodBody(String source, String signature) {
        return bodyAfter(source, signature);
    }

    private static String typeBody(String source, String declaration) {
        return bodyAfter(source, declaration);
    }

    private static String bodyAfter(String source, String anchor) {
        int start = source.indexOf(anchor);
        assertTrue(anchor, start >= 0);
        int opening = nextCodeOpeningBrace(source, start);
        assertTrue(anchor, opening >= 0);
        int depth = 0;
        int state = 0;
        boolean escaped = false;
        for (int index = opening; index < source.length(); index++) {
            char current = source.charAt(index);
            char next = index + 1 < source.length()
                    ? source.charAt(index + 1) : '\0';
            if (state == 1) {
                if (current == '\n') {
                    state = 0;
                }
                continue;
            }
            if (state == 2) {
                if (current == '*' && next == '/') {
                    state = 0;
                    index++;
                }
                continue;
            }
            if (state == 3 || state == 4) {
                if (escaped) {
                    escaped = false;
                } else if (current == '\\') {
                    escaped = true;
                } else if ((state == 3 && current == '\"')
                        || (state == 4 && current == '\'')) {
                    state = 0;
                }
                continue;
            }
            if (current == '/' && next == '/') {
                state = 1;
                index++;
            } else if (current == '/' && next == '*') {
                state = 2;
                index++;
            } else if (current == '\"') {
                state = 3;
            } else if (current == '\'') {
                state = 4;
            } else if (current == '{') {
                depth++;
            } else if (current == '}') {
                depth--;
                if (depth == 0) {
                    return source.substring(opening + 1, index);
                }
            }
        }
        throw new AssertionError("unterminated body: " + anchor);
    }

    private static int nextCodeOpeningBrace(String source, int start) {
        int state = 0;
        boolean escaped = false;
        for (int index = start; index < source.length(); index++) {
            char current = source.charAt(index);
            char next = index + 1 < source.length()
                    ? source.charAt(index + 1) : '\0';
            if (state == 1) {
                if (current == '\n') {
                    state = 0;
                }
                continue;
            }
            if (state == 2) {
                if (current == '*' && next == '/') {
                    state = 0;
                    index++;
                }
                continue;
            }
            if (state == 3 || state == 4) {
                if (escaped) {
                    escaped = false;
                } else if (current == '\\') {
                    escaped = true;
                } else if ((state == 3 && current == '\"')
                        || (state == 4 && current == '\'')) {
                    state = 0;
                }
                continue;
            }
            if (current == '/' && next == '/') {
                state = 1;
                index++;
            } else if (current == '/' && next == '*') {
                state = 2;
                index++;
            } else if (current == '\"') {
                state = 3;
            } else if (current == '\'') {
                state = 4;
            } else if (current == '{') {
                return index;
            }
        }
        return -1;
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
}
