use std::collections::VecDeque;

#[derive(Debug)]
pub struct BoundedRing<T> {
    items: VecDeque<T>,
    capacity: usize,
    dropped: u64,
}

impl<T> BoundedRing<T> {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        Self {
            items: VecDeque::with_capacity(capacity),
            capacity,
            dropped: 0,
        }
    }

    pub fn push(&mut self, item: T) -> bool {
        let dropped = if self.items.len() == self.capacity {
            self.items.pop_front();
            self.dropped = self.dropped.saturating_add(1);
            true
        } else {
            false
        };
        self.items.push_back(item);
        dropped
    }

    pub fn pop(&mut self) -> Option<T> {
        self.items.pop_front()
    }

    pub fn dropped(&self) -> u64 {
        self.dropped
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overflow_is_bounded_and_counted() {
        let mut ring = BoundedRing::new(2);
        assert!(!ring.push(1));
        assert!(!ring.push(2));
        assert!(ring.push(3));
        assert_eq!(ring.dropped(), 1);
        assert_eq!(ring.pop(), Some(2));
        assert_eq!(ring.pop(), Some(3));
    }
}
