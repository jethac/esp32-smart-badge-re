package net.jethachan.factory_badges.ui;

import android.content.Context;
import android.os.Handler;
import android.os.HandlerThread;
import java.util.concurrent.Executor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import net.jethachan.factory_badges.transition.StockGattDriver;
import net.jethachan.factory_badges.transition.StockQixGattTransport;
import net.jethachan.factory_badges.transition.StockQixTransferMachine;
import net.jethachan.factory_badges.transition.StockTransitionController;
import net.jethachan.factory_badges.transition.TransitionArtifact;

/** Owns the Android threads and the exact stock-controller stack for one confirmed attempt. */
final class AndroidStockTransitionSession implements MaintenanceUiPresenter.Session {
    private static final long SETUP_TIMEOUT_MS = 15_000L;
    private static final long WRITE_TIMEOUT_MS = 15_000L;
    private static final long RESPONSE_TIMEOUT_MS = 15_000L;

    private final StockHostIdentity identity;
    private final MaintenanceUiPresenter.Listener listener;
    private final Executor listenerExecutor;
    private final HandlerThread bleThread;
    private final ExecutorService fifoExecutor;
    private final ScheduledExecutorService timerExecutor;
    private final StockTransitionController controller;
    private final AtomicBoolean closed = new AtomicBoolean();

    AndroidStockTransitionSession(Context context, TransitionArtifact artifact,
            StockHostIdentity identity, Executor listenerExecutor,
            MaintenanceUiPresenter.Listener listener) {
        if (context == null || artifact == null || identity == null
                || listenerExecutor == null || listener == null) {
            throw new IllegalArgumentException("session inputs must not be null");
        }
        Context applicationContext = context.getApplicationContext();
        if (applicationContext == null) {
            throw new IllegalArgumentException("application context must not be null");
        }
        this.identity = identity;
        this.listener = listener;
        this.listenerExecutor = listenerExecutor;
        bleThread = new HandlerThread("E87-Stock-BLE");
        bleThread.start();
        Handler bleHandler = new Handler(bleThread.getLooper());
        fifoExecutor = Executors.newSingleThreadExecutor();
        timerExecutor = Executors.newSingleThreadScheduledExecutor();

        StockQixGattTransport transport = new StockQixGattTransport(
                applicationContext, bleHandler, fifoExecutor);
        controller = new StockTransitionController(
                artifact,
                transport,
                fifoExecutor,
                new SchedulerPort(timerExecutor),
                new StockTransitionController.Timeouts(
                        SETUP_TIMEOUT_MS, WRITE_TIMEOUT_MS, RESPONSE_TIMEOUT_MS),
                new ControllerListener());
    }

    @Override public void startScan() {
        requireOpen();
        controller.startScan();
    }

    @Override public void connect(StockGattDriver.Peer peer) {
        if (peer == null) throw new IllegalArgumentException("peer must not be null");
        requireOpen();
        controller.connect(peer, identity.settings(), identity.hostId());
    }

    @Override public void cancel() {
        if (closed.get()) return;
        controller.cancel();
    }

    @Override public void close() {
        if (!closed.compareAndSet(false, true)) return;
        controller.close();
        try {
            fifoExecutor.execute(new Runnable() {
                @Override public void run() {
                    timerExecutor.shutdownNow();
                    bleThread.quitSafely();
                    fifoExecutor.shutdown();
                }
            });
        } catch (RejectedExecutionException rejected) {
            timerExecutor.shutdownNow();
            bleThread.quitSafely();
            fifoExecutor.shutdown();
        }
    }

    private void requireOpen() {
        if (closed.get()) throw new IllegalStateException("session is closed");
    }

    private void deliver(Runnable callback) {
        if (closed.get()) return;
        try {
            listenerExecutor.execute(callback);
        } catch (RuntimeException ignored) {
            // A destroyed UI owns no remaining callback delivery.
        }
    }

    private final class ControllerListener implements StockTransitionController.Listener {
        @Override public void onCandidate(final StockGattDriver.Peer candidate) {
            deliver(new Runnable() {
                @Override public void run() { listener.onCandidate(candidate); }
            });
        }

        @Override public void onSnapshot(final StockQixTransferMachine.Snapshot snapshot) {
            deliverProgress(snapshot);
        }

        @Override public void onComplete(final StockQixTransferMachine.Snapshot snapshot) {
            deliver(new Runnable() {
                @Override public void run() {
                    listener.onProgress(snapshot.acknowledgedOffset(),
                            snapshot.totalBytes(), false);
                    listener.onAccepted();
                }
            });
        }

        @Override public void onFailed(
                final StockQixTransferMachine.FailureCode failureCode,
                final StockQixTransferMachine.Snapshot snapshot) {
            deliver(new Runnable() {
                @Override public void run() {
                    listener.onProgress(snapshot.acknowledgedOffset(),
                            snapshot.totalBytes(), snapshot.mayCancel());
                    listener.onFailed(failureCode);
                }
            });
        }

        private void deliverProgress(final StockQixTransferMachine.Snapshot snapshot) {
            deliver(new Runnable() {
                @Override public void run() {
                    listener.onProgress(snapshot.acknowledgedOffset(),
                            snapshot.totalBytes(), snapshot.mayCancel());
                }
            });
        }
    }

    private static final class SchedulerPort implements StockTransitionController.Scheduler {
        private final ScheduledExecutorService executor;

        SchedulerPort(ScheduledExecutorService executor) {
            this.executor = executor;
        }

        @Override public Handle schedule(long delayMillis, Runnable runnable) {
            if (delayMillis <= 0L || runnable == null) {
                throw new IllegalArgumentException("valid deadline and callback are required");
            }
            final ScheduledFuture<?> future = executor.schedule(
                    runnable, delayMillis, TimeUnit.MILLISECONDS);
            return new Handle() {
                @Override public void cancel() { future.cancel(false); }
            };
        }
    }
}
