# Embedded typeface

**Manrope**, Mikhail Sharanda / The Manrope Project Authors.

- Source: https://github.com/google/fonts/tree/main/ofl/manrope
- License: SIL Open Font License 1.1; see [Manrope-OFL.txt](Manrope-OFL.txt).
- Used for Latin interface text, the wordmark and temperature units.

Temperature and fan-speed values use egui's monospace family so equal-length
readings keep a stable width. Manrope's proportional digits are not treated as
tabular figures. Chinese text uses the operating system's font provider.
Manrope is embedded in both platform binaries; fonts are not downloaded at runtime.
