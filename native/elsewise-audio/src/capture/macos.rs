use std::collections::BTreeMap;
use std::ffi::{CStr, c_void};
use std::mem::{MaybeUninit, size_of};
use std::ptr::{NonNull, null};
use std::sync::atomic::{AtomicU32, Ordering};

use objc2::{AnyThread, rc::Retained};
use objc2_core_audio::{
    AudioHardwareCreateAggregateDevice, AudioHardwareCreateProcessTap,
    AudioHardwareDestroyAggregateDevice, AudioHardwareDestroyProcessTap,
    AudioObjectGetPropertyData, AudioObjectGetPropertyDataSize, AudioObjectID,
    AudioObjectPropertyAddress, CATapDescription, CATapMuteBehavior, kAudioAggregateDeviceNameKey,
    kAudioAggregateDeviceTapAutoStartKey, kAudioAggregateDeviceTapListKey,
    kAudioAggregateDeviceUIDKey, kAudioEndPointDeviceIsPrivateKey, kAudioHardwareNoError,
    kAudioHardwarePropertyProcessObjectList, kAudioObjectPropertyElementMain,
    kAudioObjectPropertyScopeGlobal, kAudioObjectSystemObject, kAudioProcessPropertyBundleID,
    kAudioProcessPropertyIsRunningOutput, kAudioProcessPropertyPID,
    kAudioSubTapDriftCompensationKey, kAudioSubTapUIDKey,
};
use objc2_core_foundation::{
    CFArray, CFDictionary, CFMutableDictionary, CFRetained, CFString, kCFAllocatorDefault,
    kCFTypeArrayCallBacks, kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks,
};
use objc2_foundation::{NSArray, NSNumber, NSString};

static PROCESS_TAP_INSTANCE: AtomicU32 = AtomicU32::new(0);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessDescriptor {
    pub target_key: String,
    pub display_name: String,
    pub active: bool,
}

pub struct ProcessTapLease {
    tap_id: AudioObjectID,
    aggregate_id: AudioObjectID,
}

impl ProcessTapLease {
    pub fn create(target_key: &str) -> Result<Self, String> {
        let process_ids = resolve_processes(target_key)?;
        if process_ids.is_empty() {
            return Err("selected audio process is unavailable".to_owned());
        }
        let number_ids: Vec<Retained<NSNumber>> =
            process_ids.iter().copied().map(NSNumber::new_u32).collect();
        let processes = NSArray::from_retained_slice(&number_ids);
        let tap_description = unsafe {
            CATapDescription::initStereoMixdownOfProcesses(
                CATapDescription::alloc(),
                processes.as_ref(),
            )
        };
        let process_id = std::process::id();
        let instance = PROCESS_TAP_INSTANCE.fetch_add(1, Ordering::Relaxed);
        unsafe {
            tap_description.setMuteBehavior(CATapMuteBehavior::Unmuted);
            tap_description.setPrivate(true);
            tap_description.setName(&NSString::from_str(&format!(
                "Elsewise process audio {process_id}.{instance}"
            )));
        }

        let mut tap_id = MaybeUninit::<AudioObjectID>::uninit();
        check_status(unsafe {
            AudioHardwareCreateProcessTap(Some(tap_description.as_ref()), tap_id.as_mut_ptr())
        })?;
        let tap_id = unsafe { tap_id.assume_init() };
        let tap_uid = unsafe { tap_description.UUID().UUIDString() };
        let aggregate_uid = format!("com.elsewise.ProcessAudio.{process_id}.{instance}");
        let aggregate_name = format!("Elsewise process audio {process_id}.{instance}");
        let properties = aggregate_device_properties(tap_uid, &aggregate_uid, &aggregate_name);
        let mut aggregate_id = 0;
        if let Err(error) = check_status(unsafe {
            AudioHardwareCreateAggregateDevice(
                properties.as_ref(),
                NonNull::from(&mut aggregate_id),
            )
        }) {
            unsafe {
                let _ = AudioHardwareDestroyProcessTap(tap_id);
            }
            return Err(error);
        }

        Ok(Self {
            tap_id,
            aggregate_id,
        })
    }

    pub fn aggregate_id(&self) -> AudioObjectID {
        self.aggregate_id
    }
}

