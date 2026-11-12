#![cfg(feature = "gui")]
//! Exercise the actual desktop renderer without a window server or hardware access.
//! Optional PNG captures are generated from egui's own meshes and font atlas; fixtures
//! never enter the application startup path. Set MECHREVO_GUI_CAPTURE_DIR to capture.
//! MECHREVO_GUI_CAPTURE_MATCH optionally selects comma-separated filename substrings.
use eframe::egui::{self, pos2, vec2, ColorImage, Context, FullOutput, RawInput, Rect, TextureId};
use egui_system_font_provider::SystemFontProvider;
use mechrevo_console_core::{
    ApplyResult, CapabilityStatus, CatalogModel, ControlError, EvidenceSource, OemApplyResult,
    OemControl, OemControlKind, OemDomain, OemPlan, OemValue, PowerProfile, ProfilePlan, Snapshot,
};
use mechrevo_console_gui::{
    desktop::{DesktopApp, RenderMetrics, Section},
    Backend, Controller, DisplayMode, Preferences, Theme,
};
use serde_json::json;
use std::{
    collections::HashMap,
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};

struct FixtureBackend(Snapshot);
impl Backend for FixtureBackend {
    fn snapshot(&mut self) -> Snapshot {
        self.0.clone()
    }
    fn catalog(&mut self) -> Vec<CatalogModel> {
        vec![]
    }
    fn plan(&mut self, _: PowerProfile) -> Result<ProfilePlan, ControlError> {
        panic!("Rendering must not request a hardware control preview")
    }
    fn apply(&mut self, _: &ProfilePlan) -> Result<ApplyResult, ControlError> {
        panic!("Rendering must not write hardware")
    }
    fn plan_oem(&mut self, _: &str, _: OemValue) -> Result<OemPlan, ControlError> {
        panic!("Rendering or editing must not request an OEM control preview")
    }
    fn apply_oem(&mut self, _: &OemPlan) -> Result<OemApplyResult, ControlError> {
        panic!("Rendering or editing must not apply an OEM control")
    }
}

fn fixture(case: &str) -> DesktopApp {
    let long = if case == "representative" {
        "GM6PX0X".to_owned()
    } else {
        "VeryLongUnbrokenHardwareIdentifier0123456789".repeat(5)
    };
    let source_path = if case == "multi_gpu" {
        format!("fixture://{long}/hwmon/{long}/temp1_input")
    } else {
        "fixture://只读测试".into()
    };
    let sensor = |id: String, label: String, device: String, value: Option<f64>| {
        json!({
            "id":id, "label":label, "device_id":device, "kind":"temperature", "value":value,
            "unit":"°C", "source":{"backend":"fixture-only", "path":source_path, "device_id":device},
            "status":if value.is_some() { "available" } else { "unavailable" },
            "reason":if value.is_some() { None } else { Some("当前设备没有提供温度读数；不会把未知数值显示成零。") }
        })
    };
    let mut telemetry = vec![sensor(
        "cpu_temp".into(),
        format!("CPU / 处理器 {long}"),
        "fixture-cpu".into(),
        Some(63.5),
    )];
    for gpu in 0..if case == "multi_gpu" { 8 } else { 2 } {
        telemetry.push(sensor(
            format!("gpu{gpu}_temp"),
            format!("GPU {gpu} / 显卡 {long}"),
            format!("fixture-gpu-{gpu}"),
            if case == "unavailable" {
                None
            } else {
                Some(48.0 + gpu as f64)
            },
        ));
    }
    let mut snapshot: Snapshot = serde_json::from_value(json!({
        "platform":"fixture-only / 非真实硬件", "identity":{
            "manufacturer":"机械革命 / TEST FIXTURE", "product_name":format!("旷世水冷 {long}"),
            "product_version":"测试型号", "board_name":format!("TEST-BOARD-{long}"),
            "bios_version":"TEST.0.0", "mechrevo_brand_detected":true,
            "support_note":"本数据只用于界面测试，检测到品牌不代表已经核验硬件控制能力。"
        },
        "telemetry":telemetry, "brightness":[], "oem_controls":[],
        "capabilities":[{
            "id":"power_profile", "label":"系统电源策略", "status":if case == "unavailable" { "unavailable" } else { "available" },
            "reason":if case == "unavailable" { "当前系统没有可用的电源策略服务；请安装对应服务后重新检测。" } else { "操作系统提供的策略接口" },
            "source":null, "options":["balanced", "performance", "power-saver"]
        },{
            "id":"fan_control", "label":"风扇控制", "status":"unsupported",
            "reason":"没有已核验的型号专属接口；不会猜测 EC 寄存器或风扇参数。", "source":null, "options":[]
        }],
        "power_policy":{"scope":"操作系统 / 不修改 OEM 固件", "current":"balanced", "options":["balanced", "performance", "power-saver"], "source":null},
        "diagnostics":[{"code":"fixture_only", "message":format!("诊断信息包含长路径：{long}，需要完整换行展示。")}]
    })).unwrap();
    if case == "no_telemetry" {
        // Missing hardware identity and a wholly empty sensor inventory are
        // different from individual GPU readings being unavailable.
        snapshot.identity = Default::default();
        snapshot.telemetry.clear();
        snapshot.power_policy.current = None;
        snapshot.power_policy.options.clear();
        for capability in &mut snapshot.capabilities {
            capability.status = mechrevo_console_core::CapabilityStatus::Unavailable;
            capability.options.clear();
        }
    }
    let mut controller = Controller::new(FixtureBackend(snapshot.clone())).unwrap();
    controller.snapshot = Some(snapshot);
    if case == "error" {
        let mut error =
            ControlError::new("access_denied", format!("权限不足，操作没有完成。{long}"));
        error.details = vec![
            format!("保留原始错误以便排查：{long}"),
            "已保留原有设置，重新检测后再试。".into(),
        ];
        controller.error = Some(error);
    }
    controller.catalog = (0..3)
        .map(|index| CatalogModel {
            id: format!("fixture-{index}"),
            name: format!("机械革命测试机型 {index} {long}"),
            slug: format!("fixture-{long}-{index}"),
            category: Some("游戏本".into()),
            series: Some("旷世".into()),
            entry_kind: "fixture-only".into(),
            url: "https://example.invalid/fixture-only".into(),
            evidence: vec![],
            support_note: "仅测试布局，未核验型号兼容性。".into(),
        })
        .collect();
    let mut preferences = Preferences::default();
    if case == "large_compact" {
        preferences.display_mode = DisplayMode::Compact;
        preferences.text_scale = 1.6;
    }
    DesktopApp::with_controller(controller, preferences)
}

fn oem_fixture() -> DesktopApp {
    let mut app = fixture("representative");
    app.preferences.auto_refresh = false;
    let controls = [
        (
            "fn_lock",
            OemControlKind::FnLock,
            "Fn 锁",
            OemValue::Boolean(false),
            OemDomain::Boolean,
        ),
        (
            "charging_profile",
            OemControlKind::ChargingProfile,
            "充电模式",
            OemValue::Choice("high_capacity".into()),
            OemDomain::Choices(vec![
                "high_capacity".into(),
                "balanced".into(),
                "stationary".into(),
            ]),
        ),
        (
            "keyboard_brightness",
            OemControlKind::KeyboardBrightness,
            "键盘亮度",
            OemValue::Level(2),
            OemDomain::Level { max: 4 },
        ),
        (
            "keyboard_color",
            OemControlKind::KeyboardColor,
            "键盘颜色",
            OemValue::Rgb([168, 78, 78]),
            OemDomain::Rgb,
        ),
        (
            "ac_auto_boot",
            OemControlKind::AcAutoBoot,
            "接电自动开机",
            OemValue::Boolean(false),
            OemDomain::Boolean,
        ),
        (
            "usb_power_share",
            OemControlKind::UsbPowerShare,
            "USB 关机供电",
            OemValue::Boolean(false),
            OemDomain::Boolean,
        ),
    ];
    app.controller.snapshot.as_mut().unwrap().oem_controls = controls
        .into_iter()
        .map(|(id, kind, label, current, domain)| OemControl {
            id: id.into(),
            kind,
            label: format!("{label} / 仅用于布局的很长设备控制名称"),
            current: Some(current),
            domain,
            status: CapabilityStatus::Available,
            writable: true,
            source: EvidenceSource {
                backend: "fixture-only".into(),
                path: format!(
                    "fixture://{}/attributes/{id}",
                    "VeryLongUnbrokenDriverIdentity0123456789".repeat(4)
                ),
                device_id: Some("fixture-oem-device".into()),
            },
            binding: format!("fixture-only:{id}:{}", "not-a-hardware-binding".repeat(5)),
            readback_scope: "仅确认测试驱动请求值；不代表实际充电阈值、物理颜色或关机供电效果。"
                .repeat(3),
            reason: Some("只有明确预览并应用才可请求后端；本数据不会接触真实硬件。".into()),
        })
        .collect();
    app.select_section(Section::Controls);
    app
}

