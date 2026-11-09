import customtkinter as ctk
import sys
import subprocess
import hashlib
import json
import math
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

# Optional drag-and-drop support (tkinterdnd2). GUI works without it.
try:
    import tkinterdnd2 as tkdnd
    DND_SUPPORTED = True
except Exception:
    tkdnd = None
    DND_SUPPORTED = False

# --- Path setup -------------------------------------------------
# src/ (this file's parent) holds the ciphervault package; the project
# root (its parent) holds launcher/updater.py used for auto-update.
SRC_DIR = Path(__file__).parent
BASE_DIR = SRC_DIR.parent
sys.path.append(str(SRC_DIR))
sys.path.append(str(BASE_DIR / "launcher"))

from ciphervault.contacts import ContactsStore
from ciphervault.crypto import KeyStore, SelfEncryptor
from ciphervault.archiving import zip_folder, cleanup_temp_zip
from ciphervault import __version__

try:
    import updater as update_engine
    UPDATER_AVAILABLE = True
except Exception:
    update_engine = None
    UPDATER_AVAILABLE = False

# --- THEME ---
# Monochrome "neon glow" palette matching CipherVault_Logo.png: a soft white
# glow against a near-black charcoal background, rather than a saturated
# accent color. "accent" is the glow itself (near-white); "accent_text" is
# the dark text used on top of it wherever accent is a fill/background.
THEME_COLORS = {
    "bg_dark": "#0A0A0D",
    "bg_card": "#141417",
    "sidebar": "#0C0C0F",
    "accent": "#F2F2F6",
    "accent_hover": "#FFFFFF",
    "accent_text": "#0A0A0D",
    "text_primary": "#FFFFFF",
    "text_secondary": "#9A9AA4",
    "success": "#3ED598",
    "error": "#FF5C6C",
    "warning": "#FFC24B",
    "muted": "#1B1B20",
    "border": "#2A2A30",
}

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

SELF_RECIPIENT_LABEL = "Me (self-encrypt)"


# =============================================================
# Small utilities
# =============================================================

def format_fp(fp: str) -> str:
    if not fp:
        return ""
    return " ".join([fp[i:i + 4] for i in range(0, len(fp), 4)])


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def interpolate_color(hex_a: str, hex_b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a = tuple(int(hex_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*mixed)


def normalize_dnd_path(data: str) -> Path | None:
    """Extract first file path from tkdnd drop data string."""
    if not data:
        return None
    raw = data.strip()
    # tkdnd wraps paths with spaces in braces: {C:/path with space/file.txt}
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    parts = raw.split()
    if not parts:
        return None
    return Path(parts[0]).expanduser().resolve()


def register_drop(widget, on_drop) -> bool:
    if not DND_SUPPORTED:
        return False
    try:
        widget.drop_target_register(tkdnd.DND_FILES)
        widget.dnd_bind("<<Drop>>", on_drop)
        return True
    except Exception:
        return False


# --- Local GUI state (onboarding flag + lightweight usage stats) ---
def load_gui_state(base_dir: Path) -> dict:
    p = base_dir / "gui_state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_gui_state(base_dir: Path, state: dict) -> None:
    p = base_dir / "gui_state.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


# --- Branding (CipherVault_Logo.png) -----------------------------
LOGO_PATH = BASE_DIR / "CipherVault_Logo.png"

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False


def _load_cropped_logo():
    """Open the logo and crop its transparent margins to the glow's bounding box."""
    img = Image.open(LOGO_PATH).convert("RGBA")
    bbox = img.split()[-1].getbbox()  # bbox of the non-transparent glow content
    if bbox:
        pad = 12
        left = max(bbox[0] - pad, 0)
        top = max(bbox[1] - pad, 0)
        right = min(bbox[2] + pad, img.width)
        bottom = min(bbox[3] + pad, img.height)
        img = img.crop((left, top, right, bottom))
    return img


def load_logo_ctk_image(height: int = 150):
    """Load the cropped logo as a CTkImage sized to a given height (aspect preserved)."""
    if not PIL_AVAILABLE or not LOGO_PATH.exists():
        return None
    try:
        img = _load_cropped_logo()
        width = int(img.width * (height / img.height))
        return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))
    except Exception:
        return None


def apply_window_icon(window) -> None:
    """Set the title-bar/taskbar icon from the logo PNG, best-effort."""
    if not PIL_AVAILABLE or not LOGO_PATH.exists():
        return
    try:
        photo = ImageTk.PhotoImage(_load_cropped_logo())
        window.iconphoto(True, photo)
        window._logo_icon_ref = photo  # keep a reference so it isn't garbage-collected
    except Exception:
        pass


# =============================================================
# Reusable widgets
# =============================================================

class ProButton(ctk.CTkButton):
    """Primary button: solid glow fill with dark text, like the logo's light-on-dark mark."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            corner_radius=10,
            fg_color=THEME_COLORS["accent"],
            hover_color=THEME_COLORS["accent_hover"],
            text_color=THEME_COLORS["accent_text"],
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40,
        )


class GhostButton(ctk.CTkButton):
    """Secondary ghost button."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            corner_radius=10,
            fg_color="transparent",
            border_width=1,
            border_color=THEME_COLORS["border"],
            hover_color=THEME_COLORS["bg_card"],
            text_color=THEME_COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            height=38,
        )


class ProCard(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(
            fg_color=THEME_COLORS["bg_card"],
            corner_radius=14,
            border_width=1,
            border_color=THEME_COLORS["border"],
        )


def page_header(parent, title: str, subtitle: str, row: int = 0, columnspan: int = 1):
    """Consistent title + one-line purpose statement, used at the top of every page."""
    header = ctk.CTkFrame(parent, fg_color="transparent")
    header.grid(row=row, column=0, columnspan=columnspan, sticky="ew", pady=(0, 24))
    ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=28, weight="bold"), text_color=THEME_COLORS["text_primary"]).pack(anchor="w")
    ctk.CTkLabel(header, text=subtitle, font=ctk.CTkFont(size=13), text_color=THEME_COLORS["text_secondary"], justify="left", wraplength=760).pack(anchor="w", pady=(5, 0))
    return header


class Pill(ctk.CTkFrame):
    """Status pill with a slow 'breathing' glow on its dot - subtle, on-brand animation."""
    def __init__(self, master, text: str, color: str):
        super().__init__(master, fg_color=THEME_COLORS["muted"], corner_radius=12)
        self.dot = ctk.CTkLabel(self, text="\u25cf", text_color=color, font=ctk.CTkFont(size=14, weight="bold"))
        self.dot.pack(side="left", padx=(10, 6), pady=6)
        self.label = ctk.CTkLabel(self, text=text, text_color=THEME_COLORS["text_primary"], font=ctk.CTkFont(size=12))
        self.label.pack(side="left", padx=(0, 12))
        self._base_color = color
        self._pulse_t = 0
        self._pulse_job = None
        self._start_pulse()

    def update(self, text: str, color: str):
        self.label.configure(text=text)
        self._base_color = color
        self.dot.configure(text_color=color)

    def _start_pulse(self):
        def step():
            if not self.winfo_exists():
                return
            self._pulse_t += 1
            factor = (math.sin(self._pulse_t / 14) + 1) / 2  # 0..1 breathing curve
            try:
                self.dot.configure(text_color=interpolate_color(self._base_color, "#FFFFFF", factor * 0.4))
            except Exception:
                return
            self._pulse_job = self.after(90, step)
        step()


