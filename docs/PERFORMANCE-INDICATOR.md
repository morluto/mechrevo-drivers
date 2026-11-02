# GM6PX0X performance button and indicator investigation

Scope: MECHREVO Kuangshi16Pro Series GM6PX0X, board GM6PX0X,
BIOS N.1.09MRO07. Other models and firmware are unqualified.

## Confirmed input and profile defects

The Uniwill mode event 0xB0 generates Meta + Alt + F6 on the TUXEDO input
device. Combining a buffered Python input stream with select() can leave F6
in the userspace buffer after the file descriptor stops reporting readiness.
A real pipe carrying the complete six-event chord reproduces the problem.
The listener now reads without buffering and reports disconnects/short events.

TCC's SetTempProfileById acknowledges a queued request. Its true return value
does not prove the selected profile is active. The control tool checks the
boolean reply and waits for the requested active-profile ID before requesting
the indicator or announcing completion. This is profile identity confirmation,
not proof of CPU power limits, thermal performance, or physical illumination.

## Duplicate compositor binding (2026-11-02)

On this GM6PX0X session, Hyprland also bound `Super+Alt+F6` to
`mechrevo-control mode cycle --notify` while the evdev daemon was active.
Injecting one complete chord into the existing TUXEDO evdev node produced two
`SetTempProfileById` calls: Turbo → Office → Gaming. The write descriptor was
closed after each bounded test; no physical button press was claimed.

The local `/home/lightjunction/.config/hypr/bindings.lua` now explicitly unbinds
that chord; the daemon remains its sole owner. After `hyprctl reload`, no F6
binding or config error remained. Three separate injected presses each produced
exactly one D-Bus request, completing Turbo → Office → Gaming → Turbo with EC
readbacks `0xa0`, `0x00`, `0x10`. Each selection stayed unchanged during its
12-second observation. This confirms the software event path, not physical
illumination or resume behavior.

Keep compositor shortcuts separate from hardware chords. Do not add a global
cooldown to hide duplicate consumers: it would also discard intentional rapid
presses. Private preimages, event traces and rollback instructions are in
`/home/lightjunction/Backups/mechrevo-drivers/light/2026-11-02-hotkey-repair-105338/`.

## OEM evidence from leanrea analysis

The preserved OEM 5.17.51.34 service is a protected .NET PE. Analysis uses the
previously restored CIL bodies rather than the exception stubs produced by an
ordinary decompiler. No OEM code was executed.

Original service SHA256:
`a2b7d81ecf5c1dbdfc19738f17ba5e01e884d1b3688beb668858727307e2a318`.

For the observed project 0x10 and RAM-fan-1p5 capability, the selected manager
is MyFanManager_RamFan1p5. The mode-button path is:

`WMIHandleEvent 06001220` (0xB0) → `MyFanCtrl.ModeSwitchChanged 06000ed3` →
`RamFan1p5.ModeSwitchChanged 060016d9` → worker → `SetUserProfile 06001700` →
`SetFanMode 06001705`.

SetFanMode body SHA256:
`528db385738f28f747c19302463802dcac8a57514cc45140bab3d341e1395ab3`.

| Selected OEM mode | 0x0751 without FanBoost | 0x0727 bit 6 | 0x0726 bit 7 |
| --- | --- | --- | --- |
| Office (0) | 0xa0 | Clear | Clear |
| Gaming (1) | 0x00 | Clear | Clear |
| Turbo (2) | 0x10 | Clear | Clear |
| Custom (3) | 0x00; 0x10 with overclock enabled | Set | Set |

FanBoost adds bit 6 in 0x0751. The 0x0727 and 0x0726 operations preserve the
other bits. CustomerModeLightOn/Off are real calls on this selected manager;
the TUXEDO model whitelist alone cannot disprove their OEM applicability.
The physical meaning on this machine still needs observation.

The selected manager's `ModeSwitchChanged` (060016d9) has an
Office → Gaming → Turbo → Office branch for AppType 3 or CustomId 0x27.
Other OEM branches can include Custom; this does not establish one universal
cycle for every machine. The Linux physical-button cycle uses the three
ordinary modes. Gaming Quiet remains separately selectable and shares Gaming's
hardware mode; Fan Boost shares Turbo's hardware mode. Neither is presented as
an additional ordinary indicator state.

The ACPI table also reads 0x0751 bit 4 (TBME) and bit 7 (UFME) in GPU/power
policy. Consequently W_UW_MODE is a hardware-mode operation, not an independent
LED-brightness interface. Its readback cannot establish emitted light.

## Rejected 0x07a5 candidate

SetPowerLedStatus (06001715) preserves the high six bits of 0x07a5 and changes
the low two. Similar Intel/QC methods take the system-power enum, not the
Office/Gaming/Turbo enum. No direct call to this private method was found in
the selected manager's restored path. This is a candidate implementation,
not evidence that the button uses it.

On 2026-10-26 a temporary, exact-host-gated module tested low-field value 2.
Both WMI and the OEM INOU.ECRR path read back 2, but the user reported **no
visible change**. The original low-field value 0 was restored and the temporary
module unloaded. It is not shipped or installed as a supported lamp feature.
Do not turn that successful register write into a claim of repaired lighting.

## Confirmed physical observation

Later on 2026-10-26, with the installed control tool selecting Turbo and
W_UW_MODE readback at 0x10, the user explicitly confirmed that the light beside
the power button illuminated or changed state. The temporary 0x07a5 module had
already been unloaded and its original value restored. The proposed 0x0727
trial was never executed. This observation therefore belongs to the existing
hardware-mode path, not either independent-lamp candidate.

The previous Linux cycle used Gaming → Gaming Quiet → Turbo. The first two
both requested 0x00, so three presses could produce only two hardware-mode
values. The physical-button cycle now requests Office (0xa0), Gaming (0x00),
and Turbo (0x10). Software profile confirmation and EC readback are required
before completion is announced. Three distinct request values still do not
establish three independently observed physical brightness levels.

Private recovery and trial receipts are under
`/home/lightjunction/Backups/mechrevo-drivers/2026-10-26-mode-led/`.
Reproducible local disassembly and the rejected source remain in the ignored
`.local-tests/mode-led-live-20261026/` directory. These are not runtime dependencies.

## Remaining acceptance

Turbo illumination has user confirmation on this host. The individual Office
and Gaming lamp states, a complete cycle using the actual physical button, and
wake/resume behavior are not yet established. The injected-input software cycle
is independently confirmed above. The existing W_UW_MODE bridge does not prove
an independent lamp interface or numeric brightness percentages. Further
changes require the actual OEM branch plus physical confirmation; the failed
candidate must not be reintroduced as a silent fallback.
