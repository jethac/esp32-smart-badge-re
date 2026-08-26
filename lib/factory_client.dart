/// factory's tile API, as a client.
///
/// Deliberately the whole reusable surface: this file knows how to talk to
/// factory and nothing about how anything is drawn. The wall app renders every
/// tile; a phone acting as a BLE gateway for ESP32 round displays fetches three
/// or four by id and forwards them. Both use this unchanged.
///
/// The client never formats and never colours. `text` arrives as "65%" or
/// "$17.34" and `colour` as a hex string, because two clients formatting
/// independently is how a wall and a watch start disagreeing about money. If a
/// number looks wrong here, it is wrong in factory.
library;

import 'dart:convert';
import 'dart:io';

/// Which band a reading falls in. Grey means nothing has moved for an hour.
enum Band { idle, low, steady, high, critical }

Band _bandOf(String s) => switch (s) {
      'low' => Band.low,
      'steady' => Band.steady,
      'high' => Band.high,
      'critical' => Band.critical,
      _ => Band.idle,
    };

/// One reading. Everything needed to draw it is already here.
class Tile {
  /// Stable address, e.g. `sub:claude-main:week`. Safe to hardcode on a device.
  final String id;

  /// `subscription` | `prepaid` | `machine` | `summary`.
  final String section;

  /// Full name, for a surface with room.
  final String label;

  /// Short name for a small screen — never more than 8 characters.
  final String short;

  /// 0-100 where the tile is a proportion, else null. Drives an arc or a bar.
  final double? pct;

  /// The reading, already formatted with its unit. Draw verbatim.
  final String text;

  final Band band;

  /// The band as a colour, so a device carries no palette of its own.
  final int colour;

  /// When the underlying window refills, or null.
  final DateTime? resetsAt;

  /// Why there is no reading. Never [text]: a small screen draws text verbatim
  /// and "reports spend only — no balance to check" is a sentence.
  final String? note;

  const Tile({
    required this.id,
    required this.section,
    required this.label,
    required this.short,
    required this.pct,
    required this.text,
    required this.band,
    required this.colour,
    required this.resetsAt,
    required this.note,
  });

  factory Tile.fromJson(Map<String, dynamic> j) {
    final raw = (j['colour'] as String? ?? '#8c9bab').replaceFirst('#', '');
    return Tile(
      id: j['id'] as String,
      section: j['section'] as String? ?? 'summary',
      label: j['label'] as String? ?? '',
      short: j['short'] as String? ?? '',
      // A percentage may be int or double over the wire.
      pct: (j['pct'] as num?)?.toDouble(),
      text: j['text'] as String? ?? '—',
      band: _bandOf(j['band'] as String? ?? 'idle'),
      colour: 0xFF000000 | int.parse(raw, radix: 16),
      resetsAt: j['resetsAt'] == null ? null : DateTime.tryParse(j['resetsAt'] as String),
      note: j['note'] as String?,
    );
  }
}

/// A whole fetch. [generatedAt] is factory's clock, not the device's.
class Board {
  final DateTime generatedAt;

  /// How long a client may hold this before it misleads. Matches the poller.
  final Duration ttl;
  final List<Tile> tiles;

  const Board({required this.generatedAt, required this.ttl, required this.tiles});

  factory Board.fromJson(Map<String, dynamic> j) => Board(
        generatedAt: DateTime.tryParse(j['generatedAt'] as String? ?? '') ?? DateTime.now(),
        ttl: Duration(seconds: (j['ttlSeconds'] as num?)?.toInt() ?? 300),
        tiles: ((j['tiles'] as List?) ?? const [])
            .map((t) => Tile.fromJson(t as Map<String, dynamic>))
            .toList(growable: false),
      );

  /// Tiles of one section, in the order factory sent them.
  List<Tile> section(String name) => tiles.where((t) => t.section == name).toList(growable: false);
}

/// Raised for anything that leaves the caller without data. Carries a message
/// short enough to draw on the screen that failed, because a wall panel has no
/// log anyone will read.
class FactoryError implements Exception {
  final String message;
  const FactoryError(this.message);
  @override
  String toString() => message;
}

class FactoryClient {
  /// e.g. `http://192.168.1.4:8793`. The LAN listener, which serves this one
  /// route and holds no other capability.
  final Uri base;

  /// The `display` persona's bearer token.
  final String token;

  final Duration timeout;

  FactoryClient({required String baseUrl, required this.token, this.timeout = const Duration(seconds: 8)})
      : base = Uri.parse(baseUrl);

  /// Fetch tiles. Pass [ids] for a subset — that is the ESP32 case, where the
  /// whole board is ~6.5KB and one tile is ~250 bytes.
  Future<Board> fetch({List<String>? ids}) async {
    final uri = base.replace(
      path: '/api/display',
      queryParameters: (ids != null && ids.isNotEmpty) ? {'tiles': ids.join(',')} : null,
    );
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final req = await client.getUrl(uri).timeout(timeout);
      req.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      req.headers.set(HttpHeaders.acceptHeader, 'application/json');
      final res = await req.close().timeout(timeout);
      final body = await res.transform(utf8.decoder).join().timeout(timeout);
      if (res.statusCode == 401 || res.statusCode == 403) {
        throw const FactoryError('token rejected');
      }
      if (res.statusCode != 200) {
        throw FactoryError('factory answered ${res.statusCode}');
      }
      // A non-JSON 200 means something other than factory answered — a captive
      // portal on the wifi, most likely. Saying so beats a parser stack trace.
      final decoded = jsonDecode(body);
      if (decoded is! Map<String, dynamic>) {
        throw const FactoryError('unexpected response');
      }
      return Board.fromJson(decoded);
    } on FactoryError {
      rethrow;
    } on SocketException {
      throw const FactoryError('no route to factory');
    } catch (e) {
      throw FactoryError(e.toString().split('\n').first);
    } finally {
      client.close(force: true);
    }
  }
}
