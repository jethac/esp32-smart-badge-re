package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

public final class GattOperationQueueTest {
    @Test
    public void startsCccdReadAndWriteStrictlyInFifoOrder() {
        Fixture fixture = new Fixture();
        RecordingOperation cccd = fixture.operation("cccd", 1);
        RecordingOperation read = fixture.operation("read", 2);
        RecordingOperation write = fixture.operation("write", 3);

        fixture.queue.enqueue(cccd);
        fixture.queue.enqueue(read);
        fixture.queue.enqueue(write);

        assertEquals(Arrays.asList("start:cccd"), fixture.events);
        assertEquals(1L, fixture.queue.activeToken());
        assertEquals(2, fixture.queue.pendingCount());

        assertTrue(fixture.queue.complete(1, 0));
        assertEquals(Arrays.asList("start:cccd", "complete:cccd:0", "start:read"),
                fixture.events);
        assertTrue(fixture.scheduler.handles.get(0).cancelled);

        assertTrue(fixture.queue.complete(2, 7));
        assertTrue(fixture.queue.complete(3, 9));
        assertEquals(Arrays.asList(
                "start:cccd", "complete:cccd:0",
                "start:read", "complete:read:7",
                "start:write", "complete:write:9"), fixture.events);
        assertEquals(0L, fixture.queue.activeToken());
        assertEquals(0, fixture.queue.pendingCount());
    }

