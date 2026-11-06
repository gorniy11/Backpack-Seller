"""Check the build and create the Windows and source archives."""
import hashlib
import json
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
VERSION = "1.1"
PRIVATE_DIRS = {"data", "demo-data", "browser", "__pycache__", ".git", ".venv"}


def source_files():
    files = [p for p in HERE.iterdir() if p.is_file() and (
        p.suffix in {".md", ".cmd"} or p.name in {
            "requirements.txt", "requirements-dev.txt", ".gitignore", ".gitattributes"})]
    files += list((HERE / "src").glob("*.py"))
    for folder, extensions in (("assets", {".png", ".ico", ".json"}),
                               ("tests/fixtures", {".json"}),
                               ("wiki", {".md"}), (".github", {".yml", ".yaml", ".md"})):
        files += [p for p in (HERE / folder).rglob("*") if p.is_file() and p.suffix in extensions]
    return sorted(files)


def source_hashes():
    return {p.relative_to(HERE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source_files()}


def write_archive(path, files, base, prefix):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            relative = file.relative_to(base)
            if file.is_symlink() or PRIVATE_DIRS.intersection(relative.parts):
                raise RuntimeError(f"Unexpected release file: {relative}")
            archive.write(file, prefix + relative.as_posix())
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"Archive verification failed: {path.name}")


def main():
    ready = HERE / "dist/BackpackSeller"
    executable = ready / "BackpackSeller.exe"
    if not executable.is_file():
        raise SystemExit("Run python build_windows.py first.")
    if any(PRIVATE_DIRS.intersection(p.relative_to(ready).parts) for p in ready.rglob("*")):
        raise SystemExit("The build contains local app data. Use a clean build directory.")
    expected = json.loads((HERE / "build/source-hashes.json").read_text(encoding="utf-8"))
    if source_hashes() != expected:
        raise SystemExit("Source files changed after the build. Run build_windows.py again.")

    suite = unittest.defaultTestLoader.discover(str(HERE / "src"))
    tests = unittest.TextTestRunner(verbosity=1).run(suite)
    if not tests.wasSuccessful() or not tests.testsRun:
        raise SystemExit("Tests failed; no release was packaged.")
    report = HERE / "build/runtime-check.json"
    report.unlink(missing_ok=True)
    subprocess.run([str(executable), "--self-check", str(report)], cwd=ready,
                   check=True, timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    check = json.loads(report.read_text(encoding="utf-8"))
    if not check.get("frozen") or not check.get("ok"):
        raise SystemExit("The executable failed its runtime check.")
    if source_hashes() != expected:
        raise SystemExit("Source files changed during verification. Build again.")

    shutil.copyfile(HERE / "README.md", ready / "README.md")
    (ready / "DEMO.cmd").write_text('@echo off\ncd /d "%~dp0"\nstart "" "%~dp0BackpackSeller.exe" --demo\n', encoding="ascii")
    (ready / "START-HERE.txt").write_text(
        "Backpack Seller 1.1\n\n"
        "Extract the whole archive and run BackpackSeller.exe. Keep _internal beside it.\n"
        "Run DEMO.cmd to try the interface without connecting any accounts.\n\n"
        "Choose English or Russian in the top-right corner. Themes are in Settings.\n"
        "Sign in to Steam, then add your backpack.tf User Token in Settings.\n"
        "Select an item, enter its price and description, and click List item.\n"
        "Relist edits a listing; Remove takes it down. Open website opens its filters.\n\n"
        "Offer monitoring checks trades and sends Telegram notifications. Configure credentials,\n"
        "send /start to your bot, then click Start. All trades are manual in Steam.\n"
        "Automatic bumps are optional and subject to backpack.tf limits.\n"
        "Keep the app open for monitoring and automatic bumps.\n\n"
        "To update, close the old app and copy its data folder beside the new EXE.\n"
        "Keep a backup. Do not share your data folder.\n\n"
        "See README.md for setup and trade handling details.\n", encoding="utf-8")
    manifest = dict(version=VERSION, tests_passed=tests.testsRun, runtime=check, source_sha256=expected)
    (ready / "BUILD-INFO.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    windows_zip = HERE / f"dist/BackpackSeller-{VERSION}-Windows.zip"
    source_zip = HERE / f"dist/BackpackSeller-{VERSION}-Source.zip"
    write_archive(windows_zip, sorted(p for p in ready.rglob("*") if p.is_file()), ready, "BackpackSeller/")
    write_archive(source_zip, source_files(), HERE, "Backpack-Seller/")
    checksums = []
    for path in (windows_zip, source_zip):
        checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
        print(path.name)
    (HERE / "dist/SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
