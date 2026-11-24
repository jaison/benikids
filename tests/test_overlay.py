import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))
MODULE_PATH = SOURCE_ROOT / "overlay.py"
SPEC = importlib.util.spec_from_file_location("overlay", MODULE_PATH)
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)


class FakeWindow:
    def __init__(self, reject_type=False):
        self.calls = []
        self.reject_type = reject_type

    def attributes(self, *args):
        self.calls.append(("attributes", *args))
        if self.reject_type and args == ("-type", "dock"):
            raise overlay.tk.TclError("unsupported window type")

    def lift(self):
        self.calls.append(("lift",))


class FakeX11Function:
    def __init__(self, result=None):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class FakeX11Library:
    def __init__(self, display=123):
        self.XOpenDisplay = FakeX11Function(display)
        self.XRaiseWindow = FakeX11Function()
        self.XFlush = FakeX11Function()
        self.XCloseDisplay = FakeX11Function()


class FakeTkWindow:
    _w = "."

    def __init__(self, frame_id, inner_id):
        self.tk = mock.Mock()
        self.tk.call.return_value = frame_id
        self.inner_id = inner_id

    def winfo_id(self):
        return self.inner_id


class OverlayWindowHintTests(unittest.TestCase):
    def test_tile_availability_closes_only_the_matching_owned_tile(self):
        status = {"profileAllowed": True, "blockedTileIds": ["paint"]}
        self.assertTrue(overlay.tile_is_blocked(status, "paint"))
        self.assertFalse(overlay.tile_is_blocked(status, "games"))
        self.assertTrue(
            overlay.tile_is_blocked(
                {"profileAllowed": False, "blockedTileIds": []},
                "games",
            )
        )
        self.assertFalse(overlay.tile_is_blocked({}, ""))

    def test_dock_and_topmost_hints_are_applied_before_lift(self):
        window = FakeWindow()

        overlay.configure_overlay_window(window)

        self.assertEqual(
            window.calls,
            [
                ("attributes", "-type", "dock"),
                ("attributes", "-topmost", True),
                ("lift",),
            ],
        )

    def test_topmost_hint_remains_when_dock_type_is_unsupported(self):
        window = FakeWindow(reject_type=True)

        overlay.configure_overlay_window(window)

        self.assertIn(("attributes", "-topmost", True), window.calls)
        self.assertEqual(window.calls[-1], ("lift",))

    def test_owned_x11_window_is_raised_without_external_commands(self):
        library = FakeX11Library()
        with mock.patch.dict(overlay.os.environ, {"DISPLAY": ":1"}):
            raiser = overlay.X11WindowRaiser(loader=lambda _: library)

        self.assertTrue(raiser.raise_window(0x1234))
        self.assertEqual(library.XOpenDisplay.calls, [(None,)])
        self.assertEqual(
            library.XRaiseWindow.calls[0][0],
            123,
        )
        self.assertEqual(
            library.XRaiseWindow.calls[0][1].value,
            0x1234,
        )
        self.assertEqual(library.XFlush.calls, [(123,)])

        raiser.close()
        self.assertEqual(library.XCloseDisplay.calls, [(123,)])
        self.assertFalse(raiser.display)

    def test_x11_raise_is_disabled_without_an_x_display(self):
        loader = mock.Mock()
        with mock.patch.dict(overlay.os.environ, {}, clear=True):
            raiser = overlay.X11WindowRaiser(loader=loader)

        self.assertFalse(raiser.raise_window(1))
        loader.assert_not_called()

    def test_outer_toplevel_id_is_used_instead_of_the_inner_tk_window(self):
        window = FakeTkWindow("0x1234", 0x1233)

        self.assertEqual(overlay.x11_toplevel_id(window), 0x1234)
        window.tk.call.assert_called_once_with("wm", "frame", ".")


