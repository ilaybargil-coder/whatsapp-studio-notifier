import os
import platform
import time
import urllib.parse
import threading
import tkinter as tk
from tkinter import messagebox, ttk

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

# ── App Config ────────────────────────────────────────────────────────────────
APP_TITLE = "WhatsApp Studio Notifier"
if platform.system() == "Windows":
    BOT_PROFILE_DIR = r"C:\WhatsAppBotProfile"
else:
    BOT_PROFILE_DIR = os.path.join(os.path.expanduser("~"), "WhatsAppBotProfile")
MIN_DELAY    = 1.5
SEND_TIMEOUT = 25

# Physical key codes — same regardless of keyboard language (Hebrew/English)
_KC_V, _KC_C, _KC_X, _KC_A = 86, 67, 88, 65

# ── Design Tokens ─────────────────────────────────────────────────────────────
BG      = "#f5fbf4"
CARD    = "#f0f5ef"   # surface-container-low
CARD_W  = "#ffffff"   # surface-container-lowest
FIELD   = "#ffffff"
ACCENT  = "#006b47"
A_DARK  = "#005235"
A_LIGHT = "#e6f4ed"
DANGER  = "#ba1a1a"
D_DARK  = "#93000a"
D_LIGHT = "#ffdad6"
TEXT    = "#171d19"
MUTED   = "#3e4942"
BORDER  = "#dee4de"
LOG_BG  = "#171d19"
LOG_OK  = "#71dba6"
LOG_ERR = "#ffb3af"
LOG_WRN = "#ffd180"
FONT    = "Segoe UI"


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


# ── Toggle Switch widget ──────────────────────────────────────────────────────

class ToggleSwitch(tk.Canvas):
    W, H = 46, 26

    def __init__(self, parent, variable: tk.BooleanVar, bg=CARD, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=bg, highlightthickness=0, cursor="hand2", **kw)
        self._var = variable
        self._draw()
        self.bind("<Button-1>", lambda e: self._toggle())
        variable.trace_add("write", lambda *_: self._draw())

    def _toggle(self):
        self._var.set(not self._var.get())

    def _draw(self):
        self.delete("all")
        on = self._var.get()
        track = ACCENT if on else "#b0bdb5"
        r = self.H // 2
        # track
        self.create_oval(0, 0, self.H, self.H, fill=track, outline="")
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=track, outline="")
        self.create_rectangle(r, 0, self.W - r, self.H, fill=track, outline="")
        # thumb
        pad = 3
        x = self.W - self.H + pad if on else pad
        self.create_oval(x, pad, x + self.H - 2*pad, self.H - pad,
                         fill="white", outline="")


# ── Main App ──────────────────────────────────────────────────────────────────

class WhatsAppApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x740")
        self.root.minsize(940, 660)
        self.root.configure(bg=BG)

        self._is_sending   = False
        self._stop_event   = threading.Event()
        self._login_driver = None

        self.delay_var          = tk.StringVar(value="3")
        self.manual_confirm_var = tk.BooleanVar(value=False)
        self._progress_var      = tk.IntVar(value=0)

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

    # ── Text-widget helpers (RTL + clipboard) ────────────────────────────────

    def _bind_text_widget(self, widget: tk.Text):

        def _rtl(*_):
            widget.tag_add("rtl", "1.0", "end")

        widget.bind("<Key>",           lambda e: widget.after(1, _rtl))
        widget.bind("<<Modified>>",    lambda e: _rtl())
        widget.bind("<ButtonRelease>", lambda e: _rtl())

        def _paste(e=None):
            try:    txt = widget.clipboard_get()
            except tk.TclError: return "break"
            try:    widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError: pass
            widget.insert(tk.INSERT, txt)
            widget.after(1, _rtl)
            return "break"

        def _copy(e=None):
            try:
                widget.clipboard_clear()
                widget.clipboard_append(widget.get(tk.SEL_FIRST, tk.SEL_LAST))
            except tk.TclError: pass
            return "break"

        def _cut(e=None):
            try:
                widget.clipboard_clear()
                widget.clipboard_append(widget.get(tk.SEL_FIRST, tk.SEL_LAST))
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError: pass
            return "break"

        def _selall(e=None):
            widget.tag_add(tk.SEL, "1.0", "end-1c")
            widget.mark_set(tk.INSERT, "end-1c")
            return "break"

        # ── keycode-based handler: works even when keyboard is in Hebrew ──────
        def _ctrl_key(e):
            if not (e.state & 0x4):   # Ctrl not held
                return
            if   e.keycode == _KC_V: return _paste()
            elif e.keycode == _KC_C: return _copy()
            elif e.keycode == _KC_X: return _cut()
            elif e.keycode == _KC_A: return _selall()

        widget.bind("<Control-Key>", _ctrl_key)   # covers all keyboard languages

        # Fallbacks: explicit letter bindings + tkinter virtual events
        for s in ("<Control-v>","<Control-V>","<Command-v>","<Command-V>","<<Paste>>"):
            widget.bind(s, _paste)
        for s in ("<Control-c>","<Control-C>","<Command-c>","<Command-C>","<<Copy>>"):
            widget.bind(s, _copy)
        for s in ("<Control-x>","<Control-X>","<Command-x>","<Command-X>","<<Cut>>"):
            widget.bind(s, _cut)
        for s in ("<Control-a>","<Control-A>","<Command-a>","<Command-A>"):
            widget.bind(s, _selall)

    # ── Generic button ────────────────────────────────────────────────────────

    def _btn(self, parent, text, command, bg, fg, hover, **kw):
        props = dict(font=(FONT, 10, "bold"), relief="flat", bd=0,
                     cursor="hand2", padx=22, pady=10, highlightthickness=0)
        props.update(kw)
        b = tk.Button(parent, text=text, command=command,
                      bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                      **props)
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    # ── Section header ────────────────────────────────────────────────────────

    def _sec_hdr(self, parent, icon, title, badge_var=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 14))
        # icon + title on the right
        tk.Label(row, text=icon,  font=(FONT, 13), bg=CARD, fg=ACCENT
                 ).pack(side="right", padx=(8, 0))
        tk.Label(row, text=title, font=(FONT, 9, "bold"), bg=CARD, fg=MUTED,
                 ).pack(side="right")
        # optional live badge on the left
        if badge_var is not None:
            self._badge_lbl = tk.Label(row, textvariable=badge_var,
                                       font=(FONT, 8, "bold"),
                                       bg=ACCENT, fg="white",
                                       padx=8, pady=2)
            self._badge_lbl.pack(side="left")
        tk.Frame(row, bg=BORDER, height=1).pack(side="bottom", fill="x")

    # ── Card frame ────────────────────────────────────────────────────────────

    def _card(self, parent, card_padx=20, card_pady=18, **grid_kw):
        shadow = tk.Frame(parent, bg="#c4d1c7")
        shadow.grid(**grid_kw)
        shadow.rowconfigure(0, weight=1)
        shadow.columnconfigure(0, weight=1)
        inner = tk.Frame(shadow, bg=CARD, padx=card_padx, pady=card_pady)
        inner.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=(0, 2))
        return inner

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):

        # ── Header band ──────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=ACCENT)
        hdr.pack(fill="x")
        inner = tk.Frame(hdr, bg=ACCENT)
        inner.pack(fill="x", padx=28, pady=14)

        logo_f = tk.Frame(inner, bg=A_DARK, highlightbackground="#003d28",
                          highlightthickness=1)
        logo_f.pack(side="left", padx=(0, 14))
        tk.Label(logo_f, text="  🚀  ", font=(FONT, 18), bg=A_DARK,
                 fg="white", pady=5).pack()

        tf = tk.Frame(inner, bg=ACCENT)
        tf.pack(side="left")
        tk.Label(tf, text="WhatsApp Studio Notifier",
                 font=(FONT, 16, "bold"), bg=ACCENT, fg="white").pack(anchor="w")
        tk.Label(tf, text="שליחת הודעות לקבוצות  ·  פותח ע״י עילאי ברגיל",
                 font=(FONT, 9), bg=ACCENT, fg="#a8d5be").pack(anchor="w")

        tk.Frame(inner, bg=A_DARK, width=1).pack(side="right", fill="y", padx=12)
        ver = tk.Frame(inner, bg=A_DARK)
        ver.pack(side="right")
        tk.Label(ver, text=" v2.1 ", font=(FONT, 8, "bold"),
                 bg=A_DARK, fg="#a8d5be", pady=5, padx=8).pack()

        tk.Frame(self.root, bg=A_DARK, height=3).pack(fill="x")

        # ── Two-column body ──────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        body.columnconfigure(0, weight=38, minsize=300)
        body.columnconfigure(1, weight=62, minsize=520)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=2)
        right.rowconfigure(3, weight=1)

        self._build_left(left)
        self._build_right(right)

    # ── Left column ───────────────────────────────────────────────────────────

    def _build_left(self, parent):

        # ── Settings card ────────────────────────────────────────────────────
        sc = self._card(parent, row=0, column=0, sticky="ew", pady=(0, 12))
        self._sec_hdr(sc, "⚙️", "הגדרות קמפיין")

        # Manual confirm — toggle switch
        row1 = tk.Frame(sc, bg=CARD_W, highlightbackground=BORDER,
                        highlightthickness=1)
        row1.pack(fill="x", pady=(0, 8))
        tk.Label(row1, text="אישור ידני לפני שליחה",
                 font=(FONT, 10), bg=CARD_W, fg=TEXT,
                 padx=14, pady=12).pack(side="right")
        ToggleSwitch(row1, self.manual_confirm_var,
                     bg=CARD_W).pack(side="left", padx=14, pady=8)

        # Delay
        row2 = tk.Frame(sc, bg=CARD_W, highlightbackground=BORDER,
                        highlightthickness=1)
        row2.pack(fill="x")
        tk.Label(row2, text="שהייה בין הודעות (שניות)",
                 font=(FONT, 10), bg=CARD_W, fg=MUTED,
                 padx=14, pady=12).pack(side="right")
        tk.Label(row2, text="⏱", font=(FONT, 12),
                 bg=CARD_W, fg=MUTED).pack(side="left", padx=(14, 4))
        tk.Entry(row2, textvariable=self.delay_var, width=5,
                 font=(FONT, 13, "bold"), justify="center",
                 relief="flat", bg=CARD_W, fg=ACCENT, bd=0,
                 insertbackground=ACCENT).pack(side="left", pady=8)

        # ── Recipients card ───────────────────────────────────────────────────
        self._nums_badge = tk.StringVar(value="0 מספרים")
        nc = self._card(parent, row=1, column=0, sticky="nsew")
        self._sec_hdr(nc, "👥", "רשימת תפוצה", badge_var=self._nums_badge)

        tk.Label(nc, text="מספר לשורה, פסיק או רווח — ישראל: 05X  /  בינ׳: +XX",
                 font=(FONT, 8), bg=CARD, fg=MUTED, anchor="e"
                 ).pack(fill="x", pady=(0, 6))

        nw = tk.Frame(nc, bg=FIELD, highlightbackground=BORDER, highlightthickness=1)
        nw.pack(fill="both", expand=True)
        nw.rowconfigure(0, weight=1)
        nw.columnconfigure(0, weight=1)

        ns = tk.Scrollbar(nw, bg=BORDER, troughcolor=FIELD, width=8, relief="flat", bd=0)
        ns.grid(row=0, column=1, sticky="ns")

        self.numbers_text = tk.Text(
            nw, font=(FONT, 11), bd=0, relief="flat",
            bg=FIELD, fg=TEXT, wrap="word", padx=12, pady=10,
            insertbackground=ACCENT, yscrollcommand=ns.set)
        self.numbers_text.grid(row=0, column=0, sticky="nsew")
        ns.config(command=self.numbers_text.yview)
        self.numbers_text.tag_configure("rtl", justify="right")
        self._bind_text_widget(self.numbers_text)
        # live badge update
        self.numbers_text.bind("<KeyRelease>", lambda e: self._refresh_badge())
        self.numbers_text.bind("<<Modified>>", lambda e: self._refresh_badge())

        # bottom strip
        bot = tk.Frame(nc, bg=CARD)
        bot.pack(fill="x", pady=(10, 0))
        self._btn(bot, "🗑  נקה רשימה", self.clear_numbers,
                  D_LIGHT, DANGER, "#f5c0bc",
                  font=(FONT, 9, "bold"), padx=14, pady=6
                  ).pack(side="right")
        self._btn(bot, "ספור", self.count_numbers,
                  A_LIGHT, ACCENT, "#c8e8d8",
                  font=(FONT, 9, "bold"), padx=14, pady=6
                  ).pack(side="right", padx=(0, 6))

    def _refresh_badge(self):
        n = len(parse_phone_numbers(self.numbers_text.get("1.0", "end")))
        self._nums_badge.set(f"{n} מספרים")

    # ── Right column ──────────────────────────────────────────────────────────

    def _build_right(self, parent):

        # ── Message card ─────────────────────────────────────────────────────
        mc = self._card(parent, row=0, column=0, sticky="nsew", pady=(0, 12))
        self._sec_hdr(mc, "💬", "תוכן ההודעה")

        mw = tk.Frame(mc, bg=FIELD, highlightbackground=BORDER, highlightthickness=1)
        mw.pack(fill="both", expand=True)
        mw.rowconfigure(0, weight=1)
        mw.columnconfigure(0, weight=1)

        ms = tk.Scrollbar(mw, bg=BORDER, troughcolor=FIELD, width=8, relief="flat", bd=0)
        ms.grid(row=0, column=1, sticky="ns")

        self.message_text = tk.Text(
            mw, font=(FONT, 12), bd=0, relief="flat",
            bg=FIELD, fg=TEXT, wrap="word", padx=14, pady=12,
            insertbackground=ACCENT, yscrollcommand=ms.set)
        self.message_text.grid(row=0, column=0, sticky="nsew")
        ms.config(command=self.message_text.yview)
        self.message_text.tag_configure("rtl", justify="right")
        self._bind_text_widget(self.message_text)
        self.message_text.insert("1.0",
            "שלום,\nרצינו לעדכן שהשיעור היום בוטל.\nעמכם הסליחה ותודה על ההבנה.", "rtl")

        # Template pills bar
        tbar = tk.Frame(mc, bg="#e8ede8", pady=10, padx=10)
        tbar.pack(fill="x")
        tk.Label(tbar, text="תבניות:", font=(FONT, 8, "bold"),
                 bg="#e8ede8", fg=MUTED).pack(side="right", padx=(0, 6))
        for label, cmd in [
            ("📅 ביטול שיעור", self._tpl_cancel),
            ("🕒 דחייה",       self._tpl_delay),
            ("🎉 חג",          self._tpl_holiday),
            ("📢 מבצע",        self._tpl_promo),
            ("🗑 נקה",         self.clear_message),
        ]:
            self._btn(tbar, label, cmd, CARD_W, MUTED, BORDER,
                      font=(FONT, 9), padx=12, pady=5,
                      highlightbackground=BORDER, highlightthickness=1
                      ).pack(side="right", padx=3)

        # ── Actions row ───────────────────────────────────────────────────────
        act = tk.Frame(parent, bg=BG)
        act.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.start_button = self._btn(
            act, "🚀  התחל שליחה עכשיו", self._start_thread,
            ACCENT, "white", A_DARK,
            font=(FONT, 13, "bold"), pady=14, padx=40)
        self.start_button.pack(side="left")

        self.stop_button = self._btn(
            act, "⛔  עצור", self._stop_sending,
            DANGER, "white", D_DARK,
            font=(FONT, 13, "bold"), pady=14, padx=40)

        side = tk.Frame(act, bg=BG)
        side.pack(side="right")
        for lbl, cmd in [("📱 חיבור ראשוני", self._first_login),
                         ("✓ בדיקת תקינות",  self.validate_inputs)]:
            self._btn(side, lbl, cmd, CARD, MUTED, A_LIGHT,
                      highlightbackground=BORDER, highlightthickness=1
                      ).pack(side="right", padx=4)

        # ── Progress ──────────────────────────────────────────────────────────
        prog = tk.Frame(parent, bg=BG)
        prog.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self._progress_label = tk.Label(prog, text="",
                                        font=(FONT, 9), bg=BG, fg=MUTED)
        self._progress_label.pack(anchor="e")
        style = ttk.Style()
        style.theme_use("default")
        style.configure("ws.Horizontal.TProgressbar",
                        troughcolor=BORDER, background=ACCENT, thickness=6)
        self._progress_bar = ttk.Progressbar(
            prog, variable=self._progress_var,
            style="ws.Horizontal.TProgressbar", mode="determinate")
        self._progress_bar.pack(fill="x")

        # ── Log terminal ──────────────────────────────────────────────────────
        log_outer = tk.Frame(parent, bg=LOG_BG, padx=18, pady=14)
        log_outer.grid(row=3, column=0, sticky="nsew")
        log_outer.rowconfigure(1, weight=1)
        log_outer.columnconfigure(1, weight=1)

        # title bar
        log_hdr = tk.Frame(log_outer, bg=LOG_BG)
        log_hdr.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        dots = tk.Frame(log_hdr, bg=LOG_BG)
        dots.pack(side="left")
        for col in ("#ff5f57", "#ffbd2e", "#28c940"):
            tk.Label(dots, text="●", font=(FONT, 9), bg=LOG_BG,
                     fg=col).pack(side="left", padx=2)
        tk.Label(log_hdr, text="LIVE LOG  ●",
                 font=("Consolas", 9, "bold"), bg=LOG_BG,
                 fg=LOG_OK).pack(side="right")

        # two-column log: timestamp | message
        ts_scroll = tk.Scrollbar(log_outer, width=8, bd=0, relief="flat",
                                 bg=LOG_BG, troughcolor=LOG_BG)
        ts_scroll.grid(row=1, column=2, sticky="ns")

        self._log_ts = tk.Text(
            log_outer, font=("Consolas", 9), width=10,
            bg=LOG_BG, fg="#4a6355", bd=0, relief="flat",
            state="disabled", wrap="none", padx=0, pady=2)
        self._log_ts.grid(row=1, column=0, sticky="ns")

        self.log_text = tk.Text(
            log_outer, font=("Consolas", 9),
            bg=LOG_BG, fg="#b0c4b8", bd=0, relief="flat",
            state="disabled", wrap="word", padx=8, pady=2,
            yscrollcommand=ts_scroll.set)
        self.log_text.grid(row=1, column=1, sticky="nsew")
        ts_scroll.config(command=self._sync_scroll)

        for tag, fg in [("success", LOG_OK), ("error", LOG_ERR),
                        ("warning", LOG_WRN), ("info", "#b0c4b8")]:
            self.log_text.tag_configure(tag, foreground=fg)
            self._log_ts.tag_configure(tag, foreground="#4a6355")

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
            w.see("end")
            w.config(state="disabled")

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
        self.message_text.insert("1.0", text, "rtl")

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
        self.start_button.pack_forget()
        self.stop_button.pack(side="left")
        threading.Thread(target=self._send_all, args=(driver,), daemon=True).start()

    def _stop_sending(self):
        self._stop_event.set()
        self.log("⛔ עצירה התבקשה. ממתין לסיום ההודעה הנוכחית...", "warning")

    def _restore_ui_after_send(self):
        self._is_sending = False
        self.stop_button.pack_forget()
        self.start_button.pack(side="left")
        self._progress_var.set(0)
        self._progress_label.config(text="")
        self._progress_bar.config(maximum=1)

    def _update_progress(self, current: int, total: int, phone: str):
        self._progress_var.set(current)
        self._progress_label.config(text=f"שולח {current}/{total}  |  {phone}")

    def _send_all(self, driver):
        numbers = self._get_numbers()
        message = self._get_message()
        delay   = max(MIN_DELAY, float(self.delay_var.get()))
        total   = len(numbers)
        sent_ok, sent_fail = [], []
        self.root.after(0, lambda: self._progress_bar.config(maximum=total))

        try:
            self.log("טוען WhatsApp Web...")
            driver.get("https://web.whatsapp.com")
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, '//div[@id="side"] | //canvas')))

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
    root = tk.Tk()
    app  = WhatsAppApp(root)
    root.mainloop()
