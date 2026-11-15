use crate::protocol::Transport;
use anyhow::{Context, Result, bail};
use rusb::{DeviceHandle, GlobalContext};
use std::time::Duration;

/// Owns claims and restores any kernel drivers detached during open, even on error.
pub struct UsbTransport {
    handle: DeviceHandle<GlobalContext>,
    claimed: Vec<u8>,
    detached: Vec<u8>,
}
impl UsbTransport {
    pub fn open() -> Result<Self> {
        let mut found = None;
        for dev in rusb::devices()?.iter() {
            let desc = dev.device_descriptor()?;
            if desc.vendor_id() == 0x1e71 && desc.product_id() == 0x3012 {
                if found.is_some() {
                    bail!("Multiple Kraken Elite V2 devices found; connect only one");
                }
                found = Some(dev);
            }
        }
        let dev = found.context("Kraken Elite V2 (1e71:3012) not found")?;
        let mut this = Self {
            handle: dev
                .open()
                .context("Opening Kraken: check USB/udev permissions")?,
            claimed: vec![],
            detached: vec![],
        };
        for interface in [0, 1] {
            if this.handle.kernel_driver_active(interface)? {
                this.handle.detach_kernel_driver(interface)?;
                this.detached.push(interface);
            }
            this.handle.claim_interface(interface).with_context(|| {
                format!("Claim interface {interface}; close other LCD controllers")
            })?;
            this.claimed.push(interface);
        }
        Ok(this)
    }
}
impl Transport for UsbTransport {
    fn write(&mut self, endpoint: u8, data: &[u8]) -> Result<usize> {
        let timeout = Duration::from_secs(5);
        Ok(if endpoint == 2 {
            self.handle.write_bulk(endpoint, data, timeout)?
        } else {
            self.handle.write_interrupt(endpoint, data, timeout)?
        })
    }

    fn read(&mut self, timeout: Duration) -> Result<Vec<u8>> {
        let mut report = vec![0; 512];
        match self.handle.read_interrupt(0x81, &mut report, timeout) {
            Ok(n) => {
                report.truncate(n);
                Ok(report)
            }
            Err(rusb::Error::Timeout) => Ok(vec![]),
            Err(e) => Err(e.into()),
        }
    }
}
impl Drop for UsbTransport {
    fn drop(&mut self) {
        for &i in self.claimed.iter().rev() {
            if let Err(e) = self.handle.release_interface(i) {
                eprintln!("Release interface {i}: {e}");
            }
        }
        for &i in &self.detached {
            if let Err(e) = self.handle.attach_kernel_driver(i) {
                eprintln!("Restore interface {i}: {e}");
            }
        }
    }
}
