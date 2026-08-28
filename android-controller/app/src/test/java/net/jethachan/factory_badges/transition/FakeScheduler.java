package net.jethachan.factory_badges.transition;

import java.util.ArrayList;
import java.util.List;

/** Test-only deterministic scheduler whose callbacks are explicitly fired by the test. */
final class FakeScheduler implements StockTransitionController.Scheduler {
    final List<Entry> entries = new ArrayList<Entry>();

    @Override public StockTransitionController.Scheduler.Handle schedule(
            long delayMillis, Runnable runnable) {
        if (runnable == null) {
            throw new IllegalArgumentException("runnable must not be null");
        }
        Entry entry = new Entry(delayMillis, runnable);
        entries.add(entry);
        return entry;
    }

    Entry lastScheduled() {
        if (entries.isEmpty()) {
            throw new IllegalStateException("no timer was scheduled");
        }
        return entries.get(entries.size() - 1);
    }

    void fire(Entry entry) {
        if (entry == null) {
            throw new IllegalArgumentException("entry must not be null");
        }
        if (!entry.cancelled) {
            entry.runnable.run();
        }
    }

    void fireRegardlessOfCancellation(Entry entry) {
        if (entry == null) {
            throw new IllegalArgumentException("entry must not be null");
        }
        entry.runnable.run();
    }

    static final class Entry implements StockTransitionController.Scheduler.Handle {
        final long delayMillis;
        final Runnable runnable;
        boolean cancelled;

        Entry(long delayMillis, Runnable runnable) {
            this.delayMillis = delayMillis;
            this.runnable = runnable;
        }

        @Override public void cancel() {
            cancelled = true;
        }
    }
}
