/// factory-android-badges — a phone acting as a BLE gateway that mirrors
/// factory's Devin usage onto one or more E87 round badges.
///
/// The screen is a control surface, not the product: the product is the image
/// on the badges. Here you preview the face, scan for badges, and watch each
/// push land.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:permission_handler/permission_handler.dart';

import 'badge_sync.dart';
import 'config.dart';
import 'e87/e87_const.dart';

void main() => runApp(const BadgesApp());

class BadgesApp extends StatelessWidget {
  const BadgesApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'factory badges',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true).copyWith(
        scaffoldBackgroundColor: const Color(0xFF141414),
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final BadgeSyncEngine _engine;

  @override
  void initState() {
    super.initState();
    _engine = BadgeSyncEngine(
      factory: AppConfig.factory,
      devinTiles: AppConfig.devinTiles,
      badges: AppConfig.badges,
    );
    _boot();
  }

  Future<void> _boot() async {
    await _requestPermissions();
    await _engine.loadPreview();
  }

  Future<void> _requestPermissions() async {
    await [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.locationWhenInUse,
    ].request();
  }

  @override
  void dispose() {
    _engine.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('factory · badges'),
        backgroundColor: const Color(0xFF141414),
        actions: [
          IconButton(
            icon: const Icon(Icons.bluetooth_searching),
            tooltip: 'Scan for E87 badges',
            onPressed: _openScanSheet,
          ),
        ],
      ),
      body: AnimatedBuilder(
        animation: _engine,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _preview(),
            const SizedBox(height: 20),
            _statusCard(),
            const SizedBox(height: 12),
            if (_engine.lastError != null)
              Card(
                color: const Color(0xFF3A1414),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text('Error: ${_engine.lastError}',
                      style: const TextStyle(color: Color(0xFFFFB4B4))),
                ),
              ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _engine.phase == SyncPhase.pushing ||
                _engine.phase == SyncPhase.fetching
            ? null
            : _engine.syncOnce,
        icon: const Icon(Icons.sync),
        label: Text(_engine.phase == SyncPhase.pushing ? 'Pushing…' : 'Sync now'),
      ),
    );
  }

  Widget _preview() {
    final jpeg = _engine.lastFaceJpeg;
    return Center(
      child: Container(
        width: 300,
        height: 300,
        decoration: const BoxDecoration(shape: BoxShape.circle, color: Colors.black),
        clipBehavior: Clip.antiAlias,
        child: jpeg == null
            ? const Center(child: CircularProgressIndicator())
            : Image.memory(jpeg, gaplessPlayback: true, fit: BoxFit.cover),
      ),
    );
  }

  Widget _statusCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('Fleet · ${_engine.badges.length} badge(s)',
                    style: const TextStyle(fontWeight: FontWeight.w600)),
                const Spacer(),
                Text(
                  _engine.lastSync == null
                      ? 'never synced'
                      : 'synced ${_ago(_engine.lastSync!)}',
                  style: const TextStyle(color: Color(0xFF8C9BAB), fontSize: 13),
                ),
              ],
            ),
            const Divider(),
            if (_engine.statuses.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  'No badges configured. Tap the scan icon to find one, then add '
                  'its id to AppConfig.badges.',
                  style: TextStyle(color: Color(0xFF8C9BAB)),
                ),
              )
            else
              for (final s in _engine.statuses)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(s.ok ? Icons.check_circle : Icons.radio_button_unchecked,
                      color: s.ok ? const Color(0xFF4CD964) : const Color(0xFF8C9BAB)),
                  title: Text(s.name),
                  subtitle: Text(s.remoteId, style: const TextStyle(fontSize: 11)),
                  trailing: Text(s.detail, style: const TextStyle(fontSize: 12)),
                ),
          ],
        ),
      ),
    );
  }

  String _ago(DateTime t) {
    final d = DateTime.now().difference(t);
    if (d.inMinutes < 1) return 'just now';
    if (d.inMinutes < 60) return '${d.inMinutes}m ago';
    return '${d.inHours}h ago';
  }

  Future<void> _openScanSheet() async {
    await _requestPermissions();
    final found = <String, String>{}; // id -> name
    final ctrl = StreamController<void>.broadcast();
    late final StreamSubscription sub;

    sub = FlutterBluePlus.scanResults.listen((results) {
      for (final r in results) {
        final name = r.advertisementData.advName;
        final isBadge = name == kLocalName ||
            r.advertisementData.serviceUuids
                .any((u) => u.str.toLowerCase() == kAdvertService16) ||
            r.advertisementData.manufacturerData.containsKey(kAdvertManufacturerId);
        if (isBadge) {
          found[r.device.remoteId.str] = name.isEmpty ? kLocalName : name;
          ctrl.add(null);
        }
      }
    });

    await FlutterBluePlus.startScan(timeout: const Duration(seconds: 10));

    if (!mounted) return;
    await showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF1E1E1E),
      builder: (context) => StreamBuilder<void>(
        stream: ctrl.stream,
        builder: (context, _) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('Scanning for E87 badges…',
                    style: TextStyle(fontWeight: FontWeight.w600)),
              ),
              if (found.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text('Nothing yet. Make sure the badge is awake.',
                      style: TextStyle(color: Color(0xFF8C9BAB))),
                ),
              for (final e in found.entries)
                ListTile(
                  leading: const Icon(Icons.badge),
                  title: Text(e.value),
                  subtitle: SelectableText(e.key,
                      style: const TextStyle(fontSize: 12)),
                  trailing: const Icon(Icons.copy, size: 18),
                  onTap: () {
                    // The id is what you paste into AppConfig.badges.
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('id: ${e.key}')),
                    );
                  },
                ),
            ],
          ),
        ),
      ),
    );

    await FlutterBluePlus.stopScan();
    await sub.cancel();
    await ctrl.close();
  }
}
