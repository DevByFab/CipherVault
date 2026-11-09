import sys
import logging
import json
import hashlib
from contextlib import contextmanager
from pathlib import Path

import click
from cryptography.hazmat.primitives import serialization
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.theme import Theme

from .crypto import KeyStore, SelfEncryptor
from .contacts import ContactsStore
from .archiving import zip_folder, cleanup_temp_zip
from . import __version__

# =============================================================
# Módulo cli
# -------------------------------------------------------------
# Fornece:
#   - Grupo principal click com --debug e --version
#   - Modo interativo persistente (menu loop) para operações simples
#   - Comandos não interativos: encrypt, encrypt-for-contact, decrypt, keys, public-key, export-public-key, verify, contacts-(list|add|delete)
#   - Funções auxiliares para validação de caminhos e visualização de chaves
#
# Notas de Segurança:
#   - Expor a chave privada só deve ser feito conscientemente; acrescentado
#     painel de aviso e confirmação explícita.
#   - Chave pública é segura para divulgação / embutida no contentor.
# =============================================================

# Tema "Violet LED"
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "success": "bold green",
    "header": "bold #bf00ff",  # Electric Purple / LED Violet
    "title": "bold #d02090",   # Violet Red
    "option": "bold #bf00ff",  # Same as header
})
console = Console(theme=custom_theme, force_terminal=True)


@click.group(invoke_without_command=True)
@click.option("--debug", is_flag=True, help="Ativar registos detalhados (debug)")
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx, debug: bool):
    """CipherVault

    CLI robusta para cifrar/decifrar ficheiros.
    Suporta qualquer ficheiro (recomenda-se .zip/.rar para pastas, ou imagens).
    """
    # Configurar registo (logging) uma única vez
    log_level = logging.DEBUG if debug else logging.INFO
    logger = logging.getLogger()
    if not logger.handlers:
        logging.basicConfig(level=log_level, format="[%(levelname)s] %(message)s")
    else:
        logger.setLevel(log_level)

    if ctx.invoked_subcommand is None:
        _interactive()


def _interactive():
    """Loop de menu interativo.

    Permite ao utilizador repetir operações sucessivamente sem relançar
    o processo. Cada escolha devolve ao menu após conclusão.
    """
    while True:
        console.clear()
        # Cabeçalho com estilo "Violet LED" e Versão Dinâmica
        console.print(Panel(
            f"[header]CipherVault[/header] [dim]v{__version__}[/dim]\n[white]Cifrar (self ou contacto) / Decifrar[/white]", 
            expand=False, 
            border_style="header",
            title="[title]MENU PRINCIPAL[/title]",
            subtitle="[dim]Secure Storage[/dim]"
        ))
        console.print("\n[bold]Ações:[/bold]")
        console.print("  [option]1)[/option] Cifrar ficheiro (para mim)")
        console.print("  [option]2)[/option] Cifrar ficheiro para contacto")
        console.print("  [option]3)[/option] Decifrar ficheiro .cvault")
        console.print("  [option]4)[/option] Partilhar a minha chave pública (exportar PEM)")
        console.print("  [option]5)[/option] Contactos (adicionar/listar/apagar)")
        console.print("  [option]6)[/option] Verificar autenticidade, integridade e metadados")
        console.print("  [option]7)[/option] Comparar dois ficheiros (detetar alteração)")
        console.print("  [option]8)[/option] Sair")
        
        # Prompt limpo sem (1) e sem default visível
        choice = Prompt.ask("Escolha", choices=["1", "2", "3", "4", "5", "6", "7", "8"], show_choices=False, show_default=False, console=console)
        
        if choice == "8":
            sys.exit(0)

        # Limpar ecrã antes de executar o comando selecionado
        console.clear()

        if choice == "1":
            _encrypt_flow(); Prompt.ask("\nEnter para voltar ao menu", console=console)
        elif choice == "2":
            _encrypt_for_contact_flow(); Prompt.ask("\nEnter para voltar ao menu", console=console)
        elif choice == "3":
            _decrypt_flow(); Prompt.ask("\nEnter para voltar ao menu", console=console)
        elif choice == "4":
            _export_public_key_flow(); Prompt.ask("\nEnter para voltar ao menu", console=console)
        elif choice == "5":
            _contacts_menu()  # regressa sem prompt extra
        elif choice == "6":
            _verify_flow(); Prompt.ask("\nEnter para voltar ao menu", console=console)
        elif choice == "7":
            _compare_files_flow(); Prompt.ask("\nEnter para voltar ao menu", console=console)


