use super::*;

#[cfg(target_os = "linux")]
#[test]
fn direct_system_write_requires_helper_before_control_discovery() {
    // This deliberately unknown ID cannot select a hardware control even if
    // the authorization guard regresses; no live attribute is opened or stored.
    let plan = transaction_plan();
    assert_eq!(plan.control_id, "fixture-control");
    // SAFETY: geteuid has no arguments, pointers or side effects.
    assert_ne!(
        unsafe { libc::geteuid() },
        0,
        "run permission regressions as an ordinary user"
    );
    let error = crate::Service::new().apply_oem(&plan).unwrap_err();
    assert_eq!(error.code, "administrator_required");
    assert_terminal_marker(&error, "oem_rejected_before_write");
}

fn transaction_plan() -> OemPlan {
    OemPlan {
        control_id: "fixture-control".into(),
        kind: OemControlKind::ChargingProfile,
        label: "Fixture control".into(),
        previous: OemValue::Choice("balanced".into()),
        target: OemValue::Choice("stationary".into()),
        domain: OemDomain::Choices(vec!["balanced".into(), "stationary".into()]),
        source: EvidenceSource {
            backend: "fixture".into(),
            path: "fixture/control".into(),
            device_id: Some("fixture-device".into()),
        },
        binding: "fixture-binding".into(),
        readback_scope: "driver-reported request only".into(),
        requires_privilege: false,
        companion_brightness: None,
    }
}

fn assert_terminal_marker(error: &ControlError, expected: &str) {
    let markers = error
        .details
        .iter()
        .filter(|detail| {
            matches!(
                detail.as_str(),
                "oem_rejected_before_write" | "oem_restore_confirmed" | "oem_state_unknown"
            )
        })
        .map(String::as_str)
        .collect::<Vec<_>>();
    assert_eq!(markers, [expected], "ambiguous OEM outcome: {error:?}");
}

struct FakeIo {
    state: Observation,
    reads: usize,
    writes: Vec<OemValue>,
    companion_writes: Vec<u32>,
    fail_reads: Vec<usize>,
    change_on_read: Vec<(usize, Observation)>,
    fail_writes: Vec<usize>,
    mutate_before_error: bool,
    fail_companion: bool,
}
impl FakeIo {
    fn new(plan: &OemPlan) -> Self {
        Self {
            state: Observation {
                value: plan.previous.clone(),
                companion_brightness: plan.companion_brightness,
            },
            reads: 0,
            writes: vec![],
            companion_writes: vec![],
            fail_reads: vec![],
            change_on_read: vec![],
            fail_writes: vec![],
            mutate_before_error: false,
            fail_companion: false,
        }
    }
}
impl OemIo for FakeIo {
    fn observe(&mut self) -> Result<Observation, ControlError> {
        self.reads += 1;
        if let Some((_, changed)) = self
            .change_on_read
            .iter()
            .find(|(read, _)| *read == self.reads)
        {
            self.state = changed.clone();
        }
        if self.fail_reads.contains(&self.reads) {
            Err(ControlError::new(
                "fixture_read_failed",
                "injected read failure",
            ))
        } else {
            Ok(self.state.clone())
        }
    }
    fn write(&mut self, value: &OemValue) -> Result<(), ControlError> {
        self.writes.push(value.clone());
        let fails = self.fail_writes.contains(&self.writes.len());
        if !fails || self.mutate_before_error {
            self.state.value = value.clone();
        }
        if fails {
            Err(ControlError::new(
                "fixture_write_failed",
                "injected write failure",
            ))
        } else {
            Ok(())
        }
    }
    fn write_companion(&mut self, value: u32) -> Result<(), ControlError> {
        self.companion_writes.push(value);
        if self.fail_companion {
            Err(ControlError::new(
                "fixture_companion_failed",
                "injected companion failure",
            ))
        } else {
            self.state.companion_brightness = Some(value);
            Ok(())
        }
    }
}

#[test]
fn transaction_success_confirms_readback_without_restoration() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    assert_eq!(transact(&mut io, &plan).unwrap(), plan.target);
    assert_eq!(io.writes, vec![plan.target]);
    assert_eq!(io.reads, 2);
    assert!(io.companion_writes.is_empty());
}

#[test]
fn transaction_failed_initial_read_is_rejected_before_any_write() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_reads = vec![1];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_read_failed");
    assert!(io.writes.is_empty());
    assert!(io.companion_writes.is_empty());
    assert_terminal_marker(&error, "oem_rejected_before_write");
}

#[test]
fn transaction_stale_value_or_companion_prevents_every_write() {
    let mut plan = transaction_plan();
    plan.kind = OemControlKind::KeyboardColor;
    plan.previous = OemValue::Rgb([10, 20, 30]);
    plan.target = OemValue::Rgb([30, 20, 10]);
    plan.domain = OemDomain::Rgb;
    plan.companion_brightness = Some(2);
    for state in [
        Observation {
            value: OemValue::Rgb([11, 20, 30]),
            companion_brightness: Some(2),
        },
        Observation {
            value: plan.previous.clone(),
            companion_brightness: Some(3),
        },
    ] {
        let mut io = FakeIo::new(&plan);
        io.state = state;
        let error = transact(&mut io, &plan).unwrap_err();
        assert_eq!(error.code, "oem_plan_stale");
        assert_terminal_marker(&error, "oem_rejected_before_write");
        assert!(io.writes.is_empty());
        assert!(io.companion_writes.is_empty());
    }
}

