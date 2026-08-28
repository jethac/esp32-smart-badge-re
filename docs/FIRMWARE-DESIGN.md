# Minimal replacement firmware design

This is a design for a deliberately narrow badge application: a phone supplies provider usage state; the badge renders it locally. It is not a claim that the referenced image boots on every E87-labeled unit.

## Display and face

The target assumption is a JD9855 DBI display at 360 x 360 pixels in RGB565. Render in twelve 360 x 30 pixel strips, using an application buffer of `0x5460` bytes and a two-buffer display descriptor.

The first face is Devin: a centered logo, on-demand credit (initially `$17.27`), a light-gray day outer ring, a white week inner ring, and small day/week Material-style indicators at ring starts. Local rendering avoids sending bitmaps over BLE.

## State packet v1

```
01 DD WW 00 BF 06 00 00
```

`01` is the protocol version; `DD` and `WW` are day/week percentages in 0..100; `00 BF 06` is the little-endian 1,727-cent credit amount; remaining bytes are reserved.

## Buttons and power

- Button 1 tap: show a large battery percentage.
- Button 1 hold: pairing at 3 seconds, warning at 7, maintenance/recovery at 10.
- Button 2: manual sleep.

Normal state is RAM-only. Charge-through display is a desired behavior, not hardware-verified.

## BLE behavior

Normal mode should advertise a small encrypted GATT service, build information, and the standard Battery Service. The phone owns account/API access and sends values; the badge owns drawing, animation, sleep, and stale-data presentation.
