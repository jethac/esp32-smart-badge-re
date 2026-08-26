/// Runtime configuration: where factory lives, which badges to drive, and which
/// tiles feed the Devin face. Everything here is a local fact about *this*
/// fleet — the same way the reference wall hard-codes its LAN address.
///
/// Fill these in for your setup. The tile ids are best guesses at factory's
/// naming (`section:owner:reading`); correct them to whatever your
/// `/api/display` actually returns for Devin.
library;

class FactoryConfig {
  /// e.g. "http://192.168.1.4:8793" — factory's LAN display listener.
  final String baseUrl;

  /// The `display` persona bearer token.
  final String token;

  const FactoryConfig({required this.baseUrl, required this.token});
}

/// One badge in the fleet: its BLE remote-id (MAC on Android) and a friendly
/// name for the UI.
class BadgeConfig {
  final String remoteId;
  final String name;
  const BadgeConfig({required this.remoteId, required this.name});
}

/// Which tiles drive the Devin face. Ids are matched exactly first, then by a
/// looser owner+suffix fallback (see devin_face.dart), so a near-miss still
/// finds the right reading.
class DevinTiles {
  final String dayTileId; // percentage → outer ring
  final String weekTileId; // percentage → inner ring
  final String onDemandTileId; // formatted "$…" text → caption
  const DevinTiles({
    this.dayTileId = 'sub:devin:day',
    this.weekTileId = 'sub:devin:week',
    this.onDemandTileId = 'prepaid:devin',
  });

  List<String> get all => [dayTileId, weekTileId, onDemandTileId];
}

/// Edit these for your environment. Left blank/example on purpose — the app
/// surfaces a clear error rather than pretending to have data.
class AppConfig {
  static const factory = FactoryConfig(
    baseUrl: 'http://192.168.1.4:8793',
    token: 'REPLACE_WITH_DISPLAY_TOKEN',
  );

  static const devinTiles = DevinTiles();

  /// The badges to keep in sync. Discover a badge's remote-id once (it advertises
  /// as "E87"; see the Scan button in the app) and paste it here.
  static const badges = <BadgeConfig>[
    // BadgeConfig(remoteId: '46:8D:00:01:2C:25', name: 'Badge A'),
  ];

  /// How often to refetch factory and repush every badge.
  static const refreshInterval = Duration(minutes: 4);
}
