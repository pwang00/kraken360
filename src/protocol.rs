use anyhow::{Result, bail, ensure};
use std::time::{Duration, Instant};

pub const WIDTH: u32 = 640;
pub const HEIGHT: u32 = 640;
pub const RGB_LENGTH: usize = 640 * 640 * 3;
pub const MAGIC: [u8; 12] = [
    0x12, 0xfa, 1, 0xe8, 0xab, 0xcd, 0xef, 0x98, 0x76, 0x54, 0x32, 0x10,
];

#[derive(Clone, Copy, Debug)]
pub enum Format {
    Rgb888,
    Q565,
}

impl Format {
    pub fn selector(self) -> u8 {
        match self {
            Self::Rgb888 => 9,
            Self::Q565 => 8,
        }
    }
    pub fn validate(self, data: &[u8]) -> Result<()> {
        match self {
            Self::Rgb888 => ensure!(
                data.len() == RGB_LENGTH,
                "RGB frame must contain {RGB_LENGTH} bytes"
            ),
            Self::Q565 => {
                ensure!(
                    data.len() >= 8 && &data[..4] == b"q565",
                    "Q565 header missing"
                );
                ensure!(
                    u16::from_le_bytes([data[4], data[5]]) == 640
                        && u16::from_le_bytes([data[6], data[7]]) == 640,
                    "Q565 dimensions must be 640x640"
                );
            }
        }
        ensure!(u32::try_from(data.len()).is_ok(), "Frame too large");
        Ok(())
    }
}

pub fn header(format: Format, length: u32) -> [u8; 20] {
    let mut out = [0; 20];
    out[..12].copy_from_slice(&MAGIC);
    out[12] = format.selector();
    out[16..].copy_from_slice(&length.to_le_bytes());
    out
}

pub fn coolant_report(report: &[u8]) -> Option<f32> {
    if report.len() < 17
        || !matches!(&report[..2], [0x75, 1] | [0x75, 2])
        || report[16] > 9
        || report[15] >= 100
    {
        return None;
    }
    Some(report[15] as f32 + report[16] as f32 / 10.)
}

/// USB transfer boundary abstraction, also usable for recorded/mock transports.
pub trait Transport {
    fn write(&mut self, endpoint: u8, data: &[u8]) -> Result<usize>;
    /// Empty report means a bounded read timeout, not device disconnection.
    fn read(&mut self, timeout: Duration) -> Result<Vec<u8>>;
}

pub struct Lcd<T: Transport> {
    transport: T,
    liquid: Option<(Instant, f32)>,
}

impl<T: Transport> Lcd<T> {
    pub fn new(transport: T) -> Self {
        Self {
            transport,
            liquid: None,
        }
    }

    fn read(&mut self, timeout: Duration) -> Result<Vec<u8>> {
        let report = self.transport.read(timeout)?;
        if let Some(value) = coolant_report(&report) {
            self.liquid = Some((Instant::now(), value));
        }
        Ok(report)
    }

    fn write(&mut self, endpoint: u8, data: &[u8]) -> Result<()> {
        ensure!(
            self.transport.write(endpoint, data)? == data.len(),
            "Short USB write on endpoint {endpoint:#x}"
        );
        Ok(())
    }

    fn command(&mut self, bytes: &[u8], expected: [u8; 2]) -> Result<()> {
        let mut padded = [0; 512];
        padded[..bytes.len()].copy_from_slice(bytes);
        self.write(1, &padded)?;
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            let report = self.read(Duration::from_millis(250))?;
            if report.starts_with(&expected) {
                ensure!(
                    report.get(14) == Some(&1),
                    "LCD rejected command {bytes:02x?}"
                );
                return Ok(());
            }
        }
        bail!("Timed out waiting for LCD acknowledgement {expected:02x?}")
    }

    pub fn display(&mut self, data: &[u8], format: Format) -> Result<()> {
        format.validate(data)?;
        self.command(&[0x36, 1, 0, 1, format.selector()], [0x37, 1])?;
        self.write(2, &header(format, data.len() as u32))?;
        self.write(2, data)?;
        self.command(&[0x36, 2], [0x37, 2])
    }
    
    /// Listen to unsolicited status reports, without changing device settings.
    pub fn coolant(&mut self) -> Result<Option<f32>> {
        let deadline = Instant::now() + Duration::from_millis(1200);
        while Instant::now() < deadline {
            self.read(Duration::from_millis(250))?;
            if let Some((when, value)) = self.liquid
                && when.elapsed() < Duration::from_secs(2)
            {
                return Ok(Some(value));
            }
        }
        Ok(None)
    }
}
