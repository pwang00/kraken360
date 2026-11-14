use crate::Temperatures;
use anyhow::{Context, Result, bail};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::Duration,
};
use wait_timeout::ChildExt;

pub fn cpu_sensor(root: &Path) -> Result<PathBuf> {
    let mut devices = fs::read_dir(root)?
        .filter_map(|p| p.ok().map(|p| p.path()))
        .collect::<Vec<_>>();
    devices.sort();
    for (driver, label) in [("k10temp", "Tctl"), ("coretemp", "Package id 0")] {
        for dev in &devices {
            if fs::read_to_string(dev.join("name"))
                .unwrap_or_default()
                .trim()
                != driver
            {
                continue;
            }
            for entry in fs::read_dir(dev)? {
                let path = entry?.path();
                let name = path.file_name().unwrap_or_default().to_string_lossy();
                if name.starts_with("temp")
                    && name.ends_with("_label")
                    && fs::read_to_string(&path).unwrap_or_default().trim() == label
                {
                    return Ok(path.with_file_name(name.replace("_label", "_input")));
                }
            }
        }
    }
    bail!("No CPU package sensor found; supply --cpu-sensor")
}

fn valid(value: f32) -> Result<f32> {
    if value.is_finite() && (-20. ..=150.).contains(&value) {
        Ok(value)
    } else {
        bail!("Invalid temperature {value}")
    }
}

pub fn read_cpu(path: &Path) -> Result<f32> {
    valid(fs::read_to_string(path)?.trim().parse::<f32>()? / 1000.)
}

pub fn read_gpu(index: u32) -> Result<f32> {
    let mut child = Command::new("nvidia-smi")
        .args([
            format!("--id={index}"),
            "--query-gpu=temperature.gpu".into(),
            "--format=csv,noheader,nounits".into(),
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("Run nvidia-smi")?;
    let status = match child.wait_timeout(Duration::from_secs(3)) {
        Ok(Some(status)) => status,
        result => {
            let _ = child.kill();
            let _ = child.wait();
            match result {
                Err(e) => return Err(e.into()),
                _ => bail!("nvidia-smi timed out"),
            }
        }
    };
    if !status.success() {
        bail!("nvidia-smi exited with {status}");
    }
    let mut output = String::new();
    child
        .stdout
        .take()
        .context("GPU output unavailable")?
        .read_to_string(&mut output)?;
    valid(output.trim().parse()?)
}

pub fn sample(cpu: &Path, gpu: u32) -> Temperatures {
    let read = |kind: &str, result: Result<f32>| match result {
        Ok(value) => Some(value),
        Err(e) => {
            eprintln!("{kind}: {e:#}");
            None
        }
    };
    Temperatures {
        cpu: read("CPU", read_cpu(cpu)),
        gpu: read("GPU", read_gpu(gpu)),
        liquid: None,
    }
}
