/// Which row a tile belongs on.
///
/// Pure, and separate from both the client and the screen, because getting it
/// wrong is silent: the first version trimmed everything after the last colon,
/// which is right for `sub:codex:week` and wrong for `prepaid:runpod`, and put
/// all six prepaid providers on one row labelled "prepaid". The board still
/// rendered, still showed numbers, and was simply wrong.
library;

import 'factory_client.dart';

/// The account, provider or machine a tile belongs to.
///
/// Ids are `section:owner` or `section:owner:reading`, so the owner is always
/// the second segment. An id with no second segment is its own owner rather
/// than being dropped — an unfamiliar id should appear on the wall looking odd,
/// not vanish from it.
String ownerOf(Tile tile) {
  final parts = tile.id.split(':');
  return parts.length > 1 && parts[1].isNotEmpty ? parts[1] : tile.id;
}

/// Tiles grouped by owner, each group in the order factory sent it, and the
/// groups themselves in the order their first tile arrived.
Map<String, List<Tile>> groupByOwner(List<Tile> tiles) {
  final groups = <String, List<Tile>>{};
  for (final t in tiles) {
    (groups[ownerOf(t)] ??= []).add(t);
  }
  return groups;
}
