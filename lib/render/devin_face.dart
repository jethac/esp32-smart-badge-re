/// Maps a factory [Board] into a [FaceModel] for Devin.
///
/// Ring colours are deliberately fixed per-metric (day green, week amber) —
/// Apple-Watch identity, so the two rings never read as the same thing. That is
/// a considered departure from factory's "colour comes from the tile"; the band
/// colour still governs everything textual on the wall, just not these two ring
/// hues. The on-demand figure is drawn verbatim from the tile's `text`, so this
/// device never formats money.
library;

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../config.dart';
import '../factory_client.dart';
import '../tile_groups.dart';
import 'provider_face.dart';

/// Apple-Watch ring identities.
const Color kDayColour = Color(0xFF4CD964);
const Color kWeekColour = Color(0xFFFF9F0A);

class DevinFaceError implements Exception {
  final String message;
  const DevinFaceError(this.message);
  @override
  String toString() => message;
}

/// Load the vendored Devin mark once.
Future<String> _loadDevinSvg() =>
    rootBundle.loadString('assets/icons/devin.svg');

/// Find a tile by exact id, else by owner + a reading suffix ("day"/"week").
Tile? _pick(Board board, String exactId, {String? ownerSuffix}) {
  for (final t in board.tiles) {
    if (t.id == exactId) return t;
  }
  if (ownerSuffix != null) {
    for (final t in board.tiles) {
      if (ownerOf(t) == 'devin' && t.id.endsWith(':$ownerSuffix')) return t;
    }
  }
  return null;
}

/// Build the Devin face from a freshly fetched [board].
Future<FaceModel> buildDevinFace(Board board, DevinTiles ids) async {
  final svg = await _loadDevinSvg();

  final day = _pick(board, ids.dayTileId, ownerSuffix: 'day');
  final week = _pick(board, ids.weekTileId, ownerSuffix: 'week');
  final onDemand = _pick(board, ids.onDemandTileId);

  if (day == null && week == null) {
    throw const DevinFaceError('no Devin day/week tiles in factory response');
  }

  double frac(Tile? t) => ((t?.pct ?? 0) / 100).clamp(0.0, 1.0);

  // Caption: the on-demand tile's pre-formatted text, else its note, else "—".
  final caption = onDemand?.text ?? onDemand?.note ?? '—';

  return FaceModel(
    logoSvg: svg,
    caption: caption,
    outer: Ring(fraction: frac(day), colour: kDayColour, label: 'Day'),
    inner: Ring(fraction: frac(week), colour: kWeekColour, label: 'Week'),
    logoColour: Colors.white,
    background: Colors.black,
  );
}

/// A face built from placeholder numbers, for previewing the layout without a
/// live factory connection (matches the confirmed on-device mock).
Future<FaceModel> buildDevinPreviewFace() async {
  final svg = await _loadDevinSvg();
  return FaceModel(
    logoSvg: svg,
    caption: r'$17.34',
    outer: const Ring(fraction: 0.63, colour: kDayColour, label: 'Day'),
    inner: const Ring(fraction: 0.41, colour: kWeekColour, label: 'Week'),
  );
}
