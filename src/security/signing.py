from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from src.execution.contracts import SignedNodeExecRequest, canonical_json


@dataclass(frozen=True)
class SigningKey:
    key_id: str
    secret: str


@dataclass
class SigningService:
    keys: dict[str, str]

    def sign(self, *, key_id: str, request_payload: dict) -> str:
        secret = self.keys.get(key_id)
        if secret is None:
            raise KeyError(f"unknown signing key id: {key_id}")
        body = canonical_json(request_payload).encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    def build_signed_request(self, *, key_id: str, request_payload: dict) -> SignedNodeExecRequest:
        from src.execution.contracts import NodeExecRequest

        signature = self.sign(key_id=key_id, request_payload=request_payload)
        return SignedNodeExecRequest(
            key_id=key_id,
            signature=signature,
            request=NodeExecRequest.from_payload(request_payload),
        )

    def verify(self, *, key_id: str, request_payload: dict, signature: str) -> bool:
        expected = self.sign(key_id=key_id, request_payload=request_payload)
        return hmac.compare_digest(expected, signature)
