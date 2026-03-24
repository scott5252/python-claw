from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerSandboxDescriptor:
    image: str
    read_only_root: bool = True
    network_disabled: bool = True
    run_as_user: str = "sandbox"
