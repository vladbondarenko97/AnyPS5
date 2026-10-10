"""Converts a PS5 title folder to a macOS application and starts it.

    python3 tools/macos_launcher.py [<title folder or .zip>]

Without an argument a folder picker opens and failures are shown in a dialog. The folder holds the
title's executable (eboot.bin or one .elf), its sce_module, sce_modules or prx directory and its
data. Fake-signed SELF containers are unwrapped to ELF; encrypted ones are refused. The relinker and
the prx libraries come from the full build in build/, the Vulkan loader and MoltenVK from VULKAN_SDK
or the newest ~/VulkanSDK/<version>/macOS. The application is written to build/launcher/."""
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WORK = BUILD / "launcher"
SELF_MAGICS = (b"\x4f\x15\x3d\x1d", b"\x54\x14\xf5\xee")
MODULE_DIRECTORIES = ("sce_module", "sce_modules", "prx")


def unwrap(data):
    if data[:4] not in SELF_MAGICS:
        return data
    count = struct.unpack_from("<H", data, 0x18)[0]
    elf = 0x20 + 0x20 * count
    if data[elf:elf + 4] != b"\x7fELF":
        raise RuntimeError("The SELF container holds no ELF header")
    program_headers = struct.unpack_from("<Q", data, elf + 0x20)[0]
    entry_size, header_count = struct.unpack_from("<HH", data, elf + 0x36)
    headers = data[elf:elf + program_headers + entry_size * header_count]
    extents = [sum(struct.unpack_from("<Q", headers, program_headers + entry_size * index + offset)[0] for offset in (8, 32))
               for index in range(header_count)]
    # Segments the container does not store (notes, SCE version) stay zero; it holds no section headers.
    if max(extents, default=0) > 1 << 32:
        raise RuntimeError("The SELF container is truncated or malformed")
    output = bytearray(max([len(headers)] + extents))
    output[:len(headers)] = headers
    struct.pack_into("<Q", output, 0x28, 0)
    struct.pack_into("<HH", output, 0x3C, 0, 0)
    for index in range(count):
        properties, offset, size = struct.unpack_from("<QQQ", data, 0x20 + 0x20 * index)
        if not properties & 0x800:
            continue
        if properties & 0xA:
            raise RuntimeError("The SELF container is encrypted or compressed; only fake-signed ones can be unwrapped")
        segment = (properties >> 20) & 0xFFF
        if segment >= header_count or offset + size > len(data):
            raise RuntimeError("The SELF container is truncated or malformed")
        target = struct.unpack_from("<Q", data, elf + program_headers + entry_size * segment + 8)[0]
        if target + size > len(output):
            raise RuntimeError("The SELF container is truncated or malformed")
        output[target:target + size] = data[offset:offset + size]
    return bytes(output)


def choose_folder():
    script = 'POSIX path of (choose folder with prompt "Choose a PS5 title folder to convert and run")'
    return Path(subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True).stdout.strip())


def alert(message):
    subprocess.run(["osascript", "-e", "on run argv", "-e", 'display alert "AnyPS5" message (item 1 of argv)', "-e", "end run", message])


def find_title(source):
    if source.suffix.lower() == ".zip":
        extracted = WORK / source.stem / "zip"
        shutil.rmtree(extracted, ignore_errors=True)
        with zipfile.ZipFile(source) as archive:
            archive.extractall(extracted)
        source = extracted
    executables = sorted(source.rglob("eboot.bin")) or sorted(source.glob("*.elf"))
    if len(executables) != 1:
        raise RuntimeError(f"Expected one eboot.bin or .elf in {source}, found {len(executables)}")
    return executables[0]


def vulkan_sdk():
    candidates = [Path(os.environ["VULKAN_SDK"])] if os.environ.get("VULKAN_SDK") else sorted((Path.home() / "VulkanSDK").glob("*/macOS"), reverse=True)
    for candidate in candidates:
        if (candidate / "lib" / "libMoltenVK.dylib").exists():
            return candidate
    raise RuntimeError("No Vulkan SDK: install the LunarG Vulkan SDK to ~/VulkanSDK or set VULKAN_SDK to its macOS directory")


def convert(source):
    relinker = BUILD / "core" / "relinker" / "relinker"
    libs = BUILD / "core" / "libs" / "libs"
    if not relinker.is_file() or not any(libs.glob("*.prx")):
        raise RuntimeError(f"No relinker or prx libraries in {BUILD}: run the full build and its libs target first")
    vulkan = vulkan_sdk()
    executable = find_title(source)
    title = executable.parent
    work = WORK / source.stem
    staged = work / "src"
    relinked = work / "out"
    for directory in (staged, relinked):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
    (staged / "eboot.elf").write_bytes(unwrap(executable.read_bytes()))
    for name in MODULE_DIRECTORIES:
        for module in sorted((title / name).glob("*")):
            if module.is_file():
                (staged / name).mkdir(exist_ok=True)
                (staged / name / module.name).write_bytes(unwrap(module.read_bytes()))
    bundle = WORK / f"{source.stem}.app"
    subprocess.run([relinker, "--macos", "--to-intel", staged / "eboot.elf", relinked / "eboot"], check=True, capture_output=True, text=True)
    subprocess.run([sys.executable, ROOT / "tools" / "package_macos_app.py", "--relinked", relinked, "--game", title,
                    "--libs", libs, "--vulkan", vulkan, bundle], check=True, capture_output=True, text=True)
    return bundle


def main():
    interactive = len(sys.argv) < 2
    try:
        bundle = convert(choose_folder() if interactive else Path(sys.argv[1]).resolve())
        subprocess.run(["open", bundle], check=True)
        print(bundle)
    except subprocess.CalledProcessError as error:
        message = (error.stderr or error.stdout or str(error)).strip()[-1500:]
        if interactive and "User canceled" in message:
            return 0
        print(message, file=sys.stderr)
        if interactive:
            alert(message)
        return 2
    except (OSError, RuntimeError, ValueError, struct.error, zipfile.BadZipFile) as error:
        print(error, file=sys.stderr)
        if interactive:
            alert(str(error))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
