use std::env;
use std::io::{ErrorKind as IoErrorKind, Read};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{Map, Value};

use super::{
    AtomicCaptureMetrics, CALLBACK_BLOCKS, CaptureSourceDescriptor, CaptureSourceKind,
    CapturedBlock, MAX_CALLBACK_SAMPLES, NativeCapture, NativeStreamHandle, elapsed_ns,
};

const SAMPLE_RATE: u32 = 48_000;
const CHANNELS: usize = 2;
const SAMPLES_PER_BLOCK: usize = SAMPLE_RATE as usize / 50 * CHANNELS;
const BYTES_PER_BLOCK: usize = SAMPLES_PER_BLOCK * size_of::<f32>();
const MAX_DISCOVERY_BYTES: usize = 8 * 1024 * 1024;
const MAX_STARTUP_ERROR_BYTES: usize = 4 * 1024;
const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(2);

pub struct LinuxRecorder {
    child: Child,
    reader: Option<JoinHandle<()>>,
    diagnostics: Option<JoinHandle<()>>,
}

impl LinuxRecorder {
    pub fn stop(&mut self) -> Result<(), String> {
        if self.child.try_wait().map_err(io_error)?.is_none() {
            if let Err(error) = self.child.kill()
                && error.kind() != IoErrorKind::InvalidInput
            {
                return Err(io_error(error));
            }
        }
        self.child.wait().map_err(io_error)?;
        if let Some(reader) = self.reader.take() {
            reader
                .join()
                .map_err(|_| "linux recorder reader thread panicked".to_owned())?;
        }
        if let Some(diagnostics) = self.diagnostics.take() {
            diagnostics
                .join()
                .map_err(|_| "linux recorder diagnostics thread panicked".to_owned())?;
        }
        Ok(())
    }
}

impl Drop for LinuxRecorder {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
        if let Some(diagnostics) = self.diagnostics.take() {
            let _ = diagnostics.join();
        }
    }
}

pub fn discover_sources() -> Result<Vec<CaptureSourceDescriptor>, String> {
    if command_available("pw-record") {
        if let Ok(output) = command_output("pw-dump", &[]) {
            if let Ok(sources) = parse_pipewire_sources(&output, default_sink_name().as_deref()) {
                return Ok(sources);
            }
        }
    }
    discover_pulse_sources()
}

