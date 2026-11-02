use mechrevo_console_core::{
    registry, ControlError, OemControl, OemControlKind, OemDomain, OemValue, PowerProfile, Service,
    Snapshot,
};
use serde_json::{json, Value};
#[cfg(any(target_os = "linux", test))]
use std::io::Read;
use std::{
    ffi::OsString,
    fs::OpenOptions,
    io::{self, Write},
    path::PathBuf,
    str::FromStr,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
const HELP:&str="mechrevo-console 0.1.0 — Windows/Linux OS controls and evidence\n\nUsage:\n  mechrevo-console status [--json]\n  mechrevo-console capabilities\n  mechrevo-console models [query]\n  mechrevo-console profile <balanced|performance|power-saver> [--dry-run]\n  mechrevo-console brightness [percent] [--device ID] [--dry-run]\n  mechrevo-console oem list\n  mechrevo-console oem set ID VALUE [--dry-run]\n  mechrevo-console export --output PATH\n  mechrevo-console --help\n\nPower profiles use Linux ACPI platform_profile or installed Windows OS power\nschemes. They are separate from OEM presets and never tune GPU/MUX/EC registers.\nBrightness requires an enumerated OS device; multiple devices require --device.\nOEM controls use only enumerated, qualified driver interfaces. Use oem list\nfor exact IDs, choices, brightness levels and readback limits. Boolean values\nare on/off; colors use '#RRGGBB'. OEM --dry-run never writes or elevates.\nAn OEM write may request authentication through the installed limited helper.\nExport writes UTF-8 JSON, requires an explicit path and refuses overwrites.\nMissing telemetry is unknown, never a simulated zero. No automatic sudo.\n";
#[derive(Debug, PartialEq)]
enum Action {
    Help,
    Version,
    Status(bool),
    Capabilities,
    Models(String),
    Profile(PowerProfile, bool),
    Brightness(Option<u8>, Option<String>, bool),
    OemList,
    OemSet(String, String, bool),
    Export(PathBuf),
}
fn text(arg: &OsString) -> Result<&str, ControlError> {
    arg.to_str()
        .ok_or_else(|| ControlError::new("invalid_argument", "This argument must be valid Unicode"))
}
fn usage(message: impl Into<String>) -> ControlError {
    ControlError::new("invalid_arguments", message)
}
fn parse(args: Vec<OsString>) -> Result<Action, ControlError> {
    let Some(command) = args.first() else {
        return Ok(Action::Help);
    };
    let command = text(command)?;
    let rest = &args[1..];
    match command {
        "--help" | "-h" if rest.is_empty() => Ok(Action::Help),
        "--version" | "-V" if rest.is_empty() => Ok(Action::Version),
        "status" if rest.is_empty() => Ok(Action::Status(false)),
        "status" if rest.len() == 1 && rest[0] == "--json" => Ok(Action::Status(true)),
        "capabilities" if rest.is_empty() => Ok(Action::Capabilities),
        "models" if rest.len() <= 1 => Ok(Action::Models(
            rest.first().map(text).transpose()?.unwrap_or("").into(),
        )),
        "profile" => {
            if rest.is_empty() || rest.len() > 2 {
                return Err(usage("profile requires one profile and optional --dry-run"));
            }
            let profile = PowerProfile::from_str(text(&rest[0])?)?;
            let dry = rest.len() == 2;
            if dry && rest[1] != "--dry-run" {
                return Err(usage("Unknown profile option"));
            }
            Ok(Action::Profile(profile, dry))
        }
        "brightness" => {
            let mut percent = None;
            let mut device = None;
            let mut dry = false;
            let mut i = 0;
            while i < rest.len() {
                let token = text(&rest[i])?;
                match token {
                    "--dry-run" if !dry => dry = true,
                    "--device" if device.is_none() => {
                        i += 1;
                        let arg = rest
                            .get(i)
                            .ok_or_else(|| usage("--device needs a device ID"))?;
                        let id = text(arg)?;
                        if id.is_empty() {
                            return Err(usage("Device ID must not be empty"));
                        }
                        device = Some(id.into());
                    }
                    value if percent.is_none() => {
                        let value = value.parse::<u16>().map_err(|_| {
                            usage("Brightness percent must be an integer from 0 through 100")
                        })?;
                        if value > 100 {
                            return Err(usage("Brightness percent must be 0 through 100"));
                        }
                        percent = Some(value as u8);
                    }
                    _ => return Err(usage("Unknown or repeated brightness argument")),
                }
                i += 1;
            }
            if dry && percent.is_none() {
                return Err(usage("--dry-run requires a target percent"));
            }
            Ok(Action::Brightness(percent, device, dry))
        }
        "oem" if rest.len() == 1 && rest[0] == "list" => Ok(Action::OemList),
        "oem" if (rest.len() == 3 || rest.len() == 4) && rest[0] == "set" => {
            let id = text(&rest[1])?;
            let value = text(&rest[2])?;
            if id.is_empty() || value.is_empty() || id.starts_with("--") || value.starts_with("--")
            {
                return Err(usage("oem set requires a control ID and a value"));
            }
            let dry = rest.len() == 4;
            if dry && rest[3] != "--dry-run" {
                return Err(usage("Unknown OEM option; only --dry-run is accepted"));
            }
            Ok(Action::OemSet(id.into(), value.into(), dry))
        }
        "oem" => Err(usage("Use oem list or oem set ID VALUE [--dry-run]")),
        "export" if rest.len() == 2 && rest[0] == "--output" && !rest[1].is_empty() => {
            Ok(Action::Export(PathBuf::from(&rest[1])))
        }
        "export" => Err(usage(
            "export requires --output PATH; existing files are never replaced",
        )),
        _ => Err(usage("Unknown command or invalid options; use --help")),
    }
}
fn select_oem_control<'a>(
    controls: &'a [OemControl],
    id: &str,
) -> Result<&'a OemControl, ControlError> {
    let mut matching = controls.iter().filter(|control| control.id == id);
    let selected = matching.next().ok_or_else(|| {
        ControlError::new(
            "oem_control_unavailable",
            "Requested OEM control was not enumerated; use oem list for exact IDs",
        )
    })?;
    if matching.next().is_some() {
        return Err(ControlError::new(
            "oem_control_ambiguous",
            "Multiple OEM controls have this ID; no write was attempted",
        ));
    }
    Ok(selected)
}
fn oem_value_error(message: impl Into<String>) -> ControlError {
    ControlError::new("invalid_oem_value", message)
}
fn parse_oem_value(
    kind: &OemControlKind,
    domain: &OemDomain,
    raw: &str,
) -> Result<OemValue, ControlError> {
    match (kind, domain) {
        (
            OemControlKind::FnLock | OemControlKind::AcAutoBoot | OemControlKind::UsbPowerShare,
            OemDomain::Boolean,
        ) => match raw {
            "on" => Ok(OemValue::Boolean(true)),
            "off" => Ok(OemValue::Boolean(false)),
            _ => Err(oem_value_error("Boolean OEM controls require on or off")),
        },
        (
            OemControlKind::ChargingProfile | OemControlKind::PerformanceProfile,
            OemDomain::Choices(choices),
        ) => {
            if choices.iter().any(|choice| choice == raw) {
                Ok(OemValue::Choice(raw.into()))
            } else {
                Err(oem_value_error(
                    "Profile must be one of the exact choices returned by oem list",
                ))
            }
        }
        (OemControlKind::KeyboardBrightness, OemDomain::Level { max }) => {
            if raw.is_empty() || !raw.bytes().all(|byte| byte.is_ascii_digit()) {
                return Err(oem_value_error(
                    "Keyboard brightness requires a nonnegative integer level",
                ));
            }
            let level = raw.parse::<u32>().map_err(|_| {
                oem_value_error("Keyboard brightness level exceeds the integer range")
            })?;
            if level > *max {
                return Err(oem_value_error(format!(
                    "Keyboard brightness must be between 0 and {max}"
                )));
            }
            Ok(OemValue::Level(level))
        }
        (OemControlKind::KeyboardColor, OemDomain::Rgb) => {
            if raw.len() != 7
                || !raw.starts_with('#')
                || !raw.as_bytes()[1..].iter().all(u8::is_ascii_hexdigit)
            {
                return Err(oem_value_error("Keyboard color requires #RRGGBB"));
            }
            let rgb = u32::from_str_radix(&raw[1..], 16)
                .map_err(|_| oem_value_error("Keyboard color requires #RRGGBB"))?;
            Ok(OemValue::Rgb([
                (rgb >> 16) as u8,
                (rgb >> 8) as u8,
                rgb as u8,
            ]))
        }
        _ => Err(ControlError::new(
            "invalid_oem_domain",
            "Enumerated OEM control kind and value domain do not agree; no write was attempted",
        )),
    }
}
fn oem_set_output(
    dry_run: bool,
    plan: Value,
    apply: impl FnOnce() -> Result<Value, ControlError>,
) -> Result<Value, ControlError> {
    if dry_run {
        Ok(json!({"dry_run":true,"plan":plan}))
    } else {
        apply()
    }
}
fn set_oem(service: &Service, id: &str, raw: &str, dry_run: bool) -> Result<Value, ControlError> {
    let controls = service.oem_controls();
    let control = select_oem_control(&controls, id)?;
    let target = parse_oem_value(&control.kind, &control.domain, raw)?;
    let plan = service.plan_oem(id, target)?;
    let plan_json = serde_json::to_value(&plan)
        .map_err(|error| ControlError::new("serialization_failed", error.to_string()))?;
    oem_set_output(dry_run, plan_json, || {
        let applied = mechrevo_console_core::privilege::apply_oem(service, &plan)?;
        serde_json::to_value(applied)
            .map_err(|error| ControlError::new("serialization_failed", error.to_string()))
    })
}
fn duration_json(duration: Duration) -> Value {
    json!({"seconds":duration.as_secs(),"nanoseconds":duration.subsec_nanos()})
}
fn epoch_json(time: SystemTime) -> Value {
    match time.duration_since(UNIX_EPOCH) {
        Ok(duration) => {
            json!({"unix_seconds":duration.as_secs(),"nanoseconds":duration.subsec_nanos()})
        }
        Err(_) => Value::Null,
    }
}
#[cfg(any(target_os = "linux", test))]
fn read_kernel_release(reader: impl Read) -> Value {
    const MAX_BYTES: usize = 256;
    let source = "/proc/sys/kernel/osrelease";
    let mut bytes = Vec::new();
    if let Err(error) = reader.take((MAX_BYTES + 1) as u64).read_to_end(&mut bytes) {
        return json!({"value":null,"source":source,"status":"read_failed","reason":error.to_string()});
    }
    if bytes.len() > MAX_BYTES {
        return json!({"value":null,"source":source,"status":"invalid_data","reason":"Kernel release exceeds the 256-byte limit"});
    }
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return json!({"value":null,"source":source,"status":"invalid_data","reason":"Kernel release is not UTF-8"});
    };
    let release = text.trim();
    if release.is_empty() || !release.bytes().all(|byte| byte.is_ascii_graphic()) {
        return json!({"value":null,"source":source,"status":"invalid_data","reason":"Kernel release is empty or contains non-printable characters"});
    }
    json!({"value":release,"source":source,"status":"available"})
}
fn runtime_metadata() -> Value {
    #[cfg(target_os = "linux")]
    let kernel_release = match std::fs::File::open("/proc/sys/kernel/osrelease") {
        Ok(file) => read_kernel_release(file),
        Err(error) => {
            json!({"value":null,"source":"/proc/sys/kernel/osrelease","status":"read_failed","reason":error.to_string()})
        }
    };
    #[cfg(not(target_os = "linux"))]
    let kernel_release = json!({"value":null,"source":null,"status":"not_collected","reason":"Runtime kernel release collection is implemented only for Linux"});
    json!({"kernel_release":kernel_release})
}
fn collect_status_json(
    snapshot_provider: impl FnOnce() -> Snapshot,
    mut wall_clock: impl FnMut() -> SystemTime,
    mut monotonic_clock: impl FnMut() -> Instant,
    runtime: Value,
) -> Result<Value, ControlError> {
    let monotonic_start = monotonic_clock();
    let started_at = wall_clock();
    let snapshot = snapshot_provider();
    let finished_at = wall_clock();
    let monotonic_finish = monotonic_clock();
    let elapsed = monotonic_finish.checked_duration_since(monotonic_start);
    let wall_clock_status = if started_at.duration_since(UNIX_EPOCH).is_err()
        || finished_at.duration_since(UNIX_EPOCH).is_err()
    {
        "before_unix_epoch"
    } else if finished_at < started_at {
        "moved_backwards"
    } else {
        "ordered"
    };
    let identification = registry::identify(&snapshot.identity);
    let mut value = serde_json::to_value(&snapshot)
        .map_err(|e| ControlError::new("serialization_failed", e.to_string()))?;
    value["identity_evidence"] = serde_json::to_value(identification)
        .map_err(|e| ControlError::new("serialization_failed", e.to_string()))?;
    value["schema_version"] = 1.into();
    value["collection"] = json!({
        "started_at":epoch_json(started_at),
        "finished_at":epoch_json(finished_at),
        "wall_clock_status":wall_clock_status,
        "monotonic_elapsed":elapsed.map(duration_json),
        "monotonic_clock_status":if elapsed.is_some(){"ordered"}else{"moved_backwards"},
        "time_basis":"UTC Unix epoch; seconds and nanoseconds are exact integer components. A timestamp before the epoch is null. Wall-clock ordering does not prove clock synchronization.",
        "consistency":"non_atomic_sequential_reads",
        "scope":"One complete Service::snapshot() call, including brightness enumeration and OEM controls. Start and finish wall-clock reads surround that call; monotonic elapsed also includes those clock reads. Excludes runtime metadata collection, model matching and JSON serialization. Values may come from different instants or cached OS readings; this is not a simultaneous hardware sample.",
        "tool":{"name":"mechrevo-console","package":env!("CARGO_PKG_NAME"),"version":env!("CARGO_PKG_VERSION")},
        "build_target":{"os":std::env::consts::OS,"arch":std::env::consts::ARCH},
        "runtime":runtime,
    });
    Ok(value)
}
fn status_json(service: &Service) -> Result<Value, ControlError> {
    let runtime = runtime_metadata();
    collect_status_json(
        || service.snapshot(),
        SystemTime::now,
        Instant::now,
        runtime,
    )
}
fn write_json(writer: &mut impl Write, value: &Value) -> Result<(), ControlError> {
    serde_json::to_writer_pretty(&mut *writer, value)
        .map_err(|e| ControlError::new("output_failed", e.to_string()))?;
    writeln!(writer).map_err(|e| ControlError::new("output_failed", e.to_string()))
}
// @mark mechrevo.console_cli role=implementation
fn export(path: &std::path::Path, value: &Value) -> Result<(), ControlError> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|e| ControlError::new("export_failed", format!("{}: {e}", path.display())))?;
    // create_new is race-safe: symlinks and existing recovery material are refused.
    write_json(&mut file, value)?;
    file.sync_all()
        .map_err(|e| ControlError::new("export_failed", format!("{}: {e}", path.display())))
}
fn run(action: Action, service: &Service) -> Result<(), ControlError> {
    let mut stdout = io::stdout().lock();
    let output = match action {
        Action::Help => {
            write!(stdout, "{HELP}")
                .map_err(|e| ControlError::new("output_failed", e.to_string()))?;
            return Ok(());
        }
        Action::Version => json!({"version":env!("CARGO_PKG_VERSION")}),
        Action::Status(true) => status_json(service)?,
        Action::Status(false) => {
            let s = service.snapshot();
            writeln!(stdout,"Platform: {}\nManufacturer: {}\nProduct: {}\nBoard: {}\nBIOS: {}\nSupport: {}\nPower policy: {}\nCurrent: {}",s.platform,s.identity.manufacturer.as_deref().unwrap_or("unknown"),s.identity.product_name.as_deref().unwrap_or("unknown"),s.identity.board_name.as_deref().unwrap_or("unknown"),s.identity.bios_version.as_deref().unwrap_or("unknown"),registry::identify(&s.identity).reason,s.power_policy.scope,s.power_policy.current.as_deref().unwrap_or("unknown")).map_err(|e|ControlError::new("output_failed",e.to_string()))?;
            for r in s.telemetry {
                writeln!(
                    stdout,
                    "{}: {} {} [device={} source={}]",
                    r.label,
                    r.value.map(|v| v.to_string()).unwrap_or("unknown".into()),
                    r.unit,
                    r.device_id,
                    r.source.path
                )
                .map_err(|e| ControlError::new("output_failed", e.to_string()))?;
            }
            for control in s.oem_controls {
                let current = control
                    .current
                    .as_ref()
                    .map(|value| json!(value).to_string())
                    .unwrap_or_else(|| "unknown".into());
                writeln!(
                    stdout,
                    "OEM {} ({}): {} [{:?}]",
                    control.id, control.label, current, control.status
                )
                .map_err(|error| ControlError::new("output_failed", error.to_string()))?;
            }
            for d in s.diagnostics {
                writeln!(stdout, "{}: {}", d.code, d.message)
                    .map_err(|e| ControlError::new("output_failed", e.to_string()))?;
            }
            return Ok(());
        }
        Action::Capabilities => json!(service.capabilities()),
        Action::Models(query) => json!(service.catalog(&query)),
        Action::OemList => json!(service.oem_controls()),
        Action::OemSet(id, value, dry_run) => set_oem(service, &id, &value, dry_run)?,
        Action::Profile(profile, dry) => {
            let plan = service.plan_profile(profile)?;
            if dry {
                json!({"dry_run":true,"plan":plan})
            } else {
                json!(service.apply_profile(&plan)?)
            }
        }
        Action::Brightness(None, device, _) => {
            let devices = service.brightness_devices();
            if let Some(id) = device {
                let selected = devices
                    .into_iter()
                    .filter(|d| d.id == id)
                    .collect::<Vec<_>>();
                if selected.is_empty() {
                    return Err(ControlError::new(
                        "brightness_device_unavailable",
                        "Requested device was not enumerated",
                    ));
                }
                json!(selected)
            } else {
                json!(devices)
            }
        }
        Action::Brightness(Some(percent), device, dry) => {
            let plan = service.plan_brightness(percent, device.as_deref())?;
            if dry {
                json!({"dry_run":true,"plan":plan})
            } else {
                json!(service.apply_brightness(&plan)?)
            }
        }
        Action::Export(path) => {
            let value = status_json(service)?;
            export(&path, &value)?;
            json!({"exported":path,"encoding":"UTF-8","schema_version":1})
        }
    };
    write_json(&mut stdout, &output)
}
fn main() {
    let result = parse(std::env::args_os().skip(1).collect())
        .and_then(|action| run(action, &Service::new()));
    if let Err(error) = result {
        let _ = write_json(&mut io::stderr().lock(), &json!({"error":error}));
        std::process::exit(2)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use mechrevo_console_core::{BrightnessDevice, CapabilityStatus, EvidenceSource, Identity};
    use std::cell::RefCell;

    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }
    #[test]
    fn oem_commands_require_explicit_control_value_and_known_options() {
        assert_eq!(parse(args(&["oem", "list"])).unwrap(), Action::OemList);
        assert_eq!(
            parse(args(&["oem", "set", "fn_lock", "on"])).unwrap(),
            Action::OemSet("fn_lock".into(), "on".into(), false)
        );
        assert_eq!(
            parse(args(&[
                "oem",
                "set",
                "keyboard_color",
                "#ab12CD",
                "--dry-run"
            ]))
            .unwrap(),
            Action::OemSet("keyboard_color".into(), "#ab12CD".into(), true)
        );
        for values in [
            vec!["oem"],
            vec!["oem", "list", "--dry-run"],
            vec!["oem", "set"],
            vec!["oem", "set", "fn_lock"],
            vec!["oem", "set", "", "on"],
            vec!["oem", "set", "fn_lock", ""],
            vec!["oem", "set", "fn_lock", "--dry-run"],
            vec!["oem", "set", "--dry-run", "on"],
            vec!["oem", "set", "fn_lock", "on", "--force"],
            vec!["oem", "set", "fn_lock", "on", "--dry-run", "--dry-run"],
            vec!["oem", "apply", "fn_lock", "on"],
        ] {
            assert!(parse(args(&values)).is_err(), "Accepted {values:?}");
        }
    }
    #[test]
    fn oem_boolean_and_choice_values_follow_the_enumerated_domain() {
        for kind in [
            OemControlKind::FnLock,
            OemControlKind::AcAutoBoot,
            OemControlKind::UsbPowerShare,
        ] {
            assert_eq!(
                json!(parse_oem_value(&kind, &OemDomain::Boolean, "on").unwrap()),
                json!({"type":"boolean","value":true})
            );
            assert_eq!(
                json!(parse_oem_value(&kind, &OemDomain::Boolean, "off").unwrap()),
                json!({"type":"boolean","value":false})
            );
            for raw in ["1", "0", "true", "ON", "on ", "$(touch /tmp/invalid)"] {
                assert!(parse_oem_value(&kind, &OemDomain::Boolean, raw).is_err());
            }
        }
        let choices = OemDomain::Choices(vec!["high_capacity".into(), "balanced".into()]);
        assert_eq!(
            json!(parse_oem_value(&OemControlKind::ChargingProfile, &choices, "balanced").unwrap()),
            json!({"type":"choice","value":"balanced"})
        );
        for raw in [
            "80",
            "stationary",
            "BALANCED",
            "balanced\n",
            "../balanced",
            "balanced; exit",
        ] {
            assert!(parse_oem_value(&OemControlKind::ChargingProfile, &choices, raw).is_err());
        }
        assert!(parse_oem_value(
            &OemControlKind::ChargingProfile,
            &OemDomain::Choices(Vec::new()),
            "balanced"
        )
        .is_err());
        assert!(parse_oem_value(&OemControlKind::FnLock, &choices, "balanced").is_err());
        assert!(
            parse_oem_value(&OemControlKind::ChargingProfile, &OemDomain::Boolean, "on").is_err()
        );
    }
    #[test]
    fn performance_profile_values_require_an_exact_enumerated_choice() {
        let kind = OemControlKind::PerformanceProfile;
        let choices = OemDomain::Choices(vec!["mechrevo_turbo".into()]);
        assert_eq!(
            parse_oem_value(&kind, &choices, "mechrevo_turbo").unwrap(),
            OemValue::Choice("mechrevo_turbo".into())
        );
        for raw in [
            "turbo",
            "mechrevo_office",
            "MECHREVO_TURBO",
            "mechrevo_turbo; exit",
        ] {
            assert!(parse_oem_value(&kind, &choices, raw).is_err());
        }
        assert!(parse_oem_value(&kind, &OemDomain::Boolean, "on").is_err());
        assert!(parse_oem_value(&kind, &OemDomain::Choices(vec![]), "mechrevo_turbo").is_err());
    }
    #[test]
    fn oem_brightness_uses_raw_levels_and_actual_maximum() {
        let kind = OemControlKind::KeyboardBrightness;
        let domain = OemDomain::Level { max: 4 };
        for (raw, expected) in [("0", 0), ("4", 4), ("001", 1)] {
            assert_eq!(
                json!(parse_oem_value(&kind, &domain, raw).unwrap()),
                json!({"type":"level","value":expected})
            );
        }
        for raw in [
            "5",
            "100",
            "-1",
            "+1",
            "1.0",
            "nan",
            " 1",
            "1 ",
            "１",
            "",
            "4294967296",
        ] {
            assert!(
                parse_oem_value(&kind, &domain, raw).is_err(),
                "Accepted {raw:?}"
            );
        }
        assert_eq!(
            json!(
                parse_oem_value(&kind, &OemDomain::Level { max: u32::MAX }, "4294967295").unwrap()
            ),
            json!({"type":"level","value":u32::MAX})
        );
        assert!(parse_oem_value(&kind, &OemDomain::Boolean, "on").is_err());
    }
    #[test]
    fn oem_colors_require_exact_rgb_hex_and_preserve_channel_order() {
        for (raw, expected) in [
            ("#000000", [0, 0, 0]),
            ("#FFFFFF", [255, 255, 255]),
            ("#ab12CD", [171, 18, 205]),
        ] {
            assert_eq!(
                json!(
                    parse_oem_value(&OemControlKind::KeyboardColor, &OemDomain::Rgb, raw).unwrap()
                ),
                json!({"type":"rgb","value":expected})
            );
        }
        for raw in [
            "000000",
            "#fff",
            "#ffffff00",
            "#gg0000",
            "#12 456",
            "#12é45",
            "#12345\n",
            "#123456;exit",
            "#12345",
            "#123456 ",
        ] {
            assert!(
                parse_oem_value(&OemControlKind::KeyboardColor, &OemDomain::Rgb, raw).is_err(),
                "Accepted {raw:?}"
            );
        }
        assert!(parse_oem_value(
            &OemControlKind::KeyboardColor,
            &OemDomain::Level { max: 255 },
            "#123456"
        )
        .is_err());
    }
    #[test]
    fn oem_dry_run_returns_plan_without_invoking_write_or_privilege_backend() {
        let plan = json!({"control_id":"fn_lock","target":{"type":"boolean","value":true},"requires_privilege":true});
        let value = oem_set_output(true, plan.clone(), || {
            panic!("Dry-run invoked the write/privilege backend")
        })
        .unwrap();
        assert_eq!(value, json!({"dry_run":true,"plan":plan}));
        let writes = RefCell::new(0);
        let applied = json!({"control_id":"fn_lock","confirmed":{"type":"boolean","value":true}});
        let value = oem_set_output(false, plan.clone(), || {
            *writes.borrow_mut() += 1;
            Ok(applied.clone())
        })
        .unwrap();
        assert_eq!(*writes.borrow(), 1);
        assert_eq!(value, applied);
        let error = oem_set_output(false, plan, || {
            Err(ControlError::new("fixture_write_failed", "fixture failure"))
        })
        .unwrap_err();
        assert_eq!(error.code, "fixture_write_failed");
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn qualified_fake_oem_control_dry_run_status_export_and_selection() {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        for native in [false, true] {
            let base = std::env::var_os("MECHREVO_TEST_TMPDIR")
                .map(PathBuf::from)
                .unwrap_or_else(std::env::temp_dir);
            let root = base.join(format!(
                "mechrevo-cli-oem-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            std::fs::create_dir(&root).unwrap();
            let module = root.join(if native {
                "module/uniwill_laptop"
            } else {
                "module/tuxedo_keyboard"
            });
            let platform = root.join(if native {
                "devices/platform/INOU0000:00"
            } else {
                "devices/platform/tuxedo_keyboard"
            });
            std::fs::create_dir_all(&module).unwrap();
            std::fs::create_dir_all(&platform).unwrap();
            std::fs::write(module.join("srcversion"), "A1B2C3D4E5F6\n").unwrap();
            if native {
                let driver = root.join("bus/platform/drivers/uniwill-laptop");
                std::fs::create_dir_all(&driver).unwrap();
                std::os::unix::fs::symlink(&module, driver.join("module")).unwrap();
                std::os::unix::fs::symlink(&driver, platform.join("driver")).unwrap();
                std::os::unix::fs::symlink(&platform, driver.join("INOU0000:00")).unwrap();
            }
            let id = if native {
                "fn-lock:uniwill_laptop:INOU0000:00"
            } else {
                "fn-lock"
            };
            let node = platform.join("fn_lock");
            std::fs::write(&node, "0\n").unwrap();
            let service = Service::with_linux_sysfs(&root);
            let controls = service.oem_controls();
            let selected = select_oem_control(&controls, id).unwrap();
            assert_eq!(
                selected.source.backend,
                if native {
                    "linux_uniwill_sysfs"
                } else {
                    "linux_tuxedo_sysfs"
                }
            );
            assert_eq!(selected.current, Some(OemValue::Boolean(false)));
            assert_eq!(selected.kind, OemControlKind::FnLock);
            assert!(!selected.binding.is_empty());
            for id in ["fn", "FN-LOCK", "../fn_lock", "$(touch /tmp/invalid)"] {
                assert_eq!(
                    select_oem_control(&controls, id).unwrap_err().code,
                    "oem_control_unavailable"
                );
            }
            let duplicate = vec![selected.clone(), selected.clone()];
            assert_eq!(
                select_oem_control(&duplicate, id).unwrap_err().code,
                "oem_control_ambiguous"
            );
            let before = std::fs::read(&node).unwrap();
            let before_modified = std::fs::metadata(&node).unwrap().modified().unwrap();
            let dry = set_oem(&service, id, "on", true).unwrap();
            assert_eq!(dry["dry_run"], true);
            assert_eq!(dry["plan"]["control_id"], id);
            assert_eq!(
                dry["plan"]["previous"],
                json!({"type":"boolean","value":false})
            );
            assert_eq!(
                dry["plan"]["target"],
                json!({"type":"boolean","value":true})
            );
            assert!(dry["plan"]["requires_privilege"].is_boolean());
            assert_eq!(before, std::fs::read(&node).unwrap());
            assert_eq!(
                before_modified,
                std::fs::metadata(&node).unwrap().modified().unwrap()
            );
            assert!(set_oem(&service, id, "true", true).is_err());
            assert_eq!(before, std::fs::read(&node).unwrap());
            let instant = Instant::now();
            let document = collect_status_json(
                || {
                    let mut snapshot = fixture_snapshot();
                    snapshot.oem_controls = controls.clone();
                    snapshot
                },
                || UNIX_EPOCH + Duration::from_secs(1_800_000_000),
                || instant,
                json!({}),
            )
            .unwrap();
            assert_eq!(document["oem_controls"], json!(controls));
            let exported_control = document["oem_controls"]
                .as_array()
                .unwrap()
                .iter()
                .find(|control| control["id"] == id)
                .unwrap();
            assert_eq!(
                exported_control["current"],
                json!({"type":"boolean","value":false})
            );
            assert!(exported_control["source"]["path"].is_string());
            assert!(exported_control["readback_scope"].is_string());
            let export_path = root.join("oem-status.json");
            export(&export_path, &document).unwrap();
            assert_eq!(
                serde_json::from_slice::<Value>(&std::fs::read(&export_path).unwrap()).unwrap(),
                document
            );
            assert_eq!(before, std::fs::read(&node).unwrap());
            std::fs::remove_dir_all(root).unwrap();
        }
    }
    fn fixture_snapshot() -> Snapshot {
        Snapshot {
            platform: "fixture".into(),
            identity: Identity::default(),
            telemetry: Vec::new(),
            capabilities: Vec::new(),
            power_policy: Default::default(),
            diagnostics: Vec::new(),
            oem_controls: Vec::new(),
            brightness: vec![BrightnessDevice {
                id: "fixture-screen".into(),
                label: "屏幕".into(),
                current_percent: Some(42.),
                control_value: Some(42),
                actual_value: None,
                maximum: Some(100),
                source: EvidenceSource {
                    backend: "fixture".into(),
                    path: "/fixture/brightness".into(),
                    device_id: Some("fixture-screen".into()),
                },
                status: CapabilityStatus::Available,
                readable: true,
                writable: false,
                supported_percentages: Vec::new(),
                reason: None,
            }],
        }
    }
    fn fixture_document() -> Value {
        let instant = Instant::now();
        collect_status_json(
            fixture_snapshot,
            || UNIX_EPOCH + Duration::new(1_800_000_000, 123_456_789),
            || instant,
            json!({"kernel_release":{"value":null,"status":"fixture"}}),
        )
        .unwrap()
    }
    #[test]
    fn collection_brackets_one_complete_snapshot_and_preserves_original_fields() {
        let events = RefCell::new(Vec::new());
        let instant = Instant::now();
        let mut ticks = [instant, instant + Duration::new(2, 345)].into_iter();
        let mut walls = [
            UNIX_EPOCH + Duration::new(1_800_000_000, 999_999_999),
            UNIX_EPOCH + Duration::new(1_800_000_003, 123),
        ]
        .into_iter();
        let value = collect_status_json(
            || {
                events.borrow_mut().push("snapshot");
                fixture_snapshot()
            },
            || {
                events.borrow_mut().push("wall");
                walls.next().unwrap()
            },
            || {
                events.borrow_mut().push("monotonic");
                ticks.next().unwrap()
            },
            json!({"kernel_release":{"value":"fixture-release","status":"fixture"}}),
        )
        .unwrap();
        assert_eq!(
            *events.borrow(),
            ["monotonic", "wall", "snapshot", "wall", "monotonic"]
        );
        let original = serde_json::to_value(fixture_snapshot()).unwrap();
        for (key, expected) in original.as_object().unwrap() {
            assert_eq!(&value[key], expected, "Snapshot field changed: {key}");
        }
        assert_eq!(value["schema_version"], 1);
        assert!(value["identity_evidence"].is_object());
        let metadata = &value["collection"];
        assert_eq!(metadata["started_at"]["unix_seconds"], 1_800_000_000);
        assert_eq!(metadata["started_at"]["nanoseconds"], 999_999_999);
        assert_eq!(metadata["finished_at"]["unix_seconds"], 1_800_000_003);
        assert_eq!(metadata["finished_at"]["nanoseconds"], 123);
        assert_eq!(
            metadata["monotonic_elapsed"],
            duration_json(Duration::new(2, 345))
        );
        assert_eq!(metadata["wall_clock_status"], "ordered");
        assert_eq!(metadata["monotonic_clock_status"], "ordered");
        assert_eq!(metadata["consistency"], "non_atomic_sequential_reads");
        assert_eq!(metadata["tool"]["version"], env!("CARGO_PKG_VERSION"));
        assert_eq!(metadata["tool"]["package"], env!("CARGO_PKG_NAME"));
        assert_eq!(metadata["build_target"]["os"], std::env::consts::OS);
        assert_eq!(metadata["build_target"]["arch"], std::env::consts::ARCH);
        assert_eq!(
            metadata["runtime"]["kernel_release"]["value"],
            "fixture-release"
        );
    }
    #[test]
    fn backward_wall_clock_keeps_observed_times_and_monotonic_duration() {
        let instant = Instant::now();
        let mut ticks = [instant, instant + Duration::from_millis(8)].into_iter();
        let mut walls = [
            UNIX_EPOCH + Duration::from_secs(20),
            UNIX_EPOCH + Duration::from_secs(10),
        ]
        .into_iter();
        let value = collect_status_json(
            fixture_snapshot,
            || walls.next().unwrap(),
            || ticks.next().unwrap(),
            json!({}),
        )
        .unwrap();
        assert_eq!(value["collection"]["wall_clock_status"], "moved_backwards");
        assert_eq!(value["collection"]["started_at"]["unix_seconds"], 20);
        assert_eq!(value["collection"]["finished_at"]["unix_seconds"], 10);
        assert_eq!(
            value["collection"]["monotonic_elapsed"],
            duration_json(Duration::from_millis(8))
        );
    }
    #[test]
    fn pre_epoch_and_backward_monotonic_time_are_explicitly_unknown() {
        let instant = Instant::now();
        let mut ticks = [instant + Duration::from_secs(1), instant].into_iter();
        let before_epoch = UNIX_EPOCH.checked_sub(Duration::from_nanos(1)).unwrap();
        let mut walls = [before_epoch, UNIX_EPOCH].into_iter();
        let value = collect_status_json(
            fixture_snapshot,
            || walls.next().unwrap(),
            || ticks.next().unwrap(),
            json!({}),
        )
        .unwrap();
        assert_eq!(
            value["collection"]["wall_clock_status"],
            "before_unix_epoch"
        );
        assert!(value["collection"]["started_at"].is_null());
        assert_eq!(
            value["collection"]["finished_at"],
            json!({"unix_seconds":0,"nanoseconds":0})
        );
        assert_eq!(
            value["collection"]["monotonic_clock_status"],
            "moved_backwards"
        );
        assert!(value["collection"]["monotonic_elapsed"].is_null());
        assert_eq!(
            duration_json(Duration::MAX),
            json!({"seconds":u64::MAX,"nanoseconds":999_999_999})
        );
    }
    #[test]
    fn kernel_release_is_bounded_and_rejects_unavailable_or_invalid_data() {
        let value = read_kernel_release(&b"6.17.1-fixture\n"[..]);
        assert_eq!(value["value"], "6.17.1-fixture");
        assert_eq!(value["source"], "/proc/sys/kernel/osrelease");
        assert_eq!(value["status"], "available");
        for bytes in [b"".as_slice(), b"\n", b"6.17\x00", b"6\n17", b"\xff"] {
            let value = read_kernel_release(bytes);
            assert!(value["value"].is_null());
            assert_eq!(value["status"], "invalid_data");
        }
        let bytes_read = std::rc::Rc::new(std::cell::Cell::new(0));
        struct EndlessReader(std::rc::Rc<std::cell::Cell<usize>>);
        impl Read for EndlessReader {
            fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
                buffer.fill(b'x');
                self.0.set(self.0.get() + buffer.len());
                Ok(buffer.len())
            }
        }
        let value = read_kernel_release(EndlessReader(bytes_read.clone()));
        assert!(value["value"].is_null());
        assert_eq!(value["status"], "invalid_data");
        assert_eq!(bytes_read.get(), 257);
        struct FailedReader;
        impl Read for FailedReader {
            fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
                Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "fixture failure",
                ))
            }
        }
        let value = read_kernel_release(FailedReader);
        assert!(value["value"].is_null());
        assert_eq!(value["status"], "read_failed");
    }
    #[test]
    fn explicit_profile_and_dry_run() {
        assert_eq!(
            parse(args(&["profile", "performance", "--dry-run"])).unwrap(),
            Action::Profile(PowerProfile::Performance, true)
        );
        assert!(parse(args(&["profile", "turbo"])).is_err());
        assert!(parse(args(&["profile", "balanced", "--force"])).is_err());
    }
    #[test]
    fn brightness_bounds_devices_and_unknown_flags() {
        for value in ["-1", "101", "256", "1.5", "nan", "99999999999999999"] {
            assert!(parse(args(&["brightness", value])).is_err());
        }
        for value in ["0", "100"] {
            assert!(parse(args(&["brightness", value, "--device", "screen"])).is_ok());
        }
        assert!(parse(args(&["brightness", "--dry-run"])).is_err());
        assert!(parse(args(&["brightness", "10", "--device"])).is_err());
        assert!(parse(args(&["brightness", "10", "--dry-run", "--dry-run"])).is_err());
    }
    #[test]
    fn export_requires_explicit_destination() {
        assert!(parse(args(&["export"])).is_err());
        assert!(parse(args(&["export", "file.json"])).is_err());
        assert_eq!(
            parse(args(&["export", "--output", "中文 空格.json"])).unwrap(),
            Action::Export("中文 空格.json".into())
        );
    }
    #[test]
    fn export_utf8_refuses_overwrite_and_reports_missing_parent() {
        let dir = std::env::temp_dir().join(format!(
            "mechrevo-export-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("中文 空格.json");
        let document = fixture_document();
        export(&path, &document).unwrap();
        assert!(std::fs::read_to_string(&path).unwrap().contains("屏幕"));
        assert_eq!(
            serde_json::from_slice::<Value>(&std::fs::read(&path).unwrap()).unwrap(),
            document
        );
        let original = std::fs::read(&path).unwrap();
        assert!(export(&path, &json!({"overwrite":true})).is_err());
        assert_eq!(original, std::fs::read(&path).unwrap());
        assert!(export(&dir.join("missing/export.json"), &json!({})).is_err());
        #[cfg(unix)]
        {
            let link = dir.join("existing-link.json");
            std::os::unix::fs::symlink(&path, &link).unwrap();
            assert!(export(&link, &document).is_err());
            assert_eq!(original, std::fs::read(&path).unwrap());
            let absent = dir.join("absent.json");
            let dangling = dir.join("dangling-link.json");
            std::os::unix::fs::symlink(&absent, &dangling).unwrap();
            assert!(export(&dangling, &document).is_err());
            assert!(!absent.exists());
            assert!(std::fs::symlink_metadata(&dangling)
                .unwrap()
                .file_type()
                .is_symlink());
        }
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn status_rejects_silent_ignored_options() {
        assert!(parse(args(&["status", "--force"])).is_err());
        assert!(parse(args(&["models", "a", "b"])).is_err());
    }
}