fn performance_fixture() -> DesktopApp {
    let mut app = oem_fixture();
    app.select_section(Section::Dashboard);
    let snapshot = app.controller.snapshot.as_mut().unwrap();
    snapshot.oem_controls.truncate(4);
    for control in &mut snapshot.oem_controls {
        control.label = control.label.split(" / ").next().unwrap().into();
    }
    snapshot.oem_controls.insert(
        0,
        OemControl {
            id: "mechrevo-performance-profile".into(),
            kind: OemControlKind::PerformanceProfile,
            label: "性能与散热档位".into(),
            current: Some(OemValue::Choice("mechrevo_turbo".into())),
            domain: OemDomain::Choices(
                [
                    "mechrevo_office",
                    "mechrevo_gaming_quiet",
                    "mechrevo_gaming",
                    "mechrevo_turbo",
                    "mechrevo_fan_boost",
                ]
                .map(str::to_owned)
                .into(),
            ),
            status: CapabilityStatus::Available,
            writable: false,
            source: EvidenceSource {
                backend: "fixture-only".into(),
                path: "fixture://saved-profiles".into(),
                device_id: Some("fixture-only".into()),
            },
            binding: "fixture-only:profiles".into(),
            readback_scope: "模拟界面数据，不代表硬件验收。".into(),
            reason: None,
        },
    );
    snapshot.brightness.push(serde_json::from_value(json!({
        "id":"fixture-panel", "label":"内置屏幕 / 模拟数据", "current_percent":65.0,
        "control_value":650, "actual_value":650, "maximum":1000,
        "status":"available", "readable":true, "writable":true, "supported_percentages":[], "reason":null,
        "source":{"backend":"fixture-only", "path":"fixture://panel", "device_id":"fixture-panel"}
    })).unwrap());
    for (id, label, value) in [
        ("cpu_fan", "CPU Fan", 2600.0),
        ("gpu_fan", "GPU Fan", 3800.0),
    ] {
        snapshot.telemetry.push(serde_json::from_value(json!({
            "id":id, "label":label, "device_id":"fixture-fans", "kind":"fan_speed", "value":value,
            "unit":"RPM", "status":"available", "reason":null,
            "source":{"backend":"fixture-only", "path":"fixture://fans", "device_id":"fixture-fans"}
        })).unwrap());
    }
    app
}

#[test]
fn five_profile_dashboard_is_responsive_in_both_themes() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let capture = std::env::var_os("MECHREVO_GUI_CAPTURE_DIR").map(std::path::PathBuf::from);
    if let Some(path) = &capture {
        std::fs::create_dir_all(path).unwrap();
    }
    for (theme, name) in [(Theme::Dark, "dark"), (Theme::Light, "light")] {
        for (physical, dpi, text_scale) in [
            ([1280, 900], 1.0, 1.0),
            ([1120, 760], 1.0, 1.0),
            ([360, 280], 1.0, 1.0),
            ([720, 560], 2.0, 1.6),
        ] {
            let mut app = performance_fixture();
            app.preferences.theme = theme;
            app.preferences.text_scale = text_scale;
            let mut harness = Harness::new(physical, dpi, fonts.clone());
            let label = format!(
                "profiles-{name}-{}x{}-text{}",
                physical[0], physical[1], text_scale
            );
            assert_layout(&label, &mut app, &mut harness, capture.as_deref(), true);
            let style = harness.ctx.global_style();
            assert_eq!(
                style.visuals.dark_mode,
                theme == Theme::Dark,
                "{label}: theme mismatch"
            );
            assert_eq!(
                style.spacing.interact_size.y, 36.0,
                "{label}: theme must not reset control sizes"
            );
            assert_eq!(
                style.spacing.button_padding,
                vec2(12.0, 8.0),
                "{label}: theme must not reset spacing"
            );
            let (metrics, output) = reveal_oem_control(
                &mut harness,
                &mut app,
                "预览档位更改",
                egui::accesskit::Role::Button,
            );
            assert_width(&label, &metrics);
            assert_client_bounds(&label, &metrics, physical, output.pixels_per_point);
            assert!(
                !app.controller.busy(),
                "drawing must not request a preview or write"
            );
            assert!(app.controller.oem_preview.is_none());
            assert_eq!(
                app.controller.selected_oem().unwrap().current,
                Some(OemValue::Choice("mechrevo_turbo".into()))
            );
        }
    }
}

#[test]
fn profile_selection_does_not_apply_or_change_current_readback() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = performance_fixture();
    let mut harness = Harness::new([1280, 900], 1.0, fonts);
    let (_, output) = settle(&mut harness, &mut app);
    let (_, office) = accessible_control(
        &output,
        "办公节能\n轻负载 · 节能优先",
        egui::accesskit::Role::Button,
    );
    let output = click(&mut harness, &mut app, office.center());
    assert_eq!(
        app.controller.requested_oem_value,
        Some(OemValue::Choice("mechrevo_office".into()))
    );
    assert_eq!(
        app.controller.selected_oem().unwrap().current,
        Some(OemValue::Choice("mechrevo_turbo".into()))
    );
    assert!(!app.controller.busy());
    assert!(app.controller.oem_preview.is_none());
    let (_, node) = output
        .platform_output
        .accesskit_update
        .as_ref()
        .unwrap()
        .nodes
        .iter()
        .find(|(_, node)| node.label() == Some("应用性能档位"))
        .unwrap();
    assert!(
        node.is_disabled(),
        "a selected card must never authorize a write"
    );
    assert_page_title(&output, "当前运行");
    assert_page_title(&output, "狂暴性能");
    // A stale preview cannot survive choosing a different profile.
    let control = app.controller.selected_oem().unwrap();
    app.controller.oem_preview = Some(OemPlan {
        control_id: control.id.clone(),
        kind: control.kind,
        label: control.label.clone(),
        previous: control.current.clone().unwrap(),
        target: OemValue::Choice("mechrevo_office".into()),
        domain: control.domain.clone(),
        source: control.source.clone(),
        binding: control.binding.clone(),
        readback_scope: control.readback_scope.clone(),
        requires_privilege: true,
        companion_brightness: None,
    });
    let (_, output) = settle(&mut harness, &mut app);
    let (_, boost) = accessible_control(
        &output,
        "全速强冷\n全速风扇请求 · 快速散热",
        egui::accesskit::Role::Button,
    );
    click(&mut harness, &mut app, boost.center());
    assert!(app.controller.oem_preview.is_none());
    assert!(!app.controller.busy());
    assert_eq!(
        app.controller.requested_oem_value,
        Some(OemValue::Choice("mechrevo_fan_boost".into()))
    );
}

#[test]
fn unavailable_performance_backend_never_offers_a_write() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = performance_fixture();
    let control = &mut app.controller.snapshot.as_mut().unwrap().oem_controls[0];
    control.current = None;
    control.status = CapabilityStatus::Unavailable;
    control.reason = Some("测试后台不可用".into());
    let mut harness = Harness::new([1280, 900], 1.0, fonts);
    let (_, output) = settle(&mut harness, &mut app);
    assert_page_title(&output, "测试后台不可用");
    assert!(!output
        .platform_output
        .accesskit_update
        .as_ref()
        .unwrap()
        .nodes
        .iter()
        .any(|(_, node)| node.label() == Some("应用性能档位") && !node.is_disabled()));
    assert!(!app.controller.busy());
}

