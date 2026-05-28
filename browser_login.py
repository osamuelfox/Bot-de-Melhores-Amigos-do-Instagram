"""
browser_login.py - Abre um Chrome real para o usuario fazer login visual no Instagram.
Retorna (sessionid, username, cookies_raw) apos login bem-sucedido.

NOTA: sessionid e HttpOnly - nao aparece em document.cookie no JS.
Usamos polling com context.cookies() do Playwright que le cookies HttpOnly.
"""

# URLs que indicam que o usuario AINDA esta no fluxo de login/desafio
_LOGIN_PATHS = (
    "/accounts/login",
    "/accounts/onetap",
    "/accounts/suspended",
    "/challenge",
    "/accounts/emailsignup",
)


def _is_logged_in_url(url: str) -> bool:
    """Retorna True se a URL indica que o login foi concluido."""
    if "instagram.com" not in url:
        return False
    return not any(path in url for path in _LOGIN_PATHS)


def open_visual_login(username: str = "", password: str = "", callback=None) -> tuple:
    """
    Abre um navegador Chrome visivel para o usuario fazer login no Instagram.
    Retorna (sessionid, username, cookies_raw) em caso de sucesso.
    Retorna (None, None, None) em caso de falha.

    Estrategia de deteccao:
      - Polling a cada 2s por ate 3 minutos
      - Verifica URL (saiu da tela de login)
      - Le cookies via context.cookies() do Playwright (le HttpOnly)

    Args:
        username: Pre-preenche o campo de usuario (opcional).
        password: Pre-preenche o campo de senha (opcional).
        callback: Funcao chamada com mensagens de status.
    """
    import time

    def notify(msg):
        if callback:
            callback(msg)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        notify("ERRO: Playwright nao encontrado. Rode: playwright install chromium")
        return None, None, None

    notify("Abrindo navegador Chrome...")

    try:
        with sync_playwright() as p:
            # Tenta Chrome do sistema; se falhar, usa o Chromium do Playwright
            try:
                browser = p.chromium.launch(
                    headless=False,
                    channel="chrome",
                    args=["--start-maximized"],
                )
                notify("Usando Google Chrome instalado no sistema.")
            except Exception:
                notify("Chrome nao encontrado. Usando Chromium do Playwright...")
                browser = p.chromium.launch(
                    headless=False,
                    args=["--start-maximized"],
                )

            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            notify("Acessando o Instagram...")
            page.goto(
                "https://www.instagram.com/accounts/login/",
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(2500)

            # Pre-preenche credenciais se fornecidas
            if username:
                try:
                    page.fill('input[name="username"]', username)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            if password:
                try:
                    page.fill('input[name="password"]', password)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

            notify("Aguardando voce completar o login no Chrome (timeout: 3 minutos)...")
            notify("Faca login normalmente. O bot detectara automaticamente quando terminar.")

            # ── POLLING DE DETECCAO ─────────────────────────────────────────
            # sessionid e HttpOnly: nao aparece em document.cookie no JS.
            # Usamos context.cookies() do Playwright que le cookies HttpOnly.

            sessionid = None
            cookies_raw = None
            logged_username = username
            deadline = time.time() + 180  # 3 minutos

            while time.time() < deadline:
                # Verifica se o Chrome ainda esta aberto
                try:
                    current_url = page.url
                except Exception:
                    notify("O navegador foi fechado antes do login ser concluido.")
                    break

                # A URL indica que o login foi concluido?
                if _is_logged_in_url(current_url):
                    # Le todos os cookies do contexto (inclui HttpOnly)
                    all_cookies = context.cookies()

                    # Busca o sessionid
                    for cookie in all_cookies:
                        if cookie["name"] == "sessionid" and cookie["value"]:
                            sessionid = cookie["value"]
                            break

                    if sessionid:
                        # Captura username do cookie rcsb_2 ou ds_user_id
                        for cookie in all_cookies:
                            if cookie["name"] == "ds_user_id" and not logged_username:
                                logged_username = cookie["value"]

                        cookies_raw = all_cookies
                        notify("Login detectado com sucesso! Extraindo sessao...")
                        break
                    # else: URL mudou mas cookie ainda nao chegou, aguarda 1.5s

                # Aguarda 2 segundos antes da proxima verificacao
                page.wait_for_timeout(2000)

            # Fecha o navegador
            try:
                browser.close()
            except Exception:
                pass

            if sessionid:
                notify("Sessao extraida! Autenticando o bot...")
                return sessionid, logged_username, cookies_raw
            else:
                notify("Nao foi possivel detectar o login. Tente novamente.")
                return None, None, None

    except Exception as e:
        notify(f"Erro inesperado no login visual: {e}")
        return None, None, None
