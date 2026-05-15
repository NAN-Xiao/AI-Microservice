package com.elex.web;

import com.elex.client.WebClientRequestForwarder;
import com.elex.config.LlmQueueProperties;
import com.elex.exception.QueueFullException;
import com.elex.model.QueuedHttpRequest;
import com.elex.model.QueuedHttpResponse;
import com.elex.service.LlmQueueService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.BodyExtractors;
import org.springframework.web.reactive.function.server.ServerRequest;
import org.springframework.web.reactive.function.server.ServerResponse;
import org.springframework.core.io.buffer.DataBufferUtils;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeoutException;

/**
 * HTTP 请求处理器。
 *
 * <p>负责把 WebFlux 请求转换为内部请求模型，并根据目标路径决定进入队列还是直接转发。</p>
 */
@Component
public class QueueRequestHandler {
    private static final Logger log = LoggerFactory.getLogger(QueueRequestHandler.class);
    private static final int MAX_LOG_BODY_LENGTH = 4096;
    private static final String PROXY_PATH_PREFIX = "/proxy";
    private static final String QUEUE_REQUEST_HEADER_MARKER = "llm_queue_request";
    private static final String SOURCE_SERVICE_HEADER = "X-Llm-Queue-Source-Service";
    private static final String SOURCE_PATH_HEADER = "X-Llm-Queue-Source-Path";
    private static final List<String> RESPONSE_HEADERS_TO_SKIP = List.of(
            "connection",
            "content-length",
            "transfer-encoding"
    );

    private final LlmQueueService queueService;
    private final WebClientRequestForwarder forwarder;
    private final LlmQueueProperties properties;

