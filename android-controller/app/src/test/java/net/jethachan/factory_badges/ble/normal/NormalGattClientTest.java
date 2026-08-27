package net.jethachan.factory_badges.ble.normal;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import android.bluetooth.BluetoothStatusCodes;
import java.lang.reflect.Field;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import net.jethachan.factory_badges.ble.normal.BondCoordinator.BondState;
import net.jethachan.factory_badges.diagnostic.UserVisibleError;
import net.jethachan.factory_badges.model.BadgeState;
import net.jethachan.factory_badges.model.BuildInfo;
import org.junit.Test;

public final class NormalGattClientTest {
    private static final byte[] VALID_BUILD = new byte[] {
        1, 1,
        'E', '8', '7', '-', 'J', 'D', '9', '8', '5', '5', '-', 'R', '1', 0, 0, 0,
        3, 7, 11, 0,
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
        0, 0
    };

    @Test
    public void bondGateConnectsOnlyAfterMatchingSuccess() {
        Harness h = new Harness(BondState.NONE);
        long oldGeneration = h.core.connect();
        assertEquals(0, h.connector.calls);

        FakeDriver driver = h.addDriver();
        long generation = h.core.connect();
        h.core.onBondStateChanged(
                oldGeneration, BondState.BONDING, BondState.BONDED);
        assertEquals(0, h.connector.calls);
        h.core.onBondStateChanged(
                generation, BondState.BONDING, BondState.BONDED);
        h.core.onBondStateChanged(
                generation, BondState.BONDING, BondState.BONDED);

        assertTrue(generation > oldGeneration && oldGeneration > 0);
        assertEquals(1, h.connector.calls);
        assertSame(driver, h.connector.connected.get(0));
    }

    @Test
    public void validEncryptedBuildOpensReadyExactlyOnce() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        long generation = h.toBuild(driver);

        h.build(generation, driver, VALID_BUILD, 0);
        h.build(generation, driver, VALID_BUILD, 0);

