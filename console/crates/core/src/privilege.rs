//! Narrow, synchronous authorization for OEM settings. No shell or daemon.
//!
//! A root helper cannot reliably be killed by its unprivileged caller. We wait
//! for its actual exit, including after output errors, and never claim timeout
//! cancellation. Hardware completion is limited to the driver's readback.
use crate::{ControlError, OemApplyResult, OemPlan, Service};
use serde::{Deserialize, Serialize};

pub const HELPER_PATH: &str = "/usr/lib/mechrevo-console/oem-helper";
pub const MAX_REQUEST_BYTES: usize = 32 * 1024;
#[cfg(target_os = "linux")]
const OUTPUT_LIMIT: usize = 64 * 1024;

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HelperRequest {
    pub schema_version: u32,
    pub request_id: String,
    pub plan: OemPlan,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HelperOutcome {
    RejectedBeforeWrite,
    AppliedVerified,
    FailedRestoredVerified,
    FailedStateUnknown,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HelperReply {
    pub schema_version: u32,
    pub request_id: String,
    pub outcome: HelperOutcome,
    pub result: Option<OemApplyResult>,
    pub error: Option<ControlError>,
}

#[cfg(any(target_os = "linux", test))]
fn unknown(message: impl Into<String>) -> ControlError {
    let mut error = ControlError::new("oem_outcome_unknown", message);
    error.details.push("helper_exited: true; do not replay the old plan; read current state and create a new preview".into());
    error
}

pub fn parse_request(input: &str) -> Result<HelperRequest, ControlError> {
    if input.len() > MAX_REQUEST_BYTES {
        return Err(ControlError::new(
            "invalid_oem_request",
            "OEM request exceeds the size limit",
        ));
    }
    let request: HelperRequest = serde_json::from_str(input)
        .map_err(|e| ControlError::new("invalid_oem_request", e.to_string()))?;
    if request.schema_version != 1
        || request.request_id.is_empty()
        || request.request_id.len() > 128
        || !request
            .request_id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-')
    {
        return Err(ControlError::new(
            "invalid_oem_request",
            "Invalid OEM request version or identity",
        ));
    }
    Ok(request)
}

fn error_outcome(error: &ControlError) -> HelperOutcome {
    if error.details.iter().any(|v| v == "oem_state_unknown") {
        HelperOutcome::FailedStateUnknown
    } else if error.details.iter().any(|v| v == "oem_restore_confirmed") {
        HelperOutcome::FailedRestoredVerified
    } else if error
        .details
        .iter()
        .any(|v| v == "oem_rejected_before_write")
    {
        HelperOutcome::RejectedBeforeWrite
    } else {
        HelperOutcome::FailedStateUnknown
    }
}

fn terminal(request_id: String, result: Result<OemApplyResult, ControlError>) -> HelperReply {
    match result {
        Ok(result) => HelperReply {
            schema_version: 1,
            request_id,
            outcome: HelperOutcome::AppliedVerified,
            result: Some(result),
            error: None,
        },
        Err(error) => {
            let outcome = error_outcome(&error);
            HelperReply {
                schema_version: 1,
                request_id,
                outcome,
                result: None,
                error: Some(error),
            }
        }
    }
}

/// Fixed helper entry: no supplied sysfs root, environment override or executable.
pub fn execute_request(request: HelperRequest) -> HelperReply {
    let result = apply_root(&Service::new(), &request.plan);
    terminal(request.request_id, result)
}

#[cfg(any(target_os = "linux", test))]
fn decode_reply(
    request: &HelperRequest,
    output: crate::command::CommandOutput,
) -> Result<OemApplyResult, ControlError> {
    if output.status == 126 && output.stdout.trim().is_empty() {
        return Err(ControlError::new(
            "authorization_cancelled",
            "Administrator authorization was cancelled before the helper ran",
        ));
    }
    if output.status == 127 && output.stdout.trim().is_empty() {
        let mut error = ControlError::new(
            "authorization_unavailable",
            "The administrator authorization agent or policy is unavailable",
        );
        if !output.stderr.is_empty() {
            error.details.push(output.stderr);
        }
        return Err(error);
    }
    let reply: HelperReply = serde_json::from_str(&output.stdout).map_err(|e| {
        unknown(format!(
            "The helper exited without a valid terminal result: {e}"
        ))
    })?;
    if reply.schema_version != 1 || reply.request_id != request.request_id {
        return Err(unknown(
            "The helper terminal result does not match this request",
        ));
    }
    match (reply.outcome, reply.result, reply.error, output.status) {
        (HelperOutcome::AppliedVerified, Some(result), None, 0)
            if result.control_id == request.plan.control_id
                && result.kind == request.plan.kind
                && result.previous == request.plan.previous
                && result.confirmed == request.plan.target
                && result.source == request.plan.source
                && result.readback_scope == request.plan.readback_scope =>
        {
            Ok(result)
        }
        (outcome, None, Some(mut error), 2)
            if outcome != HelperOutcome::AppliedVerified && outcome == error_outcome(&error) =>
        {
            error.details.push(format!(
                "helper_outcome: {}",
                match outcome {
                    HelperOutcome::RejectedBeforeWrite => "rejected_before_write",
                    HelperOutcome::FailedRestoredVerified => "failed_restored_verified",
                    _ => "failed_state_unknown",
                }
            ));
            Err(error)
        }
        _ => Err(unknown(
            "Helper terminal state, payload and exit status disagree",
        )),
    }
}

/// Used only after an explicit Apply. Discovery/preview never starts pkexec.
// @mark mechrevo.oem_controls role=authorization
pub fn apply_oem(service: &Service, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
    #[cfg(target_os = "linux")]
    {
        if service.linux_root != std::path::Path::new("/sys") {
            // Explicit library fixture roots are never passed to the helper.
            return service.apply_oem(plan);
        }
        if unsafe { libc::geteuid() } == 0 {
            return apply_root(service, plan);
        }
        validate_program(std::path::Path::new(HELPER_PATH))?;
        validate_program(std::path::Path::new("/usr/bin/pkexec"))?;
        let request = HelperRequest {
            schema_version: 1,
            request_id: format!(
                "{}-{}-{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_err(|e| ControlError::new("invalid_clock", e.to_string()))?
                    .as_nanos(),
                NEXT_REQUEST.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ),
            plan: plan.clone(),
        };
        let payload = serde_json::to_string(&request)
            .map_err(|e| ControlError::new("invalid_oem_request", e.to_string()))?;
        if payload.len() > MAX_REQUEST_BYTES {
            return Err(ControlError::new(
                "invalid_oem_request",
                "OEM request exceeds the size limit",
            ));
        }
        let output = crate::command::run_control_helper(
            "/usr/bin/pkexec",
            &[
                "--disable-internal-agent",
                HELPER_PATH,
                "--apply-plan",
                &payload,
            ],
            OUTPUT_LIMIT,
        )?;
        decode_reply(&request, output)
    }
    #[cfg(not(target_os = "linux"))]
    {
        service.apply_oem(plan)
    }
}

#[cfg(target_os = "linux")]
static NEXT_REQUEST: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);

#[cfg(target_os = "linux")]
pub(crate) fn validate_program(path: &std::path::Path) -> Result<(), ControlError> {
    use std::os::unix::fs::MetadataExt;
    let mut current = std::path::PathBuf::from("/");
    for component in path.components().skip(1) {
        current.push(component);
        let metadata = std::fs::symlink_metadata(&current).map_err(|e| {
            ControlError::new(
                "oem_helper_unavailable",
                format!("Cannot inspect {}: {e}", current.display()),
            )
        })?;
        if metadata.uid() != 0
            || metadata.mode() & 0o022 != 0
            || metadata.file_type().is_symlink()
            || (current != path && !metadata.is_dir())
            || (current == path && (!metadata.is_file() || metadata.mode() & 0o111 == 0))
        {
            return Err(ControlError::new(
                "oem_helper_untrusted",
                "The helper and its directories must be root-owned and not writable by other users",
            ));
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn acquire_lock(path: &std::path::Path, owner: u32) -> Result<std::fs::File, ControlError> {
    acquire_lock_checked(path, owner, || {})
}

#[cfg(target_os = "linux")]
fn verify_lock(
    file: &std::fs::File,
    path: &std::path::Path,
    owner: u32,
) -> Result<(), ControlError> {
    use std::os::unix::fs::MetadataExt;
    let held = file
        .metadata()
        .map_err(|e| ControlError::new("oem_lock_unavailable", e.to_string()))?;
    let named = std::fs::symlink_metadata(path)
        .map_err(|e| ControlError::new("oem_lock_unavailable", e.to_string()))?;
    if !held.is_file()
        || held.uid() != owner
        || held.mode() & 0o077 != 0
        || held.nlink() != 1
        || held.dev() != named.dev()
        || held.ino() != named.ino()
        || named.file_type().is_symlink()
    {
        return Err(ControlError::new(
            "oem_lock_untrusted",
            "The OEM transaction lock is not a private owned regular file",
        ));
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn acquire_lock_checked(
    path: &std::path::Path,
    owner: u32,
    before_lock: impl FnOnce(),
) -> Result<std::fs::File, ControlError> {
    use std::os::{fd::AsRawFd, unix::fs::OpenOptionsExt};
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .map_err(|e| ControlError::new("oem_lock_unavailable", e.to_string()))?;
    verify_lock(&file, path, owner)?;
    before_lock();
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err(ControlError::new(
            "oem_busy",
            "Another OEM transaction is still running; no write was attempted",
        ));
    }
    verify_lock(&file, path, owner)?;
    Ok(file)
}

fn apply_root(service: &Service, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
    #[cfg(target_os = "linux")]
    {
        if unsafe { libc::geteuid() } != 0 {
            let mut error = ControlError::new(
                "administrator_required",
                "The fixed OEM helper must run as root through its authorization policy",
            );
            error.details.push("oem_rejected_before_write".into());
            return Err(error);
        }
        let _lock = acquire_lock(
            std::path::Path::new("/run/lock/mechrevo-console-oem.lock"),
            0,
        )
        .map_err(|mut error| {
            error.details.push("oem_rejected_before_write".into());
            error
        })?;
        service.apply_oem(plan)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (service, plan);
        let mut error = ControlError::new(
            "oem_helper_unsupported",
            "The privileged helper is implemented only for Linux",
        );
        error.details.push("oem_rejected_before_write".into());
        Err(error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{EvidenceSource, OemControlKind, OemDomain, OemValue};
    fn request() -> HelperRequest {
        HelperRequest {
            schema_version: 1,
            request_id: "request-1".into(),
            plan: OemPlan {
                control_id: "fn-lock".into(),
                kind: OemControlKind::FnLock,
                label: "Fn 锁".into(),
                previous: OemValue::Boolean(false),
                target: OemValue::Boolean(true),
                domain: OemDomain::Boolean,
                source: EvidenceSource {
                    backend: "fixture".into(),
                    path: "/fixture/fn_lock".into(),
                    device_id: None,
                },
                binding: "fixture-driver".into(),
                readback_scope: "driver state".into(),
                requires_privilege: true,
                companion_brightness: None,
            },
        }
    }
    fn output(reply: &HelperReply, status: i32) -> crate::command::CommandOutput {
        crate::command::CommandOutput {
            stdout: serde_json::to_string(reply).unwrap(),
            stderr: String::new(),
            status,
        }
    }
    fn success(request: &HelperRequest) -> HelperReply {
        terminal(
            request.request_id.clone(),
            Ok(OemApplyResult {
                control_id: request.plan.control_id.clone(),
                kind: request.plan.kind,
                previous: request.plan.previous.clone(),
                confirmed: request.plan.target.clone(),
                source: request.plan.source.clone(),
                readback_scope: request.plan.readback_scope.clone(),
            }),
        )
    }
    #[test]
    fn request_limits_and_unknown_envelope_fields_are_rejected() {
        let valid = serde_json::to_string(&request()).unwrap();
        assert!(parse_request(&valid).is_ok());
        assert!(parse_request(&" ".repeat(MAX_REQUEST_BYTES + 1)).is_err());
        for id in ["", "../../escape", "line\nbreak"] {
            let mut v = request();
            v.request_id = id.into();
            assert!(parse_request(&serde_json::to_string(&v).unwrap()).is_err());
        }
        let mut value = serde_json::to_value(request()).unwrap();
        value["command"] = "arbitrary".into();
        assert!(parse_request(&value.to_string()).is_err());
    }
    #[test]
    fn terminal_requires_matching_request_values_and_exit() {
        let request = request();
        let mut reply = success(&request);
        assert!(decode_reply(&request, output(&reply, 0)).is_ok());
        assert!(decode_reply(&request, output(&reply, 2)).is_err());
        reply.request_id = "other-request".into();
        assert_eq!(
            decode_reply(&request, output(&reply, 0)).unwrap_err().code,
            "oem_outcome_unknown"
        );
        reply = success(&request);
        reply.result.as_mut().unwrap().confirmed = OemValue::Boolean(false);
        assert!(decode_reply(&request, output(&reply, 0)).is_err());
        reply = success(&request);
        reply.error = Some(ControlError::new("bad", "contradictory"));
        assert!(decode_reply(&request, output(&reply, 0)).is_err());
    }
    #[test]
    fn error_terminal_preserves_recovery_state_and_unknown_wins() {
        for (marker, expected) in [
            (
                "oem_rejected_before_write",
                HelperOutcome::RejectedBeforeWrite,
            ),
            (
                "oem_restore_confirmed",
                HelperOutcome::FailedRestoredVerified,
            ),
            ("oem_state_unknown", HelperOutcome::FailedStateUnknown),
        ] {
            let mut error = ControlError::new("original_write_error", "keep original");
            error.details.push(marker.into());
            let reply = terminal("request-1".into(), Err(error));
            assert_eq!(reply.outcome, expected);
            let e = decode_reply(&request(), output(&reply, 2)).unwrap_err();
            assert_eq!(e.code, "original_write_error");
            assert!(e.details.iter().any(|v| v == marker));
        }
        let mut error = ControlError::new("failed", "unknown takes precedence");
        error.details = vec!["oem_restore_confirmed".into(), "oem_state_unknown".into()];
        assert_eq!(
            terminal("request-1".into(), Err(error)).outcome,
            HelperOutcome::FailedStateUnknown
        );
        let mut error =
            ControlError::new("restore_failed", "unknown must not be reported restored");
        error.details.push("oem_state_unknown".into());
        let mut contradictory = terminal("request-1".into(), Err(error));
        contradictory.outcome = HelperOutcome::FailedRestoredVerified;
        assert_eq!(
            decode_reply(&request(), output(&contradictory, 2))
                .unwrap_err()
                .code,
            "oem_outcome_unknown"
        );
    }
    #[test]
    fn truncated_protocol_is_unknown_and_auth_codes_are_separate() {
        for (stdout, status, expected) in [
            ("{", 2, "oem_outcome_unknown"),
            ("", 126, "authorization_cancelled"),
            ("", 127, "authorization_unavailable"),
            ("", 0, "oem_outcome_unknown"),
        ] {
            let e = decode_reply(
                &request(),
                crate::command::CommandOutput {
                    stdout: stdout.into(),
                    stderr: String::new(),
                    status,
                },
            )
            .unwrap_err();
            assert_eq!(e.code, expected);
        }
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn transaction_lock_excludes_second_writer_and_rejects_links() {
        use std::os::unix::fs::{symlink, PermissionsExt};
        let dir = std::env::temp_dir().join(format!(
            "mechrevo-oem-lock-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&dir).unwrap();
        let path = dir.join("transaction.lock");
        let uid = unsafe { libc::geteuid() };
        let first = acquire_lock(&path, uid).unwrap();
        assert_eq!(acquire_lock(&path, uid).unwrap_err().code, "oem_busy");
        drop(first);
        drop(acquire_lock(&path, uid).unwrap());
        let link = dir.join("linked.lock");
        symlink(&path, &link).unwrap();
        assert!(acquire_lock(&link, uid).is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666)).unwrap();
        assert_eq!(
            acquire_lock(&path, uid).unwrap_err().code,
            "oem_lock_untrusted"
        );
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let error = acquire_lock_checked(&path, uid, || {
            std::fs::rename(&path, dir.join("prior.lock")).unwrap();
            std::fs::write(&path, b"replacement").unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        })
        .unwrap_err();
        assert_eq!(error.code, "oem_lock_untrusted");
        std::fs::remove_dir_all(dir).unwrap();
    }
}