def _show_public_key():
    """Mostra a chave pública em PEM (sem riscos de confidencialidade)."""
    ks = KeyStore(); ks.ensure_keys()
    pem = ks.get_public_pem().decode("utf-8", errors="ignore")
    panel = Panel(pem, title="Chave Pública (PEM)", expand=False)
    console.print(panel)


def _contacts_menu():
    store = ContactsStore()
    while True:
        console.clear()
        console.print(Panel("[header]Contactos[/header]", expand=False, border_style="header"))
        console.print("  [option]1)[/option] Adicionar contacto")
        console.print("  [option]2)[/option] Listar contactos")
        console.print("  [option]3)[/option] Apagar contacto")
        console.print("  [option]4)[/option] Voltar")
        
        c = Prompt.ask("Escolha", choices=["1", "2", "3", "4"], show_choices=False, show_default=False, console=console)
        
        if c == "4":
            break
            
        console.clear()
        
        if c == "1":
            _contact_add_flow(store)
            Prompt.ask("\nEnter para continuar", console=console)
        elif c == "2":
            _contact_list_flow(store)
            Prompt.ask("\nEnter para continuar", console=console)
        elif c == "3":
            _contact_delete_flow(store)
            Prompt.ask("\nEnter para continuar", console=console)

def _contact_add_flow(store: ContactsStore):
    console.print("\n[bold]Adicionar novo contacto[/bold]")
    name = Prompt.ask("Nome do contacto", console=console)
    pem_path = Prompt.ask("Caminho do ficheiro da chave pública do contacto (PEM)", console=console)
    p = Path(_clean_path(pem_path)).expanduser().resolve()
    if not p.exists() or not p.is_file():
        console.print("[red]Caminho inválido para ficheiro[/red]")
        return
    pem_text = p.read_text(encoding="utf-8", errors="ignore")
    try:
        store.add_contact(name, pem_text)
        console.print("[green]Contacto adicionado com sucesso[/green]")
    except Exception as e:
        console.print(f"[red]Falha ao adicionar:[/red] {e}")

def _contact_list_flow(store: ContactsStore):
    items = store.list_contacts()
    table = Table(title="Contactos", show_lines=True)
    # MUDANÇA AQUI: style="option" para usar a cor violeta definida no tema
    table.add_column("Nome", style="option", no_wrap=True)
    table.add_column("Fingerprint (SHA-256)", style="white")
    table.add_column("Excerto PEM", style="white")
    for c in items:
        pem_lines = (c.get("public_pem") or "").splitlines()
        snippet = []
        if pem_lines:
            snippet.append(pem_lines[0])
        if len(pem_lines) > 1:
            snippet.append("…")
            snippet.append(pem_lines[-1])
        table.add_row(c.get("name", ""), c.get("fingerprint", ""), "\n".join(snippet))
    console.print(table)

def _contact_delete_flow(store: ContactsStore):
    name = Prompt.ask("Nome do contacto a apagar", console=console)
    ok = store.delete_contact(name)
    if ok:
        console.print("[yellow]Contacto removido[/yellow]")
    else:
        console.print("[red]Nenhum contacto com esse nome[/red]")


def _clean_path(path_str: str) -> str:
    """Normaliza caminho introduzido removendo aspas exteriores e espaços.

    Objetivo: tolerar colagem de caminhos provenientes do Explorador
    do Windows que frequentemente incluem aspas.
    """
    if path_str is None:
        return ""
    s = path_str.strip()
    # Remover aspas correspondentes se presentes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s


