"""
app.py - Servidor Flask com interface web para o Bot de Melhores Amigos do Instagram.
"""

import json
import queue
import threading
import time
import random
import traceback
import sys

from flask import Flask, render_template, jsonify, request, Response
from dotenv import load_dotenv
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired

load_dotenv()

app = Flask(__name__)

# Forca UTF-8 na saida do terminal (resolve UnicodeEncodeError no Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

state = {
    "client": None,
    "username": None,
    "user_id": None,
    "logged_in": False,
    "running": False,
    "is_running": False,
    "done": False,
    "progress_done": 0,
    "progress_total": 0,
    "pending_users": [],
    "session_type": None, # "web" ou "mobile"
    "login_token": None,  # Token único por tentativa de login; revogado no logout
    # ── Monitor de novos seguidores ──
    "monitor_running": False,
    "monitor_interval": 300,
    "monitor_known_ids": None,
    "monitor_added_count": 0,
    "monitor_last_check": None,
    "monitor_cycle_count": 0,
    # ── Monitor de novos seguindo ──
    "mf_running": False,
    "mf_interval": 300,
    "mf_known_ids": None,
    "mf_added_count": 0,
    "mf_last_check": None,
    "mf_cycle_count": 0,
}

event_queue: queue.Queue = queue.Queue()
lock = threading.Lock()
BATCH_SIZE = 50


def push_event(event_type: str, **kwargs):
    data = {"type": event_type, **kwargs}
    event_queue.put(data)


def log(msg, level="info"):
    push_event("log", message=msg, level=level)
    print(f"[{level.upper()}] {msg}", flush=True)

def _get_client():
    return state["client"]


# ─────────────────────────────────────────────────────────────────────────────
# ROTAS
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify({
        "logged_in": state["logged_in"],
        "username": state["username"],
        "running": state["running"],
        "done": state["done"],
        "progress_done": state["progress_done"],
        "progress_total": state["progress_total"],
    })


