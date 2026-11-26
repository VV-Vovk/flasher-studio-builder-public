#!/usr/bin/env bash
# Only trusted workflow code performs provisioning. No user project is sourced here.
set -euo pipefail
engine="$1"; version="$2"; target="$3"
base="${RUNNER_TEMP:?}/flasher-sdk"; mkdir -p "$base"
if [[ "$engine" == stm32cube || "$engine" == stm32-bare || "$engine" == stm32cubeide-gcc ]]; then
  [[ "$version" == system ]]
else
  [[ "$version" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]
fi
sudo apt-get update -qq
case "$engine" in
 esp-idf)
   [[ "$target" =~ ^esp32([a-z][0-9])?$ ]]
   sudo apt-get install -y git wget flex bison gperf python3-venv cmake ninja-build ccache libffi-dev libssl-dev dfu-util
   git clone --depth 1 --branch "$version" --recursive --shallow-submodules https://github.com/espressif/esp-idf.git "$base/esp-idf"
   "$base/esp-idf/install.sh" "$target"
   sdk="$base/esp-idf";;
 pico-sdk)
   sudo apt-get install -y cmake ninja-build ccache gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib build-essential pkg-config libusb-1.0-0-dev
   git clone --depth 1 --branch "$version" --recursive --shallow-submodules https://github.com/raspberrypi/pico-sdk.git "$base/pico-sdk"
   sdk="$base/pico-sdk";;
 stm32-bare)
   sudo apt-get install -y ccache gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib
   sdk="$base/stm32-bare"; mkdir -p "$sdk"
   read -r family tag < <(python3 -c 'import sys;sys.path.insert(0,"tools/universal");import stm32;p=stm32.profile(sys.argv[1])[1];print(p["family"],stm32.CUBE_TAGS[p["family"]])' "$target")
   bash tools/universal/stm32-sdk-checkout.sh "$sdk" "$family" "$tag" "https://github.com/STMicroelectronics/STM32Cube${family^^}.git";;
 stm32cube|stm32cubeide-gcc)
   sudo apt-get install -y cmake ninja-build ccache gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib make
   sdk="$base";;
 zephyr)
   sudo apt-get install -y git cmake ninja-build ccache gperf device-tree-compiler wget xz-utils file make gcc g++ libsdl2-dev libmagic1
   python -m pip install west==1.3.0
   west init -m https://github.com/zephyrproject-rtos/zephyr --mr "$version" "$base/zephyr-workspace"
   cd "$base/zephyr-workspace"
   west update --narrow -o=--depth=1
   west zephyr-export
   python -m pip install -r zephyr/scripts/requirements.txt
   west sdk install --toolchains arm-zephyr-eabi riscv64-zephyr-elf
   sdk="$base/zephyr-workspace/zephyr";;
 *) echo 'Invalid native engine' >&2; exit 1;;
esac
{
  printf 'FS_NATIVE_ENGINE=%s\nFS_NATIVE_VERSION=%s\nFS_SDK_PATH=%s\n' "$engine" "$version" "$sdk"
  printf 'CCACHE_DIR=%s\n' "$RUNNER_TEMP/flasher-ccache"
} >> "${GITHUB_ENV:?}"