@contextmanager
def _resolved_input_path(path_str: str):
    """Resolve um caminho de entrada para cifragem, aceitando ficheiros ou pastas.

    Pastas são comprimidas automaticamente para um .zip temporário (ver
    `archiving.zip_folder`), que é depois cifrado pela mesma função usada
    para qualquer outro ficheiro. O .zip temporário é limpo no final.

    Produz (caminho_a_cifrar, caminho_de_saida_sugerido). O caminho de saída
    é None para ficheiros normais (a função de cifragem decide o omisso);
    para pastas é explícito e aponta para a pasta-mãe original, já que o
    .zip temporário (e portanto qualquer .cvault escrito ao lado dele) é
    apagado assim que a cifragem termina.
    """
    cleaned = _clean_path(path_str)
    p = Path(cleaned).expanduser().resolve()
    if not p.exists():
        raise click.BadParameter(f"Caminho não encontrado: {p}")
    if p.is_dir():
        console.print(f"[dim]A comprimir pasta '{p.name}' antes de cifrar...[/dim]")
        zipped = zip_folder(p)
        out_path = p.parent / f"{p.name}.zip.cvault"
        try:
            yield zipped, out_path
        finally:
            cleanup_temp_zip(zipped)
    else:
        yield p, None


def _encrypt_flow():
    """Fluxo interativo para cifrar um único ficheiro.

    Recolhe caminho, valida, executa cifragem híbrida e reporta resultado.
    """
    ks = KeyStore()
    ks.ensure_keys()
    se = SelfEncryptor(ks)

    console.print("\nIntroduza o [bold]caminho para o ficheiro ou pasta[/bold] a cifrar (pastas são comprimidas automaticamente):")
    path_str = Prompt.ask("Caminho do ficheiro/pasta", console=console)
    try:
        with _resolved_input_path(path_str) as (in_path, out_hint):
            out_path = se.encrypt_file(in_path, out_hint)
            console.print(f"\n[green]Sucesso![/green] Cifrado em: [bold]{out_path}[/bold]")
    except click.BadParameter as e:
        console.print(f"[red]Erro:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Falha ao cifrar:[/red] {e}")


def _encrypt_for_contact_flow():
    """Fluxo interativo: cifrar ficheiro para um contacto (usa formato v2)."""
    store = ContactsStore()
    items = store.list_contacts()
    if not items:
        console.print("[red]Não há contactos. Adicione primeiro em 'Contactos'.[/red]")
        return
    table = Table(title="Escolha Contacto", show_lines=True)
    table.add_column("#", style="cyan")
    table.add_column("Nome", style="white")
    table.add_column("Fingerprint", style="white")
    for idx, c in enumerate(items, start=1):
        table.add_row(str(idx), c.get("name",""), c.get("fingerprint","")[:32] + "…")
    console.print(table)
    choice_str = Prompt.ask("Número do contacto", console=console)
    try:
        idx = int(choice_str)
        contact = items[idx-1]
    except Exception:
        console.print("[red]Seleção inválida[/red]")
        return
    path_str = Prompt.ask("Caminho do ficheiro ou pasta a cifrar", console=console)
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    try:
        with _resolved_input_path(path_str) as (in_path, out_hint):
            out_path = se.encrypt_for_contact(in_path, contact["public_pem"].encode("utf-8"), out_hint, recipient_name=contact.get("name"))
            console.print(f"\n[green]Sucesso![/green] Cifrado para contacto '{contact.get('name')}' em: [bold]{out_path}[/bold]")
    except click.BadParameter as e:
        console.print(f"[red]Erro:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Falha ao cifrar para contacto:[/red] {e}")


