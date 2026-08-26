/// JieLi RCSP mutual-auth handshake over AE01 (write) / AE02 (notify).
///
/// Six raw writes — NOT FE-framed — prefixed with a single type byte:
///   1. phone→ 0x00 + 16 random          4. badge→ 0x00 + 16 challenge
///   2. badge→ 0x01 + 16 encrypted       5. phone→ 0x01 + enc(challenge)
///   3. phone→ 0x02 + "pass"             6. badge→ 0x02 + "pass"  (success)
library;

import 'dart:async';
import 'dart:typed_data';

import 'jieli_cipher.dart';
import 'notify_bus.dart';

class E87AuthError implements Exception {
  final String message;
  const E87AuthError(this.message);
  @override
  String toString() => 'E87AuthError: $message';
}

typedef AuthWriter = Future<void> Function(Uint8List data);

Uint8List _prefixed(int prefix, List<int> body) =>
    Uint8List.fromList([prefix, ...body]);

Future<void> doAuth(AuthWriter writeAe01, NotifyBus bus) async {
  // Step 1: phone → [0x00, rand*16]
  await writeAe01(_prefixed(0x00, getRandomAuthData()));

  // Step 2: badge → [0x01, enc*16]
  try {
    await bus.waitForRaw(
      (r) => r.length == 17 && r[0] == 0x01,
      const Duration(seconds: 5),
      'auth device response [0x01, encrypted*16]',
    );
  } on TimeoutException {
    throw const E87AuthError('device did not respond to challenge');
  }

  // Step 3: phone → [0x02, "pass"]
  await writeAe01(_prefixed(0x02, 'pass'.codeUnits));

  // Step 4: badge → [0x00, challenge*16]
  final Uint8List devChal;
  try {
    devChal = await bus.waitForRaw(
      (r) => r.length == 17 && r[0] == 0x00,
      const Duration(seconds: 5),
      'auth device challenge [0x00, challenge*16]',
    );
  } on TimeoutException {
    throw const E87AuthError('device never sent its challenge');
  }

  // Step 5: phone → [0x01, enc(challenge)]
  final encrypted = getEncryptedAuthData(devChal.sublist(1, 17));
  await writeAe01(_prefixed(0x01, encrypted));

  // Step 6: badge → [0x02, "pass"]
  try {
    await bus.waitForRaw(
      (r) =>
          r.length >= 5 &&
          r[0] == 0x02 &&
          r[1] == 0x70 &&
          r[2] == 0x61 &&
          r[3] == 0x73 &&
          r[4] == 0x73,
      const Duration(seconds: 5),
      'auth pass confirmation',
    );
  } on TimeoutException {
    throw const E87AuthError('device never confirmed our response');
  }
}
