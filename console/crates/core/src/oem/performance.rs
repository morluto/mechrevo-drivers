//! Bridge to the already installed, locally verified GM6PX0X profile controller.
//! No new EC protocol or tuning defaults live here. Discovery only reads tccd;
//! application uses a fixed root-owned executable through the existing helper.
use super::*;
use crate::command::{run_command, run_control_helper};
use serde_json::Value;
use std::{fs, os::unix::fs::MetadataExt, time::Duration};

pub(super) const ID: &str = "mechrevo-performance-profile";
const PROGRAM: &str = "/usr/bin/mechrevo-control";
const PROFILES: &[(&str, &str)] = &[
    ("mechrevo_office", "office"),
    ("mechrevo_gaming_quiet", "gaming-quiet"),
    ("mechrevo_gaming", "gaming"),
    ("mechrevo_turbo", "turbo"),
    ("mechrevo_fan_boost", "boost"),
];
const SCOPE: &str = "已保存的 tccd 性能档位；应用由 mechrevo-control 完成并核对 EC 模式字节，再回读活动配置。不是固定功耗、持续频率、实际灯光或风扇转速保证。";

fn invalid(message: impl Into<String>) -> ControlError {
    ControlError::new("performance_profiles_unavailable", message)
}
fn source() -> EvidenceSource {
    EvidenceSource {
        backend: "linux_mechrevo_profiles".into(),
        path: "/etc/tcc/profiles".into(),
        device_id: Some("MECHREVO/GM6PX0X".into()),
    }
}
fn supported_machine(root: &Path) -> bool {
    let read = |name| fs::read_to_string(root.join("class/dmi/id").join(name)).ok();
    read("sys_vendor").is_some_and(|v| v.trim() == "MECHREVO")
        && read("board_name").is_some_and(|v| v.trim() == "GM6PX0X")
}
fn string_reply(output: &str) -> Result<String, ControlError> {
    let envelope: Value = serde_json::from_str(output).map_err(|e| invalid(e.to_string()))?;
    if envelope["type"] != "s" || envelope["data"].as_array().is_none_or(|a| a.len() != 1) {
        return Err(invalid("Unexpected tccd string reply"));
    }
    envelope["data"][0]
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| invalid("Missing tccd string payload"))
}
fn bus_string(
    destination: &str,
    path: &str,
    interface: &str,
    args: &[&str],
) -> Result<String, ControlError> {
    let mut command = vec![
        "--system",
        "--timeout=3s",
        "--json=short",
        "call",
        destination,
        path,
        interface,
    ];
    command.extend_from_slice(args);
    let output = run_command(
        "/usr/bin/busctl",
        &command,
        Duration::from_secs(4),
        128 * 1024,
    )?;
    string_reply(&output.stdout)
}
fn daemon_owner() -> Result<String, ControlError> {
    bus_string(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        &["GetNameOwner", "s", "com.tuxedocomputers.tccd"],
    )
}
fn daemon_json(owner: &str, method: &str) -> Result<Value, ControlError> {
    let payload = bus_string(
        owner,
        "/com/tuxedocomputers/tccd",
        "com.tuxedocomputers.tccd",
        &[method],
    )?;
    serde_json::from_str(&payload).map_err(|e| invalid(e.to_string()))
}
#[derive(Clone)]
struct State {
    profiles: Vec<Value>,
    active: Value,
    identity: String,
}
impl State {
    fn control(&self) -> Result<OemControl, ControlError> {
        let active = self.active["id"]
            .as_str()
            .ok_or_else(|| invalid("Active profile has no ID"))?;
        let choices: Vec<String> = PROFILES
            .iter()
            .filter(|(id, _)| self.profiles.iter().any(|p| p["id"] == *id))
            .map(|(id, _)| (*id).into())
            .collect();
        for choice in &choices {
            if self.profiles.iter().filter(|p| p["id"] == *choice).count() != 1 {
                return Err(invalid("Duplicate configured performance profile ID"));
            }
        }
        if !choices.iter().any(|id| id == active) {
            return Err(invalid(
                "当前为自定义或未识别档位；请先用 mechrevo-control 选择已验证的五档之一，再刷新。",
            ));
        }
        // Exact configuration, not a lossy hash: stale previews detect edits,
        // active temporary profiles, daemon restarts and controller replacement.
        let configured: Vec<_> = self
            .profiles
            .iter()
            .filter(|p| choices.iter().any(|id| p["id"] == *id))
            .collect();
        let binding = serde_json::json!({"identity":self.identity, "profiles":configured, "active":self.active}).to_string();
        if binding.len() > 20 * 1024 {
            return Err(invalid(
                "Saved profile configuration exceeds the preview size limit",
            ));
        }
        Ok(OemControl {
            id: ID.into(),
            kind: OemControlKind::PerformanceProfile,
            label: "性能与散热档位".into(),
            current: Some(OemValue::Choice(active.into())),
            domain: OemDomain::Choices(choices),
            status: CapabilityStatus::Available,
            writable: false,
            source: source(),
            binding,
            readback_scope: SCOPE.into(),
            reason: Some("使用本机已保存的参数；选择不会写入，预览后应用需要管理员授权。".into()),
        })
    }
    fn plan(&self, target: OemValue) -> Result<OemPlan, ControlError> {
        let control = self.control()?;
        validate_target(&control.domain, &target)?;
        Ok(OemPlan {
            control_id: control.id,
            kind: control.kind,
            label: control.label,
            previous: control.current.ok_or_else(unavailable)?,
            target,
            domain: control.domain,
            source: control.source,
            binding: control.binding,
            readback_scope: control.readback_scope,
            requires_privilege: true,
            companion_brightness: None,
        })
    }
}
trait ProfileIo {
    fn read(&mut self) -> Result<State, ControlError>;
    fn select(&mut self, key: &str) -> Result<(), ControlError>;
}
struct Installed;
impl ProfileIo for Installed {
    fn read(&mut self) -> Result<State, ControlError> {
        if !supported_machine(Path::new("/sys")) {
            return Err(invalid(
                "Performance presets are verified only on MECHREVO GM6PX0X",
            ));
        }
        crate::privilege::validate_program(Path::new(PROGRAM))?;
        let metadata = fs::metadata(PROGRAM).map_err(|e| invalid(e.to_string()))?;
        let owner = daemon_owner()?;
        let profiles = daemon_json(&owner, "GetProfilesJSON")?
            .as_array()
            .cloned()
            .ok_or_else(|| invalid("tccd profiles are not an array"))?;
        let active = daemon_json(&owner, "GetActiveProfileJSON")?;
        if daemon_owner()? != owner {
            return Err(invalid("tccd restarted during discovery"));
        }
        Ok(State {
            profiles,
            active,
            identity: format!(
                "{owner}|{}:{}:{}:{}:{}",
                metadata.dev(),
                metadata.ino(),
                metadata.len(),
                metadata.mtime(),
                metadata.mtime_nsec()
            ),
        })
    }
    fn select(&mut self, key: &str) -> Result<(), ControlError> {
        if !PROFILES.iter().any(|(_, candidate)| *candidate == key) {
            return Err(invalid("Profile is outside the fixed command whitelist"));
        }
        crate::privilege::validate_program(Path::new(PROGRAM))?;
        // Isolated Python ignores user import paths. Never invoke the user's
        // /usr/local/bin wrapper or let a GUI plan choose a program or path.
        let python = fs::canonicalize("/usr/bin/python3").map_err(|e| invalid(e.to_string()))?;
        crate::privilege::validate_program(&python)?;
        let output = run_control_helper(
            python.to_str().ok_or_else(unavailable)?,
            &["-I", PROGRAM, "mode", key],
            64 * 1024,
        )?;
        if output.status != 0 {
            let mut error = ControlError::new(
                "performance_apply_failed",
                "The installed profile controller failed; inspect refreshed state before retrying",
            );
            error.details.extend([output.stdout, output.stderr]);
            return Err(error);
        }
        Ok(())
    }
}
pub(super) fn control(root: &Path) -> Option<OemControl> {
    if root != Path::new("/sys") || !supported_machine(root) || !Path::new(PROGRAM).exists() {
        return None;
    }
    Some(
        Installed
            .read()
            .and_then(|state| state.control())
            .unwrap_or_else(|error| OemControl {
                id: ID.into(),
                kind: OemControlKind::PerformanceProfile,
                label: "性能与散热档位".into(),
                current: None,
                domain: OemDomain::Choices(vec![]),
                status: CapabilityStatus::Unavailable,
                writable: false,
                source: source(),
                binding: String::new(),
                readback_scope: SCOPE.into(),
                reason: Some(error.to_string()),
            }),
    )
}
pub(super) fn plan(root: &Path, target: OemValue) -> Result<OemPlan, ControlError> {
    if root != Path::new("/sys") {
        return Err(unavailable());
    }
    Installed.read()?.plan(target)
}
fn apply_with(io: &mut impl ProfileIo, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
    let before = io.read().map_err(rejected)?;
    let fresh = before.plan(plan.target.clone()).map_err(rejected)?;
    if &fresh != plan {
        return Err(rejected(ControlError::new(
            "oem_plan_stale",
            "性能配置、控制程序或活动档位已变化，请重新预览。",
        )));
    }
    let OemValue::Choice(target) = &plan.target else {
        return Err(rejected(unavailable()));
    };
    let key = PROFILES
        .iter()
        .find(|(id, _)| *id == target)
        .map(|(_, key)| *key)
        .ok_or_else(|| rejected(unavailable()))?;
    let attempt = io.select(key).and_then(|()| {
        let after = io.read()?;
        let expected = before
            .profiles
            .iter()
            .find(|p| p["id"] == *target)
            .ok_or_else(unavailable)?;
        if after.identity != before.identity
            || after.profiles != before.profiles
            || after.active != *expected
        {
            return Err(ControlError::new(
                "performance_readback_mismatch",
                "应用后活动配置或后台身份发生变化；请刷新核对，不要重放旧请求。",
            ));
        }
        Ok(())
    });
    if let Err(mut error) = attempt {
        // A profile spans CPU, fans and EC state. Never claim an ID-only rollback
        // restored all of them or overwrite a concurrent chassis-button choice.
        error.details.push("oem_state_unknown".into());
        error
            .details
            .push("No automatic profile rollback; refresh before making a new request".into());
        return Err(error);
    }
    Ok(OemApplyResult {
        control_id: plan.control_id.clone(),
        kind: plan.kind,
        previous: plan.previous.clone(),
        confirmed: plan.target.clone(),
        source: plan.source.clone(),
        readback_scope: plan.readback_scope.clone(),
    })
}
pub(super) fn apply(root: &Path, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
    // SAFETY: geteuid has no arguments or side effects.
    if root != Path::new("/sys") || unsafe { libc::geteuid() } != 0 {
        return Err(rejected(ControlError::new(
            "administrator_required",
            "性能档位写入需要授权辅助程序。",
        )));
    }
    apply_with(&mut Installed, plan)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[derive(Clone, Copy)]
    enum Outcome {
        Applied,
        WriteFailed,
        WrongReadback,
        ReadFailed,
        DaemonRestarted,
        ConfigurationChanged,
    }
    struct Fake {
        state: State,
        writes: Vec<String>,
        outcome: Outcome,
    }
    fn fake() -> Fake {
        let profiles: Vec<_> = PROFILES
            .iter()
            .map(|(id, _)| serde_json::json!({"id":id,"cpu":{"maximum":42}}))
            .collect();
        Fake {
            state: State {
                active: profiles[0].clone(),
                profiles,
                identity: "fixture-daemon-and-program".into(),
            },
            writes: vec![],
            outcome: Outcome::Applied,
        }
    }
    impl ProfileIo for Fake {
        fn read(&mut self) -> Result<State, ControlError> {
            if !self.writes.is_empty() && matches!(self.outcome, Outcome::ReadFailed) {
                return Err(invalid("fixture readback unavailable"));
            }
            Ok(self.state.clone())
        }
        fn select(&mut self, key: &str) -> Result<(), ControlError> {
            self.writes.push(key.into());
            if matches!(self.outcome, Outcome::WriteFailed) {
                return Err(invalid("fixture partial failure"));
            }
            if !matches!(self.outcome, Outcome::WrongReadback) {
                let id = PROFILES.iter().find(|(_, k)| *k == key).unwrap().0;
                self.state.active = self
                    .state
                    .profiles
                    .iter()
                    .find(|p| p["id"] == id)
                    .unwrap()
                    .clone();
            }
            match self.outcome {
                Outcome::DaemonRestarted => self.state.identity.push_str("-restarted"),
                Outcome::ConfigurationChanged => {
                    self.state.profiles[0]["cpu"]["maximum"] = 99.into();
                }
                _ => {}
            }
            Ok(())
        }
    }
    #[test]
    fn all_five_profiles_preview_without_writes_then_apply_and_read_back() {
        for (id, key) in PROFILES {
            let mut io = fake();
            let plan = io.state.plan(OemValue::Choice((*id).into())).unwrap();
            assert!(io.writes.is_empty());
            assert_eq!(apply_with(&mut io, &plan).unwrap().confirmed, plan.target);
            assert_eq!(io.writes, [*key]);
        }
    }
    #[test]
    fn unavailable_duplicate_and_unknown_profiles_are_rejected() {
        let mut io = fake();
        io.state.profiles.retain(|p| p["id"] != "mechrevo_turbo");
        assert!(io
            .state
            .plan(OemValue::Choice("mechrevo_turbo".into()))
            .is_err());
        assert!(io
            .state
            .plan(OemValue::Choice("../../arbitrary".into()))
            .is_err());
        assert!(io.state.plan(OemValue::Boolean(true)).is_err());
        io.state.profiles.push(io.state.profiles[0].clone());
        assert!(io.state.control().is_err());
        io.state.active["id"] = "unknown".into();
        assert!(io.state.control().is_err());
        assert!(io.writes.is_empty());
    }
    #[test]
    fn changed_config_identity_or_previous_state_rejects_before_write() {
        for change in 0..4 {
            let mut io = fake();
            let plan = io
                .state
                .plan(OemValue::Choice("mechrevo_turbo".into()))
                .unwrap();
            match change {
                0 => io.state.identity.push_str("-restarted"),
                1 => io.state.active = io.state.profiles[1].clone(),
                2 => io.state.profiles[3]["cpu"]["maximum"] = 99.into(),
                _ => io.state.active["cpu"]["maximum"] = 99.into(),
            }
            let error = apply_with(&mut io, &plan).unwrap_err();
            assert!(error
                .details
                .iter()
                .any(|d| d == "oem_rejected_before_write"));
            assert!(io.writes.is_empty());
        }
    }
    #[test]
    fn altered_plan_fields_reject_before_write() {
        for change in 0..5 {
            let mut io = fake();
            let mut plan = io
                .state
                .plan(OemValue::Choice("mechrevo_turbo".into()))
                .unwrap();
            match change {
                0 => plan.control_id = "fn-lock".into(),
                1 => plan.kind = OemControlKind::FnLock,
                2 => plan.source.path = "/tmp/user-command".into(),
                3 => plan.requires_privilege = false,
                _ => plan.companion_brightness = Some(3),
            }
            assert!(apply_with(&mut io, &plan).is_err());
            assert!(io.writes.is_empty());
        }
    }
    #[test]
    fn failure_or_wrong_readback_is_unknown_and_never_replayed() {
        for outcome in [
            Outcome::WriteFailed,
            Outcome::WrongReadback,
            Outcome::ReadFailed,
            Outcome::DaemonRestarted,
            Outcome::ConfigurationChanged,
        ] {
            let mut io = fake();
            io.outcome = outcome;
            let plan = io
                .state
                .plan(OemValue::Choice("mechrevo_turbo".into()))
                .unwrap();
            let error = apply_with(&mut io, &plan).unwrap_err();
            assert!(error.details.iter().any(|d| d == "oem_state_unknown"));
            assert!(!error.details.iter().any(|d| d == "oem_restore_confirmed"));
            assert_eq!(io.writes, ["turbo"]);
        }
    }
    #[test]
    fn oversized_configuration_never_creates_a_write_plan() {
        let mut io = fake();
        io.state.profiles[0]["description"] = "x".repeat(20 * 1024).into();
        assert!(io
            .state
            .plan(OemValue::Choice("mechrevo_turbo".into()))
            .is_err());
        assert!(io.writes.is_empty());
    }
    #[test]
    fn malformed_bus_replies_and_fixture_roots_never_activate_real_backend() {
        for reply in [
            "{}",
            "{\"type\":\"s\",\"data\":[]}",
            "{\"type\":\"b\",\"data\":[true]}",
            "{\"type\":\"s\",\"data\":[\"a\",\"b\"]}",
        ] {
            assert!(string_reply(reply).is_err());
        }
        assert_eq!(
            string_reply("{\"type\":\"s\",\"data\":[\"ok\"]}").unwrap(),
            "ok"
        );
        assert!(control(Path::new("/tmp/fixture")).is_none());
        assert!(plan(
            Path::new("/tmp/fixture"),
            OemValue::Choice("mechrevo_turbo".into())
        )
        .is_err());
    }
}
