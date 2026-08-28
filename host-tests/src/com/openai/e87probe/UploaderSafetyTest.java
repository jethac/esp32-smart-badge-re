package com.openai.e87probe;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;

public final class UploaderSafetyTest {
    private static final byte[] VALID_HEADER = Hex.decode(
            "BCAF01312E30000000000000000800000000000000000000001234");
    private static final byte[] VALID_PAYLOAD = Hex.decode("0011223344556677");
    private static final byte[] VALID_PACKAGE = concat(VALID_HEADER, VALID_PAYLOAD);
    private static final String VALID_SHA256 =
            "190F32B094719E9587CCE687243F062C7E967B09A5362113AEE79A2E90CF250A";

    public static void main(String[] args) throws Exception {
        testConstructionAndUncheckedStartHaveNoSideEffects();
        testValidationFailureConsumesTheSingleStart();
        testPermissionRequestFollowsValidationAndGrantStartsExactScan();
        testExistingPermissionStartsScanImmediatelyAfterValidation();
        testPermissionDenialAndDuplicateCallbacksStayClosed();
        testValidPinnedPackageReturnsDefensiveHeaderAndPayload();
        testPinRejectsUnsafeOrNoncanonicalConstantsBeforeAllocation();
        testValidatorRejectsSizeHashAndHeaderMismatch();
        testValidatorRejectsMissingDirectoryAndSymlinkInputs();
        System.out.println("UploaderSafetyTest: PASS");
    }

    private static void testConstructionAndUncheckedStartHaveNoSideEffects() {
        FakeHost host = new FakeHost();
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);

