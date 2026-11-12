//! The UI never performs blocking platform calls or speculative hardware writes.
//! A single worker and a one-item channel bound refresh requests and results.
use mechrevo_console_core::{
    ApplyResult, BrightnessApplyResult, BrightnessPlan, CapabilityStatus, CatalogModel,
    ControlError, OemApplyResult, OemControl, OemDomain, OemPlan, OemValue, PowerProfile,
    ProfilePlan, SensorReading, Service, Snapshot,
};
use serde::{Deserialize, Serialize};
use std::{
    panic::{catch_unwind, AssertUnwindSafe},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, SyncSender, TryRecvError},
        Arc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

#[cfg(feature = "gui")]
mod appearance;
#[cfg(feature = "gui")]
pub mod desktop;

pub trait Backend: Send + 'static {
    fn snapshot(&mut self) -> Snapshot;
    fn catalog(&mut self) -> Vec<CatalogModel>;
    fn plan(&mut self, profile: PowerProfile) -> Result<ProfilePlan, ControlError>;
    fn apply(&mut self, plan: &ProfilePlan) -> Result<ApplyResult, ControlError>;
    fn plan_brightness(
        &mut self,
        _percent: u8,
        _device: &str,
    ) -> Result<BrightnessPlan, ControlError> {
        Err(ControlError::new(
            "brightness_unavailable",
            "No brightness backend is available",
        ))
    }
    fn apply_brightness(
        &mut self,
        _plan: &BrightnessPlan,
    ) -> Result<BrightnessApplyResult, ControlError> {
        Err(ControlError::new(
            "brightness_unavailable",
            "No brightness backend is available",
        ))
    }
    fn plan_oem(&mut self, _control: &str, _target: OemValue) -> Result<OemPlan, ControlError> {
        Err(ControlError::new(
            "oem_unavailable",
            "No OEM control backend is available",
        ))
    }
    fn apply_oem(&mut self, _plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
        Err(ControlError::new(
            "oem_unavailable",
            "No OEM control backend is available",
        ))
    }
}

