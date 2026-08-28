package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import org.junit.Test;

public final class QixFrameCodecTest {
    @Test public void captureVectorsHavePinnedHashesAndDecodeExactly() throws Exception {
        byte[] bindRequest = fixture("qix-bind-request.bin");
        byte[] bindResponse = fixture("qix-bind-response-fd01.bin");
        byte[] c0 = fixture("qix-c0-update-header-request.bin");
        byte[] firstC2 = fixture("qix-c2-first.bin");
        byte[] lastC2 = fixture("qix-c2-last.bin");

        assertEquals("8C79A1003503843C2AAFE16C5EBA22DD83D00139C00DDE5B48AACB1E7F44B608",
                sha256(bindRequest));
        assertEquals("4762B7EABBFDF4293BA1A362C1D3DB84F85849DDF140660BAF91C54F0D78DC26",
                sha256(bindResponse));
        assertEquals("FEF8138346C609E7982842DE3CE5CB351704CD46475166962DD21BB96D03FC8E",
                sha256(c0));
        assertEquals("FD24BEE44DB57B0C90FE62622709570BF836610EF403AE9666DAD32F72804EF3",
                sha256(firstC2));
        assertEquals("6F57560661B6C0FE94B15A9DD96CBCAE8D3CFCE86443F36E9C4E2C775B3C58BF",
                sha256(lastC2));

        assertFrame(bindRequest, 0x02, 0x60, 13);
        assertFrame(bindResponse, 0x04, 0x61, 30);
        assertFrame(c0, 0x05, 0xC0, 27);
        assertFrame(firstC2, 0x0D, 0xC2, 1032);
        assertFrame(lastC2, 0x05, 0xC2, 48);
    }

    @Test public void encodeAndFrameConstructorDefendAgainstMutation() {
        byte[] source = new byte[] {1, 2, 3};
        QixFrame frame = new QixFrame(0x02, 0x60, source);
        source[0] = 9;
        assertArrayEquals(new byte[] {1, 2, 3}, frame.payload());
        byte[] returned = frame.payload();
        returned[1] = 9;
        assertArrayEquals(new byte[] {1, 2, 3}, frame.payload());

        byte[] encoded = QixFrameCodec.encode(frame.flags(), frame.opcode(), frame.payload());
        encoded[6] = 9;
        assertArrayEquals(new byte[] {1, 2, 3}, QixFrameCodec.decode(
                QixFrameCodec.encode(0x02, 0x60, new byte[] {1, 2, 3})).payload());
    }

    @Test public void rejectsOutOfRangeFieldsNullsAndOversizedPayloads() {
        assertIllegalArgument(() -> new QixFrame(-1, 0, new byte[0]));
        assertIllegalArgument(() -> new QixFrame(0, 256, new byte[0]));
        assertIllegalArgument(() -> new QixFrame(0, 0, null));
        assertIllegalArgument(() -> QixFrameCodec.encode(-1, 0, new byte[0]));
        assertIllegalArgument(() -> QixFrameCodec.encode(0, 256, new byte[0]));
        assertIllegalArgument(() -> QixFrameCodec.encode(0, 0, null));
        assertIllegalArgument(() -> QixFrameCodec.encode(0, 0, new byte[65536]));
    }

    @Test public void decodeRejectsEveryIncompleteHeaderAndMalformedLengths() throws Exception {
        byte[] encoded = fixture("qix-bind-request.bin");
        for (int length = 0; length < 6; length++) {
            byte[] truncated = Arrays.copyOf(encoded, length);
            assertIllegalArgument(() -> QixFrameCodec.decode(truncated));
        }
        assertIllegalArgument(() -> QixFrameCodec.decode(null));

        byte[] shortDeclared = encoded.clone();
        shortDeclared[4] = 12;
        assertIllegalArgument(() -> QixFrameCodec.decode(shortDeclared));
        byte[] longDeclared = encoded.clone();
        longDeclared[4] = 14;
        assertIllegalArgument(() -> QixFrameCodec.decode(longDeclared));
        byte[] wrongMagic = encoded.clone();
        wrongMagic[0] = 0;
        assertIllegalArgument(() -> QixFrameCodec.decode(wrongMagic));
    }

    @Test public void decodeRejectsChecksumMutation() throws Exception {
        byte[] encoded = fixture("qix-c0-update-header-request.bin");
        encoded[10] ^= 1;
        assertIllegalArgument(() -> QixFrameCodec.decode(encoded));
    }

    private static void assertFrame(byte[] encoded, int flags, int opcode, int payloadLength) {
        QixFrame frame = QixFrameCodec.decode(encoded);
        assertEquals(flags, frame.flags());
        assertEquals(opcode, frame.opcode());
        assertEquals(payloadLength, frame.payload().length);
        assertArrayEquals(encoded, QixFrameCodec.encode(flags, opcode, frame.payload()));
    }

    private static void assertIllegalArgument(ThrowingRunnable runnable) {
        assertThrows(IllegalArgumentException.class, () -> runnable.run());
    }

    private static byte[] fixture(String name) throws IOException {
        try (InputStream input = QixFrameCodecTest.class.getResourceAsStream("/transition/" + name)) {
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

    private static String sha256(byte[] bytes) throws NoSuchAlgorithmException {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder hex = new StringBuilder(digest.length * 2);
        for (byte value : digest) {
            hex.append(String.format("%02X", value & 0xFF));
        }
        return hex.toString();
    }

    private interface ThrowingRunnable {
        void run();
    }
}
