#pragma once

#include <vector>

#include "esphome/components/i2c/i2c.h"
#include "esphome/components/select/select.h"
#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/core/preferences.h"

namespace esphome::picokvm {

/// Monitor switched over DDC/CI (VESA MCCS), through one of the board's HDMI ports.
class DdcMonitor : public i2c::I2CDevice {
 public:
  static constexpr uint8_t VCP_INPUT_SOURCE = 0x60;
  static constexpr uint8_t VCP_POWER_MODE = 0xD6;

  void set_inputs(uint16_t a, uint16_t b) {
    this->inputs_[0] = a;
    this->inputs_[1] = b;
  }
  void set_power_on(bool power_on, uint32_t delay_ms) {
    this->power_on_ = power_on;
    this->power_on_delay_ = delay_ms;
  }
  uint16_t input(size_t index) const { return this->inputs_[index]; }
  bool power_on() const { return this->power_on_; }
  uint32_t power_on_delay() const { return this->power_on_delay_; }

  /// Set VCP feature: false on NACK (no monitor, DDC/CI disabled in its menu, or monitor fully off)
  bool set_vcp(uint8_t code, uint16_t value);

 protected:
  uint16_t inputs_[2]{};
  bool power_on_{false};
  uint32_t power_on_delay_{2000};
};

/// Input select: moves the USB peripherals and every DDC/CI monitor to input A or B.
class PicoKvmSelect : public select::Select, public Component {
 public:
  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::HARDWARE; }

  void set_usb_select_pin(GPIOPin *pin) { this->usb_select_pin_ = pin; }
  void set_usb_enable_pin(GPIOPin *pin) { this->usb_enable_pin_ = pin; }
  void set_peripheral_power_pin(GPIOPin *pin) { this->peripheral_power_pin_ = pin; }
  void set_peripheral_off_time(uint32_t ms) { this->peripheral_off_time_ = ms; }
  void set_restore_value(bool restore) { this->restore_value_ = restore; }
  void set_initial_index(size_t index) { this->initial_index_ = index; }
  void add_monitor(DdcMonitor *monitor) { this->monitors_.push_back(monitor); }

 protected:
  void control(size_t index) override;
  void select_usb_(size_t index);
  void switch_monitor_(size_t monitor, size_t index);

  GPIOPin *usb_select_pin_{nullptr};
  GPIOPin *usb_enable_pin_{nullptr};
  GPIOPin *peripheral_power_pin_{nullptr};
  uint32_t peripheral_off_time_{200};
  bool restore_value_{true};
  size_t initial_index_{0};
  size_t usb_index_{0};
  std::vector<DdcMonitor *> monitors_;
  ESPPreferenceObject pref_;
};

}  // namespace esphome::picokvm