#[test]
fn failed_callback_after_mutation_restores_and_reads_previous_value() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_writes = vec![1];
    io.mutate_before_error = true;
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_write_failed");
    assert_terminal_marker(&error, "oem_restore_confirmed");
    assert_eq!(io.writes, vec![plan.target, plan.previous.clone()]);
    assert_eq!(io.state.value, plan.previous);
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[test]
fn failed_readback_uses_independent_observation_before_restoring() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_reads = vec![2];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_read_failed");
    assert_eq!(io.state.value, plan.previous);
    assert_terminal_marker(&error, "oem_restore_confirmed");
    assert_eq!(io.writes.len(), 2);
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[test]
fn restoration_never_overwrites_an_external_or_unknown_state() {
    let plan = transaction_plan();
    for unknown in [false, true] {
        let mut io = FakeIo::new(&plan);
        io.fail_reads = if unknown { vec![2, 3] } else { vec![2] };
        io.change_on_read = vec![(
            3,
            Observation {
                value: OemValue::Choice("external-change".into()),
                companion_brightness: None,
            },
        )];
        let error = transact(&mut io, &plan).unwrap_err();
        assert_terminal_marker(&error, "oem_state_unknown");
        assert_eq!(io.writes, vec![plan.target.clone()]);
        assert!(error
            .details
            .iter()
            .any(|s| s.starts_with("restore_not_attempted:")));
        assert!(!error
            .details
            .iter()
            .any(|s| s.starts_with("restore_confirmed:")));
    }
}

#[test]
fn readback_mismatch_preserves_a_valid_third_party_choice() {
    let mut plan = transaction_plan();
    plan.domain = OemDomain::Choices(vec![
        "balanced".into(),
        "stationary".into(),
        "high_capacity".into(),
    ]);
    let external = OemValue::Choice("high_capacity".into());
    let mut io = FakeIo::new(&plan);
    io.change_on_read = vec![(
        2,
        Observation {
            value: external.clone(),
            companion_brightness: None,
        },
    )];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "oem_readback_mismatch");
    assert_terminal_marker(&error, "oem_state_unknown");
    assert_eq!(io.state.value, external);
    assert_eq!(io.writes, vec![plan.target]);
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_not_attempted:")));
}

#[test]
fn companion_change_after_rgb_write_prevents_both_restoration_writes() {
    let mut plan = transaction_plan();
    plan.kind = OemControlKind::KeyboardColor;
    plan.previous = OemValue::Rgb([10, 20, 30]);
    plan.target = OemValue::Rgb([30, 20, 10]);
    plan.domain = OemDomain::Rgb;
    plan.companion_brightness = Some(2);
    let mut io = FakeIo::new(&plan);
    io.change_on_read = vec![(
        2,
        Observation {
            value: plan.target.clone(),
            companion_brightness: Some(3),
        },
    )];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "oem_readback_mismatch");
    assert_terminal_marker(&error, "oem_state_unknown");
    assert_eq!(io.writes, vec![plan.target]);
    assert!(io.companion_writes.is_empty());
    assert_eq!(io.state.companion_brightness, Some(3));
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_not_attempted:")));
}

