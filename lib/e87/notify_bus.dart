/// Buffer of incoming BLE notifications with predicate-based async waiters.
/// Dart analogue of the reference `NotifyBus`.
library;

import 'dart:async';
import 'dart:typed_data';

import 'frame.dart';

class NotifyBus {
  final List<Uint8List> _queue = [];
  final StreamController<void> _tick = StreamController<void>.broadcast();

  void push(Uint8List data) {
    _queue.add(data);
    // Bound the queue so a slow consumer can't exhaust memory.
    if (_queue.length > 300) {
      _queue.removeRange(0, _queue.length - 300);
    }
    if (!_tick.isClosed) _tick.add(null);
  }

  /// Drop everything queued. Stale frames from a previous auth or upload
  /// session must never satisfy a later session's waiters.
  void clear() => _queue.clear();

  Uint8List? _consume(bool Function(Uint8List) predicate) {
    for (var i = 0; i < _queue.length; i++) {
      if (predicate(_queue[i])) {
        return _queue.removeAt(i);
      }
    }
    return null;
  }

  Future<Uint8List> waitForRaw(
    bool Function(Uint8List) predicate,
    Duration timeout,
    String label,
  ) async {
    final deadline = DateTime.now().add(timeout);
    while (true) {
      final hit = _consume(predicate);
      if (hit != null) return hit;
      final remaining = deadline.difference(DateTime.now());
      if (remaining <= Duration.zero) {
        throw TimeoutException('timeout waiting for $label');
      }
      // Wake on the next push, or when the remaining budget elapses.
      try {
        await _tick.stream.first.timeout(remaining);
      } on TimeoutException {
        // loop around; _consume re-checks then the deadline test throws.
      }
    }
  }

  Future<E87Frame> waitForFrame(
    bool Function(E87Frame) predicate,
    Duration timeout,
    String label,
  ) async {
    final raw = await waitForRaw((r) {
      final f = parseFeFrame(r);
      return f != null && predicate(f);
    }, timeout, label);
    return parseFeFrame(raw)!;
  }

  void dispose() {
    if (!_tick.isClosed) _tick.close();
  }
}