struct Harness {
    ctx: Context,
    textures: HashMap<TextureId, ColorImage>,
    physical: [u32; 2],
    dpi: f32,
    frame_number: u32,
}
impl Harness {
    fn new(physical: [u32; 2], dpi: f32, fonts: Arc<SystemFontProvider>) -> Self {
        let ctx = Context::default();
        ctx.add_font_provider(fonts);
        ctx.enable_accesskit();
        // A tofu/replacement glyph must fail the same layout regression that draws it.
        ctx.set_missing_glyph_policy(egui::epaint::text::MissingGlyphPolicy::Panic);
        Self {
            ctx,
            textures: HashMap::new(),
            physical,
            dpi,
            frame_number: 0,
        }
    }
    fn frame(&mut self, app: &mut DesktopApp) -> (RenderMetrics, FullOutput) {
        self.frame_with_events(app, vec![])
    }
    fn frame_with_events(
        &mut self,
        app: &mut DesktopApp,
        events: Vec<egui::Event>,
    ) -> (RenderMetrics, FullOutput) {
        let mut input = RawInput {
            screen_rect: Some(Rect::from_min_size(
                pos2(0.0, 0.0),
                vec2(
                    self.physical[0] as f32 / (self.dpi * self.ctx.zoom_factor()),
                    self.physical[1] as f32 / (self.dpi * self.ctx.zoom_factor()),
                ),
            )),
            time: Some(self.frame_number as f64 * 0.1),
            events,
            ..Default::default()
        };
        input
            .viewports
            .get_mut(&egui::ViewportId::ROOT)
            .unwrap()
            .native_pixels_per_point = Some(self.dpi);
        let mut metrics = None;
        let mut output = self.ctx.run_ui(input, |ui| metrics = Some(app.render(ui)));
        self.frame_number += 1;
        for (id, deltas) in output.textures_delta.set.drain() {
            for delta in deltas {
                let egui::ImageData::Color(image) = delta.image;
                if let Some([x, y]) = delta.pos {
                    let texture = self
                        .textures
                        .get_mut(&id)
                        .expect("partial update requires a known texture");
                    assert!(
                        x + image.size[0] <= texture.size[0]
                            && y + image.size[1] <= texture.size[1]
                    );
                    for row in 0..image.size[1] {
                        let start = (y + row) * texture.size[0] + x;
                        texture.pixels[start..start + image.size[0]].copy_from_slice(
                            &image.pixels[row * image.size[0]..(row + 1) * image.size[0]],
                        );
                    }
                } else {
                    self.textures.insert(id, (*image).clone());
                }
            }
        }
        // Our captures need only textures present in this frame. egui currently uses
        // the persistent font atlas; free requests must still be acknowledged.
        output.textures_delta.free.clear();
        (metrics.unwrap(), output)
    }
    fn capture(&self, output: FullOutput, path: &Path) {
        // Limit optional PNG artifacts without skipping a render or assertion.
        if let Ok(filter) = std::env::var("MECHREVO_GUI_CAPTURE_MATCH") {
            let patterns: Vec<_> = filter
                .split(',')
                .map(str::trim)
                .filter(|pattern| !pattern.is_empty())
                .collect();
            let filename = path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("");
            if !patterns.is_empty() && !patterns.iter().any(|pattern| filename.contains(pattern)) {
                return;
            }
        }
        let [width, height] = self.physical;
        let mut pixels = vec![[27, 29, 34, 255]; (width * height) as usize];
        for primitive in self.ctx.tessellate(output.shapes, output.pixels_per_point) {
            let egui::epaint::Primitive::Mesh(mesh) = primitive.primitive else {
                panic!("headless renderer does not accept GPU callbacks");
            };
            let texture = self
                .textures
                .get(&mesh.texture_id)
                .expect("mesh texture must be uploaded");
            let clip = primitive.clip_rect * output.pixels_per_point;
            for triangle in mesh.indices.as_chunks::<3>().0 {
                let v = [
                    mesh.vertices[triangle[0] as usize],
                    mesh.vertices[triangle[1] as usize],
                    mesh.vertices[triangle[2] as usize],
                ];
                let p = v.map(|v| v.pos * output.pixels_per_point);
                let cross = |a: egui::Pos2, b: egui::Pos2, c: egui::Pos2| {
                    (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
                };
                let area = cross(p[0], p[1], p[2]);
                if area.abs() < 0.00001 {
                    continue;
                }
                let min_x = p
                    .iter()
                    .map(|p| p.x)
                    .fold(f32::INFINITY, f32::min)
                    .max(clip.min.x)
                    .max(0.0)
                    .floor() as u32;
                let min_y = p
                    .iter()
                    .map(|p| p.y)
                    .fold(f32::INFINITY, f32::min)
                    .max(clip.min.y)
                    .max(0.0)
                    .floor() as u32;
                let max_x = p
                    .iter()
                    .map(|p| p.x)
                    .fold(f32::NEG_INFINITY, f32::max)
                    .min(clip.max.x)
                    .min(width as f32)
                    .ceil()
                    .max(0.0) as u32;
                let max_y = p
                    .iter()
                    .map(|p| p.y)
                    .fold(f32::NEG_INFINITY, f32::max)
                    .min(clip.max.y)
                    .min(height as f32)
                    .ceil()
                    .max(0.0) as u32;
                for y in min_y..max_y {
                    for x in min_x..max_x {
                        let sample = pos2(x as f32 + 0.5, y as f32 + 0.5);
                        if !clip.contains(sample) {
                            continue;
                        }
                        let weights = [
                            cross(p[1], p[2], sample) / area,
                            cross(p[2], p[0], sample) / area,
                            cross(p[0], p[1], sample) / area,
                        ];
                        if weights.iter().any(|w| *w < -0.00001) {
                            continue;
                        }
                        let u = (0..3).map(|i| weights[i] * v[i].uv.x).sum::<f32>();
                        let t = (0..3).map(|i| weights[i] * v[i].uv.y).sum::<f32>();
                        let texel = sample_texture(texture, u, t);
                        let mut color = [0.0; 4];
                        for (channel, out) in color.iter_mut().enumerate() {
                            *out = (0..3)
                                .map(|i| weights[i] * v[i].color.to_array()[channel] as f32 / 255.0)
                                .sum::<f32>()
                                * texel[channel];
                        }
                        let target = &mut pixels[(y * width + x) as usize];
                        for channel in 0..3 {
                            target[channel] = ((color[channel]
                                + target[channel] as f32 / 255.0 * (1.0 - color[3]))
                                * 255.0)
                                .round()
                                .clamp(0.0, 255.0)
                                as u8;
                        }
                    }
                }
            }
        }
        write_png(path, width, height, &pixels);
    }
}
fn sample_texture(image: &ColorImage, u: f32, v: f32) -> [f32; 4] {
    let x = (u * image.size[0] as f32 - 0.5).clamp(0.0, (image.size[0] - 1) as f32);
    let y = (v * image.size[1] as f32 - 0.5).clamp(0.0, (image.size[1] - 1) as f32);
    let x0 = x.floor() as usize;
    let y0 = y.floor() as usize;
    let x1 = (x0 + 1).min(image.size[0] - 1);
    let y1 = (y0 + 1).min(image.size[1] - 1);
    let get = |x: usize, y: usize| {
        image.pixels[y * image.size[0] + x]
            .to_array()
            .map(|c| c as f32 / 255.0)
    };
    let a = get(x0, y0);
    let b = get(x1, y0);
    let c = get(x0, y1);
    let d = get(x1, y1);
    std::array::from_fn(|i| {
        (a[i] * (1.0 - x.fract()) + b[i] * x.fract()) * (1.0 - y.fract())
            + (c[i] * (1.0 - x.fract()) + d[i] * x.fract()) * y.fract()
    })
}

// @mark mechrevo.console_ui role=verification
#[test]
fn responsive_layout_and_last_action_are_accessible_at_every_dpi() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let capture = std::env::var_os("MECHREVO_GUI_CAPTURE_DIR").map(std::path::PathBuf::from);
    if let Some(path) = &capture {
        std::fs::create_dir_all(path).unwrap();
    }
    let mut verified = 0;
    for dpi in [1.0, 1.25, 1.5, 2.0] {
        for logical in [[360, 280], [800, 600]] {
            // Native window minimum sizes are logical OS pixels; the monitor DPI
            // converts these to physical pixels independently of the text zoom.
            let physical = [
                (logical[0] as f32 * dpi).round() as u32,
                (logical[1] as f32 * dpi).round() as u32,
            ];
            for case in [
                "long_names",
                "multi_gpu",
                "error",
                "unavailable",
                "large_compact",
            ] {
                let label = format!(
                    "logical{}x{}-physical{}x{}-dpi{}-{case}",
                    logical[0],
                    logical[1],
                    physical[0],
                    physical[1],
                    (dpi * 100.0) as u32
                );
                let mut app = fixture(case);
                let mut harness = Harness::new(physical, dpi, fonts.clone());
                assert_layout(&label, &mut app, &mut harness, capture.as_deref(), true);
                verified += 1;
            }
            for case in [
                "settings_open",
                "sensor_sources",
                "catalog",
                "empty_dashboard",
                "empty_sensors",
            ] {
                let label = format!(
                    "logical{}x{}-physical{}x{}-dpi{}-{case}",
                    logical[0],
                    logical[1],
                    physical[0],
                    physical[1],
                    (dpi * 100.0) as u32
                );
                let mut app = fixture(match case {
                    "sensor_sources" => "multi_gpu",
                    "empty_dashboard" | "empty_sensors" => "no_telemetry",
                    _ => "long_names",
                });
                match case {
                    "settings_open" => {
                        app.preferences.text_scale = 1.6;
                        app.open_display_settings();
                    }
                    "sensor_sources" | "empty_sensors" => app.select_section(Section::Sensors),
                    "catalog" => app.select_section(Section::Catalog),
                    "empty_dashboard" => {}
                    _ => unreachable!(),
                }
                let mut harness = Harness::new(physical, dpi, fonts.clone());
                if case == "sensor_sources" {
                    assert_source_details_expand(&label, &mut app, &mut harness);
                }
                assert_layout(&label, &mut app, &mut harness, capture.as_deref(), false);
                verified += 1;
            }
        }
    }
    assert_eq!(verified, 80);
    println!("Verified {verified} rendered layouts: 4 DPI scales x 2 logical window sizes (native physical pixels = logical size x DPI) x 10 states/views; Chinese missing-glyph policy=Panic; long source paths wrap; empty telemetry is safe; last marker reachable.");
}

