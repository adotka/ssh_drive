"""Диалоги: профиль подключения, ввод пароля, известные хосты."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import paramiko

from . import keys, paths, rclone, sshutil
from .profiles import Profile


def center_on(parent: tk.Misc, window: tk.Toplevel) -> None:
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 3
    window.geometry(f"+{max(0, x)}+{max(0, y)}")


class SecretDialog(tk.Toplevel):
    """Ввод пароля / парольной фразы с опцией сохранения."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        *,
        save_allowed: bool = False,
        save_default: bool = True,
    ) -> None:
        super().__init__(parent)
        self.result: tuple[str, bool] | None = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=message, wraplength=420, justify="left").pack(anchor="w")
        self.value = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.value, show="•", width=42)
        entry.pack(fill="x", pady=(10, 6))
        entry.focus_set()

        self.remember = tk.BooleanVar(value=save_default)
        if save_allowed:
            ttk.Checkbutton(
                frame, text="Сохранить (в зашифрованном виде, только для этого пользователя)",
                variable=self.remember,
            ).pack(anchor="w", pady=(0, 6))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Отмена", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._ok, style="Accent.TButton").pack(
            side="right", padx=(0, 8)
        )

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_on(parent, self)
        self.grab_set()

    def _ok(self) -> None:
        self.result = (self.value.get(), bool(self.remember.get()))
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_secret(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    save_allowed: bool = False,
    save_default: bool = True,
) -> tuple[str, bool] | None:
    dialog = SecretDialog(
        parent, title, message, save_allowed=save_allowed, save_default=save_default
    )
    parent.wait_window(dialog)
    return dialog.result


