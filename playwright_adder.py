"""
playwright_adder.py - Adiciona usuarios aos Melhores Amigos via Instagram Web.

Estrategia (duas camadas):
  1. API Direta: Usa page.evaluate(fetch(...)) para chamar o endpoint
     /api/v1/friendships/set_besties/ diretamente do contexto do navegador.
     Isso usa os cookies reais da sessao web, sem precisar de seletores CSS frageis.
     Adicionando UM USUARIO POR VEZ com delays aleatorios para evitar bloqueios.
  2. Fallback UI: Se a API falhar, tenta via automacao de interface (pesquisa + clique).

Delays recomendados (baseados em comportamento humano natural):
  - Entre cada usuario: 25–55 segundos (aleatorio)
  - Apos erro 429 (rate limit): 15–30 minutos de cooldown
  - Apos erro desconhecido: 60–120 segundos
"""

import json
import time
import random
import traceback
from playwright.sync_api import sync_playwright

# Delays em segundos (configuracao central)
DELAY_ENTRE_USUARIOS_MIN = 25   # Minimo entre cada adicao individual
DELAY_ENTRE_USUARIOS_MAX = 55   # Maximo entre cada adicao individual
DELAY_RATE_LIMIT_MIN     = 900  # 15 min apos erro 429
DELAY_RATE_LIMIT_MAX     = 1800 # 30 min apos erro 429
DELAY_ERRO_MIN           = 60   # Apos erro desconhecido
DELAY_ERRO_MAX           = 120


def _abrir_browser_com_sessao():
    """
    Abre o browser Playwright com os cookies da sessao salva.
    Retorna (browser, context, page) ou lança excecao se falhar.
    """
    with open("session.json", "r") as f:
        session_data = json.load(f)
        cookies_dict = session_data.get("cookies", {})

    playwright_cookies = [
        {"name": k, "value": str(v), "domain": ".instagram.com", "path": "/"}
        for k, v in cookies_dict.items()
    ]

    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(
            headless=True, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    context.add_cookies(playwright_cookies)
    page = context.new_page()
    return p, browser, context, page


def obter_melhores_amigos_ids(log_cb=None) -> set:
    """
    Busca a lista atual de Melhores Amigos (Close Friends) via API web do Instagram.

    Chama o endpoint paginado /api/v1/friendships/besties/ e coleta todos os
    user_ids presentes na lista. Retorna um set de strings com os IDs.

    Usa o session.json para autenticar via Playwright (mesmo mecanismo da adicao).

    Args:
        log_cb: Funcao opcional log(msg, level) para logging. Se None, usa print.

    Retorna:
        set de strings com os user_ids ja presentes nos Melhores Amigos.
        Em caso de falha retorna set vazio.
    """
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)
        else:
            print(f"[{level.upper()}] {msg}", flush=True)

    try:
        _log("Buscando lista atual de Melhores Amigos...", "info")

        try:
            with open("session.json", "r") as f:
                session_data = json.load(f)
                cookies_dict = session_data.get("cookies", {})
        except Exception as e:
            _log(f"Erro ao ler session.json: {e}", "error")
            return set()

        if not cookies_dict.get("sessionid"):
            _log("sessionid nao encontrado em session.json.", "error")
            return set()

        playwright_cookies = [
            {"name": k, "value": str(v), "domain": ".instagram.com", "path": "/"}
            for k, v in cookies_dict.items()
        ]

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True, channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            context.add_cookies(playwright_cookies)
            page = context.new_page()

            # Navega ao Instagram para carregar cookies no contexto
            try:
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
            except Exception as e:
                _log(f"Erro ao carregar Instagram: {e}", "error")
                browser.close()
                return set()

            if "/accounts/login" in page.url or "/challenge" in page.url:
                _log("Sessao expirada ao buscar Melhores Amigos.", "error")
                browser.close()
                return set()

            # Busca paginada — tenta múltiplos endpoints que o Instagram usa
            result = page.evaluate("""
                async () => {
                    const allIds = [];

                    // O Instagram Web usa close_friends/ com paginação ou besties/ com params
                    const ENDPOINTS = [
                        '/api/v1/friendships/close_friends/',
                        '/api/v1/friendships/besties/?source=audience_manager',
                    ];

                    for (const baseUrl of ENDPOINTS) {
                        let nextMaxId = null;
                        let pageCount = 0;
                        let worked = false;

                        try {
                            do {
                                const url = baseUrl + (nextMaxId
                                    ? (baseUrl.includes('?') ? '&' : '?') + 'max_id=' + encodeURIComponent(nextMaxId)
                                    : '');

                                const resp = await fetch(url, {
                                    method: 'GET',
                                    headers: {
                                        'X-IG-App-ID': '936619743392459',
                                        'X-Requested-With': 'XMLHttpRequest',
                                        'Accept': 'application/json',
                                    },
                                    credentials: 'include',
                                });

                                if (!resp.ok) {
                                    // Esse endpoint nao funcionou, tenta o proximo
                                    break;
                                }

                                const data = await resp.json();
                                const users = data.users || data.besties || [];
                                for (const u of users) {
                                    const uid = String(u.pk || u.id || '');
                                    if (uid && !allIds.includes(uid)) allIds.push(uid);
                                }

                                worked = true;
                                pageCount++;
                                nextMaxId = data.next_max_id || null;

                            } while (nextMaxId && pageCount < 50);

                            if (worked) break; // Parou apos o primeiro endpoint que funcionou
                        } catch (err) {
                            // Tenta o proximo endpoint
                        }
                    }

                    return { ok: true, ids: allIds };
                }
            """)

            browser.close()

            if result and result.get("ok"):
                ids = set(result.get("ids", []))
                _log(f"Lista de Melhores Amigos obtida: {len(ids)} usuario(s) ja adicionado(s).", "success")
                return ids
            else:
                _log("Falha ao buscar lista de Melhores Amigos nos endpoints disponiveis.", "warning")
                return set()

    except Exception as e:
        _log(f"Excecao ao buscar lista de Melhores Amigos: {e}", "error")
        return set()


