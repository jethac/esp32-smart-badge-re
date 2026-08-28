package net.jethachan.factory_badges.transition;

import java.util.Arrays;

/**
 * Pure, single-use reducer for the captured FD00/Qix stock transfer conversation.
 *
 * <p>The caller performs transport writes and invokes one logical acknowledgement only after all
 * fragments of that frame have completed. This class neither performs I/O nor depends on Android.
 */
public final class StockQixTransferMachine {
    private static final int BIND_RESPONSE_OPCODE = 0x61;
    private static final int BIND_ACK_OPCODE = 0xFF;
    private static final int C0_OPCODE = 0xC0;
    private static final int C1_OPCODE = 0xC1;
    private static final int C2_OPCODE = 0xC2;
    private static final int C3_OPCODE = 0xC3;
    private static final int C5_OPCODE = 0xC5;
    private static final int MAX_WINDOW = 65_527;

    public enum Phase {
        NEW, WRITE_BIND, WAIT_BIND, WRITE_BIND_ACK, WRITE_C0, WAIT_C1,
        WRITE_C2, WAIT_C3, WAIT_FINAL, WAIT_C5, COMPLETE, FAILED
    }

    public enum FailureCode {
        NONE, INVALID_STATE, WRONG_CHANNEL, WRONG_OPCODE, MALFORMED_PAYLOAD,
        PROTOCOL_REJECTED, OFFSET_MISMATCH, TRANSPORT_SETUP_FAILED,
        TRANSPORT_WRITE_FAILED, TRANSPORT_DISCONNECTED, TRANSPORT_TIMEOUT, CANCELLED,
        FAILED_RECONNECT_REQUIRED
    }

    public abstract static class Action {
        public enum Kind {
            SEND_FD02, AWAIT_FD01, AWAIT_FD03, COMPLETE, FAILED
        }

        public abstract Kind kind();
    }

    public static final class SendFd02 extends Action {
        private final byte[] frame;
        private final int opcode;

        private SendFd02(byte[] frame, int opcode) {
            if (frame == null || opcode < 0 || opcode > 0xFF) {
                throw new IllegalArgumentException("send action needs a complete frame and opcode");
            }
            this.frame = Arrays.copyOf(frame, frame.length);
            this.opcode = opcode;
        }

        @Override public Kind kind() {
            return Kind.SEND_FD02;
        }

        public byte[] frame() {
            return Arrays.copyOf(frame, frame.length);
        }

        public int opcode() {
            return opcode;
        }
    }

    public static final class AwaitFd01 extends Action {
        private AwaitFd01() {
        }

        @Override public Kind kind() {
            return Kind.AWAIT_FD01;
        }

        public int expectedOpcode() {
            return BIND_RESPONSE_OPCODE;
        }
    }

    public static final class AwaitFd03 extends Action {
        private final int[] expectedOpcodes;

        private AwaitFd03(int[] expectedOpcodes) {
            if (expectedOpcodes == null || expectedOpcodes.length == 0) {
                throw new IllegalArgumentException("FD03 wait action needs expected opcodes");
            }
            this.expectedOpcodes = Arrays.copyOf(expectedOpcodes, expectedOpcodes.length);
        }

        @Override public Kind kind() {
            return Kind.AWAIT_FD03;
        }

        public int[] expectedOpcodes() {
            return Arrays.copyOf(expectedOpcodes, expectedOpcodes.length);
        }
    }

    public static final class Complete extends Action {
        private Complete() {
        }

        @Override public Kind kind() {
            return Kind.COMPLETE;
        }
    }

    public static final class Failed extends Action {
        private final FailureCode failureCode;

        private Failed(FailureCode failureCode) {
            if (failureCode == null || failureCode == FailureCode.NONE) {
                throw new IllegalArgumentException("failed action needs a concrete failure code");
            }
            this.failureCode = failureCode;
        }

        @Override public Kind kind() {
            return Kind.FAILED;
        }

        public FailureCode failureCode() {
            return failureCode;
        }
    }

    public static final class Snapshot {
        private final Phase phase;
        private final long totalBytes;
        private final long acknowledgedOffset;
        private final long pendingOffset;
        private final int pendingLength;
        private final boolean mayCancel;
        private final boolean terminal;
        private final FailureCode failureCode;
        private final byte[] qixSha256;
        private final byte[] expectedBuildId;