pub fn start_capture(
    source_kind: CaptureSourceKind,
    target_key: &str,
    helper_started: Instant,
) -> Result<NativeCapture, String> {
    let resolved = if target_key.is_empty() || target_key == "default" {
        let sources = discover_sources()?;
        sources
            .iter()
            .find(|source| source.source_kind == source_kind && source.is_default)
            .or_else(|| {
                sources
                    .iter()
                    .find(|source| source.source_kind == source_kind && source.active)
            })
            .map(|source| source.target_key.clone())
            .ok_or_else(|| match source_kind {
                CaptureSourceKind::SystemAudio => {
                    "default PipeWire/Pulse system-audio target is unavailable".to_owned()
                }
                CaptureSourceKind::ProcessAudio => {
                    "no active PipeWire/Pulse process-audio target is available".to_owned()
                }
                CaptureSourceKind::Microphone => "default microphone is unavailable".to_owned(),
            })?
    } else {
        target_key.to_owned()
    };

    let mut child = recorder_command(source_kind, &resolved)?
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| recorder_spawn_error(&resolved, error))?;

    thread::sleep(Duration::from_millis(75));
    if let Some(status) = child.try_wait().map_err(io_error)? {
        let mut detail = String::new();
        if let Some(stderr) = child.stderr.take() {
            let mut bytes = Vec::new();
            let _ = stderr
                .take(MAX_STARTUP_ERROR_BYTES as u64)
                .read_to_end(&mut bytes);
            detail = String::from_utf8_lossy(&bytes).trim().to_owned();
        }
        return Err(format!(
            "linux audio recorder exited during startup ({status}){}",
            if detail.is_empty() {
                String::new()
            } else {
                format!(": {detail}")
            }
        ));
    }

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "linux audio recorder stdout is unavailable".to_owned())?;
    let mut stderr = child
        .stderr
        .take()
        .ok_or_else(|| "linux audio recorder stderr is unavailable".to_owned())?;
    let diagnostics = thread::Builder::new()
        .name("elsewise-linux-audio-diagnostics".to_owned())
        .spawn(move || {
            // Discard diagnostics after the bounded startup probe so the child
            // cannot block on a full pipe and raw backend text is not retained.
            let _ = std::io::copy(&mut stderr, &mut std::io::sink());
        })
        .map_err(io_error)?;

    let metrics = Arc::new(AtomicCaptureMetrics::default());
    let (free_tx, free_rx) = mpsc::sync_channel(CALLBACK_BLOCKS);
    let (filled_tx, filled_rx) = mpsc::sync_channel(CALLBACK_BLOCKS);
    for _ in 0..CALLBACK_BLOCKS {
        free_tx
            .try_send(Vec::with_capacity(MAX_CALLBACK_SAMPLES))
            .map_err(|_| "failed to initialize linux recorder buffer pool".to_owned())?;
    }
    let reader_metrics = Arc::clone(&metrics);
    let reader_free_tx = free_tx.clone();
    let reader = thread::Builder::new()
        .name("elsewise-linux-audio".to_owned())
        .spawn(move || {
            read_recorder(
                stdout,
                free_rx,
                reader_free_tx,
                filled_tx,
                reader_metrics,
                helper_started,
            );
        })
        .map_err(io_error)?;

    Ok(NativeCapture {
        stream: NativeStreamHandle::LinuxRecorder(LinuxRecorder {
            child,
            reader: Some(reader),
            diagnostics: Some(diagnostics),
        }),
        filled_rx,
        free_tx,
        metrics,
        channels: CHANNELS,
        sample_rate: SAMPLE_RATE,
        stopped: false,
    })
}

fn recorder_command(source_kind: CaptureSourceKind, target_key: &str) -> Result<Command, String> {
    if let Some(target) = target_key.strip_prefix("pipewire:") {
        if target.is_empty() || target.len() > 512 {
            return Err("invalid PipeWire target".to_owned());
        }
        let mut command = Command::new("pw-record");
        command.args([
            "--target",
            target,
            "--rate",
            "48000",
            "--channels",
            "2",
            "--format",
            "f32",
            "--latency",
            "40ms",
            "-",
        ]);
        return Ok(command);
    }
    if let Some(source) = target_key.strip_prefix("pulse-monitor:") {
        if source_kind != CaptureSourceKind::SystemAudio || source.is_empty() || source.len() > 512
        {
            return Err("invalid PulseAudio monitor target".to_owned());
        }
        let mut command = pulse_recorder();
        command.arg(format!("--device={source}"));
        return Ok(command);
    }
    if let Some(index) = target_key.strip_prefix("pulse-stream:") {
        if source_kind != CaptureSourceKind::ProcessAudio || index.parse::<u32>().is_err() {
            return Err("invalid PulseAudio process target".to_owned());
        }
        let mut command = pulse_recorder();
        command.arg(format!("--monitor-stream={index}"));
        return Ok(command);
    }
    Err("unsupported Linux audio target; refresh the source inventory".to_owned())
}

fn pulse_recorder() -> Command {
    let mut command = Command::new("parec");
    command.args([
        "--raw",
        "--format=float32le",
        "--rate=48000",
        "--channels=2",
        "--latency-msec=40",
        "--process-time-msec=20",
        "--client-name=Elsewise",
        "--stream-name=Elsewise remote audio",
    ]);
    command
}

