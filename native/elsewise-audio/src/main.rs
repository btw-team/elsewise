use std::env;
use std::process::ExitCode;

use elsewise_audio::protocol::frame::PROTOCOL_VERSION;
use serde::Serialize;

#[derive(Serialize)]
struct Descriptor<'a> {
    name: &'a str,
    version: &'a str,
    protocol_version: u16,
    canonical_sample_rate: u32,
    canonical_channels: u8,
    canonical_sample_format: &'a str,
    capabilities: &'a [&'a str],
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
            capabilities: capabilities(),
        };
        println!("{}", serde_json::to_string(&descriptor).unwrap());
        return ExitCode::SUCCESS;
    }
    if !args.iter().any(|arg| arg == "--serve") {
        eprintln!("use --describe or --serve");
        return ExitCode::from(2);
    }
    let control_socket = match value_after(&args, "--control-socket") {
        Some(value) => value,
        None => {
            eprintln!("missing --control-socket");
            return ExitCode::from(2);
        }
    };
    let data_socket = match value_after(&args, "--data-socket") {
        Some(value) => value,
        None => {
            eprintln!("missing --data-socket");
            return ExitCode::from(2);
        }
    };

    match serve(&control_socket, &data_socket) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::from(2)
        }
    }
}

#[cfg(unix)]
fn capabilities() -> &'static [&'static str] {
    #[cfg(target_os = "macos")]
    {
        &[
            "synthetic_audio",
            "multi_stream",
            "unix_socket_ipc",
            "native_microphone",
            "native_process_audio",
            "native_system_audio",
        ]
    }
    #[cfg(not(target_os = "macos"))]
    {
        &["synthetic_audio", "multi_stream", "unix_socket_ipc"]
    }
}

#[cfg(not(unix))]
fn capabilities() -> &'static [&'static str] {
    &["synthetic_audio"]
}

#[cfg(unix)]
fn serve(control_socket: &str, data_socket: &str) -> Result<(), String> {
    unix::serve(control_socket, data_socket)
}

#[cfg(not(unix))]
fn serve(_control_socket: &str, _data_socket: &str) -> Result<(), String> {
    Err("local IPC is not implemented on this platform".to_owned())
}

#[cfg(unix)]
mod unix {
    use std::collections::{HashMap, VecDeque};
    use std::f32::consts::TAU;
    use std::fs;
    use std::io::{BufReader, Write};
    use std::net::Shutdown;
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::{UnixListener, UnixStream};
    use std::path::{Path, PathBuf};
    use std::sync::mpsc::{self, Receiver, SyncSender, TryRecvError, TrySendError};
    use std::thread;
    use std::time::{Duration, Instant};

    use elsewise_audio::capture::{
        CaptureMetrics, CaptureSourceKind, NativeCapture, discover_sources, start_capture,
    };
    use elsewise_audio::common::resample::{linear_resample, mix_to_mono};
    use elsewise_audio::protocol::control::{read_control_frame, write_control_frame};
    use elsewise_audio::protocol::frame::{AudioFrame, PROTOCOL_VERSION};
    use serde_json::{Value, json};
    use uuid::Uuid;

    const FRAME_SAMPLES: u32 = 320;
    const MAX_SYNTHETIC_FRAMES: u64 = 100_000;
    const DATA_QUEUE_FRAMES: usize = 128;
    const IDEMPOTENCY_CACHE_SIZE: usize = 256;

    struct SocketFiles {
        control: PathBuf,
        data: PathBuf,
    }

