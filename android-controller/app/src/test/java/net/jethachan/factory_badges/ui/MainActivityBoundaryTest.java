package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.Test;

public final class MainActivityBoundaryTest {
    private static final Path ACTIVITY = Paths.get(
            "app/src/main/java/net/jethachan/factory_badges/ui/MainActivity.java");
    private static final Path SCANNER = Paths.get(
            "app/src/main/java/net/jethachan/factory_badges/ble/normal/NormalBadgeScanner.java");

    @Test public void mainActivityExistsWithNarrowPlatformSurface() throws Exception {
        Source source = Source.load(ACTIVITY);
        assertTrue(source.code.contains(
                "public final class MainActivity extends Activity"));
        assertFalse(source.code.contains("implements MainUiPresenter.Host"));
        assertFalse(source.code.contains("implements NormalBadgeScanner.Listener"));
        assertFalse(source.code.contains("implements SeekBar.OnSeekBarChangeListener"));
        assertFalse(source.code.contains("implements ServiceConnection"));

        Set<String> allowed = new LinkedHashSet<>(Arrays.asList(
                "android.Manifest", "android.annotation.SuppressLint",
                "android.app.Activity", "android.app.AlertDialog",
                "android.bluetooth.BluetoothAdapter", "android.bluetooth.BluetoothDevice",
                "android.bluetooth.BluetoothManager", "android.content.ComponentName",
                "android.content.Context", "android.content.Intent",
                "android.content.ServiceConnection", "android.content.pm.PackageManager",
                "android.os.Build", "android.os.Bundle", "android.os.Handler",
                "android.os.IBinder", "android.os.Looper", "android.view.View",
                "android.widget.ArrayAdapter", "android.widget.Button",
                "android.widget.SeekBar", "android.widget.TextView",
                "java.util.ArrayList", "java.util.LinkedHashMap",
                "java.util.List", "java.util.Map",
                "net.jethachan.factory_badges.R",
                "net.jethachan.factory_badges.ble.normal.NormalBadgeScanner",
                "net.jethachan.factory_badges.diagnostic.UserVisibleError",
                "net.jethachan.factory_badges.model.BadgeState",
                "net.jethachan.factory_badges.model.BuildInfo",
                "net.jethachan.factory_badges.model.ConnectionSnapshot",
                "net.jethachan.factory_badges.sync.BadgeSyncService"));
        assertEquals(allowed, source.imports());
        assertFalse(source.code.matches("(?s).*(androidx|compose|material|ViewModel|"
                + "WorkManager|StatePacketCodec|Maintenance|Canvas|Bitmap|WebView).*"));
    }

    @Test public void onCreateBindsExactViewsAndUsesStrictRestoreDecoder() throws Exception {
        Source source = Source.load(ACTIVITY);
        String body = source.method("onCreate");
        assertOrder(body, "super.onCreate(savedInstanceState)", "setContentView(R.layout.activity_main)",
                "findViewById(R.id.day_seek)", "setKeyProgressIncrement(1)",
                "MainUiPresenter.decodeRestoredState(", "new MainUiPresenter(",
                "new Handler(Looper.getMainLooper())", "new NormalBadgeScanner(",
                "refreshEnvironment()");
        assertEquals(1, count(body, "daySeek.setKeyProgressIncrement(1)"));
        assertEquals(1, count(body, "weekSeek.setKeyProgressIncrement(1)"));
        assertEquals(2, count(body, "savedInstanceState.containsKey("));
        assertEquals(2, count(body, "savedInstanceState.get("));
        assertFalse(body.contains("getInt("));
        assertFalse(body.contains("(Integer)"));
        assertFalse(body.contains("requestPermissions("));
        assertFalse(body.contains(".start()"));
        assertFalse(body.contains("startService("));
        assertFalse(body.contains("startForegroundService("));
        assertEquals(1, count(source.code, "@SuppressWarnings(\"deprecation\")"));
        assertTrue(source.code.contains("@SuppressWarnings(\"deprecation\")\n    @Override protected void onCreate"));
        for (String id : REQUIRED_IDS) {
            assertEquals(id, 1, count(body, "R.id." + id));
        }
    }

