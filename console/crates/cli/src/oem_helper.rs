//! This installed executable has one operation. It never accepts a shell,
//! arbitrary file, alternate sysfs root, plugin, environment backend or daemon.
use mechrevo_console_core::privilege::{self, HelperOutcome};
use std::io::Write;

fn main() {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let result = if args.len() == 2 && args[0] == "--apply-plan" {
        args[1]
            .to_str()
            .ok_or("The request must be UTF-8")
            .map_err(String::from)
            .and_then(|input| privilege::parse_request(input).map_err(|e| e.to_string()))
    } else {
        Err("Expected exactly --apply-plan JSON".into())
    };
    let request = match result {
        Ok(request) => request,
        Err(error) => {
            let _ = writeln!(
                std::io::stderr().lock(),
                "{}",
                serde_json::json!({"error":error,"phase":"rejected_before_write"})
            );
            std::process::exit(2);
        }
    };
    let reply = privilege::execute_request(request);
    let exit = if reply.outcome == HelperOutcome::AppliedVerified {
        0
    } else {
        2
    };
    // A broken output pipe must never initiate a second hardware transaction.
    let mut stdout = std::io::stdout().lock();
    let write = serde_json::to_writer(&mut stdout, &reply)
        .map_err(std::io::Error::other)
        .and_then(|()| stdout.write_all(b"\n"))
        .and_then(|()| stdout.flush());
    if write.is_err() {
        std::process::exit(3);
    }
    std::process::exit(exit);
}
