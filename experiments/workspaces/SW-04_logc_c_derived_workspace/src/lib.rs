use std::ptr;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Level {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}

impl Level {
    fn label(self) -> &'static str {
        match self {
            Self::Trace => "TRACE",
            Self::Debug => "DEBUG",
            Self::Info => "INFO",
            Self::Warn => "WARN",
            Self::Error => "ERROR",
        }
    }
}

pub fn should_log(current: Level, message: Level) -> bool {
    message >= current
}

pub fn format_log_record_c2rust_style(
    current: Level,
    message: Level,
    file: &str,
    line: u32,
    text: &str,
) -> Option<String> {
    if !should_log(current, message) {
        return None;
    }

    let rendered = format!("{} {}:{}: {}", message.label(), file, line, text);
    let src = rendered.as_bytes();
    let mut buffer = vec![0_u8; src.len()];

    // SAFETY: buffer is allocated to exactly src.len(), and both pointers are valid for that range.
    unsafe {
        ptr::copy_nonoverlapping(src.as_ptr(), buffer.as_mut_ptr(), src.len());
    }

    String::from_utf8(buffer).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filters_below_current_level() {
        assert_eq!(
            format_log_record_c2rust_style(Level::Warn, Level::Info, "main.c", 7, "hidden"),
            None
        );
    }

    #[test]
    fn formats_enabled_record() {
        assert_eq!(
            format_log_record_c2rust_style(Level::Debug, Level::Error, "main.c", 42, "disk full"),
            Some("ERROR main.c:42: disk full".to_string())
        );
    }
}
