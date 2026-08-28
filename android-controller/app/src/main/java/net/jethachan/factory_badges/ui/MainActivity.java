package net.jethachan.factory_badges.ui;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.SeekBar;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import net.jethachan.factory_badges.R;
import net.jethachan.factory_badges.ble.normal.NormalBadgeScanner;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.model.ConnectionSnapshot;
import net.jethachan.factory_badges.sync.BadgeSyncService;

public final class MainActivity extends Activity {
    private static final int REQUEST_NEARBY = 4101;
    private static final int REQUEST_NOTIFICATIONS = 4102;
    private static final String STATE_DAY = "main.day";
    private static final String STATE_WEEK = "main.week";

    private TextView mainTitle;
    private TextView selectedBadgeLabel;
    private TextView selectedBadgeValue;
    private TextView connectionLabel;
    private TextView connectionStatusValue;
    private TextView connectionDetailValue;
    private TextView syncPairGuidance;
    private TextView localWarningValue;
    private TextView notificationWarningValue;
    private TextView dayLabel;
    private TextView dayValue;
    private TextView weekLabel;
    private TextView weekValue;
    private TextView creditLabel;
    private TextView creditValue;
    private TextView lastSyncValue;
    private SeekBar daySeek;
    private SeekBar weekSeek;
    private Button chooseBadgeButton;
    private Button syncButton;
    private Button stopSyncButton;
    private Button maintenanceButton;

    private MainUiPresenter presenter;
    private Handler mainHandler;
    private NormalBadgeScanner scanner;
    private BadgeSyncService.LocalBinder currentBinder;
    private boolean listenerRegistered;
    private boolean bindReleaseOwed;
    private boolean rendering;
    private boolean notificationPromptAttempted;

    private AlertDialog candidateDialog;
    private ArrayAdapter<String> candidateAdapter;
    private List<String> candidateAddresses;
    private Map<String, BluetoothDevice> candidateDevices;

    private final MainUiPresenter.Host host = new MainUiPresenter.Host() {
        @Override public void render(MainUiPresenter.ViewState state) {
            MainActivity.this.render(state);
        }

        @Override public MainUiPresenter.CommandResult publishState(BadgeState state) {
            BadgeSyncService.LocalBinder binder = currentBinder;
            if (binder == null) return MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE;
            try {
                binder.setCurrentState(state);
                return MainUiPresenter.CommandResult.ACCEPTED;
            } catch (IllegalStateException | SecurityException failure) {
                return MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE;
            }
        }

        @Override public void requestBluetoothPermissions() {
            requestPermissions(new String[] {
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT
            }, REQUEST_NEARBY);
        }

        @Override public void beginBadgeScan() {
            openCandidateDialog();
            scanner.start();
        }

        @Override public MainUiPresenter.CommandResult startForegroundSync() {
            if (Build.VERSION.SDK_INT >= 33
                    && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                            != PackageManager.PERMISSION_GRANTED
                    && !notificationPromptAttempted) {
                notificationPromptAttempted = true;
                try {
                    requestPermissions(
                            new String[] {Manifest.permission.POST_NOTIFICATIONS},
                            REQUEST_NOTIFICATIONS);
                } catch (RuntimeException promptFailure) {
                    // Notification permission is optional and never gates sync.
                }
            }
            try {
                ComponentName started = startForegroundService(
                        BadgeSyncService.enableIntent(MainActivity.this));
                return started == null
                        ? MainUiPresenter.CommandResult.SYNC_START_FAILED
                        : MainUiPresenter.CommandResult.ACCEPTED;
            } catch (SecurityException permissionFailure) {
                return MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED;
            } catch (RuntimeException startFailure) {
                return MainUiPresenter.CommandResult.SYNC_START_FAILED;
            }
        }

        @Override public MainUiPresenter.CommandResult requestSyncNow() {
            BadgeSyncService.LocalBinder binder = currentBinder;
            if (binder == null) return MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE;
            try {
                binder.syncNow();
                return MainUiPresenter.CommandResult.ACCEPTED;
            } catch (IllegalStateException | SecurityException failure) {
                return MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE;
            }
        }

        @Override public MainUiPresenter.CommandResult requestStopSync() {
            try {
                ComponentName stopped = startService(
                        BadgeSyncService.disableIntent(MainActivity.this));
                return stopped == null
                        ? MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE
                        : MainUiPresenter.CommandResult.ACCEPTED;
            } catch (RuntimeException stopFailure) {
                return MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE;
            }
        }
    };

