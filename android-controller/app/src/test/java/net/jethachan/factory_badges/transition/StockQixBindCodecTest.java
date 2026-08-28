package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.junit.Test;

public final class StockQixBindCodecTest {
    @Test public void capturedRedmiHostIdProducesThePinnedBindRequest() throws Exception {
        byte[] expected = fixture("qix-bind-request.bin");
        byte[] actual = StockQixBindCodec.request(0x06, -1168149652);

        assertArrayEquals(expected, actual);
        QixFrame frame = QixFrameCodec.decode(actual);
        assertEquals(0x02, frame.flags());
        assertEquals(0x60, frame.opcode());
        assertArrayEquals(new byte[] {0x06, 0x6c, 0x73, 0x5f, (byte) 0xba, (byte) 0xff,
                (byte) 0xff, 0x6c, 0x73, 0x5f, (byte) 0xba, (byte) 0xff, (byte) 0xff},
                frame.payload());
    }

    @Test public void requestUsesLowSixLittleEndianBytesOfAnySignedHostIdTwice() {
        QixFrame frame = QixFrameCodec.decode(StockQixBindCodec.request(0xA5, -1));
        assertEquals(0x02, frame.flags());
        assertEquals(0x60, frame.opcode());
        assertArrayEquals(new byte[] {(byte) 0xA5, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF,
                (byte) 0xFF, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF,
                (byte) 0xFF, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF}, frame.payload());
        assertIllegalArgument(() -> StockQixBindCodec.request(-1, 0));
        assertIllegalArgument(() -> StockQixBindCodec.request(256, 0));
    }

    @Test public void parsesOnlyACompleteSuccessfulBindResponseWithBoundedAsciiVersion()
            throws Exception {
        QixFrame frame = QixFrameCodec.decode(fixture("qix-bind-response-fd01.bin"));
        StockQixBindCodec.BindResponse response = StockQixBindCodec.parseResponse(frame);

        assertEquals(0x04, response.flags());
        assertEquals(0, response.serial());
        assertFalse(response.requestsReply());
        assertEquals("11.1.0.3", response.firmwareVersion());
    }

    @Test public void parseResponseRejectsWrongOpcodeResultVersionAndNull() {
        assertIllegalArgument(() -> StockQixBindCodec.parseResponse(null));
        assertIllegalArgument(() -> StockQixBindCodec.parseResponse(
                new QixFrame(0, 0x60, validPayload("11.1.0.3"))));
        byte[] nonzeroResult = validPayload("11.1.0.3");
        nonzeroResult[0] = 1;
        assertIllegalArgument(() -> StockQixBindCodec.parseResponse(
                new QixFrame(0, 0x61, nonzeroResult)));
        assertIllegalArgument(() -> StockQixBindCodec.parseResponse(
                new QixFrame(0, 0x61, validPayload("12345678901"))));
        byte[] unterminated = validPayload("11.1.0.3");
        unterminated[4 + "11.1.0.3".length()] = 'X';
        assertIllegalArgument(() -> StockQixBindCodec.parseResponse(
                new QixFrame(0, 0x61, unterminated)));
        byte[] nonAscii = validPayload("11.1.0.3");
        nonAscii[4] = 0x1F;
        assertIllegalArgument(() -> StockQixBindCodec.parseResponse(
                new QixFrame(0, 0x61, nonAscii)));
    }

    @Test public void successAckUsesResponseSerialAndExactAcknowledgementPayload() {
        byte[] ack = StockQixBindCodec.successAck(0x61, 15);
        QixFrame frame = QixFrameCodec.decode(ack);

        assertEquals(0x79, frame.flags());
        assertEquals(0xFF, frame.opcode());
        assertArrayEquals(new byte[] {0x61, 0}, frame.payload());
        assertIllegalArgument(() -> StockQixBindCodec.successAck(-1, 0));
        assertIllegalArgument(() -> StockQixBindCodec.successAck(256, 0));
        assertIllegalArgument(() -> StockQixBindCodec.successAck(0x61, -1));
        assertIllegalArgument(() -> StockQixBindCodec.successAck(0x61, 16));
    }

    private static byte[] validPayload(String version) {
        byte[] ascii = version.getBytes(StandardCharsets.US_ASCII);
        byte[] payload = new byte[4 + ascii.length + 1];
        System.arraycopy(ascii, 0, payload, 4, ascii.length);
        return payload;
    }

    private static byte[] fixture(String name) throws IOException {
        try (InputStream input = StockQixBindCodecTest.class.getResourceAsStream("/transition/" + name)) {
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