def adicionar_usuario_via_playwright(user_id: str, username: str, push_event_cb, log_cb) -> bool:
    """
    Adiciona um único usuário aos Melhores Amigos via sessão web (Playwright).
    Usado pelo monitor de novos seguidores quando o login foi feito via Chrome.

    Args:
        user_id: ID do usuário a adicionar (string).
        username: @username para logs.
        push_event_cb: Callback push_event(type, **kwargs).
        log_cb: Callback log(msg, level).

    Retorna True se adicionado com sucesso, False caso contrário.
    """
    try:
        with open("session.json", "r") as f:
            session_data = json.load(f)
            cookies_dict = session_data.get("cookies", {})
    except Exception as e:
        log_cb(f"[Monitor] Erro ao ler session.json para adicionar @{username}: {e}", "error")
        return False

    if not cookies_dict.get("sessionid"):
        log_cb(f"[Monitor] sessionid não encontrado para adicionar @{username}.", "error")
        return False

    playwright_cookies = [
        {"name": k, "value": str(v), "domain": ".instagram.com", "path": "/"}
        for k, v in cookies_dict.items()
    ]

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(
                    headless=True, channel="chrome",
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            context.add_cookies(playwright_cookies)
            page = context.new_page()

            # Navega brevemente para carregar os cookies no contexto
            try:
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
            except Exception as e:
                log_cb(f"[Monitor] Erro ao carregar Instagram para @{username}: {e}", "error")
                browser.close()
                return False

            if "/accounts/login" in page.url or "/challenge" in page.url:
                log_cb(f"[Monitor] Sessão expirada ao tentar adicionar @{username}.", "error")
                browser.close()
                return False

            # Chama o endpoint set_besties via fetch no contexto do browser
            result = page.evaluate("""
                async (userId) => {
                    try {
                        const csrftoken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                        if (!csrftoken) return { ok: false, body: 'csrftoken não encontrado' };

                        const resp = await fetch('/api/v1/friendships/set_besties/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-CSRFToken': csrftoken,
                                'X-IG-App-ID': '936619743392459',
                                'X-Instagram-AJAX': '1',
                                'X-Requested-With': 'XMLHttpRequest',
                            },
                            body: 'module=CLOSE_FRIENDS_V2_SEARCH&source=audience_manager'
                                + '&add=' + JSON.stringify([userId])
                                + '&remove=[]',
                            credentials: 'include',
                        });
                        const text = await resp.text();
                        return { ok: resp.ok, status: resp.status, body: text.substring(0, 300) };
                    } catch(err) {
                        return { ok: false, body: String(err) };
                    }
                }
            """, str(user_id))

            browser.close()

            if result and result.get("ok"):
                return True
            else:
                body = result.get("body", "") if result else "sem resposta"
                status = result.get("status", "?") if result else "?"
                log_cb(f"[Monitor] set_besties web para @{username} falhou: HTTP {status} — {body[:150]}", "warning")
                return False

    except Exception as e:
        log_cb(f"[Monitor] Exceção ao adicionar @{username} via Playwright: {e}", "error")
        return False


def adicionar_via_playwright(usuarios, push_event, set_progress, check_running,
                             delay_min=None, delay_max=None, batch_size=1):
    """
    Adiciona usuarios aos Melhores Amigos usando o Instagram Web via Playwright.

    Args:
        usuarios: Lista de dicts com {user_id, username}.
        push_event: Callback para enviar eventos SSE.
        set_progress: Callback para atualizar progresso.
        check_running: Callback que retorna True se a operacao deve continuar.
        delay_min: Delay minimo em segundos entre cada adicao (padrao: DELAY_ENTRE_USUARIOS_MIN).
        delay_max: Delay maximo em segundos entre cada adicao (padrao: DELAY_ENTRE_USUARIOS_MAX).
        batch_size: Numero de usuarios a serem adicionados por requisicao (padrao: 1).

    Returns:
        True se pelo menos parte dos usuarios foi processada.
    """
    # Usa as constantes globais se nao fornecidos
    d_min = delay_min if delay_min is not None else DELAY_ENTRE_USUARIOS_MIN
    d_max = delay_max if delay_max is not None else DELAY_ENTRE_USUARIOS_MAX

    # ── 1. Carrega cookies da sessao ──────────────────────────────────────
    try:
        with open("session.json", "r") as f:
            session_data = json.load(f)
            cookies_dict = session_data.get("cookies", {})
    except Exception as e:
        push_event("log", message=f"Erro ao ler session.json: {e}", level="error")
        return False

    if not cookies_dict.get("sessionid"):
        push_event("log", message="sessionid nao encontrado em session.json!", level="error")
        return False

    # Converte cookies para o formato Playwright
    playwright_cookies = []
    for k, v in cookies_dict.items():
        playwright_cookies.append({
            "name": k,
            "value": str(v),
            "domain": ".instagram.com",
            "path": "/"
        })

    total = len(usuarios)
    push_event("log", message=f"Preparando Playwright para {total} usuarios...", level="info")

    # ── 2. Abre o navegador e valida a sessao ─────────────────────────────
    with sync_playwright() as p:
        # Tenta Chrome do sistema; se falhar, usa Chromium do Playwright
        try:
            browser = p.chromium.launch(
                headless=True,
                channel="chrome",
                args=["--window-size=1280,800", "--disable-blink-features=AutomationControlled"],
            )
            push_event("log", message="Google Chrome iniciado (headless).", level="info")
        except Exception:
            push_event("log", message="Chrome nao encontrado. Usando Chromium...", level="warning")
            try:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--window-size=1280,800", "--disable-blink-features=AutomationControlled"],
                )
            except Exception as e:
                push_event("log", message=f"Erro ao iniciar navegador: {e}", level="error")
                return False

        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        context.add_cookies(playwright_cookies)
        page = context.new_page()

        # Navega ao Instagram para validar a sessao
        push_event("log", message="Verificando sessao no Instagram...", level="info")
        try:
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception as e:
            push_event("log", message=f"Erro ao acessar Instagram: {e}", level="error")
            browser.close()
            return False

        # Verifica se foi redirecionado para login
        if "/accounts/login" in page.url or "/challenge" in page.url:
            push_event("log", message="Sessao expirada ou bloqueada! Faca login novamente.", level="error")
            browser.close()
            return False

        push_event("log", message="Sessao valida! Iniciando adicao aos Melhores Amigos...", level="success")

        # ── 3. Tenta a abordagem via API direta ──────────────────────────
        api_ok = _try_api_approach(page, usuarios, push_event, set_progress, check_running,
                                   delay_min=d_min, delay_max=d_max, batch_size=batch_size)

        if not api_ok:
            push_event("log", message="API direta falhou. Tentando via interface web...", level="warning")
            _try_ui_approach(page, usuarios, push_event, set_progress, check_running)

        browser.close()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 1: API DIRETA (um usuario por vez, delays seguros)
