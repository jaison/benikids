"""Quiosque do Edge: a segunda janela fecha; a bolha de download fica."""
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import quiosque_edge as q  # noqa: E402


def janela(hwnd, classe, titulo="", dono=False, area=0, visivel=True):
    return {
        "hwnd": hwnd, "classe": classe, "titulo": titulo,
        "dono": dono, "area": area, "visivel": visivel,
    }


QUIOSQUE = janela("quiosque", "Chrome_WidgetWin_1", "Jogo", area=1920 * 1080)
POPUP = janela("popup", "Chrome_WidgetWin_1", "Powered by Ren'Py", area=800 * 600)
BOLHA = janela("bolha", "Chrome_WidgetWin_1", "", dono=True, area=400 * 200)


class DecisaoTests(unittest.TestCase):
    def test_a_primeira_janela_fica_e_a_segunda_fecha(self):
        estado = q.Estado()
        self.assertEqual(estado.para_cuidar([QUIOSQUE]), ["quiosque"])
        # a nova está na frente (primeira da lista) e não é adotada
        self.assertEqual(estado.para_cuidar([POPUP, QUIOSQUE]), ["quiosque"])
        fechadas = [j["hwnd"] for j in estado.observar([POPUP, QUIOSQUE])]
        self.assertEqual(fechadas, ["popup"])
        self.assertEqual(estado.principal, "quiosque")

    def test_as_duas_juntas_na_primeira_vista_ficam_com_a_maior(self):
        estado = q.Estado()
        # empate de tamanho: a do fundo (índice maior), que nasceu antes
        pequena_frente = janela("nova", "Chrome_WidgetWin_1", "Ctrl+N", area=100)
        pequena_fundo = janela("velha", "Chrome_WidgetWin_1", "Jogo", area=100)
        self.assertEqual(estado.para_cuidar([pequena_frente, pequena_fundo]), ["velha"])
        # a maior ganha mesmo estando atrás
        estado = q.Estado()
        self.assertEqual(estado.para_cuidar([POPUP, QUIOSQUE]), ["quiosque"])

    def test_dialogo_de_arquivo_impressao_e_menu_fecham_e_o_ime_fica(self):
        estado = q.Estado()
        estado.observar([QUIOSQUE])
        dialogo = janela("abrir", "#32770", "Abrir", dono=True, area=50000)
        salvar = janela("salvar", "#32770", "Salvar como", dono=True, area=50000)
        imprimir = janela("print", "#32770", "Imprimir", dono=True, area=70000)
        menu = janela("menu", "#32768", "Inspecionar", dono=True, area=20000)
        ime = janela("ime", "IME", "", dono=True, area=1000)
        outra = janela("ime2", "MSCTFIME UI", "", dono=False, area=1000)
        fechadas = {
            j["hwnd"]: j["classe"]
            for j in estado.observar([POPUP, dialogo, salvar, imprimir, menu, ime, outra, QUIOSQUE])
        }
        self.assertEqual(set(fechadas), {"popup", "abrir", "salvar", "print", "menu"})
        self.assertEqual(estado.para_cuidar([POPUP, dialogo, QUIOSQUE]), ["quiosque"])
        self.assertEqual(q.mensagens_para_fechar("#32770"), [(q.WM_COMMAND, q.IDCANCEL), (q.WM_CLOSE, 0)])
        self.assertEqual(q.mensagens_para_fechar("Chrome_WidgetWin_1"), [(q.WM_CLOSE, 0)])
        self.assertEqual(q.mensagens_para_fechar("#32768"), [(q.WM_CLOSE, 0)])

    def test_a_bolha_de_download_fica_e_janela_sem_titulo_fecha(self):
        estado = q.Estado()
        estado.observar([QUIOSQUE])
        sem_titulo = janela("nova", "Chrome_WidgetWin_1", "", area=1920 * 1080)
        grande_com_dono = janela("grande", "Chrome_WidgetWin_1", "", dono=True, area=800 * 600)
        com_titulo = janela("titulo", "Chrome_WidgetWin_1", "Downloads", dono=True, area=400 * 200)
        fechadas = [j["hwnd"] for j in estado.observar([sem_titulo, grande_com_dono, com_titulo, BOLHA, QUIOSQUE])]
        self.assertEqual(set(fechadas), {"nova", "grande", "titulo"})
        self.assertEqual([j["hwnd"] for j in estado.preservadas], ["bolha"])
        # a bolha não vira o app
        self.assertEqual(estado.para_cuidar([BOLHA, QUIOSQUE]), ["quiosque"])
        self.assertFalse(q.e_bolha_de_download(sem_titulo))
        self.assertFalse(q.e_bolha_de_download(grande_com_dono))
        self.assertFalse(q.e_bolha_de_download(com_titulo))
        self.assertTrue(q.e_bolha_de_download(BOLHA))
        self.assertTrue(q.e_bolha_de_download(janela("vazia", "Chrome_WidgetWin_1", "  ", dono=True, area=0)))

    def test_sumiu_a_do_quiosque_nao_adota_a_que_sobrou(self):
        estado = q.Estado()
        estado.observar([QUIOSQUE])
        self.assertEqual(estado.para_cuidar([POPUP]), [])
        self.assertEqual(estado.principal, "quiosque")
        fechadas = [j["hwnd"] for j in estado.observar([POPUP])]
        self.assertEqual(fechadas, ["popup"])
        # na volta seguinte a que sobrou continua não sendo o app
        self.assertEqual(estado.para_cuidar([POPUP]), [])
        # a bolha que sobrou também não é adotada
        self.assertEqual(estado.para_cuidar([BOLHA]), [])
        self.assertEqual(estado.observar([BOLHA]), [])

    def test_firefox_nao_entra_no_vigia(self):
        estado = q.Estado()
        firefox = janela("ff", "MozillaWindowClass", "Site", area=1920 * 1080)
        dialogo = janela("abrir", "#32770", "Abrir", dono=True)
        self.assertEqual(estado.para_cuidar([dialogo, firefox]), ["ff"])
        self.assertEqual(estado.observar([dialogo, firefox]), [])
        self.assertFalse(estado.edge)

    def test_titulo_curto_cabe_numa_linha(self):
        self.assertEqual(q.titulo_curto("  Abrir\narquivo  "), "Abrir arquivo")
        self.assertEqual(q.titulo_curto(""), "(sem título)")
        longo = "https://www.renpy.org/ " * 5
        curto = q.titulo_curto(longo)
        self.assertLessEqual(len(curto), 40)
        self.assertTrue(curto.endswith("…"))


if __name__ == "__main__":
    unittest.main()
