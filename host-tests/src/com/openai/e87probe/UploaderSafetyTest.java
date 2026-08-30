package com.openai.e87probe;

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
        testPermissionCannotBeRequestedByStart();
        testExistingPermissionStartsScanImmediatelyAfterValidation();
        testPickerStateSafety();
        testFreshTransferRejectsEveryNonzeroC1Offset();
        testC5DispositionRequiresCompletedFinalWriteOrFullC3();
        testValidPinnedPackageReturnsDefensiveHeaderAndPayload();
        testPinRejectsUnsafeOrNoncanonicalConstantsBeforeAllocation();
        testValidatorRejectsSizeHashAndHeaderMismatch();
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
        equal(0, host.scanCalls, "invalid package cannot scan");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED, coordinator.start(),
                "failed destructive attempt is still one-shot");
        equal(1, host.validationCalls, "consumed Start cannot validate again");
    }

    private static void testPermissionCannotBeRequestedByStart() {
        FakeHost host = new FakeHost();
        host.packageValid = true;
        host.permissionsGranted = false;
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);
        coordinator.setReceiveModeConfirmed(true);

        equal(UploadStartCoordinator.Result.PERMISSION_DENIED, coordinator.start(),
                "Start cannot request picker permission");
        equal(1, host.freezeCalls, "exact address freezes before package access");
        equal(1, host.validationCalls, "package validation ran once");
        equal(0, host.scanCalls, "upload scan cannot start without picker permission");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED, coordinator.start(),
                "permission loss still consumes the attempt");
    }

    private static void testExistingPermissionStartsScanImmediatelyAfterValidation() {
        FakeHost host = new FakeHost();
        host.packageValid = true;
        host.permissionsGranted = true;
        UploadStartCoordinator coordinator = new UploadStartCoordinator(host);
        coordinator.setReceiveModeConfirmed(true);

        equal(UploadStartCoordinator.Result.SCAN_STARTED, coordinator.start(),
                "pre-granted permission starts exact scan after validation");
        equal("AA:BB:CC:DD:EE:FF", host.frozenAddress, "exact selected address was frozen");
        equal(1, host.validationCalls, "package validated before scan");
        equal(1, host.scanCalls, "scan starts once");
        equal(UploadStartCoordinator.Result.ALREADY_CONSUMED, coordinator.start(),
                "successful Start is one-shot");
        equal(1, host.scanCalls, "second click cannot rescan");
    }

    private static void testPickerStateSafety() {
        BlePickerState picker = new BlePickerState(2);
        equal(false, picker.isStartEnabled(), "inert launch has no selection");
        long first = picker.beginScan();
        equal(false, picker.addCandidate(first, "bad", "E87", -50,
                BlePickerState.ServiceStatus.UNKNOWN), "invalid address rejected");
        equal(true, picker.addCandidate(first, "aa:bb:cc:dd:ee:01", "E87 A", -60,
                BlePickerState.ServiceStatus.ADVERTISED), "first candidate accepted");
        equal(true, picker.addCandidate(first, "AA:BB:CC:DD:EE:01", "E87 A", -40,
                BlePickerState.ServiceStatus.NOT_ADVERTISED), "duplicate updates exact MAC");
        equal(1, picker.candidates().size(), "duplicates do not consume capacity");
        picker.addCandidate(first, "AA:BB:CC:DD:EE:02", "E87 B", -55,
                BlePickerState.ServiceStatus.UNKNOWN);
        equal(false, picker.addCandidate(first, "AA:BB:CC:DD:EE:03", "E87 C", -45,
                BlePickerState.ServiceStatus.UNKNOWN), "overflow rejected");
        equal(true, picker.select(first, "AA:BB:CC:DD:EE:01"), "listed address selected");
        picker.setConfirmed(true);
        equal(true, picker.isStartEnabled(), "selection and confirmation enable Start");
        equal(true, picker.select(first, "AA:BB:CC:DD:EE:02"), "selection can change");
        equal(false, picker.isStartEnabled(), "selection change clears confirmation");
        long second = picker.beginScan();
        equal(false, picker.select(first, "AA:BB:CC:DD:EE:02"), "stale selection rejected");
        equal(false, picker.addCandidate(first, "AA:BB:CC:DD:EE:04", "E87", -30,
                BlePickerState.ServiceStatus.UNKNOWN), "stale result rejected");
        picker.addCandidate(second, "AA:BB:CC:DD:EE:05", "E87", -30,
                BlePickerState.ServiceStatus.ADVERTISED);
        picker.select(second, "AA:BB:CC:DD:EE:05");
        picker.setConfirmed(true);
        equal("AA:BB:CC:DD:EE:05", picker.consumeAndFreeze(), "exact address freezes");
        equal("AA:BB:CC:DD:EE:05", picker.frozenAddress(), "frozen address is retained");
        equal(false, picker.select(second, "AA:BB:CC:DD:EE:01"), "consumed picker has no fallback");
        equal(null, picker.consumeAndFreeze(), "consumed picker cannot return another target");
    }

    private static void testFreshTransferRejectsEveryNonzeroC1Offset() {
        FirmwareTransferSafety.requireFreshC1Offset(0);
        throwsIllegalArgument(
                () -> FirmwareTransferSafety.requireFreshC1Offset(-1),
                "negative C1 resume offset is rejected");
        throwsIllegalArgument(
                () -> FirmwareTransferSafety.requireFreshC1Offset(1),
                "partial C1 resume offset is rejected");
        throwsIllegalArgument(
                () -> FirmwareTransferSafety.requireFreshC1Offset(8),
                "fully staged C1 offset is rejected without package identity proof");
    }

    private static void testC5DispositionRequiresCompletedFinalWriteOrFullC3() {
        equal(FirmwareTransferSafety.C5Disposition.REJECT,
                FirmwareTransferSafety.c5Disposition(
                        false, false, false, 0, VALID_PAYLOAD.length),
                "C5 before accepted C1 is rejected");
        equal(FirmwareTransferSafety.C5Disposition.REJECT,
                FirmwareTransferSafety.c5Disposition(
                        true, false, false, 0, VALID_PAYLOAD.length),
                "C5 without a final block is rejected");
        equal(FirmwareTransferSafety.C5Disposition.DEFER,
                FirmwareTransferSafety.c5Disposition(
                        true, true, false, 0, VALID_PAYLOAD.length),
                "C5 during final fragmented write is deferred");
        equal(FirmwareTransferSafety.C5Disposition.ACCEPT,
                FirmwareTransferSafety.c5Disposition(
                        true, true, true, 0, VALID_PAYLOAD.length),
                "C5 after every final C2 callback is accepted");
        equal(FirmwareTransferSafety.C5Disposition.DEFER,
                FirmwareTransferSafety.c5Disposition(
                        true, true, false, VALID_PAYLOAD.length, VALID_PAYLOAD.length),
                "full C3 cannot bypass an incomplete final C2 write callback");
        equal(FirmwareTransferSafety.C5Disposition.ACCEPT,
                FirmwareTransferSafety.c5Disposition(
                        true, true, true, VALID_PAYLOAD.length, VALID_PAYLOAD.length),
                "C5 after full C3 and every final C2 callback is accepted");
        equal(FirmwareTransferSafety.C5Disposition.REJECT,
                FirmwareTransferSafety.c5Disposition(
                        true, true, true, VALID_PAYLOAD.length + 1, VALID_PAYLOAD.length),
                "out-of-range acknowledgement cannot accept C5");
    }

    private static void testValidPinnedPackageReturnsDefensiveHeaderAndPayload() {
        PackagePin pin = validPin();
        byte[] mutableSnapshot = VALID_PACKAGE.clone();
        PinnedPackageValidator.ValidatedPackage validated =
                PinnedPackageValidator.validate(mutableSnapshot, pin);

        mutableSnapshot[0] ^= 0x7F;
        mutableSnapshot[mutableSnapshot.length - 1] ^= 0x7F;
        bytes(VALID_HEADER, validated.header(), "validated header is exact and immutable");
        bytes(VALID_PAYLOAD, validated.payload(), "validated payload is exact and immutable");
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

    private static void testValidatorRejectsSizeHashAndHeaderMismatch() {
        throwsIllegalArgument(
                () -> PinnedPackageValidator.validate(
                        Arrays.copyOf(VALID_PACKAGE, VALID_PACKAGE.length + 1), validPin()),
                "wrong snapshot size fails before parsing");

        byte[] changedPayload = VALID_PACKAGE.clone();
        changedPayload[changedPayload.length - 1] ^= 0x01;
        throwsIllegalArgument(
                () -> PinnedPackageValidator.validate(changedPayload, validPin()),
                "wrong digest is rejected");

        byte[] changedHeader = VALID_PACKAGE.clone();
        changedHeader[3] ^= 0x01;
        PackagePin matchingDigestWrongHeader =
                new PackagePin(changedHeader.length, sha256(changedHeader), VALID_HEADER);
        throwsIllegalArgument(
                () -> PinnedPackageValidator.validate(
                        changedHeader, matchingDigestWrongHeader),
                "exact 27-byte header mismatch is rejected even with matching digest");
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

    private static void equal(Object expected, Object actual, String message) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
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
        int freezeCalls;
        int validationCalls;
        int scanCalls;
        String frozenAddress;

        @Override
        public String freezeSelectedAddress() {
            freezeCalls++;
            frozenAddress = "AA:BB:CC:DD:EE:FF";
            return frozenAddress;
        }

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
        public void startExactAddressScan() {
            scanCalls++;
        }

        int totalCalls() {
            return freezeCalls + validationCalls + scanCalls;
        }
    }
}