#[test]
fn failed_restore_never_claims_the_previous_request_was_restored() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_reads = vec![2];
    io.fail_writes = vec![2];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(io.state.value, plan.target);
    assert_terminal_marker(&error, "oem_state_unknown");
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_value_write_failed:")));
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_unconfirmed:")));
    assert!(!error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[test]
fn failed_restoration_confirmation_keeps_the_original_error_and_unknown_status() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_reads = vec![2, 4];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_read_failed");
    assert_eq!(io.state.value, plan.previous);
    assert_terminal_marker(&error, "oem_state_unknown");
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_unknown:")));
    assert!(!error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[test]
fn rgb_callback_failure_reapplies_color_and_brightness_independently() {
    let mut plan = transaction_plan();
    plan.kind = OemControlKind::KeyboardColor;
    plan.previous = OemValue::Rgb([10, 20, 30]);
    plan.target = OemValue::Rgb([30, 20, 10]);
    plan.domain = OemDomain::Rgb;
    plan.companion_brightness = Some(2);
    for fail_companion in [false, true] {
        let mut io = FakeIo::new(&plan);
        io.fail_writes = vec![1];
        io.fail_companion = fail_companion;
        let error = transact(&mut io, &plan).unwrap_err();
        assert_terminal_marker(
            &error,
            if fail_companion {
                "oem_state_unknown"
            } else {
                "oem_restore_confirmed"
            },
        );
        // The callback can partially change physical registers despite the
        // LED core retaining its old requested value after a failed callback.
        assert_eq!(io.writes, vec![plan.target.clone(), plan.previous.clone()]);
        assert_eq!(io.companion_writes, vec![2]);
        let expected = if fail_companion {
            "restore_brightness_write_failed:"
        } else {
            "restore_brightness_write_completed"
        };
        assert!(error.details.iter().any(|s| s.starts_with(expected)));
        assert!(error
            .details
            .iter()
            .any(|s| s.starts_with("readback scope:")));
    }
}

fn rgb_transaction_plan() -> OemPlan {
    OemPlan {
        kind: OemControlKind::KeyboardColor,
        previous: OemValue::Rgb([10, 20, 30]),
        target: OemValue::Rgb([30, 20, 10]),
        domain: OemDomain::Rgb,
        companion_brightness: Some(2),
        ..transaction_plan()
    }
}

#[test]
fn failed_rgb_color_restore_is_unknown_even_when_requested_cache_stays_previous() {
    let plan = rgb_transaction_plan();
    let mut io = FakeIo::new(&plan);
    // Both callbacks can fail after partial physical writes while leaving the
    // requested-state cache unchanged. Cache equality cannot erase either error.
    io.fail_writes = vec![1, 2];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_write_failed");
    assert_eq!(io.state.value, plan.previous);
    assert_eq!(io.state.companion_brightness, plan.companion_brightness);
    assert_eq!(io.companion_writes, vec![2]);
    assert_terminal_marker(&error, "oem_state_unknown");
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_value_write_failed:")));
    assert!(!error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[test]
fn failed_rgb_brightness_restore_is_unknown_even_when_requested_cache_stays_previous() {
    let plan = rgb_transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_writes = vec![1];
    io.fail_companion = true;
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_write_failed");
    assert_eq!(io.state.value, plan.previous);
    assert_eq!(io.state.companion_brightness, plan.companion_brightness);
    assert_terminal_marker(&error, "oem_state_unknown");
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_brightness_write_failed:")));
    assert!(!error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[test]
fn failed_or_changed_restore_observation_is_not_erased_by_a_later_old_cache() {
    let plan = rgb_transaction_plan();
    for failed_read in [false, true] {
        let mut io = FakeIo::new(&plan);
        io.fail_writes = vec![1];
        if failed_read {
            io.fail_reads = vec![3];
        } else {
            io.change_on_read = vec![
                (
                    3,
                    Observation {
                        value: OemValue::Rgb([90, 80, 70]),
                        companion_brightness: Some(2),
                    },
                ),
                (
                    4,
                    Observation {
                        value: plan.previous.clone(),
                        companion_brightness: Some(2),
                    },
                ),
            ];
        }
        let error = transact(&mut io, &plan).unwrap_err();
        assert_eq!(error.code, "fixture_write_failed");
        assert_eq!(io.state.value, plan.previous);
        assert!(io.companion_writes.is_empty());
        assert_terminal_marker(&error, "oem_state_unknown");
        assert!(!error
            .details
            .iter()
            .any(|s| s.starts_with("restore_confirmed:")));
    }
}

#[test]
fn unchanged_non_rgb_live_state_needs_no_restore_write() {
    let plan = transaction_plan();
    let mut io = FakeIo::new(&plan);
    io.fail_writes = vec![1];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(error.code, "fixture_write_failed");
    assert_eq!(io.state.value, plan.previous);
    assert_eq!(io.writes, vec![plan.target]);
    assert!(io.companion_writes.is_empty());
    assert_terminal_marker(&error, "oem_restore_confirmed");
}

#[test]
fn rgb_restoration_stops_before_brightness_if_another_writer_changes_color() {
    let mut plan = transaction_plan();
    plan.kind = OemControlKind::KeyboardColor;
    plan.previous = OemValue::Rgb([10, 20, 30]);
    plan.target = OemValue::Rgb([30, 20, 10]);
    plan.domain = OemDomain::Rgb;
    plan.companion_brightness = Some(2);
    let external = OemValue::Rgb([90, 80, 70]);
    let mut io = FakeIo::new(&plan);
    io.fail_writes = vec![1];
    io.change_on_read = vec![(
        3,
        Observation {
            value: external.clone(),
            companion_brightness: Some(2),
        },
    )];
    let error = transact(&mut io, &plan).unwrap_err();
    assert_eq!(io.writes, vec![plan.target, plan.previous]);
    assert_terminal_marker(&error, "oem_state_unknown");
    assert!(io.companion_writes.is_empty());
    assert_eq!(io.state.value, external);
    assert!(error
        .details
        .iter()
        .any(|s| s.starts_with("restore_brightness_not_attempted:")));
    assert!(!error
        .details
        .iter()
        .any(|s| s.starts_with("restore_confirmed:")));
}

#[cfg(target_os = "linux")]
mod linux_fixtures {
    use super::*;
    use crate::Service;
    use std::{
        fs,
        os::unix::fs::{symlink, FileTypeExt, PermissionsExt},
        path::PathBuf,
        process::{Command, Stdio},
        sync::atomic::{AtomicUsize, Ordering},
        time::{Duration, Instant},
    };

    static NEXT: AtomicUsize = AtomicUsize::new(0);
    const PLATFORM: &str = "devices/platform/tuxedo_keyboard";
    const MODULE: &str = "module/tuxedo_keyboard/srcversion";

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../.local-tests/oem-controls/core")
                .join(format!(
                    "fixture-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                ));
            fs::create_dir_all(&root).unwrap();
            let fixture = Self(root);
            fixture.put(MODULE, "ABCD0123456789ABCD012345\n");
            fs::create_dir_all(fixture.0.join(PLATFORM)).unwrap();
            fixture
        }
        fn put(&self, path: &str, contents: &str) {
            let path = self.0.join(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, contents).unwrap();
        }
        fn get(&self, path: &str) -> String {
            fs::read_to_string(self.0.join(path)).unwrap()
        }
        fn service(&self) -> Service {
            Service::with_linux_sysfs(&self.0)
        }
        fn control(&self, kind: OemControlKind) -> OemControl {
            self.service()
                .oem_controls()
                .into_iter()
                .find(|c| c.kind == kind)
                .unwrap_or_else(|| panic!("Missing fixture control: {kind:?}"))
        }
        fn boolean(&self, relative: &str, value: &str) -> String {
            let path = format!("{PLATFORM}/{relative}");
            self.put(&path, value);
            path
        }
        fn led(&self) -> PathBuf {
            self.led_named("test:kbd_backlight")
        }
        fn led_named(&self, name: &str) -> PathBuf {
            let path = self.0.join(PLATFORM).join("leds").join(name);
            fs::create_dir_all(&path).unwrap();
            fs::write(path.join("brightness"), "2\n").unwrap();
            fs::write(path.join("max_brightness"), "4\n").unwrap();
            fs::write(path.join("multi_index"), "blue red green\n").unwrap();
            fs::write(path.join("multi_intensity"), "30 10 20\n").unwrap();
            fs::write(path.join("multi_max_intensity"), "255 255 255\n").unwrap();
            fs::create_dir_all(self.0.join("class/leds")).unwrap();
            symlink(&path, self.0.join("class/leds").join(name)).unwrap();
            path
        }
        fn native(&self, bitland: bool) -> (PathBuf, PathBuf, String) {
            let (module, driver, device, name, maximum) = if bitland {
                (
                    "bitland_mifs_wmi",
                    "bus/wmi/drivers/bitland-mifs-wmi",
                    "devices/platform/PNP0C14:00/wmi_bus/wmi_bus-PNP0C14:00/B60BFB48-3E5B-49E4-A0E9-8CFFE1B3434B-4",
                    "bitland-mifs-wmi::kbd_backlight",
                    "3\n",
                )
            } else {
                (
                    "uniwill_laptop",
                    "bus/platform/drivers/uniwill-laptop",
                    "devices/platform/INOU0000:00",
                    "uniwill:white:kbd_backlight",
                    "4\n",
                )
            };
            self.put(&format!("module/{module}/srcversion"), "1234ABCD\n");
            let driver = self.0.join(driver);
            let device = self.0.join(device);
            fs::create_dir_all(&driver).unwrap();
            fs::create_dir_all(&device).unwrap();
            symlink(self.0.join("module").join(module), driver.join("module")).unwrap();
            symlink(&driver, device.join("driver")).unwrap();
            symlink(&device, driver.join(device.file_name().unwrap())).unwrap();
            self.put(
                device
                    .join("fn_lock")
                    .strip_prefix(&self.0)
                    .unwrap()
                    .to_str()
                    .unwrap(),
                "0\n",
            );
            let led = device.join("leds").join(name);
            fs::create_dir_all(&led).unwrap();
            fs::write(led.join("brightness"), "1\n").unwrap();
            fs::write(led.join("max_brightness"), maximum).unwrap();
            fs::create_dir_all(self.0.join("class/leds")).unwrap();
            symlink(&led, self.0.join("class/leds").join(name)).unwrap();
            (device, driver, format!("keyboard-brightness:{name}"))
        }
    }

    #[test]
    fn native_bitland_keyboard_brightness_uses_the_bound_driver_and_advertised_range() {
        let fixture = Fixture::new();
        let (device, _, id) = fixture.native(true);
        let service = fixture.service();
        let control = fixture.control(OemControlKind::KeyboardBrightness);
        assert_eq!(control.status, CapabilityStatus::Available);
        assert_eq!(control.source.backend, "linux_bitland_sysfs");
        assert_eq!(control.domain, OemDomain::Level { max: 3 });
        assert_eq!(
            control.source.device_id,
            Some(fs::canonicalize(&device).unwrap().display().to_string())
        );
        assert!(service.plan_oem(&id, OemValue::Level(4)).is_err());
        let plan = service.plan_oem(&id, OemValue::Level(2)).unwrap();
        let path = device.join("leds/bitland-mifs-wmi::kbd_backlight/brightness");
        assert_eq!(fs::read_to_string(&path).unwrap(), "1\n");
        assert_eq!(
            service.apply_oem(&plan).unwrap().confirmed,
            OemValue::Level(2)
        );
        assert_eq!(fs::read_to_string(path).unwrap(), "2\n");
    }

    #[test]
    fn native_uniwill_boolean_controls_preview_then_apply_without_a_tuxedo_module() {
        let fixture = Fixture::new();
        let (device, _, _) = fixture.native(false);
        fs::remove_file(fixture.0.join(MODULE)).unwrap();
        fs::write(device.join("ac_auto_boot"), "0\n").unwrap();
        fs::write(device.join("usb_powershare_high"), "0\n").unwrap();
        for (kind, attribute) in [
            (OemControlKind::FnLock, "fn_lock"),
            (OemControlKind::AcAutoBoot, "ac_auto_boot"),
            (OemControlKind::UsbPowerShare, "usb_powershare_high"),
        ] {
            let control = fixture.control(kind);
            assert_eq!(control.status, CapabilityStatus::Available);
            assert_eq!(control.source.backend, "linux_uniwill_sysfs");
            let plan = fixture
                .service()
                .plan_oem(&control.id, OemValue::Boolean(true))
                .unwrap();
            assert_eq!(fs::read_to_string(device.join(attribute)).unwrap(), "0\n");
            assert_eq!(
                fixture.service().apply_oem(&plan).unwrap().confirmed,
                OemValue::Boolean(true)
            );
        }
        assert_eq!(
            fixture.control(OemControlKind::KeyboardBrightness).domain,
            OemDomain::Level { max: 4 }
        );
    }

    #[test]
    fn native_driver_rebinding_or_module_revision_change_invalidates_a_plan() {
        for revision_change in [false, true] {
            let fixture = Fixture::new();
            let (device, _, id) = fixture.native(true);
            let plan = fixture.service().plan_oem(&id, OemValue::Level(2)).unwrap();
            if revision_change {
                fixture.put("module/bitland_mifs_wmi/srcversion", "FFFF1234\n");
            } else {
                fs::remove_file(device.join("driver")).unwrap();
                symlink(
                    fixture.0.join("bus/wmi/drivers/redmi-wmi"),
                    device.join("driver"),
                )
                .unwrap();
            }
            let error = fixture.service().apply_oem(&plan).unwrap_err();
            assert_terminal_marker(&error, "oem_rejected_before_write");
            assert_eq!(
                fs::read_to_string(device.join("leds/bitland-mifs-wmi::kbd_backlight/brightness"))
                    .unwrap(),
                "1\n"
            );
        }
    }

    #[test]
    fn native_driver_requires_its_own_loaded_module_and_device_ownership() {
        for missing in [false, true] {
            let fixture = Fixture::new();
            let (_, driver, id) = fixture.native(true);
            if missing {
                fs::remove_file(fixture.0.join("module/bitland_mifs_wmi/srcversion")).unwrap();
            } else {
                fs::remove_file(driver.join("module")).unwrap();
                symlink(
                    fixture.0.join("module/tuxedo_keyboard"),
                    driver.join("module"),
                )
                .unwrap();
            }
            assert_eq!(
                fixture.control(OemControlKind::KeyboardBrightness).status,
                CapabilityStatus::Unavailable
            );
            assert!(fixture.service().plan_oem(&id, OemValue::Level(2)).is_err());
        }
    }

    #[test]
    fn native_color_does_not_inherit_the_tuxedo_255_channel_fallback() {
        let fixture = Fixture::new();
        let (device, _, _) = fixture.native(false);
        let led = device.join("leds/uniwill:white:kbd_backlight");
        fs::write(led.join("multi_index"), "red green blue\n").unwrap();
        fs::write(led.join("multi_intensity"), "10 20 30\n").unwrap();
        assert!(!fixture
            .service()
            .oem_controls()
            .iter()
            .any(|control| control.kind == OemControlKind::KeyboardColor));
    }
    #[test]
    fn native_event_nodes_and_invalid_acpi_instances_never_authorize_controls() {
        for (bitland, name, led) in [
            (
                true,
                "46C93E13-EE9B-4262-8488-563BCA757FEF-0",
                "bitland-mifs-wmi::kbd_backlight",
            ),
            (false, "INOU0000:ZZ", "uniwill:white:kbd_backlight"),
        ] {
            let fixture = Fixture::new();
            let (device, driver, id) = fixture.native(bitland);
            let renamed = device.with_file_name(name);
            fs::rename(&device, &renamed).unwrap();
            fs::remove_file(driver.join(device.file_name().unwrap())).unwrap();
            symlink(&renamed, driver.join(name)).unwrap();
            fs::remove_file(fixture.0.join("class/leds").join(led)).unwrap();
            symlink(
                renamed.join("leds").join(led),
                fixture.0.join("class/leds").join(led),
            )
            .unwrap();
            assert!(fixture.service().plan_oem(&id, OemValue::Level(2)).is_err());
            assert!(!fixture
                .service()
                .oem_controls()
                .iter()
                .any(|control| control.source.backend != "linux_tuxedo_sysfs"
                    && control.status == CapabilityStatus::Available));
            assert_eq!(
                fs::read_to_string(renamed.join("leds").join(led).join("brightness")).unwrap(),
                "1\n"
            );
        }
    }

    #[test]
    fn native_boolean_instances_have_distinct_plans_and_never_write_the_other_device() {
        let fixture = Fixture::new();
        let (device, driver, _) = fixture.native(false);
        let second = device.with_file_name("INOU0000:01");
        fs::create_dir_all(&second).unwrap();
        fs::write(second.join("fn_lock"), "1\n").unwrap();
        symlink(&driver, second.join("driver")).unwrap();
        symlink(&second, driver.join("INOU0000:01")).unwrap();
        let controls: Vec<_> = fixture
            .service()
            .oem_controls()
            .into_iter()
            .filter(|control| {
                control.kind == OemControlKind::FnLock
                    && control.source.backend == "linux_uniwill_sysfs"
            })
            .collect();
        assert_eq!(controls.len(), 2);
        assert_ne!(controls[0].id, controls[1].id);
        let control = controls
            .iter()
            .find(|control| {
                control
                    .source
                    .device_id
                    .as_ref()
                    .unwrap()
                    .ends_with("INOU0000:01")
            })
            .unwrap();
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(false))
            .unwrap();
        assert_eq!(fs::read_to_string(second.join("fn_lock")).unwrap(), "1\n");
        assert_eq!(
            fixture.service().apply_oem(&plan).unwrap().confirmed,
            OemValue::Boolean(false)
        );
        assert_eq!(fs::read_to_string(device.join("fn_lock")).unwrap(), "0\n");
        assert_eq!(fs::read_to_string(second.join("fn_lock")).unwrap(), "0\n");
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            // Own fixture directories only. Directory permissions are never
            // reduced; the read-only attribute tests need no chmod to unlink.
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn boolean_fixed_attributes_plan_without_writing_then_apply_and_readback() {
        for (kind, path) in [
            (OemControlKind::FnLock, "fn_lock"),
            (OemControlKind::AcAutoBoot, "ac_auto_boot/ac_auto_boot"),
            (
                OemControlKind::UsbPowerShare,
                "usb_powershare/usb_powershare",
            ),
        ] {
            let fixture = Fixture::new();
            let relative = fixture.boolean(path, "0\n");
            let control = fixture.control(kind);
            assert_eq!(control.current, Some(OemValue::Boolean(false)));
            assert_eq!(control.status, CapabilityStatus::Available);
            assert!(control.writable);
            let plan = fixture
                .service()
                .plan_oem(&control.id, OemValue::Boolean(true))
                .unwrap();
            assert_eq!(fixture.get(&relative), "0\n", "preview wrote an attribute");
            let result = fixture.service().apply_oem(&plan).unwrap();
            assert_eq!(result.previous, OemValue::Boolean(false));
            assert_eq!(result.confirmed, OemValue::Boolean(true));
            assert_eq!(fixture.get(&relative).trim(), "1");
            assert_eq!(fixture.control(kind).current, Some(OemValue::Boolean(true)));
            assert!(plan.companion_brightness.is_none());
        }
    }

    #[test]
    fn charging_choices_come_from_attribute_and_invalid_choice_does_not_write() {
        let fixture = Fixture::new();
        let path = fixture.boolean("charging_profile/charging_profile", "balanced\n");
        fixture.boolean(
            "charging_profile/charging_profiles_available",
            "high_capacity balanced stationary\n",
        );
        let control = fixture.control(OemControlKind::ChargingProfile);
        assert_eq!(control.current, Some(OemValue::Choice("balanced".into())));
        assert_eq!(
            control.domain,
            OemDomain::Choices(vec![
                "high_capacity".into(),
                "balanced".into(),
                "stationary".into()
            ])
        );
        for invalid in [OemValue::Choice("80%".into()), OemValue::Boolean(true)] {
            assert!(fixture.service().plan_oem(&control.id, invalid).is_err());
            assert_eq!(fixture.get(&path), "balanced\n");
        }
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Choice("stationary".into()))
            .unwrap();
        assert_eq!(
            fixture.service().apply_oem(&plan).unwrap().confirmed,
            plan.target
        );
        assert_eq!(fixture.get(&path).trim(), "stationary");
    }

    #[test]
    fn keyboard_levels_use_advertised_maximum_and_color_uses_component_order() {
        let fixture = Fixture::new();
        let led = fixture.led();
        let level = fixture.control(OemControlKind::KeyboardBrightness);
        assert_eq!(level.domain, OemDomain::Level { max: 4 });
        assert!(fixture
            .service()
            .plan_oem(&level.id, OemValue::Level(5))
            .is_err());
        let plan = fixture
            .service()
            .plan_oem(&level.id, OemValue::Level(4))
            .unwrap();
        assert_eq!(
            fixture.service().apply_oem(&plan).unwrap().confirmed,
            OemValue::Level(4)
        );
        let color = fixture.control(OemControlKind::KeyboardColor);
        assert_eq!(color.current, Some(OemValue::Rgb([10, 20, 30])));
        let plan = fixture
            .service()
            .plan_oem(&color.id, OemValue::Rgb([40, 50, 60]))
            .unwrap();
        assert_eq!(plan.companion_brightness, Some(4));
        assert_eq!(
            fs::read_to_string(led.join("multi_intensity")).unwrap(),
            "30 10 20\n"
        );
        let result = fixture.service().apply_oem(&plan).unwrap();
        assert_eq!(result.confirmed, OemValue::Rgb([40, 50, 60]));
        assert_eq!(
            fs::read_to_string(led.join("multi_intensity"))
                .unwrap()
                .split_whitespace()
                .collect::<Vec<_>>(),
            ["60", "40", "50"]
        );
        assert_eq!(
            fs::read_to_string(led.join("brightness")).unwrap().trim(),
            "4"
        );
    }

    #[test]
    fn stale_value_and_changed_choices_reject_plans_without_overwriting_new_state() {
        let fixture = Fixture::new();
        let path = fixture.boolean("fn_lock", "0\n");
        let control = fixture.control(OemControlKind::FnLock);
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        fixture.put(&path, "1\n");
        assert!(fixture.service().apply_oem(&plan).is_err());
        assert_eq!(fixture.get(&path), "1\n");

        let path = fixture.boolean("charging_profile/charging_profile", "balanced\n");
        fixture.boolean(
            "charging_profile/charging_profiles_available",
            "balanced stationary\n",
        );
        let control = fixture.control(OemControlKind::ChargingProfile);
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Choice("stationary".into()))
            .unwrap();
        fixture.boolean(
            "charging_profile/charging_profiles_available",
            "balanced high_capacity\n",
        );
        assert!(fixture.service().apply_oem(&plan).is_err());
        assert_eq!(fixture.get(&path), "balanced\n");
    }

    #[test]
    fn forged_plan_fields_cannot_redirect_or_broaden_a_write() {
        let fixture = Fixture::new();
        let path = fixture.boolean("fn_lock", "0\n");
        fixture.put("sentinel", "never overwrite\n");
        let control = fixture.control(OemControlKind::FnLock);
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        let mut forged = Vec::new();
        let mut p = plan.clone();
        p.source.path = fixture.0.join("sentinel").display().to_string();
        forged.push(p);
        let mut p = plan.clone();
        p.source.backend.push_str("-forged");
        forged.push(p);
        let mut p = plan.clone();
        p.source.device_id = Some("forged-device".into());
        forged.push(p);
        let mut p = plan.clone();
        p.control_id.push_str("-forged");
        forged.push(p);
        let mut p = plan.clone();
        p.binding.push_str("-forged");
        forged.push(p);
        let mut p = plan.clone();
        p.domain = OemDomain::Level { max: u32::MAX };
        forged.push(p);
        let mut p = plan.clone();
        p.kind = OemControlKind::AcAutoBoot;
        forged.push(p);
        let mut p = plan.clone();
        p.target = OemValue::Level(999);
        forged.push(p);
        let mut p = plan.clone();
        p.previous = OemValue::Boolean(true);
        forged.push(p);
        let mut p = plan.clone();
        p.companion_brightness = Some(4);
        forged.push(p);
        for p in forged {
            let error = fixture.service().apply_oem(&p).unwrap_err();
            assert_terminal_marker(&error, "oem_rejected_before_write");
            assert_eq!(fixture.get(&path), "0\n");
            assert_eq!(fixture.get("sentinel"), "never overwrite\n");
        }
    }

    #[test]
    fn module_change_or_device_replacement_invalidates_existing_plan() {
        let fixture = Fixture::new();
        let path = fixture.boolean("fn_lock", "0\n");
        let control = fixture.control(OemControlKind::FnLock);
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        fixture.put(MODULE, "FFFF0123456789ABCD012345\n");
        assert!(fixture.service().apply_oem(&plan).is_err());
        assert_eq!(fixture.get(&path), "0\n");
        fixture.put(MODULE, "ABCD0123456789ABCD012345\n");
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        let replacement = fixture
            .0
            .join("devices/platform/tuxedo_keyboard-replacement");
        fs::create_dir_all(&replacement).unwrap();
        fs::write(replacement.join("fn_lock"), "0\n").unwrap();
        fs::rename(fixture.0.join(PLATFORM), fixture.0.join("old-device")).unwrap();
        fs::rename(replacement, fixture.0.join(PLATFORM)).unwrap();
        assert!(fixture.service().apply_oem(&plan).is_err());
        assert_eq!(fixture.get(&path), "0\n");
    }

    #[test]
    fn unavailable_driver_and_strict_invalid_values_never_produce_writable_controls() {
        let fixture = Fixture::new();
        let path = fixture.boolean("fn_lock", "0\n");
        for invalid in ["", "2\n", "true\n", "1 0\n", "+1\n", "01\n"] {
            fixture.put(&path, invalid);
            let control = fixture.control(OemControlKind::FnLock);
            assert!(
                control.current.is_none(),
                "accepted invalid boolean: {invalid:?}"
            );
            assert!(!control.writable);
            assert_ne!(control.status, CapabilityStatus::Available);
            assert!(fixture
                .service()
                .plan_oem(&control.id, OemValue::Boolean(true))
                .is_err());
            assert_eq!(fixture.get(&path), invalid);
        }
        fixture.put(&path, "0\n");
        for invalid in ["", "not-a-module-hash\n"] {
            fixture.put(MODULE, invalid);
            assert!(fixture.service().oem_controls().iter().all(|c| !c.writable));
        }
        fs::remove_file(fixture.0.join(MODULE)).unwrap();
        assert!(fixture.service().oem_controls().iter().all(|c| !c.writable));
    }

    #[test]
    fn read_only_attribute_is_reported_and_revoked_write_permission_is_rechecked() {
        let uid = Command::new("id").arg("-u").output().unwrap();
        assert!(uid.status.success());
        assert_ne!(
            String::from_utf8_lossy(&uid.stdout).trim(),
            "0",
            "permission regression must run as an ordinary user"
        );
        let fixture = Fixture::new();
        let path = fixture.boolean("fn_lock", "0\n");
        let control = fixture.control(OemControlKind::FnLock);
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        fs::set_permissions(fixture.0.join(&path), fs::Permissions::from_mode(0o444)).unwrap();
        let control = fixture.control(OemControlKind::FnLock);
        assert_eq!(control.current, Some(OemValue::Boolean(false)));
        assert!(!control.writable);
        let readonly_plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        assert!(readonly_plan.requires_privilege);
        assert_eq!(fixture.get(&path), "0\n", "readonly preview changed bytes");
        assert_eq!(control.status, CapabilityStatus::Available);
        let error = fixture.service().apply_oem(&readonly_plan).unwrap_err();
        assert_terminal_marker(&error, "oem_rejected_before_write");
        let error = fixture.service().apply_oem(&plan).unwrap_err();
        assert_terminal_marker(&error, "oem_rejected_before_write");
        assert_eq!(fixture.get(&path), "0\n");
    }

    #[test]
    fn escaped_attribute_and_led_alias_never_read_or_write_unowned_targets() {
        let fixture = Fixture::new();
        fixture.put("outside/fn_lock", "0\n");
        let attribute = fixture.0.join(PLATFORM).join("fn_lock");
        symlink(fixture.0.join("outside/fn_lock"), &attribute).unwrap();
        let controls = fixture.service().oem_controls();
        assert!(controls
            .iter()
            .filter(|c| c.kind == OemControlKind::FnLock)
            .all(|c| !c.writable));
        assert_eq!(fixture.get("outside/fn_lock"), "0\n");

        let outside_led = fixture.0.join("outside/unowned:kbd_backlight");
        fs::create_dir_all(&outside_led).unwrap();
        fs::write(outside_led.join("brightness"), "2\n").unwrap();
        fs::write(outside_led.join("max_brightness"), "4\n").unwrap();
        fs::create_dir_all(fixture.0.join("class/leds")).unwrap();
        symlink(
            &outside_led,
            fixture.0.join("class/leds/unowned:kbd_backlight"),
        )
        .unwrap();
        assert!(fixture
            .service()
            .oem_controls()
            .iter()
            .filter(|c| c.kind == OemControlKind::KeyboardBrightness)
            .all(|c| !c.writable));
        assert_eq!(
            fs::read_to_string(outside_led.join("brightness")).unwrap(),
            "2\n"
        );
    }

    #[test]
    fn rgb_requires_unique_components_and_safe_range_without_guessing() {
        let fixture = Fixture::new();
        let led = fixture.led();
        for invalid in [
            "red red blue\n",
            "red green white\n",
            "red green blue white\n",
        ] {
            fs::write(led.join("multi_index"), invalid).unwrap();
            assert!(fixture
                .service()
                .oem_controls()
                .iter()
                .filter(|c| c.kind == OemControlKind::KeyboardColor)
                .all(|c| !c.writable));
        }
        fs::write(led.join("multi_index"), "blue red green\n").unwrap();
        for invalid in ["256 10 20\n", "30 10\n", "-1 10 20\n"] {
            fs::write(led.join("multi_intensity"), invalid).unwrap();
            assert!(fixture
                .service()
                .oem_controls()
                .iter()
                .filter(|c| c.kind == OemControlKind::KeyboardColor)
                .all(|c| !c.writable));
        }
        fs::write(led.join("multi_intensity"), "30 10 20\n").unwrap();
        for invalid in ["100 100 100\n", "255 255\n", "255 -1 255\n"] {
            fs::write(led.join("multi_max_intensity"), invalid).unwrap();
            assert!(fixture
                .service()
                .oem_controls()
                .iter()
                .filter(|c| c.kind == OemControlKind::KeyboardColor)
                .all(|c| !c.writable));
        }
        fs::remove_file(led.join("multi_max_intensity")).unwrap();
        assert!(fixture
            .service()
            .oem_controls()
            .iter()
            .filter(|c| c.kind == OemControlKind::KeyboardColor)
            .all(|c| !c.writable));
        assert!(fixture.control(OemControlKind::KeyboardBrightness).writable);
    }

    #[test]
    fn rgb_plan_binds_companion_brightness_and_component_order() {
        let fixture = Fixture::new();
        let led = fixture.led();
        let color = fixture.control(OemControlKind::KeyboardColor);
        let plan = fixture
            .service()
            .plan_oem(&color.id, OemValue::Rgb([40, 50, 60]))
            .unwrap();
        fs::write(led.join("brightness"), "3\n").unwrap();
        assert!(fixture.service().apply_oem(&plan).is_err());
        assert_eq!(
            fs::read_to_string(led.join("multi_intensity")).unwrap(),
            "30 10 20\n"
        );
        assert_eq!(fs::read_to_string(led.join("brightness")).unwrap(), "3\n");
        fs::write(led.join("brightness"), "2\n").unwrap();
        fs::write(led.join("multi_index"), "red green blue\n").unwrap();
        assert!(fixture.service().apply_oem(&plan).is_err());
        assert_eq!(
            fs::read_to_string(led.join("multi_intensity")).unwrap(),
            "30 10 20\n"
        );
    }

    #[test]
    fn missing_rgb_maximum_compatibility_requires_exact_name_and_driver_ownership() {
        let fixture = Fixture::new();
        let led = fixture.led_named("rgb:kbd_backlight");
        fs::remove_file(led.join("multi_max_intensity")).unwrap();
        let color = fixture.control(OemControlKind::KeyboardColor);
        assert_eq!(color.status, CapabilityStatus::Available);
        assert!(color.writable);
        assert_eq!(color.current, Some(OemValue::Rgb([10, 20, 30])));
        assert!(color
            .reason
            .as_deref()
            .unwrap()
            .contains("multi_max_intensity"));
        let plan = fixture
            .service()
            .plan_oem(&color.id, OemValue::Rgb([17, 93, 241]))
            .unwrap();
        assert_eq!(
            fixture.service().apply_oem(&plan).unwrap().confirmed,
            OemValue::Rgb([17, 93, 241])
        );
        assert_eq!(
            fs::read_to_string(led.join("multi_intensity"))
                .unwrap()
                .trim(),
            "241 17 93"
        );
        assert_eq!(
            fs::read_to_string(led.join("brightness")).unwrap().trim(),
            "2"
        );

        // A present contradictory range cannot use the old-kernel fallback.
        fs::write(led.join("multi_max_intensity"), "127 127 127\n").unwrap();
        let unavailable = fixture.control(OemControlKind::KeyboardColor);
        assert!(unavailable.current.is_none());
        assert!(!unavailable.writable);
        assert!(fixture
            .service()
            .plan_oem(&color.id, OemValue::Rgb([0, 0, 0]))
            .is_err());

        let similar = Fixture::new();
        let led = similar.led_named("test:rgb:kbd_backlight");
        fs::remove_file(led.join("multi_max_intensity")).unwrap();
        let control = similar.control(OemControlKind::KeyboardColor);
        assert!(control.current.is_none());
        assert!(!control.writable);
        assert!(similar
            .service()
            .plan_oem(&control.id, OemValue::Rgb([0, 0, 0]))
            .is_err());

        let unowned = Fixture::new();
        let led = unowned.led_named("rgb:kbd_backlight");
        fs::remove_file(led.join("multi_max_intensity")).unwrap();
        let outside = unowned.0.join("outside/rgb:kbd_backlight");
        fs::create_dir_all(outside.parent().unwrap()).unwrap();
        fs::rename(&led, &outside).unwrap();
        let alias = unowned.0.join("class/leds/rgb:kbd_backlight");
        fs::remove_file(&alias).unwrap();
        symlink(&outside, alias).unwrap();
        let control = unowned.control(OemControlKind::KeyboardColor);
        assert!(control.current.is_none());
        assert!(!control.writable);
        assert!(unowned
            .service()
            .plan_oem(&control.id, OemValue::Rgb([0, 0, 0]))
            .is_err());
        assert_eq!(
            fs::read_to_string(outside.join("multi_intensity")).unwrap(),
            "30 10 20\n"
        );
    }

    #[test]
    fn oversized_and_directory_attributes_are_unavailable_without_a_setter_plan() {
        let fixture = Fixture::new();
        let relative = fixture.boolean("fn_lock", &"0".repeat(4097));
        let control = fixture.control(OemControlKind::FnLock);
        assert!(control.current.is_none());
        assert!(!control.writable);
        assert!(fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .is_err());
        assert_eq!(fixture.get(&relative).len(), 4097);
        fs::remove_file(fixture.0.join(&relative)).unwrap();
        fs::create_dir(fixture.0.join(&relative)).unwrap();
        let control = fixture.control(OemControlKind::FnLock);
        assert!(control.current.is_none());
        assert!(!control.writable);
        assert!(fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .is_err());
        assert!(fixture.0.join(&relative).is_dir());
    }

    #[test]
    fn non_regular_attributes_are_rejected_without_blocking_on_fifo() {
        const CHILD_ROOT: &str = "MECHREVO_TEST_OEM_FIFO_ROOT";
        const CHILD_PLAN: &str = "MECHREVO_TEST_OEM_FIFO_PLAN";
        const COMPLETED: &str = "OEM_FIFO_REJECTION_COMPLETED";
        if let Some(root) = std::env::var_os(CHILD_ROOT) {
            let root = PathBuf::from(root);
            assert!(fs::metadata(root.join(PLATFORM).join("fn_lock"))
                .unwrap()
                .file_type()
                .is_fifo());
            let service = Service::with_linux_sysfs(&root);
            assert!(service.oem_controls().iter().all(|c| !c.writable));
            assert!(service
                .plan_oem("fn-lock", OemValue::Boolean(true))
                .is_err());
            let plan: OemPlan = serde_json::from_str(&std::env::var(CHILD_PLAN).unwrap()).unwrap();
            assert!(service.apply_oem(&plan).is_err());
            println!("{COMPLETED}");
            return;
        }
        let fixture = Fixture::new();
        fixture.boolean("fn_lock", "0\n");
        let control = fixture.control(OemControlKind::FnLock);
        let plan = fixture
            .service()
            .plan_oem(&control.id, OemValue::Boolean(true))
            .unwrap();
        let attribute = fixture.0.join(PLATFORM).join("fn_lock");
        fs::remove_file(&attribute).unwrap();
        let status = Command::new("mkfifo")
            .arg(&attribute)
            .status()
            .expect("Linux FIFO regression requires mkfifo");
        assert!(status.success());
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "oem::tests::linux_fixtures::non_regular_attributes_are_rejected_without_blocking_on_fifo", "--nocapture"])
            .env(CHILD_ROOT, &fixture.0)
            .env(CHILD_PLAN, serde_json::to_string(&plan).unwrap())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn().expect("Cannot start bounded OEM FIFO child");
        let deadline = Instant::now() + Duration::from_secs(5);
        let completion = loop {
            match child.try_wait() {
                Ok(Some(_)) => break Ok(()),
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(10))
                }
                Ok(None) => break Err("OEM discovery blocked on FIFO for 5 seconds".to_owned()),
                Err(error) => break Err(format!("Cannot wait for FIFO child: {error}")),
            }
        };
        if completion.is_err() {
            let _ = child.kill();
        }
        let output = child.wait_with_output().unwrap();
        assert!(completion.is_ok(), "{completion:?}");
        assert!(
            output.status.success(),
            "FIFO child failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(
            String::from_utf8_lossy(&output.stdout).contains(COMPLETED),
            "Exact FIFO regression was not executed: {}",
            String::from_utf8_lossy(&output.stdout)
        );
    }
}
