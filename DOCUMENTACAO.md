# CipherVault – Documentação Completa do Protótipo (v1.9.0)

Este documento central reúne numa só referência tudo o que é necessário para
compreender, explicar e justificar o funcionamento do protótipo CipherVault.
Inclui: objetivos, arquitetura, formato de ficheiro, fluxo interno, código
organizado por módulos, comandos CLI, segurança, limitações e roadmap.

## Objetivo

- Fornecer uma aplicação simples de linha de comandos para proteger ficheiros locais.
- Cifrar e decifrar “para o próprio” (self), cifrar “para um contacto” e verificar autenticidade/integridade.
- Usar uma abordagem criptográfica moderna e segura (híbrida: simétrica + assimétrica).
- Manter um formato de contentor único (`.cvault`) auto‑descritivo.
- Facilitar futura evolução para multi-destinatários e funcionalidades adicionais.
- Gerir contactos (nome + chave pública) localmente via ficheiro PEM e exportar a própria chave pública para partilha.
- Fornecer um Relatório de Segurança Unificado (Metadados + Integridade + Autenticidade).
- **Novo na v1.6.x:** Smart Launcher para gestão automática de ambiente e atualizações, e interface visual melhorada (Tema "Violet LED").
- **Novo na v1.8.0:** GUI única e completa (`src/gui.py`) com Dashboard, Vault, Contactos, Ferramentas e Settings (verificação/aplicação de atualizações a partir da própria janela, com reinício automático). Lançador gráfico dedicado (`launcher/launcher_gui.ps1`, invocado por `CipherVault.vbs`/`start_gui.cmd`) que prepara o ambiente virtual, aplica atualizações e abre a GUI sem consola. Tema visual "Neon Glow" alinhado com `CipherVault_Logo.png` (glow branco sobre antracite quase preto), usado também como marca na barra lateral e como ícone da janela/barra de tarefas. Cifragem de pastas (GUI e CLI): uma pasta é comprimida automaticamente para `.zip` e cifrada pelas mesmas funções `encrypt_file`/`encrypt_for_contact` já existentes (ver `src/ciphervault/archiving.py`), sem qualquer alteração ao formato `.cvault`.
- **Novo na v1.9.0:** Redesenho de navegação — cada função (Encrypt, Decrypt, Verify, Contactos, Ferramentas, Settings) passou a ser a sua própria página na barra lateral (em vez de separadores dentro de "Vault"), com um cabeçalho de página consistente (título + descrição de uma linha) explicando o propósito de cada uma. Ecrã de boas-vindas (`WelcomePage`) na primeira execução, com os 3 passos essenciais; reacessível a qualquer momento em Settings. Sistema de notificações não-bloqueantes ("toasts") a substituir a maioria dos `messagebox.showinfo`. Pequenas animações: fade-in da janela ao arrancar e um indicador de identidade com um efeito de "respiração" subtil. Ao selecionar uma pasta para cifrar, é feita uma contagem em segundo plano do número de ficheiros e tamanho total, mostrada junto à seleção. Estado local da GUI (`~/.ciphervault/gui_state.json`) para lembrar se o utilizador já viu o ecrã de boas-vindas e para acumular estatísticas de utilização (ficheiros cifrados/decifrados) mostradas no Dashboard. Todas as páginas passaram a usar `CTkScrollableFrame`, corrigindo um problema em que o conteúdo do Dashboard podia ficar cortado (sem scroll) em janelas mais pequenas.

## Arquitetura

- Criptografia híbrida: RSA-4096 (assimétrico) + AES-256-GCM (simétrico).
- Controlo de autenticidade: assinatura RSA-PSS sobre hash SHA-256 do conteúdo original.
- Metadados: JSON no cabeçalho (não cifrado) para inspeção rápida.
- Contentor `.cvault`: inclui metadados, chave pública, chave AES envolvida, assinatura, nonce, tag e ciphertext.
- Armazenamento local das chaves: `~/.ciphervault/` contendo `private_key.pem` e `public_key.pem`.
- Código organizado em módulos (`crypto.py` para operações de baixo nível, `cli.py` para interface e fluxo de utilização).

