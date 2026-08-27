package net.jethachan.factory_badges.protocol;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import net.jethachan.factory_badges.model.BuildInfo;

public final class BuildInfoCodec {
    public static final int CAPABILITY_SEMANTIC_METRICS = 1 << 0;
    public static final int CAPABILITY_BATTERY_SERVICE = 1 << 1;
    public static final int CAPABILITY_PHYSICALLY_GATED_RCSP = 1 << 2;
    public static final String HARDWARE_PROFILE = "E87-JD9855-R1";

    public static final int RECORD_LENGTH = 40;
    private static final int SCHEMA_V1 = 1;
    private static final int ALLOWED_CAPABILITIES = 0x07;
    private static final int PROFILE_OFFSET = 2;
    private static final int PROFILE_LENGTH = 16;
    private static final int BUILD_ID_OFFSET = 22;
    private static final int BUILD_ID_LENGTH = 16;

    private BuildInfoCodec() {
    }

    /** Protocol-owned expected-build view used without a maintenance-package dependency. */
    public interface ExpectedBuild {
        int capabilities();

        String hardwareProfile();

        int major();

        int minor();

        int patch();

        /** Returns a defensive copy of the exact 16-byte build ID. */
        byte[] buildId();
    }

    public static byte[] encode(BuildInfo info) {
        if (info == null) {
            throw new IllegalArgumentException("build info must not be null");
        }
        byte[] record = new byte[RECORD_LENGTH];
        record[0] = SCHEMA_V1;
        record[1] = (byte) info.capabilities();
        byte[] profile = info.hardwareProfile().getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(profile, 0, record, PROFILE_OFFSET, profile.length);
        record[18] = (byte) info.major();
        record[19] = (byte) info.minor();
        record[20] = (byte) info.patch();
        byte[] buildId = info.buildId();
        System.arraycopy(buildId, 0, record, BUILD_ID_OFFSET, BUILD_ID_LENGTH);
        return record;
    }

    public static BuildInfo decode(byte[] record) {
        if (record == null || record.length != RECORD_LENGTH) {
            throw new IllegalArgumentException("build info must contain exactly 40 bytes");
        }

        int schema = unsigned(record[0]);
        int capabilities = unsigned(record[1]);
        String hardwareProfile = decodeProfile(record);
        int major = unsigned(record[18]);
        int minor = unsigned(record[19]);
        int patch = unsigned(record[20]);
        int reservedTwentyOne = unsigned(record[21]);
        byte[] buildId = Arrays.copyOfRange(
                record, BUILD_ID_OFFSET, BUILD_ID_OFFSET + BUILD_ID_LENGTH);
        int reservedThirtyEight = unsigned(record[38]);
        int reservedThirtyNine = unsigned(record[39]);

        if (schema != SCHEMA_V1) {
            throw new IllegalArgumentException("unsupported build-info schema");
        }
        if ((capabilities & ~ALLOWED_CAPABILITIES) != 0) {
            throw new IllegalArgumentException("capabilities contain unknown bits");
        }
        if (!HARDWARE_PROFILE.equals(hardwareProfile)) {
            throw new IllegalArgumentException("unsupported hardware profile");
        }
        if (reservedTwentyOne != 0 || reservedThirtyEight != 0
                || reservedThirtyNine != 0) {
            throw new IllegalArgumentException("reserved bytes must be zero");
        }

        return new BuildInfo(capabilities, hardwareProfile, major, minor, patch, buildId);
    }

    public static boolean matchesExpected(BuildInfo actual, ExpectedBuild expected) {
        if (actual == null || expected == null) {
            return false;
        }
        try {
            int capabilities = expected.capabilities();
            String hardwareProfile = expected.hardwareProfile();
            int major = expected.major();
            int minor = expected.minor();
            int patch = expected.patch();
            byte[] providedBuildId = expected.buildId();
            if ((capabilities & ~ALLOWED_CAPABILITIES) != 0
                    || !HARDWARE_PROFILE.equals(hardwareProfile)
                    || !isUnsignedByte(major)
                    || !isUnsignedByte(minor)
                    || !isUnsignedByte(patch)
                    || providedBuildId == null
                    || providedBuildId.length != BUILD_ID_LENGTH) {
                return false;
            }
            byte[] buildId = Arrays.copyOf(providedBuildId, providedBuildId.length);
            return actual.capabilities() == capabilities
                    && actual.hardwareProfile().equals(hardwareProfile)
                    && actual.major() == major
                    && actual.minor() == minor
                    && actual.patch() == patch
                    && Arrays.equals(actual.buildId(), buildId);
        } catch (RuntimeException malformedExpected) {
            return false;
        }
    }

    private static String decodeProfile(byte[] record) {
        StringBuilder profile = new StringBuilder(PROFILE_LENGTH);
        boolean terminated = false;
        for (int index = 0; index < PROFILE_LENGTH; index++) {
            int value = unsigned(record[PROFILE_OFFSET + index]);
            if (value > 0x7F) {
                throw new IllegalArgumentException("hardware profile must be ASCII");
            }
            if (terminated) {
                if (value != 0) {
                    throw new IllegalArgumentException(
                            "hardware profile has data after NUL terminator");
                }
            } else if (value == 0) {
                terminated = true;
            } else {
                profile.append((char) value);
            }
        }
        if (!terminated) {
            throw new IllegalArgumentException("hardware profile must be NUL padded");
        }
        return profile.toString();
    }

    private static boolean isUnsignedByte(int value) {
        return value >= 0 && value <= 255;
    }

    private static int unsigned(byte value) {
        return value & 0xFF;
    }
}