        private Snapshot(Phase phase, long totalBytes, long acknowledgedOffset,
                long pendingOffset, int pendingLength, boolean mayCancel, boolean terminal,
                FailureCode failureCode, byte[] qixSha256, byte[] expectedBuildId) {
            this.phase = phase;
            this.totalBytes = totalBytes;
            this.acknowledgedOffset = acknowledgedOffset;
            this.pendingOffset = pendingOffset;
            this.pendingLength = pendingLength;
            this.mayCancel = mayCancel;
            this.terminal = terminal;
            this.failureCode = failureCode;
            this.qixSha256 = Arrays.copyOf(qixSha256, qixSha256.length);
            this.expectedBuildId = Arrays.copyOf(expectedBuildId, expectedBuildId.length);
        }

        public Phase phase() {
            return phase;
        }

        public long totalBytes() {
            return totalBytes;
        }

        public long acknowledgedOffset() {
            return acknowledgedOffset;
        }

        public long pendingOffset() {
            return pendingOffset;
        }

        public int pendingLength() {
            return pendingLength;
        }

        public boolean mayCancel() {
            return mayCancel;
        }

        public boolean terminal() {
            return terminal;
        }

        public FailureCode failureCode() {
            return failureCode;
        }

        public byte[] qixSha256() {
            return Arrays.copyOf(qixSha256, qixSha256.length);
        }

        public byte[] expectedBuildId() {
            return Arrays.copyOf(expectedBuildId, expectedBuildId.length);
        }
    }

    private final TransitionArtifact artifact;
    private final byte[] qixHeader;
    private final byte[] ufwPayload;
    private final byte[] qixSha256;
    private final byte[] expectedBuildId;

    private Phase phase = Phase.NEW;
    private FailureCode failureCode = FailureCode.NONE;
    private long window;
    private long acknowledgedOffset;
    private long pendingOffset;
    private int pendingLength;
    private int nextBindSerial = 1;
    private int nextC2Serial = 1;
    private boolean mayCancel = true;
    private Action terminalAction;
    private Snapshot snapshot;

    public StockQixTransferMachine(TransitionArtifact artifact) {
        if (artifact == null) {
            throw new IllegalArgumentException("transition artifact must not be null");
        }
        this.artifact = artifact;
        this.qixHeader = artifact.qixHeader();
        this.ufwPayload = artifact.ufwPayload();
        this.qixSha256 = artifact.qixSha256();
        this.expectedBuildId = artifact.expectedBuildId();
        refreshSnapshot();
    }

    public Action start(int settings, int hostId) {
        if (phase != Phase.NEW) {
            return enterFailure(FailureCode.INVALID_STATE);
        }
        byte[] bind = StockQixBindCodec.request(settings, hostId);
        phase = Phase.WRITE_BIND;
        refreshSnapshot();
        return new SendFd02(bind, 0x60);
    }

    public Action onFd01(QixFrame frame) {
        if (isTerminal()) {
            return terminalAction;
        }
        if (frame == null) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        int opcode = frame.opcode();
        if (isFd03Opcode(opcode)) {
            return enterFailure(FailureCode.WRONG_CHANNEL);
        }
        if (opcode != BIND_RESPONSE_OPCODE) {
            return enterFailure(FailureCode.WRONG_OPCODE);
        }
        if (phase != Phase.WAIT_BIND) {
            return enterFailure(FailureCode.INVALID_STATE);
        }

        byte[] payload = frame.payload();
        if (payload.length == 0) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        if (payload[0] != 0) {
            return enterFailure(FailureCode.PROTOCOL_REJECTED);
        }
        final StockQixBindCodec.BindResponse response;
        try {
            response = StockQixBindCodec.parseResponse(frame);
        } catch (IllegalArgumentException failure) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        if (response.requestsReply()) {
            byte[] bindAck = StockQixBindCodec.successAck(BIND_RESPONSE_OPCODE, nextBindSerial);
            nextBindSerial = (nextBindSerial + 1) & 0x0F;
            phase = Phase.WRITE_BIND_ACK;
            refreshSnapshot();
            return new SendFd02(bindAck, BIND_ACK_OPCODE);
        }
        return sendC0();
    }

    public Action onFd03(QixFrame frame) {
        if (isTerminal()) {
            return terminalAction;
        }
        if (frame == null) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        int opcode = frame.opcode();
        if (isFd01Opcode(opcode)) {
            return enterFailure(FailureCode.WRONG_CHANNEL);
        }
        if (!isFd03Opcode(opcode)) {
            return enterFailure(FailureCode.WRONG_OPCODE);
        }

        if (phase == Phase.WAIT_C1) {
            if (opcode != C1_OPCODE) {
                return enterFailure(FailureCode.INVALID_STATE);
            }
            return onC1(frame);
        }
        if (phase == Phase.WAIT_C3) {
            if (opcode != C3_OPCODE) {
                return enterFailure(FailureCode.INVALID_STATE);
            }
            return onC3(frame, false);
        }
        if (phase == Phase.WAIT_FINAL) {
            if (opcode == C3_OPCODE) {
                return onC3(frame, true);
            }
            if (opcode == C5_OPCODE) {
                return onC5(frame, true);
            }
            return enterFailure(FailureCode.INVALID_STATE);
        }
        if (phase == Phase.WAIT_C5) {
            if (opcode != C5_OPCODE) {
                return enterFailure(FailureCode.INVALID_STATE);
            }
            return onC5(frame, false);
        }
        return enterFailure(FailureCode.INVALID_STATE);
    }

