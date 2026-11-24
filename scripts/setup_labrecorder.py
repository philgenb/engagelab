"""Build the official LabRecorder CLI locally without installing its GUI."""

import hashlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
SOURCES = (
    (
        "labstreaminglayer/App-LabRecorder",
        "v1.18.0",
        "App-LabRecorder-1.18.0",
        "06e177798101ccad091ad71f9e8d56072024479a904f317984c29f0570e4e334",
    ),
    (
        "sccn/liblsl",
        "v1.18.0.b3",
        "liblsl-1.18.0.b3",
        "5f5f7eda155090ef2ccc88422d52d96ee4b92bf5697bd1374332702cf887e3e1",
    ),
)


def download_source(source):
    """Download a pinned source archive, verify its SHA-256, and return its unpacked path."""
    repository, tag, folder, expected = source
    destination = TOOLS / "sources"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{folder}.tar.gz"
    if not archive.exists():
        url = f"https://codeload.github.com/{repository}/tar.gz/refs/tags/{tag}"
        print(f"Downloading {repository} {tag}", flush=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        temporary = archive.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"Source archive checksum mismatch: {archive}")
    output = destination / folder
    if not output.exists():
        with tarfile.open(archive) as source_archive:
            source_archive.extractall(destination, filter="data")
    return output


def main():
    """Build and install LabRecorderCLI and liblsl under the project tools directory."""
    cmake = shutil.which("cmake")
    if not cmake:
        executable = Path(sys.executable).parent / (
            "cmake.exe" if sys.platform == "win32" else "cmake"
        )
        if executable.is_file():
            cmake = str(executable)
    if not cmake:
        raise SystemExit("Install build tooling first: pip install -e '.[xdf-build]'")
    with ThreadPoolExecutor(max_workers=2) as pool:
        recorder, lsl = list(pool.map(download_source, SOURCES))
    build = TOOLS / "build-labrecorder"
    install = TOOLS / "labrecorder"
    platform_options = []
    if sys.platform == "darwin":
        sdk = subprocess.check_output(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True
        ).strip()
        platform_options.append(f"-DCMAKE_OSX_SYSROOT={sdk}")
    subprocess.run(
        [
            cmake,
            "-S",
            str(recorder),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DLABRECORDER_BUILD_GUI=OFF",
            "-DLSL_BUILD_EXAMPLES=OFF",
            "-DLSL_BUILD_TESTING=OFF",
            f"-DLSL_SOURCE_DIR={lsl}",
            f"-DCMAKE_INSTALL_PREFIX={install}",
            *platform_options,
        ],
        check=True,
    )
    subprocess.run(
        [cmake, "--build", str(build), "--config", "Release", "--parallel", "4"], check=True
    )
    subprocess.run([cmake, "--install", str(build), "--config", "Release"], check=True)
    print(f"LabRecorder installed in {install}", flush=True)


if __name__ == "__main__":
    main()
