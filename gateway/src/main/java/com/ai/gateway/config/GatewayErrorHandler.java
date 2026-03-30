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
 * Unified error handler that returns JSON responses matching
 * the ApiResult format used by downstream services.
 */
@Slf4j
@Order(-1)
@Component
public class GatewayErrorHandler implements ErrorWebExceptionHandler {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public Mono<Void> handle(ServerWebExchange exchange, Throwable ex) {
        HttpStatus status;
        String message;

        if (ex instanceof ConnectException) {
            status = HttpStatus.BAD_GATEWAY;
            message = "Downstream service unavailable";
        } else if (ex instanceof TimeoutException) {
            status = HttpStatus.GATEWAY_TIMEOUT;
            message = "Downstream service timed out";
        } else {
            status = HttpStatus.INTERNAL_SERVER_ERROR;
            message = "Gateway internal error";
        }

        log.error("Gateway error on {} {}: {}",
                exchange.getRequest().getMethod(),
                exchange.getRequest().getURI().getRawPath(),
                ex.getMessage());

        exchange.getResponse().setStatusCode(status);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);

        Map<String, Object> body = Map.of(
                "code", status.value(),
                "message", message,
                "data", (Object) Map.of()
        );

        byte[] bytes;
        try {
            bytes = objectMapper.writeValueAsBytes(body);
        } catch (JsonProcessingException e) {
            bytes = "{\"code\":500,\"message\":\"Gateway error\",\"data\":{}}".getBytes(StandardCharsets.UTF_8);
        }

        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(bytes);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }
}
