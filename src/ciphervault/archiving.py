import shutil
import tempfile
import zipfile
from pathlib import Path

# =============================================================
# Módulo archiving
# -------------------------------------------------------------
# Permite cifrar pastas sem alterar o formato .cvault ou as funções
# de cifragem existentes (encrypt_file / encrypt_for_contact): a pasta
# é comprimida para um .zip temporário, que depois passa pelo mesmo
# caminho de código usado para qualquer outro ficheiro.
# =============================================================


def zip_folder(folder: Path) -> Path:
    """Comprime uma pasta para um .zip temporário (nome preservado).

    O chamador é responsável por limpar o resultado com `cleanup_temp_zip`
    depois de terminar a cifragem.
    """
    folder = Path(folder)
    tmp_dir = Path(tempfile.mkdtemp(prefix="ciphervault_"))
    zip_path = tmp_dir / f"{folder.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in folder.rglob("*"):
            if file.is_file():
                zf.write(file, arcname=str(Path(folder.name) / file.relative_to(folder)))
    return zip_path


def cleanup_temp_zip(zip_path: Path) -> None:
    """Remove o diretório temporário criado por `zip_folder`."""
    shutil.rmtree(Path(zip_path).parent, ignore_errors=True)
