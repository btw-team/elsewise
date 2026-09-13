pub fn mix_to_mono(interleaved: &[f32], channels: usize) -> Vec<f32> {
    assert!(channels > 0);
    interleaved
        .chunks_exact(channels)
        .map(|frame| frame.iter().copied().sum::<f32>() / channels as f32)
        .collect()
}

pub fn linear_resample(input: &[f32], input_rate: u32, output_rate: u32) -> Vec<f32> {
    assert!(input_rate > 0 && output_rate > 0);
    if input.is_empty() || input_rate == output_rate {
        return input.to_vec();
    }
    let output_len = input.len().saturating_mul(output_rate as usize) / input_rate as usize;
    (0..output_len)
        .map(|index| {
            let source = index as f64 * f64::from(input_rate) / f64::from(output_rate);
            let left = source.floor() as usize;
            let right = (left + 1).min(input.len() - 1);
            let fraction = (source - left as f64) as f32;
            input[left] * (1.0 - fraction) + input[right] * fraction
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mixes_channels_and_resamples_once() {
        assert_eq!(mix_to_mono(&[1.0, -1.0, 0.5, 0.5], 2), vec![0.0, 0.5]);
        assert_eq!(linear_resample(&[0.0, 1.0], 2, 4), vec![0.0, 0.5, 1.0, 1.0]);
    }
}