def _decrypt_flow():
    """Fluxo interativo para decifrar contentor .cvault.

    Valida extensão, decifra, verifica assinatura e escreve ficheiro original.
    """
    ks = KeyStore()
    ks.ensure_keys()
    se = SelfEncryptor(ks)

    console.print("\nIntroduza o [bold]caminho para o ficheiro .cvault[/bold] a decifrar:")
    path_str = Prompt.ask("Caminho do ficheiro .cvault", console=console)
    cleaned = _clean_path(path_str)
    p = Path(cleaned).expanduser().resolve()
    if not p.exists() or not p.is_file() or p.suffix != ".cvault":
        console.print("[red]Indique um caminho válido para um ficheiro .cvault[/red]")
        return

    try:
        out_path = se.decrypt_file(p)
        console.print(f"\n[green]Sucesso![/green] Decifrado em: [bold]{out_path}[/bold]")
    except Exception as e:
        msg = str(e)
        if "Formato de ficheiro inválido" in msg or "decryption failed" in msg.lower() or "tag mismatch" in msg.lower():
            console.print("[red]O ficheiro .cvault está corrompido ou foi adulterado.[/red]")
        else:
            console.print(f"[red]Falha ao decifrar:[/red] {e}")

def _verify_flow():
    """Fluxo interativo para verificar autenticidade, integridade e metadados."""
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    console.print("\n[bold]Verificar Autenticidade, Integridade e Metadados[/bold]")
    path_str = Prompt.ask("Caminho do ficheiro .cvault", console=console)
    cleaned = _clean_path(path_str)
    p = Path(cleaned).expanduser().resolve()
    if not p.exists() or not p.is_file() or p.suffix != ".cvault":
        console.print("[red]Indique um caminho válido para um ficheiro .cvault[/red]")
        return
    
    try:
        # Primeiro obtemos metadados (sem verificar integridade profunda ainda)
        info = se.inspect_file(p)
        
        # Depois verificamos integridade e autenticidade
        result = se.verify_authenticity(p)
        
        # Combinamos a informação
        table = Table(title=f"Relatório de Segurança: {p.name}", show_lines=True)
        table.add_column("Propriedade", style="cyan")
        table.add_column("Valor", style="white")

        # Metadados
        table.add_row("Versão do Formato", str(info["version"]))
        table.add_row("Nome Original", info["filename"])
        table.add_row("Tamanho Original", f"{info['size']} bytes")
        
        # Chaves e Identidade
        is_me = info["is_for_me"]
        dest_str = "[green]Sim (Pode decifrar)[/green]" if is_me else "[red]Não (Chave privada diferente)[/red]"
        table.add_row("Cifrado para mim?", dest_str)
        table.add_row("Fingerprint Remetente", info["sender_fp"][:16] + "...")
        table.add_row("Fingerprint Destinatário", info["recipient_fp"][:16] + "...")

        # Segurança
        int_ok = result.get("integrity_ok")
        auth_ok = result.get("authenticity_ok")
        
        int_str = "[green]VÁLIDA (OK)[/green]" if int_ok else "[red]FALHA (Corrompido)[/red]"
        auth_str = "[green]VÁLIDA (Assinatura OK)[/green]" if auth_ok else "[red]INVÁLIDA (Adulterado)[/red]"
        
        table.add_row("Integridade (AES-GCM)", int_str)
        table.add_row("Autenticidade (RSA-PSS)", auth_str)

        console.print(table)

        if int_ok and auth_ok:
            console.print("\n[green bold]CONCLUSÃO: O ficheiro é autêntico e íntegro.[/green bold]")
            console.print("[green]Pode confiar neste conteúdo.[/green]")
        elif int_ok and not auth_ok:
            console.print("\n[yellow bold]ALERTA: A integridade técnica está ok, mas a assinatura digital falhou.[/yellow bold]")
            console.print("[yellow]O ficheiro pode ter sido modificado ou a chave pública do remetente não corresponde.[/yellow]")
        else:
            console.print("\n[red bold]PERIGO: O ficheiro está corrompido ou foi adulterado.[/red bold]")
            console.print("[red]Não tente decifrar este ficheiro.[/red]")

    except Exception as e:
        msg = str(e)
        if "Formato de ficheiro inválido" in msg or "decryption failed" in msg.lower() or "tag mismatch" in msg.lower():
            console.print("[red]O ficheiro .cvault está corrompido ou foi adulterado (Falha Crítica).[/red]")
        else:
            console.print(f"[red]Erro na verificação:[/red] {e}")

