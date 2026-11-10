//! Render the production UI in a native window using explicit, immutable fixtures.
//!
//! cargo run --manifest-path console/Cargo.toml -p mechrevo-console-gui \
//!   --features screenshot --example ui_preview -- --section sensors --light
//! EFRAME_SCREENSHOT_TO=/absolute/path/preview.png saves the native framebuffer
//! and exits. This example never constructs a hardware Service or writes hardware.
use eframe::egui;
use mechrevo_console_core::{
    ApplyResult, BrightnessApplyResult, BrightnessPlan, CapabilityStatus, CatalogModel,
    ControlError, EvidenceSource, OemApplyResult, OemControl, OemControlKind, OemDomain, OemPlan,
    OemValue, PowerProfile, ProfilePlan, SensorReading, Snapshot,
};
use mechrevo_console_gui::{
    desktop::{DesktopApp, Section},
    Backend, Controller, Preferences, Theme,
};
use serde_json::json;
use std::{io, sync::Arc, time::Instant};

struct PreviewBackend(Snapshot);
fn preview_only<T>() -> Result<T, ControlError> {
    Err(ControlError::new(
        "fixture_only",
        "这是界面预览；所有数据均为模拟数据，不执行设备操作。",
    ))
}
impl Backend for PreviewBackend {
    fn snapshot(&mut self) -> Snapshot {
        self.0.clone()
    }
    fn catalog(&mut self) -> Vec<CatalogModel> {
        catalog()
    }
    fn plan(&mut self, _: PowerProfile) -> Result<ProfilePlan, ControlError> {
        preview_only()
    }
    fn apply(&mut self, _: &ProfilePlan) -> Result<ApplyResult, ControlError> {
        preview_only()
    }
    fn plan_brightness(&mut self, _: u8, _: &str) -> Result<BrightnessPlan, ControlError> {
        preview_only()
    }
    fn apply_brightness(
        &mut self,
        _: &BrightnessPlan,
    ) -> Result<BrightnessApplyResult, ControlError> {
        preview_only()
    }
    fn plan_oem(&mut self, _: &str, _: OemValue) -> Result<OemPlan, ControlError> {
        preview_only()
    }
    fn apply_oem(&mut self, _: &OemPlan) -> Result<OemApplyResult, ControlError> {
        preview_only()
    }
}

fn source(id: &str) -> EvidenceSource {
    EvidenceSource {
        backend: "fixture-only".into(),
        path: format!("fixture://preview/{id}"),
        device_id: Some(format!("fixture-{id}")),
    }
}

fn snapshot() -> Snapshot {
    let mut snapshot: Snapshot = serde_json::from_value(json!({
        "platform":"fixture-only / 界面预览",
        "identity":{
            "manufacturer":"机械革命 · 模拟设备",
            "product_name":"旷世 16 Pro · 界面预览",
            "product_version":"fixture-only", "board_name":"PREVIEW-BOARD",
            "bios_version":"PREVIEW.0", "mechrevo_brand_detected":true,
            "support_note":"仅用于视觉验收的模拟设备，不代表任何型号的硬件兼容性。"
        },
        "telemetry":[], "capabilities":[], "oem_controls":[], "diagnostics":[],
        "brightness":[{
            "id":"fixture-panel", "label":"内置屏幕 · 模拟数据", "current_percent":65.0,
            "control_value":650, "actual_value":650, "maximum":1000,
            "status":"available", "readable":true, "writable":true,
            "supported_percentages":[], "reason":null,
            "source":{"backend":"fixture-only", "path":"fixture://preview/panel", "device_id":"fixture-panel"}
        }],
        "power_policy":{
            "scope":"fixture-only / 模拟电源策略", "current":"balanced",
            "options":["power-saver", "balanced", "performance"], "source":null
        }
    }))
    .expect("built-in preview fixture must match the snapshot schema");
    snapshot.telemetry = [
        ("cpu", "CPU / 处理器 · 模拟", "temperature", 63.0, "°C"),
        ("gpu", "GPU / 独立显卡 · 模拟", "temperature", 48.0, "°C"),
        ("cpu-fan", "CPU Fan · 模拟", "fan_speed", 2600.0, "RPM"),
        ("gpu-fan", "GPU Fan · 模拟", "fan_speed", 2800.0, "RPM"),
        ("battery", "电池电量 · 模拟", "battery_capacity", 82.0, "%"),
        ("ac", "外部电源 · 模拟", "external_power_online", 1.0, ""),
    ]
    .into_iter()
    .map(|(id, label, kind, value, unit)| SensorReading {
        id: id.into(),
        label: label.into(),
        device_id: format!("fixture-{id}"),
        kind: kind.into(),
        value: Some(value),
        unit: unit.into(),
        source: source(id),
        status: CapabilityStatus::Available,
        reason: None,
    })
    .collect();
    let choices =
        |values: &[&str]| OemDomain::Choices(values.iter().map(|v| (*v).into()).collect());
    snapshot.oem_controls = [
        (
            "performance",
            "性能与散热档位",
            OemControlKind::PerformanceProfile,
            OemValue::Choice("mechrevo_gaming".into()),
            choices(&[
                "mechrevo_office",
                "mechrevo_gaming_quiet",
                "mechrevo_gaming",
                "mechrevo_turbo",
                "mechrevo_fan_boost",
            ]),
        ),
        (
            "charging",
            "充电模式",
            OemControlKind::ChargingProfile,
            OemValue::Choice("stationary".into()),
            choices(&["high_capacity", "balanced", "stationary"]),
        ),
        (
            "keyboard-brightness",
            "键盘亮度",
            OemControlKind::KeyboardBrightness,
            OemValue::Level(2),
            OemDomain::Level { max: 4 },
        ),
        (
            "keyboard-color",
            "键盘颜色",
            OemControlKind::KeyboardColor,
            OemValue::Rgb([157, 223, 202]),
            OemDomain::Rgb,
        ),
        (
            "fn-lock",
            "Fn 锁",
            OemControlKind::FnLock,
            OemValue::Boolean(false),
            OemDomain::Boolean,
        ),
    ]
    .into_iter()
    .map(|(id, label, kind, current, domain)| OemControl {
        id: id.into(),
        label: label.into(),
        kind,
        current: Some(current),
        domain,
        status: CapabilityStatus::Available,
        writable: true,
        source: source(id),
        binding: format!("fixture-only:{id}"),
        readback_scope: "模拟界面数据；所有操作由预览后端拒绝，不接触硬件。".into(),
        reason: None,
    })
    .collect();
    snapshot
}

