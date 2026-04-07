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
 * 全局访问日志过滤器，记录每一次请求与响应，格式类似于 Nginx 的 access_log。
 */
@Slf4j
@Component
public class AccessLogFilter implements GlobalFilter, Ordered {

    private static final String START_TIME_ATTR = "gatewayRequestStartTime";

    /**
     * 网关全局过滤器主逻辑
     * 记录请求的起始时间、请求基本信息，然后在响应后记录状态码和耗时。
     *
     * @param exchange 当前请求上下文
     * @param chain    过滤器链
     * @return Mono<Void> 异步处理结果
     */
    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        // 在请求属性中保存当前时间，便于后续计算耗时
        exchange.getAttributes().put(START_TIME_ATTR, Instant.now());

        // 解析客户端 IP
        String clientIp = resolveClientIp(request);
        // 记录请求基本信息
        log.info(">>> {} {} from {} | Content-Type: {}",
                request.getMethod(),
                request.getURI().getRawPath(),
                clientIp,
                request.getHeaders().getFirst(HttpHeaders.CONTENT_TYPE));

        // 在响应时记录状态码和耗时
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

    /**
     * 配置过滤器优先级。
     * 跟 Ordered 接口约定，值越小优先级越高。
     *
     * @return int 优先级
     */
    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }

    /**
     * 解析客户端真实 IP 地址。
     * 优先读取 X-Forwarded-For 头，其次读取 X-Real-IP，
     * 最后 fallback 到底层 socket 连接的 remote address。
     *
     * @param request 当前请求
     * @return String 解析出的 IP 地址，若无法获取则为 "unknown"
     */
    private String resolveClientIp(ServerHttpRequest request) {
        HttpHeaders headers = request.getHeaders();
        String ip = headers.getFirst("X-Forwarded-For");
        if (ip != null && !ip.isBlank()) {
            // 可能存在逗号分隔的多个 IP，仅取第一个
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