def _compare_files_flow():
    """Compara dois ficheiros claros e mostra SHA-256 e se são iguais."""
    console.print("\n[bold]Comparar dois ficheiros[/bold]")
    a_path = Path(_clean_path(Prompt.ask("Ficheiro A", console=console))).expanduser().resolve()
    b_path = Path(_clean_path(Prompt.ask("Ficheiro B", console=console))).expanduser().resolve()
    if not a_path.exists() or not a_path.is_file() or not b_path.exists() or not b_path.is_file():
        console.print("[red]Indique caminhos válidos para ambos os ficheiros[/red]")
        return
    a_bytes = a_path.read_bytes(); b_bytes = b_path.read_bytes()
    h_a = hashlib.sha256(a_bytes).hexdigest(); h_b = hashlib.sha256(b_bytes).hexdigest()
    iguais = h_a == h_b
    table = Table(title="Resultado da Comparação", show_lines=True)
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="white")
    table.add_row("Ficheiro A", str(a_path))
    table.add_row("Ficheiro B", str(b_path))
    table.add_row("SHA256(A)", h_a)
    table.add_row("SHA256(B)", h_b)
    table.add_row("Iguais?", "SIM" if iguais else "NAO")
    console.print(table)
    if iguais:
        console.print("[green]Os ficheiros são idênticos.[/green]")
    else:
        console.print("[yellow]Os ficheiros diferem (conteúdo alterado).[/yellow]")


@cli.command()
@click.argument("path", type=click.Path(path_type=Path))
def encrypt(path: Path):
    """Cifrar um ficheiro ou pasta para si (modo não interativo). Pastas são comprimidas automaticamente."""
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    p = path.expanduser().resolve()
    if not p.exists():
        raise click.ClickException(f"Caminho não encontrado: {p}")
    temp_zip = None
    out_hint = None
    try:
        if p.is_dir():
            temp_zip = zip_folder(p)
            out_hint = p.parent / f"{p.name}.zip.cvault"
            p = temp_zip
        out = se.encrypt_file(p, out_hint)
        console.print(f"[green]Cifrado:[/green] {out}")
    finally:
        if temp_zip:
            cleanup_temp_zip(temp_zip)


@cli.command()
@click.argument("path", type=click.Path(path_type=Path))
def decrypt(path: Path):
    """Decifrar um ficheiro .cvault (modo não interativo)."""
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    p = path.expanduser().resolve()
    if not p.exists() or not p.is_file() or p.suffix != ".cvault":
        raise click.ClickException("Indique um caminho válido para um ficheiro .cvault")
    try:
        out = se.decrypt_file(p)
        console.print(f"[green]Decifrado:[/green] {out}")
    except Exception as e:
        msg = str(e)
        if "Formato de ficheiro inválido" in msg or "decryption failed" in msg.lower() or "tag mismatch" in msg.lower():
            raise click.ClickException("O ficheiro .cvault está corrompido ou foi adulterado.")
        raise click.ClickException(f"Falha ao decifrar: {e}")


@cli.command(name="keys")
def keys_info():
    """Mostrar onde as chaves estão guardadas e a sua impressão digital."""
    ks = KeyStore()
    ks.ensure_keys()

    table = Table(title="Informação do Cofre de Chaves", show_lines=True)
    table.add_column("Item", style="cyan", no_wrap=True)
    table.add_column("Valor", style="white")

    table.add_row("Diretoria base", str(ks.base_dir))
    table.add_row("Chave privada", str(ks.private_key_path))
    table.add_row("Chave pública", str(ks.public_key_path))

    try:
        fp = ks.get_fingerprint_hex()
    except Exception:
        fp = "<unavailable>"
    table.add_row("Impressão digital da chave pública (SHA-256)", fp)

    # Mostrar um pequeno excerto da chave pública PEM para confirmação visual
    try:
        pub_pem = ks.get_public_pem().decode("utf-8", errors="ignore").splitlines()
        snippet = []
        if pub_pem:
            snippet.append(pub_pem[0])
        if len(pub_pem) > 1:
            snippet.append("…")
            snippet.append(pub_pem[-1])
        table.add_row("Excerto do PEM público", "\n".join(snippet))
    except Exception:
        table.add_row("Excerto do PEM público", "<unavailable>")

    console.print(table)


