# CipherVault GUI (v1.9.0)

The modern graphical interface for CipherVault, built with CustomTkinter and themed after the official `CipherVault_Logo.png` — a monochrome "neon glow" look (near-black background, soft white glow accents) instead of the older violet theme. The logo is also used as the sidebar mark and the window/taskbar icon.

## Design

Every function lives on its own page, reachable from a single sidebar — there is exactly one way to reach any feature, which keeps the app predictable for new users:

- **MAIN** — Dashboard
- **VAULT** — Encrypt, Decrypt, Verify
- **MANAGE** — Contacts, Tools
- **Settings**, pinned at the bottom

First launch shows a short **welcome walkthrough** (identity → encrypt → share) instead of dropping you straight into the app; it only appears once; you can reopen it any time from Settings → "Show welcome guide again". Non-blocking **toast notifications** confirm successful actions (encrypted, decrypted, copied, exported, …) without an intrusive pop-up; the window fades in on launch and the identity indicator has a slow "breathing" glow — small, deliberate touches rather than heavy animation.

## Features
- **Dashboard**: identity card (fingerprint, key paths, export), quick-action tiles for Encrypt/Decrypt/Verify/Contacts, and running totals of files encrypted/decrypted.
- **Encrypt**: protect a file *or a folder* for yourself or a contact, with drag & drop (when `tkinterdnd2` is installed). Folders are zipped automatically — a background scan shows file count and total size so large folders are no surprise — then encrypts through the exact same `encrypt_file`/`encrypt_for_contact` functions used for any other file.
- **Decrypt**: restore a `.cvault` back to the original file (or zipped folder).
- **Verify**: check a `.cvault`'s signature and integrity without writing anything to disk.
- **Contacts**: add, list, copy fingerprint, and delete contacts.
- **Tools**: view/export your public key, compare files by SHA-256, compare a plain file against a `.cvault` container.
- **Settings**: current version, check/apply updates from GitHub without leaving the app (CipherVault restarts itself automatically once applied), and where your keys/contacts are stored.

## How to Run
Double-click `CipherVault.vbs` (opens with no console window) or run `start_gui.cmd`.

Either entry point runs the Smart GUI Launcher (`launcher/launcher_gui.ps1`), which:
1. Creates/reuses the `.venv` virtual environment.
2. Installs/updates dependencies from `requirements.txt`.
3. Checks GitHub for a newer release and updates in place automatically.
4. Launches `src/gui.py`.

## Requirements
Everything needed (`customtkinter`, `tkinterdnd2`, `Pillow`, `requests`, `packaging`, …) is listed in `requirements.txt` and installed automatically by the launcher on first run.