### Fluxo de Cifragem (“para mim”, v1)

1. Ler o ficheiro original (plaintext).
2. Gerar chave AES-256 aleatória (32 bytes) e nonce GCM (12 bytes).
3. Cifrar o plaintext com AES-256-GCM → produz ciphertext + tag de integridade.
4. Envolver a chave AES com a chave pública RSA-4096 do utilizador (OAEP/SHA-256).
5. Calcular hash SHA-256 do plaintext e assinar com a chave privada (RSA-PSS).
6. Construir e escrever o ficheiro `.cvault` com a estrutura definida.

### Fluxo de Cifragem para Contacto (v2)

1. Ler o ficheiro original (plaintext).
2. Gerar chave AES-256 aleatória (32 bytes) e nonce GCM (12 bytes).
3. Cifrar o plaintext com AES-256-GCM → ciphertext + tag.
4. Envolver a chave AES com a chave pública do contacto (RSA-OAEP/SHA-256).
5. Calcular hash SHA-256 do plaintext e assinar com a chave privada do remetente (RSA-PSS).
6. Construir o `.cvault` v2 com chaves públicas do remetente e do destinatário.

O destinatário decifra a chave AES com a sua chave privada e valida a assinatura com a chave pública do remetente embutida.

### Fluxo de Decifragem

1. Ler e validar cabeçalho (`Magic`, versão, flags).
2. Recuperar metadados e chave pública embutida.
3. Confirmar que a chave pública do contentor coincide com a chave local (garante que foi cifrado “para mim”).
4. Decifrar a chave AES com a chave privada (RSA-OAEP).
5. Decifrar dados com AES-256-GCM (verificando a tag de integridade).
6. Recalcular hash do plaintext e verificar assinatura RSA-PSS.
7. Escrever ficheiro restaurado.

Se qualquer verificação falhar (tag ou assinatura), o processo termina com erro.

### Fluxo de Verificação (novo em 1.4.0)

Objetivo: validar rapidamente se um ficheiro `.cvault` é autêntico (assinatura RSA-PSS válida) e íntegro (tag GCM válida) sem restaurar o plaintext para disco.

Passos:
1. Ler e validar cabeçalho.
2. Decifrar chave AES (RSA-OAEP).
3. Tentar decifrar ciphertext com AES-256-GCM (se falhar, integridade falha).
4. Se integridade ok, recalcular hash SHA-256 do plaintext e verificar assinatura RSA-PSS.
5. Reportar JSON com `authenticity_ok`, `integrity_ok`, versão, filename e fingerprints.

Benefício: permite inspeção de confiança antes de consumir/escrever dados.

### Estrutura Binária do Contentor `.cvault`

| Ordem | Campo | Tamanho | Descrição |
|-------|-------|---------|-----------|
| 1 | Magic | 6 | `CVAULT` identificação|
| 2 | Versão | 1 | Versão de formato |
| 3 | Flags | 1 | bit0=1 cifrado (reserva futura) |
| 4 | Meta_len | 2 | uint16 tamanho do JSON |
| 5 | Metadados | n | JSON `{filename,size}` |
| 6 | Pub_len | 2 | uint16 tamanho PEM chave pública |
| 7 | PubKey PEM | n | Chave pública do autor |
| 8 | AES_wrap_len | 2 | uint16 tamanho chave AES envolvida |
| 9 | AES_wrapped | n | Chave AES cifrada RSA-OAEP |
|10 | Sig_len | 2 | uint16 tamanho assinatura |
|11 | Assinatura | n | RSA-PSS(SHA-256) sobre plaintext |
|12 | Nonce | 12 | Nonce GCM (96 bits) |
|13 | Tag | 16 | Tag GCM (integridade simétrica) |
|14 | Ciphertext | resto | Dados cifrados |

