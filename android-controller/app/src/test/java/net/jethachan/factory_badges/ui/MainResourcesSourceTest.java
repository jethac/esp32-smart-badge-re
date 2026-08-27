package net.jethachan.factory_badges.ui;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import javax.xml.parsers.DocumentBuilderFactory;
import org.junit.Test;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

public final class MainResourcesSourceTest {
    private static final String ANDROID = "http://schemas.android.com/apk/res/android";

    // Mutation: alter a reviewed Task 4C notification string while adding UI resources.
    @Test public void notificationStringsRemainExact() throws Exception {
        Map<String, String> values = strings();
        assertEquals("Badge sync", values.get("badge_sync_channel_name"));
        assertEquals("Badge sync active", values.get("badge_sync_notification_title"));
        assertEquals("Waiting for a badge", values.get("badge_sync_notification_waiting"));
        assertEquals("Connecting to badge", values.get("badge_sync_notification_connecting"));
        assertEquals("Badge connected", values.get("badge_sync_notification_ready"));
        assertEquals("Reconnecting to badge", values.get("badge_sync_notification_retry"));
        assertEquals("Badge sync needs attention", values.get("badge_sync_notification_error"));
    }

    // Mutation: drift any user-facing value, format, warning, or fixed credit resource.
    @Test public void taskFiveStringsResolveToExactDecodedText() throws Exception {
        Map<String, String> expected = new LinkedHashMap<>();
        expected.put("app_name", "Factory Badges");
        expected.put("main_title", "Devin badge");
        expected.put("selected_badge_label", "Selected badge");
        expected.put("no_badge_selected", "No E87 badge selected");
        expected.put("selected_badge_format", "E87 • …%1$s • %2$s");
        expected.put("selected_badge_name_only", "E87");
        expected.put("paired", "Paired");
        expected.put("not_paired", "Not paired");
        expected.put("choose_badge", "Find E87 badge");
        expected.put("connection_label", "Connection");
        expected.put("status_service_connecting", "Opening badge sync");
        expected.put("status_service_unavailable", "Service unavailable");
        expected.put("status_sync_off", "Sync is off");
        expected.put("status_no_device", "Choose a badge");
        expected.put("status_bonding", "Pairing");
        expected.put("status_connecting", "Connecting");
        expected.put("status_discovering", "Checking services");
        expected.put("status_validating_build", "Checking firmware");
        expected.put("status_ready", "Connected");
        expected.put("status_retrying", "Reconnecting");
        expected.put("status_error", "Needs attention");
        expected.put("guidance_wait_for_service", "Preparing badge sync controls.");
        expected.put("guidance_choose_badge",
                "Hold Sync/Pair on the badge for 3 seconds, then tap Find E87 badge.");
        expected.put("guidance_hold_sync_pair",
                "Hold Sync/Pair on the badge for 3 seconds, then release it.");
        expected.put("guidance_wait_for_connection",
                "Keep the phone near the badge while it connects.");
        expected.put("guidance_adjust_and_sync",
                "Adjust Day and Week, then tap Start syncing or Sync now.");
        expected.put("guidance_retrying", "The phone will retry automatically.");
        expected.put("guidance_stop_fix_retry",
                "Tap Stop sync, fix the issue, then tap Start syncing to try again.");
        expected.put("day_label", "Day");
        expected.put("week_label", "Week");
        expected.put("percent_format", "%1$d%%");
        expected.put("percent_state_format", "Progress %1$d%%");
        expected.put("day_seek_description", "Day percentage");
        expected.put("week_seek_description", "Week percentage");
        expected.put("credit_label", "On-demand credit");
        expected.put("credit_value", "$17.27");
        expected.put("credit_description", "On-demand credit, 17 dollars and 27 cents");
        expected.put("start_sync", "Start syncing");
        expected.put("sync_now", "Sync now");
        expected.put("stop_sync", "Stop sync");
        expected.put("last_sync_never", "Not synced yet.");
        expected.put("last_sync_current",
                "Last sync acknowledged: Day %1$d%%, Week %2$d%%.");
        expected.put("last_sync_older",
                "Last sync acknowledged: Day %1$d%%, Week %2$d%%. Current sliders are not yet acknowledged.");
        expected.put("firmware_format", "Firmware %1$d.%2$d.%3$d");
        expected.put("ready_detail_with_battery",
                "Firmware %1$d.%2$d.%3$d • Battery %4$d%%");
        expected.put("retry_seconds_format", "Reconnecting in %1$d s");
        expected.put("retry_error_format", "%1$s Reconnecting in %2$d s");
        expected.put("bluetooth_permission_problem",
                "Nearby devices permission is required to find and sync an E87 badge.");
        expected.put("bluetooth_off_problem", "Bluetooth is off. Turn it on and try again.");
        expected.put("no_badge_found_problem",
                "No E87 badge found. Hold Sync/Pair for 3 seconds and try again.");
        expected.put("scan_failed_problem", "Android could not scan for the badge. Try again.");
        expected.put("service_unavailable_problem",
                "Badge sync service is unavailable. Reopen this screen and try again.");
        expected.put("sync_start_failed_problem",
                "Android could not start badge sync. Keep this screen open and try again.");
        expected.put("notification_permission_warning",
                "Notifications are off; badge sync can still run.");
        expected.put("scan_dialog_title", "Nearby E87 badges");
        expected.put("scan_dialog_searching", "Searching…");
        expected.put("cancel", "Cancel");
        Map<String, String> actual = strings();
        for (Map.Entry<String, String> entry : expected.entrySet()) {
            assertEquals(entry.getKey(), entry.getValue(), actual.get(entry.getKey()));
        }
    }

