pub fn first_value(values: &[i32]) -> Option<i32> {
    if values.is_empty() {
        return None;
    }

    let ptr = values.as_ptr();
    // SAFETY: ptr is derived from a non-empty slice and points to its first element.
    unsafe { Some(*ptr) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_first_value() {
        assert_eq!(first_value(&[7, 8, 9]), Some(7));
    }

    #[test]
    fn empty_slice_returns_none() {
        assert_eq!(first_value(&[]), None);
    }
}
