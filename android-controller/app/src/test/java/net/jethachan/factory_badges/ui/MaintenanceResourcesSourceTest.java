package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Set;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.Test;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

public final class MaintenanceResourcesSourceTest {
    private static final String ANDROID = "http://schemas.android.com/apk/res/android";

    @Test public void layoutExposesOnlyExplicitGatedTransitionControls() throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        Document document = factory.newDocumentBuilder().parse(
                Paths.get("app/src/main/res/layout/activity_maintenance.xml").toFile());
        Set<String> ids = new LinkedHashSet<String>();
        NodeList all = document.getElementsByTagName("*");
        for (int index = 0; index < all.getLength(); index++) {
            Element element = (Element) all.item(index);
            String id = element.getAttributeNS(ANDROID, "id");
            if (!id.isEmpty()) ids.add(id.replace("@+id/", "").replace("@id/", ""));
            assertFalse(element.getTagName().equals("EditText"));
            assertFalse(element.getTagName().equals("WebView"));
        }

        assertEquals(new LinkedHashSet<String>(Arrays.asList(
                "maintenance_title", "artifact_status", "artifact_identity",
                "receive_mode_warning", "receive_mode_confirmation",
                "start_transition_button", "candidate_label", "candidate_list",
                "transition_progress", "transition_status", "cancel_transition_button",
                "rewrite_heading", "rewrite_explanation", "rewrite_button")), ids);
        Element confirmation = byId(document, "receive_mode_confirmation");
        assertEquals("CheckBox", confirmation.getTagName());
        assertEquals("false", confirmation.getAttributeNS(ANDROID, "checked"));
        assertEquals("@string/confirm_stock_receiving",
                confirmation.getAttributeNS(ANDROID, "text"));
        assertEquals("false", byId(document, "start_transition_button")
                .getAttributeNS(ANDROID, "enabled"));
        assertEquals("false", byId(document, "rewrite_button")
                .getAttributeNS(ANDROID, "enabled"));
    }

    @Test public void stringsNeverCallTransportAcceptanceSuccess() throws Exception {
        String xml = new String(Files.readAllBytes(
                Paths.get("app/src/main/res/values/strings.xml")), StandardCharsets.UTF_8);
        assertTrue(xml.contains(">I put the badge in its stock receiving screen<"));
        assertTrue(xml.contains(">Waiting for custom firmware to boot and identify itself.<"));
        assertTrue(xml.contains(">Not available until custom recovery is hardware-proven.<"));
        assertFalse(xml.contains(">Transition succeeded<"));
        assertFalse(xml.contains(">Firmware update succeeded<"));
    }

    private static Element byId(Document document, String wanted) {
        NodeList all = document.getElementsByTagName("*");
        for (int index = 0; index < all.getLength(); index++) {
            Element element = (Element) all.item(index);
            String id = element.getAttributeNS(ANDROID, "id");
            if (id.equals("@+id/" + wanted) || id.equals("@id/" + wanted)) {
                return element;
            }
        }
        assertNotNull(wanted, null);
        throw new AssertionError(wanted);
    }
}
