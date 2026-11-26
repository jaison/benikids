import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

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

    def test_fora_de_windows_e_linux_nao_liga_a_thread(self):
        # o Mac de quem desenvolve não pode entrar na contagem de instalações
        from unittest import mock
        with mock.patch.object(telemetria, "SISTEMA_SUPORTADO", False), \
             mock.patch.object(telemetria.threading, "Thread") as thread:
            self.t.iniciar(primeira_espera=0)
        thread.assert_not_called()
        with mock.patch.object(telemetria, "SISTEMA_SUPORTADO", True), \
             mock.patch.object(telemetria.threading, "Thread") as thread:
            self.t.iniciar(primeira_espera=0)
        thread.assert_called_once()

    def test_desligada_pelos_pais_nao_envia(self):
        self.cfg = {"telemetryEnabled": False}
        self.assertFalse(self.t.talvez_enviar())
        self.assertEqual(self.enviados, [])

    def test_sem_setup_nada_envia_e_o_que_ja_estava_na_fila_nao_vai_depois(self):
        self.cfg = {"setupCompleted": False, "usageTelemetryEnabled": True,
                    "profiles": [{"id": "default", "telemetryId": "c" * 32, "birthMonth": "2018-05",
                                  "tiles": []}]}
        self.historico = {"default": {"2026-11-12": {"totalSeconds": 600, "categories": {}, "tiles": {}}}}
        self.assertFalse(telemetria.relatar_problema(
            "instalar", "antes da escolha", fila=self.fila, por_dia=True,
            marcas=os.path.join(self.tmp.name, "marcas.json"), cfg=self.cfg))
        self.assertFalse(os.path.exists(self.fila))
        with open(self.fila, "w", encoding="utf-8") as f:
            f.write(json.dumps({"etapa": "instalar", "detalhe": "x", "assinatura": "instalar"}) + "\n")
        self.assertFalse(self.t.talvez_enviar())
        self.assertFalse(self.t.enviar_uso())
        self.assertEqual(self.enviados, [])
        self.assertFalse(os.path.exists(self.fila))
        self.assertFalse(os.path.exists(self.estado))
        self.cfg = {"setupCompleted": True, "telemetryEnabled": True}
        self.assertTrue(self.t.talvez_enviar())
        self.assertEqual(self.para, [telemetria.ENDERECO])

    def test_setup_concluido_com_telemetria_desligada_nada_envia(self):
        self.cfg = {"setupCompleted": True, "telemetryEnabled": False}
        telemetria.relatar_problema("instalar", "x", fila=self.fila, cfg=self.cfg)
        self.assertFalse(self.t.talvez_enviar())
        self.assertEqual(self.enviados, [])
        self.assertFalse(os.path.exists(self.fila))

    def test_setup_concluido_com_telemetria_ligada_envia(self):
        self.cfg = {"setupCompleted": True, "telemetryEnabled": True}
        self.assertTrue(self.t.talvez_enviar())
        self.assertEqual(self.para, [telemetria.ENDERECO])
        self.assertEqual(set(self.enviados[0]), CAMPOS)

    def test_config_antigo_sem_telemetry_enabled_envia(self):
        # instalação que já concluiu o setup antes deste campo: padrão continua ligado
        self.cfg = {"setupCompleted": True}
        self.assertTrue(telemetria.ligada(self.cfg))
        self.assertTrue(self.t.talvez_enviar())
        self.assertEqual(self.para, [telemetria.ENDERECO])

    def test_config_pendente_no_disco_nao_enfileira(self):
        caminho = os.path.join(self.tmp.name, "config.json")
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"setupCompleted": False}, f)
        with mock.patch.object(telemetria, "CONFIG_JSON", caminho):
            self.assertFalse(telemetria.relatar_problema("instalar", "x", fila=self.fila))
        self.assertFalse(os.path.exists(self.fila))
        with mock.patch.object(telemetria, "CONFIG_JSON", os.path.join(self.tmp.name, "nao-existe.json")):
            self.assertTrue(telemetria.relatar_problema("instalar", "x", fila=self.fila))
        self.assertTrue(os.path.exists(self.fila))

    def test_ao_subir_com_setup_pendente_descarta_a_fila_e_olha_de_novo_cedo(self):
        self.cfg = {"setupCompleted": False}
        with open(self.fila, "w", encoding="utf-8") as f:
            f.write("{}\n")
        with mock.patch.object(telemetria, "SISTEMA_SUPORTADO", True), \
             mock.patch.object(telemetria.threading, "Thread"):
            self.t.iniciar()
        self.assertFalse(os.path.exists(self.fila))
        self.assertEqual(telemetria.espera_da_proxima_tentativa(self.cfg, 3600), 30)
        self.assertEqual(telemetria.espera_da_proxima_tentativa(
            {"setupCompleted": True}, 3600), 3600)

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

    def test_estado_estragado_grava_um_id_e_repete_o_mesmo(self):
        os.makedirs(os.path.dirname(self.estado))
        with open(self.estado, "w") as f:
            f.write("{nada")
        primeiro = telemetria.ler_estado(self.estado)
        self.assertRegex(primeiro["id"], r"^[0-9a-f]{32}$")
        with open(self.estado, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], primeiro["id"])
        telemetria._memoria.clear()
        self.assertEqual(telemetria.ler_estado(self.estado)["id"], primeiro["id"])
        self.assertFalse(any(nome.endswith(".tmp") and ".tmp." not in nome
                             for nome in os.listdir(os.path.dirname(self.estado))))

    def test_dois_fios_gravam_o_mesmo_id(self):
        ids = []

        def pega():
            ids.append(telemetria.ler_estado(self.estado)["id"])

        fios = [threading.Thread(target=pega) for _ in range(8)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join()
        self.assertEqual(len(set(ids)), 1)
        with open(self.estado, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], ids[0])

    def test_tmp_do_estado_leva_o_pid(self):
        vistos = []
        real = os.replace

        def guarda(origem, destino):
            vistos.append(origem)
            return real(origem, destino)

        with mock.patch("telemetria.os.replace", side_effect=guarda):
            telemetria.ler_estado(self.estado)
        self.assertTrue(vistos)
        self.assertTrue(all(str(os.getpid()) in caminho for caminho in vistos))
        self.assertFalse(any(caminho == self.estado + ".tmp" for caminho in vistos))

    def test_leitura_negada_nao_troca_o_id_nem_envia(self):
        self.assertTrue(self.t.talvez_enviar())
        original = self.enviados[0]["id"]
        self.enviados.clear()
        telemetria._memoria.clear()
        real = open

        def bloqueia(caminho, *args, **kwargs):
            if os.path.abspath(caminho) == os.path.abspath(self.estado):
                raise PermissionError("negado")
            return real(caminho, *args, **kwargs)

        self.relogio[0] += 24 * 3600
        with mock.patch("builtins.open", side_effect=bloqueia):
            self.assertIsNone(telemetria.ler_estado(self.estado))
            self.assertFalse(self.t.talvez_enviar())
        self.assertEqual(self.enviados, [])
        with open(self.estado, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], original)

    def test_leitura_negada_reusa_o_id_deste_processo(self):
        primeiro = telemetria.ler_estado(self.estado)["id"]
        real = open

        def bloqueia(caminho, *args, **kwargs):
            if os.path.abspath(caminho) == os.path.abspath(self.estado):
                raise PermissionError("negado")
            return real(caminho, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=bloqueia):
            self.assertEqual(telemetria.ler_estado(self.estado)["id"], primeiro)

    def test_se_nao_grava_o_id_nao_envia(self):
        with mock.patch("telemetria.os.replace", side_effect=OSError("disco")):
            self.assertFalse(self.t.talvez_enviar())
        self.assertEqual(self.enviados, [])
        self.assertFalse(os.path.exists(self.estado))

    def test_problema_e_ping_usam_o_id_gravado(self):
        telemetria.relatar_problema("instalar", "x", fila=self.fila)
        self.assertTrue(self.t.talvez_enviar())
        ids = {corpo["id"] for corpo in self.enviados}
        self.assertEqual(len(ids), 1)
        with open(self.estado, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], self.enviados[0]["id"])


class UsoTest(TelemetriaTest):
    def perfil(self, **extra):
        p = {"id": "default", "name": "Ângela", "telemetryId": "c" * 32, "birthMonth": "2018-05",
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
        self.assertNotIn("Ângela", texto)
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