    public Action onFd02WriteAcknowledged() {
        if (isTerminal()) {
            return terminalAction;
        }
        if (phase == Phase.WRITE_BIND) {
            phase = Phase.WAIT_BIND;
            refreshSnapshot();
            return new AwaitFd01();
        }
        if (phase == Phase.WRITE_BIND_ACK) {
            return sendC0();
        }
        if (phase == Phase.WRITE_C0) {
            phase = Phase.WAIT_C1;
            refreshSnapshot();
            return awaitFd03(C1_OPCODE);
        }
        if (phase == Phase.WRITE_C2) {
            long expectedNextOffset = pendingOffset + pendingLength;
            phase = expectedNextOffset == ufwPayload.length ? Phase.WAIT_FINAL : Phase.WAIT_C3;
            refreshSnapshot();
            return expectedNextOffset == ufwPayload.length
                    ? awaitFd03(C3_OPCODE, C5_OPCODE) : awaitFd03(C3_OPCODE);
        }
        return enterFailure(FailureCode.INVALID_STATE);
    }

    public Action onProtocolFailed(FailureCode failureCode) {
        if (isTerminal()) {
            return terminalAction;
        }
        if (!isProtocolFailureInput(failureCode)) {
            throw new IllegalArgumentException("not a protocol failure input");
        }
        return enterFailure(failureCode);
    }

    public Action onTransportFailed(FailureCode failureCode) {
        if (isTerminal()) {
            return terminalAction;
        }
        if (!isTransportFailureInput(failureCode)) {
            throw new IllegalArgumentException("not a transport failure input");
        }
        return enterFailure(failureCode);
    }

    public Snapshot snapshot() {
        return snapshot;
    }

    private Action sendC0() {
        byte[] c0 = QixFrameCodec.encode(0x05, C0_OPCODE, qixHeader);
        phase = Phase.WRITE_C0;
        refreshSnapshot();
        return new SendFd02(c0, C0_OPCODE);
    }

    private Action onC1(QixFrame frame) {
        byte[] payload = frame.payload();
        if (payload.length != 9) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        if ((payload[0] & 0xFF) != 1) {
            return enterFailure(FailureCode.PROTOCOL_REJECTED);
        }
        long allowedLength = readUnsignedU32(payload, 1);
        long resumeOffset = readUnsignedU32(payload, 5);
        if (allowedLength < 1 || allowedLength > MAX_WINDOW) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        if (resumeOffset > ufwPayload.length) {
            return enterFailure(FailureCode.OFFSET_MISMATCH);
        }
        if (resumeOffset != ufwPayload.length && (resumeOffset % allowedLength) != 0) {
            return enterFailure(FailureCode.OFFSET_MISMATCH);
        }

        window = allowedLength;
        acknowledgedOffset = resumeOffset;
        pendingOffset = resumeOffset;
        pendingLength = 0;
        mayCancel = false;
        if (resumeOffset == ufwPayload.length) {
            phase = Phase.WAIT_C5;
            refreshSnapshot();
            return awaitFd03(C5_OPCODE);
        }
        return sendNextC2();
    }

    private Action sendNextC2() {
        long remaining = ufwPayload.length - acknowledgedOffset;
        if (remaining <= 0 || window < 1 || window > MAX_WINDOW) {
            return enterFailure(FailureCode.INVALID_STATE);
        }
        int chunkLength = (int) Math.min(window, remaining);
        byte[] payload = new byte[8 + chunkLength];
        putUnsignedU32(payload, 0, chunkLength);
        putUnsignedU32(payload, 4, acknowledgedOffset);
        System.arraycopy(ufwPayload, (int) acknowledgedOffset, payload, 8, chunkLength);

        int flags = 0x01 | (nextC2Serial << 3);
        if (14 + chunkLength > 20) {
            flags |= 0x04;
        }
        nextC2Serial = (nextC2Serial + 1) & 0x0F;
        pendingOffset = acknowledgedOffset;
        pendingLength = chunkLength;
        phase = Phase.WRITE_C2;
        refreshSnapshot();
        return new SendFd02(QixFrameCodec.encode(flags, C2_OPCODE, payload), C2_OPCODE);
    }

