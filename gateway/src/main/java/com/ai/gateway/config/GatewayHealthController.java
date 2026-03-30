package com.ai.gateway.config;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.Map;

@RestController
public class GatewayHealthController {

    // 网关启动时间
    private final Instant startTime = Instant.now();

    // 健康检查接口，返回网关状态信息
    @GetMapping(value = "/gateway-health", produces = MediaType.APPLICATION_JSON_VALUE)
    public Mono<Map<String, Object>> health() {
        return Mono.just(Map.of(
                "status", "UP",
                "service", "ai-gateway",
                "uptime_seconds", Instant.now().getEpochSecond() - startTime.getEpochSecond()));
    }
}