fn catalog() -> Vec<CatalogModel> {
    [
        ("旷世", "旷世 16 Pro"),
        ("蛟龙", "蛟龙 16"),
        ("无界", "无界 14"),
    ]
    .into_iter()
    .enumerate()
    .map(|(index, (series, name))| CatalogModel {
        id: format!("preview-{index}"),
        name: format!("{name} · 预览条目"),
        slug: format!("preview-{index}"),
        category: Some("模拟型号".into()),
        series: Some(series.into()),
        entry_kind: "fixture-only".into(),
        url: "https://example.invalid/fixture-only".into(),
        evidence: vec![],
        support_note: "模拟目录数据，不代表型号兼容性。".into(),
    })
    .collect()
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut size = [1280.0, 900.0];
    let mut preferences = Preferences {
        auto_refresh: false,
        ..Default::default()
    };
    let mut section = Section::Dashboard;
    let mut args = std::env::args().skip(1);
    let invalid = |message: &str| io::Error::new(io::ErrorKind::InvalidInput, message);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--light" => preferences.theme = Theme::Light,
            "--width" | "--height" | "--scale" => {
                let value: f32 = args
                    .next()
                    .ok_or_else(|| invalid("missing numeric argument"))?
                    .parse()?;
                if !value.is_finite() || value <= 0.0 {
                    return Err(
                        invalid("window dimensions and scale must be positive and finite").into(),
                    );
                }
                match arg.as_str() {
                    "--width" => size[0] = value,
                    "--height" => size[1] = value,
                    _ => preferences.text_scale = value,
                }
            }
            "--section" => {
                section = match args.next().as_deref() {
                    Some("dashboard") => Section::Dashboard,
                    Some("controls") => Section::Controls,
                    Some("sensors") => Section::Sensors,
                    Some("catalog") => Section::Catalog,
                    _ => {
                        return Err(
                            invalid("expected dashboard, controls, sensors or catalog").into()
                        )
                    }
                }
            }
            "--help" | "-h" => {
                println!("ui_preview [--light] [--section dashboard|controls|sensors|catalog] [--width 1280] [--height 900] [--scale 1.0]\nFixture-only native UI. Set EFRAME_SCREENSHOT_TO=/absolute/path.png to capture and exit.");
                return Ok(());
            }
            _ => return Err(invalid("unknown preview option; use --help").into()),
        }
    }
    let snapshot = snapshot();
    let mut controller = Controller::new(PreviewBackend(snapshot.clone()))?;
    controller.snapshot = Some(snapshot);
    controller.catalog = catalog();
    controller.last_refresh = Some(Instant::now());
    controller.select_brightness_device("fixture-panel");
    controller.select_oem_control(if section == Section::Controls {
        "fn-lock"
    } else {
        "performance"
    });
    let mut app = DesktopApp::with_controller(controller, preferences);
    app.select_section(section);
    eframe::run_native(
        "机械革命控制中心 · 模拟数据预览",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default()
                .with_inner_size(size)
                .with_min_inner_size([360.0, 280.0])
                .with_app_id("best.lmm.mechrevo-console.ui-preview"),
            renderer: eframe::Renderer::Glow,
            persist_window: false,
            ..Default::default()
        },
        Box::new(move |creation| {
            creation.egui_ctx.add_font_provider(Arc::new(
                egui_system_font_provider::SystemFontProvider::new().with_locale(Some("zh-Hans")),
            ));
            Ok(Box::new(app))
        }),
    )?;
    Ok(())
}