    private Action onC3(QixFrame frame, boolean finalC2WasAcknowledged) {
        byte[] payload = frame.payload();
        if (payload.length != 5) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        if (payload[0] != 0) {
            return enterFailure(FailureCode.PROTOCOL_REJECTED);
        }
        long nextOffset = readUnsignedU32(payload, 1);
        long expectedOffset = pendingOffset + pendingLength;
        if (nextOffset != expectedOffset) {
            return enterFailure(FailureCode.OFFSET_MISMATCH);
        }
        if (finalC2WasAcknowledged) {
            if (nextOffset != ufwPayload.length) {
                return enterFailure(FailureCode.OFFSET_MISMATCH);
            }
            acknowledgedOffset = nextOffset;
            pendingOffset = nextOffset;
            pendingLength = 0;
            phase = Phase.WAIT_C5;
            refreshSnapshot();
            return awaitFd03(C5_OPCODE);
        }

        acknowledgedOffset = nextOffset;
        return sendNextC2();
    }

    private Action onC5(QixFrame frame, boolean directFinalC5) {
        byte[] payload = frame.payload();
        if (payload.length != 1) {
            return enterFailure(FailureCode.MALFORMED_PAYLOAD);
        }
        if (payload[0] != 0) {
            return enterFailure(FailureCode.PROTOCOL_REJECTED);
        }
        if (directFinalC5) {
            acknowledgedOffset = ufwPayload.length;
        } else if (acknowledgedOffset != ufwPayload.length) {
            return enterFailure(FailureCode.OFFSET_MISMATCH);
        }
        pendingOffset = ufwPayload.length;
        pendingLength = 0;
        phase = Phase.COMPLETE;
        terminalAction = new Complete();
        refreshSnapshot();
        return terminalAction;
    }

    private Action enterFailure(FailureCode code) {
        phase = Phase.FAILED;
        failureCode = code;
        terminalAction = new Failed(code);
        refreshSnapshot();
        return terminalAction;
    }

    private void refreshSnapshot() {
        boolean terminal = isTerminal();
        FailureCode snapshotFailure = phase == Phase.FAILED ? failureCode : FailureCode.NONE;
        snapshot = new Snapshot(phase, ufwPayload.length, acknowledgedOffset, pendingOffset,
                pendingLength, mayCancel, terminal, snapshotFailure, qixSha256, expectedBuildId);
    }

    private boolean isTerminal() {
        return phase == Phase.COMPLETE || phase == Phase.FAILED;
    }

    private static AwaitFd03 awaitFd03(int... expectedOpcodes) {
        return new AwaitFd03(expectedOpcodes);
    }

    private static boolean isFd01Opcode(int opcode) {
        return opcode == 0x60 || opcode == BIND_RESPONSE_OPCODE || opcode == BIND_ACK_OPCODE;
    }

    private static boolean isFd03Opcode(int opcode) {
        return opcode == C1_OPCODE || opcode == C3_OPCODE || opcode == C5_OPCODE;
    }

    private static boolean isProtocolFailureInput(FailureCode failureCode) {
        return failureCode == FailureCode.INVALID_STATE
                || failureCode == FailureCode.WRONG_CHANNEL
                || failureCode == FailureCode.WRONG_OPCODE
                || failureCode == FailureCode.MALFORMED_PAYLOAD
                || failureCode == FailureCode.PROTOCOL_REJECTED
                || failureCode == FailureCode.OFFSET_MISMATCH;
    }

    private static boolean isTransportFailureInput(FailureCode failureCode) {
        return failureCode == FailureCode.TRANSPORT_SETUP_FAILED
                || failureCode == FailureCode.TRANSPORT_WRITE_FAILED
                || failureCode == FailureCode.TRANSPORT_DISCONNECTED
                || failureCode == FailureCode.TRANSPORT_TIMEOUT
                || failureCode == FailureCode.CANCELLED
                || failureCode == FailureCode.FAILED_RECONNECT_REQUIRED;
    }

    private static long readUnsignedU32(byte[] bytes, int offset) {
        return ((long) bytes[offset] & 0xFF)
                | (((long) bytes[offset + 1] & 0xFF) << 8)
                | (((long) bytes[offset + 2] & 0xFF) << 16)
                | (((long) bytes[offset + 3] & 0xFF) << 24);
    }

    private static void putUnsignedU32(byte[] bytes, int offset, long value) {
        bytes[offset] = (byte) value;
        bytes[offset + 1] = (byte) (value >>> 8);
        bytes[offset + 2] = (byte) (value >>> 16);
        bytes[offset + 3] = (byte) (value >>> 24);
    }
}
