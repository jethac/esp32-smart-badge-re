/// 9-phase upload state machine for the E87 badge. Faithful port of the
/// reference `protocol.py` `UploadSession`.
///
/// Takes two writer callables (AE01 and FD02) and a [NotifyBus] already fed by
/// AE02 (and ideally FD01/FD03/FD05). `run(data, extension:)` negotiates the
/// pre-upload phases and streams the payload in windowed chunks. `extension`
/// selects still image ('jpg') or animated MJPG-AVI ('avi').
library;

import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

import 'crc.dart';
import 'e87_const.dart';
import 'frame.dart';
import 'notify_bus.dart';

typedef Writer = Future<void> Function(Uint8List data);

class E87ProtocolError implements Exception {
  final String message;
  const E87ProtocolError(this.message);
  @override
  String toString() => 'E87ProtocolError: $message';
}

class E87TransferAborted implements Exception {
  final String message;
  const E87TransferAborted(this.message);
  @override
  String toString() => 'E87TransferAborted: $message';
}

/// How many times we'll honour a badge re-requesting an already-delivered
/// offset (a legitimate failed-window-CRC retransmit) before ignoring it (a
/// wedged badge that would otherwise loop us until timeout).
const int _maxPostEofResends = 3;

Uint8List _hex(String s) {
  final out = Uint8List(s.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    out[i] = int.parse(s.substring(i * 2, i * 2 + 2), radix: 16);
  }
  return out;
}

class _TransferState {
  int dataSeq;
  final int totalChunks;
  int sentChunks = 0;
  int totalBytesSent = 0;
  int maxOffsetDelivered = 0;
  final Map<int, int> postEofResends = {};
  _TransferState({required this.dataSeq, required this.totalChunks});
}

class UploadSession {
  final Writer _writeAe01;
  final Writer _writeFd02;
  final NotifyBus _bus;
  final Random _rng = Random();

  int _seq = 0x00;
  bool _fileCompleteHandled = false;

  UploadSession(this._writeAe01, this._writeFd02, this._bus);

  Future<void> run(Uint8List data, {String extension = kExtStatic}) async {
    _seq = 0x00;
    _fileCompleteHandled = false;
    _bus.clear();

    await _phase1ResetAuth();
    await _phase2Fd02Control();
    await _phase3DeviceInfo();
    await _phase4DeviceConfig();
    await _phase5Fd02Bootstrap();
    await _phase6BeginUpload();
    await _phase7TransferParams();
    final chunkSize = await _phase8FileMetadata(data, extension);
    await _phase9Transfer(data, chunkSize, extension);
  }

  Future<void> _sendFe(int flag, int cmd, List<int> body) =>
      _writeAe01(buildFeFrame(flag, cmd, body));

  Future<void> _phase1ResetAuth() async {
    await _sendFe(kFlagCommand, 0x06, const [0x02, 0x00, 0x01]);
    _seq = 0x01;
    await _writeFd02(_hex('9EBD0B600D0003'));
    try {
      await _bus.waitForFrame(
          (f) => f.cmd == 0x06, const Duration(seconds: 3), 'ack cmd 0x06');
    } on TimeoutException {/* continue */}
  }

  Future<void> _phase2Fd02Control() async {
    final now = DateTime.now();
    final timePayload = Uint8List.fromList([
      0x9E, 0x45, 0x08, 0x02, 0x07, 0x00,
      now.year & 0xFF, (now.year >> 8) & 0xFF,
      now.month, now.day, 0x00,
      now.hour, now.minute,
    ]);
    await _writeFd02(timePayload);
    await Future.delayed(const Duration(milliseconds: 20));
    await _writeFd02(_hex('9E200816010001'));
    await Future.delayed(const Duration(milliseconds: 20));
    await _writeFd02(_hex('9EB50B29010080'));
    await Future.delayed(const Duration(milliseconds: 200));
  }

  Future<void> _phase3DeviceInfo() async {
    try {
      await _sendFe(kFlagCommand, 0x03, [_seq, 0xFF, 0xFF, 0xFF, 0xFF, 0x01]);
      _seq++;
      await _writeFd02(_hex('9ED30BC6010001'));
      await Future.delayed(const Duration(milliseconds: 20));
      await _writeFd02(_hex('9E3008200200FF07'));
      await _bus.waitForFrame(
          (f) => f.cmd == 0x03, const Duration(seconds: 3), 'ack cmd 0x03');
    } on TimeoutException {/* continue */}
  }

  Future<void> _phase4DeviceConfig() async {
    try {
      await _sendFe(kFlagCommand, 0x07, [_seq, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]);
      _seq++;
      await _writeFd02(_hex('9E2B08FF02002200'));
      await Future.delayed(const Duration(milliseconds: 40));
      await _writeFd02(_hex('9E2D08FF02002400'));
      await _bus.waitForFrame(
          (f) => f.cmd == 0x07, const Duration(seconds: 3), 'ack cmd 0x07');
    } on TimeoutException {/* continue */}
  }

