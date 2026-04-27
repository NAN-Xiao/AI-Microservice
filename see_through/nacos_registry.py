import asyncio
import json
import logging
import socket
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _detect_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class NacosRegistry:
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
        if not self.enabled:
            logger.info("Nacos registration disabled")
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
            resp = await self._client.post(f"{self._base_url}/instance", params=params)
            ok = resp.status_code == 200 and resp.text.strip() == "ok"
            if ok:
                logger.info("Nacos 注册成功: %s -> %s:%s", self.service_name, self.service_ip, self.service_port)
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                return True
            logger.error("Nacos 注册失败: status=%s body=%s", resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("Nacos 注册异常: %s", exc)
            return False

    async def deregister(self) -> bool:
        if not self.enabled or self._client is None:
            return False

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
            resp = await self._client.delete(f"{self._base_url}/instance", params=params)
            logger.info("Nacos 注销完成: %s", resp.text.strip())
            return resp.status_code == 200
        except Exception as exc:
            logger.error("Nacos 注销异常: %s", exc)
            return False
        finally:
            await self._client.aclose()
            self._client = None

    async def _heartbeat_loop(self):
        beat_info = json.dumps(
            {
                "serviceName": self.service_name,
                "ip": self.service_ip,
                "port": self.service_port,
                "cluster": self.cluster_name,
                "scheduled": True,
                "weight": 1.0,
            }
        )

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

                resp = await self._client.put(f"{self._base_url}/instance/beat", params=params)
                if resp.status_code != 200:
                    logger.warning("Nacos 心跳失败: %s", resp.status_code)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Nacos 心跳异常: %s", exc)
