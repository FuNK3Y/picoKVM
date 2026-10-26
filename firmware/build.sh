#!/bin/sh
# Builds the picoKVM firmware: MicroPython for the ESP32-S3, with the application (src/) frozen in.
#
# Needs ESP-IDF v5.5.2 in the environment (`. $IDF_PATH/export.sh`). MicroPython is cloned into firmware/build/,
# unless MICROPY_DIR points to a checkout of MICROPYTHON_VERSION.
#
# Writes, to firmware/build/:
#   firmware.bin      bootloader, partition table and application: flashed at offset 0 over USB
#   firmware-ota.bin  application only: uploaded for an over-the-air update
set -e

MICROPYTHON_VERSION=v1.29.0  # Its ports/esp32/README.md gives the ESP-IDF version it supports

firmware_dir=$(cd "$(dirname "$0")" && pwd)
build_dir="$firmware_dir/build"
micropython_dir="${MICROPY_DIR:-$build_dir/micropython}"

if [ ! -d "$micropython_dir" ]; then
    git clone --depth 1 --branch "$MICROPYTHON_VERSION" https://github.com/micropython/micropython "$micropython_dir"
fi
mkdir -p "$build_dir"
python3 "$firmware_dir/generate.py"
make -C "$micropython_dir/mpy-cross"
# Not BUILD=: make passes it on to the mpy-cross build that freezing runs, which then overwrites the port's headers
make -C "$micropython_dir/ports/esp32" BOARD_DIR="$firmware_dir/PICOKVM" submodules
make -C "$micropython_dir/ports/esp32" BOARD_DIR="$firmware_dir/PICOKVM"
cp "$micropython_dir/ports/esp32/build-PICOKVM/firmware.bin" "$build_dir/firmware.bin"
cp "$micropython_dir/ports/esp32/build-PICOKVM/micropython.bin" "$build_dir/firmware-ota.bin"
python3 "$firmware_dir/check_image.py" "$build_dir/firmware-ota.bin"  # The updater must accept the image
