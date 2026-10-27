#define MICROPY_HW_BOARD_NAME               "picoKVM"
#define MICROPY_HW_MCU_NAME                 "ESP32-S3"

// As the generic ESP32-S3 build: REPL on UART0 as well as on the native USB
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// The native USB as the chip's USB Serial/JTAG, not TinyUSB: the same port as the ROM bootloader's, so the browser
// installer keeps it from flashing to Improv, and esptool resets the chip into the bootloader without the BOOT button
#define MICROPY_HW_ENABLE_USBDEV            (0)
