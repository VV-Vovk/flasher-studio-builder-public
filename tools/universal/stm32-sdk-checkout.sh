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
test -d "$sdk/Drivers/CMSIS/Include"
test -d "$sdk/Drivers/STM32${family^^}xx_HAL_Driver/Inc"
