#[derive(Debug, Clone)]
pub struct SampleClock {
    sample_rate: u32,
    next_position: u64,
    last_host_ns: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockObservation {
    pub first_sample_position: u64,
    pub host_monotonic_ns: u64,
    pub discontinuity: bool,
}

impl SampleClock {
    pub fn new(sample_rate: u32) -> Self {
        assert!(sample_rate > 0);
        Self {
            sample_rate,
            next_position: 0,
            last_host_ns: None,
        }
    }

    pub fn observe(&mut self, frame_samples: u32, host_monotonic_ns: u64) -> ClockObservation {
        let discontinuity = self
            .last_host_ns
            .is_some_and(|last| host_monotonic_ns <= last);
        let observation = ClockObservation {
            first_sample_position: self.next_position,
            host_monotonic_ns,
            discontinuity,
        };
        self.next_position = self.next_position.saturating_add(u64::from(frame_samples));
        self.last_host_ns = Some(host_monotonic_ns);
        observation
    }

    pub fn duration_ns(&self, samples: u64) -> u64 {
        samples.saturating_mul(1_000_000_000) / u64::from(self.sample_rate)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sample_positions_are_monotonic_and_clock_reset_is_visible() {
        let mut clock = SampleClock::new(16_000);
        assert_eq!(clock.observe(320, 1_000).first_sample_position, 0);
        assert_eq!(clock.observe(320, 2_000).first_sample_position, 320);
        assert!(clock.observe(320, 1_500).discontinuity);
        assert_eq!(clock.duration_ns(16_000), 1_000_000_000);
    }
}