#[test]
fn light_theme_and_representative_desktop_views_remain_accessible() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let capture = std::env::var_os("MECHREVO_GUI_CAPTURE_DIR").map(std::path::PathBuf::from);
    if let Some(path) = &capture {
        std::fs::create_dir_all(path).unwrap();
    }
    let mut verified = 0;
    for (theme, name) in [(Theme::Dark, "dark"), (Theme::Light, "light")] {
        for (section, view) in [
            (Section::Dashboard, "dashboard"),
            (Section::Sensors, "sensors"),
            (Section::Catalog, "catalog"),
        ] {
            let mut app = fixture("representative");
            app.preferences.theme = theme;
            app.select_section(section);
            let mut harness = Harness::new([1120, 760], 1.0, fonts.clone());
            assert_layout(
                &format!("desktop1120x760-{name}-{view}"),
                &mut app,
                &mut harness,
                capture.as_deref(),
                false,
            );
            assert_eq!(
                harness.ctx.global_style().visuals.dark_mode,
                theme == Theme::Dark
            );
            verified += 1;
        }
    }
    for dpi in [1.0, 1.25, 1.5, 2.0] {
        for (case, scale) in [("long_names", 1.0), ("large_compact", 1.6)] {
            let mut app = fixture(case);
            app.preferences.theme = Theme::Light;
            let mut harness = Harness::new(
                [(360.0 * dpi) as u32, (280.0 * dpi) as u32],
                dpi,
                fonts.clone(),
            );
            assert_layout(
                &format!(
                    "light-minimum-dpi{}-text{}",
                    (dpi * 100.0) as u32,
                    (scale * 100.0) as u32
                ),
                &mut app,
                &mut harness,
                capture.as_deref(),
                true,
            );
            assert!(!harness.ctx.global_style().visuals.dark_mode);
            verified += 1;
        }
    }
    assert_eq!(verified, 14);
    println!("Verified {verified} additional layouts: six 1120x760 desktop views in dark/light themes and eight minimum-window light-theme DPI/text-size combinations; actual bundled display/number fonts and Chinese fallback rendered under missing-glyph Panic.");
}

fn accessible_control(
    output: &FullOutput,
    label: &str,
    role: egui::accesskit::Role,
) -> (egui::accesskit::NodeId, Rect) {
    let update = output.platform_output.accesskit_update.as_ref().unwrap();
    let (id, node) = update
        .nodes
        .iter()
        .find(|(_, node)| node.role() == role && node.label() == Some(label))
        .unwrap_or_else(|| panic!("Accessible {role:?} '{label}' is missing"));
    let bounds = node.bounds().expect("interactive control needs bounds");
    (
        *id,
        Rect::from_min_max(
            pos2(bounds.x0 as f32, bounds.y0 as f32),
            pos2(bounds.x1 as f32, bounds.y1 as f32),
        ),
    )
}

fn click(harness: &mut Harness, app: &mut DesktopApp, position: egui::Pos2) -> FullOutput {
    harness.frame_with_events(
        app,
        vec![
            egui::Event::PointerMoved(position),
            egui::Event::PointerButton {
                pos: position,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: egui::Modifiers::NONE,
            },
        ],
    );
    harness.frame_with_events(
        app,
        vec![egui::Event::PointerButton {
            pos: position,
            button: egui::PointerButton::Primary,
            pressed: false,
            modifiers: egui::Modifiers::NONE,
        }],
    );
    harness.frame(app).1
}

fn key(harness: &mut Harness, app: &mut DesktopApp, key: egui::Key) -> FullOutput {
    for pressed in [true, false] {
        harness.frame_with_events(
            app,
            vec![egui::Event::Key {
                key,
                physical_key: None,
                pressed,
                repeat: false,
                modifiers: egui::Modifiers::NONE,
            }],
        );
    }
    harness.frame(app).1
}

fn assert_page_title(output: &FullOutput, title: &str) {
    assert!(
        output
            .platform_output
            .accesskit_update
            .as_ref()
            .unwrap()
            .nodes
            .iter()
            .any(|(_, node)| node.role() == egui::accesskit::Role::Label
                && node.value() == Some(title)),
        "navigation did not render the requested page heading '{title}'"
    );
}

fn rendered_shapes(output: &FullOutput) -> Vec<&egui::Shape> {
    fn collect<'a>(shape: &'a egui::Shape, leaves: &mut Vec<&'a egui::Shape>) {
        match shape {
            egui::Shape::Vec(shapes) => {
                for shape in shapes {
                    collect(shape, leaves);
                }
            }
            _ => leaves.push(shape),
        }
    }
    let mut leaves = Vec::new();
    for shape in &output.shapes {
        collect(&shape.shape, &mut leaves);
    }
    leaves
}

fn rendered_text(output: &FullOutput) -> Vec<&egui::epaint::TextShape> {
    rendered_shapes(output)
        .into_iter()
        .filter_map(|shape| match shape {
            egui::Shape::Text(text) => Some(text),
            _ => None,
        })
        .collect()
}

fn has_visible_text(output: &FullOutput, value: &str) -> bool {
    rendered_text(output)
        .iter()
        .any(|shape| shape.galley.job.text == value)
}

fn settle(harness: &mut Harness, app: &mut DesktopApp) -> (RenderMetrics, FullOutput) {
    for _ in 0..3 {
        harness.frame(app);
    }
    harness.frame(app)
}

fn set_sample(app: &mut DesktopApp, time: Instant, cpu: f64, gpu: Option<f64>) {
    app.controller.last_refresh = Some(time);
    for reading in &mut app.controller.snapshot.as_mut().unwrap().telemetry {
        match reading.id.as_str() {
            "cpu_temp" => reading.value = Some(cpu),
            // A wholly unavailable GPU must never leave a stale chart endpoint.
            "gpu0_temp" | "gpu1_temp" => reading.value = gpu,
            _ => {}
        }
    }
}

#[test]
fn trend_requires_real_samples_and_labels_elapsed_time_and_current_endpoints() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = fixture("representative");
    app.preferences.auto_refresh = false;
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let start = Instant::now() - Duration::from_secs(120);

    set_sample(&mut app, start, 61.0, Some(47.0));
    let (_, output) = settle(&mut harness, &mut app);
    assert!(has_visible_text(&output, "正在积累趋势"));
    assert!(
        rendered_text(&output)
            .iter()
            .any(|shape| shape.galley.job.text.contains("手动更新")),
        "manual sampling should describe the collected state without a frozen relative age"
    );
    // settle renders the same observation four times. Repaints are not samples.
    assert!(!has_visible_text(&output, "最近 0 秒"));

    set_sample(&mut app, start + Duration::from_secs(3), 64.0, Some(49.0));
    let (_, output) = settle(&mut harness, &mut app);
    assert!(
        has_visible_text(&output, "正在积累趋势"),
        "two observations should not present an almost empty line as a mature trend"
    );
    assert!(!has_visible_text(&output, "最近 3 秒"));

    set_sample(&mut app, start + Duration::from_secs(6), 68.0, Some(52.0));
    let (_, output) = settle(&mut harness, &mut app);
    assert!(!has_visible_text(&output, "正在积累趋势"));
    for label in ["最近 6 秒", "CPU 68°C", "GPU 52°C"] {
        assert!(
            has_visible_text(&output, label),
            "missing trend label '{label}'"
        );
        assert_page_title(&output, label);
    }

    set_sample(&mut app, start + Duration::from_secs(65), 66.0, None);
    let (_, output) = settle(&mut harness, &mut app);
    for label in ["最近 1 分 05 秒", "CPU 66°C", "GPU —"] {
        assert!(
            has_visible_text(&output, label),
            "missing updated trend label '{label}'"
        );
    }
    assert!(!has_visible_text(&output, "GPU 52°C"));

    // A different device begins a new history, even if its sensor IDs match.
    app.controller
        .snapshot
        .as_mut()
        .unwrap()
        .identity
        .product_name = Some("另一台测试设备".into());
    let (_, output) = settle(&mut harness, &mut app);
    assert!(has_visible_text(&output, "正在积累趋势"));
    assert!(!has_visible_text(&output, "最近 1 分 05 秒"));
}