Racional: formato direto facilita debugging e futura migração para cabeçalho
opaco (ex.: DER/CBOR) sem perder legibilidade interna do protótipo.

#### Variante v2 (para contacto)

Campos (ordem):
1) Magic; 2) Versão=2; 3) Flags; 4) Meta_len; 5) Metadados `{filename,size,sender_fp,recipient_fp,recipient_name?}`;
6) SenderPub_len; 7) SenderPub PEM; 8) RecipientPub_len; 9) RecipientPub PEM; 10) AES_wrapped_len; 11) AES_wrapped; 12) Sig_len; 13) Signature; 14) Nonce; 15) Tag; 16) Ciphertext.

Racional: permite cifrar para um destinatário externo preservando a autenticação do remetente.

## Estrutura de Diretórios e Papéis

```
src/
  ciphervault/
    __init__.py      -> expõe __version__
    crypto.py        -> operações criptográficas (KeyStore, SelfEncryptor)
    contacts.py      -> gestão de contactos (persistência JSON, validação PEM)
    cli.py           -> interface CLI (menu interativo + comandos diretos)
    archiving.py     -> comprime pastas para .zip temporário antes de cifrar (reutiliza encrypt_file/encrypt_for_contact sem alterações)
  main.py            -> ponto de entrada da CLI
  gui.py             -> interface gráfica completa (Dashboard, Vault, Contactos, Ferramentas, Settings)

launcher/
  launcher.ps1       -> Smart Launcher da CLI (venv + auto-update + arranque)
  launcher_gui.ps1   -> Smart Launcher da GUI (venv + auto-update + arranque sem consola)
  updater.py         -> lógica de verificação/aplicação de atualizações (partilhada por ambos os lançadores e pela GUI)

ciphervault.cmd      -> lançador Windows da CLI
start_gui.cmd        -> lançador Windows da GUI (consola visível durante o arranque)
CipherVault.vbs      -> lançador Windows da GUI, totalmente silencioso (sem consola)
DOCUMENTACAO.md      -> documentação completa (este ficheiro)
README.md            -> instruções rápidas de uso
requirements.txt     -> lista de dependências Python
```

### Módulo `crypto.py`
- `KeyStore`: garante existência e carregamento das chaves, gera fingerprint.
- `SelfEncryptor`: implementa cifrar e decifrar para o próprio; constrói/parceia o formato.

### Módulo `cli.py`
- Grupo principal Click: parse de opções, ativação de debug.
- Função `_interactive`: loop de menu: 1) Cifrar (self) 2) Cifrar para contacto 3) Decifrar 4) Partilhar chave (exportar PEM) 5) Contactos 6) Verificar autenticidade 7) Comparar ficheiros 8) Sair.
- Comandos individuais: `encrypt`, `encrypt-for-contact`, `decrypt`, `verify`, `compare-files`, `compare-with-vault`, `keys`, `public-key`, `export-public-key`, `contacts-list`, `contacts-add`, `contacts-delete`.
- Auxiliares: normalização de caminhos, exportação PEM, contactos via ficheiro PEM.

### Módulo `contacts.py`
- `ContactsStore`: armazena contactos em `~/.ciphervault/contacts.json`.
  - Cada contacto contém: `name`, `public_pem` (PEM), `fingerprint` (SHA-256 em hex do PEM).
  - Valida se o PEM fornecido é uma chave pública válida.
  - Operações: `add_contact`, `list_contacts`, `delete_contact`.

### `main.py`
- Proxy para `cli()` permitindo `python src/main.py`.

### `ciphervault.cmd`
- Conveniência Windows: abre consola separada e inicia modo interativo.
- Mostra versão, ajuda, e exemplos rápidos (incluindo contactos). Pode ser estendido para mostrar `export-public-key`.

## Opções Técnicas e Justificação

