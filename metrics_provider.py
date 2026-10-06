import gc
import network
import esp32
from machine import Pin
from config import Config


class MetricsProvider:
    def metrics(self):
        output = f"""
# HELP wlan_rssi_dbm Received Signal Strength Indicator in dBm
# TYPE wlan_rssi_dbm gauge
wlan_rssi_dbm {network.WLAN(network.STA_IF).status("rssi")}
"""
        output += f"""
# HELP micropython_gc_mem_free Micropython free memory in bytes
# TYPE micropython_gc_mem_free gauge
micropython_gc_mem_free {gc.mem_free()}
# HELP micropython_gc_mem_alloc Micropython allocated memory in bytes
# TYPE micropython_gc_mem_alloc gauge
micropython_gc_mem_alloc {gc.mem_alloc()}
# HELP micropython_gc_mem_total Micropython total heap memory in bytes
# TYPE micropython_gc_mem_total gauge
micropython_gc_mem_total {gc.mem_alloc()+gc.mem_free()}
"""
        output += f"""
# HELP esp_heap_total_bytes Total heap size in bytes
# TYPE esp_heap_total_bytes gauge
# HELP esp_heap_free_bytes Free heap size in bytes
# TYPE esp_heap_free_bytes gauge
# HELP esp_heap_largest_free_block Largest free block in bytes
# TYPE esp_heap_largest_free_block gauge
# HELP esp_heap_minimum_free_bytes Minimum free seen overtime in bytes
# TYPE esp_heap_minimum_free_bytes gauge
"""
        for region, data in enumerate(esp32.idf_heap_info(esp32.HEAP_DATA)):
            output += f"""
esp_heap_total_bytes{{region="{region}"}} {data[0]}
esp_heap_free_bytes{{region="{region}"}} {data[1]}
esp_heap_largest_free_block{{region="{region}"}} {data[2]}
esp_heap_minimum_free_bytes{{region="{region}"}} {data[3]}
"""
        if Config.vbus_sense_gpio_pins:
            output += """
# HELP usb_input_powered 1 while the computer on that input powers its USB port
# TYPE usb_input_powered gauge
"""
            for input, pin in Config.vbus_sense_gpio_pins.items():
                output += f'usb_input_powered{{input="{input}"}} {Pin(pin, Pin.IN).value()}\n'
        if Config.peripheral_fault_gpio_pin is not None:
            output += f"""
# HELP usb_peripheral_fault 1 while the peripheral port is in over-current / over-temperature shutdown
# TYPE usb_peripheral_fault gauge
usb_peripheral_fault {1 - Pin(Config.peripheral_fault_gpio_pin, Pin.IN).value()}
"""
        output += f"""
# HELP esp_mcu_temperature Temperature of the MCU in degree
# TYPE esp_mcu_temperature gauge
esp_mcu_temperature {esp32.mcu_temperature()}
"""
        return output
