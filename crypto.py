import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


def _k():
    v = os.environ.get("EMAKTAB_ENC_KEY", "")
    if len(v) != 64:
        raise RuntimeError("EMAKTAB_ENC_KEY 64 hex kerak")
    return bytes.fromhex(v)


def encrypt(t):
    iv = os.urandom(16)
    p = padding.PKCS7(algorithms.AES.block_size).padder()
    pd = p.update(t.encode()) + p.finalize()
    c = Cipher(algorithms.AES(_k()), modes.CBC(iv))
    e = c.encryptor()
    return f"{iv.hex()}:{(e.update(pd) + e.finalize()).hex()}"


def decrypt(v):
    ih, dh = v.split(":", 1)
    c = Cipher(algorithms.AES(_k()), modes.CBC(bytes.fromhex(ih)))
    d = c.decryptor()
    pd = d.update(bytes.fromhex(dh)) + d.finalize()
    u = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return (u.update(pd) + u.finalize()).decode()