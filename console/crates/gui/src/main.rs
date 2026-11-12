#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 900.0])
            .with_min_inner_size([360.0, 280.0])
            .with_app_id("best.lmm.mechrevo-console"),
        renderer: eframe::Renderer::Glow,
        ..Default::default()
    };
    eframe::run_native(
        "机械革命控制中心",
        options,
        Box::new(|creation| {
            mechrevo_console_gui::desktop::DesktopApp::new(creation)
                .map(|app| Box::new(app) as Box<dyn eframe::App>)
                .map_err(|error| Box::new(error) as Box<dyn std::error::Error + Send + Sync>)
        }),
    )
}
