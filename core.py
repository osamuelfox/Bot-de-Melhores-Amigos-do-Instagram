"""
core.py - Módulo principal para automação do Instagram (Melhores Amigos)
Utiliza a biblioteca instagrapi para interagir com a API privada do Instagram.
"""

import json
import os
import time
import random
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    TwoFactorRequired,
    ChallengeRequired,
    BadPassword,
    UserNotFound,
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SESSION_FILE = "session.json"
BATCH_SIZE = 50  # Quantidade de usuários por lote


def criar_cliente() -> Client:
    """Cria e retorna uma instância configurada do cliente instagrapi."""
    cl = Client()
    cl.delay_range = [2, 5]
    return cl


def login_por_sessao(sessionid: str, cookies_raw: list = None) -> Client:
    """
    Autentica o instagrapi usando cookies extraidos do Chrome via Playwright.

    Estrategia:
      1. Injeta todos os cookies do browser via set_settings (inclui sessionid, ds_user_id, csrftoken...)
      2. Extrai o user_id do cookie ds_user_id (evita chamada a API mobile que retorna 467)
      3. Valida a sessao via user_short_gql (GraphQL publico, mais permissivo que a API mobile)

    Args:
        sessionid: Valor do cookie 'sessionid' extraido do Chrome.
        cookies_raw: Lista completa de cookies do contexto Playwright (opcional).

    Retorna o cliente autenticado ou None em caso de falha.
    """
    cl = criar_cliente()
    try:
        # Monta dict de cookies a partir dos dados brutos do Playwright
        cookie_dict = {"sessionid": sessionid}
        user_id_str = None

        if cookies_raw:
            for c in cookies_raw:
                name = c.get("name", "")
                value = c.get("value", "")
                if value:
                    cookie_dict[name] = value
                if name == "ds_user_id":
                    user_id_str = value

        # Se nao encontrou ds_user_id nos cookies, tenta extrair do sessionid
        # (formato antigo: "USER_ID:..." - nem sempre presente)
        if not user_id_str:
            import re
            match = re.match(r"^(\d+)", sessionid)
            if match:
                user_id_str = match.group(1)

        print(f"[INFO] Injetando {len(cookie_dict)} cookies na sessao instagrapi...")
        print(f"[INFO] user_id encontrado: {user_id_str}")

        # Injeta os cookies via set_settings
        cl.set_settings({"cookies": cookie_dict})

        # Injeta tambem na sessao requests diretamente
        cl.private.cookies.update(cookie_dict)
        cl.public.cookies.update(cookie_dict)

        if user_id_str:
            try:
                user_id_int = int(user_id_str)
                cl.user_id = user_id_int

                # Valida via GraphQL (publico, nao usa API mobile que retorna 467)
                user = cl.user_short_gql(user_id_int)
                cl.username = user.username
                print(f"[OK] Login confirmado como @{user.username} (id={user_id_int})")
                cl.dump_settings(SESSION_FILE)
                return cl
            except Exception as e:
                print(f"[AVISO] user_short_gql falhou: {e}. Tentando account_info...")

        # Fallback: tenta via account_info
        try:
            info = cl.account_info()
            cl.user_id = info.pk
            cl.username = info.username
            print(f"[OK] Login confirmado como @{info.username}")
            cl.dump_settings(SESSION_FILE)
            return cl
        except Exception as e2:
            print(f"[ERRO] Falha ao confirmar login: {e2}")
            return None

    except Exception as e:
        print(f"[ERRO] Falha ao configurar sessao: {e}")
        return None


