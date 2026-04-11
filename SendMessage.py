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

# Mac uses Command, Windows/Linux use Control
_MOD = "Command" if platform.system() == "Darwin" else "Control"

# ── App Config ───────────────────────────────────────────────────────────────
APP_TITLE = "WhatsApp Studio Notifier"
if platform.system() == "Windows":
    BOT_PROFILE_DIR = r"C:\WhatsAppBotProfile"
else:
    BOT_PROFILE_DIR = os.path.join(os.path.expanduser("~"), "WhatsAppBotProfile")
MIN_DELAY    = 1.5
SEND_TIMEOUT = 25

# ── Design Tokens ─────────────────────────────────────────────────────────────
BG       = "#f0f4f1"   # app background
HDR_BG   = "#006b47"   # top header band
HDR_DK   = "#004d34"   # header bottom shadow strip
CARD     = "#ffffff"   # card surface
CARD_SH  = "#c4d1c7"   # card drop-shadow colour
FIELD    = "#f4f8f5"   # textarea / input bg
ACCENT   = "#006b47"   # primary green
A_DARK   = "#004d34"   # hover green
A_LIGHT  = "#e6f2ec"   # tint green
DANGER   = "#c0392b"   # red
D_DARK   = "#922b21"   # hover red
D_LIGHT  = "#fdecea"   # tint red
TEXT     = "#1a2921"   # main text
MUTED    = "#5f7a6e"   # secondary text
BORDER   = "#dae3db"   # borders / dividers
TBAR     = "#eef4ef"   # template bar bg
SEP      = "#d0dbd1"   # separator
LOG_BG   = "#0d1f17"   # terminal background
LOG_OK   = "#4ade80"   # terminal green
LOG_ERR  = "#ff8a80"   # terminal red
LOG_WARN = "#ffd54f"   # terminal yellow
FONT     = "Segoe UI"


# ── Phone Number Helpers ──────────────────────────────────────────────────────

def parse_phone_numbers(raw_text: str) -> list[str]:
    raw_text = raw_text.replace(",", " ").replace(";", " ").replace("\t", " ")
    cleaned, seen = [], set()
    for part in raw_text.split():
        num = "".join(ch for ch in part if ch.isdigit() or ch == "+")
        if len(num) >= 7 and num not in seen:
            seen.add(num)
            cleaned.append(num)
    return cleaned


def normalize_il_number(phone: str) -> str:
    phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+").strip()
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("972"):
        return phone
    if phone.startswith("0"):
        return "972" + phone[1:]
    return phone


# ── App ───────────────────────────────────────────────────────────────────────

class WhatsAppApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x720")
        self.root.minsize(920, 640)
        self.root.configure(bg=BG)

        self._is_sending    = False
        self._stop_event    = threading.Event()
        self._login_driver  = None

        self.delay_var          = tk.StringVar(value="3")
        self.manual_confirm_var = tk.BooleanVar(value=False)
        self._progress_var      = tk.IntVar(value=0)

        self._set_app_icon()
        self._build_ui()

    # ── Icon ──────────────────────────────────────────────────────────────────

    def _set_app_icon(self):
        """Load logo_icon.png as the window icon (falls back to green circle)."""
        base    = os.path.dirname(os.path.abspath(__file__))
        # prefer the pre-cropped square icon; fall back to full logo
        for name in ("logo_icon.png", "logo.png"):
            icon_path = os.path.join(base, name)
            if os.path.exists(icon_path):
                break
        else:
            icon_path = None

        try:
            if _HAS_PIL and icon_path:
                pil_img = Image.open(icon_path).resize((256, 256), Image.LANCZOS)
                self._icon_ref = ImageTk.PhotoImage(pil_img)
                self.root.iconphoto(True, self._icon_ref)

                # On Windows also write a proper .ico for the taskbar
                if platform.system() == "Windows":
                    ico_path = os.path.join(base, "logo_icon.ico")
                    if not os.path.exists(ico_path):
                        pil_img.save(ico_path, format="ICO",
                                     sizes=[(16,16),(32,32),(48,48),(64,64),(256,256)])
                    try:
                        self.root.iconbitmap(ico_path)
                    except Exception:
                        pass
                return
        except Exception:
            pass

        # Fallback: draw a simple green circle
        try:
            size = 64
            img  = tk.PhotoImage(width=size, height=size)
            cx = cy = size // 2
            r  = cx - 2
            for y in range(size):
                row = []
                for x in range(size):
                    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    row.append(ACCENT if dist <= r else BG)
                img.put("{" + " ".join(row) + "}", to=(0, y))
            self.root.iconphoto(True, img)
        except Exception:
            pass

    # ── Clipboard + RTL helpers ───────────────────────────────────────────────

    def _bind_text_widget(self, widget: tk.Text):
        """Bind RTL display fix + full clipboard shortcuts to a Text widget."""

        # ── RTL fix: apply tag immediately after each keystroke ──────────────
        def _fix_rtl(e=None):
            widget.tag_add("rtl", "1.0", "end")

        widget.bind("<Key>",           lambda e: widget.after(1, _fix_rtl))
        widget.bind("<<Modified>>",    lambda e: _fix_rtl())
        widget.bind("<ButtonRelease>", lambda e: _fix_rtl())

        # ── Clipboard shortcuts ───────────────────────────────────────────────
        def _paste(e):
            try:
                text = widget.clipboard_get()
            except tk.TclError:
                return "break"
            try:                                   # delete selection first
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                pass
            widget.insert(tk.INSERT, text)
            widget.after(1, _fix_rtl)
            return "break"

        def _copy(e):
            try:
                widget.clipboard_clear()
                widget.clipboard_append(widget.get(tk.SEL_FIRST, tk.SEL_LAST))
            except tk.TclError:
                pass
            return "break"

        def _cut(e):
            try:
                widget.clipboard_clear()
                widget.clipboard_append(widget.get(tk.SEL_FIRST, tk.SEL_LAST))
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                pass
            return "break"

        def _select_all(e):
            widget.tag_add(tk.SEL, "1.0", "end-1c")
            widget.mark_set(tk.INSERT, "end-1c")
            return "break"

        # Bind every possible variant — Control (Windows/Linux) + Command (Mac)
        # + tkinter virtual events (most reliable cross-platform)
        for seq in ("<Control-v>", "<Control-V>", "<Command-v>", "<Command-V>", "<<Paste>>"):
            widget.bind(seq, _paste)
        for seq in ("<Control-c>", "<Control-C>", "<Command-c>", "<Command-C>", "<<Copy>>"):
            widget.bind(seq, _copy)
        for seq in ("<Control-x>", "<Control-X>", "<Command-x>", "<Command-X>", "<<Cut>>"):
            widget.bind(seq, _cut)
        for seq in ("<Control-a>", "<Control-A>", "<Command-a>", "<Command-A>"):
            widget.bind(seq, _select_all)

    # ── UI component helpers ──────────────────────────────────────────────────

    def _btn(self, parent, text, command, bg, fg, hover, **kw):
        props = dict(font=(FONT, 10, "bold"), relief="flat", bd=0,
                     cursor="hand2", padx=22, pady=9,
                     highlightthickness=0)
        props.update(kw)
        b = tk.Button(parent, text=text, command=command,
                      bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                      **props)
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _card(self, parent, card_padx=20, card_pady=18, **grid_kw):
        """White card with a subtle bottom-right drop shadow."""
        shadow = tk.Frame(parent, bg=CARD_SH)
        shadow.grid(**grid_kw)
        shadow.rowconfigure(0, weight=1)
        shadow.columnconfigure(0, weight=1)
        inner = tk.Frame(shadow, bg=CARD, padx=card_padx, pady=card_pady)
        inner.grid(row=0, column=0, sticky="nsew", padx=(0, 2), pady=(0, 2))
        return inner

    def _section_title(self, parent, icon, title):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=(0, 16))
        tk.Label(row, text=icon, font=(FONT, 15), bg=CARD, fg=ACCENT
                 ).pack(side="right", padx=(10, 0))
        tk.Label(row, text=title, font=(FONT, 11, "bold"), bg=CARD, fg=TEXT
                 ).pack(side="right")
        tk.Frame(row, bg=SEP, height=1).pack(side="bottom", fill="x")

    def _field_row(self, parent, label_text, widget_factory):
        """A labelled field row with a border."""
        row = tk.Frame(parent, bg=FIELD,
                       highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text=label_text, font=(FONT, 10), bg=FIELD, fg=MUTED,
                 padx=14, pady=10).pack(side="right")
        widget_factory(row)
        return row

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):

        # ── Header band ─────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=HDR_BG)
        hdr.pack(fill="x")

        hdr_inner = tk.Frame(hdr, bg=HDR_BG)
        hdr_inner.pack(fill="x", padx=28, pady=14)

        # logo pill
        logo_pill = tk.Frame(hdr_inner, bg=A_DARK,
                             highlightbackground="#003d28", highlightthickness=1)
        logo_pill.pack(side="left", padx=(0, 16))
        tk.Label(logo_pill, text="  ⚡  ", font=(FONT, 20), bg=A_DARK,
                 fg="white", pady=6).pack()

        title_f = tk.Frame(hdr_inner, bg=HDR_BG)
        title_f.pack(side="left")
        tk.Label(title_f, text="WhatsApp Studio Notifier",
                 font=(FONT, 17, "bold"), bg=HDR_BG, fg="white").pack(anchor="w")
        tk.Label(title_f, text="שליחת הודעות לקבוצות — פותח ע״י עילאי ברגיל",
                 font=(FONT, 9), bg=HDR_BG, fg="#a8d5be").pack(anchor="w")

        # version badge
        ver = tk.Frame(hdr_inner, bg=A_DARK)
        ver.pack(side="right")
        tk.Label(ver, text=" v2.0 ", font=(FONT, 8, "bold"),
                 bg=A_DARK, fg="#a8d5be", pady=4, padx=6).pack()

        # thin bottom strip on header
        tk.Frame(self.root, bg=HDR_DK, height=3).pack(fill="x")

        # ── Two-column body ──────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        body.columnconfigure(0, weight=36, minsize=290)
        body.columnconfigure(1, weight=64, minsize=500)
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
        scard = self._card(parent, row=0, column=0, sticky="ew", pady=(0, 12))
        self._section_title(scard, "⚙️", "הגדרות קמפיין")

        # delay row
        delay_row = tk.Frame(scard, bg=FIELD,
                             highlightbackground=BORDER, highlightthickness=1)
        delay_row.pack(fill="x", pady=(0, 8))
        tk.Label(delay_row, text="שניות בין הודעות  (מינ׳ 1.5)",
                 font=(FONT, 10), bg=FIELD, fg=MUTED,
                 padx=14, pady=11).pack(side="right")
        # accent-bordered entry
        entry_wrap = tk.Frame(delay_row, bg=ACCENT, padx=1, pady=1)
        entry_wrap.pack(side="left", padx=12)
        tk.Entry(entry_wrap, textvariable=self.delay_var, width=5,
                 font=(FONT, 12, "bold"), justify="center",
                 relief="flat", bg=FIELD, fg=ACCENT, bd=0,
                 insertbackground=ACCENT).pack(ipady=4)

        # manual confirm row
        confirm_row = tk.Frame(scard, bg=FIELD,
                               highlightbackground=BORDER, highlightthickness=1)
        confirm_row.pack(fill="x")
        tk.Checkbutton(confirm_row, text="אישור ידני לפני כל שליחה",
                       variable=self.manual_confirm_var,
                       font=(FONT, 10), bg=FIELD, fg=TEXT,
                       activebackground=FIELD, selectcolor=ACCENT,
                       cursor="hand2", padx=14, pady=11).pack(side="right")

        # ── Numbers card ─────────────────────────────────────────────────────
        ncard = self._card(parent, row=1, column=0, sticky="nsew")
        self._section_title(ncard, "👥", "רשימת תפוצה")

        # hint label
        tk.Label(ncard, text="מספר לשורה, פסיק או רווח — ישראל: 05X…  בינ׳: +XX…",
                 font=(FONT, 8), bg=CARD, fg=MUTED, anchor="e").pack(fill="x", pady=(0, 6))

        # textarea + scrollbar wrapper
        nums_wrap = tk.Frame(ncard, bg=FIELD,
                             highlightbackground=BORDER, highlightthickness=1)
        nums_wrap.pack(fill="both", expand=True)
        nums_wrap.rowconfigure(0, weight=1)
        nums_wrap.columnconfigure(0, weight=1)

        nums_scroll = tk.Scrollbar(nums_wrap, bg=BORDER, troughcolor=FIELD,
                                   width=10, relief="flat", bd=0)
        nums_scroll.grid(row=0, column=1, sticky="ns")

        self.numbers_text = tk.Text(
            nums_wrap, font=(FONT, 11), bd=0, relief="flat",
            bg=FIELD, fg=TEXT, wrap="word", padx=12, pady=10,
            insertbackground=ACCENT,
            yscrollcommand=nums_scroll.set
        )
        self.numbers_text.grid(row=0, column=0, sticky="nsew")
        nums_scroll.config(command=self.numbers_text.yview)
        self.numbers_text.tag_configure("rtl", justify="right")
        self._bind_text_widget(self.numbers_text)

        # action buttons below numbers
        btn_row = tk.Frame(ncard, bg=CARD)
        btn_row.pack(fill="x", pady=(10, 0))
        self._btn(btn_row, "ספור מספרים", self.count_numbers,
                  A_LIGHT, ACCENT, "#c8e8d8",
                  font=(FONT, 9, "bold"), padx=14, pady=6).pack(side="right", padx=(4, 0))
        self._btn(btn_row, "🗑 נקה", self.clear_numbers,
                  D_LIGHT, DANGER, "#fad7d4",
                  font=(FONT, 9, "bold"), padx=14, pady=6).pack(side="right", padx=4)

    # ── Right column ──────────────────────────────────────────────────────────

    def _build_right(self, parent):

        # ── Message card ─────────────────────────────────────────────────────
        mcard = self._card(parent, row=0, column=0, sticky="nsew", pady=(0, 12))
        self._section_title(mcard, "💬", "תוכן ההודעה")

        # message textarea
        msg_wrap = tk.Frame(mcard, bg=FIELD,
                            highlightbackground=BORDER, highlightthickness=1)
        msg_wrap.pack(fill="both", expand=True)
        msg_wrap.rowconfigure(0, weight=1)
        msg_wrap.columnconfigure(0, weight=1)

        msg_scroll = tk.Scrollbar(msg_wrap, bg=BORDER, troughcolor=FIELD,
                                  width=10, relief="flat", bd=0)
        msg_scroll.grid(row=0, column=1, sticky="ns")

        self.message_text = tk.Text(
            msg_wrap, font=(FONT, 12), bd=0, relief="flat",
            bg=FIELD, fg=TEXT, wrap="word", padx=14, pady=12,
            insertbackground=ACCENT,
            yscrollcommand=msg_scroll.set
        )
        self.message_text.grid(row=0, column=0, sticky="nsew")
        msg_scroll.config(command=self.message_text.yview)
        self.message_text.tag_configure("rtl", justify="right")
        self._bind_text_widget(self.message_text)
        self.message_text.insert("1.0",
            "שלום,\nרצינו לעדכן שהשיעור היום בוטל.\nעמכם הסליחה ותודה על ההבנה.", "rtl")

        # Template bar
        tpl_bar = tk.Frame(mcard, bg=TBAR, pady=10, padx=10)
        tpl_bar.pack(fill="x")

        tk.Label(tpl_bar, text="תבניות מהירות:",
                 font=(FONT, 8, "bold"), bg=TBAR, fg=MUTED).pack(side="right", padx=(0, 4))

        templates = [
            ("🗑 נקה",         self.clear_message),
            ("📢 מבצע",        self._tpl_promo),
            ("🎉 חג",          self._tpl_holiday),
            ("🕒 דחייה",       self._tpl_delay),
            ("📅 ביטול שיעור", self._tpl_cancel),
        ]
        for label, cmd in templates:
            self._btn(tpl_bar, label, cmd,
                      CARD, MUTED, BORDER,
                      font=(FONT, 9, "bold"), padx=11, pady=5,
                      highlightbackground=BORDER, highlightthickness=1
                      ).pack(side="right", padx=3)

        # ── Action buttons row ────────────────────────────────────────────────
        actions = tk.Frame(parent, bg=BG)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.start_button = self._btn(
            actions, "🚀  התחל שליחה עכשיו", self._start_thread,
            ACCENT, "white", A_DARK,
            font=(FONT, 13, "bold"), pady=14, padx=40
        )
        self.start_button.pack(side="left")

        self.stop_button = self._btn(
            actions, "⛔  עצור", self._stop_sending,
            DANGER, "white", D_DARK,
            font=(FONT, 13, "bold"), pady=14, padx=40
        )
        # hidden until sending starts

        side_btns = tk.Frame(actions, bg=BG)
        side_btns.pack(side="right")
        self._btn(side_btns, "📱 חיבור ראשוני", self._first_login,
                  CARD, MUTED, A_LIGHT,
                  highlightbackground=BORDER, highlightthickness=1
                  ).pack(side="right", padx=(6, 0))
        self._btn(side_btns, "✓ בדיקת תקינות", self.validate_inputs,
                  CARD, MUTED, A_LIGHT,
                  highlightbackground=BORDER, highlightthickness=1
                  ).pack(side="right", padx=6)

        # ── Progress strip ────────────────────────────────────────────────────
        prog = tk.Frame(parent, bg=BG)
        prog.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self._progress_label = tk.Label(prog, text="",
                                        font=(FONT, 9), bg=BG, fg=MUTED)
        self._progress_label.pack(anchor="e")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("ws.Horizontal.TProgressbar",
                        troughcolor=BORDER, background=ACCENT,
                        thickness=6, borderwidth=0)
        self._progress_bar = ttk.Progressbar(
            prog, variable=self._progress_var,
            style="ws.Horizontal.TProgressbar", mode="determinate"
        )
        self._progress_bar.pack(fill="x")

        # ── Live log terminal ─────────────────────────────────────────────────
        log_outer = tk.Frame(parent, bg=LOG_BG, padx=16, pady=14)
        log_outer.grid(row=3, column=0, sticky="nsew")
        log_outer.rowconfigure(1, weight=1)
        log_outer.columnconfigure(0, weight=1)

        # terminal title bar
        log_hdr = tk.Frame(log_outer, bg=LOG_BG)
        log_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        dots = tk.Frame(log_hdr, bg=LOG_BG)
        dots.pack(side="left")
        for col in ("#ff5f57", "#ffbd2e", "#28c940"):
            tk.Label(dots, text="●", font=(FONT, 10), bg=LOG_BG,
                     fg=col).pack(side="left", padx=2)

        tk.Label(log_hdr, text="●  לוג פעילות חי",
                 font=("Consolas", 9, "bold"), bg=LOG_BG, fg=LOG_OK
                 ).pack(side="right")

        log_scroll = tk.Scrollbar(log_outer, bg=LOG_BG, troughcolor=LOG_BG,
                                  width=8, bd=0, relief="flat")
        log_scroll.grid(row=1, column=1, sticky="ns")

        self.log_text = tk.Text(
            log_outer, font=("Consolas", 9),
            bg=LOG_BG, fg="#b0c4b8", bd=0, relief="flat",
            state="disabled", wrap="word", padx=4, pady=2,
            yscrollcommand=log_scroll.set
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        log_scroll.config(command=self.log_text.yview)

        self.log_text.tag_configure("success", foreground=LOG_OK)
        self.log_text.tag_configure("error",   foreground=LOG_ERR)
        self.log_text.tag_configure("warning", foreground=LOG_WARN)
        self.log_text.tag_configure("info",    foreground="#b0c4b8")

        self._ui_log("✅ המערכת נטענה ומוכנה לעבודה.", "success")

    # ── Logging (thread-safe) ─────────────────────────────────────────────────

    def _ui_log(self, msg: str, level: str = "info"):
        ts = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}]  {msg}\n", level)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def log(self, msg: str, level: str = "info"):
        self.root.after(0, lambda m=msg, lv=level: self._ui_log(m, lv))

    # ── Templates ────────────────────────────────────────────────────────────

    def clear_numbers(self):
        self.numbers_text.delete("1.0", "end")

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
            messagebox.showwarning("שגיאה", "לא הוכנסו מספרי טלפון.")
            return False
        if not self._get_message():
            messagebox.showwarning("שגיאה", "ההודעה ריקה. אנא הקלד תוכן.")
            return False
        try:
            d = float(self.delay_var.get())
            if d < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("שגיאה", "השהיה חייבת להיות מספר תקין (לדוגמה: 3).")
            return False
        messagebox.showinfo("תקינות", f"✅ הכל תקין!\n{len(self._get_numbers())} מספרים • הודעה מוכנה.")
        return True

    # ── Chrome Driver ─────────────────────────────────────────────────────────

    def _create_driver(self):
        os.makedirs(BOT_PROFILE_DIR, exist_ok=True)
        for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            try:
                os.remove(os.path.join(BOT_PROFILE_DIR, lock_file))
            except FileNotFoundError:
                pass

        opts = ChromeOptions()
        opts.add_argument("--start-maximized")
        opts.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
        opts.add_argument("--no-first-run")
        opts.add_argument("--disable-notifications")
        opts.page_load_strategy = "normal"

        if _USE_WEBDRIVER_MANAGER:
            service = ChromeService(ChromeDriverManager().install())
            driver  = webdriver.Chrome(service=service, options=opts)
        else:
            driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(30)
        return driver

    # ── First-Time Login ──────────────────────────────────────────────────────

    def _first_login(self):
        if self._login_driver is not None:
            messagebox.showinfo("כבר פתוח",
                "חלון ההתחברות כבר פתוח.\nסרוק את ה-QR ואז סגור את החלון.")
            return
        try:
            self._ui_log("פותח דפדפן להתחברות ראשונית...")
            self._login_driver = self._create_driver()
            self._login_driver.get("https://web.whatsapp.com")
            self._ui_log("סרוק QR בטלפון ואז סגור את חלון הדפדפן.", "warning")
            threading.Thread(target=self._monitor_login_window, daemon=True).start()
        except Exception as e:
            self._ui_log(f"שגיאה בפתיחה ראשונית: {e}", "error")
            messagebox.showerror("שגיאה", f"לא הצלחתי לפתוח Chrome:\n{e}")
            self._login_driver = None

    def _monitor_login_window(self):
        try:
            while True:
                time.sleep(1)
                try:
                    _ = self._login_driver.title
                except Exception:
                    break
        finally:
            try:
                self._login_driver.quit()
            except Exception:
                pass
            self._login_driver = None
            self.log("✅ חלון ההתחברות נסגר. ההפעלה נשמרה בהצלחה.", "success")

    # ── Sending Logic ─────────────────────────────────────────────────────────

    def _start_thread(self):
        if self._is_sending:
            messagebox.showinfo("בפעולה", "שליחה כבר מתבצעת.")
            return
        if not self.validate_inputs():
            return

        self._ui_log("מאתחל דפדפן Chrome...")
        try:
            driver = self._create_driver()
        except Exception as e:
            self._ui_log(f"שגיאה בפתיחת Chrome: {e}", "error")
            messagebox.showerror("שגיאה", f"לא הצלחתי לפתוח Chrome:\n{e}")
            return

        self._stop_event.clear()
        self._is_sending = True
        self.start_button.pack_forget()
        self.stop_button.pack(side="left")

        threading.Thread(target=self._send_all, args=(driver,), daemon=True).start()

    def _stop_sending(self):
        self._stop_event.set()
        self.log("⛔ בקשת עצירה נשלחה. ממתין לסיום ההודעה הנוכחית...", "warning")

    def _restore_ui_after_send(self):
        self._is_sending = False
        self.stop_button.pack_forget()
        self.start_button.pack(side="left")
        self._progress_var.set(0)
        self._progress_label.config(text="")
        self._progress_bar.config(maximum=1)

    def _update_progress(self, current: int, total: int, phone: str):
        self._progress_var.set(current)
        self._progress_label.config(text=f"שולח {current} מתוך {total}  |  {phone}")

    def _send_all(self, driver):
        numbers = self._get_numbers()
        message = self._get_message()
        delay   = max(MIN_DELAY, float(self.delay_var.get()))
        total   = len(numbers)

        sent_ok, sent_fail = [], []
        self.root.after(0, lambda: self._progress_bar.config(maximum=total))

        try:
            self.log("טוען את WhatsApp Web...")
            driver.get("https://web.whatsapp.com")

            wait = WebDriverWait(driver, 60)
            wait.until(EC.presence_of_element_located((By.XPATH,
                '//div[@id="side"] | //canvas'
            )))

            if not driver.find_elements(By.ID, "side"):
                self.log("⚠️ WhatsApp Web לא מחובר! נדרשת סריקת QR.", "error")
                self.root.after(0, lambda: messagebox.showerror(
                    "לא מחובר",
                    "WhatsApp Web לא מחובר לחשבון.\n\n"
                    "לחץ על 'חיבור ראשוני', סרוק QR ואז נסה שוב."
                ))
                return

            self.log(f"✅ מחובר ל-WhatsApp! שולח ל-{total} נמענים.", "success")

            for idx, raw_phone in enumerate(numbers, 1):
                if self._stop_event.is_set():
                    self.log("⛔ השליחה הופסקה.", "warning")
                    break

                phone = normalize_il_number(raw_phone)
                self.root.after(0, lambda i=idx, t=total, p=phone:
                                self._update_progress(i, t, p))
                self.log(f"[{idx}/{total}]  שולח ל-{phone}...")

                if self.manual_confirm_var.get():
                    confirmed_event = threading.Event()
                    approved = [True]

                    def _ask(ph=phone, ev=confirmed_event, res=approved):
                        res[0] = messagebox.askyesno("אישור שליחה", f"לאשר שליחה למספר {ph}?")
                        ev.set()

                    self.root.after(0, _ask)
                    confirmed_event.wait()

                    if not approved[0]:
                        self.log(f"⏩ דולג על {phone}.", "warning")
                        continue

                success = self._send_one(driver, phone, message)
                if success:
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
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.root.after(0, self._restore_ui_after_send)

        self.log("─" * 40)
        if sent_fail:
            self.log(f"סיכום: ✅ {len(sent_ok)} הצליחו  |  ❌ {len(sent_fail)} נכשלו", "warning")
        else:
            self.log(f"🎉 כל ה-{len(sent_ok)} הודעות נשלחו בהצלחה!", "success")

        summary = f"✅  נשלח בהצלחה: {len(sent_ok)}\n❌  נכשל:  {len(sent_fail)}"
        if sent_fail:
            summary += "\n\nמספרים שנכשלו:\n" + "\n".join(sent_fail)
        title = "סיכום שליחה" if not sent_fail else "סיכום — יש כשלונות"
        self.root.after(150, lambda s=summary, t=title: messagebox.showinfo(t, s))

    def _send_one(self, driver, phone: str, message: str) -> bool:
        encoded = urllib.parse.quote(message)
        url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded}"

        try:
            driver.get(url)
        except Exception:
            return False

        deadline = time.time() + SEND_TIMEOUT

        while time.time() < deadline:
            try:
                # 1. דיאלוג מספר לא תקין
                for dialog in driver.find_elements(By.XPATH, '//div[@role="dialog"]'):
                    try:
                        if "לא קיים ב-WhatsApp" in (dialog.text or ""):
                            try:
                                dialog.find_element(By.XPATH, './/button').click()
                            except Exception:
                                pass
                            return False
                    except StaleElementReferenceException:
                        break

                # 2. כפתור שליחה
                send_btns = driver.find_elements(By.XPATH,
                    '//span[@data-icon="send"]/ancestor::button[1]')
                if send_btns:
                    try:
                        send_btns[0].click()
                    except StaleElementReferenceException:
                        time.sleep(0.3)
                        continue
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", send_btns[0])
                        except Exception:
                            time.sleep(0.3)
                            continue
                    time.sleep(2.0)
                    return True

                # 3. גיבוי — Enter בתיבת הטקסט
                text_boxes = driver.find_elements(By.XPATH,
                    '//div[@contenteditable="true"][@data-tab="10"]')
                if text_boxes:
                    try:
                        content = (text_boxes[0].text or
                                   driver.execute_script(
                                       "return arguments[0].textContent;", text_boxes[0]
                                   ) or "")
                        if content.strip():
                            text_boxes[0].send_keys(Keys.ENTER)
                            time.sleep(2.0)
                            return True
                    except StaleElementReferenceException:
                        time.sleep(0.3)
                        continue

            except StaleElementReferenceException:
                time.sleep(0.3)
                continue

            time.sleep(0.5)

        return False


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app  = WhatsAppApp(root)
    root.mainloop()
