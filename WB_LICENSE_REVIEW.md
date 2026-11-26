# STM32WB CPU1 candidate

Pinned upstream STM32CubeWB v1.24.0. Upstream LICENSE.md lists CMSIS / CMSIS Device Apache-2.0 and HAL BSD-3-Clause. Fetch these paths only, no FUS, wireless coprocessor binaries, WPAN middleware (SLA0044), audio or proprietary tools. No SDK code or binaries committed. Actual linked firmware redistribution requires applicable notices and component review; public distribution is not cleared by this candidate. User may provide their own lawfully obtained full project. Source-only default 32 KiB application budget; `wbAppFlashKiB` sets an explicit page-aligned limit based on device SFSA. The browser independently enforces live SFSA. Real SDK smoke validation completed: 69/69 builds across 23 catalogue templates (CMSIS, HAL, LL), including a negative link test for actual shared mailbox sections. Previous validation used the same compiler source in the private development repository. This is compiler validation, not hardware validation or clearance for public firmware redistribution. Personal build requests remain in a separate private repository.

Upstream: https://github.com/STMicroelectronics/STM32CubeWB/blob/v1.24.0/LICENSE.md

## Self-contained CubeIDE WB preview

Use an exact reviewed STM32WB target and complete, portable GNU CubeIDE ZIP. User supplies legally obtained middleware, startup, linker script, and source; no download of restricted components. Include flasher-native.json at project root with explicit wbAppFlashKiB from live SFSA. The build preserves project linker and checks resulting HEX is CPU1 Flash only and has valid vectors. Radio stack/FUS compatibility, shared RAM layout and BLE operation are not independently validated; this is compilation preview, not automatic radio flashing. No licenses accepted on user's behalf.
