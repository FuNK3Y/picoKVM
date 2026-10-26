import asyncio
import hashlib
import json
import os
import unittest

from mocks import WDT, Partition, Reset, TestCase, image, reader
from updater import Updater


class ImageVersionTest(unittest.TestCase):
    def test_reads_the_version(self):
        self.assertEqual(Updater.image_version(bytearray(image("v1.2.3")[:4096])), "v1.2.3")

    def test_refuses_other_images(self):
        for data, message in (
            (b"\0" * 4096, "ESP32 application"),
            (image("v2", chip=0), "ESP32-S3"),
            (image("v2", prefix="other "), "picoKVM"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                Updater.image_version(bytearray(data[:4096]))


class InstallTest(TestCase):
    async def test_writes_the_image_to_the_other_slot(self):
        updater = Updater()
        data = image("v2.0.0", size=10001)
        version = await updater.install(reader(data, 777), len(data), hashlib.sha256(data).hexdigest().upper())
        self.assertEqual(version, "v2.0.0")
        self.assertEqual(Partition.booted, "ota_1")
        slot = Partition.slots["ota_1"]
        self.assertEqual(slot[: len(data)], data)
        self.assertEqual(slot[len(data) : 3 * 4096], b"\xff" * (3 * 4096 - len(data)))  # The last block, padded as erased flash
        with open("update.json") as file:
            self.assertEqual(json.load(file), {"from": "v1.0.0", "to": "v2.0.0", "slot": "ota_1"})

    async def test_refuses_bad_uploads(self):
        updater = Updater()
        data = image("v2.0.0")
        for args, message in (
            ((reader(data), len(data), "00" * 32), "SHA-256"),
            ((reader(data[:5000]), len(data)), "cut off"),
            ((reader(data), Partition.SLOT_SIZE + 1), "does not fit"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                await updater.install(*args)
        self.assertIsNone(Partition.booted)
        self.assertFalse(os.path.exists("update.json"))

    async def test_refuses_another_image_before_writing(self):
        other = image("v9", prefix="other ")
        with self.assertRaises(ValueError):
            await Updater().install(reader(other), len(other))
        self.assertNotIn("ota_1", Partition.slots)

    async def test_image_rejected_by_the_bootloader_check(self):
        Partition.reject = True
        data = image("v2.0.0")
        with self.assertRaisesRegex(ValueError, "rejected"):
            await Updater().install(reader(data), len(data))
        self.assertFalse(os.path.exists("update.json"))


class RestartTest(TestCase):
    async def test_restarts_after_the_response(self):
        with self.assertRaises(Reset):
            await asyncio.wait_for(Updater().restart(), 2)


class TrialTest(TestCase):
    async def install_and_boot(self, version="v2.0.0"):
        data = image(version)
        await Updater().install(reader(data), len(data))
        Partition.boot("ota_1", data)
        return Updater()

    async def test_normal_boot(self):
        updater = Updater()
        self.assertEqual(updater.version, "v1.0.0")
        self.assertEqual(WDT.instances, [])
        await updater.run(lambda: False)  # Not a trial: returns at once

    async def test_confirmed_once_healthy(self):
        updater = await self.install_and_boot()
        self.assertEqual(len(WDT.instances), 1)
        healthy = [False, False, True]
        task = asyncio.ensure_future(updater.run(lambda: healthy.pop(0)))
        await asyncio.sleep(2.5)
        self.assertEqual(Partition.marked_valid, 1)
        self.assertFalse(os.path.exists("update.json"))
        self.assertEqual(updater.status, "Updated from v1.0.0 to v2.0.0")
        self.assertGreaterEqual(WDT.instances[0].feeds, 2)
        task.cancel()

    async def test_no_update_while_on_trial(self):
        updater = await self.install_and_boot()
        data = image("v3.0.0")
        with self.assertRaisesRegex(ValueError, "on trial"):
            await updater.install(reader(data), len(data))
        task = asyncio.ensure_future(updater.run(lambda: True))
        await asyncio.sleep(0.1)
        self.assertEqual(await updater.install(reader(data), len(data)), "v3.0.0")  # Confirmed: updates again
        self.assertEqual(Partition.booted, "ota_0")
        task.cancel()

    async def test_not_healthy_restarts_into_the_previous_firmware(self):
        updater = await self.install_and_boot()
        updater._TRIAL_TIMEOUT = 0
        with self.assertRaises(Reset):
            await updater.run(lambda: False)
        self.assertEqual(Partition.marked_valid, 0)
        self.assertTrue(os.path.exists("update.json"))  # For the previous firmware to report the rollback

    async def test_rollback_reported(self):
        await self.install_and_boot()
        Partition.boot("ota_0")  # The bootloader went back to the previous firmware
        updater = Updater()
        self.assertEqual(updater.status, "Update to v2.0.0 failed, rolled back to v1.0.0")
        self.assertFalse(os.path.exists("update.json"))
        self.assertEqual(len(WDT.instances), 1)  # Only the trial's


if __name__ == "__main__":
    unittest.main()
