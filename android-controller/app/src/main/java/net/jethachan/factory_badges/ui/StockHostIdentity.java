package net.jethachan.factory_badges.ui;

/** Qix binding identity derived from the current phone without a device-specific constant. */
final class StockHostIdentity {
    private static final int BUILD_FIELD_COUNT = 13;

    private final int settings;
    private final int hostId;

    private StockHostIdentity(int settings, int hostId) {
        this.settings = settings;
        this.hostId = hostId;
    }

    static StockHostIdentity derive(
            String language, boolean is24HourClock, String[] buildFields) {
        if (language == null) {
            throw new IllegalArgumentException("language must not be null");
        }
        if (buildFields == null || buildFields.length != BUILD_FIELD_COUNT) {
            throw new IllegalArgumentException("exactly thirteen build fields are required");
        }
        int languageBit = "zh".equals(language) ? 0 : 1;
        int clockBit = is24HourClock ? 0 : 1;
        int settings = (clockBit << 2) | (languageBit << 1);

        StringBuilder fingerprint = new StringBuilder("35");
        for (String field : buildFields) {
            if (field == null) {
                throw new IllegalArgumentException("build fields must not contain null");
            }
            fingerprint.append(field.length() % 10);
        }
        return new StockHostIdentity(settings, fingerprint.toString().hashCode());
    }

    int settings() {
        return settings;
    }

    int hostId() {
        return hostId;
    }
}
