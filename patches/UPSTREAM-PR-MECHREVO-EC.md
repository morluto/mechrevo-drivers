# Linux hwmon upstream patch: MECHREVO GM6PX0X

**Status:** submitted by email and verified in the sender's Sent mailbox; awaiting maintainer review.

Patch: [`0001-hwmon-mechrevo-ec-v1.patch`](0001-hwmon-mechrevo-ec-v1.patch)

The patch adds a read-only hwmon driver for the verified `Kuangshi16Pro Series GM6PX0X`, board `GM6PX0X`, BIOS `N.1.09MRO07`. It reads CPU/GPU EC temperatures and fan RPM using `INOU.ECRR`, checks the EC project and fan capability, and makes no EC writes. Other models and BIOS versions are not included.

## Verification

- Project regression tests: 10 passed.
- Patch source: external-module `W=1` build against the running `7.2.11-arch1-1` kernel headers passed.
- Hardware: temporary patch module loaded beside the installed driver, exposed all four read-only attributes, and unloaded while the installed hwmon device remained. Five sequential comparison pairs tracked the same sensor ranges; temperatures and fan speeds changed between reads.
- The first patch draft had an ACPI integer-union initializer error and was rejected by the firmware. That draft emitted ACPI parameter warnings. The initializer was fixed, the module rebuilt, and the corrected module passed hardware reads. The historical warnings remain in the kernel log.
- `checkpatch.pl --strict --no-tree`, with the author's DCO trailer included: 0 errors, 1 advisory asking whether `MAINTAINERS` needs an entry. The existing general HWMON entry already covers `drivers/hwmon/` and `Documentation/hwmon/`; no individual maintainer commitment has been added.
- Mail-format verification: the rich-text-edited draft had lost tabs and wrapped diff headers and failed `git apply --numstat`. It was rebuilt as plain text from the original verified patch. The code diff is unchanged. `git mailsplit` and `git mailinfo` parsed the SMTP-format message, and `git apply --check` passed against the original mainline base files at `c339f4010dea8b0d754f84ace70cd1b089878ef8` after checking their Git blob hashes.

The source and hardware verification above was performed on 2026-10-29; the mail-format checks were performed on 2026-10-30. The draft repair changed attribution and submission notes only. No full kernel-tree build, installation, boot-time loading test, or validation on another laptop/BIOS has been performed.

## Submission

- Sent to `linux-hwmon@vger.kernel.org`, with `linux@roeck-us.net` copied.
- Sent message date: `Thu, 29 Oct 2026 15:35:05 -0500`.
- Subject: `[PATCH] hwmon: add read-only MECHREVO GM6PX0X sensor driver`.
- RFC Message-ID: `<CAOD9jOPXYG=n1BL+OjyLBz-zjy8RXnN3h9OTyapTFZwOvD1Rsg@mail.gmail.com>`.
- The sent message was read back with the `SENT` label. It is a single `text/plain` body with no HTML or attachments, and its body matches the verified submission.
- The author's DCO sign-off is included separately from the AI attribution.
- This records email submission; acceptance into Linux and public-list archiving have not been confirmed.