    /**
     * 创建请求处理器。
     *
     * @param queueService 串行队列服务
     * @param forwarder 直通转发器
     */
    public QueueRequestHandler(
            LlmQueueService queueService,
            WebClientRequestForwarder forwarder,
            LlmQueueProperties properties
    ) {
        this.queueService = queueService;
        this.forwarder = forwarder;
        this.properties = properties;
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
                "queueSize", queueService.queueSize()
        ));
    }

    /**
     * 统一请求分发入口。
     *
     * <p>代理请求进入转发逻辑，其他路径返回 404。</p>
     *
     * @param request 当前请求
     * @return HTTP 响应
     */
    public Mono<ServerResponse> dispatch(ServerRequest request) {
        String path = request.path();
        log.info(
                "received request method={} path={} query={} uri={}",
                request.method(),
                path,
                request.uri().getRawQuery() == null ? "" : request.uri().getRawQuery(),
                request.uri()
        );
        if (path.startsWith(PROXY_PATH_PREFIX + "/") || PROXY_PATH_PREFIX.equals(path)) {
            return proxy(request);
        }
        return notFound(request);
    }

    /**
     * 代理入口。
     *
     * <p>先剥离 {@code /proxy} 前缀，再根据请求头标记选择串行队列或直通转发。</p>
     *
     * @param request 当前请求
     * @return 上游服务响应或错误响应
     */
    public Mono<ServerResponse> proxy(ServerRequest request) {
        String targetPath = stripProxyPrefix(request.path());
        boolean headerQueued = hasQueueRequestHeader(request.headers().asHttpHeaders());
        String sourcePath = firstHeader(request.headers().asHttpHeaders(), SOURCE_PATH_HEADER);
        if (shouldRejectBeforeReadingBody(headerQueued)) {
            log.warn(
                    "queue full before reading request body sourceService={} sourcePath={} targetPath={} headerQueued={} currentQueueSize={}",
                    firstHeader(request.headers().asHttpHeaders(), SOURCE_SERVICE_HEADER),
                    sourcePath,
                    targetPath,
                    headerQueued,
                    queueService.queueSize()
            );
            return jsonError(HttpStatus.TOO_MANY_REQUESTS, "queue is full");
        }

        return DataBufferUtils.join(request.body(BodyExtractors.toDataBuffers()), properties.getMaxInMemorySize())
                .map(dataBuffer -> {
                    byte[] body = new byte[dataBuffer.readableByteCount()];
                    dataBuffer.read(body);
                    DataBufferUtils.release(dataBuffer);
                    return body;
                })
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
        log.info(
                "final response source=upstream status={} contentType={} body={}",
                response.statusCode(),
                response.headers().getFirst(HttpHeaders.CONTENT_TYPE),
                bodyForLog(response.headers(), response.body())
        );
        return ServerResponse.status(response.statusCode())
                .headers(headers -> copyResponseHeaders(headers, response.headers()))
                .bodyValue(response.body());
    }

    /**
     * 根据目标路径选择处理方式。
     *
     * <p>带 {@code llm_queue_request} 请求头标记的请求进入单 worker 队列；
     * 其他 ComfyUI 接口直接转发，避免轮询和下载占用队列。</p>
     *
     * @param request 已剥离代理前缀的请求
     * @return 上游响应
     */
    private Mono<QueuedHttpResponse> forwardByPathRule(QueuedHttpRequest request) {
        boolean headerQueued = hasQueueRequestHeader(request.headers());
        log.info(
                "proxy request sourceService={} sourcePath={} targetPath={} headerQueued={} queued={}",
                firstHeader(request.headers(), SOURCE_SERVICE_HEADER),
                firstHeader(request.headers(), SOURCE_PATH_HEADER),
                request.uri().getRawPath(),
                headerQueued,
                headerQueued
        );
        if (headerQueued) {
            return queueService.enqueue(request);
        }
        return Mono.fromCallable(() -> forwarder.forward(request))
                .subscribeOn(Schedulers.boundedElastic());
    }

    /**
     * 判断是否应在读取请求体前直接拒绝。
     *
     * <p>带 {@code llm_queue_request} 请求头的请求表示调用方要求进入队列；
     * 若队列已满，此处提前拒绝，避免大请求体继续读入内存。</p>
     */
    private boolean shouldRejectBeforeReadingBody(boolean headerQueued) {
        return headerQueued && queueService.isQueueFull();
    }

    private static String firstHeader(HttpHeaders headers, String name) {
        String value = headers.getFirst(name);
        return value == null || value.isBlank() ? "-" : value;
    }

    private static boolean hasQueueRequestHeader(HttpHeaders headers) {
        if (headers == null || headers.isEmpty()) {
            return false;
        }
        return headers.keySet().stream()
                .filter(name -> name != null)
                .map(name -> name.toLowerCase(Locale.ROOT))
                .anyMatch(name -> name.contains(QUEUE_REQUEST_HEADER_MARKER));
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
        log.warn("final response source=llm_queue status={} body={{\"error\":\"{}\"}}", status.value(), message);
        return ServerResponse.status(status).bodyValue(Map.of("error", message));
    }

    private static String stripProxyPrefix(String path) {
        if (path == null || path.isBlank()) {
            return "/";
        }
        if (!path.startsWith(PROXY_PATH_PREFIX)) {
            return path;
        }
        String stripped = path.substring(PROXY_PATH_PREFIX.length());
        return stripped.isBlank() ? "/" : stripped;
    }

    private static String bodyForLog(HttpHeaders headers, byte[] body) {
        if (body == null) {
            return "";
        }
        if (!isTextual(headers)) {
            return "<binary body length=" + body.length + ">";
        }
        String text = new String(body, StandardCharsets.UTF_8);
        if (text.length() <= MAX_LOG_BODY_LENGTH) {
            return text;
        }
        return text.substring(0, MAX_LOG_BODY_LENGTH) + "...(truncated)";
    }

    private static boolean isTextual(HttpHeaders headers) {
        MediaType contentType = headers.getContentType();
        if (contentType == null) {
            return true;
        }
        return "text".equalsIgnoreCase(contentType.getType())
                || contentType.isCompatibleWith(MediaType.APPLICATION_JSON)
                || contentType.isCompatibleWith(MediaType.APPLICATION_XML)
                || contentType.isCompatibleWith(MediaType.APPLICATION_FORM_URLENCODED);
    }
}
