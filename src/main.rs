use anyhow::{Context, Result, ensure};
use clap::{Parser, Subcommand, ValueEnum};
use fs2::FileExt;
use kraken360::{
    protocol::{Format, Lcd},
    render::{DashboardRenderer, Layout, Primary},
    sensors,
    usb::UsbTransport,
};
use std::{
    fs::{self, OpenOptions},
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

#[derive(Parser)]
#[command(
    version,
    about = "Live Linux CPU/GPU/coolant dashboard for Kraken Elite V2"
)]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Read host sensors and save a PNG, without opening USB (coolant shows --).
    Preview {
        #[command(flatten)]
        options: Options,
    },
    /// Update the LCD until Ctrl+C; --frames bounds the run.
    Run {
        #[command(flatten)]
        options: Options,
        #[arg(long, default_value_t = 0)]
        frames: u64,
        #[arg(long, default_value_t = 1.0)]
        interval: f64,
    },
    /// Send one already encoded Q565 file (experimental; header validation only).
    UploadQ565 {
        file: PathBuf,
        #[arg(long, default_value = "artifacts/runtime/dashboard.lock")]
        lock: PathBuf,
    },
}

#[derive(Clone, Copy, ValueEnum)]
enum MainReading {
    Cpu,
    Gpu,
}

#[derive(clap::Args)]
struct Options {
    #[arg(long)]
    cpu_sensor: Option<PathBuf>,
    #[arg(long, default_value_t = 0)]
    gpu_index: u32,
    /// Large, upper-right, lower-right: g=GPU, c=CPU, l=Liquid. Default: gcl.
    #[arg(long, conflicts_with = "primary")]
    layout: Option<Layout>,
    /// Compatibility option: gpu = gcl, cpu = cgl. Prefer --layout.
    #[arg(long, value_enum, conflicts_with = "layout")]
    primary: Option<MainReading>,
    /// System font by default; a locally extracted CAM OTF can also be selected.
    #[arg(
        long,
        default_value = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    )]
    font: PathBuf,
    #[arg(long, default_value = "artifacts/runtime/rust-dashboard.png")]
    output: PathBuf,
    /// Same lock path as the Python PoC to prevent concurrent controllers.
    #[arg(long, default_value = "artifacts/runtime/dashboard.lock")]
    lock: PathBuf,
}

fn lock(path: &PathBuf) -> Result<std::fs::File> {
    parent(path)?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(path)?;
    file.try_lock_exclusive()
        .context("Dashboard lock held; stop the other Python/Rust controller")?;
    Ok(file)
}

fn parent(path: &std::path::Path) -> Result<()> {
    if let Some(p) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        fs::create_dir_all(p)?;
    }
    Ok(())
}

fn main() -> Result<()> {
    let args = Args::parse();
    let stop = Arc::new(AtomicBool::new(false));
    for signal in [signal_hook::consts::SIGINT, signal_hook::consts::SIGTERM] {
        signal_hook::flag::register(signal, Arc::clone(&stop))?;
    }
    match args.command {
        Command::UploadQ565 { file, lock: path } => {
            let data = fs::read(file)?;
            Format::Q565.validate(&data)?;
            let _lock = lock(&path)?;
            Lcd::new(UsbTransport::open()?).display(&data, Format::Q565)?;
            println!("Q565 uploaded and acknowledged");
        }
        command => {
            let (options, run) = match command {
                Command::Preview { options } => (options, None),
                Command::Run {
                    options,
                    frames,
                    interval,
                } => {
                    ensure!(
                        interval.is_finite() && (0.2..=86400.).contains(&interval),
                        "Interval must be 0.2..86400 seconds"
                    );
                    (options, Some((frames, Duration::from_secs_f64(interval))))
                }
                _ => unreachable!(),
            };
            let sensor = match options.cpu_sensor {
                Some(p) => p,
                None => sensors::cpu_sensor(std::path::Path::new("/sys/class/hwmon"))?,
            };
            let layout = options.layout.unwrap_or_else(|| match options.primary {
                Some(MainReading::Cpu) => Primary::Cpu.into(),
                Some(MainReading::Gpu) | None => Layout::default(),
            });
            let renderer = DashboardRenderer::with_layout(&options.font, layout)?;
            parent(&options.output)?;
            eprintln!(
                "CPU sensor: {}; NVIDIA GPU index: {}",
                sensor.display(),
                options.gpu_index
            );
            let _lock = if run.is_some() {
                Some(lock(&options.lock)?)
            } else {
                None
            };
            let mut lcd = if run.is_some() {
                Some(Lcd::new(UsbTransport::open()?))
            } else {
                None
            };
            let mut count = 0;
            while !stop.load(Ordering::Relaxed) {
                let started = Instant::now();
                let mut readings = sensors::sample(&sensor, options.gpu_index);
                if let Some(lcd) = &mut lcd {
                    readings.liquid = lcd.coolant()?;
                }
                let image = renderer.render(readings);
                if let Some(lcd) = &mut lcd {
                    lcd.display(image.as_raw(), Format::Rgb888)?;
                }
                image.save(&options.output)?;
                println!("{readings:?}");
                count += 1;
                let Some((frames, interval)) = run else {
                    break;
                };
                if frames != 0 && count >= frames {
                    break;
                }
                while started.elapsed() < interval && !stop.load(Ordering::Relaxed) {
                    thread::sleep(
                        (interval - started.elapsed().min(interval))
                            .min(Duration::from_millis(100)),
                    );
                }
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layout_cli_accepts_all_permutations_for_run_and_preview() {
        for subcommand in ["run", "preview"] {
            for layout in ["gcl", "glc", "cgl", "clg", "lgc", "lcg"] {
                let args =
                    Args::try_parse_from(["kraken360", subcommand, "--layout", layout]).unwrap();
                let options = match args.command {
                    Command::Run { options, .. } | Command::Preview { options } => options,
                    _ => unreachable!(),
                };
                assert_eq!(options.layout.unwrap().to_string(), layout);
            }
        }
    }

    #[test]
    fn ambiguous_and_invalid_layouts_fail_before_device_access() {
        for args in [
            vec!["kraken360", "run", "--layout", "gcc"],
            vec!["kraken360", "run", "--layout", "clg", "--primary", "gpu"],
        ] {
            assert!(Args::try_parse_from(args).is_err());
        }
        assert!(Args::try_parse_from(["kraken360", "run", "--primary", "cpu"]).is_ok());
    }
}
