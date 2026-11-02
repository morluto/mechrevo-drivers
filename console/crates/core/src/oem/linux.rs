use super::*;
use std::{
    ffi::CString,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{
            ffi::OsStrExt,
            fs::{MetadataExt, OpenOptionsExt},
        },
    },
    path::{Component, PathBuf},
};

const PLATFORM: &str = "devices/platform/tuxedo_keyboard";
const EC_SCOPE: &str = "EC-reported state through the loaded tuxedo_keyboard driver; physical behavior and persistence require separate verification";
const LED_SCOPE: &str =
    "LED core requested-state cache; readback does not measure physical color or emitted light";
const ATTRIBUTES: &[&str] = &[
    "srcversion",
    "fn_lock",
    "charging_profile",
    "charging_profiles_available",
    "ac_auto_boot",
    "usb_powershare",
    "usb_powershare_high",
    "brightness",
    "max_brightness",
    "multi_index",
    "multi_intensity",
    "multi_max_intensity",
];
fn io_error(action: &str, error: impl std::fmt::Display) -> ControlError {
    ControlError::new("oem_io", format!("{action}: {error}"))
}
fn invalid(message: impl Into<String>) -> ControlError {
    ControlError::new("invalid_oem_device", message)
}
struct Device {
    dir: File,
    canonical: PathBuf,
    require_sysfs: bool,
}
fn verify_sysfs(file: &File) -> Result<(), ControlError> {
    let mut info = std::mem::MaybeUninit::<libc::statfs>::uninit();
    // SAFETY: live file descriptor and storage large enough for one statfs.
    if unsafe { libc::fstatfs(file.as_raw_fd(), info.as_mut_ptr()) } != 0 {
        return Err(io_error(
            "Cannot identify OEM filesystem",
            std::io::Error::last_os_error(),
        ));
    }
    // SAFETY: successful fstatfs initialized the structure.
    if unsafe { info.assume_init() }.f_type != libc::SYSFS_MAGIC {
        return Err(invalid("The real /sys OEM interface is not on sysfs"));
    }
    Ok(())
}
impl Device {
    fn open(root: &Path, relative: &Path, led_owner: Option<&Path>) -> Result<Self, ControlError> {
        let canonical = fs::canonicalize(root.join(relative))
            .map_err(|e| io_error("Cannot resolve OEM device", e))?;
        if let Some(owner) = led_owner {
            let expected = root.join(owner);
            if canonical.parent() != Some(expected.join("leds").as_path())
                || canonical.file_name() != relative.file_name()
            {
                return Err(invalid(
                    "Keyboard LED is not owned by the selected driver device",
                ));
            }
        } else if canonical != root.join(relative) {
            return Err(invalid("Fixed OEM device path was replaced by a symlink"));
        }
        let relative = canonical
            .strip_prefix(root)
            .map_err(|_| invalid("OEM device escapes the selected sysfs root"))?;
        if relative.as_os_str().is_empty() {
            return Err(invalid("OEM device cannot be the sysfs root"));
        }
        let mut dir = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(root)
            .map_err(|e| io_error("Cannot open sysfs root", e))?;
        let require_sysfs = root == Path::new("/sys");
        if require_sysfs {
            verify_sysfs(&dir)?;
        }
        for component in relative.components() {
            let Component::Normal(name) = component else {
                return Err(invalid("Invalid OEM directory component"));
            };
            let name = CString::new(name.as_bytes()).map_err(|e| invalid(e.to_string()))?;
            // SAFETY: held parent descriptor and NUL-terminated single component.
            let fd = unsafe {
                libc::openat(
                    dir.as_raw_fd(),
                    name.as_ptr(),
                    libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
                )
            };
            if fd < 0 {
                return Err(io_error(
                    "Cannot open OEM directory",
                    std::io::Error::last_os_error(),
                ));
            }
            // SAFETY: openat returned a new owned descriptor.
            dir = unsafe { File::from_raw_fd(fd) };
        }
        if require_sysfs {
            verify_sysfs(&dir)?;
        }
        Ok(Self {
            dir,
            canonical,
            require_sysfs,
        })
    }
    fn attribute(&self, name: &str, write: bool) -> Result<File, ControlError> {
        if !ATTRIBUTES.contains(&name)
            || (write
                && !matches!(
                    name,
                    "fn_lock"
                        | "charging_profile"
                        | "ac_auto_boot"
                        | "usb_powershare"
                        | "usb_powershare_high"
                        | "brightness"
                        | "multi_intensity"
                ))
        {
            return Err(invalid("OEM attribute is outside the fixed whitelist"));
        }
        let name = CString::new(name).expect("fixed attribute");
        let flags = libc::O_NOFOLLOW
            | libc::O_CLOEXEC
            | libc::O_NONBLOCK
            | if write {
                libc::O_WRONLY
            } else {
                libc::O_RDONLY
            };
        // SAFETY: held device descriptor and a whitelisted attribute basename.
        let fd = unsafe { libc::openat(self.dir.as_raw_fd(), name.as_ptr(), flags) };
        if fd < 0 {
            return Err(io_error(
                "Cannot open OEM attribute",
                std::io::Error::last_os_error(),
            ));
        }
        // SAFETY: openat returned a new owned descriptor.
        let file = unsafe { File::from_raw_fd(fd) };
        if !file
            .metadata()
            .map_err(|e| io_error("Cannot inspect OEM attribute", e))?
            .is_file()
        {
            return Err(invalid("OEM attribute is not a regular sysfs file"));
        }
        if self.require_sysfs {
            verify_sysfs(&file)?;
        }
        Ok(file)
    }
    fn read(&self, name: &str) -> Result<String, ControlError> {
        let mut value = String::new();
        self.attribute(name, false)?
            .take(4097)
            .read_to_string(&mut value)
            .map_err(|e| io_error("Cannot read OEM attribute", e))?;
        if value.len() > 4096 || value.trim().is_empty() || value.contains('\0') {
            return Err(invalid(format!("Invalid or oversized {name}")));
        }
        Ok(value.trim().into())
    }
    fn numeric(&self, name: &str) -> Result<u32, ControlError> {
        numeric(&self.read(name)?)
    }
    fn write(&self, name: &str, value: &str) -> Result<(), ControlError> {
        let mut file = self.attribute(name, true).map_err(rejected)?;
        // Sysfs stores consume one write; a short write is a failure, not an
        // invitation to submit a second, potentially different device command.
        let payload = format!("{value}\n");
        let written = file
            .write(payload.as_bytes())
            .map_err(|e| io_error("Cannot write OEM attribute", e))?;
        if written != payload.len() {
            return Err(io_error("Cannot write OEM attribute", "short write"));
        }
        // Injected roots use regular-file sysfs fixtures. Trim their old tail
        // only after the store succeeds. Real /sys receives exactly one write,
        // with its filesystem verified before any data-changing operation.
        if !self.require_sysfs {
            file.set_len(payload.len() as u64)
                .map_err(|e| io_error("Cannot finish OEM fixture store", e))?;
        }
        Ok(())
    }
    fn writable(&self, name: &str) -> bool {
        let name = CString::new(name).expect("fixed attribute");
        // SAFETY: held directory descriptor; only checks effective permissions.
        unsafe {
            libc::faccessat(
                self.dir.as_raw_fd(),
                name.as_ptr(),
                libc::W_OK,
                libc::AT_EACCESS | libc::AT_SYMLINK_NOFOLLOW,
            ) == 0
        }
    }
    fn identity(&self) -> Result<String, ControlError> {
        let metadata = self
            .dir
            .metadata()
            .map_err(|e| io_error("Cannot inspect OEM binding", e))?;
        Ok(format!(
            "{}@{}:{}",
            self.canonical.display(),
            metadata.dev(),
            metadata.ino()
        ))
    }
}
fn numeric(value: &str) -> Result<u32, ControlError> {
    if value.is_empty() || !value.bytes().all(|v| v.is_ascii_digit()) {
        return Err(invalid("Expected an unsigned decimal OEM attribute"));
    }
    value
        .parse()
        .map_err(|e| invalid(format!("OEM numeric value is out of range: {e}")))
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Provider {
    Tuxedo,
    Uniwill,
    Bitland,
}
impl Provider {
    fn module(self) -> &'static str {
        match self {
            Self::Tuxedo => "tuxedo_keyboard",
            Self::Uniwill => "uniwill_laptop",
            Self::Bitland => "bitland_mifs_wmi",
        }
    }
    fn driver(self) -> &'static str {
        match self {
            Self::Tuxedo => "bus/platform/drivers/tuxedo_keyboard",
            Self::Uniwill => "bus/platform/drivers/uniwill-laptop",
            Self::Bitland => "bus/wmi/drivers/bitland-mifs-wmi",
        }
    }
    fn backend(self) -> &'static str {
        match self {
            Self::Tuxedo => "linux_tuxedo_sysfs",
            Self::Uniwill => "linux_uniwill_sysfs",
            Self::Bitland => "linux_bitland_sysfs",
        }
    }
    fn accepts_device(self, name: &str) -> bool {
        match self {
            Self::Tuxedo => false,
            Self::Uniwill => name.strip_prefix("INOU0000:").is_some_and(|suffix| {
                suffix.len() == 2 && suffix.bytes().all(|b| b.is_ascii_hexdigit())
            }),
            // Only the control GUID owns controls; never the shared event GUID.
            Self::Bitland => name
                .strip_prefix("B60BFB48-3E5B-49E4-A0E9-8CFFE1B3434B-")
                .is_some_and(|suffix| {
                    !suffix.is_empty()
                        && suffix.len() <= 8
                        && suffix.bytes().all(|b| b.is_ascii_digit())
                }),
        }
    }
}

