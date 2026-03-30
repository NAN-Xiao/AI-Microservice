package com.ai.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Ensures X-Real-IP / X-Forwarded-For / X-Forwarded-Proto reach downstream.
 * Works both standalone and behind Nginx:
 * - Behind Nginx: trusts and preserves the headers Nginx already set
 * - Standalone: populates headers from the direct client connection
 */
@Component
public class ForwardHeadersFilter implements GlobalFilter, Ordered {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest original = exchange.getRequest();
        HttpHeaders headers = original.getHeaders();

        String directIp = original.getRemoteAddress() != null
                ? original.getRemoteAddress().getAddress().getHostAddress()
                : "unknown";

        String realIp = headers.getFirst("X-Real-IP");
        String forwardedFor = headers.getFirst("X-Forwarded-For");
        String proto = headers.getFirst("X-Forwarded-Proto");

        ServerHttpRequest.Builder builder = original.mutate();

        if (realIp == null || realIp.isBlank()) {
            builder.header("X-Real-IP", directIp);
        }

        if (forwardedFor == null || forwardedFor.isBlank()) {
            builder.header("X-Forwarded-For", directIp);
        }

        if (proto == null || proto.isBlank()) {
            String scheme = original.getURI().getScheme();
            builder.header("X-Forwarded-Proto", scheme != null ? scheme : "http");
        }

        return chain.filter(exchange.mutate().request(builder.build()).build());
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE + 1;
    }
}
