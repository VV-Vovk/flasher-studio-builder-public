# STM32WB CPU1 candidate

Pinned upstream STM32CubeWB v1.24.0. Upstream LICENSE.md lists CMSIS / CMSIS Device Apache-2.0 and HAL BSD-3-Clause. Fetch these paths only, no FUS, wireless coprocessor binaries, WPAN middleware (SLA0044), audio or proprietary tools. No SDK code or binaries committed. Actual linked firmware redistribution requires applicable notices and component review; public distribution is not cleared by this candidate. User may provide their own lawfully obtained full project. Source-only default 32 KiB application budget; `wbAppFlashKiB` sets an explicit page-aligned limit based on device SFSA. The browser independently enforces live SFSA. Real SDK smoke validation completed: 69/69 builds across 23 catalogue templates (CMSIS, HAL, LL), including a negative link test for actual shared mailbox sections. Previous validation used the same compiler source in the private development repository. This is compiler validation, not hardware validation or clearance for public firmware redistribution. Personal build requests remain in a separate private repository.

Upstream: https://github.com/STMicroelectronics/STM32CubeWB/blob/v1.24.0/LICENSE.md

## Self-contained CubeIDE WB preview

Use an exact reviewed STM32WB target and complete, portable GNU CubeIDE ZIP. User supplies legally obtained middleware, startup, linker script, and source; no download of restricted components. Include flasher-native.json at project root with explicit wbAppFlashKiB from live SFSA. The build preserves project linker and checks resulting HEX is CPU1 Flash only and has valid vectors. Radio stack/FUS compatibility, shared RAM layout and BLE operation are not independently validated; this is compilation preview, not automatic radio flashing. No licenses accepted on user's behalf.

## Static ELF allocation audit

Original audit code, not copied from vendor firmware. On WB55 variants with 192 KiB SRAM1, validate ARM ELF32 load segments and allocated sections against RM0434 and AN5289: application Flash, SRAM1, SRAM2a/b. Shared SRAM must be NOLOAD and non-executable. Other geometries retain compile-only preview. Static ELF checks cannot establish runtime stack compatibility or a complete memory-use proof. No WPAN/FUS redistribution or automatic license acceptance. Public tests use original synthetic C/linker inputs; no linked firmware artifacts published.

## License gate, 2026-11-26

Reviewed exact upstream v1.24.0 LICENSE.md (Git blob c8ae886e79d0eca1e5f23df0fe5a49e42192edb5), tag resolves to 7c5aa7dcd2c0abe787f922bb06a6213c724d08e4. CMSIS and CMSIS Device Apache-2.0, STM32WB HAL BSD-3-Clause; STM32_WPAN and STM32_USB_Device_Library SLA0044, STM32 Audio PDM SLA0047, STM32 Projects SLA0044. Source-only checkout fails closed on changed tag/commit or license blob. Public CI accepts original source/test fixtures, not restricted vendor source, compiled images or private requests. No blanket redistribution clearance for linked firmware. Other vendors/SDK releases require separate component-level review before adding or distributing dependencies. The automated checks are guardrails, not a legal opinion.

## OTA application build preview

AN5247 Rev 8 documents the relocated user application; `wbOtaLayout: st-ble-app-0x7000` is an explicit opt-in for reviewed WB55 192 KiB SRAM1. Checks the addressed image, reserves the first SRAM1 word, validates the end marker and preserves the bootloader by not generating a full-image write. Original synthetic test sources only, no vendor OTA code, FUS, middleware, or binary distribution. Runtime OTA/radio compatibility still requires hardware validation. Source for protocol constants: ST AN5247 and upstream BLE HeartRate example (reference only, not copied).

## Expanded SRAM audit (AN5451 rev 5, table 7)

WB55 64/192 KiB, WB35/30 32 KiB and WB50 64 KiB SRAM1: independent SRAM1 limit and fixed SRAM2a/b mappings. The intervening address hole is invalid. WB1x shared layout remains on hold. Synthetic tests only; no new vendor code or firmware. OTA relocation remains restricted to WB55 192 KiB pending separate review.

Radio binary metadata review: three upstream family directories in v1.24.0 share LICENSE.md blob 2bb0eca192a05eff8533a93671c688bb2e6a5fc6 (SLA0044 Rev6, October 2025). Only file names, byte counts and Git blob identifiers are recorded in Web; no encrypted firmware, license acceptance or distribution by Builder. ST-specific use and release-note compatibility checks remain necessary. No CPU2 update commands yet.

## WB1x geometry (RM0473 rev9, memory map and FLASH_SRRVR)

SRAM1 12 KiB, SRAM2a 32 KiB, SRAM2b 4 KiB; live SBRSA_B is two bits (26:25), not five. WB1MMC is based on WB15CCY; WB5MMG is based on WB55. Audit uses their actual CPU1 macro and SRAM geometry. Original synthetic sources only. Module USB routing not enabled. References: https://www.st.com/en/microcontrollers-microprocessors/stm32wbxm-modules.html and RM0473.
