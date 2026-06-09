#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IniPair {
    pub section: String,
    pub name: String,
    pub value: String,
}

fn trim_ascii(bytes: &[u8]) -> &[u8] {
    let mut start = 0;
    let mut end = bytes.len();

    while start < end && bytes[start].is_ascii_whitespace() {
        start += 1;
    }
    while end > start && bytes[end - 1].is_ascii_whitespace() {
        end -= 1;
    }

    &bytes[start..end]
}

fn decode_ascii(bytes: &[u8]) -> String {
    String::from_utf8_lossy(bytes).into_owned()
}

pub fn parse_ini_pairs_c2rust_style(input: &str) -> Vec<IniPair> {
    let bytes = input.as_bytes();
    let base = bytes.as_ptr();
    let mut section = String::new();
    let mut pairs = Vec::new();
    let mut line_start = 0_usize;
    let mut index = 0_usize;

    while index <= bytes.len() {
        let at_end = index == bytes.len();
        let is_newline = if at_end {
            true
        } else {
            // SAFETY: index is checked against bytes.len(), so base.add(index) is in bounds.
            unsafe { *base.add(index) == b'\n' }
        };

        if is_newline {
            let mut line_end = index;
            if line_end > line_start && bytes[line_end - 1] == b'\r' {
                line_end -= 1;
            }

            let line = trim_ascii(&bytes[line_start..line_end]);
            if line.is_empty() || line[0] == b';' || line[0] == b'#' {
                line_start = index + 1;
                index += 1;
                continue;
            }

            if line[0] == b'[' && line[line.len() - 1] == b']' {
                section = decode_ascii(trim_ascii(&line[1..line.len() - 1]));
            } else if let Some(eq) = line.iter().position(|&b| b == b'=' || b == b':') {
                let name = decode_ascii(trim_ascii(&line[..eq]));
                let value = decode_ascii(trim_ascii(&line[eq + 1..]));
                if !name.is_empty() {
                    pairs.push(IniPair {
                        section: section.clone(),
                        name,
                        value,
                    });
                }
            }

            line_start = index + 1;
        }

        index += 1;
    }

    pairs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_sections_and_pairs() {
        let pairs = parse_ini_pairs_c2rust_style(
            "\
; comment
[server]
host = localhost
port: 8080

[feature]
enabled = true
",
        );

        assert_eq!(
            pairs,
            vec![
                IniPair {
                    section: "server".to_string(),
                    name: "host".to_string(),
                    value: "localhost".to_string(),
                },
                IniPair {
                    section: "server".to_string(),
                    name: "port".to_string(),
                    value: "8080".to_string(),
                },
                IniPair {
                    section: "feature".to_string(),
                    name: "enabled".to_string(),
                    value: "true".to_string(),
                },
            ]
        );
    }

    #[test]
    fn ignores_comments_and_blank_lines() {
        let pairs = parse_ini_pairs_c2rust_style("\n# ignored\nname=value\n");
        assert_eq!(pairs.len(), 1);
        assert_eq!(pairs[0].name, "name");
        assert_eq!(pairs[0].value, "value");
    }
}
