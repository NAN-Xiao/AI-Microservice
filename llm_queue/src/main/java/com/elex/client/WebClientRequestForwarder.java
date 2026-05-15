package com.elex.client;

import com.elex.config.LlmQueueProperties;
import com.elex.model.QueuedHttpRequest;
import com.elex.model.QueuedHttpResponse;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.ExchangeStrategies;
import org.springframework.web.reactive.function.client.WebClient;

import java.net.URI;
import java.util.Locale;
import java.util.Set;

/**
 * 基于 WebClient 的上游 HTTP 转发器。
 *
 * <p>负责把内部请求模型转换为真实上游请求，并将上游响应快照返回给调用方。
 * 当前实现会完整读取请求体和响应体，适合普通 JSON 和中小文件场景。</p>
 */
@Component
public class WebClientRequestForwarder {
    private static final Set<String> HOP_BY_HOP_HEADERS = Set.of(
            "connection",
            "content-length",
            "expect",
            "host",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade"
    );

    private final WebClient webClient;
    private final LlmQueueProperties properties;

    /**
     * 创建转发器。
     *
     * @param builder Spring 提供的 WebClient 构建器
     * @param properties 上游地址和超时配置
     */
    public WebClientRequestForwarder(WebClient.Builder builder, LlmQueueProperties properties) {
        ExchangeStrategies strategies = ExchangeStrategies.builder()
                .codecs(codecs -> codecs.defaultCodecs().maxInMemorySize(properties.getMaxInMemorySize()))
                .build();
        this.webClient = builder.exchangeStrategies(strategies).build();
        this.properties = properties;
    }

    /**
     * 执行一次上游 HTTP 转发。
     *
     * @param request 待转发请求
     * @return 上游响应快照
     */
    public QueuedHttpResponse forward(QueuedHttpRequest request) {
        WebClient.RequestBodySpec spec = webClient.method(request.method())
                .uri(buildTargetUri(request))
                .headers(headers -> copyRequestHeaders(headers, request.headers()));

        WebClient.RequestHeadersSpec<?> headersSpec = request.body().length == 0
                ? spec
                : spec.bodyValue(request.body());

        return headersSpec.exchangeToMono(response -> response.bodyToMono(byte[].class)
                        .defaultIfEmpty(new byte[0])
                        .map(body -> new QueuedHttpResponse(
                                response.statusCode().value(),
                                response.headers().asHttpHeaders(),
                                body
                        )))
                .block(properties.getUpstreamTimeout());
    }

    /**
     * 根据上游基础地址和请求原始路径拼接目标 URI。
     *
     * @param request 待转发请求
     * @return 实际访问的上游 URI
     */
    private URI buildTargetUri(QueuedHttpRequest request) {
        StringBuilder uri = new StringBuilder(properties.normalizedTargetBaseUrl());
        String rawPath = request.uri().getRawPath();
        if (rawPath == null || rawPath.isBlank()) {
            uri.append('/');
        } else if (rawPath.charAt(0) == '/') {
            uri.append(rawPath);
        } else {
            uri.append('/').append(rawPath);
        }

        String rawQuery = request.uri().getRawQuery();
        if (rawQuery != null && !rawQuery.isBlank()) {
            uri.append('?').append(rawQuery);
        }
        return URI.create(uri.toString());
    }

    /**
     * 复制请求头，过滤不适合代理转发的逐跳头。
     *
     * @param target WebClient 请求头
     * @param source 原始请求头
     */
    private static void copyRequestHeaders(HttpHeaders target, HttpHeaders source) {
        source.forEach((name, values) -> {
            if (name != null && !HOP_BY_HOP_HEADERS.contains(name.toLowerCase(Locale.ROOT))) {
                target.put(name, values);
            }
        });
    }
}
