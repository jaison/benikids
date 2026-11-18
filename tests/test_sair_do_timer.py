"""Roteiro 34 (aprovado pelo mantenedor): na tela "Acabou o tempo!", o PIN já digitado
vale para o Sair, nos dois menus. Vazio ou errado: a tela de PIN de sempre. O log de
teclas dessa tela diz só "dígito" ou "outra", nunca o valor."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


class SairDoTimerTests(unittest.TestCase):
    def test_native_menu_uses_the_typed_pin(self):
        rs = (RAIZ / "cliente" / "src" / "menu.rs").read_text(encoding="utf-8")
        self.assertIn("fn sair_do_timer(", rs)
        self.assertIn('api.post("/api/verify-pin", Some(&json!({"pin": pin})))', rs)
        # o Sair da tela (clique e Enter) passa pelo sair_do_timer
        tela = rs[rs.index("Janela::TimerEsgotado { pin, erro, foco } => {"):]
        tela = tela[:tela.index("Janela::Pin {")]
        self.assertIn("m.sair_do_timer(cx);", tela)
        self.assertNotIn("pedir_pin(AcaoPin::Sair", tela)
        self.assertIn("if foco == 3 {\n                            self.sair_do_timer(cx);", rs)

    def test_key_log_never_has_the_value(self):
        rs = (RAIZ / "cliente" / "src" / "menu.rs").read_text(encoding="utf-8")
        linhas = [linha for linha in rs.splitlines() if "tela Acabou o tempo: tecla" in linha]
        self.assertEqual(len(linhas), 1)
        self.assertIn('if digito.is_some() { "dígito" } else { "outra" }', linhas[0])
        self.assertNotRegex(linhas[0], r"\{(d|k|pin|digito)\}")

    def test_web_menu_does_the_same(self):
        html = (RAIZ / "src" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="timerBlockExitBtn" class="smallbtn" onclick="exitFromBlock()"', html)
        js = (RAIZ / "src" / "frontend" / "runtime-controls.js").read_text(encoding="utf-8")
        corpo = js[js.index("async function exitFromBlock(){"):]
        corpo = corpo[:corpo.index("\n}\n")]
        self.assertIn("if(!cfg.pinConfigured||!pin){ exitKids(); return; }", corpo)
        self.assertIn("fetch('/api/verify-pin'", corpo)
        self.assertIn("fetch('/exit-kids',{method:'POST'})", corpo)
        self.assertIn("err.textContent=uiText.pinWrong", corpo)
        self.assertFalse(re.search(r"console\.log", corpo))


if __name__ == "__main__":
    unittest.main()
