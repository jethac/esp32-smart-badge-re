package com.openai.e87probe;

public final class ProbeRunState {
    public static final long BROWSE_WINDOW_MS = 20_000L;

    public enum ResponseResult { ACCEPTED, IGNORED, EXPIRED }
    public enum BrowseEventResult { ACCEPTED, UNEXPECTED, EXPIRED }

    private enum Phase {
        READY,
        WAIT_TARGET_RESPONSE,
        TARGET_ACCEPTED,
        WAIT_STORAGE_RESPONSE,
        STORAGE_ACCEPTED,
        WAIT_BROWSE_START_RESPONSE,
        RECEIVE_BROWSE,
        ACK_DRAIN,
        TERMINAL
    }

    private Phase phase = Phase.READY;
    private int expectedOpcode = -1;
    private int expectedSequence = -1;
    private long browseDeadlineMillis = -1L;
    private int stopSequence = -1;
    private int stopReason = -1;
    private boolean startedRcsp;

    public void beginRequest(int opcode, int sequence, long nowMillis) {
        if ((sequence & ~0xFF) != 0) {
            throw new IllegalArgumentException("sequence must be uint8");
        }
        Phase next;
        if (opcode == RcspProtocol.GET_TARGET_INFO && phase == Phase.READY) {
            next = Phase.WAIT_TARGET_RESPONSE;
        } else if (opcode == RcspProtocol.GET_SYS_INFO && phase == Phase.TARGET_ACCEPTED) {
            next = Phase.WAIT_STORAGE_RESPONSE;
        } else if (opcode == RcspProtocol.START_FILE_BROWSE
                && phase == Phase.STORAGE_ACCEPTED) {
            next = Phase.WAIT_BROWSE_START_RESPONSE;
            browseDeadlineMillis = nowMillis + BROWSE_WINDOW_MS;
        } else {
            throw new IllegalStateException("request opcode 0x"
                    + Integer.toHexString(opcode) + " is illegal in phase " + phase);
        }
        expectedOpcode = opcode;
        expectedSequence = sequence;
        phase = next;
        startedRcsp = true;
    }

    public ResponseResult acceptResponse(int opcode, int sequence, long nowMillis) {
        if (isBrowseTimedPhase() && isExpired(nowMillis)) {
            return ResponseResult.EXPIRED;
        }
        if (!isWaitingForResponse()
                || opcode != expectedOpcode || sequence != expectedSequence) {
            return ResponseResult.IGNORED;
        }
        expectedOpcode = -1;
        expectedSequence = -1;
        if (phase == Phase.WAIT_TARGET_RESPONSE) phase = Phase.TARGET_ACCEPTED;
        else if (phase == Phase.WAIT_STORAGE_RESPONSE) phase = Phase.STORAGE_ACCEPTED;
        else phase = Phase.RECEIVE_BROWSE;
        return ResponseResult.ACCEPTED;
    }

    public BrowseEventResult acceptBrowseData(long nowMillis) {
        if (phase != Phase.RECEIVE_BROWSE) return BrowseEventResult.UNEXPECTED;
        return isExpired(nowMillis)
                ? BrowseEventResult.EXPIRED : BrowseEventResult.ACCEPTED;
    }

    public BrowseEventResult beginAckDrain(int sequence, int reason, long nowMillis) {
        if ((sequence & ~0xFF) != 0 || (reason & ~0xFF) != 0) {
            throw new IllegalArgumentException("stop sequence and reason must be uint8");
        }
        if (phase != Phase.RECEIVE_BROWSE) return BrowseEventResult.UNEXPECTED;
        boolean expired = isExpired(nowMillis);
        stopSequence = sequence;
        stopReason = reason;
        phase = Phase.ACK_DRAIN;
        return expired ? BrowseEventResult.EXPIRED : BrowseEventResult.ACCEPTED;
    }

    public boolean isExactStopDuplicate(int sequence, int reason) {
        return phase == Phase.ACK_DRAIN
                && stopSequence == sequence && stopReason == reason;
    }

    public boolean isReceivingBrowse() {
        return phase == Phase.RECEIVE_BROWSE;
    }

    public boolean hasStartedRcsp() {
        return startedRcsp;
    }

    public long remainingBrowseMillis(long nowMillis) {
        if (browseDeadlineMillis < 0) return 0L;
        return Math.max(0L, browseDeadlineMillis - nowMillis);
    }

    public void markTerminal() {
        expectedOpcode = -1;
        expectedSequence = -1;
        phase = Phase.TERMINAL;
    }

    private boolean isWaitingForResponse() {
        return phase == Phase.WAIT_TARGET_RESPONSE
                || phase == Phase.WAIT_STORAGE_RESPONSE
                || phase == Phase.WAIT_BROWSE_START_RESPONSE;
    }

    private boolean isBrowseTimedPhase() {
        return phase == Phase.WAIT_BROWSE_START_RESPONSE || phase == Phase.RECEIVE_BROWSE;
    }

    private boolean isExpired(long nowMillis) {
        return browseDeadlineMillis >= 0 && nowMillis >= browseDeadlineMillis;
    }
}
