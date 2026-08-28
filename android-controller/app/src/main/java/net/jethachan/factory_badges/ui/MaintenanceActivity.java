package net.jethachan.factory_badges.ui;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.format.DateFormat;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Executor;
import net.jethachan.factory_badges.R;
import net.jethachan.factory_badges.transition.EmbeddedFirmwareRepository;
import net.jethachan.factory_badges.transition.StockGattDriver;
import net.jethachan.factory_badges.transition.StockQixTransferMachine;
import net.jethachan.factory_badges.transition.TransitionArtifact;
import net.jethachan.factory_badges.transition.TransitionArtifactProvider;

/** Explicit, fail-closed UI for the one-time stock-firmware transition. */
public final class MaintenanceActivity extends Activity {
    private static final int REQUEST_NEARBY = 4201;

    private TextView artifactStatus;
    private TextView artifactIdentity;
    private TextView candidateLabel;
    private TextView transitionStatus;
    private CheckBox receiveModeConfirmation;
    private Button startTransitionButton;
    private Button cancelTransitionButton;
    private LinearLayout candidateList;
    private ProgressBar transitionProgress;
    private Handler mainHandler;
    private MaintenanceUiPresenter presenter;
    private boolean rendering;

    private final MaintenanceUiPresenter.Host host = new MaintenanceUiPresenter.Host() {
        @Override public void render(MaintenanceUiPresenter.ViewState state) {
            MaintenanceActivity.this.render(state);
        }

        @Override public MaintenanceUiPresenter.Session openSession(
                TransitionArtifact artifact, MaintenanceUiPresenter.Listener listener) {
            return new AndroidStockTransitionSession(
                    getApplicationContext(), artifact, currentIdentity(), mainExecutor(), listener);
        }
    };

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_maintenance);
        artifactStatus = findViewById(R.id.artifact_status);
        artifactIdentity = findViewById(R.id.artifact_identity);
        candidateLabel = findViewById(R.id.candidate_label);
        transitionStatus = findViewById(R.id.transition_status);
        receiveModeConfirmation = findViewById(R.id.receive_mode_confirmation);
        startTransitionButton = findViewById(R.id.start_transition_button);
        cancelTransitionButton = findViewById(R.id.cancel_transition_button);
        candidateList = findViewById(R.id.candidate_list);
        transitionProgress = findViewById(R.id.transition_progress);
        mainHandler = new Handler(Looper.getMainLooper());

        receiveModeConfirmation.setOnCheckedChangeListener(
                (button, checked) -> {
                    if (!rendering) presenter.onConfirmationChanged(checked);
                });
        startTransitionButton.setOnClickListener(
                view -> onStartTransitionClicked());
        cancelTransitionButton.setOnClickListener(
                view -> presenter.onCancelPressed());
        presenter = new MaintenanceUiPresenter(
                new EmbeddedFirmwareRepository(getApplicationContext()), host);
    }

    @Override public void onRequestPermissionsResult(
            int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_NEARBY) return;
        render(presenter.viewState());
        if (!nearbyPermissionsGranted()) {
            transitionStatus.setText(R.string.transition_permission_required);
        }
    }

    @Override protected void onDestroy() {
        try {
            if (presenter != null) presenter.close();
        } finally {
            super.onDestroy();
        }
    }

    private void onStartTransitionClicked() {
        if (!nearbyPermissionsGranted()) {
            requestPermissions(new String[] {
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT
            }, REQUEST_NEARBY);
            presenter.onConfirmationChanged(false);
            transitionStatus.setText(R.string.transition_permission_required);
            return;
        }
        presenter.onStartPressed();
    }

    private boolean nearbyPermissionsGranted() {
        return checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)
                        == PackageManager.PERMISSION_GRANTED
                && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                        == PackageManager.PERMISSION_GRANTED;
    }

    private Executor mainExecutor() {
        return new Executor() {
            @Override public void execute(Runnable command) {
                if (command == null || !mainHandler.post(command)) {
                    throw new IllegalStateException("main callback queue is unavailable");
                }
            }
        };
    }

    @SuppressWarnings("deprecation")
    private StockHostIdentity currentIdentity() {
        String[] buildFields = new String[] {
                safe(Build.BOARD), safe(Build.BRAND), safe(Build.CPU_ABI),
                safe(Build.DEVICE), safe(Build.DISPLAY), safe(Build.HOST), safe(Build.ID),
                safe(Build.MANUFACTURER), safe(Build.MODEL), safe(Build.PRODUCT),
                safe(Build.TAGS), safe(Build.TYPE), safe(Build.USER)
        };
        return StockHostIdentity.derive(
                Locale.getDefault().getLanguage(), DateFormat.is24HourFormat(this), buildFields);
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }

    private void render(MaintenanceUiPresenter.ViewState state) {
        rendering = true;
        try {
            renderArtifact(state);
            receiveModeConfirmation.setEnabled(state.confirmationEnabled());
            receiveModeConfirmation.setChecked(state.confirmationChecked());
            startTransitionButton.setEnabled(state.startEnabled());
            cancelTransitionButton.setEnabled(state.cancelEnabled());
            transitionProgress.setProgress(state.progressPercent());
            renderCandidates(state);
            transitionStatus.setText(statusText(state));
        } finally {
            rendering = false;
        }
    }

    private void renderArtifact(MaintenanceUiPresenter.ViewState state) {
        switch (state.artifactStatus()) {
            case READY:
                artifactStatus.setText(R.string.artifact_ready_label);
                artifactIdentity.setText(getResources().getQuantityString(
                        R.plurals.artifact_identity,
                        (int) state.qixByteLength(),
                        state.qixByteLength(), state.expectedBuildIdHex()));
                artifactIdentity.setVisibility(View.VISIBLE);
                return;
            case NOT_PACKAGED:
                artifactStatus.setText(R.string.artifact_not_packaged);
                break;
            case VALIDATOR_NOT_INTEGRATED:
                artifactStatus.setText(R.string.artifact_validator_unavailable);
                break;
            case INVALID_PACKAGE:
                artifactStatus.setText(R.string.artifact_invalid);
                break;
            default:
                throw new AssertionError("unhandled artifact status");
        }
        artifactIdentity.setVisibility(View.GONE);
    }

    private void renderCandidates(MaintenanceUiPresenter.ViewState state) {
        List<StockGattDriver.Peer> candidates = state.candidates();
        candidateList.removeAllViews();
        for (final StockGattDriver.Peer peer : candidates) {
            Button candidateButton = new Button(this);
            candidateButton.setLayoutParams(new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
            candidateButton.setText(getString(R.string.stock_candidate_format,
                    displayName(peer), finalTwoOctets(peer.address()), peer.rssi()));
            candidateButton.setEnabled(state.phase() == MaintenanceUiPresenter.Phase.CANDIDATES);
            candidateButton.setOnClickListener(
                    view -> presenter.onCandidateSelected(peer));
            candidateList.addView(candidateButton);
        }
        int visibility = candidates.isEmpty() ? View.GONE : View.VISIBLE;
        candidateLabel.setVisibility(visibility);
        candidateList.setVisibility(visibility);
    }

    private CharSequence statusText(MaintenanceUiPresenter.ViewState state) {
        switch (state.phase()) {
            case ARTIFACT_UNAVAILABLE:
            case READY:
                return getText(R.string.transition_idle);
            case STARTING:
                return getText(R.string.transition_starting);
            case SCANNING:
            case CANDIDATES:
                return getText(R.string.transition_scanning);
            case CONNECTING:
                return getText(R.string.transition_connecting);
            case TRANSFERRING:
                return getResources().getQuantityString(
                        R.plurals.transition_progress_format,
                        (int) state.totalBytes(),
                        state.progressPercent(), state.acknowledgedBytes(), state.totalBytes());
            case WAITING_FOR_CUSTOM_FIRMWARE:
                return getText(R.string.transition_waiting_custom);
            case FAILED:
                StockQixTransferMachine.FailureCode code = state.failureCode();
                return getString(R.string.transition_failed_format,
                        code == null ? "UNKNOWN" : code.name());
            case CLOSED:
                return getText(R.string.transition_closed);
            default:
                throw new AssertionError("unhandled transition phase");
        }
    }

    private static String displayName(StockGattDriver.Peer peer) {
        String name = peer.displayName();
        return name.trim().isEmpty() ? "Bluetooth device" : name;
    }

    private static String finalTwoOctets(String address) {
        return address.substring(12);
    }
}