    @Test public void lifecycleMethodsHaveExactlyOneSuperCall() throws Exception {
        Source source = Source.load(ACTIVITY);
        for (String name : Arrays.asList("onCreate", "onStart", "onStop", "onDestroy",
                "onSaveInstanceState", "onRestoreInstanceState",
                "onRequestPermissionsResult")) {
            assertEquals(name, 1, count(source.method(name), "super." + name + "("));
        }
        assertTrue(source.method("onCreate").trim().startsWith(
                "super.onCreate(savedInstanceState);"));
        assertTrue(source.method("onStart").trim().startsWith("super.onStart();"));
        assertTrue(source.method("onRequestPermissionsResult").trim().startsWith(
                "super.onRequestPermissionsResult(requestCode, permissions, grantResults);"));
    }

    @Test public void bindingAndCleanupPreserveExactLifecycleOwnership() throws Exception {
        Source source = Source.load(ACTIVITY);
        String start = source.method("onStart");
        assertOrder(start, "super.onStart()", "refreshEnvironment()",
                "presenter.onServiceBinding()", "new Intent(this, BadgeSyncService.class)",
                "bindReleaseOwed = true", "bindService(");
        assertEquals(1, count(start, "bindService("));
        assertTrue(start.contains("Context.BIND_AUTO_CREATE"));
        assertTrue(start.contains("if (!accepted)"));
        assertTrue(start.contains("catch (SecurityException"));
        assertEquals(2, count(start, "presenter.onServiceBindFailed()"));
        assertFalse(start.contains("bindReleaseOwed = false"));
        assertFalse(start.contains("startService("));
        assertFalse(start.contains("startForegroundService("));

        String stop = source.method("onStop");
        assertOrder(stop, "scanner.stop()", "releaseCandidateSession(",
                "removeSnapshotListener(snapshotListener)",
                "listenerRegistered = false", "currentBinder = null",
                "presenter.onServiceUnbound()", "bindReleaseOwed = false",
                "unbindService(serviceConnection)", "super.onStop()");
        assertTrue("nested cleanup must be finally-safe", count(stop, "finally") >= 5);
        assertEquals(1, count(stop, "unbindService("));
        assertTrue(stop.contains("if (bindReleaseOwed) {"));
        assertEquals(1, count(stop, "bindReleaseOwed = false"));
        assertTrue(stop.contains("catch (IllegalArgumentException"));
        assertTrue(stop.contains("catch (SecurityException"));
        assertFalse(stop.contains("disableIntent"));

        String destroy = source.method("onDestroy");
        assertOrder(destroy, "scanner.close()", "presenter.close()", "super.onDestroy()");
        assertTrue(count(destroy, "finally") >= 2);
        assertFalse(destroy.contains("disableIntent"));
    }

    @Test public void serviceConnectionSnapshotsThenRegistersAndFailsClosed() throws Exception {
        Source source = Source.load(ACTIVITY);
        assertTrue(source.code.contains("new ServiceConnection()"));
        assertTrue(source.code.contains("new BadgeSyncService.SnapshotListener()"));
        String connected = source.method("onServiceConnected");
        assertOrder(connected, "instanceof BadgeSyncService.LocalBinder",
                "currentBinder = binder", "binder.snapshot()",
                "presenter.onServiceBound(snapshot)",
                "binder.addSnapshotListener(snapshotListener)",
                "listenerRegistered = true");
        assertTrue(connected.contains("catch (IllegalStateException"));
        assertTrue(connected.contains("cleanupFailedBinding("));
        assertFalse(connected.contains("setCurrentState("));
        assertFalse(connected.contains("syncNow("));

        String failed = source.method("cleanupFailedBinding");
        assertOrder(failed, "removeSnapshotListener(snapshotListener)",
                "listenerRegistered = false", "currentBinder = null",
                "presenter.onServiceBindFailed()");
        assertFalse(failed.contains("bindReleaseOwed"));
        for (String callback : Arrays.asList("onServiceDisconnected", "onBindingDied",
                "onNullBinding")) {
            assertEquals(callback, 1, count(source.method(callback), "cleanupFailedBinding("));
        }
    }

