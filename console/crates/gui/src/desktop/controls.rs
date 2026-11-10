//! Everyday controls are visible before diagnostic detail. Selection, preview
//! and application remain separate; drawing a screen never writes hardware.
use super::*;

fn mode_description(id: &str) -> &'static str {
    match id {
        "mechrevo_office" => "轻负载 · 节能优先",
        "mechrevo_gaming_quiet" => "游戏参数 · 较低风扇请求",
        "mechrevo_gaming" => "动态睿频 · 日常游戏",
        "mechrevo_turbo" => "性能优先 · 允许空闲降频",
        "mechrevo_fan_boost" => "全速风扇请求 · 快速散热",
        _ => "本机已保存的参数",
    }
}
fn control_hint(kind: OemControlKind) -> &'static str {
    match kind {
        OemControlKind::PerformanceProfile => "性能与散热",
        OemControlKind::ChargingProfile => "电池保养",
        OemControlKind::KeyboardBrightness => "键盘照明",
        OemControlKind::KeyboardColor => "键盘色彩",
        OemControlKind::FnLock => "功能键行为",
        OemControlKind::AcAutoBoot => "接电启动",
        OemControlKind::UsbPowerShare => "关机 USB 供电",
    }
}
impl DesktopApp {
    pub(super) fn sidebar(&mut self, ui: &mut egui::Ui) {
        let colors = appearance::palette(ui);
        ui.spacing_mut().item_spacing = Vec2::new(10.0, 6.0);
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            let (rect, _) = ui.allocate_exact_size(Vec2::splat(24.0), egui::Sense::hover());
            icon(ui.painter(), rect, Icon::Brand, colors.accent);
            ui.label(RichText::new("MECHREVO").size(17.0).strong());
        });
        ui.add_space(4.0);
        ui.label(
            RichText::new("机械革命控制中心")
                .size(12.0)
                .color(colors.secondary),
        );
        ui.add_space(34.0);
        for (section, label, detail) in [
            (Section::Dashboard, "概览", "性能、温度与常用控制"),
            (Section::Controls, "控制", "电池、键盘与功能键"),
            (Section::Sensors, "传感器", "全部读数与数据来源"),
            (Section::Catalog, "型号目录", "机型信息与支持范围"),
        ] {
            let selected = self.section == section;
            let color = if selected {
                colors.accent
            } else {
                colors.label
            };
            let glyph_id = egui::IdSalt::new(("navigation-icon", section));
            let mut button = egui::Button::new((
                egui::Atom::custom(glyph_id, Vec2::splat(18.0)),
                RichText::new(label).size(14.0).color(color),
                egui::Atom::grow(),
            ))
            .selected(selected)
            .frame_when_inactive(selected)
            .stroke(Stroke::NONE)
            .corner_radius(10.0)
            .gap(12.0)
            .min_size(Vec2::new(ui.available_width(), 44.0));
            if selected {
                button = button.fill(colors.selection);
            }
            let output = button.atom_ui(ui);
            if let Some(rect) = output.rect(glyph_id) {
                navigation_icon(ui.painter(), rect, section, color);
            }
            if output.response.has_focus() {
                ui.painter().rect_stroke(
                    output.response.rect,
                    10.0,
                    Stroke::new(1.0, colors.accent),
                    egui::StrokeKind::Inside,
                );
            }
            if output.response.on_hover_text(detail).clicked() {
                self.section = section;
            }
        }
        // Keep the footer quiet and anchored, without taking space from the
        // navigation in short windows or at larger text sizes.
        if ui.available_height() >= 100.0 {
            ui.add_space((ui.available_height() - 58.0).max(16.0));
            ui.label(
                RichText::new("更改先预览，应用后回读")
                    .size(12.0)
                    .color(colors.secondary),
            );
            ui.label(
                RichText::new("MECHREVO CONSOLE")
                    .size(10.0)
                    .color(colors.secondary),
            );
        }
    }

    pub(super) fn performance_controls(&mut self, ui: &mut egui::Ui) {
        // An immutable display snapshot allows a click to update selection
        // without retaining a borrow of the worker's current device inventory.
        let control = self
            .controller
            .snapshot
            .as_ref()
            .and_then(|s| {
                s.oem_controls
                    .iter()
                    .find(|c| c.kind == OemControlKind::PerformanceProfile)
            })
            .cloned();
        let Some(control) = control else {
            return;
        };
        if self.controller.selected_oem_control.is_none() {
            self.controller.select_oem_control(&control.id);
        }
        let is_selected = self.controller.selected_oem_control.as_deref() == Some(&control.id);
        let requested = if is_selected {
            self.controller.requested_oem_value.as_ref()
        } else {
            control.current.as_ref()
        };
        let selected = match requested {
            Some(OemValue::Choice(id)) => Some(id.clone()),
            _ => None,
        };
        let colors = appearance::palette(ui);
        surface(ui, |ui| {
            ui.spacing_mut().item_spacing.y = 8.0;
            heading_with_icon(ui, "性能与散热", Icon::Power);
            ui.add_space(2.0);
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new("当前运行").size(13.0).color(colors.secondary));
                ui.label(
                    RichText::new(
                        control
                            .current
                            .as_ref()
                            .map(oem_value_text)
                            .unwrap_or_else(|| "等待检测".into()),
                    )
                    .size(16.0)
                    .strong()
                    .color(colors.accent),
                );
                if let Some(OemValue::Choice(id)) = &control.current {
                    ui.label(
                        RichText::new(mode_description(id))
                            .size(13.0)
                            .color(colors.secondary),
                    );
                }
            });
            if control.status != CapabilityStatus::Available {
                unavailable(
                    ui,
                    control
                        .reason
                        .as_deref()
                        .unwrap_or("性能档位暂不可用，请刷新核对。"),
                );
                return;
            }
            let OemDomain::Choices(choices) = &control.domain else {
                return;
            };
            ui.add_space(12.0);
            let columns = if ui.available_width() >= 780.0 {
                5
            } else if ui.available_width() >= 480.0 {
                3
            } else if ui.available_width() >= 300.0 {
                2
            } else {
                1
            };
            for row in choices.chunks(columns) {
                ui.columns(columns, |columns| {
                    for (ui, id) in columns.iter_mut().zip(row) {
                        let chosen = selected.as_deref() == Some(id.as_str());
                        let text = tile_text(
                            oem_choice_label(id),
                            mode_description(id),
                            if chosen { colors.accent } else { colors.text },
                            colors.secondary,
                        );
                        let mut button = egui::Button::new(text)
                            .selected(chosen)
                            .corner_radius(10.0)
                            .min_size(Vec2::new(ui.available_width(), 78.0))
                            .wrap();
                        if chosen {
                            button = button
                                .fill(colors.selection)
                                .stroke(Stroke::new(1.0, colors.accent));
                        }
                        let response = ui.add_enabled(!self.controller.busy(), button);
                        if response.clicked() {
                            self.controller.select_oem_control(&control.id);
                            self.controller.set_oem_target(OemValue::Choice(id.clone()));
                        }
                    }
                });
            }
            ui.add_space(12.0);
            let owns_selection =
                self.controller.selected_oem_control.as_deref() == Some(&control.id);
            let reason = if owns_selection {
                self.controller.oem_unavailable_reason().map(str::to_owned)
            } else {
                None
            };
            let preview = self
                .controller
                .oem_preview
                .as_ref()
                .filter(|p| p.control_id == control.id);
            if let Some(plan) = preview {
                ui.label(
                    RichText::new(format!(
                        "待应用：{} → {}",
                        oem_value_text(&plan.previous),
                        oem_value_text(&plan.target)
                    ))
                    .color(colors.accent),
                );
            }
            let can_apply =
                preview.is_some() && owns_selection && reason.is_none() && !self.controller.busy();
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(
                        owns_selection && reason.is_none() && !self.controller.busy(),
                        egui::Button::new("预览档位更改"),
                    )
                    .clicked()
                {
                    let _ = self.controller.preview_oem();
                }
                let apply_button = if can_apply {
                    primary_button(ui, "应用性能档位")
                } else {
                    egui::Button::new(RichText::new("应用性能档位").color(colors.secondary))
                        .fill(colors.inset)
                        .stroke(Stroke::NONE)
                };
                if ui.add_enabled(can_apply, apply_button).clicked() {
                    if let Err(error) = self.controller.apply_oem_preview() {
                        self.controller.error = Some(mechrevo_console_core::ControlError::new(
                            "oem_preview_invalidated",
                            format!("档位或接口已变化，请重新预览：{error:?}"),
                        ));
                    }
                }
                ui.label(
                    RichText::new("预览后应用更改")
                        .size(12.0)
                        .color(colors.secondary),
                );
            });
            if let Some(reason) = reason {
                unavailable(ui, &reason);
            }
            egui::CollapsingHeader::new("档位与回读说明").id_salt("performance-details").show(ui, |ui| {
                ui.label(&control.readback_scope);
                ui.label("参数来自本机已保存的配置，保留独立温控。强冷为全速请求，实际 RPM 请看监测读数；机身按键与其他控制程序仍可能改变当前档位。");
                evidence(ui, &control.source.backend, &control.source.path);
            });
        });
        ui.add_space(18.0);
    }

    pub(super) fn everyday_power(&mut self, ui: &mut egui::Ui) {
        let charging = self
            .controller
            .snapshot
            .as_ref()
            .and_then(|s| {
                s.oem_controls
                    .iter()
                    .find(|c| c.kind == OemControlKind::ChargingProfile)
            })
            .cloned();
        let Some(control) = charging else {
            self.power_controls(ui);
            return;
        };
        heading_with_icon(ui, "电池保养", Icon::Battery);
        ui.label(
            RichText::new(format!(
                "当前  {}",
                control
                    .current
                    .as_ref()
                    .map(oem_value_text)
                    .unwrap_or_else(|| "未采集".into())
            ))
            .color(secondary(ui)),
        );
        let selected = self.controller.selected_oem_control.as_deref() == Some(&control.id);
        let target = if selected {
            self.controller.requested_oem_value.as_ref()
        } else {
            control.current.as_ref()
        }
        .cloned();
        if control.status == CapabilityStatus::Available {
            if let OemDomain::Choices(choices) = &control.domain {
                ui.horizontal_wrapped(|ui| {
                    for choice in choices {
                        let value = OemValue::Choice(choice.clone());
                        if ui
                            .add_enabled(
                                !self.controller.busy(),
                                egui::Button::selectable(
                                    target.as_ref() == Some(&value),
                                    oem_choice_label(choice),
                                ),
                            )
                            .clicked()
                        {
                            self.controller.select_oem_control(&control.id);
                            self.controller.set_oem_target(value);
                        }
                    }
                });
            }
            let owns_selection =
                self.controller.selected_oem_control.as_deref() == Some(&control.id);
            let ready = owns_selection
                && !self.controller.busy()
                && self.controller.oem_unavailable_reason().is_none();
            let preview = self
                .controller
                .oem_preview
                .as_ref()
                .filter(|p| p.control_id == control.id);
            if let Some(plan) = preview {
                ui.label(
                    RichText::new(format!(
                        "待应用：{} → {}",
                        oem_value_text(&plan.previous),
                        oem_value_text(&plan.target)
                    ))
                    .color(green(ui)),
                );
            }
            let can_apply = ready && preview.is_some();
            ui.horizontal_wrapped(|ui| {
                if ui
                    .add_enabled(ready, egui::Button::new("预览充电更改"))
                    .clicked()
                {
                    let _ = self.controller.preview_oem();
                }
                if ui
                    .add_enabled(can_apply, primary_button(ui, "应用充电模式"))
                    .clicked()
                {
                    let _ = self.controller.apply_oem_preview();
                }
            });
        } else {
            unavailable(ui, control.reason.as_deref().unwrap_or("充电控制暂不可用"));
        }
        ui.label(
            RichText::new("选择驱动充电模式，不承诺固定 60% / 80% 上限。")
                .size(12.0)
                .color(secondary(ui)),
        );
        egui::CollapsingHeader::new("系统电源策略")
            .id_salt("advanced-os-profile")
            .show(ui, |ui| {
                ui.label("这是操作系统策略，不等于上方的机械革命性能档位。");
                self.power_controls(ui);
            });
    }

    pub(super) fn quick_controls(&mut self, ui: &mut egui::Ui) {
        let controls: Vec<_> = self
            .controller
            .snapshot
            .as_ref()
            .map(|s| {
                s.oem_controls
                    .iter()
                    .filter(|c| c.kind != OemControlKind::PerformanceProfile)
                    .cloned()
                    .collect()
            })
            .unwrap_or_default();
        if controls.is_empty() {
            return;
        }
        heading_with_icon(ui, "常用设备控制", Icon::Laptop);
        ui.add_space(8.0);
        let columns = if ui.available_width() >= 760.0 {
            3
        } else if ui.available_width() >= 440.0 {
            2
        } else {
            1
        };
        let colors = appearance::palette(ui);
        for row in controls.chunks(columns) {
            ui.columns(columns, |columns| {
                for (ui, control) in columns.iter_mut().zip(row) {
                    let value = control
                        .current
                        .as_ref()
                        .map(oem_value_text)
                        .unwrap_or_else(|| "暂不可用".into());
                    let text = tile_text(
                        control_hint(control.kind),
                        &value,
                        colors.text,
                        colors.secondary,
                    );
                    let arrow_id = egui::IdSalt::new(("control-arrow", &control.id));
                    let output = ui
                        .add_enabled_ui(!self.controller.write_in_progress(), |ui| {
                            egui::Button::new((
                                text,
                                egui::Atom::grow(),
                                egui::Atom::custom(arrow_id, Vec2::splat(14.0)),
                            ))
                            .corner_radius(12.0)
                            .min_size(Vec2::new(ui.available_width(), 76.0))
                            .wrap()
                            .atom_ui(ui)
                        })
                        .inner;
                    if let Some(rect) = output.rect(arrow_id) {
                        let center = rect.center();
                        ui.painter().line(
                            vec![
                                center + Vec2::new(-2.0, -4.0),
                                center + Vec2::new(2.0, 0.0),
                                center + Vec2::new(-2.0, 4.0),
                            ],
                            Stroke::new(1.2, colors.secondary),
                        );
                    }
                    if output.response.on_hover_text(&control.label).clicked() {
                        self.controller.select_oem_control(&control.id);
                        self.section = Section::Controls;
                    }
                }
            });
            ui.add_space(6.0);
        }
    }
}

