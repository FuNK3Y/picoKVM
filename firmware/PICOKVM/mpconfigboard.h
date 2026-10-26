#define MICROPY_HW_BOARD_NAME               "picoKVM"
#define MICROPY_HW_MCU_NAME                 "ESP32-S3"

// As the generic ESP32-S3 build: REPL on UART0 as well as on the native USB
#define MICROPY_HW_ENABLE_UART_REPL         (1)
