#!/usr/bin/env python3
"""Fullscreen timer watchdog: blocks the screen when time is up.
Runs outside the browser so it also covers native apps and games."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
import urllib.error
import urllib.request

import timer_fim
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


def xid_da_janela(janela):
    """XID de fora da janela Tk, ou None se não der para ler."""
    try:
        frame = janela.tk.call("wm", "frame", janela._w)
        return int(str(frame), 0)
    except Exception:  # noqa: BLE001
        try:
            return int(janela.winfo_id())
        except Exception:  # noqa: BLE001
            return None


def _log_windows(texto):
    if os.name != "nt":
        return
    try:
        caminho = os.path.join(CACHE_DIR, "beni-windows.log")
        with open(caminho, "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except OSError:
        pass


def janela_na_frente(janela, campo, plataforma=None):
    """Põe a tela de tempo esgotado no primeiro plano e o foco num campo dela.

    Roteiro 17/18: a tela aparecia por cima, mas o teclado não entrava.
    - O stay_top fazia focus_force() na janela inteira a cada 500 ms, o que
      tirava o foco do campo do PIN (e do de minutos). Agora só põe o foco no
      PIN quando ele não está em nenhum campo desta tela.
    - No Windows, um processo de fundo não toma o primeiro plano só com o
      focus_force do Tk: o teclado continuava indo para a janela de baixo (um
      "5" foi para o PIN do menu nativo). trazer_para_frente usa o
      SetForegroundWindow (com o truque do Alt), sem AttachThreadInput (roteiro 31)."""
    if plataforma is None and os.name == "nt":
        try:
            import plataforma_windows as plataforma
        except Exception:
            plataforma = None
    if plataforma is not None:
        try:
            if plataforma.pid_da_janela_ativa() != os.getpid():
                plataforma.trazer_para_frente(plataforma.raiz_da_janela(janela.winfo_id()))
        except Exception:
            pass
    try:
        atual = janela.focus_get()
    except Exception:
        atual = None
    # num campo desta tela (PIN ou minutos): deixa onde está
    if atual is None or not str(atual).startswith(str(janela) + "."):
        campo.focus_force()


# Logo depois de a vigia abrir (o Benikids acabou de abrir), o menu ainda não
# está registrado nem na frente: a tela de tempo esgotado espera por ele.
PARTIDA_SEGUNDOS = 12


def decidir(status, bloqueio_aberto, aviso_aberto, menu_na_frente, partida=False, app_aberto=False):
    """O que a vigia faz a cada volta. `menu_na_frente` é chamado só quando
    importa (pergunta ao servidor); `partida` = a vigia abriu há pouco. Devolve
    uma lista de ações: "bloquear", "fechar_bloqueio", "aviso", "fechar_aviso",
    "fechar_app" (timer da sessão acabou e ainda há app aberto)."""
    acoes = []
    if status.get("expired"):
        # com o menu na frente e sem app aberto, a tela é a do próprio menu
        if app_aberto:
            # a pílula também fecha; se ela travou, a vigia fecha do mesmo jeito
            acoes.append("fechar_app")
        if bloqueio_aberto or not (partida or menu_na_frente()):
            acoes.append("bloquear")
        if aviso_aberto:
            acoes.append("fechar_aviso")
        return acoes
    if bloqueio_aberto:
        # tempo estendido por outra tela (menu, área dos pais, API) ou timer parado
        acoes.append("fechar_bloqueio")
    if status.get("warning"):
        menu = partida or menu_na_frente()
        if not aviso_aberto and not menu:
            acoes.append("aviso")
        elif aviso_aberto and menu:
            # roteiro 19: o aviso foi decidido com a área dos pais na frente e
            # continuou depois do "Voltar", junto com o do menu
            acoes.append("fechar_aviso")
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
        self.aberto_em = time.monotonic()
        self._fechar_app = threading.Lock()
        self._cobrir = threading.Lock()

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

        # Keep trying to stay on top (sem roubar o foco do campo em que se digita)
        def stay_top():
            try:
                b.lift()
                b.attributes("-topmost", True)
                janela_na_frente(b, pin_entry)
                # fora da thread do Tk: wmctrl/xdotool não podem travar o PIN
                self._pedir_cobrir(xid_da_janela(b))
            except tk.TclError:
                return
            except Exception:  # noqa: BLE001 — a tela continua; o WM que falhou
                pass
            b.after(500, stay_top)

        b.update_idletasks()
        stay_top()

    def _destroy_block(self):
        if self.block_window is not None:
            try:
                self.block_window.destroy()
            except tk.TclError:
                pass
            self.block_window = None
            if os.name != "nt":
                # o tempo foi estendido e o app sobreviveu: devolve o Alt+Tab
                try:
                    timer_fim.restaurar_app()
                except Exception:  # noqa: BLE001
                    pass

    def _pedir_cobrir(self, xid):
        if os.name == "nt" or not self._cobrir.acquire(blocking=False):
            return

        def cobrir():
            try:
                timer_fim.por_o_bloqueio_na_frente(bloqueio=xid)
            except Exception:  # noqa: BLE001
                pass
            finally:
                self._cobrir.release()

        try:
            threading.Thread(target=cobrir, name="cobrir-bloqueio", daemon=True).start()
        except Exception:  # noqa: BLE001
            self._cobrir.release()

    def _fechar_app_do_timer(self):
        """SIGTERM e, se continuar, SIGKILL — o mesmo contrato do ✕. Uma vez
        por vez: o poll de 5 s não empilha esperas."""
        if not self._fechar_app.acquire(blocking=False):
            return
        try:
            ok = timer_fim.tratar_expiracao(self.status)
            if ok:
                _log_windows("vigia: o timer acabou; o app foi encerrado")
        except Exception:  # noqa: BLE001 — a tela de bloqueio continua
            pass
        finally:
            self._fechar_app.release()

    def tick(self):
        if not self.polling:
            return
        data = api("/api/timer/status")
        self.status = data
        remaining = data.get("remainingSeconds", 0)
        if data:  # servidor fora do ar: não mexe em nada
            try:
                aberto = timer_fim.app_aberto()
            except Exception:  # noqa: BLE001
                aberto = False
            acoes = decidir(
                data,
                self.block_window is not None,
                self.warn_window is not None,
                lambda: bool(api("/api/timer/tela").get("menuNaFrente")),
                partida=time.monotonic() - self.aberto_em < PARTIDA_SEGUNDOS,
                app_aberto=aberto,
            )
            if "fechar_bloqueio" in acoes:
                self._destroy_block()
            if "fechar_aviso" in acoes:
                self._destroy_warn()
            if "bloquear" in acoes:
                self.show_block()
            if "fechar_app" in acoes:
                threading.Thread(
                    target=self._fechar_app_do_timer,
                    name="fechar-app-timer",
                    daemon=True,
                ).start()
            if "aviso" in acoes:
                self.show_warning(max(1, (remaining + 59) // 60))  # para cima, como a pílula e o menu

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
    try:
        import telemetria

        telemetria.instalar_excepthook("vigia")
    except Exception:  # noqa: BLE001
        pass
    app = WatchdogApp()
    app.run()


if __name__ == "__main__":
    main()
