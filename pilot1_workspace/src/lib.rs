mod utils;

pub fn entry(buf: &mut [u8]) {
    utils::copy_buf(buf);
}