impl Drop for ProcessTapLease {
    fn drop(&mut self) {
        unsafe {
            let _ = AudioHardwareDestroyAggregateDevice(self.aggregate_id);
            let _ = AudioHardwareDestroyProcessTap(self.tap_id);
        }
    }
}

pub fn discover_processes() -> Result<Vec<ProcessDescriptor>, String> {
    let mut by_target = BTreeMap::<String, ProcessDescriptor>::new();
    for process_id in process_object_ids()? {
        let pid = read_i32(process_id, kAudioProcessPropertyPID).unwrap_or_default();
        let bundle_id = read_string(process_id, kAudioProcessPropertyBundleID);
        let active = read_u32(process_id, kAudioProcessPropertyIsRunningOutput)
            .is_some_and(|value| value != 0);
        let (target_key, display_name) = match bundle_id.filter(|value| !value.is_empty()) {
            Some(bundle_id) => (
                format!("bundle:{bundle_id}"),
                format!("{bundle_id} ({pid})"),
            ),
            None if pid > 0 => (format!("pid:{pid}"), format!("Audio process {pid}")),
            None => continue,
        };
        if target_key.len() > 512 {
            continue;
        }
        by_target
            .entry(target_key.clone())
            .and_modify(|descriptor| descriptor.active |= active)
            .or_insert(ProcessDescriptor {
                target_key,
                display_name,
                active,
            });
    }
    Ok(by_target.into_values().collect())
}

fn resolve_processes(target_key: &str) -> Result<Vec<AudioObjectID>, String> {
    let process_ids = process_object_ids()?;
    if let Some(bundle_id) = target_key.strip_prefix("bundle:") {
        if bundle_id.is_empty() {
            return Err("process bundle target is empty".to_owned());
        }
        return Ok(process_ids
            .into_iter()
            .filter(|process_id| {
                read_string(*process_id, kAudioProcessPropertyBundleID).as_deref()
                    == Some(bundle_id)
            })
            .collect());
    }
    if let Some(pid) = target_key.strip_prefix("pid:") {
        let pid = pid
            .parse::<i32>()
            .map_err(|_| "process PID target is invalid".to_owned())?;
        return Ok(process_ids
            .into_iter()
            .filter(|process_id| read_i32(*process_id, kAudioProcessPropertyPID) == Some(pid))
            .collect());
    }
    Err("process target must start with bundle: or pid:".to_owned())
}

fn process_object_ids() -> Result<Vec<AudioObjectID>, String> {
    let address = property_address(kAudioHardwarePropertyProcessObjectList);
    let mut data_size = 0;
    check_status(unsafe {
        AudioObjectGetPropertyDataSize(
            kAudioObjectSystemObject as AudioObjectID,
            NonNull::from(&address),
            0,
            null(),
            NonNull::from(&mut data_size),
        )
    })?;
    let count = data_size as usize / size_of::<AudioObjectID>();
    if count == 0 {
        return Ok(Vec::new());
    }
    if data_size as usize % size_of::<AudioObjectID>() != 0 {
        return Err("Core Audio returned an invalid process list size".to_owned());
    }
    let mut process_ids = Vec::with_capacity(count);
    check_status(unsafe {
        AudioObjectGetPropertyData(
            kAudioObjectSystemObject as AudioObjectID,
            NonNull::from(&address),
            0,
            null(),
            NonNull::from(&mut data_size),
            NonNull::new(process_ids.as_mut_ptr())
                .expect("non-zero Core Audio process list capacity")
                .cast(),
        )
    })?;
    unsafe {
        process_ids.set_len(count);
    }
    Ok(process_ids)
}

fn read_i32(object_id: AudioObjectID, selector: u32) -> Option<i32> {
    let address = property_address(selector);
    let mut value = 0_i32;
    let mut data_size = size_of::<i32>() as u32;
    (unsafe {
        AudioObjectGetPropertyData(
            object_id,
            NonNull::from(&address),
            0,
            null(),
            NonNull::from(&mut data_size),
            NonNull::from(&mut value).cast(),
        )
    } == kAudioHardwareNoError)
        .then_some(value)
}

