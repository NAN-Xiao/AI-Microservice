package com.ai.gateway.filter;

import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.time.Instant;

/**
 * Global filter that logs every request/response pair,
 * similar to the Nginx access_log format.
 */
@Slf4j
@Component
public class AccessLogFilter implements GlobalFilter, Ordered {

    private static final String START_TIME_ATTR = "gatewayRequestStartTime";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        exchange.getAttributes().put(START_TIME_ATTR, Instant.now());

        String clientIp = resolveClientIp(request);
        log.info(">>> {} {} from {} | Content-Type: {}",
                request.getMethod(),
                request.getURI().getRawPath(),
                clientIp,
                request.getHeaders().getFirst(HttpHeaders.CONTENT_TYPE));

        return chain.filter(exchange).then(Mono.fromRunnable(() -> {
            Instant start = exchange.getAttribute(START_TIME_ATTR);
            long elapsedMs = start != null ? Instant.now().toEpochMilli() - start.toEpochMilli() : -1;

            ServerHttpResponse response = exchange.getResponse();
            log.info("<<< {} {} | status={} | {}ms",
                    request.getMethod(),
                    request.getURI().getRawPath(),
                    response.getStatusCode(),
                    elapsedMs);
        }));
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }

    private String resolveClientIp(ServerHttpRequest request) {
        HttpHeaders headers = request.getHeaders();
        String ip = headers.getFirst("X-Forwarded-For");
        if (ip != null && !ip.isBlank()) {
            return ip.split(",")[0].trim();
        }
        ip = headers.getFirst("X-Real-IP");
        if (ip != null && !ip.isBlank()) {
            return ip;
        }
        return request.getRemoteAddress() != null
                ? request.getRemoteAddress().getAddress().getHostAddress()
                : "unknown";
    }
}
