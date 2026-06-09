use std::ptr;

pub fn checksum_c2rust_style(buf: &[u8]) -> u32 {
    let mut total = 0_u32;
    let base = buf.as_ptr();

    for i in 0..buf.len() {
        // SAFETY: i is bounded by buf.len(), so base.add(i) points inside buf.
        let byte = unsafe { *base.add(i) };
        total = total.wrapping_add(byte as u32);
    }

    total
}

pub fn copy_and_checksum(src: &[u8], dst: &mut [u8]) -> Option<u32> {
    if src.len() > dst.len() {
        return None;
    }

    // SAFETY: dst is at least src.len() bytes and both pointers are valid for that range.
    unsafe {
        ptr::copy_nonoverlapping(src.as_ptr(), dst.as_mut_ptr(), src.len());
    }

    Some(checksum_c2rust_style(&dst[..src.len()]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn computes_checksum_with_pointer_walk() {
        assert_eq!(checksum_c2rust_style(&[1, 2, 3, 4]), 10);
    }

    #[test]
    fn copies_then_checksums() {
        let src = [10_u8, 20, 30];
        let mut dst = [0_u8; 5];
        assert_eq!(copy_and_checksum(&src, &mut dst), Some(60));
        assert_eq!(&dst[..3], &src);
    }
}
