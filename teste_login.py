"""
teste_login.py - Script de diagnostico isolado do login visual.
Execute com: python teste_login.py
Mostra TODOS os detalhes do processo de login sem o Flask.
"""

import sys
import time

print("=" * 60)
print("  DIAGNOSTICO DE LOGIN VISUAL DO INSTAGRAM")
print("=" * 60)
print()

# ── 1. Verifica imports ────────────────────────────────────────
print("[1/5] Verificando dependencias...")
try:
    from playwright.sync_api import sync_playwright
    print("  [OK] playwright importado")
except ImportError as e:
    print(f"  [ERRO] playwright: {e}")
    sys.exit(1)

try:
    from instagrapi import Client
    print("  [OK] instagrapi importado")
except ImportError as e:
    print(f"  [ERRO] instagrapi: {e}")
    sys.exit(1)

print()

# ── 2. Abre o browser e aguarda login ─────────────────────────
print("[2/5] Abrindo Chrome para login...")

LOGIN_PATHS = (
    "/accounts/login",
    "/accounts/onetap",
    "/accounts/suspended",
    "/challenge",
    "/accounts/emailsignup",
)

def is_logged_in_url(url):
    return "instagram.com" in url and not any(p in url for p in LOGIN_PATHS)

sessionid = None
cookies_raw = None
user_id_str = None

with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=False, channel="chrome", args=["--start-maximized"])
        print("  [OK] Chrome do sistema aberto")
    except Exception:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        print("  [OK] Chromium do Playwright aberto")

    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    )
    page = context.new_page()

    print("  Navegando para instagram.com/accounts/login/ ...")
    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    print()
    print(">>> FACA LOGIN NORMALMENTE NO CHROME <<<")
    print("    O script detectara automaticamente quando o login for concluido.")
    print("    Timeout: 3 minutos")
    print()

    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            url = page.url
        except Exception:
            print("  [AVISO] Janela do browser fechada.")
            break

        print(f"  URL atual: {url[:80]}")

        if is_logged_in_url(url):
            print("  URL indica login concluido! Lendo cookies...")
            all_cookies = context.cookies()
            print(f"  Total de cookies encontrados: {len(all_cookies)}")

            for c in all_cookies:
                print(f"    cookie: name={c['name']}, domain={c.get('domain','')}, httpOnly={c.get('httpOnly',False)}, value_len={len(str(c.get('value','')))})")
                if c["name"] == "sessionid":
                    sessionid = c["value"]
                if c["name"] == "ds_user_id":
                    user_id_str = c["value"]

            cookies_raw = all_cookies
            break

        page.wait_for_timeout(3000)

    browser.close()

print()

# ── 3. Verifica o que foi capturado ──────────────────────────
print("[3/5] Resultado da captura:")
print(f"  sessionid: {'SIM (' + str(len(sessionid)) + ' chars)' if sessionid else 'NAO ENCONTRADO'}")
print(f"  ds_user_id: {user_id_str if user_id_str else 'NAO ENCONTRADO'}")
print(f"  total cookies: {len(cookies_raw) if cookies_raw else 0}")

if not sessionid:
    print()
    print("[FALHA] sessionid nao capturado. Causas possiveis:")
    print("  - Login nao foi concluido antes do timeout")
    print("  - Instagram redirecionou para uma URL nao reconhecida")
    print("  - O cookie ainda nao apareceu ao verificar")
    sys.exit(1)

print()

# ── 4. Tenta autenticar o instagrapi ─────────────────────────
print("[4/5] Autenticando instagrapi com os cookies...")

cl = Client()
cl.delay_range = [2, 5]

cookie_dict = {c["name"]: c["value"] for c in cookies_raw if c.get("value")}
cookie_dict["sessionid"] = sessionid

print(f"  Cookies injetados: {list(cookie_dict.keys())}")

cl.set_settings({"cookies": cookie_dict})
cl.private.cookies.update(cookie_dict)
cl.public.cookies.update(cookie_dict)

if user_id_str:
    cl.user_id = int(user_id_str)
    print(f"  user_id configurado: {cl.user_id}")

# Tenta validar
print()
print("  Tentando user_short_gql...")
try:
    u = cl.user_short_gql(cl.user_id)
    print(f"  [OK] user_short_gql retornou: @{u.username}")
    cl.username = u.username
except Exception as e:
    print(f"  [ERRO] user_short_gql: {type(e).__name__}: {e}")

print()
print("  Tentando account_info...")
try:
    info = cl.account_info()
    print(f"  [OK] account_info retornou: @{info.username} (id={info.pk})")
except Exception as e:
    print(f"  [ERRO] account_info: {type(e).__name__}: {e}")

print()
print("  Tentando get_timeline_feed...")
try:
    feed = cl.get_timeline_feed()
    print(f"  [OK] get_timeline_feed OK")
except Exception as e:
    print(f"  [ERRO] get_timeline_feed: {type(e).__name__}: {e}")

print()

# ── 5. Resultado final ────────────────────────────────────────
print("[5/5] Resumo final:")
print(f"  sessionid capturado:  {'SIM' if sessionid else 'NAO'}")
print(f"  ds_user_id capturado: {'SIM (' + user_id_str + ')' if user_id_str else 'NAO'}")
print()
print("Copie e cole todo o output acima para o assistente analisar.")
print("=" * 60)