        equal(false, coordinator.isStartEnabled(), "confirmation begins unchecked");
        equal(0, host.totalCalls(), "construction has no host side effects");
        equal(UploadStartCoordinator.Result.NOT_CONFIRMED, coordinator.start(),
                "unchecked Start is inert");
        equal(0, host.totalCalls(), "unchecked Start has no host side effects");
    }

    private static void testValidationFailureConsumesTheSingleStart() {
        FakeHost host = new FakeHost();
        host.packageValid = false;
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);
        coordinator.setReceiveModeConfirmed(true);

        equal(UploadStartCoordinator.Result.VALIDATION_FAILED, coordinator.start(),
                "invalid package fails before Android permissions");
        equal(1, host.validationCalls, "package is validated exactly once");
        equal(0, host.permissionCalls, "invalid package cannot request permissions");
        equal(0, host.scanCalls, "invalid package cannot scan");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED, coordinator.start(),
                "failed destructive attempt is still one-shot");
        equal(1, host.validationCalls, "consumed Start cannot validate again");
    }

    private static void testPermissionRequestFollowsValidationAndGrantStartsExactScan() {
        FakeHost host = new FakeHost();
        host.packageValid = true;
        host.permissionsGranted = false;
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);
        coordinator.setReceiveModeConfirmed(true);

        equal(UploadStartCoordinator.Result.PERMISSION_REQUESTED, coordinator.start(),
                "permission request follows successful validation");
        equal(1, host.validationCalls, "package validation ran first");
        equal(1, host.permissionCalls, "permissions requested once");
        equal(0, host.scanCalls, "scan waits for permission result");
        equal(UploadStartCoordinator.Result.SCAN_STARTED, coordinator.onPermissionResult(true),
                "granted callback starts exact-address scan");
        equal(1, host.scanCalls, "scan starts once");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED,
                coordinator.onPermissionResult(true),
                "duplicate permission callback cannot scan again");
        equal(1, host.scanCalls, "duplicate callback remains inert");
    }

    private static void testExistingPermissionStartsScanImmediatelyAfterValidation() {
        FakeHost host = new FakeHost();
        host.packageValid = true;
        host.permissionsGranted = true;
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);
        coordinator.setReceiveModeConfirmed(true);

        equal(UploadStartCoordinator.Result.SCAN_STARTED, coordinator.start(),
                "pre-granted permission starts scan after validation");
        equal(1, host.validationCalls, "package validated before scan");
        equal(0, host.permissionCalls, "pre-granted permission is not requested again");
        equal(1, host.scanCalls, "scan starts once");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED, coordinator.start(),
                "successful Start is one-shot");
        equal(1, host.scanCalls, "second click cannot rescan");
    }

    private static void testPermissionDenialAndDuplicateCallbacksStayClosed() {
        FakeHost host = new FakeHost();
        host.packageValid = true;
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);
        coordinator.setReceiveModeConfirmed(true);

        equal(UploadStartCoordinator.Result.PERMISSION_REQUESTED, coordinator.start(),
                "permission request is armed");
        equal(UploadStartCoordinator.Result.PERMISSION_DENIED,
                coordinator.onPermissionResult(false),
                "denial ends the one-shot attempt");
        equal(0, host.scanCalls, "denial cannot start scanning");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED,
                coordinator.onPermissionResult(true),
                "late grant after denial remains inert");
        equal(0, host.scanCalls, "late callback cannot bypass denial");
    }

    private static void testValidPinnedPackageReturnsDefensiveHeaderAndPayload()
            throws IOException {
        Path directory = Files.createTempDirectory("e87-valid-package-");
        try {
            Path packagePath = directory.resolve("update.bin");
            Files.write(packagePath, VALID_PACKAGE);
            PackagePin pin = validPin();

            PinnedPackageValidator.ValidatedPackage validated =
                    PinnedPackageValidator.validate(packagePath.toFile(), pin);

            bytes(VALID_HEADER, validated.header(), "validated header is exact");
            bytes(VALID_PAYLOAD, validated.payload(), "validated payload is exact");
            equal(VALID_SHA256, validated.sha256(), "validated digest is canonical");

            byte[] returnedHeader = validated.header();
            byte[] returnedPayload = validated.payload();
            returnedHeader[0] ^= 0x7F;
            returnedPayload[0] ^= 0x7F;
            bytes(VALID_HEADER, validated.header(), "header is defensively copied");
            bytes(VALID_PAYLOAD, validated.payload(), "payload is defensively copied");

            byte[] pinHeader = pin.header();
            pinHeader[0] ^= 0x7F;
            bytes(VALID_HEADER, pin.header(), "pin header is defensively copied");
        } finally {
            deleteTree(directory);
        }
    }

    private static void testPinRejectsUnsafeOrNoncanonicalConstantsBeforeAllocation() {
        throwsIllegalArgument(
                () -> new PackagePin(27, VALID_SHA256, VALID_HEADER),
                "package must contain payload after 27-byte header");
        throwsIllegalArgument(
                () -> new PackagePin(PackagePin.MAX_PACKAGE_SIZE_BYTES + 1,
                        VALID_SHA256, headerWithDeclaredLength(
                                PackagePin.MAX_PACKAGE_SIZE_BYTES + 1 - 27)),
                "package hard cap is enforced");
        throwsIllegalArgument(
                () -> new PackagePin(35, VALID_SHA256.toLowerCase(), VALID_HEADER),
                "runtime SHA pin must already be canonical uppercase");
        throwsIllegalArgument(
                () -> new PackagePin(35, VALID_SHA256.substring(2), VALID_HEADER),
                "runtime SHA pin must be exactly 64 hex digits");
        throwsIllegalArgument(
                () -> new PackagePin(35, VALID_SHA256.substring(0, 63) + "G", VALID_HEADER),
                "runtime SHA pin cannot contain non-hex digits");
        throwsIllegalArgument(
                () -> new PackagePin(35, VALID_SHA256, Arrays.copyOf(VALID_HEADER, 26)),
                "header pin must be exactly 27 bytes");
        throwsIllegalArgument(
                () -> new PackagePin(35, VALID_SHA256, new byte[27]),
                "header declared length must equal package size minus header");
    }

    private static void testValidatorRejectsSizeHashAndHeaderMismatch() throws IOException {
        Path directory = Files.createTempDirectory("e87-invalid-package-");
        try {
            Path packagePath = directory.resolve("update.bin");

            Files.write(packagePath, Arrays.copyOf(VALID_PACKAGE, VALID_PACKAGE.length + 1));
            throwsIllegalArgument(
                    () -> PinnedPackageValidator.validate(packagePath.toFile(), validPin()),
                    "wrong file size fails before parsing");

            byte[] changedPayload = VALID_PACKAGE.clone();
            changedPayload[changedPayload.length - 1] ^= 0x01;
            Files.write(packagePath, changedPayload);
            throwsIllegalArgument(
                    () -> PinnedPackageValidator.validate(packagePath.toFile(), validPin()),
                    "wrong digest is rejected");

            byte[] changedHeader = VALID_PACKAGE.clone();
            changedHeader[3] ^= 0x01;
            Files.write(packagePath, changedHeader);
            PackagePin matchingDigestWrongHeader =
                    new PackagePin(changedHeader.length, sha256(changedHeader), VALID_HEADER);
            throwsIllegalArgument(
                    () -> PinnedPackageValidator.validate(
                            packagePath.toFile(), matchingDigestWrongHeader),
                    "exact 27-byte header mismatch is rejected even with matching digest");
        } finally {
            deleteTree(directory);
        }
    }

    private static void testValidatorRejectsMissingDirectoryAndSymlinkInputs()
            throws IOException {
        Path directory = Files.createTempDirectory("e87-path-policy-");
        try {
            Path missing = directory.resolve("missing.bin");
            throwsIllegalArgument(
                    () -> PinnedPackageValidator.validate(missing.toFile(), validPin()),
                    "missing input is rejected");
            throwsIllegalArgument(
                    () -> PinnedPackageValidator.validate(directory.toFile(), validPin()),
                    "directory input is rejected");

            Path real = directory.resolve("real.bin");
            Path link = directory.resolve("link.bin");
            Files.write(real, VALID_PACKAGE);
            try {
                Files.createSymbolicLink(link, real.getFileName());
                throwsIllegalArgument(
                        () -> PinnedPackageValidator.validate(link.toFile(), validPin()),
                        "symbolic-link input is rejected");
            } catch (UnsupportedOperationException | SecurityException exception) {
                // The production check is still exercised on platforms supporting symlinks.
            }
        } finally {
            deleteTree(directory);
        }
    }

    private static PackagePin validPin() {
        return new PackagePin(VALID_PACKAGE.length, VALID_SHA256, VALID_HEADER);
    }

    private static byte[] headerWithDeclaredLength(int payloadLength) {
        byte[] header = VALID_HEADER.clone();
        header[13] = (byte) payloadLength;
        header[14] = (byte) (payloadLength >>> 8);
        header[15] = (byte) (payloadLength >>> 16);
        header[16] = (byte) (payloadLength >>> 24);
        return header;
    }

    private static String sha256(byte[] bytes) {
        try {
            return Hex.encode(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException impossible) {
            throw new AssertionError(impossible);
        }
    }

    private static byte[] concat(byte[] first, byte[] second) {
        byte[] out = Arrays.copyOf(first, first.length + second.length);
        System.arraycopy(second, 0, out, first.length, second.length);
        return out;
    }

    private static void deleteTree(Path root) throws IOException {
        if (!Files.exists(root)) return;
        try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
            paths.sorted(java.util.Comparator.reverseOrder())
                    .map(Path::toFile)
                    .forEach(File::delete);
        }
    }

    private static void equal(Object expected, Object actual, String message) {
        if (!expected.equals(actual)) {
            throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
        }
    }

    private static void bytes(byte[] expected, byte[] actual, String message) {
        if (!Arrays.equals(expected, actual)) {
            throw new AssertionError(message + ": expected=" + Hex.encode(expected)
                    + " actual=" + Hex.encode(actual));
        }
    }

    private static void throwsIllegalArgument(ThrowingRunnable action, String message) {
        try {
            action.run();
        } catch (IllegalArgumentException expected) {
            return;
        } catch (Exception unexpected) {
            throw new AssertionError(message + ": wrong exception", unexpected);
        }
        throw new AssertionError(message + ": expected IllegalArgumentException");
    }

    private interface ThrowingRunnable {
        void run() throws Exception;
    }

    private static final class FakeHost implements UploadStartCoordinator.Host {
        boolean packageValid;
        boolean permissionsGranted;
        int validationCalls;
        int permissionCalls;
        int scanCalls;

        @Override
        public boolean validatePinnedPackage() {
            validationCalls++;
            return packageValid;
        }

        @Override
        public boolean bluetoothPermissionsGranted() {
            return permissionsGranted;
        }

        @Override
        public void requestBluetoothPermissions() {
            permissionCalls++;
        }

        @Override
        public void startExactAddressScan() {
            scanCalls++;
        }

        int totalCalls() {
            return validationCalls + permissionCalls + scanCalls;
        }
    }
}
