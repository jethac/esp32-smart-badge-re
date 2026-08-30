package com.openai.e87probe;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class BlePickerState {
    public enum ServiceStatus { ADVERTISED, NOT_ADVERTISED, UNKNOWN }

    public static final class Candidate {
        public final String address;
        public final String name;
        public final int rssi;
        public final ServiceStatus serviceStatus;

        Candidate(String address, String name, int rssi, ServiceStatus serviceStatus) {
            this.address = address;
            this.name = name;
            this.rssi = rssi;
            this.serviceStatus = serviceStatus;
        }
    }

    private final int maximumCandidates;
    private final Map<String, Candidate> candidates = new LinkedHashMap<>();
    private long generation;
    private String selectedAddress;
    private String frozenAddress;
    private boolean confirmed;
    private boolean consumed;

    public BlePickerState(int maximumCandidates) {
        if (maximumCandidates < 1) throw new IllegalArgumentException("maximumCandidates");
        this.maximumCandidates = maximumCandidates;
    }

    public long beginScan() {
        if (consumed) return generation;
        generation++;
        candidates.clear();
        selectedAddress = null;
        confirmed = false;
        return generation;
    }

    public boolean addCandidate(long scanGeneration, String address, String name, int rssi,
                                ServiceStatus serviceStatus) {
        if (consumed || scanGeneration != generation || !isValidAddress(address)) return false;
        String exact = address.toUpperCase(Locale.ROOT);
        if (!candidates.containsKey(exact) && candidates.size() >= maximumCandidates) return false;
        candidates.put(exact, new Candidate(exact, name, rssi,
                serviceStatus == null ? ServiceStatus.UNKNOWN : serviceStatus));
        return true;
    }

    public List<Candidate> candidates() {
        return Collections.unmodifiableList(new ArrayList<>(candidates.values()));
    }

    public boolean select(long scanGeneration, String address) {
        if (consumed || scanGeneration != generation || !isValidAddress(address)) return false;
        String exact = address.toUpperCase(Locale.ROOT);
        if (!candidates.containsKey(exact)) return false;
        if (!exact.equals(selectedAddress)) confirmed = false;
        selectedAddress = exact;
        return true;
    }

    public void setConfirmed(boolean value) {
        if (!consumed) confirmed = value;
    }

    public boolean isStartEnabled() {
        return !consumed && selectedAddress != null && confirmed;
    }

    public String consumeAndFreeze() {
        if (!isStartEnabled()) return null;
        consumed = true;
        frozenAddress = selectedAddress;
        return frozenAddress;
    }

    public String frozenAddress() {
        return frozenAddress;
    }

    public static boolean isValidAddress(String address) {
        return address != null && address.matches("(?i)[0-9a-f]{2}(:[0-9a-f]{2}){5}");
    }
}