class Toast(ctk.CTkFrame):
    KIND_COLORS = {
        "success": THEME_COLORS["success"],
        "error": THEME_COLORS["error"],
        "info": THEME_COLORS["accent"],
        "warning": THEME_COLORS["warning"],
    }

    def __init__(self, master, message: str, kind: str = "info"):
        super().__init__(master, fg_color=THEME_COLORS["bg_card"], corner_radius=10,
                          border_width=1, border_color=THEME_COLORS["border"])
        color = self.KIND_COLORS.get(kind, THEME_COLORS["accent"])
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(padx=14, pady=12)
        ctk.CTkLabel(row, text="\u25cf", text_color=color, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(0, 8), anchor="n")
        ctk.CTkLabel(row, text=message, text_color=THEME_COLORS["text_primary"], font=ctk.CTkFont(size=13),
                     wraplength=300, justify="left").pack(side="left")


class ToastManager:
    """Non-blocking, self-dismissing notifications stacked bottom-right of the window."""
    def __init__(self, root):
        self.root = root
        self.active: list[Toast] = []

    def show(self, message: str, kind: str = "info", duration_ms: int = 3400):
        toast = Toast(self.root, message, kind)
        toast.update_idletasks()
        self.active.append(toast)
        toast.place(relx=1.0, rely=1.0, x=300, y=self._target_y(toast), anchor="se")
        self._slide_in(toast)
        toast.after(duration_ms, lambda: self._dismiss(toast))

    def _target_y(self, toast) -> int:
        offset = 20
        for t in self.active:
            if t is toast:
                break
            offset += t.winfo_reqheight() + 10
        return -offset

    def _reflow(self):
        for t in self.active:
            if t.winfo_exists():
                t.place(relx=1.0, rely=1.0, x=-20, y=self._target_y(t), anchor="se")

    def _slide_in(self, toast, i=0, steps=10):
        if not toast.winfo_exists():
            return
        frac = i / steps
        x = int(300 * (1 - frac)) - 20
        toast.place(relx=1.0, rely=1.0, x=x, y=self._target_y(toast), anchor="se")
        if i < steps:
            toast.after(14, lambda: self._slide_in(toast, i + 1, steps))

    def _dismiss(self, toast):
        if toast not in self.active:
            return
        self.active.remove(toast)
        toast.destroy()
        self._reflow()


class TaskStatus(ctk.CTkFrame):
    """Compact status row with indeterminate bar."""
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.indicator = ctk.CTkLabel(self, text="\u25cf", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=14, weight="bold"))
        self.indicator.pack(side="left", padx=(2, 6))
        self.label = ctk.CTkLabel(self, text="Idle", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12))
        self.label.pack(side="left")
        self.progress = ctk.CTkProgressBar(self, height=6, fg_color=THEME_COLORS["bg_card"], progress_color=THEME_COLORS["accent"], mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.running = False

    def set_state(self, text: str, state: str):
        colors = {
            "idle": THEME_COLORS["text_secondary"],
            "running": THEME_COLORS["accent"],
            "success": THEME_COLORS["success"],
            "error": THEME_COLORS["error"],
        }
        color = colors.get(state, THEME_COLORS["text_secondary"])
        self.indicator.configure(text_color=color)
        self.label.configure(text=text, text_color=color)
        if state == "running" and not self.running:
            self.progress.start(); self.running = True
        elif state != "running" and self.running:
            self.progress.stop(); self.running = False
            self.progress.set(1 if state == "success" else 0)


class DropZone(ProCard):
    """Re-usable drop area with optional drag-and-drop."""
    def __init__(self, master, title: str, subtitle: str, on_browse, on_drop, browse_label: str = "Browse"):
        super().__init__(master)
        self.on_browse = on_browse
        self.on_drop = on_drop
        self.drop_enabled = register_drop(self, self._handle_drop)

        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=THEME_COLORS["text_primary"]).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))
        hint = subtitle
        if self.drop_enabled:
            hint += "  \u2022  Drag & drop ready"
        else:
            hint += "  \u2022  Drag & drop needs tkinterdnd2"
        self.hint_label = ctk.CTkLabel(self, text=hint, text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12))
        self.hint_label.grid(row=1, column=0, sticky="w", padx=18)
        self.selection = ctk.CTkLabel(self, text="", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12))
        self.selection.grid(row=2, column=0, sticky="w", padx=18, pady=(8, 0))
        ProButton(self, text=browse_label, command=self.on_browse, width=150).grid(row=3, column=0, sticky="w", padx=18, pady=(12, 18))

    def _handle_drop(self, event):
        path = normalize_dnd_path(getattr(event, "data", ""))
        if path and self.on_drop:
            self.on_drop(path)

    def set_text(self, text: str):
        self.selection.configure(text=f"Selected: {text}")


class TopBar(ctk.CTkFrame):
    """Identity-only status strip. Navigation lives solely in the sidebar
    so there is exactly one way to reach any function in the app."""
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        container = ProCard(self)
        container.grid(row=0, column=0, sticky="ew")
        container.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(container, fg_color="transparent")
        header.grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        self.pill = Pill(header, "Secure channel", THEME_COLORS["accent"])
        self.pill.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(header, text="CipherVault", text_color=THEME_COLORS["text_primary"], font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")

        self.fp_label = ctk.CTkLabel(container, text="Fingerprint: loading...", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(family="Consolas", size=12))
        self.fp_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 16))

    def set_fingerprint(self, fp: str):
        formatted = format_fp(fp) if fp else "Unavailable"
        self.fp_label.configure(text=f"Fingerprint: {formatted}")
        if fp:
            self.pill.update("Identity ready", THEME_COLORS["success"])
        else:
            self.pill.update("Identity missing", THEME_COLORS["error"])


# =============================================================
# Main application window
# =============================================================