class ProfileDialog(tk.Toplevel):
    """Создание и редактирование профиля."""

    def __init__(self, parent: tk.Misc, profile: Profile) -> None:
        super().__init__(parent)
        self.result: Profile | None = None
        self._profile = Profile.from_dict(profile.to_dict())

        self.title("Профиль подключения")
        self.resizable(False, False)
        self.transient(parent)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        self.name = tk.StringVar(value=self._profile.name)
        self.host = tk.StringVar(value=self._profile.host)
        self.port = tk.StringVar(value=str(self._profile.port))
        self.user = tk.StringVar(value=self._profile.user)
        self.auth = tk.StringVar(value=self._profile.auth)
        self.key_path = tk.StringVar(value=self._profile.key_path)
        self.passphrase = tk.StringVar(value="")
        self.password = tk.StringVar(value="")
        self.save_secret = tk.BooleanVar(value=self._profile.save_secret)
        self.remote_path = tk.StringVar(value=self._profile.remote_path)
        self.read_only = tk.BooleanVar(value=self._profile.read_only)
        self.extra = tk.StringVar(value=self._profile.extra_opts)

        row = 0
        ttk.Label(body, text="Название").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.name, width=46).grid(
            row=row, column=1, columnspan=3, sticky="ew", pady=3
        )

        row += 1
        ttk.Label(body, text="Сервер").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.host).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Порт").grid(row=row, column=2, sticky="e", padx=(10, 4))
        ttk.Entry(body, textvariable=self.port, width=7).grid(row=row, column=3, sticky="w")

        row += 1
        ttk.Label(body, text="Пользователь").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.user).grid(
            row=row, column=1, columnspan=3, sticky="ew", pady=3
        )

        row += 1
        ttk.Label(body, text="Вход").grid(row=row, column=0, sticky="nw", pady=(10, 3))
        auth_box = ttk.Frame(body)
        auth_box.grid(row=row, column=1, columnspan=3, sticky="w", pady=(10, 3))
        ttk.Radiobutton(
            auth_box, text="по ключу", value="key", variable=self.auth, command=self._toggle
        ).pack(side="left")
        ttk.Radiobutton(
            auth_box, text="по паролю", value="password", variable=self.auth, command=self._toggle
        ).pack(side="left", padx=(16, 0))

        # --- блок ключа / пароля (взаимоисключающие) -------------------------
        row += 1
        auth_holder = ttk.Frame(body)
        auth_holder.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        auth_holder.columnconfigure(0, weight=1)

        self.key_frame = ttk.LabelFrame(auth_holder, text="Ключ", padding=8)
        self.key_frame.grid(row=0, column=0, sticky="ew")
        self.key_frame.columnconfigure(1, weight=1)
        ttk.Label(self.key_frame, text="Файл").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.key_frame, textvariable=self.key_path).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )
        key_buttons = ttk.Frame(self.key_frame)
        key_buttons.grid(row=1, column=1, sticky="e", pady=(4, 0), padx=(6, 0))
        ttk.Button(key_buttons, text="Обзор…", command=self._browse_key).pack(side="left")
        ttk.Button(key_buttons, text="Создать…", command=self._create_key).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(self.key_frame, text="Парольная фраза").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Entry(self.key_frame, textvariable=self.passphrase, show="•").grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(6, 0)
        )
        ttk.Checkbutton(
            self.key_frame,
            text="Сохранить парольную фразу",
            variable=self.save_secret,
        ).grid(row=3, column=1, sticky="w", padx=(6, 0), pady=(4, 0))

        # --- блок пароля ----------------------------------------------------
        self.pass_frame = ttk.LabelFrame(auth_holder, text="Пароль", padding=8)
        self.pass_frame.grid(row=0, column=0, sticky="ew")
        self.pass_frame.columnconfigure(1, weight=1)
        ttk.Label(self.pass_frame, text="Пароль").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.pass_frame, textvariable=self.password, show="•").grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Checkbutton(
            self.pass_frame,
            text="Сохранить пароль (шифруется DPAPI)",
            variable=self.save_secret,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=0, pady=(6, 0))

        row += 1
        ttk.Label(body, text="Папка на сервере").grid(row=row, column=0, sticky="w", pady=(10, 3))
        ttk.Entry(body, textvariable=self.remote_path).grid(
            row=row, column=1, columnspan=3, sticky="ew", pady=(10, 3)
        )
        ttk.Label(
            body, text="пусто = корень, например /home/user или C:/Users/user",
            foreground="#666666",
        ).grid(row=row + 1, column=1, columnspan=3, sticky="w")
        row += 2

        ttk.Label(body, text="Буква диска").grid(row=row, column=0, sticky="w", pady=3)
        free = rclone.free_letters()
        values = ["авто"] + free
        self.drive = tk.StringVar()
        self.drive_combo = ttk.Combobox(
            body, textvariable=self.drive, values=values, state="readonly", width=10
        )
        self.drive_combo.grid(row=row, column=1, sticky="w", pady=3)
        if self._profile.drive and self._profile.drive not in free:
            self.drive_combo.configure(values=values + [self._profile.drive])
        self.drive.set(self._profile.drive or "авто")

        row += 1
        ttk.Checkbutton(body, text="Только чтение", variable=self.read_only).grid(
            row=row, column=1, sticky="w", pady=(6, 0)
        )

        row += 1
        ttk.Label(body, text="Доп. опции rclone").grid(row=row, column=0, sticky="w", pady=(10, 3))
        ttk.Entry(body, textvariable=self.extra).grid(
            row=row, column=1, columnspan=3, sticky="ew", pady=(10, 3)
        )
        ttk.Label(
            body,
            text="например: --vfs-cache-max-size 4G --transfers 4",
            foreground="#666666",
        ).grid(row=row + 1, column=1, columnspan=3, sticky="w")
        row += 2

        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=0, columnspan=4, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Отмена", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="Сохранить", command=self._ok, style="Accent.TButton").pack(
            side="right", padx=(0, 8)
        )

        self._toggle()
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_on(parent, self)
        self.grab_set()

    # ------------------------------------------------------------------
    def _toggle(self) -> None:
        if self.auth.get() == "key":
            self.pass_frame.grid_remove()
            self.key_frame.grid()
            if not self.key_path.get():
                self.key_path.set(str(keys.default_key_path()))
        else:
            self.key_frame.grid_remove()
            self.pass_frame.grid()

    def _browse_key(self) -> None:
        initial = Path(self.key_path.get()).parent if self.key_path.get() else paths.keys_dir()
        chosen = filedialog.askopenfilename(
            parent=self,
            title="Приватный SSH-ключ",
            initialdir=str(initial),
            filetypes=[("SSH-ключи", "id_* *"), ("Все файлы", "*.*")],
        )
        if chosen:
            self.key_path.set(chosen)

    def _create_key(self) -> None:
        initial = str(keys.default_key_path())
        chosen = filedialog.asksaveasfilename(
            parent=self,
            title="Куда сохранить новый ключ",
            initialdir=str(paths.keys_dir()),
            initialfile=Path(initial).name,
        )
        if not chosen:
            return
        answer = ask_secret(
            self,
            "Парольная фраза",
            "Парольная фраза для нового ключа (можно оставить пустой).",
        )
        if answer is None:
            return
        passphrase = answer[0]
        try:
            path = keys.unique_path(Path(chosen))
            comment = f"{self.user.get() or 'user'}@{self.host.get() or 'host'}"
            keys.generate(path, comment, passphrase)
        except Exception as exc:
            messagebox.showerror("Ключ", f"Не удалось создать ключ:\n{exc}", parent=self)
            return
        self.key_path.set(str(path))
        self.passphrase.set(passphrase)
        messagebox.showinfo(
            "Ключ создан",
            f"{path}\n\nТеперь нажмите «Установить ключ» в главном окне, "
            "чтобы добавить его на сервер.",
            parent=self,
        )

    def _ok(self) -> None:
        name = self.name.get().strip()
        host = self.host.get().strip()
        user = self.user.get().strip()
        try:
            port = int(self.port.get())
        except ValueError:
            messagebox.showerror("Профиль", "Порт должен быть числом.", parent=self)
            return
        if not host:
            messagebox.showerror("Профиль", "Укажите сервер.", parent=self)
            return
        if not user:
            messagebox.showerror("Профиль", "Укажите пользователя.", parent=self)
            return
        if not (1 <= port <= 65535):
            messagebox.showerror("Профиль", "Порт вне диапазона 1–65535.", parent=self)
            return

        auth = self.auth.get()
        if auth == "key":
            key_path = self.key_path.get().strip()
            if not key_path:
                messagebox.showerror("Профиль", "Выберите существующий ключ или создайте новый.", parent=self)
                return
            if not Path(key_path).exists():
                messagebox.showerror("Профиль", f"Файл ключа не найден:\n{key_path}", parent=self)
                return
            self._profile.key_path = key_path
        else:
            self._profile.key_path = ""

        self._profile.name = name or f"{user}@{host}"
        self._profile.host = host
        self._profile.port = port
        self._profile.user = user
        self._profile.auth = auth
        self._profile.remote_path = self.remote_path.get().strip()
        self._profile.read_only = bool(self.read_only.get())
        self._profile.extra_opts = self.extra.get().strip()
        self._profile.save_secret = bool(self.save_secret.get())
        selected_drive = self.drive.get()
        self._profile.drive = (
            "" if selected_drive in ("", "авто", "только свободные") else selected_drive.upper()
        )

        from .secretstore import protect

        password = self.password.get()
        if auth == "password":
            if password and self._profile.save_secret:
                self._profile.password_enc = protect(password)
            elif not self._profile.save_secret:
                self._profile.password_enc = ""

        passphrase = self.passphrase.get()
        if auth == "key":
            if passphrase and self._profile.save_secret:
                self._profile.passphrase_enc = protect(passphrase)
            elif not self._profile.save_secret:
                self._profile.passphrase_enc = ""

        self.result = self._profile
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