#[test]
fn temperature_digits_and_unit_do_not_shift_between_equal_length_readings() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = fixture("representative");
    app.preferences.auto_refresh = false;
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let start = Instant::now() - Duration::from_secs(60);
    let mut reference: Option<(Rect, f32)> = None;
    for (sample, value) in [11.0, 22.0, 88.0, 99.0].into_iter().enumerate() {
        set_sample(
            &mut app,
            start + Duration::from_secs(sample as u64 * 3),
            value,
            Some(49.0),
        );
        let (_, output) = settle(&mut harness, &mut app);
        let text = rendered_text(&output);
        let value = format!("{value:.0}");
        let number = text
            .iter()
            .find(|shape| {
                shape.galley.job.text == value
                    && shape
                        .galley
                        .job
                        .sections
                        .iter()
                        .any(|section| section.format.font_id.size >= 40.0)
            })
            .expect("the actual primary temperature must remain a large, visible reading");
        let bounds = number.galley.rect.translate(number.pos.to_vec2());
        let unit = text
            .iter()
            .filter(|shape| shape.galley.job.text == "°C" && shape.pos.x >= bounds.right())
            .min_by(|a, b| {
                a.pos
                    .distance_sq(bounds.center())
                    .total_cmp(&b.pos.distance_sq(bounds.center()))
            })
            .expect("the temperature unit should sit beside its value");
        if let Some((previous, unit_x)) = reference {
            assert!(
                (bounds.width() - previous.width()).abs() <= 0.1
                    && (bounds.left() - previous.left()).abs() <= 0.1
                    && (unit.pos.x - unit_x).abs() <= 0.1,
                "equal-length readings shift the numeric width or unit: {value}, previous={previous:?}, current={bounds:?}, unit {unit_x} -> {}",
                unit.pos.x
            );
        } else {
            reference = Some((bounds, unit.pos.x));
        }
    }
}

#[test]
fn auto_sampling_switch_exposes_state_and_accepts_pointer_and_keyboard() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = fixture("representative");
    app.preferences.auto_refresh = false;
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let (_, mut output) = settle(&mut harness, &mut app);
    let (switch_id, bounds) =
        accessible_control(&output, "自动采样", egui::accesskit::Role::Switch);
    assert!(Rect::from_min_size(pos2(0.0, 0.0), vec2(1120.0, 760.0)).contains_rect(bounds));
    let assert_state = |output: &FullOutput, enabled| {
        let (_, node) = output
            .platform_output
            .accesskit_update
            .as_ref()
            .unwrap()
            .nodes
            .iter()
            .find(|(id, _)| *id == switch_id)
            .expect("sampling switch must stay in the accessibility tree");
        assert_eq!(
            node.toggled(),
            Some(if enabled {
                egui::accesskit::Toggled::True
            } else {
                egui::accesskit::Toggled::False
            })
        );
    };
    assert_state(&output, false);
    output = click(&mut harness, &mut app, bounds.center());
    assert!(app.preferences.auto_refresh);
    assert_state(&output, true);

    let mut focused = false;
    for _ in 0..24 {
        output = key(&mut harness, &mut app, egui::Key::Tab);
        if output
            .platform_output
            .accesskit_update
            .as_ref()
            .unwrap()
            .focus
            == switch_id
        {
            focused = true;
            break;
        }
    }
    assert!(focused, "keyboard focus never reached the sampling switch");
    output = key(&mut harness, &mut app, egui::Key::Space);
    assert!(!app.preferences.auto_refresh);
    assert_state(&output, false);
}