    @Test public void savedStateAndPermissionCallbacksAreNarrow() throws Exception {
        Source source = Source.load(ACTIVITY);
        String save = source.method("onSaveInstanceState");
        assertOrder(save, "super.onSaveInstanceState(outState)",
                "outState.putInt(STATE_DAY", "outState.putInt(STATE_WEEK");
        assertEquals(2, count(save, "outState.putInt("));
        assertFalse(save.matches("(?s).*(credit|address|selected|syncEnabled|error|battery).*"));

        String restore = source.method("onRestoreInstanceState");
        assertOrder(restore, "super.onRestoreInstanceState(savedInstanceState)",
                "render(presenter.viewState())");
        assertFalse(restore.matches("(?s).*(presenter\\.on|scanner\\.|bindService|startService|"
                + "startForegroundService|requestPermissions).*"));

        String permissions = source.method("onRequestPermissionsResult");
        assertTrue(permissions.trim().startsWith(
                "super.onRequestPermissionsResult(requestCode, permissions, grantResults);"));
        assertEquals(1, count(permissions, "refreshEnvironment()"));
        assertTrue(permissions.contains("REQUEST_NEARBY"));
        assertTrue(permissions.contains("REQUEST_NOTIFICATIONS"));
        assertFalse(permissions.matches("(?s).*(grantResults\\[|scanner\\.start|selectDevice|"
                + "startService|startForegroundService|syncNow).*"));
    }

    @Test public void hostAdapterRoutesOnlyReviewedCommands() throws Exception {
        Source source = Source.load(ACTIVITY);
        assertTrue(source.code.contains("new MainUiPresenter.Host()"));
        assertFalse(source.code.contains(".setSyncEnabled("));

        String publish = source.method("publishState");
        assertEquals(1, count(publish, "binder.setCurrentState(state)"));
        assertTrue(publish.contains("CommandResult.ACCEPTED"));
        assertTrue(publish.contains("CommandResult.SERVICE_UNAVAILABLE"));
        assertFalse(publish.matches("(?s).*(syncNow|startService|startForegroundService|selectDevice).*"));

        String permissions = source.method("requestBluetoothPermissions");
        assertTrue(permissions.contains("Manifest.permission.BLUETOOTH_SCAN"));
        assertTrue(permissions.contains("Manifest.permission.BLUETOOTH_CONNECT"));
        assertEquals(1, count(permissions, "requestPermissions("));
        assertFalse(permissions.contains("POST_NOTIFICATIONS"));

        String scan = source.method("beginBadgeScan");
        assertOrder(scan, "openCandidateDialog()", "scanner.start()");
        assertEquals(1, count(scan, "scanner.start()"));

        String foreground = source.method("startForegroundSync");
        assertOrder(foreground, "notificationPromptAttempted = true",
                "requestPermissions(", "startForegroundService(",
                "BadgeSyncService.enableIntent(MainActivity.this)");
        assertEquals(1, count(foreground, "startForegroundService("));
        assertTrue(foreground.contains("Manifest.permission.POST_NOTIFICATIONS"));
        assertFalse(foreground.substring(0,
                foreground.indexOf("startForegroundService(")).contains("return"));
        assertTrue(foreground.contains("CommandResult.BLUETOOTH_PERMISSION_REQUIRED"));
        assertTrue(foreground.contains("CommandResult.SYNC_START_FAILED"));

        String sync = source.method("requestSyncNow");
        assertEquals(1, count(sync, "binder.syncNow()"));
        assertFalse(sync.matches("(?s).*(startService|startForegroundService|setCurrentState).*"));
        String stop = source.method("requestStopSync");
        assertEquals(1, count(stop, "startService("));
        assertEquals(1, count(stop,
                "BadgeSyncService.disableIntent(MainActivity.this)"));
        assertFalse(stop.matches("(?s).*(syncNow|setSyncEnabled|startForegroundService).*"));
    }

