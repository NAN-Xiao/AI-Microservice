package com.ai.gateway.config;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.web.reactive.error.ErrorWebExceptionHandler;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.net.ConnectException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.TimeoutException;

/**
 * 统一错误处理器，返回下游服务使用的 ApiResult 格式 JSON 响应
 */
@Slf4j
@Order(-1)
@Component
public class GatewayErrorHandler implements ErrorWebExceptionHandler {

    // ObjectMapper 用于序列化响应为 JSON
    private final ObjectMapper objectMapper = new ObjectMapper();
    /**
     * 统一错误处理器，返回下游服务使用的 ApiResult 格式 JSON 响应
     * @param exchange 当前请求上下文
     * @param ex 异常
     * @return Mono<Void> 异步处理结果
     *  Mono<Void> 是什么用法？是Spring Boot中的一个异步处理结果，用于处理异步请求。
     */ 
    @Override
    public Mono<Void> handle(ServerWebExchange exchange, Throwable ex) {
        HttpStatus status;
        String message;

        // 判断异常类型，设置对应的 HTTP 状态码和消息
        if (ex instanceof ConnectException) {
            status = HttpStatus.BAD_GATEWAY;
            message = "下游服务不可用";
        } else if (ex instanceof TimeoutException) {
            status = HttpStatus.GATEWAY_TIMEOUT;
            message = "下游服务请求超时";
        } else {
            status = HttpStatus.INTERNAL_SERVER_ERROR;
            message = "网关内部错误";
        }

        // 记录异常日志
        log.error("Gateway error on {} {}: {}",
                exchange.getRequest().getMethod(),
                exchange.getRequest().getURI().getRawPath(),
                ex.getMessage());

        // 设置响应状态码和响应类型为 JSON
        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);

        // 构造响应体，格式为 {"code":xxx,"message":"...","data":{}}
        Map<String, Object> body = Map.of(
                "code", status.value(),
                "message", message,
                "data", (Object) Map.of());

        byte[] bytes;
        try {
            // 优先使用 ObjectMapper 转 JSON 字节数组
            bytes = objectMapper.writeValueAsBytes(body);
        } catch (JsonProcessingException e) {
            // 序列化异常时，使用兜底 JSON 响应
            bytes = "{\"code\":500,\"message\":\"Gateway error\",\"data\":{}}".getBytes(StandardCharsets.UTF_8);
        }

        // 写入响应内容
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }
}