@cli.command(name="public-key")
def public_key_cmd():
    """Imprimir chave pública em PEM."""
    ks = KeyStore(); ks.ensure_keys()
    console.print(ks.get_public_pem().decode("utf-8", errors="ignore"))

def _export_public_key_flow():
    """Exporta a chave pública para um ficheiro PEM fácil de partilhar."""
    ks = KeyStore(); ks.ensure_keys()
    default_path = Path.home() / "Documents" / "CipherVault_public_key.pem"
    out_str = Prompt.ask("Caminho de saída para ficheiro PEM", default=str(default_path), console=console)
    out_path = Path(_clean_path(out_str)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(ks.get_public_pem())
    # MUDANÇA AQUI: [option] para usar a cor violeta no caminho
    console.print(f"[green]Chave pública exportada para:[/green] [option]{out_path}[/option]")

@cli.command(name="export-public-key")
@click.option("--out", type=click.Path(path_type=Path), help="Caminho de saída para o PEM (por omissão: Documentos)")
def export_public_key_cmd(out: Path | None):
    """Exportar a chave pública para um ficheiro PEM para partilha."""
    ks = KeyStore(); ks.ensure_keys()
    if out is None:
        out = (Path.home() / "Documents" / "CipherVault_public_key.pem").expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ks.get_public_pem())
    console.print(f"[green]Chave pública exportada para:[/green] {out}")
@cli.command(name="encrypt-for-contact")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--name", required=True, help="Nome do contacto a usar")
def encrypt_for_contact_cmd(path: Path, name: str):
    """Cifrar um ficheiro ou pasta para um contacto armazenado (formato v2). Pastas são comprimidas automaticamente."""
    store = ContactsStore()
    contact = next((c for c in store.list_contacts() if c.get("name") == name), None)
    if not contact:
        raise click.ClickException("Contacto não encontrado")
    p = path.expanduser().resolve()
    if not p.exists():
        raise click.ClickException("Caminho inválido para ficheiro/pasta")
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    temp_zip = None
    out_hint = None
    try:
        if p.is_dir():
            temp_zip = zip_folder(p)
            out_hint = p.parent / f"{p.name}.zip.cvault"
            p = temp_zip
        out = se.encrypt_for_contact(p, contact["public_pem"].encode("utf-8"), out_hint, recipient_name=name)
        console.print(f"[green]Cifrado para '{name}':[/green] {out}")
    finally:
        if temp_zip:
            cleanup_temp_zip(temp_zip)

def _inspect_flow():
    """(Obsoleto) Integrado no _verify_flow."""
    pass

@cli.command(name="inspect")
@click.argument("path", type=click.Path(path_type=Path))
def inspect_cmd(path: Path):
    """(Obsoleto) Use 'verify' para ver metadados e segurança."""
    console.print("[yellow]O comando 'inspect' foi integrado no 'verify'. Use 'verify' para ver metadados e segurança.[/yellow]")
    verify_cmd(path)

@cli.command(name="verify")
@click.argument("vault_file", type=click.Path(path_type=Path))
def verify_cmd(vault_file: Path):
    """Verificar autenticidade, integridade e metadados de um ficheiro .cvault."""
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    p = vault_file.expanduser().resolve()
    if not p.exists() or not p.is_file() or p.suffix != ".cvault":
        raise click.ClickException("Indique um caminho válido para um ficheiro .cvault")
    try:
        # Obter metadados primeiro
        info = se.inspect_file(p)
        # Verificar segurança
        result = se.verify_authenticity(p)
        
        # Combinar resultados num único JSON para output de comando
        combined = {**info, **result}
        console.print(json.dumps(combined, indent=2, ensure_ascii=False))
        
    except Exception as e:
        msg = str(e)
        if "Formato de ficheiro inválido" in msg or "decryption failed" in msg.lower() or "tag mismatch" in msg.lower():
            raise click.ClickException("O ficheiro .cvault está corrompido ou foi adulterado.")
        raise click.ClickException(f"Falha na verificação: {e}")