fn read_recorder<R: Read>(
    mut reader: R,
    free_rx: mpsc::Receiver<Vec<f32>>,
    free_tx: mpsc::SyncSender<Vec<f32>>,
    filled_tx: mpsc::SyncSender<CapturedBlock>,
    metrics: Arc<AtomicCaptureMetrics>,
    helper_started: Instant,
) {
    let mut bytes = vec![0_u8; BYTES_PER_BLOCK];
    loop {
        match reader.read_exact(&mut bytes) {
            Ok(()) => {}
            Err(error) if error.kind() == IoErrorKind::UnexpectedEof => break,
            Err(_) => {
                metrics.errors.fetch_add(1, Ordering::Relaxed);
                break;
            }
        }
        let mut samples = match free_rx.try_recv() {
            Ok(samples) => samples,
            Err(_) => {
                metrics
                    .dropped_callback_blocks
                    .fetch_add(1, Ordering::Relaxed);
                continue;
            }
        };
        samples.extend(
            bytes
                .chunks_exact(size_of::<f32>())
                .map(|chunk| f32::from_le_bytes(chunk.try_into().unwrap())),
        );
        let block = CapturedBlock {
            samples,
            captured_monotonic_ns: elapsed_ns(helper_started),
        };
        if let Err(
            mpsc::TrySendError::Full(mut block) | mpsc::TrySendError::Disconnected(mut block),
        ) = filled_tx.try_send(block)
        {
            metrics
                .dropped_callback_blocks
                .fetch_add(1, Ordering::Relaxed);
            block.samples.clear();
            let _ = free_tx.try_send(block.samples);
        }
    }
}

fn parse_pipewire_sources(
    bytes: &[u8],
    default_sink: Option<&str>,
) -> Result<Vec<CaptureSourceDescriptor>, String> {
    let values: Vec<Value> = serde_json::from_slice(bytes).map_err(json_error)?;
    let mut sources = Vec::new();
    for value in values {
        if value.get("type").and_then(Value::as_str) != Some("PipeWire:Interface:Node") {
            continue;
        }
        let Some(info) = value.get("info").and_then(Value::as_object) else {
            continue;
        };
        let Some(properties) = info.get("props").and_then(Value::as_object) else {
            continue;
        };
        let Some(media_class) = string_property(properties, "media.class") else {
            continue;
        };
        let source_kind = match media_class {
            "Audio/Sink" => CaptureSourceKind::SystemAudio,
            "Stream/Output/Audio" => CaptureSourceKind::ProcessAudio,
            _ => continue,
        };
        let Some(serial) = property_text(properties, "object.serial") else {
            continue;
        };
        let node_name = string_property(properties, "node.name").unwrap_or_default();
        let display_name = if source_kind == CaptureSourceKind::ProcessAudio {
            process_display_name(properties)
        } else {
            first_property(
                properties,
                &[
                    "node.description",
                    "device.description",
                    "node.nick",
                    "node.name",
                ],
            )
            .unwrap_or("System audio")
            .to_owned()
        };
        if display_name.is_empty() || display_name.len() > 512 {
            continue;
        }
        let state = info
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        sources.push(CaptureSourceDescriptor {
            source_kind,
            target_key: format!("pipewire:{serial}"),
            display_name,
            is_default: source_kind == CaptureSourceKind::SystemAudio
                && default_sink == Some(node_name),
            active: source_kind == CaptureSourceKind::SystemAudio
                || !matches!(state, "error" | "suspended"),
        });
    }
    Ok(sources)
}

fn discover_pulse_sources() -> Result<Vec<CaptureSourceDescriptor>, String> {
    if !command_available("parec") {
        return Err(
            "Linux remote capture requires PipeWire tools (pw-dump, pw-record) or PulseAudio tools (pactl, parec)"
                .to_owned(),
        );
    }
    let default_sink = default_sink_name();
    let source_bytes = command_output("pactl", &["-f", "json", "list", "sources"])?;
    let stream_bytes = command_output("pactl", &["-f", "json", "list", "sink-inputs"])?;
    let mut sources = parse_pulse_monitors(&source_bytes, default_sink.as_deref())?;
    sources.extend(parse_pulse_streams(&stream_bytes)?);
    Ok(sources)
}