fn oem_edits() -> [(&'static str, OemValue); 4] {
    [
        ("fn_lock", OemValue::Boolean(true)),
        ("charging_profile", OemValue::Choice("stationary".into())),
        ("keyboard_brightness", OemValue::Level(3)),
        ("keyboard_color", OemValue::Rgb([12, 80, 230])),
    ]
}

fn reveal_oem_control(
    harness: &mut Harness,
    app: &mut DesktopApp,
    label: &str,
    role: egui::accesskit::Role,
) -> (RenderMetrics, FullOutput) {
    // The application's bottom request uses its last measured content size.
    // A fresh app has no such measurement yet; establish layout first.
    settle(harness, app);
    app.scroll_to_bottom();
    let (mut metrics, mut output) = settle(harness, app);
    let mut scroll_trace = Vec::new();
    // A full dashboard is taller than one editor at 160% zoom. Keep the
    // reachability check bounded while allowing its longer real scroll path.
    for _ in 0..32 {
        let (id, bounds) = accessible_control(&output, label, role);
        scroll_trace.push(format!(
            "offset={:?}, viewport={:?}, control={bounds:?}",
            metrics.scroll_offset, metrics.viewport
        ));
        if metrics.viewport.expand(1.0).contains_rect(bounds) {
            let (_, node) = output
                .platform_output
                .accesskit_update
                .as_ref()
                .unwrap()
                .nodes
                .iter()
                .find(|(node_id, _)| *node_id == id)
                .unwrap();
            assert!(
                !node.is_disabled(),
                "OEM control '{label}' should be enabled"
            );
            return (metrics, output);
        }
        // At maximum text zoom the informational footer can fill much of the
        // viewport. Exercise real wheel input to reveal the actual action,
        // rather than assuming that reaching the footer proves it is usable.
        harness.frame_with_events(
            app,
            vec![
                egui::Event::PointerMoved(metrics.viewport.center()),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    delta: vec2(
                        0.0,
                        (metrics.viewport.center().y - bounds.center().y).clamp(-200.0, 200.0),
                    ),
                    phase: egui::TouchPhase::Move,
                    source: egui::MouseWheelSource::Unknown,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
        (metrics, output) = settle(harness, app);
    }
    panic!("OEM control '{label}' remained clipped after bounded scrolling: {scroll_trace:?}");
}

fn assert_oem_editor(output: &FullOutput, id: &str) {
    let nodes = &output
        .platform_output
        .accesskit_update
        .as_ref()
        .unwrap()
        .nodes;
    match id {
        "fn_lock" => {
            let (id, _) = accessible_control(output, "目标状态", egui::accesskit::Role::CheckBox);
            let (_, node) = nodes.iter().find(|(node_id, _)| *node_id == id).unwrap();
            assert_eq!(node.toggled(), Some(egui::accesskit::Toggled::True));
        }
        "charging_profile" => {
            assert_page_title(output, "目标模式");
            let (id, _) = accessible_control(output, "长期接电", egui::accesskit::Role::Button);
            let (_, node) = nodes.iter().find(|(node_id, _)| *node_id == id).unwrap();
            assert_eq!(node.toggled(), Some(egui::accesskit::Toggled::True));
        }
        "keyboard_brightness" => {
            assert!(nodes.iter().any(|(_, node)| {
                node.role() == egui::accesskit::Role::Slider
                    && node.numeric_value() == Some(3.0)
                    && node.max_numeric_value() == Some(4.0)
            }));
        }
        "keyboard_color" => {
            for label in ["红", "绿", "蓝"] {
                assert_page_title(output, label);
            }
            for value in [12.0, 80.0, 230.0] {
                assert!(nodes.iter().any(|(_, node)| {
                    node.role() == egui::accesskit::Role::SpinButton
                        && node.numeric_value() == Some(value)
                        && node.min_numeric_value() == Some(0.0)
                        && node.max_numeric_value() == Some(255.0)
                }));
            }
        }
        _ => unreachable!(),
    }
}

#[test]
fn oem_controls_wrap_at_every_dpi_and_keep_real_preview_actions_reachable() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let capture = std::env::var_os("MECHREVO_GUI_CAPTURE_DIR").map(std::path::PathBuf::from);
    if let Some(path) = &capture {
        std::fs::create_dir_all(path).unwrap();
    }
    let mut verified = 0;
    for dpi in [1.0, 1.25, 1.5, 2.0] {
        for (id, target) in oem_edits() {
            let mut app = oem_fixture();
            if dpi == 2.0 {
                app.preferences.text_scale = 1.6;
            }
            if dpi == 1.5 {
                app.preferences.theme = Theme::Light;
            }
            app.controller.select_oem_control(id);
            app.controller.set_oem_target(target.clone());
            let mut harness = Harness::new(
                [(360.0 * dpi) as u32, (280.0 * dpi) as u32],
                dpi,
                fonts.clone(),
            );
            let label = format!("oem-minimum-dpi{}-{id}", (dpi * 100.0) as u32);
            assert_layout(&label, &mut app, &mut harness, capture.as_deref(), true);
            let (metrics, output) = reveal_oem_control(
                &mut harness,
                &mut app,
                "预览更改",
                egui::accesskit::Role::Button,
            );
            assert_width(&label, &metrics);
            assert_client_bounds(&label, &metrics, harness.physical, output.pixels_per_point);
            assert_eq!(app.controller.selected_oem_control.as_deref(), Some(id));
            assert_eq!(app.controller.requested_oem_value, Some(target));
            assert!(app.controller.oem_preview.is_none());
            assert!(
                !app.controller.busy(),
                "layout and editing must not submit a backend job"
            );
            verified += 1;
        }
    }
    for (id, target) in oem_edits() {
        let mut app = oem_fixture();
        app.controller.select_oem_control(id);
        app.controller.set_oem_target(target);
        let mut harness = Harness::new([1120, 760], 1.0, fonts.clone());
        let (_, mut output) = settle(&mut harness, &mut app);
        assert_page_title(&output, "设备控制");
        assert_oem_editor(&output, id);
        if id == "charging_profile" {
            assert_eq!(
                app.controller.requested_oem_value,
                Some(OemValue::Choice("stationary".into())),
                "localized display labels must preserve the driver's typed choice value"
            );
        }
        if id == "fn_lock" {
            let (_, toggle) =
                accessible_control(&output, "目标状态", egui::accesskit::Role::CheckBox);
            output = click(&mut harness, &mut app, toggle.center());
            assert_eq!(
                app.controller.requested_oem_value,
                Some(OemValue::Boolean(false)),
                "editing the visible Boolean must update the typed request"
            );
            let (_, toggle) =
                accessible_control(&output, "目标状态", egui::accesskit::Role::CheckBox);
            output = click(&mut harness, &mut app, toggle.center());
            assert_oem_editor(&output, id);
            let last_label = app
                .controller
                .snapshot
                .as_ref()
                .unwrap()
                .oem_controls
                .last()
                .unwrap()
                .label
                .clone();
            let (_, selector) =
                accessible_control(&output, &last_label, egui::accesskit::Role::Button);
            click(&mut harness, &mut app, selector.center());
            assert_eq!(
                app.controller.selected_oem_control.as_deref(),
                Some("usb_power_share")
            );
            assert_eq!(
                app.controller.requested_oem_value,
                Some(OemValue::Boolean(false))
            );
            assert!(!app.controller.busy());
            app.controller.select_oem_control(id);
            app.controller.set_oem_target(OemValue::Boolean(true));
        }
        assert_layout(
            &format!("oem-desktop-{id}"),
            &mut app,
            &mut harness,
            capture.as_deref(),
            false,
        );
        reveal_oem_control(
            &mut harness,
            &mut app,
            "预览更改",
            egui::accesskit::Role::Button,
        );
        verified += 1;
    }
    let mut app = oem_fixture();
    app.preferences.text_scale = 1.6;
    app.controller.select_oem_control("usb_power_share");
    app.controller.set_oem_target(OemValue::Boolean(true));
    let control = app.controller.selected_oem().unwrap().clone();
    app.controller.oem_preview = Some(OemPlan {
        control_id: control.id,
        kind: control.kind,
        label: control.label,
        previous: control.current.unwrap(),
        target: OemValue::Boolean(true),
        domain: control.domain,
        source: control.source,
        binding: control.binding,
        readback_scope: control.readback_scope,
        requires_privilege: true,
        companion_brightness: None,
    });
    let mut harness = Harness::new([720, 560], 2.0, fonts);
    let (_, output) = reveal_oem_control(
        &mut harness,
        &mut app,
        "接口详情",
        egui::accesskit::Role::DisclosureTriangle,
    );
    let (details_id, details) = accessible_control(
        &output,
        "接口详情",
        egui::accesskit::Role::DisclosureTriangle,
    );
    let output = click(&mut harness, &mut app, details.center());
    let (_, node) = output
        .platform_output
        .accesskit_update
        .as_ref()
        .unwrap()
        .nodes
        .iter()
        .find(|(id, _)| *id == details_id)
        .unwrap();
    assert_eq!(node.is_expanded(), Some(true));
    let (metrics, output) = reveal_oem_control(
        &mut harness,
        &mut app,
        "应用并回读",
        egui::accesskit::Role::Button,
    );
    assert_width("oem-expanded-details-and-apply", &metrics);
    assert_client_bounds(
        "oem-expanded-details-and-apply",
        &metrics,
        harness.physical,
        output.pixels_per_point,
    );
    assert!(app.controller.oem_preview.is_some());
    assert!(!app.controller.busy());
    verified += 1;
    assert_eq!(verified, 21);
    println!("Verified {verified} OEM layouts with six actual fixture controls: all four value domains, four minimum-window DPI scales, 160% text, light theme, and actual preview-action reachability; rendering and editing submit no backend request.");
}

#[test]
fn unavailable_oem_controls_and_empty_inventory_cannot_offer_a_write() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    for status in [CapabilityStatus::Unavailable, CapabilityStatus::Unsupported] {
        let mut app = oem_fixture();
        app.controller.select_oem_control("usb_power_share");
        let control = app
            .controller
            .snapshot
            .as_mut()
            .unwrap()
            .oem_controls
            .last_mut()
            .unwrap();
        control.status = status;
        control.current = None;
        control.writable = false;
        control.reason = Some("测试接口当前不可用，未进行任何硬件写入。".into());
        let mut harness = Harness::new([360, 280], 1.0, fonts.clone());
        assert_layout("oem-unavailable", &mut app, &mut harness, None, true);
        let (_, output) = settle(&mut harness, &mut app);
        assert!(app.controller.oem_unavailable_reason().is_some());
        assert!(!output
            .platform_output
            .accesskit_update
            .as_ref()
            .unwrap()
            .nodes
            .iter()
            .any(|(_, node)| {
                node.role() == egui::accesskit::Role::Button
                    && matches!(node.label(), Some("预览更改" | "应用并回读"))
                    && !node.is_disabled()
            }));
        assert!(!app.controller.busy());
    }
    let mut app = fixture("no_telemetry");
    app.select_section(Section::Controls);
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let (_, output) = settle(&mut harness, &mut app);
    assert_page_title(&output, "未发现 OEM 控制接口");
    assert!(app.controller.selected_oem_control.is_none());
    assert!(app.controller.oem_unavailable_reason().is_some());
    assert!(!app.controller.busy());
}

#[test]
fn overview_gives_compact_space_to_real_device_readings() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    for physical in [[1120, 760], [1280, 720]] {
        let mut app = fixture("representative");
        let snapshot = app.controller.snapshot.as_mut().unwrap();
        for (id, label, value) in [
            ("cpu_fan", "mechrevo_ec: CPU Fan", 2600.0),
            ("gpu_fan", "mechrevo_ec: GPU Fan", 3800.0),
        ] {
            snapshot.telemetry.push(
                serde_json::from_value(json!({
                    "id":id, "label":label, "device_id":"fixture-fans", "kind":"fan_speed",
                    "value":value, "unit":"RPM", "status":"available", "reason":null,
                    "source":{"backend":"fixture-only", "path":"fixture://fans", "device_id":"fixture-fans"}
                }))
                .unwrap(),
            );
        }
        let mut harness = Harness::new(physical, 1.0, fonts.clone());
        let (metrics, output) = settle(&mut harness, &mut app);
        assert_page_title(&output, "设备概览");
        let text = rendered_text(&output);
        let title = text
            .iter()
            .find(|shape| shape.galley.job.text == "设备概览")
            .unwrap();
        assert!(title
            .galley
            .job
            .sections
            .iter()
            .all(|section| { (32.0..=36.0).contains(&section.format.font_id.size) }));
        assert!(
            metrics.heading_rect.is_finite() && metrics.heading_rect.height() <= 80.0,
            "device heading consumes the compact overview: {:?}",
            metrics.heading_rect
        );
        let panel = metrics.thermal_panel_rect;
        assert!(
            panel.is_finite() && (240.0..=290.0).contains(&panel.height()),
            "thermal card with two actual fan readings is no longer compact: {panel:?}"
        );
        let (_, navigation) = accessible_control(&output, "概览", egui::accesskit::Role::Button);
        assert!(
            panel.top() - navigation.bottom() <= 132.0,
            "too much space between navigation and device readings: {}",
            panel.top() - navigation.bottom()
        );
        for label in ["CPU", "GPU", "2600", "3800"] {
            assert!(
                has_visible_text(&output, label),
                "reading '{label}' disappeared"
            );
        }
        // Compactness must not be achieved by reducing the key readings to body text.
        for value in ["64", "49"] {
            assert!(text.iter().any(|shape| {
                shape.galley.job.text == value
                    && shape
                        .galley
                        .job
                        .sections
                        .iter()
                        .any(|section| section.format.font_id.size >= 40.0)
            }));
        }
        let label_bounds = |value: &str| {
            let shape = text
                .iter()
                .find(|shape| shape.galley.job.text == value)
                .unwrap();
            shape.galley.rect.translate(shape.pos.to_vec2())
        };
        let shapes = rendered_shapes(&output);
        let heading_card = |heading: Rect| {
            shapes
                .iter()
                .filter_map(|shape| match shape {
                    egui::Shape::Rect(rect)
                        if rect.fill.a() > 0
                            && rect.rect.width() >= 200.0
                            && rect.rect.height() >= 70.0
                            && rect.rect.contains_rect(heading) =>
                    {
                        Some(rect.rect)
                    }
                    _ => None,
                })
                .min_by(|a, b| a.area().total_cmp(&b.area()))
                .expect("control heading must belong to a painted card")
        };
        let power_heading = label_bounds("系统电源策略");
        let brightness_heading = label_bounds("屏幕亮度");
        let power_card = heading_card(power_heading);
        let brightness_card = heading_card(brightness_heading);
        let card_gap = brightness_card.left() - power_card.right();
        assert!(
            (12.0..=24.0).contains(&card_gap),
            "independent control cards must have visible breathing room: power={power_card:?}, brightness={brightness_card:?}, gap={card_gap}"
        );
        let cpu = label_bounds("64");
        let gpu = label_bounds("49");
        let cpu_fan = label_bounds("2600");
        let gpu_fan = label_bounds("3800");
        for (fan, own, other) in [(cpu_fan, cpu, gpu), (gpu_fan, gpu, cpu)] {
            assert!(
                fan.top() >= own.bottom()
                    && (fan.center().x - own.center().x).abs()
                        < (fan.center().x - other.center().x).abs(),
                "a named fan should be beside its own component, not grouped under the other one"
            );
        }
        println!(
            "Compact overview {}x{}: heading {:.1}px, thermal card {:.1}px, navigation-to-card {:.1}px, control-card gap {:.1}px; named fan readings belong to their components.",
            physical[0],
            physical[1],
            metrics.heading_rect.height(),
            panel.height(),
            panel.top() - navigation.bottom(),
            card_gap
        );

        // A generic index provides no CPU/GPU ownership. Its reading stays on
        // a separate row rather than being assigned by order or numeric ID.
        app.controller.snapshot.as_mut().unwrap().telemetry.push(
            serde_json::from_value(json!({
                "id":"fan3", "label":"System fan 3", "device_id":"fixture-fans", "kind":"fan_speed",
                "value":1700.0, "unit":"RPM", "status":"available", "reason":null,
                "source":{"backend":"fixture-only", "path":"fixture://fans/3", "device_id":"fixture-fans"}
            }))
            .unwrap(),
        );
        let (_, output) = settle(&mut harness, &mut app);
        let text = rendered_text(&output);
        let generic = text
            .iter()
            .find(|shape| shape.galley.job.text == "1700")
            .expect("unassigned fan reading must remain visible");
        assert!(has_visible_text(&output, "System fan 3"));
        assert!(
            generic.pos.y > cpu_fan.bottom().max(gpu_fan.bottom()),
            "an unassigned fan was presented as a CPU/GPU fan"
        );
    }
}

