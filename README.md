# Kraken Elite V2 USB investigation

The Rust library and CLI are now available at the project root. See [Rust build and usage instructions](RUST.md). Run `cargo run --release -- run` for the live display.

Device visible on this host: NZXT Kraken Elite V2, VID:PID **1e71:3012**,
USB path `1-10.4`, USB 2 high speed (480 Mb/s). The capture device descriptor
matches that identity and reports bcdDevice 0x0102 (not necessarily the complete firmware version).

## Findings from export.pcapng

274 USBPcap records spanning 10.193198 seconds, ten LCD updates at approximately
one update per second. All captured completions report success.

The configuration has two interfaces:

| Interface | Type | Endpoints |
| --- | --- | --- |
| 0 | vendor-specific | bulk OUT 0x02, max packet 512 |
| 1 | HID | interrupt OUT 0x01 and IN 0x81, max packet 512 |

Each LCD update follows this sequence (interrupt commands are padded to 512 bytes):

1. Interrupt OUT: `36 01 00 01 09`, followed by IN `37 01 ...`.
2. Bulk OUT: 20-byte header `12 fa 01 e8 ab cd ef 98 76 54 32 10 09 00 00 00 00 c0 12 00`.
3. Bulk OUT: 1,228,800 bytes of image data.
4. Interrupt OUT: `36 02`, followed by IN `37 02 ...`.

The header's last four bytes encode 1,228,800 as little-endian uint32.
This is exactly **640 × 640 × 3**. Decoding the retained bytes as RGB888 shows
a smooth pink arc against black. Thus this capture strongly supports raw RGB888
mode 0x09, rather than Q565. Channel order and orientation still require a live
color-pattern check. There are no mode 0x08 uploads in this capture, so it cannot
establish a Q565 codec or its framing.

The actual image bulk transfers take 59.41–59.85 ms, approximately 20.6 MB/s.
That suggests a transport-only upper bound around 16.7 full frames/s; the capture
only demonstrates CAM uploading at 1 Hz, not a tested display frame-rate limit.

**Capture truncation:** each image URB declares 1,228,800 payload bytes but only
65,508 payload bytes were saved (65,535-byte snaplen minus 27-byte USBPcap header).
Only 5.33% of each frame survives: 34 complete RGB rows plus 228 bytes.
These missing bytes are absent from the file, not deferred to later packets.
`artifacts/*.rgb-prefix.png` shows only captured complete rows; it does not fill
missing image data. Several prefixes repeat, but full-frame equality is unknown.

Other traffic:

- `72 02 01 01` and `72 01 01 00`, followed by 41 bytes of `64`, repeat at 1 Hz.
  These resemble fan and pump curves with every duty set to 100%; interpretation
  is supported by the installed liquidctl channel mapping, not isolated testing.
- `26 14 01 01` followed by repeated RGB triplets looks like lighting updates.
- Unsolicited `75 02` reports arrive at 1 Hz; `ff 01` reports acknowledge other
  commands by echoing their first two bytes at offsets 14–15.
- LCD `37 01` and `37 02` replies have byte 14 equal to 1 in this capture.

## Tools

Reproduce extraction (Pillow is optional for parsing, required for previews):

```sh
python3 scripts/analyze_capture.py export.pcapng
```

Results: `artifacts/summary.json`, `transactions.jsonl`, ten partial binary
payloads, and ten RGB prefix previews. The parser targets little-endian USBPcap
pcapng with microsecond timestamps, as used by this file; it is not a general
capture library.

The experimental uploader mirrors the observed display sequence and does not
replay fan, pump, or lighting commands:

```sh
/usr/bin/python3 scripts/kraken_usb.py
/usr/bin/python3 scripts/kraken_usb.py --status
/usr/bin/python3 scripts/kraken_usb.py --test-pattern --dry-run artifacts/test-pattern.rgb
/usr/bin/python3 scripts/kraken_usb.py --test-pattern
/usr/bin/python3 scripts/kraken_usb.py --image picture.png
```

