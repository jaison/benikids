#!/usr/bin/env python3
"""Exercise core launcher journeys in a real Chromium browser."""

import argparse
import getpass
import hashlib
import http.server
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from browser_driver import BrowserSession, find_browser, stop_process


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PIN = "2468"


class ReleaseFixtureHandler(http.server.BaseHTTPRequestHandler):
    latest_version = "0.0.0"
    mode = "ok"

    def do_GET(self):
        if self.mode != "ok":
            self.send_error(503, "synthetic update service failure")
            return
        if self.path == "/releases/latest":
            payload = json.dumps({
                "tag_name": f"v{self.latest_version}",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"name": f"cozy-kids-launcher-{self.latest_version}.tar.gz"},
                    {"name": "SHA256SUMS"},
                ],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path == "/VERSION":
            payload = f"{self.latest_version}\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        else:
            self.send_error(404)
            return
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format_string, *args):
        pass


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for_server(url, process, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Launcher server exited before becoming ready ({process.returncode})"
            )
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.load(response)
                if response.status == 200 and isinstance(payload, dict):
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise TimeoutError("Launcher server did not become ready")


def write_demo_config(config_path, browser_name, setup_completed=False, base=None):
    if base is None:
        with config_path.open(encoding="utf-8") as handle:
            config = json.load(handle)
    else:
        config = json.loads(json.dumps(base))
    config.update({
        "language": "en",
        "setupCompleted": setup_completed,
        "telemetryEnabled": False,
        "usageTelemetryEnabled": False,
        "parentLabel": "Parent",
        "exitLabel": "Exit kids mode",
        "pinHash": "",
        "autoScanDone": True,
        "browser": browser_name,
    })
    config["profiles"][0].update({
        "title": "E2E Home",
        "theme": "rosa",
        "themeMotionEnabled": False,
        "themeTimeOfDayEnabled": False,
        "layoutMode": "gross",
        "currentPage": 0,
        # Beni Launcher: estes cenários testam a grade completa do original
        "choiceScreenEnabled": False,
        "timerMinutes": 0,
        "timerWarningMinutes": 5,
        "tiles": [
            {
                "id": "paint",
                "label": "Paint",
                "emoji": "🎨",
                "cmd": ["true"],
                "visible": True,
            },
            {
                "id": "music",
                "label": "Music",
                "emoji": "🎵",
                "cmd": ["special:filme-musik"],
                "visible": True,
            },
        ],
    })
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return config


def assert_js(browser, expression, message):
    value = browser.evaluate(expression)
    if value is not True:
        raise AssertionError(f"{message} (expression returned {value!r})")


def log_scenario(name):
    print(f"  ✓ {name}", flush=True)


def enter_parent_settings(browser):
    browser.click("#parentBtn")
    browser.wait_for(
        "!document.getElementById('pin').classList.contains('hidden')",
        message="PIN dialog did not open",
    )
    browser.set_value("#pinInput", PIN)
    browser.click("#pin .save")
    browser.wait_for(
        "!document.getElementById('admin').classList.contains('hidden')",
        message="Correct PIN did not open Parent settings",
    )


def run_native_menu_parent_handoff(browser, artifacts):
    """Área dos pais pelo menu nativo: a página fica escondida esperando o PIN
    digitado no menu e entra liberada, sem pedir o PIN de novo."""
    espera = browser.evaluate(
        "fetch('/api/pais/preparar',{method:'POST'}).then(r=>r.json()).then(d=>d.espera)",
        await_promise=True,
    )
    assert espera, "Native menu handoff did not create a wait id"
    browser.evaluate(
        "location.replace('/cliente.html?ir=%2Findex.html%3Fpais%3D1#espera=' + "
        + json.dumps(espera) + ")"
    )
    browser.wait_for(
        "location.pathname==='/index.html' && document.querySelector('.cliente-capa')!==null "
        "&& typeof cfg!=='undefined' && cfg!==null",
        message="Hidden parent page did not wait behind the brand cover",
    )
    browser.evaluate("new Promise(resolve=>setTimeout(resolve,1500))", await_promise=True)
    assert_js(
        browser,
        "document.getElementById('admin').classList.contains('hidden') && "
        "document.getElementById('pin').classList.contains('hidden') && "
        "location.hash==='' && !location.search.includes('espera')",
        "Hidden parent page opened something before the PIN",
    )
    browser.screenshot(artifacts / "native-parent-waiting.png")
    wrong = browser.evaluate(
        "fetch('/api/pais/liberar',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({pin:'0000',espera:" + json.dumps(espera) + "})}).then(r=>r.status)",
        await_promise=True,
    )
    assert wrong == 403, f"Wrong PIN was not rejected: {wrong}"
    right = browser.evaluate(
        "fetch('/api/pais/liberar',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({pin:" + json.dumps(PIN) + ",espera:" + json.dumps(espera) + "})})"
        ".then(r=>r.json())",
        await_promise=True,
    )
    assert right == {"valid": True, "entregue": True}, right
    browser.wait_for(
        "!document.getElementById('admin').classList.contains('hidden') && "
        "document.getElementById('pin').classList.contains('hidden') && "
        "document.querySelector('.cliente-capa')===null",
        message="Parent settings did not open after the native PIN",
    )
    browser.screenshot(artifacts / "native-parent-open.png")
    # volta à aba comum do menu web para os próximos cenários
    browser.evaluate("sessionStorage.clear(); location.replace('/index.html')")
    browser.wait_for(
        "location.pathname==='/index.html' && typeof cfg!=='undefined' && cfg!==null && "
        "!document.documentElement.classList.contains('beni-cliente') && "
        "!document.querySelector('.cornerbar').classList.contains('hidden')",
        message="Launcher did not come back after the native parent handoff",
    )
    log_scenario("native menu PIN unlocks the hidden parent page once")


def run_benikids_setup(browser, artifacts):
    """Benikids: a fresh install opens configurar.html (children, parent PIN, preferences)."""
    browser.wait_for(
        "location.pathname==='/configurar.html' && "
        "document.querySelectorAll('#criancas .crianca').length===1 && "
        "!document.querySelector('section.passo[data-passo=\"1\"]').hidden",
        message="A fresh installation did not open the Benikids setup page",
    )
    assert_js(
        browser,
        "document.getElementById('telemetria').checked===true && "
        "document.getElementById('telemetriaUso').checked===false && "
        "document.getElementById('inicio').checked===true",
        "Setup consent defaults changed (device on, usage off, start on login on)",
    )
    for width, height in ((800, 600), (390, 844)):
        browser.set_device_metrics(width, height)
        assert_js(
            browser,
            "document.documentElement.scrollWidth<=window.innerWidth && "
            "[...document.querySelectorAll('.icone')].every(b=>b.getBoundingClientRect().right<=window.innerWidth)",
            f"The setup page overflows horizontally at {width}x{height}",
        )
        browser.screenshot(artifacts / f"setup-{width}x{height}.png")
    browser.set_device_metrics(1366, 768)
    assert_js(
        browser,
        "document.getElementById('avancar').getBoundingClientRect().bottom<=window.innerHeight",
        "The Continue button is below the fold at 1366x768",
    )
    # step 1: validation stays on the step and points at the field
    browser.click("#avancar")
    browser.wait_for(
        "document.getElementById('erro').textContent.length>0 && "
        "document.activeElement.classList.contains('nome')",
        message="The setup page accepted a child without a name",
    )
    browser.click("#mais")
    browser.wait_for("document.querySelectorAll('#criancas .crianca').length===2")
    browser.click("#criancas .crianca:last-child .remover")
    browser.wait_for("document.querySelectorAll('#criancas .crianca').length===1")
    browser.set_value("#criancas .nome", "Kiddo")
    browser.set_value("#criancas .mes", "03")
    browser.evaluate(
        "(() => { const s=document.querySelector('#criancas .ano');"
        " s.value=s.options[3].value; s.dispatchEvent(new Event('change',{bubbles:true})); })()"
    )
    browser.click("#avancar")
    browser.wait_for(
        "document.getElementById('erro').textContent.includes('Menino ou Menina')",
        message="The setup page accepted a child without boy/girl",
    )
    browser.click("#criancas .icone.menina")
    browser.click("#avancar")
    browser.wait_for(
        "!document.querySelector('section.passo[data-passo=\"2\"]').hidden && "
        "document.activeElement.id==='pin'",
        message="Step 1 did not advance to the parent PIN",
    )
    # step 2: weak and mismatched PINs are refused
    browser.set_value("#pin", "1111")
    browser.set_value("#pin2", "1111")
    browser.click("#avancar")
    browser.wait_for("document.getElementById('erro').textContent.length>0",
                     message="The setup page accepted a repeated-digit PIN")
    browser.set_value("#pin", PIN)
    browser.set_value("#pin2", "1357")
    assert_js(browser, "document.getElementById('confere').classList.contains('nao')",
              "The PIN match hint did not flag different PINs")
    browser.click("#avancar")
    browser.wait_for(
        "document.getElementById('erro').textContent.length>0 && "
        "!document.querySelector('section.passo[data-passo=\"2\"]').hidden",
        message="The setup page accepted two different PINs",
    )
    browser.set_value("#pin2", PIN)
    assert_js(browser, "document.getElementById('confere').classList.contains('ok')",
              "The PIN match hint did not confirm equal PINs")
    browser.click("#avancar")
    browser.wait_for(
        "!document.querySelector('section.passo[data-passo=\"3\"]').hidden && "
        "!document.getElementById('comecar').hidden",
        message="Step 2 did not advance to preferences",
    )
    browser.screenshot(artifacts / "setup-preferences.png")
    # back keeps what was typed
    browser.click("#voltarPasso")
    browser.wait_for("document.getElementById('pin').value===" + json.dumps(PIN))
    browser.click("#avancar")
    browser.wait_for("!document.querySelector('section.passo[data-passo=\"3\"]').hidden")
    browser.click("#telemetria")
    browser.click("#inicio")
    browser.click("#comecar")
    browser.wait_for(
        "document.getElementById('pronto').hidden===false && "
        "document.getElementById('prontoTitulo').textContent.includes('Kiddo')",
        message="Finishing the Benikids setup did not show the ready screen",
    )
    browser.screenshot(artifacts / "setup-ready.png")
    saved = browser.evaluate(
        "fetch('/api/config',{cache:'no-store'}).then(response=>response.json())",
        await_promise=True,
    )
    # /api/config flattens the active profile into the top level
    if not (
        saved.get("setupCompleted") is True
        and saved.get("pinConfigured") is True
        and saved.get("telemetryEnabled") is False
        and saved.get("usageTelemetryEnabled") is False
        and saved.get("name") == "Kiddo"
        and saved.get("avatar") == "👧"
        and saved.get("gender") == "menina"
        and str(saved.get("birthMonth", "")).endswith("-03")
        and len(saved.get("profiles", [])) == 1
    ):
        raise AssertionError(f"Benikids setup was not persisted: {saved!r}")
    browser.click("#irMenu")
    browser.wait_for(
        "location.pathname==='/index.html'",
        message="The ready screen did not return to the launcher",
    )
    browser.set_device_metrics(1440, 900)
    log_scenario("Benikids setup walks children, parent PIN, and preferences with inline validation")


