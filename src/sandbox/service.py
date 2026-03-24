from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from src.capabilities.repository import CapabilitiesRepository
from src.config.settings import Settings
from src.execution.contracts import NodeCommandTemplate


@dataclass(frozen=True)
class SandboxResolution:
    sandbox_mode: str
    sandbox_key: str
    workspace_root: str
    workspace_mount_mode: str


@dataclass
class SandboxService:
    settings: Settings
    capabilities_repository: CapabilitiesRepository

    def resolve(
        self,
        db: Session,
        *,
        agent_id: str,
        session_id: str,
        template: NodeCommandTemplate,
    ) -> SandboxResolution:
        profile = self.capabilities_repository.get_agent_sandbox_profile(db, agent_id=agent_id)
        default_mode = profile.default_mode if profile is not None else "agent"
        allow_off = profile.allow_off_mode if profile is not None else False
        max_timeout = profile.max_timeout_seconds if profile is not None else self.settings.node_runner_timeout_ceiling_seconds
        if template.timeout_seconds > max_timeout:
            raise PermissionError("requested timeout exceeds sandbox profile maximum")
        if default_mode == "off" and (not allow_off or not self.settings.node_runner_allow_off_mode):
            raise PermissionError("off mode is disabled")

        if default_mode == "shared":
            sandbox_key = profile.shared_profile_key if profile is not None else self.settings.sandbox_shared_base_key
        elif default_mode == "agent":
            sandbox_key = f"{session_id}:{agent_id}:{template.sandbox_profile_key}"
        else:
            sandbox_key = "off"

        workspace_root = self._resolve_workspace_root(
            agent_id=agent_id,
            session_id=session_id,
            template=template,
        )
        workspace_mount_mode = template.workspace_mount_mode
        if default_mode == "shared":
            workspace_mount_mode = "read_only"
        return SandboxResolution(
            sandbox_mode=default_mode,
            sandbox_key=sandbox_key,
            workspace_root=workspace_root,
            workspace_mount_mode=workspace_mount_mode,
        )

    def _resolve_workspace_root(
        self,
        *,
        agent_id: str,
        session_id: str,
        template: NodeCommandTemplate,
    ) -> str:
        base = Path(self.settings.sandbox_workspace_root)
        if template.workspace_binding_kind == "agent":
            return str((base / "agents" / agent_id).resolve())
        if template.workspace_binding_kind == "session":
            return str((base / "sessions" / agent_id / session_id).resolve())
        if template.workspace_binding_kind == "fixed":
            if not template.fixed_workspace_key:
                raise ValueError("fixed workspace binding requires fixed_workspace_key")
            return str((base / "fixed" / template.fixed_workspace_key).resolve())
        raise ValueError(f"unsupported workspace binding kind: {template.workspace_binding_kind}")
