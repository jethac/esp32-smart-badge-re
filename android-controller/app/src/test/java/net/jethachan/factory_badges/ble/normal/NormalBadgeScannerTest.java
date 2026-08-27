package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

public final class NormalBadgeScannerTest {
    private static final byte[] NORMAL = bytes(
            "02 01 06 11 07 35 07 A7 01 9C 5D 0B 9F 62 4C 1B 7A 01 00 7D E8"
                    + " 04 09 45 38 37");

    // Mutation: bypass the reviewed parser or reject the exact normal vector.
    @Test public void coreAcceptsExactVectorAndRetainsLiteralCandidateFields() {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long token = core.begin();
        NormalBadgeScanner.Core.Candidate candidate = core.accept(
                token, "aA:Bb:cC:dD:eE:Ff", true, NORMAL);
        assertNotNull(candidate);
        assertEquals("E87", candidate.advertisedName());
        assertEquals("aA:Bb:cC:dD:eE:Ff", candidate.address());
        assertTrue(candidate.bonded());
        assertTrue(core.finish(token).foundAny());
    }

    // Mutation: accept a duplicate address or lose per-session foundAny.
    @Test public void duplicateIsSuppressedAndDistinctAddressAccepted() {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long token = core.begin();
        assertNotNull(core.accept(token, address(0), false, NORMAL));
        assertNull(core.accept(token, address(0), true, NORMAL));
        assertNotNull(core.accept(token, address(1), true, NORMAL));
        NormalBadgeScanner.Core.FinishResult finish = core.finish(token);
        assertTrue(finish.eligible());
        assertTrue(finish.foundAny());
    }

    // Mutation: treat differently cased spellings of one canonical MAC as distinct devices.
    @Test public void caseVariantAddressIsDuplicateAndFirstLiteralIsRetained() {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long token = core.begin();
        String firstLiteral = "aA:bB:Cc:dD:eE:Ff";
        NormalBadgeScanner.Core.Candidate first = core.accept(
                token, firstLiteral, false, NORMAL);
        assertNotNull(first);
        assertEquals(firstLiteral, first.address());
        assertNull(core.accept(token, "Aa:Bb:cC:Dd:Ee:fF", true, NORMAL));
        assertTrue(core.finish(token).foundAny());
    }

    // Mutation: admit a seventeenth new address or evict an earlier candidate.
    @Test public void candidateCapIsExactlySixteen() {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long token = core.begin();
        for (int index = 0; index < NormalBadgeScanner.MAX_CANDIDATES; index++) {
            assertNotNull(core.accept(token, address(index), false, NORMAL));
        }
        assertNull(core.accept(token, address(NormalBadgeScanner.MAX_CANDIDATES), false, NORMAL));
    }

    // Mutation: accept name-only, service-only, update, loader, AE00, or malformed bytes.
    @Test public void nonNormalAdvertisementsNeverBecomeCandidates() {
        byte[][] rejected = {
                bytes("02 01 06 04 09 45 38 37"),
                bytes("02 01 06 11 07 35 07 A7 01 9C 5D 0B 9F 62 4C 1B 7A 01 00 7D E8"),
                bytes("02 01 06 0B 09 45 38 37 20 55 50 44 41 54 45"),
                bytes("02 01 06 05 FF 41 45 30 30"),
                bytes("02 01 06 07 FF 4C 4F 41 44 45 52"),
                bytes("02 01 06 11 07 35 07"),
                null,
                new byte[0]
        };
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long token = core.begin();
        for (byte[] record : rejected) {
            assertNull(core.accept(token, address(0), false, record));
        }
        assertFalse(core.finish(token).foundAny());
    }

    // Mutation: accept a null, blank, shortened, nonhex, or differently delimited address.
    @Test public void addressMustBeCanonicalSixOctetHex() {
        String[] rejected = {null, "", " ", "AA:BB", "GG:BB:CC:DD:EE:FF",
                "AA-BB-CC-DD-EE-FF", "A:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FFF"};
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long token = core.begin();
        for (String address : rejected) assertNull(core.accept(token, address, false, NORMAL));
        assertFalse(core.finish(token).foundAny());
    }

    // Mutation: let canceled/completed/prior-session work mutate current state.
    @Test public void staleWorkIsSilentAndNewSessionResetsDedupeAndFoundAny() {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long first = core.begin();
        assertNotNull(core.accept(first, address(0), false, NORMAL));
        assertTrue(core.cancel(first));
        assertFalse(core.cancel(first));
        assertNull(core.accept(first, address(1), false, NORMAL));
        assertFalse(core.finish(first).eligible());
        long second = core.begin();
        assertTrue(second > 0L);
        assertNotEquals(first, second);
        assertNotNull(core.accept(second, address(0), false, NORMAL));
        assertTrue(core.finish(second).foundAny());
        assertFalse(core.isCurrent(second));
    }