fn parse_pulse_monitors(
    bytes: &[u8],
    default_sink: Option<&str>,
) -> Result<Vec<CaptureSourceDescriptor>, String> {
    let values: Vec<Value> = serde_json::from_slice(bytes).map_err(json_error)?;
    Ok(values
        .into_iter()
        .filter_map(|value| {
            let object = value.as_object()?;
            let name = object.get("name")?.as_str()?;
            let monitored_sink = object.get("monitor_source")?.as_str()?;
            if monitored_sink.is_empty() || name.len() > 512 {
                return None;
            }
            let display_name = object
                .get("description")
                .and_then(Value::as_str)
                .unwrap_or("System audio");
            Some(CaptureSourceDescriptor {
                source_kind: CaptureSourceKind::SystemAudio,
                target_key: format!("pulse-monitor:{name}"),
                display_name: display_name.chars().take(512).collect(),
                is_default: default_sink == Some(monitored_sink),
                active: true,
            })
        })
        .collect())
}

fn parse_pulse_streams(bytes: &[u8]) -> Result<Vec<CaptureSourceDescriptor>, String> {
    let values: Vec<Value> = serde_json::from_slice(bytes).map_err(json_error)?;
    Ok(values
        .into_iter()
        .filter_map(|value| {
            let object = value.as_object()?;
            let index = object.get("index")?.as_u64()?;
            let properties = object.get("properties")?.as_object()?;
            let display_name = process_display_name(properties);
            if display_name.is_empty() || display_name.len() > 512 {
                return None;
            }
            Some(CaptureSourceDescriptor {
                source_kind: CaptureSourceKind::ProcessAudio,
                target_key: format!("pulse-stream:{index}"),
                display_name,
                is_default: false,
                active: !object
                    .get("corked")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
            })
        })
        .collect())
}

fn process_display_name(properties: &Map<String, Value>) -> String {
    let application = first_property(
        properties,
        &[
            "application.name",
            "application.process.binary",
            "node.name",
        ],
    )
    .unwrap_or("Application audio");
    let media = string_property(properties, "media.name");
    let value = match media {
        Some(media) if media != application => format!("{application} — {media}"),
        _ => application.to_owned(),
    };
    value.chars().take(512).collect()
}

fn first_property<'a>(properties: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a str> {
    keys.iter()
        .find_map(|key| string_property(properties, key))
        .filter(|value| !value.is_empty())
}

fn string_property<'a>(properties: &'a Map<String, Value>, key: &str) -> Option<&'a str> {
    properties.get(key).and_then(Value::as_str)
}

fn property_text(properties: &Map<String, Value>, key: &str) -> Option<String> {
    match properties.get(key)? {
        Value::String(value) if !value.is_empty() && value.len() <= 512 => Some(value.clone()),
        Value::Number(value) => Some(value.to_string()),
        _ => None,
    }
}

fn default_sink_name() -> Option<String> {
    let bytes = command_output("pactl", &["get-default-sink"]).ok()?;
    let value = String::from_utf8(bytes).ok()?.trim().to_owned();
    (!value.is_empty() && value.len() <= 512).then_some(value)
}

fn command_available(name: &str) -> bool {
    env::var_os("PATH").is_some_and(|paths| {
        env::split_paths(&paths).any(|directory| {
            let candidate = directory.join(name);
            candidate.is_file() && is_executable(&candidate)
        })
    })
}

#[cfg(unix)]
fn is_executable(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    path.metadata()
        .is_ok_and(|metadata| metadata.permissions().mode() & 0o111 != 0)
}