Ubuntu's system Python here already has PyUSB and Pillow. Elsewhere install
`python3-usb python3-pil libusb-1.0-0`. The host must expose `/dev/bus/usb` and
grant access to this device (e.g. liquidctl's udev rules). The script temporarily
claims the necessary interfaces and restores detached kernel drivers afterward.
It checks write lengths and captured LCD acknowledgement patterns. It is a
single-frame experiment, not a complete cooler-control daemon.

## Validation and limitation

The parser extracted all 274 records and ten truncated frames, agreeing with
`capinfos`. The dry-run generated exactly 1,228,800 bytes and a header identical
to CAM's. A live test was attempted, but libusb cannot initialize in this session:
`/dev/bus/usb` and `/dev/hidraw*` are unavailable despite sysfs device visibility.
**No commands reached the physical cooler; live uploader behavior is unverified.**

For a new Windows capture, set USBPcap/Wireshark capture length to at least
2 MiB (or unlimited), then verify caplen equals original length for image URBs.
Capture known red/green/blue frames and, separately, any Q565 mode upload to
resolve channel order and compression. On Linux usbmon, likewise check for
truncation rather than assuming a large snaplen alone preserves the full URB.

## Existing Linux work

The installed liquidctl already lists this VID:PID with a 640×640 screen.
Its `_send_2023_data_fw2` uses the same bulk magic, but starts transfers in mode
0x06, whereas every CAM upload here uses 0x09. Model recognition alone does not
prove this particular LCD path works.

Primary sources checked:
- https://github.com/liquidctl/liquidctl/blob/main/liquidctl/driver/kraken3.py
- https://github.com/liquidctl/liquidctl/issues/745
- https://github.com/liquidctl/liquidctl/blob/main/extra/linux/71-liquidctl.rules

## Follow-up: Q565 versus USB packet boundaries

Q565 support and this RGB capture are compatible: AIOLCDUnchained's `driver.py`
explicitly includes PID 0x3012 in its Q565 device list. Its `writeQ565` starts
with `36 01 00 01 08`, uses 0x08 at bulk-header offset 12, then sends a
length-delimited encoded frame and finishes with `36 02`. This is the same
framing pattern observed here, with a different format selector (0x09 here).
Source: https://github.com/brokenmass/AIOLCDUnchained/blob/main/driver.py

Distinguish three boundaries: a screen frame, host USB transfers/URBs, and the
individual USB bus packets making up each transfer. Large images certainly span
many bus packets, and software can also split a frame across multiple writes.
This particular file records whole host transfer requests, not individual bus
packets: every image request declares 1,228,800 bytes, but its capture record
retains only 65,508. Its completion contains no remaining image payload, and the
next bulk submission is the next frame's 20-byte header. Joining these recorded
prefixes therefore would join different frames, not restore missing data.
A scan of all captured bytes found no ASCII `q565` magic; absence by itself is
not decisive, but is consistent with the mode and RGB preview evidence.

The user's decoder repository is now available locally in `rust-q565-decoder/`.
Its `data/frame.q565` is a **10,586-byte** Q565 file: magic `q565`, followed by
little-endian width/height 640×640. Its `out.png` is a 640×640 RGB image showing
a white rounded diamond/ring logo shape on black (non-black bounds
x=228..411, y=228..411). Neither the file nor its 8-byte header appears in the
current capture. This establishes an earlier Q565 sample alongside the RGB
uploads observed here, rather than contradicting either finding.

The sample is about **116× smaller** than raw 640×640 RGB888. This ratio is
specific to this mostly black logo; it does not predict animation frame rates.
The Rust decoder calls `Q565DecodeContext::decode::<LittleEndian>` with RGB888
output, then creates a PNG with the decoded dimensions. An offline Cargo run
could not reproduce the PNG because the `q565` dependency is not cached.
The existing PNG was inspected, not freshly generated. One CLI caveat: `main.rs`
silently returns success if `decode_frame` returns an error, since it uses
`if let Ok(...)` without an error branch.

The experimental uploader now accepts a pre-encoded Q565 frame:

```sh
/usr/bin/python3 scripts/kraken_usb.py --q565 rust-q565-decoder/data/frame.q565 --dry-run artifacts/q565-upload.bin
/usr/bin/python3 scripts/kraken_usb.py --q565 rust-q565-decoder/data/frame.q565
```

The dry run preserves the sample byte-for-byte and produces this bulk header:
`12 fa 01 e8 ab cd ef 98 76 54 32 10 08 00 00 00 5a 29 00 00`.
It uses mode 0x08 in both the start command and bulk header. Input validation
checks magic and dimensions; it does not decode or fully validate the compressed
stream. Hardware behavior is still unverified because USB access is unavailable.

## Hardware confirmation

The user ran `/usr/bin/python3 scripts/kraken_usb.py --test-pattern` on the host
and confirmed it transfers and renders correctly. This validates the raw RGB888
mode 0x09 uploader on this device. Q565 mode 0x08 remains untested. Direct
agent access is still blocked by unavailable device nodes in the sandbox.

## Live temperature display

`scripts/kraken_dashboard.py` renders a Windows CAM-like layout with a large
GPU temperature, CPU and liquid temperatures beside it, and cyan/purple arcs.
It uses the already verified raw RGB888 upload path, once per second by default.
All generated files and logs stay under this project's `artifacts/` directory.
No installation, startup service, cooling profile, or RGB lighting changes.

Sources on this machine:

- CPU: AMD `k10temp` **Tctl**, read from hwmon (automatically discovers its path).
- GPU: **NVIDIA GeForce RTX 5070 Ti**, `nvidia-smi` temperature.gpu, GPU index 0.
  This deliberately selects the discrete NVIDIA card, rather than the AMD iGPU.
- Liquid: spontaneous Kraken USB `75 02` reports; byte 15 + byte 16 / 10 °C.
  The same temperature byte interpretation appears in liquidctl's Kraken driver.

Temperature values are rounded to whole °C on screen; logs retain precision.
Windows CAM may choose a different CPU sensor or averaging window, so exact CPU
numbers can differ. The arcs are decorative LCD graphics, not physical ring LED
control or temperature gauges. GPU/CPU read failures display `--` and are logged;
missing/stale liquid reports also display `--`. USB errors stop the program.

```sh
# Read live CPU/GPU sensors and generate a preview without touching USB:
/usr/bin/python3 scripts/kraken_dashboard.py --preview

# Run until Ctrl+C (no root needed on the tested host):
/usr/bin/python3 scripts/kraken_dashboard.py

# Finite hardware test:
/usr/bin/python3 scripts/kraken_dashboard.py --frames 5

# Optional sensor selections:
/usr/bin/python3 scripts/kraken_dashboard.py --gpu-index 0 --interval 1
```

Do not run the single-frame uploader, liquidctl LCD commands, or another LCD
controller at the same time. An advisory project lock prevents two instances
of this dashboard; it cannot coordinate unrelated USB clients. Exiting restores
kernel drivers detached by the process and leaves the final image on the LCD.
After exiting, displayed values stop updating.

Validation: a five-update live test completed with every LCD acknowledgement
accepted, reporting approximately CPU 51°C, GPU 38°C, and liquid 33.5–33.7°C.
The generated preview was visually inspected. Checks also exercised missing CPU
and timed-out GPU inputs, plus coolant report decoding. The image on the physical
LCD has not been visually confirmed by the agent.

A background instance started for this session writes `artifacts/dashboard.log`
and its PID to `artifacts/dashboard.pid`. Stop it before running another instance:

```sh
kill "$(cat artifacts/dashboard.pid)"
```

It is not configured to start at login or boot. The latest uploaded frame is
saved as `artifacts/dashboard-preview.png`.

## New complete Windows capture and executable

An independent analysis of `windows_capture/inspection/cam-frames.pcapng` confirms
15 complete RGB888 frames with the existing mode 0x09 framing, about 1 Hz, and no
truncation. Every supplied frame binary and PNG was verified against its packet
payload. Static analysis of `NZXT CAM.exe` confirms Electron runtime and Vulkan
support strings, but does not establish the LCD rendering backend or recover a
complete dashboard template. See [the detailed findings](artifacts/windows-analysis/FINDINGS.md)
and [the change overlay](artifacts/windows-analysis/changes-overlay.png).
Reproduce with `/usr/bin/python3 scripts/investigate_windows.py`.

## CAM resource bundle investigation

The new `all_files/` directory supplies the missing application archive and
native core. The native `cam-core/dist/index.node` contains readable WGSL shaders,
Gotham fonts and Rust LCD renderer paths. CAM's JS configuration defaults the
native graphics API to Vulkan. Recovered the triple-reading configuration,
5% inactive arc opacity on Elite models, and the actual radial-gauge shader.
See [resource findings](artifacts/cam-resources/FINDINGS.md) and
[extraction metadata](artifacts/cam-resources/extraction-report.json).
Reproduce extraction with `/usr/bin/python3 scripts/extract_cam_resources.py`.
The existing live dashboard code has not been changed by this investigation.

The Rust dashboard is now installed as `~/.local/bin/kraken360` with an enabled
user systemd service. It runs now and starts at sign-in. See
[service management instructions](RUST.md#installed-user-service).