    // Mutation: retain the dead standalone battery-only format resource.
    @Test public void deadStandaloneBatteryFormatIsAbsent() throws Exception {
        assertFalse(strings().containsKey("battery_format"));
    }

    // Mutation: clip at large fonts, change an ID, add a forbidden view, or loosen slider semantics.
    @Test public void layoutHasExactStructureIdsAndAccessibility() throws Exception {
        Document document = parse(Files.readAllBytes(
                Paths.get("app/src/main/res/layout/activity_main.xml")));
        Element root = document.getDocumentElement();
        assertEquals("ScrollView", root.getTagName());
        Element content = onlyElementChild(root);
        assertEquals("LinearLayout", content.getTagName());
        assertEquals("vertical", attr(content, "orientation"));
        assertEquals("16dp", attr(content, "padding"));

        Set<String> ids = new LinkedHashSet<>();
        NodeList all = document.getElementsByTagName("*");
        for (int index = 0; index < all.getLength(); index++) {
            Element element = (Element) all.item(index);
            String id = attr(element, "id");
            if (!id.isEmpty()) ids.add(id.replace("@+id/", "").replace("@id/", ""));
            assertFalse(Arrays.asList("EditText", "ImageView", "SurfaceView", "TextureView",
                    "WebView", "ComposeView", "View").contains(element.getTagName()));
            assertFalse(element.hasAttributeNS(ANDROID, "src"));
            assertFalse(element.hasAttributeNS(ANDROID, "background")
                    && attr(element, "background").startsWith("@drawable/"));
        }
        assertEquals(new LinkedHashSet<>(Arrays.asList("main_title", "selected_badge_label",
                "selected_badge_value", "choose_badge_button", "connection_label",
                "connection_status_value", "connection_detail_value", "sync_pair_guidance",
                "local_warning_value", "notification_warning_value", "day_label", "day_value",
                "day_seek", "week_label", "week_value", "week_seek", "credit_label",
                "credit_value", "last_sync_value", "sync_button", "stop_sync_button")), ids);

        assertSeek(document, "day_seek", "@string/day_seek_description");
        assertSeek(document, "week_seek", "@string/week_seek_description");
        assertEquals("@id/day_seek", attr(byId(document, "day_label"), "labelFor"));
        assertEquals("@id/week_seek", attr(byId(document, "week_label"), "labelFor"));
        Element credit = byId(document, "credit_value");
        assertEquals("TextView", credit.getTagName());
        assertEquals("@string/credit_value", attr(credit, "text"));
        assertEquals("@string/credit_description", attr(credit, "contentDescription"));
        for (String id : Arrays.asList("connection_status_value",
                "connection_detail_value", "sync_pair_guidance", "last_sync_value")) {
            assertEquals(id, "polite", attr(byId(document, id),
                    "accessibilityLiveRegion"));
        }
        assertEquals("assertive", attr(byId(document, "local_warning_value"), "accessibilityLiveRegion"));
        assertEquals("gone", attr(byId(document, "local_warning_value"), "visibility"));
        assertEquals("polite", attr(byId(document, "notification_warning_value"),
                "accessibilityLiveRegion"));
        assertEquals("gone", attr(byId(document, "notification_warning_value"), "visibility"));
        for (String id : Arrays.asList("choose_badge_button", "sync_button", "stop_sync_button")) {
            assertEquals("48dp", attr(byId(document, id), "minHeight"));
        }
    }