fn read_u32(object_id: AudioObjectID, selector: u32) -> Option<u32> {
    let address = property_address(selector);
    let mut value = 0_u32;
    let mut data_size = size_of::<u32>() as u32;
    (unsafe {
        AudioObjectGetPropertyData(
            object_id,
            NonNull::from(&address),
            0,
            null(),
            NonNull::from(&mut data_size),
            NonNull::from(&mut value).cast(),
        )
    } == kAudioHardwareNoError)
        .then_some(value)
}

fn read_string(object_id: AudioObjectID, selector: u32) -> Option<String> {
    let address = property_address(selector);
    let mut value: *mut CFString = std::ptr::null_mut();
    let mut data_size = size_of::<*mut CFString>() as u32;
    let status = unsafe {
        AudioObjectGetPropertyData(
            object_id,
            NonNull::from(&address),
            0,
            null(),
            NonNull::from(&mut data_size),
            NonNull::from(&mut value).cast(),
        )
    };
    if status != kAudioHardwareNoError {
        return None;
    }
    let value = NonNull::new(value)?;
    Some(unsafe { CFRetained::from_raw(value) }.to_string())
}

fn property_address(selector: u32) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress {
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain,
    }
}

fn aggregate_device_properties(
    tap_uid: Retained<NSString>,
    aggregate_uid: &str,
    aggregate_name: &str,
) -> CFRetained<CFDictionary> {
    let tap = unsafe {
        let dictionary = CFMutableDictionary::new(
            kCFAllocatorDefault,
            2,
            &kCFTypeDictionaryKeyCallBacks,
            &kCFTypeDictionaryValueCallBacks,
        )
        .expect("Core Foundation dictionary allocation failed");
        CFMutableDictionary::set_value(
            Some(dictionary.as_ref()),
            &*cf_string(kAudioSubTapUIDKey) as *const _ as *const c_void,
            &*tap_uid as *const _ as *const c_void,
        );
        CFMutableDictionary::set_value(
            Some(dictionary.as_ref()),
            &*cf_string(kAudioSubTapDriftCompensationKey) as *const _ as *const c_void,
            &*NSNumber::new_bool(true) as *const _ as *const c_void,
        );
        dictionary
    };
    let taps = unsafe {
        CFArray::new(
            kCFAllocatorDefault,
            [tap].as_ptr() as *mut *const c_void,
            1,
            &kCFTypeArrayCallBacks,
        )
        .expect("Core Foundation array allocation failed")
    };
    unsafe {
        let dictionary = CFMutableDictionary::new(
            kCFAllocatorDefault,
            5,
            &kCFTypeDictionaryKeyCallBacks,
            &kCFTypeDictionaryValueCallBacks,
        )
        .expect("Core Foundation dictionary allocation failed");
        for (key, value) in [
            (
                kAudioAggregateDeviceNameKey,
                &*CFString::from_str(aggregate_name) as *const _ as *const c_void,
            ),
            (
                kAudioAggregateDeviceUIDKey,
                &*CFString::from_str(aggregate_uid) as *const _ as *const c_void,
            ),
            (
                kAudioAggregateDeviceTapListKey,
                &*taps as *const _ as *const c_void,
            ),
            (
                kAudioAggregateDeviceTapAutoStartKey,
                &*NSNumber::new_bool(true) as *const _ as *const c_void,
            ),
            (
                kAudioEndPointDeviceIsPrivateKey,
                &*NSNumber::new_bool(true) as *const _ as *const c_void,
            ),
        ] {
            CFMutableDictionary::set_value(
                Some(dictionary.as_ref()),
                &*cf_string(key) as *const _ as *const c_void,
                value,
            );
        }
        CFRetained::cast_unchecked::<CFDictionary>(dictionary)
    }
}

fn cf_string(value: &'static CStr) -> CFRetained<CFString> {
    unsafe { CFString::with_c_string(kCFAllocatorDefault, value.as_ptr(), 0x0800_0100) }
        .expect("Core Foundation string allocation failed")
}

fn check_status(status: i32) -> Result<(), String> {
    if status == kAudioHardwareNoError {
        Ok(())
    } else {
        Err(format!("core_audio_status_{status}"))
    }
}