def run_scenarios(browser, release_fixture, installed_version, artifacts, restore_demo):
    run_benikids_setup(browser, artifacts)
    # the remaining journeys come from the upstream launcher: they start from the
    # demo profile with setup done and no PIN yet
    restore_demo()
    browser.evaluate("location.replace('/index.html')")
    browser.wait_for(
        "location.pathname==='/index.html' && "
        "typeof cfg !== 'undefined' && cfg !== null && "
        "bootstrapPromise===null && cfg.pinConfigured===false && "
        "document.querySelectorAll('#grid .tile:not(.placeholder)').length === 2 && "
        "document.getElementById('firstRunOverlay').classList.contains('hidden') && "
        "document.getElementById('title').textContent==='E2E Home'",
        message="Home screen did not finish rendering",
    )
    assert_js(
        browser,
        "document.getElementById('title').textContent === 'E2E Home' && "
        "document.getElementById('kids').classList.contains('hidden') === false && "
        "Array.from(document.querySelectorAll('#grid .tile:not(.placeholder)'))"
        ".map(tile => tile.textContent.trim()).join('|').includes('Paint')",
        "Home title or tiles are incorrect",
    )
    browser.click('#grid .tile[data-tile-id="music"]')
    browser.wait_for(
        "location.pathname==='/media.html' && "
        "document.querySelectorAll('#mediaGrid .media-card').length===2 && "
        "document.getElementById('mediaTitle').textContent==="
        "mediaTile(mediaConfig,mediaTileId).label",
        message="The cover media library did not finish rendering",
    )
    browser.wait_for(
        "document.querySelector('.media-card img')!==null && "
        "document.querySelector('.media-card img').complete && "
        "document.querySelector('.media-card img').naturalWidth>0",
        message="The local media cover did not finish loading",
    )
    assert_js(
        browser,
        "document.documentElement.lang==='en' && "
        "document.querySelectorAll('.media-cover-fallback > .ui-icon').length===1 && "
        "document.body.textContent.includes('E2E Film') && "
        "document.body.textContent.includes('Bedtime Song') && "
        "!document.body.textContent.includes('/Videos/')",
        "The media library did not render safe localized covers and fallbacks",
    )
    browser.evaluate(
        "Array.from(document.querySelectorAll('.media-card-shell')).find(shell=>"
        "shell.querySelector('.media-card-title').textContent==='Bedtime Song')"
        ".querySelector('.media-favorite').click()"
    )
    browser.wait_for(
        "mediaFavoriteIds.size===1 && "
        "Array.from(document.querySelectorAll('.media-favorite')).some(button=>"
        "button.getAttribute('aria-pressed')==='true')",
        message="The media favorite did not persist and re-render",
    )
    favorite_state = browser.evaluate(
        "fetch('/api/media',{cache:'no-store'}).then(response=>response.json())",
        await_promise=True,
    )
    if len(favorite_state.get("favoriteIds", [])) != 1:
        raise AssertionError(f"The favorite API did not retain one opaque ID: {favorite_state!r}")
    browser.click('[data-media-filter="favorites"]')
    assert_js(
        browser,
        "document.querySelectorAll('.media-card').length===1 && "
        "document.querySelector('.media-card-title').textContent==='Bedtime Song'",
        "The Favorites view did not show only the saved item",
    )
    browser.click('[data-media-filter="recents"]')
    assert_js(
        browser,
        "document.querySelectorAll('.media-card').length===1 && "
        "document.querySelector('.media-card-title').textContent==='E2E Film'",
        "The Recently played view did not preserve its profile-specific order",
    )
    browser.click('[data-media-filter="all"]')
    browser.evaluate("document.querySelector('.media-card').focus()")
    browser.key_press("ArrowRight")
    assert_js(
        browser,
        "document.activeElement===document.querySelectorAll('.media-card')[1]",
        "Arrow-key navigation did not move between media cards",
    )
    browser.screenshot(artifacts / "media-library.png")
    browser.click("#mediaBack")
    browser.wait_for(
        "location.pathname==='/index.html' && typeof cfg!=='undefined' && cfg!==null && "
        "bootstrapPromise===null && document.querySelectorAll('#grid .tile:not(.placeholder)').length===2 && "
        "document.getElementById('kids').classList.contains('screen-returning') && "
        "document.querySelector('#grid .tile[data-tile-id=\"music\"]')"
        ".classList.contains('return-highlight')",
        message="The media library did not return to the launcher",
    )
    browser.evaluate("new Promise(resolve=>setTimeout(resolve,250))", await_promise=True)
    browser.screenshot(artifacts / "launcher-return.png")
    browser.evaluate(
        "window.__transitionOriginalFetch=window.fetch.bind(window);"
        "window.fetch=(input,options)=>String(input)==='/launch/paint'"
        " ? new Promise(resolve=>{window.__completeTransitionLaunch=()=>"
        "resolve(new Response(null,{status:204}));})"
        " : window.__transitionOriginalFetch(input,options)"
    )
    browser.click('#grid .tile[data-tile-id="paint"]')
    browser.wait_for(
        "document.getElementById('startOverlay').classList.contains('launch-starting') && "
        "document.getElementById('startText').textContent.includes('Paint')",
        message="A pending local launch did not expose its visual status",
    )
    browser.evaluate("window.__completeTransitionLaunch()")
    browser.wait_for(
        "document.getElementById('startOverlay').classList.contains('launch-success') && "
        "document.getElementById('startText').textContent.includes('Paint') && "
        "document.getElementById('startText').textContent.includes('ready')",
        message="A successful local launch did not expose its visual status",
    )
    browser.evaluate("new Promise(resolve=>setTimeout(resolve,250))", await_promise=True)
    browser.screenshot(artifacts / "launch-success.png")
    browser.wait_for(
        "document.getElementById('startOverlay').classList.contains('hidden')",
        timeout=3,
        message="Successful launch feedback did not close automatically",
    )
    browser.evaluate(
        "window.fetch=window.__transitionOriginalFetch;"
        "delete window.__transitionOriginalFetch;"
        "delete window.__completeTransitionLaunch"
    )
    log_scenario("home and the local cover media library render safely")

    icon_metrics = browser.evaluate(
        "({tiles:document.querySelectorAll('#grid .tile:not(.placeholder) .local-tile-icon').length,"
        "paths:document.querySelectorAll('#grid .tile:not(.placeholder) .local-tile-icon path').length,"
        "clock:document.querySelector('#clockBadge .ui-icon')!==null})"
    )
    if icon_metrics != {"tiles": 2, "paths": 7, "clock": True}:
        raise AssertionError(
            "Built-in tiles or launcher chrome did not use the local icon registry "
            f"({icon_metrics!r})"
        )
    browser.evaluate(
        "cfg.tiles.push({id:'custom-emoji',label:'Unicorn',emoji:'🦄',"
        "cmd:['true'],visible:true}); renderAll()"
    )
    assert_js(
        browser,
        "Array.from(document.querySelectorAll('#grid .tile')).some(tile => "
        "tile.textContent.includes('Unicorn') && "
        "tile.querySelector('.emoji').tagName==='SPAN' && "
        "tile.querySelector('.emoji').textContent==='🦄' && "
        "tile.querySelector('.local-tile-icon')===null)",
        "A custom emoji tile was replaced by the local icon registry",
    )
    browser.evaluate(
        "cfg.tiles=cfg.tiles.filter(tile=>tile.id!=='custom-emoji'); renderAll()"
    )
    log_scenario("local icons render built-ins while custom emoji remain text")

    browser.evaluate(
        "window.__cozyOriginalFetch=window.fetch.bind(window);"
        "window.__failConfigOnce=true;"
        "window.fetch=(input,options)=>{"
        " if(String(input)==='/api/config'&&window.__failConfigOnce){"
        "  window.__failConfigOnce=false;"
        "  return Promise.resolve(new Response('{}',{status:503,"
        "headers:{'Content-Type':'application/json'}}));"
        " }"
        " return window.__cozyOriginalFetch(input,options);"
        "};"
        "bootstrapLauncher()"
    )
    browser.wait_for(
        "document.getElementById('startupState') && "
        "document.getElementById('startupState').classList.contains('ui-state-error')",
        message="Failed config load did not render a recoverable startup error",
    )
    assert_js(
        browser,
        "cfg===null && document.getElementById('startupState').getAttribute('role')==='alert' && "
        "document.querySelector('.cornerbar').classList.contains('hidden') && "
        "document.querySelector('#startupState .ui-state-retry')!==null",
        "Startup error did not preserve a safe, actionable state",
    )
    browser.screenshot(artifacts / "startup-error.png")
    browser.click("#startupState .ui-state-retry")
    browser.wait_for(
        "cfg!==null && document.getElementById('startupState')===null && "
        "document.querySelectorAll('#grid .tile:not(.placeholder)').length===2 && "
        "!document.querySelector('.cornerbar').classList.contains('hidden')",
        message="Startup retry did not restore the launcher",
    )
    browser.evaluate(
        "window.fetch=window.__cozyOriginalFetch;"
        "delete window.__cozyOriginalFetch; delete window.__failConfigOnce"
    )
    log_scenario("startup failure renders an error and recovers in place")

    browser.click("#parentBtn")
    browser.wait_for("!document.getElementById('admin').classList.contains('hidden')")
    browser.click("[data-admin-section='system']")
    browser.set_value("#cfgPin", PIN)
    browser.set_value("#cfgPinConfirm", PIN)
    browser.click("#setPinBtn")
    browser.wait_for("cfg.pinConfigured === true")
    browser.click("#backBtn")

    run_native_menu_parent_handoff(browser, artifacts)

    browser.click("#parentBtn")
    browser.wait_for("!document.getElementById('pin').classList.contains('hidden')")
    browser.set_value("#pinInput", "0000")
    browser.click("#pin .save")
    browser.wait_for("document.getElementById('pinErr').textContent.length > 0")
    assert_js(
        browser,
        "document.getElementById('admin').classList.contains('hidden')",
        "Wrong PIN unexpectedly opened Parent settings",
    )
    browser.set_value("#pinInput", PIN)
    browser.click("#pin .save")
    browser.wait_for(
        "!document.getElementById('admin').classList.contains('hidden') && "
        "document.querySelectorAll('[data-admin-section]').length===6 && "
        "document.querySelectorAll('#adminNav .ui-icon').length===6 && "
        "document.querySelector('[data-admin-section=\"overview\"]')"
        ".getAttribute('aria-current')==='page'"
    )
    log_scenario("PIN setup rejects a wrong PIN and accepts the correct PIN")

    browser.click("[data-admin-section='appearance']")
    saved_theme = browser.evaluate("cfg.theme")
    saved_layout = browser.evaluate("cfg.layoutMode")
    assert_js(
        browser,
        "document.getElementById('feedbackOptionsTitle').textContent===uiText.feedbackOptions && "
        "document.getElementById('soundFeedbackLabel').textContent===uiText.soundFeedback && "
        "document.getElementById('speechFeedbackLabel').textContent===uiText.speechFeedback && "
        "document.getElementById('speechFeedbackStatus').getAttribute('role')==='status' && "
        "document.getElementById('speechFeedbackStatus').textContent==="
        "(features.speechFeedbackAvailable?uiText.speechAvailable:uiText.speechUnavailable) && "
        "document.getElementById('accessibilityOptionsTitle').textContent===uiText.accessibilityOptions && "
        "document.getElementById('accessibilityKeyboardFocusLabel').textContent==="
        "uiText.accessibilityKeyboardFocus && "
        "document.getElementById('cfgSoundFeedbackEnabled').checked===false && "
        "document.getElementById('cfgSpeechFeedbackEnabled').checked===false && "
        "['LargeText','HighContrast','ReducedMotion','KeyboardFocus'].every(name=>"
        "document.getElementById('cfgAccessibility'+name).checked===false)",
        "Optional local feedback and accessibility presets did not render their default-off state",
    )
    browser.click("#openThemeBtn")
    browser.wait_for("!document.getElementById('themeOverlay').classList.contains('hidden')")
    chosen = browser.evaluate(
        "(() => { const index=ALL_THEMES.findIndex(theme => theme.id==='weltraum');"
        " const tiles=document.querySelectorAll('#themeChooser .theme-thumb');"
        " if(index < 0 || !tiles[index]) return false; tiles[index].click(); return true; })()"
    )
    if chosen is not True:
        raise AssertionError("Space theme could not be selected")
    assert_js(
        browser,
        "document.getElementById('appearancePreview').classList.contains('theme-weltraum') && "
        "document.getElementById('appearancePreview').style.background.includes('space.jpg') && "
        "!document.getElementById('cfgThemeMotionEnabled').disabled && "
        "!document.getElementById('cfgThemeTimeOfDayEnabled').disabled && "
        "document.getElementById('cfgThemeMotionEnabled').checked===false && "
        "document.getElementById('cfgThemeTimeOfDayEnabled').checked===false && "
        "!document.getElementById('appearancePreview').classList.contains('theme-world-motion') && "
        "document.getElementById('appearancePreview').dataset.themePeriod===undefined && "
        f"cfg.theme==={json.dumps(saved_theme)} && "
        f"document.body.classList.contains('theme-{saved_theme}')",
        "Theme preview changed the saved or active launcher theme",
    )
    assert_js(
        browser,
        "themePeriodAt(new Date(2026,0,1,6))==='morning' && "
        "themePeriodAt(new Date(2026,0,1,12))==='day' && "
        "themePeriodAt(new Date(2026,0,1,18))==='evening' && "
        "themePeriodAt(new Date(2026,0,1,23))==='night'",
        "World theme periods do not follow the documented local-time boundaries",
    )
    browser.click("#cfgThemeMotionEnabled")
    browser.click("#cfgThemeTimeOfDayEnabled")
    browser.click("#cfgSoundFeedbackEnabled")
    browser.click("#cfgSpeechFeedbackEnabled")
    browser.click("#cfgCelebrationEnabled")
    celebration_result = browser.evaluate(
        "playCelebrationMoment({...cfg,celebrationEnabled:true,accessibilityReducedMotion:false})"
        " && !document.getElementById('celebrationLayer').hidden"
        " && document.querySelectorAll('#celebrationLayer .celebration-star').length===8"
    )
    if celebration_result is not True:
        raise AssertionError("The fixed opt-in celebration moment did not start")
    browser.screenshot(artifacts / "celebration-moment.png")
    browser.wait_for(
        "document.getElementById('celebrationLayer').hidden && "
        "document.getElementById('celebrationLayer').childElementCount===0",
        message="The celebration moment did not clean itself up",
    )
    assert_js(
        browser,
        "document.getElementById('appearancePreview').classList.contains('theme-world-motion') && "
        "document.getElementById('appearancePreview').dataset.themePeriod===themePeriodAt() && "
        "Array.from(document.getElementById('appearancePreview').classList)"
        ".some(name=>name.startsWith('theme-time-')) && "
        f"cfg.theme==={json.dumps(saved_theme)} && cfg.themeMotionEnabled!==true",
        "Optional world effects did not stay inside the unsaved preview",
    )
    browser.screenshot(artifacts / "world-theme-effects.png")
    for selector in (
        "#cfgAccessibilityLargeText",
        "#cfgAccessibilityHighContrast",
        "#cfgAccessibilityReducedMotion",
        "#cfgAccessibilityKeyboardFocus",
    ):
        browser.click(selector)
    assert_js(
        browser,
        "['access-large-text','access-high-contrast','access-reduced-motion',"
        "'access-keyboard-focus'].every(name=>"
        "document.getElementById('appearancePreview').classList.contains(name)) && "
        "getComputedStyle(document.getElementById('appearancePreview'))"
        ".getPropertyValue('--text').trim()==='#111' && "
        "getComputedStyle(document.querySelector('#appearancePreview .preview-tile'))"
        ".outlineWidth==='6px' && "
        "playCelebrationMoment({...cfg,celebrationEnabled:true,accessibilityReducedMotion:true})===false && "
        "document.getElementById('celebrationLayer').hidden && "
        "!document.documentElement.classList.contains('access-large-text')",
        "Accessibility presets did not stay inside the unsaved preview",
    )
    browser.screenshot(artifacts / "accessibility-presets.png")
    browser.set_value("#cfgLayoutMode", "klein")
    assert_js(
        browser,
        "document.getElementById('appearancePreviewGrid').classList.contains('klein') && "
        "document.querySelectorAll('#appearancePreviewGrid .preview-tile').length===2 && "
        f"cfg.layoutMode==={json.dumps(saved_layout)}",
        "Layout preview changed the saved launcher layout",
    )
    browser.click("[data-admin-section='children']")
    browser.set_value("#cfgTitle", "Polished E2E Home")
    browser.set_value("#cfgParentLabel", "Family controls")
    assert_js(
        browser,
        "document.getElementById('appearancePreviewTitle').textContent==='Polished E2E Home'",
        "Title input did not update the isolated launcher preview",
    )
    browser.click("#saveBtn")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "document.body.classList.contains('theme-weltraum')",
        message="Saved settings were not applied to the home screen",
    )
    assert_js(
        browser,
        "document.getElementById('title').textContent === 'Polished E2E Home' && "
        "document.getElementById('grid').classList.contains('klein') && "
        "document.getElementById('parentBtn').textContent === 'Family controls'",
        "Title, layout, or parent label did not update",
    )
    saved_config = browser.evaluate(
        "fetch('/api/config',{cache:'no-store'}).then(response => response.json())",
        await_promise=True,
    )
    expected = {
        "title": "Polished E2E Home",
        "layoutMode": "klein",
        "theme": "weltraum",
        "themeMotionEnabled": True,
        "themeTimeOfDayEnabled": True,
        "soundFeedbackEnabled": True,
        "speechFeedbackEnabled": True,
        "celebrationEnabled": True,
        "accessibilityLargeText": True,
        "accessibilityHighContrast": True,
        "accessibilityReducedMotion": True,
        "accessibilityKeyboardFocus": True,
        "parentLabel": "Family controls",
    }
    if any(saved_config.get(key) != value for key, value in expected.items()):
        raise AssertionError(f"Saved config does not match the UI: {saved_config!r}")
    # the reduced-motion preset shortens the font-size transition to .01ms, but the
    # computed size keeps the old value until the next frames run
    browser.wait_for(
        "['access-large-text','access-high-contrast','access-reduced-motion',"
        "'access-keyboard-focus'].every(name=>document.documentElement.classList.contains(name)) && "
        "getComputedStyle(document.documentElement).fontSize==='18px' && "
        "getComputedStyle(document.body).getPropertyValue('--text').trim()==='#111' && "
        "getComputedStyle(document.querySelector('#grid .tile')).outlineWidth==='6px'",
        message="Saved accessibility presets were not applied to the launcher",
    )
    feedback_result = browser.evaluate(
        "(()=>{window.__toneStarts=0;cozyFeedbackAudioContext=null;"
        "window.AudioContext=class{constructor(){this.state='running';this.currentTime=0;"
        "this.destination={};}resume(){return Promise.resolve();}createOscillator(){return "
        "{type:'',frequency:{setValueAtTime(){},exponentialRampToValueAtTime(){}},"
        "connect(){},disconnect(){},start(){window.__toneStarts+=1;},"
        "stop(){if(this.onended)this.onended();}};}createGain(){return "
        "{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},"
        "connect(){},disconnect(){}};}};return playFeedbackSound('success')&&"
        "window.__toneStarts===1;})()"
    )
    if feedback_result is not True:
        raise AssertionError("The dependency-free local feedback tone did not start")
    browser.evaluate(
        "window.__feedbackOriginalFetch=window.fetch.bind(window);"
        "window.__speechBody=null;features.speechFeedbackAvailable=true;"
        "window.fetch=(input,options)=>String(input)==='/api/feedback/speak'"
        " ? (window.__speechBody=JSON.parse(options.body),"
        "Promise.resolve(new Response('{\"status\":\"spoken\"}',{status:200,"
        "headers:{'Content-Type':'application/json'}})))"
        " : window.__feedbackOriginalFetch(input,options);"
        "document.querySelector('#grid .tile[data-tile-id=\"music\"]').focus()"
    )
    browser.wait_for(
        "window.__speechBody!==null",
        message="Focused-tile speech feedback did not call its local endpoint",
    )
    assert_js(
        browser,
        "JSON.stringify(window.__speechBody)===JSON.stringify({tileId:'music'})",
        "Speech feedback sent more than the opaque tile identifier",
    )
    browser.evaluate(
        "(async()=>{cancelTileSpeech();window.fetch=window.__feedbackOriginalFetch;"
        "delete window.__feedbackOriginalFetch;delete window.__speechBody;"
        "features.speechFeedbackAvailable=false;cfg.soundFeedbackEnabled=false;"
        "cfg.speechFeedbackEnabled=false;cfg.accessibilityLargeText=false;"
        "cfg.celebrationEnabled=false;"
        "cfg.accessibilityHighContrast=false;cfg.accessibilityReducedMotion=false;"
        "cfg.accessibilityKeyboardFocus=false;await persistConfig();renderAll();})()",
        await_promise=True,
    )
    log_scenario("settings, themes, local feedback, celebrations, and accessibility presets persist safely")

    enter_parent_settings(browser)
    browser.wait_for(
        "activityState==='empty' && "
        "document.getElementById('cfgActivityTracking').checked===false && "
        "document.getElementById('activityExportBtn').disabled && "
        "document.getElementById('activityClearBtn').disabled",
        message="The disabled empty activity dashboard did not finish loading",
    )
    browser.click("#cfgActivityTracking")
    browser.click("#saveBtn")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "cfg.activityTrackingEnabled===true",
        message="Opting in to local activity tracking was not persisted",
    )
    prepared_activity = browser.evaluate(
        "(async()=>{cfg.tiles[0].cmd=['special:browser:'+location.origin+"
        "'/no-media.html'];cfg.tiles[0].browserAllowedOrigins="
        "['https://media.example/videos'];await persistConfig();"
        "return cfg.tiles[0].id;})()",
        await_promise=True,
    )
    if prepared_activity != "paint":
        raise AssertionError("The activity test tile could not be prepared")
    enter_parent_settings(browser)
    browser.click("[data-admin-section='apps']")
    browser.wait_for(
        "document.querySelector('#forms .tileform.has-browser .browser-allowlist textarea')"
        ".value==='https://media.example' && "
        "document.querySelector('#forms .tileform.has-browser .browser-boundary-hint')"
        ".textContent===uiText.browserBoundaryEmbedded",
        message="The embedded browser allowlist did not render its exact origin",
    )
    browser.screenshot(artifacts / "browser-allowlist.png")
    browser.set_value(
        "#forms .tileform.has-browser .browser-primary select",
        "external",
    )
    assert_js(
        browser,
        "document.querySelector('#forms .tileform.has-browser .browser-allowlist').hidden && "
        "document.querySelector('#forms .tileform.has-browser .browser-boundary-hint')"
        ".textContent===uiText.browserBoundaryExternal",
        "External browser mode did not explain that it is outside the allowlist boundary",
    )
    browser.set_value(
        "#forms .tileform.has-browser .browser-primary select",
        "embedded",
    )
    browser.click("#backBtn")
    embedded_finished = browser.evaluate(
        "(async()=>{const response=await fetch('/launch/paint',{method:'POST'});"
        "const target=new URL(response.url);"
        "const token=target.searchParams.get('activity')||'';"
        "const policy=response.headers.get('Content-Security-Policy')||'';"
        "if(!response.redirected||target.pathname!=='/browser.html'||token.length<16)"
        "return false;"
        "const finish=await fetch('/api/activity/finish',{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});"
        "const forged=await fetch('/browser.html?url=https%3A%2F%2Fevil.example"
        "&tile=paint&activity=');"
        "return finish.status===204&&forged.status===404&&"
        "policy.includes('frame-src '+location.origin+' https://media.example;')&&"
        "!policy.includes('*');})()",
        await_promise=True,
    )
    if embedded_finished is not True:
        raise AssertionError(
            "The tracked embedded app did not issue and finish an opaque token"
        )
    recorded = browser.evaluate(
        "(async()=>{for(let attempt=0;attempt<30;attempt++){"
        "const data=await fetch('/api/activity',{cache:'no-store'}).then(r=>r.json());"
        "if(data.recordCount===1)return true;"
        "await new Promise(resolve=>setTimeout(resolve,100));}return false;})()",
        await_promise=True,
    )
    if recorded is not True:
        raise AssertionError("Completed embedded usage was not recorded")
    restored_activity_tile = browser.evaluate(
        "(async()=>{cfg.tiles[0].cmd=['tuxpaint'];delete cfg.tiles[0].browserAllowedOrigins;"
        "await persistConfig();return true;})()",
        await_promise=True,
    )
    if restored_activity_tile is not True:
        raise AssertionError("The activity test tile was not restored")
    enter_parent_settings(browser)
    browser.wait_for(
        "activityState==='ready' && activityData.recordCount===1 && "
        "document.querySelectorAll('#activityRecentList .activity-item').length===1 && "
        "document.getElementById('activityExportBtn').disabled===false && "
        "document.getElementById('activityClearBtn').disabled===false",
        message="Recorded usage did not render in the Parent dashboard",
    )
    browser.screenshot(artifacts / "activity-dashboard.png")
    activity_export = browser.evaluate(
        "fetch('/api/activity/export').then(response=>response.json())",
        await_promise=True,
    )
    if (
        activity_export.get("activityVersion") != 1
        or len(activity_export.get("records", [])) != 1
        or "profiles" in activity_export
    ):
        raise AssertionError(
            f"The local activity export exposed an unexpected shape: {activity_export!r}"
        )
    browser.click("#activityClearBtn")
    browser.wait_for(
        "!document.getElementById('confirmOverlay').classList.contains('hidden')",
        message="Clearing activity did not use the shared confirmation dialog",
    )
    browser.click("#confirmActionBtn")
    browser.wait_for(
        "activityState==='empty' && activityData.recordCount===0 && "
        "document.getElementById('activityMessage').textContent===uiText.activityClearSuccess && "
        "document.getElementById('activityExportBtn').disabled && "
        "document.getElementById('activityClearBtn').disabled",
        message="Clearing activity did not remove and re-render the local records",
    )
    browser.click("#cfgActivityTracking")
    browser.click("#saveBtn")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "cfg.activityTrackingEnabled===false",
        message="Opting out of local activity tracking was not persisted",
    )
    log_scenario("opt-in local activity dashboard exports and clears completed usage")

    enter_parent_settings(browser)
    browser.click("[data-admin-section='children']")
    browser.set_value("#newProfileName", "Alex")
    browser.set_value("#newProfileAvatar", "🚀")
    browser.click("#createProfileBtn")
    browser.wait_for(
        "cfg.activeProfileId!=='default' && cfg.name==='Alex' && "
        "cfg.profiles.length===2 && "
        "document.querySelectorAll('#profileList .profile-card').length===2",
        message="Creating a child profile did not activate and render it",
    )
    browser.screenshot(artifacts / "profile-management.png")
    alex_profile_id = browser.evaluate("cfg.activeProfileId")
    browser.set_value("#cfgProfileName", "Alex E2E")
    browser.set_value("#cfgProfileAvatar", "🪐")
    browser.set_value("#cfgTitle", "Alex's Space")
    browser.click("#saveBtn")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "cfg.name==='Alex E2E' && cfg.avatar==='🪐' && "
        "document.getElementById('title').textContent===\"Alex's Space\"",
        message="Profile edits were not persisted on the active home screen",
    )
    browser.click("#profileBtn")
    browser.wait_for(
        "!document.getElementById('profileOverlay').classList.contains('hidden') && "
        "document.querySelectorAll('#profilePickerGrid .profile-choice').length===2 && "
        "document.activeElement.matches('.profile-choice[aria-pressed=\"true\"]')",
        message="The child-facing profile picker did not open accessibly",
    )
    browser.screenshot(artifacts / "profile-picker.png")
    browser.click('.profile-choice[data-profile-id="default"]')
    browser.wait_for(
        "!document.getElementById('pin').classList.contains('hidden') && "
        "document.activeElement.id==='pinInput'",
        message="A child-facing profile switch bypassed Parent PIN confirmation",
    )
    browser.set_value("#pinInput", PIN)
    browser.click("#pin .save")
    browser.wait_for(
        "cfg.activeProfileId==='default' && "
        "document.getElementById('profileOverlay').classList.contains('hidden') && "
        "document.getElementById('title').textContent==='Polished E2E Home'",
        message="The confirmed profile switch did not restore the separate profile",
    )
    enter_parent_settings(browser)
    browser.click("[data-admin-section='children']")
    delete_selector = (
        f'.profile-card[data-profile-id={json.dumps(alex_profile_id)}] .danger'
    )
    browser.click(delete_selector)
    browser.wait_for(
        "!document.getElementById('confirmOverlay').classList.contains('hidden')",
        message="Profile deletion did not use the shared confirmation dialog",
    )
    browser.click("#confirmActionBtn")
    browser.wait_for(
        "cfg.profiles.length===1 && "
        "document.querySelectorAll('#profileList .profile-card').length===1",
        message="The inactive child profile was not deleted",
    )
    browser.click("#backBtn")
    log_scenario("profile creation, editing, PIN-gated selection, and deletion work end to end")

    enter_parent_settings(browser)
    browser.click("[data-admin-section='apps']")
    browser.evaluate(
        "cfg.layoutMode='gross'; cfg.tiles=cfg.tiles.concat(["
        "{id:'reading-filter',label:'Reading',emoji:'📚',cmd:['true'],visible:true},"
        "{id:'puzzles-filter',label:'Puzzles',emoji:'🧩',cmd:['true'],visible:true},"
        "{id:'drawing-filter',label:'Drawing',emoji:'✏️',cmd:['true'],visible:true}"
        "]); renderAdmin()"
    )
    browser.wait_for(
        "document.getElementById('adminPageNav').children.length===3",
        message="Unfiltered app editor did not paginate its five tiles",
    )
    browser.set_value("#tileSearch", "Paint")
    browser.wait_for(
        "Array.from(document.querySelectorAll('#forms .tileform'))"
        ".filter(row => getComputedStyle(row).display!=='none').length===1 && "
        "document.getElementById('adminTileResultCount').textContent.includes('1') && "
        "document.getElementById('adminPageNav').children.length===0",
        message="App search did not narrow the editor list",
    )
    browser.click("#bulkSelectFiltered")
    assert_js(
        browser,
        "adminSelectedTileIds.size===1 && "
        "document.getElementById('bulkHideTilesBtn').disabled===false",
        "Selecting filtered app results did not enable bulk actions",
    )
    browser.click("#bulkHideTilesBtn")
    browser.wait_for(
        "cfg.tiles[0].visible===false && adminSelectedTileIds.size===0",
        message="Bulk hide did not update the selected tile",
    )
    browser.set_value("#tileVisibilityFilter", "hidden")
    browser.wait_for(
        "filteredAdminTileIndexes().length===1 && "
        "document.querySelector('#forms .tileform input:nth-of-type(2)').value==='Paint'",
        message="Visibility filter did not isolate the bulk-hidden tile",
    )
    browser.click(
        "#forms .tileform[style*='display: grid'] .tile-select-toggle input"
    )
    browser.click("#bulkShowTilesBtn")
    browser.wait_for(
        "cfg.tiles[0].visible===true && "
        "!document.getElementById('adminTileEmptyState').hidden",
        message="Bulk show did not refresh the active hidden filter",
    )
    browser.set_value("#tileVisibilityFilter", "all")
    browser.set_value("#tileSearch", "no matching tile")
    browser.wait_for(
        "!document.getElementById('adminTileEmptyState').hidden && "
        "Array.from(document.querySelectorAll('#forms .tileform'))"
        ".every(row => getComputedStyle(row).display==='none')",
        message="Empty search results did not expose their status",
    )
    browser.set_value("#tileSearch", "Drawing")
    browser.wait_for(
        "filteredAdminTileIndexes().length===1",
        message="Synthetic tile was not available for bulk deletion",
    )
    browser.click(
        "#forms .tileform[style*='display: grid'] .tile-select-toggle input"
    )
    browser.evaluate("document.getElementById('bulkDeleteTilesBtn').focus()")
    browser.click("#bulkDeleteTilesBtn")
    browser.wait_for(
        "!document.getElementById('confirmOverlay').classList.contains('hidden') && "
        "document.activeElement.id==='confirmCancelBtn' && cfg.tiles.length===5",
        message="Bulk delete did not open the shared confirmation dialog safely",
    )
    browser.key_press("Escape")
    browser.wait_for(
        "document.getElementById('confirmOverlay').classList.contains('hidden') && "
        "document.activeElement.id==='bulkDeleteTilesBtn' && cfg.tiles.length===5",
        message="Confirmation cancellation did not restore focus and preserve tiles",
    )
    browser.click("#bulkDeleteTilesBtn")
    browser.wait_for("document.activeElement.id==='confirmCancelBtn'")
    browser.screenshot(artifacts / "confirmation-dialog.png")
    browser.key_press("Tab")
    assert_js(
        browser,
        "document.activeElement.id==='confirmActionBtn'",
        "Confirmation tab order did not reach its action",
    )
    browser.key_press("Tab")
    assert_js(
        browser,
        "document.activeElement.id==='confirmCancelBtn'",
        "Confirmation dialog did not keep keyboard focus contained",
    )
    browser.click("#confirmActionBtn")
    browser.wait_for(
        "cfg.tiles.length===4 && !cfg.tiles.some(tile => tile.id==='drawing-filter') && "
        "!document.getElementById('adminTileEmptyState').hidden && "
        "filteredAdminTileIndexes().length===0",
        message="Bulk delete did not remove the selected tile or refresh results",
    )
    browser.evaluate(
        "cfg.tiles=cfg.tiles.slice(0,2); cfg.layoutMode='klein'; "
        "adminTileQuery=''; adminTileVisibility='all'; adminPage=0; renderAdmin()"
    )
    log_scenario("app search, filtering, bulk actions, and empty results stay local")

    browser.evaluate(
        "window.__cozyOriginalFetch=window.fetch.bind(window);"
        "window.fetch=(input,options)=>{"
        " if(String(input)==='/api/recommendations') return new Promise((resolve,reject)=>{"
        "  window.__rejectRecommendations=reject;"
        " });"
        " return window.__cozyOriginalFetch(input,options);"
        "};"
        "loadRecommendations()"
    )
    browser.wait_for(
        "recommendationState==='loading' && "
        "document.getElementById('recommendationState').getAttribute('aria-busy')==='true'",
        message="Recommendation refresh did not expose its loading state",
    )
    browser.evaluate("window.__rejectRecommendations(new Error('synthetic failure'))")
    browser.wait_for(
        "recommendationState==='error' && "
        "document.getElementById('recommendationState').classList.contains('ui-state-error') && "
        "document.querySelector('#recommendationState .ui-state-retry')!==null",
        message="Recommendation failure did not expose an actionable error state",
    )
    browser.screenshot(artifacts / "recommendations-error.png")
    browser.evaluate(
        "window.fetch=(input,options)=>String(input)==='/api/recommendations'"
        " ? Promise.resolve(new Response('[]',{status:200,"
        "headers:{'Content-Type':'application/json'}}))"
        " : window.__cozyOriginalFetch(input,options)"
    )
    browser.click("#recommendationState .ui-state-retry")
    browser.wait_for(
        "recommendationState==='empty' && "
        "document.getElementById('recommendationState').classList.contains('ui-state-empty')",
        message="Empty recommendations did not render a clear empty state",
    )
    browser.evaluate(
        "window.fetch=window.__cozyOriginalFetch;"
        "delete window.__cozyOriginalFetch; delete window.__rejectRecommendations;"
        "loadRecommendations()"
    )
    browser.wait_for(
        "recommendationState==='ready' && document.getElementById('recommendationState')===null",
        message="Recommendation retry did not restore the populated state",
    )
    log_scenario("recommendations expose loading, error, empty, and recovery states")

    browser.click("[data-admin-section='screen-time']")
    browser.click("#appScheduleEnabled")
    browser.wait_for(
        "cfg.appAvailability[selectedAppScheduleId].enabled===true && "
        "document.querySelectorAll('#appScheduleDays .schedule-window').length===7",
        message="Enabling a per-app schedule did not create editable weekly defaults",
    )
    assert_js(
        browser,
        "document.querySelector('[data-admin-panel=\"screen-time\"]')"
        ".scrollWidth<=document.querySelector('[data-admin-panel=\"screen-time\"]')"
        ".clientWidth+1 && "
        "document.querySelector('.schedule-settings-grid').scrollWidth<="
        "document.querySelector('.schedule-settings-grid').clientWidth+1",
        "Schedule controls require horizontal scrolling",
    )
    browser.screenshot(artifacts / "schedule-editor.png")
    browser.evaluate(
        "cfg.appAvailability[selectedAppScheduleId]={enabled:true,days:{}};"
        "renderScheduleControls()"
    )
    browser.click("#saveBtn")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "availabilityStatus.profileAllowed===true && "
        "availabilityStatus.blockedTileIds.includes(cfg.tiles[0].id) && "
        "document.querySelector('#grid .tile.unavailable')!==null",
        message="The saved app schedule did not mark its tile unavailable",
    )
    browser.click("#grid .tile.unavailable")
    browser.wait_for(
        "!document.getElementById('availabilityBlock').classList.contains('hidden') && "
        "document.getElementById('availabilityBlock').dataset.reason==='app_schedule' && "
        "document.activeElement.id==='availabilityBlockClose'",
        message="An unavailable app did not explain its blocked state accessibly",
    )
    browser.screenshot(artifacts / "app-schedule-blocked.png")
    browser.click("#availabilityBlockClose")

    enter_parent_settings(browser)
    browser.click("[data-admin-section='screen-time']")
    browser.click("#clearAppScheduleBtn")
    browser.click("#weeklyScheduleEnabled")
    browser.wait_for(
        "cfg.weeklySchedule.enabled===true && "
        "document.querySelectorAll('#weeklyScheduleDays .schedule-window').length===7",
        message="Enabling the weekly schedule did not create editable daily defaults",
    )
    browser.evaluate("cfg.weeklySchedule={enabled:true,days:{}};renderScheduleControls()")
    browser.click("#saveBtn")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "availabilityStatus.profileAllowed===false && "
        "!document.getElementById('availabilityBlock').classList.contains('hidden') && "
        "document.getElementById('availabilityBlock').dataset.reason==='profile_schedule' && "
        "document.getElementById('availabilityBlockClose').hidden===true",
        message="The profile-wide schedule did not block the launcher",
    )
    browser.screenshot(artifacts / "weekly-schedule-blocked.png")
    browser.click("#availabilityParentsBtn")
    browser.wait_for("!document.getElementById('pin').classList.contains('hidden')")
    browser.set_value("#pinInput", PIN)
    browser.click("#pin .save")
    browser.wait_for("!document.getElementById('admin').classList.contains('hidden')")
    browser.click("[data-admin-section='screen-time']")
    browser.click("#weeklyScheduleEnabled")
    browser.click("#saveBtn")
    browser.wait_for(
        "availabilityStatus.profileAllowed===true && "
        "document.getElementById('availabilityBlock').classList.contains('hidden')",
        message="Disabling the weekly schedule did not restore launcher availability",
    )
    log_scenario("weekly and per-app schedules persist and explain blocked states")

    enter_parent_settings(browser)
    browser.click("[data-admin-section='screen-time']")
    browser.set_value("#cfgTimerMinutes", "15")
    browser.click("#timerToggleBtn")
    browser.wait_for(
        "lastTimerStatus.active === true && lastTimerStatus.expired === false && "
        "document.getElementById('timerBadge').style.display === 'block'",
        message="Timer did not become active",
    )
    assert_js(
        browser,
        "document.getElementById('timerBadge').textContent.includes('15') || "
        "document.getElementById('timerBadge').textContent.includes('14')",
        "Timer badge does not show the remaining time",
    )
    browser.click("#timerToggleBtn")
    browser.wait_for(
        "lastTimerStatus.active === false && "
        "document.getElementById('timerBadge').style.display === 'none'",
        message="Timer did not stop cleanly",
    )
    log_scenario("screen timer starts, renders its badge, and stops")

    # Beni Launcher: as atualizações são automáticas (beni-atualizar); o botão só
    # mostra o estado e nunca oferece "Atualizar agora".
    browser.click("[data-admin-section='system']")
    browser.click("#checkUpdateBtn")
    encoded_installed = json.dumps(installed_version)
    browser.wait_for(
        "document.getElementById('checkUpdateBtn').disabled === false && "
        "document.querySelector('#updateMsg .ui-state-message') !== null && "
        "!document.querySelector('#updateMsg').textContent.includes(uiText.updateLoading)",
        message="Update status check did not finish",
    )
    assert_js(
        browser,
        "document.getElementById('updateRow').style.display === 'none' && "
        f"document.getElementById('versionDisplay').textContent.includes({encoded_installed}) && "
        "/Atualiza[çc][õo]es autom[áa]ticas|Em dia|baixada/.test(document.getElementById('updateMsg').textContent)",
        "Automatic-update status was not rendered",
    )
    log_scenario("update panel shows the automatic-update status")


