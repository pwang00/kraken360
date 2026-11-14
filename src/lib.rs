//! Sensor acquisition, CPU rendering, and USB LCD transport for Kraken Elite V2.
//! No fan, pump, lighting, firmware, or persistent configuration commands are sent.
pub mod protocol;
pub mod render;
pub mod sensors;
pub mod usb;

/// A missing reading is rendered as `--`, never as a previous or invented value.
#[derive(Clone, Copy, Debug, Default)]
pub struct Temperatures {
    pub cpu: Option<f32>,
    pub gpu: Option<f32>,
    pub liquid: Option<f32>,
}
