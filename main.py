"""KOTOR Mod Installer — entry point."""

import sys

def check_deps():
    missing = []
    for pkg, import_name in [
        ("customtkinter", "customtkinter"),
        ("requests", "requests"),
        ("beautifulsoup4", "bs4"),
        ("lxml", "lxml"),
        ("keyring", "keyring"),
        ("py7zr", "py7zr"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    return missing


def main():
    missing = check_deps()
    if missing:
        print("Missing dependencies. Install with:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)

    from ui.app import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
