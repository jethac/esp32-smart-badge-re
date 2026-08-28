package net.jethachan.factory_badges.transition;

import static org.junit.Assert.assertEquals;

import java.util.UUID;
import org.junit.Test;

public final class StockQixUuidsTest {
    @Test public void pinsTheCapturedFd00ServiceAndCharacteristics() {
        assertEquals(UUID.fromString("c2e6fd00-e966-1000-8000-bef9c223df6a"),
                StockQixUuids.SERVICE);
        assertEquals(UUID.fromString("c2e6fd01-e966-1000-8000-bef9c223df6a"),
                StockQixUuids.FD01);
        assertEquals(UUID.fromString("c2e6fd02-e966-1000-8000-bef9c223df6a"),
                StockQixUuids.FD02);
        assertEquals(UUID.fromString("c2e6fd03-e966-1000-8000-bef9c223df6a"),
                StockQixUuids.FD03);
        assertEquals(UUID.fromString("00002902-0000-1000-8000-00805f9b34fb"),
                StockQixUuids.CCCD);
    }
}