fn native_owners(root: &Path) -> Vec<(Provider, PathBuf)> {
    let mut result = vec![];
    for provider in [Provider::Uniwill, Provider::Bitland] {
        let driver = root.join(provider.driver());
        let mut entries = fs::read_dir(&driver)
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .take(64)
            .collect::<Vec<_>>();
        entries.sort_by_key(|entry| entry.file_name());
        for entry in entries {
            let name = entry.file_name();
            if !name
                .to_str()
                .is_some_and(|name| provider.accepts_device(name))
            {
                continue;
            }
            let Ok(owner) = fs::canonicalize(entry.path()) else {
                continue;
            };
            if !owner.starts_with(root.join("devices"))
                || owner.file_name() != Some(name.as_os_str())
                || fs::canonicalize(owner.join("driver")).ok().as_ref() != Some(&driver)
            {
                continue;
            }
            if let Ok(relative) = owner.strip_prefix(root) {
                result.push((provider, relative.to_owned()));
            }
        }
    }
    result
}

fn driver_binding(root: &Path, spec: &Spec) -> Result<String, ControlError> {
    let module_path = PathBuf::from("module").join(spec.provider.module());
    let module = Device::open(root, &module_path, None)?;
    let revision = module.read("srcversion")?;
    if revision.len() > 128 || !revision.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(invalid("The loaded OEM driver srcversion is invalid"));
    }
    let mut binding = format!("{}:srcversion={revision}", module.identity()?);
    if spec.provider != Provider::Tuxedo {
        let owner = root.join(&spec.owner);
        let driver = root.join(spec.provider.driver());
        if fs::canonicalize(owner.join("driver")).ok().as_ref() != Some(&driver)
            || fs::canonicalize(driver.join("module")).ok().as_ref()
                != Some(&root.join(module_path))
        {
            return Err(invalid(
                "Native OEM device is not bound to its expected driver/module",
            ));
        }
        let owner_device = Device::open(root, &spec.owner, None)?;
        binding.push_str(&format!("|owner={}", owner_device.identity()?));
    }
    Ok(binding)
}
#[derive(Clone)]
struct Spec {
    id: String,
    kind: OemControlKind,
    label: &'static str,
    directory: PathBuf,
    attribute: &'static str,
    led: bool,
    provider: Provider,
    owner: PathBuf,
}
impl Spec {
    fn scope(&self) -> &'static str {
        if self.led {
            LED_SCOPE
        } else if self.provider == Provider::Tuxedo {
            EC_SCOPE
        } else {
            "State reported by the bound native kernel driver; physical behavior and persistence require separate verification"
        }
    }
    fn fallback_domain(&self) -> OemDomain {
        match self.kind {
            OemControlKind::ChargingProfile => OemDomain::Choices(vec![]),
            OemControlKind::KeyboardBrightness => OemDomain::Level { max: 0 },
            OemControlKind::KeyboardColor => OemDomain::Rgb,
            _ => OemDomain::Boolean,
        }
    }
}
fn specs(root: &Path) -> Vec<Spec> {
    let mut result = vec![];
    for (id, kind, label, directory, attribute) in [
        (
            "fn-lock",
            OemControlKind::FnLock,
            "Fn 锁",
            PLATFORM,
            "fn_lock",
        ),
        (
            "charging-profile",
            OemControlKind::ChargingProfile,
            "充电模式",
            "devices/platform/tuxedo_keyboard/charging_profile",
            "charging_profile",
        ),
        (
            "ac-auto-boot",
            OemControlKind::AcAutoBoot,
            "接电开机",
            "devices/platform/tuxedo_keyboard/ac_auto_boot",
            "ac_auto_boot",
        ),
        (
            "usb-power-share",
            OemControlKind::UsbPowerShare,
            "关机 USB 供电",
            "devices/platform/tuxedo_keyboard/usb_powershare",
            "usb_powershare",
        ),
    ] {
        if fs::symlink_metadata(root.join(directory).join(attribute)).is_ok() {
            result.push(Spec {
                id: id.into(),
                kind,
                label,
                directory: directory.into(),
                attribute,
                led: false,
                provider: Provider::Tuxedo,
                owner: PLATFORM.into(),
            });
        }
    }
    let owners = native_owners(root);
    for (provider, owner) in &owners {
        for (id, kind, label, attribute) in [
            ("fn-lock", OemControlKind::FnLock, "Fn 锁", "fn_lock"),
            (
                "ac-auto-boot",
                OemControlKind::AcAutoBoot,
                "接电开机",
                "ac_auto_boot",
            ),
            (
                "usb-power-share",
                OemControlKind::UsbPowerShare,
                "关机 USB 供电",
                "usb_powershare_high",
            ),
        ] {
            // These ABI attributes belong to uniwill-laptop. The Bitland
            // driver currently provides keyboard brightness through LED class.
            if *provider != Provider::Uniwill {
                continue;
            }
            if fs::symlink_metadata(root.join(owner).join(attribute)).is_ok() {
                result.push(Spec {
                    id: format!(
                        "{id}:{}:{}",
                        provider.module(),
                        owner.file_name().unwrap_or_default().to_string_lossy()
                    ),
                    kind,
                    label,
                    directory: owner.clone(),
                    attribute,
                    led: false,
                    provider: *provider,
                    owner: owner.clone(),
                });
            }
        }
    }
    let mut leds = fs::read_dir(root.join("class/leds"))
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .take(64)
        .collect::<Vec<_>>();
    leds.sort_by_key(|entry| entry.file_name());
    for led in leds {
        let Some(name) = led.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        if !name.ends_with(":kbd_backlight")
            || name.len() > 255
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_:-.+".contains(&b))
        {
            continue;
        }
        let canonical = fs::canonicalize(led.path()).ok();
        let (provider, owner) = owners
            .iter()
            .find(|(_, owner)| {
                canonical.as_ref().and_then(|path| path.parent())
                    == Some(root.join(owner).join("leds").as_path())
            })
            .cloned()
            .unwrap_or((Provider::Tuxedo, PathBuf::from(PLATFORM)));
        for (id, kind, label, attribute) in [
            (
                "keyboard-brightness",
                OemControlKind::KeyboardBrightness,
                "键盘背光亮度",
                "brightness",
            ),
            (
                "keyboard-color",
                OemControlKind::KeyboardColor,
                "键盘背光颜色",
                "multi_intensity",
            ),
        ] {
            // Native Uniwill RGB uses a different channel range (50), and
            // Bitland does not expose this multicolor ABI. Do not inherit the
            // old tuxedo_keyboard fallback range of 255.
            if provider != Provider::Tuxedo && kind == OemControlKind::KeyboardColor {
                continue;
            }
            if fs::symlink_metadata(led.path().join(attribute)).is_ok() {
                result.push(Spec {
                    id: format!("{id}:{name}"),
                    kind,
                    label,
                    directory: PathBuf::from("class/leds").join(&name),
                    attribute,
                    led: true,
                    provider,
                    owner: owner.clone(),
                });
            }
        }
    }
    result
}
struct Inspected {
    control: OemControl,
    companion: Option<u32>,
    device: Device,
    order: Option<[usize; 3]>,
}
fn rgb_order(device: &Device) -> Result<[usize; 3], ControlError> {
    let indices = device.read("multi_index")?;
    let names = indices.split_whitespace().collect::<Vec<_>>();
    if names.len() != 3 {
        return Err(invalid("Only a three-channel RGB keyboard is supported"));
    }
    let mut order = [0; 3];
    for (channel, name) in ["red", "green", "blue"].iter().enumerate() {
        let positions = names
            .iter()
            .enumerate()
            .filter(|(_, v)| *v == name)
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if positions.len() != 1 {
            return Err(invalid(
                "RGB channel names must be unique red, green and blue",
            ));
        }
        order[channel] = positions[0];
    }
    match device.read("multi_max_intensity") {
        Ok(value) => {
            let values = value
                .split_whitespace()
                .map(numeric)
                .collect::<Result<Vec<_>, _>>()?;
            if values != [255, 255, 255] {
                return Err(invalid("RGB intensity maxima are not 255 per channel"));
            }
        }
        Err(error) => {
            // Older kernels omit multi_max_intensity. The bound driver's
            // single-zone RGB implementation defines 0xff per-channel input
            // (uniwill_leds.h UNIWILL_KBD_INTENSITY_MAX_1_ZONE_RGB). No other
            // LED name, owner or advertised maximum receives this fallback.
            if device
                .canonical
                .file_name()
                .is_none_or(|n| n != "rgb:kbd_backlight")
                || !fs::symlink_metadata(device.canonical.join("multi_max_intensity"))
                    .is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound)
            {
                return Err(error);
            }
        }
    }
    Ok(order)
}
fn read_rgb(device: &Device, order: [usize; 3]) -> Result<OemValue, ControlError> {
    let values = device
        .read("multi_intensity")?
        .split_whitespace()
        .map(numeric)
        .collect::<Result<Vec<_>, _>>()?;
    if values.len() != 3 || values.iter().any(|v| *v > 255) {
        return Err(invalid(
            "RGB intensity must contain exactly three 0..255 values",
        ));
    }
    Ok(OemValue::Rgb([
        values[order[0]] as u8,
        values[order[1]] as u8,
        values[order[2]] as u8,
    ]))
}
fn inspect(root: &Path, spec: &Spec) -> Result<Inspected, ControlError> {
    let driver = driver_binding(root, spec)?;
    let device = Device::open(
        root,
        &spec.directory,
        spec.led.then_some(spec.owner.as_path()),
    )?;
    let mut order = None;
    let mut companion = None;
    let (domain, current) = match spec.kind {
        OemControlKind::PerformanceProfile => return Err(unavailable()),
        OemControlKind::FnLock | OemControlKind::AcAutoBoot | OemControlKind::UsbPowerShare => {
            let value = match device.read(spec.attribute)?.as_str() {
                "0" => false,
                "1" => true,
                _ => return Err(invalid("Boolean OEM attribute is neither 0 nor 1")),
            };
            (OemDomain::Boolean, OemValue::Boolean(value))
        }
        OemControlKind::ChargingProfile => {
            let advertised = device.read("charging_profiles_available")?;
            let choices = advertised
                .split_whitespace()
                .map(str::to_owned)
                .collect::<Vec<_>>();
            let allowed = ["high_capacity", "balanced", "stationary"];
            if choices.is_empty()
                || choices.iter().any(|v| !allowed.contains(&v.as_str()))
                || choices
                    .iter()
                    .collect::<std::collections::HashSet<_>>()
                    .len()
                    != choices.len()
            {
                return Err(invalid("Invalid or duplicate advertised charging profiles"));
            }
            let value = device.read(spec.attribute)?;
            if !choices.contains(&value) {
                return Err(invalid("Current charging profile is not advertised"));
            }
            (OemDomain::Choices(choices), OemValue::Choice(value))
        }
        OemControlKind::KeyboardBrightness => {
            let max = device.numeric("max_brightness")?;
            let value = device.numeric("brightness")?;
            if max == 0 || value > max {
                return Err(invalid("Invalid keyboard brightness range"));
            }
            (OemDomain::Level { max }, OemValue::Level(value))
        }
        OemControlKind::KeyboardColor => {
            let max = device.numeric("max_brightness")?;
            let brightness = device.numeric("brightness")?;
            if max == 0 || brightness > max {
                return Err(invalid("Invalid companion keyboard brightness"));
            }
            let indices = rgb_order(&device)?;
            let value = read_rgb(&device, indices)?;
            order = Some(indices);
            companion = Some(brightness);
            (OemDomain::Rgb, value)
        }
    };
    let writable =
        device.writable(spec.attribute) && (companion.is_none() || device.writable("brightness"));
    let compatibility = spec.kind == OemControlKind::KeyboardColor
        && fs::symlink_metadata(device.canonical.join("multi_max_intensity")).is_err();
    let mut reasons = vec![];
    if !writable {
        reasons.push("当前用户没有写权限；预览可用，应用需要受限授权辅助程序。".to_owned());
    }
    if compatibility {
        reasons.push("旧内核未提供 multi_max_intensity；使用已绑定 tuxedo_keyboard 单区 RGB 驱动定义的每通道 0..255 范围。".to_owned());
    }
    let control = OemControl {
        id: spec.id.clone(),
        kind: spec.kind,
        label: spec.label.into(),
        current: Some(current),
        domain,
        status: CapabilityStatus::Available,
        writable,
        source: EvidenceSource {
            backend: spec.provider.backend().into(),
            path: device.canonical.join(spec.attribute).display().to_string(),
            device_id: Some(root.join(&spec.owner).display().to_string()),
        },
        binding: format!("{}|{driver}", device.identity()?),
        readback_scope: spec.scope().into(),
        reason: (!reasons.is_empty()).then(|| reasons.join(" ")),
    };
    Ok(Inspected {
        control,
        companion,
        device,
        order,
    })
}
pub(super) fn controls(root: &Path) -> Vec<OemControl> {
    let Ok(root) = fs::canonicalize(root) else {
        return vec![];
    };
    specs(&root)
        .into_iter()
        .map(|spec| match inspect(&root, &spec) {
            Ok(inspected) => inspected.control,
            Err(error) => OemControl {
                id: spec.id.clone(),
                kind: spec.kind,
                label: spec.label.into(),
                current: None,
                domain: spec.fallback_domain(),
                status: CapabilityStatus::Unavailable,
                writable: false,
                source: EvidenceSource {
                    backend: spec.provider.backend().into(),
                    path: root
                        .join(&spec.directory)
                        .join(spec.attribute)
                        .display()
                        .to_string(),
                    device_id: Some(root.join(&spec.owner).display().to_string()),
                },
                binding: String::new(),
                readback_scope: spec.scope().into(),
                reason: Some(error.to_string()),
            },
        })
        .collect()
}
fn prepare(
    root: &Path,
    id: &str,
    target: OemValue,
) -> Result<(OemPlan, Inspected, Spec), ControlError> {
    let root = fs::canonicalize(root).map_err(|e| io_error("Cannot resolve sysfs root", e))?;
    let spec = specs(&root)
        .into_iter()
        .find(|spec| spec.id == id)
        .ok_or_else(unavailable)?;
    let inspected = inspect(&root, &spec)?;
    validate_target(&inspected.control.domain, &target)?;
    let control = &inspected.control;
    let plan = OemPlan {
        control_id: control.id.clone(),
        kind: control.kind,
        label: control.label.clone(),
        previous: control.current.clone().ok_or_else(unavailable)?,
        target,
        domain: control.domain.clone(),
        source: control.source.clone(),
        binding: control.binding.clone(),
        readback_scope: control.readback_scope.clone(),
        // SAFETY: geteuid has no arguments, pointers or side effects.
        requires_privilege: !control.writable
            || (root == Path::new("/sys") && unsafe { libc::geteuid() } != 0),
        companion_brightness: inspected.companion,
    };
    Ok((plan, inspected, spec))
}
pub(super) fn plan(root: &Path, id: &str, target: OemValue) -> Result<OemPlan, ControlError> {
    prepare(root, id, target).map(|(plan, _, _)| plan)
}
struct ControlIo {
    inspected: Inspected,
    spec: Spec,
}
impl OemIo for ControlIo {
    fn observe(&mut self) -> Result<Observation, ControlError> {
        let device = &self.inspected.device;
        let value = match self.spec.kind {
            OemControlKind::PerformanceProfile => return Err(unavailable()),
            OemControlKind::FnLock | OemControlKind::AcAutoBoot | OemControlKind::UsbPowerShare => {
                match device.read(self.spec.attribute)?.as_str() {
                    "0" => OemValue::Boolean(false),
                    "1" => OemValue::Boolean(true),
                    _ => return Err(invalid("Invalid boolean readback")),
                }
            }
            OemControlKind::ChargingProfile => OemValue::Choice(device.read(self.spec.attribute)?),
            OemControlKind::KeyboardBrightness => OemValue::Level(device.numeric("brightness")?),
            OemControlKind::KeyboardColor => {
                if Some(rgb_order(device)?) != self.inspected.order {
                    return Err(invalid("RGB channel order changed"));
                }
                read_rgb(device, self.inspected.order.ok_or_else(unavailable)?)?
            }
        };
        validate_target(&self.inspected.control.domain, &value)?;
        let companion_brightness = if self.spec.kind == OemControlKind::KeyboardColor {
            Some(device.numeric("brightness")?)
        } else {
            None
        };
        Ok(Observation {
            value,
            companion_brightness,
        })
    }
    fn write(&mut self, value: &OemValue) -> Result<(), ControlError> {
        validate_target(&self.inspected.control.domain, value)?;
        let text = match value {
            OemValue::Boolean(value) => if *value { "1" } else { "0" }.into(),
            OemValue::Choice(value) => value.clone(),
            OemValue::Level(value) => value.to_string(),
            OemValue::Rgb(rgb) => {
                let order = self.inspected.order.ok_or_else(unavailable)?;
                let mut channels = [0; 3];
                for (channel, index) in order.iter().enumerate() {
                    channels[*index] = rgb[channel];
                }
                format!("{} {} {}", channels[0], channels[1], channels[2])
            }
        };
        self.inspected.device.write(self.spec.attribute, &text)
    }
    fn write_companion(&mut self, value: u32) -> Result<(), ControlError> {
        if self.spec.kind != OemControlKind::KeyboardColor {
            return Err(invalid("This control has no companion brightness"));
        }
        let max = self.inspected.device.numeric("max_brightness")?;
        if value > max {
            return Err(invalid("Companion brightness is outside its current range"));
        }
        self.inspected
            .device
            .write("brightness", &value.to_string())
    }
}
pub(super) fn apply(root: &Path, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
    let canonical_root =
        fs::canonicalize(root).map_err(|e| rejected(io_error("Cannot resolve sysfs root", e)))?;
    // All ordinary-user system writes must go through the authorized helper,
    // even if an older utility has made an attribute world-writable. A direct
    // root caller remains trusted; other root tools do not share this API lock.
    // SAFETY: geteuid has no arguments, pointers or side effects.
    if canonical_root == Path::new("/sys") && unsafe { libc::geteuid() } != 0 {
        return Err(rejected(ControlError::new(
            "administrator_required",
            "System OEM writes require the authorized helper and its transaction lock",
        )));
    }
    let (mut fresh, inspected, spec) =
        prepare(&canonical_root, &plan.control_id, plan.target.clone()).map_err(rejected)?;
    // Privilege belongs to the caller's credentials, not hardware identity. A
    // separately authorized helper may revalidate an unprivileged user's plan.
    fresh.requires_privilege = plan.requires_privilege;
    if &fresh != plan {
        return Err(rejected(ControlError::new("oem_plan_stale", "OEM plan identity, previous state, source or advertised limits changed; create a new preview")));
    }
    let confirmed = transact(&mut ControlIo { inspected, spec }, plan)?;
    Ok(OemApplyResult {
        control_id: plan.control_id.clone(),
        kind: plan.kind,
        previous: plan.previous.clone(),
        confirmed,
        source: plan.source.clone(),
        readback_scope: plan.readback_scope.clone(),
    })
}
