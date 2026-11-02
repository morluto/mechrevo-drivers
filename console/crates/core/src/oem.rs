//! Model-owned controls exposed by a verified platform driver.
//!
//! Linux uses fixed sysfs attributes, not guessed EC addresses. Discovery and
//! plans never write. A plan records the observed driver/device identity and is
//! revalidated immediately before application; this is not a kernel CAS.
#![cfg_attr(not(target_os = "linux"), allow(dead_code))]
use crate::{CapabilityStatus, ControlError, EvidenceSource};
use serde::{Deserialize, Serialize};
use std::path::Path;

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
mod performance;
#[cfg(test)]
mod tests;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OemControlKind {
    PerformanceProfile,
    FnLock,
    ChargingProfile,
    KeyboardBrightness,
    KeyboardColor,
    AcAutoBoot,
    UsbPowerShare,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum OemValue {
    Boolean(bool),
    Choice(String),
    Level(u32),
    Rgb([u8; 3]),
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum OemDomain {
    Boolean,
    Choices(Vec<String>),
    Level { max: u32 },
    Rgb,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OemControl {
    pub id: String,
    pub kind: OemControlKind,
    pub label: String,
    pub current: Option<OemValue>,
    pub domain: OemDomain,
    pub status: CapabilityStatus,
    pub writable: bool,
    pub source: EvidenceSource,
    pub binding: String,
    pub readback_scope: String,
    pub reason: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OemPlan {
    pub control_id: String,
    pub kind: OemControlKind,
    pub label: String,
    pub previous: OemValue,
    pub target: OemValue,
    pub domain: OemDomain,
    pub source: EvidenceSource,
    pub binding: String,
    pub readback_scope: String,
    pub requires_privilege: bool,
    #[serde(default)]
    pub companion_brightness: Option<u32>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OemApplyResult {
    pub control_id: String,
    pub kind: OemControlKind,
    pub previous: OemValue,
    pub confirmed: OemValue,
    pub source: EvidenceSource,
    pub readback_scope: String,
}

fn unavailable() -> ControlError {
    ControlError::new(
        "oem_unavailable",
        "No verified OEM driver backend exposes the selected control on this platform",
    )
}
fn validate_target(domain: &OemDomain, value: &OemValue) -> Result<(), ControlError> {
    let valid = match (domain, value) {
        (OemDomain::Boolean, OemValue::Boolean(_)) | (OemDomain::Rgb, OemValue::Rgb(_)) => true,
        (OemDomain::Choices(choices), OemValue::Choice(value)) => choices.contains(value),
        (OemDomain::Level { max }, OemValue::Level(value)) => value <= max,
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(ControlError::new(
            "invalid_oem_value",
            "The value type or range does not match the driver's advertised control",
        ))
    }
}
pub fn controls(root: &Path) -> Vec<OemControl> {
    #[cfg(target_os = "linux")]
    {
        let mut controls = linux::controls(root);
        if let Some(profile) = performance::control(root) {
            controls.insert(0, profile);
        }
        controls
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = root;
        vec![]
    }
}
pub fn plan(root: &Path, id: &str, target: OemValue) -> Result<OemPlan, ControlError> {
    #[cfg(target_os = "linux")]
    {
        if id == performance::ID {
            performance::plan(root, target)
        } else {
            linux::plan(root, id, target)
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (root, id, target);
        Err(unavailable())
    }
}
pub fn apply(root: &Path, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
    #[cfg(target_os = "linux")]
    {
        if plan.control_id == performance::ID || plan.kind == OemControlKind::PerformanceProfile {
            performance::apply(root, plan)
        } else {
            linux::apply(root, plan)
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (root, plan);
        Err(unavailable())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Observation {
    value: OemValue,
    companion_brightness: Option<u32>,
}
trait OemIo {
    fn observe(&mut self) -> Result<Observation, ControlError>;
    fn write(&mut self, value: &OemValue) -> Result<(), ControlError>;
    fn write_companion(&mut self, value: u32) -> Result<(), ControlError>;
}
fn belongs_to_request(value: &Observation, plan: &OemPlan) -> bool {
    (value.value == plan.previous || value.value == plan.target)
        && value.companion_brightness == plan.companion_brightness
}
fn rejected(mut error: ControlError) -> ControlError {
    error.details.retain(|detail| {
        !matches!(
            detail.as_str(),
            "oem_restore_confirmed" | "oem_state_unknown"
        )
    });
    if !error
        .details
        .iter()
        .any(|detail| detail == "oem_rejected_before_write")
    {
        error.details.push("oem_rejected_before_write".into());
    }
    error
}
fn transact(io: &mut impl OemIo, plan: &OemPlan) -> Result<OemValue, ControlError> {
    let previous = Observation {
        value: plan.previous.clone(),
        companion_brightness: plan.companion_brightness,
    };
    if io.observe().map_err(rejected)? != previous {
        return Err(rejected(ControlError::new(
            "oem_plan_stale",
            "The control or its companion brightness changed before the write",
        )));
    }
    let attempt = io.write(&plan.target).and_then(|()| {
        let observed = io.observe()?;
        if observed.value == plan.target
            && observed.companion_brightness == plan.companion_brightness
        {
            Ok(observed.value)
        } else {
            Err(ControlError::new(
                "oem_readback_mismatch",
                "The driver did not report the requested value and unchanged companion state",
            ))
        }
    });
    let mut error = match attempt {
        Ok(value) => return Ok(value),
        Err(error) => error,
    };
    if error
        .details
        .iter()
        .any(|detail| detail == "oem_rejected_before_write")
    {
        return Err(error);
    }
    error
        .details
        .push(format!("readback scope: {}", plan.readback_scope));
    let observed = match io.observe() {
        Ok(value) if belongs_to_request(&value, plan) => value,
        Ok(_) => {
            error.details.push("restore_not_attempted: a third-party value or companion change was observed; it was not overwritten".into());
            error.details.push("oem_state_unknown".into());
            return Err(error);
        }
        Err(observe) => {
            error.details.push(format!(
                "restore_not_attempted: current state is unknown: {observe}"
            ));
            error.details.push("oem_state_unknown".into());
            return Err(error);
        }
    };
    // Even a failed RGB callback can leave some physical registers changed
    // while the LED core retains a requested value. Reapply the old request,
    // then the companion brightness, reporting each outcome independently.
    let mut restore_operations_ok = true;
    if observed.value != plan.previous || plan.kind == OemControlKind::KeyboardColor {
        match io.write(&plan.previous) {
            Ok(()) => error.details.push("restore_value_write_completed".into()),
            Err(restore) => {
                restore_operations_ok = false;
                error
                    .details
                    .push(format!("restore_value_write_failed: {restore}"));
            }
        }
    }
    if let Some(brightness) = plan.companion_brightness {
        match io.observe() {
            Ok(value) if value == previous => match io.write_companion(brightness) {
                Ok(()) => error
                    .details
                    .push("restore_brightness_write_completed".into()),
                Err(restore) => {
                    restore_operations_ok = false;
                    error
                        .details
                        .push(format!("restore_brightness_write_failed: {restore}"));
                }
            },
            Ok(_) => {
                restore_operations_ok = false;
                error.details.push(
                    "restore_brightness_not_attempted: state changed during restoration".into(),
                );
            }
            Err(restore) => {
                restore_operations_ok = false;
                error
                    .details
                    .push(format!("restore_brightness_not_attempted: {restore}"));
            }
        }
    }
    match io.observe() {
        Ok(value) if value == previous && restore_operations_ok => {
            error.details.push(
                "restore_confirmed: previous driver-reported value and companion state".into(),
            );
            error.details.push("oem_restore_confirmed".into());
        }
        Ok(value) if value == previous => {
            // In particular, LED core can retain the old requested value even
            // when physical restore callbacks fail. Its cache cannot turn a
            // known failed restoration into a verified success.
            error.details.push("restore_unconfirmed: previous requested state is visible, but a restoration operation failed or observed a concurrent change".into());
            error.details.push("oem_state_unknown".into());
        }
        Ok(_) => {
            error.details.push(
                "restore_unconfirmed: driver-reported state differs from the previous state".into(),
            );
            error.details.push("oem_state_unknown".into());
        }
        Err(restore) => {
            error.details.push(format!("restore_unknown: {restore}"));
            error.details.push("oem_state_unknown".into());
        }
    }
    Err(error)
}
