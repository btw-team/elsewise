#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct StreamCounters {
    pub frames: u64,
    pub dropped_frames: u64,
    pub discontinuities: u64,
    pub xruns: u64,
}

impl StreamCounters {
    pub fn record_frame(&mut self, discontinuity: bool, xrun: bool) {
        self.frames = self.frames.saturating_add(1);
        self.discontinuities = self
            .discontinuities
            .saturating_add(u64::from(discontinuity));
        self.xruns = self.xruns.saturating_add(u64::from(xrun));
    }
}
