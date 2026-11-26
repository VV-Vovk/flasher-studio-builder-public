#!/usr/bin/env bash
# Checkout pinned ST package with ordinary directories AND gitlinks.
set -euo pipefail
sdk="$1"; family="$2"; tag="$3"; url="$4"
[[ "$family" =~ ^([a-z][0-9]|wb)$ && "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
git clone --depth 1 --branch "$tag" --filter=blob:none --sparse "$url" "$sdk"
# Non-cone patterns work whether the HAL path is a directory or submodule.
# Fetch only the middleware the source-only adapter actually supports.
if [[ "$family" == wb ]]; then
  # Only reviewed Apache-2.0 CMSIS and BSD-3-Clause HAL/LL, no wireless stack.
  [[ "$tag" == v1.24.0 && "$(git -C "$sdk" rev-parse HEAD)" == 7c5aa7dcd2c0abe787f922bb06a6213c724d08e4 ]] || { echo 'WB SDK revision requires license review' >&2; exit 1; }
  git -C "$sdk" sparse-checkout set --no-cone '/.gitmodules' '/LICENSE.md' '/Drivers/CMSIS/' "/Drivers/STM32${family^^}xx_HAL_Driver"
else
  git -C "$sdk" sparse-checkout set --no-cone '/.gitmodules' '/Drivers/CMSIS/' "/Drivers/STM32${family^^}xx_HAL_Driver" '/Middlewares/Third_Party/FreeRTOS' '/Middlewares/Third_Party/FatFs' '/Middlewares/ST/STM32_USB_Device_Library'
fi
# Keep all submodules at the exact commits in the pinned parent package.
submodules=$(git -C "$sdk" ls-files --stage -- Drivers/CMSIS "Drivers/STM32${family^^}xx_HAL_Driver" Middlewares | awk '$1=="160000" {print $4}')
while IFS= read -r sub; do
  [[ -z "$sub" ]] && continue
  if [[ "$family" == wb && "$sub" == Middlewares/* ]]; then continue; fi
  case "$sub" in Drivers/*|Middlewares/Third_Party/FreeRTOS|Middlewares/Third_Party/FatFs|Middlewares/ST/STM32_USB_Device_Library)
    git -C "$sdk" submodule update --init --depth 1 --recursive -- "$sub";; esac
done <<< "$submodules"
if [[ "$family" == wb ]]; then
  [[ "$(git -C "$sdk" hash-object LICENSE.md)" == c8ae886e79d0eca1e5f23df0fe5a49e42192edb5 ]] || { echo 'WB SDK license changed: review required' >&2; exit 1; }
  test ! -e "$sdk/Middlewares/ST/STM32_WPAN"
  test ! -e "$sdk/Projects/STM32WB_Copro_Wireless_Binaries"
  echo 'WB_LICENSE_PIN_PASS v1.24.0 (CMSIS/HAL only)'
fi
test -d "$sdk/Drivers/CMSIS/Include"
test -d "$sdk/Drivers/STM32${family^^}xx_HAL_Driver/Inc"