class CipherVaultApp(ctk.CTk):
    NAV_ITEMS = [
        ("MAIN", [("dashboard", "Dashboard")]),
        ("VAULT", [("encrypt", "Encrypt"), ("decrypt", "Decrypt"), ("verify", "Verify")]),
        ("MANAGE", [("contacts", "Contacts"), ("tools", "Tools")]),
    ]

    def __init__(self):
        super().__init__()
        self.attributes("-alpha", 0.0)  # fade in once everything is laid out

        self.title(f"CipherVault {__version__}")
        self.geometry("1320x860")
        self.minsize(1120, 760)
        self.configure(fg_color=THEME_COLORS["bg_dark"])
        apply_window_icon(self)

        self.contacts_store = ContactsStore()
        self.keystore = KeyStore()
        self.encryptor = SelfEncryptor(self.keystore)
        self.gui_state = load_gui_state(self.keystore.base_dir)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=232, fg_color=THEME_COLORS["sidebar"], corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        logo_image = load_logo_ctk_image(height=124)
        if logo_image is not None:
            self.logo = ctk.CTkLabel(self.sidebar, text="", image=logo_image)
        else:
            self.logo = ctk.CTkLabel(self.sidebar, text="CipherVault", font=ctk.CTkFont(size=24, weight="bold"), text_color=THEME_COLORS["accent"])
        self.logo.grid(row=0, column=0, padx=22, pady=(26, 18), sticky="w")

        self.nav_buttons = {}
        row = 1
        for section_label, items in self.NAV_ITEMS:
            self._add_section_label(section_label, row)
            row += 1
            for key, label in items:
                self._add_nav_button(key, label, row)
                row += 1

        self.sidebar.grid_rowconfigure(row, weight=1)  # spacer pushes Settings + version to the bottom
        row += 1
        self._add_nav_button("settings", "Settings", row)
        row += 1

        self.version_label = ctk.CTkLabel(self.sidebar, text=f"v{__version__}", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12))
        self.version_label.grid(row=row, column=0, padx=22, pady=(6, 20), sticky="w")

        # --- Main content ---
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=30, pady=30)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        self.topbar = TopBar(self.main, self)
        self.topbar.grid(row=0, column=0, sticky="ew", pady=(0, 18))

        self.content = ctk.CTkFrame(self.main, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.toast_manager = ToastManager(self)

        self.welcome_page = WelcomePage(self.content, self)
        self.dashboard_page = DashboardPage(self.content, self)
        self.encrypt_page = EncryptPage(self.content, self)
        self.decrypt_page = DecryptPage(self.content, self)
        self.verify_page = VerifyPage(self.content, self)
        self.contacts_page = ContactsPage(self.content, self)
        self.tools_page = ToolsPage(self.content, self)
        self.settings_page = SettingsPage(self.content, self)
        self._pages = (
            self.welcome_page, self.dashboard_page, self.encrypt_page, self.decrypt_page,
            self.verify_page, self.contacts_page, self.tools_page, self.settings_page,
        )

        self.refresh_identity()
        if self.gui_state.get("onboarded"):
            self.show_dashboard()
        else:
            self._show(self.welcome_page, "welcome")

        self.after(30, self._fade_in)

    # --- window chrome -------------------------------------------------
    def _fade_in(self, step: int = 0, total: int = 14):
        try:
            self.attributes("-alpha", min(1.0, (step + 1) / total))
        except Exception:
            return
        if step + 1 < total:
            self.after(15, lambda: self._fade_in(step + 1, total))

    def _add_section_label(self, text: str, row: int):
        ctk.CTkLabel(self.sidebar, text=text, text_color=THEME_COLORS["text_secondary"],
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=row, column=0, padx=22, pady=(14, 4), sticky="w")

    def _add_nav_button(self, key: str, label: str, row: int):
        btn = ctk.CTkButton(self.sidebar, text=label, command=lambda k=key: self.navigate(k), height=40, anchor="w", corner_radius=10,
                             fg_color="transparent", hover_color=THEME_COLORS["bg_card"],
                             text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=14))
        btn.grid(row=row, column=0, padx=14, pady=3, sticky="ew")
        self.nav_buttons[key] = btn

    def _activate_nav(self, name: str):
        for key, btn in self.nav_buttons.items():
            if key == name:
                btn.configure(fg_color=THEME_COLORS["bg_card"], text_color=THEME_COLORS["text_primary"])
            else:
                btn.configure(fg_color="transparent", text_color=THEME_COLORS["text_secondary"])

    def _show(self, frame, name: str):
        for child in self._pages:
            child.grid_forget()
        frame.grid(row=0, column=0, sticky="nsew")
        self._activate_nav(name)

    # --- navigation ------------------------------------------------------
    def navigate(self, key: str):
        {
            "dashboard": self.show_dashboard,
            "encrypt": self.show_encrypt,
            "decrypt": self.show_decrypt,
            "verify": self.show_verify,
            "contacts": self.show_contacts,
            "tools": self.show_tools,
            "settings": self.show_settings,
        }[key]()

    def show_welcome(self):
        self._show(self.welcome_page, "welcome")

    def show_dashboard(self):
        self._show(self.dashboard_page, "dashboard")
        self.dashboard_page.refresh()

    def show_encrypt(self):
        self._show(self.encrypt_page, "encrypt")

    def show_decrypt(self):
        self._show(self.decrypt_page, "decrypt")

    def show_verify(self):
        self._show(self.verify_page, "verify")

    def show_contacts(self):
        self._show(self.contacts_page, "contacts")
        self.contacts_page.refresh()

    def show_tools(self):
        self._show(self.tools_page, "tools")
        self.tools_page.refresh()

    def show_settings(self):
        self._show(self.settings_page, "settings")
        self.settings_page.refresh()

    def refresh_identity(self):
        try:
            self.keystore.ensure_keys()
            fp = self.keystore.get_fingerprint_hex()
        except Exception:
            fp = ""
        self.topbar.set_fingerprint(fp)

    # --- shared helpers for pages -----------------------------------------
    def toast(self, message: str, kind: str = "info", duration_ms: int = 3400):
        self.toast_manager.show(message, kind, duration_ms)

    def save_state(self):
        save_gui_state(self.keystore.base_dir, self.gui_state)

    def bump_stat(self, name: str):
        stats = self.gui_state.setdefault("stats", {})
        stats[name] = stats.get(name, 0) + 1
        self.save_state()

    def get_stat(self, name: str) -> int:
        return self.gui_state.get("stats", {}).get(name, 0)


# =============================================================
# Welcome / first-run onboarding
# =============================================================