  Future<void> _phase5Fd02Bootstrap() async {
    await _writeFd02(_hex('9EB50B29010080'));
    await Future.delayed(const Duration(milliseconds: 400));
    await _writeFd02(_hex('9ED30BC6010001'));
    try {
      await _bus.waitForRaw(
        (r) => r.length >= 5 && r[0] == 0x9E && (r[3] == 0xC7 || r[2] == 0xC7),
        const Duration(seconds: 3),
        'FD01 device info (C7)',
      );
    } on TimeoutException {/* continue */}
    await _writeFd02(_hex('9EF40BDC01000C'));
    try {
      await _bus.waitForRaw(
        (r) => r.length >= 4 && r[0] == 0x9E && r[1] == 0xE6,
        const Duration(seconds: 3),
        'FD03 ready signal (9EE6)',
      );
    } on TimeoutException {/* continue */}
  }

  Future<void> _phase6BeginUpload() async {
    await _sendFe(kFlagCommand, 0x21, [_seq, 0x00]);
    _seq++;
    try {
      await _bus.waitForFrame(
          (f) => f.cmd == 0x21, const Duration(seconds: 8), 'ack cmd 0x21');
    } on TimeoutException {
      throw const E87ProtocolError('device did not ack begin-upload (cmd 0x21)');
    }
  }

  Future<void> _phase7TransferParams() async {
    await _sendFe(kFlagCommand, 0x27, [_seq, 0x00, 0x00, 0x00, 0x00, 0x02, 0x01]);
    _seq++;
    try {
      await _bus.waitForFrame(
          (f) => f.cmd == 0x27, const Duration(seconds: 8), 'ack cmd 0x27');
    } on TimeoutException {
      throw const E87ProtocolError('device did not ack transfer params (cmd 0x27)');
    }
  }

  Future<int> _phase8FileMetadata(Uint8List data, String extension) async {
    final fileSize = data.length;
    final tempName = '${_rng.nextInt(0xFFFFFF).toRadixString(16).padLeft(6, '0')}.$extension';
    final nameBytes = tempName.codeUnits;
    final fileCrc = crc16Xmodem(data);

    final meta = Uint8List(3 + 2 + 4 + nameBytes.length + 1);
    meta[0] = _seq & 0xFF;
    _seq++;
    meta[1] = (fileSize >> 24) & 0xFF;
    meta[2] = (fileSize >> 16) & 0xFF;
    meta[3] = (fileSize >> 8) & 0xFF;
    meta[4] = fileSize & 0xFF;
    meta[5] = (fileCrc >> 8) & 0xFF;
    meta[6] = fileCrc & 0xFF;
    meta[7] = _rng.nextInt(256);
    meta[8] = _rng.nextInt(256);
    meta.setRange(9, 9 + nameBytes.length, nameBytes);
    meta[meta.length - 1] = 0x00;

    await _sendFe(kFlagCommand, 0x1B, meta);
    final E87Frame metaAck;
    try {
      metaAck = await _bus.waitForFrame(
          (f) => f.cmd == 0x1B, const Duration(seconds: 8), 'ack cmd 0x1b');
    } on TimeoutException {
      throw const E87ProtocolError('device did not ack file metadata (cmd 0x1b)');
    }

    var chunkSize = kDataChunkSize;
    if (metaAck.body.length >= 4) {
      final hinted = (metaAck.body[2] << 8) | metaAck.body[3];
      if (hinted > 0 && hinted <= 4096) chunkSize = hinted;
    }
    return chunkSize;
  }

