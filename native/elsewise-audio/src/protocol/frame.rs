use uuid::Uuid;

pub const PROTOCOL_VERSION: u16 = 1;
pub const MAX_FRAME_SAMPLES: u32 = 3_200;
pub const HEADER_BYTES: usize = 72;
const MAGIC: [u8; 4] = *b"EWA1";

#[derive(Debug, Clone, PartialEq)]
pub struct AudioFrame {
    pub source_id: Uuid,
    pub epoch_id: Uuid,
    pub sequence: u64,
    pub source_sample_position: u64,
    pub host_monotonic_ns: u64,
    pub frame_samples: u32,
    pub flags: u16,
    pub pcm: Vec<f32>,
}

impl AudioFrame {
    pub fn encode(&self) -> Result<Vec<u8>, &'static str> {
        if self.frame_samples > MAX_FRAME_SAMPLES
            || self.pcm.len() != self.frame_samples as usize
            || self.flags & !0b111 != 0
        {
            return Err("invalid audio frame");
        }
        let payload_bytes = self.frame_samples * 4;
        let mut result = Vec::with_capacity(HEADER_BYTES + payload_bytes as usize);
        result.extend_from_slice(&MAGIC);
        result.extend_from_slice(&PROTOCOL_VERSION.to_le_bytes());
        result.extend_from_slice(&self.flags.to_le_bytes());
        result.extend_from_slice(self.source_id.as_bytes());
        result.extend_from_slice(self.epoch_id.as_bytes());
        result.extend_from_slice(&self.sequence.to_le_bytes());
        result.extend_from_slice(&self.source_sample_position.to_le_bytes());
        result.extend_from_slice(&self.host_monotonic_ns.to_le_bytes());
        result.extend_from_slice(&self.frame_samples.to_le_bytes());
        result.extend_from_slice(&payload_bytes.to_le_bytes());
        for sample in &self.pcm {
            result.extend_from_slice(&sample.to_le_bytes());
        }
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_python_golden_vector() {
        let frame = AudioFrame {
            source_id: Uuid::parse_str("00000000-0000-4000-8000-000000000001").unwrap(),
            epoch_id: Uuid::parse_str("00000000-0000-4000-8000-000000000002").unwrap(),
            sequence: 7,
            source_sample_position: 640,
            host_monotonic_ns: 123_456_789,
            frame_samples: 4,
            flags: 1,
            pcm: vec![0.0, 0.25, -0.5, 1.0],
        };
        let encoded = frame.encode().unwrap();
        let expected = concat!(
            "455741310100010000000000000040008000000000000001",
            "000000000000400080000000000000020700000000000000",
            "800200000000000015cd5b07000000000400000010000000",
            "000000000000803e000000bf0000803f"
        );
        assert_eq!(hex(&encoded), expected);
    }

    fn hex(data: &[u8]) -> String {
        data.iter().map(|byte| format!("{byte:02x}")).collect()
    }
}