    @Test public void environmentRefreshHasNoCommandSideEffects() throws Exception {
        Source source = Source.load(ACTIVITY);
        String refresh = source.method("refreshEnvironment");
        assertTrue(refresh.contains("Manifest.permission.BLUETOOTH_SCAN"));
        assertTrue(refresh.contains("Manifest.permission.BLUETOOTH_CONNECT"));
        assertTrue(refresh.contains("Manifest.permission.POST_NOTIFICATIONS"));
        assertOrder(refresh, "connectGranted", "adapter.isEnabled()", "scanner.isScanning()",
                "presenter.onEnvironment(new MainUiPresenter.Environment(");
        assertEquals(1, count(refresh, "adapter.isEnabled()"));
        assertTrue(refresh.contains("if (connectGranted) {"));
        assertTrue(refresh.contains("catch (SecurityException"));
        assertTrue(refresh.contains("connectGranted = false"));
        assertFalse(refresh.matches("(?s).*(requestPermissions|scanner\\.start|bindService|"
                + "selectDevice|startService|startForegroundService|syncNow).*"));

        for (String owner : Arrays.asList("onCreate", "onStart",
                "onRequestPermissionsResult", "onChooseBadgeClicked",
                "onSyncClicked", "onCandidateSelected")) {
            assertTrue(owner, source.method(owner).contains("refreshEnvironment()"));
        }
    }

    @Test public void seekbarAndButtonAdaptersArePrivateAnonymousForwarders() throws Exception {
        Source source = Source.load(ACTIVITY);
        assertEquals(2, count(source.code, "new SeekBar.OnSeekBarChangeListener()"));
        String progress = source.method("onProgressChanged");
        assertTrue(progress.contains("fromUser"));
        assertTrue(progress.contains("!rendering"));
        assertTrue(source.code.contains("presenter.onDayChanged(progress)"));
        assertTrue(source.code.contains("presenter.onWeekChanged(progress)"));
        assertFalse(source.code.contains("announceForAccessibility"));
        assertEquals(1, count(source.method("onChooseBadgeClicked"),
                "presenter.onChooseBadgePressed()"));
        assertEquals(1, count(source.method("onSyncClicked"), "presenter.onSyncPressed()"));
        assertEquals(1, count(source.method("onStopSyncClicked"),
                "presenter.onStopPressed()"));
    }

    @Test public void androidImportsAndSuppressionsStayInsideReviewedBoundary() throws Exception {
        Source scanner = Source.load(SCANNER);
        Set<String> scannerAllowed = new LinkedHashSet<>(Arrays.asList(
                "android.annotation.SuppressLint", "android.bluetooth.BluetoothAdapter",
                "android.bluetooth.BluetoothDevice", "android.bluetooth.BluetoothManager",
                "android.bluetooth.le.BluetoothLeScanner",
                "android.bluetooth.le.ScanCallback", "android.bluetooth.le.ScanFilter",
                "android.bluetooth.le.ScanRecord", "android.bluetooth.le.ScanResult",
                "android.bluetooth.le.ScanSettings", "android.content.Context",
                "android.os.Handler", "android.os.Looper", "android.os.ParcelUuid",
                "java.util.Arrays", "java.util.HashSet", "java.util.List",
                "java.util.Set"));
        assertTrue(scannerAllowed.containsAll(scanner.imports()));
        assertFalse(scanner.imports().contains("java.util.Optional"));
        assertEquals(4, count(scanner.code, "@SuppressLint(\"MissingPermission\")"));
        assertFalse(scanner.code.contains("@SuppressLint(\"all\")"));

        Source activity = Source.load(ACTIVITY);
        assertEquals(1, count(activity.code, "@SuppressLint(\"MissingPermission\")"));
        assertTrue(activity.method("refreshEnvironment").contains(
                "catch (SecurityException"));
        assertFalse(activity.code.contains("@SuppressLint(\"all\")"));
    }