class WelcomePage(ctk.CTkFrame):
    STEPS = [
        ("1", "Your identity", "A private/public RSA-4096 key pair was just generated automatically and stored only on this computer."),
        ("2", "Encrypt anything", "Protect a single file or an entire folder with AES-256-GCM — for yourself, or for a saved contact."),
        ("3", "Share safely", "Export your public key so others can send you files that only your private key can open."),
    ]

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        center = ctk.CTkFrame(self, fg_color="transparent", width=560)
        center.grid(row=0, column=0)

        logo_image = load_logo_ctk_image(height=120)
        if logo_image is not None:
            ctk.CTkLabel(center, text="", image=logo_image).pack(pady=(0, 20))

        ctk.CTkLabel(center, text="Welcome to CipherVault", font=ctk.CTkFont(size=30, weight="bold")).pack()
        ctk.CTkLabel(
            center,
            text="Hybrid RSA-4096 + AES-256-GCM encryption for your files and folders.\nEverything runs locally — your keys never leave this computer.",
            font=ctk.CTkFont(size=13), text_color=THEME_COLORS["text_secondary"], justify="center",
        ).pack(pady=(8, 28))

        steps_card = ProCard(center)
        steps_card.pack(fill="x", pady=(0, 28))
        for i, (num, title, desc) in enumerate(self.STEPS):
            row = ctk.CTkFrame(steps_card, fg_color="transparent")
            row.pack(fill="x", padx=22, pady=(18 if i == 0 else 8, 18 if i == len(self.STEPS) - 1 else 8))
            ctk.CTkLabel(row, text=num, font=ctk.CTkFont(size=20, weight="bold"), text_color=THEME_COLORS["accent"], width=32).pack(side="left", padx=(0, 14))
            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(text_col, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w").pack(fill="x")
            ctk.CTkLabel(text_col, text=desc, font=ctk.CTkFont(size=12), text_color=THEME_COLORS["text_secondary"],
                         anchor="w", justify="left", wraplength=440).pack(fill="x", pady=(2, 0))

        ProButton(center, text="Get Started", width=240, command=self.finish).pack()

    def finish(self):
        self.app.gui_state["onboarded"] = True
        self.app.save_state()
        self.app.show_dashboard()


# =============================================================
# Dashboard
# =============================================================

class DashboardPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        page_header(self, "Dashboard", "Your identity, quick actions, and activity at a glance.")

        self.identity_card = ProCard(self)
        self.identity_card.grid(row=1, column=0, sticky="ew", pady=8)
        ctk.CTkLabel(self.identity_card, text="Identity", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(self.identity_card, text="This fingerprint uniquely identifies your public key — share it (or the exported file) so contacts can verify it's really you.",
                     text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12), wraplength=700, justify="left").pack(anchor="w", padx=20, pady=(0, 10))
        self.fp_label = ctk.CTkLabel(self.identity_card, text="--", font=ctk.CTkFont(family="Consolas", size=14))
        self.fp_label.pack(anchor="w", padx=20, pady=(0, 8))
        self.key_paths = ctk.CTkLabel(self.identity_card, text="", text_color=THEME_COLORS["text_secondary"], justify="left")
        self.key_paths.pack(anchor="w", padx=20, pady=(0, 14))
        btn_row = ctk.CTkFrame(self.identity_card, fg_color="transparent")
        btn_row.pack(anchor="w", padx=20, pady=(0, 18))
        ProButton(btn_row, text="Export public key", width=170, command=self.export_pub).pack(side="left", padx=(0, 10))
        GhostButton(btn_row, text="Copy fingerprint", width=150, command=self.copy_fp).pack(side="left")

        ctk.CTkLabel(self, text="Quick actions", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=0, sticky="w", pady=(18, 8))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        self._action_tile(actions, "Encrypt", "Protect a file or folder for yourself or a contact.", self.app.show_encrypt, 0, 0)
        self._action_tile(actions, "Decrypt", "Restore a .cvault container back to its original file.", self.app.show_decrypt, 1, 0)
        self._action_tile(actions, "Verify", "Check a .cvault's signature and integrity without decrypting to disk.", self.app.show_verify, 0, 1)
        self._action_tile(actions, "Contacts", "Manage the people you can encrypt files for.", self.app.show_contacts, 1, 1)

        self.stats_card = ProCard(self)
        self.stats_card.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        self.stats_card.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.contacts_stat = self._stat_block(self.stats_card, "Contacts", "0", 0)
        self.encrypted_stat = self._stat_block(self.stats_card, "Files encrypted", "0", 1)
        self.decrypted_stat = self._stat_block(self.stats_card, "Files decrypted", "0", 2)
        self.keys_stat = self._stat_block(self.stats_card, "Keypair", "Loaded", 3)

    def _action_tile(self, parent, title, desc, command, col, row):
        card = ProCard(parent)
        card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 8 if col == 0 else 0), pady=8)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(size=12), text_color=THEME_COLORS["text_secondary"],
                     justify="left", wraplength=260, anchor="w").pack(anchor="w", padx=18, pady=(0, 14))
        ProButton(card, text=title, command=command).pack(fill="x", padx=18, pady=(0, 18))
        return card

    def _stat_block(self, parent, title, value, col):
        block = ctk.CTkFrame(parent, fg_color="transparent")
        block.grid(row=0, column=col, padx=14, pady=18, sticky="ew")
        ctk.CTkLabel(block, text=title, text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        val = ctk.CTkLabel(block, text=value, font=ctk.CTkFont(size=24, weight="bold"))
        val.pack(anchor="w", pady=(2, 0))
        return val

    def refresh(self):
        try:
            ks = self.app.keystore
            ks.ensure_keys()
            fp = ks.get_fingerprint_hex()
            self.fp_label.configure(text=format_fp(fp))
            self.key_paths.configure(text=f"Private: {ks.private_key_path}\nPublic:  {ks.public_key_path}")
            self.keys_stat.configure(text="Loaded")
        except Exception:
            self.fp_label.configure(text="Unavailable")
            self.keys_stat.configure(text="Error")
        count = len(self.app.contacts_store.list_contacts())
        self.contacts_stat.configure(text=str(count))
        self.encrypted_stat.configure(text=str(self.app.get_stat("encrypted")))
        self.decrypted_stat.configure(text=str(self.app.get_stat("decrypted")))

    def export_pub(self):
        path = filedialog.asksaveasfilename(defaultextension=".pem", initialfile="CipherVault_public_key.pem")
        if not path:
            return
        try:
            Path(path).write_bytes(self.app.keystore.get_public_pem())
            self.app.toast(f"Public key exported to {Path(path).name}", "success")
        except Exception as e:
            self.app.toast(f"Export failed: {e}", "error")

    def copy_fp(self):
        try:
            fp = self.app.keystore.get_fingerprint_hex()
            self.app.clipboard_clear(); self.app.clipboard_append(format_fp(fp)); self.app.update()
            self.app.toast("Fingerprint copied to clipboard", "success")
        except Exception as e:
            self.app.toast(f"Copy failed: {e}", "error")


# =============================================================
# Encrypt
# =============================================================

class EncryptPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        page_header(self, "Encrypt", "Protect a file or an entire folder using RSA-4096 + AES-256-GCM hybrid "
                                      "encryption. Choose yourself as the recipient to keep it private, or a "
                                      "saved contact to share it securely.")

        self.card = ProCard(self)
        self.card.grid(row=1, column=0, sticky="ew", pady=8)

        self.file_label = ctk.CTkLabel(self.card, text="No file or folder selected", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=13, weight="bold"))
        self.file_label.pack(anchor="w", padx=20, pady=(20, 2))
        self.detail_label = ctk.CTkLabel(self.card, text="", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12))
        self.detail_label.pack(anchor="w", padx=20, pady=(0, 8))

        self.drop = DropZone(
            self.card,
            title="Drop a file or folder here to encrypt",
            subtitle="Any format works. Folders of any size are zipped automatically",
            on_browse=self.select_file,
            on_drop=self.on_drop_file,
            browse_label="Choose file",
        )
        self.drop.pack(fill="x", padx=16, pady=(4, 4))
        GhostButton(self.card, text="Choose a folder instead", command=self.select_folder, width=200).pack(anchor="w", padx=20, pady=(0, 16))

        opts = ctk.CTkFrame(self.card, fg_color="transparent")
        opts.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkLabel(opts, text="Recipient", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(opts, text="Keep it for yourself, or pick a saved contact to encrypt it for their key instead.",
                     font=ctk.CTkFont(size=12), text_color=THEME_COLORS["text_secondary"]).pack(anchor="w", pady=(2, 6))
        self.recipient_var = ctk.StringVar(value=SELF_RECIPIENT_LABEL)
        self.recipient_menu = ctk.CTkOptionMenu(opts, variable=self.recipient_var, values=[SELF_RECIPIENT_LABEL], width=280, fg_color=THEME_COLORS["muted"], button_color=THEME_COLORS["accent"], button_hover_color=THEME_COLORS["accent_hover"])
        self.recipient_menu.pack(anchor="w")

        self.action_btn = ProButton(self.card, text="Encrypt", state="disabled", command=self.run)
        self.action_btn.pack(fill="x", padx=20, pady=(18, 14))

        self.status = TaskStatus(self.card)
        self.status.pack(fill="x", padx=16, pady=(0, 18))

        self.selected_path: Path | None = None
        self.is_folder: bool = False
        self.refresh_contacts()

    def refresh_contacts(self):
        contacts = self.app.contacts_store.list_contacts()
        names = [SELF_RECIPIENT_LABEL] + [c["name"] for c in contacts]
        self.recipient_menu.configure(values=names)

    def select_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.set_selected(path, is_folder=False)

    def select_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.set_selected(path, is_folder=True)

    def on_drop_file(self, path: Path):
        p = Path(path)
        self.set_selected(p, is_folder=p.is_dir())

    def set_selected(self, path: str | Path, is_folder: bool = False):
        p = Path(path)
        if is_folder:
            if not p.exists() or not p.is_dir():
                messagebox.showwarning("Invalid selection", "Please choose a folder.")
                return
        elif not p.exists() or not p.is_file():
            messagebox.showwarning("Invalid selection", "Please choose a file.")
            return
        name = p.name + ("/" if is_folder else "")
        self.selected_path = p
        self.is_folder = is_folder
        self.file_label.configure(text=name, text_color=THEME_COLORS["accent"])
        if hasattr(self, "drop"):
            self.drop.set_text(name)
        self.action_btn.configure(state="normal")
        self.status.set_state("Ready", "idle")
        self.refresh_contacts()

        if is_folder:
            self.detail_label.configure(text="Scanning folder…")
            threading.Thread(target=self._scan_folder, args=(p,), daemon=True).start()
        else:
            try:
                self.detail_label.configure(text=human_size(p.stat().st_size))
            except OSError:
                self.detail_label.configure(text="")

    def _scan_folder(self, folder: Path):
        count = 0
        total = 0
        try:
            for f in folder.rglob("*"):
                if f.is_file():
                    count += 1
                    try:
                        total += f.stat().st_size
                    except OSError:
                        pass
        except Exception:
            pass
        if self.selected_path == folder:
            self.after(0, lambda: self.detail_label.configure(text=f"{count:,} files \u2022 {human_size(total)} total"))

    def run(self):
        if not self.selected_path:
            return
        self.action_btn.configure(state="disabled")
        self.status.set_state("Zipping folder..." if self.is_folder else "Encrypting...", "running")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        temp_zip = None
        try:
            input_path = self.selected_path
            out_hint = None
            if self.is_folder:
                temp_zip = zip_folder(self.selected_path)
                out_hint = self.selected_path.parent / f"{self.selected_path.name}.zip.cvault"
                input_path = temp_zip
                self.after(0, lambda: self.status.set_state("Encrypting...", "running"))

            recipient = self.recipient_var.get()
            if recipient == SELF_RECIPIENT_LABEL:
                out = self.app.encryptor.encrypt_file(input_path, out_hint)
            else:
                contacts = self.app.contacts_store.list_contacts()
                contact = next((c for c in contacts if c.get("name") == recipient), None)
                if not contact:
                    raise ValueError("Contact not found")
                out = self.app.encryptor.encrypt_for_contact(input_path, contact["public_pem"].encode("utf-8"), out_hint, recipient_name=recipient)
            self.after(0, lambda o=out: self._done(o))
        except Exception as e:
            self.after(0, lambda err=e: self._error(err))
        finally:
            if temp_zip:
                cleanup_temp_zip(temp_zip)

    def _done(self, out: Path):
        self.app.bump_stat("encrypted")
        self.app.toast(f"Encrypted successfully \u2014 {out.name}", "success")
        self.selected_path = None
        self.is_folder = False
        self.file_label.configure(text="No file or folder selected", text_color=THEME_COLORS["text_secondary"])
        self.detail_label.configure(text="")
        self.action_btn.configure(state="disabled")
        self.status.set_state("Encrypted", "success")

    def _error(self, err: Exception):
        self.app.toast(f"Encryption failed: {err}", "error", 5000)
        self.status.set_state("Failed", "error")
        self.action_btn.configure(state="normal")


# =============================================================
# Decrypt
# =============================================================

class DecryptPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        page_header(self, "Decrypt", "Restore a .cvault container back to the original file. CipherVault checks "
                                      "that the container was encrypted for your key before it decrypts anything.")

        self.card = ProCard(self)
        self.card.grid(row=1, column=0, sticky="ew", pady=8)
        self.file_label = ctk.CTkLabel(self.card, text="No .cvault selected", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=13, weight="bold"))
        self.file_label.pack(anchor="w", padx=20, pady=(20, 8))
        self.drop = DropZone(
            self.card,
            title="Drop a .cvault file here to decrypt",
            subtitle="Restores the original file next to it",
            on_browse=self.select_file,
            on_drop=self.on_drop_file,
            browse_label="Choose .cvault file",
        )
        self.drop.pack(fill="x", padx=16, pady=(4, 16))

        self.action_btn = ProButton(self.card, text="Decrypt", state="disabled", command=self.run)
        self.action_btn.pack(fill="x", padx=20, pady=(4, 14))

        self.status = TaskStatus(self.card)
        self.status.pack(fill="x", padx=16, pady=(0, 18))

        self.selected_file: Path | None = None

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("CipherVault", "*.cvault")])
        if path:
            self.set_selected(path)

    def on_drop_file(self, path: Path):
        self.set_selected(path)

    def set_selected(self, path: str | Path):
        p = Path(path)
        if not p.exists() or not p.is_file():
            messagebox.showwarning("Invalid selection", "Please drop a file.")
            return
        if p.suffix.lower() != ".cvault":
            messagebox.showwarning("Invalid selection", "Expecting a .cvault file.")
            return
        self.selected_file = p
        name = p.name
        self.file_label.configure(text=name, text_color=THEME_COLORS["success"])
        if hasattr(self, "drop"):
            self.drop.set_text(name)
        self.action_btn.configure(state="normal")
        self.status.set_state("Ready", "idle")

    def run(self):
        if not self.selected_file:
            return
        self.action_btn.configure(state="disabled")
        self.status.set_state("Decrypting...", "running")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            out = self.app.encryptor.decrypt_file(self.selected_file)
            self.after(0, lambda o=out: self._done(o))
        except Exception as e:
            self.after(0, lambda err=e: self._error(err))

    def _done(self, out: Path):
        self.app.bump_stat("decrypted")
        self.app.toast(f"Decrypted successfully \u2014 {out.name}", "success")
        self.selected_file = None
        self.file_label.configure(text="No .cvault selected", text_color=THEME_COLORS["text_secondary"])
        self.action_btn.configure(state="disabled")
        self.status.set_state("Decrypted", "success")

    def _error(self, err: Exception):
        self.app.toast(f"Decryption failed: {err}", "error", 5000)
        self.status.set_state("Failed", "error")
        self.action_btn.configure(state="normal")


