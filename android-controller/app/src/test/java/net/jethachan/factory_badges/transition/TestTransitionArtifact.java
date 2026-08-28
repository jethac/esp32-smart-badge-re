package net.jethachan.factory_badges.transition;

final class TestTransitionArtifact {
    private static final byte[] QIX_SHA256 = new byte[] {
            (byte) 0xF3, (byte) 0xAE, (byte) 0xFF, 0x3E,
            0x22, (byte) 0x95, (byte) 0xC0, 0x6A,
            0x4F, 0x79, 0x0C, 0x1C,
            (byte) 0xEC, 0x3F, 0x1C, 0x3F,
            0x35, 0x61, (byte) 0xD3, (byte) 0xF6,
            (byte) 0x8F, (byte) 0x95, 0x2F, 0x00,
            0x32, 0x72, (byte) 0xBF, 0x7E,
            0x60, 0x40, (byte) 0xD5, (byte) 0xE2
    };

    private TestTransitionArtifact() {}

    static TransitionArtifact create() {
        byte[] header = new byte[27];
        header[13] = 1;
        byte[] payload = new byte[] {0x2A};
        byte[] buildId = new byte[16];
        for (int index = 0; index < buildId.length; index++) {
            buildId[index] = (byte) (index + 1);
        }
        return new TransitionArtifact(header, payload, QIX_SHA256, buildId);
    }
}