fn command_output(name: &str, arguments: &[&str]) -> Result<Vec<u8>, String> {
    let mut child = Command::new(name)
        .args(arguments)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| recorder_spawn_error(name, error))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| format!("{name} stdout is unavailable"))?;
    let reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stdout
            .take((MAX_DISCOVERY_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map(|_| bytes)
    });
    let deadline = Instant::now() + DISCOVERY_TIMEOUT;
    let status = loop {
        if let Some(status) = child.try_wait().map_err(io_error)? {
            break status;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            let _ = reader.join();
            return Err(format!("{name} discovery timed out"));
        }
        thread::sleep(Duration::from_millis(10));
    };
    let bytes = reader
        .join()
        .map_err(|_| format!("{name} discovery reader panicked"))?
        .map_err(io_error)?;
    if !status.success() {
        return Err(format!("{name} exited with {status}"));
    }
    if bytes.len() > MAX_DISCOVERY_BYTES {
        return Err(format!("{name} output exceeds the discovery bound"));
    }
    Ok(bytes)
}

fn recorder_spawn_error(target: &str, error: std::io::Error) -> String {
    if error.kind() == IoErrorKind::NotFound {
        format!(
            "Linux audio recorder for {target} is missing; install PipeWire tools or pulseaudio-utils"
        )
    } else {
        io_error(error)
    }
}

fn io_error(error: std::io::Error) -> String {
    format!("linux_audio_error: {error}")
}

fn json_error(error: serde_json::Error) -> String {
    format!("linux audio discovery returned invalid JSON: {error}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_pipewire_sink_and_process_using_object_serial() {
        let json = br#"[
          {"type":"PipeWire:Interface:Node","info":{"state":"idle","props":{
            "media.class":"Audio/Sink","object.serial":48,
            "node.name":"alsa_output.test","node.description":"Built-in Audio"}}},
          {"type":"PipeWire:Interface:Node","info":{"state":"running","props":{
            "media.class":"Stream/Output/Audio","object.serial":190,
            "application.name":"Meeting App","media.name":"Call audio"}}}
        ]"#;
        let sources = parse_pipewire_sources(json, Some("alsa_output.test")).unwrap();
        assert_eq!(sources.len(), 2);
        assert_eq!(sources[0].target_key, "pipewire:48");
        assert!(sources[0].is_default);
        assert_eq!(sources[1].target_key, "pipewire:190");
        assert_eq!(sources[1].display_name, "Meeting App — Call audio");
        assert!(sources[1].active);
    }

    #[test]
    fn parses_pulse_monitor_and_process_fallback() {
        let monitors = br#"[{"name":"sink.monitor","description":"Monitor",
          "monitor_source":"sink"}]"#;
        let streams = br#"[{"index":12,"corked":false,"properties":{
          "application.name":"Browser","media.name":"Meeting"}}]"#;
        let monitor_sources = parse_pulse_monitors(monitors, Some("sink")).unwrap();
        let process_sources = parse_pulse_streams(streams).unwrap();
        assert_eq!(monitor_sources[0].target_key, "pulse-monitor:sink.monitor");
        assert!(monitor_sources[0].is_default);
        assert_eq!(process_sources[0].target_key, "pulse-stream:12");
        assert!(process_sources[0].active);
    }

    #[test]
    fn recorder_reader_decodes_little_endian_float_blocks() {
        let mut bytes = Vec::with_capacity(BYTES_PER_BLOCK);
        for index in 0..SAMPLES_PER_BLOCK {
            bytes.extend_from_slice(&(index as f32 / 10.0).to_le_bytes());
        }
        let (free_tx, free_rx) = mpsc::sync_channel(1);
        let (filled_tx, filled_rx) = mpsc::sync_channel(1);
        free_tx
            .try_send(Vec::with_capacity(MAX_CALLBACK_SAMPLES))
            .unwrap();
        let metrics = Arc::new(AtomicCaptureMetrics::default());
        read_recorder(
            bytes.as_slice(),
            free_rx,
            free_tx,
            filled_tx,
            Arc::clone(&metrics),
            Instant::now(),
        );
        let block = filled_rx.try_recv().unwrap();
        assert_eq!(block.samples.len(), SAMPLES_PER_BLOCK);
        assert_eq!(block.samples[10], 1.0);
        assert_eq!(metrics.errors.load(Ordering::Relaxed), 0);
    }
}
