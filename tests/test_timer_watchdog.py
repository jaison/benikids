"""timer_watchdog: uma tela de tempo esgotado só, fechar quando o tempo é
estendido em outro lugar, e "Sair" que só sai com o PIN certo."""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def carregar():
    tk = types.ModuleType("tkinter")
    fonte = types.ModuleType("tkinter.font")
    tk.font = fonte
    with mock.patch.dict(sys.modules, {"tkinter": tk, "tkinter.font": fonte}):
        sys.modules.pop("timer_watchdog", None)
        return importlib.import_module("timer_watchdog")


tw = carregar()


class DecidirTest(unittest.TestCase):
    def test_tempo_esgotado_com_o_menu_na_frente_fica_so_a_tela_do_menu(self):
        # roteiro 17: eram duas telas, a rosa por cima e a do menu (com o teclado) por baixo
        self.assertEqual(tw.decidir({"active": True, "expired": True}, False, False, lambda: True), [])

    def test_tempo_esgotado_com_app_na_frente_bloqueia(self):
        self.assertEqual(tw.decidir({"active": True, "expired": True}, False, False, lambda: False), ["bloquear"])

    def test_bloqueio_aberto_continua_sem_perguntar(self):
        perguntou = mock.Mock(return_value=True)
        self.assertEqual(tw.decidir({"expired": True}, True, True, perguntou), ["bloquear", "fechar_aviso"])
        perguntou.assert_not_called()

    def test_tempo_estendido_em_outro_lugar_fecha_a_tela(self):
        # roteiro 17: /api/timer/extend com o PIN certo não fechava a tela rosa
        self.assertEqual(tw.decidir({"active": True, "expired": False}, True, False, lambda: False),
                         ["fechar_bloqueio"])
        self.assertEqual(tw.decidir({"active": False}, True, False, lambda: False), ["fechar_bloqueio"])

    def test_aviso_so_quando_o_menu_nao_mostra_o_dele(self):
        st = {"active": True, "warning": True}
        self.assertEqual(tw.decidir(st, False, False, lambda: False), ["aviso"])
        self.assertEqual(tw.decidir(st, False, False, lambda: True), [])
        self.assertEqual(tw.decidir({"active": True}, False, True, lambda: False), ["fechar_aviso"])


class SairComPinTest(unittest.TestCase):
    def servidor(self, pin_certo="1234", bloqueado=False, sem_pin=False):
        chamadas = []

        def pedir(metodo, caminho, dados=None, cookie=""):
            chamadas.append((caminho, dados, cookie))
            if caminho == "/api/verify-pin":
                if bloqueado:
                    return 429, {"valid": False}, {}
                if sem_pin:
                    return 200, {"valid": True, "pinConfigured": False}, {}
                if dados.get("pin") == pin_certo:
                    return 200, {"valid": True}, {"Set-Cookie": "cozy_admin=abc; Path=/; HttpOnly"}
                return 403, {"valid": False}, {}
            if caminho == "/exit-kids":
                return (204 if cookie == "cozy_admin=abc" or sem_pin else 403), None, {}
            raise AssertionError(caminho)

        return pedir, chamadas

    def test_pin_certo_sai_com_o_cookie_de_admin(self):
        pedir, chamadas = self.servidor()
        self.assertEqual(tw.sair_com_pin("1234", pedir), "saiu")
        self.assertEqual(chamadas[-1], ("/exit-kids", {}, "cozy_admin=abc"))

    def test_pin_errado_ou_vazio_nao_sai_nem_chama_o_exit(self):
        for pin in ("9999", "", None):
            pedir, chamadas = self.servidor()
            self.assertEqual(tw.sair_com_pin(pin, pedir), "pin")
            self.assertNotIn("/exit-kids", [c[0] for c in chamadas])

    def test_muitas_tentativas(self):
        pedir, chamadas = self.servidor(bloqueado=True)
        self.assertEqual(tw.sair_com_pin("1234", pedir), "espera")
        self.assertEqual(len(chamadas), 1)

    def test_sem_pin_configurado_sai(self):
        pedir, _ = self.servidor(sem_pin=True)
        self.assertEqual(tw.sair_com_pin("", pedir), "saiu")

    def test_servidor_fora_do_ar_nao_sai(self):
        self.assertEqual(tw.sair_com_pin("1234", lambda *a, **k: (0, None, {})), "erro")

    def test_botao_sair_nao_mata_o_menu_sem_o_pin(self):
        texto = (Path(tw.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("def exit_kids", texto)
        trecho = texto[texto.index("def sair():"):texto.index("err_lbl.config(text=textos")]
        self.assertLess(trecho.index('if resultado == "saiu":'), trecho.index("kill_browser()"))


if __name__ == "__main__":
    unittest.main()



class BotaoDoTimerTest(unittest.TestCase):
    def test_botao_mostra_o_estado_e_faz_o_que_diz(self):
        # roteiro 17: "Iniciar timer" com o timer ligado, e o clique o parava
        raiz = Path(__file__).resolve().parent.parent / "src" / "frontend"
        js = (raiz / "runtime-controls.js").read_text(encoding="utf-8")
        self.assertIn("lastTimerStatus=data;\n    atualizarBotaoTimer();", js)
        self.assertIn("btn.dataset.acao=ligado?'parar':'iniciar';", js)
        self.assertIn("const parar=btn.dataset.acao?btn.dataset.acao==='parar'", js)
        ps = (raiz / "parent-settings.js").read_text(encoding="utf-8")
        self.assertIn("atualizarBotaoTimer();", ps)
        self.assertNotIn("setIconLabel(timerBtn,'timer'", ps)
