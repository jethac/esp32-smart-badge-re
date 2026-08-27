package net.jethachan.factory_badges.architecture;

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
        List<String> permissions = effectivePermissions(xml);
        assertOnlyAllowedPermissions(permissions);
    }

    @Test
    public void mergedDebugManifestHasNoForbiddenPermissionsOrCleartextTraffic() throws Exception {
        Path mergedManifest = Paths.get(
                "app/build/intermediates/merged_manifests/debug/processDebugManifest/AndroidManifest.xml");
        String xml = new String(Files.readAllBytes(mergedManifest), StandardCharsets.UTF_8);
        assertFalse("usesCleartextTraffic", xml.contains("usesCleartextTraffic"));
        List<String> permissions = effectivePermissions(xml);
        assertOnlyAllowedPermissions(permissions);
    }

    private static List<String> effectivePermissions(String xml) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        NodeList nodes = factory.newDocumentBuilder().parse(
                new ByteArrayInputStream(xml.getBytes(StandardCharsets.UTF_8))).getDocumentElement()
                .getChildNodes();
        java.util.ArrayList<String> permissions = new java.util.ArrayList<String>();
        for (int index = 0; index < nodes.getLength(); index++) {
            Node node = nodes.item(index);
            if (node.getNodeType() == Node.ELEMENT_NODE
                    && "uses-permission".equals(node.getNodeName())) {
                Element permission = (Element) node;
                if (!"remove".equals(permission.getAttributeNS(TOOLS_NAMESPACE, "node"))) {
                    permissions.add(permission.getAttributeNS(ANDROID_NAMESPACE, "name"));
                }
            }
        }
        return permissions;
    }

    private static void assertOnlyAllowedPermissions(List<String> permissions) {
        for (String forbidden : FORBIDDEN) {
            assertFalse(forbidden, permissions.contains(forbidden));
        }
        assertTrue("only allowed permissions: " + permissions,
                ALLOWED.containsAll(permissions) && permissions.containsAll(ALLOWED));
    }
}
