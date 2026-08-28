package com.openai.e87probe;

public final class ProbeSequence {
    public enum Action { SEND_STORAGE_INFO, SEND_ROOT_LISTING, STOP }

    private ProbeSequence() {}

    public static Action afterTargetInfoStatus(int status) {
        return status == 0 ? Action.SEND_STORAGE_INFO : Action.STOP;
    }

    public static Action afterStorageInfo(int status, long storageHandle) {
        return status == 0 && storageHandle == 0x00000002L
                ? Action.SEND_ROOT_LISTING
                : Action.STOP;
    }

    public static boolean matchesAdvertisement(String expectedMac, String advertisedMac) {
        return expectedMac != null && advertisedMac != null
                && expectedMac.equalsIgnoreCase(advertisedMac);
    }

    public static boolean shouldRetryConnection(int gattStatus, int completedAttempts,
                                                boolean preProtocol) {
        return preProtocol && gattStatus == 62 && completedAttempts == 1;
    }
}
