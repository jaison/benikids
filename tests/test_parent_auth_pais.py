"""Token da área dos pais pelo menu nativo (parent_auth): uso único e validade."""

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import parent_auth as pa  # noqa: E402


class EsperaTokenTest(unittest.TestCase):
    def setUp(self):
        pa.limpar_pais()

    def test_espera_entrega_o_token_uma_vez_e_ele_vale_uma_vez(self):
        espera = pa.criar_espera()
        self.assertEqual(pa.aguardar_espera(espera, 0), ("aguardando", None))
        self.assertTrue(pa.liberar_espera(espera))
        estado, token = pa.aguardar_espera(espera, 0)
        self.assertEqual(estado, "pronto")
        self.assertEqual(pa.aguardar_espera(espera, 0), ("desconhecida", None))
        self.assertTrue(pa.trocar_token_pais(token))
        self.assertFalse(pa.trocar_token_pais(token))

    def test_token_vence(self):
        agora = 1000.0
        espera = pa.criar_espera(now=agora)
        pa.liberar_espera(espera, now=agora)
        _, token = pa.aguardar_espera(espera, 0)
        self.assertFalse(pa.trocar_token_pais(token, now=agora + pa.PAIS_TOKEN_TTL_SECONDS + 0.1))
        # e não volta a valer
        self.assertFalse(pa.trocar_token_pais(token, now=agora + 1))

    def test_espera_vencida_nao_libera(self):
        espera = pa.criar_espera(now=time.time() - pa.PAIS_ESPERA_TTL_SECONDS - 1)
        self.assertFalse(pa.liberar_espera(espera))
        self.assertEqual(pa.aguardar_espera(espera, 0), ("desconhecida", None))

    def test_valores_estranhos(self):
        for ruim in (None, "", 123, ["x"]):
            self.assertFalse(pa.liberar_espera(ruim))
            self.assertFalse(pa.trocar_token_pais(ruim))
            self.assertEqual(pa.aguardar_espera(ruim, 0), ("desconhecida", None))
        self.assertFalse(pa.liberar_espera("nao-existe"))

    def test_aguardar_acorda_quando_o_pin_chega(self):
        espera = pa.criar_espera()
        resultado = []
        t = threading.Thread(target=lambda: resultado.append(pa.aguardar_espera(espera, 5)))
        t.start()
        time.sleep(0.05)
        inicio = time.monotonic()
        pa.liberar_espera(espera)
        t.join(5)
        self.assertLess(time.monotonic() - inicio, 1)
        self.assertEqual(resultado[0][0], "pronto")

    def test_um_pedido_por_vez_em_cada_espera(self):
        # o id fica na linha de comando do navegador: outro programa esperando junto
        # não pode disputar o token com a página
        espera = pa.criar_espera()
        resultado = []
        t = threading.Thread(target=lambda: resultado.append(pa.aguardar_espera(espera, 5)))
        t.start()
        time.sleep(0.05)
        self.assertEqual(pa.aguardar_espera(espera, 0), ("ocupada", None))
        pa.liberar_espera(espera)
        t.join(5)
        self.assertEqual(resultado[0][0], "pronto")
        # o 2º não levou nada, e depois da entrega a espera não existe mais
        self.assertEqual(pa.aguardar_espera(espera, 0), ("desconhecida", None))

    def test_depois_do_tempo_a_espera_aceita_o_proximo_pedido(self):
        espera = pa.criar_espera()
        self.assertEqual(pa.aguardar_espera(espera, 0), ("aguardando", None))
        self.assertEqual(pa.aguardar_espera(espera, 0), ("aguardando", None))

    def test_cancelar_acorda_e_invalida(self):
        espera = pa.criar_espera()
        pa.liberar_espera(espera)
        self.assertTrue(pa.cancelar_espera(espera))
        self.assertEqual(pa.aguardar_espera(espera, 0), ("desconhecida", None))

    def test_numero_de_esperas_e_limitado(self):
        esperas = [pa.criar_espera() for _ in range(pa.PAIS_ESPERAS_MAX + 3)]
        self.assertEqual(len(pa._esperas), pa.PAIS_ESPERAS_MAX)
        self.assertFalse(pa.liberar_espera(esperas[0]))
        self.assertTrue(pa.liberar_espera(esperas[-1]))

    def test_ids_e_tokens_sao_longos_e_diferentes(self):
        a, b = pa.criar_espera(), pa.criar_espera()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 30)


if __name__ == "__main__":
    unittest.main()
