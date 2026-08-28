package com.openai.e87probe;

public final class Hex {
    private static final char[] DIGITS = "0123456789ABCDEF".toCharArray();

    private Hex() {}

    public static String encode(byte[] data) {
        if (data == null) return "<null>";
        char[] out = new char[data.length * 2];
        for (int i = 0; i < data.length; i++) {
            int value = data[i] & 0xFF;
            out[i * 2] = DIGITS[value >>> 4];
            out[i * 2 + 1] = DIGITS[value & 0x0F];
        }
        return new String(out);
    }

    public static byte[] decode(String text) {
        String normalized = text.replaceAll("[^0-9A-Fa-f]", "");
        if ((normalized.length() & 1) != 0) {
            throw new IllegalArgumentException("Odd number of hexadecimal digits");
        }
        byte[] out = new byte[normalized.length() / 2];
        for (int i = 0; i < out.length; i++) {
            int high = Character.digit(normalized.charAt(i * 2), 16);
            int low = Character.digit(normalized.charAt(i * 2 + 1), 16);
            out[i] = (byte) ((high << 4) | low);
        }
        return out;
    }
}
