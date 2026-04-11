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

try:
    from webdriver_manager.chrome import ChromeDriverManager
    _USE_WEBDRIVER_MANAGER = True
except ImportError:
    _USE_WEBDRIVER_MANAGER = False

# ── App Config ───────────────────────────────────────────────────────────────
APP_TITLE = "WhatsApp Studio Notifier"
if platform.system() == "Windows":
    BOT_PROFILE_DIR = r"C:\WhatsAppBotProfile"
else:
    BOT_PROFILE_DIR = os.path.join(os.path.expanduser("~"), "WhatsAppBotProfile")
MIN_DELAY    = 1.5
SEND_TIMEOUT = 25

# ── Design Tokens (from HTML design) ─────────────────────────────────────────
BG       = "#f5fbf4"   # surface background
CARD     = "#f0f5ef"   # card / section bg
FIELD    = "#ffffff"   # input field bg
ACCENT   = "#006b47"   # primary green
A_DARK   = "#005235"   # hover green
DANGER   = "#ba1a1a"   # error red
D_DARK   = "#93000a"   # hover red
TEXT     = "#171d19"   # main text
MUTED    = "#3e4942"   # secondary text
BORDER   = "#dee4de"   # dividers
TBAR     = "#e4eae3"   # template bar bg
LOG_BG   = "#171d19"   # terminal bg
LOG_OK   = "#71dba6"   # terminal green
LOG_ERR  = "#ffb3af"   # terminal red
LOG_WARN = "#ffd180"   # terminal yellow
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
        self.root.geometry("1080x700")
        self.root.minsize(900, 620)
        self.root.configure(bg=BG)

        self._is_sending    = False
        self._stop_event    = threading.Event()
        self._login_driver  = None

        self.delay_var          = tk.StringVar(value="3")
        self.manual_confirm_var = tk.BooleanVar(value=False)
        self._progress_var      = tk.IntVar(value=0)

        self._build_ui()

    # ── UI Helpers ────────────────────────────────────────────────────────────

    def _btn(self, parent, text, command, bg, fg, hover, **kw):
        props = dict(font=(FONT, 10, "bold"), relief="flat", bd=0,
                     cursor="hand2", padx=20, pady=8,
                     highlightthickness=0, highlightbackground=bg)
        props.update(kw)
        b = tk.Button(parent, text=text, command=command,
                      bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                      **props)
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _section_title(self, parent, icon, title, bg=CARD):
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x", pady=(0, 14))
        tk.Label(row, text=icon, font=(FONT, 14), bg=bg, fg=ACCENT).pack(side="right", padx=(8, 0))
        tk.Label(row, text=title, font=(FONT, 10, "bold"), bg=bg, fg=TEXT).pack(side="right")
        tk.Frame(row, bg=BORDER, height=1).pack(side="bottom", fill="x")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(14, 10))

        logo_box = tk.Frame(hdr, bg=ACCENT, width=46, height=46,
                            highlightbackground=A_DARK, highlightthickness=2)
        logo_box.pack(side="left", padx=(0, 14))
        logo_box.pack_propagate(False)
        tk.Label(logo_box, text="⚡", font=(FONT, 18), bg=ACCENT, fg="white").pack(expand=True)

        title_f = tk.Frame(hdr, bg=BG)
        title_f.pack(side="left")
        tk.Label(title_f, text="WhatsApp Studio Notifier",
                 font=(FONT, 16, "bold"), bg=BG, fg=ACCENT).pack(anchor="w")
        tk.Label(title_f, text="פותח ע״י עילאי ברגיל",
                 font=(FONT, 9), bg=BG, fg=MUTED).pack(anchor="w")

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        # ── Two-Column Grid ──────────────────────────────────────────────────
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=14)
        main.columnconfigure(0, weight=38, minsize=280)
        main.columnconfigure(1, weight=62, minsize=480)
        main.rowconfigure(0, weight=1)

        left = tk.Frame(main, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        right = tk.Frame(main, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=2)
        right.rowconfigure(3, weight=1)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent):
        # ── Settings Card ────────────────────────────────────────────────────
        settings = tk.Frame(parent, bg=CARD, padx=18, pady=16,
                            highlightbackground=BORDER, highlightthickness=1)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self._section_title(settings, "⚙", "הגדרות קמפיין")

        delay_row = tk.Frame(settings, bg=FIELD, pady=10, padx=14,
                             highlightbackground=BORDER, highlightthickness=1)
        delay_row.pack(fill="x", pady=(0, 8))
        tk.Label(delay_row, text="שניות בין הודעות (מינ׳ 1.5)",
                 font=(FONT, 10), bg=FIELD, fg=MUTED).pack(side="right")
        entry_frame = tk.Frame(delay_row, bg=ACCENT, padx=1, pady=1)
        entry_frame.pack(side="left")
        tk.Entry(entry_frame, textvariable=self.delay_var, width=4,
                 font=(FONT, 12, "bold"), justify="center",
                 relief="flat", bg=FIELD, fg=ACCENT, bd=0,
                 insertbackground=ACCENT).pack()

        confirm_row = tk.Frame(settings, bg=FIELD, pady=10, padx=14,
                               highlightbackground=BORDER, highlightthickness=1)
        confirm_row.pack(fill="x")
        tk.Checkbutton(confirm_row, text="אישור ידני לפני שליחה",
                       variable=self.manual_confirm_var,
                       font=(FONT, 10), bg=FIELD, fg=TEXT,
                       activebackground=FIELD, selectcolor=ACCENT,
                       cursor="hand2").pack(side="right")

        # ── Numbers Card ─────────────────────────────────────────────────────
        nums = tk.Frame(parent, bg=CARD, padx=18, pady=16,
                        highlightbackground=BORDER, highlightthickness=1)
        nums.grid(row=1, column=0, sticky="nsew")

        self._section_title(nums, "👥", "רשימת תפוצה")

        # Textarea wrapper — uses pack inside nums, grid inside wrapper
        nums_wrap = tk.Frame(nums, bg=FIELD,
                             highlightbackground=BORDER, highlightthickness=1)
        nums_wrap.pack(fill="both", expand=True)
        nums_wrap.rowconfigure(0, weight=1)
        nums_wrap.columnconfigure(0, weight=1)

        nums_scroll = tk.Scrollbar(nums_wrap)
        nums_scroll.grid(row=0, column=1, sticky="ns")

        self.numbers_text = tk.Text(
            nums_wrap, font=(FONT, 11), bd=0, relief="flat",
            bg=FIELD, fg=TEXT, wrap="word", padx=10, pady=8,
            insertbackground=ACCENT,
            yscrollcommand=nums_scroll.set
        )
        self.numbers_text.grid(row=0, column=0, sticky="nsew")
        nums_scroll.config(command=self.numbers_text.yview)
        self.numbers_text.tag_configure("rtl", justify="right")
        self.numbers_text.bind("<KeyRelease>",
                               lambda e: e.widget.tag_add("rtl", "1.0", "end"))

        # Buttons
        btn_row = tk.Frame(nums, bg=CARD)
        btn_row.pack(fill="x", pady=(10, 0))

        self._btn(btn_row, "ספור", self.count_numbers,
                  BORDER, ACCENT, "#c6d0c6",
                  font=(FONT, 9, "bold"), padx=14, pady=6).pack(side="right", padx=3)
        self._btn(btn_row, "נקה רשימה", self.clear_numbers,
                  "#ffdad6", DANGER, "#f5c0bc",
                  font=(FONT, 9, "bold"), padx=14, pady=6).pack(side="right", padx=3)
        tk.Label(btn_row, text="מספר לשורה, פסיק או רווח",
                 font=(FONT, 8), bg=CARD, fg=MUTED).pack(side="left")

    def _build_right(self, parent):
        # ── Message Card ─────────────────────────────────────────────────────
        msg = tk.Frame(parent, bg=CARD, padx=18, pady=16,
                       highlightbackground=BORDER, highlightthickness=1)
        msg.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        self._section_title(msg, "💬", "תוכן ההודעה")

        # Textarea wrapper — pack inside msg, grid inside wrapper
        msg_wrap = tk.Frame(msg, bg=FIELD,
                            highlightbackground=BORDER, highlightthickness=1)
        msg_wrap.pack(fill="both", expand=True)
        msg_wrap.rowconfigure(0, weight=1)
        msg_wrap.columnconfigure(0, weight=1)

        msg_scroll = tk.Scrollbar(msg_wrap)
        msg_scroll.grid(row=0, column=1, sticky="ns")

        self.message_text = tk.Text(
            msg_wrap, font=(FONT, 12), bd=0, relief="flat",
            bg=FIELD, fg=TEXT, wrap="word", padx=12, pady=10,
            insertbackground=ACCENT,
            yscrollcommand=msg_scroll.set
        )
        self.message_text.grid(row=0, column=0, sticky="nsew")
        msg_scroll.config(command=self.message_text.yview)
        self.message_text.tag_configure("rtl", justify="right")
        self.message_text.insert("1.0",
            "שלום,\nרצינו לעדכן שהשיעור היום בוטל.\nעמכם הסליחה ותודה על ההבנה.", "rtl")
        self.message_text.bind("<KeyRelease>",
                               lambda e: e.widget.tag_add("rtl", "1.0", "end"))

        # Template bar
        tpl_bar = tk.Frame(msg, bg=TBAR, pady=10, padx=8)
        tpl_bar.pack(fill="x")

        templates = [
            ("📅 ביטול שיעור", self._tpl_cancel),
            ("🕒 דחיית שיעור", self._tpl_delay),
            ("🎉 הודעת חג",    self._tpl_holiday),
            ("📢 מבצע סטודיו", self._tpl_promo),
            ("🗑 נקה",         self.clear_message),
        ]
        for label, cmd in reversed(templates):
            self._btn(tpl_bar, label, cmd,
                      FIELD, MUTED, BORDER,
                      font=(FONT, 9, "bold"), padx=12, pady=6,
                      highlightbackground=BORDER, highlightthickness=1
                      ).pack(side="right", padx=3)

        # ── Actions Row ──────────────────────────────────────────────────────
        actions = tk.Frame(parent, bg=BG)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.start_button = self._btn(
            actions, "🚀  התחל שליחה עכשיו", self._start_thread,
            ACCENT, "white", A_DARK,
            font=(FONT, 13, "bold"), pady=13, padx=36
        )
        self.start_button.pack(side="left")

        self.stop_button = self._btn(
            actions, "⛔  עצור שליחה", self._stop_sending,
            DANGER, "white", D_DARK,
            font=(FONT, 13, "bold"), pady=13, padx=36
        )
        # מוסתר עד שמתחילים

        side_btns = tk.Frame(actions, bg=BG)
        side_btns.pack(side="right")
        self._btn(side_btns, "📱 חיבור ראשוני", self._first_login,
                  CARD, MUTED, BORDER,
                  highlightbackground=BORDER, highlightthickness=1).pack(side="right", padx=4)
        self._btn(side_btns, "✓ בדיקת תקינות", self.validate_inputs,
                  CARD, MUTED, BORDER,
                  highlightbackground=BORDER, highlightthickness=1).pack(side="right", padx=4)

        # ── Progress ─────────────────────────────────────────────────────────
        prog = tk.Frame(parent, bg=BG)
        prog.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self._progress_label = tk.Label(prog, text="",
                                        font=(FONT, 9), bg=BG, fg=MUTED)
        self._progress_label.pack(anchor="e")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("ws.Horizontal.TProgressbar",
                        troughcolor=BORDER, background=ACCENT, thickness=5)
        self._progress_bar = ttk.Progressbar(
            prog, variable=self._progress_var,
            style="ws.Horizontal.TProgressbar", mode="determinate"
        )
        self._progress_bar.pack(fill="x")

        # ── Log (dark terminal) ───────────────────────────────────────────────
        log_outer = tk.Frame(parent, bg=LOG_BG, padx=16, pady=14,
                             highlightbackground="#0a1510", highlightthickness=1)
        log_outer.grid(row=3, column=0, sticky="nsew")
        log_outer.rowconfigure(1, weight=1)
        log_outer.columnconfigure(0, weight=1)

        log_hdr = tk.Frame(log_outer, bg=LOG_BG)
        log_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        dots_frame = tk.Frame(log_hdr, bg=LOG_BG)
        dots_frame.pack(side="left")
        for dot_color in ("#ff5f57", "#ffbd2e", "#28c940"):
            tk.Label(dots_frame, text="●", font=(FONT, 9),
                     bg=LOG_BG, fg=dot_color).pack(side="left", padx=1)
        tk.Label(log_hdr, text="לוג פעילות חי",
                 font=(FONT, 9, "bold"), bg=LOG_BG, fg=LOG_OK).pack(side="right")

        log_scroll = tk.Scrollbar(log_outer, bg=LOG_BG, troughcolor=LOG_BG, bd=0)
        log_scroll.grid(row=1, column=1, sticky="ns")

        self.log_text = tk.Text(
            log_outer, font=("Consolas", 9),
            bg=LOG_BG, fg="#cccccc", bd=0, relief="flat",
            state="disabled", wrap="word", padx=4, pady=2,
            yscrollcommand=log_scroll.set
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        log_scroll.config(command=self.log_text.yview)

        self.log_text.tag_configure("success", foreground=LOG_OK)
        self.log_text.tag_configure("error",   foreground=LOG_ERR)
        self.log_text.tag_configure("warning", foreground=LOG_WARN)
        self.log_text.tag_configure("info",    foreground="#cccccc")

        self._ui_log("המערכת נטענה ומוכנה לעבודה.", "success")

    # ── Logging (thread-safe) ─────────────────────────────────────────────────

    def _ui_log(self, msg: str, level: str = "info"):
        ts = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n", level)
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
            driver = webdriver.Chrome(service=service, options=opts)
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
            # 1. דיאלוג מספר לא תקין
            for dialog in driver.find_elements(By.XPATH, '//div[@role="dialog"]'):
                if "לא קיים ב-WhatsApp" in (dialog.text or ""):
                    try:
                        dialog.find_element(By.XPATH, './/button').click()
                    except Exception:
                        pass
                    return False

            # 2. כפתור שליחה
            send_btns = driver.find_elements(By.XPATH,
                '//span[@data-icon="send"]/ancestor::button[1]')
            if send_btns:
                try:
                    send_btns[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", send_btns[0])
                time.sleep(2.0)
                return True

            # 3. גיבוי — Enter בתיבת הטקסט
            text_boxes = driver.find_elements(By.XPATH,
                '//div[@contenteditable="true"][@data-tab="10"]')
            if text_boxes:
                content = (text_boxes[0].text or
                           driver.execute_script("return arguments[0].textContent;",
                                                 text_boxes[0]) or "")
                if content.strip():
                    text_boxes[0].send_keys(Keys.ENTER)
                    time.sleep(2.0)
                    return True

            time.sleep(0.5)

        return False


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = WhatsAppApp(root)
    root.mainloop()