class KnownHostsDialog(tk.Toplevel):
    """Просмотр и удаление сохранённых ключей хостов."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("Известные хосты")
        self.geometry("640x360")
        self.transient(parent)
        self._path = paths.known_hosts_file()

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Ключи, которым вы доверяете. Удаляйте запись, если сервер переустановлен.",
            foreground="#555555",
        ).pack(anchor="w")

        columns = ("host", "type", "fingerprint")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        for column, text, width in (
            ("host", "Хост", 160),
            ("type", "Тип", 90),
            ("fingerprint", "Отпечаток", 360),
        ):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(8, 8))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Удалить выбранное", command=self._delete).pack(side="left")
        ttk.Button(buttons, text="Закрыть", command=self.destroy).pack(side="right")

        self._hosts = paramiko.HostKeys()
        if self._path.exists():
            try:
                self._hosts.load(str(self._path))
            except Exception as exc:
                messagebox.showwarning("Известные хосты", str(exc), parent=self)
        self._fill()
        center_on(parent, self)
        self.grab_set()

    def _fill(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for host, keymap in sorted(self._hosts.items()):
            for keytype, key in sorted(keymap.items()):
                try:
                    fp = sshutil.fingerprint(key)
                except Exception:
                    fp = "?"
                self.tree.insert(
                    "", "end", values=(host, keytype, fp), tags=(host, keytype)
                )
        if not self.tree.get_children():
            self.tree.insert("", "end", values=("(пусто)", "", ""))

    def _delete(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        tags = self.tree.item(selected[0], "tags")
        if len(tags) != 2:
            return
        host, keytype = tags
        if not messagebox.askyesno(
            "Известные хосты",
            f"Удалить ключ {keytype} для {host}?\nПри следующем подключении его придётся подтвердить заново.",
            parent=self,
        ):
            return
        # Пересобираем файл целиком: так удаление предсказуемо (в т. ч. для host:port).
        fresh = paramiko.HostKeys()
        for existing_host, keymap in self._hosts.items():
            for existing_type, key in keymap.items():
                if (existing_host, existing_type) == (host, keytype):
                    continue
                fresh.add(existing_host, existing_type, key)
        fresh.save(str(self._path))
        self._hosts = fresh
        self._fill()
