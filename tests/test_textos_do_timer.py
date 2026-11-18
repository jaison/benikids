"""Textos do timer no menu web e na moldura do navegador (roteiro 25: a área dos pais
mostrava "Faltam 1 minutes" e "Faltam 14 minutes")."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "src"


def funcoes_do_timer():
    codigo = (RAIZ / "frontend" / "runtime-controls.js").read_text(encoding="utf-8")
    return codigo[:codigo.index("async function pollTimer")]


class TextosDoTimerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "sem node")
    def test_singular_and_plural_in_portuguese(self):
        pt = json.loads((RAIZ / "frontend" / "locales" / "pt.json").read_text(encoding="utf-8"))
        script = (f"const uiText={json.dumps(pt)};\n" + funcoes_do_timer() +
                  "\nconsole.log(JSON.stringify([formatTimeLeft(60), formatTimeLeft(14*60), formatTimeLeft(59),"
                  " formatTimeLeft(61), formatTime(5*60)]));")
        saida = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(saida), ["Falta 1 minuto", "Faltam 14 minutos", "Falta 1 minuto",
                                            "Faltam 2 minutos", "5 minutos"])

    def test_every_locale_has_the_new_keys(self):
        for nome in ("pt", "en", "de"):
            dados = json.loads((RAIZ / "frontend" / "locales" / f"{nome}.json").read_text(encoding="utf-8"))
            for chave in ("timerRemainingOne", "timerOneMinute", "timerManyMinutes"):
                self.assertIn(chave, dados, nome)

    def test_no_hardcoded_english_minutes_left_on_screen(self):
        for arquivo in [RAIZ / "browser.html", RAIZ / "index.html", *sorted((RAIZ / "frontend").glob("*.js"))]:
            texto = arquivo.read_text(encoding="utf-8")
            if arquivo.name == "state.js":
                continue  # textos em inglês de reserva, trocados pelo idioma escolhido
            self.assertIsNone(re.search(r"['\"]\s?minutes?['\"]", texto), arquivo.name)


if __name__ == "__main__":
    unittest.main()
