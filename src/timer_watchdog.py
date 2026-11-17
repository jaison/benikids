#!/usr/bin/env python3
"""Fullscreen timer watchdog: blocks the screen when time is up.
Runs outside the browser so it also covers native apps and games."""
import argparse
import json
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
import urllib.error
import urllib.request

from process_state import terminate_owned_process

HOME = os.path.expanduser("~")
APP_ID = "cozy-kids-launcher"
APP_NAME = "Cozy Kids Launcher"
PORT = int("38431")
BASE_URL = f"http://127.0.0.1:{PORT}"
CACHE_DIR = os.path.join(HOME, ".cache", APP_ID)
BROWSER_PIDFILE = os.path.join(CACHE_DIR, "browser.pid")

# Theme colours matching the launcher
THEME = {
    "bg1": "#ffd6e8",
    "bg2": "#ffeef6",
    "card": "#ffffff",
    "text": "#5f2148",
    "btn": "#e85a9c",
    "btn_text": "#ffffff",
    "accent": "#c2185b",
    "warning": "#ff9800",
    "input_border": "#e8bfd2",
    "smallbtn_bg": "#fff7fb",
}


def api(path, data=None):
    url = BASE_URL + path
    try:
        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def kill_browser():
    try:
        terminate_owned_process(BROWSER_PIDFILE, "browser")
    except Exception:
        pass


