import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPOSITORY_ROOT / "beni" / "bin" / "cozy-usuario-permitido"


class UsuarioPermitidoTests(unittest.TestCase):
    def run_helper(self, conf_text, user, **extra_env):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "launcher.conf"
            if conf_text is not None:
                conf.write_text(conf_text, encoding="utf-8")
            env = {**os.environ, "COZY_KIDS_TRAVA_CONF": str(conf), **extra_env}
            env.pop("COZY_KIDS_IGNORAR_TRAVA_USUARIO", None)
            env.update(extra_env)
            return subprocess.run([str(HELPER), user], env=env).returncode

    def test_sem_arquivo_libera_qualquer_usuario(self):
        self.assertEqual(self.run_helper(None, "jaison"), 0)

    def test_lista_vazia_libera_qualquer_usuario(self):
        self.assertEqual(self.run_helper("USUARIOS_PERMITIDOS=\n", "jaison"), 0)

    def test_so_usuario_listado_abre(self):
        conf = "# comentario\nUSUARIOS_PERMITIDOS=beni\n"
        self.assertEqual(self.run_helper(conf, "beni"), 0)
        self.assertEqual(self.run_helper(conf, "jaison"), 1)

    def test_aceita_varios_usuarios_com_aspas_e_virgula(self):
        conf = 'USUARIOS_PERMITIDOS="beni, ana"\n'
        self.assertEqual(self.run_helper(conf, "ana"), 0)
        self.assertEqual(self.run_helper(conf, "jaison"), 1)

    def test_nao_confunde_prefixo_de_nome(self):
        self.assertEqual(self.run_helper("USUARIOS_PERMITIDOS=beni\n", "ben"), 1)

    def test_variavel_de_ambiente_pula_a_trava(self):
        conf = "USUARIOS_PERMITIDOS=beni\n"
        self.assertEqual(self.run_helper(conf, "jaison", COZY_KIDS_IGNORAR_TRAVA_USUARIO="1"), 0)

    def test_launcher_e_iniciar_consultam_a_trava_antes_de_abrir(self):
        for name, before in (("cozy-kids-launcher", 'exec 9>"$LOCK_FILE"'),
                             ("cozy-iniciar", "cozy-carregando\" --pid")):
            source = (REPOSITORY_ROOT / "beni" / "bin" / name).read_text(encoding="utf-8")
            self.assertIn("cozy-usuario-permitido", source)
            self.assertLess(source.index("cozy-usuario-permitido"), source.index(before))


if __name__ == "__main__":
    unittest.main()