# ─────────────────────────────────────────────────────────────────────────────

def _try_api_approach(page, usuarios, push_event, set_progress, check_running,
                      delay_min=None, delay_max=None, batch_size=1):
    """
    Chama o endpoint set_besties diretamente do contexto do navegador.

    Quando delay_min == 0 e batch_size == 1: envia todos os usuarios em um unico request (lote).
    Caso contrario: agrupa em lotes de batch_size e envia com delays aleatorios entre lotes.

    Estrategia de delays:
      - Entre cada lote: delay_min a delay_max segundos (configuravel pelo usuario)
      - Apos erro 429 (rate limit): DELAY_RATE_LIMIT_MIN a DELAY_RATE_LIMIT_MAX segundos
      - Apos erro desconhecido: DELAY_ERRO_MIN a DELAY_ERRO_MAX segundos
    """
    # Usa as constantes globais se nao fornecidos
    d_min = delay_min if delay_min is not None else DELAY_ENTRE_USUARIOS_MIN
    d_max = delay_max if delay_max is not None else DELAY_ENTRE_USUARIOS_MAX

    # ── Modo Lote Único (delay = 0) ─────────────────────────────────────
    if d_min == 0:
        return _try_api_batch(page, usuarios, push_event, set_progress, check_running)

    total = len(usuarios)
    done = 0
    consecutive_errors = 0

    chunks = [usuarios[i:i + batch_size] for i in range(0, total, batch_size)]

    push_event("log",
        message=f"Iniciando adicao em lotes de {batch_size}: {total} usuario(s) em {len(chunks)} lote(s). "
                f"Delay entre lotes: {d_min}–{d_max}s.",
        level="info"
    )

    for idx, chunk in enumerate(chunks):
        if not check_running():
            push_event("log", message="Operacao cancelada pelo usuario.", level="warning")
            return True  # Parcial OK

        chunk_ids = [str(u["user_id"]) for u in chunk]
        chunk_usernames = [u.get("username", "?") for u in chunk]
        usernames_str = ', '.join(f'@{u}' for u in chunk_usernames[:3])
        if len(chunk_usernames) > 3:
            usernames_str += f" e mais {len(chunk_usernames) - 3}"

        num_lote = idx + 1
        push_event("log", message=f"[Lote {num_lote}/{len(chunks)}] Adicionando {len(chunk)} usuario(s): {usernames_str}...", level="info")

        try:
            result = page.evaluate("""
                async (addIds) => {
                    try {
                        const csrftoken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                        if (!csrftoken) {
                            return { status: 0, ok: false, body: 'csrftoken nao encontrado nos cookies' };
                        }

                        const response = await fetch('/api/v1/friendships/set_besties/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-CSRFToken': csrftoken,
                                'X-IG-App-ID': '936619743392459',
                                'X-Instagram-AJAX': '1',
                                'X-Requested-With': 'XMLHttpRequest',
                            },
                            body: 'module=CLOSE_FRIENDS_V2_SEARCH&source=audience_manager'
                                + '&add=' + JSON.stringify(addIds)
                                + '&remove=[]',
                            credentials: 'include',
                        });

                        const text = await response.text();
                        return {
                            status: response.status,
                            ok: response.ok,
                            body: text.substring(0, 500)
                        };
                    } catch (err) {
                        return { status: 0, ok: false, body: err.message || String(err) };
                    }
                }
            """, chunk_ids)

            if result and result.get("ok"):
                done += len(chunk)
                consecutive_errors = 0
                set_progress(done)
                push_event("progress", done=done, total=total)
                push_event("log", message=f"[Lote {num_lote}/{len(chunks)}] Sucesso! ✓", level="success")

            elif result:
                status = result.get("status", "?")
                body   = result.get("body", "")
                consecutive_errors += 1
                push_event("log",
                    message=f"[Lote {num_lote}/{len(chunks)}] Falhou: HTTP {status} — {body[:150]}",
                    level="error"
                )

                if status == 429:
                    # Rate limit: pausa longa antes de retomar
                    cooldown = random.randint(DELAY_RATE_LIMIT_MIN, DELAY_RATE_LIMIT_MAX)
                    mins = cooldown // 60
                    push_event("log",
                        message=f"Rate limit (429) detectado! Cooldown de {mins} min antes de retomar...",
                        level="warning"
                    )
                    for s in range(cooldown, 0, -1):
                        if not check_running():
                            return True
                        push_event("countdown", seconds=s)
                        time.sleep(1)
                    # Retenta o mesmo lote apos o cooldown
                    push_event("log", message=f"Retentando lote {num_lote} apos cooldown...", level="info")
                    continue

                elif status in (401, 403):
                    push_event("log", message="Sessao invalida. Encerrando.", level="error")
                    return False

                elif status == 400:
                    push_event("log", message="Request rejeitado (400). Tentando fallback UI...", level="error")
                    return False

                else:
                    # Erro desconhecido: pausa moderada e continua
                    wait = random.randint(DELAY_ERRO_MIN, DELAY_ERRO_MAX)
                    push_event("log", message=f"Erro desconhecido. Aguardando {wait}s...", level="warning")
                    for s in range(wait, 0, -1):
                        if not check_running():
                            return True
                        push_event("countdown", seconds=s)
                        time.sleep(1)

                # Para se muitos erros consecutivos
                if consecutive_errors >= 3:
                    push_event("log",
                        message="3 erros consecutivos. Abortando API para tentar fallback.",
                        level="error"
                    )
                    return False
            else:
                push_event("log", message=f"[Lote {num_lote}/{len(chunks)}] Resposta vazia do evaluate.", level="error")
                return False

        except Exception as e:
            push_event("log", message=f"Excecao ao adicionar lote {num_lote}: {e}", level="error")
            push_event("log", message=traceback.format_exc(), level="error")
            return False

        # ── Delay entre lotes (exceto no ultimo) ────────────────────────
        if num_lote < len(chunks):
            delay = random.randint(d_min, d_max)
            push_event("log", message=f"Aguardando {delay}s antes do proximo lote...", level="info")
            for s in range(delay, 0, -1):
                if not check_running():
                    return True
                push_event("countdown", seconds=s)
                time.sleep(1)


    if done > 0:
        push_event("log",
            message=f"Concluido via API! {done}/{total} adicionados aos Melhores Amigos.",
            level="success"
        )
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 1b: LOTE ÚNICO (sem delays, todos de uma vez)
# ─────────────────────────────────────────────────────────────────────────────

