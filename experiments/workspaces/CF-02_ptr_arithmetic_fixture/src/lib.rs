pub fn value_at(values: &[i32], index: usize) -> Option<i32> {
    if index >= values.len() {
        return None;
    }

    let base = values.as_ptr();
    // SAFETY: index was checked against the slice length, so base.add(index) is in bounds.
    unsafe { Some(*base.add(index)) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_index_with_pointer_arithmetic() {
        assert_eq!(value_at(&[1, 3, 5, 7], 2), Some(5));
    }

    #[test]
    fn out_of_bounds_returns_none() {
        assert_eq!(value_at(&[1, 3, 5, 7], 4), None);
    }
}
