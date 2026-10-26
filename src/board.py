# The picoKVM board's pins (hardware/README.md, "Firmware contract")
USB_SELECT = 8  # Output: low = input A, high = input B (data and peripheral power source)
USB_ENABLE = 9  # Output, active low: the USB data switches (off at reset)
PERIPHERAL_POWER = 10  # Output, active high: the peripheral port's power (off at reset)
VBUS_SENSE = {"A": 11, "B": 12}  # Inputs: high while that computer powers its USB port
BUTTON = 13  # Input, active low: on-board button and Grove key
LEDS = (14, 17)  # SK6812 data: on-board status LED, Grove key LED
PERIPHERAL_FAULT = 16  # Input, active low: peripheral port over-current / over-temperature
HDMI_DDC = {1: (1, 2), 2: (4, 5)}  # HDMI port: (SDA, SCL) of its DDC lines
