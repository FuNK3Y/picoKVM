import esphome.codegen as cg
from esphome.components import i2c, select
import esphome.config_validation as cv
from esphome import pins
from esphome.const import CONF_ID, CONF_INITIAL_OPTION, CONF_OPTIONS, CONF_RESTORE_VALUE

from . import picokvm_ns

PicoKvmSelect = picokvm_ns.class_("PicoKvmSelect", select.Select, cg.Component)
DdcMonitor = picokvm_ns.class_("DdcMonitor", i2c.I2CDevice)

CONF_USB_SELECT_PIN = "usb_select_pin"
CONF_USB_ENABLE_PIN = "usb_enable_pin"
CONF_PERIPHERAL_POWER_PIN = "peripheral_power_pin"
CONF_PERIPHERAL_OFF_TIME = "peripheral_off_time"
CONF_MONITORS = "monitors"
CONF_INPUTS = "inputs"
CONF_POWER_ON = "power_on"
CONF_POWER_ON_DELAY = "power_on_delay"

MONITOR_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(DdcMonitor),
        # VCP 0x60 (input source) value for USB A, then USB B: 0x0F DP1, 0x10 DP2, 0x11 HDMI1, 0x12 HDMI2
        cv.Required(CONF_INPUTS): cv.All(cv.ensure_list(cv.hex_uint16_t), cv.Length(min=2, max=2)),
        cv.Optional(CONF_POWER_ON, default=False): cv.boolean,
        cv.Optional(CONF_POWER_ON_DELAY, default="2s"): cv.positive_time_period_milliseconds,
    }
).extend(i2c.i2c_device_schema(0x37))


def _validate(config):
    if CONF_INITIAL_OPTION in config and config[CONF_INITIAL_OPTION] not in config[CONF_OPTIONS]:
        raise cv.Invalid(f"initial_option '{config[CONF_INITIAL_OPTION]}' is not one of the options")
    return config


# Pin defaults are the picoKVM board's (hardware/README.md)
CONFIG_SCHEMA = cv.All(
    select.select_schema(PicoKvmSelect)
    .extend(
        {
            # Names of input A and input B
            cv.Optional(CONF_OPTIONS, default=["USB A", "USB B"]): cv.All(
                cv.ensure_list(cv.string_strict), cv.Length(min=2, max=2)
            ),
            cv.Optional(CONF_INITIAL_OPTION): cv.string_strict,
            cv.Optional(CONF_RESTORE_VALUE, default=True): cv.boolean,
            cv.Optional(CONF_USB_SELECT_PIN, default="GPIO8"): pins.gpio_output_pin_schema,
            cv.Optional(CONF_USB_ENABLE_PIN, default={"number": "GPIO9", "inverted": True}): pins.gpio_output_pin_schema,
            cv.Optional(CONF_PERIPHERAL_POWER_PIN, default="GPIO10"): pins.gpio_output_pin_schema,
            cv.Optional(CONF_PERIPHERAL_OFF_TIME, default="200ms"): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_MONITORS, default=[]): cv.ensure_list(MONITOR_SCHEMA),
        }
    )
    .extend(cv.COMPONENT_SCHEMA),
    _validate,
)


async def to_code(config):
    var = await select.new_select(config, options=config[CONF_OPTIONS])
    await cg.register_component(var, config)

    cg.add(var.set_usb_select_pin(await cg.gpio_pin_expression(config[CONF_USB_SELECT_PIN])))
    cg.add(var.set_usb_enable_pin(await cg.gpio_pin_expression(config[CONF_USB_ENABLE_PIN])))
    cg.add(var.set_peripheral_power_pin(await cg.gpio_pin_expression(config[CONF_PERIPHERAL_POWER_PIN])))
    cg.add(var.set_peripheral_off_time(config[CONF_PERIPHERAL_OFF_TIME]))
    cg.add(var.set_restore_value(config[CONF_RESTORE_VALUE]))
    if CONF_INITIAL_OPTION in config:
        cg.add(var.set_initial_index(config[CONF_OPTIONS].index(config[CONF_INITIAL_OPTION])))

    for conf in config[CONF_MONITORS]:
        mon = cg.new_Pvariable(conf[CONF_ID])
        await i2c.register_i2c_device(mon, conf)
        cg.add(mon.set_inputs(conf[CONF_INPUTS][0], conf[CONF_INPUTS][1]))
        cg.add(mon.set_power_on(conf[CONF_POWER_ON], conf[CONF_POWER_ON_DELAY]))
        cg.add(var.add_monitor(mon))
