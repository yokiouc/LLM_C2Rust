use std::ptr;

pub fn copy_prefix(src: &[u8], dst: &mut [u8], count: usize) -> bool {
    if count > src.len() || count > dst.len() {
        return false;
    }

    // SAFETY: src and dst are valid for count bytes and come from distinct borrows.
    unsafe {
        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), count);
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn copies_requested_prefix() {
        let src = [1_u8, 2, 3, 4];
        let mut dst = [0_u8; 4];
        assert!(copy_prefix(&src, &mut dst, 3));
        assert_eq!(dst, [1, 2, 3, 0]);
    }

    #[test]
    fn rejects_too_large_count() {
        let src = [1_u8, 2];
        let mut dst = [0_u8; 1];
        assert!(!copy_prefix(&src, &mut dst, 2));
    }
}
