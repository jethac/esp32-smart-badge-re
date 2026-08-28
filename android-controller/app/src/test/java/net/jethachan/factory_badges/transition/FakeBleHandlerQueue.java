package net.jethachan.factory_badges.transition;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/** Test-only separately drained stand-in for BLE-handler acceptance and ordering. */
final class FakeBleHandlerQueue {
    private final ArrayDeque<Runnable> queue = new ArrayDeque<Runnable>();
    final List<String> acceptedLabels = new ArrayList<String>();
    boolean acceptsPosts = true;

    boolean post(String label, Runnable command) {
        if (label == null || command == null) {
            throw new IllegalArgumentException("label and command must not be null");
        }
        if (!acceptsPosts) {
            return false;
        }
        acceptedLabels.add(label);
        queue.addLast(command);
        return true;
    }

    int queuedCount() {
        return queue.size();
    }

    void drain() {
        while (!queue.isEmpty()) {
            queue.removeFirst().run();
        }
    }
}
