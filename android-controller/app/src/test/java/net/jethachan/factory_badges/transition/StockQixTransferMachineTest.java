package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import org.junit.Test;

public final class StockQixTransferMachineTest {
    private static final int CAPTURE_PAYLOAD_LENGTH = 1_080_360;
    private static final int CAPTURE_WINDOW = 1_024;
    private static final int CAPTURE_BLOCKS = 1_056;
    private static final int CAPTURE_C3_RESPONSES = 1_055;
    private static final int MAX_WINDOW = 65_527;
    private static final int MAX_QIX_PAYLOAD = (32 * 1024 * 1024) - 27;
    private static final byte[] CAPTURE_FINAL_C5 = new byte[] {
            (byte) 0x9E, (byte) 0xC7, 0x01, (byte) 0xC5, 0x01, 0x00, 0x00
    };

    @Test public void artifactRejectsNullBoundsLengthAndWholeQixHashMismatch() {
        byte[] payload = new byte[] {1, 2};
        byte[] header = headerFor(payload.length);

        assertIllegalArgument(() -> new TransitionArtifact(null, payload, new byte[32], buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(header, null, new byte[32], buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(header, payload, null, buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(header, payload, new byte[32], null));
        assertIllegalArgument(() -> new TransitionArtifact(new byte[26], payload,
                new byte[32], buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(headerFor(0), new byte[0],
                new byte[32], buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(header, payload, new byte[31], buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(header, payload, new byte[32],
                new byte[15]));
        assertIllegalArgument(() -> new TransitionArtifact(headerFor(1), payload,
                new byte[32], buildId()));
        assertIllegalArgument(() -> new TransitionArtifact(header, payload, new byte[32],
                buildId()));

        byte[] tooLarge = new byte[MAX_QIX_PAYLOAD + 1];
        assertIllegalArgument(() -> new TransitionArtifact(headerFor(tooLarge.length), tooLarge,
                new byte[32], buildId()));
    }

    @Test public void artifactDefensivelyCopiesEveryConstructorInputAndGetterResult() {
        byte[] header = headerFor(3);
        byte[] payload = new byte[] {0x11, 0x22, 0x33};
        byte[] qixSha = sha256(header, payload);
        byte[] expectedBuildId = buildId();
        byte[] expectedHeader = Arrays.copyOf(header, header.length);
        byte[] expectedPayload = Arrays.copyOf(payload, payload.length);
        byte[] expectedSha = Arrays.copyOf(qixSha, qixSha.length);
        byte[] expectedBuild = Arrays.copyOf(expectedBuildId, expectedBuildId.length);

        TransitionArtifact artifact = new TransitionArtifact(header, payload, qixSha, expectedBuildId);
        header[0] = 0;
        payload[0] = 0;
        qixSha[0] = 0;
        expectedBuildId[0] = 0;

        assertArrayEquals(expectedHeader, artifact.qixHeader());
        assertArrayEquals(expectedPayload, artifact.ufwPayload());
        assertArrayEquals(expectedSha, artifact.qixSha256());
        assertArrayEquals(expectedBuild, artifact.expectedBuildId());

        byte[] mutatedHeader = artifact.qixHeader();
        byte[] mutatedPayload = artifact.ufwPayload();
        byte[] mutatedSha = artifact.qixSha256();
        byte[] mutatedBuild = artifact.expectedBuildId();
        mutatedHeader[0] ^= 0x7F;
        mutatedPayload[0] ^= 0x7F;
        mutatedSha[0] ^= 0x7F;
        mutatedBuild[0] ^= 0x7F;

        assertArrayEquals(expectedHeader, artifact.qixHeader());
        assertArrayEquals(expectedPayload, artifact.ufwPayload());
        assertArrayEquals(expectedSha, artifact.qixSha256());
        assertArrayEquals(expectedBuild, artifact.expectedBuildId());
    }

    @Test public void constructorOwnsArtifactAndSecondStartIsStickyInvalidState() {
        assertIllegalArgument(() -> new StockQixTransferMachine(null));

        StockQixTransferMachine machine = new StockQixTransferMachine(artifact(new byte[] {1}));
        StockQixTransferMachine.Action first = machine.start(0x06, -1168149652);
        assertSend(first, 0x60);

        StockQixTransferMachine.Action second = machine.start(0x06, -1168149652);
        assertFailure(second, StockQixTransferMachine.FailureCode.INVALID_STATE);
        assertEquals(StockQixTransferMachine.Phase.FAILED, machine.snapshot().phase());
        assertSame(second, machine.onFd01(null));
    }

    @Test public void captureSizedSyntheticTransferPinsCountsAndSmallCaptureVectors()
            throws Exception {
        byte[] header = QixFrameCodec.decode(fixture("qix-c0-update-header-request.bin")).payload();
        byte[] payload = new byte[CAPTURE_PAYLOAD_LENGTH];
        StockQixTransferMachine machine = new StockQixTransferMachine(artifact(header, payload));

        assertSend(machine.start(0x06, -1168149652), 0x60);
        assertAwaitFd01(machine.onFd02WriteAcknowledged());
        StockQixTransferMachine.SendFd02 c0 = assertSend(machine.onFd01(bindResponse(0x04)), 0xC0);
        assertArrayEquals(fixture("qix-c0-update-header-request.bin"), c0.frame());
        assertAwaitFd03(machine.onFd02WriteAcknowledged(), 0xC1);

        QixFrame capturedFirst = QixFrameCodec.decode(fixture("qix-c2-first.bin"));
        QixFrame capturedLast = QixFrameCodec.decode(fixture("qix-c2-last.bin"));
        StockQixTransferMachine.Action c2Action = machine.onFd03(c1(CAPTURE_WINDOW, 0));
        int blocksSent = 0;
        int acknowledgedByC3 = 0;
        for (int block = 0; block < CAPTURE_BLOCKS; block++) {
            StockQixTransferMachine.SendFd02 c2 = assertSend(c2Action, 0xC2);
            blocksSent++;
            QixFrame actual = QixFrameCodec.decode(c2.frame());
            if (block == 0) {
                assertEquals(capturedFirst.flags(), actual.flags());
                assertEquals(capturedFirst.opcode(), actual.opcode());
                assertEquals(capturedFirst.payload().length, actual.payload().length);
                assertArrayEquals(Arrays.copyOf(capturedFirst.payload(), 8),
                        Arrays.copyOf(actual.payload(), 8));
            }
            if (block == CAPTURE_BLOCKS - 1) {
                assertEquals(capturedLast.flags(), actual.flags());
                assertEquals(capturedLast.opcode(), actual.opcode());
                assertEquals(capturedLast.payload().length, actual.payload().length);
                assertArrayEquals(Arrays.copyOf(capturedLast.payload(), 8),
                        Arrays.copyOf(actual.payload(), 8));
            }

            StockQixTransferMachine.Action afterWrite = machine.onFd02WriteAcknowledged();
            if (block == CAPTURE_BLOCKS - 1) {
                assertAwaitFd03(afterWrite, 0xC3, 0xC5);
            } else {
                assertAwaitFd03(afterWrite, 0xC3);
                acknowledgedByC3++;
                c2Action = machine.onFd03(c3((long) (block + 1) * CAPTURE_WINDOW));
            }
        }

        assertEquals(CAPTURE_BLOCKS, blocksSent);
        assertEquals(CAPTURE_C3_RESPONSES, acknowledgedByC3);
        assertArrayEquals(CAPTURE_FINAL_C5, QixFrameCodec.encode(0x01, 0xC5,
                new byte[] {0}));
        assertComplete(machine.onFd03(QixFrameCodec.decode(CAPTURE_FINAL_C5)));
        assertEquals(CAPTURE_PAYLOAD_LENGTH, machine.snapshot().acknowledgedOffset());
    }

    @Test public void optionalBindAckUsesIndependentSerialOneAndThenC0() {
        StockQixTransferMachine machine = new StockQixTransferMachine(artifact(new byte[] {1}));

        assertSend(machine.start(0x06, -1168149652), 0x60);
        assertAwaitFd01(machine.onFd02WriteAcknowledged());
        StockQixTransferMachine.SendFd02 bindAck = assertSend(machine.onFd01(bindResponse(0x7A)),
                0xFF);
        QixFrame decodedAck = QixFrameCodec.decode(bindAck.frame());
        assertEquals(0x09, decodedAck.flags());
        assertArrayEquals(new byte[] {0x61, 0}, decodedAck.payload());
        StockQixTransferMachine.SendFd02 c0 = assertSend(machine.onFd02WriteAcknowledged(), 0xC0);
        assertEquals(0x05, QixFrameCodec.decode(c0.frame()).flags());
    }

    @Test public void c1AndC2UseExactFieldsLogicalAcknowledgementAndSnapshot() {
        byte[] payload = new byte[] {
                0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19,
                0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23
        };
        StockQixTransferMachine machine = readyForC1(payload);
        assertTrue(machine.snapshot().mayCancel());

        StockQixTransferMachine.SendFd02 c2 = assertSend(machine.onFd03(c1(7, 0)), 0xC2);
        QixFrame frame = QixFrameCodec.decode(c2.frame());
        assertEquals(0x0D, frame.flags());
        assertArrayEquals(new byte[] {
                0x07, 0, 0, 0, 0, 0, 0, 0, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16
        }, frame.payload());

        StockQixTransferMachine.Snapshot snapshot = machine.snapshot();
        assertEquals(StockQixTransferMachine.Phase.WRITE_C2, snapshot.phase());
        assertEquals(payload.length, snapshot.totalBytes());
        assertEquals(0, snapshot.acknowledgedOffset());
        assertEquals(0, snapshot.pendingOffset());
        assertEquals(7, snapshot.pendingLength());
        assertFalse(snapshot.mayCancel());
        assertFalse(snapshot.terminal());
        assertEquals(StockQixTransferMachine.FailureCode.NONE, snapshot.failureCode());

        assertAwaitFd03(machine.onFd02WriteAcknowledged(), 0xC3);
    }

    @Test public void c2LongFrameBoundaryAndMaximumWindowAreExact() {
        StockQixTransferMachine.SendFd02 sixByte = assertSend(
                readyForC1(new byte[] {1, 2, 3, 4, 5, 6}).onFd03(c1(6, 0)), 0xC2);
        assertEquals(0x09, QixFrameCodec.decode(sixByte.frame()).flags());

        StockQixTransferMachine.SendFd02 sevenByte = assertSend(
                readyForC1(new byte[] {1, 2, 3, 4, 5, 6, 7}).onFd03(c1(7, 0)), 0xC2);
        assertEquals(0x0D, QixFrameCodec.decode(sevenByte.frame()).flags());

        byte[] maximumPayload = new byte[MAX_WINDOW];
        StockQixTransferMachine maximum = readyForC1(maximumPayload);
        StockQixTransferMachine.SendFd02 c2 = assertSend(maximum.onFd03(c1(MAX_WINDOW, 0)), 0xC2);
        QixFrame maximumFrame = QixFrameCodec.decode(c2.frame());
        assertEquals(0x0D, maximumFrame.flags());
        assertEquals(65_535, maximumFrame.payload().length);
        assertArrayEquals(new byte[] {(byte) 0xF7, (byte) 0xFF, 0, 0, 0, 0, 0, 0},
                Arrays.copyOf(maximumFrame.payload(), 8));
        assertAwaitFd03(maximum.onFd02WriteAcknowledged(), 0xC3, 0xC5);
    }

    @Test public void c1UsesUnsignedU32AndRejectsBadWindowOffsetAndDuplicateResume() {
        assertFailure(readyForC1(new byte[20]).onFd03(c1(0, 0)),
                StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
        assertFailure(readyForC1(new byte[20]).onFd03(c1(MAX_WINDOW + 1L, 0)),
                StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
        assertFailure(readyForC1(new byte[20]).onFd03(c1(0x80000000L, 0)),
                StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);
        assertFailure(readyForC1(new byte[20]).onFd03(c1(1, 0x80000000L)),
                StockQixTransferMachine.FailureCode.OFFSET_MISMATCH);
        assertFailure(readyForC1(new byte[20]).onFd03(c1(5, 3)),
                StockQixTransferMachine.FailureCode.OFFSET_MISMATCH);
        assertFailure(readyForC1(new byte[20]).onFd03(c1(5, 21)),
                StockQixTransferMachine.FailureCode.OFFSET_MISMATCH);

        StockQixTransferMachine machine = readyForC1(new byte[20]);
        assertSend(machine.onFd03(c1(5, 0)), 0xC2);
        assertFailure(machine.onFd03(c1(5, 0)),
                StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    @Test public void supportsAlignedAndFullResumeAndBothFinalPaths() {
        byte[] payload = new byte[] {
                0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
        };
        StockQixTransferMachine aligned = readyForC1(payload);
        StockQixTransferMachine.SendFd02 finalC2 = assertSend(aligned.onFd03(c1(5, 10)), 0xC2);
        assertArrayEquals(new byte[] {5, 0, 0, 0, 10, 0, 0, 0, 10, 11, 12, 13, 14},
                QixFrameCodec.decode(finalC2.frame()).payload());
        assertEquals(10, aligned.snapshot().acknowledgedOffset());
        assertAwaitFd03(aligned.onFd02WriteAcknowledged(), 0xC3, 0xC5);
        assertEquals(10, aligned.snapshot().acknowledgedOffset());
        assertComplete(aligned.onFd03(QixFrameCodec.decode(CAPTURE_FINAL_C5)));
        assertEquals(15, aligned.snapshot().acknowledgedOffset());

        StockQixTransferMachine fullResume = readyForC1(payload);
        assertAwaitFd03(fullResume.onFd03(c1(5, 15)), 0xC5);
        assertEquals(15, fullResume.snapshot().acknowledgedOffset());
        assertComplete(fullResume.onFd03(QixFrameCodec.decode(CAPTURE_FINAL_C5)));

        StockQixTransferMachine finalC3 = readyForC1(new byte[] {1, 2, 3, 4, 5});
        assertSend(finalC3.onFd03(c1(5, 0)), 0xC2);
        assertAwaitFd03(finalC3.onFd02WriteAcknowledged(), 0xC3, 0xC5);
        assertAwaitFd03(finalC3.onFd03(c3(5)), 0xC5);
        assertEquals(5, finalC3.snapshot().acknowledgedOffset());
        assertEquals(0, finalC3.snapshot().pendingLength());
        assertComplete(finalC3.onFd03(QixFrameCodec.decode(CAPTURE_FINAL_C5)));
    }

    @Test public void acceptedNonfinalC3UpdatesSnapshotAndImmediatelySendsNextC2() {
        StockQixTransferMachine machine = readyForC1(new byte[] {
                0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
        });
        assertSend(machine.onFd03(c1(5, 0)), 0xC2);
        assertAwaitFd03(machine.onFd02WriteAcknowledged(), 0xC3);

        StockQixTransferMachine.SendFd02 next = assertSend(machine.onFd03(c3(5)), 0xC2);
        assertArrayEquals(new byte[] {5, 0, 0, 0, 5, 0, 0, 0, 5, 6, 7, 8, 9},
                QixFrameCodec.decode(next.frame()).payload());
        StockQixTransferMachine.Snapshot snapshot = machine.snapshot();
        assertEquals(StockQixTransferMachine.Phase.WRITE_C2, snapshot.phase());
        assertEquals(5, snapshot.acknowledgedOffset());
        assertEquals(5, snapshot.pendingOffset());
        assertEquals(5, snapshot.pendingLength());
    }

    @Test public void c2SerialWrapsIndependentlyOfResponseFlags() {
        StockQixTransferMachine machine = readyForC1(new byte[16]);
        StockQixTransferMachine.Action c2Action = machine.onFd03(c1(1, 0));

        for (int block = 0; block < 16; block++) {
            StockQixTransferMachine.SendFd02 c2 = assertSend(c2Action, 0xC2);
            int expectedSerial = (block + 1) & 0x0F;
            assertEquals(0x01 | (expectedSerial << 3), QixFrameCodec.decode(c2.frame()).flags());
            StockQixTransferMachine.Action afterWrite = machine.onFd02WriteAcknowledged();
            if (block == 15) {
                assertAwaitFd03(afterWrite, 0xC3, 0xC5);
            } else {
                assertAwaitFd03(afterWrite, 0xC3);
                c2Action = machine.onFd03(c3WithFlags(0x7D, block + 1L));
            }
        }
    }

    @Test public void nestedActionsAndSnapshotsExposeOnlyDefensiveImmutableState() {
        TransitionArtifact artifact = artifact(new byte[] {0x55});
        StockQixTransferMachine machine = new StockQixTransferMachine(artifact);
        StockQixTransferMachine.Snapshot initial = machine.snapshot();
        assertEquals(StockQixTransferMachine.Phase.NEW, initial.phase());
        assertEquals(1, initial.totalBytes());
        assertEquals(0, initial.acknowledgedOffset());
        assertEquals(0, initial.pendingOffset());
        assertEquals(0, initial.pendingLength());
        assertTrue(initial.mayCancel());
        assertFalse(initial.terminal());
        assertEquals(StockQixTransferMachine.FailureCode.NONE, initial.failureCode());
        assertArrayEquals(artifact.qixSha256(), initial.qixSha256());
        assertArrayEquals(artifact.expectedBuildId(), initial.expectedBuildId());
        byte[] mutatedSnapshotSha = initial.qixSha256();
        byte[] mutatedSnapshotBuild = initial.expectedBuildId();
        mutatedSnapshotSha[0] ^= 0x7F;
        mutatedSnapshotBuild[0] ^= 0x7F;
        assertArrayEquals(artifact.qixSha256(), initial.qixSha256());
        assertArrayEquals(artifact.expectedBuildId(), initial.expectedBuildId());

        StockQixTransferMachine.SendFd02 bind = assertSend(machine.start(0x06, -1168149652), 0x60);
        byte[] bindFrame = bind.frame();
        bindFrame[0] ^= 0x7F;
        assertArrayEquals(StockQixBindCodec.request(0x06, -1168149652), bind.frame());
        assertEquals(StockQixTransferMachine.Action.Kind.SEND_FD02, bind.kind());

        StockQixTransferMachine.AwaitFd01 awaitBind = assertAwaitFd01(
                machine.onFd02WriteAcknowledged());
        assertEquals(StockQixTransferMachine.Action.Kind.AWAIT_FD01, awaitBind.kind());
        assertEquals(0x61, awaitBind.expectedOpcode());
        assertSend(machine.onFd01(bindResponse(0x04)), 0xC0);
        StockQixTransferMachine.AwaitFd03 awaitC1 = assertAwaitFd03(
                machine.onFd02WriteAcknowledged(), 0xC1);
        assertEquals(StockQixTransferMachine.Action.Kind.AWAIT_FD03, awaitC1.kind());
        int[] expectedC1 = awaitC1.expectedOpcodes();
        expectedC1[0] = 0;
        assertArrayEquals(new int[] {0xC1}, awaitC1.expectedOpcodes());

        assertSend(machine.onFd03(c1(1, 0)), 0xC2);
        StockQixTransferMachine.AwaitFd03 awaitFinal = assertAwaitFd03(
                machine.onFd02WriteAcknowledged(), 0xC3, 0xC5);
        int[] expectedFinal = awaitFinal.expectedOpcodes();
        expectedFinal[0] = 0;
        assertArrayEquals(new int[] {0xC3, 0xC5}, awaitFinal.expectedOpcodes());
        StockQixTransferMachine.AwaitFd03 awaitC5 = assertAwaitFd03(machine.onFd03(c3(1)), 0xC5);
        int[] expectedC5 = awaitC5.expectedOpcodes();
        expectedC5[0] = 0;
        assertArrayEquals(new int[] {0xC5}, awaitC5.expectedOpcodes());
        StockQixTransferMachine.Complete complete = assertComplete(
                machine.onFd03(QixFrameCodec.decode(CAPTURE_FINAL_C5)));
        assertEquals(StockQixTransferMachine.Action.Kind.COMPLETE, complete.kind());

        StockQixTransferMachine.Failed failed = assertFailure(
                new StockQixTransferMachine(artifact(new byte[] {1})).onFd02WriteAcknowledged(),
                StockQixTransferMachine.FailureCode.INVALID_STATE);
        assertEquals(StockQixTransferMachine.Action.Kind.FAILED, failed.kind());
        assertEquals(StockQixTransferMachine.FailureCode.INVALID_STATE, failed.failureCode());
    }

    @Test public void rejectsWrongChannelOpcodeAndState() {
        StockQixTransferMachine waitingForBind = waitingForBind(new byte[] {1});
        assertFailure(waitingForBind.onFd03(bindResponse(0x04)),
                StockQixTransferMachine.FailureCode.WRONG_CHANNEL);

        waitingForBind = waitingForBind(new byte[] {1});
        assertFailure(waitingForBind.onFd01(c1(1, 0)),
                StockQixTransferMachine.FailureCode.WRONG_CHANNEL);

        waitingForBind = waitingForBind(new byte[] {1});
        assertFailure(waitingForBind.onFd01(new QixFrame(0, 0x62, new byte[0])),
                StockQixTransferMachine.FailureCode.WRONG_OPCODE);

        StockQixTransferMachine fresh = new StockQixTransferMachine(artifact(new byte[] {1}));
        assertFailure(fresh.onFd03(c1(1, 0)), StockQixTransferMachine.FailureCode.INVALID_STATE);

        StockQixTransferMachine waitingForC1 = readyForC1(new byte[] {1});
        assertFailure(waitingForC1.onFd03(c3(0)),
                StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    @Test public void rejectsMalformedPayloadsProtocolResultsAndOrderingErrors() {
        assertFailure(waitingForBind(new byte[] {1}).onFd01(null),
                StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);

        byte[] rejectedBind = bindResponse(0x04).payload();
        rejectedBind[0] = 1;
        assertFailure(waitingForBind(new byte[] {1}).onFd01(new QixFrame(0x04, 0x61, rejectedBind)),
                StockQixTransferMachine.FailureCode.PROTOCOL_REJECTED);

        assertFailure(readyForC1(new byte[] {1}).onFd03(new QixFrame(0, 0xC1, new byte[8])),
                StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD);

        byte[] wrongState = c1(1, 0).payload();
        wrongState[0] = 0;
        assertFailure(readyForC1(new byte[] {1}).onFd03(new QixFrame(0, 0xC1, wrongState)),
                StockQixTransferMachine.FailureCode.PROTOCOL_REJECTED);

        StockQixTransferMachine c3Result = readyForC1(new byte[] {1, 2, 3, 4, 5});
        assertSend(c3Result.onFd03(c1(5, 0)), 0xC2);
        assertAwaitFd03(c3Result.onFd02WriteAcknowledged(), 0xC3, 0xC5);
        byte[] rejectedC3 = c3(5).payload();
        rejectedC3[0] = 1;
        assertFailure(c3Result.onFd03(new QixFrame(0, 0xC3, rejectedC3)),
                StockQixTransferMachine.FailureCode.PROTOCOL_REJECTED);

        StockQixTransferMachine notificationBeforeAck = new StockQixTransferMachine(artifact(new byte[] {1}));
        notificationBeforeAck.start(0x06, -1168149652);
        assertFailure(notificationBeforeAck.onFd01(bindResponse(0x04)),
                StockQixTransferMachine.FailureCode.INVALID_STATE);

        StockQixTransferMachine duplicateAck = waitingForBind(new byte[] {1});
        assertFailure(duplicateAck.onFd02WriteAcknowledged(),
                StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    @Test public void rejectsC3BeforeWriteAckNonmonotonicOffsetPrematureC5AndConcurrentC2() {
        StockQixTransferMachine beforeAck = readyForC1(new byte[] {1, 2, 3, 4, 5, 6});
        assertSend(beforeAck.onFd03(c1(5, 0)), 0xC2);
        assertFailure(beforeAck.onFd03(c3(5)),
                StockQixTransferMachine.FailureCode.INVALID_STATE);

        StockQixTransferMachine nonMonotonic = readyForC1(new byte[] {1, 2, 3, 4, 5, 6});
        assertSend(nonMonotonic.onFd03(c1(5, 0)), 0xC2);
        assertAwaitFd03(nonMonotonic.onFd02WriteAcknowledged(), 0xC3);
        assertFailure(nonMonotonic.onFd03(c3(4)),
                StockQixTransferMachine.FailureCode.OFFSET_MISMATCH);

        StockQixTransferMachine prematureC5 = readyForC1(new byte[] {1, 2, 3, 4, 5, 6});
        assertSend(prematureC5.onFd03(c1(5, 0)), 0xC2);
        assertAwaitFd03(prematureC5.onFd02WriteAcknowledged(), 0xC3);
        assertFailure(prematureC5.onFd03(QixFrameCodec.decode(CAPTURE_FINAL_C5)),
                StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    @Test public void externalFailureDomainsAreClosedAndLeaveInvalidCallsUntouched() {
        StockQixTransferMachine.FailureCode[] protocolCodes = new StockQixTransferMachine.FailureCode[] {
                StockQixTransferMachine.FailureCode.INVALID_STATE,
                StockQixTransferMachine.FailureCode.WRONG_CHANNEL,
                StockQixTransferMachine.FailureCode.WRONG_OPCODE,
                StockQixTransferMachine.FailureCode.MALFORMED_PAYLOAD,
                StockQixTransferMachine.FailureCode.PROTOCOL_REJECTED,
                StockQixTransferMachine.FailureCode.OFFSET_MISMATCH
        };
        StockQixTransferMachine.FailureCode[] transportCodes = new StockQixTransferMachine.FailureCode[] {
                StockQixTransferMachine.FailureCode.TRANSPORT_SETUP_FAILED,
                StockQixTransferMachine.FailureCode.TRANSPORT_WRITE_FAILED,
                StockQixTransferMachine.FailureCode.TRANSPORT_DISCONNECTED,
                StockQixTransferMachine.FailureCode.TRANSPORT_TIMEOUT,
                StockQixTransferMachine.FailureCode.CANCELLED,
                StockQixTransferMachine.FailureCode.FAILED_RECONNECT_REQUIRED
        };
        StockQixTransferMachine machine = new StockQixTransferMachine(artifact(new byte[] {1}));
        StockQixTransferMachine.Snapshot before = machine.snapshot();
        assertIllegalArgument(() -> machine.onProtocolFailed(null));
        assertIllegalArgument(() -> machine.onProtocolFailed(StockQixTransferMachine.FailureCode.NONE));
        assertIllegalArgument(() -> machine.onTransportFailed(null));
        assertIllegalArgument(() -> machine.onTransportFailed(StockQixTransferMachine.FailureCode.NONE));
        for (StockQixTransferMachine.FailureCode code : transportCodes) {
            assertIllegalArgument(() -> machine.onProtocolFailed(code));
        }
        for (StockQixTransferMachine.FailureCode code : protocolCodes) {
            assertIllegalArgument(() -> machine.onTransportFailed(code));
        }
        assertSameSnapshotValues(before, machine.snapshot());

        for (StockQixTransferMachine.FailureCode code : protocolCodes) {
            StockQixTransferMachine failed = new StockQixTransferMachine(artifact(new byte[] {1}));
            assertFailure(failed.onProtocolFailed(code), code);
            assertTrue(failed.snapshot().mayCancel());
        }

        for (StockQixTransferMachine.FailureCode code : transportCodes) {
            StockQixTransferMachine failed = new StockQixTransferMachine(artifact(new byte[] {1}));
            assertFailure(failed.onTransportFailed(code), code);
            assertTrue(failed.snapshot().mayCancel());
        }

        StockQixTransferMachine invalidC1 = readyForC1(new byte[] {1});
        assertTrue(invalidC1.snapshot().mayCancel());
        byte[] badState = c1(1, 0).payload();
        badState[0] = 0;
        assertFailure(invalidC1.onFd03(new QixFrame(0, 0xC1, badState)),
                StockQixTransferMachine.FailureCode.PROTOCOL_REJECTED);
        assertTrue(invalidC1.snapshot().mayCancel());

        StockQixTransferMachine acceptedC1 = readyForC1(new byte[] {1});
        assertTrue(acceptedC1.snapshot().mayCancel());
        assertSend(acceptedC1.onFd03(c1(1, 0)), 0xC2);
        assertFalse(acceptedC1.snapshot().mayCancel());
    }

    @Test public void terminalActionsAreStickyBeforeExternalFailureValidationExceptRestart() {
        StockQixTransferMachine completeMachine = readyForC1(new byte[] {1});
        assertSend(completeMachine.onFd03(c1(1, 0)), 0xC2);
        assertAwaitFd03(completeMachine.onFd02WriteAcknowledged(), 0xC3, 0xC5);
        StockQixTransferMachine.Action complete = completeMachine.onFd03(
                QixFrameCodec.decode(CAPTURE_FINAL_C5));
        assertComplete(complete);
        assertSame(complete, completeMachine.onProtocolFailed(null));
        assertSame(complete, completeMachine.onTransportFailed(
                StockQixTransferMachine.FailureCode.NONE));
        assertSame(complete, completeMachine.onFd03(null));

        StockQixTransferMachine.Action restart = completeMachine.start(0x06, -1168149652);
        assertFailure(restart, StockQixTransferMachine.FailureCode.INVALID_STATE);
        assertSame(restart, completeMachine.onFd02WriteAcknowledged());

        StockQixTransferMachine failedMachine = new StockQixTransferMachine(artifact(new byte[] {1}));
        StockQixTransferMachine.Action failed = failedMachine.onProtocolFailed(
                StockQixTransferMachine.FailureCode.WRONG_OPCODE);
        assertFailure(failed, StockQixTransferMachine.FailureCode.WRONG_OPCODE);
        assertSame(failed, failedMachine.onTransportFailed(
                StockQixTransferMachine.FailureCode.INVALID_STATE));
        assertSame(failed, failedMachine.onProtocolFailed(null));
        StockQixTransferMachine.Action invalidRestart = failedMachine.start(0x06, -1168149652);
        assertFailure(invalidRestart, StockQixTransferMachine.FailureCode.INVALID_STATE);
    }

    private static StockQixTransferMachine readyForC1(byte[] payload) {
        StockQixTransferMachine machine = new StockQixTransferMachine(artifact(payload));
        assertSend(machine.start(0x06, -1168149652), 0x60);
        assertAwaitFd01(machine.onFd02WriteAcknowledged());
        assertSend(machine.onFd01(bindResponse(0x04)), 0xC0);
        assertAwaitFd03(machine.onFd02WriteAcknowledged(), 0xC1);
        return machine;
    }

    private static StockQixTransferMachine waitingForBind(byte[] payload) {
        StockQixTransferMachine machine = new StockQixTransferMachine(artifact(payload));
        assertSend(machine.start(0x06, -1168149652), 0x60);
        assertAwaitFd01(machine.onFd02WriteAcknowledged());
        return machine;
    }

    private static TransitionArtifact artifact(byte[] payload) {
        return artifact(headerFor(payload.length), payload);
    }

    private static TransitionArtifact artifact(byte[] header, byte[] payload) {
        return new TransitionArtifact(header, payload, sha256(header, payload), buildId());
    }

    private static byte[] headerFor(long payloadLength) {
        byte[] header = new byte[27];
        header[0] = (byte) 0xBC;
        header[1] = (byte) 0xAF;
        header[2] = 0x01;
        byte[] version = "1.2.3".getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(version, 0, header, 3, version.length);
        putU32(header, 13, payloadLength);
        return header;
    }

    private static byte[] buildId() {
        byte[] buildId = new byte[16];
        for (int index = 0; index < buildId.length; index++) {
            buildId[index] = (byte) index;
        }
        return buildId;
    }

    private static byte[] sha256(byte[] header, byte[] payload) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(header);
            digest.update(payload);
            return digest.digest();
        } catch (NoSuchAlgorithmException failure) {
            throw new AssertionError(failure);
        }
    }

    private static QixFrame bindResponse(int flags) {
        return new QixFrame(flags, 0x61, new byte[] {
                0, 0, 0, 0, '1', '1', '.', '1', '.', '0', '.', '3', 0
        });
    }

    private static QixFrame c1(long window, long offset) {
        byte[] payload = new byte[9];
        payload[0] = 1;
        putU32(payload, 1, window);
        putU32(payload, 5, offset);
        return new QixFrame(0, 0xC1, payload);
    }

    private static QixFrame c3(long offset) {
        return c3WithFlags(0, offset);
    }

    private static QixFrame c3WithFlags(int flags, long offset) {
        byte[] payload = new byte[5];
        putU32(payload, 1, offset);
        return new QixFrame(flags, 0xC3, payload);
    }

    private static void putU32(byte[] bytes, int offset, long value) {
        bytes[offset] = (byte) value;
        bytes[offset + 1] = (byte) (value >>> 8);
        bytes[offset + 2] = (byte) (value >>> 16);
        bytes[offset + 3] = (byte) (value >>> 24);
    }

    private static StockQixTransferMachine.SendFd02 assertSend(
            StockQixTransferMachine.Action action, int expectedOpcode) {
        assertTrue(action instanceof StockQixTransferMachine.SendFd02);
        StockQixTransferMachine.SendFd02 send = (StockQixTransferMachine.SendFd02) action;
        assertEquals(StockQixTransferMachine.Action.Kind.SEND_FD02, send.kind());
        assertEquals(expectedOpcode, send.opcode());
        assertEquals(expectedOpcode, QixFrameCodec.decode(send.frame()).opcode());
        return send;
    }

    private static StockQixTransferMachine.AwaitFd01 assertAwaitFd01(
            StockQixTransferMachine.Action action) {
        assertTrue(action instanceof StockQixTransferMachine.AwaitFd01);
        StockQixTransferMachine.AwaitFd01 await = (StockQixTransferMachine.AwaitFd01) action;
        assertEquals(StockQixTransferMachine.Action.Kind.AWAIT_FD01, await.kind());
        assertEquals(0x61, await.expectedOpcode());
        return await;
    }

    private static StockQixTransferMachine.AwaitFd03 assertAwaitFd03(
            StockQixTransferMachine.Action action, int... expectedOpcodes) {
        assertTrue(action instanceof StockQixTransferMachine.AwaitFd03);
        StockQixTransferMachine.AwaitFd03 await = (StockQixTransferMachine.AwaitFd03) action;
        assertEquals(StockQixTransferMachine.Action.Kind.AWAIT_FD03, await.kind());
        assertArrayEquals(expectedOpcodes, await.expectedOpcodes());
        return await;
    }

    private static StockQixTransferMachine.Complete assertComplete(
            StockQixTransferMachine.Action action) {
        assertTrue(action instanceof StockQixTransferMachine.Complete);
        StockQixTransferMachine.Complete complete = (StockQixTransferMachine.Complete) action;
        assertEquals(StockQixTransferMachine.Action.Kind.COMPLETE, complete.kind());
        return complete;
    }

    private static StockQixTransferMachine.Failed assertFailure(
            StockQixTransferMachine.Action action, StockQixTransferMachine.FailureCode expected) {
        assertTrue(action instanceof StockQixTransferMachine.Failed);
        StockQixTransferMachine.Failed failed = (StockQixTransferMachine.Failed) action;
        assertEquals(StockQixTransferMachine.Action.Kind.FAILED, failed.kind());
        assertEquals(expected, failed.failureCode());
        return failed;
    }

    private static void assertSameSnapshotValues(StockQixTransferMachine.Snapshot expected,
            StockQixTransferMachine.Snapshot actual) {
        assertEquals(expected.phase(), actual.phase());
        assertEquals(expected.totalBytes(), actual.totalBytes());
        assertEquals(expected.acknowledgedOffset(), actual.acknowledgedOffset());
        assertEquals(expected.pendingOffset(), actual.pendingOffset());
        assertEquals(expected.pendingLength(), actual.pendingLength());
        assertEquals(expected.mayCancel(), actual.mayCancel());
        assertEquals(expected.terminal(), actual.terminal());
        assertEquals(expected.failureCode(), actual.failureCode());
        assertArrayEquals(expected.qixSha256(), actual.qixSha256());
        assertArrayEquals(expected.expectedBuildId(), actual.expectedBuildId());
    }

    private static byte[] fixture(String name) throws IOException {
        try (InputStream input = StockQixTransferMachineTest.class.getResourceAsStream(
                "/transition/" + name)) {
            if (input == null) {
                throw new IOException("missing fixture " + name);
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] block = new byte[256];
            for (int read; (read = input.read(block)) != -1;) {
                output.write(block, 0, read);
            }
            return output.toByteArray();
        }
    }

    private static void assertIllegalArgument(ThrowingRunnable runnable) {
        assertThrows(IllegalArgumentException.class, () -> runnable.run());
    }

    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}