/// Two text levels inside an ordinary button keep the entire tile keyboard
/// accessible; the label remains available to assistive technology.
fn tile_text(
    title: &str,
    detail: &str,
    title_color: Color32,
    detail_color: Color32,
) -> egui::text::LayoutJob {
    let mut job = egui::text::LayoutJob::default();
    job.append(
        title,
        0.0,
        egui::TextFormat {
            font_id: FontId::proportional(14.0),
            color: title_color,
            line_height: Some(24.0),
            ..Default::default()
        },
    );
    job.append(
        &format!("\n{detail}"),
        0.0,
        egui::TextFormat {
            font_id: FontId::proportional(12.0),
            color: detail_color,
            line_height: Some(19.0),
            ..Default::default()
        },
    );
    job
}

fn navigation_icon(painter: &egui::Painter, rect: Rect, section: Section, color: Color32) {
    let rect = rect.shrink(1.0);
    let point = |x: f32, y: f32| rect.min + rect.size() * egui::vec2(x, y);
    let stroke = Stroke::new(1.35, color);
    match section {
        Section::Dashboard => {
            for (x, y) in [(0.0, 0.0), (0.58, 0.0), (0.0, 0.58), (0.58, 0.58)] {
                painter.rect_stroke(
                    Rect::from_min_size(point(x, y), rect.size() * 0.4),
                    1.5,
                    stroke,
                    egui::StrokeKind::Inside,
                );
            }
        }
        Section::Controls => {
            for (y, x) in [(0.2, 0.3), (0.75, 0.7)] {
                painter.line_segment([point(0.0, y), point(1.0, y)], stroke);
                painter.circle_filled(point(x, y), 2.5, color);
            }
        }
        Section::Sensors => {
            painter.line(
                vec![
                    point(0.0, 0.55),
                    point(0.2, 0.55),
                    point(0.36, 0.12),
                    point(0.6, 0.9),
                    point(0.78, 0.4),
                    point(1.0, 0.4),
                ],
                stroke,
            );
        }
        Section::Catalog => {
            for y in [0.12, 0.5, 0.88] {
                painter.circle_filled(point(0.08, y), 1.2, color);
                painter.line_segment([point(0.32, y), point(1.0, y)], stroke);
            }
        }
    }
}
