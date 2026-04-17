import os
import platform
import time
import urllib.parse
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    _USE_WEBDRIVER_MANAGER = True
except ImportError:
    _USE_WEBDRIVER_MANAGER = False

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# ── Appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

# ── App Config ────────────────────────────────────────────────────────────────
APP_TITLE = "WhatsApp Studio Notifier"
if platform.system() == "Windows":
    BOT_PROFILE_DIR = r"C:\WhatsAppBotProfile"
else:
    BOT_PROFILE_DIR = os.path.join(os.path.expanduser("~"), "WhatsAppBotProfile")
MIN_DELAY    = 1.5
SEND_TIMEOUT = 25

# Physical key codes — hardware position, same regardless of keyboard language (Hebrew/English)
# Windows/Linux: Virtual-Key codes match ASCII uppercase letters
# macOS:         Cocoa key codes are completely different
if platform.system() == "Darwin":
    _KC_V, _KC_C, _KC_X, _KC_A = 9, 8, 7, 0
else:
    _KC_V, _KC_C, _KC_X, _KC_A = 86, 67, 88, 65

# Modifier state bits in Tkinter event.state
_MOD_CTRL = 0x4                                          # Ctrl on all platforms
_MOD_CMD  = 0x8 if platform.system() == "Darwin" else 0 # Command (⌘) on Mac only

# ── Design Tokens ─────────────────────────────────────────────────────────────
BG       = "#eef2ee"
CARD     = "#ffffff"
FIELD    = "#f4f8f5"
ACCENT   = "#006b47"
A_DARK   = "#004d34"
A_LIGHT  = "#d6efe3"
DANGER   = "#ba1a1a"
D_DARK   = "#93000a"
D_LIGHT  = "#ffdad6"
TEXT     = "#171d19"
MUTED    = "#4a6355"
BORDER   = "#c8d8cc"
HDR_BG   = "#006b47"
HDR_DK   = "#004d34"
LOG_BG   = "#111f18"
LOG_OK   = "#4ade80"
LOG_ERR  = "#ff8a80"
LOG_WRN  = "#ffd54f"
FONT     = "Segoe UI"

# Fonts are created inside __init__ after the root window exists
F_BODY = F_SMALL = F_LABEL = F_TITLE = F_CTA = F_LOG = None


# ── Phone helpers ─────────────────────────────────────────────────────────────

def parse_phone_numbers(raw: str) -> list[str]:
    raw = raw.replace(",", " ").replace(";", " ").replace("\t", " ")
    out, seen = [], set()
    for part in raw.split():
        n = "".join(c for c in part if c.isdigit() or c == "+")
        if len(n) >= 7 and n not in seen:
            seen.add(n); out.append(n)
    return out

def normalize_il_number(phone: str) -> str:
    phone = "".join(c for c in phone if c.isdigit() or c == "+").strip()
    if phone.startswith("+"): phone = phone[1:]
    if phone.startswith("972"): return phone
    if phone.startswith("0"):   return "972" + phone[1:]
    return phone


# ── Main App ──────────────────────────────────────────────────────────────────

class WhatsAppApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1160x760")
        self.root.minsize(960, 680)
        self.root.configure(fg_color=BG)

        self._is_sending   = False
        self._stop_event   = threading.Event()
        self._login_driver = None

        self.delay_var          = tk.StringVar(value="3")
        self.manual_confirm_var = tk.BooleanVar(value=False)
        self._progress_var      = tk.DoubleVar(value=0)
        self._nums_badge_var    = tk.StringVar(value="0 מספרים")

        # Create fonts here, after the root window exists
        global F_BODY, F_SMALL, F_LABEL, F_TITLE, F_CTA, F_LOG
        F_BODY  = ctk.CTkFont(family=FONT, size=13)
        F_SMALL = ctk.CTkFont(family=FONT, size=10)
        F_LABEL = ctk.CTkFont(family=FONT, size=11, weight="bold")
        F_TITLE = ctk.CTkFont(family=FONT, size=17, weight="bold")
        F_CTA   = ctk.CTkFont(family=FONT, size=14, weight="bold")
        F_LOG   = ctk.CTkFont(family="Consolas", size=9)

        self._set_app_icon()
        self._build_ui()

    # ── Icon ──────────────────────────────────────────────────────────────────

    def _set_app_icon(self):
        base = os.path.dirname(os.path.abspath(__file__))
        for name in ("logo_icon.png", "logo.png"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                try:
                    if _HAS_PIL:
                        pil = Image.open(p).resize((256, 256), Image.LANCZOS)
                        self._icon_ref = ImageTk.PhotoImage(pil)
                        self.root.iconphoto(True, self._icon_ref)
                        if platform.system() == "Windows":
                            ico = os.path.join(base, "logo_icon.ico")
                            if not os.path.exists(ico):
                                pil.save(ico, format="ICO",
                                         sizes=[(16,16),(32,32),(48,48),(64,64),(256,256)])
                            try: self.root.iconbitmap(ico)
                            except Exception: pass
                        return
                except Exception:
                    pass

    # ── Text-widget helpers ───────────────────────────────────────────────────

    def _bind_text_widget(self, ctk_box: ctk.CTkTextbox):
        """RTL display fix + full clipboard shortcuts on a CTkTextbox."""
        w = ctk_box._textbox   # underlying tk.Text

        # ── RTL / BiDi helpers ────────────────────────────────────────────────

        def _rtl(*_):
            w.tag_add("rtl", "1.0", "end")

        _bidi_busy = [False]   # guard against re-entrant calls

        def _force_bidi_render():
            """
            Fix: Hebrew chars display scrambled (e.g. שלום → וםשל) until Space
            is pressed.  Tk only re-runs its BiDi pass at word boundaries, so
            we force a full layout by saving, clearing and re-inserting the
            text, then restoring the cursor.  O(n) per keystroke but imperceptible
            for typical message lengths (<500 chars).
            """
            if _bidi_busy[0]:
                return
            _bidi_busy[0] = True
            try:
                saved = w.index(tk.INSERT)
                content = w.get("1.0", "end-1c")
                w.delete("1.0", "end")
                w.insert("1.0", content)
                w.tag_add("rtl", "1.0", "end")
                try:
                    w.mark_set(tk.INSERT, saved)
                except tk.TclError:
                    pass
            finally:
                _bidi_busy[0] = False

        def _on_key(e):
            """After each key: re-tag RTL; for Hebrew chars also force BiDi re-render."""
            w.after(1, _rtl)
            if e.char and len(e.char) == 1 and 0x0590 <= ord(e.char) <= 0x05FF:
                w.after(2, _force_bidi_render)

        w.bind("<Key>",           _on_key)
        w.bind("<<Modified>>",    lambda e: _rtl())
        w.bind("<ButtonRelease>", lambda e: _rtl())

        # ── Clipboard helpers ─────────────────────────────────────────────────

        def _paste(e=None):
            try:    txt = w.clipboard_get()
            except tk.TclError: return "break"
            try:    w.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError: pass
            w.insert(tk.INSERT, txt)
            w.after(1, _rtl)
            w.after(2, _force_bidi_render)
            return "break"

        def _copy(e=None):
            try:
                w.clipboard_clear()
                w.clipboard_append(w.get(tk.SEL_FIRST, tk.SEL_LAST))
            except tk.TclError: pass
            return "break"

        def _cut(e=None):
            try:
                w.clipboard_clear()
                w.clipboard_append(w.get(tk.SEL_FIRST, tk.SEL_LAST))
                w.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError: pass
            return "break"

        def _selall(e=None):
            w.tag_add(tk.SEL, "1.0", "end-1c")
            w.mark_set(tk.INSERT, "end-1c")
            return "break"

        # ── Physical-keycode handler ──────────────────────────────────────────
        # Works in Hebrew AND English keyboard mode:
        #   • Windows: keycode stays 86/67/88/65 regardless of layout
        #   • macOS:   keycode stays 9/8/7/0; also catches ⌘ via <Meta-Key>

        def _ctrl_key(e):
            mod = e.state
            if not ((mod & _MOD_CTRL) or (mod & _MOD_CMD)):
                return
            if   e.keycode == _KC_V: return _paste()
            elif e.keycode == _KC_C: return _copy()
            elif e.keycode == _KC_X: return _cut()
            elif e.keycode == _KC_A: return _selall()

        w.bind("<Control-Key>", _ctrl_key)
        if platform.system() == "Darwin":
            w.bind("<Meta-Key>", _ctrl_key)   # ⌘ key on macOS

        for s in ("<Control-v>","<Control-V>","<Command-v>","<Command-V>","<<Paste>>"):
            w.bind(s, _paste)
        for s in ("<Control-c>","<Control-C>","<Command-c>","<Command-C>","<<Copy>>"):
            w.bind(s, _copy)
        for s in ("<Control-x>","<Control-X>","<Command-x>","<Command-X>","<<Cut>>"):
            w.bind(s, _cut)
        for s in ("<Control-a>","<Control-A>","<Command-a>","<Command-A>"):
            w.bind(s, _selall)

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _card(self, parent, **kw) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16,
                            border_width=1, border_color=BORDER, **kw)

    def _pill_btn(self, parent, text, command, fg, txt, hover, **kw) -> ctk.CTkButton:
        kw.setdefault("font", F_BODY)
        return ctk.CTkButton(parent, text=text, command=command,
                             fg_color=fg, text_color=txt, hover_color=hover,
                             corner_radius=50, **kw)

    def _section_hdr(self, parent, icon, title, badge_var=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 14))

        # badge on left
        if badge_var:
            ctk.CTkLabel(row, textvariable=badge_var,
                         fg_color=ACCENT, text_color="white",
                         corner_radius=50, font=F_SMALL,
                         padx=10, pady=2).pack(side="left")

        # title + icon on right
        ctk.CTkLabel(row, text=f"{title}  {icon}",
                     font=F_LABEL, text_color=MUTED,
                     anchor="e").pack(side="right")

        ctk.CTkFrame(row, height=1, fg_color=BORDER).pack(
            side="bottom", fill="x")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):

        # ── Header ───────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self.root, fg_color=HDR_BG, corner_radius=0, height=72)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        inner = ctk.CTkFrame(hdr, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=28)

        # logo pill
        logo = ctk.CTkFrame(inner, fg_color=HDR_DK, corner_radius=12,
                            width=50, height=50)
        logo.pack(side="left", pady=11, padx=(0, 16))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="🚀", font=ctk.CTkFont(size=22)).pack(expand=True)

        # title
        tf = ctk.CTkFrame(inner, fg_color="transparent")
        tf.pack(side="left", pady=11)
        ctk.CTkLabel(tf, text="WhatsApp Studio Notifier",
                     font=F_TITLE, text_color="white",
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(tf, text="שליחת הודעות לקבוצות  ·  פותח ע״י עילאי ברגיל",
                     font=F_SMALL, text_color="#a8d5be",
                     anchor="w").pack(anchor="w")

        # version
        ctk.CTkLabel(inner, text=" v2.1 ",
                     fg_color=HDR_DK, text_color="#a8d5be",
                     corner_radius=8, font=F_SMALL,
                     padx=8).pack(side="right", pady=22)

        ctk.CTkFrame(self.root, height=3, fg_color=HDR_DK,
                     corner_radius=0).pack(fill="x")

        # ── Body grid ────────────────────────────────────────────────────────
        body = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        body.columnconfigure(0, weight=38, minsize=300)
        body.columnconfigure(1, weight=62, minsize=520)
        body.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=2)
        right.rowconfigure(3, weight=1)

        self._build_left(left)
        self._build_right(right)

    # ── Left column ───────────────────────────────────────────────────────────

    def _build_left(self, parent):

        # ── Settings card ────────────────────────────────────────────────────
        sc = self._card(parent)
        sc.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        sc_inner = ctk.CTkFrame(sc, fg_color="transparent")
        sc_inner.pack(fill="x", padx=20, pady=18)

        self._section_hdr(sc_inner, "⚙️", "הגדרות קמפיין")

        # toggle row
        tr = ctk.CTkFrame(sc_inner, fg_color=FIELD, corner_radius=12)
        tr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(tr, text="אישור ידני לפני שליחה",
                     font=F_BODY, text_color=TEXT,
                     anchor="e").pack(side="right", padx=16, pady=12)
        ctk.CTkSwitch(tr, text="",
                      variable=self.manual_confirm_var,
                      onvalue=True, offvalue=False,
                      progress_color=ACCENT,
                      button_color="white",
                      button_hover_color="#f0f0f0",
                      fg_color="#b0bdb5"
                      ).pack(side="left", padx=16, pady=12)

        # delay row
        dr = ctk.CTkFrame(sc_inner, fg_color=FIELD, corner_radius=12)
        dr.pack(fill="x")
        ctk.CTkLabel(dr, text="שהייה בין הודעות (שניות)",
                     font=F_BODY, text_color=MUTED,
                     anchor="e").pack(side="right", padx=16, pady=12)
        ctk.CTkLabel(dr, text="⏱", font=F_BODY,
                     text_color=MUTED).pack(side="left", padx=(16, 4), pady=12)
        ctk.CTkEntry(dr, textvariable=self.delay_var, width=60,
                     font=ctk.CTkFont(family=FONT, size=14, weight="bold"),
                     justify="center", fg_color=FIELD,
                     text_color=ACCENT, border_color=ACCENT,
                     border_width=2, corner_radius=8
                     ).pack(side="left", pady=12)

        # ── Numbers card ─────────────────────────────────────────────────────
        nc = self._card(parent)
        nc.grid(row=1, column=0, sticky="nsew")
        nc_inner = ctk.CTkFrame(nc, fg_color="transparent")
        nc_inner.pack(fill="both", expand=True, padx=20, pady=18)
        nc_inner.rowconfigure(1, weight=1)
        nc_inner.columnconfigure(0, weight=1)

        self._section_hdr(nc_inner, "👥", "רשימת תפוצה",
                          badge_var=self._nums_badge_var)

        ctk.CTkLabel(nc_inner,
                     text="מספר לשורה, פסיק או רווח  |  ישראל: 05X  /  בינ׳: +XX",
                     font=F_SMALL, text_color=MUTED, anchor="e"
                     ).pack(fill="x", pady=(0, 6))

        self.numbers_text = ctk.CTkTextbox(
            nc_inner, font=F_BODY, fg_color=FIELD,
            text_color=TEXT, border_color=BORDER, border_width=1,
            corner_radius=10, wrap="word",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=A_LIGHT)
        self.numbers_text.pack(fill="both", expand=True)
        self.numbers_text._textbox.tag_configure("rtl", justify="right")
        self._bind_text_widget(self.numbers_text)
        self.numbers_text._textbox.bind(
            "<KeyRelease>", lambda e: self._refresh_badge())

        # bottom buttons
        bot = ctk.CTkFrame(nc_inner, fg_color="transparent")
        bot.pack(fill="x", pady=(10, 0))

        self._pill_btn(bot, "🗑  נקה רשימה", self.clear_numbers,
                       D_LIGHT, DANGER, "#f5c0bc",
                       font=F_SMALL).pack(side="right")
        self._pill_btn(bot, "ספור", self.count_numbers,
                       A_LIGHT, ACCENT, "#b8deca",
                       font=F_SMALL).pack(side="right", padx=(0, 8))

    def _refresh_badge(self):
        n = len(parse_phone_numbers(self.numbers_text.get("1.0", "end")))
        self._nums_badge_var.set(f"{n} מספרים")

    # ── Right column ──────────────────────────────────────────────────────────

    def _build_right(self, parent):

        # ── Message card ─────────────────────────────────────────────────────
        mc = self._card(parent)
        mc.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        mc.rowconfigure(1, weight=1)
        mc.columnconfigure(0, weight=1)

        mc_hdr = ctk.CTkFrame(mc, fg_color="transparent")
        mc_hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 0))
        self._section_hdr(mc_hdr, "💬", "תוכן ההודעה")

        self.message_text = ctk.CTkTextbox(
            mc, font=F_BODY, fg_color=FIELD,
            text_color=TEXT, border_color=BORDER, border_width=1,
            corner_radius=10, wrap="word",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=A_LIGHT)
        self.message_text.grid(row=1, column=0, sticky="nsew", padx=20, pady=8)
        self.message_text._textbox.tag_configure("rtl", justify="right")
        self._bind_text_widget(self.message_text)
        self.message_text.insert("1.0",
            "שלום,\nרצינו לעדכן שהשיעור היום בוטל.\nעמכם הסליחה ותודה על ההבנה.")
        self.message_text._textbox.tag_add("rtl", "1.0", "end")

        # template bar
        tbar = ctk.CTkFrame(mc, fg_color="#ddeee3", corner_radius=0,
                            border_width=0)
        tbar.grid(row=2, column=0, sticky="ew",
                  padx=0, pady=0)
        tbar_inner = ctk.CTkFrame(tbar, fg_color="transparent")
        tbar_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(tbar_inner, text="תבניות ←",
                     font=F_SMALL, text_color=MUTED).pack(side="right", padx=(0, 8))
        for label, cmd in [
            ("📅 ביטול שיעור", self._tpl_cancel),
            ("🕒 דחייה",       self._tpl_delay),
            ("🎉 חג",          self._tpl_holiday),
            ("📢 מבצע",        self._tpl_promo),
            ("🗑 נקה",         self.clear_message),
        ]:
            self._pill_btn(tbar_inner, label, cmd,
                           CARD, MUTED, A_LIGHT,
                           font=F_SMALL,
                           border_width=1, border_color=BORDER
                           ).pack(side="right", padx=3)

        # ── CTA button ───────────────────────────────────────────────────────
        cta_frame = ctk.CTkFrame(parent, fg_color="transparent")
        cta_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        cta_frame.columnconfigure(0, weight=1)

        self.start_button = self._pill_btn(
            cta_frame, "🚀   התחל שליחה עכשיו", self._start_thread,
            ACCENT, "white", A_DARK, font=F_CTA, height=52)
        self.start_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.stop_button = self._pill_btn(
            cta_frame, "⛔   עצור שליחה", self._stop_sending,
            DANGER, "white", D_DARK, font=F_CTA, height=52)
        # hidden until sending

        util = ctk.CTkFrame(cta_frame, fg_color="transparent")
        util.grid(row=1, column=0, sticky="ew")
        util.columnconfigure(0, weight=1)
        util.columnconfigure(1, weight=1)

        self._pill_btn(util, "✓  בדיקת תקינות", self.validate_inputs,
                       CARD, ACCENT, A_LIGHT, font=F_SMALL,
                       border_width=1, border_color=BORDER, height=40
                       ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._pill_btn(util, "📱  חיבור ראשוני", self._first_login,
                       CARD, ACCENT, A_LIGHT, font=F_SMALL,
                       border_width=1, border_color=BORDER, height=40
                       ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # ── Progress ─────────────────────────────────────────────────────────
        prog = ctk.CTkFrame(parent, fg_color="transparent")
        prog.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self._progress_label = ctk.CTkLabel(prog, text="",
                                            font=F_SMALL, text_color=MUTED,
                                            anchor="e")
        self._progress_label.pack(fill="x")

        self._progress_bar = ctk.CTkProgressBar(
            prog, variable=self._progress_var,
            progress_color=ACCENT, fg_color=BORDER,
            corner_radius=4, height=6)
        self._progress_bar.set(0)
        self._progress_bar.pack(fill="x")

        # ── Log terminal ─────────────────────────────────────────────────────
        log_card = ctk.CTkFrame(parent, fg_color=LOG_BG, corner_radius=16)
        log_card.grid(row=3, column=0, sticky="nsew")
        log_card.rowconfigure(1, weight=1)
        log_card.columnconfigure(1, weight=1)

        # title bar
        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.grid(row=0, column=0, columnspan=3, sticky="ew",
                     padx=18, pady=(14, 8))

        dots = ctk.CTkFrame(log_hdr, fg_color="transparent")
        dots.pack(side="left")
        for col in ("#ff5f57", "#ffbd2e", "#28c940"):
            ctk.CTkLabel(dots, text="●", font=ctk.CTkFont(size=11),
                         text_color=col).pack(side="left", padx=2)

        ctk.CTkLabel(log_hdr, text="LIVE LOG  ●",
                     font=ctk.CTkFont(family="Consolas", size=9, weight="bold"),
                     text_color=LOG_OK).pack(side="right")

        # timestamp column
        self._log_ts = tk.Text(
            log_card, font=("Consolas", 9), width=10,
            bg=LOG_BG, fg="#3d5c4a", bd=0, relief="flat",
            state="disabled", wrap="none", padx=4, pady=2)
        self._log_ts.grid(row=1, column=0, sticky="ns", padx=(18, 0), pady=(0, 14))

        # separator
        tk.Frame(log_card, bg="#1e3828", width=1).grid(
            row=1, column=1, sticky="ns", pady=(0, 14))

        # message column
        log_scroll = tk.Scrollbar(log_card, bg=LOG_BG, troughcolor=LOG_BG,
                                  width=8, bd=0, relief="flat")
        log_scroll.grid(row=1, column=3, sticky="ns", padx=(0, 8), pady=(0, 14))

        self.log_text = tk.Text(
            log_card, font=("Consolas", 9),
            bg=LOG_BG, fg="#b0c4b8", bd=0, relief="flat",
            state="disabled", wrap="word", padx=12, pady=2,
            yscrollcommand=log_scroll.set)
        self.log_text.grid(row=1, column=2, sticky="nsew", pady=(0, 14))
        log_scroll.config(command=self._sync_scroll)

        for tag, fg in [("success", LOG_OK), ("error", LOG_ERR),
                        ("warning", LOG_WRN), ("info", "#b0c4b8")]:
            self.log_text.tag_configure(tag, foreground=fg)
            self._log_ts.tag_configure(tag, foreground="#3d5c4a")

        self._ui_log("המערכת נטענה ומוכנה לעבודה.", "success")

    def _sync_scroll(self, *args):
        self.log_text.yview(*args)
        self._log_ts.yview(*args)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _ui_log(self, msg: str, level: str = "info"):
        ts = time.strftime("%H:%M:%S")
        for w in (self.log_text, self._log_ts):
            w.config(state="normal")
        self._log_ts.insert("end", f"{ts}\n", level)
        self.log_text.insert("end", f"{msg}\n", level)
        for w in (self.log_text, self._log_ts):
            w.see("end"); w.config(state="disabled")

    def log(self, msg: str, level: str = "info"):
        self.root.after(0, lambda m=msg, lv=level: self._ui_log(m, lv))

    # ── Templates ────────────────────────────────────────────────────────────

    def clear_numbers(self):
        self.numbers_text.delete("1.0", "end")
        self._refresh_badge()

    def clear_message(self):
        self.message_text.delete("1.0", "end")

    def _set_message(self, text):
        self.message_text.delete("1.0", "end")
        self.message_text.insert("1.0", text)
        self.message_text._textbox.tag_add("rtl", "1.0", "end")

    def _tpl_cancel(self):
        self._set_message("שלום,\nרצינו לעדכן שהשיעור היום בוטל.\nעמכם הסליחה ותודה על ההבנה.")

    def _tpl_delay(self):
        self._set_message("שלום,\nרצינו לעדכן כי שעת השיעור השתנתה.\nאנא בדקו מול המערכת / המועדון.\nתודה.")

    def _tpl_holiday(self):
        self._set_message("שלום,\nחג שמח לכם ולמשפחותיכם!\nנתראה אחרי החג 🎉")

    def _tpl_promo(self):
        self._set_message("שלום,\nיש לנו בשורה מעולה — החודש מחיר מיוחד לחברים!\nפרטים נוספים בקרוב 📢")

    # ── Getters & Validation ──────────────────────────────────────────────────

    def _get_numbers(self) -> list[str]:
        return parse_phone_numbers(self.numbers_text.get("1.0", "end").strip())

    def _get_message(self) -> str:
        return self.message_text.get("1.0", "end").strip()

    def count_numbers(self):
        n = len(self._get_numbers())
        messagebox.showinfo("כמות מספרים", f"נמצאו {n} מספרים ייחודיים תקינים.")

    def validate_inputs(self) -> bool:
        if not self._get_numbers():
            messagebox.showwarning("שגיאה", "לא הוכנסו מספרי טלפון."); return False
        if not self._get_message():
            messagebox.showwarning("שגיאה", "ההודעה ריקה."); return False
        try:
            if float(self.delay_var.get()) < 0: raise ValueError
        except ValueError:
            messagebox.showwarning("שגיאה", "השהיה חייבת להיות מספר חיובי."); return False
        messagebox.showinfo("תקינות",
            f"✅ הכל תקין!\n{len(self._get_numbers())} מספרים · הודעה מוכנה.")
        return True

    # ── Chrome Driver ─────────────────────────────────────────────────────────

    def _create_driver(self):
        os.makedirs(BOT_PROFILE_DIR, exist_ok=True)
        for lf in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try: os.remove(os.path.join(BOT_PROFILE_DIR, lf))
            except FileNotFoundError: pass

        opts = ChromeOptions()
        opts.add_argument("--start-maximized")
        opts.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
        opts.add_argument("--no-first-run")
        opts.add_argument("--disable-notifications")
        opts.page_load_strategy = "normal"

        if _USE_WEBDRIVER_MANAGER:
            driver = webdriver.Chrome(
                service=ChromeService(ChromeDriverManager().install()), options=opts)
        else:
            driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(30)
        return driver

    # ── First-Time Login ──────────────────────────────────────────────────────

    def _first_login(self):
        if self._login_driver is not None:
            messagebox.showinfo("כבר פתוח",
                "חלון ההתחברות כבר פתוח.\nסרוק QR ואז סגור את החלון.")
            return
        try:
            self._ui_log("פותח דפדפן להתחברות ראשונית...")
            self._login_driver = self._create_driver()
            self._login_driver.get("https://web.whatsapp.com")
            self._ui_log("סרוק QR בטלפון ואז סגור את חלון הדפדפן.", "warning")
            threading.Thread(target=self._monitor_login_window, daemon=True).start()
        except Exception as e:
            self._ui_log(f"שגיאה: {e}", "error")
            messagebox.showerror("שגיאה", f"לא הצלחתי לפתוח Chrome:\n{e}")
            self._login_driver = None

    def _monitor_login_window(self):
        try:
            while True:
                time.sleep(1)
                try: _ = self._login_driver.title
                except Exception: break
        finally:
            try: self._login_driver.quit()
            except Exception: pass
            self._login_driver = None
            self.log("✅ חלון ההתחברות נסגר. ההפעלה נשמרה.", "success")

    # ── Sending ───────────────────────────────────────────────────────────────

    def _start_thread(self):
        if self._is_sending:
            messagebox.showinfo("בפעולה", "שליחה כבר מתבצעת."); return
        if not self.validate_inputs(): return

        self._ui_log("מאתחל Chrome...")
        try:
            driver = self._create_driver()
        except Exception as e:
            self._ui_log(f"שגיאה: {e}", "error")
            messagebox.showerror("שגיאה", f"לא הצלחתי לפתוח Chrome:\n{e}"); return

        self._stop_event.clear()
        self._is_sending = True
        self.start_button.grid_remove()
        self.stop_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        threading.Thread(target=self._send_all, args=(driver,), daemon=True).start()

    def _stop_sending(self):
        self._stop_event.set()
        self.log("⛔ עצירה התבקשה. ממתין לסיום ההודעה הנוכחית...", "warning")

    def _restore_ui_after_send(self):
        self._is_sending = False
        self.stop_button.grid_remove()
        self.start_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._progress_var.set(0)
        self._progress_bar.set(0)
        self._progress_label.configure(text="")

    def _update_progress(self, current: int, total: int, phone: str):
        self._progress_var.set(current / total if total else 0)
        self._progress_bar.set(current / total if total else 0)
        self._progress_label.configure(text=f"שולח {current}/{total}  |  {phone}")

    def _send_all(self, driver):
        numbers = self._get_numbers()
        message = self._get_message()
        delay   = max(MIN_DELAY, float(self.delay_var.get()))
        total   = len(numbers)
        sent_ok, sent_fail = [], []

        try:
            self.log("טוען WhatsApp Web...")
            driver.get("https://web.whatsapp.com")
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH,
                    '//div[@id="side"] | //canvas')))

            if not driver.find_elements(By.ID, "side"):
                self.log("⚠️ לא מחובר! נדרשת סריקת QR.", "error")
                self.root.after(0, lambda: messagebox.showerror("לא מחובר",
                    "WhatsApp Web לא מחובר.\n\nלחץ 'חיבור ראשוני', סרוק QR ונסה שוב."))
                return

            self.log(f"✅ מחובר! שולח ל-{total} נמענים.", "success")

            for idx, raw_phone in enumerate(numbers, 1):
                if self._stop_event.is_set():
                    self.log("⛔ השליחה הופסקה.", "warning"); break

                phone = normalize_il_number(raw_phone)
                self.root.after(0, lambda i=idx, t=total, p=phone:
                                self._update_progress(i, t, p))
                self.log(f"[{idx}/{total}] שולח ל-{phone}...")

                if self.manual_confirm_var.get():
                    ev, res = threading.Event(), [True]
                    def _ask(ph=phone, e=ev, r=res):
                        r[0] = messagebox.askyesno("אישור", f"לשלוח ל-{ph}?"); e.set()
                    self.root.after(0, _ask); ev.wait()
                    if not res[0]:
                        self.log(f"⏩ דולג על {phone}.", "warning"); continue

                if self._send_one(driver, phone, message):
                    sent_ok.append(phone)
                    self.log(f"✅ נשלח ל-{phone}", "success")
                else:
                    sent_fail.append(phone)
                    self.log(f"❌ נכשל: {phone}", "error")

                if not self._stop_event.is_set() and idx < total:
                    time.sleep(delay)

        except Exception as e:
            self.log(f"שגיאה קריטית: {e}", "error")
            self.root.after(0, lambda err=str(e): messagebox.showerror(
                "שגיאה", f"התהליך הופסק:\n{err}"))
        finally:
            try: driver.quit()
            except Exception: pass
            self.root.after(0, self._restore_ui_after_send)

        self.log("─" * 36)
        if sent_fail:
            self.log(f"סיכום: ✅ {len(sent_ok)} הצליחו  ❌ {len(sent_fail)} נכשלו", "warning")
        else:
            self.log(f"🎉 כל ה-{len(sent_ok)} הודעות נשלחו בהצלחה!", "success")

        summary = f"✅ נשלח: {len(sent_ok)}\n❌ נכשל: {len(sent_fail)}"
        if sent_fail: summary += "\n\nנכשלו:\n" + "\n".join(sent_fail)
        self.root.after(150, lambda s=summary: messagebox.showinfo("סיכום שליחה", s))

    def _send_one(self, driver, phone: str, message: str) -> bool:
        try:
            driver.get(f"https://web.whatsapp.com/send"
                       f"?phone={phone}&text={urllib.parse.quote(message)}")
        except Exception:
            return False

        deadline = time.time() + SEND_TIMEOUT
        while time.time() < deadline:
            try:
                for dialog in driver.find_elements(By.XPATH, '//div[@role="dialog"]'):
                    try:
                        if "לא קיים ב-WhatsApp" in (dialog.text or ""):
                            try: dialog.find_element(By.XPATH, './/button').click()
                            except Exception: pass
                            return False
                    except StaleElementReferenceException:
                        break

                send_btns = driver.find_elements(By.XPATH,
                    '//span[@data-icon="send"]/ancestor::button[1]')
                if send_btns:
                    try: send_btns[0].click()
                    except StaleElementReferenceException:
                        time.sleep(0.3); continue
                    except Exception:
                        try: driver.execute_script("arguments[0].click();", send_btns[0])
                        except Exception: time.sleep(0.3); continue
                    time.sleep(2.0); return True

                tbs = driver.find_elements(By.XPATH,
                    '//div[@contenteditable="true"][@data-tab="10"]')
                if tbs:
                    try:
                        content = tbs[0].text or driver.execute_script(
                            "return arguments[0].textContent;", tbs[0]) or ""
                        if content.strip():
                            tbs[0].send_keys(Keys.ENTER)
                            time.sleep(2.0); return True
                    except StaleElementReferenceException:
                        time.sleep(0.3); continue

            except StaleElementReferenceException:
                time.sleep(0.3); continue
            time.sleep(0.5)
        return False


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = ctk.CTk()
    app  = WhatsAppApp(root)
    root.mainloop()
