"""企业微信回调的签名校验与消息加解密（W4-CHAN-02A）。

协议来源：企业微信开放平台"接收消息与事件"（developer.work.weixin.qq.com/document/path/90930）。
与微信公众平台 WXBizMsgCrypt 同源 —— EncodingAESKey 是 43 位 base64 字符串，
补 "=" 后 base64 解码得 32 字节 AESKey（AES-256-CBC），IV = AESKey[:16]。

加解密明文布局：random(16B) + msg_len(4B big-endian) + msg + receiveid
PKCS#7 填充（块长 32）。

签名：SHA1(sort(token, timestamp, nonce, encrypt))。

被动回复（同步响应）格式：
    <xml>
      <Encrypt><![CDATA[msg_encrypt]]></Encrypt>
      <MsgSignature><![CDATA[msg_signature]]></MsgSignature>
      <TimeStamp><time></TimeStamp>
      <Nonce><![CDATA[nonce]]></Nonce>
    </xml>
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class CryptoError(RuntimeError):
    """加解密/验签失败时抛出；调用方捕获后返回 400 或吞掉。"""


# ---------------------------------------------------------------------------
# 加解密核心
# ---------------------------------------------------------------------------

class WeComCrypto:
    """企微回调的加解密 + 签名工具。

    EncodingAESKey 是用户在企微后台填的 43 位 base64 字符串；
    token 是签名用的自定义字符串；receive_id 是企微 CorpID
    （解密/加密时要校验的标识）。
    """

    BLOCK_SIZE = 32  # PKCS#7 块长（AES-256 的 key 字节数）
    RANDOM_LEN = 16
    MSG_LEN_LEN = 4  # msg_len 字段占 4 字节

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        self.token = token
        self.receive_id = receive_id
        # AESKey：43 位 EncodingAESKey 补 "=" 后 base64 decode → 32 字节
        padded = encoding_aes_key + "="
        self._aes_key = base64.b64decode(padded)
        if len(self._aes_key) != 32:
            raise CryptoError(
                f"EncodingAESKey 解码后应为 32 字节，实际 {len(self._aes_key)}"
            )
        self._iv = self._aes_key[:16]

    # --- 验签 -------------------------------------------------------------

    def verify_signature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypt: str
    ) -> bool:
        """校验 msg_signature = SHA1(sort(token, timestamp, nonce, encrypt))。"""
        expected = hashlib.sha1(
            "".join(sorted([self.token, timestamp, nonce, encrypt])).encode()
        ).hexdigest()
        return expected == msg_signature

    # --- 解密 -------------------------------------------------------------

    def decrypt(self, encrypt: str) -> str:
        """解密密文，返回明文 msg。

        Raises:
            CryptoError: base64 解码失败 / 解密失败 / receive_id 校验不通过 / msg_len 越界。
        """
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:  # noqa: BLE001
            raise CryptoError("pycryptodome 未安装") from exc

        try:
            ciphertext = base64.b64decode(encrypt + "=")
        except Exception as exc:  # noqa: BLE001
            raise CryptoError(f"encrypt base64 解码失败: {exc}") from exc

        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        plaintext = self._pkcs7_unpad(cipher.decrypt(ciphertext))

        # 明文布局：random(16) + msg_len(4) + msg + receive_id
        if len(plaintext) < self.RANDOM_LEN + self.MSG_LEN_LEN:
            raise CryptoError("解密后明文长度不足")
        msg_len = int.from_bytes(
            plaintext[self.RANDOM_LEN : self.RANDOM_LEN + self.MSG_LEN_LEN],
            byteorder="big",
            signed=False,
        )
        msg_end = self.RANDOM_LEN + self.MSG_LEN_LEN + msg_len
        if msg_end > len(plaintext):
            raise CryptoError("msg_len 越界")
        msg = plaintext[self.RANDOM_LEN + self.MSG_LEN_LEN : msg_end].decode("utf-8")
        receive_id_from_encrypt = plaintext[msg_end:].decode("utf-8", errors="replace")
        if receive_id_from_encrypt != self.receive_id:
            log.warning(
                "企微解密 receive_id 不匹配：期望 %r，实际 %r",
                self.receive_id,
                receive_id_from_encrypt,
            )
        return msg

    # --- 加密（被动回复） --------------------------------------------------

    def encrypt(self, msg: str, nonce: str, timestamp: str | None = None) -> dict[str, str]:
        """加密被动回复消息，返回 XML 各字段 dict。

        Returns:
            {"Encrypt": ..., "MsgSignature": ..., "TimeStamp": ..., "Nonce": nonce}
        """
        try:
            from Crypto.Cipher import AES
        except ImportError as exc:  # noqa: BLE001
            raise CryptoError("pycryptodome 未安装") from exc

        timestamp = timestamp or str(int(time.time()))
        random_bytes = os.urandom(self.RANDOM_LEN)
        msg_bytes = msg.encode("utf-8")
        full_plaintext = (
            random_bytes
            + len(msg_bytes).to_bytes(self.MSG_LEN_LEN, byteorder="big")
            + msg_bytes
            + self.receive_id.encode("utf-8")
        )
        padded = self._pkcs7_pad(full_plaintext)
        cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
        encrypted = base64.b64encode(cipher.encrypt(padded)).decode("ascii")

        signature = hashlib.sha1(
            "".join(sorted([self.token, timestamp, nonce, encrypted])).encode()
        ).hexdigest()
        return {
            "Encrypt": encrypted,
            "MsgSignature": signature,
            "TimeStamp": timestamp,
            "Nonce": nonce,
        }

    # --- PKCS#7 ---------------------------------------------------------

    @classmethod
    def _pkcs7_pad(cls, data: bytes) -> bytes:
        pad_len = cls.BLOCK_SIZE - len(data) % cls.BLOCK_SIZE
        return data + bytes([pad_len] * pad_len)

    @classmethod
    def _pkcs7_unpad(cls, data: bytes) -> bytes:
        pad_len = data[-1]
        if pad_len < 1 or pad_len > cls.BLOCK_SIZE:
            raise CryptoError("PKCS#7 unpad 失败（填充字节越界）")
        if data[-pad_len:] != bytes([pad_len] * pad_len):
            raise CryptoError("PKCS#7 unpad 失败（填充内容不匹配）")
        return data[:-pad_len]


# ---------------------------------------------------------------------------
# 顶层便捷函数（controller 用）
# ---------------------------------------------------------------------------

def build_passive_reply_xml(parts: dict[str, str]) -> str:
    """把 WeComCrypto.encrypt() 产出的 dict 拼回被动回复 XML 字符串。"""
    return (
        "<xml>"
        "<Encrypt><![CDATA[{Encrypt}]]></Encrypt>"
        "<MsgSignature><![CDATA[{MsgSignature}]]></MsgSignature>"
        "<TimeStamp>{TimeStamp}</TimeStamp>"
        "<Nonce><![CDATA[{Nonce}]]></Nonce>"
        "</xml>"
    ).format(**parts)


__all__ = ["CryptoError", "WeComCrypto", "build_passive_reply_xml"]
