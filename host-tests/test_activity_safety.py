import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_PATH = (
    ROOT
    / "src"
    / "main"
    / "java"
    / "com"
    / "openai"
    / "e87probe"
    / "ProbeActivity.java"
)
MANIFEST_PATH = ROOT / "src" / "main" / "AndroidManifest.xml"


def method_body(source, signature, next_signature):
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


class ActivitySafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ACTIVITY_PATH.read_text(encoding="utf-8")
        cls.manifest = MANIFEST_PATH.read_text(encoding="utf-8")

    def test_launch_is_ui_only_and_requires_unchecked_confirmation(self):
        self.assertRegex(
            self.source,
            r"public final class ProbeActivity extends Activity\s+"
            r"implements UploadStartCoordinator[.]Host",
        )
        on_create = method_body(
            self.source,
            "protected void onCreate(Bundle savedInstanceState)",
            "private void handleStartResult",
        )
        self.assertNotIn("requestPermissions(", on_create)
        self.assertNotIn("startScan(", on_create)
        self.assertNotIn("connectGatt(", on_create)
        self.assertNotIn("getExternalFilesDir(", on_create)
        self.assertNotIn("new FileOutputStream", on_create)
        self.assertNotIn("log(", on_create)
        self.assertIn("receiveModeConfirmation.setChecked(false)", on_create)
        self.assertIn("startButton.setEnabled(false)", on_create)
        self.assertIn("startCoordinator.setReceiveModeConfirmed(isChecked)", on_create)
        self.assertIn("startCoordinator.start()", on_create)
        self.assertIn("scanButton.setOnClickListener", on_create)
        self.assertIn("TARGET DEVICE - NO EXACT MAC SELECTED", on_create)
        self.assertIn("DESTRUCTIVE ONE-SHOT LAB UPLOAD", on_create)
        self.assertIn("hardware receive/update mode", on_create)

    def test_permission_is_picker_scan_only(self):
        callback = method_body(
            self.source,
            "public void onRequestPermissionsResult",
            "public String freezeSelectedAddress()",
        )
        self.assertIn("!pickerPermissionPending", callback)
        self.assertIn("if (granted) startPickerScan()", callback)
        self.assertNotIn("startExactAddressScan", callback)
        coordinator = (ROOT / "src/main/java/com/openai/e87probe/UploadStartCoordinator.java").read_text()
        self.assertNotIn("requestBluetoothPermissions", coordinator)

    def test_no_default_or_intent_upload_target(self):
        self.assertNotIn("DEFAULT_MAC", self.source)
        self.assertNotIn('getStringExtra("mac")', self.source)
        self.assertIn("targetMac = pickerState.consumeAndFreeze()", self.source)

    def test_scan_and_result_are_exact_address_only(self):
        scan = method_body(
            self.source,
            "private void startScan()",
            "private final ScanCallback scanCallback",
        )
        self.assertIn(
            "new ScanFilter.Builder().setDeviceAddress(targetMac).build()",
            scan,
        )
        self.assertNotIn("setDeviceName", scan)
        self.assertNotIn("or name", scan)

        result = method_body(
            self.source,
            "private void handleScanResult(ScanResult result)",
            "private void stopScan()",
        )
        self.assertIn(
            "if (!ProbeSequence.matchesAdvertisement(targetMac, address)) return;",
            result,
        )
        self.assertNotIn("namedE87", result)
        self.assertNotIn('contains("E87")', result)

    def test_reviewed_pin_is_loaded_before_permissions_and_reused_for_c0(self):
        self.assertIn("GeneratedPackagePin.create()", self.source)
        validation = method_body(
            self.source,
            "public boolean validatePinnedPackage()",
            "public boolean bluetoothPermissionsGranted()",
        )
        self.assertIn(
            "AndroidFdPackageReader.readExactly(",
            validation,
        )
        self.assertIn(
            "PinnedPackageValidator.validate(packageBytes, packagePin)",
            validation,
        )
        self.assertNotIn("PinnedPackageValidator.validate(source, packagePin)", validation)
        self.assertIn("validatedPackage = validated", validation)

        send_c0 = method_body(
            self.source,
            "private void sendUpdateHeaderProbe()",
            "private void beginFd02Frame",
        )
        self.assertIn("validatedPackage.header()", send_c0)
        self.assertNotIn("loadFirmwarePackage()", send_c0)
        self.assertNotIn("EXPECTED_PACKAGE_SIZE", self.source)
        self.assertNotIn("EXPECTED_PACKAGE_SHA256", self.source)
        self.assertNotIn("UPDATE_HEADER", self.source)
        self.assertNotIn("verifyOnly", self.source)
        self.assertNotIn("getAssets()", self.source)

    def test_package_identity_and_lab_label_stay_intentional(self):
        self.assertIn('package="com.openai.e87probe"', self.manifest)
        self.assertIn('android:label="E87 One-Shot Lab Uploader"', self.manifest)
        self.assertIn('new File(root, "update.bin")', self.source)
        self.assertNotIn("asset", self.source.lower())

    def test_fresh_transfer_and_c5_are_physically_gated(self):
        self.assertIn(
            "FirmwareTransferSafety.requireFreshC1Offset(update.offset)",
            self.source,
        )
        self.assertIn("finalC2WriteCompleted = true", self.source)
        self.assertIn("FirmwareTransferSafety.C5Disposition.DEFER", self.source)
        self.assertIn("deferredC5Frame", self.source)
        self.assertIn("processDeferredC5IfReady()", self.source)
        self.assertIn("if (!outputDirectory.mkdir())", self.source)
        self.assertIn("if (!appendJournal(", self.source)


if __name__ == "__main__":
    unittest.main()
