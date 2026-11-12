//! Subprocess capture for inspection and non-cancellable control helpers.

use std::io::Read;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, SyncSender};
use std::time::{Duration, Instant};

#[derive(Debug)]
pub struct CommandOutput {
    pub stdout: String,
    pub stderr: String,
    pub status: i32,
}

enum PipeEvent {
    Data(bool, Vec<u8>),
    Closed,
    Failed(String),
}

fn pipe_events(mut pipe: impl Read, stdout: bool, sender: SyncSender<PipeEvent>) {
    let mut buffer = [0; 8192];
    loop {
        match pipe.read(&mut buffer) {
            Ok(0) => {
                let _ = sender.send(PipeEvent::Closed);
                break;
            }
            Ok(length) => {
                if sender
                    .send(PipeEvent::Data(stdout, buffer[..length].to_vec()))
                    .is_err()
                {
                    break;
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => {
                let _ = sender.send(PipeEvent::Failed(error.to_string()));
                break;
            }
        }
    }
}

fn read_pipe(pipe: impl Read + Send + 'static, stdout: bool, sender: SyncSender<PipeEvent>) {
    std::thread::spawn(move || pipe_events(pipe, stdout, sender));
}

fn terminate(child: &mut Child) {
    #[cfg(unix)]
    {
        // process_group(0) gives this helper its own group. Killing the group also
        // closes pipes inherited by grandchildren after the group leader exits.
        unsafe extern "C" {
            fn kill(pid: i32, signal: i32) -> i32;
        }
        if let Ok(pid) = i32::try_from(child.id()) {
            // SAFETY: kill takes only integer values; a negative PID addresses
            // the process group created for this child, and 9 is SIGKILL.
            unsafe {
                kill(-pid, 9);
            }
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn failure(code: &str, message: String, stdout: &[u8], stderr: &[u8]) -> crate::ControlError {
    let mut error = crate::ControlError::new(code, message);
    if !stdout.is_empty() {
        error
            .details
            .push(format!("stdout: {}", String::from_utf8_lossy(stdout)));
    }
    if !stderr.is_empty() {
        error
            .details
            .push(format!("stderr: {}", String::from_utf8_lossy(stderr)));
    }
    error
}

/// Run a control helper synchronously without claiming that it can be cancelled.
///
/// A privileged helper may no longer be signalable by its unprivileged caller.
/// This function never kills it or imposes a completion deadline. Call it from a
/// background transaction worker, and keep writes blocked until it returns.
/// The helper must not delegate control writes to descendants: waiting for this
/// process does not establish the lifetime of an independently running worker.
///
/// Both output pipes are drained even after the shared capture limit or a pipe
/// error. A capture failure is reported only after the child has actually been
/// reaped. Nonzero exits are returned to the caller for protocol/authentication
/// interpretation; an exit by itself does not establish the hardware outcome.
pub fn run_control_helper(
    program: &str,
    args: &[&str],
    output_limit: usize,
) -> Result<CommandOutput, crate::ControlError> {
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().map_err(|error| {
        crate::ControlError::new(
            "command_unavailable",
            format!("Cannot start {program}: {error}"),
        )
    })?;
    let (sender, receiver) = mpsc::sync_channel(4);
    let mut readers = Vec::new();
    let mut capture_failure = None;
    let stdout_pipe = child.stdout.take().expect("stdout was piped");
    let stdout_sender = sender.clone();
    match std::thread::Builder::new()
        .name("control-helper-stdout".into())
        .spawn(move || pipe_events(stdout_pipe, true, stdout_sender))
    {
        Ok(reader) => readers.push(reader),
        Err(error) => capture_failure = Some(format!("Cannot capture helper stdout: {error}")),
    }
    let stderr_pipe = child.stderr.take().expect("stderr was piped");
    match std::thread::Builder::new()
        .name("control-helper-stderr".into())
        .spawn(move || pipe_events(stderr_pipe, false, sender))
    {
        Ok(reader) => readers.push(reader),
        Err(error) => {
            capture_failure.get_or_insert_with(|| format!("Cannot capture helper stderr: {error}"));
        }
    }

    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    let mut closed = 0;
    for event in receiver {
        match event {
            PipeEvent::Data(is_stdout, bytes) => {
                let available = output_limit.saturating_sub(stdout.len() + stderr.len());
                let destination = if is_stdout { &mut stdout } else { &mut stderr };
                destination.extend_from_slice(&bytes[..bytes.len().min(available)]);
                if bytes.len() > available && capture_failure.is_none() {
                    capture_failure = Some(format!(
                        "{program} exceeded its {output_limit} byte capture limit"
                    ));
                }
                // Continue receiving and discard excess bytes. Returning here
                // could leave a privileged write running or block its output.
            }
            PipeEvent::Closed => closed += 1,
            PipeEvent::Failed(error) => {
                capture_failure
                    .get_or_insert_with(|| format!("Cannot read helper output: {error}"));
            }
        }
    }

    let status = child.wait().map_err(|error| {
        failure(
            "oem_helper_liveness_unknown",
            format!("Cannot confirm that {program} exited: {error}; control writes may still be pending"),
            &stdout,
            &stderr,
        )
    })?;
    for reader in readers {
        if reader.join().is_err() {
            capture_failure.get_or_insert_with(|| "Helper output reader panicked".into());
        }
    }
    if closed != 2 {
        capture_failure.get_or_insert_with(|| "Helper output did not reach both pipe EOFs".into());
    }
    if std::str::from_utf8(&stdout).is_err() || std::str::from_utf8(&stderr).is_err() {
        capture_failure.get_or_insert_with(|| "Helper output was not valid UTF-8".into());
    }
    let code = status.code().unwrap_or(-1);
    if let Some(message) = capture_failure {
        return Err(failure(
            "oem_outcome_unknown",
            format!(
                "{message}; helper was reaped with exit status {code}, hardware outcome is unknown"
            ),
            &stdout,
            &stderr,
        ));
    }
    Ok(CommandOutput {
        stdout: String::from_utf8(stdout).expect("UTF-8 was checked"),
        stderr: String::from_utf8(stderr).expect("UTF-8 was checked"),
        status: code,
    })
}

/// Execute a program directly, bounding wall time and the combined raw output.
///
/// Callers provide arguments separately: no shell is invoked or interpolated.
/// A nonzero exit is an error whose details retain the bounded helper output.
pub fn run_command(
    program: &str,
    args: &[&str],
    timeout: Duration,
    output_limit: usize,
) -> Result<CommandOutput, crate::ControlError> {
    let started = Instant::now();
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().map_err(|error| {
        crate::ControlError::new(
            "command_unavailable",
            format!("Cannot start {program}: {error}"),
        )
    })?;
    // A small bounded channel prevents unbounded allocations even when a helper
    // continuously fills both pipes. The receiver enforces the combined limit.
    let (sender, receiver) = mpsc::sync_channel(4);
    read_pipe(
        child.stdout.take().expect("stdout was piped"),
        true,
        sender.clone(),
    );
    read_pipe(
        child.stderr.take().expect("stderr was piped"),
        false,
        sender,
    );
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    let mut closed = 0;
    let mut exit_status = None;
    loop {
        if exit_status.is_none() {
            match child.try_wait() {
                Ok(status) => exit_status = status,
                Err(error) => {
                    terminate(&mut child);
                    return Err(failure(
                        "command_failed",
                        format!("Cannot wait for {program}: {error}"),
                        &stdout,
                        &stderr,
                    ));
                }
            }
        }
        if let Some(status) = exit_status {
            if closed == 2 {
                let code = status.code().unwrap_or(-1);
                if !status.success() {
                    return Err(failure(
                        "command_failed",
                        format!("{program} exited with status {code}"),
                        &stdout,
                        &stderr,
                    ));
                }
                return Ok(CommandOutput {
                    stdout: String::from_utf8_lossy(&stdout).into_owned(),
                    stderr: String::from_utf8_lossy(&stderr).into_owned(),
                    status: code,
                });
            }
        }
        if started.elapsed() >= timeout {
            terminate(&mut child);
            return Err(failure(
                "command_timeout",
                format!("{program} exceeded its {} ms timeout", timeout.as_millis()),
                &stdout,
                &stderr,
            ));
        }
        let wait = timeout
            .saturating_sub(started.elapsed())
            .min(Duration::from_millis(10));
        match receiver.recv_timeout(wait) {
            Ok(PipeEvent::Data(is_stdout, bytes)) => {
                let available = output_limit.saturating_sub(stdout.len() + stderr.len());
                let destination = if is_stdout { &mut stdout } else { &mut stderr };
                destination.extend_from_slice(&bytes[..bytes.len().min(available)]);
                if bytes.len() > available {
                    terminate(&mut child);
                    return Err(failure(
                        "command_output_limit",
                        format!("{program} exceeded its {output_limit} byte output limit"),
                        &stdout,
                        &stderr,
                    ));
                }
            }
            Ok(PipeEvent::Closed) => closed += 1,
            Ok(PipeEvent::Failed(error)) => {
                terminate(&mut child);
                return Err(failure(
                    "command_failed",
                    format!("Cannot read output from {program}: {error}"),
                    &stdout,
                    &stderr,
                ));
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                // Both reader threads have finished; an exit status can arrive
                // on the next iteration if pipe closure preceded process exit.
                closed = 2;
                std::thread::sleep(wait);
            }
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    struct ControlFixture {
        directory: std::path::PathBuf,
    }

    impl ControlFixture {
        fn new() -> Self {
            use std::sync::atomic::{AtomicU64, Ordering};
            static NEXT: AtomicU64 = AtomicU64::new(0);
            let root = std::env::var_os("TMPDIR")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| {
                    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                        .join("../../.local-tests/oem-controls/command")
                });
            std::fs::create_dir_all(&root).unwrap();
            let directory = root.join(format!(
                "control-helper-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std::fs::create_dir(&directory).unwrap();
            Self { directory }
        }

        fn run(&self, body: &str, limit: usize) -> Result<CommandOutput, crate::ControlError> {
            run_control_helper(
                "/bin/sh",
                &[
                    "-c",
                    body,
                    "control-helper-test",
                    self.directory.to_str().unwrap(),
                ],
                limit,
            )
        }

        fn assert_reaped(&self) {
            #[cfg(target_os = "linux")]
            {
                let pid = std::fs::read_to_string(self.directory.join("pid")).unwrap();
                assert!(
                    !std::path::Path::new("/proc").join(pid).exists(),
                    "control helper was not reaped"
                );
            }
        }
    }

    impl Drop for ControlFixture {
        fn drop(&mut self) {
            // Every fixture has a finite script. On a failed assertion, give it
            // time to finish without pretending that killing this same-UID
            // process would establish cancellation of a privileged helper.
            #[cfg(target_os = "linux")]
            if let Ok(pid) = std::fs::read_to_string(self.directory.join("pid")) {
                let stat = std::path::Path::new("/proc").join(pid).join("stat");
                for _ in 0..300 {
                    match std::fs::read_to_string(&stat) {
                        Ok(value)
                            if !value
                                .rsplit_once(") ")
                                .is_some_and(|(_, tail)| tail.starts_with('Z')) =>
                        {
                            std::thread::sleep(Duration::from_millis(10));
                        }
                        _ => break,
                    }
                }
            }
            let _ = std::fs::remove_dir_all(&self.directory);
        }
    }

    #[test]
    fn control_helper_waits_beyond_short_deadline_and_pipe_eof() {
        let fixture = ControlFixture::new();
        let started = Instant::now();
        let output = fixture
            .run(
                "printf '%s' \"$$\" > \"$1/pid\"; exec 1>&- 2>&-; sleep 0.15; printf done > \"$1/done\"",
                0,
            )
            .unwrap();
        assert!(started.elapsed() >= Duration::from_millis(100));
        assert_eq!(
            std::fs::read(fixture.directory.join("done")).unwrap(),
            b"done"
        );
        assert_eq!(output.status, 0);
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
        fixture.assert_reaped();
    }

    #[test]
    fn control_helper_overflow_drains_both_streams_and_waits_for_sentinel() {
        let fixture = ControlFixture::new();
        let started = Instant::now();
        let error = fixture
            .run(
                "printf '%s' \"$$\" > \"$1/pid\"; i=0; while [ \"$i\" -lt 4096 ]; do printf 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef; printf 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef >&2; i=$((i+1)); done; exec 1>&- 2>&-; sleep 0.15; printf done > \"$1/done\"",
                8,
            )
            .unwrap_err();
        assert_eq!(error.code, "oem_outcome_unknown");
        assert!(started.elapsed() >= Duration::from_millis(100));
        assert_eq!(
            std::fs::read(fixture.directory.join("done")).unwrap(),
            b"done"
        );
        let captured: usize = error
            .details
            .iter()
            .filter_map(|detail| {
                detail
                    .strip_prefix("stdout: ")
                    .or_else(|| detail.strip_prefix("stderr: "))
            })
            .map(str::len)
            .sum();
        assert_eq!(captured, 8);
        fixture.assert_reaped();
    }

    #[test]
    fn control_helper_returns_nonzero_for_protocol_interpretation() {
        let fixture = ControlFixture::new();
        let output = fixture
            .run(
                "printf '%s' \"$$\" > \"$1/pid\"; printf terminal; printf denied >&2; exit 127",
                14,
            )
            .unwrap();
        assert_eq!(output.status, 127);
        assert_eq!(output.stdout, "terminal");
        assert_eq!(output.stderr, "denied");
        fixture.assert_reaped();
    }

    #[test]
    fn control_helper_returns_signal_exit_without_claiming_cancellation() {
        let fixture = ControlFixture::new();
        let output = fixture
            .run(
                "printf '%s' \"$$\" > \"$1/pid\"; printf before-crash; kill -TERM \"$$\"",
                12,
            )
            .unwrap();
        assert_eq!(output.status, -1);
        assert_eq!(output.stdout, "before-crash");
        fixture.assert_reaped();
    }

    #[test]
    fn control_helper_capture_limit_is_shared_and_inclusive() {
        let fixture = ControlFixture::new();
        let output = fixture
            .run(
                "printf '%s' \"$$\" > \"$1/pid\"; printf 1234; printf 5678 >&2",
                8,
            )
            .unwrap();
        assert_eq!(output.stdout, "1234");
        assert_eq!(output.stderr, "5678");
        assert_eq!(output.status, 0);
        fixture.assert_reaped();
    }

    #[test]
    fn control_helper_invalid_utf8_is_unknown_after_reaping() {
        let fixture = ControlFixture::new();
        let error = fixture
            .run("printf '%s' \"$$\" > \"$1/pid\"; printf '\\377'", 8)
            .unwrap_err();
        assert_eq!(error.code, "oem_outcome_unknown");
        assert!(error.message.contains("UTF-8"));
        fixture.assert_reaped();
    }

    #[test]
    fn control_helper_missing_program_did_not_start() {
        let error = run_control_helper("/no/such/mechrevo-control-helper", &[], 128).unwrap_err();
        assert_eq!(error.code, "command_unavailable");
    }

    #[test]
    fn captures_both_streams_and_exact_boundary() {
        let output = run_command(
            "/bin/sh",
            &["-c", "printf 1234; printf 5678 >&2"],
            Duration::from_secs(2),
            8,
        )
        .unwrap();
        assert_eq!(output.stdout, "1234");
        assert_eq!(output.stderr, "5678");
        assert_eq!(output.status, 0);
    }

    #[test]
    fn arguments_are_literal() {
        let output = run_command(
            "/usr/bin/printf",
            &["%s", "a; $(printf injected)"],
            Duration::from_secs(2),
            128,
        )
        .unwrap();
        assert_eq!(output.stdout, "a; $(printf injected)");
    }

    #[test]
    fn missing_program_has_distinct_error() {
        let error =
            run_command("/no/such/mechrevo-helper", &[], Duration::from_secs(1), 128).unwrap_err();
        assert_eq!(error.code, "command_unavailable");
    }

    #[test]
    fn nonzero_retains_stderr() {
        let error = run_command(
            "/bin/sh",
            &["-c", "printf denied >&2; exit 7"],
            Duration::from_secs(2),
            128,
        )
        .unwrap_err();
        assert_eq!(error.code, "command_failed");
        assert!(error
            .details
            .iter()
            .any(|detail| detail == "stderr: denied"));
    }

    #[test]
    fn output_limit_is_shared_across_streams() {
        let error = run_command(
            "/bin/sh",
            &["-c", "printf 1234; printf 56789 >&2"],
            Duration::from_secs(2),
            8,
        )
        .unwrap_err();
        assert_eq!(error.code, "command_output_limit");
        let captured: usize = error
            .details
            .iter()
            .map(|detail| detail.split_once(": ").unwrap().1.len())
            .sum();
        assert_eq!(captured, 8);
    }

    #[test]
    fn large_stderr_does_not_block_on_stdout() {
        let started = Instant::now();
        let error = run_command(
            "/bin/sh",
            &["-c", "while :; do printf 1234567890 >&2; done"],
            Duration::from_secs(3),
            64,
        )
        .unwrap_err();
        assert_eq!(error.code, "command_output_limit");
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn zero_limit_allows_empty_output() {
        let output = run_command("/bin/sh", &["-c", "exit 0"], Duration::from_secs(2), 0).unwrap();
        assert_eq!(output.stdout, "");
        let error =
            run_command("/bin/sh", &["-c", "printf x"], Duration::from_secs(2), 0).unwrap_err();
        assert_eq!(error.code, "command_output_limit");
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn timeout_kills_descendant_after_leader_has_exited() {
        let started = Instant::now();
        let error = run_command(
            "/bin/sh",
            &["-c", "sleep 60 & printf '%s' \"$!\"; exit 0"],
            Duration::from_millis(150),
            128,
        )
        .unwrap_err();
        assert_eq!(error.code, "command_timeout");
        assert!(started.elapsed() < Duration::from_secs(2));
        let pid: u32 = error
            .details
            .iter()
            .find_map(|detail| detail.strip_prefix("stdout: "))
            .unwrap()
            .parse()
            .unwrap();
        // Reparented children can briefly remain zombies until PID 1 reaps them.
        // A zombie cannot run or keep either output pipe open.
        for _ in 0..100 {
            let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"));
            if stat.as_ref().is_err() || stat.unwrap().split_once(") ").unwrap().1.starts_with('Z')
            {
                return;
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        panic!("helper descendant {pid} survived timeout");
    }
}
