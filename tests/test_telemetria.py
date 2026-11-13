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

        self.para = []
        self.historico = {}

        def enviar(corpo, endereco=telemetria.ENDERECO):
            self.enviados.append(corpo)
            self.para.append(endereco)
            return self.resposta

        self.fila = os.path.join(self.tmp.name, "problemas.jsonl")
        self.t = telemetria.Telemetria(self.estado, lambda: self.cfg, lambda: "1.2.3", lambda: "nativo",
                                       enviar=enviar, agora=lambda: self.relogio[0],
                                       ler_historico=lambda: self.historico, fila=self.fila)

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


class UsoTest(TelemetriaTest):
    def perfil(self, **extra):
        p = {"id": "default", "name": "Lívia", "telemetryId": "c" * 32, "birthMonth": "2018-05",
             "gender": "menina", "tiles": [{"id": "gcompris", "label": "GCompris", "category": "educativo"}]}
        p.update(extra)
        return p

    def test_faixa_etaria_a_partir_do_mes_e_ano(self):
        self.assertEqual(telemetria.faixa_etaria("2018-05", "2026-04-30"), "6-7")  # ainda 7 antes de maio
        self.assertEqual(telemetria.faixa_etaria("2018-05", "2026-05-01"), "8-10")
        self.assertEqual(telemetria.faixa_etaria("2023-01", "2026-06-01"), "0-3")
        self.assertIsNone(telemetria.faixa_etaria(None, "2026-06-01"))

    def test_relatorio_de_uso_e_anonimo(self):
        cfg = {"profiles": [self.perfil()]}
        historico = {"default": {"2026-11-12": {"totalSeconds": 1800, "categories": {"educativo": 1800},
                                                "tiles": {"gcompris": 1500, "outro": 20}}}}
        dias = telemetria.relatorio_de_uso(cfg, historico)
        self.assertEqual(dias, [{"crianca": "c" * 32, "faixa": "8-10", "genero": "menina", "dia": "2026-11-12",
                                 "minutos": 30, "categorias": {"educativo": 30},
                                 "apps": [{"app": "gcompris", "nome": "GCompris", "categoria": "educativo",
                                           "minutos": 25}]}])
        texto = json.dumps(dias, ensure_ascii=False)
        self.assertNotIn("Lívia", texto)
        self.assertNotIn("2018", texto)  # a data de nascimento não sai

    def test_uso_so_com_a_caixinha_e_so_a_partir_do_dia_em_que_ligou(self):
        self.historico = {"default": {"2026-01-01": {"totalSeconds": 600, "categories": {}, "tiles": {"gcompris": 600}}}}
        self.cfg = {"profiles": [self.perfil()]}
        self.assertFalse(self.t.enviar_uso())  # desligado (padrão)
        self.cfg["usageTelemetryEnabled"] = True
        self.relogio[0] = 1_767_225_600.0 + 86400 * 10  # alguns dias depois de 2026-01-01
        self.assertFalse(self.t.enviar_uso())  # liga hoje: o dia antigo não vai
        desde = telemetria.ler_estado(self.estado)["uso_desde"]
        self.historico["default"][desde] = {"totalSeconds": 120, "categories": {}, "tiles": {"gcompris": 120}}
        self.assertTrue(self.t.enviar_uso())
        self.assertEqual([d["dia"] for d in self.enviados[-1]["dias"]], [desde])
        self.assertEqual(self.para[-1], telemetria.ENDERECO_USO)
        self.assertFalse(self.t.enviar_uso())  # já enviado

    def test_problemas_vao_limpos_e_so_com_a_telemetria_ligada(self):
        casa = os.path.expanduser("~")
        telemetria.relatar_problema("instalar", f"falhou em {casa}\\x.msi para ana@exemplo.com", fila=self.fila)
        self.assertEqual(self.t.enviar_problemas(), 1)
        enviado = self.enviados[-1]
        self.assertEqual(self.para[-1], telemetria.ENDERECO_PROBLEMA)
        self.assertNotIn(casa, enviado["detalhe"])
        self.assertIn("%USERPROFILE%", enviado["detalhe"])
        self.assertIn("<email>", enviado["detalhe"])
        self.assertEqual(enviado["etapa"], "instalar")
        self.cfg = {"telemetryEnabled": False}
        telemetria.relatar_problema("instalar", "x", fila=self.fila)
        self.assertEqual(self.t.enviar_problemas(), 0)
        self.assertFalse(os.path.exists(self.fila))  # descartado, não fica guardando


if __name__ == "__main__":
    unittest.main()