def login(username: str, password: str, codigo_2fa: str = None) -> Client:
    """
    Realiza login no Instagram de forma segura.
    - Tenta reutilizar sessão salva para reduzir o risco de bloqueio.
    - Suporta autenticação de 2 fatores (2FA).

    Retorna o cliente autenticado ou None em caso de falha.
    """
    cl = criar_cliente()

    # Tenta carregar sessão existente
    if Path(SESSION_FILE).exists():
        print("🔄 Sessão anterior encontrada. Tentando reutilizar...")
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(username, password)
            cl.get_timeline_feed()  # Verifica se a sessão ainda é válida
            print("✅ Sessão reutilizada com sucesso!")
            return cl
        except LoginRequired:
            print("⚠️  Sessão expirada. Fazendo login completo...")
        except Exception as e:
            print(f"⚠️  Erro ao reutilizar sessão: {e}. Fazendo login completo...")

    # Login completo
    print("🔑 Realizando login completo...")
    try:
        if codigo_2fa:
            cl.login(username, password, verification_code=codigo_2fa)
        else:
            cl.login(username, password)

        # Salva a nova sessão
        cl.dump_settings(SESSION_FILE)
        print(f"✅ Login realizado! Sessão salva em '{SESSION_FILE}'.")
        return cl

    except TwoFactorRequired:
        print("\n📱 Sua conta tem verificação em 2 etapas ativada.")
        codigo = input("   Digite o código de 6 dígitos do seu aplicativo autenticador: ").strip()
        try:
            cl.login(username, password, verification_code=codigo)
            cl.dump_settings(SESSION_FILE)
            print(f"✅ Login com 2FA realizado! Sessão salva em '{SESSION_FILE}'.")
            return cl
        except Exception as e:
            print(f"❌ Falha no login com 2FA: {e}")
            return None

    except ChallengeRequired:
        print("⚠️  O Instagram pediu um desafio de verificação (ex: confirmar e-mail/SMS).")
        print("   Por favor, abra o Instagram no seu celular, conclua a verificação e tente novamente.")
        return None

    except BadPassword:
        print("❌ Usuário ou senha incorretos.")
        return None

    except Exception as e:
        print(f"❌ Erro inesperado no login: {e}")
        return None


def obter_seguidores(cl: Client, user_id: int, verbose: bool = True) -> list:
    """
    Busca todos os seguidores da conta autenticada.
    Retorna uma lista de dicionários com {user_id, username}.
    """
    if verbose:
        print(f"\n📥 Buscando lista de seguidores...")

    try:
        seguidores = cl.user_followers_gql(user_id, amount=0)
        lista = [{"user_id": str(u.pk), "username": u.username} for u in seguidores]
        if verbose:
            print(f"   ✅ {len(lista)} seguidores encontrados.")
        return lista
    except Exception as e:
        print(f"❌ Erro ao buscar seguidores: {e}")
        return []


def obter_seguindo(cl: Client, user_id: int, verbose: bool = True) -> list:
    """
    Busca todas as contas que o usuário autenticado segue.
    Retorna uma lista de dicionários com {user_id, username}.
    """
    if verbose:
        print(f"\n📤 Buscando lista de quem você segue...")

    try:
        seguindo = cl.user_following_gql(user_id, amount=0)
        lista = [{"user_id": str(u.pk), "username": u.username} for u in seguindo]
        if verbose:
            print(f"   ✅ {len(lista)} contas que você segue encontradas.")
        return lista
    except Exception as e:
        print(f"❌ Erro ao buscar seguindo: {e}")
        return []


