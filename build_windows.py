"""Build the Windows app with PyInstaller."""
import ast
import json
import ssl
import sys
from pathlib import Path

from package_release import HERE, source_hashes


def main():
    if sys.platform != "win32":
        raise SystemExit("Build this application on Windows.")
    target = HERE / "dist/BackpackSeller"
    if any((target / name).exists() for name in ("data", "demo-data", "browser")):
        raise SystemExit("Move your app data out of dist before rebuilding.")

    import PyInstaller.__main__

    args = [str(HERE / "app.py"), "--noconfirm", "--clean", "--windowed", "--onedir",
            "--name", "BackpackSeller", "--distpath", str(HERE / "dist"),
            "--workpath", str(HERE / "build/pyinstaller"),
            "--specpath", str(HERE / "build"), "--collect-all", "playwright",
            "--icon", str(HERE / "assets/app.ico"),
            "--add-data", str(HERE / "assets") + ";assets"]
    # Some Python distributions ship extra trust files next to ssl.py.
    ssl_path = Path(ssl.__file__)
    literals = ast.walk(ast.parse(ssl_path.read_text(encoding="utf-8")))
    for name in sorted({node.value for node in literals if isinstance(node, ast.Constant)
                        and isinstance(node.value, str) and node.value.endswith(".pem")
                        and Path(node.value).name == node.value}):
        certificate = ssl_path.with_name(name)
        if not certificate.is_file():
            raise RuntimeError(f"Missing Python trust file: {name}")
        args.extend(["--add-data", str(certificate) + ";."])
    before = source_hashes()
    PyInstaller.__main__.run(args)
    if source_hashes() != before:
        raise RuntimeError("Source files changed during the build; build again.")
    (HERE / "build/source-hashes.json").write_text(json.dumps(before, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
