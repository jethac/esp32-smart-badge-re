/// Which mark belongs to a row, and what colour to draw it.
///
/// Mirrors factory's `providerIcon()`: an owner with no mark returns null, and
/// null means initials rather than a substitute drawing. A wrong mark is worse
/// than none — it is a false claim about whose number is on the wall. Do not
/// add one by finding a picture on the web; see assets/icons/README.md.
library;

import 'dart:ui' show Color;

/// The marks in assets/icons. Anything not here has none.
const _marks = {
  'aiand',
  'apple',
  'claude',
  'codex',
  'cursor',
  'debian',
  'devin',
  'gemini',
  'grok',
  'moonshot',
  'nvidia',
  'openrouter',
  'runpod',
  'vast',
  'windows',
};

/// Row owners whose mark is filed under a different name. `claude-main` and
/// `claude-jp` are two seats on one provider and share the one mark.
const _aliases = {
  'claude-main': 'claude',
  'claude-jp': 'claude',
  'cursor-agent': 'cursor',
  'kimi': 'moonshot',
  // Machines are identified by what they run, which nothing in the payload
  // reports — these three are a local fact about the fleet, the same way the
  // LAN address is. A host not listed here simply gets no mark.
  'jethas-mac-mini': 'apple',
  'stadia-testbed': 'debian',
  'thinkstationpgx-00b4': 'nvidia',
  'jetha-ws3': 'windows',
};

/// Brand colours, from simple-icons' published data rather than picked by eye.
///
/// Only the ones whose brand actually has a colour. A mark that is black or
/// near-black in its brand guidelines — Apple, OpenAI, Cursor, X, Kimi — is not
/// listed: forcing a colour on a monochrome mark would be inventing a brand.
/// Those draw in the foreground colour, which is what they look like on any
/// dark surface anyway.
const _brandColours = {
  'claude': Color(0xFFD97757),
  'debian': Color(0xFFA81D33),
  'nvidia': Color(0xFF76B900),
  'gemini': Color(0xFF8E75B2),
  'openrouter': Color(0xFF94A3B8),
  // Fluent blue. simple-icons carries no Microsoft marks, so this is Microsoft's
  // own published Windows blue rather than a value from that data set.
  'windows': Color(0xFF0078D4),
};

String _canonical(String owner) {
  final key = _aliases[owner] ?? owner;
  if (_marks.contains(key)) return key;
  // A seat named `<provider>-<something>` shares its provider's mark, so a new
  // account does not need a code change to be recognised on the wall.
  final dash = key.indexOf('-');
  if (dash > 0 && _marks.contains(key.substring(0, dash))) {
    return key.substring(0, dash);
  }
  return '';
}

/// Asset path for an owner's mark, or null when none is vendored.
///
/// Every provider has one now. An owner still not covered — a new account, an
/// unrecognised host — returns null and falls back to initials.
String? markFor(String owner) {
  final key = _canonical(owner);
  return key.isEmpty ? null : 'assets/icons/$key.svg';
}

/// The mark's brand colour, or null to draw it in the foreground colour.
Color? brandColour(String owner) => _brandColours[_canonical(owner)];

/// What to draw when there is no mark: at most two letters, upper case.
///
/// Letters only — `thinkstationpgx-00b4` initialled as "TH", not "T0", and a
/// row whose name starts with punctuation still gets something legible.
String initialsFor(String owner) {
  final letters = owner.replaceAll(RegExp(r'[^A-Za-z]'), '');
  if (letters.isEmpty) return '?';
  return letters.substring(0, letters.length >= 2 ? 2 : 1).toUpperCase();
}
