#![cfg(feature = "gui")]
//! Closing a window must keep the write/readback/rollback worker alive until it returns.
use eframe::egui::{self, Context, RawInput, Rect, ViewportCommand, ViewportEvent, ViewportId};
use egui_system_font_provider::SystemFontProvider;
use mechrevo_console_core::{
    ApplyResult, CatalogModel, ControlError, EvidenceSource, PowerProfile, ProfilePlan, Snapshot,
};
use mechrevo_console_gui::{desktop::DesktopApp, Backend, Controller, Preferences};
use serde_json::json;
use std::{
    sync::{
        mpsc::{self, Receiver, SyncSender},
        Arc,
    },
    time::{Duration, Instant},
};

struct WritingBackend {
    snapshot: Snapshot,
    entered: SyncSender<()>,
    release: Receiver<()>,
    fail_after_restore: bool,
}
impl Backend for WritingBackend {
    fn snapshot(&mut self) -> Snapshot {
        self.snapshot.clone()
    }
    fn catalog(&mut self) -> Vec<CatalogModel> {
        vec![]
    }
    fn plan(&mut self, _: PowerProfile) -> Result<ProfilePlan, ControlError> {
        unreachable!("test provides an explicit preview")
    }
    fn apply(&mut self, plan: &ProfilePlan) -> Result<ApplyResult, ControlError> {
        self.entered.send(()).unwrap();
        // A bad UI implementation must produce a bounded test failure, not hang CI.
        self.release
            .recv_timeout(Duration::from_secs(2))
            .expect("UI froze before releasing the test transaction");
        if self.fail_after_restore {
            let mut error =
                ControlError::new("readback_mismatch", "测试回读不一致，已完成恢复回读。");
            error.details.push("restore_confirmed: balanced".into());
            Err(error)
        } else {
            Ok(ApplyResult {
                requested: plan.requested,
                confirmed: plan.target.clone(),
                previous: plan.previous.clone(),
                scope: plan.scope.clone(),
            })
        }
    }
}

fn render(ctx: &Context, app: &mut DesktopApp, close: bool) -> Vec<ViewportCommand> {
    let mut input = RawInput {
        screen_rect: Some(Rect::from_min_size(
            egui::Pos2::ZERO,
            egui::vec2(800.0, 600.0),
        )),
        ..Default::default()
    };
    if close {
        input
            .viewports
            .get_mut(&ViewportId::ROOT)
            .unwrap()
            .events
            .push(ViewportEvent::Close);
    }
    let output = ctx.run_ui(input, |ui| {
        app.render(ui);
    });
    let commands = output
        .viewport_output
        .get(&ViewportId::ROOT)
        .unwrap()
        .commands
        .clone();
    output.drop_without_applying_deltas();
    commands
}

// @mark mechrevo.console_ui role=verification
#[test]
fn close_waits_without_freezing_for_success_and_completed_rollback() {
    for fail_after_restore in [false, true] {
        let snapshot:Snapshot=serde_json::from_value(json!({
            "platform":"linux", "identity":{"support_note":"仅测试，不访问硬件。","mechrevo_brand_detected":false},
            "telemetry":[], "brightness":[], "diagnostics":[],
            "capabilities":[{"id":"power_profile","label":"系统电源策略","status":"available","reason":"fixture-only","source":null,"options":["balanced","performance"]}],
            "power_policy":{"scope":"fixture-only","current":"balanced","options":["balanced","performance"],"source":null}
        })).unwrap();
        let (entered_send, entered_recv) = mpsc::sync_channel(1);
        let (release_send, release_recv) = mpsc::sync_channel(1);
        let backend = WritingBackend {
            snapshot: snapshot.clone(),
            entered: entered_send,
            release: release_recv,
            fail_after_restore,
        };
        let mut controller = Controller::new(backend).unwrap();
        controller.snapshot = Some(snapshot);
        controller.selected_profile = PowerProfile::Performance;
        controller.preview = Some(ProfilePlan {
            requested: PowerProfile::Performance,
            target: "performance".into(),
            previous: "balanced".into(),
            scope: "fixture-only".into(),
            source: EvidenceSource {
                backend: "fixture-only".into(),
                path: "fixture://no-hardware".into(),
                device_id: None,
            },
        });
        let mut app = DesktopApp::with_controller(controller, Preferences::default());
        let ctx = Context::default();
        ctx.add_font_provider(Arc::new(
            SystemFontProvider::new().with_locale(Some("zh-Hans")),
        ));
        for _ in 0..3 {
            render(&ctx, &mut app, false);
        }
        app.controller.apply_preview().unwrap();
        entered_recv
            .recv_timeout(Duration::from_secs(2))
            .expect("test worker never entered write stage");
        assert!(app.controller.write_in_progress());
        let started = Instant::now();
        let commands = render(&ctx, &mut app, true);
        assert!(
            started.elapsed() < Duration::from_millis(500),
            "close handling blocked the UI while a write was active"
        );
        assert!(
            commands.contains(&ViewportCommand::CancelClose),
            "in-flight write must defer native window close"
        );
        assert!(
            !commands.contains(&ViewportCommand::Close),
            "native window closed before write/readback/restore completed"
        );
        assert!(app.controller.write_in_progress());
        let commands = render(&ctx, &mut app, false);
        assert!(
            !commands.contains(&ViewportCommand::Close),
            "a second frame closed an unfinished transaction"
        );
        release_send.send(()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        while app.controller.busy() && Instant::now() < deadline {
            app.controller.poll();
            std::thread::yield_now();
        }
        assert!(
            !app.controller.busy(),
            "worker did not complete after release"
        );
        if fail_after_restore {
            assert!(app.controller.applied.is_none());
            assert_eq!(
                app.controller.error.as_ref().unwrap().details,
                ["restore_confirmed: balanced"]
            );
        } else {
            assert_eq!(
                app.controller.applied.as_ref().unwrap().confirmed,
                "performance"
            );
        }
        let commands = render(&ctx, &mut app, false);
        assert!(
            commands.contains(&ViewportCommand::Close),
            "deferred native close was not resumed after transaction returned"
        );
        assert!(
            !commands.contains(&ViewportCommand::CancelClose),
            "finished transaction incorrectly keeps window open"
        );
    }
}