def run_accessibility_scenarios(browser, artifacts):
    prepared = browser.evaluate(
        "(() => {"
        " if(!document.getElementById('admin').classList.contains('hidden')) closeAdmin();"
        " cfg.layoutMode='gross'; cfg.currentPage=0;"
        " cfg.tiles=cfg.tiles.slice(0,1).concat(["
        "  {id:'reading',label:'Reading',emoji:'📚',cmd:['true'],visible:true},"
        "  {id:'puzzles',label:'Puzzles',emoji:'🧩',cmd:['true'],visible:true},"
        "  {id:'drawing',label:'Drawing',emoji:'✏️',cmd:['true'],visible:true},"
        "  {id:'science',label:'Science',emoji:'🔬',cmd:['true'],visible:true}"
        " ]); focusedTileIndex=0; renderAll();"
        " return visibleTiles().length===5 && pageCount()===2 && "
        "document.querySelectorAll('#grid .tile:not(.placeholder)').length===4;"
        "})()"
    )
    if prepared is not True:
        raise AssertionError("Accessibility fixture did not create a second page")

    assert_js(
        browser,
        "document.activeElement===document.querySelector('#grid .tile:not(.placeholder)')",
        "Home keyboard focus did not start on the first tile",
    )
    browser.key_press("ArrowRight")
    assert_js(
        browser,
        "document.activeElement===document.querySelectorAll('#grid .tile:not(.placeholder)')[1] && "
        "document.activeElement.classList.contains('focused')",
        "Arrow navigation did not move real focus to the next tile",
    )
    browser.key_press("ArrowLeft")
    browser.key_press("Tab")
    assert_js(
        browser,
        "document.activeElement===document.querySelectorAll('#grid .tile:not(.placeholder)')[1] && "
        "document.activeElement.classList.contains('focused') && focusedTileIndex===1",
        "Tab navigation did not synchronize real and visual tile focus",
    )
    browser.key_press("Enter")
    browser.wait_for(
        "!document.getElementById('startOverlay').classList.contains('hidden') && "
        "document.getElementById('startText').textContent.includes(tilesForPage(cfg.currentPage)[1].label)",
        message="Keyboard activation did not launch the focused tile",
    )
    browser.wait_for(
        "document.getElementById('startOverlay').classList.contains('hidden')",
        timeout=3,
    )
    for _ in range(10):
        if browser.evaluate("document.activeElement.id==='parentBtn'") is True:
            break
        browser.key_press("Tab")
    else:
        raise AssertionError("Tab navigation did not reach Parent settings")
    browser.key_press("Enter")
    browser.wait_for(
        "!document.getElementById('pin').classList.contains('hidden') && "
        "document.activeElement.id==='pinInput'",
        message="Keyboard activation did not focus the PIN dialog",
    )
    browser.insert_text(PIN)
    browser.key_press("Enter")
    browser.wait_for(
        "!document.getElementById('admin').classList.contains('hidden') && "
        "document.activeElement.id==='adminNavOverview' && "
        "document.querySelector('[data-admin-panel=\"overview\"]')"
        ".hidden===false",
        message="Keyboard PIN submission did not focus the Parent overview",
    )
    for _ in range(4):
        browser.key_press("ArrowRight")
    assert_js(
        browser,
        "document.activeElement.id==='adminNavAppearance' && "
        "document.querySelector('[data-admin-panel=\"appearance\"]')"
        ".hidden===false && document.querySelector('[data-admin-panel=\"appearance\"]')"
        ".classList.contains('admin-panel-enter')",
        "Arrow navigation did not activate the Appearance section",
    )
    browser.key_press("Tab")
    assert_js(
        browser,
        "document.activeElement.id==='openThemeBtn'",
        "Appearance tab order did not reach the theme picker",
    )
    browser.key_press("Enter")
    browser.wait_for(
        "!document.getElementById('themeOverlay').classList.contains('hidden') && "
        "document.activeElement.matches('#themeChooser .theme-thumb')",
        message="Theme picker did not focus its first semantic button",
    )
    assert_js(
        browser,
        "Array.from(document.querySelectorAll('#themeChooser .theme-thumb')).every(button => "
        "button.tagName==='BUTTON' && button.type==='button' && button.getAttribute('aria-label'))",
        "Theme choices are not exposed as labelled buttons",
    )
    # Ordem: benikids (1º), rosa (tema atual), lila.
    browser.key_press("Tab")
    browser.key_press("Tab")
    browser.key_press("Enter")
    browser.wait_for(
        "document.getElementById('themeOverlay').classList.contains('hidden') && "
        "document.getElementById('cfgTheme').value==='lila' && "
        "document.activeElement.id==='openThemeBtn'",
        message="Keyboard theme selection did not return focus to its trigger",
    )
    browser.key_press("Escape")
    browser.wait_for(
        "document.getElementById('admin').classList.contains('hidden') && "
        "document.activeElement.matches('#grid .tile:not(.placeholder)')",
        message="Escape did not return from Parent settings to the tile grid",
    )
    log_scenario("keyboard-only flow keeps real focus and operates Parent settings")

    browser.evaluate("cfg.currentPage=0; focusedTileIndex=0; renderAll()")
    browser.touch_swipe(700, 400, 100, 400)
    browser.wait_for(
        "location.pathname==='/index.html' && typeof cfg!=='undefined' && cfg.currentPage===1 && "
        "document.getElementById('grid').classList.contains('page-enter-next')",
        message="Left swipe did not advance the page without activating a tile",
    )
    browser.touch_swipe(100, 400, 700, 400)
    browser.wait_for(
        "location.pathname==='/index.html' && typeof cfg!=='undefined' && cfg.currentPage===0 && "
        "document.getElementById('grid').classList.contains('page-enter-back')",
        message="Right swipe did not return the page without activating a tile",
    )
    browser.evaluate("showPin()")
    browser.touch_swipe(700, 400, 100, 400)
    assert_js(
        browser,
        "cfg.currentPage===0",
        "Touch navigation changed the hidden home page behind a modal",
    )
    browser.key_press("Escape")
    browser.disable_touch_emulation()
    assert_js(
        browser,
        "document.getElementById('pin').classList.contains('hidden') && "
        "document.activeElement.matches('#grid .tile:not(.placeholder)')",
        "Closing the PIN dialog did not restore home focus",
    )
    log_scenario("touch swipes navigate pages and stop at modal boundaries")

    browser.set_emulated_media([("prefers-reduced-motion", "reduce")])
    browser.evaluate("playLauncherPageTransition(1)")
    assert_js(
        browser,
        "matchMedia('(prefers-reduced-motion: reduce)').matches && "
        "parseFloat(getComputedStyle(document.querySelector('.tile')).transitionDuration)<=0.001 && "
        "parseFloat(getComputedStyle(document.querySelector('.startbox .emoji')).animationDuration)<=0.001 && "
        "document.getElementById('grid').classList.contains('page-enter-next') && "
        "parseFloat(getComputedStyle(document.getElementById('grid')).animationDuration)<=0.001 && "
        "document.body.classList.contains('theme-world-motion') && "
        "parseFloat(getComputedStyle(document.getElementById('themeBg')).animationDuration)<=0.001",
        "Reduced-motion preference did not suppress launcher movement",
    )
    log_scenario("reduced-motion preference suppresses transitions and animations")

    browser.set_emulated_media([("forced-colors", "active")])
    assert_js(
        browser,
        "matchMedia('(forced-colors: active)').matches && "
        "getComputedStyle(document.querySelector('.tile')).borderTopStyle==='solid' && "
        "parseFloat(getComputedStyle(document.querySelector('.tile')).borderTopWidth)>=2 && "
        "getComputedStyle(document.querySelector('.tile')).boxShadow==='none'",
        "Forced-colors mode did not expose bounded high-contrast controls",
    )
    browser.screenshot(artifacts / "forced-colors.png")
    log_scenario("forced-colors mode keeps controls bounded and visible")

    browser.set_emulated_media()
    browser.set_device_metrics(800, 600)
    browser.evaluate("cfg.currentPage=0; focusedTileIndex=0; renderAll()")
    assert_js(
        browser,
        "window.innerWidth===800 && window.innerHeight===600 && "
        "document.documentElement.scrollWidth<=window.innerWidth && "
        "Array.from(document.querySelectorAll('#kids .tile:not(.placeholder),.cornerbar button,.nav:not(.hidden)'))"
        ".every(element => { const r=element.getBoundingClientRect(); return r.width>=44 && "
        "r.height>=44 && r.left>=0 && r.right<=window.innerWidth && r.top>=0 && r.bottom<=window.innerHeight; })",
        "The 800x600 home layout clipped content or touch targets",
    )
    browser.screenshot(artifacts / "low-resolution-home.png")
    browser.evaluate("enterAdmin()")
    assert_js(
        browser,
        "document.documentElement.scrollWidth<=window.innerWidth && "
        "document.querySelector('#admin .wrap').scrollWidth<=document.querySelector('#admin .wrap').clientWidth+1 && "
        "getComputedStyle(document.querySelector('#admin .wrap')).overflowY==='auto' && "
        "document.getElementById('adminTitle').getBoundingClientRect().top>=64 && "
        "document.querySelectorAll('[data-admin-section]').length===6 && "
        "Array.from(document.querySelectorAll('[data-admin-section]')).every(button => "
        "button.getBoundingClientRect().height>=44) && "
        "document.querySelector('.cornerbar').classList.contains('hidden') && "
        "document.getElementById('navLeft').classList.contains('hidden') && "
        "document.getElementById('navRight').classList.contains('hidden')",
        "The 800x600 Parent layout requires horizontal scrolling",
    )
    for section in (
        "overview",
        "children",
        "apps",
        "screen-time",
        "appearance",
        "system",
    ):
        panel_selector = json.dumps(f'[data-admin-panel="{section}"]')
        metrics = browser.evaluate(
            "(() => { activateAdminSection(" + json.dumps(section) + "); "
            "const panel=document.querySelector(" + panel_selector + "); "
            "const wrap=document.querySelector('#admin .wrap'); "
            "return {hidden:panel.hidden,panelScroll:panel.scrollWidth,"
            "panelClient:panel.clientWidth,wrapScroll:wrap.scrollWidth,"
            "wrapClient:wrap.clientWidth}; })()"
        )
        if (
            metrics["hidden"]
            or metrics["panelScroll"] > metrics["panelClient"] + 1
            or metrics["wrapScroll"] > metrics["wrapClient"] + 1
        ):
            raise AssertionError(
                f"Parent section {section!r} overflows at 800x600: {metrics!r}"
            )
    browser.evaluate(
        "activateAdminSection('appearance'); document.querySelector('#admin .wrap').scrollTop=0"
    )
    browser.screenshot(artifacts / "low-resolution-appearance.png")
    browser.evaluate(
        "activateAdminSection('apps'); document.querySelector('#admin .wrap').scrollTop=0"
    )
    browser.screenshot(artifacts / "low-resolution-apps.png")
    browser.evaluate("activateAdminSection('overview')")
    browser.screenshot(artifacts / "low-resolution-parent.png")
    browser.key_press("Escape")
    assert_js(
        browser,
        "!document.querySelector('.cornerbar').classList.contains('hidden')",
        "Closing Parent settings did not restore the home controls",
    )
    browser.set_device_metrics(1440, 900)
    log_scenario("800x600 home and Parent flows avoid clipping and horizontal scroll")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", help="Chromium-family executable name")
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=REPOSITORY_ROOT / ".test-artifacts" / "browser-e2e",
    )
    parser.add_argument("--timeout", type=float, default=25)
    args = parser.parse_args()

    browser_path = find_browser(args.browser)
    browser_name = Path(browser_path).name
    args.artifacts.mkdir(parents=True, exist_ok=True)
    print(f"Browser E2E: {browser_path}", flush=True)

    release_server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        ReleaseFixtureHandler,
    )
    release_thread = threading.Thread(target=release_server.serve_forever, daemon=True)
    release_thread.start()
    release_port = release_server.server_address[1]

    server_process = None
    server_log = None
    try:
        with tempfile.TemporaryDirectory(prefix="cozy-kids-browser-e2e-") as temp_dir:
            test_home = Path(temp_dir)
            install_log_path = args.artifacts / "install.log"
            with install_log_path.open("w", encoding="utf-8") as install_log:
                subprocess.run(
                    [
                        "bash",
                        "scripts/install.sh",
                        "--user",
                        getpass.getuser(),
                        "--home",
                        str(test_home),
                        "--lang",
                        "en",
                        "--browser",
                        browser_name,
                        "--launch-mode",
                        "window",
                        "--skip-browser-check",
                        "--force",
                    ],
                    cwd=REPOSITORY_ROOT,
                    stdout=install_log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )

            app_root = test_home / ".local" / "share" / "cozy-kids-launcher"
            config_path = test_home / ".config" / "cozy-kids-launcher" / "config.json"
            videos = test_home / "Videos"
            music = test_home / "Music"
            videos.mkdir(exist_ok=True)
            music.mkdir(exist_ok=True)
            (videos / "E2E_Film.mp4").write_bytes(b"video fixture")
            shutil.copyfile(
                app_root / "themes" / "ocean.jpg",
                videos / "E2E_Film.jpg",
            )
            (music / "Bedtime_Song.ogg").write_bytes(b"audio fixture")
            recent_media_id = hashlib.sha256(
                os.fsencode(os.path.realpath(videos / "E2E_Film.mp4"))
            ).hexdigest()[:24]
            media_state_path = (
                test_home / ".local" / "state" / "cozy-kids-launcher" / "media.json"
            )
            media_state_path.parent.mkdir(parents=True, exist_ok=True)
            media_state_path.write_text(
                json.dumps({
                    "mediaStateVersion": 1,
                    "profiles": {
                        "default": {"favorites": [], "recents": [recent_media_id]}
                    },
                }),
                encoding="utf-8",
            )
            demo_base = json.loads(config_path.read_text(encoding="utf-8"))
            write_demo_config(config_path, browser_name)
            installed_version = (app_root / "version").read_text(encoding="utf-8").strip()
            ReleaseFixtureHandler.latest_version = installed_version

            app_port = available_port()
            environment = dict(os.environ)
            environment.update({
                "HOME": str(test_home),
                "COZY_KIDS_PORT": str(app_port),
                "COZY_KIDS_RELEASE_API_URL": (
                    f"http://127.0.0.1:{release_port}/releases/latest"
                ),
                "COZY_KIDS_RAW_URL": f"http://127.0.0.1:{release_port}",
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
            })
            server_log = (args.artifacts / "server.log").open("w", encoding="utf-8")
            server_process = subprocess.Popen(
                ["python3", str(app_root / "server.py")],
                cwd=app_root,
                env=environment,
                stdout=server_log,
                stderr=subprocess.STDOUT,
            )
            base_url = f"http://127.0.0.1:{app_port}"
            wait_for_server(f"{base_url}/api/config", server_process)

            with BrowserSession(
                browser_name,
                f"{base_url}/index.html",
                test_home / "browser-profile",
                args.artifacts / "browser.log",
                timeout=args.timeout,
                width=1440,
                height=900,
            ) as browser:
                try:
                    run_scenarios(
                        browser,
                        ReleaseFixtureHandler,
                        installed_version,
                        args.artifacts,
                        lambda: write_demo_config(
                            config_path, browser_name, setup_completed=True, base=demo_base
                        ),
                    )
                    run_accessibility_scenarios(browser, args.artifacts)
                    browser.screenshot(args.artifacts / "final-state.png")
                except Exception:
                    browser.screenshot(args.artifacts / "failure.png")
                    raise
    finally:
        if server_process:
            stop_process(server_process)
        if server_log:
            server_log.close()
        release_server.shutdown()
        release_server.server_close()
        release_thread.join(timeout=5)

    print("Browser E2E passed: 18 core and accessibility journeys", flush=True)
    print(f"Artifacts: {args.artifacts}", flush=True)


if __name__ == "__main__":
    main()
