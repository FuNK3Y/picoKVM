"""Writes the build inputs derived from the repository to firmware/generated/:
- index_html.py: src/index.html as a module, as frozen code cannot open files;
- sdkconfig.version: the firmware version, stored in the image's application descriptor, where the
  updater reads it (of the running firmware, and of an uploaded image before flashing it).

The version is `git describe` of the repository, or $PICOKVM_VERSION when set.
"""

import os
import subprocess

VERSION_PREFIX = "picoKVM "  # Marks a picoKVM image (src/updater.py)

firmware_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(firmware_dir)
generated_dir = os.path.join(firmware_dir, "generated")


def write(name, content):
    path = os.path.join(generated_dir, name)
    if os.path.exists(path):
        with open(path) as file:
            if file.read() == content:  # Unchanged: keep the timestamp, a new sdkconfig rebuilds everything
                return
    with open(path, "w") as file:
        file.write(content)


def version():
    if os.environ.get("PICOKVM_VERSION"):
        return os.environ["PICOKVM_VERSION"]
    result = subprocess.run(["git", "describe", "--tags", "--always", "--dirty=+"], cwd=root_dir, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


os.makedirs(generated_dir, exist_ok=True)
with open(os.path.join(root_dir, "src", "index.html")) as file:
    write("index_html.py", f"content = {file.read()!r}\n")
project_version = (VERSION_PREFIX + version())[:31]  # The descriptor holds 31 characters
write(
    "sdkconfig.version",
    f'CONFIG_APP_EXCLUDE_PROJECT_VER_VAR=n\nCONFIG_APP_PROJECT_VER_FROM_CONFIG=y\nCONFIG_APP_PROJECT_VER="{project_version}"\n',
)
print("Firmware version:", project_version)
