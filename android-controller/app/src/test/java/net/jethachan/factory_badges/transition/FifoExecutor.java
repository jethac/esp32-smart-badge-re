package net.jethachan.factory_badges.transition;

import java.util.ArrayDeque;
import java.util.concurrent.Executor;

/** Test-only explicitly drained FIFO executor. */
final class FifoExecutor implements Executor {
    private final ArrayDeque<Runnable> queue = new ArrayDeque<Runnable>();

    @Override public void execute(Runnable command) {
        if (command == null) {
            throw new IllegalArgumentException("command must not be null");
        }
        queue.addLast(command);
    }

    int queuedCount() {
        return queue.size();
    }

    void runNext() {
        Runnable next = queue.pollFirst();
        if (next == null) {
            throw new IllegalStateException("FIFO has no queued task");
        }
        next.run();
    }

    void drain() {
        while (!queue.isEmpty()) {
            runNext();
        }
    }
}
