package com.openai.e87probe;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

public final class RootDirectoryPage {
    public final List<Entry> entries;

    private RootDirectoryPage(List<Entry> entries) {
        this.entries = Collections.unmodifiableList(entries);
    }

    public static RootDirectoryPage parse(byte[] data, int maxRecords) {
        if (data == null) throw new IllegalArgumentException("directory data is null");
        if (maxRecords < 1 || maxRecords > 10) {
            throw new IllegalArgumentException("maxRecords must be between 1 and 10");
        }
        List<Entry> entries = new ArrayList<>();
        int cursor = 0;
        while (cursor < data.length) {
            if (entries.size() >= maxRecords) {
                throw new IllegalArgumentException("directory page exceeds record limit");
            }
            if (data.length - cursor < 8) {
                throw new IllegalArgumentException("truncated directory record header");
            }
            int flags = data[cursor] & 0xFF;
            long cluster = readBe32(data, cursor + 1);
            int ordinal = ((data[cursor + 5] & 0xFF) << 8)
                    | (data[cursor + 6] & 0xFF);
            int nameLength = data[cursor + 7] & 0xFF;
            int recordLength = 8 + nameLength;
            if (data.length - cursor < recordLength) {
                throw new IllegalArgumentException("truncated directory record name");
            }
            boolean gbk = (flags & 0x02) != 0;
            Charset charset = gbk ? Charset.forName("GBK") : StandardCharsets.UTF_16LE;
            String name;
            try {
                name = charset.newDecoder()
                        .onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT)
                        .decode(ByteBuffer.wrap(data, cursor + 8, nameLength))
                        .toString();
            } catch (CharacterCodingException error) {
                throw new IllegalArgumentException("invalid directory filename encoding", error);
            }
            entries.add(new Entry(
                    (flags & 0x01) != 0,
                    (flags >>> 2) & 0x1F,
                    cluster,
                    ordinal,
                    gbk,
                    name));
            cursor += recordLength;
        }
        return new RootDirectoryPage(entries);
    }

    public String toEvidenceText() {
        StringBuilder out = new StringBuilder();
        out.append("count=").append(entries.size()).append('\n');
        for (int i = 0; i < entries.size(); i++) {
            Entry entry = entries.get(i);
            String escapedName = entry.name
                    .replace("\\", "\\\\")
                    .replace("\t", "\\t")
                    .replace("\r", "\\r")
                    .replace("\n", "\\n");
            out.append(i)
                    .append('\t').append(entry.file ? "file" : "directory")
                    .append("\tdevIndex=").append(entry.deviceIndex)
                    .append("\tcluster=").append(String.format(
                            Locale.ROOT, "0x%08X", entry.cluster))
                    .append("\tordinal=").append(entry.ordinal)
                    .append("\tencoding=").append(entry.gbk ? "GBK" : "UTF-16LE")
                    .append("\tnameUtf8Hex=").append(Hex.encode(
                            entry.name.getBytes(StandardCharsets.UTF_8)))
                    .append("\tname=").append(escapedName)
                    .append('\n');
        }
        return out.toString();
    }

    private static long readBe32(byte[] data, int offset) {
        return ((long) (data[offset] & 0xFF) << 24)
                | ((long) (data[offset + 1] & 0xFF) << 16)
                | ((long) (data[offset + 2] & 0xFF) << 8)
                | (long) (data[offset + 3] & 0xFF);
    }

    public static final class Entry {
        public final boolean file;
        public final int deviceIndex;
        public final long cluster;
        public final int ordinal;
        public final boolean gbk;
        public final String name;

        private Entry(boolean file, int deviceIndex, long cluster, int ordinal,
                      boolean gbk, String name) {
            this.file = file;
            this.deviceIndex = deviceIndex;
            this.cluster = cluster;
            this.ordinal = ordinal;
            this.gbk = gbk;
            this.name = name;
        }
    }
}
