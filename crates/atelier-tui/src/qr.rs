//! QR code renderer for terminal display.

/// Render a URL as a compact QR code using half-block characters.
/// Returns `Vec<String>` — each string is one terminal row (2 QR rows per row).
pub fn render_qr(url: &str) -> Vec<String> {
    use qrcode::render::unicode;
    use qrcode::{EcLevel, QrCode};

    match QrCode::with_error_correction_level(url.as_bytes(), EcLevel::L) {
        Ok(code) => {
            let image = code
                .render::<unicode::Dense1x2>()
                .dark_color(unicode::Dense1x2::Dark)
                .light_color(unicode::Dense1x2::Light)
                .build();
            image.lines().map(|l| l.to_string()).collect()
        }
        Err(_) => vec![format!("QR: {url}")],
    }
}
