"""
Nacos 服务注册工具模块

为 Python (FastAPI) 微服务提供向 Nacos 注册 / 注销 / 心跳的功能。
使用方式：在 FastAPI lifespan 中调用 register() 和 deregister()。

示例:
    from nacos_registry import NacosRegistry

    registry = NacosRegistry(
        server_addr="127.0.0.1:8848",
        service_name="video-analyze-service",
        service_ip="127.0.0.1",
        service_port=9001,
    )

    @asynccontextmanager
    async def lifespan(app):
        await registry.register()
        yield
        await registry.deregister()
"""

import asyncio
import logging
import os
import socket
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    """自动检测本机局域网 IP（非 127.0.0.1）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class NacosRegistry:
    """Nacos 服务注册客户端（基于 Nacos Open API v1）"""

    def __init__(
        self,
        service_name: str,
        service_port: int,
        server_addr: str = "127.0.0.1:8848",
        service_ip: Optional[str] = None,
        namespace: str = "",
        group: str = "DEFAULT_GROUP",
        cluster_name: str = "DEFAULT",
        username: str = "nacos",
        password: str = "nacos",
        heartbeat_interval: int = 5,
        enabled: bool = True,
    ):
        self.service_name = service_name
        self.service_port = service_port
        self.server_addr = server_addr.rstrip("/")
        self.service_ip = service_ip or _detect_local_ip()
        self.namespace = namespace
        self.group = group
        self.cluster_name = cluster_name
        self.username = username
        self.password = password
        self.heartbeat_interval = heartbeat_interval
        self.enabled = enabled

        self._base_url = f"http://{self.server_addr}/nacos/v1/ns"
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def register(self) -> bool:
        """注册服务实例到 Nacos 并启动心跳"""
        if not self.enabled:
            logger.info("Nacos registration disabled, skipping")
            return False

        self._client = httpx.AsyncClient(timeout=10)

        params = {
            "serviceName": self.service_name,
            "ip": self.service_ip,
            "port": self.service_port,
            "namespaceId": self.namespace,
            "groupName": self.group,
            "clusterName": self.cluster_name,
            "healthy": "true",
            "enabled": "true",
            "ephemeral": "true",
        }
        if self.username:
            params["username"] = self.username
            params["password"] = self.password

        try:
            resp = await self._client.post(
                f"{self._base_url}/instance", params=params
            )
            if resp.status_code == 200 and resp.text.strip() == "ok":
                logger.info(
                    "Registered to Nacos: %s -> %s:%s (server=%s, ns=%s, group=%s)",
                    self.service_name, self.service_ip, self.service_port,
                    self.server_addr, self.namespace or "public", self.group,
                )
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                return True
            else:
                logger.error(
                    "Nacos register failed: status=%s body=%s",
                    resp.status_code, resp.text,
                )
                return False
        except Exception as e:
            logger.error("Nacos register error: %s", e)
            return False

    async def deregister(self) -> bool:
        """从 Nacos 注销服务实例并停止心跳"""
        if not self.enabled or self._client is None:
            return False

        # 停止心跳
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        params = {
            "serviceName": self.service_name,
            "ip": self.service_ip,
            "port": self.service_port,
            "namespaceId": self.namespace,
            "groupName": self.group,
            "clusterName": self.cluster_name,
            "ephemeral": "true",
        }
        if self.username:
            params["username"] = self.username
            params["password"] = self.password

        try:
            resp = await self._client.delete(
                f"{self._base_url}/instance", params=params
            )
            logger.info(
                "Deregistered from Nacos: %s -> %s:%s (result=%s)",
                self.service_name, self.service_ip, self.service_port, resp.text.strip(),
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("Nacos deregister error: %s", e)
            return False
        finally:
            await self._client.aclose()
            self._client = None

    async def _heartbeat_loop(self):
        """定期发送心跳，保持实例存活（Nacos 临时实例需要心跳）"""
        import json

        beat_info = json.dumps({
            "serviceName": self.service_name,
            "ip": self.service_ip,
            "port": self.service_port,
            "cluster": self.cluster_name,
            "scheduled": True,
            "weight": 1.0,
        })

        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                params = {
                    "serviceName": self.service_name,
                    "ip": self.service_ip,
                    "port": self.service_port,
                    "namespaceId": self.namespace,
                    "groupName": self.group,
                    "clusterName": self.cluster_name,
                    "beat": beat_info,
                }
                if self.username:
                    params["username"] = self.username
                    params["password"] = self.password

                resp = await self._client.put(
                    f"{self._base_url}/instance/beat", params=params
                )
                if resp.status_code != 200:
                    logger.warning("Nacos heartbeat failed: status=%s", resp.status_code)
            except asyncio.CancelledError:
                logger.debug("Nacos heartbeat stopped")
                raise
            except Exception as e:
                logger.warning("Nacos heartbeat error: %s", e)
