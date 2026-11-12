# SPDX-License-Identifier: GPL-2.0-or-later
"""Known-bug function excerpt, retained only to demonstrate the regression.

Extracted unchanged from legacy CLI preimage SHA256
0d1b9a26c7caaddb24416ecd88523f334704c73c90971c0ba14c16b952058f79.
No mode, device, service, or hardware code is included or executed.
"""
import json
from pathlib import Path

PROFILES_PATH: Path
MECHREVO_PROFILES: list[dict]


def sync_oem_profiles() -> None:
    """Inject Mechrevo OEM profiles into /etc/tcc/profiles."""
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    current_profiles: list[dict] = []
    if PROFILES_PATH.exists():
        try:
            current_profiles = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            current_profiles = []

    profile_map = {p.get("id"): p for p in current_profiles if "id" in p}
    for oem_p in MECHREVO_PROFILES:
        profile_map[oem_p["id"]] = oem_p

    ordered = list(profile_map.values())
    try:
        PROFILES_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except PermissionError:
        pass
