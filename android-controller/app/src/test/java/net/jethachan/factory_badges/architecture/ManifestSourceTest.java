package net.jethachan.factory_badges.architecture;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
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
