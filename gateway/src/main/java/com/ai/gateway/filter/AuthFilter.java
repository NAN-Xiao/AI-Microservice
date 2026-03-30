package com.ai.gateway.filter;

import com.ai.gateway.config.GatewayAuthProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 基于静态 Bearer Token 的网关认证过滤器。
 * <p>
 * 当 {@code gateway.auth.enabled=true} 时，会校验 Authorization 头部信息。
 * 默认是关闭的（false）。启用后需通过配置提供允许访问的 Bearer Token 列表。
 */
@Slf4j
@Component
public class AuthFilter implements GlobalFilter, Ordered {

    private final GatewayAuthProperties authProperties;

    public AuthFilter(GatewayAuthProperties authProperties) {
        this.authProperties = authProperties;
    }

    /**
     * 网关全局过滤器，认证主要逻辑入口
     * @param exchange 当前请求上下文
     * @param chain 过滤器链
     * @return Mono<Void> 异步过滤结果
     */
    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        // 若未开启认证，直接放行
        if (!authProperties.isEnabled()) {
            return chain.filter(exchange);
        }

        ServerHttpRequest request = exchange.getRequest();
        String path = request.getURI().getRawPath();

        // 白名单路径无需认证，直接放行
        if (isWhiteListed(path)) {
            return chain.filter(exchange);
        }

        // 检查 Authorization 头部是否存在且不为空
        String authHeader = request.getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
        if (authHeader == null || authHeader.isBlank()) {
            log.warn("Auth rejected: missing Authorization header for {}", path);
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }

        if (!authHeader.regionMatches(true, 0, "Bearer ", 0, 7)) {
            log.warn("Auth rejected: unsupported Authorization scheme for {}", path);
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }

        String token = authHeader.substring(7).trim();
        if (token.isEmpty()) {
            log.warn("Auth rejected: blank bearer token for {}", path);
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }

        if (authProperties.getAllowedTokens().isEmpty()) {
            log.error("Auth is enabled but no allowed tokens are configured");
            exchange.getResponse().setStatusCode(HttpStatus.INTERNAL_SERVER_ERROR);
            return exchange.getResponse().setComplete();
        }

        if (!authProperties.getAllowedTokens().contains(token)) {
            log.warn("Auth rejected: invalid bearer token for {}", path);
            exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
            return exchange.getResponse().setComplete();
        }

        log.debug("Auth passed for {}", path);
        return chain.filter(exchange);
    }

    /**
     * 过滤器顺序配置
     * @return int 越小优先级越高
     */
    @Override
    public int getOrder() {
        // 比 AccessLogFilter 稍晚
        return Ordered.HIGHEST_PRECEDENCE + 2;
    }

    /**
     * 判断请求路径是否属于白名单（无需认证）
     * @param path 请求路径
     * @return boolean 属于白名单返回 true
     */
    private boolean isWhiteListed(String path) {
        return authProperties.getWhitelist().stream().anyMatch(path::startsWith);
    }
}
