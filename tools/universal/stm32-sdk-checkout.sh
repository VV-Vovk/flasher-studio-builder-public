#!/usr/bin/env bash
# Checkout pinned ST package with ordinary directories AND gitlinks.
set -euo pipefail
sdk="$1"; family="$2"; tag="$3"; url="$4"
[[ "$family" =~ ^[a-z][0-9]$ && "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
git clone --depth 1 --branch "$tag" --filter=blob:none --sparse "$url" "$sdk"
# Non-cone patterns work whether the HAL path is a directory or submodule.
# Fetch only the middleware the source-only adapter actually supports.
git -C "$sdk" sparse-checkout set --no-cone '/.gitmodules' '/Drivers/CMSIS/' "/Drivers/STM32${family^^}xx_HAL_Driver" '/Middlewares/Third_Party/FreeRTOS' '/Middlewares/Third_Party/FatFs' '/Middlewares/ST/STM32_USB_Device_Library'
# Keep all submodules at the exact commits in the pinned parent package.
submodules=$(git -C "$sdk" ls-files --stage -- Drivers/CMSIS "Drivers/STM32${family^^}xx_HAL_Driver" Middlewares | awk '$1=="160000" {print $4}')
while IFS= read -r sub; do
  [[ -z "$sub" ]] && continue
  case "$sub" in Drivers/*|Middlewares/Third_Party/FreeRTOS|Middlewares/Third_Party/FatFs|Middlewares/ST/STM32_USB_Device_Library)
    git -C "$sdk" submodule update --init --depth 1 --recursive -- "$sub";; esac
done <<< "$submodules"
test -d "$sdk/Drivers/CMSIS/Include"
test -d "$sdk/Drivers/STM32${family^^}xx_HAL_Driver/Inc"
