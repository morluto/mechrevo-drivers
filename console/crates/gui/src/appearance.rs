//! Shared colors, type and quiet surfaces for the native control center.
use eframe::egui::{self, Color32, FontId, Rect};

/// Shared semantic colors. Widgets and materials must use the same theme;
/// status text is deliberately dark enough in the ivory theme to remain legible.
#[derive(Clone, Copy)]
pub(crate) struct Palette {
    pub background: Color32,
    pub panel: Color32,
    pub raised: Color32,
    pub inset: Color32,
    pub text: Color32,
    pub secondary: Color32,
    pub label: Color32,
    pub border: Color32,
    pub accent: Color32,
    pub selection: Color32,
    pub warning: Color32,
    pub error: Color32,
}
impl Palette {
    pub fn new(dark: bool) -> Self {
        if dark {
            Self {
                background: Color32::from_rgb(10, 12, 14),
                panel: Color32::from_rgb(21, 24, 27),
                raised: Color32::from_rgb(35, 39, 43),
                inset: Color32::from_rgb(16, 19, 22),
                text: Color32::from_rgb(239, 243, 245),
                secondary: Color32::from_rgb(155, 165, 174),
                label: Color32::from_rgb(210, 218, 225),
                border: Color32::from_rgb(44, 50, 56),
                accent: Color32::from_rgb(157, 223, 202),
                selection: Color32::from_rgb(29, 52, 46),
                warning: Color32::from_rgb(236, 196, 142),
                error: Color32::from_rgb(248, 160, 160),
            }
        } else {
            Self {
                background: Color32::from_rgb(244, 246, 248),
                panel: Color32::WHITE,
                raised: Color32::from_rgb(232, 237, 240),
                inset: Color32::from_rgb(239, 243, 245),
                text: Color32::from_rgb(25, 33, 40),
                secondary: Color32::from_rgb(89, 101, 111),
                label: Color32::from_rgb(56, 71, 81),
                border: Color32::from_rgb(217, 225, 230),
                accent: Color32::from_rgb(23, 101, 81),
                selection: Color32::from_rgb(222, 239, 233),
                warning: Color32::from_rgb(129, 83, 16),
                error: Color32::from_rgb(164, 46, 46),
            }
        }
    }
}
pub(crate) fn palette(ui: &egui::Ui) -> Palette {
    Palette::new(ui.visuals().dark_mode)
}

/// Install once per context, keeping the platform's Chinese fallback provider.
pub(crate) fn install_fonts(ctx: &egui::Context) {
    let key = egui::Id::unique("mechrevo-bundled-fonts-v2");
    if ctx.data(|data| data.get_temp::<bool>(key).unwrap_or(false)) {
        return;
    }
    use egui::epaint::text::{FontInsert, FontPriority, InsertFontFamily};
    for (name, bytes, families) in [(
        "Manrope",
        include_bytes!("../assets/fonts/Manrope.ttf").as_slice(),
        vec![
            egui::FontFamily::Name("Numbers".into()),
            egui::FontFamily::Proportional,
        ],
    )] {
        let data = egui::FontData::from_static(bytes).tweak(egui::epaint::text::FontTweak {
            coords: egui::epaint::text::VariationCoords::new([(b"wght", 450.0)]),
            ..Default::default()
        });
        ctx.add_font(FontInsert::new(
            name,
            data,
            families
                .into_iter()
                .map(|family| InsertFontFamily {
                    family,
                    priority: FontPriority::Highest,
                })
                .collect(),
        ));
    }
    ctx.data_mut(|data| data.insert_temp(key, true));
}

pub(crate) fn display_font(size: f32) -> FontId {
    number_font(size)
}

pub(crate) fn number_font(size: f32) -> FontId {
    FontId::new(size, egui::FontFamily::Name("Numbers".into()))
}

/// The bundled proportional face does not promise tabular figures. Readouts
/// use egui's actual monospace family so equal-length values keep their width.
pub(crate) fn tabular_font(size: f32) -> FontId {
    FontId::monospace(size)
}

pub(crate) fn paint_backdrop(ui: &egui::Ui, rect: Rect) {
    ui.painter().rect_filled(rect, 0.0, palette(ui).background);
}

pub(crate) fn surface<R>(ui: &mut egui::Ui, contents: impl FnOnce(&mut egui::Ui) -> R) -> R {
    let colors = palette(ui);
    let response = egui::Frame::new()
        .fill(colors.panel)
        .corner_radius(16.0)
        .inner_margin(if ui.available_width() < 380.0 {
            18.0
        } else {
            24.0
        })
        .show(ui, |ui| {
            ui.set_min_width(ui.available_width());
            contents(ui)
        });
    response.inner
}

#[cfg(test)]
mod tests {
    use super::*;

    fn contrast(a: Color32, b: Color32) -> f32 {
        let luminance = |color: Color32| {
            [color.r(), color.g(), color.b()]
                .into_iter()
                .zip([0.2126, 0.7152, 0.0722])
                .map(|(channel, weight)| {
                    let c = f32::from(channel) / 255.0;
                    weight
                        * if c <= 0.04045 {
                            c / 12.92
                        } else {
                            ((c + 0.055) / 1.055).powf(2.4)
                        }
                })
                .sum::<f32>()
        };
        let a = luminance(a);
        let b = luminance(b);
        (a.max(b) + 0.05) / (a.min(b) + 0.05)
    }

    #[test]
    fn semantic_text_has_readable_contrast_in_both_themes() {
        for dark in [true, false] {
            let p = Palette::new(dark);
            for bg in [p.background, p.panel, p.inset] {
                for fg in [p.text, p.secondary, p.label, p.accent, p.warning, p.error] {
                    assert!(contrast(fg, bg) >= 4.5, "dark={dark}: {fg:?} on {bg:?}");
                }
            }
            assert!(contrast(p.accent, p.selection) >= 4.5);
            assert!(contrast(p.background, p.accent) >= 4.5);
        }
    }
}
