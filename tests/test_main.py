import asyncio
import json
import os
import runpy
import unittest
from unittest.mock import AsyncMock, patch

from mocks import ROOT, WDT, WLAN, Partition, Pin, TestCase, image, reader
import board
from updater import Updater


class Loop:
    def run_forever(self):  # The test's loop runs the tasks main.py creates
        pass


class MainTest(TestCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(ROOT, "config.example.json")) as file:
            example = json.load(file)
        example["devices"] = example["devices"][:2]  # The DDC/CI monitors
        with open("config.json", "w") as file:
            json.dump(example, file)

    async def start(self):
        """Runs main.py, then lets its tasks run a moment; returns the web server start mock."""
        start_server = AsyncMock()
        with patch("asyncio.get_event_loop", return_value=Loop()), patch("asyncio.start_server", start_server):
            runpy.run_path(os.path.join(ROOT, "src", "main.py"), run_name="main")
            await asyncio.sleep(1.5)
        return start_server

    async def asyncTearDown(self):
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def test_starts(self):
        start_server = await self.start()
        self.assertEqual(start_server.call_args.args[1:], ("0.0.0.0", 80))
        self.assertEqual(Pin.levels[board.USB_ENABLE], 0)  # Controller up
        self.assertEqual(WDT.instances, [])  # Not a trial

    async def test_confirms_an_update_once_on_the_network(self):
        data = image("v2.0.0")
        await Updater().install(reader(data), len(data))
        Partition.boot("ota_1", data)
        WLAN.connected = False
        await self.start()
        self.assertEqual(len(WDT.instances), 1)
        self.assertEqual(Partition.marked_valid, 0)
        WLAN.connected = True
        await asyncio.sleep(1.5)
        self.assertEqual(Partition.marked_valid, 1)


if __name__ == "__main__":
    unittest.main()
