package net.jethachan.factory_badges.model;

import java.util.Arrays;

public final class BuildInfo {
    private static final int ALLOWED_CAPABILITIES = 0x07;
    private static final String REQUIRED_HARDWARE_PROFILE = "E87-JD9855-R1";
    private static final int BUILD_ID_LENGTH = 16;

    private final int capabilities;
    private final String hardwareProfile;
    private final int major;
    private final int minor;
    private final int patch;
    private final byte[] buildId;

    public BuildInfo(int capabilities, String hardwareProfile, int major, int minor, int patch,
            byte[] buildId) {
        if ((capabilities & ~ALLOWED_CAPABILITIES) != 0) {
            throw new IllegalArgumentException("capabilities contain unknown bits");
        }
        if (!REQUIRED_HARDWARE_PROFILE.equals(hardwareProfile)) {
            throw new IllegalArgumentException("unsupported hardware profile");
        }
        requireUnsignedByte("major", major);
        requireUnsignedByte("minor", minor);
        requireUnsignedByte("patch", patch);
        if (buildId == null || buildId.length != BUILD_ID_LENGTH) {
            throw new IllegalArgumentException("buildId must contain exactly 16 bytes");
        }
        this.capabilities = capabilities;
        this.hardwareProfile = hardwareProfile;
        this.major = major;
        this.minor = minor;
        this.patch = patch;
        this.buildId = Arrays.copyOf(buildId, buildId.length);
    }

    public int capabilities() {
        return capabilities;
    }

    public String hardwareProfile() {
        return hardwareProfile;
    }

    public int major() {
        return major;
    }

    public int minor() {
        return minor;
    }

    public int patch() {
        return patch;
    }

    public byte[] buildId() {
        return Arrays.copyOf(buildId, buildId.length);
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof BuildInfo)) {
            return false;
        }
        BuildInfo that = (BuildInfo) other;
        return capabilities == that.capabilities
                && major == that.major
                && minor == that.minor
                && patch == that.patch
                && hardwareProfile.equals(that.hardwareProfile)
                && Arrays.equals(buildId, that.buildId);
    }

    @Override
    public int hashCode() {
        int result = capabilities;
        result = 31 * result + hardwareProfile.hashCode();
        result = 31 * result + major;
        result = 31 * result + minor;
        result = 31 * result + patch;
        result = 31 * result + Arrays.hashCode(buildId);
        return result;
    }

    private static void requireUnsignedByte(String field, int value) {
        if (value < 0 || value > 255) {
            throw new IllegalArgumentException(field + " must be in 0..255");
        }
    }
}