    impl Drop for SocketFiles {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.control);
            let _ = fs::remove_file(&self.data);
        }
    }

    struct SyntheticStream {
        source_id: Uuid,
        epoch_id: Uuid,
        next_sequence: u64,
        frame_count: u64,
        stopping: bool,
        backpressure_count: u64,
    }

    struct NativeStream {
        source_id: Uuid,
        epoch_id: Uuid,
        capture: NativeCapture,
        native_samples: VecDeque<f32>,
        native_samples_per_frame: usize,
        next_sequence: u64,
        stopping: bool,
        pending_frame: Option<Vec<u8>>,
        pending_frame_is_end: bool,
        backpressure_count: u64,
        last_metrics: CaptureMetrics,
        pending_discontinuity: bool,
        pending_xrun: bool,
        stream_started_ns: u64,
    }

    enum ActiveStream {
        Synthetic(SyntheticStream),
        Native(Box<NativeStream>),
    }

    impl ActiveStream {
        fn source_id(&self) -> Uuid {
            match self {
                Self::Synthetic(stream) => stream.source_id,
                Self::Native(stream) => stream.source_id,
            }
        }

        fn epoch_id(&self) -> Uuid {
            match self {
                Self::Synthetic(stream) => stream.epoch_id,
                Self::Native(stream) => stream.epoch_id,
            }
        }

        fn stopping(&self) -> bool {
            match self {
                Self::Synthetic(stream) => stream.stopping,
                Self::Native(stream) => stream.stopping,
            }
        }

        fn stop(&mut self) -> Result<(), String> {
            match self {
                Self::Synthetic(stream) => stream.stopping = true,
                Self::Native(stream) => {
                    if !stream.stopping {
                        stream.capture.pause()?;
                        stream.stopping = true;
                    }
                }
            }
            Ok(())
        }

        fn next_sequence(&self) -> u64 {
            match self {
                Self::Synthetic(stream) => stream.next_sequence,
                Self::Native(stream) => stream.next_sequence,
            }
        }

        fn backpressure_count(&self) -> u64 {
            match self {
                Self::Synthetic(stream) => stream.backpressure_count,
                Self::Native(stream) => stream.backpressure_count,
            }
        }

        fn capture_metrics(&self) -> CaptureMetrics {
            match self {
                Self::Synthetic(_) => CaptureMetrics::default(),
                Self::Native(stream) => stream.capture.metrics(),
            }
        }
    }

    enum ControlInput {
        Message(Value),
        Closed(String),
    }

    struct ResponseCache {
        entries: HashMap<String, (Value, Value)>,
        order: VecDeque<String>,
    }

    impl ResponseCache {
        fn new() -> Self {
            Self {
                entries: HashMap::new(),
                order: VecDeque::new(),
            }
        }

        fn get(&self, request_id: &str, request: &Value) -> Result<Option<Value>, &'static str> {
            match self.entries.get(request_id) {
                Some((known_request, response)) if known_request == request => {
                    Ok(Some(response.clone()))
                }
                Some(_) => Err("request_id was reused with a different payload"),
                None => Ok(None),
            }
        }

        fn insert(&mut self, request_id: String, request: Value, response: Value) {
            if self.entries.contains_key(&request_id) {
                return;
            }
            if self.order.len() == IDEMPOTENCY_CACHE_SIZE {
                if let Some(expired) = self.order.pop_front() {
                    self.entries.remove(&expired);
                }
            }
            self.order.push_back(request_id.clone());
            self.entries.insert(request_id, (request, response));
        }
    }

    pub fn serve(control_path: &str, data_path: &str) -> Result<(), String> {
        let control_path = PathBuf::from(control_path);
        let data_path = PathBuf::from(data_path);
        validate_socket_path(&control_path)?;
        validate_socket_path(&data_path)?;
        if control_path == data_path {
            return Err("control and data socket paths must differ".to_owned());
        }

        let control_listener = bind_private(&control_path)?;
        let data_listener = bind_private(&data_path)?;
        let _socket_files = SocketFiles {
            control: control_path,
            data: data_path,
        };

        let (mut control, _) = control_listener
            .accept()
            .map_err(|error| error.to_string())?;
        let (data, _) = data_listener.accept().map_err(|error| error.to_string())?;
        let helper_started = Instant::now();
        let helper_instance_id = Uuid::new_v4();

        write_control_frame(
            &mut control,
            &json!({
                "type": "helper.hello",
                "protocol_version": PROTOCOL_VERSION,
                "helper_instance_id": helper_instance_id,
                "capabilities": super::capabilities(),
            }),
        )
        .map_err(|error| error.to_string())?;

        let reader = control.try_clone().map_err(|error| error.to_string())?;
        let (control_tx, control_rx) = mpsc::channel();
        let control_thread = thread::spawn(move || read_control_loop(reader, control_tx));

        let (data_tx, data_rx) = mpsc::sync_channel(DATA_QUEUE_FRAMES);
        let data_thread = thread::spawn(move || write_data_loop(data, data_rx));

        let result = run_loop(
            &mut control,
            control_rx,
            data_tx,
            helper_started,
            helper_instance_id,
        );
        let _ = control.shutdown(Shutdown::Both);
        let _ = control_thread.join();
        let data_result = data_thread
            .join()
            .map_err(|_| "data writer thread panicked".to_owned())?;
        match result {
            Ok(()) => Ok(()),
            Err(error) => Err(data_result.err().unwrap_or(error)),
        }
    }

    fn validate_socket_path(path: &Path) -> Result<(), String> {
        let parent = path
            .parent()
            .ok_or_else(|| "socket path must have a parent directory".to_owned())?;
        let metadata = fs::metadata(parent).map_err(|error| error.to_string())?;
        if !metadata.is_dir() {
            return Err("socket parent is not a directory".to_owned());
        }
        if path.exists() {
            return Err("socket path already exists".to_owned());
        }
        Ok(())
    }

    fn bind_private(path: &Path) -> Result<UnixListener, String> {
        let listener = UnixListener::bind(path).map_err(|error| error.to_string())?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))
            .map_err(|error| error.to_string())?;
        Ok(listener)
    }

    fn read_control_loop(stream: UnixStream, sender: mpsc::Sender<ControlInput>) {
        let mut reader = BufReader::new(stream);
        loop {
            match read_control_frame(&mut reader) {
                Ok(message) => {
                    if sender.send(ControlInput::Message(message)).is_err() {
                        return;
                    }
                }
                Err(error) => {
                    let _ = sender.send(ControlInput::Closed(error.to_string()));
                    return;
                }
            }
        }
    }

    fn write_data_loop(mut stream: UnixStream, receiver: Receiver<Vec<u8>>) -> Result<(), String> {
        for frame in receiver {
            stream
                .write_all(&frame)
                .map_err(|error| error.to_string())?;
        }
        stream.flush().map_err(|error| error.to_string())
    }

    fn run_loop(
        control: &mut UnixStream,
        control_rx: Receiver<ControlInput>,
        data_tx: SyncSender<Vec<u8>>,
        helper_started: Instant,
        helper_instance_id: Uuid,
    ) -> Result<(), String> {
        let mut streams: HashMap<Uuid, ActiveStream> = HashMap::new();
        let mut cache = ResponseCache::new();
        let mut ready = false;
        let mut shutdown_requested = false;

        loop {
            match control_rx.recv_timeout(Duration::from_millis(if streams.is_empty() {
                100
            } else {
                1
            })) {
                Ok(ControlInput::Message(message)) => {
                    handle_control(
                        control,
                        message,
                        &mut streams,
                        &mut cache,
                        &mut ready,
                        &mut shutdown_requested,
                        helper_started,
                        helper_instance_id,
                    )?;
                }
                Ok(ControlInput::Closed(error)) => {
                    if shutdown_requested {
                        break;
                    }
                    return Err(format!("control connection closed: {error}"));
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }

            loop {
                match control_rx.try_recv() {
                    Ok(ControlInput::Message(message)) => handle_control(
                        control,
                        message,
                        &mut streams,
                        &mut cache,
                        &mut ready,
                        &mut shutdown_requested,
                        helper_started,
                        helper_instance_id,
                    )?,
                    Ok(ControlInput::Closed(error)) => {
                        if !shutdown_requested {
                            return Err(format!("control connection closed: {error}"));
                        }
                        break;
                    }
                    Err(TryRecvError::Empty) => break,
                    Err(TryRecvError::Disconnected) => return Ok(()),
                }
            }

            if ready {
                pump_streams(&mut streams, &data_tx, helper_started)?;
            }
            if shutdown_requested && streams.is_empty() {
                break;
            }
        }
        drop(data_tx);
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn handle_control(
        control: &mut UnixStream,
        message: Value,
        streams: &mut HashMap<Uuid, ActiveStream>,
        cache: &mut ResponseCache,
        ready: &mut bool,
        shutdown_requested: &mut bool,
        helper_started: Instant,
        helper_instance_id: Uuid,
    ) -> Result<(), String> {
        let message_type = message["type"].as_str().unwrap_or_default();
        let request_id = message["request_id"].as_str().unwrap_or_default();
        if !request_id.is_empty() {
            match cache.get(request_id, &message) {
                Ok(Some(response)) => {
                    return write_control_frame(control, &response)
                        .map_err(|error| error.to_string());
                }
                Err(error) => {
                    return send_protocol_error(
                        control,
                        Some(request_id),
                        "request_id_conflict",
                        error,
                    );
                }
                Ok(None) => {}
            }
        }

        let response = match message_type {
            "daemon.hello" if !request_id.is_empty() => {
                *ready = true;
                json!({
                    "type": "helper.ready",
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": request_id,
                    "helper_instance_id": helper_instance_id,
                    "helper_monotonic_ns": elapsed_ns(helper_started),
                    "echo_daemon_monotonic_ns": message["daemon_monotonic_ns"],
                })
            }
            "source.start" if !request_id.is_empty() && *ready && !*shutdown_requested => {
                match parse_start(&message, helper_started) {
                    Ok(stream) => {
                        if streams.contains_key(&stream.source_id()) {
                            protocol_error(
                                request_id,
                                "source_already_running",
                                "source is already running",
                            )
                        } else {
                            let source_id = stream.source_id();
                            let epoch_id = stream.epoch_id();
                            streams.insert(source_id, stream);
                            json!({
                                "type": "source.started",
                                "protocol_version": PROTOCOL_VERSION,
                                "request_id": request_id,
                                "source_id": source_id,
                                "epoch_id": epoch_id,
                            })
                        }
                    }
                    Err((code, detail)) => protocol_error(request_id, &code, &detail),
                }
            }
            "source.stop" if !request_id.is_empty() && *ready => {
                match parse_uuid(&message, "source_id") {
                    Ok(source_id) => {
                        if let Some(stream) = streams.get_mut(&source_id) {
                            match stream.stop() {
                                Ok(()) => json!({
                                    "type": "source.stopped",
                                    "protocol_version": PROTOCOL_VERSION,
                                    "request_id": request_id,
                                    "source_id": source_id,
                                    "was_running": true,
                                }),
                                Err(detail) => {
                                    protocol_error(request_id, "capture_stop_failed", &detail)
                                }
                            }
                        } else {
                            json!({
                                "type": "source.stopped",
                                "protocol_version": PROTOCOL_VERSION,
                                "request_id": request_id,
                                "source_id": source_id,
                                "was_running": false,
                            })
                        }
                    }
                    Err(detail) => protocol_error(request_id, "invalid_source_id", detail),
                }
            }
            "helper.health" if !request_id.is_empty() && *ready => json!({
                "type": "helper.health_result",
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "status": "ready",
                "active_streams": streams.len(),
                "data_queue_capacity_frames": DATA_QUEUE_FRAMES,
            }),
            "source.list" if !request_id.is_empty() && *ready => source_list_result(request_id),
            "source.health" if !request_id.is_empty() && *ready => {
                match parse_uuid(&message, "source_id") {
                    Ok(source_id) => {
                        let stream = streams.get(&source_id);
                        json!({
                            "type": "source.health_result",
                            "protocol_version": PROTOCOL_VERSION,
                            "request_id": request_id,
                            "source_id": source_id,
                            "state": stream.map_or("not_running", |value| if value.stopping() {
                                "stopping"
                            } else {
                                "running"
                            }),
                            "next_sequence": stream.map(ActiveStream::next_sequence),
                            "backpressure_count": stream.map_or(0, ActiveStream::backpressure_count),
                            "dropped_callback_blocks": stream.map_or(0, |value| value.capture_metrics().dropped_callback_blocks),
                            "xruns": stream.map_or(0, |value| value.capture_metrics().xruns),
                            "route_changes": stream.map_or(0, |value| value.capture_metrics().route_changes),
                            "capture_errors": stream.map_or(0, |value| value.capture_metrics().errors),
                        })
                    }
                    Err(detail) => protocol_error(request_id, "invalid_source_id", detail),
                }
            }
            "helper.shutdown" if !request_id.is_empty() && *ready => {
                *shutdown_requested = true;
                for stream in streams.values_mut() {
                    let _ = stream.stop();
                }
                json!({
                    "type": "helper.shutdown_ack",
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": request_id,
                })
            }
            _ => protocol_error(
                request_id,
                "invalid_command",
                "command is invalid in the current helper state",
            ),
        };

        write_control_frame(control, &response).map_err(|error| error.to_string())?;
        if !request_id.is_empty() {
            cache.insert(request_id.to_owned(), message, response);
        }
        Ok(())
    }

    fn parse_start(
        message: &Value,
        helper_started: Instant,
    ) -> Result<ActiveStream, (String, String)> {
        let source_id = parse_uuid(message, "source_id").map_err(|_| {
            (
                "invalid_source_id".to_owned(),
                "source_id must be a UUID".to_owned(),
            )
        })?;
        let epoch_id = parse_uuid(message, "epoch_id").map_err(|_| {
            (
                "invalid_epoch_id".to_owned(),
                "epoch_id must be a UUID".to_owned(),
            )
        })?;
        match message["source_kind"].as_str() {
            Some("synthetic_audio") => {
                let frame_count = message["frame_count"].as_u64().unwrap_or_default();
                if !(1..=MAX_SYNTHETIC_FRAMES).contains(&frame_count) {
                    return Err((
                        "invalid_frame_count".to_owned(),
                        "frame_count is outside the supported bound".to_owned(),
                    ));
                }
                Ok(ActiveStream::Synthetic(SyntheticStream {
                    source_id,
                    epoch_id,
                    next_sequence: 0,
                    frame_count,
                    stopping: false,
                    backpressure_count: 0,
                }))
            }
            Some("native_microphone")
            | Some("native_process_audio")
            | Some("native_system_audio") => {
                let source_kind = match message["source_kind"].as_str() {
                    Some("native_microphone") => CaptureSourceKind::Microphone,
                    Some("native_process_audio") => CaptureSourceKind::ProcessAudio,
                    _ => CaptureSourceKind::SystemAudio,
                };
                #[cfg(not(target_os = "macos"))]
                if source_kind != CaptureSourceKind::Microphone {
                    return Err((
                        "unsupported_source_kind".to_owned(),
                        "remote native audio is currently enabled only on macOS".to_owned(),
                    ));
                }
                let target_key = message["target_key"].as_str().unwrap_or("default");
                let capture = start_capture(source_kind, target_key, helper_started)
                    .map_err(|detail| ("capture_start_failed".to_owned(), detail))?;
                let native_samples_per_frame =
                    capture.sample_rate() as usize / 50 * capture.channels();
                Ok(ActiveStream::Native(Box::new(NativeStream {
                    source_id,
                    epoch_id,
                    capture,
                    native_samples: VecDeque::with_capacity(native_samples_per_frame * 2),
                    native_samples_per_frame,
                    next_sequence: 0,
                    stopping: false,
                    pending_frame: None,
                    pending_frame_is_end: false,
                    backpressure_count: 0,
                    last_metrics: CaptureMetrics::default(),
                    pending_discontinuity: false,
                    pending_xrun: false,
                    stream_started_ns: elapsed_ns(helper_started),
                })))
            }
            _ => Err((
                "unsupported_source_kind".to_owned(),
                "source_kind is not supported".to_owned(),
            )),
        }
    }

    fn parse_uuid(message: &Value, field: &str) -> Result<Uuid, &'static str> {
        message[field]
            .as_str()
            .and_then(|value| Uuid::parse_str(value).ok())
            .ok_or("value must be a UUID")
    }

    fn protocol_error(request_id: &str, code: &str, detail: &str) -> Value {
        json!({
            "type": "protocol.error",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "code": code,
            "detail": detail,
        })
    }

    fn send_protocol_error(
        control: &mut UnixStream,
        request_id: Option<&str>,
        code: &str,
        detail: &str,
    ) -> Result<(), String> {
        write_control_frame(
            control,
            &json!({
                "type": "protocol.error",
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "code": code,
                "detail": detail,
            }),
        )
        .map_err(|error| error.to_string())
    }

    fn pump_streams(
        streams: &mut HashMap<Uuid, ActiveStream>,
        data_tx: &SyncSender<Vec<u8>>,
        helper_started: Instant,
    ) -> Result<(), String> {
        let source_ids: Vec<Uuid> = streams.keys().copied().collect();
        let mut completed = Vec::new();
        for source_id in source_ids {
            let stream = streams.get_mut(&source_id).expect("stream disappeared");
            let is_complete = match stream {
                ActiveStream::Synthetic(stream) => {
                    pump_synthetic_stream(stream, data_tx, helper_started)?
                }
                ActiveStream::Native(stream) => pump_native_stream(stream, data_tx)?,
            };
            if is_complete {
                completed.push(source_id);
            }
        }
        for source_id in completed {
            streams.remove(&source_id);
        }
        Ok(())
    }

    fn pump_synthetic_stream(
        stream: &mut SyntheticStream,
        data_tx: &SyncSender<Vec<u8>>,
        helper_started: Instant,
    ) -> Result<bool, String> {
        let sequence = stream.next_sequence;
        let is_last = stream.stopping || sequence + 1 == stream.frame_count;
        let frame = synthetic_frame(stream, helper_started, is_last);
        let encoded = frame.encode().map_err(str::to_owned)?;
        match data_tx.try_send(encoded) {
            Ok(()) => {
                stream.next_sequence += 1;
                Ok(is_last)
            }
            Err(TrySendError::Full(_)) => {
                stream.backpressure_count = stream.backpressure_count.saturating_add(1);
                Ok(false)
            }
            Err(TrySendError::Disconnected(_)) => Err("data connection closed".to_owned()),
        }
    }

    fn pump_native_stream(
        stream: &mut NativeStream,
        data_tx: &SyncSender<Vec<u8>>,
    ) -> Result<bool, String> {
        ingest_native_blocks(stream)?;
        if stream.pending_frame.is_none() {
            prepare_native_frame(stream)?;
        }
        let Some(encoded) = stream.pending_frame.take() else {
            return Ok(false);
        };
        match data_tx.try_send(encoded) {
            Ok(()) => {
                stream.next_sequence = stream.next_sequence.saturating_add(1);
                let completed = stream.pending_frame_is_end;
                stream.pending_frame_is_end = false;
                Ok(completed)
            }
            Err(TrySendError::Full(encoded)) => {
                stream.pending_frame = Some(encoded);
                stream.backpressure_count = stream.backpressure_count.saturating_add(1);
                Ok(false)
            }
            Err(TrySendError::Disconnected(_)) => Err("data connection closed".to_owned()),
        }
    }

    fn ingest_native_blocks(stream: &mut NativeStream) -> Result<(), String> {
        let maximum_pending = stream.native_samples_per_frame.saturating_mul(4);
        while stream.native_samples.len() < maximum_pending {
            let Some(block) = stream.capture.try_read()? else {
                break;
            };
            stream.native_samples.extend(block.samples.iter().copied());
            stream.capture.recycle(block);
        }
        let metrics = stream.capture.metrics();
        if metrics.dropped_callback_blocks > stream.last_metrics.dropped_callback_blocks
            || metrics.route_changes > stream.last_metrics.route_changes
            || metrics.errors > stream.last_metrics.errors
        {
            stream.pending_discontinuity = true;
        }
        if metrics.xruns > stream.last_metrics.xruns {
            stream.pending_discontinuity = true;
            stream.pending_xrun = true;
        }
        stream.last_metrics = metrics;
        Ok(())
    }

    fn prepare_native_frame(stream: &mut NativeStream) -> Result<(), String> {
        let complete_frame = stream.native_samples.len() >= stream.native_samples_per_frame;
        if !complete_frame && !stream.stopping {
            return Ok(());
        }
        let input_samples = if complete_frame {
            stream.native_samples_per_frame
        } else {
            stream.native_samples.len()
        };
        let interleaved: Vec<f32> = stream.native_samples.drain(..input_samples).collect();
        let mono = mix_to_mono(&interleaved, stream.capture.channels());
        let pcm = linear_resample(&mono, stream.capture.sample_rate(), 16_000);
        let is_end = stream.stopping && stream.native_samples.is_empty();
        let mut flags = u16::from(stream.pending_discontinuity);
        flags |= u16::from(stream.pending_xrun) << 1;
        flags |= u16::from(is_end) << 2;
        stream.pending_discontinuity = false;
        stream.pending_xrun = false;
        let frame = AudioFrame {
            source_id: stream.source_id,
            epoch_id: stream.epoch_id,
            sequence: stream.next_sequence,
            source_sample_position: stream.next_sequence * u64::from(FRAME_SAMPLES),
            host_monotonic_ns: stream
                .stream_started_ns
                .saturating_add(stream.next_sequence.saturating_mul(20_000_000)),
            frame_samples: u32::try_from(pcm.len()).map_err(|_| "audio frame is too large")?,
            flags,
            pcm,
        };
        stream.pending_frame = Some(frame.encode().map_err(str::to_owned)?);
        stream.pending_frame_is_end = is_end;
        Ok(())
    }

    fn source_list_result(request_id: &str) -> Value {
        let mut sources = vec![json!({
            "source_kind": "synthetic_audio",
            "target_key": "synthetic:sine-440hz",
            "display_name": "Synthetic 440 Hz sine",
            "available": true,
            "is_default": false,
            "active": true,
        })];
        let mut inventory_error = Value::Null;
        match discover_sources() {
            Ok(discovered) => {
                sources.extend(discovered.into_iter().map(|source| {
                    json!({
                            "source_kind": source.source_kind.protocol_name(),
                            "target_key": source.target_key,
                            "display_name": source.display_name,
                        "available": true,
                        "is_default": source.is_default,
                        "active": source.active,
                    })
                }));
            }
            Err(error) => inventory_error = Value::String(error),
        }
        json!({
            "type": "source.list_result",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "sources": sources,
            "inventory_error": inventory_error,
        })
    }

    fn synthetic_frame(stream: &SyntheticStream, helper_started: Instant, end: bool) -> AudioFrame {
        let first_sample = stream.next_sequence * u64::from(FRAME_SAMPLES);
        let pcm = (0..FRAME_SAMPLES)
            .map(|index| {
                let position = first_sample + u64::from(index);
                (TAU * 440.0 * position as f32 / 16_000.0).sin() * 0.1
            })
            .collect();
        AudioFrame {
            source_id: stream.source_id,
            epoch_id: stream.epoch_id,
            sequence: stream.next_sequence,
            source_sample_position: first_sample,
            host_monotonic_ns: elapsed_ns(helper_started),
            frame_samples: FRAME_SAMPLES,
            flags: u16::from(end) << 2,
            pcm,
        }
    }

    fn elapsed_ns(started: Instant) -> u64 {
        u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn idempotency_cache_rejects_changed_payload() {
            let request = json!({"request_id": "one", "value": 1});
            let response = json!({"type": "ok"});
            let mut cache = ResponseCache::new();
            cache.insert("one".to_owned(), request.clone(), response.clone());
            assert_eq!(cache.get("one", &request).unwrap(), Some(response));
            assert!(
                cache
                    .get("one", &json!({"request_id": "one", "value": 2}))
                    .is_err()
            );
        }
    }
}
