package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertThrows;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

public final class QixFrameAssemblerTest {
    @Test public void emptyFragmentsProduceNoFramesAndDoNotChangeState() {
        QixFrameAssembler assembler = new QixFrameAssembler();

        assertTrue(assembler.accept(new byte[0]).isEmpty());
        assertTrue(assembler.accept(new byte[0]).isEmpty());
        assertIllegalArgument(() -> assembler.accept(null));
    }

    @Test public void reassemblesBindRequestAtEveryByteBoundary() throws Exception {
        byte[] bind = fixture("qix-bind-request.bin");
        for (int split = 1; split < bind.length; split++) {
            QixFrameAssembler assembler = new QixFrameAssembler();
            assertTrue(assembler.accept(Arrays.copyOf(bind, split)).isEmpty());
            List<QixFrame> frames = assembler.accept(Arrays.copyOfRange(bind, split, bind.length));
            assertEquals(1, frames.size());
            assertArrayEquals(bind, QixFrameCodec.encode(
                    frames.get(0).flags(), frames.get(0).opcode(), frames.get(0).payload()));
        }
    }

    @Test public void reassemblesFd01BindResponseAcrossNotificationFragments() throws Exception {
        byte[] response = fixture("qix-bind-response-fd01.bin");
        QixFrameAssembler assembler = new QixFrameAssembler();
        List<QixFrame> frames = new ArrayList<QixFrame>();
        for (int offset = 0; offset < response.length; offset += 7) {
            frames.addAll(assembler.accept(Arrays.copyOfRange(response, offset,
                    Math.min(response.length, offset + 7))));
        }
        assertEquals(1, frames.size());
        assertEquals(0x61, frames.get(0).opcode());
        assertArrayEquals(response, QixFrameCodec.encode(
                frames.get(0).flags(), frames.get(0).opcode(), frames.get(0).payload()));
    }

    @Test public void emitsTwoConcatenatedFramesInInputOrder() throws Exception {
        byte[] first = fixture("qix-bind-request.bin");
        byte[] second = fixture("qix-c0-update-header-request.bin");
        byte[] concatenated = new byte[first.length + second.length];
        System.arraycopy(first, 0, concatenated, 0, first.length);
        System.arraycopy(second, 0, concatenated, first.length, second.length);

        List<QixFrame> frames = new QixFrameAssembler().accept(concatenated);
        assertEquals(2, frames.size());
        assertEquals(0x60, frames.get(0).opcode());
        assertEquals(0xC0, frames.get(1).opcode());
    }

    @Test public void handlesMaximumSizedFrameWithoutRetainingAnOversizedBuffer() {
        byte[] payload = new byte[65535];
        payload[0] = 1;
        payload[payload.length - 1] = 2;
        byte[] encoded = QixFrameCodec.encode(0, 0xC2, payload);
        QixFrameAssembler assembler = new QixFrameAssembler();

        assertTrue(assembler.accept(Arrays.copyOf(encoded, encoded.length - 1)).isEmpty());
        List<QixFrame> frames = assembler.accept(new byte[] {encoded[encoded.length - 1]});
        assertEquals(1, frames.size());
        assertArrayEquals(payload, frames.get(0).payload());
    }

    @Test public void rejectsBadAssemblyAndResetsBeforeTheNextFrame() throws Exception {
        byte[] valid = fixture("qix-bind-request.bin");
        QixFrameAssembler assembler = new QixFrameAssembler();
        assertIllegalArgument(() -> assembler.accept(new byte[] {0}));

        assertTrue(assembler.accept(Arrays.copyOf(valid, 6)).isEmpty());
        byte[] corruptedTail = Arrays.copyOfRange(valid, 6, valid.length);
        corruptedTail[0] ^= 1;
        assertIllegalArgument(() -> assembler.accept(corruptedTail));

        List<QixFrame> frames = assembler.accept(valid);
        assertEquals(1, frames.size());
        assertEquals(0x60, frames.get(0).opcode());
    }

    @Test public void resetDropsAnIncompleteSuffixDeterministically() throws Exception {
        byte[] valid = fixture("qix-bind-request.bin");
        QixFrameAssembler assembler = new QixFrameAssembler();
        assertTrue(assembler.accept(Arrays.copyOf(valid, 9)).isEmpty());
        assembler.reset();

        List<QixFrame> frames = assembler.accept(valid);
        assertEquals(1, frames.size());
        assertEquals(0x60, frames.get(0).opcode());
    }

    private static byte[] fixture(String name) throws IOException {
        try (InputStream input = QixFrameAssemblerTest.class.getResourceAsStream("/transition/" + name)) {
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
        void run();
    }
}