    // Mutation: change the platform theme parent or introduce dynamic/remote presentation.
    @Test public void themeIsExactNeutralPlatformTheme() throws Exception {
        Document document = parse(Files.readAllBytes(Paths.get("app/src/main/res/values/styles.xml")));
        Element style = (Element) document.getElementsByTagName("style").item(0);
        assertNotNull(style);
        assertEquals("Theme.FactoryBadges", style.getAttribute("name"));
        assertEquals("@android:style/Theme.Material.Light.NoActionBar", style.getAttribute("parent"));
        String xml = new String(Files.readAllBytes(Paths.get("app/src/main/res/values/styles.xml")),
                StandardCharsets.UTF_8);
        assertTrue(xml.contains("windowActionModeOverlay"));
        assertTrue(xml.contains("windowLightStatusBar"));
        assertFalse(xml.matches("(?s).*https?://.*"));
    }

    // Mutation: let a malformed fixture satisfy a structural assertion by substring alone.
    @Test public void malformedLayoutFixturesAreRejectedStructurally() {
        assertThrows(AssertionError.class, () -> assertSeek(parse(
                ("<ScrollView xmlns:android='http://schemas.android.com/apk/res/android'>"
                        + "<SeekBar android:id='@+id/day_seek' android:max='99'/></ScrollView>")
                                .getBytes(StandardCharsets.UTF_8)),
                "day_seek", "@string/day_seek_description"));
    }

    private static void assertSeek(Document document, String id, String description) {
        Element seek = byId(document, id);
        assertEquals("SeekBar", seek.getTagName());
        assertEquals("0", attr(seek, "min"));
        assertEquals("100", attr(seek, "max"));
        assertEquals("", attr(seek, "keyProgressIncrement"));
        assertEquals("false", attr(seek, "splitTrack"));
        assertEquals("0", attr(seek, "progress"));
        assertEquals(description, attr(seek, "contentDescription"));
    }

    private static Map<String, String> strings() throws Exception {
        Document document = parse(Files.readAllBytes(Paths.get("app/src/main/res/values/strings.xml")));
        Map<String, String> values = new LinkedHashMap<>();
        NodeList strings = document.getElementsByTagName("string");
        for (int index = 0; index < strings.getLength(); index++) {
            Element element = (Element) strings.item(index);
            values.put(element.getAttribute("name"), element.getTextContent());
        }
        return values;
    }

    private static Element byId(Document document, String id) {
        NodeList all = document.getElementsByTagName("*");
        for (int index = 0; index < all.getLength(); index++) {
            Element element = (Element) all.item(index);
            if (("@+id/" + id).equals(attr(element, "id"))
                    || ("@id/" + id).equals(attr(element, "id"))) return element;
        }
        throw new AssertionError("missing id " + id);
    }

    private static Element onlyElementChild(Element parent) {
        Element result = null;
        NodeList children = parent.getChildNodes();
        for (int index = 0; index < children.getLength(); index++) {
            Node node = children.item(index);
            if (node instanceof Element) {
                if (result != null) throw new AssertionError("more than one root child");
                result = (Element) node;
            }
        }
        assertNotNull(result);
        return result;
    }

    private static String attr(Element element, String name) {
        return element.getAttributeNS(ANDROID, name);
    }

    private static Document parse(byte[] bytes) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        return factory.newDocumentBuilder().parse(new ByteArrayInputStream(bytes));
    }
}