    @Test public void candidateDialogOwnsIdentityScopedSessionAndMaskedRows() throws Exception {
        Source source = Source.load(ACTIVITY);
        String open = source.method("openCandidateDialog");
        assertOrder(open, "scanner.stop()", "releaseCandidateSession(",
                "new LinkedHashMap<>()", "R.string.scan_dialog_searching",
                "setTitle(R.string.scan_dialog_title)", "dialog.show()");
        assertTrue(open.contains("setCancelable(true)"));
        assertTrue(open.contains("setOnCancelListener"));
        assertTrue(open.contains("setOnDismissListener"));
        assertTrue(open.contains("candidateDialog == dialog"));
        assertTrue(open.contains("candidateDevices == devices"));
        assertOrder(open, "setOnDismissListener", "scanner.stop()", "devices.clear()");
        assertEquals("cancel and dismiss must each identity-gate scanner cleanup", 2,
                count(open, "boolean currentSession = candidateDialog == dialog"
                        + " && candidateDevices == devices"));

        String add = source.method("addCandidate");
        assertTrue(add.contains("NormalBadgeScanner.MAX_CANDIDATES"));
        assertOrder(add, "finalTwoOctets(address)", "devices.put(address, device)",
                "addresses.add(address)", "R.string.selected_badge_format");
        assertTrue(add.contains("R.string.paired"));
        assertTrue(add.contains("R.string.not_paired"));
        assertFalse(add.contains("device.getName"));
        assertFalse(add.contains("device.getAddress"));

        String release = source.method("releaseCandidateSession");
        assertOrder(release, "devices.clear()", "candidateDialog == dialog",
                "candidateDevices = null", "candidateDialog = null", "dialog.dismiss()");
        assertFalse(source.code.matches("(?s).*android\\.util\\.Log.*"));
    }

    @Test public void scannerCallbacksRefreshAfterTransitionsAndMapFailuresExactly()
            throws Exception {
        Source source = Source.load(ACTIVITY);
        assertEquals(1, count(source.method("onStarted"), "refreshEnvironment()"));
        String finished = source.method("onFinished");
        assertOrder(finished, "refreshEnvironment()", "if (foundAny",
                "removeSearchingRow()", "releaseCandidateSession(",
                "presenter.onScanEnded(false)");
        String candidateTimeout = finished.substring(finished.indexOf("if (foundAny"),
                finished.indexOf("return;", finished.indexOf("if (foundAny")));
        assertFalse(candidateTimeout.contains("clear()"));
        assertFalse(candidateTimeout.contains("releaseCandidateSession("));
        String failure = source.method("onFailure");
        assertOrder(failure, "refreshEnvironment()", "releaseCandidateSession(",
                "presenter.onScanFailed(problemFor(failure))");
        String mapping = source.method("problemFor");
        assertTrue(mapping.contains(
                "NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED"));
        assertTrue(mapping.contains("NormalBadgeScanner.Failure.BLUETOOTH_OFF"));
        assertTrue(mapping.contains("MainUiPresenter.ProblemKind.SCAN_FAILED"));
    }

    @Test public void selectionDisposesSessionBeforeExactOrderedBinderCommands()
            throws Exception {
        Source source = Source.load(ACTIVITY);
        String selection = source.method("onCandidateSelected");
        assertOrder(selection, "BluetoothDevice selectedDevice = devices.get(address)",
                "refreshEnvironment()", "BadgeSyncService.LocalBinder binder = currentBinder",
                "nearbyPermissionsGranted()", "scanner.stop()",
                "releaseCandidateSession(", "refreshEnvironment()",
                "binder.setCurrentState(presenter.currentState())",
                "binder.selectDevice(selectedDevice)", "presenter.onScanEnded(true)");
        assertTrue(count(selection, "refreshEnvironment()") >= 2);
        assertEquals(1, count(selection, "binder.setCurrentState("));
        assertEquals(1, count(selection, "binder.selectDevice("));
        assertEquals(1, count(selection, "if (!permissionsGranted)"));
        assertTrue(selection.contains("catch (SecurityException"));
        assertTrue(selection.contains("catch (IllegalStateException"));
        assertTrue(selection.contains("if (!nearbyPermissionsGranted())"));
        assertFalse(selection.contains(".getMessage("));
        assertFalse(selection.matches("(?s).*(syncNow|enableIntent|startService|"
                + "startForegroundService).*"));
    }

