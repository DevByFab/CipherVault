import os
import json
import struct
import logging
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

# =============================================================
# Módulo crypto
# -------------------------------------------------------------
# Responsável por:
#   - Gestão do par de chaves RSA do utilizador (KeyStore)
#   - Cifragem híbrida (AES-256-GCM + RSA-OAEP) e assinatura (RSA-PSS)
#   - Formato do contentor .cvault (auto‑descritivo para uso próprio)
#
# Conceitos-Chave:
#   AES-256-GCM: confidencialidade + integridade (tag de 16 bytes)
#   RSA-OAEP: envolve / protege a chave simétrica (anti padding-oracle)
#   RSA-PSS: assinatura probabilística resistente a ataques de forja
#   SHA-256: função de hash usada em fingerprint e assinatura
# =============================================================

logger = logging.getLogger("ciphervault")


class KeyStore:
    """Gere o par de chaves RSA do utilizador em ~/.ciphervault

    - Cria diretoria base se não existir.
    - Gera par RSA-4096 na primeira execução (PKCS#8 sem password).
    - Carrega chaves já existentes se presentes.
    - Fornece fingerprint SHA-256 (hex) para identificação humana.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or (Path.home() / ".ciphervault")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.private_key_path = self.base_dir / "private_key.pem"
        self.public_key_path = self.base_dir / "public_key.pem"
        self.private_key = None
        self.public_key = None
        logger.debug(f"KeyStore inicializado em: {self.base_dir}")

    def ensure_keys(self) -> None:
        """Garante que o par de chaves está disponível em memória.

        - Se não existir, gera novo par.
        - Se existir, carrega o par para self.private_key / self.public_key.
        """
        if self.private_key_path.exists() and self.public_key_path.exists():
            logger.debug("Chaves encontradas no disco; a carregar par existente.")
            self._load()
        else:
            logger.debug("Nenhuma chave encontrada; a gerar novo par RSA-4096.")
            self._generate()

    def _generate(self) -> None:
        """Gera novas chaves RSA-4096 e persiste em PEM.

        Segurança:
        - Sem password: simplifica protótipo (pode ser adicionada proteção futura).
        - chmod 600 (melhor esforço) em sistemas compatíveis.
        """
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        self.public_key = self.private_key.public_key()

        self.private_key_path.write_bytes(
            self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        try:
            os.chmod(self.private_key_path, 0o600)
        except Exception:
            # Em Windows pode não ter efeito; ignoramos silenciosamente.
            pass
        logger.debug(f"Chave privada escrita: {self.private_key_path}")

        self.public_key_path.write_bytes(
            self.public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        logger.debug(f"Chave pública escrita: {self.public_key_path}")

    def _load(self) -> None:
        """Carrega chaves existentes do disco.

        Confiança: assume-se que ficheiros não foram adulterados; validação
        adicional (hash assinado) poderia ser futura melhoria.
        """
        self.private_key = serialization.load_pem_private_key(
            self.private_key_path.read_bytes(), password=None
        )
        self.public_key = self.private_key.public_key()
        logger.debug(f"Chave privada carregada de: {self.private_key_path}")
        logger.debug(f"Chave pública carregada de: {self.public_key_path}")

    def get_public_pem(self) -> bytes:
        if not self.public_key:
            self.ensure_keys()
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def get_fingerprint_hex(self) -> str:
        """Retorna fingerprint SHA-256 da chave pública em hexadecimal.

        Utilidade:
        - Verificação visual rápida (ex: primeiras 16–32 hex) entre máquinas.
        - Não é um identificador criptograficamente forte para evitar colisões
          intencionais, mas suficiente para uso humano.
        """
        pub = self.get_public_pem()
        d = hashes.Hash(hashes.SHA256())
        d.update(pub)
        return d.finalize().hex()


class SelfEncryptor:
    """Cifragem/Decifragem local ("para mim") usando RSA-4096 + AES-256-GCM.

    Formato do contentor `.cvault` (sequência EXACTA):
      1. Magic               (6 bytes)   => b"CVAULT" para identificação rápida
      2. Versão              (1 byte)    => permite evolução futura
      3. Flags               (1 byte)    => bit0=1 indica conteúdo cifrado (reserva para outros bits)
      4. Metadados_len       (2 bytes)   => uint16 tamanho do JSON
      5. Metadados JSON      (n bytes)   => {"filename":…, "size":…}
      6. PubKey_len          (2 bytes)
      7. PubKey PEM          (n bytes)   => chave pública do autor (auto‑contido)
      8. AES_wrapped_len     (2 bytes)
      9. AES_wrapped         (n bytes)   => chave AES cifrada via RSA-OAEP
     10. Signature_len       (2 bytes)
     11. Signature           (n bytes)   => RSA-PSS(SHA-256) sobre hash do plaintext
     12. Nonce GCM           (12 bytes)  => recomendado 96 bits
     13. Tag GCM             (16 bytes)  => integridade/autenticidade simétrica
     14. Ciphertext          (restante)  => dados cifrados AES-256-GCM

    Notas:
    - Public Key embutida facilita verificação futura sem depender de ficheiros externos.
    - Assinatura garante que plaintext não foi modificado antes/após cifragem.
    - Estrutura simples de parse; pode ser tornada binária opaca em versões futuras.
    """

    MAGIC = b"CVAULT"
    VERSION_SELF = 1   # v1: contentor "para mim" (apenas chave pública local)
    VERSION_CONTACT = 2  # v2: contentor cifrado para um contacto (inclui chave pública do remetente + destinatário)

    def __init__(self, keystore: Optional[KeyStore] = None):
        self.keystore = keystore or KeyStore()
        self.keystore.ensure_keys()

    def _key_id(self, public_pem: bytes) -> bytes:
        """Deriva identificador curto (16 bytes) da chave pública.

        Usado internamente se necessário para referência futura (não persistido
        no formato atual). Mantido para extensibilidade.
        """
        digest = hashes.Hash(hashes.SHA256())
        digest.update(public_pem)
        return digest.finalize()[:16]

    def encrypt_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Cifra um ficheiro arbitrário e produz contentor `.cvault`.

        Etapas principais:
          (1) Ler plaintext
          (2) Gerar chave AES + nonce
          (3) Cifrar dados com AES-GCM
          (4) Envolver chave AES com RSA-OAEP
          (5) Assinar hash SHA-256 do plaintext com RSA-PSS
          (6) Escrever contentor estruturado
        """
        input_path = Path(input_path)
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"Ficheiro não encontrado: {input_path}")

        data = input_path.read_bytes()
        filename = input_path.name
        logger.debug(f"A cifrar ficheiro: {input_path} (tamanho={len(data)} bytes)")

        # === BLOCO: GERAÇÃO DE SEGREDOS SIMÉTRICOS ===
        # GERAÇÃO: chave simétrica AES-256 (32 bytes aleatórios)
        aes_key = os.urandom(32)  # 256 bits
        # GERAÇÃO: nonce GCM (12 bytes único) – nunca reutilizar com mesma chave
        nonce = os.urandom(12)    # 96 bits recomendado para GCM
        logger.debug("Gerada chave AES-256 e nonce GCM de 12 bytes.")

        # === BLOCO: CIFRAGEM SIMÉTRICA ===
        # INSTANCIA: objeto de cifragem AES-GCM com chave e nonce
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce))
        encryptor = cipher.encryptor()
        # OPERAÇÃO: cifragem do plaintext; finalize() sela e produz tag
        ciphertext = encryptor.update(data) + encryptor.finalize()
        tag = encryptor.tag  # CAPTURA: tag de autenticação (16 bytes)
        logger.debug(f"Cifragem AES-GCM concluída. tag_len={len(tag)} bytes, ciphertext_len={len(ciphertext)} bytes.")

        # === BLOCO: ENVOLTURA DA CHAVE AES ===
        # ENVOLTURA: chave AES cifrada com RSA-OAEP (usa SHA-256) garantindo sigilo da chave simétrica
        encrypted_aes_key = self.keystore.public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )  # RESULTADO: bytes da chave envolvida
        logger.debug(f"Chave AES envolvida com RSA-OAEP. wrapped_len={len(encrypted_aes_key)} bytes.")

        # === BLOCO: ASSINATURA DO CONTEÚDO ORIGINAL ===
        # HASH: produzir digest SHA-256 do plaintext
        d = hashes.Hash(hashes.SHA256())
        d.update(data)
        file_hash = d.finalize()
        # ASSINATURA: RSA-PSS sobre hash SHA-256 – autentica autor + integridade
        signature = self.keystore.private_key.sign(
            file_hash,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )  # RESULTADO: bytes da assinatura variável (dependente de chave)
        logger.debug(f"Hash do plaintext assinado com RSA-PSS. signature_len={len(signature)} bytes.")

        # === BLOCO: PREPARAÇÃO DE METADADOS ===
        # METADADOS: nome e tamanho para reconstrução simplificada na decifragem
        public_pem = self.keystore.get_public_pem()
        fp = self.keystore.get_fingerprint_hex()
        metadata = {
            "filename": filename, 
            "size": len(data),
            "created_by": "CipherVault 1.5.0"
        }
        metadata_json = json.dumps(metadata).encode("utf-8")

        if output_path is None:
            output_path = input_path.with_suffix(input_path.suffix + ".cvault")

        # === BLOCO: SERIALIZAÇÃO DO CONTENTOR .cvault ===
        with open(output_path, "wb") as f:
            f.write(self.MAGIC)                                   # [1] Magic
            f.write(struct.pack("B", self.VERSION_SELF))         # [2] Versão
            f.write(struct.pack("B", 0x01))                     # [3] Flags (bit0=encrypted)
            f.write(struct.pack("H", len(metadata_json)))       # [4] Tam metadados
            f.write(metadata_json)                               # [5] Metadados JSON

            f.write(struct.pack("H", len(public_pem)))          # [6] Tam chave pública PEM
            f.write(public_pem)                                  # [7] Chave pública PEM

            f.write(struct.pack("H", len(encrypted_aes_key)))   # [8] Tam chave AES envolvida
            f.write(encrypted_aes_key)                           # [9] Chave AES envolvida

            f.write(struct.pack("H", len(signature)))           # [10] Tam assinatura
            f.write(signature)                                   # [11] Assinatura RSA-PSS

            f.write(nonce)                                       # [12] Nonce GCM
            f.write(tag)                                         # [13] Tag GCM
            f.write(ciphertext)                                  # [14] Ciphertext
        logger.debug(f"Ficheiro .cvault escrito: {output_path} (fp_chave_pub={fp[:16]}…)")
        return output_path

    def encrypt_for_contact(self, input_path: Path, contact_public_pem: bytes, output_path: Optional[Path] = None, recipient_name: str | None = None) -> Path:
        """Cifra um ficheiro para um contacto usando a CHAVE PÚBLICA desse contacto.

        Formato v2 (VERSION_CONTACT):
          1. Magic
          2. Versão (2)
          3. Flags (bit0=encrypted)
          4. Meta_len (uint16)
          5. Metadados JSON {filename,size,recipient_name?,sender_fp,recipient_fp}
          6. SenderPub_len (uint16)
          7. SenderPub PEM (remetente)
          8. RecipientPub_len (uint16)
          9. RecipientPub PEM (destinatário)
         10. AES_wrapped_len (uint16)
         11. AES_wrapped (cifrada com recipient pub)
         12. Signature_len (uint16)
         13. Signature (RSA-PSS do hash plaintext usando private do remetente)
         14. Nonce (12)
         15. Tag (16)
         16. Ciphertext (resto)

        Decifração posterior: destinatário usa private key local. Autenticidade do remetente verificada pela assinatura.
        """
        input_path = Path(input_path)
        if not input_path.exists() or not input_path.is_file():
            raise FileNotFoundError(f"Ficheiro não encontrado: {input_path}")

        data = input_path.read_bytes()
        filename = input_path.name
        logger.debug(f"A cifrar PARA CONTACTO: {input_path} (tamanho={len(data)} bytes)")

        # Segredos simétricos
        aes_key = os.urandom(32)
        nonce = os.urandom(12)

        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()
        tag = encryptor.tag

        # Envolver AES com a chave pública do CONTACTO
        recipient_pub = serialization.load_pem_public_key(contact_public_pem)
        wrapped_aes = recipient_pub.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        # Assinatura do remetente
        d = hashes.Hash(hashes.SHA256()); d.update(data); file_hash = d.finalize()
        signature = self.keystore.private_key.sign(
            file_hash,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        sender_pub_pem = self.keystore.get_public_pem()
        sender_fp = self.keystore.get_fingerprint_hex()
        # Fingerprint do destinatário
        d2 = hashes.Hash(hashes.SHA256()); d2.update(contact_public_pem); recipient_fp = d2.finalize().hex()

        meta = {
            "filename": filename,
            "size": len(data),
            "sender_fp": sender_fp,
            "recipient_fp": recipient_fp,
        }
        if recipient_name:
            meta["recipient_name"] = recipient_name
        meta_json = json.dumps(meta).encode("utf-8")

        if output_path is None:
            output_path = input_path.with_suffix(input_path.suffix + ".cvault")

        with open(output_path, "wb") as f:
            f.write(self.MAGIC)                                   # [1]
            f.write(struct.pack("B", self.VERSION_CONTACT))     # [2]
            f.write(struct.pack("B", 0x01))                     # [3]
            f.write(struct.pack("H", len(meta_json)))           # [4]
            f.write(meta_json)                                   # [5]
            f.write(struct.pack("H", len(sender_pub_pem)))      # [6]
            f.write(sender_pub_pem)                              # [7]
            f.write(struct.pack("H", len(contact_public_pem)))  # [8]
            f.write(contact_public_pem)                          # [9]
            f.write(struct.pack("H", len(wrapped_aes)))         # [10]
            f.write(wrapped_aes)                                 # [11]
            f.write(struct.pack("H", len(signature)))           # [12]
            f.write(signature)                                   # [13]
            f.write(nonce)                                       # [14]
            f.write(tag)                                         # [15]
            f.write(ciphertext)                                  # [16]
        logger.debug(f"Ficheiro .cvault (v2) escrito: {output_path} (recipient_fp={recipient_fp[:16]}… sender_fp={sender_fp[:16]}…)")
        return output_path

    def decrypt_file(self, vault_path: Path, output_path: Optional[Path] = None) -> Path:
        """Decifra contentor `.cvault` previamente produzido por `encrypt_file`.

        Verificações:
          - Magic & versão
          - Chave pública embutida == chave local (garante que foi "para mim")
          - Integridade simétrica (GCM tag)
          - Autenticidade (assinatura RSA-PSS sobre plaintext recuperado)
        """
        vault_path = Path(vault_path)
        if not vault_path.exists() or not vault_path.is_file():
            raise FileNotFoundError(f"Ficheiro não encontrado: {vault_path}")

        with open(vault_path, "rb") as f:
            magic = f.read(6)                        # [1] Magic
            if magic != self.MAGIC:
                raise ValueError("Formato de ficheiro inválido (magic)")
            version = struct.unpack("B", f.read(1))[0]  # [2] Versão
            if version not in (self.VERSION_SELF, self.VERSION_CONTACT):
                raise ValueError(f"Versão não suportada: {version}")
            flags = struct.unpack("B", f.read(1))[0]    # [3] Flags
            meta_len = struct.unpack("H", f.read(2))[0] # [4] Tam metadados
            metadata = json.loads(f.read(meta_len).decode("utf-8"))  # [5] Metadados

            if version == self.VERSION_SELF:
                pub_len = struct.unpack("H", f.read(2))[0]    # [6]
                sender_pub_pem = f.read(pub_len)               # [7] (neste caso é também destinatário)
                key_len = struct.unpack("H", f.read(2))[0]    # [8]
                encrypted_aes_key = f.read(key_len)            # [9]
                sig_len = struct.unpack("H", f.read(2))[0]    # [10]
                signature = f.read(sig_len)                    # [11]
                nonce = f.read(12)                             # [12]
                tag = f.read(16)                               # [13]
                ciphertext = f.read()                          # [14]
                recipient_pub_pem = sender_pub_pem
                logger.debug("Contentor v1 lido (self). meta=%s", metadata)
            else:  # VERSION_CONTACT
                sender_pub_len = struct.unpack("H", f.read(2))[0]     # [6]
                sender_pub_pem = f.read(sender_pub_len)                # [7]
                recipient_pub_len = struct.unpack("H", f.read(2))[0]  # [8]
                recipient_pub_pem = f.read(recipient_pub_len)          # [9]
                key_len = struct.unpack("H", f.read(2))[0]            # [10]
                encrypted_aes_key = f.read(key_len)                    # [11]
                sig_len = struct.unpack("H", f.read(2))[0]            # [12]
                signature = f.read(sig_len)                            # [13]
                nonce = f.read(12)                                     # [14]
                tag = f.read(16)                                       # [15]
                ciphertext = f.read()                                  # [16]
                logger.debug("Contentor v2 lido (para contacto). meta=%s", metadata)

        # === VALIDAR DESTINATÁRIO ===
        my_pub_pem = self.keystore.get_public_pem()
        if recipient_pub_pem != my_pub_pem:
            raise PermissionError("Este ficheiro não foi cifrado para a SUA chave pública.")
        else:
            logger.debug("Destinatário confirmado (fingerprint local=%s)", self.keystore.get_fingerprint_hex()[:32])

        # Recuperar chave AES
        aes_key = self.keystore.private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        # === BLOCO: DECIFRAGEM SIMÉTRICA ===
        # INSTANCIA: preparação descifragem GCM (inclui nonce + tag para validação)
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        # OPERAÇÃO: descifragem; finalize() valida tag (integridade)
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        logger.debug("Decifragem AES-GCM finalizada.")

        # Verificar assinatura (usa chave do remetente)
        sender_pub = serialization.load_pem_public_key(sender_pub_pem)
        d = hashes.Hash(hashes.SHA256())
        d.update(plaintext)
        file_hash = d.finalize()
        try:
            sender_pub.verify(
                signature,
                file_hash,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
        except Exception as e:
            # Assinatura inválida: alerta e falha
            raise ValueError("Assinatura inválida: ficheiro alterado ou chave incorreta") from e
        logger.debug("Assinatura verificada com sucesso (RSA-PSS/SHA-256).")

        # Determine output path
        if output_path is None:
            output_path = vault_path.parent / metadata.get("filename", vault_path.stem)

        Path(output_path).write_bytes(plaintext)
        logger.debug(f"Ficheiro decifrado escrito: {output_path} (tamanho={len(plaintext)} bytes)")
        return output_path

    def verify_authenticity(self, vault_path: Path) -> dict:
        """Verifica a autenticidade (assinatura RSA-PSS) e integridade (tag GCM) de um contentor.

        Não escreve o plaintext decifrado. Retorna dicionário com:
          {
            'version': <int>,
            'filename': <str>,
            'size': <int>,
            'sender_fp': <str>,
            'recipient_fp': <str>,
            'authenticity_ok': <bool>,
            'integrity_ok': <bool>
          }
        Lança exceções em caso de formato inválido ou destinatário incorreto.
        """
        vault_path = Path(vault_path)
        if not vault_path.exists() or not vault_path.is_file():
            raise FileNotFoundError(f"Ficheiro não encontrado: {vault_path}")

        with open(vault_path, "rb") as f:
            magic = f.read(6)
            if magic != self.MAGIC:
                raise ValueError("Formato de ficheiro inválido (magic)")
            version = struct.unpack("B", f.read(1))[0]
            if version not in (self.VERSION_SELF, self.VERSION_CONTACT):
                raise ValueError(f"Versão não suportada: {version}")
            flags = struct.unpack("B", f.read(1))[0]
            meta_len = struct.unpack("H", f.read(2))[0]
            metadata = json.loads(f.read(meta_len).decode("utf-8"))
            if version == self.VERSION_SELF:
                sender_pub_len = struct.unpack("H", f.read(2))[0]
                sender_pub_pem = f.read(sender_pub_len)
                recipient_pub_pem = sender_pub_pem
                key_len = struct.unpack("H", f.read(2))[0]
                encrypted_aes_key = f.read(key_len)
                sig_len = struct.unpack("H", f.read(2))[0]
                signature = f.read(sig_len)
                nonce = f.read(12)
                tag = f.read(16)
                ciphertext = f.read()
            else:  # VERSION_CONTACT
                sender_pub_len = struct.unpack("H", f.read(2))[0]
                sender_pub_pem = f.read(sender_pub_len)
                recipient_pub_len = struct.unpack("H", f.read(2))[0]
                recipient_pub_pem = f.read(recipient_pub_len)
                key_len = struct.unpack("H", f.read(2))[0]
                encrypted_aes_key = f.read(key_len)
                sig_len = struct.unpack("H", f.read(2))[0]
                signature = f.read(sig_len)
                nonce = f.read(12)
                tag = f.read(16)
                ciphertext = f.read()

        my_pub_pem = self.keystore.get_public_pem()
        if recipient_pub_pem != my_pub_pem:
            raise PermissionError("Este ficheiro não foi cifrado para a SUA chave pública.")

        # Integridade (GCM): tentar decifrar; se falhar lança exceção
        aes_key = self.keystore.private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        integrity_ok = True
        try:
            cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce, tag))
            decryptor = cipher.decryptor()
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        except Exception:
            integrity_ok = False
            plaintext = b""

        sender_pub = serialization.load_pem_public_key(sender_pub_pem)
        d = hashes.Hash(hashes.SHA256()); d.update(plaintext); file_hash = d.finalize()
        authenticity_ok = False
        if integrity_ok:
            try:
                sender_pub.verify(
                    signature,
                    file_hash,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    hashes.SHA256(),
                )
                authenticity_ok = True
            except Exception:
                authenticity_ok = False

        # Fingerprints
        sd = hashes.Hash(hashes.SHA256()); sd.update(sender_pub_pem); sender_fp = sd.finalize().hex()
        rd = hashes.Hash(hashes.SHA256()); rd.update(recipient_pub_pem); recipient_fp = rd.finalize().hex()

        return {
            "version": version,
            "filename": metadata.get("filename"),
            "size": metadata.get("size"),
            "sender_fp": sender_fp,
            "recipient_fp": recipient_fp,
            "authenticity_ok": authenticity_ok,
            "integrity_ok": integrity_ok,
        }

    def decrypt_to_bytes(self, vault_path: Path) -> tuple[bytes, dict]:
        """Decifra um contentor .cvault e devolve (plaintext, metadata).

        Verifica integridade e assinatura. Lança erros se algo falhar.
        Não escreve o ficheiro no disco.
        """
        vault_path = Path(vault_path)
        if not vault_path.exists() or not vault_path.is_file():
            raise FileNotFoundError(f"Ficheiro não encontrado: {vault_path}")
        with open(vault_path, "rb") as f:
            magic = f.read(6)
            if magic != self.MAGIC:
                raise ValueError("Formato inválido (magic)")
            version = struct.unpack("B", f.read(1))[0]
            if version not in (self.VERSION_SELF, self.VERSION_CONTACT):
                raise ValueError("Versão não suportada")
            flags = struct.unpack("B", f.read(1))[0]
            meta_len = struct.unpack("H", f.read(2))[0]
            metadata = json.loads(f.read(meta_len).decode("utf-8"))
            if version == self.VERSION_SELF:
                pub_len = struct.unpack("H", f.read(2))[0]
                sender_pub_pem = f.read(pub_len)
                recipient_pub_pem = sender_pub_pem
                key_len = struct.unpack("H", f.read(2))[0]
                encrypted_aes_key = f.read(key_len)
                sig_len = struct.unpack("H", f.read(2))[0]
                signature = f.read(sig_len)
                nonce = f.read(12)
                tag = f.read(16)
                ciphertext = f.read()
            else:
                sender_pub_len = struct.unpack("H", f.read(2))[0]
                sender_pub_pem = f.read(sender_pub_len)
                recipient_pub_len = struct.unpack("H", f.read(2))[0]
                recipient_pub_pem = f.read(recipient_pub_len)
                key_len = struct.unpack("H", f.read(2))[0]
                encrypted_aes_key = f.read(key_len)
                sig_len = struct.unpack("H", f.read(2))[0]
                signature = f.read(sig_len)
                nonce = f.read(12)
                tag = f.read(16)
                ciphertext = f.read()

        if recipient_pub_pem != self.keystore.get_public_pem():
            raise PermissionError("Contentor não destinado à sua chave")

        aes_key = self.keystore.private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        sender_pub = serialization.load_pem_public_key(sender_pub_pem)
        d = hashes.Hash(hashes.SHA256()); d.update(plaintext); file_hash = d.finalize()
        sender_pub.verify(
            signature,
            file_hash,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        metadata["version"] = version
        return plaintext, metadata

    def inspect_file(self, vault_path: Path) -> dict:
        """Lê os metadados do cabeçalho .cvault sem decifrar o conteúdo.

        Retorna dicionário com:
          - version: int
          - filename: str
          - size: int
          - sender_fp: str (fingerprint)
          - recipient_fp: str (fingerprint)
          - is_for_me: bool (se a chave de destino corresponde à minha)
          - has_signature: bool (sempre True neste design)
        """
        vault_path = Path(vault_path)
        if not vault_path.exists() or not vault_path.is_file():
            raise FileNotFoundError(f"Ficheiro não encontrado: {vault_path}")

        with open(vault_path, "rb") as f:
            magic = f.read(6)
            if magic != self.MAGIC:
                raise ValueError("Formato de ficheiro inválido (magic)")
            version = struct.unpack("B", f.read(1))[0]
            if version not in (self.VERSION_SELF, self.VERSION_CONTACT):
                raise ValueError(f"Versão não suportada: {version}")
            flags = struct.unpack("B", f.read(1))[0]
            meta_len = struct.unpack("H", f.read(2))[0]
            metadata = json.loads(f.read(meta_len).decode("utf-8"))

            if version == self.VERSION_SELF:
                sender_pub_len = struct.unpack("H", f.read(2))[0]
                sender_pub_pem = f.read(sender_pub_len)
                recipient_pub_pem = sender_pub_pem
            else:  # VERSION_CONTACT
                sender_pub_len = struct.unpack("H", f.read(2))[0]
                sender_pub_pem = f.read(sender_pub_len)
                recipient_pub_len = struct.unpack("H", f.read(2))[0]
                recipient_pub_pem = f.read(recipient_pub_len)

        # Calcular fingerprints
        sd = hashes.Hash(hashes.SHA256()); sd.update(sender_pub_pem); sender_fp = sd.finalize().hex()
        rd = hashes.Hash(hashes.SHA256()); rd.update(recipient_pub_pem); recipient_fp = rd.finalize().hex()

        # Verificar se é para mim
        my_pub_pem = self.keystore.get_public_pem()
        is_for_me = (recipient_pub_pem == my_pub_pem)

        return {
            "version": version,
            "filename": metadata.get("filename", "Desconhecido"),
            "size": metadata.get("size", 0),
            "sender_fp": sender_fp,
            "recipient_fp": recipient_fp,
            "is_for_me": is_for_me,
            "has_signature": True  # Por design, todos têm
        }
