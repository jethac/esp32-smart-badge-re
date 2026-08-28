package com.openai.e87probe;

import java.io.ByteArrayOutputStream;
import java.util.Arrays;

public final class RootBrowseSession {
    public static final int MAX_BYTES = 4096;
    public static final int MAX_RECORDS = 10;

    public enum AppendResult { ACCEPTED, LIMIT_REACHED, IGNORED_AFTER_LIMIT }

    private final ByteArrayOutputStream data = new ByteArrayOutputStream();
    private boolean started;
    private boolean finished;
    private boolean collecting = true;
    private boolean dataBeyondLimit;

    public void acceptStartResponse(int status) {
        if (started || finished) {
            throw new IllegalStateException("browse start response already handled");
        }
        if (status != 0) {
            throw new IllegalArgumentException("browse start failed with status " + status);
        }
        started = true;
    }

    public AppendResult appendData(byte[] chunk) {
        if (!started || finished) {
            throw new IllegalStateException("browse data received outside active session");
        }
        if (chunk == null) throw new IllegalArgumentException("browse data is null");
        if (!collecting) {
            if (chunk.length > 0) dataBeyondLimit = true;
            return AppendResult.IGNORED_AFTER_LIMIT;
        }

        byte[] existing = data.toByteArray();
        int retainedLength = Math.min(MAX_BYTES, existing.length + chunk.length);
        byte[] candidate = Arrays.copyOf(existing, retainedLength);
        int copied = retainedLength - existing.length;
        if (copied > 0) System.arraycopy(chunk, 0, candidate, existing.length, copied);

        int tenthRecordEnd = findTenthRecordEnd(candidate);
        if (tenthRecordEnd >= 0) {
            replaceData(Arrays.copyOf(candidate, tenthRecordEnd));
            collecting = false;
            if (existing.length + chunk.length > tenthRecordEnd) dataBeyondLimit = true;
            return AppendResult.LIMIT_REACHED;
        }
        replaceData(candidate);
        if (existing.length + chunk.length >= MAX_BYTES) {
            collecting = false;
            if (existing.length + chunk.length > MAX_BYTES) dataBeyondLimit = true;
            return AppendResult.LIMIT_REACHED;
        }
        return AppendResult.ACCEPTED;
    }

    public byte[] rawData() {
        return data.toByteArray();
    }

    public boolean hasDataBeyondLimit() {
        return dataBeyondLimit;
    }

    public RootDirectoryPage finish() {
        if (!started || finished) {
            throw new IllegalStateException("browse stop received outside active session");
        }
        RootDirectoryPage page = RootDirectoryPage.parse(data.toByteArray(), MAX_RECORDS);
        finished = true;
        return page;
    }

    private void replaceData(byte[] bytes) {
        data.reset();
        data.write(bytes, 0, bytes.length);
    }

    private static int findTenthRecordEnd(byte[] bytes) {
        int cursor = 0;
        int count = 0;
        while (bytes.length - cursor >= 8) {
            int recordLength = 8 + (bytes[cursor + 7] & 0xFF);
            if (bytes.length - cursor < recordLength) return -1;
            cursor += recordLength;
            count++;
            if (count == MAX_RECORDS) return cursor;
        }
        return -1;
    }
}
