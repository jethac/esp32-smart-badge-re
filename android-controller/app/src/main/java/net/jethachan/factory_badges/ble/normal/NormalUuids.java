package net.jethachan.factory_badges.ble.normal;

import java.util.UUID;

public final class NormalUuids {
    public static final UUID SERVICE =
            UUID.fromString("e87d0001-7a1b-4c62-9f0b-5d9c01a70735");
    public static final UUID SEMANTIC_STATE =
            UUID.fromString("e87d0002-7a1b-4c62-9f0b-5d9c01a70735");
    public static final UUID BUILD_INFO =
            UUID.fromString("e87d0003-7a1b-4c62-9f0b-5d9c01a70735");
    public static final UUID BATTERY_SERVICE =
            UUID.fromString("0000180f-0000-1000-8000-00805f9b34fb");
    public static final UUID BATTERY_LEVEL =
            UUID.fromString("00002a19-0000-1000-8000-00805f9b34fb");

    private NormalUuids() {
    }
}
