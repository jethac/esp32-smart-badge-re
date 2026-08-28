package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.junit.Test;

public final class MaintenanceActivityBoundaryTest {
    private static final Path ACTIVITY = Paths.get(
            "app/src/main/java/net/jethachan/factory_badges/ui/MaintenanceActivity.java");
    private static final Path SESSION = Paths.get(
            "app/src/main/java/net/jethachan/factory_badges/ui/AndroidStockTransitionSession.java");

    @Test public void activityCreationLoadsAvailabilityButNeverScansOrTransfers() throws Exception {
        String source = read(ACTIVITY);
        String onCreate = method(source, "onCreate");

        assertTrue(onCreate.contains("new EmbeddedFirmwareRepository("));
        assertTrue(onCreate.contains("new MaintenanceUiPresenter("));
        assertFalse(onCreate.matches("(?s).*(startScan|onStartPressed|requestPermissions|"
                + "StockTransitionController|StockQixGattTransport).*"));
        assertFalse(source.matches("(?s).*(update\\.ufw|\\\"[^\\\"]*\\.qix\\\"|"
                + "QIX_HEADER|byte\\[\\].*=).*"));
    }

    @Test public void directLifecycleEntryFailsClosedBeforeAnyUiOrSessionSideEffect()
            throws Exception {
        String onCreate = method(read(ACTIVITY), "onCreate");

        assertOrder(onCreate,
                "super.onCreate(savedInstanceState)",
                "if (!MaintenanceEntryGate.canEnter(getApplicationContext()))",
                "finish()",
                "return",
                "setContentView(R.layout.activity_maintenance)",
                "findViewById(R.id.artifact_status)",
                "new Handler(Looper.getMainLooper())",
                "new MaintenanceUiPresenter(",
                "new EmbeddedFirmwareRepository(getApplicationContext())");
        String beforeGate = onCreate.substring(0,
                onCreate.indexOf("MaintenanceEntryGate.canEnter"));
        assertFalse(beforeGate.matches("(?s).*(setContentView|findViewById|new Handler|"
                + "new EmbeddedFirmwareRepository|new MaintenanceUiPresenter|requestPermissions|"
                + "startScan|openSession).*"));
    }

    @Test public void explicitStartChecksPermissionBeforePresenterConsumesGate() throws Exception {
        String start = method(read(ACTIVITY), "onStartTransitionClicked");

        assertOrder(start, "nearbyPermissionsGranted()", "requestPermissions(",
                "presenter.onConfirmationChanged(false)");
        assertTrue(start.indexOf("presenter.onStartPressed()")
                > start.indexOf("nearbyPermissionsGranted()"));
        assertFalse(start.matches("(?s).*(startScan|StockTransitionController|"
                + "StockQixGattTransport).*"));
    }

    @Test public void sessionAdapterOwnsTheOnlyUiToStockControllerBridge() throws Exception {
        String source = read(SESSION);

        assertTrue(source.contains("implements MaintenanceUiPresenter.Session"));
        assertTrue(source.contains("new StockQixGattTransport("));
        assertTrue(source.contains("new StockTransitionController("));
        assertTrue(method(source, "startScan").contains("controller.startScan()"));
        assertTrue(method(source, "connect").contains(
                "controller.connect(peer, identity.settings(), identity.hostId())"));
        assertFalse(source.matches("(?s).*(AssetManager|update\\.ufw|\\.qix|"
                + "BluetoothOTAManager|AE00|AE01|AE02).*"));
    }

    @Test public void surfacedCandidateButtonsRemainDisabledUntilTheFreshConnectGate()
            throws Exception {
        String renderCandidates = method(read(ACTIVITY), "renderCandidates");

        assertTrue(renderCandidates.contains("MaintenanceUiPresenter.Phase.CANDIDATES"));
        assertTrue(renderCandidates.contains("state.confirmationChecked()"));
        assertTrue(renderCandidates.contains("presenter.onCandidateSelected(peer)"));
    }

    @Test public void mainScreenCanOnlyOpenMaintenanceByExplicitActivityIntent() throws Exception {
        String source = read(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ui/MainActivity.java"));
        String click = method(source, "onMaintenanceClicked");

        assertTrue(click.contains(
                "new Intent(MainActivity.this, MaintenanceActivity.class)"));
        assertTrue(click.contains("startActivity("));
        assertFalse(click.matches("(?s).*(startScan|StockTransition|TransitionArtifact|"
                + "EmbeddedFirmwareRepository).*"));
    }

    private static String read(Path path) throws Exception {
        return new String(Files.readAllBytes(path), StandardCharsets.UTF_8)
                .replace("\r\n", "\n");
    }

    private static String method(String source, String name) {
        int marker = source.indexOf("void " + name + "(");
        if (marker < 0) throw new AssertionError("missing method " + name);
        int open = source.indexOf('{', marker);
        if (open < 0) throw new AssertionError("missing method body " + name);
        int depth = 0;
        boolean string = false;
        boolean character = false;
        boolean escaped = false;
        for (int index = open; index < source.length(); index++) {
            char value = source.charAt(index);
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
                return source.substring(open + 1, index);
            }
        }
        throw new AssertionError("unterminated method " + name);
    }

    private static void assertOrder(String text, String... fragments) {
        int position = -1;
        for (String fragment : fragments) {
            int next = text.indexOf(fragment, position + 1);
            assertTrue("missing/out of order: " + fragment, next > position);
            position = next;
        }
    }
}