- RSA-4096 OAEP(SHA-256): segurança contra ataques de padding e robustez futura.
- AES-256-GCM: padrão industrial (AEAD) evitando necessidade separada de HMAC.
- RSA-PSS (SHA-256): assinatura moderna com randomização, mitigando ataques de forja.
- Fingerprint SHA-256: identificação humana rápida; pode evoluir para ID truncado etiquetado.
- PEM para chave pública: legibilidade e interoperabilidade; poderá migrar para DER (opacidade) em versão 1.2.x.
- Sem compressão automática: reduz complexidade; utilizador controla compressão (zip/rar) conforme necessidade.

## Limitações Atuais (v1.5.0)

- Suporta um destinatário por contentor (cifragem para um contacto de cada vez).
- Cabeçalho parcialmente legível (inclui PEM) – melhoria futura: versão opaca.
- Não suporta cifragem de múltiplos ficheiros em lote num único contentor.
- Chave privada sem proteção adicional (ex.: password / hardware token).
- Não há verificação de revogação/rotação automática de chaves.
 - Requer que o utilizador possua o ficheiro PEM da chave pública do contacto.

## Roadmap Proposto

### 1.2.x (Incremental)
- Cabeçalho binário opaco (DER/CBOR) ou substituição PEM por fingerprint.
- Opção de saída personalizada (`--out` / escolha no menu).
- Modo “ver detalhes” do contentor (inspeção sem decifrar total).

### 1.3.0 (Funcionalidade Nova)
- Gestão de contactos local (adicionar/listar/apagar) com validação do PEM público e fingerprint.
- Remoção da visualização de chave privada no CLI (redução de superfície de risco).

### 1.6.0 (Atual)
- **Smart Launcher:** Sistema de arranque inteligente que gere instalação de dependências e atualizações automáticas.
- **Auto-Update:** Verificação de versão contra repositório remoto e atualização "in-place" sem afetar dados do utilizador.
- **Multi-destinatários:** (Preparação) Estrutura de código pronta para suportar múltiplos destinatários.

### 1.5.0
- Relatório de Segurança Unificado (Metadados + Integridade + Autenticidade).
- Integração do comando `inspect` no `verify`.
- Tradução completa de comentários e documentação para Português.

### 1.6.x
- Modo assinatura apenas (gerar ficheiro + assinatura separada .sig).
- Integração opcional com hash de diretórios e manifestos.

### 2.0.0 (Potencial)
- Reformulação do formato com estrutura escalável (TLV / CBOR com índice).
- Rotação de chaves e metadados de política (algoritmos permitidos, expiração).

## Segurança – Resumo Executivo

- Confidencialidade: AES-256-GCM protege o conteúdo.
- Integridade: Tag GCM + assinatura RSA-PSS (dupla verificação: simétrica e assimétrica).
- Autenticidade: Garantida pela assinatura do plaintext (origem + não alteração).

### Detalhe dos Primitivos
- AES-256-GCM: modo AEAD; nonce único por cifragem (12 bytes). Reutilização de nonce com mesma chave é perigosa – mitigado pela geração aleatória.
- RSA-OAEP: adiciona máscara (MGF1) e digest para prevenir ataques de texto escolhido.
- RSA-PSS: usa salt aleatório, evitando determinismo e aumentando resistência a ataques.
- SHA-256: equilibrado entre segurança e ubiquidade.

### Superfície de Ataque e Mitigações
- Exposição da chave privada ⇒ comprometimento total. Mitigação futura: password / HSM.
- Modificação do contentor ⇒ assinatura ou tag falham (detetado).
- Colisões intencionais de fingerprint (SHA-256) são impraticáveis com recursos normais.

## Notas de Versão

