package net.jethachan.factory_badges.transition;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** Fakeable asynchronous boundary for the isolated stock FD00 GATT conversation. */
public interface StockGattDriver {
    int STATUS_SUCCESS = 0;
    int PROPERTY_WRITE = 0x08;
    int NOTIFY = 0x10;
    int INDICATE = 0x20;
    int WRITE_TYPE_DEFAULT = 2;

    final class Peer {
        private final String address;
        private final String displayName;
        private final int rssi;

        public Peer(String address, String displayName, int rssi) {
            if (address == null || displayName == null) {
                throw new IllegalArgumentException("peer fields must not be null");
            }
            this.address = canonicalAddress(address);
            this.displayName = displayName;
            this.rssi = rssi;
        }

        public String address() {
            return address;
        }

        public String displayName() {
            return displayName;
        }

        public int rssi() {
            return rssi;
        }

        @Override public boolean equals(Object other) {
            return other instanceof Peer && address.equals(((Peer) other).address);
        }

        @Override public int hashCode() {
            return address.hashCode();
        }

        private static String canonicalAddress(String input) {
            if (input.length() != 17) {
                throw new IllegalArgumentException("peer address must have six octets");
            }
            StringBuilder canonical = new StringBuilder(17);
            for (int index = 0; index < input.length(); index++) {
                char value = input.charAt(index);
                if (index == 2 || index == 5 || index == 8 || index == 11 || index == 14) {
                    if (value != ':') {
                        throw new IllegalArgumentException("peer address must use colon octets");
                    }
                    canonical.append(':');
                } else {
                    if (value >= '0' && value <= '9') {
                        canonical.append(value);
                    } else if (value >= 'A' && value <= 'F') {
                        canonical.append(value);
                    } else if (value >= 'a' && value <= 'f') {
                        canonical.append((char) (value - ('a' - 'A')));
                    } else {
                        throw new IllegalArgumentException("peer address contains non-hex octet");
                    }
                }
            }
            return canonical.toString();
        }
    }

    final class Service {
        private final UUID uuid;
        private final List<Characteristic> characteristics;

        public Service(UUID uuid, List<Characteristic> characteristics) {
            if (uuid == null || characteristics == null) {
                throw new IllegalArgumentException("service inputs must not be null");
            }
            List<Characteristic> copied = new ArrayList<Characteristic>(characteristics.size());
            for (Characteristic characteristic : characteristics) {
                if (characteristic == null) {
                    throw new IllegalArgumentException("service characteristics must not contain null");
                }
                copied.add(characteristic);
            }
            this.uuid = uuid;
            this.characteristics = Collections.unmodifiableList(copied);
        }

        public UUID uuid() {
            return uuid;
        }

        public List<Characteristic> characteristics() {
            return characteristics;
        }
    }

    final class Characteristic {
        private final UUID uuid;
        private final int properties;
        private final Set<UUID> descriptorUuids;

        public Characteristic(UUID uuid, int properties, List<UUID> descriptorUuids) {
            if (uuid == null || descriptorUuids == null) {
                throw new IllegalArgumentException("characteristic inputs must not be null");
            }
            Set<UUID> copied = new HashSet<UUID>();
            for (UUID descriptorUuid : descriptorUuids) {
                if (descriptorUuid == null) {
                    throw new IllegalArgumentException("descriptor UUIDs must not contain null");
                }
                copied.add(descriptorUuid);
            }
            this.uuid = uuid;
            this.properties = properties;
            this.descriptorUuids = Collections.unmodifiableSet(copied);
        }

        public UUID uuid() {
            return uuid;
        }

        public int properties() {
            return properties;
        }

        public boolean hasDescriptor(UUID descriptorUuid) {
            if (descriptorUuid == null) {
                throw new IllegalArgumentException("descriptor UUID must not be null");
            }
            return descriptorUuids.contains(descriptorUuid);
        }
    }

    interface Listener {
        void onScanResult(long generation, long token, Peer peer);
        void onScanFailed(long generation, long token, int status);
        void onConnectionResult(long generation, long token, int status);
        void onDisconnected(long generation, int status);
        void onServicesResult(long generation, long token, List<Service> services, int status);
        void onSubscriptionResult(long generation, long token, Characteristic characteristic,
                UUID descriptorUuid, int status);
        void onMtuResult(long generation, long token, int mtu, int status);
        void onCharacteristicWrite(long generation, long token, Characteristic characteristic,
                int status);
        void onNotification(long generation, Characteristic characteristic, byte[] value);
    }

    void setListener(Listener listener);
    boolean startScan(long generation, long token);
    void stopScan(long generation);
    boolean connect(long generation, long token, Peer peer);
    boolean discoverServices(long generation, long token);
    boolean subscribe(long generation, long token, Characteristic characteristic,
            UUID descriptorUuid, byte[] value);
    boolean requestMtu(long generation, long token, int mtu);
    boolean writeCharacteristic(long generation, long token, Characteristic characteristic,
            byte[] value, int writeType);
    void disconnect(long generation);
    void close();
}
