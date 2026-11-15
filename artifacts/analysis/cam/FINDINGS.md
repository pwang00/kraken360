# CAM application resources: relevant rendering code recovered

Inspected supplied `artifacts/local/cam-installation/` statically; did not execute the Windows software,
change hardware settings, or replace the existing Linux display renderer.

## Main result

The useful component is
`artifacts/local/cam-installation/resources/app.asar.unpacked/node_modules/@nzxt/cam-core/dist/index.node`,
a native Rust Node addon. It contains readable WGSL shaders, embedded fonts,
LCD renderer paths and pipeline names. This provides substantially stronger
evidence than Vulkan strings in the Electron executable.

The JavaScript application identifies itself as CAM **4.76.9** and depends on
`@nzxt/cam-core` **71.9.4**. The archive contains 22,884 file entries; the extraction
script selects application JS/JSON/CSS/HTML/maps/fonts/SVGs and verifies extracted
SHA256 integrity entries where present. It does not execute archived code.

## Relevant pipeline, with evidence boundaries

```
JS dashboard configuration and selected sensors
    -> native cam-core CoreClient / LcdApi
    -> Rust lcd-rendering graphics (including triple_infographic)
    -> GPU rendering, shaders and font rendering
    -> image conversion/device sending
    -> USB RGB888 frames observed in the capture
```

Direct evidence:

- `renderer.js` defines `forcedGraphicsApi` with default `ForcedGraphicsApi.Vulkan`.
- `170.bundle.js` passes that setting into `new CoreClient(...)`.
  Its parsing helper also defaults to Vulkan.
- LCD rendering calls `this.instance.lcd().renderGraphic(...)`.
- Native source-path strings identify `wgpu-23.0.1`, `naga-23.0.0`,
  `lcd-rendering/src/graphics/triple_infographic.rs`,
  `single_infographic_arc.rs`, and `kraken_rendering/send_to_device.rs`.
- Actual WGSL vertex/fragment source, uniforms, textures, samplers, and rendering
  pipeline labels are embedded in the native module.
- Format strings include RGB888, RGB565 and Q565 variants.

The specific running Windows process's selected graphics backend was not traced.
Vulkan is the configured default in this build, not merely a generic Electron
capability, but an override/fallback remains possible. Static evidence plus the
PCAP supports the overall pipeline; it is not a call-by-call execution trace.
The top-level `vulkan-1.dll`, `vk_swiftshader.dll`, `libEGL.dll` and `libGLESv2.dll`
by themselves are less specific evidence than the native renderer and its JS
configuration.

## Dashboard configuration recovered

`fromTripleInfographicsGraphic` in `170.bundle.js` constructs:

- three reading configurations (`reading1`, `reading2`, `reading3`), each with
  monitoring key, reading color/outline, label color/outline and translated label;
- Celsius/Fahrenheit selection and CPU temperature display selection;
- selected GPU ID and the Kraken supplying liquid temperature;
- optional logo configuration;
- background color and gradient stops from `ringGradient`;
- `inactiveArcOpacity = 0.05` for Kraken Elite / Elite V2, 1 for other models;
- `GraphicTypeDiscriminant.TripleInfographic`, or a GIF variant with a media path.

These settings are passed to a renderer, rather than selecting a single fixed
raster dashboard file. See `evidence.json` for bounded source excerpts and offsets.
This does not exclude cached textures or raster elements within the renderer.

## Useful recovered shaders

Fourteen WGSL sources are saved in `shaders/`. Most relevant:

- `infographic_radial_gauge.wgsl`: takes `reading_normalized` and
  `inactive_arc_opacity`, derives angular position, samples a one-dimensional
  gradient, and lowers alpha past the reading. Its normalized angular range has
  a 90-degree lower gap (270-degree sweep), matching the captured open arc.
- `infographic_radial_gauge_indicator.wgsl`: samples the same gradient at
  `reading_normalized` for the indicator's color. Indicator geometry/position is
  supplied outside this shader.
- `glyphon-text.wgsl`: glyph atlas text rendering.
- `overlay_texture.wgsl`: compositing an image/texture with a color filter.
- `dual_infographic.wgsl`: a simple vertex-color shader, illustrating that shader
  source alone does not contain all layout logic.

Also recovered clockface, square/full-fill infographic, audio visualizer,
image-rotation and solid-color shaders. Source boundaries were identified from
embedded readable runs and adjacent filenames, with brace-balance checks. These
files have **not** been compiler-validated or executed; the extraction report
records exact native file offsets and hashes.

## Fonts

Recovered embedded OpenType files parsed successfully with FreeType:

- `embedded-fonts/Gotham-Bold-01e0ebe6.otf`
- `embedded-fonts/Gotham_Light-Regular-01e16148.otf`
- a second embedded Gotham Bold blob at offset `0x1f2cda0`.

The archive also has Gotham SSm Bold WOFF, Akkurat fonts and an NZXT icon font.
The native embedded Gotham fonts are a particularly useful lead for matching
LCD text. Exact font size, placement, rasterizer settings and the full digit
appearance have not yet been matched to the captured dashboard.

## What remains to recreate accurately

The shader controls arc color/opacity, while compiled Rust still supplies layout,
geometry, numeric normalization, font sizing and possibly smoothing. Those
parameters are not all present as readable source. Combining recovered fonts
and arc formulas with the full RGB captures is a practical route to an accurate
Linux recreation; we do not need CAM's complete graphics stack to send the final
pixels to the device. The current live Python renderer was not changed here.

## Reproduce

From the project root:

```
/usr/bin/python3 artifacts/scripts/extract_cam_resources.py
```

Outputs stay under `artifacts/local/cam-resources/`. `extraction-report.json` records
archive counts, shader offsets/hashes, native module hash, and parsed fonts.
`evidence.json` contains the focused JS excerpts and native path evidence gathered
in this investigation. Extracted application assets remain local.
