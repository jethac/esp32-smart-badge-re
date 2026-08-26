/// GATT UUIDs, FE-framing constants, and transfer defaults for the E87 /
/// JieLi AC697 badge. Ported from the Python reference
/// (jumpingmushroom/e87_badge, `const.py`). No runtime logic here.
library;

// ── Advertising ────────────────────────────────────────────────────────────

/// GAP local name in the scan response. Active scan required to see it.
const String kLocalName = 'E87';

/// 16-bit service 0xFD00 in the primary advertisement (passive-safe).
const String kAdvertService16 = '0000fd00-0000-1000-8000-00805f9b34fb';

/// Manufacturer company id 0x6DB3 — not a real SIG id, an E87-family
/// fingerprint that passive scanners can match on.
const int kAdvertManufacturerId = 28083;

// ── Primary image-upload service (AE00) ────────────────────────────────────

const String kAeService = '0000ae00-0000-1000-8000-00805f9b34fb';
const String kAeWrite = '0000ae01-0000-1000-8000-00805f9b34fb'; // write-without-response
const String kAeNotify = '0000ae02-0000-1000-8000-00805f9b34fb'; // notify

// ── JieLi RCSP side-channel service (FD00) ─────────────────────────────────

const String kFdService = 'c2e6fd00-e966-1000-8000-bef9c223df6a';
const String kFdWrite = 'c2e6fd02-e966-1000-8000-bef9c223df6a';
const List<String> kFdNotify = [
  'c2e6fd01-e966-1000-8000-bef9c223df6a',
  'c2e6fd03-e966-1000-8000-bef9c223df6a',
  'c2e6fd05-e966-1000-8000-bef9c223df6a',
];

/// Every notify characteristic we subscribe to during auth + upload.
const List<String> kAllNotify = [kAeNotify, ...kFdNotify];

// ── Image encoding targets ─────────────────────────────────────────────────

const int kImageWidth = 368;
const int kImageHeight = 368;

/// Upstream targets ≤16 KB for a single-image JPEG.
const int kTargetImageBytes = 16000;

/// Descending JPEG qualities tried to stay under [kTargetImageBytes].
const List<int> kJpegQualitySteps = [88, 80, 72, 64, 56, 48, 40, 34];

// ── FE-framed wire protocol ────────────────────────────────────────────────

const List<int> kFeHeader = [0xFE, 0xDC, 0xBA];
const int kFeTerminator = 0xEF;

const int kFlagCommand = 0xC0; // phone→device request
const int kFlagResponse = 0x00; // ack / response
const int kFlagData = 0x80; // data frame / data-channel notify (0x1D)

// ── File-transfer defaults ─────────────────────────────────────────────────

/// Default per-chunk payload. The badge advertises its preferred value in the
/// cmd 0x1B ack; honour that when present, fall back to this otherwise.
const int kDataChunkSize = 490;

const String kExtStatic = 'jpg';
const String kExtAnimated = 'avi';