impl Backend for Service {
    fn snapshot(&mut self) -> Snapshot {
        Service::snapshot(self)
    }
    fn catalog(&mut self) -> Vec<CatalogModel> {
        Service::catalog(self, "")
    }
    fn plan(&mut self, profile: PowerProfile) -> Result<ProfilePlan, ControlError> {
        self.plan_profile(profile)
    }
    fn apply(&mut self, plan: &ProfilePlan) -> Result<ApplyResult, ControlError> {
        self.apply_profile(plan)
    }
    fn plan_brightness(
        &mut self,
        percent: u8,
        device: &str,
    ) -> Result<BrightnessPlan, ControlError> {
        Service::plan_brightness(self, percent, Some(device))
    }
    fn apply_brightness(
        &mut self,
        plan: &BrightnessPlan,
    ) -> Result<BrightnessApplyResult, ControlError> {
        Service::apply_brightness(self, plan)
    }
    fn plan_oem(&mut self, control: &str, target: OemValue) -> Result<OemPlan, ControlError> {
        Service::plan_oem(self, control, target)
    }
    fn apply_oem(&mut self, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
        mechrevo_console_core::privilege::apply_oem(self, plan)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum DisplayMode {
    #[default]
    Standard,
    Compact,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum Theme {
    #[default]
    System,
    Light,
    Dark,
}

/// Only display preferences persist. Plans and hardware state never do.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Preferences {
    pub display_mode: DisplayMode,
    pub theme: Theme,
    pub text_scale: f32,
    pub auto_refresh: bool,
}

impl Default for Preferences {
    fn default() -> Self {
        Self {
            display_mode: DisplayMode::Standard,
            theme: Theme::Dark,
            text_scale: 1.0,
            auto_refresh: true,
        }
    }
}

impl Preferences {
    pub fn sanitize(&mut self) {
        self.text_scale = if self.text_scale.is_finite() {
            self.text_scale.clamp(0.8, 1.6)
        } else {
            1.0
        };
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobKind {
    Refresh,
    Preview,
    Apply,
}

#[derive(Debug)]
enum Job {
    Refresh,
    Preview(PowerProfile),
    Apply(ProfilePlan),
    PreviewBrightness { percent: u8, device: String },
    ApplyBrightness(BrightnessPlan),
    PreviewOem { control: String, target: OemValue },
    ApplyOem(OemPlan),
}

impl Job {
    fn kind(&self) -> JobKind {
        match self {
            Self::Refresh => JobKind::Refresh,
            Self::Preview(_) | Self::PreviewBrightness { .. } | Self::PreviewOem { .. } => {
                JobKind::Preview
            }
            Self::Apply(_) | Self::ApplyBrightness(_) | Self::ApplyOem(_) => JobKind::Apply,
        }
    }
}

struct Request {
    id: u64,
    job: Job,
}

enum Reply {
    Snapshot(Snapshot, Vec<CatalogModel>),
    Preview(ProfilePlan),
    Applied(ApplyResult, Snapshot),
    BrightnessPreview(BrightnessPlan),
    BrightnessApplied(BrightnessApplyResult, Snapshot),
    OemPreview(OemPlan),
    OemApplied(OemApplyResult, Snapshot),
    Error(ControlError),
}

struct Response {
    id: u64,
    reply: Reply,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SubmitError {
    Busy,
    WorkerStopped,
    Unsupported,
    PreviewRequired,
}

struct InFlight {
    id: u64,
    kind: JobKind,
    started: Instant,
    selection_revision: u64,
}

pub struct Controller {
    requests: Option<SyncSender<Request>>,
    responses: Receiver<Response>,
    alive: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
    in_flight: Option<InFlight>,
    next_id: u64,
    pub snapshot: Option<Snapshot>,
    pub catalog: Vec<CatalogModel>,
    pub selected_profile: PowerProfile,
    pub preview: Option<ProfilePlan>,
    pub applied: Option<ApplyResult>,
    pub selected_brightness_device: Option<String>,
    pub requested_brightness: u8,
    pub brightness_preview: Option<BrightnessPlan>,
    pub brightness_applied: Option<BrightnessApplyResult>,
    pub selected_oem_control: Option<String>,
    pub requested_oem_value: Option<OemValue>,
    pub oem_preview: Option<OemPlan>,
    pub oem_applied: Option<OemApplyResult>,
    selection_revision: u64,
    oem_write_uncertain: bool,
    pub error: Option<ControlError>,
    pub last_refresh: Option<Instant>,
    pub worker_available: bool,
}

impl Controller {
    /// Starting a controller does not access hardware. Refresh is explicit.
    pub fn new(mut backend: impl Backend) -> Result<Self, std::io::Error> {
        let (requests, incoming) = mpsc::sync_channel::<Request>(1);
        let (outgoing, responses) = mpsc::sync_channel::<Response>(1);
        let alive = Arc::new(AtomicBool::new(true));
        let worker_alive = alive.clone();
        let worker = thread::Builder::new()
            .name("mechrevo-platform".into())
            .spawn(move || {
                while let Ok(request) = incoming.recv() {
                    if !worker_alive.load(Ordering::Acquire) {
                        break;
                    }
                    let result = catch_unwind(AssertUnwindSafe(|| match request.job {
                        Job::Refresh => Reply::Snapshot(backend.snapshot(), backend.catalog()),
                        Job::Preview(profile) => match backend.plan(profile) {
                            Ok(plan) => Reply::Preview(plan),
                            Err(error) => Reply::Error(error),
                        },
                        Job::Apply(plan) => match backend.apply(&plan) {
                            Ok(result) => Reply::Applied(result, backend.snapshot()),
                            Err(error) => Reply::Error(error),
                        },
                        Job::PreviewBrightness { percent, device } => {
                            match backend.plan_brightness(percent, &device) {
                                Ok(plan) => Reply::BrightnessPreview(plan),
                                Err(error) => Reply::Error(error),
                            }
                        }
                        Job::ApplyBrightness(plan) => match backend.apply_brightness(&plan) {
                            Ok(result) => Reply::BrightnessApplied(result, backend.snapshot()),
                            Err(error) => Reply::Error(error),
                        },
                        Job::PreviewOem { control, target } => {
                            match backend.plan_oem(&control, target) {
                                Ok(plan) => Reply::OemPreview(plan),
                                Err(error) => Reply::Error(error),
                            }
                        }
                        Job::ApplyOem(plan) => match backend.apply_oem(&plan) {
                            Ok(result) => Reply::OemApplied(result, backend.snapshot()),
                            Err(error) => Reply::Error(error),
                        },
                    }));
                    let panicked = result.is_err();
                    let reply = result.unwrap_or_else(|_| {
                        Reply::Error(ControlError::new(
                            "worker_panicked",
                            "后台检测意外退出；请关闭后重新打开控制台。",
                        ))
                    });
                    if !worker_alive.load(Ordering::Acquire)
                        || outgoing
                            .send(Response {
                                id: request.id,
                                reply,
                            })
                            .is_err()
                        || panicked
                    {
                        break;
                    }
                }
            })?;
        Ok(Self {
            requests: Some(requests),
            responses,
            alive,
            worker: Some(worker),
            in_flight: None,
            next_id: 1,
            snapshot: None,
            catalog: Vec::new(),
            selected_profile: PowerProfile::Balanced,
            preview: None,
            applied: None,
            selected_brightness_device: None,
            requested_brightness: 70,
            brightness_preview: None,
            brightness_applied: None,
            selected_oem_control: None,
            requested_oem_value: None,
            oem_preview: None,
            oem_applied: None,
            selection_revision: 0,
            oem_write_uncertain: false,
            error: None,
            last_refresh: None,
            worker_available: true,
        })
    }

    pub fn busy(&self) -> bool {
        self.in_flight.is_some() || self.oem_write_uncertain
    }

    pub fn write_in_progress(&self) -> bool {
        self.oem_write_uncertain
            || self
                .in_flight
                .as_ref()
                .is_some_and(|job| job.kind == JobKind::Apply)
    }

    pub fn oem_write_state_unknown(&self) -> bool {
        self.oem_write_uncertain
    }

    pub fn activity(&self) -> Option<(JobKind, Duration)> {
        self.in_flight
            .as_ref()
            .map(|job| (job.kind, job.started.elapsed()))
    }

    pub fn refresh(&mut self) -> Result<(), SubmitError> {
        self.submit(Job::Refresh)?;
        self.invalidate_previews();
        Ok(())
    }

    pub fn has_pending_preview(&self) -> bool {
        self.preview.is_some() || self.brightness_preview.is_some() || self.oem_preview.is_some()
    }

    fn invalidate_previews(&mut self) {
        self.preview = None;
        self.brightness_preview = None;
        self.oem_preview = None;
        self.selection_revision = self.selection_revision.wrapping_add(1);
    }

    pub fn select_profile(&mut self, profile: PowerProfile) {
        if self.selected_profile != profile {
            self.selected_profile = profile;
            self.invalidate_previews();
        }
    }

    pub fn policy_unavailable_reason(&self) -> Option<&str> {
        let Some(snapshot) = self.snapshot.as_ref() else {
            return Some("设备检测完成后才能预览电源策略。");
        };
        match snapshot
            .capabilities
            .iter()
            .find(|cap| cap.id == "power_profile")
        {
            Some(cap)
                if cap.status == CapabilityStatus::Available
                    && mechrevo_console_core::profile_available(
                        snapshot,
                        self.selected_profile,
                    ) =>
            {
                None
            }
            Some(cap) if cap.status == CapabilityStatus::Available => {
                Some("当前系统未公布所选电源策略，请选择受支持的档位。")
            }
            Some(cap) => Some(cap.reason.as_str()),
            None => Some("当前系统没有提供可用的电源策略接口。"),
        }
    }

    pub fn preview_profile(&mut self) -> Result<(), SubmitError> {
        if self.policy_unavailable_reason().is_some() {
            return Err(SubmitError::Unsupported);
        }
        self.invalidate_previews();
        self.submit(Job::Preview(self.selected_profile))?;
        Ok(())
    }

    pub fn apply_preview(&mut self) -> Result<(), SubmitError> {
        if self.policy_unavailable_reason().is_some() {
            return Err(SubmitError::Unsupported);
        }
        let plan = self
            .preview
            .as_ref()
            .filter(|plan| plan.requested == self.selected_profile)
            .cloned()
            .ok_or(SubmitError::PreviewRequired)?;
        self.submit(Job::Apply(plan))?;
        // A preview is single-use, including when applying fails or readback fails.
        self.invalidate_previews();
        self.applied = None;
        Ok(())
    }

    pub fn select_brightness_device(&mut self, device: &str) {
        if self.selected_brightness_device.as_deref() != Some(device) {
            self.selected_brightness_device = Some(device.to_owned());
            self.invalidate_previews();
            if let Some(current) = self
                .snapshot
                .as_ref()
                .and_then(|snapshot| {
                    snapshot
                        .brightness
                        .iter()
                        .find(|candidate| candidate.id == device)
                })
                .and_then(|candidate| {
                    candidate
                        .control_value
                        .zip(candidate.maximum)
                        .filter(|(_, maximum)| *maximum > 0)
                        .map(|(value, maximum)| f64::from(value) * 100.0 / f64::from(maximum))
                        .or(candidate.current_percent)
                })
                .filter(|value| value.is_finite())
            {
                self.requested_brightness = current.round().clamp(0.0, 100.0) as u8;
            }
        }
    }

    pub fn set_brightness_target(&mut self, percent: u8) {
        if self.requested_brightness != percent {
            self.requested_brightness = percent;
            self.invalidate_previews();
        }
    }

    pub fn brightness_unavailable_reason(&self) -> Option<&str> {
        let Some(snapshot) = &self.snapshot else {
            return Some("设备检测完成后才能预览亮度。");
        };
        let Some(id) = &self.selected_brightness_device else {
            return Some(if snapshot.brightness.is_empty() {
                "未发现操作系统亮度设备。"
            } else {
                "请选择要调节的显示设备。"
            });
        };
        let Some(device) = snapshot.brightness.iter().find(|device| &device.id == id) else {
            return Some("所选显示设备已离线，请刷新并重新选择。");
        };
        if device.status != CapabilityStatus::Available || !device.readable || !device.writable {
            return Some(
                device
                    .reason
                    .as_deref()
                    .unwrap_or("当前用户不能读写此设备的系统亮度接口。"),
            );
        }
        if self.requested_brightness > 100 {
            return Some("亮度必须在 0% 到 100% 之间。");
        }
        if !device.supported_percentages.is_empty()
            && !device
                .supported_percentages
                .contains(&self.requested_brightness)
        {
            return Some("该显示设备不支持此亮度档位，请选择其公布的档位。");
        }
        None
    }

    pub fn preview_brightness(&mut self) -> Result<(), SubmitError> {
        if self.brightness_unavailable_reason().is_some() {
            return Err(SubmitError::Unsupported);
        }
        self.invalidate_previews();
        self.submit(Job::PreviewBrightness {
            percent: self.requested_brightness,
            device: self
                .selected_brightness_device
                .clone()
                .ok_or(SubmitError::Unsupported)?,
        })?;
        Ok(())
    }

    pub fn apply_brightness_preview(&mut self) -> Result<(), SubmitError> {
        if self.brightness_unavailable_reason().is_some() {
            return Err(SubmitError::Unsupported);
        }
        let plan = self
            .brightness_preview
            .as_ref()
            .filter(|plan| {
                Some(plan.device_id.as_str()) == self.selected_brightness_device.as_deref()
                    && plan.requested_percent == self.requested_brightness
            })
            .cloned()
            .ok_or(SubmitError::PreviewRequired)?;
        self.submit(Job::ApplyBrightness(plan))?;
        self.invalidate_previews();
        self.brightness_applied = None;
        Ok(())
    }

    pub fn select_oem_control(&mut self, id: &str) {
        if self.selected_oem_control.as_deref() != Some(id) {
            self.selected_oem_control = Some(id.to_owned());
            self.requested_oem_value = self
                .selected_oem()
                .and_then(|control| control.current.clone());
            self.invalidate_previews();
        }
    }

    pub fn set_oem_target(&mut self, target: OemValue) {
        if self.requested_oem_value.as_ref() != Some(&target) {
            self.requested_oem_value = Some(target);
            self.invalidate_previews();
        }
    }

    pub fn selected_oem(&self) -> Option<&OemControl> {
        let id = self.selected_oem_control.as_deref()?;
        self.snapshot
            .as_ref()?
            .oem_controls
            .iter()
            .find(|control| control.id == id)
    }

    pub fn oem_unavailable_reason(&self) -> Option<&str> {
        let Some(control) = self.selected_oem() else {
            return Some("请选择本机实际提供的设备控制接口。");
        };
        if control.status != CapabilityStatus::Available || control.current.is_none() {
            return Some(
                control
                    .reason
                    .as_deref()
                    .unwrap_or("该接口目前无法完成读取与写入，请刷新核对。"),
            );
        }
        if control
            .current
            .as_ref()
            .is_some_and(|value| !oem_value_in_domain(&control.domain, value))
        {
            return Some("接口当前值不在驱动公布的类型或范围内，请刷新核对。");
        }
        let Some(target) = &self.requested_oem_value else {
            return Some("选择目标值后才能预览更改。");
        };
        if !oem_value_in_domain(&control.domain, target) {
            return Some("目标值不在驱动公布的类型或范围内，请重新选择。");
        }
        None
    }

    fn oem_plan_matches(&self, plan: &OemPlan) -> bool {
        self.selected_oem().is_some_and(|control| {
            control.id == plan.control_id
                && control.kind == plan.kind
                && control.current.as_ref() == Some(&plan.previous)
                && control.domain == plan.domain
                && control.source == plan.source
                && control.binding == plan.binding
                && control.readback_scope == plan.readback_scope
                && self.requested_oem_value.as_ref() == Some(&plan.target)
        })
    }

    pub fn preview_oem(&mut self) -> Result<(), SubmitError> {
        if self.oem_unavailable_reason().is_some() {
            return Err(SubmitError::Unsupported);
        }
        let control = self
            .selected_oem_control
            .clone()
            .ok_or(SubmitError::Unsupported)?;
        let target = self
            .requested_oem_value
            .clone()
            .ok_or(SubmitError::Unsupported)?;
        self.invalidate_previews();
        self.submit(Job::PreviewOem { control, target })
    }

    pub fn apply_oem_preview(&mut self) -> Result<(), SubmitError> {
        if self.busy() {
            return Err(SubmitError::Busy);
        }
        if self.oem_unavailable_reason().is_some() {
            self.invalidate_previews();
            return Err(SubmitError::Unsupported);
        }
        let Some(plan) = self
            .oem_preview
            .as_ref()
            .filter(|plan| self.oem_plan_matches(plan))
            .cloned()
        else {
            self.invalidate_previews();
            return Err(SubmitError::PreviewRequired);
        };
        self.submit(Job::ApplyOem(plan))?;
        self.invalidate_previews();
        self.oem_applied = None;
        Ok(())
    }

    fn submit(&mut self, job: Job) -> Result<(), SubmitError> {
        if self.busy() {
            return Err(SubmitError::Busy);
        }
        if !self.worker_available {
            return Err(SubmitError::WorkerStopped);
        }
        let id = self.next_id;
        let kind = job.kind();
        let result = self
            .requests
            .as_ref()
            .ok_or(SubmitError::WorkerStopped)?
            .try_send(Request { id, job });
        match result {
            Ok(()) => {
                self.next_id = self.next_id.wrapping_add(1);
                self.in_flight = Some(InFlight {
                    id,
                    kind,
                    started: Instant::now(),
                    selection_revision: self.selection_revision,
                });
                self.error = None;
                Ok(())
            }
            Err(mpsc::TrySendError::Full(_)) => Err(SubmitError::Busy),
            Err(mpsc::TrySendError::Disconnected(_)) => {
                self.stopped();
                Err(SubmitError::WorkerStopped)
            }
        }
    }

    /// Nonblocking; safe to call from the event/render thread.
    pub fn poll(&mut self) -> bool {
        match self.responses.try_recv() {
            Ok(response) => {
                if self.in_flight.as_ref().map(|job| job.id) != Some(response.id) {
                    return false;
                }
                let current_selection = self
                    .in_flight
                    .as_ref()
                    .is_some_and(|job| job.selection_revision == self.selection_revision);
                self.in_flight = None;
                match response.reply {
                    Reply::Snapshot(snapshot, catalog) => {
                        self.snapshot = Some(snapshot);
                        self.catalog = catalog;
                        self.last_refresh = Some(Instant::now());
                    }
                    Reply::Preview(plan) => {
                        // A selection made while a request ran must invalidate its late result.
                        if current_selection && plan.requested == self.selected_profile {
                            self.preview = Some(plan);
                        }
                    }
                    Reply::BrightnessPreview(plan) => {
                        if current_selection
                            && Some(plan.device_id.as_str())
                                == self.selected_brightness_device.as_deref()
                            && plan.requested_percent == self.requested_brightness
                        {
                            self.brightness_preview = Some(plan);
                        }
                    }
                    Reply::Applied(result, snapshot) => {
                        self.applied = Some(result);
                        self.snapshot = Some(snapshot);
                        self.last_refresh = Some(Instant::now());
                    }
                    Reply::BrightnessApplied(result, snapshot) => {
                        self.brightness_applied = Some(result);
                        self.snapshot = Some(snapshot);
                        self.last_refresh = Some(Instant::now());
                    }
                    Reply::OemPreview(plan) => {
                        if current_selection {
                            if self.oem_plan_matches(&plan) {
                                self.oem_preview = Some(plan);
                            } else {
                                self.error = Some(ControlError::new(
                                    "oem_preview_stale",
                                    "设备状态或接口已变化，请刷新后重新预览。",
                                ));
                            }
                        }
                    }
                    Reply::OemApplied(result, snapshot) => {
                        self.oem_applied = Some(result);
                        self.snapshot = Some(snapshot);
                        self.last_refresh = Some(Instant::now());
                    }
                    Reply::Error(error) => {
                        if error.code == "oem_helper_liveness_unknown" {
                            // A missing wait result is not evidence that a
                            // privileged writer stopped. Keep the write/close
                            // interlock until this process is explicitly shut
                            // down outside the normal native close path.
                            self.oem_write_uncertain = true;
                            self.invalidate_previews();
                        }
                        self.error = Some(error);
                    }
                }
                if let Some(snapshot) = &self.snapshot {
                    if self.selected_brightness_device.is_none() && snapshot.brightness.len() == 1 {
                        let id = snapshot.brightness[0].id.clone();
                        self.select_brightness_device(&id);
                    }
                }
                // A previously unavailable control can recover with the same
                // ID. Initialize only an absent target; keep user edits.
                if self.requested_oem_value.is_none() {
                    if let Some(value) = self
                        .selected_oem()
                        .filter(|control| control.status == CapabilityStatus::Available)
                        .and_then(|control| control.current.clone())
                    {
                        self.requested_oem_value = Some(value);
                        self.invalidate_previews();
                    }
                }
                true
            }
            Err(TryRecvError::Empty) => false,
            Err(TryRecvError::Disconnected) => {
                let changed = self.worker_available;
                self.stopped();
                changed
            }
        }
    }

    fn stopped(&mut self) {
        self.worker_available = false;
        self.in_flight = None;
        self.preview = None;
        self.brightness_preview = None;
        self.oem_preview = None;
        if self.error.is_none() {
            self.error = Some(ControlError::new(
                "worker_stopped",
                "后台检测已退出；请关闭后重新打开控制台。",
            ));
        }
    }

    pub fn matching_models<'a>(&'a self, query: &str) -> Vec<&'a CatalogModel> {
        let query = query.trim().to_lowercase();
        self.catalog
            .iter()
            .filter(|model| {
                [
                    model.id.as_str(),
                    model.name.as_str(),
                    model.slug.as_str(),
                    model.category.as_deref().unwrap_or(""),
                    model.series.as_deref().unwrap_or(""),
                ]
                .iter()
                .any(|part| part.to_lowercase().contains(&query))
            })
            .collect()
    }
}

impl Drop for Controller {
    fn drop(&mut self) {
        self.alive.store(false, Ordering::Release);
        self.requests.take();
        // Native UI defers close while write_in_progress(). Read-only operations
        // may detach: a process exit can safely terminate an unfinished read.
        // Core separately bounds subprocess execution.
        if let Some(worker) = self.worker.take() {
            if worker.is_finished() {
                let _ = worker.join();
            }
        }
    }
}

pub fn reading_text(reading: &SensorReading) -> String {
    match reading.value.filter(|value| value.is_finite()) {
        Some(value) if reading.status == CapabilityStatus::Available => {
            format!("{value:.1} {}", reading.unit)
        }
        _ => "不可用".into(),
    }
}

fn oem_value_in_domain(domain: &OemDomain, value: &OemValue) -> bool {
    match (domain, value) {
        (OemDomain::Boolean, OemValue::Boolean(_)) | (OemDomain::Rgb, OemValue::Rgb(_)) => true,
        (OemDomain::Choices(choices), OemValue::Choice(value)) => choices.contains(value),
        (OemDomain::Level { max }, OemValue::Level(value)) => value <= max,
        _ => false,
    }
}

// @mark mechrevo.console_ui role=verification
#[cfg(test)]
mod tests {
    use super::*;
    use mechrevo_console_core::{
        brightness::BrightnessBackend, BrightnessDevice, Capability, EvidenceSource, Identity,
        PowerPolicy,
    };
    use std::sync::atomic::AtomicUsize;

    pub(crate) fn fixture_snapshot() -> Snapshot {
        Snapshot {
            platform: "linux".into(),
            identity: Identity {
                product_name: Some("TEST FIXTURE / 非真实硬件".into()),
                ..Default::default()
            },
            telemetry: vec![],
            capabilities: vec![Capability {
                id: "power_profile".into(),
                label: "System power policy".into(),
                status: CapabilityStatus::Available,
                reason: "fixture".into(),
                source: None,
                options: vec!["balanced".into(), "performance".into()],
            }],
            power_policy: PowerPolicy {
                scope: "OS test fixture".into(),
                current: Some("balanced".into()),
                options: vec!["balanced".into(), "performance".into(), "low-power".into()],
                source: None,
            },
            brightness: vec![BrightnessDevice {
                id: "fixture-display".into(),
                label: "TEST DISPLAY / 非真实硬件".into(),
                current_percent: Some(50.0),
                control_value: Some(50),
                actual_value: Some(50),
                maximum: Some(100),
                source: EvidenceSource {
                    backend: "fixture".into(),
                    path: "display".into(),
                    device_id: Some("fixture-display".into()),
                },
                status: CapabilityStatus::Available,
                readable: true,
                writable: true,
                supported_percentages: vec![],
                reason: None,
            }],
            diagnostics: vec![],
            oem_controls: vec![],
        }
    }

    struct FixtureBackend {
        reads: Arc<AtomicUsize>,
        apply_error: bool,
        panic: bool,
    }

    impl Backend for FixtureBackend {
        fn snapshot(&mut self) -> Snapshot {
            self.reads.fetch_add(1, Ordering::Relaxed);
            assert!(!self.panic, "fixture worker panic");
            fixture_snapshot()
        }
        fn catalog(&mut self) -> Vec<CatalogModel> {
            vec![]
        }
        fn plan(&mut self, profile: PowerProfile) -> Result<ProfilePlan, ControlError> {
            Ok(ProfilePlan {
                requested: profile,
                target: profile.to_string(),
                previous: "balanced".into(),
                scope: "OS fixture".into(),
                source: EvidenceSource {
                    backend: "test".into(),
                    path: "fixture".into(),
                    device_id: None,
                },
            })
        }
        fn apply(&mut self, plan: &ProfilePlan) -> Result<ApplyResult, ControlError> {
            if self.apply_error {
                return Err(ControlError::new(
                    "access_denied",
                    "fixture permission denied",
                ));
            }
            Ok(ApplyResult {
                requested: plan.requested,
                confirmed: plan.target.clone(),
                previous: plan.previous.clone(),
                scope: plan.scope.clone(),
            })
        }
        fn plan_brightness(
            &mut self,
            percent: u8,
            device: &str,
        ) -> Result<BrightnessPlan, ControlError> {
            Ok(BrightnessPlan {
                device_id: device.into(),
                requested_percent: percent,
                target: u32::from(percent),
                previous: 50,
                maximum: 100,
                source: EvidenceSource {
                    backend: "fixture".into(),
                    path: "display".into(),
                    device_id: Some(device.into()),
                },
                backend: BrightnessBackend::LinuxSysfs,
            })
        }
        fn apply_brightness(
            &mut self,
            plan: &BrightnessPlan,
        ) -> Result<BrightnessApplyResult, ControlError> {
            if self.apply_error {
                return Err(ControlError::new(
                    "brightness_readback_mismatch",
                    "fixture readback mismatch; rollback confirmed",
                ));
            }
            Ok(BrightnessApplyResult {
                device_id: plan.device_id.clone(),
                requested_percent: plan.requested_percent,
                confirmed: plan.target,
                previous: plan.previous,
                actual_value: Some(plan.target),
                source: plan.source.clone(),
            })
        }
    }

    fn controller() -> Controller {
        Controller::new(FixtureBackend {
            reads: Arc::new(AtomicUsize::new(0)),
            apply_error: false,
            panic: false,
        })
        .unwrap()
    }

    pub(crate) fn finish(controller: &mut Controller) {
        let deadline = Instant::now() + Duration::from_secs(2);
        while controller.busy() && Instant::now() < deadline {
            controller.poll();
            thread::yield_now();
        }
        assert!(
            !controller.busy(),
            "worker failed to finish within test deadline"
        );
    }

    #[test]
    fn startup_does_not_read_or_apply_hardware() {
        let reads = Arc::new(AtomicUsize::new(0));
        let mut controller = Controller::new(FixtureBackend {
            reads: reads.clone(),
            apply_error: false,
            panic: false,
        })
        .unwrap();
        assert_eq!(reads.load(Ordering::Relaxed), 0);
        assert_eq!(controller.apply_preview(), Err(SubmitError::Unsupported));
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(reads.load(Ordering::Relaxed), 1);
        assert!(controller.snapshot.is_some());
    }

    #[test]
    fn repeated_refresh_is_single_in_flight_and_nonblocking() {
        let mut controller = controller();
        controller.refresh().unwrap();
        for _ in 0..1000 {
            assert_eq!(controller.refresh(), Err(SubmitError::Busy));
        }
        finish(&mut controller);
        assert!(controller.snapshot.is_some());
    }

    #[test]
    fn missing_driver_is_explained_and_cannot_be_applied() {
        let mut controller = controller();
        let mut snapshot = fixture_snapshot();
        snapshot.capabilities[0].status = CapabilityStatus::Unavailable;
        snapshot.capabilities[0].reason = "power-profiles-daemon is absent".into();
        controller.snapshot = Some(snapshot);
        assert!(controller
            .policy_unavailable_reason()
            .unwrap()
            .contains("absent"));
        assert_eq!(controller.preview_profile(), Err(SubmitError::Unsupported));
        assert_eq!(controller.apply_preview(), Err(SubmitError::Unsupported));
        assert!(!controller.busy());
    }

    #[test]
    fn apply_requires_preview_and_success_has_readback_and_updated_snapshot() {
        let mut controller = controller();
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(
            controller.apply_preview(),
            Err(SubmitError::PreviewRequired)
        );
        controller.select_profile(PowerProfile::Performance);
        controller.preview_profile().unwrap();
        finish(&mut controller);
        assert_eq!(
            controller.preview.as_ref().unwrap().requested,
            PowerProfile::Performance
        );
        controller.apply_preview().unwrap();
        assert!(controller.preview.is_none());
        finish(&mut controller);
        assert_eq!(
            controller.applied.as_ref().unwrap().confirmed,
            "performance"
        );
        assert!(controller.snapshot.is_some());
        assert_eq!(
            controller.apply_preview(),
            Err(SubmitError::PreviewRequired)
        );
    }

    #[test]
    fn permission_error_is_visible_and_preview_cannot_be_replayed() {
        let mut controller = Controller::new(FixtureBackend {
            reads: Arc::new(AtomicUsize::new(0)),
            apply_error: true,
            panic: false,
        })
        .unwrap();
        controller.refresh().unwrap();
        finish(&mut controller);
        controller.preview_profile().unwrap();
        finish(&mut controller);
        controller.apply_preview().unwrap();
        finish(&mut controller);
        assert_eq!(controller.error.as_ref().unwrap().code, "access_denied");
        assert!(controller.applied.is_none());
        assert!(controller.preview.is_none());
    }

    #[test]
    fn changed_selection_and_refresh_invalidate_plans() {
        let mut controller = controller();
        controller.refresh().unwrap();
        finish(&mut controller);
        controller.preview_profile().unwrap();
        controller.select_profile(PowerProfile::PowerSaver);
        finish(&mut controller);
        assert!(
            controller.preview.is_none(),
            "late response must not revive an old selection"
        );
        controller.preview_profile().unwrap();
        finish(&mut controller);
        assert!(controller.preview.is_some());
        controller.refresh().unwrap();
        assert!(controller.preview.is_none());
        finish(&mut controller);
    }

    #[test]
    fn worker_panic_clears_loading_and_reports_restart() {
        let mut controller = Controller::new(FixtureBackend {
            reads: Arc::new(AtomicUsize::new(0)),
            apply_error: false,
            panic: true,
        })
        .unwrap();
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(controller.error.as_ref().unwrap().code, "worker_panicked");
        let deadline = Instant::now() + Duration::from_secs(2);
        while controller.worker_available && Instant::now() < deadline {
            controller.poll();
            thread::yield_now();
        }
        assert!(!controller.worker_available);
        assert_eq!(controller.refresh(), Err(SubmitError::WorkerStopped));
    }

    #[test]
    fn closing_a_delayed_backend_does_not_wait_for_it() {
        struct Delayed {
            entered: SyncSender<()>,
            release: Receiver<()>,
        }
        impl Backend for Delayed {
            fn snapshot(&mut self) -> Snapshot {
                self.entered.send(()).unwrap();
                let _ = self.release.recv();
                fixture_snapshot()
            }
            fn catalog(&mut self) -> Vec<CatalogModel> {
                vec![]
            }
            fn plan(&mut self, _: PowerProfile) -> Result<ProfilePlan, ControlError> {
                unreachable!()
            }
            fn apply(&mut self, _: &ProfilePlan) -> Result<ApplyResult, ControlError> {
                unreachable!()
            }
        }
        let (entered, ready) = mpsc::sync_channel(1);
        let (release, delayed) = mpsc::sync_channel(1);
        let mut controller = Controller::new(Delayed {
            entered,
            release: delayed,
        })
        .unwrap();
        controller.refresh().unwrap();
        ready.recv_timeout(Duration::from_secs(2)).unwrap();
        let before = Instant::now();
        drop(controller);
        assert!(before.elapsed() < Duration::from_millis(100));
        release.send(()).unwrap();
    }

    #[test]
    fn absent_invalid_and_unsupported_values_never_become_zero() {
        let mut reading = SensorReading {
            id: "fan0".into(),
            label: "Fan".into(),
            device_id: "gpu0".into(),
            kind: "fan".into(),
            unit: "RPM".into(),
            value: None,
            source: EvidenceSource {
                backend: "fixture".into(),
                path: "none".into(),
                device_id: Some("gpu0".into()),
            },
            status: CapabilityStatus::Unavailable,
            reason: Some("missing".into()),
        };
        assert_eq!(reading_text(&reading), "不可用");
        reading.value = Some(0.0);
        assert_eq!(reading_text(&reading), "不可用");
        reading.status = CapabilityStatus::Available;
        assert_eq!(reading_text(&reading), "0.0 RPM");
        reading.value = Some(f64::NAN);
        assert_eq!(reading_text(&reading), "不可用");
    }

    #[test]
    fn display_mode_persists_but_no_hardware_plan_is_serialized() {
        let preferences = Preferences {
            display_mode: DisplayMode::Compact,
            theme: Theme::Dark,
            text_scale: 1.5,
            auto_refresh: true,
        };
        let encoded = serde_json::to_string(&preferences).unwrap();
        let decoded: Preferences = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded.display_mode, DisplayMode::Compact);
        assert_eq!(decoded.theme, Theme::Dark);
        assert_eq!(decoded.text_scale, 1.5);
        assert!(!encoded.contains("plan"));
        let mut old: Preferences = serde_json::from_str("{}").unwrap();
        old.text_scale = f32::INFINITY;
        old.sanitize();
        assert_eq!(old.text_scale, 1.0);
    }

    #[test]
    fn brightness_success_is_single_use_and_has_separate_request_and_actual_readback() {
        let mut controller = controller();
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(
            controller.selected_brightness_device.as_deref(),
            Some("fixture-display")
        );
        assert_eq!(
            controller.apply_brightness_preview(),
            Err(SubmitError::PreviewRequired)
        );
        controller.set_brightness_target(80);
        controller.preview_brightness().unwrap();
        finish(&mut controller);
        let plan = controller.brightness_preview.as_ref().unwrap();
        assert_eq!((plan.previous, plan.target), (50, 80));
        controller.apply_brightness_preview().unwrap();
        finish(&mut controller);
        let applied = controller.brightness_applied.as_ref().unwrap();
        assert_eq!(applied.confirmed, 80);
        assert_eq!(applied.actual_value, Some(80));
        assert!(controller.brightness_preview.is_none());
        assert_eq!(
            controller.apply_brightness_preview(),
            Err(SubmitError::PreviewRequired)
        );
    }

    #[test]
    fn brightness_target_changes_and_supported_levels_reject_wrong_or_late_plan() {
        let mut controller = controller();
        controller.refresh().unwrap();
        finish(&mut controller);
        controller.set_brightness_target(80);
        controller.preview_brightness().unwrap();
        controller.set_brightness_target(60);
        finish(&mut controller);
        assert!(controller.brightness_preview.is_none());
        controller.snapshot.as_mut().unwrap().brightness[0].supported_percentages =
            vec![0, 50, 100];
        assert_eq!(
            controller.preview_brightness(),
            Err(SubmitError::Unsupported)
        );
        controller.set_brightness_target(100);
        assert!(controller.brightness_unavailable_reason().is_none());
        controller.snapshot.as_mut().unwrap().brightness[0].writable = false;
        assert_eq!(
            controller.preview_brightness(),
            Err(SubmitError::Unsupported)
        );
        assert!(!controller.busy());
    }

    fn oem_control() -> OemControl {
        OemControl {
            id: "fixture-fn-lock".into(),
            kind: mechrevo_console_core::OemControlKind::FnLock,
            label: "TEST Fn Lock / 非真实硬件".into(),
            current: Some(OemValue::Boolean(false)),
            domain: OemDomain::Boolean,
            status: CapabilityStatus::Available,
            // Root-owned OEM attributes still support the reviewed helper.
            writable: false,
            source: EvidenceSource {
                backend: "fixture-only".into(),
                path: "fixture://fn-lock".into(),
                device_id: None,
            },
            binding: "fixture-identity".into(),
            readback_scope: "fixture driver request; not physical measurement".into(),
            reason: None,
        }
    }

    struct OemFixtureBackend {
        control: OemControl,
        writes: Arc<AtomicUsize>,
        reads: Arc<AtomicUsize>,
        failure: Option<&'static str>,
        apply_entered: Option<SyncSender<()>>,
        apply_release: Option<Receiver<()>>,
    }
    impl Backend for OemFixtureBackend {
        fn snapshot(&mut self) -> Snapshot {
            self.reads.fetch_add(1, Ordering::Relaxed);
            let mut snapshot = fixture_snapshot();
            snapshot.oem_controls = vec![self.control.clone()];
            snapshot
        }
        fn catalog(&mut self) -> Vec<CatalogModel> {
            vec![]
        }
        fn plan(&mut self, _: PowerProfile) -> Result<ProfilePlan, ControlError> {
            unreachable!("OEM fixture never changes system power policy")
        }
        fn apply(&mut self, _: &ProfilePlan) -> Result<ApplyResult, ControlError> {
            unreachable!("OEM fixture never writes system power policy")
        }
        fn plan_oem(&mut self, id: &str, target: OemValue) -> Result<OemPlan, ControlError> {
            assert_eq!(id, self.control.id);
            assert!(oem_value_in_domain(&self.control.domain, &target));
            Ok(OemPlan {
                control_id: id.into(),
                kind: self.control.kind,
                label: self.control.label.clone(),
                previous: self.control.current.clone().unwrap(),
                target,
                domain: self.control.domain.clone(),
                source: self.control.source.clone(),
                binding: self.control.binding.clone(),
                readback_scope: self.control.readback_scope.clone(),
                requires_privilege: true,
                companion_brightness: None,
            })
        }
        fn apply_oem(&mut self, plan: &OemPlan) -> Result<OemApplyResult, ControlError> {
            if let Some(entered) = self.apply_entered.take() {
                entered.send(()).unwrap();
            }
            if let Some(release) = self.apply_release.take() {
                release.recv().unwrap();
            }
            self.writes.fetch_add(1, Ordering::Relaxed);
            if let Some(code) = self.failure {
                let mut error = ControlError::new(code, "fixture OEM operation failed");
                error.details =
                    vec!["fixture rollback/readback evidence must remain visible".into()];
                return Err(error);
            }
            self.control.current = Some(plan.target.clone());
            Ok(OemApplyResult {
                control_id: plan.control_id.clone(),
                kind: plan.kind,
                previous: plan.previous.clone(),
                confirmed: plan.target.clone(),
                source: plan.source.clone(),
                readback_scope: plan.readback_scope.clone(),
            })
        }
    }
    fn oem_controller(
        failure: Option<&'static str>,
    ) -> (Controller, Arc<AtomicUsize>, Arc<AtomicUsize>) {
        let writes = Arc::new(AtomicUsize::new(0));
        let reads = Arc::new(AtomicUsize::new(0));
        let controller = Controller::new(OemFixtureBackend {
            control: oem_control(),
            writes: writes.clone(),
            reads: reads.clone(),
            failure,
            apply_entered: None,
            apply_release: None,
        })
        .unwrap();
        (controller, writes, reads)
    }
    pub(crate) fn prepare_oem(controller: &mut Controller) {
        controller.refresh().unwrap();
        finish(controller);
        controller.select_oem_control("fixture-fn-lock");
        controller.set_oem_target(OemValue::Boolean(true));
    }
    pub(crate) fn gated_oem_controller(
        failure: Option<&'static str>,
    ) -> (Controller, Receiver<()>, SyncSender<()>) {
        let (entered, ready) = mpsc::sync_channel(1);
        let (release, delayed) = mpsc::sync_channel(1);
        let controller = Controller::new(OemFixtureBackend {
            control: oem_control(),
            writes: Arc::new(AtomicUsize::new(0)),
            reads: Arc::new(AtomicUsize::new(0)),
            failure,
            apply_entered: Some(entered),
            apply_release: Some(delayed),
        })
        .unwrap();
        (controller, ready, release)
    }

    #[test]
    fn oem_success_requires_single_use_preview_and_refreshes_actual_snapshot() {
        let (mut controller, writes, reads) = oem_controller(None);
        prepare_oem(&mut controller);
        assert_eq!(
            controller.apply_oem_preview(),
            Err(SubmitError::PreviewRequired)
        );
        controller.preview_oem().unwrap();
        finish(&mut controller);
        assert_eq!(
            writes.load(Ordering::Relaxed),
            0,
            "preview must not authorize or write"
        );
        assert!(controller.oem_preview.as_ref().unwrap().requires_privilege);
        assert!(controller.has_pending_preview());
        controller.apply_oem_preview().unwrap();
        assert!(controller.write_in_progress());
        assert!(!controller.has_pending_preview());
        finish(&mut controller);
        assert_eq!(writes.load(Ordering::Relaxed), 1);
        assert_eq!(reads.load(Ordering::Relaxed), 2);
        assert_eq!(
            controller.oem_applied.as_ref().unwrap().confirmed,
            OemValue::Boolean(true)
        );
        assert_eq!(
            controller.selected_oem().unwrap().current,
            Some(OemValue::Boolean(true))
        );
        assert!(!controller.write_in_progress());
        assert_eq!(
            controller.apply_oem_preview(),
            Err(SubmitError::PreviewRequired)
        );
    }

    #[test]
    fn oem_missing_unavailable_unknown_and_out_of_domain_never_reach_worker() {
        let (mut controller, writes, _) = oem_controller(None);
        assert_eq!(controller.preview_oem(), Err(SubmitError::Unsupported));
        prepare_oem(&mut controller);
        for status in [CapabilityStatus::Unavailable, CapabilityStatus::Unsupported] {
            controller.snapshot.as_mut().unwrap().oem_controls[0].status = status;
            assert_eq!(controller.preview_oem(), Err(SubmitError::Unsupported));
        }
        let control = &mut controller.snapshot.as_mut().unwrap().oem_controls[0];
        control.status = CapabilityStatus::Available;
        control.current = None;
        assert_eq!(controller.preview_oem(), Err(SubmitError::Unsupported));
        controller.snapshot.as_mut().unwrap().oem_controls[0].current =
            Some(OemValue::Boolean(false));
        for (domain, target) in [
            (OemDomain::Boolean, OemValue::Level(1)),
            (
                OemDomain::Choices(vec!["balanced".into()]),
                OemValue::Choice("made-up".into()),
            ),
            (OemDomain::Level { max: 3 }, OemValue::Level(4)),
            (OemDomain::Rgb, OemValue::Boolean(true)),
        ] {
            let current = match &domain {
                OemDomain::Boolean => OemValue::Boolean(false),
                OemDomain::Choices(choices) => OemValue::Choice(choices[0].clone()),
                OemDomain::Level { .. } => OemValue::Level(0),
                OemDomain::Rgb => OemValue::Rgb([0, 0, 0]),
            };
            controller.snapshot.as_mut().unwrap().oem_controls[0].current = Some(current);
            controller.snapshot.as_mut().unwrap().oem_controls[0].domain = domain;
            controller.set_oem_target(target);
            assert_eq!(controller.preview_oem(), Err(SubmitError::Unsupported));
        }
        assert_eq!(writes.load(Ordering::Relaxed), 0);
        assert!(!controller.busy());
    }

    #[test]
    fn oem_default_backend_reports_unsupported_without_manufactured_success() {
        let mut controller = controller();
        let mut snapshot = fixture_snapshot();
        snapshot.oem_controls = vec![oem_control()];
        controller.snapshot = Some(snapshot);
        controller.select_oem_control("fixture-fn-lock");
        controller.set_oem_target(OemValue::Boolean(true));
        controller.preview_oem().unwrap();
        finish(&mut controller);
        assert_eq!(controller.error.as_ref().unwrap().code, "oem_unavailable");
        assert!(controller.oem_preview.is_none());
        assert!(controller.oem_applied.is_none());
    }

    #[test]
    fn oem_failed_apply_preserves_recovery_details_and_cannot_replay_preview() {
        let (mut controller, writes, reads) = oem_controller(Some("oem_readback_mismatch"));
        prepare_oem(&mut controller);
        controller.preview_oem().unwrap();
        finish(&mut controller);
        controller.apply_oem_preview().unwrap();
        finish(&mut controller);
        let error = controller.error.as_ref().unwrap();
        assert_eq!(error.code, "oem_readback_mismatch");
        assert!(error.details[0].contains("rollback/readback"));
        assert_eq!(writes.load(Ordering::Relaxed), 1);
        assert_eq!(
            reads.load(Ordering::Relaxed),
            1,
            "failed apply is not a confirmed snapshot"
        );
        assert!(controller.oem_applied.is_none());
        assert_eq!(
            controller.apply_oem_preview(),
            Err(SubmitError::PreviewRequired)
        );
    }

    #[test]
    fn oem_late_a_to_b_to_a_and_cross_control_results_cannot_revive_old_plan() {
        let (mut controller, writes, _) = oem_controller(None);
        prepare_oem(&mut controller);
        controller.preview_oem().unwrap();
        controller.set_oem_target(OemValue::Boolean(false));
        controller.set_oem_target(OemValue::Boolean(true));
        finish(&mut controller);
        assert!(
            controller.oem_preview.is_none(),
            "matching value does not cancel request revisions"
        );
        controller.preview_oem().unwrap();
        controller.select_oem_control("different-control");
        controller.select_oem_control("fixture-fn-lock");
        controller.set_oem_target(OemValue::Boolean(true));
        finish(&mut controller);
        assert!(controller.oem_preview.is_none());
        assert_eq!(writes.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn oem_other_requests_refresh_and_changed_binding_invalidate_preview() {
        let (mut controller, writes, _) = oem_controller(None);
        prepare_oem(&mut controller);
        controller.preview_oem().unwrap();
        finish(&mut controller);
        controller.select_profile(PowerProfile::Performance);
        assert!(controller.oem_preview.is_none());
        controller.preview_oem().unwrap();
        finish(&mut controller);
        controller.set_brightness_target(42);
        assert!(controller.oem_preview.is_none());
        controller.preview_oem().unwrap();
        finish(&mut controller);
        controller.snapshot.as_mut().unwrap().oem_controls[0].binding = "replaced-device".into();
        assert_eq!(
            controller.apply_oem_preview(),
            Err(SubmitError::PreviewRequired)
        );
        assert!(controller.oem_preview.is_none());
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(writes.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn oem_same_id_recovery_initializes_absent_target_without_overwriting_user_choice() {
        let (mut controller, _, _) = oem_controller(None);
        let mut snapshot = fixture_snapshot();
        let mut control = oem_control();
        control.status = CapabilityStatus::Unavailable;
        control.current = None;
        snapshot.oem_controls = vec![control];
        controller.snapshot = Some(snapshot);
        controller.select_oem_control("fixture-fn-lock");
        assert!(controller.requested_oem_value.is_none());
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(
            controller.requested_oem_value,
            Some(OemValue::Boolean(false))
        );
        controller.set_oem_target(OemValue::Boolean(true));
        controller.refresh().unwrap();
        finish(&mut controller);
        assert_eq!(
            controller.requested_oem_value,
            Some(OemValue::Boolean(true))
        );
        controller.preview_oem().unwrap();
        finish(&mut controller);
        assert!(controller.oem_preview.is_some());
    }

    #[test]
    fn oem_fresh_preview_of_changed_device_state_explains_required_refresh() {
        let (mut controller, writes, _) = oem_controller(None);
        prepare_oem(&mut controller);
        controller.snapshot.as_mut().unwrap().oem_controls[0].current =
            Some(OemValue::Boolean(true));
        controller.preview_oem().unwrap();
        finish(&mut controller);
        assert!(controller.oem_preview.is_none());
        assert_eq!(controller.error.as_ref().unwrap().code, "oem_preview_stale");
        assert_eq!(writes.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn oem_busy_write_owns_single_worker_until_result_finishes() {
        let (mut controller, ready, release) = gated_oem_controller(None);
        prepare_oem(&mut controller);
        controller.preview_oem().unwrap();
        finish(&mut controller);
        controller.apply_oem_preview().unwrap();
        ready.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(controller.busy() && controller.write_in_progress());
        assert_eq!(controller.refresh(), Err(SubmitError::Busy));
        assert_eq!(controller.preview_oem(), Err(SubmitError::Busy));
        assert!(
            controller.write_in_progress(),
            "native close must remain deferred for OEM writes"
        );
        release.send(()).unwrap();
        finish(&mut controller);
        assert!(!controller.write_in_progress());
    }

    #[test]
    fn oem_unknown_helper_liveness_keeps_write_and_close_interlock() {
        let (mut controller, _, _) = oem_controller(Some("oem_helper_liveness_unknown"));
        prepare_oem(&mut controller);
        controller.preview_oem().unwrap();
        finish(&mut controller);
        controller.apply_oem_preview().unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        while controller.error.is_none() && Instant::now() < deadline {
            controller.poll();
            thread::yield_now();
        }
        assert_eq!(
            controller.error.as_ref().unwrap().code,
            "oem_helper_liveness_unknown"
        );
        assert!(controller.busy() && controller.write_in_progress());
        assert_eq!(controller.refresh(), Err(SubmitError::Busy));
        assert!(controller.oem_preview.is_none());
        assert!(controller.oem_applied.is_none());
    }

    #[test]
    fn brightness_readback_failure_keeps_the_error_and_invalidates_the_plan() {
        let mut controller = Controller::new(FixtureBackend {
            reads: Arc::new(AtomicUsize::new(0)),
            apply_error: true,
            panic: false,
        })
        .unwrap();
        controller.refresh().unwrap();
        finish(&mut controller);
        controller.preview_brightness().unwrap();
        finish(&mut controller);
        controller.apply_brightness_preview().unwrap();
        finish(&mut controller);
        assert_eq!(
            controller.error.as_ref().unwrap().code,
            "brightness_readback_mismatch"
        );
        assert!(controller.brightness_applied.is_none());
        assert!(controller.brightness_preview.is_none());
        assert_eq!(
            controller.apply_brightness_preview(),
            Err(SubmitError::PreviewRequired)
        );
    }

    #[test]
    fn brightness_target_starts_from_requested_value_when_actual_lags() {
        let mut controller = controller();
        let mut snapshot = fixture_snapshot();
        let device = &mut snapshot.brightness[0];
        device.control_value = Some(250);
        device.actual_value = Some(200);
        device.current_percent = Some(20.0);
        device.maximum = Some(1000);
        controller.snapshot = Some(snapshot);
        controller.select_brightness_device("fixture-display");
        assert_eq!(controller.requested_brightness, 25);
    }

    #[test]
    fn idle_worker_exits_after_controller_closes() {
        struct Idle {
            stopped: SyncSender<()>,
        }
        impl Drop for Idle {
            fn drop(&mut self) {
                let _ = self.stopped.send(());
            }
        }
        impl Backend for Idle {
            fn snapshot(&mut self) -> Snapshot {
                fixture_snapshot()
            }
            fn catalog(&mut self) -> Vec<CatalogModel> {
                vec![]
            }
            fn plan(&mut self, _: PowerProfile) -> Result<ProfilePlan, ControlError> {
                unreachable!()
            }
            fn apply(&mut self, _: &ProfilePlan) -> Result<ApplyResult, ControlError> {
                unreachable!()
            }
        }
        let (stopped, done) = mpsc::sync_channel(1);
        let controller = Controller::new(Idle { stopped }).unwrap();
        drop(controller);
        done.recv_timeout(Duration::from_secs(2))
            .expect("idle worker should release the backend after its sender closes");
    }
}