    @Test public void renderingUsesOnlyPresenterEnumsAndSafeReviewedText() throws Exception {
        Source source = Source.load(ACTIVITY);
        String render = source.outerMethod("render");
        assertEquals(1, count(render, "daySeek.setStateDescription("));
        assertEquals(1, count(render, "weekSeek.setStateDescription("));
        assertEquals(2, count(render, "R.string.percent_state_format"));
        assertTrue(render.contains("R.string.selected_badge_name_only"));
        assertTrue(render.contains("finalTwoOctets(address)"));
        assertTrue(render.contains("R.string.selected_badge_format,\n"
                + "                            suffix,"));
        assertFalse(render.contains("R.string.selected_badge_format,\n"
                + "                            address,"));
        assertTrue(render.contains("renderAcknowledgment(state)"));
        assertFalse(source.code.contains("creditValue.setText"));
        assertTrue(source.method("renderAcknowledgment").contains(
                "state.currentStateAcknowledged()"));
        assertFalse(render.matches("(?s).*(ConnectionSnapshot\\.Phase|UserVisibleError\\.Code|"
                + "buildId\\(|gattStatus\\(|selectedDeviceName\\().*"));

        String problem = source.method("renderProblemAndDetail");
        assertOrder(problem, "state.localProblem() != MainUiPresenter.ProblemKind.NONE",
                "localWarningValue.setText(problemResource(",
                "connectionDetailValue.setVisibility(View.GONE)", "renderConnectionDetail(state)");
        String detail = source.method("renderConnectionDetail");
        assertTrue(detail.contains("state.connectionError().message()"));
        assertTrue(detail.contains("R.string.retry_error_format"));
        assertTrue(detail.contains("R.string.ready_detail_with_battery"));
        assertFalse(detail.matches("(?s).*(buildId\\(|gattStatus\\(|getMessage\\().*"));

        String ceil = source.method("wholeSecondsCeiling");
        assertTrue(ceil.contains("milliseconds / 1000L"));
        assertTrue(ceil.contains("milliseconds % 1000L"));
        assertFalse(ceil.contains("milliseconds + 999"));
        for (String resource : Arrays.asList(
                "status_service_connecting", "status_service_unavailable", "status_sync_off",
                "status_no_device", "status_bonding", "status_connecting",
                "status_discovering", "status_validating_build", "status_ready",
                "status_retrying", "status_error")) {
            assertEquals(resource, 1, count(source.method("statusResource"),
                    "R.string." + resource));
        }
        for (String resource : Arrays.asList(
                "guidance_wait_for_service", "guidance_choose_badge",
                "guidance_hold_sync_pair", "guidance_wait_for_connection",
                "guidance_adjust_and_sync", "guidance_retrying",
                "guidance_stop_fix_retry")) {
            assertEquals(resource, 1, count(source.method("guidanceResource"),
                    "R.string." + resource));
        }
        for (String resource : Arrays.asList(
                "bluetooth_permission_problem", "bluetooth_off_problem",
                "no_badge_found_problem", "scan_failed_problem",
                "service_unavailable_problem", "sync_start_failed_problem")) {
            assertEquals(resource, 1, count(source.method("problemResource"),
                    "R.string." + resource));
        }
    }