# =============================================================
# Verify
# =============================================================

class VerifyPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        page_header(self, "Verify", "Check a .cvault's signature and integrity without writing the decrypted "
                                     "file to disk \u2014 useful before you trust a file someone sent you.")

        self.card = ProCard(self)
        self.card.grid(row=1, column=0, sticky="ew", pady=8)
        self.file_label = ctk.CTkLabel(self.card, text="No .cvault selected", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=13, weight="bold"))
        self.file_label.pack(anchor="w", padx=20, pady=(20, 8))
        self.drop = DropZone(
            self.card,
            title="Drop a .cvault file here to verify",
            subtitle="Signature & integrity report, nothing written to disk",
            on_browse=self.select_file,
            on_drop=self.on_drop_file,
            browse_label="Choose .cvault file",
        )
        self.drop.pack(fill="x", padx=16, pady=(4, 12))

        self.result = ctk.CTkTextbox(self.card, height=220, fg_color=THEME_COLORS["bg_dark"], text_color=THEME_COLORS["text_primary"], font=ctk.CTkFont(family="Consolas", size=12))
        self.result.pack(fill="x", padx=16, pady=(0, 12))

        self.status = TaskStatus(self.card)
        self.status.pack(fill="x", padx=16, pady=(0, 18))

        self.selected_file: Path | None = None

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("CipherVault", "*.cvault")])
        if path:
            self.set_selected(path, auto_run=True)

    def on_drop_file(self, path: Path):
        self.set_selected(path, auto_run=True)

    def set_selected(self, path: str | Path, auto_run: bool = False):
        p = Path(path)
        if not p.exists() or not p.is_file():
            messagebox.showwarning("Invalid selection", "Please drop a .cvault file.")
            return
        if p.suffix.lower() != ".cvault":
            messagebox.showwarning("Invalid selection", "Expecting a .cvault file.")
            return
        name = p.name
        self.selected_file = p
        self.file_label.configure(text=name, text_color=THEME_COLORS["accent"])
        if hasattr(self, "drop"):
            self.drop.set_text(name)
        if auto_run:
            self.run()

    def run(self):
        if not self.selected_file:
            return
        self.result.delete("1.0", "end")
        self.status.set_state("Verifying...", "running")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            info = self.app.encryptor.inspect_file(self.selected_file)
            verdict = self.app.encryptor.verify_authenticity(self.selected_file)
            report = [
                f"File: {info['filename']}",
                f"Size: {info['size']} bytes",
                f"Version: {info['version']}",
                f"For me: {'YES' if info['is_for_me'] else 'NO'}",
                f"Sender FP: {info['sender_fp']}",
                f"Recipient FP: {info['recipient_fp']}",
                f"Integrity (AES-GCM): {'VALID' if verdict['integrity_ok'] else 'INVALID'}",
                f"Authenticity (RSA-PSS): {'VALID' if verdict['authenticity_ok'] else 'INVALID'}",
            ]
            text = "\n".join(report)
            ok = verdict.get("integrity_ok") and verdict.get("authenticity_ok")
            self.after(0, lambda t=text, ok=ok: self._done(t, ok))
        except Exception as e:
            self.after(0, lambda err=e: self._error(err))

    def _done(self, text: str, ok: bool):
        self.result.insert("1.0", text)
        self.status.set_state("Verified" if ok else "Check failed", "success" if ok else "error")
        self.app.toast("File is authentic and intact" if ok else "Verification failed \u2014 see report", "success" if ok else "error")

    def _error(self, err: Exception):
        self.result.insert("1.0", f"Error: {err}")
        self.status.set_state("Failed", "error")
        self.app.toast(f"Verification error: {err}", "error", 5000)


