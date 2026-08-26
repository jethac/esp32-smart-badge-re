/// FE-framed wire format used on AE01 (write) / AE02 (notify).
///
///     3 bytes   header      FE DC BA
///     1 byte    flag        0xC0 command, 0x00 response, 0x80 data/notify
///     1 byte    cmd         command opcode
///     2 bytes   length      big-endian body length
///     N bytes   body
///     1 byte    terminator  0xEF
library;

import 'dart:typed_data';

import 'e87_const.dart';

class E87Frame {
  final int flag;
  final int cmd;
  final int length;
  final Uint8List body;

  const E87Frame(this.flag, this.cmd, this.length, this.body);

  @override
  String toString() =>
      'E87Frame(flag=0x${flag.toRadixString(16)}, cmd=0x${cmd.toRadixString(16)}, '
      'len=$length)';
}

/// Parse a well-formed FE frame, or null if [data] is not one.
E87Frame? parseFeFrame(List<int> data) {
  if (data.length < 8) return null;
  if (data[0] != kFeHeader[0] ||
      data[1] != kFeHeader[1] ||
      data[2] != kFeHeader[2] ||
      data[data.length - 1] != kFeTerminator) {
    return null;
  }
  final flag = data[3];
  final cmd = data[4];
  final length = (data[5] << 8) | data[6];
  final body = Uint8List.fromList(data.sublist(7, data.length - 1));
  if (body.length != length) return null;
  return E87Frame(flag, cmd, length, body);
}

Uint8List buildFeFrame(int flag, int cmd, List<int> body) {
  if (body.length > 0xFFFF) {
    throw ArgumentError('body too long for 16-bit length');
  }
  final out = BytesBuilder();
  out.add(kFeHeader);
  out.addByte(flag & 0xFF);
  out.addByte(cmd & 0xFF);
  out.addByte((body.length >> 8) & 0xFF);
  out.addByte(body.length & 0xFF);
  out.add(body);
  out.addByte(kFeTerminator);
  return out.toBytes();
}
