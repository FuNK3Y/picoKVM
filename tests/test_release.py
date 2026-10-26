import hashlib
import json
import unittest

from mocks import ClientSession, Partition, TestCase, image
from updater import Updater

API = "https://api.github.com/repos/owner/repo/releases/latest"
URL = "https://github.com/owner/repo/releases/download/v2.0.0/firmware-ota.bin"
STORAGE = "https://objects.githubusercontent.com/release-asset?signature=1"  # Where GitHub redirects the download
IMAGE = image("v2.0.0", 9000)


def serve(tag="v2.0.0", digest=True, name="firmware-ota.bin", data=IMAGE, size=None):
    asset = {"name": name, "browser_download_url": URL, "size": size or len(IMAGE)}
    if digest:
        asset["digest"] = "sha256:" + hashlib.sha256(IMAGE).hexdigest()
    release = {"tag_name": tag, "assets": [{"name": "firmware.bin", "browser_download_url": "elsewhere", "size": 1}, asset]}
    ClientSession.served[API] = (200, json.dumps(release).encode())
    ClientSession.served[URL] = (302, b"", {"Location": STORAGE})
    ClientSession.served[STORAGE] = (200, data, {"Content-Type": "application/octet-stream", "Content-Length": len(data)})


class ReleaseTest(TestCase):
    async def test_latest_release(self):
        serve()
        release = await Updater().latest_release("owner/repo")
        self.assertEqual(release, {"version": "v2.0.0", "url": URL, "size": len(IMAGE), "sha256": hashlib.sha256(IMAGE).hexdigest()})

    async def test_follows_the_redirect_with_its_own_headers(self):
        serve()
        updater = Updater()
        await updater.install_release(await updater.latest_release("owner/repo"))
        downloads = [(url, kwargs["headers"]) for _, url, kwargs in ClientSession.requests]
        self.assertEqual([url for url, _ in downloads], [URL, STORAGE])
        for _, headers in downloads:  # aiohttp's request_raw() adds the Host of each URL
            self.assertNotIn("Host", headers)

    async def test_redirect_errors(self):
        serve()
        ClientSession.served[STORAGE] = (302, b"", {"Location": URL})  # A loop
        updater = Updater()
        with self.assertRaisesRegex(OSError, "redirected too many times"):
            await updater.install_release(await updater.latest_release("owner/repo"))
        ClientSession.served[URL] = (302, b"")  # No Location
        with self.assertRaisesRegex(OSError, "answered 302"):
            await updater.install_release(await updater.latest_release("owner/repo"))

    async def test_installs_with_or_without_digest(self):
        for digest in (True, False):
            Partition.boot()
            serve(digest=digest)
            updater = Updater()
            self.assertEqual(await updater.install_release(await updater.latest_release("owner/repo")), "v2.0.0")
            self.assertEqual(Partition.booted, "ota_1")

    async def test_refuses_bad_downloads(self):
        corrupted = bytearray(IMAGE)
        corrupted[5000] ^= 1
        for data, message in ((IMAGE[:6000], "cut off"), (bytes(corrupted), "SHA-256")):
            serve(data=data)
            updater = Updater()
            with self.assertRaisesRegex(ValueError, message):
                await updater.install_release(await updater.latest_release("owner/repo"))

    async def test_already_running(self):
        serve(tag="v1.0.0")
        updater = Updater()
        with self.assertRaisesRegex(ValueError, "Already running"):
            await updater.install_release(await updater.latest_release("owner/repo"))

    async def test_github_errors(self):
        updater = Updater()
        ClientSession.served[API] = (404, b"{}")
        with self.assertRaisesRegex(OSError, "404"):
            await updater.latest_release("owner/repo")
        serve(name="other.bin")
        with self.assertRaisesRegex(OSError, "has no firmware-ota.bin"):
            await updater.latest_release("owner/repo")
        serve()
        ClientSession.served[URL] = (404, b"")
        with self.assertRaisesRegex(OSError, "404"):
            await updater.install_release(await updater.latest_release("owner/repo"))


if __name__ == "__main__":
    unittest.main()
