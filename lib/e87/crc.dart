/// CRC-16/XMODEM — polynomial 0x1021, init 0x0000, no reflection, no final
/// XOR. Verified against `crc16Xmodem("123456789") == 0x31C3`.
library;

int crc16Xmodem(List<int> data) {
  var crc = 0x0000;
  for (final raw in data) {
    crc ^= (raw & 0xFF) << 8;
    for (var i = 0; i < 8; i++) {
      if ((crc & 0x8000) != 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF;
      } else {
        crc = (crc << 1) & 0xFFFF;
      }
    }
  }
  return crc;
}
