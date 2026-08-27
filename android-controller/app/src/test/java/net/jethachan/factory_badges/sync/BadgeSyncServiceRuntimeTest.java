package net.jethachan.factory_badges.sync;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BuildInfo;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.ConnectionSnapshot;
import org.junit.Test;

public final class BadgeSyncServiceRuntimeTest {
    // Mutation caught: the runtime accepts a null initial snapshot or port.
    @Test
    public void constructorRejectsNullInputs() {
        ConnectionSnapshot initial = disabledSnapshot();
        BleQueue ble = new BleQueue();
        MainQueue main = new MainQueue();
        Foreground foreground = new Foreground();
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncServiceRuntime(null, ble, main, foreground));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncServiceRuntime(initial, null, main, foreground));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncServiceRuntime(initial, ble, null, foreground));
        assertThrows(IllegalArgumentException.class,
                () -> new BadgeSyncServiceRuntime(initial, ble, main, null));
    }

    // Mutation caught: null or unknown starts become sticky or queue controller work.
    @Test
    public void nullAndUnknownActionsAreNotStickyAndHaveNoSideEffect() {
        Harness harness = new Harness();
        Counter enable = new Counter();
        Counter disable = new Counter();

        assertEquals(2, harness.runtime.onStartCommand(null, enable, disable));
        assertEquals(2, harness.runtime.onStartCommand("unexpected", enable, disable));

        assertEquals(0, harness.ble.tasks.size());
        assertTrue(harness.foreground.events.isEmpty());
        assertEquals(0, enable.count);
        assertEquals(0, disable.count);
    }

    // Mutation caught: enable posts before foreground promotion or runs more than once.
    @Test
    public void enablePromotesBeforePostingAndRunsExactlyOnce() {
        List<String> order = new ArrayList<String>();
        Harness harness = new Harness(order);
        Counter enable = new Counter();

        assertEquals(2, harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                enable,
                new Counter()));

        assertEquals("promote:WAITING", order.get(0));
        assertEquals("ble-post", order.get(1));
        assertEquals(0, enable.count);
        harness.ble.runNext();
        assertEquals(1, enable.count);
        assertEquals(0, harness.ble.tasks.size());
    }

    // Mutation caught: disable promotes or invokes the enable mutation.
    @Test
    public void disablePostsOnlyTheDisableMutation() {
        Harness harness = new Harness();
        Counter enable = new Counter();
        Counter disable = new Counter();

        assertEquals(2, harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.DISABLE_BADGE_SYNC",
                enable,
                disable));

        assertTrue(harness.foreground.events.isEmpty());
        assertEquals(1, harness.ble.tasks.size());
        harness.ble.runNext();
        assertEquals(0, enable.count);
        assertEquals(1, disable.count);
    }

    // Mutation caught: a rejected BLE post is treated as queued controller work.
    @Test
    public void rejectedBlePostStopsEnableForegroundAndRejectsBinderWork() {
        Harness harness = new Harness();
        harness.ble.accepted = false;
        Counter enable = new Counter();

        assertEquals(2, harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                enable,
                new Counter()));

        assertEquals(0, enable.count);
        assertEquals(0, harness.ble.tasks.size());
        assertEquals(java.util.Arrays.asList(
                        "promote:WAITING", "stop"),
                harness.foreground.events);
        IllegalStateException failure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.postBinderMutation(new Counter()));
        assertEquals("BLE worker is unavailable", failure.getMessage());
    }

    // Mutation caught: a binder mutation bypasses the guarded BLE queue.
    @Test
    public void acceptedBinderMutationRunsOnlyFromItsQueuedRunnable() {
        Harness harness = new Harness();
        Counter mutation = new Counter();

        harness.runtime.postBinderMutation(mutation);

        assertEquals(0, mutation.count);
        harness.ble.runNext();
        assertEquals(1, mutation.count);
    }
    // Mutation caught: repeated enable/start callbacks promote the same foreground twice.
    @Test
    public void repeatedEnableAndControllerStartDoNotDuplicatePromotion() {
        Harness harness = new Harness();
        Counter enable = new Counter();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                enable,
                new Counter());

        harness.runtime.onControllerForegroundStart();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                enable,
                new Counter());

        assertEquals(java.util.Arrays.asList("promote:WAITING"),
                harness.foreground.events);
    }

    // Mutation caught: latestSnapshot waits for main delivery or maps READY incorrectly.
    @Test
    public void snapshotChangesImmediatelyAndNotificationUpdatesOnMain() {
        Harness harness = new Harness();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.foreground.events.clear();
        ConnectionSnapshot ready = snapshot(ConnectionSnapshot.Phase.READY);

        harness.runtime.onSnapshot(ready);

        assertEquals(ready, harness.runtime.latestSnapshot());
        assertTrue(harness.foreground.events.isEmpty());
        assertEquals(1, harness.main.tasks.size());
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList("update:READY"),
                harness.foreground.events);
    }

    // Mutation caught: any one of the nine phases selects the wrong notification kind.
    @Test
    public void everyPhaseMapsToItsExactNotificationKind() {
        ConnectionSnapshot.Phase[] phases = new ConnectionSnapshot.Phase[] {
            ConnectionSnapshot.Phase.DISABLED,
            ConnectionSnapshot.Phase.NO_DEVICE,
            ConnectionSnapshot.Phase.BONDING,
            ConnectionSnapshot.Phase.CONNECTING,
            ConnectionSnapshot.Phase.DISCOVERING,
            ConnectionSnapshot.Phase.VALIDATING_BUILD,
            ConnectionSnapshot.Phase.READY,
            ConnectionSnapshot.Phase.RETRY_WAIT,
            ConnectionSnapshot.Phase.ERROR
        };
        String[] kinds = new String[] {
            "WAITING", "WAITING",
            "CONNECTING", "CONNECTING", "CONNECTING", "CONNECTING",
            "READY", "RETRY", "ERROR"
        };
        Harness harness = new Harness();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.foreground.events.clear();

        for (int index = 0; index < phases.length; index++) {
            harness.runtime.onSnapshot(snapshot(phases[index]));
            harness.main.runNext();
            assertEquals("update:" + kinds[index],
                    harness.foreground.events.get(index));
        }
    }

    // Mutation caught: a queued stop from generation N stops re-enabled generation N+1.
    @Test
    public void staleStopCannotStopAReenabledForeground() {
        Harness harness = new Harness();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.foreground.events.clear();

        harness.runtime.onControllerForegroundStop();
        harness.runtime.onControllerForegroundStart();
        assertEquals(1, harness.main.tasks.size());
        harness.main.runNext();
        assertTrue(harness.foreground.events.isEmpty());

        harness.runtime.onControllerForegroundStop();
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList("stop"),
                harness.foreground.events);
    }

    // Mutation caught: a rejected main post invokes a foreground port on BLE.
    @Test
    public void rejectedMainPostPerformsNoForegroundCallback() {
        Harness harness = new Harness();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.foreground.events.clear();
        harness.main.accepted = false;

        harness.runtime.onSnapshot(snapshot(ConnectionSnapshot.Phase.READY));
        harness.runtime.onControllerForegroundStop();

        assertTrue(harness.foreground.events.isEmpty());
        assertTrue(harness.main.tasks.isEmpty());
    }

    // Mutation caught: a rejected controller-start post leaves desire stuck true.
    @Test
    public void rejectedControllerStartCanBeRetriedOnAnAvailableMainQueue() {
        Harness harness = new Harness();
        harness.main.accepted = false;

        harness.runtime.onControllerForegroundStart();
        harness.main.accepted = true;
        harness.runtime.onControllerForegroundStart();

        assertEquals(1, harness.main.tasks.size());
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList("promote:WAITING"),
                harness.foreground.events);
    }

    // Mutation caught: a false main post is ignored when its Runnable leaks.
    @Test
    public void rejectedLeakedMainCallbacksCannotReachForegroundOrListenerPorts() {
        Harness harness = new Harness();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.foreground.events.clear();
        Object identity = new Object();
        Delivery delivery = new Delivery();
        harness.runtime.addSnapshotListener(identity, delivery);
        harness.main.runNext();
        delivery.snapshots.clear();
        harness.main.accepted = false;
        harness.main.enqueueWhenRejected = true;

        harness.runtime.onSnapshot(snapshot(ConnectionSnapshot.Phase.READY));
        harness.runtime.onControllerForegroundStop();
        while (!harness.main.tasks.isEmpty()) {
            harness.main.runNext();
        }

        assertTrue(harness.foreground.events.isEmpty());
        assertTrue(delivery.snapshots.isEmpty());
    }

    // Mutation caught: the runtime accepts a null snapshot.
    @Test
    public void snapshotRejectsNull() {
        Harness harness = new Harness();
        assertThrows(IllegalArgumentException.class,
                () -> harness.runtime.onSnapshot(null));
    }

    private static ConnectionSnapshot snapshot(ConnectionSnapshot.Phase phase) {
        BadgeState state = new BadgeState(12, 34, 1727L);
        String name = null;
        String address = null;
        boolean enabled = phase != ConnectionSnapshot.Phase.DISABLED;
        boolean bonded = false;
        BuildInfo build = null;
        Long delay = null;
        UserVisibleError error = null;
        if (phase != ConnectionSnapshot.Phase.DISABLED
                && phase != ConnectionSnapshot.Phase.NO_DEVICE) {
            name = "E87";
            address = "AA:BB:CC:DD:EE:FF";
            bonded = phase != ConnectionSnapshot.Phase.BONDING;
        }
        if (phase == ConnectionSnapshot.Phase.READY) {
            build = semanticBuild();
        } else if (phase == ConnectionSnapshot.Phase.RETRY_WAIT) {
            delay = Long.valueOf(1000L);
            error = new UserVisibleError(
                    UserVisibleError.Code.CONNECT_FAILED, 7);
        } else if (phase == ConnectionSnapshot.Phase.ERROR) {
            error = new UserVisibleError(
                    UserVisibleError.Code.UNSUPPORTED_BADGE);
        }
        return new ConnectionSnapshot(
                enabled,
                phase,
                name,
                address,
                bonded,
                state,
                build,
                null,
                null,
                null,
                delay,
                error);
    }

    private static BuildInfo semanticBuild() {
        return new BuildInfo(
                1,
                "E87-JD9855-R1",
                1,
                2,
                3,
                new byte[] {
                    0, 1, 2, 3, 4, 5, 6, 7,
                    8, 9, 10, 11, 12, 13, 14, 15
                });
    }

    // Mutation caught: listener registration or removal is accepted off the main thread.
    @Test
    public void listenerMembershipRequiresMainThread() {
        Harness harness = new Harness();
        harness.main.mainThread = false;
        Object identity = new Object();
        Delivery delivery = new Delivery();

        IllegalStateException addFailure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.addSnapshotListener(identity, delivery));
        assertEquals("snapshot listeners require main thread",
                addFailure.getMessage());
        IllegalStateException removeFailure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.removeSnapshotListener(identity));
        assertEquals("snapshot listeners require main thread",
                removeFailure.getMessage());
    }

    // Mutation caught: duplicate listener identity receives duplicate initial deliveries.
    @Test
    public void duplicateListenerAddPostsOneCurrentSnapshot() {
        Harness harness = new Harness();
        Object identity = new Object();
        Delivery delivery = new Delivery();

        harness.runtime.addSnapshotListener(identity, delivery);
        harness.runtime.addSnapshotListener(identity, delivery);

        assertEquals(1, harness.main.tasks.size());
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList(disabledSnapshot()),
                delivery.snapshots);
    }

    // Mutation caught: removal does not invalidate an already queued listener delivery.
    @Test
    public void removeAndReaddInvalidatesOldListenerToken() {
        Harness harness = new Harness();
        Object identity = new Object();
        Delivery first = new Delivery();
        Delivery second = new Delivery();

        harness.runtime.addSnapshotListener(identity, first);
        harness.runtime.removeSnapshotListener(identity);
        harness.runtime.addSnapshotListener(identity, second);

        assertEquals(2, harness.main.tasks.size());
        harness.main.runNext();
        assertTrue(first.snapshots.isEmpty());
        assertTrue(second.snapshots.isEmpty());
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList(disabledSnapshot()),
                second.snapshots);
    }

    // Mutation caught: snapshot delivery runs immediately or ignores current membership.
    @Test
    public void snapshotListenerReceivesAcceptedMainDeliveryOnlyWhileRegistered() {
        Harness harness = new Harness();
        Object identity = new Object();
        Delivery delivery = new Delivery();
        harness.runtime.addSnapshotListener(identity, delivery);
        harness.main.runNext();
        delivery.snapshots.clear();
        ConnectionSnapshot ready = snapshot(ConnectionSnapshot.Phase.READY);

        harness.runtime.onSnapshot(ready);

        assertTrue(delivery.snapshots.isEmpty());
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList(ready), delivery.snapshots);
        harness.runtime.removeSnapshotListener(identity);
        harness.runtime.onSnapshot(disabledSnapshot());
        assertEquals(1, delivery.snapshots.size());
    }

    // Mutation caught: a rejected initial listener post remains registered or counts delivered.
    @Test
    public void rejectedInitialListenerPostRemovesRegistration() {
        Harness harness = new Harness();
        Object identity = new Object();
        Delivery delivery = new Delivery();
        harness.main.accepted = false;

        IllegalStateException failure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.addSnapshotListener(identity, delivery));

        assertEquals("main thread is unavailable", failure.getMessage());
        assertTrue(delivery.snapshots.isEmpty());
        harness.main.accepted = true;
        harness.runtime.addSnapshotListener(identity, delivery);
        assertEquals(1, harness.main.tasks.size());
    }

    // Mutation caught: null listener values enter the registry.
    @Test
    public void listenerMethodsRejectNullValues() {
        Harness harness = new Harness();
        assertThrows(IllegalArgumentException.class,
                () -> harness.runtime.addSnapshotListener(
                        null, new Delivery()));
        assertThrows(IllegalArgumentException.class,
                () -> harness.runtime.addSnapshotListener(
                        new Object(), null));
        assertThrows(IllegalArgumentException.class,
                () -> harness.runtime.removeSnapshotListener(null));
    }
    // Mutation caught: destroy marks the runtime only inside its later BLE cleanup.
    @Test
    public void destroySynchronouslyGatesQueuedWorkAndStopsForeground() {
        Harness harness = new Harness();
        Counter enable = new Counter();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                enable,
                new Counter());
        harness.ble.runNext();
        Counter pending = new Counter();
        harness.runtime.postBinderMutation(pending);
        Object identity = new Object();
        Delivery delivery = new Delivery();
        harness.runtime.addSnapshotListener(identity, delivery);
        RecordingDestroy destroy = new RecordingDestroy(harness.ble, false);

        harness.runtime.destroy(destroy);

        assertEquals(java.util.Arrays.asList(
                        "promote:WAITING", "stop"),
                harness.foreground.events);
        IllegalStateException unavailable = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.postBinderMutation(new Counter()));
        assertEquals("BLE worker is unavailable", unavailable.getMessage());
        harness.main.runNext();
        assertTrue(delivery.snapshots.isEmpty());
        harness.ble.runNext();
        assertEquals(0, pending.count);
        harness.ble.runNext();
        assertEquals(java.util.Arrays.asList("close", "quit"), destroy.events);
    }

    // Mutation caught: controller close and BLE quit use different Runnables or wrong order.
    @Test
    public void destroyCleanupClosesThenQuitsInSameRunnableEvenWhenCloseThrows() {
        Harness harness = new Harness();
        RecordingDestroy destroy = new RecordingDestroy(harness.ble, true);
        harness.runtime.destroy(destroy);

        assertThrows(RuntimeException.class, () -> harness.ble.runNext());

        assertEquals(java.util.Arrays.asList("close", "quit"), destroy.events);
        assertEquals(2, destroy.identities.size());
        assertTrue(destroy.identities.get(0) == destroy.identities.get(1));
        assertTrue(destroy.identities.get(0) != null);
    }

    // Mutation caught: a rejected cleanup post closes the controller on main.
    @Test
    public void rejectedCleanupPostQuitsOnlyOnTheCallerPath() {
        Harness harness = new Harness();
        harness.ble.accepted = false;
        RecordingDestroy destroy = new RecordingDestroy(harness.ble, false);

        harness.runtime.destroy(destroy);

        assertEquals(java.util.Arrays.asList("quit"), destroy.events);
        assertEquals(1, destroy.identities.size());
        assertTrue(destroy.identities.get(0) == null);
    }

    // Mutation caught: duplicate destroy posts cleanup or stops foreground twice.
    @Test
    public void duplicateDestroyHasNoSideEffect() {
        Harness harness = new Harness();
        RecordingDestroy destroy = new RecordingDestroy(harness.ble, false);

        harness.runtime.destroy(destroy);
        harness.runtime.destroy(destroy);

        assertEquals(1, harness.ble.tasks.size());
        harness.ble.runNext();
        assertEquals(java.util.Arrays.asList("close", "quit"), destroy.events);
    }

    // Mutation caught: destroy accepts null or executes off main.
    @Test
    public void destroyRejectsNullAndRequiresMainThread() {
        Harness harness = new Harness();
        assertThrows(IllegalArgumentException.class,
                () -> harness.runtime.destroy(null));
        harness.main.mainThread = false;
        assertThrows(IllegalStateException.class,
                () -> harness.runtime.destroy(
                        new RecordingDestroy(harness.ble, false)));
        assertTrue(harness.ble.tasks.isEmpty());
    }
    // Mutation caught: a queued BLE callback omits captured-token equality.
    @Test
    public void queuedMutationWithChangedLifecycleTokenIsIneligible()
            throws Exception {
        Harness harness = new Harness();
        Counter pending = new Counter();
        harness.runtime.postBinderMutation(pending);
        seedCounter(harness.runtime, "lifecycleToken", Long.MAX_VALUE);

        harness.ble.runNext();

        assertEquals(0, pending.count);
    }

    // Mutation caught: a stale queued promote wins with its old notification kind.
    @Test
    public void stalePromoteCannotWinAfterForegroundGenerationChanges() {
        Harness harness = new Harness();
        harness.runtime.onControllerForegroundStart();
        harness.runtime.onControllerForegroundStop();
        harness.runtime.onSnapshot(snapshot(ConnectionSnapshot.Phase.READY));
        harness.runtime.onControllerForegroundStart();

        assertEquals(2, harness.main.tasks.size());
        harness.main.runNext();
        assertTrue(harness.foreground.events.isEmpty());
        harness.main.runNext();
        assertEquals(java.util.Arrays.asList("promote:READY"),
                harness.foreground.events);
    }

    // Mutation caught: a runtime generation reuses its previous positive token.
    @Test
    public void runtimeCountersAdvanceStrictlyAcrossTransitions()
            throws Exception {
        Harness foregroundHarness = new Harness();
        long firstForeground = readCounter(
                foregroundHarness.runtime, "foregroundGeneration");
        foregroundHarness.runtime.onControllerForegroundStart();
        long secondForeground = readCounter(
                foregroundHarness.runtime, "foregroundGeneration");
        foregroundHarness.runtime.onControllerForegroundStop();
        long thirdForeground = readCounter(
                foregroundHarness.runtime, "foregroundGeneration");
        assertTrue(firstForeground > 0L);
        assertTrue(secondForeground > firstForeground);
        assertTrue(thirdForeground > secondForeground);

        Harness listenerHarness = new Harness();
        Object identity = new Object();
        listenerHarness.runtime.addSnapshotListener(identity, new Delivery());
        long firstListener = readCounter(
                listenerHarness.runtime, "listenerToken");
        listenerHarness.runtime.removeSnapshotListener(identity);
        listenerHarness.runtime.addSnapshotListener(identity, new Delivery());
        long secondListener = readCounter(
                listenerHarness.runtime, "listenerToken");
        assertTrue(firstListener > 0L);
        assertTrue(secondListener > firstListener);

        Harness lifecycleHarness = new Harness();
        long firstLifecycle = readCounter(
                lifecycleHarness.runtime, "lifecycleToken");
        lifecycleHarness.runtime.destroy(
                new RecordingDestroy(lifecycleHarness.ble, false));
        long secondLifecycle = readCounter(
                lifecycleHarness.runtime, "lifecycleToken");
        assertTrue(firstLifecycle > 0L);
        assertTrue(secondLifecycle > firstLifecycle);
    }

    // Mutation caught: lifecycle token wraps or posts ordinary work at Long.MAX_VALUE.
    @Test
    public void lifecycleTokenExhaustionFailsClosedBeforeOrdinaryPost()
            throws Exception {
        Harness harness = new Harness();
        seedCounter(harness.runtime, "lifecycleToken", Long.MAX_VALUE);
        Counter mutation = new Counter();

        IllegalStateException failure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.postBinderMutation(mutation));

        assertEquals("service generation exhausted", failure.getMessage());
        assertEquals(0, mutation.count);
        assertTrue(harness.ble.tasks.isEmpty());
        assertTrue(harness.ble.order.isEmpty());
        assertEquals(Long.MAX_VALUE,
                readCounter(harness.runtime, "lifecycleToken"));
        RecordingDestroy destroy = new RecordingDestroy(harness.ble, false);
        harness.runtime.destroy(destroy);
        harness.ble.runNext();
        assertEquals(java.util.Arrays.asList("close", "quit"), destroy.events);
    }

    // Mutation caught: foreground generation wraps and promotes before exhaustion gating.
    @Test
    public void foregroundGenerationExhaustionRejectsActionBeforePorts()
            throws Exception {
        Harness harness = new Harness();
        seedCounter(harness.runtime, "foregroundGeneration", Long.MAX_VALUE);

        assertEquals(2, harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter()));

        assertTrue(harness.foreground.events.isEmpty());
        assertTrue(harness.ble.tasks.isEmpty());
        assertTrue(harness.ble.order.isEmpty());
        IllegalStateException failure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.postBinderMutation(new Counter()));
        assertEquals("service generation exhausted", failure.getMessage());
        assertEquals(Long.MAX_VALUE,
                readCounter(harness.runtime, "foregroundGeneration"));
    }

    // Mutation caught: exhaustion leaves an already-promoted foreground running.
    @Test
    public void foregroundExhaustionStopsAnExistingPromotionOnMain()
            throws Exception {
        Harness harness = new Harness();
        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.ble.runNext();
        harness.foreground.events.clear();
        seedCounter(harness.runtime, "foregroundGeneration", Long.MAX_VALUE);

        harness.runtime.onControllerForegroundStop();

        assertEquals(java.util.Arrays.asList("stop"),
                harness.foreground.events);
        assertTrue(harness.main.tasks.isEmpty());
    }

    // Mutation caught: listener tokens wrap and register a reused identity token.
    @Test
    public void listenerTokenExhaustionRegistersNothing() throws Exception {
        Harness harness = new Harness();
        seedCounter(harness.runtime, "listenerToken", Long.MAX_VALUE);

        IllegalStateException failure = assertThrows(
                IllegalStateException.class,
                () -> harness.runtime.addSnapshotListener(
                        new Object(), new Delivery()));

        assertEquals("service generation exhausted", failure.getMessage());
        assertTrue(harness.main.tasks.isEmpty());
        assertEquals(Long.MAX_VALUE,
                readCounter(harness.runtime, "listenerToken"));
    }

    // Mutation caught: work queued before generation exhaustion still executes afterward.
    @Test
    public void queuedOrdinaryWorkIsGatedAfterGenerationExhaustion()
            throws Exception {
        Harness harness = new Harness();
        Counter pending = new Counter();
        harness.runtime.postBinderMutation(pending);
        seedCounter(harness.runtime, "foregroundGeneration", Long.MAX_VALUE);

        harness.runtime.onStartCommand(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC",
                new Counter(),
                new Counter());
        harness.ble.runNext();

        assertEquals(0, pending.count);
    }

    // Mutation caught: a service adapter owns a second action/lifecycle policy path.
    @Test
    public void serviceAdapterContractRunsEntireLifecycleThroughRuntime() {
        ServiceContractFake service = new ServiceContractFake();

        assertEquals(2, service.start(
                "net.jethachan.factory_badges.action.ENABLE_BADGE_SYNC"));
        assertEquals(java.util.Arrays.asList("create"),
                service.adapterEvents);
        assertEquals(java.util.Arrays.asList("promote:WAITING"),
                service.harness.foreground.events);
        service.harness.ble.runNext();
        assertEquals(java.util.Arrays.asList("create", "enable-handler"),
                service.adapterEvents);
        service.harness.main.runNext();
        assertEquals(java.util.Arrays.asList(
                        "promote:WAITING", "update:READY"),
                service.harness.foreground.events);

        assertEquals(2, service.start(
                "net.jethachan.factory_badges.action.DISABLE_BADGE_SYNC"));
        service.harness.ble.runNext();
        service.harness.main.runNext();
        assertEquals(java.util.Arrays.asList(
                        "promote:WAITING", "update:READY", "stop"),
                service.harness.foreground.events);

        service.destroy();
        service.harness.ble.runNext();
        assertEquals(java.util.Arrays.asList(
                        "create", "enable-handler", "disable-handler"),
                service.adapterEvents);
        assertEquals(java.util.Arrays.asList("close", "quit"),
                service.destroy.events);
    }

    private static void seedCounter(
            BadgeSyncServiceRuntime runtime, String name, long value)
            throws Exception {
        Field field = BadgeSyncServiceRuntime.class.getDeclaredField(name);
        field.setAccessible(true);
        field.setLong(runtime, value);
    }

    private static long readCounter(
            BadgeSyncServiceRuntime runtime, String name) throws Exception {
        Field field = BadgeSyncServiceRuntime.class.getDeclaredField(name);
        field.setAccessible(true);
        return field.getLong(runtime);
    }
    private static ConnectionSnapshot disabledSnapshot() {
        return new ConnectionSnapshot(
                false,
                ConnectionSnapshot.Phase.DISABLED,
                null,
                null,
                false,
                new BadgeState(0, 0, 1727L),
                null,
                null,
                null,
                null,
                null,
                null);
    }

    private static final class ServiceContractFake {
        final Harness harness = new Harness();
        final List<String> adapterEvents = new ArrayList<String>();
        final RecordingDestroy destroy =
                new RecordingDestroy(harness.ble, false);

        ServiceContractFake() {
            adapterEvents.add("create");
        }

        int start(String action) {
            return harness.runtime.onStartCommand(
                    action,
                    new Runnable() {
                        @Override
                        public void run() {
                            adapterEvents.add("enable-handler");
                            harness.runtime.onControllerForegroundStart();
                            harness.runtime.onSnapshot(
                                    snapshot(ConnectionSnapshot.Phase.READY));
                        }
                    },
                    new Runnable() {
                        @Override
                        public void run() {
                            adapterEvents.add("disable-handler");
                            harness.runtime.onControllerForegroundStop();
                        }
                    });
        }

        void destroy() {
            harness.runtime.destroy(destroy);
        }
    }

    private static final class Harness {
        final BleQueue ble;
        final MainQueue main;
        final Foreground foreground;
        final BadgeSyncServiceRuntime runtime;

        Harness() {
            ble = new BleQueue();
            main = new MainQueue();
            foreground = new Foreground();
            runtime = new BadgeSyncServiceRuntime(
                    disabledSnapshot(), ble, main, foreground);
        }

        Harness(List<String> order) {
            ble = new BleQueue(order);
            main = new MainQueue();
            foreground = new Foreground(order);
            runtime = new BadgeSyncServiceRuntime(
                    disabledSnapshot(), ble, main, foreground);
        }
    }


    private static final class Delivery
            implements BadgeSyncServiceRuntime.SnapshotDelivery {
        final List<ConnectionSnapshot> snapshots =
                new ArrayList<ConnectionSnapshot>();

        @Override
        public void deliver(ConnectionSnapshot snapshot) {
            snapshots.add(snapshot);
        }
    }

    private static final class RecordingDestroy
            implements BadgeSyncServiceRuntime.DestroyPort {
        final BleQueue ble;
        final boolean throwOnClose;
        final List<String> events = new ArrayList<String>();
        final List<Runnable> identities = new ArrayList<Runnable>();

        RecordingDestroy(BleQueue ble, boolean throwOnClose) {
            this.ble = ble;
            this.throwOnClose = throwOnClose;
        }

        @Override
        public void closeController() {
            events.add("close");
            identities.add(ble.currentRunnable);
            if (throwOnClose) {
                throw new RuntimeException("close failed");
            }
        }

        @Override
        public void quitBleThreadSafely() {
            events.add("quit");
            identities.add(ble.currentRunnable);
        }
    }
    private static final class Counter implements Runnable {
        int count;

        @Override
        public void run() {
            count++;
        }
    }

    private static final class BleQueue
            implements BadgeSyncServiceRuntime.BlePoster {
        final List<Runnable> tasks = new ArrayList<Runnable>();
        final List<String> order;
        boolean accepted = true;
        Runnable currentRunnable;

        BleQueue() {
            this(new ArrayList<String>());
        }

        BleQueue(List<String> order) {
            this.order = order;
        }

        @Override
        public boolean post(Runnable task) {
            order.add("ble-post");
            if (!accepted) {
                return false;
            }
            tasks.add(task);
            return true;
        }

        void runNext() {
            currentRunnable = tasks.remove(0);
            try {
                currentRunnable.run();
            } finally {
                currentRunnable = null;
            }
        }
    }

    private static final class MainQueue
            implements BadgeSyncServiceRuntime.MainPoster {
        final List<Runnable> tasks = new ArrayList<Runnable>();
        boolean mainThread = true;
        boolean accepted = true;
        boolean enqueueWhenRejected;

        @Override
        public boolean isMainThread() {
            return mainThread;
        }

        @Override
        public boolean post(Runnable task) {
            if (!accepted) {
                if (enqueueWhenRejected) {
                    tasks.add(task);
                }
                return false;
            }
            tasks.add(task);
            return true;
        }

        void runNext() {
            Runnable task = tasks.remove(0);
            task.run();
        }
    }

    private static final class Foreground
            implements BadgeSyncServiceRuntime.ForegroundPort {
        final List<String> events;

        Foreground() {
            this(new ArrayList<String>());
        }

        Foreground(List<String> events) {
            this.events = events;
        }

        @Override
        public void promote(BadgeSyncServiceRuntime.NotificationKind kind) {
            events.add("promote:" + kind.name());
        }

        @Override
        public void update(BadgeSyncServiceRuntime.NotificationKind kind) {
            events.add("update:" + kind.name());
        }

        @Override
        public void stop() {
            events.add("stop");
        }
    }
}
