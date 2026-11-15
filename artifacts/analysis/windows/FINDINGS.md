# Independent verification of the Windows capture and CAM executable

## Complete frames confirm the transport

Validated `artifacts/local/windows-session/inspection/cam-frames.pcapng` with the existing local
USBPcap parser: 396 records, no truncated packets, 15 complete 1,228,800-byte
outbound RGB frames. Every frame is byte-for-byte identical to both its supplied
`.bin` and the RGB pixels of its supplied `.png`.

The frame headers are all:

```
12 fa 01 e8 ab cd ef 98 76 54 32 10 09 00 00 00 00 c0 12 00
```

Frame submission intervals are 0.9980–1.0029 seconds. This confirms complete
RGB888 frames at approximately 1 Hz for this CAM configuration, with exactly
the mode/header already used by our Linux uploader. It does not measure maximum
supported update rate or establish how other CAM screens are encoded.

## What the frame comparison reveals

There are 11 distinct complete rasters among 15 uploads. Across all samples,
12,148 of 409,600 pixel locations change at all (2.97%). Some changes are subtle
antialiasing/color differences around the arc and large text. The substantial
changes appear in the CPU/GPU digits and the arc endpoint/dot.

- Large CPU digit crop: three distinct rasters (visually 56, 59, 58).
- Small GPU digit crop: two distinct rasters (visually 33, 32).
- Liquid digit crop: one raster, showing 32 throughout.
- NZXT label, CPU/GPU/Liquid labels, and divider crops: exactly invariant.

This is consistent with a layout assembled from static and dynamic elements.
It cannot distinguish cached bitmaps from vector geometry, browser rendering,
or shaders. Identical pixels can result from redrawing the same objects.
The unchanged liquid reading is not evidence that liquid digits are static UI.

Generated artifacts:

- `changes-overlay.png`: strongly changing pixels (>8 channel-value range)
  highlighted in pink over a dimmed first frame.
- `changed-pixels.png`: all pixels that changed, including tiny differences.
- `invariant-pixels.png`: first-frame pixels with changing locations blacked out.
  This is an analytical mask, **not a reusable complete dashboard template**:
  unchanging digits from this short capture remain present.
- `captured-nzxt-label.png`: exact crop of the dashboard wordmark.
- `report.json`: hashes, packet/frame timings, region counts, PE sections and
  asset/string evidence with executable offsets.

## Executable findings (static analysis only)

`artifacts/local/NZXT CAM.exe` is a 64-bit PE with 15 sections. It contains:

- `Electron v32.1.0` at file offset `0x954b112`.
- `app.asar` references, including Electron's application loader code.
- `vulkan-1.dll` at `0x97966ac`, and three `vkCreateInstance` strings.
- No exact ASCII `Kraken`, `kraken`, `Q565`, or `q565` strings.
- One complete CRC-validated embedded PNG, 256×256, at `0xb0cc564`, 5,442 bytes.
  This independently matches the image already found by the Windows session.
- No plausible standalone little-endian SPIR-V headers found by a magic/header
  scan (version 1.0–1.6, sane ID bound, reserved word zero).

The Vulkan evidence establishes bundled support, not active Vulkan use and not
its connection to the Kraken renderer. No valid dashboard-sized embedded PNG
was recovered. This scan does not rule out compressed/packed assets, other image
formats, runtime-compiled shaders, native helper code, or external resources.
The executable was never run.

## Best next target

Inspect the CAM installation's `resources/app.asar`, `app.asar.unpacked`, other
resource bundles, native `.node`/DLL modules, and any Kraken/device helper
executables. The Electron runtime strings make application resources a better
next lead than trying to identify the dashboard from generic Vulkan strings.
Only the executable and the supplied capture/extraction directory are present
here; the application resource archive is not among the supplied files.

An application bundle may expose the actual layout, fonts, gradient stops,
temperature ranges and smoothing, or the code that delegates rendering to a
native helper. This would be more useful for an accurate recreation than
recovering a single shader without its inputs and layout.

For a further controlled capture: hold the layout fixed and change the arc
color or primary CPU/GPU selection, then compare the resulting complete frames.
This separates configurable drawing parameters from the static wordmark and
text styling without requiring knowledge of CAM's rendering backend.

## Reproduce

From the project root, using the already installed system Python dependencies:

```
/usr/bin/python3 artifacts/scripts/investigate_windows.py
```

Reads only the supplied files and writes analysis artifacts under
`artifacts/analysis/windows/`. No hardware access or system changes.