@app.route("/api/login/visual", methods=["POST"])
def login_visual():
    import uuid
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    # Gera um token único para esta tentativa de login
    # Se o usuário fizer logout antes de concluir, o token muda e a thread ignora o resultado
    my_token = str(uuid.uuid4())
    with lock:
        state["login_token"] = my_token

    def _login_log(msg, level="info"):
        """Envia log apenas se este token de login ainda for válido."""
        with lock:
            current_token = state.get("login_token")
        if current_token != my_token:
            return  # Token revogado: login cancelado, silencia esta thread
        push_event("login_progress", message=msg, level=level)
        print(f"[LOGIN-{level.upper()}] {msg}", flush=True)

    def _do_login():
        try:
            _login_log("Iniciando login visual...")

            from browser_login import open_visual_login

            def on_status(msg):
                _login_log(msg)

            result = open_visual_login(username, password, callback=on_status)

            # Verifica token antes de processar resultado
            with lock:
                if state.get("login_token") != my_token:
                    print("[LOGIN] Token revogado, ignorando resultado.", flush=True)
                    return

            if result and len(result) == 3:
                sessionid, user, cookies_raw = result
            else:
                sessionid, user, cookies_raw = None, None, None

            if not sessionid:
                _login_log("Login nao detectado. Certifique-se de completar o login no Chrome.", "error")
                push_event("login_error", message="Login nao detectado. Tente novamente.")
                return

            _login_log(f"Sessionid extraido! Tamanho: {len(sessionid)} chars")
            _login_log(f"Cookies extraidos: {len(cookies_raw) if cookies_raw else 0}")

            # Monta dict de cookies
            cookie_dict = {}
            user_id_str = None
            csrf_token = None

            if cookies_raw:
                for c in cookies_raw:
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name and value:
                        cookie_dict[name] = value
                    if name == "ds_user_id":
                        user_id_str = value
                    if name == "csrftoken":
                        csrf_token = value

            # Garante sessionid no dict
            cookie_dict["sessionid"] = sessionid

            _login_log(f"user_id (ds_user_id): {user_id_str}")
            _login_log(f"csrftoken presente: {'sim' if csrf_token else 'nao'}")

            if not user_id_str:
                _login_log("Cookie ds_user_id nao encontrado. Tentando extrair do sessionid...", "warning")
                import re
                match = re.match(r"^(\d+)", sessionid)
                if match:
                    user_id_str = match.group(1)
                    _login_log(f"user_id extraido do sessionid: {user_id_str}")

            if not user_id_str:
                _login_log("Nao foi possivel determinar o user_id.", "error")
                push_event("login_error", message="Nao foi possivel identificar o usuario. Tente fazer login novamente.")
                return

            # Verifica token novamente antes de criar o cliente (operação longa)
            with lock:
                if state.get("login_token") != my_token:
                    print("[LOGIN] Token revogado antes de criar cliente.", flush=True)
                    return

            # Cria o cliente instagrapi e injeta os cookies
            from instagrapi import Client
            cl = Client()
            cl.delay_range = [2, 5]
            cl.request_timeout = 15  # Evita hang infinito

            _login_log(f"Injetando {len(cookie_dict)} cookies no cliente via set_settings...")

            # Garante o ds_user_id no dict de cookies antes de injetar
            cookie_dict["ds_user_id"] = str(user_id_str)

            # Injeta todos os cookies no instagrapi usando o metodo oficial
            cl.set_settings({"cookies": cookie_dict, "authorization_data": {"ds_user_id": str(user_id_str), "sessionid": sessionid}})

            cl.username = user or username or ""

            _login_log(f"Cliente instagrapi configurado! Validando via GraphQL...")

            # Tenta validar via GraphQL (mais permissivo que API mobile)
            try:
                _login_log("Validando sessao via GraphQL...")
                gql_user = cl.user_short_gql(cl.user_id)
                cl.username = gql_user.username
                _login_log(f"Sessao validada! Conta: @{cl.username}", "success")
            except Exception as e_gql:
                _login_log(f"GraphQL retornou: {e_gql}. Tentando account_info...", "warning")
                try:
                    info = cl.account_info()
                    cl.user_id = info.pk
                    cl.username = info.username
                    _login_log(f"account_info OK! Conta: @{cl.username}", "success")
                except Exception as e_acc:
                    _login_log(f"account_info retornou: {e_acc}. Continuando sem validacao...", "warning")
                    if cl.username == "":
                        cl.username = user or username or f"usuario_{user_id_str}"
                    _login_log(f"Usando conta: @{cl.username} (sem validacao de API)", "warning")

            # Verifica token antes de marcar como logado
            with lock:
                if state.get("login_token") != my_token:
                    print("[LOGIN] Token revogado antes de marcar logado.", flush=True)
                    return

            # Salva a sessao
            try:
                cl.dump_settings("session.json")
                _login_log("Sessao salva em session.json")
            except Exception as e_dump:
                _login_log(f"Nao foi possivel salvar session.json: {e_dump}", "warning")

            state["client"] = cl
            state["username"] = cl.username
            state["user_id"] = cl.user_id
            state["logged_in"] = True
            state["session_type"] = "web"
            push_event("login_success", username=cl.username)
            _login_log(f"Login concluido como @{cl.username}!", "success")

        except Exception as e:
            tb = traceback.format_exc()
            _login_log(f"ERRO CRITICO no login: {e}", "error")
            print(f"[LOGIN-TRACEBACK] {tb}", flush=True)
            # Verifica se o token ainda é válido antes de emitir erro
            with lock:
                if state.get("login_token") == my_token:
                    push_event("login_error", message=f"Erro interno: {str(e)[:120]}")

    threading.Thread(target=_do_login, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    with lock:
        state["client"] = None
        state["username"] = None
        state["user_id"] = None
        state["logged_in"] = False
        state["session_type"] = None
        state["is_running"] = False
        state["running"] = False
        state["login_token"] = None  # Revoga o token: silencia qualquer thread de login ativa
        
    try:
        import os
        if os.path.exists("session.json"):
            os.remove("session.json")
            log("Sessao anterior removida do disco (session.json).", "info")
    except Exception as e:
        log(f"Erro ao remover session.json: {e}", "warning")

    return jsonify({"status": "success", "message": "Desconectado com sucesso."})

@app.route("/api/start", methods=["POST"])
def start_operation():
    if not state["logged_in"]:
        return jsonify({"error": "Nao autenticado"}), 401
    if state["is_running"]:
        return jsonify({"error": "Operacao em andamento"}), 409

    data = request.get_json() or {}
    mode = data.get("mode", "followers")

    def _do_preview():
        try:
            from core import obter_seguidores, obter_seguindo

            state["running"] = True
            state["is_running"] = True
            state["done"] = False
            state["progress_done"] = 0
            state["progress_total"] = 0

            cl = state["client"]
            user_id = state["user_id"]

            push_event("operation_started", mode=mode)
            seguidores = []
            seguindo = []

            if mode in ("followers", "both", "mutuals"):
                try:
                    log("Buscando lista de seguidores...")
                    seguidores = obter_seguidores(cl, user_id, verbose=False)
                    log(f"{len(seguidores)} seguidores encontrados.", "success")
                except Exception as e_seg:
                    log(f"Erro ao buscar seguidores: {e_seg}", "error")
                    push_event("preview_error", message=f"Falha ao buscar seguidores: {str(e_seg)[:200]}")
                    with lock:
                        state["is_running"] = False
                        state["running"] = False
                    return

            if mode in ("following", "both", "mutuals"):
                try:
                    push_event("log", message="Buscando lista de quem voce segue...")
                    seguindo = obter_seguindo(cl, int(user_id), verbose=False)
                    push_event("log", message=f"{len(seguindo)} contas encontradas.", level="success")
                except Exception as e_fol:
                    log(f"Erro ao buscar seguindo: {e_fol}", "error")
                    push_event("preview_error", message=f"Falha ao buscar contas seguidas: {str(e_fol)[:200]}")
                    with lock:
                        state["is_running"] = False
                        state["running"] = False
                    return

            vistos = set()
            unique = []

            if mode == "mutuals":
                seguindo_ids = {u["user_id"] for u in seguindo}
                for u in seguidores:
                    if u["user_id"] in seguindo_ids and u["user_id"] not in vistos:
                        vistos.add(u["user_id"])
                        unique.append(u)
            else:
                todas = seguidores + seguindo
                for u in todas:
                    if u["user_id"] not in vistos:
                        vistos.add(u["user_id"])
                        unique.append(u)

            push_event("log", message=f"{len(unique)} usuarios unicos a processar.", level="info")

            # ── Filtra quem já está nos Melhores Amigos (via API Direta Minimalista) ──
            try:
                import urllib.request
                import json
                
                push_event("log", message="Pesquisando quem ja esta nos Melhores Amigos no Instagram...", level="info")
                
                cookies_dict = {}
                try:
                    import os
                    if os.path.exists("session.json"):
                        with open("session.json", "r", encoding="utf-8") as f:
                            s_data = json.load(f)
                            cookies_dict = s_data.get("cookies", {})
                except Exception:
                    pass
                    
                sessionid = cookies_dict.get("sessionid", "")
                csrftoken = cookies_dict.get("csrftoken", "")
                
                if sessionid:
                    headers = {
                        "User-Agent": "Instagram 219.0.0.12.117 Android",
                        "Cookie": f"sessionid={sessionid}; csrftoken={csrftoken};",
                        "Accept": "*/*",
                        "X-IG-App-ID": "936619743392459",
                    }
                    
                    max_id = None
                    ja_adicionados = set()
                    
                    for page_num in range(50): # Limite de seguranca
                        url = "https://i.instagram.com/api/v1/friendships/besties/?source=audience_manager"
                        if max_id:
                            url += f"&max_id={max_id}"
                            
                        req = urllib.request.Request(url, headers=headers)
                        try:
                            resp = urllib.request.urlopen(req, timeout=10)
                            data = json.loads(resp.read().decode("utf-8"))
                            users = data.get("users", [])
                            for u in users:
                                ja_adicionados.add(str(u["pk"]))
                            max_id = data.get("next_max_id")
                            if not max_id:
                                break
                        except Exception as e_req:
                            push_event("log", message=f"Aviso na pagina {page_num+1} da lista de Melhores Amigos: {e_req}", level="warning")
                            break
                    
                    if ja_adicionados:
                        push_event("log", message=f"[DEBUG] IDs encontrados nos Melhores Amigos online: {list(ja_adicionados)[:5]}...", level="info")
                        antes = len(unique)
                        unique = [u for u in unique if str(u["user_id"]) not in ja_adicionados]
                        pulados = antes - len(unique)
                        if pulados > 0:
                            push_event("log",
                                message=f"{pulados} usuario(s) ja estao nos Melhores Amigos (pesquisa online) e serao pulados.",
                                level="success"
                            )
                        push_event("log",
                            message=f"{len(unique)} usuario(s) ainda precisam ser adicionados.",
                            level="info"
                        )
                    else:
                        push_event("log", message="Ninguem encontrado na sua lista de Melhores Amigos atual.", level="info")
                else:
                    push_event("log", message="Sessao nao encontrada. Nao foi possivel filtrar Melhores Amigos.", level="warning")
                    
            except Exception as e_cf:
                push_event("log",
                    message=f"Aviso: Falha ao consultar lista online ({str(e_cf)[:100]}).",
                    level="warning"
                )


            if len(unique) == 0:
                push_event("log", message="Nenhum usuario novo para adicionar. Todos ja sao Melhores Amigos ou a lista esta vazia.", level="warning")
                push_event("preview_ready", count=0)
                with lock:
                    state["pending_users"] = []
                    state["progress_total"] = 0
                    state["is_running"] = False
                return

            with lock:
                state["pending_users"] = unique
                state["progress_total"] = len(unique)
            
            # Envia o evento de preview_ready com o total encontrado
            push_event("preview_ready", count=len(unique))
            
            # Preview concluida, aguarda /api/confirm_start
            with lock:
                state["is_running"] = False
        except Exception as e:
            tb = traceback.format_exc()
            log(f"Erro fatal na preview: {e}", "error")
            push_event("preview_error", message=f"Erro inesperado: {str(e)[:200]}")
            with lock:
                state["is_running"] = False
                state["running"] = False

    threading.Thread(target=_do_preview, daemon=True).start()
    return jsonify({"status": "previewing"}), 200

@app.route("/api/confirm_start", methods=["POST"])
def api_confirm_start():
    data = request.get_json() or {}
    delay_min = int(data.get("delay_min", 40))
    delay_max = int(data.get("delay_max", 56))
    batch_size = int(data.get("batch_size", 1))
    
    batch_size = max(1, min(100, batch_size))

    # delay_min == 0 é o modo especial "lote único" — não aplica floor
    if delay_min == 0:
        delay_max = 0
    else:
        # Garante limites seguros para o modo individual
        delay_min = max(15, min(300, delay_min))
        delay_max = max(delay_min + 5, min(600, delay_max))

    def _do_addition():
        try:
            cl = _get_client()
            with lock:
                state["is_running"] = True
                unique = list(state.get("pending_users", []))
                total = len(unique)
                sess_type = state.get("session_type")

            push_event("operation_started", total=total)
            if delay_min == 0:
                push_event("log", message="Modo Lote Único — todos serão adicionados em uma única requisição.", level="info")
            else:
                push_event("log", message=f"Delay configurado: {delay_min}s–{delay_max}s entre cada usuário.", level="info")

            
            if total == 0:
                push_event("operation_done", done=0, total=0)
                return

            if sess_type == "web":
                push_event("log", message="Modo Web (Visual) detectado. Usando o robô invisível Playwright para evitar bloqueio do Instagram.", level="info")
                import playwright_adder
                
                def _push(ev_type, **kwargs):
                    push_event(ev_type, **kwargs)
                    
                def _set_prog(d):
                    with lock:
                        state["progress_done"] = d
                        
                def _check_running():
                    with lock:
                        return state.get("is_running", False)
                
                playwright_adder.adicionar_via_playwright(
                    unique, _push, _set_prog, _check_running,
                    delay_min=delay_min, delay_max=delay_max, batch_size=batch_size
                )
                
                with lock:
                    done = state["progress_done"]
                push_event("operation_done", done=done, total=total)
                return

            from core import BATCH_SIZE
            import random
            
            total_lotes = (total + BATCH_SIZE - 1) // BATCH_SIZE
            push_event("log", message=f"{total} usuarios em {total_lotes} lotes de {BATCH_SIZE}.")

            done = 0
            for i in range(0, total, BATCH_SIZE):
                lote = unique[i : i + BATCH_SIZE]
                num_lote = (i // BATCH_SIZE) + 1
                ids_lote = [u["user_id"] for u in lote]

                push_event("log", message=f"Lote {num_lote}/{total_lotes} ({len(lote)} usuarios)...", level="info")

                try:
                    # Implementacao direta do set_besties que falta no instagrapi nativo
                    data = {
                        "block_on_empty_thread_creation": "false",
                        "module": "CLOSE_FRIENDS_V2_SEARCH",
                        "source": "audience_manager",
                        "_uid": cl.user_id,
                        "_uuid": cl.uuid,
                        "remove": [],
                        "add": [str(uid) for uid in ids_lote],
                    }
                    cl.private_request("friendships/set_besties/", data)
                    done += len(lote)
                    with lock:
                        state["progress_done"] = done
                    push_event("progress", done=done, total=total)
                    push_event("log", message=f"Lote {num_lote} OK! ({done}/{total})", level="success")
                except Exception as e:
                    push_event("log", message=f"Erro no lote {num_lote}: {e}. Aguardando 2min...", level="warning")
                    time.sleep(120)
                    continue

                if i + BATCH_SIZE < total:
                    delay = random.randint(30, 90)
                    push_event("log", message=f"Aguardando {delay}s...", level="info")
                    for s in range(delay, 0, -1):
                        push_event("countdown", seconds=s)
                        time.sleep(1)

            push_event("log", message=f"Concluido! {done}/{total} adicionados aos Melhores Amigos.", level="success")
            push_event("operation_done", done=done, total=total)

        except Exception as e:
            tb = traceback.format_exc()
            push_event("log", message=f"Erro fatal: {e}", level="error")
            push_event("log", message=f"Traceback: {tb}", level="error")
        finally:
            with lock:
                state["is_running"] = False
                state["running"] = False
                state["done"] = True
                
    threading.Thread(target=_do_addition, daemon=True).start()
    return jsonify({"status": "starting"}), 200


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reset operation state (used when user cancels from preview)."""
    with lock:
        state["running"] = False
        state["is_running"] = False
        state["done"] = False
        state["progress_done"] = 0
        state["progress_total"] = 0
        state["pending_users"] = []
    return jsonify({"status": "reset"})


# ─────────────────────────────────────────────────────────────────────────────
# MONITOR DE NOVOS SEGUIDORES
# ─────────────────────────────────────────────────────────────────────────────

def _monitor_loop():
    """
    Loop em background que detecta novos seguidores periodicamente
    e os adiciona automaticamente aos Melhores Amigos.

    Usa concurrent.futures para garantir timeouts em operações bloqueantes
    (GQL fetch e Playwright), evitando travamentos do loop.
    """
    from core import obter_seguidores_ids, adicionar_usuario_bestie
    import datetime
    import concurrent.futures

    FETCH_TIMEOUT  = 90   # segundos — timeout para buscar seguidores via GQL
    ADD_TIMEOUT    = 120  # segundos — timeout para adicionar via Playwright
    HEARTBEAT_STEP = 30   # segundos — log de "ainda vivo" durante a espera

    # ── Helper: fetch com timeout ─────────────────────────────────────────────
    def _fetch_followers_safe():
        """Executa obter_seguidores_ids com timeout para não travar o loop."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(obter_seguidores_ids, cl, int(user_id))
            try:
                return future.result(timeout=FETCH_TIMEOUT)
            except concurrent.futures.TimeoutError:
                log(f"[Monitor] Timeout ({FETCH_TIMEOUT}s) ao buscar seguidores. Tentará novamente.", "warning")
                return {}
            except Exception as e_fetch:
                log(f"[Monitor] Erro ao buscar seguidores: {e_fetch}", "warning")
                return {}

    # ── Helper: adicionar com timeout ─────────────────────────────────────────
    def _add_bestie_safe(uid, uname, sess_type):
        """Adiciona um usuário com timeout, sem bloquear o loop principal."""
        def _do_add():
            if sess_type == "web":
                try:
                    from playwright_adder import adicionar_usuario_via_playwright
                    return adicionar_usuario_via_playwright(uid, uname, push_event, log)
                except Exception as e_pw:
                    log(f"[Monitor] Playwright falhou para @{uname}: {e_pw}", "error")
                    return False
            else:
                return adicionar_usuario_bestie(cl, uid)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_do_add)
            try:
                return future.result(timeout=ADD_TIMEOUT)
            except concurrent.futures.TimeoutError:
                log(f"[Monitor] Timeout ({ADD_TIMEOUT}s) ao adicionar @{uname}. Pulando.", "warning")
                return False
            except Exception as e_add:
                log(f"[Monitor] Erro inesperado ao adicionar @{uname}: {e_add}", "error")
                return False

    log("[Monitor] Loop iniciado. Fazendo snapshot inicial dos seguidores...", "info")

    cl      = state["client"]
    user_id = state["user_id"]

    # ── Snapshot inicial ──────────────────────────────────────────────────────
    initial_snapshot = _fetch_followers_safe()

    with lock:
        state["monitor_known_ids"] = initial_snapshot
        state["monitor_last_check"] = datetime.datetime.now().isoformat()

    total_inicial = len(initial_snapshot)
    log(f"[Monitor] Snapshot inicial: {total_inicial} seguidores. Monitorando novos...", "success")
    push_event("monitor_started", total_inicial=total_inicial)

    # ── Loop principal ────────────────────────────────────────────────────────
    while True:
        with lock:
            still_running = state["monitor_running"]
            interval      = state["monitor_interval"]

        if not still_running:
            break

        # ── Espera o intervalo com heartbeat a cada HEARTBEAT_STEP segundos ──
        elapsed = 0
        for _ in range(interval):
            with lock:
                still_running = state["monitor_running"]
            if not still_running:
                break

            time.sleep(1)
            elapsed += 1

            # Heartbeat periódico para confirmar que o loop está vivo
            if elapsed % HEARTBEAT_STEP == 0:
                remaining = interval - elapsed
                log(f"[Monitor] Aguardando próximo ciclo... {remaining}s restantes.", "info")

        # Verifica novamente após o sleep
        with lock:
            still_running = state["monitor_running"]
        if not still_running:
            break

        # ── Ciclo de verificação ─────────────────────────────────────────────
        try:
            with lock:
                cycle_num = state["monitor_cycle_count"] + 1
                state["monitor_cycle_count"] = cycle_num

            log(f"[Monitor] Ciclo #{cycle_num} — verificando novos seguidores...", "info")
            push_event("monitor_checking", cycle=cycle_num)

            current_snapshot = _fetch_followers_safe()

            if not current_snapshot:
                log("[Monitor] Fetch retornou vazio. Tentará novamente no próximo ciclo.", "warning")
                push_event("monitor_cycle_done",
                           cycle=cycle_num, new_count=0, error=True,
                           total_added=state.get("monitor_added_count", 0),
                           last_check=datetime.datetime.now().isoformat())
                continue

            with lock:
                known = state["monitor_known_ids"] or {}
                sess_type = state.get("session_type", "mobile")

            # IDs novos: estão no snapshot atual mas não no anterior
            new_ids = {uid: uname for uid, uname in current_snapshot.items()
                       if uid not in known}

            if new_ids:
                log(f"[Monitor] {len(new_ids)} novo(s) seguidor(es) detectado(s)!", "success")
                added = 0

                for uid, uname in new_ids.items():
                    ok = _add_bestie_safe(uid, uname, sess_type)

                    status_level = "success" if ok else "warning"
                    msg = f"[Monitor] @{uname} {'adicionado aos Melhores Amigos ✓' if ok else 'falhou ao adicionar'}"
                    log(msg, status_level)
                    push_event("monitor_new_follower",
                               user_id=uid, username=uname, added=ok)
                    if ok:
                        added += 1
                    time.sleep(random.uniform(1, 3))  # delay leve anti-spam

                with lock:
                    state["monitor_added_count"] += added
                    state["monitor_known_ids"] = current_snapshot
            else:
                log(f"[Monitor] Nenhum seguidor novo neste ciclo.", "info")
                with lock:
                    state["monitor_known_ids"] = current_snapshot

            now_iso = datetime.datetime.now().isoformat()
            with lock:
                state["monitor_last_check"] = now_iso
                total_added = state["monitor_added_count"]

            push_event("monitor_cycle_done",
                       cycle=cycle_num,
                       new_count=len(new_ids),
                       total_added=total_added,
                       last_check=now_iso)

        except Exception as e:
            tb = traceback.format_exc()
            log(f"[Monitor] Erro no ciclo #{cycle_num}: {e}", "error")
            log(f"[Monitor] Traceback: {tb}", "error")
            push_event("monitor_error", message=str(e))
            # Emite cycle_done mesmo em caso de erro para o frontend não ficar preso
            push_event("monitor_cycle_done",
                       cycle=cycle_num, new_count=0, error=True,
                       total_added=state.get("monitor_added_count", 0),
                       last_check=datetime.datetime.now().isoformat())

    log("[Monitor] Monitor encerrado.", "info")
    push_event("monitor_stopped")
    with lock:
        state["monitor_running"] = False


@app.route("/api/monitor/start", methods=["POST"])
def api_monitor_start():
    """Inicia o monitor de novos seguidores."""
    if not state["logged_in"]:
        return jsonify({"error": "Nao autenticado"}), 401
    if state["monitor_running"]:
        return jsonify({"error": "Monitor ja esta ativo"}), 409

    data = request.get_json() or {}
    interval_min = max(2, min(60, int(data.get("interval_min", 5))))

    with lock:
        state["monitor_running"] = True
        state["monitor_interval"] = interval_min * 60
        state["monitor_added_count"] = 0
        state["monitor_known_ids"] = None
        state["monitor_last_check"] = None
        state["monitor_cycle_count"] = 0

    threading.Thread(target=_monitor_loop, daemon=True).start()
    return jsonify({"status": "started", "interval_min": interval_min})


@app.route("/api/monitor/stop", methods=["POST"])
def api_monitor_stop():
    """Para o monitor de novos seguidores."""
    with lock:
        state["monitor_running"] = False
    return jsonify({"status": "stopping"})


@app.route("/api/monitor/status", methods=["GET"])
def api_monitor_status():
    """Retorna o status atual do monitor."""
    with lock:
        return jsonify({
            "running": state["monitor_running"],
            "interval_sec": state["monitor_interval"],
            "added_count": state["monitor_added_count"],
            "last_check": state["monitor_last_check"],
            "cycle_count": state["monitor_cycle_count"],
        })


# ─────────────────────────────────────────────────────────────────────────────
# MONITOR DE NOVOS SEGUINDO
# ─────────────────────────────────────────────────────────────────────────────

def _monitor_following_loop():
    """
    Loop em background que detecta quando o usuário começa a seguir alguém
    e adiciona essa pessoa automaticamente aos Melhores Amigos.

    Usa concurrent.futures para garantir timeouts em operações bloqueantes.
    """
    from core import obter_seguindo_ids, adicionar_usuario_bestie
    import datetime
    import concurrent.futures

    FETCH_TIMEOUT  = 90
    ADD_TIMEOUT    = 120
    HEARTBEAT_STEP = 30

    def _fetch_following_safe():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(obter_seguindo_ids, cl, int(user_id))
            try:
                return future.result(timeout=FETCH_TIMEOUT)
            except concurrent.futures.TimeoutError:
                log(f"[Monitor Seguindo] Timeout ({FETCH_TIMEOUT}s) ao buscar seguindo.", "warning")
                return {}
            except Exception as e_f:
                log(f"[Monitor Seguindo] Erro ao buscar seguindo: {e_f}", "warning")
                return {}

    def _add_bestie_safe(uid, uname, sess_type):
        def _do_add():
            if sess_type == "web":
                try:
                    from playwright_adder import adicionar_usuario_via_playwright
                    return adicionar_usuario_via_playwright(uid, uname, push_event, log)
                except Exception as e_pw:
                    log(f"[Monitor Seguindo] Playwright falhou para @{uname}: {e_pw}", "error")
                    return False
            else:
                return adicionar_usuario_bestie(cl, uid)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_do_add)
            try:
                return future.result(timeout=ADD_TIMEOUT)
            except concurrent.futures.TimeoutError:
                log(f"[Monitor Seguindo] Timeout ({ADD_TIMEOUT}s) ao adicionar @{uname}.", "warning")
                return False
            except Exception as e_add:
                log(f"[Monitor Seguindo] Erro inesperado ao adicionar @{uname}: {e_add}", "error")
                return False

    log("[Monitor Seguindo] Loop iniciado. Fazendo snapshot inicial de seguindo...", "info")

    cl      = state["client"]
    user_id = state["user_id"]

    # Snapshot inicial
    initial_snapshot = _fetch_following_safe()

    with lock:
        state["mf_known_ids"]   = initial_snapshot
        state["mf_last_check"]  = datetime.datetime.now().isoformat()

    total_inicial = len(initial_snapshot)
    log(f"[Monitor Seguindo] Snapshot inicial: {total_inicial} contas seguidas. Monitorando novos...", "success")
    push_event("mf_started", total_inicial=total_inicial)

    while True:
        with lock:
            still_running = state["mf_running"]
            interval      = state["mf_interval"]

        if not still_running:
            break

        elapsed = 0
        for _ in range(interval):
            with lock:
                still_running = state["mf_running"]
            if not still_running:
                break
            time.sleep(1)
            elapsed += 1
            if elapsed % HEARTBEAT_STEP == 0:
                remaining = interval - elapsed
                log(f"[Monitor Seguindo] Aguardando próximo ciclo... {remaining}s restantes.", "info")

        with lock:
            still_running = state["mf_running"]
        if not still_running:
            break

        try:
            with lock:
                cycle_num = state["mf_cycle_count"] + 1
                state["mf_cycle_count"] = cycle_num

            log(f"[Monitor Seguindo] Ciclo #{cycle_num} — verificando novas contas seguidas...", "info")
            push_event("mf_checking", cycle=cycle_num)

            current_snapshot = _fetch_following_safe()

            if not current_snapshot:
                log("[Monitor Seguindo] Fetch retornou vazio. Tentando novamente.", "warning")
                push_event("mf_cycle_done",
                           cycle=cycle_num, new_count=0, error=True,
                           total_added=state.get("mf_added_count", 0),
                           last_check=datetime.datetime.now().isoformat())
                continue

            with lock:
                known     = state["mf_known_ids"] or {}
                sess_type = state.get("session_type", "mobile")

            new_ids = {uid: uname for uid, uname in current_snapshot.items()
                       if uid not in known}

            if new_ids:
                log(f"[Monitor Seguindo] {len(new_ids)} nova(s) conta(s) seguidas detectadas!", "success")
                added = 0

                for uid, uname in new_ids.items():
                    ok = _add_bestie_safe(uid, uname, sess_type)

                    status_level = "success" if ok else "warning"
                    msg = f"[Monitor Seguindo] @{uname} {'adicionado aos Melhores Amigos ✓' if ok else 'falhou ao adicionar'}"
                    log(msg, status_level)
                    push_event("mf_new_following",
                               user_id=uid, username=uname, added=ok)
                    if ok:
                        added += 1
                    time.sleep(random.uniform(1, 3))

                with lock:
                    state["mf_added_count"] += added
                    state["mf_known_ids"]    = current_snapshot
            else:
                log("[Monitor Seguindo] Nenhuma conta nova seguida neste ciclo.", "info")
                with lock:
                    state["mf_known_ids"] = current_snapshot

            now_iso = datetime.datetime.now().isoformat()
            with lock:
                state["mf_last_check"] = now_iso
                total_added = state["mf_added_count"]

            push_event("mf_cycle_done",
                       cycle=cycle_num,
                       new_count=len(new_ids),
                       total_added=total_added,
                       last_check=now_iso)

        except Exception as e:
            tb = traceback.format_exc()
            log(f"[Monitor Seguindo] Erro no ciclo #{cycle_num}: {e}", "error")
            log(f"[Monitor Seguindo] Traceback: {tb}", "error")
            push_event("mf_error", message=str(e))
            push_event("mf_cycle_done",
                       cycle=cycle_num, new_count=0, error=True,
                       total_added=state.get("mf_added_count", 0),
                       last_check=datetime.datetime.now().isoformat())

    log("[Monitor Seguindo] Monitor encerrado.", "info")
    push_event("mf_stopped")
    with lock:
        state["mf_running"] = False