fn assert_selected_navigation(output: &FullOutput, selected: &str) {
    let nodes = &output
        .platform_output
        .accesskit_update
        .as_ref()
        .unwrap()
        .nodes;
    for label in ["概览", "传感器", "控制", "型号目录"] {
        let (_, node) = nodes
            .iter()
            .find(|(_, node)| {
                node.role() == egui::accesskit::Role::Button && node.label() == Some(label)
            })
            .unwrap();
        assert_eq!(
            node.toggled(),
            Some(if label == selected {
                egui::accesskit::Toggled::True
            } else {
                egui::accesskit::Toggled::False
            }),
            "navigation must expose its current page to assistive technology: '{label}'"
        );
    }
}

#[test]
fn wrapped_navigation_accepts_pointer_and_keyboard_at_minimum_window_size() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    for dpi in [1.0, 2.0] {
        for text_scale in [1.0, 1.6] {
            let physical = [(360.0 * dpi) as u32, (280.0 * dpi) as u32];
            let mut app = fixture("representative");
            app.preferences.text_scale = text_scale;
            let mut harness = Harness::new(physical, dpi, fonts.clone());
            let mut output = harness.frame(&mut app).1;
            for _ in 0..3 {
                output = harness.frame(&mut app).1;
            }
            let client = Rect::from_min_size(
                pos2(0.0, 0.0),
                vec2(
                    physical[0] as f32 / output.pixels_per_point,
                    physical[1] as f32 / output.pixels_per_point,
                ),
            );
            let mut bounds = Vec::new();
            for label in ["概览", "传感器", "控制", "型号目录"] {
                let (_, rect) = accessible_control(&output, label, egui::accesskit::Role::Button);
                assert!(client.expand(1.0).contains_rect(rect), "DPI={dpi} text={text_scale}: navigation '{label}' is clipped: {rect:?} outside {client:?}");
                assert!(
                    bounds
                        .iter()
                        .all(|previous: &Rect| !previous.intersects(rect)),
                    "wrapped navigation buttons overlap"
                );
                bounds.push(rect);
            }
            // These are pointer events at actual accessible button bounds, not a
            // direct mutation of the section field or a synthetic click result.
            for label in ["型号目录", "控制", "传感器", "概览"] {
                let (_, rect) = accessible_control(&output, label, egui::accesskit::Role::Button);
                output = click(&mut harness, &mut app, rect.center());
                assert_selected_navigation(&output, label);
            }
            let (sensor_id, _) =
                accessible_control(&output, "传感器", egui::accesskit::Role::Button);
            let mut focused_sensor = false;
            for _ in 0..24 {
                output = key(&mut harness, &mut app, egui::Key::Tab);
                if output
                    .platform_output
                    .accesskit_update
                    .as_ref()
                    .unwrap()
                    .focus
                    == sensor_id
                {
                    focused_sensor = true;
                    break;
                }
            }
            assert!(
                focused_sensor,
                "DPI={dpi} text={text_scale}: keyboard focus never reached sensor navigation"
            );
            output = key(&mut harness, &mut app, egui::Key::Enter);
            assert_selected_navigation(&output, "传感器");
        }
    }
    // At minimum size the page heading can validly be below the scroll viewport.
    // Also verify actual page content changes in a window where headings fit.
    let mut app = fixture("representative");
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let mut output = harness.frame(&mut app).1;
    for _ in 0..3 {
        output = harness.frame(&mut app).1;
    }
    for (label, title) in [
        ("型号目录", "型号目录"),
        ("控制", "设备控制"),
        ("传感器", "传感器"),
        ("概览", "设备概览"),
    ] {
        let (_, rect) = accessible_control(&output, label, egui::accesskit::Role::Button);
        output = click(&mut harness, &mut app, rect.center());
        assert_selected_navigation(&output, label);
        assert_page_title(&output, title);
    }
}

#[test]
fn navigation_stays_reachable_after_scrolling_with_a_usable_content_viewport() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    for (physical, dpi, text_scale) in [
        ([360, 280], 1.0, 1.0),
        ([360, 280], 1.0, 1.6),
        ([720, 560], 2.0, 1.6),
        ([1120, 760], 1.0, 1.0),
    ] {
        let mut app = fixture("representative");
        app.preferences.text_scale = text_scale;
        let mut harness = Harness::new(physical, dpi, fonts.clone());
        let (_, output) = settle(&mut harness, &mut app);
        let client = Rect::from_min_size(
            pos2(0.0, 0.0),
            vec2(
                physical[0] as f32 / output.pixels_per_point,
                physical[1] as f32 / output.pixels_per_point,
            ),
        );
        let labels = ["传感器", "型号目录", "控制", "概览"];
        let original: Vec<_> = labels
            .iter()
            .map(|label| accessible_control(&output, label, egui::accesskit::Role::Button).1)
            .collect();
        for (index, label) in labels.iter().enumerate() {
            app.scroll_to_bottom();
            let (metrics, output) = settle(&mut harness, &mut app);
            if index == 0 {
                assert!(
                    metrics.scroll_offset.y > 0.0,
                    "the overview must actually scroll"
                );
            }
            assert!(
                metrics.viewport.height() >= 36.0,
                "pinned navigation leaves less than one control row for content: {:?}",
                metrics.viewport
            );
            assert_client_bounds(
                "pinned navigation",
                &metrics,
                physical,
                output.pixels_per_point,
            );
            assert_width("pinned navigation", &metrics);
            for (name, before) in labels.iter().zip(&original) {
                let (_, after) = accessible_control(&output, name, egui::accesskit::Role::Button);
                assert!(
                    client.expand(1.0).contains_rect(after),
                    "navigation '{name}' left the window"
                );
                assert!(
                    before.min.distance(after.min) <= 1.0 && before.max.distance(after.max) <= 1.0,
                    "navigation '{name}' moved with the page: {before:?} -> {after:?}"
                );
                assert!(
                    !after.intersects(metrics.viewport),
                    "navigation overlaps the scroll viewport"
                );
            }
            let (_, bounds) = accessible_control(&output, label, egui::accesskit::Role::Button);
            let output = click(&mut harness, &mut app, bounds.center());
            assert_selected_navigation(&output, label);
        }
    }
}