    private final BadgeSyncService.SnapshotListener snapshotListener =
            new BadgeSyncService.SnapshotListener() {
                @Override public void onSnapshot(ConnectionSnapshot snapshot) {
                    if (presenter != null) presenter.onSnapshot(snapshot);
                }
            };

    private final ServiceConnection serviceConnection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder service) {
            if (!(service instanceof BadgeSyncService.LocalBinder)) {
                cleanupFailedBinding();
                return;
            }
            BadgeSyncService.LocalBinder binder =
                    (BadgeSyncService.LocalBinder) service;
            currentBinder = binder;
            try {
                ConnectionSnapshot snapshot = binder.snapshot();
                presenter.onServiceBound(snapshot);
                binder.addSnapshotListener(snapshotListener);
                listenerRegistered = true;
            } catch (IllegalStateException failure) {
                cleanupFailedBinding();
            }
        }

        @Override public void onServiceDisconnected(ComponentName name) {
            cleanupFailedBinding();
        }

        @Override public void onBindingDied(ComponentName name) {
            cleanupFailedBinding();
        }

        @Override public void onNullBinding(ComponentName name) {
            cleanupFailedBinding();
        }
    };

    private final NormalBadgeScanner.Listener scannerListener =
            new NormalBadgeScanner.Listener() {
                @Override public void onStarted() {
                    refreshEnvironment();
                }

                @Override public void onCandidate(BluetoothDevice device,
                        String advertisedName, String address, boolean bonded) {
                    addCandidate(device, address, bonded);
                }

                @Override public void onFinished(boolean foundAny) {
                    refreshEnvironment();
                    AlertDialog dialog = candidateDialog;
                    Map<String, BluetoothDevice> devices = candidateDevices;
                    if (dialog == null || devices == null) return;
                    if (foundAny && !devices.isEmpty()) {
                        removeSearchingRow();
                        return;
                    }
                    releaseCandidateSession(dialog, devices, true);
                    presenter.onScanEnded(false);
                }

                @Override public void onFailure(NormalBadgeScanner.Failure failure) {
                    refreshEnvironment();
                    AlertDialog dialog = candidateDialog;
                    Map<String, BluetoothDevice> devices = candidateDevices;
                    if (dialog != null && devices != null) {
                        releaseCandidateSession(dialog, devices, true);
                    }
                    presenter.onScanFailed(problemFor(failure));
                }
            };

    private final SeekBar.OnSeekBarChangeListener dayListener =
            new SeekBar.OnSeekBarChangeListener() {
                @Override public void onProgressChanged(
                        SeekBar seekBar, int progress, boolean fromUser) {
                    if (fromUser && !rendering) presenter.onDayChanged(progress);
                }
                @Override public void onStartTrackingTouch(SeekBar seekBar) {}
                @Override public void onStopTrackingTouch(SeekBar seekBar) {}
            };

    private final SeekBar.OnSeekBarChangeListener weekListener =
            new SeekBar.OnSeekBarChangeListener() {
                @Override public void onProgressChanged(
                        SeekBar seekBar, int progress, boolean fromUser) {
                    if (fromUser && !rendering) presenter.onWeekChanged(progress);
                }
                @Override public void onStartTrackingTouch(SeekBar seekBar) {}
                @Override public void onStopTrackingTouch(SeekBar seekBar) {}
            };

    @SuppressWarnings("deprecation")
    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mainTitle = findViewById(R.id.main_title);
        selectedBadgeLabel = findViewById(R.id.selected_badge_label);
        selectedBadgeValue = findViewById(R.id.selected_badge_value);
        chooseBadgeButton = findViewById(R.id.choose_badge_button);
        connectionLabel = findViewById(R.id.connection_label);
        connectionStatusValue = findViewById(R.id.connection_status_value);
        connectionDetailValue = findViewById(R.id.connection_detail_value);
        syncPairGuidance = findViewById(R.id.sync_pair_guidance);
        localWarningValue = findViewById(R.id.local_warning_value);
        notificationWarningValue = findViewById(R.id.notification_warning_value);
        dayLabel = findViewById(R.id.day_label);
        dayValue = findViewById(R.id.day_value);
        daySeek = findViewById(R.id.day_seek);
        weekLabel = findViewById(R.id.week_label);
        weekValue = findViewById(R.id.week_value);
        weekSeek = findViewById(R.id.week_seek);
        creditLabel = findViewById(R.id.credit_label);
        creditValue = findViewById(R.id.credit_value);
        lastSyncValue = findViewById(R.id.last_sync_value);
        syncButton = findViewById(R.id.sync_button);
        stopSyncButton = findViewById(R.id.stop_sync_button);
        maintenanceButton = findViewById(R.id.maintenance_button);
        daySeek.setKeyProgressIncrement(1);
        weekSeek.setKeyProgressIncrement(1);

        daySeek.setOnSeekBarChangeListener(dayListener);
        weekSeek.setOnSeekBarChangeListener(weekListener);
        chooseBadgeButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { onChooseBadgeClicked(); }
        });
        syncButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { onSyncClicked(); }
        });
        stopSyncButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { onStopSyncClicked(); }
        });
        maintenanceButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { onMaintenanceClicked(); }
        });

        boolean dayPresent = savedInstanceState != null
                && savedInstanceState.containsKey(STATE_DAY);
        Object dayRaw = savedInstanceState == null
                ? null : savedInstanceState.get(STATE_DAY);
        boolean weekPresent = savedInstanceState != null
                && savedInstanceState.containsKey(STATE_WEEK);
        Object weekRaw = savedInstanceState == null
                ? null : savedInstanceState.get(STATE_WEEK);
        BadgeState restored = MainUiPresenter.decodeRestoredState(
                dayPresent, dayRaw, weekPresent, weekRaw);
        presenter = new MainUiPresenter(host, restored);
        mainHandler = new Handler(Looper.getMainLooper());
        scanner = new NormalBadgeScanner(getApplicationContext(), mainHandler, scannerListener);
        refreshEnvironment();
    }

    @Override protected void onStart() {
        super.onStart();
        refreshEnvironment();
        presenter.onServiceBinding();
        Intent serviceIntent = new Intent(this, BadgeSyncService.class);
        bindReleaseOwed = true;
        try {
            boolean accepted = bindService(
                    serviceIntent, serviceConnection, Context.BIND_AUTO_CREATE);
            if (!accepted) presenter.onServiceBindFailed();
        } catch (SecurityException bindFailure) {
            presenter.onServiceBindFailed();
        }
    }

    @Override protected void onStop() {
        try {
            try {
                if (scanner != null) scanner.stop();
            } finally {
                AlertDialog dialog = candidateDialog;
                Map<String, BluetoothDevice> devices = candidateDevices;
                if (dialog != null && devices != null) {
                    releaseCandidateSession(dialog, devices, true);
                }
            }
        } finally {
            try {
                try {
                    BadgeSyncService.LocalBinder binder = currentBinder;
                    if (listenerRegistered && binder != null) {
                        try {
                            binder.removeSnapshotListener(snapshotListener);
                        } catch (IllegalStateException removalFailure) {
                            // The dying service may already have dropped its listener set.
                        }
                    }
                } finally {
                    listenerRegistered = false;
                    currentBinder = null;
                    if (presenter != null) presenter.onServiceUnbound();
                }
            } finally {
                try {
                    if (bindReleaseOwed) {
                        bindReleaseOwed = false;
                        try {
                            unbindService(serviceConnection);
                        } catch (IllegalArgumentException notRegistered) {
                            // A false bind result still owes this single release attempt.
                        } catch (SecurityException denied) {
                            // The bind SecurityException path still owes one release attempt.
                        }
                    }
                } finally {
                    super.onStop();
                }
            }
        }
    }

    @Override protected void onDestroy() {
        try {
            try {
                if (scanner != null) scanner.close();
            } finally {
                if (presenter != null) presenter.close();
            }
        } finally {
            super.onDestroy();
        }
    }

    @Override protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        BadgeState state = presenter.currentState();
        outState.putInt(STATE_DAY, state.dayPercent());
        outState.putInt(STATE_WEEK, state.weekPercent());
    }

    @Override protected void onRestoreInstanceState(Bundle savedInstanceState) {
        super.onRestoreInstanceState(savedInstanceState);
        render(presenter.viewState());
    }

    @Override public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_NEARBY || requestCode == REQUEST_NOTIFICATIONS) {
            refreshEnvironment();
        }
    }

    private void onChooseBadgeClicked() {
        refreshEnvironment();
        presenter.onChooseBadgePressed();
    }

    private void onSyncClicked() {
        refreshEnvironment();
        presenter.onSyncPressed();
    }

    private void onStopSyncClicked() {
        presenter.onStopPressed();
    }

    private void onMaintenanceClicked() {
        if (!MaintenanceEntryGate.canEnter(getApplicationContext())) return;
        Intent intent = new Intent(MainActivity.this, MaintenanceActivity.class);
        startActivity(intent);
    }

    @SuppressLint("MissingPermission")
    private void refreshEnvironment() {
        boolean scanGranted = checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)
                == PackageManager.PERMISSION_GRANTED;
        boolean connectGranted = checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                == PackageManager.PERMISSION_GRANTED;
        boolean notificationGranted = Build.VERSION.SDK_INT < 33
                || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                        == PackageManager.PERMISSION_GRANTED;
        boolean bluetoothEnabled = false;
        if (connectGranted) {
            try {
                BluetoothManager manager = getSystemService(BluetoothManager.class);
                BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
                bluetoothEnabled = adapter != null && adapter.isEnabled();
            } catch (SecurityException permissionLost) {
                connectGranted = false;
            }
        }
        boolean scanning = scanner != null && scanner.isScanning();
        presenter.onEnvironment(new MainUiPresenter.Environment(
                scanGranted, connectGranted, notificationGranted,
                bluetoothEnabled, scanning));
    }

    private void cleanupFailedBinding() {
        BadgeSyncService.LocalBinder binder = currentBinder;
        try {
            if (listenerRegistered && binder != null) {
                try {
                    binder.removeSnapshotListener(snapshotListener);
                } catch (IllegalStateException removalFailure) {
                    // Best effort after a service-side failure.
                }
            }
        } finally {
            listenerRegistered = false;
            currentBinder = null;
            if (presenter != null) presenter.onServiceBindFailed();
        }
    }

    private void openCandidateDialog() {
        AlertDialog previousDialog = candidateDialog;
        Map<String, BluetoothDevice> previousDevices = candidateDevices;
        if (previousDialog != null && previousDevices != null) {
            scanner.stop();
            releaseCandidateSession(previousDialog, previousDevices, true);
            refreshEnvironment();
        }

        final List<String> addresses = new ArrayList<>();
        final Map<String, BluetoothDevice> devices = new LinkedHashMap<>();
        final ArrayAdapter<String> adapter = new ArrayAdapter<>(
                this, android.R.layout.simple_list_item_1, new ArrayList<String>());
        adapter.add(getString(R.string.scan_dialog_searching));
        final AlertDialog[] dialogHolder = new AlertDialog[1];
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.scan_dialog_title)
                .setAdapter(adapter, (ignored, which) -> {
                    if (which >= 0 && which < addresses.size()) {
                        onCandidateSelected(
                                dialogHolder[0], devices, addresses.get(which));
                    }
                })
                .setNegativeButton(R.string.cancel, (ignored, which) -> {
                    // The dismiss listener owns session disposal.
                })
                .create();
        dialogHolder[0] = dialog;
        dialog.setCancelable(true);
        dialog.setOnCancelListener(ignored -> {
            boolean currentSession = candidateDialog == dialog && candidateDevices == devices;
            if (!currentSession) {
                devices.clear();
                return;
            }
            scanner.stop();
            releaseCandidateSession(dialog, devices, false);
            refreshEnvironment();
        });
        dialog.setOnDismissListener(ignored -> {
            boolean currentSession = candidateDialog == dialog && candidateDevices == devices;
            if (currentSession) scanner.stop();
            devices.clear();
            if (currentSession) {
                candidateDevices = null;
                candidateAddresses = null;
                candidateAdapter = null;
                candidateDialog = null;
                refreshEnvironment();
            }
        });

        candidateAddresses = addresses;
        candidateDevices = devices;
        candidateAdapter = adapter;
        candidateDialog = dialog;
        dialog.show();
    }

    private void addCandidate(BluetoothDevice device, String address, boolean bonded) {
        Map<String, BluetoothDevice> devices = candidateDevices;
        List<String> addresses = candidateAddresses;
        ArrayAdapter<String> adapter = candidateAdapter;
        if (device == null || address == null || devices == null
                || addresses == null || adapter == null
                || devices.containsKey(address)
                || devices.size() >= NormalBadgeScanner.MAX_CANDIDATES) {
            return;
        }
        String suffix = finalTwoOctets(address);
        if (suffix == null) return;
        if (devices.isEmpty()) adapter.clear();
        devices.put(address, device);
        addresses.add(address);
        adapter.add(getString(R.string.selected_badge_format, suffix,
                getString(bonded ? R.string.paired : R.string.not_paired)));
    }

    private void removeSearchingRow() {
        if (candidateAdapter != null && candidateDevices != null
                && candidateDevices.isEmpty()) {
            candidateAdapter.clear();
        }
    }

    private void releaseCandidateSession(AlertDialog dialog,
            Map<String, BluetoothDevice> devices, boolean dismiss) {
        devices.clear();
        if (candidateDialog == dialog && candidateDevices == devices) {
            candidateDevices = null;
            candidateAddresses = null;
            candidateAdapter = null;
            candidateDialog = null;
        }
        if (dismiss && dialog.isShowing()) dialog.dismiss();
    }

    private void onCandidateSelected(AlertDialog dialog,
            Map<String, BluetoothDevice> devices, String address) {
        BluetoothDevice selectedDevice = devices.get(address);
        refreshEnvironment();
        BadgeSyncService.LocalBinder binder = currentBinder;
        boolean permissionsGranted = nearbyPermissionsGranted();
        scanner.stop();
        releaseCandidateSession(dialog, devices, true);
        refreshEnvironment();

        if (!permissionsGranted) {
            presenter.onCommandFailed(
                    MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED);
            return;
        }
        if (binder == null || selectedDevice == null) {
            presenter.onCommandFailed(MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE);
            return;
        }
        try {
            binder.setCurrentState(presenter.currentState());
            binder.selectDevice(selectedDevice);
            presenter.onScanEnded(true);
        } catch (SecurityException permissionLost) {
            presenter.onCommandFailed(
                    MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED);
        } catch (IllegalStateException translatedFailure) {
            if (!nearbyPermissionsGranted()) {
                refreshEnvironment();
                presenter.onCommandFailed(
                        MainUiPresenter.CommandResult.BLUETOOTH_PERMISSION_REQUIRED);
            } else {
                presenter.onCommandFailed(MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE);
            }
        } catch (RuntimeException commandFailure) {
            presenter.onCommandFailed(MainUiPresenter.CommandResult.SERVICE_UNAVAILABLE);
        }
    }

    private void render(MainUiPresenter.ViewState state) {
        rendering = true;
        try {
            int day = state.dayPercent();
            int week = state.weekPercent();
            daySeek.setProgress(day);
            weekSeek.setProgress(week);
            dayValue.setText(getString(R.string.percent_format, day));
            weekValue.setText(getString(R.string.percent_format, week));
            daySeek.setStateDescription(
                    getString(R.string.percent_state_format, day));
            weekSeek.setStateDescription(
                    getString(R.string.percent_state_format, week));

            String address = state.selectedDeviceAddress();
            if (address == null) {
                selectedBadgeValue.setText(R.string.no_badge_selected);
            } else {
                String suffix = finalTwoOctets(address);
                if (suffix == null) {
                    selectedBadgeValue.setText(R.string.selected_badge_name_only);
                } else {
                    selectedBadgeValue.setText(getString(
                            R.string.selected_badge_format,
                            suffix,
                            getString(state.bonded()
                                    ? R.string.paired : R.string.not_paired)));
                }
            }

            connectionStatusValue.setText(statusResource(state.statusKind()));
            syncPairGuidance.setText(guidanceResource(state.guidanceKind()));
            renderProblemAndDetail(state);
            if (state.notificationPermissionWarning()) {
                notificationWarningValue.setText(
                        R.string.notification_permission_warning);
                notificationWarningValue.setVisibility(View.VISIBLE);
            } else {
                notificationWarningValue.setVisibility(View.GONE);
            }
            renderAcknowledgment(state);

            chooseBadgeButton.setEnabled(state.chooseBadgeButtonEnabled());
            syncButton.setText(state.syncButtonKind()
                    == MainUiPresenter.SyncButtonKind.START_SYNC
                    ? R.string.start_sync : R.string.sync_now);
            syncButton.setEnabled(state.syncButtonEnabled());
            stopSyncButton.setEnabled(state.stopButtonEnabled());
        } finally {
            rendering = false;
        }
    }

    private void renderProblemAndDetail(MainUiPresenter.ViewState state) {
        if (state.localProblem() != MainUiPresenter.ProblemKind.NONE) {
            localWarningValue.setText(problemResource(state.localProblem()));
            localWarningValue.setVisibility(View.VISIBLE);
            connectionDetailValue.setVisibility(View.GONE);
            return;
        }
        localWarningValue.setVisibility(View.GONE);
        renderConnectionDetail(state);
    }

    private void renderConnectionDetail(MainUiPresenter.ViewState state) {
        if (state.statusKind() == MainUiPresenter.StatusKind.READY) {
            BuildInfo build = state.buildInfo();
            if (build == null) {
                connectionDetailValue.setVisibility(View.GONE);
                return;
            }
            Integer battery = state.batteryPercent();
            if (battery == null) {
                connectionDetailValue.setText(getString(R.string.firmware_format,
                        build.major(), build.minor(), build.patch()));
            } else {
                connectionDetailValue.setText(getString(
                        R.string.ready_detail_with_battery,
                        build.major(), build.minor(), build.patch(),
                        battery.intValue()));
            }
            connectionDetailValue.setVisibility(View.VISIBLE);
            return;
        }
        if (state.statusKind() == MainUiPresenter.StatusKind.RETRYING) {
            Long delay = state.nextReconnectDelayMs();
            if (delay == null) {
                connectionDetailValue.setVisibility(View.GONE);
                return;
            }
            long seconds = wholeSecondsCeiling(delay.longValue());
            UserVisibleError error = state.connectionError();
            if (error == null) {
                connectionDetailValue.setText(getString(
                        R.string.retry_seconds_format, seconds));
            } else {
                connectionDetailValue.setText(getString(
                        R.string.retry_error_format, error.message(), seconds));
            }
            connectionDetailValue.setVisibility(View.VISIBLE);
            return;
        }
        if (state.statusKind() == MainUiPresenter.StatusKind.ERROR
                && state.connectionError() != null) {
            connectionDetailValue.setText(state.connectionError().message());
            connectionDetailValue.setVisibility(View.VISIBLE);
            return;
        }
        connectionDetailValue.setVisibility(View.GONE);
    }

    private void renderAcknowledgment(MainUiPresenter.ViewState state) {
        BadgeState acknowledged = state.lastAcknowledgedState();
        if (acknowledged == null) {
            lastSyncValue.setText(R.string.last_sync_never);
        } else if (state.currentStateAcknowledged()) {
            lastSyncValue.setText(getString(R.string.last_sync_current,
                    acknowledged.dayPercent(), acknowledged.weekPercent()));
        } else {
            lastSyncValue.setText(getString(R.string.last_sync_older,
                    acknowledged.dayPercent(), acknowledged.weekPercent()));
        }
    }

    private static long wholeSecondsCeiling(long milliseconds) {
        return milliseconds / 1000L
                + (milliseconds % 1000L == 0L ? 0L : 1L);
    }

    private static int statusResource(MainUiPresenter.StatusKind kind) {
        switch (kind) {
            case SERVICE_CONNECTING:
                return R.string.status_service_connecting;
            case SERVICE_UNAVAILABLE:
                return R.string.status_service_unavailable;
            case SYNC_OFF:
                return R.string.status_sync_off;
            case NO_DEVICE:
                return R.string.status_no_device;
            case BONDING:
                return R.string.status_bonding;
            case CONNECTING:
                return R.string.status_connecting;
            case DISCOVERING:
                return R.string.status_discovering;
            case VALIDATING_BUILD:
                return R.string.status_validating_build;
            case READY:
                return R.string.status_ready;
            case RETRYING:
                return R.string.status_retrying;
            case ERROR:
                return R.string.status_error;
            default:
                throw new AssertionError("unhandled status");
        }
    }

    private static int guidanceResource(MainUiPresenter.GuidanceKind kind) {
        switch (kind) {
            case WAIT_FOR_SERVICE:
                return R.string.guidance_wait_for_service;
            case CHOOSE_BADGE:
                return R.string.guidance_choose_badge;
            case HOLD_SYNC_PAIR:
                return R.string.guidance_hold_sync_pair;
            case WAIT_FOR_CONNECTION:
                return R.string.guidance_wait_for_connection;
            case ADJUST_AND_SYNC:
                return R.string.guidance_adjust_and_sync;
            case RETRYING_AUTOMATICALLY:
                return R.string.guidance_retrying;
            case STOP_FIX_AND_RETRY:
                return R.string.guidance_stop_fix_retry;
            default:
                throw new AssertionError("unhandled guidance");
        }
    }

    private static int problemResource(MainUiPresenter.ProblemKind kind) {
        switch (kind) {
            case BLUETOOTH_PERMISSION_REQUIRED:
                return R.string.bluetooth_permission_problem;
            case BLUETOOTH_OFF:
                return R.string.bluetooth_off_problem;
            case NO_BADGE_FOUND:
                return R.string.no_badge_found_problem;
            case SCAN_FAILED:
                return R.string.scan_failed_problem;
            case SERVICE_UNAVAILABLE:
                return R.string.service_unavailable_problem;
            case SYNC_START_FAILED:
                return R.string.sync_start_failed_problem;
            case NONE:
            default:
                throw new AssertionError("no visible problem");
        }
    }

    private boolean nearbyPermissionsGranted() {
        return checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)
                        == PackageManager.PERMISSION_GRANTED
                && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                        == PackageManager.PERMISSION_GRANTED;
    }

    private static String finalTwoOctets(String address) {
        if (address == null || address.length() != 17) return null;
        for (int index = 0; index < address.length(); index++) {
            char value = address.charAt(index);
            if (index == 2 || index == 5 || index == 8 || index == 11 || index == 14) {
                if (value != ':') return null;
            } else if (!isHex(value)) {
                return null;
            }
        }
        return address.substring(12);
    }

    private static boolean isHex(char value) {
        return (value >= '0' && value <= '9')
                || (value >= 'a' && value <= 'f')
                || (value >= 'A' && value <= 'F');
    }

    private static MainUiPresenter.ProblemKind problemFor(
            NormalBadgeScanner.Failure failure) {
        if (failure == NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED) {
            return MainUiPresenter.ProblemKind.BLUETOOTH_PERMISSION_REQUIRED;
        }
        if (failure == NormalBadgeScanner.Failure.BLUETOOTH_OFF) {
            return MainUiPresenter.ProblemKind.BLUETOOTH_OFF;
        }
        return MainUiPresenter.ProblemKind.SCAN_FAILED;
    }
}
