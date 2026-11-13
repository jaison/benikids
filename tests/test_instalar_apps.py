import os
import queue
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import instalar_apps  # noqa: E402


def avisos_de(fila):
    saida = []
    while True:
        try:
            saida.append(fila.get_nowait())
        except queue.Empty:
            return saida


class InstalarAppsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memoria = os.path.join(self.tmp.name, "Benikids", "pedem-senha.json")
        patcher = mock.patch.object(instalar_apps, "_memoria", return_value=self.memoria)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_lembra_os_apps_que_pediram_senha(self):
        self.assertEqual(instalar_apps.pedem_senha(), set())
        instalar_apps.lembrar_que_pede_senha("tuxpaint")
        instalar_apps.lembrar_que_pede_senha("supertux")
        instalar_apps.lembrar_que_pede_senha("tuxpaint")
        self.assertEqual(instalar_apps.pedem_senha(), {"tuxpaint", "supertux"})

    def test_precisa_de_senha_pelo_catalogo_ou_pela_memoria(self):
        self.assertTrue(instalar_apps.precisa_de_senha({"id": "a", "escopo": "machine"}))
        self.assertFalse(instalar_apps.precisa_de_senha({"id": "b", "escopo": "user"}))
        self.assertTrue(instalar_apps.precisa_de_senha({"id": "b", "escopo": "user"}, {"b"}))

    def test_le_o_tipo_do_instalador_do_winget_show(self):
        saida = "Found Tux Paint [NewBreedSoftware.TuxPaint]\nInstaller:\n  Installer Type: inno\n  Installer Url: x\n"
        self.assertEqual(instalar_apps.ler_tipo(saida), "inno")
        self.assertEqual(instalar_apps.ler_tipo("nada aqui"), "")
        self.assertEqual(instalar_apps.tipo_do_instalador({"instalador": "msi", "winget": "X"}), "msi")

    def test_sem_senha_primeiro_e_quem_falha_vai_para_o_lote_do_fim(self):
        itens = [
            {"id": "maquina", "winget": "A.Maquina", "escopo": "machine"},
            {"id": "usuario", "winget": "B.Usuario", "escopo": "user"},
            {"id": "teimoso", "winget": "C.Teimoso", "escopo": "user"},
        ]
        ordem = []

        def instalar(item, ao_pedir_senha=None):
            ordem.append(item["id"])
            return (item["id"] == "usuario"), "x"

        lote = []
        with mock.patch.object(instalar_apps.catalogo_windows, "localizar", return_value=None), \
             mock.patch.object(instalar_apps, "instalar", side_effect=instalar), \
             mock.patch.object(instalar_apps, "baixar", side_effect=lambda item, pasta: f"{item['id']}.exe"), \
             mock.patch.object(instalar_apps, "instalar_como_admin", side_effect=lambda pares, pasta, ao_terminar=None: lote.extend(i["id"] for i, _ in pares) or {}):
            fila = queue.Queue()
            instalar_apps.trabalhar(itens, fila)
        self.assertEqual(ordem, ["usuario", "teimoso"])  # o "machine" nem passa pela fila sem senha
        self.assertEqual(lote, ["maquina", "teimoso"])  # um só pedido de senha, no fim
        self.assertEqual(instalar_apps.pedem_senha(), {"teimoso"})  # da próxima vez vai direto ao lote
        estados = [(i, e) for i, e, _ in avisos_de(fila) if i]
        self.assertIn(("usuario", "ok"), estados)
        self.assertIn(("teimoso", "espera"), estados)

    def test_o_lote_com_senha_baixa_enquanto_os_outros_instalam(self):
        import threading
        itens = [
            {"id": "usuario", "winget": "B.Usuario", "escopo": "user"},
            {"id": "maquina", "winget": "A.Maquina", "escopo": "machine"},
        ]
        comecou_a_baixar = threading.Event()
        baixou_durante = []

        def baixar(item, pasta):
            comecou_a_baixar.set()
            return f"{item['id']}.msi"

        def instalar(item, ao_pedir_senha=None):
            baixou_durante.append(comecou_a_baixar.wait(2))
            return True, "instalado"

        with mock.patch.object(instalar_apps.catalogo_windows, "localizar", return_value=None), \
             mock.patch.object(instalar_apps, "instalar", side_effect=instalar), \
             mock.patch.object(instalar_apps, "baixar", side_effect=baixar), \
             mock.patch.object(instalar_apps, "instalar_como_admin") as admin:
            instalar_apps.trabalhar(itens, queue.Queue(), pasta=self.tmp.name)
        self.assertEqual(baixou_durante, [True])
        admin.assert_called_once()
        self.assertEqual([i["id"] for i, _ in admin.call_args[0][0]], ["maquina"])

    def test_script_do_lote_instala_dependencias_antes_e_anota_os_codigos(self):
        pasta = self.tmp.name
        app = os.path.join(pasta, "etr", "ETR.msi")
        dep = os.path.join(pasta, "etr", "Dependencies", "VCRedist", "vc_redist.x64.exe")
        os.makedirs(os.path.dirname(dep))
        for caminho in (app, dep):
            open(caminho, "w").close()
        open(os.path.join(pasta, "etr", "Dependencies", "leia.txt"), "w").close()
        item = {"id": "etr", "winget": "X.ETR", "instalador": "msi"}
        texto, resultados = instalar_apps.script_admin([(item, app)], pasta)
        linhas = texto.splitlines()
        i_dep = next(n for n, l in enumerate(linhas) if "vc_redist.x64.exe" in l)
        i_app = next(n for n, l in enumerate(linhas) if "ETR.msi" in l)
        self.assertLess(i_dep, i_app)
        self.assertIn("ALLUSERS=1", linhas[i_app])
        # uma string só em -ArgumentList, com cada caminho entre aspas uma única vez
        self.assertIn(f"-ArgumentList '/i \"{app}\" /qn /norestart ALLUSERS=1 /l*v \"", linhas[i_app])
        self.assertNotIn("@(", linhas[i_app])
        self.assertIn("/l*v", linhas[i_app])
        self.assertIn("etr.log", linhas[i_app])
        self.assertIn("-PassThru", linhas[i_app])
        self.assertIn("'etr|'", linhas[i_app])
        self.assertIn("'etr-dependencia1|'", linhas[i_dep])
        self.assertTrue(linhas[-1].endswith("'fim|0'"))
        with open(resultados, "w", encoding="utf-8-sig") as f:
            f.write("etr-dependencia1|0\netr|1603\nfim|0\n")
        self.assertEqual(instalar_apps.ler_resultados(resultados),
                         {"etr-dependencia1": "0", "etr": "1603", "fim": "0"})

    def test_avisa_quando_o_windows_abre_o_uac_numa_instalacao_por_usuario(self):
        itens = [{"id": "eleva", "winget": "D.Eleva", "escopo": "user"}]

        def instalar(item, ao_pedir_senha=None):
            ao_pedir_senha()
            return True, "instalado"

        with mock.patch.object(instalar_apps.catalogo_windows, "localizar", return_value=None), \
             mock.patch.object(instalar_apps, "instalar", side_effect=instalar):
            fila = queue.Queue()
            instalar_apps.trabalhar(itens, fila)
        self.assertEqual(instalar_apps.pedem_senha(), {"eleva"})
        textos = [t for i, _e, t in avisos_de(fila) if i == "eleva"]
        self.assertIn("o Windows pediu a senha de um adulto", textos)


if __name__ == "__main__":
    unittest.main()
