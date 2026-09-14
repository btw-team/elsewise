use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender, TryRecvError, TrySendError};
use std::time::Instant;

#[cfg(target_os = "macos")]
use coreaudio::audio_unit::macos_helpers::audio_unit_from_device_id_uninitialized;
#[cfg(target_os = "macos")]
use coreaudio::audio_unit::render_callback::{Args, data};
#[cfg(target_os = "macos")]
use coreaudio::audio_unit::{
    AudioUnit, Element, SampleFormat as CoreAudioSampleFormat, Scope, StreamFormat,
    audio_format::LinearPcmFlags,
};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{
    Device, DeviceId, Error, ErrorKind, FromSample, Sample, SampleFormat, SizedSample, Stream,
    StreamConfig,
};

#[cfg(target_os = "macos")]
mod macos;

const CALLBACK_BLOCKS: usize = 32;
const MAX_CALLBACK_SAMPLES: usize = 65_536;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureSourceKind {
    Microphone,
    ProcessAudio,
    SystemAudio,
}

impl CaptureSourceKind {
    pub fn protocol_name(self) -> &'static str {
        match self {
            Self::Microphone => "native_microphone",
            Self::ProcessAudio => "native_process_audio",
            Self::SystemAudio => "native_system_audio",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CaptureSourceDescriptor {
    pub source_kind: CaptureSourceKind,
    pub target_key: String,
    pub display_name: String,
    pub is_default: bool,
    pub active: bool,
}

#[derive(Debug)]
pub struct CapturedBlock {
    pub samples: Vec<f32>,
    pub captured_monotonic_ns: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CaptureMetrics {
    pub dropped_callback_blocks: u64,
    pub xruns: u64,
    pub route_changes: u64,
    pub errors: u64,
}

#[derive(Default)]
struct AtomicCaptureMetrics {
    dropped_callback_blocks: AtomicU64,
    xruns: AtomicU64,
    route_changes: AtomicU64,
    errors: AtomicU64,
}

pub struct NativeCapture {
    stream: NativeStreamHandle,
    filled_rx: Receiver<CapturedBlock>,
    free_tx: SyncSender<Vec<f32>>,
    metrics: Arc<AtomicCaptureMetrics>,
    channels: usize,
    sample_rate: u32,
    #[cfg(target_os = "macos")]
    _process_tap: Option<macos::ProcessTapLease>,
}

enum NativeStreamHandle {
    Cpal(Stream),
    #[cfg(target_os = "macos")]
    CoreAudio(AudioUnit),
}

impl NativeCapture {
    pub fn channels(&self) -> usize {
        self.channels
    }

    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }

    pub fn try_read(&self) -> Result<Option<CapturedBlock>, String> {
        match self.filled_rx.try_recv() {
            Ok(block) => Ok(Some(block)),
            Err(TryRecvError::Empty) => Ok(None),
            Err(TryRecvError::Disconnected) => {
                Err("native capture callback disconnected".to_owned())
            }
        }
    }

    pub fn recycle(&self, mut block: CapturedBlock) {
        block.samples.clear();
        let _ = self.free_tx.try_send(block.samples);
    }

    pub fn pause(&mut self) -> Result<(), String> {
        match &mut self.stream {
            NativeStreamHandle::Cpal(stream) => stream.pause().map_err(capture_error),
            #[cfg(target_os = "macos")]
            NativeStreamHandle::CoreAudio(stream) => {
                stream.stop().map_err(|error| error.to_string())
            }
        }
    }

    pub fn metrics(&self) -> CaptureMetrics {
        CaptureMetrics {
            dropped_callback_blocks: self.metrics.dropped_callback_blocks.load(Ordering::Relaxed),
            xruns: self.metrics.xruns.load(Ordering::Relaxed),
            route_changes: self.metrics.route_changes.load(Ordering::Relaxed),
            errors: self.metrics.errors.load(Ordering::Relaxed),
        }
    }
}

pub fn discover_sources() -> Result<Vec<CaptureSourceDescriptor>, String> {
    let host = cpal::default_host();
    let default_input_id = host
        .default_input_device()
        .and_then(|device| device.id().ok())
        .map(|id| id.to_string());
    let default_output_id = host
        .default_output_device()
        .and_then(|device| device.id().ok())
        .map(|id| id.to_string());
    let mut sources = Vec::new();

    let input_devices = host.input_devices().map_err(capture_error)?;
    for device in input_devices {
        if let Some(descriptor) = describe_device(
            &device,
            CaptureSourceKind::Microphone,
            default_input_id.as_deref(),
        ) {
            sources.push(descriptor);
        }
    }

    #[cfg(target_os = "macos")]
    {
        let output_devices = host.output_devices().map_err(capture_error)?;
        for device in output_devices {
            if let Some(descriptor) = describe_device(
                &device,
                CaptureSourceKind::SystemAudio,
                default_output_id.as_deref(),
            ) {
                sources.push(descriptor);
            }
        }
        for process in macos::discover_processes()? {
            sources.push(CaptureSourceDescriptor {
                source_kind: CaptureSourceKind::ProcessAudio,
                target_key: process.target_key,
                display_name: process.display_name,
                is_default: false,
                active: process.active,
            });
        }
    }

    sources.sort_by(|left, right| {
        left.source_kind
            .protocol_name()
            .cmp(right.source_kind.protocol_name())
            .then_with(|| right.is_default.cmp(&left.is_default))
            .then_with(|| left.display_name.cmp(&right.display_name))
    });
    Ok(sources)
}

pub fn start_capture(
    source_kind: CaptureSourceKind,
    target_key: &str,
    helper_started: Instant,
) -> Result<NativeCapture, String> {
    #[cfg(target_os = "macos")]
    if source_kind == CaptureSourceKind::ProcessAudio {
        return start_process_capture(target_key, helper_started);
    }
    let device = select_device(source_kind, target_key)?;
    #[cfg(not(target_os = "macos"))]
    let device = select_device(source_kind, target_key)?;
    let supported_config = match source_kind {
        CaptureSourceKind::Microphone => device.default_input_config(),
        CaptureSourceKind::ProcessAudio => device.default_input_config(),
        CaptureSourceKind::SystemAudio => device.default_output_config(),
    }
    .map_err(capture_error)?;
    let channels = usize::from(supported_config.channels());
    let sample_rate = supported_config.sample_rate();
    if channels == 0 || sample_rate == 0 || sample_rate % 50 != 0 {
        return Err("audio device format cannot produce exact 20 ms frames".to_owned());
    }

    let metrics = Arc::new(AtomicCaptureMetrics::default());
    let (free_tx, free_rx) = mpsc::sync_channel(CALLBACK_BLOCKS);
    let (filled_tx, filled_rx) = mpsc::sync_channel(CALLBACK_BLOCKS);
    for _ in 0..CALLBACK_BLOCKS {
        free_tx
            .try_send(Vec::with_capacity(MAX_CALLBACK_SAMPLES))
            .map_err(|_| "failed to initialize native callback buffer pool".to_owned())?;
    }

    let sample_format = supported_config.sample_format();
    let config: StreamConfig = supported_config.into();
    let error_metrics = Arc::clone(&metrics);
    let error_callback = move |error: Error| match error.kind() {
        ErrorKind::Xrun => {
            error_metrics.xruns.fetch_add(1, Ordering::Relaxed);
        }
        ErrorKind::DeviceChanged => {
            error_metrics.route_changes.fetch_add(1, Ordering::Relaxed);
        }
        _ => {
            error_metrics.errors.fetch_add(1, Ordering::Relaxed);
        }
    };
    let callback_metrics = Arc::clone(&metrics);
    let stream = build_stream(
        &device,
        config,
        sample_format,
        free_rx,
        free_tx.clone(),
        filled_tx,
        callback_metrics,
        helper_started,
        error_callback,
    )?;
    stream.play().map_err(capture_error)?;

    Ok(NativeCapture {
        stream: NativeStreamHandle::Cpal(stream),
        filled_rx,
        free_tx,
        metrics,
        channels,
        sample_rate,
        #[cfg(target_os = "macos")]
        _process_tap: None,
    })
}

#[cfg(target_os = "macos")]
fn start_process_capture(
    target_key: &str,
    helper_started: Instant,
) -> Result<NativeCapture, String> {
    let process_tap = macos::ProcessTapLease::create(target_key)?;
    let mut audio_unit = audio_unit_from_device_id_uninitialized(process_tap.aggregate_id(), true)
        .map_err(|error| error.to_string())?;
    let device_format = audio_unit
        .input_stream_format()
        .map_err(|error| error.to_string())?;
    let channels = device_format.channels as usize;
    let sample_rate = device_format.sample_rate.round() as u32;
    if channels == 0 || sample_rate == 0 || sample_rate % 50 != 0 {
        return Err("process tap format cannot produce exact 20 ms frames".to_owned());
    }
    audio_unit
        .set_stream_format(
            StreamFormat {
                sample_rate: f64::from(sample_rate),
                sample_format: CoreAudioSampleFormat::F32,
                flags: LinearPcmFlags::IS_FLOAT | LinearPcmFlags::IS_PACKED,
                channels: channels as u32,
            },
            Scope::Output,
            Element::Input,
        )
        .map_err(|error| error.to_string())?;

    let metrics = Arc::new(AtomicCaptureMetrics::default());
    let (free_tx, free_rx) = mpsc::sync_channel(CALLBACK_BLOCKS);
    let (filled_tx, filled_rx) = mpsc::sync_channel(CALLBACK_BLOCKS);
    for _ in 0..CALLBACK_BLOCKS {
        free_tx
            .try_send(Vec::with_capacity(MAX_CALLBACK_SAMPLES))
            .map_err(|_| "failed to initialize process callback buffer pool".to_owned())?;
    }
    let callback_metrics = Arc::clone(&metrics);
    let callback_free_tx = free_tx.clone();
    audio_unit
        .set_input_callback(move |args: Args<data::Interleaved<f32>>| {
            copy_callback_data(
                args.data.buffer,
                &free_rx,
                &callback_free_tx,
                &filled_tx,
                &callback_metrics,
                helper_started,
            );
            Ok(())
        })
        .map_err(|error| error.to_string())?;
    audio_unit.initialize().map_err(|error| error.to_string())?;
    audio_unit.start().map_err(|error| error.to_string())?;

    Ok(NativeCapture {
        stream: NativeStreamHandle::CoreAudio(audio_unit),
        filled_rx,
        free_tx,
        metrics,
        channels,
        sample_rate,
        _process_tap: Some(process_tap),
    })
}

fn describe_device(
    device: &Device,
    source_kind: CaptureSourceKind,
    default_id: Option<&str>,
) -> Option<CaptureSourceDescriptor> {
    let target_key = device.id().ok()?.to_string();
    if target_key.len() > 512 {
        return None;
    }
    let display_name = device
        .description()
        .map(|description| description.name().to_owned())
        .unwrap_or_else(|_| "Audio device".to_owned());
    Some(CaptureSourceDescriptor {
        source_kind,
        is_default: default_id == Some(target_key.as_str()),
        target_key,
        display_name,
        active: true,
    })
}

fn select_device(source_kind: CaptureSourceKind, target_key: &str) -> Result<Device, String> {
    if target_key.is_empty() || target_key == "default" {
        let host = cpal::default_host();
        return match source_kind {
            CaptureSourceKind::Microphone => host.default_input_device(),
            CaptureSourceKind::ProcessAudio => None,
            CaptureSourceKind::SystemAudio => host.default_output_device(),
        }
        .ok_or_else(|| "default audio device is unavailable".to_owned());
    }
    if target_key.len() > 512 {
        return Err("audio target key exceeds the supported bound".to_owned());
    }
    let device_id = DeviceId::from_str(target_key).map_err(capture_error)?;
    let host = cpal::host_from_id(device_id.host()).map_err(capture_error)?;
    let device = host
        .device_by_id(&device_id)
        .ok_or_else(|| "selected audio device is unavailable".to_owned())?;
    match source_kind {
        CaptureSourceKind::Microphone if !device.supports_input() => {
            Err("selected device does not support microphone input".to_owned())
        }
        CaptureSourceKind::SystemAudio if !device.supports_output() => {
            Err("selected device does not support system output capture".to_owned())
        }
        CaptureSourceKind::ProcessAudio => {
            Err("native process capture is available only on macOS".to_owned())
        }
        _ => Ok(device),
    }
}

#[allow(clippy::too_many_arguments)]
fn build_stream<E>(
    device: &Device,
    config: StreamConfig,
    sample_format: SampleFormat,
    free_rx: Receiver<Vec<f32>>,
    free_tx: SyncSender<Vec<f32>>,
    filled_tx: SyncSender<CapturedBlock>,
    metrics: Arc<AtomicCaptureMetrics>,
    helper_started: Instant,
    error_callback: E,
) -> Result<Stream, String>
where
    E: FnMut(Error) + Send + 'static,
{
    macro_rules! input_stream {
        ($sample:ty) => {
            device.build_input_stream(
                config,
                move |data: &[$sample], _| {
                    copy_callback_data(
                        data,
                        &free_rx,
                        &free_tx,
                        &filled_tx,
                        &metrics,
                        helper_started,
                    );
                },
                error_callback,
                None,
            )
        };
    }

    let result = match sample_format {
        SampleFormat::I8 => input_stream!(i8),
        SampleFormat::I16 => input_stream!(i16),
        SampleFormat::I24 => input_stream!(cpal::I24),
        SampleFormat::I32 => input_stream!(i32),
        SampleFormat::I64 => input_stream!(i64),
        SampleFormat::U8 => input_stream!(u8),
        SampleFormat::U16 => input_stream!(u16),
        SampleFormat::U24 => input_stream!(cpal::U24),
        SampleFormat::U32 => input_stream!(u32),
        SampleFormat::U64 => input_stream!(u64),
        SampleFormat::F32 => input_stream!(f32),
        SampleFormat::F64 => input_stream!(f64),
        _ => return Err(format!("unsupported native sample format: {sample_format}")),
    };
    result.map_err(capture_error)
}

fn copy_callback_data<T>(
    data: &[T],
    free_rx: &Receiver<Vec<f32>>,
    free_tx: &SyncSender<Vec<f32>>,
    filled_tx: &SyncSender<CapturedBlock>,
    metrics: &AtomicCaptureMetrics,
    helper_started: Instant,
) where
    T: Sample + SizedSample,
    f32: FromSample<T>,
{
    if data.len() > MAX_CALLBACK_SAMPLES {
        metrics
            .dropped_callback_blocks
            .fetch_add(1, Ordering::Relaxed);
        return;
    }
    let mut samples = match free_rx.try_recv() {
        Ok(samples) => samples,
        Err(_) => {
            metrics
                .dropped_callback_blocks
                .fetch_add(1, Ordering::Relaxed);
            return;
        }
    };
    samples.extend(data.iter().copied().map(f32::from_sample));
    let block = CapturedBlock {
        samples,
        captured_monotonic_ns: elapsed_ns(helper_started),
    };
    if let Err(TrySendError::Full(mut block) | TrySendError::Disconnected(mut block)) =
        filled_tx.try_send(block)
    {
        metrics
            .dropped_callback_blocks
            .fetch_add(1, Ordering::Relaxed);
        block.samples.clear();
        let _ = free_tx.try_send(block.samples);
    }
}

fn capture_error(error: Error) -> String {
    format!("{}: {error}", error_kind_name(error.kind()))
}

fn error_kind_name(kind: ErrorKind) -> &'static str {
    match kind {
        ErrorKind::DeviceBusy => "device_busy",
        ErrorKind::DeviceChanged => "device_changed",
        ErrorKind::DeviceNotAvailable => "device_not_available",
        ErrorKind::HostUnavailable => "host_unavailable",
        ErrorKind::InvalidInput => "invalid_input",
        ErrorKind::PermissionDenied => "permission_denied",
        ErrorKind::RealtimeDenied => "realtime_denied",
        ErrorKind::ResourceExhausted => "resource_exhausted",
        ErrorKind::StreamInvalidated => "stream_invalidated",
        ErrorKind::UnsupportedConfig => "unsupported_config",
        ErrorKind::UnsupportedOperation => "unsupported_operation",
        ErrorKind::Xrun => "xrun",
        ErrorKind::BackendError => "backend_error",
        ErrorKind::Other => "other",
        _ => "unknown",
    }
}

fn elapsed_ns(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn callback_copy_uses_preallocated_pool_and_reports_overflow() {
        let (free_tx, free_rx) = mpsc::sync_channel(1);
        let (filled_tx, filled_rx) = mpsc::sync_channel(1);
        free_tx.try_send(Vec::with_capacity(4)).unwrap();
        let metrics = AtomicCaptureMetrics::default();
        let started = Instant::now();

        copy_callback_data(
            &[i16::MIN, 0, i16::MAX],
            &free_rx,
            &free_tx,
            &filled_tx,
            &metrics,
            started,
        );
        let block = filled_rx.try_recv().unwrap();
        assert_eq!(block.samples.len(), 3);
        assert!(block.samples[0] <= -0.999);
        assert_eq!(block.samples[1], 0.0);
        assert!(block.samples[2] >= 0.999);

        copy_callback_data(&[0_i16], &free_rx, &free_tx, &filled_tx, &metrics, started);
        assert_eq!(metrics.dropped_callback_blocks.load(Ordering::Relaxed), 1);
    }
}
