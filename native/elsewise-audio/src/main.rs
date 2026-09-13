use std::env;
use std::f32::consts::TAU;
use std::io::{self, Write};
use std::process::ExitCode;

use elsewise_audio::protocol::frame::{AudioFrame, PROTOCOL_VERSION};
use serde::Serialize;
use uuid::Uuid;

#[derive(Serialize)]
struct Descriptor<'a> {
    name: &'a str,
    version: &'a str,
    protocol_version: u16,
    canonical_sample_rate: u32,
    canonical_channels: u8,
    canonical_sample_format: &'a str,
    capabilities: [&'a str; 1],
}

fn value_after(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|pair| pair[0] == flag)
        .map(|pair| pair[1].clone())
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.iter().any(|arg| arg == "--describe") {
        let descriptor = Descriptor {
            name: "elsewise-audio",
            version: env!("CARGO_PKG_VERSION"),
            protocol_version: PROTOCOL_VERSION,
            canonical_sample_rate: 16_000,
            canonical_channels: 1,
            canonical_sample_format: "f32le",
            capabilities: ["synthetic_audio"],
        };
        println!("{}", serde_json::to_string(&descriptor).unwrap());
        return ExitCode::SUCCESS;
    }
    if !args.iter().any(|arg| arg == "--synthetic") {
        eprintln!("use --describe or --synthetic");
        return ExitCode::from(2);
    }
    match run_synthetic(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::from(2)
        }
    }
}

fn run_synthetic(args: &[String]) -> Result<(), String> {
    let source_id = value_after(args, "--source-id")
        .ok_or("missing --source-id")?
        .parse::<Uuid>()
        .map_err(|_| "invalid --source-id")?;
    let epoch_id = value_after(args, "--epoch-id")
        .ok_or("missing --epoch-id")?
        .parse::<Uuid>()
        .map_err(|_| "invalid --epoch-id")?;
    let frame_count = value_after(args, "--frames")
        .unwrap_or_else(|| "10".to_owned())
        .parse::<u64>()
        .map_err(|_| "invalid --frames")?;
    let frame_samples = 320_u32;
    let origin_ns = 0_u64;
    let mut stdout = io::stdout().lock();
    for sequence in 0..frame_count {
        let first_sample = sequence * u64::from(frame_samples);
        let pcm = (0..frame_samples)
            .map(|index| {
                let position = first_sample + u64::from(index);
                (TAU * 440.0 * position as f32 / 16_000.0).sin() * 0.1
            })
            .collect();
        let frame = AudioFrame {
            source_id,
            epoch_id,
            sequence,
            source_sample_position: first_sample,
            host_monotonic_ns: origin_ns + first_sample * 1_000_000_000 / 16_000,
            frame_samples,
            flags: u16::from(sequence + 1 == frame_count) << 2,
            pcm,
        };
        stdout
            .write_all(&frame.encode().map_err(str::to_owned)?)
            .map_err(|error| error.to_string())?;
    }
    stdout.flush().map_err(|error| error.to_string())
}
