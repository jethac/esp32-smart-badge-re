/// Renders an Apple-Watch-style provider "face" to a 368×368 JPEG the badge can
/// display: a centred provider mark, small grey caption below it, and two
/// concentric activity rings (outer = day, inner = week).
///
/// The output matches the on-device design mock: black field, rounded-cap arcs
/// over faint tracks, monochrome mark tinted to [FaceModel.logoColour].
library;

import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:image/image.dart' as img;

import '../e87/e87_const.dart';

/// One ring's data: how full (0..1) and what colour.
class Ring {
  final double fraction; // 0..1, clamped
  final Color colour;
  final String label; // "Day" / "Week", for legend/debug
  const Ring({required this.fraction, required this.colour, required this.label});
}

/// Everything needed to draw one provider face.
class FaceModel {
  /// Raw SVG string of the provider mark (e.g. contents of devin.svg).
  final String logoSvg;

  /// Colour to tint the mark (mark SVGs use `currentColor`).
  final Color logoColour;

  /// Small grey text under the mark — the on-demand usage, e.g. "$17.34".
  final String caption;

  /// Outer ring (day) and inner ring (week).
  final Ring outer;
  final Ring inner;

  final Color background;

  const FaceModel({
    required this.logoSvg,
    required this.caption,
    required this.outer,
    required this.inner,
    this.logoColour = Colors.white,
    this.background = Colors.black,
  });
}

const double _side = 368;
const double _centre = _side / 2;
const double _outerR = 158;
const double _innerR = 120;
const double _stroke = 26;

/// Render [model] and return JPEG bytes sized for the badge.
Future<Uint8List> renderFaceJpeg(FaceModel model, {int quality = 88}) async {
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder, const Rect.fromLTWH(0, 0, _side, _side));

  // Field.
  canvas.drawRect(
    const Rect.fromLTWH(0, 0, _side, _side),
    Paint()..color = model.background,
  );

  _paintRing(canvas, _outerR, model.outer);
  _paintRing(canvas, _innerR, model.inner);

  await _paintLogo(canvas, model);
  _paintCaption(canvas, model.caption);

  final picture = recorder.endRecording();
  final uiImage = await picture.toImage(kImageWidth, kImageHeight);
  final rgba = await uiImage.toByteData(format: ui.ImageByteFormat.rawRgba);
  uiImage.dispose();

  final decoded = img.Image.fromBytes(
    width: kImageWidth,
    height: kImageHeight,
    bytes: rgba!.buffer,
    numChannels: 4,
    order: img.ChannelOrder.rgba,
  );
  return Uint8List.fromList(img.encodeJpg(decoded, quality: quality));
}

void _paintRing(Canvas canvas, double radius, Ring ring) {
  final rect = Rect.fromCircle(center: const Offset(_centre, _centre), radius: radius);

  // Track behind the arc.
  canvas.drawArc(
    rect,
    0,
    6.28318530718,
    false,
    Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = _stroke
      ..color = ring.colour.withValues(alpha: 0.14),
  );

  // Progress arc, from 12 o'clock, clockwise, rounded cap.
  final frac = ring.fraction.clamp(0.0, 1.0);
  if (frac <= 0) return;
  canvas.drawArc(
    rect,
    -1.5707963267948966, // -90°, top
    6.28318530718 * frac,
    false,
    Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = _stroke
      ..strokeCap = StrokeCap.round
      ..color = ring.colour,
  );
}

Future<void> _paintLogo(Canvas canvas, FaceModel model) async {
  final info = await vg.loadPicture(
    SvgStringLoader(model.logoSvg, theme: SvgTheme(currentColor: model.logoColour)),
    null,
  );
  const box = 96.0;
  final src = info.size;
  final scale = box / (src.width > src.height ? src.width : src.height);

  canvas.save();
  // Sit the mark a touch above centre so the caption has room below.
  canvas.translate(_centre - (src.width * scale) / 2, _centre - (src.height * scale) / 2 - 14);
  canvas.scale(scale);
  // Tint the whole mark, covering SVGs that hard-code a fill instead of
  // currentColor.
  canvas.saveLayer(null, Paint());
  canvas.drawPicture(info.picture);
  canvas.drawRect(
    Rect.fromLTWH(0, 0, src.width, src.height),
    Paint()
      ..colorFilter = ColorFilter.mode(model.logoColour, BlendMode.srcIn),
  );
  canvas.restore();
  canvas.restore();
  info.picture.dispose();
}

void _paintCaption(Canvas canvas, String text) {
  final tp = TextPainter(
    text: TextSpan(
      text: text,
      style: const TextStyle(
        color: Color(0xFF8C9BAB), // factory's default grey
        fontSize: 30,
        fontWeight: FontWeight.w500,
        letterSpacing: 0.3,
      ),
    ),
    textDirection: TextDirection.ltr,
  )..layout();
  tp.paint(canvas, Offset(_centre - tp.width / 2, _centre + 34));
}
