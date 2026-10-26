import asyncio
import unittest

from mocks import Pin, TestCase
from config import Config
from controller import Controller
import board


class Device:
    def __init__(self, fail=0):
        self.inputs = []
        self.fail = fail

    async def set_active_input(self, input):
        self.inputs.append(input)
        if self.fail:
            self.fail -= 1
            raise OSError("monitor unreachable")

    def to_dict(self):
        return {}


class ControllerTest(TestCase):
    def setUp(self):
        super().setUp()
        Config.devices = [Device()]

    def test_enables_the_board_at_start(self):
        Controller()
        self.assertEqual(Pin.levels[board.USB_ENABLE], 0)
        self.assertEqual(Pin.levels[board.PERIPHERAL_POWER], 1)

    async def test_switch_power_cycles_the_peripherals(self):
        controller = Controller()
        Pin.history.clear()
        await controller.set_active_input("B")
        self.assertEqual(controller.selected_input, "B")
        self.assertEqual(Config.devices[0].inputs, ["B"])
        power, select = board.PERIPHERAL_POWER, board.USB_SELECT
        switch = [entry for entry in Pin.history if entry[0] in (power, select)]
        self.assertEqual(switch, [(power, 0), (select, 1), (power, 1)])

    async def test_same_input_leaves_the_peripherals_alone(self):
        controller = Controller()
        Pin.history.clear()
        await controller.set_active_input("A")
        self.assertNotIn((board.PERIPHERAL_POWER, 0), Pin.history)

    async def test_state(self):
        controller = Controller()
        self.assertEqual(controller.state(), {"active_input": {"A": Config.inputs["A"]}, "switching": None, "error": None})
        states = []

        async def watch():
            while True:
                changed = controller.changed
                await changed.wait()
                states.append(controller.state())

        watcher = asyncio.ensure_future(watch())
        await asyncio.sleep(0)
        await controller.set_active_input("B")
        await asyncio.sleep(0)
        self.assertEqual(states[0]["switching"], {"B": Config.inputs["B"]})
        self.assertEqual(states[-1], {"active_input": {"B": Config.inputs["B"]}, "switching": None, "error": None})
        Config.devices = [Device(fail=2)]
        with self.assertRaises(OSError):
            await controller.set_active_input("A")
        self.assertEqual(controller.state()["error"], "monitor unreachable")
        watcher.cancel()

    async def test_toggle(self):
        controller = Controller()
        await controller.set_active_input()
        self.assertEqual(controller.selected_input, "B")
        await controller.set_active_input()
        self.assertEqual(controller.selected_input, "A")

    async def test_retries_then_fails_without_switching_usb(self):
        Config.devices = [Device(fail=1)]
        controller = Controller()
        await controller.set_active_input("B")  # Second attempt succeeds
        self.assertEqual(Config.devices[0].inputs, ["B", "B"])
        Config.devices = [Device(fail=2)]
        with self.assertRaises(OSError):
            await controller.set_active_input("A")
        self.assertEqual(controller.selected_input, "B")


if __name__ == "__main__":
    unittest.main()