def adicionar_melhores_amigos(cl: Client, usuarios: list, delay_min: int = 30, delay_max: int = 90) -> bool:
    """
    Adiciona uma lista de usuários aos Melhores Amigos (Close Friends).
    Processa em lotes de BATCH_SIZE com delay aleatório entre cada lote.

    Args:
        cl: Cliente autenticado do instagrapi.
        usuarios: Lista de dicts com {user_id, username}.
        delay_min: Delay mínimo em segundos entre lotes.
        delay_max: Delay máximo em segundos entre lotes.

    Retorna True se concluído sem erros críticos, False caso contrário.
    """
    if not usuarios:
        print("⚠️  Lista de usuários vazia. Nenhuma ação realizada.")
        return False

    total = len(usuarios)
    total_lotes = (total + BATCH_SIZE - 1) // BATCH_SIZE
    sucesso_total = 0

    print(f"\n🚀 Iniciando adição de {total} usuários aos Melhores Amigos...")
    print(f"   Serão {total_lotes} lotes de até {BATCH_SIZE} usuários.")
    print(f"   Delays entre lotes: {delay_min}s a {delay_max}s.\n")

    for i in range(0, total, BATCH_SIZE):
        lote = usuarios[i : i + BATCH_SIZE]
        num_lote = (i // BATCH_SIZE) + 1
        ids_lote = [u["user_id"] for u in lote]

        print(f"📦 Lote {num_lote}/{total_lotes} — {len(lote)} usuário(s)...")

        try:
            # A API do Instagram espera uma lista de IDs como strings ou inteiros
            cl.close_friends_set(ids_lote)
            sucesso_total += len(lote)
            print(f"   ✅ Lote {num_lote} adicionado com sucesso! ({sucesso_total}/{total} no total)")

        except Exception as e:
            print(f"   ❌ Erro no lote {num_lote}: {e}")
            print("   ⚠️  Aguardando mais tempo antes de continuar...")
            time.sleep(random.randint(120, 180))
            continue

        # Delay entre lotes (exceto no último)
        if i + BATCH_SIZE < total:
            delay = random.randint(delay_min, delay_max)
            print(f"   ⏳ Aguardando {delay} segundos antes do próximo lote...")
            time.sleep(delay)

    print(f"\n🏁 Concluído! {sucesso_total}/{total} usuários processados com sucesso.")
    return sucesso_total == total


def obter_id_proprio(cl: Client) -> int:
    """Retorna o user_id do usuário autenticado."""
    return cl.user_id


def adicionar_usuario_bestie(cl: Client, user_id: str) -> bool:
    """
    Adiciona um único usuário à lista de Melhores Amigos (Close Friends).

    Usa a mesma endpoint privada que o processamento em lote, mas com apenas
    um usuário. Ideal para o monitor de novos seguidores.

    Args:
        cl: Cliente autenticado do instagrapi.
        user_id: ID do usuário a adicionar (string ou int).

    Retorna True em caso de sucesso, False em caso de erro.
    """
    try:
        data = {
            "block_on_empty_thread_creation": "false",
            "module": "CLOSE_FRIENDS_V2_SEARCH",
            "source": "audience_manager",
            "_uid": cl.user_id,
            "_uuid": cl.uuid,
            "remove": [],
            "add": [str(user_id)],
        }
        cl.private_request("friendships/set_besties/", data)
        return True
    except Exception as e:
        print(f"[ERRO] Falha ao adicionar {user_id} aos Melhores Amigos: {e}")
        return False


def obter_seguidores_ids(cl: Client, user_id: int) -> set:
    """
    Busca todos os seguidores e retorna apenas um set de IDs (strings).
    Otimizado para comparação rápida em ciclos de monitoramento.

    Args:
        cl: Cliente autenticado do instagrapi.
        user_id: ID do usuário autenticado.

    Retorna dict {user_id: username}, ou dict vazio em caso de erro.
    """
    try:
        seguidores = cl.user_followers_gql(user_id, amount=0)
        return {str(u.pk): u.username for u in seguidores}
    except Exception as e:
        print(f"[ERRO] Falha ao buscar seguidores para monitor: {e}")
        return {}


def obter_seguindo_ids(cl: Client, user_id: int) -> dict:
    """
    Busca todas as contas que o usuário segue e retorna um dict {user_id: username}.
    Otimizado para comparação rápida em ciclos do monitor de seguindo.

    Args:
        cl: Cliente autenticado do instagrapi.
        user_id: ID do usuário autenticado.

    Retorna dict {user_id: username}, ou dict vazio em caso de erro.
    """
    try:
        seguindo = cl.user_following_gql(user_id, amount=0)
        return {str(u.pk): u.username for u in seguindo}
    except Exception as e:
        print(f"[ERRO] Falha ao buscar seguindo para monitor: {e}")
        return {}