@cli.command(name="compare-files")
@click.argument("file_a", type=click.Path(path_type=Path))
@click.argument("file_b", type=click.Path(path_type=Path))
def compare_files_cmd(file_a: Path, file_b: Path):
    """Comparar dois ficheiros claros (SHA-256)."""
    a = file_a.expanduser().resolve(); b = file_b.expanduser().resolve()
    if not a.exists() or not a.is_file() or not b.exists() or not b.is_file():
        raise click.ClickException("Indique caminhos válidos para ambos os ficheiros")
    a_bytes = a.read_bytes(); b_bytes = b.read_bytes()
    h_a = hashlib.sha256(a_bytes).hexdigest(); h_b = hashlib.sha256(b_bytes).hexdigest()
    iguais = h_a == h_b
    result = {"file_a": str(a), "file_b": str(b), "sha256_a": h_a, "sha256_b": h_b, "iguais": iguais}
    console.print(json.dumps(result, indent=2, ensure_ascii=False))

@cli.command(name="compare-with-vault")
@click.argument("vault_file", type=click.Path(path_type=Path))
@click.argument("file_plain", type=click.Path(path_type=Path))
def compare_with_vault_cmd(vault_file: Path, file_plain: Path):
    """Compara plaintext fornecido com conteúdo decifrado de um .cvault (deteta alteração)."""
    ks = KeyStore(); ks.ensure_keys(); se = SelfEncryptor(ks)
    v = vault_file.expanduser().resolve(); p = file_plain.expanduser().resolve()
    if not v.exists() or not v.is_file() or v.suffix != ".cvault":
        raise click.ClickException("Indique um .cvault válido")
    if not p.exists() or not p.is_file():
        raise click.ClickException("Indique um ficheiro claro válido")
    try:
        vault_plain, meta = se.decrypt_to_bytes(v)
    except Exception as e:
        raise click.ClickException(f"Falha ao decifrar contentor: {e}")
    given_bytes = p.read_bytes()
    h_v = hashlib.sha256(vault_plain).hexdigest()
    h_p = hashlib.sha256(given_bytes).hexdigest()
    iguais = h_v == h_p
    result = {"vault_file": str(v), "plain_file": str(p), "sha256_vault_plain": h_v, "sha256_plain": h_p, "iguais": iguais, "metadata": meta}
    console.print(json.dumps(result, indent=2, ensure_ascii=False))

@cli.command(name="contacts-list")
def contacts_list_cmd():
    """Listar contactos guardados."""
    store = ContactsStore()
    _contact_list_flow(store)

@cli.command(name="contacts-add")
@click.option("--name", required=True, help="Nome do contacto")
@click.option("--pubkey", type=click.Path(path_type=Path), required=True, help="Caminho para PEM da chave pública")
def contacts_add_cmd(name: str, pubkey: Path):
    """Adicionar um contacto (nome + caminho para ficheiro PEM de chave pública)."""
    store = ContactsStore()
    p = pubkey.expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise click.ClickException("Caminho inválido para PEM")
    pem = p.read_text(encoding="utf-8", errors="ignore")
    store.add_contact(name, pem)
    console.print("[green]Contacto adicionado[/green]")

@cli.command(name="contacts-delete")
@click.option("--name", required=True, help="Nome do contacto a apagar")
def contacts_delete_cmd(name: str):
    """Apagar um contacto pelo nome."""
    store = ContactsStore()
    if not store.delete_contact(name):
        raise click.ClickException("Contacto não encontrado")
    console.print("[yellow]Contacto removido[/yellow]")