    // Mutation: finish an already-finished token twice or make explicit cancel produce a result.
    @Test public void finishEligibilityAndCancelAreExact() {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        long empty = core.begin();
        NormalBadgeScanner.Core.FinishResult first = core.finish(empty);
        assertTrue(first.eligible());
        assertFalse(first.foundAny());
        assertFalse(core.finish(empty).eligible());
        long canceled = core.begin();
        assertTrue(core.cancel(canceled));
        assertFalse(core.finish(canceled).eligible());
    }

    // Mutation: wrap the generation and accidentally make an old token current again.
    @Test public void generationExhaustionFailsPermanentlyClosed() throws Exception {
        NormalBadgeScanner.Core core = new NormalBadgeScanner.Core();
        Field generation = NormalBadgeScanner.Core.class.getDeclaredField("generation");
        generation.setAccessible(true);
        generation.setLong(core, Long.MAX_VALUE);
        IllegalStateException first = assertThrows(IllegalStateException.class, core::begin);
        assertEquals("scanner generation exhausted", first.getMessage());
        assertEquals("scanner generation exhausted",
                assertThrows(IllegalStateException.class, core::begin).getMessage());
        assertNull(core.accept(1L, address(0), false, NORMAL));
    }

    // Mutation: make Candidate mutable or expose an Android type from Core.
    @Test public void candidateAndCoreSurfaceAreFrameworkFreeAndImmutable() {
        for (Field field : NormalBadgeScanner.Core.Candidate.class.getDeclaredFields()) {
            assertTrue(Modifier.isPrivate(field.getModifiers()));
            assertTrue(Modifier.isFinal(field.getModifiers()));
            assertFalse(field.getType().getName().startsWith("android."));
        }
        Arrays.stream(NormalBadgeScanner.Core.class.getDeclaredMethods()).forEach(method -> {
            assertFalse(method.getReturnType().getName().startsWith("android."));
            Arrays.stream(method.getParameterTypes()).forEach(type ->
                    assertFalse(type.getName().startsWith("android.")));
        });
    }