- 1.0.1: Logs de debug, comando `keys`, versão CLI.
- 1.1.0: Tradução inicial documentação e mensagens PT-PT.
- 1.2.0: Menu interativo persistente; lançador `ciphervault.cmd`.
- 1.2.1: Visualização de chave pública/privada via menu e comandos (`public-key`, `private-key`) + comentários detalhados no código.
- 1.3.0: Contactos (adicionar/listar/apagar); remoção de visualização da chave privada; atualização de CLI e lançador.
- 1.3.1: Exportar chave pública para ficheiro PEM; adicionar contactos via caminho para ficheiro PEM; cifrar para um contacto (formato v2).
- 1.4.0: Comando `verify` para verificação de autenticidade/integridade sem escrever ficheiro decifrado.
- 1.4.1: Comandos `compare-files` (comparação direta SHA-256) e `compare-with-vault` (comparar conteúdo decifrado de .cvault com ficheiro claro).
- 1.5.0: Relatório de Segurança Unificado; integração de inspeção e verificação; tradução integral de comentários e documentação.
- 1.6.0-1.6.x: Smart Launcher (venv + auto-update) e temas visuais da CLI.
- 1.8.0: Consolidação das três variantes de GUI num único `src/gui.py` com separador Settings (verificar/aplicar atualizações e reiniciar automaticamente); novo lançador gráfico dedicado (`launcher_gui.ps1`, `CipherVault.vbs`, `start_gui.cmd`) com o mesmo fluxo de venv + auto-update da CLI; correção do `ciphervault.cmd` (código morto após o lançador) e limpeza de dependências não utilizadas; novo tema visual "Neon Glow" com o logótipo oficial integrado na GUI (barra lateral + ícone da janela); suporte a cifragem de pastas na GUI e na CLI via compressão automática para `.zip` (`src/ciphervault/archiving.py`), reutilizando as funções de cifragem existentes sem alterar o formato `.cvault`.
- 1.9.0: Navegação por página (uma função = uma página na barra lateral, sem separadores aninhados); ecrã de boas-vindas na primeira execução; notificações "toast" não-bloqueantes; animações subtis (fade-in, indicador a "respirar"); contagem de ficheiros/tamanho em segundo plano ao selecionar uma pasta; estatísticas de utilização no Dashboard; todas as páginas com scroll (`CTkScrollableFrame`) para nunca cortar conteúdo.

## Esquema de Versionamento

- Patch (x.y.Z): correções e melhorias pequenas sem alterar formato.
- Minor (x.Y.z): novas funcionalidades compatíveis (ex.: multi-destinatários, cabeçalho opaco).
- Major (X.y.z): mudanças de formato ou quebra de compatibilidade (ex.: estrutura binária radicalmente diferente).

## FAQ Rápida

**Porque é visível a chave pública no contentor?**
Facilita verificação e não prejudica segurança; apenas a chave privada permite decifrar.

**Porque assinar o plaintext e não o ciphertext?**
Assinar o plaintext torna explícita a integridade do conteúdo original e evita dependência do modo simétrico para autenticação completa.

**Posso partilhar um `.cvault` com outra pessoa?**
Sim, se o contentor tiver sido cifrado “para esse contacto” (v2). Para isso, primeiro obtenha o ficheiro PEM da chave pública do destinatário, adicione-o como contacto e use a opção “Cifrar para contacto”.

**O que acontece se alterar um byte do ficheiro?**
Tag GCM ou assinatura falham – o processo acusa corrupção.

**Posso cifrar pastas diretamente?**
Sim (a partir da v1.8.0). Tanto a GUI como a CLI aceitam uma pasta diretamente: é comprimida automaticamente para `.zip` (ver `src/ciphervault/archiving.py`) e cifrada pelas mesmas funções usadas para qualquer ficheiro; o `.zip` temporário é removido no final.

**O que é um ficheiro PEM?**
Formato de texto legível com cabeçalhos/rodapés (BEGIN/END PUBLIC KEY) contendo a chave em Base64. É o padrão para partilha de chaves públicas.

---

---

Para detalhes adicionais (multi-destinatários, cabeçalhos binários, integração
com manifestos ou assinatura isolada) evoluir conforme roadmap descrito.
