#include "picokvm_select.h"

#include <algorithm>

#include "esphome/core/log.h"

namespace esphome::picokvm {

static const char *const TAG = "picokvm";

static constexpr uint8_t DDC_HOST_ADDRESS = 0x51;  // Source address, as seen by the monitor
static constexpr uint32_t DDC_MESSAGE_GAP_MS = 50;  // DDC/CI asks for 50 ms between messages

bool DdcMonitor::set_vcp(uint8_t code, uint16_t value) {
  uint8_t msg[7] = {DDC_HOST_ADDRESS, 0x84, 0x03, code, uint8_t(value >> 8), uint8_t(value & 0xFF), 0};
  uint8_t checksum = this->address_ << 1;  // The checksum covers the write address (0x6E) too
  for (size_t i = 0; i < 6; i++)
    checksum ^= msg[i];
  msg[6] = checksum;
  if (this->write(msg, sizeof(msg)) != i2c::ERROR_OK) {
    ESP_LOGW(TAG, "DDC/CI write of VCP 0x%02X to 0x%02X failed: no monitor, DDC/CI disabled, or monitor off", code,
             this->address_);
    return false;
  }
  return true;
}

void PicoKvmSelect::setup() {
  this->usb_select_pin_->setup();
  this->usb_enable_pin_->setup();
  this->peripheral_power_pin_->setup();

  size_t index = this->initial_index_;
  if (this->restore_value_) {
    this->pref_ = this->template make_entity_preference<size_t>();
    size_t restored;
    if (this->pref_.load(&restored) && this->has_index(restored))
      index = restored;
  }
  // USB only at boot: the monitors stay where they are until the next switch
  this->usb_index_ = index;
  this->usb_select_pin_->digital_write(index == 1);
  this->usb_enable_pin_->digital_write(true);  // The data switches are off until enabled
  this->peripheral_power_pin_->digital_write(true);  // The peripheral port is unpowered at reset
  this->publish_state(index);
}

void PicoKvmSelect::control(size_t index) {
  for (size_t i = 0; i < this->monitors_.size(); i++)
    this->switch_monitor_(i, index);
  this->select_usb_(index);
  this->publish_state(index);
  if (this->restore_value_)
    this->pref_.save(&index);
}

void PicoKvmSelect::switch_monitor_(size_t i, size_t index) {
  DdcMonitor *monitor = this->monitors_[i];
  uint16_t input = monitor->input(index);
  if (!monitor->power_on()) {
    monitor->set_vcp(DdcMonitor::VCP_INPUT_SOURCE, input);
    return;
  }
  monitor->set_vcp(DdcMonitor::VCP_POWER_MODE, 0x01);
  // One pending input change per monitor: a newer switch replaces it
  this->set_timeout(static_cast<uint32_t>(i), std::max(monitor->power_on_delay(), DDC_MESSAGE_GAP_MS),
                    [monitor, input]() { monitor->set_vcp(DdcMonitor::VCP_INPUT_SOURCE, input); });
}

void PicoKvmSelect::select_usb_(size_t index) {
  if (index == this->usb_index_)
    return;
  this->usb_index_ = index;
  // Power and data move together, so the peripheral never sees a half-switched port and re-enumerates on the new
  // computer
  this->peripheral_power_pin_->digital_write(false);
  this->usb_select_pin_->digital_write(index == 1);
  this->set_timeout("peripheral_power", this->peripheral_off_time_,
                    [this]() { this->peripheral_power_pin_->digital_write(true); });
}

void PicoKvmSelect::dump_config() {
  LOG_SELECT("", "picoKVM", this);
  LOG_PIN("  USB select pin: ", this->usb_select_pin_);
  LOG_PIN("  USB enable pin: ", this->usb_enable_pin_);
  LOG_PIN("  Peripheral power pin: ", this->peripheral_power_pin_);
  ESP_LOGCONFIG(TAG, "  Peripheral off time: %" PRIu32 " ms", this->peripheral_off_time_);
  for (auto *monitor : this->monitors_) {
    ESP_LOGCONFIG(TAG, "  DDC/CI monitor at 0x%02X: inputs 0x%02X / 0x%02X%s", monitor->get_i2c_address(),
                  monitor->input(0), monitor->input(1), monitor->power_on() ? ", powers on" : "");
  }
}

}  // namespace esphome::picokvm
