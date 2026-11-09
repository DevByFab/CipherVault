# CipherVault – Protótipo (v1.9.0)

Aplicação de cifragem híbrida (RSA-4096 + AES-256-GCM) com **interface gráfica completa** e uma CLI robusta como alternativa. Permite o uso pessoal e a partilha segura com contactos. Inclui gestão de chaves, exportação de chave pública, cifragem direcionada a destinatários específicos e atualização automática.

**Novo em 1.9.0:** Redesenho completo da GUI focado em clareza para novos utilizadores: cada função (Encrypt, Decrypt, Verify, Contacts, Tools, Settings) é agora a sua própria página na barra lateral, em vez de separadores aninhados. Ecrã de boas-vindas na primeira execução a explicar os 3 passos essenciais (identidade, cifrar, partilhar). Notificações não-intrusivas ("toasts") substituem a maioria dos pop-ups de sucesso. Pequenas animações subtis (fade-in da janela, indicador de identidade "respirando"). Ao escolher uma pasta para cifrar, a app conta ficheiros e tamanho total em segundo plano para dar confiança em pastas grandes. Página de Dashboard com estatísticas de utilização (ficheiros cifrados/decifrados). Correção de um bug em que o conteúdo do Dashboard podia ficar cortado em janelas mais pequenas — todas as páginas agora deslizam (scroll) quando o conteúdo excede o espaço visível.

**Novo em 1.8.0:** GUI unificada (`src/gui.py`) com Dashboard, Vault (cifrar/decifrar/verificar), Contactos, Ferramentas e um novo separador **Settings** com verificação/aplicação de atualizações a partir da própria janela. Lançador gráfico dedicado (`CipherVault.vbs` / `start_gui.cmd`) que também prepara o ambiente virtual e aplica atualizações automaticamente antes de abrir a app — sem janela de consola. Visual renovado com o tema "Neon Glow" do logótipo oficial (`CipherVault_Logo.png`), usado também como ícone da janela. **Cifragem de pastas**: tanto a GUI como a CLI aceitam agora uma pasta diretamente — é comprimida automaticamente para `.zip` e cifrada com as mesmas funções `encrypt_file`/`encrypt_for_contact` de sempre, sem alterar o formato `.cvault`.
**Novo em 1.6.0:** Smart Launcher com atualização automática (verifica GitHub), gestão automática de ambiente virtual e dependências, e proteção contra downgrade.

## Pré-requisitos

- Python 3.10+
- Windows PowerShell (fornecido) ou outro terminal
- Ligação à Internet (para atualizações automáticas)

## Instalação e Execução Rápida

### Interface Gráfica (recomendado)

Basta abrir `CipherVault.vbs` (duplo-clique, sem janela de consola) ou `start_gui.cmd`:

```cmd
.\start_gui.cmd
```

Tal como o launcher de CLI, este lançador irá:
1. Verificar/Criar o ambiente virtual (`.venv`).
2. Instalar/Atualizar dependências (`requirements.txt`).
3. Verificar se existe uma nova versão no GitHub e atualizar automaticamente.
4. Abrir a interface gráfica (`src/gui.py`).

Também é possível verificar e aplicar atualizações manualmente a qualquer momento a partir do separador **Settings** dentro da própria aplicação.

### Linha de Comandos (CLI)

A partir da versão 1.6.0, o **Smart Launcher** trata de tudo (ambiente virtual, dependências e atualizações).

Basta executar o ficheiro de comando:

```cmd
.\ciphervault.cmd
```

O launcher irá:
1. Verificar/Criar o ambiente virtual (`.venv`).
2. Instalar/Atualizar dependências (`requirements.txt`).
3. Verificar se existe uma nova versão no GitHub e atualizar automaticamente.
4. Iniciar a aplicação.

## Executar Manualmente (Avançado)

Se preferir não usar o launcher:

1) Criar o ambiente virtual:
   ```
   python -m venv .venv
   ```

2) Ativar o ambiente virtual:
   ```
   .\.venv\Scripts\Activate.ps1
   ```

3) Instalar dependências:
   ```
   pip install -r requirements.txt
   ```

4) Executar:
   ```
   python src/main.py
   ```

## Comandos Disponíveis

```
# Cifrar para si (aceita um ficheiro OU uma pasta — pastas são comprimidas automaticamente)
python src/main.py encrypt <caminho_ficheiro_ou_pasta>

# Decifrar ficheiro .cvault
python src/main.py decrypt <caminho_ficheiro.cvault>

# Verificar autenticidade, integridade e metadados (Relatório de Segurança)
python src/main.py verify <caminho_ficheiro.cvault>

# Ver chaves e impressões digitais
python src/main.py --debug keys

# Mostrar versão
python src/main.py --version

# Ver chave pública no terminal
python src/main.py public-key

# Exportar a minha chave pública para ficheiro PEM (partilha)
python src/main.py export-public-key --out "C:\\Users\\Tu\\Documents\\CipherVault_public_key.pem"

# Contactos (gestão local)
python src/main.py contacts-list
python src/main.py contacts-add --name "NOME" --pubkey "caminho/para/public.pem"
python src/main.py contacts-delete --name "NOME"

# Cifrar para um contacto (usa a chave pública do contacto; também aceita pastas)
python src/main.py encrypt-for-contact <caminho_ficheiro_ou_pasta> --name "NOME"
```

Notas:
- Qualquer formato de ficheiro pode ser cifrado diretamente (imagens, vídeos, documentos, executáveis, arquivos comprimidos, etc.) — a cifragem opera sobre os bytes, independentemente do tipo.
- Pastas são suportadas diretamente: são comprimidas automaticamente para um `.zip` temporário antes de serem cifradas com as mesmas funções usadas para qualquer ficheiro, e o `.zip` temporário é removido no final. O resultado (`<pasta>.zip.cvault`) fica ao lado da pasta original.
- As chaves são guardadas em: %USERPROFILE%\.ciphervault\ (chave privada e pública)
- Modo debug: adicione `--debug` antes do comando (ex.: `python src/main.py --debug encrypt ...`) para ver registos detalhados (geração/carregamento de chaves, etapas de cifragem/decifragem).

## Versionamento

- Formato: MAIOR.MENOR.CORRETIVO (ex.: 1.1.0)
- Regras:
  - Corretivo (+0.0.1): pequenas melhorias, registos, correções
  - Menor (+0.1.0): novas funcionalidades compatíveis (ex.: novo comando)
  - Maior (+1.0.0): alterações importantes/incompatíveis

Versão atual: 1.9.0 (GUI redesenhada com navegação por página, onboarding, notificações e atualização automática integrada; Smart Launcher para GUI e CLI).

## Segurança (Resumo)

- Dados: AES-256-GCM (confidencialidade + integridade via tag)
- Chave: envolvida com RSA-4096 OAEP (SHA-256)
- Assinatura: RSA-PSS (SHA-256) sobre conteúdo original

Para mais teoria, consultar `DOCUMENTACAO.md`.

## Abrir uma janela CMD dedicada (Windows)

Pode lançar uma janela própria do CipherVault com opções visíveis e arranque em modo interativo:

```
./ciphervault.cmd
```

Notas:
- Se existir `.venv\Scripts\python.exe`, será usado automaticamente; caso contrário usa `python` do sistema.
- O script mostra `--version`, depois `--help`, exemplos de contactos e arranca o modo interativo.
- No fim, a janela pede uma tecla para fechar.