  Future<void> _phase9Transfer(Uint8List data, int chunkSize, String extension) async {
    final totalChunks = (data.length + chunkSize - 1) ~/ chunkSize;
    final state = _TransferState(dataSeq: _seq, totalChunks: totalChunks);

    E87Frame? currentAck;
    try {
      currentAck = await _bus.waitForFrame(
        (f) => f.flag == kFlagData && f.cmd == 0x1D,
        const Duration(seconds: 30),
        'initial window ack',
      );
    } on TimeoutException {
      await _abortSession('no initial window ack');
      throw const E87TransferAborted(
          'device did not send the initial window ack within 30s');
    }

    var fileFullySent = false;
    while (true) {
      if (currentAck != null && currentAck.cmd == 0x1D && currentAck.body.length >= 8) {
        final b = currentAck.body;
        final winSize = (b[2] << 8) | b[3];
        final nextOffset = (b[4] << 24) | (b[5] << 16) | (b[6] << 8) | b[7];

        if (nextOffset >= data.length) {
          fileFullySent = true;
        } else if (fileFullySent && nextOffset < data.length) {
          final resends = state.postEofResends[nextOffset] ?? 0;
          if (resends < _maxPostEofResends) {
            state.postEofResends[nextOffset] = resends + 1;
            await _sendWindow(data, chunkSize, nextOffset, winSize, state);
          }
        } else {
          await _sendWindow(data, chunkSize, nextOffset, winSize, state);
          if (state.maxOffsetDelivered >= data.length) fileFullySent = true;
        }
      }

      final E87Frame frame;
      try {
        frame = await _bus.waitForFrame(
          (f) => (f.flag == kFlagData && f.cmd == 0x1D) || f.cmd == 0x20 || f.cmd == 0x1C,
          const Duration(seconds: 30),
          'window ack, FILE_COMPLETE or session close',
        );
      } on TimeoutException {
        await _abortSession('no window ack at ${state.totalBytesSent}/${data.length}');
        throw E87TransferAborted(
            'no window ack or completion within 30s '
            '(${state.totalBytesSent}/${data.length} bytes sent)');
      }

      if (frame.cmd == 0x20 && frame.flag == kFlagCommand) {
        final deviceSeq20 = frame.body.isNotEmpty ? frame.body[0] : (state.dataSeq & 0xFF);
        if (!_fileCompleteHandled) {
          await _sendFe(kFlagResponse, 0x20, _buildFilePathResponse(deviceSeq20, extension));
          _fileCompleteHandled = true;
        }
        final closeFrame = await _bus.waitForFrame(
            (f) => f.cmd == 0x1C, const Duration(seconds: 30), 'session close (cmd 0x1c)');
        await _finalize(closeFrame);
        return;
      }

      if (frame.cmd == 0x1C) {
        await _finalize(frame);
        return;
      }

      currentAck = frame;
    }
  }

  Future<void> _sendWindow(
      Uint8List data, int chunkSize, int offset, int winSize, _TransferState state) async {
    var slot = 0;
    var bytesInWindow = 0;
    while (bytesInWindow < winSize) {
      final chunkOffset = offset + bytesInWindow;
      if (chunkOffset >= data.length) break;
      final remaining = min(winSize - bytesInWindow, data.length - chunkOffset);
      final chunkLen = min(chunkSize, remaining);
      final payload = data.sublist(chunkOffset, chunkOffset + chunkLen);
      final crc = crc16Xmodem(payload);

      final body = Uint8List(5 + payload.length);
      body[0] = state.dataSeq & 0xFF;
      body[1] = 0x1D;
      body[2] = slot & 0xFF;
      body[3] = (crc >> 8) & 0xFF;
      body[4] = crc & 0xFF;
      body.setRange(5, 5 + payload.length, payload);

      await _writeAe01(buildFeFrame(kFlagData, 0x01, body));

      state.sentChunks++;
      state.totalBytesSent += chunkLen;
      state.dataSeq = (state.dataSeq + 1) & 0xFF;
      slot = (slot + 1) & 0x07;
      bytesInWindow += chunkLen;
    }
    state.maxOffsetDelivered =
        max(state.maxOffsetDelivered, offset + bytesInWindow);
  }

  Future<void> _abortSession(String reason) async {
    try {
      await _sendFe(kFlagCommand, 0x1C, [_seq & 0xFF, 0x00]);
      _seq = (_seq + 1) & 0xFF;
    } catch (_) {/* about to disconnect anyway */}
  }

  Future<void> _finalize(E87Frame closeFrame) async {
    final deviceSeq = closeFrame.body.isNotEmpty ? closeFrame.body[0] : 0;
    final hasStatus = closeFrame.body.length >= 2;
    final status = hasStatus ? closeFrame.body[1] : 0xFF;
    await _sendFe(kFlagResponse, 0x1C, [0x00, deviceSeq & 0xFF]);
    if (hasStatus && status != 0x00) {
      throw E87ProtocolError(
          'badge reported failure status 0x${status.toRadixString(16)} on session close');
    }
  }

  Uint8List _buildFilePathResponse(int deviceSeq, String extension) {
    final now = DateTime.now();
    String two(int v) => v.toString().padLeft(2, '0');
    final dateStr = '${now.year}${two(now.month)}${two(now.day)}'
        '${two(now.hour)}${two(now.minute)}${two(now.second)}';
    final devicePath = '啜$dateStr.$extension';
    // UTF-16LE + trailing 0x0000 terminator.
    final units = devicePath.codeUnits;
    final utf16 = Uint8List(units.length * 2 + 2);
    for (var i = 0; i < units.length; i++) {
      utf16[i * 2] = units[i] & 0xFF;
      utf16[i * 2 + 1] = (units[i] >> 8) & 0xFF;
    }
    return Uint8List.fromList([0x00, deviceSeq & 0xFF, ...utf16]);
  }
}
