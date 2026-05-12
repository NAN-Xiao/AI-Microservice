package com.elex.web;

import com.elex.client.WebClientRequestForwarder;
import com.elex.exception.QueueFullException;
import com.elex.model.QueuedHttpRequest;
import com.elex.model.QueuedHttpResponse;
import com.elex.service.LlmQueueService;
import com.elex.service.QueueRuleReloadService;
import com.elex.service.QueueRuleService;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.server.ServerRequest;
import org.springframework.web.reactive.function.server.ServerResponse;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.TimeoutException;

/**
 * HTTP 请求处理器。
 *
 * <p>负责把 WebFlux 请求转换为内部请求模型，并根据目标路径决定进入队列还是直接转发。
 * 当前只有上游 {@code /prompt} 会串行排队，上传、轮询和下载接口直接转发。</p>
 */
@Component
public class QueueRequestHandler {
    private static final String PROXY_PATH_PREFIX = "/proxy";
    private static final String ADMIN_RELOAD_PATH = "/admin/reload";
    private static final List<String> RESPONSE_HEADERS_TO_SKIP = List.of(
            "connection",
            "content-length",
            "transfer-encoding"
    );

    private final LlmQueueService queueService;
    private final QueueRuleService queueRuleService;
    private final QueueRuleReloadService queueRuleReloadService;
    private final WebClientRequestForwarder forwarder;

    /**
     * 创建请求处理器。
     *
     * @param queueService 串行队列服务
     * @param queueRuleService 入队规则服务
     * @param queueRuleReloadService 入队规则重载服务
     * @param forwarder 直通转发器
     */
    public QueueRequestHandler(
            LlmQueueService queueService,
            QueueRuleService queueRuleService,
            QueueRuleReloadService queueRuleReloadService,
            WebClientRequestForwarder forwarder
    ) {
        this.queueService = queueService;
        this.queueRuleService = queueRuleService;
        this.queueRuleReloadService = queueRuleReloadService;
        this.forwarder = forwarder;
    }

    /**
     * 健康检查接口。
     *
     * @param request 当前请求
     * @return 服务状态和当前队列长度
     */
    public Mono<ServerResponse> health(ServerRequest request) {
        return ServerResponse.ok().bodyValue(Map.of(
                "status", "UP",
                "queueSize", queueService.queueSize(),
                "queuedPaths", queueRuleService.currentRules()
        ));
    }

    /**
     * 统一请求分发入口。
     *
     * <p>管理接口在这里直接处理，代理请求进入转发逻辑，其他路径返回 404。</p>
     *
     * @param request 当前请求
     * @return HTTP 响应
     */
    public Mono<ServerResponse> dispatch(ServerRequest request) {
        String path = request.path();
        if (isAdminReload(path)) {
            return reload(request);
        }
        if (path.startsWith(PROXY_PATH_PREFIX + "/") || PROXY_PATH_PREFIX.equals(path)) {
            return proxy(request);
        }
        return notFound(request);
    }

    /**
     * 从本地配置文件重新加载入队规则。
     *
     * @param request 当前请求
     * @return 新规则列表
     */
    public Mono<ServerResponse> reload(ServerRequest request) {
        return Mono.fromCallable(queueRuleReloadService::reload)
                .subscribeOn(Schedulers.boundedElastic())
                .flatMap(rules -> ServerResponse.ok().bodyValue(Map.of(
                        "reloaded", true,
                        "queuedPaths", rules
                )))
                .onErrorResume(e -> jsonError(HttpStatus.INTERNAL_SERVER_ERROR, e.getMessage()));
    }

    /**
     * 代理入口。
     *
     * <p>先剥离 {@code /proxy} 前缀，再根据剥离后的目标路径选择串行队列或直通转发。</p>
     *
     * @param request 当前请求
     * @return 上游服务响应或错误响应
     */
    public Mono<ServerResponse> proxy(ServerRequest request) {
        return request.bodyToMono(byte[].class)
                .defaultIfEmpty(new byte[0])
                .map(body -> QueuedHttpRequest.from(request, body, PROXY_PATH_PREFIX))
                .flatMap(this::forwardByPathRule)
                .flatMap(this::toServerResponse)
                .onErrorResume(QueueFullException.class, e -> jsonError(HttpStatus.TOO_MANY_REQUESTS, "queue is full"))
                .onErrorResume(TimeoutException.class, e -> jsonError(HttpStatus.GATEWAY_TIMEOUT, "request timed out in queue"))
                .onErrorResume(e -> jsonError(HttpStatus.BAD_GATEWAY, "upstream request failed"));
    }

    /**
     * 未匹配路径的兜底响应。
     *
     * @param request 当前请求
     * @return 404 JSON 响应
     */
    public Mono<ServerResponse> notFound(ServerRequest request) {
        return jsonError(HttpStatus.NOT_FOUND, "path not found");
    }

    /**
     * 将内部响应模型转换成 WebFlux 响应。
     *
     * @param response 上游响应快照
     * @return 返回给调用方的 HTTP 响应
     */
    private Mono<ServerResponse> toServerResponse(QueuedHttpResponse response) {
        return ServerResponse.status(response.statusCode())
                .headers(headers -> copyResponseHeaders(headers, response.headers()))
                .bodyValue(response.body());
    }

    /**
     * 根据目标路径选择处理方式。
     *
     * <p>匹配 {@code llm.queue.queued-paths} 的目标路径进入单 worker 队列；
     * 其他 ComfyUI 接口直接转发，避免轮询和下载占用队列。</p>
     *
     * @param request 已剥离代理前缀的请求
     * @return 上游响应
     */
    private Mono<QueuedHttpResponse> forwardByPathRule(QueuedHttpRequest request) {
        if (queueRuleService.shouldQueue(request.uri().getRawPath())) {
            return queueService.enqueue(request);
        }
        return Mono.fromCallable(() -> forwarder.forward(request))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * 复制上游响应头，过滤不应由代理透传的逐跳头。
     *
     * @param target 返回给客户端的响应头
     * @param source 上游响应头
     */
    private static void copyResponseHeaders(HttpHeaders target, HttpHeaders source) {
        for (Map.Entry<String, List<String>> entry : source.entrySet()) {
            String name = entry.getKey();
            if (name == null || RESPONSE_HEADERS_TO_SKIP.contains(name.toLowerCase(Locale.ROOT))) {
                continue;
            }
            target.put(name, entry.getValue());
        }
    }

    /**
     * 构造统一 JSON 错误响应。
     *
     * @param status HTTP 状态码
     * @param message 错误信息
     * @return JSON 错误响应
     */
    private static Mono<ServerResponse> jsonError(HttpStatus status, String message) {
        return ServerResponse.status(status).bodyValue(Map.of("error", message));
    }

    private static boolean isAdminReload(String path) {
        return ADMIN_RELOAD_PATH.equals(path) || (ADMIN_RELOAD_PATH + "/").equals(path);
    }
}
