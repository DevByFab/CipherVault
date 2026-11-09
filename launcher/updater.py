import os
import sys
import json
import shutil
import zipfile
import logging
import argparse
import requests
from pathlib import Path
from packaging import version

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format="[UPDATER] %(message)s")
logger = logging.getLogger("updater")

# Configuração do Repositório
REPO_OWNER = "DevByFab"
REPO_NAME = "CipherVault"
BRANCH = "main"
RAW_BASE_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}"
ZIP_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{BRANCH}.zip"

# Caminhos Locais
BASE_DIR = Path(__file__).parent.parent.resolve()  # Raiz do projeto
SRC_DIR = BASE_DIR / "src"
VERSION_FILE = SRC_DIR / "ciphervault" / "__init__.py"

def get_local_version():
    """Lê a versão local do ficheiro __init__.py"""
    if not VERSION_FILE.exists():
        return "0.0.0"
    
    try:
        content = VERSION_FILE.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("__version__"):
                # Extrai "1.6.0" de __version__ = "1.6.0"
                # Remove comentários e aspas
                return line.split("=")[1].split("#")[0].strip().strip('"').strip("'")
    except Exception as e:
        logger.error(f"Erro ao ler versão local: {e}")
        return "0.0.0"
    return "0.0.0"

import time
import random

def get_remote_version():
    """Obtém a versão remota do GitHub"""
    # Adiciona timestamp para evitar cache do GitHub Raw
    url = f"{RAW_BASE_URL}/src/ciphervault/__init__.py?t={int(time.time())}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            for line in response.text.splitlines():
                if line.startswith("__version__"):
                    # Remove comentários e aspas
                    return line.split("=")[1].split("#")[0].strip().strip('"').strip("'")
    except Exception as e:
        logger.warning(f"Não foi possível verificar atualizações: {e}")
    return None

def download_and_update():
    """Baixa o código novo e substitui a pasta src/"""
    logger.info("A iniciar atualização...")
    
    temp_zip = BASE_DIR / "update_temp.zip"
    temp_extract = BASE_DIR / "update_temp_dir"
    
    try:
        # 1. Download
        logger.info(f"A descarregar de: {ZIP_URL}")
        r = requests.get(ZIP_URL, stream=True)
        with open(temp_zip, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # 2. Extração
        logger.info("A extrair ficheiros...")
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(temp_extract)
        
        # A estrutura do zip do GitHub é geralmente Reponame-branch/src/...
        # Vamos encontrar a pasta 'src' dentro do extraído
        extracted_root = list(temp_extract.glob("*"))[0] # Ex: CipherVault-main
        new_src = extracted_root / "src"
        
        if not new_src.exists():
            raise Exception("Estrutura de atualização inválida (pasta src não encontrada no zip)")

        # 3. Swap (Troca)
        logger.info("A aplicar atualização...")
        
        # Atualizar src/
        if SRC_DIR.exists():
            shutil.rmtree(SRC_DIR)
        shutil.move(str(new_src), str(SRC_DIR))
        logger.info("Código fonte (src) atualizado.")

        # Atualizar launcher/
        new_launcher = extracted_root / "launcher"
        local_launcher = BASE_DIR / "launcher"
        if new_launcher.exists():
            # Nota: Atualizar o launcher enquanto ele corre pode ser arriscado, 
            # mas como é um script interpretado carregado em memória, geralmente funciona no Windows 
            # se não estivermos a substituir o próprio python.exe.
            # Vamos tentar copiar ficheiro a ficheiro para evitar bloquear a pasta.
            if not local_launcher.exists():
                local_launcher.mkdir()
            
            for item in new_launcher.glob("*"):
                dst = local_launcher / item.name
                try:
                    if item.is_dir():
                        if dst.exists(): shutil.rmtree(dst)
                        shutil.copytree(item, dst)
                    else:
                        shutil.copy2(item, dst)
                except Exception as e:
                    logger.warning(f"Não foi possível atualizar {item.name}: {e}")
            logger.info("Launcher atualizado.")

        # Atualizar Documentação e outros ficheiros raiz
        for file_name in ["README.md", "DOCUMENTACAO.md", "requirements.txt", "ciphervault.cmd"]:
            src_file = extracted_root / file_name
            dst_file = BASE_DIR / file_name
            if src_file.exists():
                try:
                    shutil.copy2(src_file, dst_file)
                    logger.info(f"{file_name} atualizado.")
                except Exception as e:
                    logger.warning(f"Erro ao atualizar {file_name}: {e}")
        
        # Atualizar requirements.txt se existir novo (já tratado acima, mas mantendo lógica de limpeza)
        # Limpeza


        logger.info("Atualização concluída com sucesso!")
        return True

    except Exception as e:
        logger.error(f"Falha na atualização: {e}")
        return False
    finally:
        # Limpeza
        if temp_zip.exists(): os.remove(temp_zip)
        if temp_extract.exists(): shutil.rmtree(temp_extract)

def check_for_update() -> tuple[bool, str, str | None]:
    """Verifica se existe uma versão mais recente no repositório remoto.

    Retorna (update_disponivel, versao_local, versao_remota_ou_None).
    Reutilizável tanto pelo launcher CLI/GUI como pelo botão "Verificar
    atualizações" dentro da própria aplicação gráfica.
    """
    local_v = get_local_version()
    remote_v = get_remote_version()
    if remote_v and version.parse(remote_v) > version.parse(local_v):
        return True, local_v, remote_v
    return False, local_v, remote_v


def apply_update() -> tuple[bool, str]:
    """Aplica a atualização (com nova verificação de segurança antes de substituir ficheiros).

    Retorna (sucesso, mensagem).
    """
    local_v = get_local_version()
    remote_v = get_remote_version()
    if remote_v and version.parse(local_v) >= version.parse(remote_v):
        msg = f"A versão local ({local_v}) é igual ou superior à remota ({remote_v}). Atualização abortada."
        logger.warning(msg)
        return False, msg
    success = download_and_update()
    if success:
        return True, f"Atualizado de {local_v} para {remote_v or get_local_version()}."
    return False, "Falha ao aplicar a atualização. Consulte os registos para mais detalhes."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true", help="Apenas verifica se há atualização")
    parser.add_argument("--perform-update", action="store_true", help="Executa a atualização")
    args = parser.parse_args()

    if args.check_only:
        has_update, local_v, remote_v = check_for_update()
        if has_update:
            logger.info(f"Nova versão disponível: {remote_v} (Local: {local_v})")
            sys.exit(1)  # Código 1 indica que há update
        else:
            logger.info(f"O sistema está atualizado (v{local_v}).")
            sys.exit(0)

    if args.perform_update:
        success, msg = apply_update()
        logger.info(msg)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
