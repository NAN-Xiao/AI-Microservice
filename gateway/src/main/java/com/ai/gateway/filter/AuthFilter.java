package com.ai.gateway.filter;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.List;

/**
 * Placeholder authentication filter.
 * <p>
 * When {@code gateway.auth.enabled=true}, it validates the Authorization header.
 * Currently disabled by default — mirrors the commented-out auth_request in nginx.conf.
 * <p>
 * TODO: Integrate with your auth service (JWT validation, OAuth2, etc.)
 */
@Slf4j
@Component
public class AuthFilter implements GlobalFilter, Ordered {

    @Value("${gateway.auth.enabled:false}")
    private boolean authEnabled;

    private static final List<String> WHITE_LIST = List.of(
            "/actuator/health",
            "/gateway-health"
    );

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        if (!authEnabled) {
            return chain.filter(exchange);
        }

        ServerHttpRequest request = exchange.getRequest();
        String path = request.getURI().getRawPath();

        if (isWhiteListed(path)) {
            return chain.filter(exchange);
        }

        String authHeader = request.getHeaders().getFirst("Authorization");
        if (authHeader == null || authHeader.isBlank()) {
            log.warn("Auth rejected: missing Authorization header for {}", path);
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }

        // TODO: call remote auth service or validate JWT locally
        // Example: WebClient call to http://127.0.0.1:9100/auth/verify
        log.debug("Auth passed for {} (token present)", path);
        return chain.filter(exchange);
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE + 2;
    }

    private boolean isWhiteListed(String path) {
        return WHITE_LIST.stream().anyMatch(path::startsWith);
    }
}