@app.route("/api/monitor/following/start", methods=["POST"])
def api_mf_start():
    """Inicia o monitor de novos seguindo."""
    if not state["logged_in"]:
        return jsonify({"error": "Nao autenticado"}), 401
    if state["mf_running"]:
        return jsonify({"error": "Monitor de seguindo ja esta ativo"}), 409

    data = request.get_json() or {}
    interval_min = max(2, min(60, int(data.get("interval_min", 5))))

    with lock:
        state["mf_running"]       = True
        state["mf_interval"]      = interval_min * 60
        state["mf_added_count"]   = 0
        state["mf_known_ids"]     = None
        state["mf_last_check"]    = None
        state["mf_cycle_count"]   = 0

    threading.Thread(target=_monitor_following_loop, daemon=True).start()
    return jsonify({"status": "started", "interval_min": interval_min})


@app.route("/api/monitor/following/stop", methods=["POST"])
def api_mf_stop():
    """Para o monitor de novos seguindo."""
    with lock:
        state["mf_running"] = False
    return jsonify({"status": "stopping"})


@app.route("/api/monitor/following/status", methods=["GET"])
def api_mf_status():
    """Retorna o status atual do monitor de seguindo."""
    with lock:
        return jsonify({
            "running":      state["mf_running"],
            "interval_sec": state["mf_interval"],
            "added_count":  state["mf_added_count"],
            "last_check":   state["mf_last_check"],
            "cycle_count":  state["mf_cycle_count"],
        })


@app.route("/api/events")
def sse_events():
    def stream():
        while True:
            try:
                event = event_queue.get(timeout=25)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
