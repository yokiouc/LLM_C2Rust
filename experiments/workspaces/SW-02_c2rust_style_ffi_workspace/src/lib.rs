/// Sum a C-style integer buffer.
///
/// # Safety
///
/// When `ptr` is non-null, callers must ensure it is valid for `len` elements.
pub unsafe extern "C" fn c2rust_sum(ptr: *const i32, len: usize) -> i32 {
    if ptr.is_null() {
        return 0;
    }

    let mut total = 0_i32;
    for i in 0..len {
        // SAFETY: callers of this C-like boundary must pass a pointer valid for len elements.
        total += unsafe { *ptr.add(i) };
    }
    total
}

pub fn sum_slice(values: &[i32]) -> i32 {
    // SAFETY: the slice pointer is valid for values.len() elements.
    unsafe { c2rust_sum(values.as_ptr(), values.len()) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_wrapper_sums_slice() {
        assert_eq!(sum_slice(&[2, 4, 6]), 12);
    }

    #[test]
    fn ffi_boundary_handles_null() {
        assert_eq!(unsafe { c2rust_sum(std::ptr::null(), 3) }, 0);
    }
}