def http(method, path, data=None, cookie=""):
    """(status, json ou None, cabeçalhos). Sem exceção: erro de rede vira status 0."""
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(BASE_URL + path, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            corpo = resp.read()
            status, cabecalhos = resp.status, resp.headers
    except urllib.error.HTTPError as erro:
        corpo, status, cabecalhos = erro.read(), erro.code, erro.headers
    except Exception:
        return 0, None, {}
    try:
        dados = json.loads(corpo.decode("utf-8")) if corpo else None
    except ValueError:
        dados = None
    return status, dados, cabecalhos


def sair_com_pin(pin, pedir=None):
    """"Sair" da tela "Acabou o tempo!". Com PIN configurado, só sai com o PIN
    certo: confere no servidor (mesmo bloqueio de tentativas), usa o cookie de
    admin para o /exit-kids (que grava a flag de saída e fecha o menu) e só
    então sai. Antes, sem o cookie, o /exit-kids dava 403 e o kill_browser()
    derrubava o menu, que voltava sozinho (Windows: "menu nativo caiu (código
    15)"). Devolve "saiu", "pin" (PIN errado), "espera" (muitas tentativas) ou
    "erro"."""
    pedir = pedir or http
    status, dados, cabecalhos = pedir("POST", "/api/verify-pin", {"pin": pin or ""})
    if status == 429:
        return "espera"
    if status != 200 or not (dados or {}).get("valid"):
        return "pin" if status == 403 else "erro"
    cookie = ""
    bruto = cabecalhos.get("Set-Cookie", "") if cabecalhos else ""
    if bruto:
        cookie = bruto.split(";", 1)[0]
    status, _, _ = pedir("POST", "/exit-kids", {}, cookie=cookie)
    return "saiu" if status in (200, 204) else "erro"


def decidir(status, bloqueio_aberto, aviso_aberto, menu_na_frente):
    """O que a vigia faz a cada volta. `menu_na_frente` é chamado só quando
    importa (pergunta ao servidor). Devolve uma lista de ações: "bloquear",
    "fechar_bloqueio", "aviso", "fechar_aviso"."""
    acoes = []
    if status.get("expired"):
        # com o menu na frente e sem app aberto, a tela é a do próprio menu
        if bloqueio_aberto or not menu_na_frente():
            acoes.append("bloquear")
        if aviso_aberto:
            acoes.append("fechar_aviso")
        return acoes
    if bloqueio_aberto:
        # tempo estendido por outra tela (menu, área dos pais, API) ou timer parado
        acoes.append("fechar_bloqueio")
    if status.get("warning"):
        if not aviso_aberto and not menu_na_frente():
            acoes.append("aviso")
    elif aviso_aberto:
        acoes.append("fechar_aviso")
    return acoes


class WatchdogApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME + " Timer")
        self.warn_window = None
        self.block_window = None
        self.polling = True
        self.poll_interval = 5000  # ms
        self.status = {}

    def show_warning(self, remaining):
        if self.warn_window is not None:
            try:
                self.warn_window.lift()
                return
            except tk.TclError:
                self.warn_window = None
        if self.block_window is not None:
            return

        w = tk.Toplevel(self.root)
        self.warn_window = w
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.lift()
        w.configure(bg=THEME["warning"])

        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        ww, wh = 380, 120
        x = (sw - ww) // 2
        y = int(sh * 0.15)
        w.geometry(f"{ww}x{wh}+{x}+{y}")

        frame = tk.Frame(w, bg=THEME["card"], bd=0)
        frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        lbl = tk.Label(
            frame,
            text=(f"⏰ Falta {remaining} minuto!" if remaining == 1 else f"⏰ Faltam {remaining} minutos!"),
            font=("system-ui", 22, "bold"),
            bg=THEME["card"],
            fg=THEME["text"],
        )
        lbl.pack(expand=True, pady=18)

        w.after(6000, lambda: self._destroy_warn())

    def _destroy_warn(self):
        if self.warn_window is not None:
            try:
                self.warn_window.destroy()
            except tk.TclError:
                pass
            self.warn_window = None

    def show_block(self):
        if self.block_window is not None:
            try:
                self.block_window.lift()
                self.block_window.attributes("-topmost", True)
                return
            except tk.TclError:
                self.block_window = None

        self._destroy_warn()

        b = tk.Toplevel(self.root)
        self.block_window = b
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.lift()
        b.focus_force()

        sw = b.winfo_screenwidth()
        sh = b.winfo_screenheight()
        b.geometry(f"{sw}x{sh}+0+0")
        b.configure(bg=THEME["bg1"])

        # Main card
        card = tk.Frame(b, bg=THEME["card"], bd=0)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Responsive sizing
        base_size = min(sw, sh)
        pad = max(24, int(base_size * 0.03))
        card.configure(padx=pad, pady=pad)

        emoji = tk.Label(
            card,
            text="⏰",
            font=("system-ui", int(base_size * 0.08)),
            bg=THEME["card"],
            fg=THEME["text"],
        )
        emoji.pack(pady=(0, 8))

        title = tk.Label(
            card,
            text="Acabou o tempo!",
            font=("system-ui", int(base_size * 0.045), "bold"),
            bg=THEME["card"],
            fg=THEME["text"],
        )
        title.pack()

        body = tk.Label(
            card,
            text="Peça para a mamãe ou o papai para continuar brincando.",
            font=("system-ui", int(base_size * 0.025)),
            bg=THEME["card"],
            fg=THEME["text"],
            wraplength=int(sw * 0.5),
        )
        body.pack(pady=(8, 16))

        # PIN section
        pin_frame = tk.Frame(card, bg=THEME["card"])
        pin_frame.pack(pady=(0, 12))

        pin_lbl = tk.Label(
            pin_frame,
            text="Digite o PIN:",
            font=("system-ui", int(base_size * 0.022)),
            bg=THEME["card"],
            fg=THEME["text"],
        )
        pin_lbl.pack()

        pin_entry = tk.Entry(
            pin_frame,
            show="●",
            font=("system-ui", int(base_size * 0.035)),
            justify="center",
            width=8,
            bg="white",
            fg=THEME["text"],
            highlightthickness=2,
            highlightcolor=THEME["btn"],
            highlightbackground=THEME["input_border"],
        )
        pin_entry.pack(pady=6)
        pin_entry.focus_set()

        err_lbl = tk.Label(
            card,
            text="",
            font=("system-ui", int(base_size * 0.02)),
            bg=THEME["card"],
            fg="#c00",
        )
        err_lbl.pack()

        # Extend buttons
        btn_frame = tk.Frame(card, bg=THEME["card"])
        btn_frame.pack(pady=(12, 0))

        def do_extend(minutes):
            pin = pin_entry.get()
            res = api("/api/timer/extend", {"pin": pin, "minutes": minutes})
            if res.get("valid"):
                err_lbl.config(text="Tempo extra liberado!", fg="#27ae60")
                b.after(800, lambda: self._destroy_block())
            else:
                err_lbl.config(text="PIN incorreto", fg="#c00")
                pin_entry.delete(0, tk.END)
                pin_entry.focus_set()

        for mins, label in [(15, "+15"), (30, "+30"), (60, "+60")]:
            btn = tk.Button(
                btn_frame,
                text=label,
                font=("system-ui", int(base_size * 0.022), "bold"),
                bg=THEME["btn"],
                fg=THEME["btn_text"],
                activebackground=THEME["accent"],
                activeforeground=THEME["btn_text"],
                bd=0,
                padx=16,
                pady=8,
                cursor="hand2",
                command=lambda m=mins: do_extend(m),
            )
            btn.pack(side=tk.LEFT, padx=6)

        # Custom extend
        custom_frame = tk.Frame(card, bg=THEME["card"])
        custom_frame.pack(pady=(12, 0))

        custom_spin = tk.Spinbox(
            custom_frame,
            from_=1,
            to=180,
            width=5,
            font=("system-ui", int(base_size * 0.022)),
            bg="white",
            fg=THEME["text"],
        )
        custom_spin.pack(side=tk.LEFT, padx=(0, 6))
        custom_spin.delete(0, tk.END)
        custom_spin.insert(0, "15")

        custom_btn = tk.Button(
            custom_frame,
            text="Dar mais tempo",
            font=("system-ui", int(base_size * 0.022), "bold"),
            bg=THEME["btn"],
            fg=THEME["btn_text"],
            activebackground=THEME["accent"],
            activeforeground=THEME["btn_text"],
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=lambda: do_extend(int(custom_spin.get())),
        )
        custom_btn.pack(side=tk.LEFT)

        # Exit button
        exit_btn = tk.Button(
            card,
            text="Sair",
            font=("system-ui", int(base_size * 0.022), "bold"),
            bg=THEME["smallbtn_bg"],
            fg=THEME["text"],
            activebackground=THEME["input_border"],
            activeforeground=THEME["text"],
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=lambda: sair(),
        )
        exit_btn.pack(pady=(16, 0))

        def sair():
            resultado = sair_com_pin(pin_entry.get())
            if resultado == "saiu":
                kill_browser()  # o servidor já fechou; garante, como antes
                sys.exit(0)
            textos = {
                "pin": "Digite o PIN para sair" if not pin_entry.get() else "PIN incorreto",
                "espera": "Muitas tentativas. Espere um pouco.",
            }
            err_lbl.config(text=textos.get(resultado, "Não deu para sair. Tente de novo."), fg="#c00")
            pin_entry.delete(0, tk.END)
            pin_entry.focus_set()

        # Trap Escape to prevent closing
        b.bind("<Escape>", lambda e: None)
        b.bind("<Alt-F4>", lambda e: None)
        b.bind("<Button-3>", lambda e: None)

        # Keep trying to stay on top
        def stay_top():
            try:
                b.lift()
                b.attributes("-topmost", True)
                b.focus_force()
            except tk.TclError:
                return
            b.after(500, stay_top)

        stay_top()

    def _destroy_block(self):
        if self.block_window is not None:
            try:
                self.block_window.destroy()
            except tk.TclError:
                pass
            self.block_window = None

    def tick(self):
        if not self.polling:
            return
        data = api("/api/timer/status")
        self.status = data
        remaining = data.get("remainingSeconds", 0)
        if data:  # servidor fora do ar: não mexe em nada
            acoes = decidir(
                data,
                self.block_window is not None,
                self.warn_window is not None,
                lambda: bool(api("/api/timer/tela").get("menuNaFrente")),
            )
            if "fechar_bloqueio" in acoes:
                self._destroy_block()
            if "fechar_aviso" in acoes:
                self._destroy_warn()
            if "bloquear" in acoes:
                self.show_block()
            if "aviso" in acoes:
                self.show_warning(max(1, remaining // 60))

        self.root.after(self.poll_interval, self.tick)

    def run(self):
        self.tick()
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    global BASE_URL
    BASE_URL = f"http://127.0.0.1:{args.port}"
    app = WatchdogApp()
    app.run()


if __name__ == "__main__":
    main()
