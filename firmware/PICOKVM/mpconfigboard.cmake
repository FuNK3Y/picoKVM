# picoKVM firmware: MicroPython's generic ESP32-S3 build, with two application slots for over-the-air updates
# and the application frozen in. Runs on the picoKVM board and on the M5Stack AtomS3 Lite (8 MiB flash both).
include(boards/mpconfigboard_esp32s3_common.cmake)

list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.flash_qio_80m
    ${MICROPY_BOARD_DIR}/sdkconfig.board
    ${MICROPY_BOARD_DIR}/../generated/sdkconfig.version
)

set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)
