import asyncio
import binascii
import hashlib
import json
import machine
import os
import struct
import time
from esp32 import Partition


class Updater:
    """Over-the-air updates of the whole firmware (MicroPython and the application frozen in).

    An update is written to the application slot not running, which the bootloader starts at the next reset.
    That first boot is a trial: unless run() confirms it once the firmware is healthy, any reset (the
    watchdog, a crash, a power cycle) brings the bootloader back to the previous firmware.
    """

    _STATE_FILE = "update.json"  # Written before restarting into an update: {"from": version, "to": version, "slot": label}
    _VERSION_PREFIX = "picoKVM "  # firmware/generate.py: marks the images of this firmware
    _WATCHDOG_TIMEOUT = 60000  # ms: generous, DNS lookups block the event loop
    _TRIAL_TIMEOUT = 120  # s: for the new firmware to come up healthy
    _BLOCK_SIZE = 4096  # Flash erase unit
    _READ_TIMEOUT = 30  # s: a stalled upload or download must not hold the KVM forever
    _RELEASE_ASSET = "firmware-ota.bin"  # .github/workflows/firmware.yml
    _GITHUB_TIMEOUT = 30  # s: for the release lookup
    _DOWNLOAD_TIMEOUT = 300  # s: for the whole download, connection included

    def __init__(self):
        self.version = self.image_version(self._read_header(Partition(Partition.RUNNING)))
        self.status = None  # Outcome of the last update, for the API
        self._trial = None
        self._watchdog = None
        try:
            with open(self._STATE_FILE) as file:
                state = json.load(file)
        except (OSError, ValueError):
            return
        if state.get("slot") == Partition(Partition.RUNNING).info()[4]:
            self._trial = state
            self._watchdog = machine.WDT(timeout=self._WATCHDOG_TIMEOUT)  # From here, a hang or a crash rolls the update back
        else:  # The bootloader rolled the update back
            self.status = f"Update to {state.get('to')} failed, rolled back to {self.version}"
            print(self.status)
            os.remove(self._STATE_FILE)

    @staticmethod
    def _read_header(partition):
        block = bytearray(4096)
        partition.readblocks(0, block)
        return block

    @classmethod
    def image_version(cls, block):
        """Version of a picoKVM application image, from its first block; raises ValueError for any other image."""
        # esp_image_header_t (24 bytes), with the chip at offset 12, then the first segment's header (8 bytes),
        # whose data starts with esp_app_desc_t: magic word, then the version at offset 16
        if len(block) < 80 or block[0] != 0xE9 or struct.unpack_from("<I", block, 32)[0] != 0xABCD5432:
            raise ValueError("Not an ESP32 application image")
        if struct.unpack_from("<H", block, 12)[0] != 9:
            raise ValueError("Not an ESP32-S3 image")
        version = bytes(block[48:80]).split(b"\0", 1)[0].decode()
        if not version.startswith(cls._VERSION_PREFIX):
            raise ValueError("Not a picoKVM firmware image")
        return version[len(cls._VERSION_PREFIX) :]

    async def install(self, read, size, sha256=None):
        """Writes an application image (firmware-ota.bin) to the slot not running, and makes it the next to boot.

        read(n) returns up to n bytes of the image, which is size bytes long. Returns the image's version.
        """
        if self._trial:  # The other slot holds the previous firmware, the one to roll back to
            raise ValueError("The running update is still on trial: retry once it is confirmed")
        slot = Partition(Partition.RUNNING).get_next_update()
        if not 0 < size <= slot.info()[3]:
            raise ValueError(f"An image of {size} bytes does not fit the {slot.info()[3]} bytes of the slot")
        block = bytearray(self._BLOCK_SIZE)
        view = memoryview(block)
        digest = hashlib.sha256()
        version = None
        received = filled = index = 0
        while received < size:
            try:
                data = await asyncio.wait_for(read(min(self._BLOCK_SIZE - filled, size - received)), self._READ_TIMEOUT)
            except EOFError:  # aiohttp's responses read exactly
                data = b""
            if not data:
                raise ValueError(f"Image cut off after {received} of {size} bytes")
            view[filled : filled + len(data)] = data
            filled += len(data)
            received += len(data)
            if filled == self._BLOCK_SIZE or received == size:
                digest.update(view[:filled])
                view[filled:] = b"\xff" * (self._BLOCK_SIZE - filled)  # Erased flash
                if index == 0:
                    version = self.image_version(block)  # Before overwriting anything
                slot.writeblocks(index, block)
                index += 1
                filled = 0
        if sha256 and binascii.hexlify(digest.digest()).decode() != sha256.lower():
            raise ValueError("Image corrupted: SHA-256 mismatch")
        with open(self._STATE_FILE, "w") as file:  # Before set_boot: a power loss right after must not skip the trial
            json.dump({"from": self.version, "to": version, "slot": slot.info()[4]}, file)
        try:
            slot.set_boot()  # Verifies the image: checksum, and the SHA-256 it carries
        except OSError as e:
            os.remove(self._STATE_FILE)
            raise ValueError(f"Image rejected: {e}")
        return version

    async def latest_release(self, repository):
        """The latest GitHub release of repository: its version (tag), and its application image's URL, size and SHA-256."""
        import aiohttp

        async def get():
            async with aiohttp.ClientSession(headers={"Accept": "application/vnd.github+json"}) as session:
                async with session.get(f"https://api.github.com/repos/{repository}/releases/latest") as response:
                    if response.status != 200:
                        raise OSError(f"GitHub answered {response.status} for the latest release of {repository}")
                    return await response.json()

        release = await asyncio.wait_for(get(), self._GITHUB_TIMEOUT)
        for asset in release["assets"]:
            if asset["name"] == self._RELEASE_ASSET:
                digest = asset.get("digest") or ""  # "sha256:<hex>", when GitHub gives it
                sha256 = digest[len("sha256:") :] if digest.startswith("sha256:") else None
                return {"version": release["tag_name"], "url": asset["browser_download_url"], "size": asset["size"], "sha256": sha256}
        raise OSError(f"The latest release of {repository} has no {self._RELEASE_ASSET}")

    async def install_release(self, release):
        """Downloads and installs a release, as given by latest_release(). Returns its version."""
        import aiohttp

        if release["version"] == self.version:
            raise ValueError(f"Already running {self.version}")

        async def download():
            async with aiohttp.ClientSession() as session:
                async with session.get(release["url"]) as response:  # Redirected to GitHub's storage
                    if response.status != 200:
                        raise OSError(f"The download of {release['url']} answered {response.status}")
                    return await self.install(response.read, release["size"], release["sha256"])

        return await asyncio.wait_for(download(), self._DOWNLOAD_TIMEOUT)

    async def restart(self):
        await asyncio.sleep(1)  # Lets the response go out
        machine.reset()

    async def run(self, is_healthy):
        """On a trial boot: confirms the update once is_healthy() holds, or restarts into the previous firmware."""
        if not self._trial:
            return
        deadline = time.ticks_add(time.ticks_ms(), self._TRIAL_TIMEOUT * 1000)
        while not is_healthy():
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                print("Update not healthy, restarting into the previous firmware")
                machine.reset()  # The state file stays: the previous firmware reports the rollback
            self._watchdog.feed()
            await asyncio.sleep(1)
        Partition.mark_app_valid_cancel_rollback()
        os.remove(self._STATE_FILE)
        self.status = f"Updated from {self._trial.get('from')} to {self.version}"
        print(self.status)
        self._trial = None
        while True:  # The watchdog cannot be stopped
            self._watchdog.feed()
            await asyncio.sleep(5)