def _try_api_batch(page, usuarios, push_event, set_progress, check_running):
    """
    Envia TODOS os usuarios em um unico request set_besties, sem delays.
    Usado quando o usuario seleciona delay = 0 (modo lote).

    O Instagram aceita lotes grandes, mas pode bloquear a conta por atividade
    nao humana. Use com cautela.
    """
    total = len(usuarios)
    add_ids = [str(u["user_id"]) for u in usuarios]
    usernames_preview = [u.get("username", "?") for u in usuarios[:5]]

    push_event("log",
        message=f"Modo Lote Unico: enviando {total} usuario(s) em uma unica requisicao...",
        level="info"
    )

    try:
        result = page.evaluate("""
            async (addIds) => {
                try {
                    const csrftoken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
                    if (!csrftoken) {
                        return { status: 0, ok: false, body: 'csrftoken nao encontrado' };
                    }

                    const response = await fetch('/api/v1/friendships/set_besties/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-CSRFToken': csrftoken,
                            'X-IG-App-ID': '936619743392459',
                            'X-Instagram-AJAX': '1',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        body: 'module=CLOSE_FRIENDS_V2_SEARCH&source=audience_manager'
                            + '&add=' + JSON.stringify(addIds)
                            + '&remove=[]',
                        credentials: 'include',
                    });

                    const text = await response.text();
                    return {
                        status: response.status,
                        ok: response.ok,
                        body: text.substring(0, 500)
                    };
                } catch (err) {
                    return { status: 0, ok: false, body: err.message || String(err) };
                }
            }
        """, add_ids)

        if result and result.get("ok"):
            set_progress(total)
            push_event("progress", done=total, total=total)
            usernames_str = ', '.join(f'@{u}' for u in usernames_preview)
            push_event("log",
                message=f"Lote unico OK! {total} usuario(s) adicionados — {usernames_str}{'...' if total > 5 else ''}",
                level="success"
            )
            return True
        else:
            status = result.get("status", "?") if result else "?"
            body   = result.get("body", "")   if result else ""
            push_event("log",
                message=f"Lote unico falhou: HTTP {status} — {body[:200]}",
                level="error"
            )
            if status == 429:
                push_event("log", message="Rate limit (429). Tente novamente mais tarde.", level="warning")
            elif status in (401, 403):
                push_event("log", message="Sessao invalida para esta API.", level="error")
            return False

    except Exception as e:
        push_event("log", message=f"Excecao no lote unico: {e}", level="error")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ESTRATEGIA 2: FALLBACK VIA UI (mais lenta, um por um)
