# 📖 Bot de Melhores Amigos do Instagram

Ferramenta em Python para adicionar automaticamente seus **Seguidores** ou as pessoas que **você segue** à sua lista de **Melhores Amigos** (Close Friends) do Instagram.

---

## ⚠️ Aviso Importante

> O Instagram detecta automação. Use com cuidado e responsabilidade. Adicionar muitas pessoas de forma muito rápida pode resultar em bloqueios temporários. O bot já possui delays automáticos para minimizar este risco.

---

## 🛠️ Pré-requisitos

- Python 3.9+
- Acesso à internet

---

## 🚀 Instalação

### 1. Clone ou baixe o projeto
Baixe os arquivos para uma pasta no seu computador.

### 2. Ative o ambiente virtual
No terminal, dentro da pasta do projeto:

**Windows:**
```bash
venv\Scripts\activate
```

**Linux/macOS:**
```bash
source venv/bin/activate
```

### 3. Instale as dependências (já instaladas se você seguiu o setup)
```bash
pip install -r requirements.txt
```

### 4. Configure suas credenciais

## ▶️ Como usar

Com o ambiente virtual ativado, execute:
```bash
python main.py
```

O menu interativo será exibido:
```
============================================================
  ★  BOT DE MELHORES AMIGOS DO INSTAGRAM  ★
============================================================

  [1] 👥 Adicionar meus SEGUIDORES aos Melhores Amigos
  [2] 💚 Adicionar quem EU SIGO aos Melhores Amigos
  [3] 🔄 Ambos (seguidores + quem eu sigo)
  [4] 🚪 Sair
```

Escolha uma opção e confirme. O bot irá:
1. Buscar a lista de usuários.
2. Exibir uma prévia.
3. Aguardar sua confirmação.
4. Adicionar em lotes com delays automáticos.

---

## 🔒 Segurança

- Suas credenciais são armazenadas apenas no arquivo `.env` local.
- O bot salva uma sessão em `session.json` para evitar logins repetidos (que são mais suspeitos para o Instagram).
- **Nunca compartilhe os arquivos `.env` e `session.json`.**

---

## 📁 Estrutura do Projeto

```
📂 projeto/
├── main.py           # Ponto de entrada (execute este)
├── core.py           # Lógica de API do Instagram
├── .env              # Suas credenciais (NÃO compartilhe)
├── .env.example      # Template de credenciais
├── requirements.txt  # Dependências
├── session.json      # Sessão salva (gerado automaticamente)
└── README.md         # Este arquivo
```
