/// High-level E87 badge client over flutter_blue_plus: connect, negotiate MTU,
/// subscribe to notifications, run the JieLi auth handshake, then push images.
///
/// Dart analogue of the reference `E87Client`. One instance drives one badge.
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'auth.dart';
import 'e87_const.dart';
import 'frame.dart';
import 'notify_bus.dart';
import 'upload_session.dart';

class E87ConnectError implements Exception {
  final String message;
  const E87ConnectError(this.message);
  @override
  String toString() => 'E87ConnectError: $message';
}

bool _uuidEq(Guid g, String s) => g.str.toLowerCase() == s.toLowerCase();

class E87Client {
  final BluetoothDevice device;
  final NotifyBus _bus = NotifyBus();
  final List<StreamSubscription<List<int>>> _subs = [];

  BluetoothCharacteristic? _aeWrite;
  BluetoothCharacteristic? _fdWrite;
  bool _authed = false;

  E87Client(this.device);

  /// Construct from a MAC / remote-id string (e.g. "46:8D:00:01:2C:25").
  factory E87Client.fromId(String remoteId) =>
      E87Client(BluetoothDevice.fromId(remoteId));

  bool get isConnected => _authed;

  Future<void> connect() async {
    E87ConnectError? last;
    for (var attempt = 1; attempt <= 3; attempt++) {
      try {
        await device.connect(timeout: const Duration(seconds: 15), autoConnect: false);
        // MTU 517 lets a 503-byte data frame land in one ATT write. This is the
        // whole reason a native client succeeds where Chrome (512-byte cap) fails.
        try {
          await device.requestMtu(517);
        } catch (_) {/* some stacks refuse; 490-byte chunks still fit lower MTUs */}

        await _bindCharacteristics();
        await _subscribeNotifications();
        await Future.delayed(const Duration(milliseconds: 100));
        _bus.clear();
        await doAuth(_writeAe01, _bus);
        _authed = true;
        return;
      } catch (e) {
        last = E87ConnectError('attempt $attempt/3 failed: $e');
        await _teardown();
        if (attempt < 3) await Future.delayed(const Duration(seconds: 3));
      }
    }
    throw last ?? const E87ConnectError('could not establish a session');
  }

  Future<void> _bindCharacteristics() async {
    final services = await device.discoverServices();
    for (final s in services) {
      for (final c in s.characteristics) {
        if (_uuidEq(c.uuid, kAeWrite)) _aeWrite = c;
        if (_uuidEq(c.uuid, kFdWrite)) _fdWrite = c;
      }
    }
    if (_aeWrite == null) {
      throw const E87ConnectError('AE01 write characteristic not found');
    }
  }

  Future<void> _subscribeNotifications() async {
    final services = await device.discoverServices();
    for (final s in services) {
      for (final c in s.characteristics) {
        final u = c.uuid.str.toLowerCase();
        if (!kAllNotify.contains(u)) continue;
        try {
          await c.setNotifyValue(true);
          _subs.add(c.onValueReceived.listen((v) => _bus.push(Uint8List.fromList(v))));
        } catch (e) {
          // AE02 is mandatory; the FD* side-channels are best-effort.
          if (u == kAeNotify) {
            throw E87ConnectError('could not subscribe to AE02 notify: $e');
          }
        }
      }
    }
  }

  Future<void> _writeAe01(Uint8List data) =>
      _aeWrite!.write(data, withoutResponse: true);

  Future<void> _writeFd02(Uint8List data) async {
    final fd = _fdWrite;
    if (fd == null) return;
    try {
      await fd.write(data, withoutResponse: true);
    } catch (_) {/* side-channel; upload tolerates its absence */}
  }

  /// Push a fully-encoded JPEG (still image). See [render] helpers for producing
  /// a 368×368 badge face.
  Future<void> sendImage(Uint8List jpeg) async {
    if (!_authed) throw const E87ConnectError('not connected — call connect() first');
    final session = UploadSession(_writeAe01, _writeFd02, _bus);
    await session.run(jpeg, extension: kExtStatic);
  }

  /// Push a fully-encoded MJPG-AVI (animation).
  Future<void> sendAnimation(Uint8List avi) async {
    if (!_authed) throw const E87ConnectError('not connected — call connect() first');
    final session = UploadSession(_writeAe01, _writeFd02, _bus);
    await session.run(avi, extension: kExtAnimated);
  }

  Future<void> disconnect() async => _teardown();

  Future<void> _teardown() async {
    for (final sub in _subs) {
      await sub.cancel();
    }
    _subs.clear();
    try {
      await device.disconnect();
    } catch (_) {}
    _authed = false;
  }

  /// Last observed FE frame parse of a raw notification — exposed for debugging.
  static E87Frame? tryParse(List<int> raw) => parseFeFrame(raw);
}