    @Test public void noLifecycleOrSliderPathAutomaticallyScansOrStartsSync()
            throws Exception {
        Source source = Source.load(ACTIVITY);
        for (String owner : Arrays.asList("onCreate", "onStart",
                "onServiceConnected", "onProgressChanged")) {
            String body = source.method(owner);
            assertFalse(owner, body.matches("(?s).*(scanner\\.start|enableIntent|"
                    + "startForegroundService|syncNow\\().*"));
        }
        assertFalse(source.code.matches("(?s).*(MaintenanceActivity|E87 UPDATE|"
                + "com\\.jieli|StatePacketCodec|SharedPreferences|SQLite|FileOutputStream).*"));
    }

    @Test public void outerClassExposesOnlyRequiredLifecycleEntryPoints() throws Exception {
        Source source = Source.load(ACTIVITY);
        assertEquals(new LinkedHashSet<>(Arrays.asList("onRequestPermissionsResult")),
                source.outerMethods("public"));
        assertEquals(new LinkedHashSet<>(Arrays.asList("onCreate", "onStart", "onStop",
                "onDestroy", "onSaveInstanceState", "onRestoreInstanceState")),
                source.outerMethods("protected"));

        int modifiers = MainUiPresenter.class.getModifiers();
        assertTrue(Modifier.isFinal(modifiers));
        assertFalse(Modifier.isPublic(modifiers));
        Class<?> scanner = Class.forName(
                "net.jethachan.factory_badges.ble.normal.NormalBadgeScanner");
        assertTrue(Modifier.isFinal(scanner.getModifiers()));
        assertTrue(Modifier.isPublic(scanner.getModifiers()));
    }

    @Test public void pureSeamsRemainFrameworkFree() throws Exception {
        assertFrameworkFree(MainUiPresenter.class);
        assertFrameworkFree(Class.forName(
                "net.jethachan.factory_badges.ble.normal.NormalBadgeScanner$Core"));
    }

    private static final String[] REQUIRED_IDS = {
        "main_title", "selected_badge_label", "selected_badge_value",
        "choose_badge_button", "connection_label", "connection_status_value",
        "connection_detail_value", "sync_pair_guidance", "local_warning_value",
        "notification_warning_value", "day_label", "day_value", "day_seek",
        "week_label", "week_value", "week_seek", "credit_label", "credit_value",
        "last_sync_value", "sync_button", "stop_sync_button"
    };

    private static void assertFrameworkFree(Class<?> type) {
        assertFalse(type.getName().startsWith("android."));
        for (Field field : type.getDeclaredFields()) {
            assertFalse(field.toString(), field.getType().getName().startsWith("android."));
        }
        for (Method method : type.getDeclaredMethods()) {
            assertFalse(method.toString(),
                    method.getReturnType().getName().startsWith("android."));
            for (Class<?> parameter : method.getParameterTypes()) {
                assertFalse(method.toString(), parameter.getName().startsWith("android."));
            }
        }
    }

    private static void assertOrder(String text, String... fragments) {
        int position = -1;
        for (String fragment : fragments) {
            int next = text.indexOf(fragment, position + 1);
            assertTrue("missing/out of order: " + fragment, next > position);
            position = next;
        }
    }

    private static int count(String text, String fragment) {
        int result = 0;
        int offset = 0;
        while ((offset = text.indexOf(fragment, offset)) >= 0) {
            result++;
            offset += fragment.length();
        }
        return result;
    }

    private static final class Source {
        final String code;

        private Source(String code) {
            this.code = code;
        }

        static Source load(Path path) throws Exception {
            assertTrue("missing MainActivity source", Files.isRegularFile(path));
            String raw = new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
            return new Source(stripComments(raw));
        }

        Set<String> imports() {
            Set<String> result = new LinkedHashSet<>();
            Matcher matcher = Pattern.compile("(?m)^import\\s+([^;]+);\\s*$").matcher(code);
            while (matcher.find()) result.add(matcher.group(1));
            return result;
        }

