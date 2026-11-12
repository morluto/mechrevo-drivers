//! Windows uses standard CIM and OS power schemes only; no OEM driver is assumed.
#![cfg_attr(not(target_os = "windows"), allow(dead_code))]
use crate::*;
use std::{path::PathBuf, time::Duration};
fn powershell() -> String {
    let root = std::env::var_os("SystemRoot").unwrap_or_else(|| r"C:\Windows".into());
    PathBuf::from(root)
        .join("System32/WindowsPowerShell/v1.0/powershell.exe")
        .to_string_lossy()
        .into_owned()
}
fn powercfg() -> String {
    let root = std::env::var_os("SystemRoot").unwrap_or_else(|| r"C:\Windows".into());
    PathBuf::from(root)
        .join("System32/powercfg.exe")
        .to_string_lossy()
        .into_owned()
}
const CIM_SCRIPT: &str = r#"$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);$c=Get-CimInstance Win32_ComputerSystem;$b=Get-CimInstance Win32_BIOS;$m=Get-CimInstance Win32_BaseBoard;$p=Get-CimInstance Win32_ComputerSystemProduct | Select-Object Version;$batteries=@(Get-CimInstance Win32_Battery | Select-Object DeviceID,Name,EstimatedChargeRemaining,BatteryStatus);[PSCustomObject]@{manufacturer=$c.Manufacturer;product_name=$c.Model;product_version=$p.Version;board_name=$m.Product;bios_version=$b.SMBIOSBIOSVersion;batteries=$batteries}|ConvertTo-Json -Depth 5 -Compress"#;
fn source(path: &str, device: &str) -> EvidenceSource {
    EvidenceSource {
        backend: "windows_cim".into(),
        path: path.into(),
        device_id: Some(device.into()),
    }
}
fn json_string(value: &serde_json::Value, key: &str) -> Option<String> {
    value[key]
        .as_str()
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
}
fn parse_cim(
    output: &str,
) -> Result<(Identity, Vec<SensorReading>, Vec<Diagnostic>), ControlError> {
    let v: serde_json::Value = serde_json::from_str(output.trim_start_matches('\u{feff}'))
        .map_err(|e| ControlError::new("cim_invalid_json", e.to_string()))?;
    if !v.is_object() {
        return Err(ControlError::new(
            "cim_invalid_json",
            "CIM response must be an object",
        ));
    }
    let mut identity = Identity {
        manufacturer: json_string(&v, "manufacturer"),
        product_name: json_string(&v, "product_name"),
        product_version: json_string(&v, "product_version"),
        board_name: json_string(&v, "board_name"),
        bios_version: json_string(&v, "bios_version"),
        ..Default::default()
    };
    identity.qualify();
    let mut telemetry = vec![];
    let mut diagnostics = vec![];
    for battery in v["batteries"].as_array().into_iter().flatten() {
        let Some(id) = json_string(battery, "DeviceID") else {
            diagnostics.push(Diagnostic {
                code: "battery_identity_unavailable".into(),
                message: "Skipped battery reading without a device ID; cannot safely associate it"
                    .into(),
            });
            continue;
        };
        let value = battery["EstimatedChargeRemaining"]
            .as_f64()
            .filter(|v| v.is_finite() && *v >= 0. && *v <= 100.);
        telemetry.push(SensorReading {
            id: format!("{id}/capacity"),
            label: json_string(battery, "Name").unwrap_or_else(|| id.clone()),
            device_id: id.clone(),
            kind: "battery_capacity".into(),
            value,
            unit: "%".into(),
            source: source("root/cimv2:Win32_Battery.EstimatedChargeRemaining", &id),
            status: if value.is_some() {
                CapabilityStatus::Available
            } else {
                CapabilityStatus::Unavailable
            },
            reason: value
                .is_none()
                .then(|| "CIM did not return a valid capacity; unknown is not 0%".into()),
        });
        diagnostics.push(Diagnostic {
            code: "battery_status".into(),
            message: format!(
                "{id}: Win32_Battery.BatteryStatus={}; this is separate from AC supply online",
                battery["BatteryStatus"]
            ),
        });
    }
    if telemetry.is_empty() {
        diagnostics.push(Diagnostic {
            code: "battery_unavailable".into(),
            message: "CIM returned no identified battery readings; no charge value invented".into(),
        });
    }
    Ok((identity, telemetry, diagnostics))
}
fn is_guid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_hexdigit()
            }
        })
}
fn parse_schemes(text: &str) -> Result<PowerPolicy, ControlError> {
    let mut options = Vec::new();
    let mut current = None;
    for line in text.lines() {
        let guid = line
            .split(|c: char| !c.is_ascii_hexdigit() && c != '-')
            .find(|v| is_guid(v));
        if let Some(guid) = guid {
            let guid = guid.to_ascii_lowercase();
            if !options.contains(&guid) {
                options.push(guid.clone())
            }
            if line.trim_end().ends_with('*') {
                if current.is_some() {
                    return Err(ControlError::new(
                        "powercfg_ambiguous",
                        "Multiple active power schemes reported",
                    ));
                }
                current = Some(guid);
            }
        }
    }
    if options.is_empty() || current.is_none() {
        return Err(ControlError::new(
            "powercfg_unavailable",
            "Cannot identify installed and active OS power schemes",
        ));
    }
    Ok(PowerPolicy {
        scope: "Windows OS power scheme (not OEM performance mode)".into(),
        current,
        options,
        source: Some(EvidenceSource {
            backend: "windows_powercfg".into(),
            path: "powercfg /list".into(),
            device_id: None,
        }),
    })
}
fn policy() -> Result<PowerPolicy, ControlError> {
    let output = command::run_command(&powercfg(), &["/list"], Duration::from_secs(3), 64 * 1024)?;
    parse_schemes(&output.stdout)
}
// @mark mechrevo.telemetry role=implementation
pub(crate) fn snapshot() -> Snapshot {
    let mut diagnostics = Vec::new();
    let (identity, telemetry, mut cim_diagnostics) = match command::run_command(
        &powershell(),
        &[
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            CIM_SCRIPT,
        ],
        Duration::from_secs(5),
        256 * 1024,
    )
    .and_then(|r| parse_cim(&r.stdout))
    {
        Ok(v) => v,
        Err(e) => {
            diagnostics.push(Diagnostic {
                code: e.code,
                message: e.message,
            });
            let mut id = Identity::default();
            id.qualify();
            (id, vec![], vec![])
        }
    };
    diagnostics.append(&mut cim_diagnostics);
    let power_policy = match policy() {
        Ok(p) => p,
        Err(e) => {
            diagnostics.push(Diagnostic {
                code: e.code,
                message: e.message,
            });
            PowerPolicy {
                scope: "Windows OS power scheme (not OEM performance mode)".into(),
                ..Default::default()
            }
        }
    };
    let mut capabilities = proprietary_capabilities();
    capabilities.push(Capability{id:"power_profile".into(),label:"OS power scheme".into(),status:if power_policy.current.is_some(){CapabilityStatus::Available}else{CapabilityStatus::Unavailable},reason:"Only an installed standard Windows OS power scheme is selectable; hardware OEM modes and GPU limits are separate and unavailable.".into(),source:power_policy.source.clone(),options:power_policy.options.clone()});
    capabilities.push(Capability{id:"telemetry".into(),label:"CIM battery telemetry".into(),status:if telemetry.iter().any(|r|r.value.is_some()){CapabilityStatus::Available}else{CapabilityStatus::Unavailable},reason:"No verified vendor driver for CPU/GPU temperature or fan RPM. CIM battery readings only; missing sensors remain unknown.".into(),source:None,options:vec![]});
    diagnostics.push(Diagnostic{code:"oem_driver_not_used".into(),message:"No proprietary driver opened. CPU/GPU temperatures, fan speeds, EC and MUX controls require a separately verified model backend.".into()});
    Snapshot {
        platform: "windows".into(),
        identity,
        telemetry,
        capabilities,
        power_policy,
        diagnostics,
        brightness: vec![],
        oem_controls: vec![],
    }
}
// @mark mechrevo.os_power_policy role=implementation
pub(crate) fn plan(requested: PowerProfile) -> Result<ProfilePlan, ControlError> {
    let state = policy()?;
    let target = profile_target("windows", requested).unwrap();
    if !state.options.iter().any(|v| v == target) {
        return Err(ControlError::new("profile_unsupported","Requested standard OS power scheme is not installed; no scheme is created or OEM mode substituted"));
    }
    Ok(ProfilePlan {
        requested,
        target: target.into(),
        previous: state.current.unwrap(),
        scope: state.scope,
        source: state.source.unwrap(),
    })
}
pub(crate) fn apply(requested: &ProfilePlan) -> Result<ApplyResult, ControlError> {
    let fresh = plan(requested.requested)?;
    if fresh.target != requested.target
        || fresh.previous != requested.previous
        || fresh.source != requested.source
        || fresh.scope != requested.scope
    {
        return Err(ControlError::new(
            "stale_plan",
            "Power scheme changed or plan target/backend is invalid; create a new plan",
        ));
    }
    apply_verified(
        requested,
        || {
            policy()?
                .current
                .ok_or_else(|| ControlError::new("readback_failed", "No active power scheme"))
        },
        |value| {
            if !is_guid(value) {
                return Err(ControlError::new(
                    "invalid_profile",
                    "Power scheme must be a validated GUID",
                ));
            }
            command::run_command(
                &powercfg(),
                &["/setactive", value],
                Duration::from_secs(3),
                64 * 1024,
            )
            .map(|_| ())
        },
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn localized_scheme_output_parses_without_english_labels() {
        let p=parse_schemes("电源方案 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e (平衡) *\nEnergieschema-GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c (Hochleistung)").unwrap();
        assert_eq!(p.options.len(), 2);
        assert!(p.current.unwrap().starts_with("381b"));
    }
    #[test]
    fn missing_or_ambiguous_active_scheme_is_an_error() {
        assert!(parse_schemes("no data").is_err());
        assert!(parse_schemes(
            "381b4222-f694-41f0-9685-ff5bb260df2e *\na1841308-3541-4fab-bc81-f71556f20b4a *"
        )
        .is_err());
    }
    #[test]
    fn null_battery_capacity_stays_unknown_and_identity_has_no_private_fields() {
        let (id,values,diagnostics)=parse_cim(r#"{"manufacturer":"MECHREVO","product_name":"GM6PX0X","serial_number":"secret","batteries":[{"DeviceID":"BAT0","EstimatedChargeRemaining":null,"BatteryStatus":2},{"DeviceID":"BAT1","EstimatedChargeRemaining":80,"BatteryStatus":6}]}"#).unwrap();
        assert!(id.mechrevo_brand_detected);
        assert_eq!(values[0].value, None);
        assert_eq!(values[1].value, Some(80.));
        assert_ne!(values[0].device_id, values[1].device_id);
        assert!(diagnostics.iter().any(|v| v.code == "battery_status"));
        assert!(!serde_json::to_string(&id).unwrap().contains("secret"));
    }
    #[test]
    fn invalid_cim_payload_is_diagnostic() {
        assert!(parse_cim("[]").is_err());
        assert!(parse_cim("broken").is_err());
    }
}
