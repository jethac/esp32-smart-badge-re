package net.jethachan.factory_badges.ble.normal;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class GattOperationQueue {
    public interface Driver {
    }

    public interface Operation {
        long token();

        long timeoutMs();

        boolean start(Driver driver);

        void onComplete(int status);

        void onFailure(Throwable cause);
    }

    public interface Scheduler {
        TimeoutHandle schedule(long timeoutMs, Runnable callback);
    }

    public interface TimeoutHandle {
        void cancel();
    }

    public static final class TimeoutFailure extends RuntimeException {
        private static final long serialVersionUID = 1L;

        private final long token;
        private final long timeoutMs;

        private TimeoutFailure(long token, long timeoutMs) {
            super("GATT operation " + token + " timed out after " + timeoutMs + " ms");
            this.token = token;
            this.timeoutMs = timeoutMs;
        }

        public long token() {
            return token;
        }

        public long timeoutMs() {
            return timeoutMs;
        }
    }

    private final Object monitor = new Object();
    private final Driver driver;
    private final Scheduler scheduler;
    private final ArrayDeque<Entry> pending = new ArrayDeque<Entry>();
    private final Set<Long> acceptedTokens = new HashSet<Long>();
    private final ArrayDeque<Runnable> actions = new ArrayDeque<Runnable>();

    private Entry active;
    private boolean advanceScheduled;
    private boolean pumping;
    private boolean failingAll;
    private long generation;

    public GattOperationQueue(Driver driver, Scheduler scheduler) {
        if (driver == null) {
            throw new IllegalArgumentException("driver must not be null");
        }
        if (scheduler == null) {
            throw new IllegalArgumentException("scheduler must not be null");
        }
        this.driver = driver;
        this.scheduler = scheduler;
    }

    public void enqueue(Operation operation) {
        if (operation == null) {
            throw new IllegalArgumentException("operation must not be null");
        }

        long token = operation.token();
        long timeoutMs = operation.timeoutMs();
        if (token <= 0) {
            throw new IllegalArgumentException("operation token must be positive");
        }
        if (timeoutMs <= 0) {
            throw new IllegalArgumentException("operation timeout must be positive");
        }

        synchronized (monitor) {
            if (failingAll) {
                throw new IllegalStateException("cannot enqueue while failAll is dispatching");
            }
            if (!acceptedTokens.add(Long.valueOf(token))) {
                throw new IllegalArgumentException(
                        "operation token was already accepted by this queue: " + token);
            }
            pending.addLast(new Entry(operation, token, timeoutMs));
            scheduleAdvanceLocked();
        }
        pump();
    }

    public boolean complete(long token, int status) {
        synchronized (monitor) {
            if (active == null || active.token != token) {
                return false;
            }
            Entry completed = removeActiveLocked();
            enqueueCancellationLocked(completed);
            actions.addLast(completionAction(completed.operation, status));
            scheduleAdvanceLocked();
        }
        pump();
        return true;
    }

    public void failAll(Throwable cause) {
        if (cause == null) {
            throw new IllegalArgumentException("failure cause must not be null");
        }

        synchronized (monitor) {
            if (failingAll) {
                throw new IllegalStateException("failAll is already dispatching");
            }
            failingAll = true;

            List<Entry> failures = new ArrayList<Entry>(pending.size() + 1);
            if (active != null) {
                Entry activeFailure = removeActiveLocked();
                enqueueCancellationLocked(activeFailure);
                failures.add(activeFailure);
            }
            while (!pending.isEmpty()) {
                failures.add(pending.removeFirst());
            }
            for (Entry failure : failures) {
                actions.addLast(failureAction(failure.operation, cause));
            }
            actions.addLast(new Runnable() {
                @Override
                public void run() {
                    finishFailAll();
                }
            });
        }
        pump();
    }

    public long activeToken() {
        synchronized (monitor) {
            return active == null ? 0L : active.token;
        }
    }

    public int pendingCount() {
        synchronized (monitor) {
            return pending.size();
        }
    }

    private void scheduleAdvanceLocked() {
        if (active != null || pending.isEmpty() || advanceScheduled || failingAll) {
            return;
        }
        advanceScheduled = true;
        actions.addLast(new Runnable() {
            @Override
            public void run() {
                advance();
            }
        });
    }

    private void advance() {
        Entry next;
        synchronized (monitor) {
            advanceScheduled = false;
            if (active != null || pending.isEmpty() || failingAll) {
                return;
            }
            next = pending.removeFirst();
            generation++;
            next.generation = generation;
            active = next;
        }
        start(next);
    }

    private void start(final Entry entry) {
        boolean started;
        try {
            started = entry.operation.start(driver);
        } catch (RuntimeException failure) {
            failCurrent(entry, entry.generation, failure);
            return;
        }

        if (!started) {
            failCurrent(entry, entry.generation, new IllegalStateException(
                    "GATT operation " + entry.token + " start rejected"));
            return;
        }

        synchronized (monitor) {
            if (!isCurrentLocked(entry, entry.generation)) {
                return;
            }
        }

        TimeoutHandle handle;
        try {
            handle = scheduler.schedule(entry.timeoutMs, new Runnable() {
                @Override
                public void run() {
                    timeOut(entry, entry.generation);
                }
            });
            if (handle == null) {
                throw new IllegalStateException("scheduler returned a null timeout handle");
            }
        } catch (RuntimeException failure) {
            failCurrent(entry, entry.generation, failure);
            return;
        }

        boolean retained;
        synchronized (monitor) {
            retained = isCurrentLocked(entry, entry.generation)
                    && entry.timeoutHandle == null;
            if (retained) {
                entry.timeoutHandle = handle;
            }
        }
        if (!retained) {
            handle.cancel();
        }
    }

    private void timeOut(Entry entry, long expectedGeneration) {
        synchronized (monitor) {
            if (!isCurrentLocked(entry, expectedGeneration)) {
                return;
            }
            Entry timedOut = removeActiveLocked();
            timedOut.timeoutHandle = null;
            actions.addLast(failureAction(timedOut.operation,
                    new TimeoutFailure(timedOut.token, timedOut.timeoutMs)));
            scheduleAdvanceLocked();
        }
        pump();
    }

    private void failCurrent(Entry entry, long expectedGeneration, Throwable cause) {
        synchronized (monitor) {
            if (!isCurrentLocked(entry, expectedGeneration)) {
                return;
            }
            Entry failed = removeActiveLocked();
            enqueueCancellationLocked(failed);
            actions.addLast(failureAction(failed.operation, cause));
            scheduleAdvanceLocked();
        }
        pump();
    }

    private Entry removeActiveLocked() {
        Entry removed = active;
        active = null;
        return removed;
    }

    private boolean isCurrentLocked(Entry entry, long expectedGeneration) {
        return active == entry && entry.generation == expectedGeneration;
    }

    private void enqueueCancellationLocked(final Entry entry) {
        final TimeoutHandle handle = entry.timeoutHandle;
        entry.timeoutHandle = null;
        if (handle != null) {
            actions.addLast(new Runnable() {
                @Override
                public void run() {
                    handle.cancel();
                }
            });
        }
    }

    private static Runnable completionAction(final Operation operation, final int status) {
        return new Runnable() {
            @Override
            public void run() {
                operation.onComplete(status);
            }
        };
    }

    private static Runnable failureAction(
            final Operation operation, final Throwable cause) {
        return new Runnable() {
            @Override
            public void run() {
                operation.onFailure(cause);
            }
        };
    }

    private void finishFailAll() {
        synchronized (monitor) {
            failingAll = false;
            scheduleAdvanceLocked();
        }
    }

    private void pump() {
        synchronized (monitor) {
            if (pumping) {
                return;
            }
            pumping = true;
        }

        Throwable firstFailure = null;
        while (true) {
            Runnable action;
            synchronized (monitor) {
                action = actions.pollFirst();
                if (action == null) {
                    pumping = false;
                    break;
                }
            }
            try {
                action.run();
            } catch (RuntimeException failure) {
                if (firstFailure == null) {
                    firstFailure = failure;
                }
            } catch (Error failure) {
                if (firstFailure == null) {
                    firstFailure = failure;
                }
            }
        }

        if (firstFailure instanceof RuntimeException) {
            throw (RuntimeException) firstFailure;
        }
        if (firstFailure instanceof Error) {
            throw (Error) firstFailure;
        }
    }

    private static final class Entry {
        final Operation operation;
        final long token;
        final long timeoutMs;
        long generation;
        TimeoutHandle timeoutHandle;

        Entry(Operation operation, long token, long timeoutMs) {
            this.operation = operation;
            this.token = token;
            this.timeoutMs = timeoutMs;
        }
    }
}
