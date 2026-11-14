use crate::{
    Temperatures,
    protocol::{HEIGHT, WIDTH},
};
use anyhow::{Context, Result};
use fontdue::{Font, FontSettings};
use image::{Rgb, RgbImage};
use std::{f32::consts::PI, fs, path::Path};

#[derive(Clone, Copy, Debug, Default)]
pub enum Primary {
    Cpu,
    #[default]
    Gpu,
}

/// CPU rasterizer. CAM assets/shaders are not needed or embedded.
pub struct DashboardRenderer {
    font: Font,
    pub primary: Primary,
}
impl DashboardRenderer {
    pub fn new(font: &Path, primary: Primary) -> Result<Self> {
        let bytes = fs::read(font).with_context(|| format!("Read font {}", font.display()))?;
        let font = Font::from_bytes(bytes, FontSettings::default())
            .map_err(|e| anyhow::anyhow!("Parse font: {e}"))?;
        Ok(Self { font, primary })
    }
    fn text(&self, image: &mut RgbImage, text: &str, size: f32, cx: f32, cy: f32) {
        let mut glyphs = vec![];
        let (mut advance, mut previous) = (0., None);
        let (mut top, mut bottom) = (i32::MAX, i32::MIN);
        for ch in text.chars() {
            if let Some(prev) = previous {
                advance += self.font.horizontal_kern(prev, ch, size).unwrap_or(0.);
            }
            let (m, alpha) = self.font.rasterize(ch, size);
            let y = -m.ymin - m.height as i32;
            top = top.min(y);
            bottom = bottom.max(y + m.height as i32);
            let step = m.advance_width;
            glyphs.push((advance + m.xmin as f32, y, m, alpha));
            advance += step;
            previous = Some(ch);
        }
        let left = cx - advance / 2.;
        let baseline = cy - (top + bottom) as f32 / 2.;
        for (x, y, metrics, alpha) in glyphs {
            for row in 0..metrics.height {
                for col in 0..metrics.width {
                    let px = (left + x).round() as i32 + col as i32;
                    let py = (baseline + y as f32).round() as i32 + row as i32;
                    if px < 0 || py < 0 || px >= WIDTH as i32 || py >= HEIGHT as i32 {
                        continue;
                    }
                    let a = alpha[row * metrics.width + col] as f32 / 255.;
                    let old = image.get_pixel(px as u32, py as u32).0;
                    image.put_pixel(
                        px as u32,
                        py as u32,
                        Rgb(old.map(|c| (c as f32 * (1. - a) + 255. * a).round() as u8)),
                    );
                }
            }
        }
    }
    pub fn render(&self, t: Temperatures) -> RgbImage {
        let (main, secondary, main_label, secondary_label) = match self.primary {
            Primary::Cpu => (t.cpu, t.gpu, "CPU", "GPU"),
            Primary::Gpu => (t.gpu, t.cpu, "GPU", "CPU"),
        };
        let reading = main
            .filter(|v| v.is_finite())
            .map(|v| (v / 100.).clamp(0., 1.));
        let mut image = RgbImage::new(WIDTH, HEIGHT);
        let start = 135_f32.to_radians();
        let sweep = 270_f32.to_radians();
        let radius = 301.;
        let dot = reading.map(|p| {
            let a = start + p * sweep;
            (320. + radius * a.cos(), 320. + radius * a.sin())
        });
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let dx = x as f32 + 0.5 - 320.;
                let dy = y as f32 + 0.5 - 320.;
                let progress = (dy.atan2(dx) - start).rem_euclid(2. * PI) / sweep;
                let distance = (dx * dx + dy * dy).sqrt();
                let mut coverage = if progress <= 1. {
                    (6.5 - (distance - radius).abs()).clamp(0., 1.)
                } else {
                    0.
                };
                // Similar to CAM's gauge: an active gradient and dim remaining arc.
                let color_progress = progress.clamp(0., 1.);
                let mut color = gradient(color_progress);
                let opacity = if reading.is_some_and(|p| progress <= p) {
                    1.
                } else {
                    0.22
                };
                for c in &mut color {
                    *c *= opacity;
                }
                if let Some((dot_x, dot_y)) = dot {
                    let d = ((x as f32 + 0.5 - dot_x).powi(2) + (y as f32 + 0.5 - dot_y).powi(2))
                        .sqrt();
                    let dot_alpha = (18.5 - d).clamp(0., 1.);
                    if dot_alpha > 0. {
                        color = gradient(reading.unwrap_or(0.));
                        coverage = coverage.max(dot_alpha);
                    }
                }
                image.put_pixel(x, y, Rgb(color.map(|c| (c * coverage).round() as u8)));
            }
        }
        let number = |v: Option<f32>| {
            v.filter(|v| v.is_finite())
                .map(|v| format!("{v:.0}"))
                .unwrap_or("--".into())
        };
        self.text(&mut image, "NZXT", 44., 320., 148.);
        self.text(&mut image, &number(main), 180., 233., 310.);
        self.text(&mut image, "°", 49., 372., 254.);
        self.text(&mut image, main_label, 33., 233., 426.);
        for y in 240..433 {
            image.put_pixel(409, y, Rgb([100; 3]));
            image.put_pixel(410, y, Rgb([100; 3]));
        }
        self.text(
            &mut image,
            &format!("{}°", number(secondary)),
            64.,
            490.,
            270.,
        );
        self.text(&mut image, secondary_label, 23., 480., 313.);
        self.text(
            &mut image,
            &format!("{}°", number(t.liquid)),
            64.,
            490.,
            383.,
        );
        self.text(&mut image, "Liquid", 23., 480., 427.);
        image
    }
}
fn gradient(t: f32) -> [f32; 3] {
    let stops = [[255., 185., 0.], [255., 127., 183.], [120., 0., 150.]];
    let (a, b, u) = if t < 0.6 {
        (stops[0], stops[1], t / 0.6)
    } else {
        (stops[1], stops[2], (t - 0.6) / 0.4)
    };
    std::array::from_fn(|i| a[i] + (b[i] - a[i]) * u)
}
