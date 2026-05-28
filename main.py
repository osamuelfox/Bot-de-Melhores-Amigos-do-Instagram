"""
main.py - Launcher do Bot de Melhores Amigos do Instagram.
Inicia o servidor Flask e abre a interface no navegador automaticamente.
"""

import threading
import webbrowser
import time
import sys
import os

PORT = 5000


def open_browser():
    """Aguarda o servidor iniciar e abre o navegador."""
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    # Instala os navegadores do Playwright se ainda não foram instalados
    playwright_browsers_path = os.path.join(
        os.path.dirname(sys.executable), "..", "playwright", "driver"
    )
    
    from app import app

    print("=" * 55)
    print("  MELHORES AMIGOS DO INSTAGRAM -- Interface Web")
    print("=" * 55)
    print(f"\n  >> Servidor iniciado em: http://localhost:{PORT}")
    print("  >> Abrindo no navegador automaticamente...")
    print("  >> Para parar: pressione Ctrl+C\n")

    # Abre o navegador em uma thread separada
    threading.Thread(target=open_browser, daemon=True).start()

    # Inicia o Flask (bloqueante)
    try:
        app.run(
            host="localhost",
            port=PORT,
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    except KeyboardInterrupt:
        print("\n\n  👋 Servidor encerrado. Até a próxima!\n")


if __name__ == "__main__":
    main()