# ─────────────────────────────────────────────────────────────────────────────

def _try_ui_approach(page, usuarios, push_event, set_progress, check_running):
    """
    Fallback: adiciona usuarios via automacao de interface web.
    Navega ate a pagina de Melhores Amigos, pesquisa cada usuario e clica no botao.
    """
    push_event("log", message="Abrindo pagina de Melhores Amigos...", level="info")

    try:
        page.goto("https://www.instagram.com/accounts/close_friends/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
    except Exception as e:
        push_event("log", message=f"Erro ao abrir pagina: {e}", level="error")
        return False

    # Verifica se fomos redirecionados
    if "/accounts/login" in page.url:
        push_event("log", message="Sessao expirada ao abrir Melhores Amigos.", level="error")
        return False

    # Procura o campo de busca com varios seletores possiveis
    search_selectors = [
        'input[placeholder*="Search"]',
        'input[placeholder*="Pesquisar"]',
        'input[placeholder*="search"]',
        'input[aria-label*="Search"]',
        'input[aria-label*="Pesquisar"]',
        'input[type="search"]',
        'input[type="text"]',
    ]

    search_input = None
    for sel in search_selectors:
        try:
            elem = page.locator(sel).first
            if elem.is_visible(timeout=2000):
                search_input = elem
                push_event("log", message=f"Campo de busca encontrado.", level="info")
                break
        except Exception:
            continue

    if not search_input:
        push_event("log", message="Campo de busca nao encontrado na pagina.", level="error")
        # Salva screenshot para debug
        try:
            page.screenshot(path="debug_close_friends.png")
            push_event("log", message="Screenshot salvo em debug_close_friends.png", level="info")
        except Exception:
            pass
        return False

    total = len(usuarios)
    done = 0

    for u in usuarios:
        if not check_running():
            push_event("log", message="Operacao cancelada pelo usuario.", level="warning")
            break

        username = u.get("username", "")
        if not username:
            continue

        push_event("log", message=f"Pesquisando @{username}...", level="info")

        try:
            # Limpa e pesquisa
            search_input.fill("")
            page.wait_for_timeout(500)
            search_input.fill(username)
            page.wait_for_timeout(2500)  # Aguarda resultados da busca

            added = False

            # Tenta encontrar o resultado da busca e clicar
            # O Instagram web mostra resultados como linhas clicaveis
            try:
                # Procura um elemento com o texto do username nos resultados
                result_row = page.locator(f'text="{username}"').first
                if result_row.is_visible(timeout=2000):
                    # Procura o botao/checkbox mais proximo
                    # Sobe na arvore DOM ate achar um container com botao
                    for level in range(1, 5):
                        parent_sel = " >> ".join([".."] * level)
                        try:
                            parent = result_row.locator(parent_sel)
                            btn = parent.locator('button, [role="button"], [role="checkbox"], circle').first
                            if btn.is_visible(timeout=500):
                                btn.click()
                                added = True
                                break
                        except Exception:
                            continue
            except Exception:
                pass

            # Fallback: clica no primeiro elemento interativo que nao e o campo de busca
            if not added:
                try:
                    clickables = page.locator('button:visible, [role="checkbox"]:visible, [role="switch"]:visible').all()
                    for btn in clickables:
                        try:
                            # Ignora botoes de navegacao/fechar
                            text = btn.inner_text(timeout=500)
                            if any(word in text.lower() for word in ["search", "pesquisar", "close", "fechar", "back"]):
                                continue
                            btn.click()
                            added = True
                            break
                        except Exception:
                            continue
                except Exception:
                    pass

            if added:
                done += 1
                set_progress(done)
                push_event("progress", done=done, total=total)
                push_event("log", message=f"@{username} adicionado! ({done}/{total})", level="success")
            else:
                push_event("log", message=f"@{username} nao encontrado ou nao pode ser adicionado.", level="warning")

            # Delay entre usuarios
            if done < total:
                time.sleep(random.randint(1, 3))

        except Exception as e:
            push_event("log", message=f"Erro ao adicionar @{username}: {e}", level="error")

    push_event("log", message=f"UI: {done}/{total} processados.", level="info")
    return done > 0