        assertTrue(h.core.isReady());
        assertEquals(1, h.listener.connected.size());
        BuildInfo info = h.listener.connected.get(0);
        assertEquals(1, info.capabilities());
        assertEquals("E87-JD9855-R1", info.hardwareProfile());
        assertNull(h.listener.batteries.get(0));
    }

    @Test
    public void buildSecurityStatusFiveAndFifteenFailTerminally() {
        for (int status : new int[] {5, 15}) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            long generation = h.toBuild(driver);

            h.build(generation, driver, VALID_BUILD, status);
            h.build(generation, driver, VALID_BUILD, 0);

            UserVisibleError error = h.listener.onlyError();
            assertEquals(UserVisibleError.Code.LINK_SECURITY_FAILED, error.code());
            assertEquals(status, error.gattStatus());
            assertFalse(error.retryable());
            assertEquals(1, driver.closeCalls);
            assertFalse(h.core.isReady());
        }
    }

    @Test
    public void noStateWriteStartsBeforeBuildValidation() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        BadgeState state = new BadgeState(17, 42, 1727);
        assertFalse(h.core.writeState(state));
        long generation = h.toBuild(driver);

        assertFalse(h.core.writeState(state));
        assertEquals(Arrays.asList(Key.of(
                NormalUuids.SERVICE, NormalUuids.BUILD_INFO)), driver.reads);
        assertEquals(0, driver.writes.size());
        h.build(generation, driver, VALID_BUILD, 0);
        assertTrue(h.core.writeState(state));
    }

    @Test
    public void exactStatePacketAcknowledgesOnlySuccessfulCallback() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        long generation = h.ready(driver);
        BadgeState state = new BadgeState(17, 42, 1727);
        h.clock.now = 9876L;

        assertTrue(h.core.writeState(state));
        assertEquals(1, driver.writes.size());
        WriteCall call = driver.writes.get(0);
        assertEquals(Key.of(NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE), call.key);
        assertArrayEquals(
                new byte[] {1, 17, 42, 0, (byte) 0xBF, 0x06, 0, 0}, call.value);
        assertEquals(0, h.listener.acknowledged.size());

        h.core.onCharacteristicWrite(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, 0);
        h.core.onCharacteristicWrite(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, 0);

        assertEquals(Arrays.asList(state), h.listener.acknowledged);
        assertEquals(Arrays.asList(Long.valueOf(9876L)),
                h.listener.acknowledgedTimes);
        assertEquals(1, h.clock.calls);
    }

    @Test
    public void staleGenerationAndDriverCannotAdvanceOrNotify() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        long generation = h.core.connect();
        FakeDriver stranger = new FakeDriver();
        h.core.onConnectionStateChanged(generation + 1, driver, 0, true);
        h.core.onConnectionStateChanged(generation, stranger, 0, true);
        assertEquals(0, driver.discoverCalls);

        h.core.onConnectionStateChanged(generation, driver, 0, true);
        h.core.onServicesDiscovered(generation, driver, 0);
        h.core.onCharacteristicRead(
                generation + 1, driver,
                NormalUuids.SERVICE, NormalUuids.BUILD_INFO, VALID_BUILD, 0);
        h.core.onCharacteristicRead(
                generation, stranger,
                NormalUuids.SERVICE, NormalUuids.BUILD_INFO, VALID_BUILD, 0);

        assertFalse(h.core.isReady());
        assertEquals(0, h.listener.eventCount());
        h.build(generation, driver, VALID_BUILD, 0);
        assertTrue(h.core.isReady());
    }

    @Test
    public void optionalBatteryFailureStillPublishesReadyWithNull() {
        for (int mode = 0; mode < 3; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            driver.table.addBattery();
            if (mode == 0) {
                driver.readResults.put(
                        NormalUuids.BATTERY_LEVEL, Boolean.FALSE);
            }
            long generation = h.toBuild(driver);
            h.build(generation, driver, VALID_BUILD, 0);
            if (mode == 1) {
                h.battery(generation, driver, null, 0);
            } else if (mode == 2) {
                h.battery(generation, driver, new byte[] {101}, 0);
            }

            assertTrue(h.core.isReady());
            assertNull(h.listener.batteries.get(0));
            assertEquals(0, h.listener.errors.size());
        }
    }

    @Test
    public void unexpectedDisconnectDeliversOnceAndClosesOnce() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        long generation = h.ready(driver);

        h.core.onConnectionStateChanged(generation, driver, 19, false);
        h.core.onConnectionStateChanged(generation, driver, 19, false);

        assertEquals(Arrays.asList(Integer.valueOf(19)), h.listener.disconnects);
        assertEquals(0, h.listener.errors.size());
        assertEquals(1, driver.disconnectCalls);
        assertEquals(1, driver.closeCalls);
        assertFalse(h.core.isReady());
    }

    @Test
    public void alreadyBondedAndBondFailureEachReportOnlyOnce() {
        Harness bonded = new Harness(BondState.BONDED);
        FakeDriver driver = bonded.addDriver();
        long generation = bonded.core.connect();
        bonded.core.onBondStateChanged(
                generation, BondState.BONDING, BondState.BONDED);
        assertEquals(1, bonded.connector.calls);
        assertSame(driver, bonded.connector.connected.get(0));

        Harness failed = new Harness(BondState.NONE);
        failed.bond.createResult = false;
        failed.core.connect();
        assertEquals(UserVisibleError.Code.BOND_START_FAILED,
                failed.listener.onlyError().code());
        assertEquals(0, failed.connector.calls);
    }

    @Test
    public void connectorConnectionAndDiscoveryFailuresMapExactly() {
        for (int mode = 0; mode < 6; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            if (mode == 0) {
                h.connector.returnNull = true;
            } else if (mode == 1) {
                h.connector.failure = new IllegalStateException("secret");
            } else if (mode == 3) {
                driver.discoverResult = false;
            } else if (mode == 4) {
                driver.discoverFailure = new IllegalStateException("secret");
            }
            long generation = h.core.connect();
            if (mode == 2) {
                h.core.onConnectionStateChanged(generation, driver, 133, false);
            } else if (mode >= 3) {
                h.core.onConnectionStateChanged(generation, driver, 0, true);
                if (mode == 5) {
                    h.core.onServicesDiscovered(generation, driver, 129);
                }
            }
            UserVisibleError error = h.listener.onlyError();
            assertEquals(mode < 3
                            ? UserVisibleError.Code.CONNECT_FAILED
                            : UserVisibleError.Code.SERVICE_DISCOVERY_FAILED,
                    error.code());
            assertEquals(mode == 2 ? 133 : (mode == 5 ? 129 : -1),
                    error.gattStatus());
        }
    }

    @Test
    public void discoveryRejectsMissingAndWrongPropertyAttributes() {
        for (int mode = 0; mode < 5; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            if (mode == 0) {
                driver.table.services.remove(NormalUuids.SERVICE);
            } else if (mode == 1) {
                driver.table.access.remove(
                        Key.of(NormalUuids.SERVICE, NormalUuids.BUILD_INFO));
            } else if (mode == 2) {
                driver.table.access.put(
                        Key.of(NormalUuids.SERVICE, NormalUuids.BUILD_INFO),
                        new NormalGattClient.Core.CharacteristicAccess(false, false));
            } else if (mode == 3) {
                driver.table.access.remove(
                        Key.of(NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE));
            } else {
                driver.table.access.put(
                        Key.of(NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE),
                        new NormalGattClient.Core.CharacteristicAccess(false, false));
            }
            long generation = h.core.connect();
            h.core.onConnectionStateChanged(generation, driver, 0, true);
            h.core.onServicesDiscovered(generation, driver, 0);
            UserVisibleError.Code expected = mode == 0
                    ? UserVisibleError.Code.REQUIRED_SERVICE_MISSING
                    : (mode == 1 || mode == 3
                            ? UserVisibleError.Code.REQUIRED_CHARACTERISTIC_MISSING
                            : UserVisibleError.Code.UNSUPPORTED_BADGE);
            assertEquals(expected, h.listener.onlyError().code());
            assertEquals(0, driver.reads.size());
        }
    }

    @Test
    public void malformedBuildAndMissingSemanticCapabilityFailClosed() {
        List<byte[]> invalid = new ArrayList<byte[]>();
        invalid.add(null);
        invalid.add(new byte[0]);
        invalid.add(new byte[39]);
        invalid.add(new byte[41]);
        for (int index : new int[] {0, 1, 2, 15, 21, 39}) {
            byte[] bytes = Arrays.copyOf(VALID_BUILD, VALID_BUILD.length);
            bytes[index] = index == 2 ? (byte) 0x80 : (byte) 8;
            invalid.add(bytes);
        }
        for (byte[] bytes : invalid) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            long generation = h.toBuild(driver);
            h.build(generation, driver, bytes, 0);
            assertEquals(UserVisibleError.Code.BUILD_INFO_INVALID,
                    h.listener.onlyError().code());
        }

        Harness missingCapability = new Harness(BondState.BONDED);
        FakeDriver driver = missingCapability.addDriver();
        long generation = missingCapability.toBuild(driver);
        byte[] bytes = Arrays.copyOf(VALID_BUILD, VALID_BUILD.length);
        bytes[1] = 6;
        missingCapability.build(generation, driver, bytes, 0);
        assertEquals(UserVisibleError.Code.UNSUPPORTED_BADGE,
                missingCapability.listener.onlyError().code());
    }

    @Test
    public void batteryEndpointsAndMalformedOrFailedReadsStayNonfatal() {
        for (int value : new int[] {0, 100}) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            driver.table.addBattery();
            long generation = h.toBuild(driver);
            h.build(generation, driver, VALID_BUILD, 0);
            h.battery(generation, driver, new byte[] {(byte) value}, 0);
            assertEquals(Integer.valueOf(value), h.listener.batteries.get(0));
        }

        byte[][] values = new byte[][] {
            null, new byte[0], new byte[] {1, 2}, new byte[] {101}, new byte[] {50}
        };
        int[] statuses = new int[] {0, 0, 0, 0, 7};
        for (int index = 0; index < values.length; index++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            driver.table.addBattery();
            long generation = h.toBuild(driver);
            h.build(generation, driver, VALID_BUILD, 0);
            h.battery(generation, driver, values[index], statuses[index]);
            assertTrue(h.core.isReady());
            assertNull(h.listener.batteries.get(0));
            assertEquals(0, h.listener.errors.size());
        }
    }

    @Test
    public void wrongWriteCallbacksDoNotAcknowledgeOrAllowSecondActiveWrite() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        long generation = h.ready(driver);
        BadgeState first = new BadgeState(1, 2, 1727);
        assertTrue(h.core.writeState(first));
        h.core.onCharacteristicRead(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, new byte[0], 0);
        h.core.onCharacteristicWrite(
                generation + 1, driver,
                NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, 0);
        h.core.onCharacteristicWrite(
                generation, new FakeDriver(),
                NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, 0);
        h.core.onCharacteristicWrite(
                generation, driver,
                NormalUuids.BATTERY_SERVICE, NormalUuids.SEMANTIC_STATE, 0);
        h.core.onCharacteristicWrite(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.BUILD_INFO, 0);
        assertEquals(0, h.listener.acknowledged.size());
        assertFalse(h.core.writeState(new BadgeState(3, 4, 1727)));
        h.core.onCharacteristicWrite(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, 0);
        assertTrue(h.core.writeState(first));
        assertEquals(2, driver.writes.size());
    }

    @Test
    public void coreRejectsNullDependenciesInputsAndNonpositiveCallbacks() {
        FakeBondPort bond = new FakeBondPort(BondState.NONE);
        FakeConnector connector = new FakeConnector();
        ManualScheduler scheduler = new ManualScheduler();
        FakeClock clock = new FakeClock();
        RecordingListener listener = new RecordingListener();
        assertThrows(IllegalArgumentException.class,
                () -> new NormalGattClient.Core(
                        null, connector, scheduler, clock, listener));
        assertThrows(IllegalArgumentException.class,
                () -> new NormalGattClient.Core(
                        bond, null, scheduler, clock, listener));
        assertThrows(IllegalArgumentException.class,
                () -> new NormalGattClient.Core(
                        bond, connector, null, clock, listener));
        assertThrows(IllegalArgumentException.class,
                () -> new NormalGattClient.Core(
                        bond, connector, scheduler, null, listener));
        assertThrows(IllegalArgumentException.class,
                () -> new NormalGattClient.Core(
                        bond, connector, scheduler, clock, null));
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        h.core.connect();
        assertThrows(IllegalArgumentException.class,
                () -> h.core.onConnectionStateChanged(0, driver, 0, true));
        assertThrows(IllegalArgumentException.class,
                () -> h.core.onServicesDiscovered(-1, driver, 0));
        assertThrows(IllegalArgumentException.class,
                () -> h.core.onCharacteristicRead(
                        0, driver,
                        NormalUuids.SERVICE, NormalUuids.BUILD_INFO, VALID_BUILD, 0));
        assertThrows(IllegalArgumentException.class,
                () -> h.core.writeState(null));
    }

    @Test
    public void permissionRaceDuringBondMapsBluetoothPermissionMissing() {
        for (int mode = 0; mode < 2; mode++) {
            Harness h = new Harness(BondState.NONE);
            if (mode == 0) {
                h.bond.currentFailure = new SecurityException("private");
            } else {
                h.bond.createFailure = new SecurityException("private");
            }

            h.core.connect();

            assertEquals(
                    UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING,
                    h.listener.onlyError().code());
        }
    }

    @Test
    public void replacementInvalidatesActiveWriteBeforeNewConnectorRuns() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver oldDriver = h.addDriver();
        long oldGeneration = h.ready(oldDriver);
        assertTrue(h.core.writeState(new BadgeState(1, 2, 1727)));
        assertEquals(1, h.scheduler.activeCount());

        FakeDriver newDriver = h.addDriver();
        h.connector.beforeConnect = () -> {
            assertEquals(1, oldDriver.disconnectCalls);
            assertEquals(1, oldDriver.closeCalls);
            assertEquals(0, h.scheduler.activeCount());
        };
        long newGeneration = h.core.connect();

        assertTrue(newGeneration > oldGeneration);
        assertSame(newDriver, h.connector.connected.get(1));
        assertEquals(0, h.listener.acknowledged.size());
    }

    @Test
    public void connectorReentrancyCannotOverwriteNewGeneration() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver currentDriver = h.addDriver();
        FakeDriver staleDriver = h.addDriver();
        long[] nestedGeneration = new long[1];
        h.connector.beforeConnect = () ->
                nestedGeneration[0] = h.core.connect();

        long staleGeneration = h.core.connect();

        assertTrue(nestedGeneration[0] > staleGeneration);
        assertEquals(nestedGeneration[0], h.core.activeGeneration());
        assertEquals(1, staleDriver.closeCalls);
        h.core.onConnectionStateChanged(
                staleGeneration, staleDriver, 0, true);
        assertEquals(0, staleDriver.discoverCalls);

        h.core.onConnectionStateChanged(
                nestedGeneration[0], currentDriver, 0, true);
        assertEquals(1, currentDriver.discoverCalls);
    }

    @Test
    public void intentionalDisconnectClosesOnceInEveryLivePhase() {
        for (int mode = 0; mode < 6; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            if (mode == 3) {
                driver.table.addBattery();
            }
            long generation = h.core.connect();
            if (mode >= 1) {
                h.core.onConnectionStateChanged(generation, driver, 0, true);
            }
            if (mode >= 2) {
                h.core.onServicesDiscovered(generation, driver, 0);
            }
            if (mode >= 3) {
                h.build(generation, driver, VALID_BUILD, 0);
            }
            if (mode == 5) {
                assertTrue(h.core.writeState(new BadgeState(4, 5, 1727)));
            }

            h.core.disconnect();
            h.core.disconnect();

            assertEquals(1, driver.disconnectCalls);
            assertEquals(1, driver.closeCalls);
            assertEquals(0, h.listener.disconnects.size());
            assertEquals(0, h.listener.errors.size());
            assertEquals(0, h.listener.acknowledged.size());
        }
    }

    @Test
    public void liveDriverIdentityCannotBeReusedAfterTeardown() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        h.core.connect();
        h.core.disconnect();
        h.connector.drivers.addLast(driver);

        h.core.connect();

        assertEquals(UserVisibleError.Code.CONNECT_FAILED,
                h.listener.onlyError().code());
        assertEquals(1, driver.disconnectCalls);
        assertEquals(1, driver.closeCalls);
    }

    @Test
    public void wrongKindAndUuidCallbacksPreserveActiveQueueToken() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        long generation = h.toBuild(driver);
        long token = h.activeToken();

        h.core.onCharacteristicWrite(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.BUILD_INFO, 0);
        h.core.onCharacteristicRead(
                generation, driver,
                NormalUuids.BATTERY_SERVICE, NormalUuids.BUILD_INFO,
                VALID_BUILD, 0);
        h.core.onCharacteristicRead(
                generation, driver,
                NormalUuids.SERVICE, NormalUuids.BATTERY_LEVEL,
                VALID_BUILD, 0);

        assertEquals(token, h.activeToken());
        assertFalse(h.core.isReady());
        h.build(generation, driver, VALID_BUILD, 0);
        assertTrue(h.core.isReady());
    }

    @Test
    public void requiredBuildStartStatusAndTimeoutFailuresMapOnce() {
        for (int mode = 0; mode < 4; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            if (mode == 0) {
                driver.readResults.put(NormalUuids.BUILD_INFO, Boolean.FALSE);
            } else if (mode == 1) {
                driver.readFailures.put(
                        NormalUuids.BUILD_INFO,
                        new IllegalStateException("private"));
            }
            long generation = h.toBuild(driver);
            if (mode == 2) {
                h.build(generation, driver, VALID_BUILD, 8);
            } else if (mode == 3) {
                h.scheduler.fireActive();
            }
            h.build(generation, driver, VALID_BUILD, 0);

            assertEquals(
                    mode == 3
                            ? UserVisibleError.Code.GATT_TIMEOUT
                            : UserVisibleError.Code.CONNECT_FAILED,
                    h.listener.onlyError().code());
            assertEquals(1, driver.closeCalls);
        }
    }

    @Test
    public void batteryThrowStatusTimeoutAndDuplicateRemainNonfatal() {
        for (int mode = 0; mode < 3; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            driver.table.addBattery();
            if (mode == 0) {
                driver.readFailures.put(
                        NormalUuids.BATTERY_LEVEL,
                        new IllegalStateException("private"));
            }
            long generation = h.toBuild(driver);
            h.build(generation, driver, VALID_BUILD, 0);
            if (mode == 1) {
                h.battery(generation, driver, new byte[] {50}, 7);
            } else if (mode == 2) {
                h.scheduler.fireActive();
            }
            h.battery(generation, driver, new byte[] {50}, 0);

            assertTrue(h.core.isReady());
            assertNull(h.listener.batteries.get(0));
            assertEquals(1, h.listener.connected.size());
            assertEquals(0, h.listener.errors.size());
        }
    }

    @Test
    public void stateStartSecurityStatusTimeoutAndLateCallbackMapOnce() {
        for (int mode = 0; mode < 6; mode++) {
            Harness h = new Harness(BondState.BONDED);
            FakeDriver driver = h.addDriver();
            long generation = h.ready(driver);
            if (mode == 0) {
                driver.writeResult = false;
            } else if (mode == 1) {
                driver.writeFailure = new IllegalStateException("private");
            }
            assertTrue(h.core.writeState(new BadgeState(4, 5, 1727)));
            int status = mode == 2 ? 5 : (mode == 3 ? 15 : 133);
            if (mode >= 2 && mode <= 4) {
                h.core.onCharacteristicWrite(
                        generation, driver,
                        NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE,
                        status);
            } else if (mode == 5) {
                h.scheduler.fireActive();
            }
            h.core.onCharacteristicWrite(
                    generation, driver,
                    NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE, 0);

            UserVisibleError.Code expected =
                    mode == 2 || mode == 3
                            ? UserVisibleError.Code.LINK_SECURITY_FAILED
                            : (mode == 5
                                    ? UserVisibleError.Code.GATT_TIMEOUT
                                    : UserVisibleError.Code.STATE_WRITE_FAILED);
            assertEquals(expected, h.listener.onlyError().code());
            assertEquals(0, h.listener.acknowledged.size());
            assertEquals(1, driver.closeCalls);
        }
    }

    @Test
    public void modernReturnedPermissionStatusMapsBluetoothPermissionMissing() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        driver.modernWriteStatus = Integer.valueOf(
                BluetoothStatusCodes.ERROR_MISSING_BLUETOOTH_CONNECT_PERMISSION);
        h.ready(driver);

        assertTrue(h.core.writeState(new BadgeState(4, 5, 1727)));
        assertEquals(
                UserVisibleError.Code.BLUETOOTH_PERMISSION_MISSING,
                h.listener.onlyError().code());
    }

    @Test
    public void readyCallbackCanReentrantlyDisconnectAndReadInputIsDefensive() {
        Harness h = new Harness(BondState.BONDED);
        FakeDriver driver = h.addDriver();
        h.listener.onConnectedAction = () -> h.core.disconnect();
        byte[] build = Arrays.copyOf(VALID_BUILD, VALID_BUILD.length);
        long generation = h.toBuild(driver);

        h.build(generation, driver, build, 0);
        build[22] = 99;

        assertFalse(h.core.isReady());
        assertEquals(1, driver.disconnectCalls);
        assertEquals(1, driver.closeCalls);
        assertEquals(1, h.listener.connected.get(0).buildId()[0]);
        assertEquals(0, h.listener.errors.size());
    }

    private static final class Harness {
        final FakeBondPort bond;
        final FakeConnector connector = new FakeConnector();
        final ManualScheduler scheduler = new ManualScheduler();
        final FakeClock clock = new FakeClock();
        final RecordingListener listener = new RecordingListener();
        final NormalGattClient.Core core;

        Harness(BondState bondState) {
            bond = new FakeBondPort(bondState);
            core = new NormalGattClient.Core(
                    bond, connector, scheduler, clock, listener);
        }

        FakeDriver addDriver() {
            FakeDriver driver = new FakeDriver();
            connector.drivers.addLast(driver);
            return driver;
        }

        long toBuild(FakeDriver driver) {
            long generation = core.connect();
            core.onConnectionStateChanged(generation, driver, 0, true);
            core.onServicesDiscovered(generation, driver, 0);
            return generation;
        }

        long ready(FakeDriver driver) {
            long generation = toBuild(driver);
            build(generation, driver, VALID_BUILD, 0);
            return generation;
        }

        void build(long generation, FakeDriver driver, byte[] value, int status) {
            core.onCharacteristicRead(
                    generation, driver,
                    NormalUuids.SERVICE, NormalUuids.BUILD_INFO, value, status);
        }

        void battery(long generation, FakeDriver driver, byte[] value, int status) {
            core.onCharacteristicRead(
                    generation, driver,
                    NormalUuids.BATTERY_SERVICE, NormalUuids.BATTERY_LEVEL,
                    value, status);
        }

        long activeToken() {
            try {
                Field field = NormalGattClient.Core.class
                        .getDeclaredField("queue");
                field.setAccessible(true);
                GattOperationQueue activeQueue =
                        (GattOperationQueue) field.get(core);
                return activeQueue == null ? 0L : activeQueue.activeToken();
            } catch (ReflectiveOperationException failure) {
                throw new AssertionError(failure);
            }
        }
    }

    private static final class FakeBondPort implements BondCoordinator.Port {
        final BondState state;
        boolean createResult = true;
        RuntimeException currentFailure;
        RuntimeException createFailure;

        FakeBondPort(BondState state) {
            this.state = state;
        }

        @Override public BondState currentState() {
            if (currentFailure != null) {
                throw currentFailure;
            }
            return state;
        }

        @Override public boolean createBond() {
            if (createFailure != null) {
                throw createFailure;
            }
            return createResult;
        }
    }

    private static final class FakeConnector
            implements NormalGattClient.Core.Connector {
        final ArrayDeque<FakeDriver> drivers = new ArrayDeque<FakeDriver>();
        final List<FakeDriver> connected = new ArrayList<FakeDriver>();
        RuntimeException failure;
        boolean returnNull;
        Runnable beforeConnect;
        int calls;

        @Override public NormalGattClient.Core.GattDriver connect(long generation) {
            calls++;
            if (beforeConnect != null) {
                Runnable action = beforeConnect;
                beforeConnect = null;
                action.run();
            }
            FakeDriver driver = drivers.removeFirst();
            if (failure != null) {
                throw failure;
            }
            if (returnNull) {
                return null;
            }
            connected.add(driver);
            return driver;
        }
    }

    private static final class FakeDriver
            implements NormalGattClient.Core.GattDriver {
        final FakeServiceTable table = new FakeServiceTable();
        final List<Key> reads = new ArrayList<Key>();
        final List<WriteCall> writes = new ArrayList<WriteCall>();
        final Map<UUID, Boolean> readResults = new HashMap<UUID, Boolean>();
        int discoverCalls;
        final Map<UUID, RuntimeException> readFailures =
                new HashMap<UUID, RuntimeException>();
        int disconnectCalls;
        boolean discoverResult = true;
        RuntimeException discoverFailure;
        int closeCalls;

        boolean writeResult = true;
        RuntimeException writeFailure;
        Integer modernWriteStatus;
        @Override public boolean discoverServices() {
            discoverCalls++;
            if (discoverFailure != null) {
                throw discoverFailure;
            }
            return discoverResult;
        }

        @Override public NormalGattClient.Core.ServiceTable serviceTable() {
            return table;
        }

        @Override public boolean read(UUID service, UUID characteristic) {
            reads.add(Key.of(service, characteristic));
            RuntimeException failure = readFailures.get(characteristic);
            if (failure != null) {
                throw failure;
            }
            Boolean result = readResults.get(characteristic);
            return result == null || result.booleanValue();
        }

        @Override public boolean writeAcknowledged(
                UUID service, UUID characteristic, byte[] value) {
            if (writeFailure != null) {
                throw writeFailure;
            }
            if (modernWriteStatus != null) {
                return NormalGattClient.writeAcknowledgedForApi(
                        33, value,
                        new ModernStatusWritePort(modernWriteStatus.intValue()));
            }
            writes.add(new WriteCall(
                    Key.of(service, characteristic),
                    Arrays.copyOf(value, value.length)));
            return writeResult;
        }

        @Override public void disconnect() {
            disconnectCalls++;
        }

        @Override public void close() {
            closeCalls++;
        }
    }

    private static final class ModernStatusWritePort
            implements NormalGattClient.WritePort {
        private final int status;

        ModernStatusWritePort(int status) {
            this.status = status;
        }

        @Override public void setLegacyWriteType(int type) {
            throw new AssertionError("legacy path");
        }

        @Override public boolean setLegacyValue(byte[] value) {
            throw new AssertionError("legacy path");
        }

        @Override public boolean writeLegacy() {
            throw new AssertionError("legacy path");
        }

        @Override public int writeModern(byte[] value, int type) {
            return status;
        }
    }

    private static final class FakeServiceTable
            implements NormalGattClient.Core.ServiceTable {
        final Set<UUID> services = new HashSet<UUID>();
        final Map<Key, NormalGattClient.Core.CharacteristicAccess> access =
                new HashMap<Key, NormalGattClient.Core.CharacteristicAccess>();

        FakeServiceTable() {
            services.add(NormalUuids.SERVICE);
            access.put(
                    Key.of(NormalUuids.SERVICE, NormalUuids.BUILD_INFO),
                    new NormalGattClient.Core.CharacteristicAccess(true, false));
            access.put(
                    Key.of(NormalUuids.SERVICE, NormalUuids.SEMANTIC_STATE),
                    new NormalGattClient.Core.CharacteristicAccess(false, true));
        }

        void addBattery() {
            services.add(NormalUuids.BATTERY_SERVICE);
            access.put(
                    Key.of(NormalUuids.BATTERY_SERVICE, NormalUuids.BATTERY_LEVEL),
                    new NormalGattClient.Core.CharacteristicAccess(true, false));
        }

        @Override public boolean hasService(UUID service) {
            return services.contains(service);
        }

        @Override public NormalGattClient.Core.CharacteristicAccess characteristic(
                UUID service, UUID characteristic) {
            return access.get(Key.of(service, characteristic));
        }
    }

    private static final class ManualScheduler
            implements GattOperationQueue.Scheduler {
        final List<TimeoutTask> tasks = new ArrayList<TimeoutTask>();

        @Override public GattOperationQueue.TimeoutHandle schedule(
                long timeoutMs, Runnable callback) {
            assertEquals(10_000L, timeoutMs);
            TimeoutTask task = new TimeoutTask(callback);
            tasks.add(task);
            return task;
        }

        int activeCount() {
            int count = 0;
            for (TimeoutTask task : tasks) {
                if (!task.cancelled && !task.fired) {
                    count++;
                }
            }
            return count;
        }

        void fireActive() {
            TimeoutTask active = null;
            for (TimeoutTask task : tasks) {
                if (!task.cancelled && !task.fired) {
                    if (active != null) {
                        throw new AssertionError("multiple active timeouts");
                    }
                    active = task;
                }
            }
            if (active == null) {
                throw new AssertionError("no active timeout");
            }
            active.fired = true;
            active.callback.run();
        }
    }

    private static final class TimeoutTask
            implements GattOperationQueue.TimeoutHandle {
        final Runnable callback;
        boolean cancelled;
        boolean fired;

        TimeoutTask(Runnable callback) {
            this.callback = callback;
        }

        @Override public void cancel() {
            cancelled = true;
        }
    }

    private static final class FakeClock implements NormalGattClient.Core.Clock {
        long now;
        int calls;

        @Override public long elapsedRealtimeMs() {
            calls++;
            return now;
        }
    }

    private static final class RecordingListener
            implements NormalGattClient.Listener {
        final List<BuildInfo> connected = new ArrayList<BuildInfo>();
        final List<Integer> batteries = new ArrayList<Integer>();
        final List<BadgeState> acknowledged = new ArrayList<BadgeState>();
        final List<Long> acknowledgedTimes = new ArrayList<Long>();
        final List<Integer> disconnects = new ArrayList<Integer>();
        final List<UserVisibleError> errors = new ArrayList<UserVisibleError>();
        Runnable onConnectedAction;

        @Override public void onConnected(BuildInfo info, Integer battery) {
            connected.add(info);
            batteries.add(battery);
            if (onConnectedAction != null) {
                onConnectedAction.run();
            }
        }

        @Override public void onStateWriteAcknowledged(
                BadgeState state, long elapsedRealtimeMs) {
            acknowledged.add(state);
            acknowledgedTimes.add(Long.valueOf(elapsedRealtimeMs));
        }

        @Override public void onDisconnected(int status) {
            disconnects.add(Integer.valueOf(status));
        }

        @Override public void onError(UserVisibleError error) {
            errors.add(error);
        }

        UserVisibleError onlyError() {
            assertEquals(1, errors.size());
            return errors.get(0);
        }

        int eventCount() {
            return connected.size()
                    + acknowledged.size()
                    + disconnects.size()
                    + errors.size();
        }
    }

    private static final class Key {
        final UUID service;
        final UUID characteristic;

        static Key of(UUID service, UUID characteristic) {
            return new Key(service, characteristic);
        }

        Key(UUID service, UUID characteristic) {
            this.service = service;
            this.characteristic = characteristic;
        }

        @Override public boolean equals(Object other) {
            if (!(other instanceof Key)) {
                return false;
            }
            Key key = (Key) other;
            return service.equals(key.service)
                    && characteristic.equals(key.characteristic);
        }

        @Override public int hashCode() {
            return 31 * service.hashCode() + characteristic.hashCode();
        }
    }

    private static final class WriteCall {
        final Key key;
        final byte[] value;

        WriteCall(Key key, byte[] value) {
            this.key = key;
            this.value = value;
        }
    }
}