class LauncherFocusTests(unittest.TestCase):
    def test_ewmh_launcher_window_is_raised_and_activated(self):
        listing = mock.Mock(
            returncode=0,
            stdout="0x03 host Cozy Kids Launcher\n",
        )
        raised = mock.Mock(returncode=0)
        activated = mock.Mock(returncode=0)
        released = mock.Mock(returncode=0)
        with mock.patch.object(
            overlay.subprocess,
            "run",
            side_effect=(listing, raised, activated, released),
        ) as run, mock.patch.object(overlay, "owned_process") as owned:
            overlay.focus_launcher()

        self.assertEqual(
            run.call_args_list,
            [
                mock.call(
                    ["wmctrl", "-l"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                ),
                mock.call(
                    ["wmctrl", "-i", "-r", "0x03", "-b", "add,above"],
                    check=False,
                ),
                mock.call(
                    ["wmctrl", "-i", "-a", "0x03"],
                    check=False,
                ),
                mock.call(
                    ["wmctrl", "-i", "-r", "0x03", "-b", "remove,above"],
                    check=False,
                ),
            ],
        )
        owned.assert_not_called()

    def test_menu_nativo_tambem_e_o_bloqueio(self):
        # a janela do beni-menu se chama "Beni", não "Cozy Kids Launcher"
        listing = mock.Mock(returncode=0, stdout="0x0b  0 host Beni\n")
        raised = mock.Mock(returncode=0)
        activated = mock.Mock(returncode=0)
        released = mock.Mock(returncode=0)
        with mock.patch.object(
            overlay.subprocess,
            "run",
            side_effect=(listing, raised, activated, released),
        ) as run, mock.patch.object(overlay, "owned_process"):
            overlay.focus_launcher()
        self.assertEqual(run.call_args_list[1].args[0][3], "0x0b")

    def test_pid_scoped_xdotool_is_the_x11_fallback(self):
        listing = mock.Mock(returncode=1, stdout="")
        activation = mock.Mock(returncode=0)
        with mock.patch.object(
            overlay.subprocess,
            "run",
            side_effect=(listing, activation),
        ) as run, mock.patch.object(
            overlay,
            "owned_process",
            return_value={"pid": 1234},
        ):
            overlay.focus_launcher()

        self.assertEqual(
            run.call_args_list[1],
            mock.call(
                [
                    "xdotool",
                    "search",
                    "--pid",
                    "1234",
                    "windowactivate",
                ],
                capture_output=True,
                timeout=3,
                check=False,
            ),
        )


class CantoPadraoTests(unittest.TestCase):
    def test_maximized_apps_start_on_the_right_to_keep_menus_free(self):
        self.assertEqual(overlay.canto_padrao("kapman"), "tr")      # maximizado
        self.assertEqual(overlay.canto_padrao("puzzles-quinze"), "tr")  # janela pequena em 26,26
        self.assertEqual(overlay.canto_padrao("nao-existe"), "tl")
        self.assertFalse(overlay.maximizar_no_inicio("puzzles-quinze"))


class CantoDoVoltarTests(unittest.TestCase):
    def test_back_button_corner_is_saved_per_site_apart_from_the_pill(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            arquivo = str(Path(pasta) / "overlay-corner.json")
            with mock.patch.object(overlay, "CORNER_FILE", arquivo):
                self.assertEqual(overlay.load_back_corner("khan"), "bl")  # padrão
                overlay.save_corner("khan", "tr")
                overlay.save_corner(overlay.back_corner_key("khan"), "br")
                self.assertEqual(overlay.load_corner("khan"), "tr")
                self.assertEqual(overlay.load_back_corner("khan"), "br")
                self.assertEqual(overlay.load_back_corner("outro"), "bl")
                with open(arquivo, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), {"khan": "tr", "khan#voltar": "br"})
                with open(arquivo, "w", encoding="utf-8") as handle:
                    json.dump({"khan#voltar": "meio"}, handle)
                self.assertEqual(overlay.load_back_corner("khan"), "bl")  # valor inválido

    def test_pill_sharing_a_corner_moves_away_from_the_back_button(self):
        self.assertEqual(overlay.stacked_offset("bl", 50), -60)  # embaixo: pílula acima
        self.assertEqual(overlay.stacked_offset("br", 50), -60)
        self.assertEqual(overlay.stacked_offset("tl", 50), 60)   # em cima: pílula abaixo
        self.assertEqual(overlay.stacked_offset("tr", 50), 60)


if __name__ == "__main__":
    unittest.main()
