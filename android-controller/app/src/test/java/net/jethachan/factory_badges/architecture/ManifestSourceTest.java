package net.jethachan.factory_badges.architecture;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.Test;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

public final class ManifestSourceTest {
    private static final String ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android";
    private static final String TOOLS_NAMESPACE = "http://schemas.android.com/tools";
    private static final List<String> FORBIDDEN = Arrays.asList(
            "android.permission.INTERNET",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.MANAGE_EXTERNAL_STORAGE");
    private static final Set<String> ALLOWED = new HashSet<String>(Arrays.asList(
            "android.permission.BLUETOOTH_SCAN",
            "android.permission.BLUETOOTH_CONNECT",
            "android.permission.FOREGROUND_SERVICE",
            "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
            "android.permission.POST_NOTIFICATIONS"));

    @Test
    public void manifestHasOnlyAllowedEffectivePermissionsAndNoCleartextTraffic() throws Exception {
        String xml = new String(Files.readAllBytes(Paths.get("app/src/main/AndroidManifest.xml")),
                StandardCharsets.UTF_8);
        assertFalse("usesCleartextTraffic", xml.contains("usesCleartextTraffic"));
        List<String> permissions = effectivePermissions(xml, true);
        assertOnlyAllowedPermissions(permissions);
        assertBluetoothScanUsesNeverForLocation(xml, true);
    }

    @Test
    public void sourceManifestHasOnlyNarrowStorageRemovalLintIgnores() throws Exception {
        String xml = new String(Files.readAllBytes(Paths.get("app/src/main/AndroidManifest.xml")),
                StandardCharsets.UTF_8);

        assertStorageRemovalLintIgnoresAreNarrow(xml);
    }

    @Test
    public void storageRemovalLintIgnoreAuditRejectsEveryBroadPlacement() {
        String narrow = " tools:ignore=\"ScopedStorage\"";
        String misplaced = "<uses-permission android:name=\"android.permission.INTERNET\""
                + " tools:node=\"remove\" tools:ignore=\"ScopedStorage\" />";
        String extra = "<application tools:ignore=\"ScopedStorage\" />";

        assertThrows(AssertionError.class, () ->
                assertStorageRemovalLintIgnoresAreNarrow(
                        storageRemovalFixture("", "", narrow, "")));
        assertThrows(AssertionError.class, () ->
                assertStorageRemovalLintIgnoresAreNarrow(
                        storageRemovalFixture("", "", narrow, misplaced)));
        assertThrows(AssertionError.class, () ->
                assertStorageRemovalLintIgnoresAreNarrow(
                        storageRemovalFixture(
                                "",
                                " tools:ignore=\"ScopedStorage,NewApi\"",
                                narrow,
                                "")));
        assertThrows(AssertionError.class, () ->
                assertStorageRemovalLintIgnoresAreNarrow(
                        storageRemovalFixture(
                                " tools:ignore=\"ScopedStorage\"",
                                narrow,
                                narrow,
                                "")));
        assertThrows(AssertionError.class, () ->
                assertStorageRemovalLintIgnoresAreNarrow(
                        storageRemovalFixture("", narrow, narrow, extra)));
        assertThrows(AssertionError.class, () ->
                assertStorageRemovalLintIgnoresAreNarrow(
                        storageRemovalFixture(
                                " tools:targetApi=\"33\"", narrow, narrow, "")));
    }
    // Mutation caught: the service stays at the obsolete package path or becomes exposed.
    @Test
    public void sourceAndMergedManifestsDeclareOnlyPrivateConnectedDeviceService()
            throws Exception {
        String source = new String(Files.readAllBytes(
                Paths.get("app/src/main/AndroidManifest.xml")),
                StandardCharsets.UTF_8);
        String merged = new String(Files.readAllBytes(Paths.get(
                "app/build/intermediates/merged_manifests/debug/"
                        + "processDebugManifest/AndroidManifest.xml")),
                StandardCharsets.UTF_8);

        assertBadgeSyncService(source, ".sync.BadgeSyncService");
        assertBadgeSyncService(
                merged,
                "net.jethachan.factory_badges.sync.BadgeSyncService");
    }

    // Mutation caught: an exported, wrong-type, or intent-filter service is accepted.
    @Test
    public void serviceAuditRejectsUnsafeComponentShapes() {
        assertThrows(AssertionError.class, () -> assertBadgeSyncService(
                serviceFixture("true", "connectedDevice", ""),
                ".sync.BadgeSyncService"));
        assertThrows(AssertionError.class, () -> assertBadgeSyncService(
                serviceFixture("false", "dataSync", ""),
                ".sync.BadgeSyncService"));
        assertThrows(AssertionError.class, () -> assertBadgeSyncService(
                serviceFixture(
                        "false",
                        "connectedDevice",
                        "<intent-filter><action android:name=\"example\" />"
                                + "</intent-filter>"),
                ".sync.BadgeSyncService"));
    }

    // Mutation caught: a receiver or provider introduces an alternate background entry point.
    @Test
    public void serviceAuditRejectsAdditionalBackgroundComponents() {
        assertThrows(AssertionError.class, () -> assertBadgeSyncService(
                serviceFixture("false", "connectedDevice", "<receiver />"),
                ".sync.BadgeSyncService"));
        assertThrows(AssertionError.class, () -> assertBadgeSyncService(
                serviceFixture("false", "connectedDevice", "<provider />"),
                ".sync.BadgeSyncService"));
    }

    @Test
    public void mergedDebugManifestHasNoForbiddenPermissionsOrCleartextTraffic() throws Exception {
        Path mergedManifest = Paths.get(
                "app/build/intermediates/merged_manifests/debug/processDebugManifest/AndroidManifest.xml");
        String xml = new String(Files.readAllBytes(mergedManifest), StandardCharsets.UTF_8);
        assertFalse("usesCleartextTraffic", xml.contains("usesCleartextTraffic"));
        List<String> permissions = effectivePermissions(xml, false);
        assertOnlyAllowedPermissions(permissions);
        assertBluetoothScanUsesNeverForLocation(xml, false);
    }

    @Test(expected = AssertionError.class)
    public void sdkQualifiedForbiddenPermissionIsRejected() throws Exception {
        String xml = "<manifest xmlns:android=\"" + ANDROID_NAMESPACE + "\">"
                + "<uses-permission android:name=\"android.permission.BLUETOOTH_SCAN\" />"
                + "<uses-permission android:name=\"android.permission.BLUETOOTH_CONNECT\" />"
                + "<uses-permission android:name=\"android.permission.FOREGROUND_SERVICE\" />"
                + "<uses-permission android:name="
                + "\"android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE\" />"
                + "<uses-permission android:name=\"android.permission.POST_NOTIFICATIONS\" />"
                + "<uses-permission-sdk-23 "
                + "android:name=\"android.permission.INTERNET\" />"
                + "</manifest>";

        assertOnlyAllowedPermissions(effectivePermissions(xml, false));
    }

    @Test(expected = AssertionError.class)
    public void bluetoothScanWithoutNeverForLocationIsRejected() throws Exception {
        String xml = "<manifest xmlns:android=\"" + ANDROID_NAMESPACE + "\">"
                + "<uses-permission-sdk-23 "
                + "android:name=\"android.permission.BLUETOOTH_SCAN\" />"
                + "</manifest>";

        assertBluetoothScanUsesNeverForLocation(xml, false);
    }

    @Test
    public void removalNodesAreExcludedOnlyFromSourceManifestChecks() throws Exception {
        String xml = "<manifest xmlns:android=\"" + ANDROID_NAMESPACE + "\""
                + " xmlns:tools=\"" + TOOLS_NAMESPACE + "\">"
                + "<uses-permission-sdk-23 android:name=\"android.permission.INTERNET\""
                + " tools:node=\"remove\" /></manifest>";

        List<String> sourcePermissions = effectivePermissions(xml, true);
        List<String> mergedPermissions = effectivePermissions(xml, false);
        assertFalse(sourcePermissions.contains("android.permission.INTERNET"));
        assertTrue(mergedPermissions.contains("android.permission.INTERNET"));
    }
    private static void assertBadgeSyncService(String xml, String expectedName)
            throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        Element manifest = factory.newDocumentBuilder().parse(
                new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)))
                .getDocumentElement();
        NodeList applications = manifest.getElementsByTagName("application");
        assertEquals("one application", 1, applications.getLength());
        Element application = (Element) applications.item(0);
        assertEquals("usesCleartextTraffic is forbidden",
                "", application.getAttributeNS(
                        ANDROID_NAMESPACE, "usesCleartextTraffic"));

        NodeList services = application.getElementsByTagName("service");
        assertEquals("one service", 1, services.getLength());
        Element service = (Element) services.item(0);
        assertEquals("badge sync service name",
                expectedName,
                service.getAttributeNS(ANDROID_NAMESPACE, "name"));
        assertEquals("badge sync service must not be exported",
                "false",
                service.getAttributeNS(ANDROID_NAMESPACE, "exported"));
        assertEquals("badge sync service foreground type",
                "connectedDevice",
                service.getAttributeNS(
                        ANDROID_NAMESPACE, "foregroundServiceType"));
        assertEquals("badge sync service has no intent filter",
                0,
                service.getElementsByTagName("intent-filter").getLength());
        assertEquals("no receiver",
                0,
                application.getElementsByTagName("receiver").getLength());
        assertEquals("no provider",
                0,
                application.getElementsByTagName("provider").getLength());
    }

    private static String serviceFixture(
            String exported, String foregroundType, String child) {
        return "<manifest xmlns:android=\"" + ANDROID_NAMESPACE + "\">"
                + "<application><service "
                + "android:name=\".sync.BadgeSyncService\" "
                + "android:exported=\"" + exported + "\" "
                + "android:foregroundServiceType=\"" + foregroundType + "\">"
                + child
                + "</service></application></manifest>";
    }

    private static void assertStorageRemovalLintIgnoresAreNarrow(String xml)
            throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        NodeList elements = factory.newDocumentBuilder().parse(
                new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8)))
                .getElementsByTagName("*");
        int readStorageNodes = 0;
        int writeStorageNodes = 0;
        for (int index = 0; index < elements.getLength(); index++) {
            Element element = (Element) elements.item(index);
            assertEquals("tools:targetApi is forbidden",
                    "", element.getAttributeNS(TOOLS_NAMESPACE, "targetApi"));
            String ignore = element.getAttributeNS(TOOLS_NAMESPACE, "ignore");
            String permission = isPermissionDeclaration(element)
                    ? element.getAttributeNS(ANDROID_NAMESPACE, "name")
                    : "";
            boolean readStorage =
                    "android.permission.READ_EXTERNAL_STORAGE".equals(permission);
            boolean writeStorage =
                    "android.permission.WRITE_EXTERNAL_STORAGE".equals(permission);
            if (readStorage || writeStorage) {
                assertEquals(permission + " must remain a removal node",
                        "remove", element.getAttributeNS(TOOLS_NAMESPACE, "node"));
                assertEquals(permission + " must ignore only ScopedStorage",
                        "ScopedStorage", ignore);
                if (readStorage) {
                    readStorageNodes++;
                } else {
                    writeStorageNodes++;
                }
            } else {
                assertEquals("tools:ignore is allowed only on storage removals: "
                        + element.getTagName(), "", ignore);
            }
        }
        assertEquals("one READ_EXTERNAL_STORAGE removal", 1, readStorageNodes);
        assertEquals("one WRITE_EXTERNAL_STORAGE removal", 1, writeStorageNodes);
    }

    private static String storageRemovalFixture(
            String manifestTools,
            String readTools,
            String writeTools,
            String extraElement) {
        return "<manifest xmlns:android=\"" + ANDROID_NAMESPACE + "\""
                + " xmlns:tools=\"" + TOOLS_NAMESPACE + "\"" + manifestTools + ">"
                + "<uses-permission android:name="
                + "\"android.permission.READ_EXTERNAL_STORAGE\""
                + " tools:node=\"remove\"" + readTools + " />"
                + "<uses-permission android:name="
                + "\"android.permission.WRITE_EXTERNAL_STORAGE\""
                + " tools:node=\"remove\"" + writeTools + " />"
                + extraElement
                + "</manifest>";
    }

    private static List<String> effectivePermissions(
            String xml, boolean excludeSourceRemovalNodes) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        NodeList nodes = factory.newDocumentBuilder().parse(
                new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8))).getDocumentElement()
                .getChildNodes();
        java.util.ArrayList<String> permissions = new java.util.ArrayList<String>();
        for (int index = 0; index < nodes.getLength(); index++) {
            Node node = nodes.item(index);
            if (isPermissionDeclaration(node)) {
                Element permission = (Element) node;
                if (!excludeSourceRemovalNodes || !isRemovalNode(permission)) {
                    permissions.add(permission.getAttributeNS(ANDROID_NAMESPACE, "name"));
                }
            }
        }
        return permissions;
    }

    private static void assertBluetoothScanUsesNeverForLocation(
            String xml, boolean excludeSourceRemovalNodes) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        NodeList nodes = factory.newDocumentBuilder().parse(
                new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8))).getDocumentElement()
                .getChildNodes();
        boolean foundBluetoothScan = false;
        for (int index = 0; index < nodes.getLength(); index++) {
            Node node = nodes.item(index);
            if (!isPermissionDeclaration(node)) {
                continue;
            }
            Element permission = (Element) node;
            if (excludeSourceRemovalNodes && isRemovalNode(permission)) {
                continue;
            }
            if ("android.permission.BLUETOOTH_SCAN".equals(
                    permission.getAttributeNS(ANDROID_NAMESPACE, "name"))) {
                foundBluetoothScan = true;
                assertEquals("BLUETOOTH_SCAN must declare neverForLocation",
                        "neverForLocation",
                        permission.getAttributeNS(ANDROID_NAMESPACE, "usesPermissionFlags"));
            }
        }
        assertTrue("BLUETOOTH_SCAN declaration missing", foundBluetoothScan);
    }

    private static boolean isPermissionDeclaration(Node node) {
        String localName = node.getLocalName();
        return node.getNodeType() == Node.ELEMENT_NODE
                && localName != null
                && localName.startsWith("uses-permission");
    }

    private static boolean isRemovalNode(Element permission) {
        return "remove".equals(permission.getAttributeNS(TOOLS_NAMESPACE, "node"));
    }

    private static void assertOnlyAllowedPermissions(List<String> permissions) {
        for (String forbidden : FORBIDDEN) {
            assertFalse(forbidden, permissions.contains(forbidden));
        }
        assertTrue("only allowed permissions: " + permissions,
                ALLOWED.containsAll(permissions) && permissions.containsAll(ALLOWED));
    }
}
