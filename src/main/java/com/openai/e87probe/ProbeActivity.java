package com.openai.e87probe;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.text.format.DateFormat;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

public final class ProbeActivity extends Activity
        implements UploadStartCoordinator.Host {
    private static final String TAG = "E87Probe";
    private static final String DEFAULT_MAC = "46:83:00:01:8A:E9";
    private static final int CONNECT_PERMISSION_REQUEST = 87;
    private static final long SETUP_TIMEOUT_MS = 10_000L;
    private static final long SCAN_DURATION_MS = 300_000L;
    private static final long UPDATE_RESPONSE_TIMEOUT_MS = 60_000L;
    private static final long FINAL_RESULT_TIMEOUT_MS = 60_000L;
    private static final int REQUESTED_MTU = 512;
    private static final UUID CCCD = uuid16(0x2902);

    private final Handler main = new Handler(Looper.getMainLooper());
    private final QixFrameAssembler fd01Assembler = new QixFrameAssembler();
    private final QixFrameAssembler fd03Assembler = new QixFrameAssembler();
    private String waitingFor = "startup";
    private String targetMac;
    private boolean scanning;
    private boolean bindSent;
    private boolean bindSucceeded;
    private boolean bindAckOutstanding;
    private boolean updateHeaderSent;
    private boolean updateRequestAccepted;
    private boolean updateCompleted;
    private boolean requestSent;
    private boolean terminal;
    private int connectionAttempts;
    private int packetNumber;
    private int fd01Packets;
    private int fd03Packets;
    private int negotiatedMtu = 23;
    private int nextSerial;
    private int updateSerial = 1;
    private int updateWindow;
    private int pendingBlockOffset = -1;
    private int pendingBlockLength;
    private int acknowledgedOffset;
    private int blocksSent;
    private int blocksAcknowledged;
    private long fd01Bytes;
    private long fd03Bytes;
    private UUID pendingSubscription;
    private byte[] updateData;
    private byte[] fd02TxFrame;
    private int fd02TxPosition;
    private int fd02TxFragment;
    private int fd02TxLastLength;
    private String fd02TxPurpose;
    private boolean pendingBlockIsFinal;
    private boolean finalC2Started;
    private boolean finalC2WriteCompleted;
    private byte[] deferredC5Frame;
    private String deferredC5Channel;
    private String observedFirmwareVersion;
    private long updateStartedAt;
    private final PackagePin packagePin = GeneratedPackagePin.create();
    private PinnedPackageValidator.ValidatedPackage validatedPackage;
    private UploadStartCoordinator startCoordinator;

    private final Runnable setupTimeout = () -> fail("Timed out waiting for " + waitingFor);
    private final Runnable scanTimeout = () -> {
        if (!scanning) return;
        stopScan();
        fail("No exact-address target advertisement appeared during the five-minute scan");
    };
    private final Runnable updateTimeout = () -> fail("Timed out waiting for " + waitingFor
            + "; acknowledgedOffset=" + acknowledgedOffset
            + " pendingOffset=" + pendingBlockOffset
            + " pendingLength=" + pendingBlockLength);

    private TextView output;
    private CheckBox receiveModeConfirmation;
    private Button startButton;
    private File outputDirectory;
    private File logFile;
    private BluetoothGatt gatt;
    private BluetoothLeScanner scanner;
    private BluetoothDevice targetDevice;
    private BluetoothGattCharacteristic fd01;
    private BluetoothGattCharacteristic fd02;
    private BluetoothGattCharacteristic fd03;
    private byte[] bindFrame;
    private byte[] updateStartFrame;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String requestedMac = getIntent().getStringExtra("mac");
        if (requestedMac == null || requestedMac.trim().isEmpty()) requestedMac = DEFAULT_MAC;
        targetMac = requestedMac.trim().toUpperCase(Locale.ROOT);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(24, 24, 24, 24);

        TextView title = new TextView(this);
        title.setText("E87 ONE-SHOT LAB UPLOADER");
        title.setTextSize(22);
        content.addView(title);

        TextView target = new TextView(this);
        target.setText("TARGET DEVICE - EXACT MAC ONLY\n\n" + targetMac);
        target.setTextSize(18);
        target.setPadding(0, 24, 0, 24);
        content.addView(target);

        TextView warning = new TextView(this);
        warning.setText("DESTRUCTIVE ONE-SHOT LAB UPLOAD\n\n"
                + "This writes the single reviewed update.bin to the exact device above. "
                + "A wrong package, wrong device, power loss, or interruption can make "
                + "the badge unusable. There is no automatic start and no retry button.");
        warning.setTextSize(17);
        content.addView(warning);

        receiveModeConfirmation = new CheckBox(this);
        receiveModeConfirmation.setText(
                "I physically placed this exact badge in hardware receive/update mode.");
        receiveModeConfirmation.setChecked(false);
        content.addView(receiveModeConfirmation);

        startButton = new Button(this);
        startButton.setText("START ONE-SHOT UPLOAD");
        startButton.setEnabled(false);
        content.addView(startButton);

        output = new TextView(this);
        output.setTextIsSelectable(true);
        output.setPadding(0, 24, 0, 24);
        content.addView(output);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(scroll);

        startCoordinator = new UploadStartCoordinator(this);
        receiveModeConfirmation.setOnCheckedChangeListener((button, isChecked) -> {
            startCoordinator.setReceiveModeConfirmed(isChecked);
            startButton.setEnabled(startCoordinator.isStartEnabled() && !terminal);
        });
        startButton.setOnClickListener(view -> {
            startButton.setEnabled(false);
            receiveModeConfirmation.setEnabled(false);
            handleStartResult(startCoordinator.start());
        });

        output.setText("IDLE - no package access, permission request, scan, connection, "
                + "or upload has started.\n"
                + "Required path: /sdcard/Android/data/com.openai.e87probe/files/update.bin\n"
                + "Pinned size: " + packagePin.size() + "\n"
                + "Pinned SHA256: " + packagePin.sha256() + "\n");
        if (!BluetoothAdapter.checkBluetoothAddress(targetMac)) {
            terminal = true;
            startButton.setEnabled(false);
            output.append("INVALID EXACT TARGET MAC - START DISABLED\n");
            return;
        }
    }

    private void handleStartResult(UploadStartCoordinator.Result result) {
        log("Start gate result: " + result);
        if (result == UploadStartCoordinator.Result.NOT_CONFIRMED) {
            receiveModeConfirmation.setEnabled(true);
            startButton.setEnabled(startCoordinator.isStartEnabled() && !terminal);
        } else if (result == UploadStartCoordinator.Result.VALIDATION_FAILED && !terminal) {
            fail("Pinned package validation failed closed");
        } else if (result == UploadStartCoordinator.Result.PERMISSION_DENIED && !terminal) {
            fail("Bluetooth connect/scan permission denied");
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != CONNECT_PERMISSION_REQUEST) return;
        boolean granted = results.length == permissions.length && results.length > 0;
        for (int result : results) {
            if (result != PackageManager.PERMISSION_GRANTED) granted = false;
        }
        handleStartResult(startCoordinator.onPermissionResult(granted));
    }

    @Override
    public boolean validatePinnedPackage() {
        if (terminal || validatedPackage != null) return false;
        File root = getExternalFilesDir(null);
        File source = root == null ? null : new File(root, "update.bin");
        if (source == null) {
            fail("App-specific external files directory is unavailable");
            return false;
        }

        final PinnedPackageValidator.ValidatedPackage validated;
        try {
            byte[] packageBytes = AndroidFdPackageReader.readExactly(
                    source,
                    packagePin.size(),
                    PackagePin.MAX_PACKAGE_SIZE_BYTES);
            validated = PinnedPackageValidator.validate(packageBytes, packagePin);
        } catch (IOException | IllegalArgumentException error) {
            fail("Pinned update package rejected: " + error.getMessage()
                    + "; required path=" + source.getAbsolutePath());
            return false;
        }

        if (!initializeEvidenceDirectory(root)) {
            return false;
        }
        log("One-shot Start consumed for exact target " + targetMac);

        byte[] payload = validated.payload();
        String info = "path=" + source.getAbsolutePath() + "\n"
                + "size=" + packagePin.size() + "\n"
                + "sha256=" + validated.sha256() + "\n"
                + "header=" + Hex.encode(validated.header()) + "\n"
                + "payloadLength=" + payload.length + "\n";
        if (!writeArtifact("firmware-package.txt", info.getBytes(StandardCharsets.UTF_8))) {
            return false;
        }
        if (!appendJournal("{\"event\":\"package_verified\",\"size\":"
                + packagePin.size() + ",\"payloadLength\":" + payload.length
                + ",\"sha256\":\"" + validated.sha256() + "\"}")) {
            return false;
        }

        validatedPackage = validated;
        updateData = payload;
        log("Pinned package verified before Bluetooth permission request; payload="
                + updateData.length);
        return true;
    }

    private boolean initializeEvidenceDirectory(File outputRoot) {
        if (outputDirectory != null || logFile != null) {
            fail("Evidence directory was already initialized");
            return false;
        }
        String runName = "run-" + new SimpleDateFormat(
                "yyyyMMdd-HHmmss-SSS", Locale.ROOT).format(new Date())
                + "-pid" + android.os.Process.myPid()
                + "-n" + Long.toHexString(System.nanoTime());
        outputDirectory = new File(outputRoot, runName);
        if (!outputDirectory.mkdir()) {
            terminal = true;
            String message = "Unable to create evidence directory " + outputDirectory;
            Log.e(TAG, message);
            output.append(message + "\n");
            return false;
        }
        logFile = new File(outputDirectory, "probe.log");
        try (FileOutputStream stream = new FileOutputStream(logFile, false)) {
            stream.flush();
        } catch (IOException error) {
            terminal = true;
            String message = "Unable to initialize run log " + logFile;
            Log.e(TAG, message, error);
            output.append(message + ": " + error + "\n");
            return false;
        }
        log("Evidence directory: " + outputDirectory.getAbsolutePath());
        log("Sequence: exact-MAC scan -> FD00 discovery -> subscribe FD01 -> subscribe FD03"
                + " -> request MTU " + REQUESTED_MTU
                + " -> bind -> C0/C1 -> C2/C3 -> C5");
        return true;
    }

    @Override
    public boolean bluetoothPermissionsGranted() {
        return android.os.Build.VERSION.SDK_INT < 31
                || (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                == PackageManager.PERMISSION_GRANTED
                && checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)
                == PackageManager.PERMISSION_GRANTED);
    }

    @Override
    public void requestBluetoothPermissions() {
        requestPermissions(new String[] {
                        Manifest.permission.BLUETOOTH_CONNECT,
                        Manifest.permission.BLUETOOTH_SCAN},
                CONNECT_PERMISSION_REQUEST);
    }

    @Override
    public void startExactAddressScan() {
        startScan();
    }

    private void startScan() {
        if (terminal || scanning || gatt != null) return;
        if (!BluetoothAdapter.checkBluetoothAddress(targetMac)) {
            fail("Invalid MAC address: " + targetMac);
            return;
        }

        BluetoothManager manager = getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            fail("Bluetooth is unavailable or disabled");
            return;
        }
        scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) {
            fail("Bluetooth LE scanner is unavailable");
            return;
        }

        waitingFor = "target advertisement";
        scanning = true;
        main.postDelayed(scanTimeout, SCAN_DURATION_MS);
        log("Scanning only for exact target " + targetMac + " (five minutes maximum)");
        ScanSettings settings = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build();
        List<ScanFilter> filters = Arrays.asList(
                new ScanFilter.Builder().setDeviceAddress(targetMac).build());
        try {
            scanner.startScan(filters, settings, scanCallback);
        } catch (Throwable error) {
            scanning = false;
            main.removeCallbacks(scanTimeout);
            fail("BLE scan did not start: " + error);
        }
    }

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            main.post(() -> handleScanResult(result));
        }

        @Override
        public void onScanFailed(int errorCode) {
            main.post(() -> {
                stopScan();
                fail("BLE scan failed with error=" + errorCode);
            });
        }
    };

    private void handleScanResult(ScanResult result) {
        if (terminal || !scanning || result == null || result.getDevice() == null) return;
        BluetoothDevice device = result.getDevice();
        String address = device.getAddress();
        if (!ProbeSequence.matchesAdvertisement(targetMac, address)) return;

        String name = null;
        if (result.getScanRecord() != null) name = result.getScanRecord().getDeviceName();
        log("Exact-target advertisement address=" + address + " name=" + name
                + " rssi=" + result.getRssi());
        stopScan();
        connect(device);
    }

    private void stopScan() {
        main.removeCallbacks(scanTimeout);
        if (!scanning) return;
        scanning = false;
        BluetoothLeScanner stopping = scanner;
        scanner = null;
        if (stopping == null) return;
        try {
            stopping.stopScan(scanCallback);
        } catch (Throwable error) {
            log("stopScan error: " + error);
        }
    }

    private void connect(BluetoothDevice device) {
        if (terminal || gatt != null || device == null) return;
        targetDevice = device;
        connectionAttempts++;
        waitingFor = "GATT connection";
        log("Connecting to " + device.getAddress() + " (attempt "
                + connectionAttempts + " of 2 maximum)");
        armSetupTimeout();
        gatt = device.connectGatt(this, false, callback, BluetoothDevice.TRANSPORT_LE);
        if (gatt == null) fail("connectGatt returned null");
    }

    private final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt callbackGatt, int status, int newState) {
            main.post(() -> handleConnectionState(callbackGatt, status, newState));
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt callbackGatt, int status) {
            main.post(() -> handleServicesDiscovered(callbackGatt, status));
        }

        @Override
        public void onDescriptorWrite(BluetoothGatt callbackGatt,
                                      BluetoothGattDescriptor descriptor, int status) {
            UUID characteristicUuid = descriptor.getCharacteristic() == null
                    ? null : descriptor.getCharacteristic().getUuid();
            main.post(() -> handleDescriptorWrite(
                    callbackGatt, descriptor.getUuid(), characteristicUuid, status));
        }

        @Override
        public void onMtuChanged(BluetoothGatt callbackGatt, int mtu, int status) {
            main.post(() -> handleMtuChanged(callbackGatt, mtu, status));
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt callbackGatt,
                                          BluetoothGattCharacteristic characteristic,
                                          int status) {
            main.post(() -> handleCharacteristicWrite(
                    callbackGatt, characteristic.getUuid(), status));
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt callbackGatt,
                                            BluetoothGattCharacteristic characteristic) {
            byte[] value = characteristic.getValue();
            byte[] copy = value == null ? new byte[0] : value.clone();
            main.post(() -> handleNotification(callbackGatt, characteristic.getUuid(), copy));
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt callbackGatt,
                                            BluetoothGattCharacteristic characteristic,
                                            byte[] value) {
            byte[] copy = value == null ? new byte[0] : value.clone();
            main.post(() -> handleNotification(callbackGatt, characteristic.getUuid(), copy));
        }
    };

    private void handleConnectionState(BluetoothGatt callbackGatt, int status, int newState) {
        log("GATT state status=" + status + " newState=" + newState);
        if (terminal || callbackGatt != gatt) return;
        if (status == BluetoothGatt.GATT_SUCCESS && newState == BluetoothProfile.STATE_CONNECTED) {
            waitingFor = "FD00 service discovery";
            armSetupTimeout();
            if (!gatt.discoverServices()) fail("discoverServices did not start");
            return;
        }
        if (newState != BluetoothProfile.STATE_DISCONNECTED) return;

        if (!requestSent && status == 62 && connectionAttempts < 2) {
            main.removeCallbacks(setupTimeout);
            gatt = null;
            callbackGatt.close();
            fd01 = null;
            fd02 = null;
            fd03 = null;
            pendingSubscription = null;
            log("Pre-request GATT status=62; retrying once after 2 seconds");
            main.postDelayed(() -> connect(targetDevice), 2_000L);
        } else if (requestSent) {
            fail("Badge disconnected during firmware update; status=" + status
                    + " acknowledgedOffset=" + acknowledgedOffset
                    + " pendingOffset=" + pendingBlockOffset
                    + " pendingLength=" + pendingBlockLength);
        } else {
            fail("Disconnected before request; GATT status=" + status);
        }
    }

    private void handleServicesDiscovered(BluetoothGatt callbackGatt, int status) {
        if (terminal || callbackGatt != gatt) return;
        log("Services discovered status=" + status);
        if (status != BluetoothGatt.GATT_SUCCESS) {
            fail("Service discovery failed: " + status);
            return;
        }

        StringBuilder layout = new StringBuilder();
        List<BluetoothGattService> services = gatt.getServices();
        for (BluetoothGattService service : services) {
            layout.append("service ").append(service.getUuid()).append('\n');
            for (BluetoothGattCharacteristic characteristic : service.getCharacteristics()) {
                layout.append("  characteristic ").append(characteristic.getUuid())
                        .append(" properties=0x")
                        .append(String.format(Locale.ROOT, "%02X",
                                characteristic.getProperties()))
                        .append('\n');
            }
        }
        log("Discovered GATT layout:\n" + layout.toString().trim());
        if (!writeArtifact("gatt-layout.txt",
                layout.toString().getBytes(StandardCharsets.UTF_8))) return;

        BluetoothGattService factory = gatt.getService(QixFactoryMemoryRead.SERVICE);
        if (factory == null) {
            fail("Qix factory service " + QixFactoryMemoryRead.SERVICE + " not found");
            return;
        }
        fd01 = factory.getCharacteristic(QixFactoryMemoryRead.FD01);
        fd02 = factory.getCharacteristic(QixFactoryMemoryRead.FD02);
        fd03 = factory.getCharacteristic(QixFactoryMemoryRead.FD03);
        if (fd01 == null || fd02 == null || fd03 == null) {
            fail("FD01, FD02, or FD03 characteristic not found under the Qix factory service");
            return;
        }
        subscribe(fd01);
    }

    private void subscribe(BluetoothGattCharacteristic characteristic) {
        int properties = characteristic.getProperties();
        byte[] cccdValue;
        if ((properties & BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
                || (properties & BluetoothGattCharacteristic.PROPERTY_INDICATE) != 0) {
            // Match the vendor SDK exactly. It writes 0x0002 even though these
            // characteristics advertise PROPERTY_NOTIFY rather than INDICATE.
            cccdValue = BluetoothGattDescriptor.ENABLE_INDICATION_VALUE;
        } else {
            fail(characteristic.getUuid() + " has neither notify nor indicate");
            return;
        }
        BluetoothGattDescriptor cccd = characteristic.getDescriptor(CCCD);
        if (cccd == null) {
            fail(characteristic.getUuid() + " has no CCCD");
            return;
        }
        if (!gatt.setCharacteristicNotification(characteristic, true)) {
            fail("Local notification enable failed for " + characteristic.getUuid());
            return;
        }
        cccd.setValue(cccdValue);
        pendingSubscription = characteristic.getUuid();
        waitingFor = pendingSubscription + " CCCD write";
        armSetupTimeout();
        log("Subscribing " + pendingSubscription + " with vendor CCCD="
                + Hex.encode(cccdValue));
        if (!gatt.writeDescriptor(cccd)) {
            fail("CCCD write did not start for " + pendingSubscription);
        }
    }

    private void handleDescriptorWrite(BluetoothGatt callbackGatt, UUID descriptorUuid,
                                       UUID characteristicUuid, int status) {
        if (terminal || callbackGatt != gatt || !CCCD.equals(descriptorUuid)) return;
        log("CCCD result characteristic=" + characteristicUuid + " status=" + status);
        if (pendingSubscription == null || !pendingSubscription.equals(characteristicUuid)) {
            fail("Unexpected CCCD completion for " + characteristicUuid
                    + "; expected " + pendingSubscription);
            return;
        }
        if (status != BluetoothGatt.GATT_SUCCESS) {
            fail("CCCD write failed for " + characteristicUuid + ": " + status);
            return;
        }
        pendingSubscription = null;
        if (QixFactoryMemoryRead.FD01.equals(characteristicUuid)) {
            subscribe(fd03);
        } else if (QixFactoryMemoryRead.FD03.equals(characteristicUuid)) {
            waitingFor = "MTU " + REQUESTED_MTU + " negotiation";
            armSetupTimeout();
            log("Requesting stock-SDK MTU " + REQUESTED_MTU);
            if (!gatt.requestMtu(REQUESTED_MTU)) {
                fail("MTU request did not start");
            }
        }
    }

    private void handleMtuChanged(BluetoothGatt callbackGatt, int mtu, int status) {
        if (terminal || callbackGatt != gatt) return;
        negotiatedMtu = mtu;
        log("MTU changed mtu=" + mtu + " status=" + status);
        if (status != BluetoothGatt.GATT_SUCCESS || mtu < 22) {
            fail("MTU negotiation failed or returned an unusable value; mtu="
                    + mtu + " status=" + status);
            return;
        }
        main.removeCallbacks(setupTimeout);
        main.postDelayed(this::sendBindRequest, 100L);
    }

    private void sendBindRequest() {
        if (terminal || bindSent || gatt == null || fd02 == null) return;
        int language = Locale.getDefault().getLanguage().equals("zh") ? 0 : 1;
        int clock = DateFormat.is24HourFormat(this) ? 0 : 1;
        int settings = (clock << 2) | (language << 1);
        String fingerprint = "35"
                + (Build.BOARD.length() % 10)
                + (Build.BRAND.length() % 10)
                + (Build.CPU_ABI.length() % 10)
                + (Build.DEVICE.length() % 10)
                + (Build.DISPLAY.length() % 10)
                + (Build.HOST.length() % 10)
                + (Build.ID.length() % 10)
                + (Build.MANUFACTURER.length() % 10)
                + (Build.MODEL.length() % 10)
                + (Build.PRODUCT.length() % 10)
                + (Build.TAGS.length() % 10)
                + (Build.TYPE.length() % 10)
                + (Build.USER.length() % 10);
        int hostId = fingerprint.hashCode();
        bindFrame = QixFactoryMemoryRead.bindRequest(settings, hostId);
        if (!writeArtifact("qix-bind-request.bin", bindFrame)) return;
        fd02.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        fd02.setValue(bindFrame);
        log("TX FD02 bind settings=0x" + String.format(Locale.ROOT, "%02X", settings)
                + " hostId=" + hostId + " " + Hex.encode(bindFrame));
        if (!gatt.writeCharacteristic(fd02)) {
            fail("FD02 bind write did not start");
            return;
        }
        bindSent = true;
        nextSerial = 1;
        waitingFor = "Qix opcode 61 bind response";
        armSetupTimeout();
    }

    private void handleCharacteristicWrite(BluetoothGatt callbackGatt,
                                           UUID characteristicUuid, int status) {
        if (terminal || callbackGatt != gatt) return;
        if (QixFactoryMemoryRead.FD02.equals(characteristicUuid)
                && fd02TxFrame != null) {
            handleFd02TransferWrite(status);
            return;
        }
        log("Characteristic write result characteristic=" + characteristicUuid
                + " status=" + status);
        if (QixFactoryMemoryRead.FD02.equals(characteristicUuid)
                && bindAckOutstanding) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                fail("FD02 bind-response ACK write failed: " + status);
                return;
            }
            bindAckOutstanding = false;
            main.postDelayed(this::sendUpdateHeaderProbe, 100L);
            return;
        }
        if (status != BluetoothGatt.GATT_SUCCESS) {
            fail("Unexpected characteristic write failure on " + characteristicUuid
                    + ": " + status);
        }
    }

    private void sendUpdateHeaderProbe() {
        if (terminal || updateHeaderSent || gatt == null || fd02 == null) return;
        if (validatedPackage == null || updateData == null) {
            fail("Pinned package was not validated before C0");
            return;
        }
        byte[] validatedHeader = validatedPackage.header();
        updateStartFrame = QixFirmwareUpdateProbe.start(validatedHeader);
        if (!writeArtifact("qix-c0-update-header-request.bin", updateStartFrame)) return;
        log("TX FD02 C0 update header " + Hex.encode(updateStartFrame));
        updateHeaderSent = true;
        requestSent = true;
        updateStartedAt = System.currentTimeMillis();
        beginFd02Frame(updateStartFrame, "C0");
    }

    private void beginFd02Frame(byte[] frame, String purpose) {
        if (terminal) return;
        if (fd02TxFrame != null) {
            fail("Tried to start " + purpose + " while " + fd02TxPurpose + " is in flight");
            return;
        }
        fd02TxFrame = frame;
        fd02TxPosition = 0;
        fd02TxFragment = 0;
        fd02TxPurpose = purpose;
        appendArtifact("tx-qix-frames.bin", frame);
        writeNextFd02Fragment();
    }

    private void writeNextFd02Fragment() {
        if (terminal || fd02TxFrame == null || gatt == null || fd02 == null) return;
        int fragmentSize = Math.max(20, negotiatedMtu - 6);
        int count = Math.min(fragmentSize, fd02TxFrame.length - fd02TxPosition);
        byte[] fragment = Arrays.copyOfRange(
                fd02TxFrame, fd02TxPosition, fd02TxPosition + count);
        fd02TxLastLength = count;
        waitingFor = fd02TxPurpose + " fragment " + (fd02TxFragment + 1)
                + " GATT callback";
        armSetupTimeout();
        fd02.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        fd02.setValue(fragment);
        if (!gatt.writeCharacteristic(fd02)) {
            fail("FD02 " + fd02TxPurpose + " fragment " + (fd02TxFragment + 1)
                    + " write did not start");
        }
    }

    private void handleFd02TransferWrite(int status) {
        if (status != BluetoothGatt.GATT_SUCCESS) {
            fail("FD02 " + fd02TxPurpose + " fragment " + (fd02TxFragment + 1)
                    + " failed status=" + status);
            return;
        }
        main.removeCallbacks(setupTimeout);
        fd02TxPosition += fd02TxLastLength;
        fd02TxFragment++;
        if (fd02TxPosition < fd02TxFrame.length) {
            writeNextFd02Fragment();
            return;
        }
        String completedPurpose = fd02TxPurpose;
        int fragments = fd02TxFragment;
        int bytes = fd02TxFrame.length;
        fd02TxFrame = null;
        fd02TxPurpose = null;
        log("FD02 " + completedPurpose + " logical frame written: " + bytes
                + " bytes in " + fragments + " fragment(s)");
        if (!appendJournal("{\"event\":\"frame_written\",\"purpose\":\""
                + completedPurpose + "\",\"bytes\":" + bytes
                + ",\"fragments\":" + fragments + "}")) return;
        if (completedPurpose.startsWith("C2") && pendingBlockIsFinal) {
            finalC2WriteCompleted = true;
        }
        if ("C0".equals(completedPurpose)) {
            waitingFor = "Qix C1 update response";
            armUpdateTimeout(UPDATE_RESPONSE_TIMEOUT_MS);
        } else if (completedPurpose.startsWith("C2")) {
            waitingFor = pendingBlockIsFinal ? "Qix C5 final result"
                    : "Qix C3 data response";
            armUpdateTimeout(pendingBlockIsFinal
                    ? FINAL_RESULT_TIMEOUT_MS : UPDATE_RESPONSE_TIMEOUT_MS);
        }
        processDeferredC5IfReady();
    }

    private void processDeferredC5IfReady() {
        if (terminal || deferredC5Frame == null || !finalC2WriteCompleted) return;
        byte[] frame = deferredC5Frame;
        String channel = deferredC5Channel;
        deferredC5Frame = null;
        deferredC5Channel = null;
        log("Processing deferred C5 after every final C2 fragment write completed");
        handleUpdateResult(channel, frame);
    }

    private void handleNotification(BluetoothGatt callbackGatt,
                                    UUID characteristicUuid, byte[] value) {
        if (terminal || callbackGatt != gatt) return;
        String channel = QixFactoryMemoryRead.channelName(characteristicUuid);
        if (channel == null) {
            log("Ignoring notification from unrequested characteristic "
                    + characteristicUuid + " " + Hex.encode(value));
            return;
        }

        packetNumber++;
        if ("fd01".equals(channel)) {
            fd01Packets++;
            fd01Bytes += value.length;
        } else {
            fd03Packets++;
            fd03Bytes += value.length;
        }
        log("RX " + channel.toUpperCase(Locale.ROOT) + " packet=" + packetNumber
                + " bytes=" + value.length + " " + Hex.encode(value));
        String packetName = String.format(Locale.ROOT,
                "rx-%06d-%s.bin", packetNumber, channel);
        if (!writeArtifact(packetName, value)) return;
        appendArtifact(channel + "-notifications.bin", value);
        QixFrameAssembler assembler = "fd01".equals(channel)
                ? fd01Assembler : fd03Assembler;
        byte[] completeFrame = assembler.append(value);
        if (completeFrame == null) return;
        if (completeFrame.length != value.length) {
            String frameName = String.format(Locale.ROOT,
                    "frame-%06d-%s.bin", packetNumber, channel);
            if (!writeArtifact(frameName, completeFrame)) return;
            log("Reassembled " + channel.toUpperCase(Locale.ROOT) + " frame bytes="
                    + completeFrame.length + " " + Hex.encode(completeFrame));
        }
        if (!bindSucceeded && QixFactoryMemoryRead.isSuccessfulBindResponse(completeFrame)) {
            bindSucceeded = true;
            main.removeCallbacks(setupTimeout);
            try {
                observedFirmwareVersion =
                        QixFactoryMemoryRead.bindFirmwareVersion(completeFrame);
            } catch (IllegalArgumentException error) {
                fail("Successful bind response did not contain a valid firmware version: "
                        + error.getMessage());
                return;
            }
            if (!writeArtifact("bind-firmware-version.txt",
                    (observedFirmwareVersion + "\n").getBytes(StandardCharsets.UTF_8))) return;
            log("Qix bind succeeded; reported firmware=" + observedFirmwareVersion);
            if (QixFactoryMemoryRead.requestsResponse(completeFrame)) {
                byte[] response = QixFactoryMemoryRead.successResponse(0x61, nextSerial);
                nextSerial = (nextSerial + 1) & 15;
                if (!writeArtifact("qix-bind-response-ack.bin", response)) return;
                fd02.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                fd02.setValue(response);
                bindAckOutstanding = true;
                log("TX FD02 bind-response ACK " + Hex.encode(response));
                if (!gatt.writeCharacteristic(fd02)) {
                    bindAckOutstanding = false;
                    fail("FD02 bind-response ACK write did not start");
                }
            } else {
                main.postDelayed(this::sendUpdateHeaderProbe, 100L);
            }
        }
        if (updateHeaderSent) handleUpdateFrame(channel, completeFrame);
    }

    private void handleUpdateFrame(String channel, byte[] frame) {
        if (frame.length < 4) return;
        int opcode = frame[3] & 0xFF;
        try {
            if (opcode == 0xC1) {
                handleUpdateRequest(channel, frame);
            } else if (opcode == 0xC3) {
                handleDataResponse(channel, frame);
            } else if (opcode == 0xC5) {
                handleUpdateResult(channel, frame);
            }
        } catch (IllegalArgumentException error) {
            fail("Rejected malformed Qix " + String.format(Locale.ROOT, "%02X", opcode)
                    + " frame on " + channel + ": " + error.getMessage()
                    + " bytes=" + Hex.encode(frame));
        }
    }

    private void handleUpdateRequest(String channel, byte[] frame) {
        QixFirmwareUpdateProbe.UpdateRequest update =
                QixFirmwareUpdateProbe.parseUpdateRequest(frame);
        if (updateRequestAccepted) {
            fail("Received duplicate C1 after update transfer began");
            return;
        }
        main.removeCallbacks(updateTimeout);
        String result = "channel=" + channel + "\n"
                + "frame=" + Hex.encode(frame) + "\n"
                + "state=" + update.state + "\n"
                + "allowedLength=" + update.allowedLength + "\n"
                + "offset=" + update.offset + "\n";
        if (!writeArtifact("qix-c1-update-response.txt",
                result.getBytes(StandardCharsets.UTF_8))) return;
        log("C1 update response state=" + update.state
                + " allowedLength=" + update.allowedLength
                + " offset=" + update.offset + " channel=" + channel);
        if (update.state != 1) {
            fail("Badge rejected update header with C1 state=" + update.state);
            return;
        }
        if (update.allowedLength <= 0 || update.allowedLength > 65_527) {
            fail("Badge returned invalid C1 update window=" + update.allowedLength);
            return;
        }
        FirmwareTransferSafety.requireFreshC1Offset(update.offset);
        updateRequestAccepted = true;
        updateWindow = update.allowedLength;
        acknowledgedOffset = 0;
        if (!appendJournal("{\"event\":\"c1\",\"channel\":\"" + channel
                + "\",\"state\":" + update.state + ",\"window\":"
                + updateWindow + ",\"offset\":" + acknowledgedOffset + "}")) return;
        main.postDelayed(() -> sendDataBlockWhenIdle(0), 5L);
    }

    private void sendDataBlockWhenIdle(int offset) {
        if (terminal) return;
        if (fd02TxFrame != null) {
            main.postDelayed(() -> sendDataBlockWhenIdle(offset), 5L);
            return;
        }
        sendDataBlock(offset);
    }

    private void sendDataBlock(int offset) {
        if (terminal || !updateRequestAccepted || updateData == null) return;
        if (fd02TxFrame != null) {
            fail("Cannot start C2 while " + fd02TxPurpose + " is still in flight");
            return;
        }
        if (offset < 0 || offset >= updateData.length) {
            fail("Refusing invalid C2 offset=" + offset);
            return;
        }
        int length = Math.min(updateWindow, updateData.length - offset);
        int serial = updateSerial;
        updateSerial = (updateSerial + 1) & 15;
        byte[] frame = QixFirmwareUpdateProbe.dataBlock(updateData, offset, length, serial);
        pendingBlockOffset = offset;
        pendingBlockLength = length;
        pendingBlockIsFinal = offset + length == updateData.length;
        if (pendingBlockIsFinal) {
            finalC2Started = true;
            finalC2WriteCompleted = false;
        }
        blocksSent++;
        if (blocksSent == 1 && !writeArtifact("qix-c2-first.bin", frame)) return;
        if (pendingBlockIsFinal
                && !writeArtifact("qix-c2-last.bin", frame)) return;
        if (!appendJournal("{\"event\":\"c2_send\",\"block\":" + blocksSent
                + ",\"serial\":" + serial + ",\"offset\":" + offset
                + ",\"length\":" + length + ",\"frameLength\":" + frame.length
                + ",\"frameSha256\":\"" + sha256Hex(frame) + "\"}")) return;
        if (blocksSent == 1 || pendingBlockIsFinal || blocksSent % 32 == 0) {
            log("C2 block=" + blocksSent + " serial=" + serial + " offset=" + offset
                    + " length=" + length + " progress="
                    + String.format(Locale.ROOT, "%.1f", 100.0 * offset / updateData.length)
                    + "%");
        }
        beginFd02Frame(frame, "C2 block " + blocksSent);
    }

    private void handleDataResponse(String channel, byte[] frame) {
        QixFirmwareUpdateProbe.DataResponse response =
                QixFirmwareUpdateProbe.parseDataResponse(frame);
        if (!updateRequestAccepted || pendingBlockOffset < 0) {
            fail("Unexpected C3 without an outstanding C2 block");
            return;
        }
        main.removeCallbacks(updateTimeout);
        int expectedOffset = pendingBlockOffset + pendingBlockLength;
        if (!appendJournal("{\"event\":\"c3\",\"channel\":\"" + channel
                + "\",\"result\":" + response.result + ",\"nextOffset\":"
                + response.nextOffset + ",\"expectedOffset\":" + expectedOffset + "}")) return;
        if (response.result != 0) {
            fail("Badge rejected C2 block at offset=" + pendingBlockOffset
                    + " with C3 result=" + response.result);
            return;
        }
        if (response.nextOffset != expectedOffset) {
            fail("C3 offset mismatch: expected " + expectedOffset
                    + " got " + response.nextOffset);
            return;
        }
        blocksAcknowledged++;
        acknowledgedOffset = response.nextOffset;
        pendingBlockOffset = -1;
        pendingBlockLength = 0;
        boolean finalAcknowledged = acknowledgedOffset == updateData.length;
        if (blocksAcknowledged == 1 || finalAcknowledged
                || blocksAcknowledged % 32 == 0) {
            log("C3 acknowledged block=" + blocksAcknowledged + " nextOffset="
                    + acknowledgedOffset + "/" + updateData.length + " ("
                    + String.format(Locale.ROOT, "%.1f",
                    100.0 * acknowledgedOffset / updateData.length) + "%)");
        }
        if (finalAcknowledged) {
            waitingFor = "Qix C5 final result after final C3";
            armUpdateTimeout(FINAL_RESULT_TIMEOUT_MS);
            return;
        }
        main.postDelayed(() -> sendDataBlockWhenIdle(acknowledgedOffset), 5L);
    }

    private void handleUpdateResult(String channel, byte[] frame) {
        int result = QixFirmwareUpdateProbe.parseUpdateResult(frame);
        int payloadLength = updateData == null ? -1 : updateData.length;
        FirmwareTransferSafety.C5Disposition disposition =
                FirmwareTransferSafety.c5Disposition(
                        updateRequestAccepted,
                        finalC2Started,
                        finalC2WriteCompleted,
                        acknowledgedOffset,
                        payloadLength);
        if (disposition == FirmwareTransferSafety.C5Disposition.DEFER) {
            if (deferredC5Frame != null) {
                fail("Received duplicate C5 while the final C2 write was incomplete");
                return;
            }
            deferredC5Frame = frame.clone();
            deferredC5Channel = channel;
            log("Deferring C5 until every final C2 fragment write callback succeeds");
            return;
        }
        if (disposition == FirmwareTransferSafety.C5Disposition.REJECT) {
            fail("C5 is not permitted by the current transfer state; acknowledgedOffset="
                    + acknowledgedOffset + " payloadLength=" + payloadLength);
            return;
        }

        main.removeCallbacks(updateTimeout);
        if (!appendJournal("{\"event\":\"c5\",\"channel\":\"" + channel
                + "\",\"result\":" + result + ",\"frame\":\""
                + Hex.encode(frame) + "\"}")) return;
        if (result != 0) {
            fail("Badge reported C5 update failure result=" + result);
            return;
        }
        acknowledgedOffset = updateData.length;
        updateCompleted = true;
        completeFirmwareUpdate("C5 result zero on " + channel);
    }

    private void completeFirmwareUpdate(String reason) {
        if (terminal) return;
        main.removeCallbacks(setupTimeout);
        main.removeCallbacks(updateTimeout);
        long elapsed = Math.max(0L, System.currentTimeMillis() - updateStartedAt);
        String summary = "reason=" + reason + "\n"
                + "bindRequest=" + (bindFrame == null ? "" : Hex.encode(bindFrame)) + "\n"
                + "updateStart=" + (updateStartFrame == null ? "" : Hex.encode(updateStartFrame)) + "\n"
                + "packageSha256=" + packagePin.sha256() + "\n"
                + "payloadLength=" + (updateData == null ? 0 : updateData.length) + "\n"
                + "acknowledgedOffset=" + acknowledgedOffset + "\n"
                + "blocksSent=" + blocksSent + "\n"
                + "blocksAcknowledgedByC3=" + blocksAcknowledged + "\n"
                + "elapsedMillis=" + elapsed + "\n"
                + "bindSucceeded=" + bindSucceeded + "\n"
                + "negotiatedMtu=" + negotiatedMtu + "\n"
                + "fd01Packets=" + fd01Packets + "\n"
                + "fd01Bytes=" + fd01Bytes + "\n"
                + "fd03Packets=" + fd03Packets + "\n"
                + "fd03Bytes=" + fd03Bytes + "\n";
        if (!writeArtifact("firmware-update-summary.txt",
                summary.getBytes(StandardCharsets.UTF_8))) return;
        if (!appendJournal("{\"event\":\"complete\",\"reason\":\"" + reason
                + "\",\"acknowledgedOffset\":" + acknowledgedOffset
                + ",\"blocksSent\":" + blocksSent + ",\"elapsedMillis\":"
                + elapsed + "}")) return;
        terminal = true;
        log("SUCCESS: firmware payload accepted; " + reason + "; bytes="
                + acknowledgedOffset + "/" + updateData.length + " blocks=" + blocksSent
                + " elapsedMs=" + elapsed);
        main.postDelayed(this::closeGatt, 2_000L);
    }

    private void armSetupTimeout() {
        main.removeCallbacks(setupTimeout);
        main.postDelayed(setupTimeout, SETUP_TIMEOUT_MS);
    }

    private void armUpdateTimeout(long timeoutMillis) {
        main.removeCallbacks(updateTimeout);
        main.postDelayed(updateTimeout, timeoutMillis);
    }

    private synchronized void log(String message) {
        String timestamp = new SimpleDateFormat("HH:mm:ss.SSS", Locale.ROOT).format(new Date());
        String line = timestamp + " " + message;
        Log.i(TAG, line);
        if (output != null) output.append(line + "\n");
        if (logFile != null) {
            try (FileOutputStream stream = new FileOutputStream(logFile, true)) {
                stream.write((line + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (IOException error) {
                Log.e(TAG, "Unable to append probe log", error);
            }
        }
    }

    private boolean writeArtifact(String name, byte[] bytes) {
        File destination = new File(outputDirectory, name);
        try (FileOutputStream stream = new FileOutputStream(destination, false)) {
            stream.write(bytes);
            log("Wrote " + destination.getAbsolutePath() + " (" + bytes.length + " bytes)");
            return true;
        } catch (IOException error) {
            fail("Unable to write " + destination + ": " + error);
            return false;
        }
    }

    private boolean appendArtifact(String name, byte[] bytes) {
        File destination = new File(outputDirectory, name);
        try (FileOutputStream stream = new FileOutputStream(destination, true)) {
            stream.write(bytes);
            return true;
        } catch (IOException error) {
            fail("Unable to append " + destination + ": " + error);
            return false;
        }
    }

    private boolean appendJournal(String json) {
        return appendArtifact("transfer-journal.jsonl",
                (json + "\n").getBytes(StandardCharsets.UTF_8));
    }

    private void fail(String message) {
        if (terminal) return;
        terminal = true;
        main.removeCallbacks(setupTimeout);
        main.removeCallbacks(updateTimeout);
        log("FAIL: " + message);
        closeGatt();
    }

    private void closeGatt() {
        stopScan();
        if (gatt == null) return;
        BluetoothGatt closing = gatt;
        gatt = null;
        try {
            closing.disconnect();
        } catch (Throwable error) {
            log("disconnect error: " + error);
        }
        closing.close();
    }

    @Override
    protected void onDestroy() {
        main.removeCallbacksAndMessages(null);
        terminal = true;
        closeGatt();
        super.onDestroy();
    }

    private static UUID uuid16(int shortUuid) {
        return UUID.fromString(String.format(Locale.ROOT,
                "0000%04x-0000-1000-8000-00805f9b34fb", shortUuid));
    }

    private static String sha256Hex(byte[] bytes) {
        try {
            return Hex.encode(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 unavailable", error);
        }
    }
}
