import json
from pathlib import Path
from typing import List, Dict

from cryptography.hazmat.primitives import hashes, serialization


class ContactsStore:
    """Armazena contactos (nome + chave pública PEM) em ~/.ciphervault/contacts.json

    Cada contacto:
      - name: str (único)
      - public_pem: str (PEM)
      - fingerprint: str (SHA-256 do PEM em hex)
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or (Path.home() / ".ciphervault")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.contacts_path = self.base_dir / "contacts.json"
        if not self.contacts_path.exists():
            self._write_all([])

    def _read_all(self) -> List[Dict[str, str]]:
        try:
            return json.loads(self.contacts_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write_all(self, items: List[Dict[str, str]]) -> None:
        self.contacts_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _fingerprint(pub_pem_bytes: bytes) -> str:
        d = hashes.Hash(hashes.SHA256())
        d.update(pub_pem_bytes)
        return d.finalize().hex()

    @staticmethod
    def _validate_public_pem(pem_bytes: bytes) -> None:
        # Lança exceção se não for um PEM de chave pública válido
        serialization.load_pem_public_key(pem_bytes)

    def list_contacts(self) -> List[Dict[str, str]]:
        return self._read_all()

    def add_contact(self, name: str, public_pem: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Nome do contacto não pode estar vazio")
        pem_bytes = public_pem.encode("utf-8")
        self._validate_public_pem(pem_bytes)
        fp = self._fingerprint(pem_bytes)

        items = self._read_all()
        if any(c.get("name") == name for c in items):
            raise ValueError(f"Já existe um contacto com o nome '{name}'")
        items.append({"name": name, "public_pem": public_pem, "fingerprint": fp})
        self._write_all(items)

    def delete_contact(self, name: str) -> bool:
        name = name.strip()
        items = self._read_all()
        new_items = [c for c in items if c.get("name") != name]
        changed = len(new_items) != len(items)
        if changed:
            self._write_all(new_items)
        return changed
