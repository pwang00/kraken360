# Investigation artifacts

See [Investigation.MD](../Investigation.MD) for findings and reproduction commands,
and [README.md](../README.md) for the Rust application's usage.

| Directory | Contents |
| --- | --- |
| `captures/june/` | Original truncated USBPcap capture, `export.pcapng` |
| `captures/windows/` | Complete dashboard capture and earlier capture attempts |
| `captures/manifest.json` | SHA256 hashes and sizes of the retained capture files |
| `samples/q565/` | 10,586-byte encoded logo frame and previously decoded PNG |
| `figures/windows/` | Selected complete CAM frames, contact sheet, and animation |
| `figures/linux/` | Python PoC and Rust layout screenshots |
| `analysis/june/` | Packet summary, transaction log, and RGB prefix previews |
| `analysis/windows/` | Independent verification, frame-change images, and report |
| `analysis/cam/` | Resource findings, focused source evidence, extraction metadata |
| `scripts/` | USB/Python PoC, capture analysis, CAM extraction, Windows capture helper |
| `runtime/` | Git-ignored live PNG, advisory lock, and historical process logs |
| `local/` | Git-ignored originals, proprietary bundles/fonts, repositories, and caches |

The full original Windows sessions are preserved in `local/windows-session/`
and `local/legacy-windows-session/`. Their scripts and notes retain their old
paths and are historical records; use the maintained scripts in `scripts/`.
The original decoder repository and its build cache are in `local/q565-decoder/`.
The complete CAM installation is in `local/cam-installation/`, the standalone
executable in `local/NZXT CAM.exe`, and extracted resources in
`local/cam-resources/`. No original binaries or caches were deleted.

Only the organized documentation, captures, samples, selected figures, scripts,
and small analysis outputs are candidates for version control. `local/`,
`runtime/`, Python bytecode, regenerable raw prefixes, and full re-extracted frame
sets are ignored. Nothing under `artifacts/` is included in the Cargo package.
