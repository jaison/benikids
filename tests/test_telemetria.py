import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import telemetria  # noqa: E402

CAMPOS = {"id", "versao", "plataforma", "sistema", "cpu", "ram_gb", "gpu", "menu", "tela", "idioma"}


class TelemetriaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.estado = os.path.join(self.tmp.name, "cfg", "telemetria.json")
        self.cfg = {}
        self.enviados = []
        self.relogio = [1_000_000.0]
        self.resposta = True

        def enviar(corpo):
            self.enviados.append(corpo)
            return self.resposta

        self.t = telemetria.Telemetria(self.estado, lambda: self.cfg, lambda: "1.2.3", lambda: "nativo",
                                       enviar=enviar, agora=lambda: self.relogio[0])

    def test_envia_so_os_campos_anonimos_uma_vez_por_dia(self):
        self.assertTrue(self.t.talvez_enviar())
        corpo = self.enviados[0]
        self.assertEqual(set(corpo), CAMPOS)
        self.assertRegex(corpo["id"], r"^[0-9a-f]{32}$")
        self.assertEqual((corpo["versao"], corpo["menu"]), ("1.2.3", "nativo"))
        self.assertFalse(self.t.talvez_enviar())  # mesmo dia
        self.relogio[0] += 24 * 3600
        self.assertTrue(self.t.talvez_enviar())
        self.assertEqual(self.enviados[1]["id"], corpo["id"])  # o mesmo número aleatório

    def test_desligada_pelos_pais_nao_envia(self):
        self.cfg = {"telemetryEnabled": False}
        self.assertFalse(self.t.talvez_enviar())
        self.assertEqual(self.enviados, [])

    def test_sem_internet_tenta_de_novo_depois(self):
        self.resposta = False
        self.assertFalse(self.t.talvez_enviar())
        self.resposta = True
        self.assertTrue(self.t.talvez_enviar())

    def test_previa_mostra_o_mesmo_id_que_sera_enviado(self):
        previa = self.t.previa()
        self.assertEqual(set(previa), CAMPOS)
        self.t.talvez_enviar()
        self.assertEqual(self.enviados[0]["id"], previa["id"])
        with open(self.estado, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], previa["id"])

    def test_estado_estragado_gera_um_id_novo(self):
        os.makedirs(os.path.dirname(self.estado))
        with open(self.estado, "w") as f:
            f.write("{nada")
        self.assertRegex(telemetria.ler_estado(self.estado)["id"], r"^[0-9a-f]{32}$")


if __name__ == "__main__":
    unittest.main()