# =============================================================
# Contacts
# =============================================================

class ContactsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = page_header(self, "Contacts", "People you can encrypt files for. Add a contact's public key once, "
                                                "then pick them as a recipient from the Encrypt page.")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        add_row = ctk.CTkFrame(self, fg_color="transparent")
        add_row.grid(row=1, column=0, sticky="e", pady=(0, 14))
        ProButton(add_row, text="+ Add contact", width=150, command=self.open_add_dialog).pack(side="right")

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.grid(row=2, column=0, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        contacts = self.app.contacts_store.list_contacts()
        if not contacts:
            empty = ProCard(self.list_frame)
            empty.pack(fill="x", pady=30)
            ctk.CTkLabel(empty, text="No contacts yet", font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(24, 4))
            ctk.CTkLabel(empty, text="Add a contact's public key (.pem) to start sending them encrypted files.",
                         text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12)).pack(pady=(0, 16))
            ProButton(empty, text="+ Add your first contact", width=200, command=self.open_add_dialog).pack(pady=(0, 24))
            return
        for contact in contacts:
            self._row(contact)

    def _row(self, contact):
        card = ProCard(self.list_frame)
        card.pack(fill="x", padx=4, pady=6)
        card.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=16, pady=14)
        avatar = ctk.CTkFrame(left, width=42, height=42, corner_radius=21, fg_color=THEME_COLORS["accent"])
        avatar.pack(side="left", padx=(0, 14))
        avatar.pack_propagate(False)
        ctk.CTkLabel(avatar, text=contact["name"][0].upper(), text_color=THEME_COLORS["accent_text"], font=ctk.CTkFont(weight="bold")).place(relx=0.5, rely=0.5, anchor="center")
        info = ctk.CTkFrame(left, fg_color="transparent")
        info.pack(side="left")
        ctk.CTkLabel(info, text=contact["name"], font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(info, text=contact.get("fingerprint", "")[:32] + "...", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(family="Consolas", size=12)).pack(anchor="w")

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e", padx=14)
        GhostButton(actions, text="Copy FP", width=90, command=lambda c=contact: self.copy_fp(c)).pack(side="left", padx=4)
        GhostButton(actions, text="Delete", width=90, command=lambda c=contact: self.delete_contact(c)).pack(side="left", padx=4)

    def copy_fp(self, contact):
        fp = contact.get("fingerprint", "")
        if not fp:
            self.app.toast("Fingerprint not available", "warning")
            return
        self.app.clipboard_clear(); self.app.clipboard_append(fp); self.app.update()
        self.app.toast(f"Fingerprint copied for {contact['name']}", "success")

    def delete_contact(self, contact):
        if messagebox.askyesno("Delete contact", f"Delete {contact['name']}? This cannot be undone."):
            self.app.contacts_store.delete_contact(contact["name"])
            self.app.toast(f"{contact['name']} removed", "info")
            self.refresh()

    def open_add_dialog(self):
        AddContactDialog(self)


class AddContactDialog(ctk.CTkToplevel):
    def __init__(self, parent: ContactsPage):
        super().__init__(parent)
        self.parent = parent
        self.title("Add contact")
        self.geometry("540x560")
        self.configure(fg_color=THEME_COLORS["bg_dark"])
        self.grid_columnconfigure(0, weight=1)
        self.transient(parent.winfo_toplevel())

        ctk.CTkLabel(self, text="Add a contact", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, pady=(22, 4), padx=26, sticky="w")
        ctk.CTkLabel(self, text="Paste their public key (.pem) or load it from a file. You'll then be able to "
                                 "pick them as a recipient when encrypting.",
                     text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12), wraplength=480, justify="left").grid(row=1, column=0, padx=26, sticky="w", pady=(0, 14))

        self.name_entry = ctk.CTkEntry(self, placeholder_text="Contact name", height=38)
        self.name_entry.grid(row=2, column=0, padx=26, pady=(0, 12), sticky="ew")

        self.pem_box = ctk.CTkTextbox(self, height=220, fg_color=THEME_COLORS["bg_card"])
        self.pem_box.grid(row=3, column=0, padx=26, pady=(4, 8), sticky="nsew")
        self.grid_rowconfigure(3, weight=1)
        GhostButton(self, text="Load PEM from file", command=self.load_file).grid(row=4, column=0, padx=26, pady=(8, 4), sticky="w")
        ProButton(self, text="Save contact", command=self.save).grid(row=5, column=0, padx=26, pady=22)

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("PEM", "*.pem"), ("All", "*.*")])
        if path:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
            self.pem_box.delete("1.0", "end")
            self.pem_box.insert("1.0", text)

    def save(self):
        name = self.name_entry.get().strip()
        pem = self.pem_box.get("1.0", "end").strip()
        if not name or not pem:
            messagebox.showwarning("Missing information", "Please provide both a name and a public key.")
            return
        try:
            self.parent.app.contacts_store.add_contact(name, pem)
            self.parent.refresh()
            self.parent.app.toast(f"{name} added to contacts", "success")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Could not add contact", str(e))


# =============================================================
# Tools
# =============================================================

