#!/usr/bin/env python3
"""
Cross-platform dependency and local-model manager.

Commands:
    install          Install the package + dev tools (uv sync, or pip -e .[dev])
    clean            Remove build/test caches and __pycache__ folders
    hard-install     Delete .venv and reinstall
    ollama-install   Install the native Ollama runtime
    ollama-pull      Download the configured Gemma model
    ollama-run       Start an interactive chat with the configured model
    ollama-setup     Install dependencies, install Ollama, pull and run the model

Examples:
    python make.py install
    python make.py ollama-setup
    python make.py ollama-run
    python make.py ollama-run --model gemma4:12b
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path.cwd()
VENV_DIR = PROJECT_ROOT / ".venv"

DEFAULT_OLLAMA_MODEL = "gemma4:26b"
OLLAMA_API_URL = "http://127.0.0.1:11434"
OLLAMA_WINDOWS_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_LINUX_INSTALL_SCRIPT_URL = "https://ollama.com/install.sh"


def run_command(
    command: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"\n> {subprocess.list2cmdline(command)}")
    return subprocess.run(
        command,
        check=check,
        env=env,
        text=True,
    )


def get_venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def create_venv() -> None:
    if VENV_DIR.exists():
        print(f"\n.venv already exists: {VENV_DIR}")
        return

    print("\nCreating virtual environment...")
    run_command([sys.executable, "-m", "venv", str(VENV_DIR)])


def install_dependencies() -> None:
    """Install the package (editable) with dev extras from pyproject.toml.

    Prefers uv (uses uv.lock); falls back to pip in .venv.
    """
    if shutil.which("uv"):
        run_command(["uv", "sync", "--extra", "dev"])
        return

    create_venv()
    venv_python = str(get_venv_python())
    run_command([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
    run_command([venv_python, "-m", "pip", "install", "-e", ".[dev]"])


def clean_cache() -> None:
    cache_dirs = [".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "htmlcov", "build", "dist"]
    for cache_dir in cache_dirs:
        path = PROJECT_ROOT / cache_dir
        if path.exists():
            print(f"Removing cache folder: {path}")
            shutil.rmtree(path, ignore_errors=True)

    print("\nRemoving __pycache__ folders...")
    for path in PROJECT_ROOT.rglob("__pycache__"):
        if VENV_DIR not in path.parents:
            shutil.rmtree(path, ignore_errors=True)

    print("\nClean completed.")


def hard_install() -> None:
    print("\nStarting hard install...")
    if VENV_DIR.exists():
        print(f"Removing virtual environment: {VENV_DIR}")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    clean_cache()
    install_dependencies()
    print("\nHard install completed successfully.")


def refresh_process_path() -> None:
    """
    Add common Ollama installation locations to PATH for this process.

    Installers can modify the user PATH, but the current terminal does not
    always receive the updated value immediately.
    """

    candidate_dirs: list[Path] = []
    system = platform.system()

    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate_dirs.append(Path(local_app_data) / "Programs" / "Ollama")
    elif system == "Darwin":
        candidate_dirs.extend(
            [
                Path("/usr/local/bin"),
                Path("/opt/homebrew/bin"),
                Path("/Applications/Ollama.app/Contents/Resources"),
            ]
        )
    else:
        candidate_dirs.extend(
            [
                Path("/usr/local/bin"),
                Path("/usr/bin"),
                Path("/bin"),
            ]
        )

    current_path = os.environ.get("PATH", "")
    existing_entries = current_path.split(os.pathsep) if current_path else []

    for directory in candidate_dirs:
        directory_text = str(directory)
        if directory.exists() and directory_text not in existing_entries:
            existing_entries.insert(0, directory_text)

    os.environ["PATH"] = os.pathsep.join(existing_entries)


def find_ollama_executable() -> Path | None:
    refresh_process_path()

    executable = shutil.which("ollama")
    if executable:
        return Path(executable)

    system = platform.system()
    candidates: list[Path] = []

    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")
    elif system == "Darwin":
        candidates.extend(
            [
                Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                Path("/usr/local/bin/ollama"),
                Path("/opt/homebrew/bin/ollama"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/local/bin/ollama"),
                Path("/usr/bin/ollama"),
                Path("/bin/ollama"),
            ]
        )

    return next((path for path in candidates if path.exists()), None)


def download_file(url: str, destination: Path) -> None:
    print(f"\nDownloading: {url}")
    print(f"Destination: {destination}")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Python dependency manager"},
    )

    with (
        urllib.request.urlopen(request, timeout=120) as response,
        destination.open("wb") as output_file,
    ):
        shutil.copyfileobj(response, output_file)


def install_ollama_windows() -> None:
    winget = shutil.which("winget")

    if winget:
        print("\nInstalling Ollama with Windows Package Manager...")
        result = run_command(
            [
                winget,
                "install",
                "--id",
                "Ollama.Ollama",
                "--exact",
                "--source",
                "winget",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            check=False,
        )

        refresh_process_path()
        if result.returncode == 0 and find_ollama_executable():
            return

        print("\nwinget installation did not complete; using the installer.")

    with tempfile.TemporaryDirectory(prefix="ollama-install-") as temp_dir:
        installer = Path(temp_dir) / "OllamaSetup.exe"
        download_file(OLLAMA_WINDOWS_INSTALLER_URL, installer)

        print(
            "\nThe Ollama installer will open. Complete the installation "
            "and let this command continue."
        )
        run_command([str(installer)])

    refresh_process_path()


def install_ollama_macos() -> None:
    brew = shutil.which("brew")

    if brew is None:
        raise RuntimeError(
            "Homebrew is required for automatic macOS installation. "
            "Install Ollama.app manually from the official Ollama download "
            "page, launch it once, and rerun this command."
        )

    print("\nInstalling the Ollama macOS application with Homebrew...")
    run_command([brew, "install", "--cask", "ollama-app"])

    # Launching the app starts its local server and creates the CLI link.
    run_command(["open", "-a", "Ollama"], check=False)
    refresh_process_path()


def install_ollama_linux() -> None:
    with tempfile.TemporaryDirectory(prefix="ollama-install-") as temp_dir:
        script_path = Path(temp_dir) / "install-ollama.sh"
        download_file(OLLAMA_LINUX_INSTALL_SCRIPT_URL, script_path)

        print("\nRunning the official Ollama Linux installer...")
        run_command(["sh", str(script_path)])

    refresh_process_path()


def install_ollama() -> Path:
    existing = find_ollama_executable()
    if existing:
        print(f"\nOllama is already installed: {existing}")
        run_command([str(existing), "--version"], check=False)
        return existing

    system = platform.system()

    if system == "Windows":
        install_ollama_windows()
    elif system == "Darwin":
        install_ollama_macos()
    elif system == "Linux":
        install_ollama_linux()
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")

    executable = find_ollama_executable()
    if executable is None:
        raise FileNotFoundError(
            "Ollama installation finished, but the CLI was not found. "
            "Restart the terminal and run the command again."
        )

    print(f"\nOllama installed successfully: {executable}")
    run_command([str(executable), "--version"], check=False)
    return executable


def is_ollama_server_running() -> bool:
    try:
        with urllib.request.urlopen(
            f"{OLLAMA_API_URL}/api/tags",
            timeout=2,
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def start_ollama_server() -> None:
    if is_ollama_server_running():
        print("\nOllama server is already running.")
        return

    ollama_executable = find_ollama_executable()
    if ollama_executable is None:
        ollama_executable = install_ollama()

    print("\nStarting the Ollama server...")

    popen_kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if platform.system() == "Windows":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_kwargs["start_new_session"] = True

    subprocess.Popen(
        [str(ollama_executable), "serve"],
        **popen_kwargs,
    )

    for _ in range(30):
        if is_ollama_server_running():
            print("Ollama server is ready.")
            return
        time.sleep(1)

    raise RuntimeError(
        "Ollama was started, but its API did not become available at "
        f"{OLLAMA_API_URL}. Check the Ollama logs."
    )


def pull_ollama_model(model: str) -> None:
    ollama_executable = find_ollama_executable()
    if ollama_executable is None:
        ollama_executable = install_ollama()

    start_ollama_server()

    print(f"\nPulling Ollama model: {model}")
    run_command([str(ollama_executable), "pull", model])


def run_ollama_model(model: str, *, pull_first: bool = False) -> None:
    ollama_executable = find_ollama_executable()
    if ollama_executable is None:
        ollama_executable = install_ollama()

    start_ollama_server()

    if pull_first:
        pull_ollama_model(model)

    print(f"\nStarting interactive model: {model}")
    print("Type /bye to exit the Ollama chat.\n")
    run_command([str(ollama_executable), "run", model])


def setup_ollama(model: str) -> None:
    install_dependencies()
    install_ollama()
    pull_ollama_model(model)
    run_ollama_model(model)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Manage Python dependencies and run local Ollama models.")
    )

    parser.add_argument(
        "command",
        choices=[
            "install",
            "clean",
            "hard-install",
            "ollama-install",
            "ollama-pull",
            "ollama-run",
            "ollama-setup",
        ],
        help="Action to perform.",
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help=(f"Ollama model tag. Default: {DEFAULT_OLLAMA_MODEL}"),
    )

    args = parser.parse_args()

    try:
        if args.command == "install":
            install_dependencies()
        elif args.command == "clean":
            clean_cache()
        elif args.command == "hard-install":
            hard_install()
        elif args.command == "ollama-install":
            install_ollama()
        elif args.command == "ollama-pull":
            pull_ollama_model(args.model)
        elif args.command == "ollama-run":
            run_ollama_model(args.model, pull_first=True)
        elif args.command == "ollama-setup":
            setup_ollama(args.model)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(130)
    except Exception as error:  # noqa: BLE001 - top-level CLI error reporting
        print(f"\nERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
