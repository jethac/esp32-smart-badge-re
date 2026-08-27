package net.jethachan.factory_badges.model;

public final class BadgeState {
    private static final long REQUIRED_CREDIT_CENTS = 1727L;

    private final int dayPercent;
    private final int weekPercent;
    private final long creditCents;

    public BadgeState(int dayPercent, int weekPercent, long creditCents) {
        requirePercentage("dayPercent", dayPercent);
        requirePercentage("weekPercent", weekPercent);
        if (creditCents != REQUIRED_CREDIT_CENTS) {
            throw new IllegalArgumentException("creditCents must be 1727");
        }
        this.dayPercent = dayPercent;
        this.weekPercent = weekPercent;
        this.creditCents = creditCents;
    }

    public int dayPercent() {
        return dayPercent;
    }

    public int weekPercent() {
        return weekPercent;
    }

    public long creditCents() {
        return creditCents;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof BadgeState)) {
            return false;
        }
        BadgeState that = (BadgeState) other;
        return dayPercent == that.dayPercent
                && weekPercent == that.weekPercent
                && creditCents == that.creditCents;
    }

    @Override
    public int hashCode() {
        int result = dayPercent;
        result = 31 * result + weekPercent;
        result = 31 * result + (int) (creditCents ^ (creditCents >>> 32));
        return result;
    }

    @Override
    public String toString() {
        return "BadgeState{"
                + "dayPercent=" + dayPercent
                + ", weekPercent=" + weekPercent
                + ", creditCents=" + creditCents
                + '}';
    }

    private static void requirePercentage(String field, int value) {
        if (value < 0 || value > 100) {
            throw new IllegalArgumentException(field + " must be in 0..100");
        }
    }
}
