import 'package:flutter_test/flutter_test.dart';
import 'package:factory_badges/e87/jieli_cipher.dart';
import 'package:factory_badges/e87/crc.dart';

void main() {
  test('JieLi auth cipher matches the captured test vector', () {
    // From a real ZRun BLE capture (docs/NOTES.md).
    final challenge = [
      0x70, 0xb7, 0x59, 0x92, 0xe0, 0x5e, 0xa7, 0x8f,
      0xec, 0x53, 0x3b, 0xa1, 0x29, 0x79, 0xb5, 0x90,
    ];
    final expected = [
      0xff, 0xe9, 0xe6, 0xc8, 0x0c, 0xe1, 0xf4, 0x0f,
      0x5c, 0xce, 0xae, 0x20, 0x83, 0x1c, 0x58, 0x79,
    ];
    expect(getEncryptedAuthData(challenge), equals(expected));
  });

  test('CRC-16/XMODEM check value', () {
    expect(crc16Xmodem('123456789'.codeUnits), equals(0x31C3));
  });
}