    @Test
    public void rejectsMalformedDuplicateAndRetiredTokensWithoutChangingQueue() {
        Fixture fixture = new Fixture();
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(null);
            }
        });
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("zero-token", 0));
            }
        });
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("negative-token", -1));
            }
        });
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("zero-timeout", 10, 0));
            }
        });

        fixture.queue.enqueue(fixture.operation("active", 1));
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("duplicate-active", 1));
            }
        });
        fixture.queue.enqueue(fixture.operation("queued", 2));
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("duplicate-queued", 2));
            }
        });

        assertTrue(fixture.queue.complete(1, 0));
        assertTrue(fixture.queue.complete(2, 0));
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("retired-token", 1));
            }
        });
        assertEquals(0L, fixture.queue.activeToken());
        assertEquals(0, fixture.queue.pendingCount());
    }

    @Test
    public void consumesOnlyTheCurrentCallbackTokenExactlyOnce() {
        Fixture fixture = new Fixture();
        RecordingOperation first = fixture.operation("first", 11);
        fixture.queue.enqueue(first);
        fixture.queue.enqueue(fixture.operation("second", 12));

        assertFalse(fixture.queue.complete(12, 1));
        assertFalse(fixture.queue.complete(99, 1));
        assertEquals(11L, fixture.queue.activeToken());
        assertEquals(0, first.completionCount);

        assertTrue(fixture.queue.complete(11, 5));
        assertFalse(fixture.queue.complete(11, 6));
        assertEquals(1, first.completionCount);
        assertEquals(12L, fixture.queue.activeToken());
    }

    @Test
    public void timeoutFailsExactGenerationOnceAndAdvancesPastLateCallbacks() {
        Fixture fixture = new Fixture();
        RecordingOperation first = fixture.operation("first", 21, 3456);
        RecordingOperation second = fixture.operation("second", 22);
        fixture.queue.enqueue(first);
        fixture.queue.enqueue(second);
        ManualTimeout oldTimeout = fixture.scheduler.handles.get(0);

        oldTimeout.fireEvenIfCancelled();

        assertEquals(1, first.failureCauses.size());
        assertTrue(first.failureCauses.get(0) instanceof GattOperationQueue.TimeoutFailure);
        GattOperationQueue.TimeoutFailure failure =
                (GattOperationQueue.TimeoutFailure) first.failureCauses.get(0);
        assertEquals(21L, failure.token());
        assertEquals(3456L, failure.timeoutMs());
        assertEquals(22L, fixture.queue.activeToken());
        assertFalse(oldTimeout.cancelled);

        oldTimeout.fireEvenIfCancelled();
        assertFalse(fixture.queue.complete(21, 0));
        assertEquals(1, first.failureCauses.size());
        assertEquals(0, second.failureCauses.size());
        assertEquals(22L, fixture.queue.activeToken());
    }

    @Test
    public void timeoutDoesNotCancelHandleFromInsideItsOwnCallback() {
        List<String> events = new ArrayList<String>();
        SelfAwareScheduler scheduler = new SelfAwareScheduler();
        GattOperationQueue queue = new GattOperationQueue(new FakeDriver(), scheduler);
        RecordingOperation operation =
                new RecordingOperation("timeout", 23, 1000, events);
        queue.enqueue(operation);

        scheduler.handle.fire();

        assertFalse(scheduler.handle.cancelled);
        assertEquals(1, operation.failureCauses.size());
        assertTrue(operation.failureCauses.get(0)
                instanceof GattOperationQueue.TimeoutFailure);
        assertEquals(0L, queue.activeToken());
        assertEquals(0, queue.pendingCount());
    }

    @Test
    public void falseAndThrowingStartsFailOnceAndContinueToNextQueuedOperation() {
        Fixture fixture = new Fixture();
        RecordingOperation gate = fixture.operation("gate", 31);
        RecordingOperation rejected = fixture.operation("rejected", 32)
                .startingWith(false);
        RuntimeException startFailure = new RuntimeException("driver exploded");
        RecordingOperation throwing = fixture.operation("throwing", 33)
                .throwingOnStart(startFailure);
        RecordingOperation finalOperation = fixture.operation("final", 34);

        fixture.queue.enqueue(gate);
        fixture.queue.enqueue(rejected);
        fixture.queue.enqueue(throwing);
        fixture.queue.enqueue(finalOperation);
        fixture.queue.complete(31, 0);

        assertEquals(Arrays.asList(
                "start:gate", "complete:gate:0",
                "start:rejected", "failure:rejected",
                "start:throwing", "failure:throwing",
                "start:final"), fixture.events);
        assertEquals(1, rejected.failureCauses.size());
        assertTrue(rejected.failureCauses.get(0) instanceof IllegalStateException);
        assertEquals(1, throwing.failureCauses.size());
        assertSame(startFailure, throwing.failureCauses.get(0));
        assertEquals(34L, fixture.queue.activeToken());
    }

    @Test
    public void failAllCancelsActiveThenFailsActiveAndQueuedInFifoOrder() {
        Fixture fixture = new Fixture();
        RecordingOperation active = fixture.operation("active", 41);
        RecordingOperation queuedOne = fixture.operation("queued-one", 42);
        RecordingOperation queuedTwo = fixture.operation("queued-two", 43);
        fixture.queue.enqueue(active);
        fixture.queue.enqueue(queuedOne);
        fixture.queue.enqueue(queuedTwo);
        ManualTimeout activeTimeout = fixture.scheduler.handles.get(0);
        RuntimeException disconnect = new RuntimeException("disconnected");

        fixture.queue.failAll(disconnect);

        assertTrue(activeTimeout.cancelled);
        assertEquals(Arrays.asList(
                "start:active",
                "failure:active",
                "failure:queued-one",
                "failure:queued-two"), fixture.events);
        assertSame(disconnect, active.failureCauses.get(0));
        assertSame(disconnect, queuedOne.failureCauses.get(0));
        assertSame(disconnect, queuedTwo.failureCauses.get(0));
        assertEquals(0L, fixture.queue.activeToken());
        assertEquals(0, fixture.queue.pendingCount());

        activeTimeout.fireEvenIfCancelled();
        assertFalse(fixture.queue.complete(41, 0));
        assertEquals(1, active.failureCauses.size());
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.failAll(null);
            }
        });
    }

    @Test
    public void failAllRejectsReentrantEnqueueAndReturnsEmptyIdle() {
        final Fixture fixture = new Fixture();
        final RecordingOperation attempted = fixture.operation("attempted", 82);
        final RuntimeException[] rejection = new RuntimeException[1];
        RecordingOperation active = fixture.operation("active", 81)
                .failingWith(new Runnable() {
                    @Override public void run() {
                        try {
                            fixture.queue.enqueue(attempted);
                        } catch (RuntimeException expected) {
                            rejection[0] = expected;
                        }
                    }
                });
        fixture.queue.enqueue(active);

        fixture.queue.failAll(new RuntimeException("disconnect"));

        assertTrue(rejection[0] instanceof IllegalStateException);
        assertEquals(0L, fixture.queue.activeToken());
        assertEquals(0, fixture.queue.pendingCount());
        assertEquals(Arrays.asList("start:active", "failure:active"), fixture.events);

        fixture.queue.enqueue(attempted);
        assertEquals(82L, fixture.queue.activeToken());
        assertEquals(Arrays.asList(
                "start:active", "failure:active", "start:attempted"), fixture.events);
    }

    @Test
    public void tokensRetireAfterStartFailureTimeoutAndFailAll() {
        final Fixture fixture = new Fixture();
        fixture.queue.enqueue(fixture.operation("start-rejected", 91)
                .startingWith(false));
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("reuse-start-failure", 91));
            }
        });

        fixture.queue.enqueue(fixture.operation("timeout", 92));
        fixture.scheduler.handles.get(fixture.scheduler.handles.size() - 1)
                .fireEvenIfCancelled();
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("reuse-timeout", 92));
            }
        });

        fixture.queue.enqueue(fixture.operation("active-fail-all", 93));
        fixture.queue.enqueue(fixture.operation("queued-fail-all", 94));
        fixture.queue.failAll(new RuntimeException("disconnect"));
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("reuse-active-fail-all", 93));
            }
        });
        assertRejected(new Action() {
            @Override public void run() {
                fixture.queue.enqueue(fixture.operation("reuse-queued-fail-all", 94));
            }
        });
        assertEquals(0L, fixture.queue.activeToken());
        assertEquals(0, fixture.queue.pendingCount());
    }

    @Test
    public void reentrantEnqueueAndCompletionPreserveOrderAndSingleStart() {
        final Fixture fixture = new Fixture();
        final boolean[] prematureCompletion = new boolean[1];
        RecordingOperation gate = fixture.operation("gate", 51);
        final RecordingOperation synchronous = fixture.operation("synchronous", 52);
        RecordingOperation after = fixture.operation("after", 53);
        final RecordingOperation tail = fixture.operation("tail", 54);

        gate.completingWith(new Runnable() {
            @Override public void run() {
                fixture.queue.enqueue(tail);
                prematureCompletion[0] = fixture.queue.complete(52, 999);
            }
        });
        synchronous.startingWith(new Runnable() {
            @Override public void run() {
                assertTrue(fixture.queue.complete(52, 202));
            }
        });

        fixture.queue.enqueue(gate);
        fixture.queue.enqueue(synchronous);
        fixture.queue.enqueue(after);
        assertTrue(fixture.queue.complete(51, 101));

        assertFalse(prematureCompletion[0]);
        assertEquals(Arrays.asList(
                "start:gate", "complete:gate:101",
                "start:synchronous", "complete:synchronous:202",
                "start:after"), fixture.events);
        assertEquals(53L, fixture.queue.activeToken());
        assertEquals(1, fixture.queue.pendingCount());

        fixture.queue.complete(53, 303);
        fixture.queue.complete(54, 404);
        assertEquals(Arrays.asList(
                "start:gate", "complete:gate:101",
                "start:synchronous", "complete:synchronous:202",
                "start:after", "complete:after:303",
                "start:tail", "complete:tail:404"), fixture.events);
    }

    @Test
    public void timeoutCallbackMayRunBeforeSchedulerReturnsWithoutDoubleDelivery() {
        List<String> events = new ArrayList<String>();
        ImmediateScheduler scheduler = new ImmediateScheduler();
        GattOperationQueue queue = new GattOperationQueue(new FakeDriver(), scheduler);
        RecordingOperation operation = new RecordingOperation("immediate", 61, 1000, events);

        queue.enqueue(operation);

        assertEquals(Arrays.asList("start:immediate", "failure:immediate"), events);
        assertEquals(1, operation.failureCauses.size());
        assertTrue(operation.failureCauses.get(0) instanceof GattOperationQueue.TimeoutFailure);
        assertTrue(scheduler.handle.cancelled);
        assertEquals(0L, queue.activeToken());
        assertEquals(0, queue.pendingCount());
    }

    @Test
    public void constructorRejectsMissingDriverOrScheduler() {
        assertRejected(new Action() {
            @Override public void run() {
                new GattOperationQueue(null, new ManualScheduler());
            }
        });
        assertRejected(new Action() {
            @Override public void run() {
                new GattOperationQueue(new FakeDriver(), null);
            }
        });
    }

    private interface Action {
        void run();
    }

    private static void assertRejected(Action action) {
        try {
            action.run();
            fail("expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    private static final class Fixture {
        final List<String> events = new ArrayList<String>();
        final ManualScheduler scheduler = new ManualScheduler();
        final GattOperationQueue queue =
                new GattOperationQueue(new FakeDriver(), scheduler);

        RecordingOperation operation(String name, long token) {
            return operation(name, token, 5000);
        }

        RecordingOperation operation(String name, long token, long timeoutMs) {
            return new RecordingOperation(name, token, timeoutMs, events);
        }
    }

    private static final class FakeDriver implements GattOperationQueue.Driver {
    }

    private static final class RecordingOperation implements GattOperationQueue.Operation {
        final String name;
        final long token;
        final long timeoutMs;
        final List<String> events;
        final List<Throwable> failureCauses = new ArrayList<Throwable>();
        boolean startResult = true;
        RuntimeException startFailure;
        Runnable startHook;
        Runnable completionHook;
        Runnable failureHook;
        int completionCount;

        RecordingOperation(String name, long token, long timeoutMs, List<String> events) {
            this.name = name;
            this.token = token;
            this.timeoutMs = timeoutMs;
            this.events = events;
        }

        RecordingOperation startingWith(boolean result) {
            startResult = result;
            return this;
        }

        RecordingOperation startingWith(Runnable hook) {
            startHook = hook;
            return this;
        }

        RecordingOperation throwingOnStart(RuntimeException failure) {
            startFailure = failure;
            return this;
        }

        RecordingOperation completingWith(Runnable hook) {
            completionHook = hook;
            return this;
        }

        RecordingOperation failingWith(Runnable hook) {
            failureHook = hook;
            return this;
        }

        @Override public long token() {
            return token;
        }

        @Override public long timeoutMs() {
            return timeoutMs;
        }

        @Override public boolean start(GattOperationQueue.Driver driver) {
            events.add("start:" + name);
            if (startFailure != null) {
                throw startFailure;
            }
            if (startHook != null) {
                startHook.run();
            }
            return startResult;
        }

        @Override public void onComplete(int status) {
            completionCount++;
            events.add("complete:" + name + ":" + status);
            if (completionHook != null) {
                completionHook.run();
            }
        }

        @Override public void onFailure(Throwable cause) {
            failureCauses.add(cause);
            events.add("failure:" + name);
            if (failureHook != null) {
                failureHook.run();
            }
        }
    }

    private static class ManualScheduler implements GattOperationQueue.Scheduler {
        final List<ManualTimeout> handles = new ArrayList<ManualTimeout>();

        @Override public GattOperationQueue.TimeoutHandle schedule(
                long timeoutMs, Runnable callback) {
            ManualTimeout handle = new ManualTimeout(timeoutMs, callback);
            handles.add(handle);
            return handle;
        }
    }

    private static final class ImmediateScheduler implements GattOperationQueue.Scheduler {
        ManualTimeout handle;

        @Override public GattOperationQueue.TimeoutHandle schedule(
                long timeoutMs, Runnable callback) {
            handle = new ManualTimeout(timeoutMs, callback);
            callback.run();
            return handle;
        }
    }

    private static final class SelfAwareScheduler implements GattOperationQueue.Scheduler {
        SelfAwareTimeout handle;

        @Override public GattOperationQueue.TimeoutHandle schedule(
                long timeoutMs, Runnable callback) {
            handle = new SelfAwareTimeout(callback);
            return handle;
        }
    }

    private static final class SelfAwareTimeout
            implements GattOperationQueue.TimeoutHandle {
        final Runnable callback;
        boolean insideCallback;
        boolean cancelled;

        SelfAwareTimeout(Runnable callback) {
            this.callback = callback;
        }

        @Override public void cancel() {
            if (insideCallback) {
                throw new IllegalStateException(
                        "timeout attempted to cancel its own executing handle");
            }
            cancelled = true;
        }

        void fire() {
            insideCallback = true;
            try {
                callback.run();
            } finally {
                insideCallback = false;
            }
        }
    }

    private static final class ManualTimeout implements GattOperationQueue.TimeoutHandle {
        final long timeoutMs;
        final Runnable callback;
        boolean cancelled;

        ManualTimeout(long timeoutMs, Runnable callback) {
            this.timeoutMs = timeoutMs;
            this.callback = callback;
        }

        @Override public void cancel() {
            cancelled = true;
        }

        void fireEvenIfCancelled() {
            callback.run();
        }
    }
}
