/// The gateway engine: fetch Devin's numbers from factory, render one face, and
/// push that identical image to every configured badge so the fleet stays in
/// sync. Sequential per-badge connect→push→disconnect — one BLE session at a
/// time is the reliable path on Android.
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';

import 'config.dart';
import 'e87/e87_client.dart';
import 'factory_client.dart';
import 'render/devin_face.dart';
import 'render/provider_face.dart';

enum SyncPhase { idle, fetching, rendering, pushing, done, error }

class BadgeStatus {
  final String name;
  final String remoteId;
  String detail;
  bool ok;
  BadgeStatus(this.name, this.remoteId, {this.detail = 'idle', this.ok = false});
}

class BadgeSyncEngine extends ChangeNotifier {
  final FactoryConfig factory;
  final DevinTiles devinTiles;
  final List<BadgeConfig> badges;

  BadgeSyncEngine({
    required this.factory,
    required this.devinTiles,
    required this.badges,
  }) {
    statuses = [
      for (final b in badges) BadgeStatus(b.name, b.remoteId),
    ];
  }

  late final FactoryClient _client =
      FactoryClient(baseUrl: factory.baseUrl, token: factory.token);

  SyncPhase phase = SyncPhase.idle;
  String? lastError;
  Uint8List? lastFaceJpeg; // for on-screen preview
  DateTime? lastSync;
  List<BadgeStatus> statuses = [];
  bool _busy = false;

  Timer? _timer;

  void startPeriodic(Duration interval) {
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) => syncOnce());
    syncOnce();
  }

  void stopPeriodic() {
    _timer?.cancel();
    _timer = null;
  }

  Future<void> syncOnce() async {
    if (_busy) return;
    _busy = true;
    lastError = null;
    try {
      _set(SyncPhase.fetching);
      final board = await _client.fetch(ids: devinTiles.all);

      _set(SyncPhase.rendering);
      final face = await buildDevinFace(board, devinTiles);
      final jpeg = await renderFaceJpeg(face);
      lastFaceJpeg = jpeg;
      notifyListeners();

      _set(SyncPhase.pushing);
      for (final status in statuses) {
        await _pushToBadge(status, jpeg);
      }

      lastSync = DateTime.now();
      _set(SyncPhase.done);
    } catch (e) {
      lastError = e.toString();
      _set(SyncPhase.error);
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  /// Render a preview face from placeholder numbers (no factory needed).
  Future<void> loadPreview() async {
    final face = await buildDevinPreviewFace();
    lastFaceJpeg = await renderFaceJpeg(face);
    notifyListeners();
  }

  Future<void> _pushToBadge(BadgeStatus status, Uint8List jpeg) async {
    final client = E87Client.fromId(status.remoteId);
    try {
      status
        ..detail = 'connecting…'
        ..ok = false;
      notifyListeners();
      await client.connect();
      status.detail = 'pushing…';
      notifyListeners();
      await client.sendImage(jpeg);
      status
        ..detail = 'synced'
        ..ok = true;
    } catch (e) {
      status
        ..detail = 'failed: $e'
        ..ok = false;
    } finally {
      await client.disconnect();
      notifyListeners();
    }
  }

  void _set(SyncPhase p) {
    phase = p;
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