        Set<String> outerMethods(String modifier) {
            Set<String> result = new LinkedHashSet<>();
            Matcher matcher = Pattern.compile(
                    "(?m)^\\s*(?:@[A-Za-z0-9_.]+(?:\\([^\\r\\n]*\\))?\\s+)*"
                    + Pattern.quote(modifier)
                    + "\\s+(?:final\\s+)?[A-Za-z0-9_<>.?\\[\\]]+\\s+"
                    + "([A-Za-z0-9_]+)\\s*\\(").matcher(code);
            while (matcher.find()) {
                if (braceDepthAt(code, matcher.start()) == 1) {
                    result.add(matcher.group(1));
                }
            }
            return result;
        }

        String outerMethod(String name) {
            Matcher matcher = methodPattern(name).matcher(code);
            while (matcher.find()) {
                if (braceDepthAt(code, matcher.start()) == 1) {
                    int open = code.indexOf('{', matcher.end());
                    assertTrue("missing body " + name, open >= 0);
                    return code.substring(open + 1, matchingBrace(code, open));
                }
            }
            throw new AssertionError("missing outer method " + name);
        }

        String method(String name) {
            Matcher matcher = methodPattern(name).matcher(code);
            assertTrue("missing method " + name, matcher.find());
            int open = code.indexOf('{', matcher.end());
            assertTrue("missing body " + name, open >= 0);
            int close = matchingBrace(code, open);
            return code.substring(open + 1, close);
        }

        private static Pattern methodPattern(String name) {
            return Pattern.compile(
                    "(?m)(?:^|\\n)\\s*(?:@[A-Za-z0-9_.()\\\" ]+\\s*)*"
                    + "(?:public|protected|private)\\s+[^;{}=]*\\b"
                    + Pattern.quote(name) + "\\s*\\(");
        }
    }

    private static int matchingBrace(String text, int open) {
        int depth = 0;
        boolean string = false;
        boolean character = false;
        boolean escaped = false;
        for (int index = open; index < text.length(); index++) {
            char value = text.charAt(index);
            if (escaped) {
                escaped = false;
            } else if ((string || character) && value == '\\') {
                escaped = true;
            } else if (!character && value == '"') {
                string = !string;
            } else if (!string && value == '\'') {
                character = !character;
            } else if (!string && !character && value == '{') {
                depth++;
            } else if (!string && !character && value == '}' && --depth == 0) {
                return index;
            }
        }
        throw new AssertionError("unbalanced braces");
    }

    private static int braceDepthAt(String text, int limit) {
        int depth = 0;
        boolean string = false;
        boolean character = false;
        boolean escaped = false;
        for (int index = 0; index < limit; index++) {
            char value = text.charAt(index);
            if (escaped) {
                escaped = false;
            } else if ((string || character) && value == '\\') {
                escaped = true;
            } else if (!character && value == '"') {
                string = !string;
            } else if (!string && value == '\'') {
                character = !character;
            } else if (!string && !character && value == '{') {
                depth++;
            } else if (!string && !character && value == '}') {
                depth--;
            }
        }
        return depth;
    }

    private static String stripComments(String text) {
        StringBuilder result = new StringBuilder(text.length());
        boolean line = false;
        boolean block = false;
        boolean string = false;
        boolean character = false;
        boolean escaped = false;
        for (int index = 0; index < text.length(); index++) {
            char value = text.charAt(index);
            char next = index + 1 < text.length() ? text.charAt(index + 1) : '\0';
            if (line) {
                if (value == '\n') { line = false; result.append(value); }
                else result.append(' ');
            } else if (block) {
                if (value == '*' && next == '/') {
                    result.append("  "); index++; block = false;
                } else result.append(value == '\n' ? '\n' : ' ');
            } else if (!string && !character && value == '/' && next == '/') {
                result.append("  "); index++; line = true;
            } else if (!string && !character && value == '/' && next == '*') {
                result.append("  "); index++; block = true;
            } else {
                result.append(value);
                if (escaped) escaped = false;
                else if ((string || character) && value == '\\') escaped = true;
                else if (!character && value == '"') string = !string;
                else if (!string && value == '\'') character = !character;
            }
        }
        return result.toString();
    }
}
