pub fn copy_buf(buf: &mut [u8]) {
    let n = buf.len(); // patched
    if n > 0 {
        buf[0] = 42;
    }
}