    // Mutation: omit STARTING/ARMED or emit onStarted before timeout ownership is accepted.
    @Test public void startingAndArmedStatesAreObservableThroughPublicLifecycle() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner[] scannerRef = new NormalBadgeScanner[1];
        List<String> transitions = new ArrayList<>();
        runtime.startHook = () -> {
            assertTrue(scannerRef[0].isScanning());
            transitions.add("starting:startScan");
        };
        runtime.delayHook = () -> {
            assertTrue(scannerRef[0].isScanning());
            transitions.add("starting:postDelayed");
        };
        scannerRef[0] = new NormalBadgeScanner(runtime, output);
        scannerRef[0].start();
        assertTrue(scannerRef[0].isScanning());
        assertEquals(Arrays.asList("starting:startScan", "starting:postDelayed"), transitions);
        scannerRef[0].stop();
        assertFalse(scannerRef[0].isScanning());
    }

    // Mutation: omit STARTING/ARMED or emit onStarted before timeout ownership is accepted.
    @Test public void successfulStartOwnsCallbackAndTimeoutBeforeStarted() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertTrue(scanner.isScanning());
        assertEquals(1, runtime.created.size());
        assertSame(runtime.created.get(0), runtime.started.get(0));
        assertEquals(1, runtime.delayed.size());
        assertEquals(NormalBadgeScanner.SCAN_TIMEOUT_MS, runtime.lastDelayMs);
        assertEquals(Arrays.asList("started"), output.events);
    }

    // Mutation: allow a synchronous startScan result to emit before onStarted.
    @Test public void synchronousResultQueuesUntilAfterStarted() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        runtime.startHook = () -> runtime.fireResult(runtime.started.get(0), address(0), NORMAL);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertEquals(Arrays.asList("started"), output.events);
        runtime.drainPosts();
        assertEquals(Arrays.asList("started", "candidate:" + address(0)), output.events);
    }

    // Mutation: deliver a synchronous failure before onStarted or skip its queued cleanup.
    @Test public void synchronousFailureQueuesUntilAfterStarted() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        runtime.startHook = () -> runtime.fireFailure(runtime.started.get(0),
                NormalBadgeScanner.Failure.SCAN_FAILED);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertEquals(Arrays.asList("started"), output.events);
        assertTrue(scanner.isScanning());
        runtime.drainPosts();
        assertEquals(Arrays.asList("started", "failure:SCAN_FAILED"), output.events);
        assertFalse(scanner.isScanning());
        assertSame(runtime.started.get(0), runtime.stopped.get(0));
        assertSame(runtime.lastTimeout, runtime.removed.get(0));
    }

    // Mutation: let accepted inline result delivery during STARTING arm the session.
    @Test public void inlineAcceptedResultDuringStartingCleansUpSilently() {
        assertInlineStartingIngressCleansUp(false);
    }

    // Mutation: let accepted inline failure delivery during STARTING arm the session.
    @Test public void inlineAcceptedFailureDuringStartingCleansUpSilently() {
        assertInlineStartingIngressCleansUp(true);
    }

    // Mutation: resurrect after a synchronous callback post rejection during STARTING.
    @Test public void synchronousRejectedPostFailsClosedWithoutArming() {
        for (boolean failureIngress : new boolean[] {false, true}) {
            for (boolean throwsInstead : new boolean[] {false, true}) {
                FakeRuntime runtime = new FakeRuntime();
                RecordingOutput output = new RecordingOutput(runtime);
                runtime.rejectPost = !throwsInstead;
                runtime.throwPost = throwsInstead;
                runtime.startHook = () -> {
                    FakeCallback callback = runtime.started.get(0);
                    if (failureIngress) runtime.fireFailure(callback,
                            NormalBadgeScanner.Failure.SCAN_FAILED);
                    else runtime.fireResult(callback, address(0), NORMAL);
                };
                NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
                scanner.start();
                assertFalse(scanner.isScanning());
                assertEquals(0, runtime.delayCalls);
                assertEquals(0, runtime.delayed.size());
                assertEquals(0, output.events.size());
                assertSame(runtime.started.get(0), runtime.stopped.get(0));
            }
        }
    }

    // Mutation: arm after startScan failed despite an accepted synchronous callback.
    @Test public void failedStartInvalidatesAlreadyQueuedCallback() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        runtime.startResult = false;
        runtime.startHook = () -> runtime.fireResult(runtime.started.get(0), address(0), NORMAL);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertEquals(Arrays.asList("failure:SCAN_FAILED"), output.events);
        runtime.drainPosts();
        assertEquals(Arrays.asList("failure:SCAN_FAILED"), output.events);
        assertFalse(scanner.isScanning());
    }

    // Mutation: let accepted synchronous work survive a false or throwing startScan.
    @Test public void everyFailedStartInvalidatesQueuedResultOrFailure() {
        for (boolean failureIngress : new boolean[] {false, true}) {
            for (int mode = 0; mode < 3; mode++) {
                FakeRuntime runtime = new FakeRuntime();
                RecordingOutput output = new RecordingOutput(runtime);
                if (mode == 0) runtime.startResult = false;
                else if (mode == 1) runtime.throwStart =
                        new IllegalStateException("start secret");
                else runtime.throwStart = new SecurityException("permission secret");
                runtime.startHook = () -> {
                    FakeCallback callback = runtime.started.get(0);
                    if (failureIngress) runtime.fireFailure(callback,
                            NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
                    else runtime.fireResult(callback, address(0), NORMAL);
                };
                NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
                scanner.start();
                String expected = mode == 2
                        ? "failure:BLUETOOTH_PERMISSION_REQUIRED" : "failure:SCAN_FAILED";
                assertEquals(Arrays.asList(expected), output.events);
                runtime.drainPosts();
                assertEquals(Arrays.asList(expected), output.events);
                assertFalse(scanner.isScanning());
                assertEquals(0, runtime.delayCalls);
                assertEquals(1, runtime.stopped.size());
                assertSame(runtime.started.get(0), runtime.stopped.get(0));
                assertEquals(1, runtime.removed.size());
                assertNotNull(runtime.removed.get(0));
            }
        }
    }

    // Mutation: accept a rejected/throwing timeout post or emit onStarted anyway.
    @Test public void timeoutPostFailureStopsAndReportsSynchronously() {
        for (boolean throwsInstead : new boolean[] {false, true}) {
            FakeRuntime runtime = new FakeRuntime();
            RecordingOutput output = new RecordingOutput(runtime);
            runtime.rejectDelayed = !throwsInstead;
            runtime.throwDelayed = throwsInstead;
            NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
            scanner.start();
            assertFalse(scanner.isScanning());
            assertEquals(Arrays.asList("failure:SCAN_FAILED"), output.events);
            assertSame(runtime.started.get(0), runtime.stopped.get(0));
            assertSame(runtime.lastTimeout, runtime.removed.get(0));
        }
    }

    // Mutation: arm after postDelayed ran the current timeout inline while STARTING.
    @Test public void inlineStartingTimeoutCannotResurrect() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        runtime.delayHookRunsTask = true;
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertFalse(scanner.isScanning());
        assertEquals(0, output.events.size());
        assertEquals(2, runtime.removed.size());
        assertSame(runtime.lastTimeout, runtime.removed.get(0));
        assertSame(runtime.lastTimeout, runtime.removed.get(1));
        assertSame(runtime.started.get(0), runtime.stopped.get(0));
    }

    // Mutation: omit the second ownership recheck after postDelayed reentrant cleanup.
    @Test public void postDelayHookRejectedCallbackCannotResurrect() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        runtime.rejectPost = true;
        runtime.delayHook = () -> runtime.fireResult(
                runtime.started.get(0), address(0), NORMAL);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertFalse(scanner.isScanning());
        assertEquals(1, runtime.delayCalls);
        assertEquals(0, output.events.size());
        assertEquals(2, runtime.removed.size());
        assertSame(runtime.lastTimeout, runtime.removed.get(0));
        assertSame(runtime.lastTimeout, runtime.removed.get(1));
        assertEquals(1, runtime.stopped.size());
        assertSame(runtime.started.get(0), runtime.stopped.get(0));
    }

    // Mutation: report explicit cancellation as no badge found or let stale callbacks emit.
    @Test public void stopCloseAndStaleWorkAreSilentAndIdempotent() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        FakeCallback first = runtime.created.get(0);
        scanner.stop();
        scanner.stop();
        runtime.fireResult(first, address(0), NORMAL);
        runtime.fireFailure(first, NormalBadgeScanner.Failure.SCAN_FAILED);
        runtime.drainPosts();
        assertEquals(Arrays.asList("started"), output.events);
        assertEquals(1, runtime.stopped.size());
        scanner.close();
        scanner.close();
        assertFalse(scanner.isScanning());
        assertEquals("scanner is closed",
                assertThrows(IllegalStateException.class, scanner::start).getMessage());
    }

    // Mutation: reuse callback identity or dedupe state across starts.
    @Test public void laterSessionUsesFreshCallbackAndFreshAdmissionState() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        FakeCallback first = runtime.created.get(0);
        runtime.fireResult(first, address(0), NORMAL);
        runtime.drainPosts();
        scanner.stop();
        scanner.start();
        FakeCallback second = runtime.created.get(1);
        assertNotSame(first, second);
        runtime.fireResult(second, address(0), NORMAL);
        runtime.drainPosts();
        assertEquals(2, output.candidates);
    }

    // Mutation: let a duplicate start allocate or arm a second session.
    @Test public void duplicateStartChangesNoLifecycleRecord() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        scanner.start();
        assertTrue(scanner.isScanning());
        assertEquals(1, runtime.created.size());
        assertEquals(1, runtime.started.size());
        assertEquals(1, runtime.delayCalls);
        assertEquals(Arrays.asList("started"), output.events);
    }

    // Mutation: retain the caller's mutable record instead of a defensive copy.
    @Test public void postedResultUsesIngressCopyOfScanBytes() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        byte[] callerRecord = Arrays.copyOf(NORMAL, NORMAL.length);
        runtime.fireResult(runtime.created.get(0), address(0), callerRecord);
        Arrays.fill(callerRecord, (byte) 0);
        runtime.drainPosts();
        assertEquals(1, output.candidates);
        assertEquals(Arrays.asList("started", "candidate:" + address(0)), output.events);
    }

    // Mutation: execute queued result/failure/timeout work from a prior session.
    @Test public void queuedPriorSessionWorkIsSilentAfterNewStart() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        FakeCallback first = runtime.created.get(0);
        Runnable firstTimeout = runtime.lastTimeout;
        runtime.fireResult(first, address(0), NORMAL);
        runtime.fireFailure(first, NormalBadgeScanner.Failure.SCAN_FAILED);
        scanner.stop();
        scanner.start();
        FakeCallback second = runtime.created.get(1);
        firstTimeout.run();
        runtime.drainPosts();
        assertTrue(scanner.isScanning());
        assertEquals(Arrays.asList("started", "started"), output.events);
        assertEquals(0, output.candidates);
        assertEquals(1, runtime.stopped.size());
        assertSame(first, runtime.stopped.get(0));
        assertNotSame(first, second);
    }

    // Mutation: use equals instead of callback reference identity.
    @Test public void equalButDistinctCallbackHandleIsRejected() {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        FakeCallback current = runtime.created.get(0);
        FakeCallback impostor = new FakeCallback(current.events);
        assertNotSame(current, impostor);
        assertEquals(current, impostor);
        current.events.onResult(impostor, new FakeResult(99), address(0), false, NORMAL);
        runtime.drainPosts();
        assertEquals(Arrays.asList("started"), output.events);
        assertEquals(0, output.candidates);
    }

    // Mutation: natural timeout loses foundAny or fires before invalidate/remove/stop.
    @Test public void naturalTimeoutReportsExactFoundAnyAfterCleanup() {
        for (boolean found : new boolean[] {false, true}) {
            FakeRuntime runtime = new FakeRuntime();
            RecordingOutput output = new RecordingOutput(runtime);
            NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
            scanner.start();
            if (found) {
                runtime.fireResult(runtime.created.get(0), address(0), NORMAL);
                runtime.drainPosts();
            }
            runtime.runTimeout();
            assertFalse(scanner.isScanning());
            assertEquals("finished:" + found, output.events.get(output.events.size() - 1));
            assertTrue(output.terminalAfterCleanup);
        }
    }

    // Mutation: leak platform failure codes or emit terminal output before cleanup.
    @Test public void asynchronousFailuresMapExactlyOnceAfterCleanup() {
        for (NormalBadgeScanner.Failure failure : new NormalBadgeScanner.Failure[] {
                NormalBadgeScanner.Failure.SCAN_FAILED,
                NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED}) {
            FakeRuntime runtime = new FakeRuntime();
            RecordingOutput output = new RecordingOutput(runtime);
            NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
            scanner.start();
            runtime.fireFailure(runtime.created.get(0), failure);
            runtime.drainPosts();
            assertEquals("failure:" + failure, output.events.get(1));
            assertEquals(1, runtime.stopped.size());
            assertTrue(output.terminalAfterCleanup);
        }
    }

    // Mutation: mis-map permission/Bluetooth/start preflight failures or retain an active session.
    @Test public void preflightAndStartFailuresMapToStableFailureKinds() {
        assertStartFailure(false, true, NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
        assertStartFailure(true, false, NormalBadgeScanner.Failure.BLUETOOTH_OFF);
        assertThrownStartFailure("permission", new SecurityException("secret"),
                NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
        assertThrownStartFailure("bluetooth", new SecurityException("secret"),
                NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
        assertThrownStartFailure("callback", new SecurityException("secret"),
                NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
        assertThrownStartFailure("start", new SecurityException("secret"),
                NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
        assertThrownStartFailure("permission", new IllegalStateException("secret"),
                NormalBadgeScanner.Failure.SCAN_FAILED);
        assertThrownStartFailure("bluetooth", new IllegalStateException("secret"),
                NormalBadgeScanner.Failure.SCAN_FAILED);
        assertThrownStartFailure("callback", new IllegalStateException("secret"),
                NormalBadgeScanner.Failure.SCAN_FAILED);
        assertThrownStartFailure("start", new IllegalStateException("secret"),
                NormalBadgeScanner.Failure.SCAN_FAILED);
        FakeRuntime falseStart = new FakeRuntime();
        falseStart.startResult = false;
        assertRuntimeStartFailure(falseStart, NormalBadgeScanner.Failure.SCAN_FAILED);
    }

    // Mutation: notify from a callback thread or stay armed when Handler.post rejects/throws.
    @Test public void rejectedAsynchronousPostsStopSilentlyForEveryIngress() {
        for (boolean result : new boolean[] {false, true}) {
            for (boolean throwsInstead : new boolean[] {false, true}) {
                FakeRuntime runtime = new FakeRuntime();
                RecordingOutput output = new RecordingOutput(runtime);
                NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
                scanner.start();
                runtime.rejectPost = !throwsInstead;
                runtime.throwPost = throwsInstead;
                FakeCallback callback = runtime.created.get(0);
                if (result) runtime.fireResult(callback, address(0), NORMAL);
                else runtime.fireFailure(callback, NormalBadgeScanner.Failure.SCAN_FAILED);
                assertFalse(scanner.isScanning());
                assertEquals(Arrays.asList("started"), output.events);
                assertEquals(1, runtime.stopped.size());
                assertSame(callback, runtime.stopped.get(0));
                assertSame(runtime.lastTimeout, runtime.removed.get(0));
            }
        }
    }

    // Mutation: clean platform resources before invalidation or replace the primary terminal event.
    @Test public void cleanupReentrancyAndExceptionsCannotResurrectOrReplaceTerminalOutput() {
        for (boolean timeout : new boolean[] {false, true}) {
            FakeRuntime runtime = new FakeRuntime();
            RecordingOutput output = new RecordingOutput(runtime);
            NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
            scanner.start();
            FakeCallback callback = runtime.created.get(0);
            Runnable reentrant = () -> {
                runtime.fireResult(callback, address(0), NORMAL);
                runtime.fireFailure(callback, NormalBadgeScanner.Failure.BLUETOOTH_PERMISSION_REQUIRED);
            };
            runtime.removeHook = reentrant;
            runtime.stopHook = reentrant;
            runtime.inlinePost = true;
            runtime.throwRemove = new IllegalStateException("remove secret");
            runtime.throwStop = new IllegalStateException("stop secret");
            if (timeout) runtime.runTimeout();
            else {
                runtime.fireFailure(callback, NormalBadgeScanner.Failure.SCAN_FAILED);
                runtime.drainPosts();
            }
            assertFalse(scanner.isScanning());
            assertEquals(Arrays.asList("started",
                    timeout ? "finished:false" : "failure:SCAN_FAILED"), output.events);
            assertEquals(1, runtime.removed.size());
            assertEquals(1, runtime.stopped.size());
            assertSame(runtime.lastTimeout, runtime.removed.get(0));
            assertSame(callback, runtime.stopped.get(0));
        }
    }

    // Mutation: skip owner-thread checks on public lifecycle calls.
    @Test public void publicLifecycleRequiresRuntimeOwnerThread() {
        FakeRuntime runtime = new FakeRuntime();
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, new RecordingOutput(runtime));
        runtime.owner = false;
        assertThrows(IllegalStateException.class, scanner::start);
        assertThrows(IllegalStateException.class, scanner::stop);
        assertThrows(IllegalStateException.class, scanner::isScanning);
        assertThrows(IllegalStateException.class, scanner::close);
    }

    private static void assertInlineStartingIngressCleansUp(boolean failureIngress) {
        FakeRuntime runtime = new FakeRuntime();
        RecordingOutput output = new RecordingOutput(runtime);
        runtime.inlinePost = true;
        runtime.startHook = () -> {
            FakeCallback callback = runtime.started.get(0);
            if (failureIngress) {
                runtime.fireFailure(callback, NormalBadgeScanner.Failure.SCAN_FAILED);
            } else {
                runtime.fireResult(callback, address(0), NORMAL);
            }
        };
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertFalse(scanner.isScanning());
        assertEquals(0, runtime.delayCalls);
        assertEquals(0, runtime.delayed.size());
        assertEquals(0, runtime.posts.size());
        assertEquals(0, output.events.size());
        assertEquals(1, runtime.removed.size());
        assertNotNull(runtime.removed.get(0));
        assertEquals(1, runtime.stopped.size());
        assertSame(runtime.started.get(0), runtime.stopped.get(0));
    }

    private static void assertStartFailure(boolean permission, boolean bluetooth,
            NormalBadgeScanner.Failure expected) {
        FakeRuntime runtime = new FakeRuntime();
        runtime.permission = permission;
        runtime.bluetooth = bluetooth;
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertEquals(Arrays.asList("failure:" + expected), output.events);
        assertFalse(scanner.isScanning());
        assertEquals(0, runtime.started.size());
    }

    private static void assertThrownStartFailure(String site, RuntimeException thrown,
            NormalBadgeScanner.Failure expected) {
        FakeRuntime runtime = new FakeRuntime();
        if ("permission".equals(site)) runtime.throwPermission = thrown;
        else if ("bluetooth".equals(site)) runtime.throwBluetooth = thrown;
        else if ("callback".equals(site)) runtime.throwCallback = thrown;
        else if ("start".equals(site)) runtime.throwStart = thrown;
        else throw new AssertionError(site);
        assertRuntimeStartFailure(runtime, expected);
    }

    private static void assertRuntimeStartFailure(FakeRuntime runtime,
            NormalBadgeScanner.Failure expected) {
        RecordingOutput output = new RecordingOutput(runtime);
        NormalBadgeScanner scanner = new NormalBadgeScanner(runtime, output);
        scanner.start();
        assertEquals(Arrays.asList("failure:" + expected), output.events);
        assertFalse(scanner.isScanning());
        if (!runtime.started.isEmpty()) {
            assertEquals(1, runtime.started.size());
            assertEquals(1, runtime.stopped.size());
            assertSame(runtime.started.get(0), runtime.stopped.get(0));
        }
    }

    // Mutation: implement a second Android classifier or lose exact scanner/callback ownership.
    @Test public void androidAdapterDelegatesToTheTestedRuntimeAndExactFilter() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "app/src/main/java/net/jethachan/factory_badges/ble/normal/NormalBadgeScanner.java")),
                StandardCharsets.UTF_8);
        assertTrue(source.contains("private static final class AndroidRuntime"));
        assertTrue(source.contains("private static final class AndroidOutput"));
        assertTrue(source.contains("new ParcelUuid(NormalUuids.SERVICE)"));
        assertTrue(source.contains("ScanSettings.SCAN_MODE_LOW_LATENCY"));
        assertTrue(source.contains("scanner.startScan(filters, settings, callback)"));
        assertTrue(source.contains("handle.scanner.stopScan(handle.callback)"));
        assertTrue(source.indexOf("handle.scanner = scanner;")
                < source.indexOf("scanner.startScan(filters, settings, callback);"));
        assertTrue(source.contains("onBatchScanResults(List<ScanResult> results)"));
        int routeStart = source.indexOf("private void route(");
        int routeEnd = source.indexOf(
                "private static AndroidCallbackHandle requireCallback", routeStart);
        assertTrue(routeStart >= 0 && routeEnd > routeStart);
        String route = source.substring(routeStart, routeEnd);
        assertTrue(route.contains("nearbyPermissionsGranted()"));
        assertTrue(route.contains("if (result == null || !nearbyPermissionsGranted())"));
        assertTrue(route.contains("if (device == null || scanRecord == null) return;"));
        assertTrue(route.contains("if (bytes == null) return;"));
        assertTrue(route.indexOf("nearbyPermissionsGranted()")
                < route.indexOf("device.getAddress()"));
        assertTrue(route.indexOf("nearbyPermissionsGranted()")
                < route.indexOf("device.getBondState()"));
        assertTrue(route.indexOf("Arrays.copyOf(bytes, bytes.length)")
                < route.indexOf("handle.events.onResult"));
        assertEquals(2, occurrences(source,
                "owner.route(AndroidCallbackHandle.this, result);"));
        assertTrue(source.contains("scanRecord.getBytes()"));
        assertTrue(source.contains("Arrays.copyOf(bytes, bytes.length)"));
        assertTrue(source.contains("Manifest.permission.BLUETOOTH_SCAN"));
        assertTrue(source.contains("Manifest.permission.BLUETOOTH_CONNECT"));
        assertFalse(source.contains("getName()"));
        assertFalse(source.contains("onScanFailed(int errorCode) { output"));
        assertFalse(source.contains("String.valueOf(errorCode)"));
        assertFalse(source.contains("getMessage()"));
        assertFalse(source.contains("createBond("));
        assertFalse(source.contains("connectGatt("));
        assertFalse(source.contains("selectDevice("));
        assertEquals(1, occurrences(source, "currentCallback == callback"));
        assertEquals(2, occurrences(source,
                "if (!matchesLocked(token, callback) || !core.isCurrent(token)) return;"));
        assertEquals(2, occurrences(source,
                "                    if (state == SessionState.STARTING) {"));
        assertEquals(2, occurrences(source,
                "                    } else if (state == SessionState.ARMED) {"));
        assertEquals(1, occurrences(source,
                "NormalAdvertisementParser.parse(scanRecord)"));
    }

    private static int occurrences(String source, String needle) {
        int count = 0;
        for (int at = 0; (at = source.indexOf(needle, at)) >= 0; at += needle.length()) count++;
        return count;
    }

    private static final class FakeCallback implements NormalBadgeScanner.Runtime.CallbackHandle {
        final NormalBadgeScanner.Runtime.Events events;

        FakeCallback(NormalBadgeScanner.Runtime.Events events) {
            this.events = events;
        }

        @Override public boolean equals(Object other) {
            return other instanceof FakeCallback;
        }

        @Override public int hashCode() {
            return 1;
        }
    }

    private static final class FakeResult implements NormalBadgeScanner.Runtime.ResultHandle {
        final int identity;

        FakeResult(int identity) {
            this.identity = identity;
        }
    }

    private static final class FakeRuntime implements NormalBadgeScanner.Runtime {
        boolean owner = true;
        boolean permission = true;
        boolean bluetooth = true;
        boolean startResult = true;
        boolean rejectPost;
        boolean throwPost;
        boolean rejectDelayed;
        boolean inlinePost;
        boolean throwDelayed;
        boolean delayHookRunsTask;
        RuntimeException throwStart;
        RuntimeException throwPermission;
        RuntimeException throwBluetooth;
        RuntimeException throwCallback;
        RuntimeException throwStop;
        RuntimeException throwRemove;
        Runnable startHook;
        Runnable stopHook;
        Runnable delayHook;
        Runnable removeHook;
        long lastDelayMs;
        Runnable lastTimeout;
        int delayCalls;
        int resultIdentity;
        final List<FakeCallback> created = new ArrayList<>();
        final List<FakeCallback> started = new ArrayList<>();
        final List<FakeCallback> stopped = new ArrayList<>();
        final List<Runnable> posts = new ArrayList<>();
        final List<Runnable> delayed = new ArrayList<>();
        final List<Runnable> removed = new ArrayList<>();

        @Override public boolean isOwnerThread() { return owner; }

        @Override public boolean nearbyPermissionsGranted() {
            if (throwPermission != null) throw throwPermission;
            return permission;
        }

        @Override public boolean bluetoothEnabled() {
            if (throwBluetooth != null) throw throwBluetooth;
            return bluetooth;
        }

        @Override public CallbackHandle newCallback(Events events) {
            if (throwCallback != null) throw throwCallback;
            FakeCallback callback = new FakeCallback(events);
            created.add(callback);
            return callback;
        }

        @Override public boolean startScan(CallbackHandle callback) {
            FakeCallback exact = (FakeCallback) callback;
            started.add(exact);
            if (startHook != null) startHook.run();
            if (throwStart != null) throw throwStart;
            return startResult;
        }

        @Override public void stopScan(CallbackHandle callback) {
            stopped.add((FakeCallback) callback);
            if (stopHook != null) stopHook.run();
            if (throwStop != null) throw throwStop;
        }

        @Override public boolean post(Runnable task) {
            if (throwPost) throw new IllegalStateException("post unavailable");
            if (rejectPost) return false;
            if (inlinePost) {
                task.run();
                return true;
            }
            posts.add(task);
            return true;
        }

        @Override public boolean postDelayed(Runnable task, long delayMs) {
            delayCalls++;
            lastTimeout = task;
            lastDelayMs = delayMs;
            if (throwDelayed) throw new IllegalStateException("delay unavailable");
            if (rejectDelayed) return false;
            delayed.add(task);
            if (delayHook != null) delayHook.run();
            if (delayHookRunsTask) task.run();
            return true;
        }

        @Override public void removeCallbacks(Runnable task) {
            removed.add(task);
            delayed.remove(task);
            if (removeHook != null) removeHook.run();
            if (throwRemove != null) throw throwRemove;
        }

        void fireResult(FakeCallback callback, String address, byte[] record) {
            callback.events.onResult(callback, new FakeResult(++resultIdentity),
                    address, false, record);
        }

        void fireFailure(FakeCallback callback, NormalBadgeScanner.Failure failure) {
            callback.events.onFailure(callback, failure);
        }

        void drainPosts() {
            List<Runnable> queued = new ArrayList<>(posts);
            posts.clear();
            for (Runnable task : queued) task.run();
        }

        void runTimeout() {
            assertNotNull(lastTimeout);
            lastTimeout.run();
        }
    }

    private static final class RecordingOutput implements NormalBadgeScanner.Output {
        final FakeRuntime runtime;
        final List<String> events = new ArrayList<>();
        boolean terminalAfterCleanup;
        int candidates;

        RecordingOutput(FakeRuntime runtime) {
            this.runtime = runtime;
        }

        @Override public void onStarted() {
            events.add("started");
        }

        @Override public void onCandidate(NormalBadgeScanner.Runtime.ResultHandle result,
                NormalBadgeScanner.Core.Candidate candidate) {
            assertNotNull(result);
            candidates++;
            events.add("candidate:" + candidate.address());
        }

        @Override public void onFinished(boolean foundAny) {
            terminalAfterCleanup = !runtime.stopped.isEmpty() && !runtime.removed.isEmpty();
            events.add("finished:" + foundAny);
        }

        @Override public void onFailure(NormalBadgeScanner.Failure failure) {
            terminalAfterCleanup = runtime.created.isEmpty()
                    || (!runtime.stopped.isEmpty() && !runtime.removed.isEmpty());
            events.add("failure:" + failure);
        }
    }

    private static String address(int index) {
        return String.format("02:00:00:00:%02X:%02X", (index >>> 8) & 0xFF, index & 0xFF);
    }

    private static byte[] bytes(String hex) {
        if (hex == null) return null;
        String[] fields = hex.trim().split("\\s+");
        byte[] result = new byte[fields.length];
        for (int index = 0; index < fields.length; index++) {
            result[index] = (byte) Integer.parseInt(fields[index], 16);
        }
        return result;
    }
}