#[test]
fn empty_fixture_still_identifies_its_data_as_simulated() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = fixture("no_telemetry");
    let snapshot = app.controller.snapshot.as_ref().unwrap();
    assert!(snapshot.telemetry.is_empty());
    assert!(snapshot.identity.manufacturer.is_none());
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let (_, output) = settle(&mut harness, &mut app);
    let text = rendered_text(&output);
    assert!(text
        .iter()
        .any(|shape| shape.galley.job.text.contains("模拟数据")));
    assert!(!text
        .iter()
        .any(|shape| shape.galley.job.text.contains("真实硬件")));
}

#[test]
fn reducing_motion_through_visible_setting_disables_transitions() {
    let fonts = Arc::new(SystemFontProvider::new().with_locale(Some("zh-Hans")));
    let mut app = fixture("representative");
    app.open_display_settings();
    let mut harness = Harness::new([1120, 760], 1.0, fonts);
    let mut output = harness.frame(&mut app).1;
    for _ in 0..3 {
        output = harness.frame(&mut app).1;
    }
    assert!(harness.ctx.global_style().animation_time > 0.0);
    let (_, bounds) = accessible_control(&output, "界面过渡动画", egui::accesskit::Role::CheckBox);
    assert!(Rect::from_min_size(pos2(0.0, 0.0), vec2(1120.0, 760.0)).contains_rect(bounds));
    output = click(&mut harness, &mut app, bounds.center());
    let (_, node) = output
        .platform_output
        .accesskit_update
        .as_ref()
        .unwrap()
        .nodes
        .iter()
        .find(|(_, node)| node.label() == Some("界面过渡动画"))
        .unwrap();
    assert_eq!(node.toggled(), Some(egui::accesskit::Toggled::False));
    assert_eq!(harness.ctx.global_style().animation_time, 0.0);
}

fn assert_source_details_expand(label: &str, app: &mut DesktopApp, harness: &mut Harness) {
    app.set_source_details_expanded(false);
    let mut collapsed = RenderMetrics::default();
    for _ in 0..4 {
        collapsed = harness.frame(app).0;
    }
    assert_width(label, &collapsed);
    // Exercise the same state change as the user-facing source-details button.
    // The real layout must grow; a flag that never renders the paths cannot pass.
    app.set_source_details_expanded(true);
    let mut expanded = RenderMetrics::default();
    for _ in 0..4 {
        expanded = harness.frame(app).0;
    }
    assert_width(label, &expanded);
    assert!(
        expanded.content_size.y > collapsed.content_size.y + 20.0,
        "{label}: source details did not expand the actual rendered content: collapsed={:?}, expanded={:?}",
        collapsed.content_size,
        expanded.content_size
    );
}

fn assert_layout(
    label: &str,
    app: &mut DesktopApp,
    harness: &mut Harness,
    capture: Option<&Path>,
    require_scroll: bool,
) {
    let mut top = None;
    for _ in 0..4 {
        top = Some(harness.frame(app));
    }
    let (metrics, output) = top.unwrap();
    assert!(
        (output.pixels_per_point - harness.dpi * app.preferences.text_scale).abs() < 0.001,
        "{label}: wrong DPI"
    );
    assert_client_bounds(label, &metrics, harness.physical, output.pixels_per_point);
    if let Some(path) = capture {
        harness.capture(output, &path.join(format!("{label}-top.png")));
    }
    assert_width(label, &metrics);
    app.scroll_to_bottom();
    let mut bottom = None;
    for _ in 0..4 {
        bottom = Some(harness.frame(app));
    }
    let (metrics, output) = bottom.unwrap();
    assert_width(label, &metrics);
    assert_client_bounds(label, &metrics, harness.physical, output.pixels_per_point);
    assert!(
        metrics.bottom_marker.min.y >= metrics.viewport.min.y - 1.0
            && metrics.bottom_marker.max.y <= metrics.viewport.max.y + 1.0,
        "{label}: last action/marker cannot be reached: marker={:?}, viewport={:?}, scroll={:?}",
        metrics.bottom_marker,
        metrics.viewport,
        metrics.scroll_offset
    );
    if require_scroll {
        assert!(
            metrics.scroll_offset.y > 0.0,
            "{label}: fixture should require vertical scrolling"
        );
    }
    if let Some(path) = capture {
        harness.capture(output, &path.join(format!("{label}-bottom.png")));
    }
}
fn assert_client_bounds(label: &str, metrics: &RenderMetrics, physical: [u32; 2], ppp: f32) {
    assert!(
        metrics.viewport.min.x >= -1.0
            && metrics.viewport.min.y >= -1.0
            && metrics.viewport.max.x <= physical[0] as f32 / ppp + 1.0
            && metrics.viewport.max.y <= physical[1] as f32 / ppp + 1.0,
        "{label}: content viewport exceeds client bounds"
    );
}
fn assert_width(label: &str, metrics: &RenderMetrics) {
    assert!(
        metrics.content_size.x.is_finite() && metrics.content_size.y.is_finite(),
        "{label}: invalid content size"
    );
    assert!(
        metrics.content_size.x <= metrics.viewport.width() + 1.0,
        "{label}: horizontal overflow: content={:?}, viewport={:?}",
        metrics.content_size,
        metrics.viewport
    );
    assert!(
        metrics.scroll_offset.x.abs() < 0.001,
        "{label}: horizontal scrolling must be unnecessary"
    );
}

// Minimal lossless PNG encoder avoids a screenshot dependency in the product.
// DEFLATE stored blocks are sufficient for bounded, optional test artifacts.
fn write_png(path: &Path, width: u32, height: u32, pixels: &[[u8; 4]]) {
    fn chunk(out: &mut Vec<u8>, kind: &[u8; 4], data: &[u8]) {
        out.extend_from_slice(&(data.len() as u32).to_be_bytes());
        out.extend_from_slice(kind);
        out.extend_from_slice(data);
        let mut crc = 0xffff_ffffu32;
        for byte in kind.iter().chain(data) {
            crc ^= *byte as u32;
            for _ in 0..8 {
                crc = (crc >> 1) ^ if crc & 1 == 1 { 0xedb8_8320 } else { 0 };
            }
        }
        out.extend_from_slice(&(!crc).to_be_bytes());
    }
    let mut raw = Vec::with_capacity((width as usize * 4 + 1) * height as usize);
    for row in pixels.chunks_exact(width as usize) {
        raw.push(0);
        for pixel in row {
            raw.extend_from_slice(pixel);
        }
    }
    let mut zlib = vec![0x78, 0x01];
    let blocks = raw.chunks(65535);
    let count = blocks.len();
    for (index, block) in blocks.enumerate() {
        zlib.push(u8::from(index + 1 == count));
        let len = block.len() as u16;
        zlib.extend_from_slice(&len.to_le_bytes());
        zlib.extend_from_slice(&(!len).to_le_bytes());
        zlib.extend_from_slice(block);
    }
    let (mut a, mut b) = (1u32, 0u32);
    for byte in raw {
        a = (a + byte as u32) % 65521;
        b = (b + a) % 65521;
    }
    zlib.extend_from_slice(&((b << 16) | a).to_be_bytes());
    let mut png = b"\x89PNG\r\n\x1a\n".to_vec();
    let mut header = Vec::new();
    header.extend_from_slice(&width.to_be_bytes());
    header.extend_from_slice(&height.to_be_bytes());
    header.extend_from_slice(&[8, 6, 0, 0, 0]);
    chunk(&mut png, b"IHDR", &header);
    chunk(&mut png, b"IDAT", &zlib);
    chunk(&mut png, b"IEND", &[]);
    std::fs::write(path, png).unwrap();
}