class ToolsPage(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure((0, 1), weight=1)

        page_header(self, "Tools", "Inspect your keys and check whether a file has been altered.", columnspan=2)

        # Keys card
        self.keys_card = ProCard(self)
        self.keys_card.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=8)
        ctk.CTkLabel(self.keys_card, text="Your keys", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(16, 6))
        self.keys_info = ctk.CTkLabel(self.keys_card, text="", justify="left", text_color=THEME_COLORS["text_primary"])
        self.keys_info.pack(anchor="w", padx=18, pady=(0, 10))
        btns = ctk.CTkFrame(self.keys_card, fg_color="transparent")
        btns.pack(anchor="w", padx=18, pady=(0, 16))
        ProButton(btns, text="Export public key", width=160, command=self.export_pub).pack(side="left", padx=(0, 8))
        GhostButton(btns, text="Copy fingerprint", width=150, command=self.copy_fp).pack(side="left")

        # Public key viewer
        self.pub_card = ProCard(self)
        self.pub_card.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=8)
        ctk.CTkLabel(self.pub_card, text="Public key (PEM)", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=18, pady=(16, 6))
        self.pub_box = ctk.CTkTextbox(self.pub_card, height=170, fg_color=THEME_COLORS["bg_dark"], font=ctk.CTkFont(family="Consolas", size=11))
        self.pub_box.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        row = ctk.CTkFrame(self.pub_card, fg_color="transparent")
        row.pack(anchor="w", padx=14, pady=(0, 14))
        GhostButton(row, text="Copy", width=90, command=self.copy_pub).pack(side="left")

        # Compare files
        self.compare_card = ProCard(self)
        self.compare_card.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=8)
        ctk.CTkLabel(self.compare_card, text="Compare two files (SHA-256)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(self.compare_card, text="Confirms two files are byte-for-byte identical.", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18, pady=(0, 10))
        self.file_a = ctk.StringVar(value="File A: not selected")
        self.file_b = ctk.StringVar(value="File B: not selected")
        self.label_a = ctk.CTkLabel(self.compare_card, textvariable=self.file_a, text_color=THEME_COLORS["text_secondary"])
        self.label_a.pack(anchor="w", padx=18)
        register_drop(self.label_a, lambda e: self._on_drop_compare("a", e))
        GhostButton(self.compare_card, text="Select File A", command=self.pick_a).pack(anchor="w", padx=18, pady=4)
        self.label_b = ctk.CTkLabel(self.compare_card, textvariable=self.file_b, text_color=THEME_COLORS["text_secondary"])
        self.label_b.pack(anchor="w", padx=18, pady=(6, 0))
        register_drop(self.label_b, lambda e: self._on_drop_compare("b", e))
        GhostButton(self.compare_card, text="Select File B", command=self.pick_b).pack(anchor="w", padx=18, pady=4)
        ProButton(self.compare_card, text="Compare", command=self.compare).pack(fill="x", padx=18, pady=(10, 8))
        self.compare_result = ctk.CTkLabel(self.compare_card, text="", text_color=THEME_COLORS["text_primary"], justify="left")
        self.compare_result.pack(anchor="w", padx=18, pady=(0, 16))

        # Compare with vault
        self.vault_card = ProCard(self)
        self.vault_card.grid(row=2, column=1, sticky="nsew", padx=(8, 0), pady=8)
        ctk.CTkLabel(self.vault_card, text="Compare a plain file with a .cvault", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(self.vault_card, text="Decrypts the container in memory and compares it to a file you have.", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12)).pack(anchor="w", padx=18, pady=(0, 10))
        self.vault_path = ctk.StringVar(value="Vault: not selected")
        self.plain_path = ctk.StringVar(value="Plain file: not selected")
        self.label_vault = ctk.CTkLabel(self.vault_card, textvariable=self.vault_path, text_color=THEME_COLORS["text_secondary"])
        self.label_vault.pack(anchor="w", padx=18)
        register_drop(self.label_vault, self._on_drop_vault)
        GhostButton(self.vault_card, text="Select .cvault", command=self.pick_vault).pack(anchor="w", padx=18, pady=4)
        self.label_plain = ctk.CTkLabel(self.vault_card, textvariable=self.plain_path, text_color=THEME_COLORS["text_secondary"])
        self.label_plain.pack(anchor="w", padx=18, pady=(6, 0))
        register_drop(self.label_plain, self._on_drop_plain)
        GhostButton(self.vault_card, text="Select plain file", command=self.pick_plain).pack(anchor="w", padx=18, pady=4)
        ProButton(self.vault_card, text="Compare with vault", command=self.compare_with_vault).pack(fill="x", padx=18, pady=(10, 8))
        self.vault_status = TaskStatus(self.vault_card)
        self.vault_status.pack(fill="x", padx=14, pady=(0, 8))
        self.vault_result = ctk.CTkLabel(self.vault_card, text="", text_color=THEME_COLORS["text_primary"], justify="left")
        self.vault_result.pack(anchor="w", padx=18, pady=(0, 16))

        self.path_a: Path | None = None
        self.path_b: Path | None = None
        self.path_vault: Path | None = None
        self.path_plain: Path | None = None

    def refresh(self):
        try:
            ks = self.app.keystore; ks.ensure_keys()
            fp = ks.get_fingerprint_hex()
            self.keys_info.configure(text=f"Base: {ks.base_dir}\nPrivate: {ks.private_key_path}\nPublic:  {ks.public_key_path}\nFingerprint: {format_fp(fp)}")
            self.pub_box.delete("1.0", "end")
            self.pub_box.insert("1.0", ks.get_public_pem().decode("utf-8", errors="ignore"))
        except Exception:
            self.keys_info.configure(text="Keys unavailable")
            self.pub_box.delete("1.0", "end")

    def export_pub(self):
        path = filedialog.asksaveasfilename(defaultextension=".pem", initialfile="CipherVault_public_key.pem")
        if not path:
            return
        try:
            Path(path).write_bytes(self.app.keystore.get_public_pem())
            self.app.toast(f"Public key exported to {Path(path).name}", "success")
        except Exception as e:
            self.app.toast(f"Export failed: {e}", "error")

    def copy_fp(self):
        try:
            fp = self.app.keystore.get_fingerprint_hex()
            self.app.clipboard_clear(); self.app.clipboard_append(format_fp(fp)); self.app.update()
            self.app.toast("Fingerprint copied", "success")
        except Exception as e:
            self.app.toast(f"Copy failed: {e}", "error")

    def copy_pub(self):
        text = self.pub_box.get("1.0", "end").strip()
        if not text:
            return
        self.app.clipboard_clear(); self.app.clipboard_append(text); self.app.update()
        self.app.toast("Public key copied", "success")

    def pick_a(self):
        path = filedialog.askopenfilename()
        if path:
            self._set_compare("a", Path(path))

    def pick_b(self):
        path = filedialog.askopenfilename()
        if path:
            self._set_compare("b", Path(path))

    def _on_drop_compare(self, slot: str, event):
        path = normalize_dnd_path(getattr(event, "data", ""))
        if path and path.exists() and path.is_file():
            self._set_compare(slot, path)

    def _set_compare(self, slot: str, path: Path):
        if slot == "a":
            self.path_a = path; self.file_a.set(f"File A: {path.name}")
        else:
            self.path_b = path; self.file_b.set(f"File B: {path.name}")

    def compare(self):
        if not self.path_a or not self.path_b:
            messagebox.showwarning("Missing files", "Select both files to compare.")
            return
        try:
            ha = hashlib.sha256(self.path_a.read_bytes()).hexdigest()
            hb = hashlib.sha256(self.path_b.read_bytes()).hexdigest()
            same = ha == hb
            self.compare_result.configure(text=f"Match: {'YES' if same else 'NO'}\nSHA256 A: {ha}\nSHA256 B: {hb}")
        except Exception as e:
            self.app.toast(f"Compare failed: {e}", "error")

    def pick_vault(self):
        path = filedialog.askopenfilename(filetypes=[("CipherVault", "*.cvault")])
        if path:
            self._set_vault(Path(path))

    def pick_plain(self):
        path = filedialog.askopenfilename()
        if path:
            self._set_plain(Path(path))

    def _on_drop_vault(self, event):
        path = normalize_dnd_path(getattr(event, "data", ""))
        if path and path.exists() and path.is_file():
            self._set_vault(path)

    def _on_drop_plain(self, event):
        path = normalize_dnd_path(getattr(event, "data", ""))
        if path and path.exists() and path.is_file():
            self._set_plain(path)

    def _set_vault(self, path: Path):
        if path.suffix.lower() != ".cvault":
            messagebox.showwarning("Invalid selection", "Expecting a .cvault file.")
            return
        self.path_vault = path; self.vault_path.set(f"Vault: {path.name}")

    def _set_plain(self, path: Path):
        self.path_plain = path; self.plain_path.set(f"Plain: {path.name}")

    def compare_with_vault(self):
        if not self.path_vault or not self.path_plain:
            messagebox.showwarning("Missing files", "Select both a .cvault and a plain file.")
            return
        self.vault_status.set_state("Comparing...", "running")
        self.vault_result.configure(text="")
        threading.Thread(target=self._compare_worker, daemon=True).start()

    def _compare_worker(self):
        try:
            vault_bytes, meta = self.app.encryptor.decrypt_to_bytes(self.path_vault)
            plain_bytes = self.path_plain.read_bytes()
            h_v = hashlib.sha256(vault_bytes).hexdigest()
            h_p = hashlib.sha256(plain_bytes).hexdigest()
            same = h_v == h_p
            text = f"Match: {'YES' if same else 'NO'}\nVault SHA256: {h_v}\nPlain SHA256: {h_p}\nOriginal name: {meta.get('filename')}"
            self.after(0, lambda t=text, same=same: self._compare_done(t, same))
        except Exception as e:
            self.after(0, lambda err=e: self._compare_error(err))

    def _compare_done(self, text: str, same: bool):
        self.vault_status.set_state("Done", "success" if same else "error")
        self.vault_result.configure(text=text)

    def _compare_error(self, err: Exception):
        self.vault_status.set_state("Failed", "error")
        self.vault_result.configure(text=f"Error: {err}")


# =============================================================
# Settings
# =============================================================

class SettingsPage(ctk.CTkScrollableFrame):
    """App info + manual update check/apply, so the GUI stays current
    even when launched without going through the auto-update launcher."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure((0, 1), weight=1)

        page_header(self, "Settings", "Application version, updates, and where your data is stored.", columnspan=2)

        self.update_card = ProCard(self)
        self.update_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)
        ctk.CTkLabel(self.update_card, text="Application updates", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(18, 4))

        self.version_lbl = ctk.CTkLabel(self.update_card, text=f"Current version: {__version__}", font=ctk.CTkFont(size=18, weight="bold"))
        self.version_lbl.pack(anchor="w", padx=20, pady=(0, 10))

        if not UPDATER_AVAILABLE:
            ctk.CTkLabel(self.update_card, text="Auto-update module not found (launcher/updater.py missing).", text_color=THEME_COLORS["warning"]).pack(anchor="w", padx=20, pady=(0, 16))
        else:
            btn_row = ctk.CTkFrame(self.update_card, fg_color="transparent")
            btn_row.pack(anchor="w", padx=20, pady=(0, 10))
            self.check_btn = ProButton(btn_row, text="Check for updates", width=180, command=self.check_updates)
            self.check_btn.pack(side="left", padx=(0, 10))
            self.update_btn = ProButton(btn_row, text="Update now", width=140, state="disabled", fg_color=THEME_COLORS["muted"], command=self.apply_update)
            self.update_btn.pack(side="left")

            self.status = TaskStatus(self.update_card)
            self.status.pack(fill="x", padx=16, pady=(0, 16))

        self.about_card = ProCard(self)
        self.about_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        ctk.CTkLabel(self.about_card, text="About CipherVault", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(self.about_card,
                     text="CipherVault protects files with RSA-4096 + AES-256-GCM hybrid encryption and RSA-PSS "
                          "signatures. All keys and contacts stay on this computer \u2014 nothing is ever uploaded.",
                     text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12), wraplength=760, justify="left").pack(anchor="w", padx=20, pady=(0, 12))
        GhostButton(self.about_card, text="Show welcome guide again", width=220, command=self.app.show_welcome).pack(anchor="w", padx=20, pady=(0, 16))

        self.info_card = ProCard(self)
        self.info_card.grid(row=3, column=0, columnspan=2, sticky="ew", pady=8)
        ctk.CTkLabel(self.info_card, text="Data location", text_color=THEME_COLORS["text_secondary"], font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(18, 4))
        self.data_lbl = ctk.CTkLabel(self.info_card, text="", justify="left", text_color=THEME_COLORS["text_primary"], font=ctk.CTkFont(family="Consolas", size=12))
        self.data_lbl.pack(anchor="w", padx=20, pady=(0, 18))

        self._remote_version = None

    def refresh(self):
        self.version_lbl.configure(text=f"Current version: {__version__}")
        ks = self.app.keystore
        self.data_lbl.configure(text=f"Keys & contacts stored in: {ks.base_dir}")

    def check_updates(self):
        self.check_btn.configure(state="disabled")
        self.update_btn.configure(state="disabled", fg_color=THEME_COLORS["muted"])
        self.status.set_state("Checking for updates...", "running")
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        try:
            has_update, local_v, remote_v = update_engine.check_for_update()
            self.after(0, lambda: self._check_done(has_update, local_v, remote_v))
        except Exception as e:
            self.after(0, lambda err=e: self._check_error(err))

    def _check_done(self, has_update: bool, local_v: str, remote_v: str | None):
        self.check_btn.configure(state="normal")
        if has_update:
            self._remote_version = remote_v
            self.status.set_state(f"Update available: v{remote_v}", "success")
            self.update_btn.configure(state="normal", fg_color=THEME_COLORS["accent"])
            self.app.toast(f"Update available: v{remote_v}", "info")
        else:
            self.status.set_state(f"Up to date (v{local_v})" if remote_v else "Up to date (offline check)", "idle")

    def _check_error(self, err: Exception):
        self.check_btn.configure(state="normal")
        self.status.set_state(f"Check failed: {err}", "error")

    def apply_update(self):
        if not messagebox.askyesno("Update CipherVault", f"Download and install version {self._remote_version}?\nThe app will restart automatically."):
            return
        self.update_btn.configure(state="disabled")
        self.check_btn.configure(state="disabled")
        self.status.set_state("Downloading update...", "running")
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self):
        try:
            success, msg = update_engine.apply_update()
            self.after(0, lambda: self._apply_done(success, msg))
        except Exception as e:
            self.after(0, lambda err=e: self._apply_error(err))

    def _apply_done(self, success: bool, msg: str):
        self.check_btn.configure(state="normal")
        if success:
            self.status.set_state("Updated. Restarting...", "success")
            self.app.toast(f"{msg} Restarting\u2026", "success", 2500)
            self.app.after(800, self._restart_app)
        else:
            self.status.set_state(msg, "error")
            messagebox.showerror("Update failed", msg)

    def _apply_error(self, err: Exception):
        self.check_btn.configure(state="normal")
        self.status.set_state(f"Update failed: {err}", "error")
        messagebox.showerror("Update failed", str(err))

    def _restart_app(self):
        """Re-launch the (now updated) GUI script in a new process, then exit this one."""
        try:
            python_exe = sys.executable
            script = str(Path(__file__).resolve())
            subprocess.Popen([python_exe, script], cwd=str(BASE_DIR))
        except Exception:
            pass
        self.app.destroy()


if __name__ == "__main__":
    app = CipherVaultApp()
    app.mainloop()
