package com.elex.model;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.web.reactive.function.server.ServerRequest;

import java.net.URI;

/**
 * 入队或转发时使用的 HTTP 请求快照。
 *
 * <p>WebFlux 的 ServerRequest 只能在响应式链路中安全读取，
 * 因此进入队列前先固化 method、uri、headers 和 body。</p>
 */
public final class QueuedHttpRequest {
    private final HttpMethod method;
    private final URI uri;
    private final HttpHeaders headers;
    private final byte[] body;

    private QueuedHttpRequest(HttpMethod method, URI uri, HttpHeaders headers, byte[] body) {
        this.method = method;
        this.uri = uri;
        this.headers = headers;
        this.body = body;
    }

    /**
     * 创建指定目标 URI 的请求快照。
     *
     * @param method HTTP 方法
     * @param uri 已剥离代理前缀的目标 URI
     * @param headers 请求头
     * @param body 请求体
     * @return 请求快照
     */
    public static QueuedHttpRequest of(HttpMethod method, URI uri, HttpHeaders headers, byte[] body) {
        return new QueuedHttpRequest(method, uri, headers, body == null ? new byte[0] : body);
    }

    /**
     * 从 WebFlux 请求创建请求快照。
     *
     * @param request WebFlux 请求
     * @param body 已读取的请求体
     * @return 请求快照
     */
    public static QueuedHttpRequest from(ServerRequest request, byte[] body) {
        return from(request, body, "");
    }

    /**
     * 从 WebFlux 请求创建请求快照，并剥离代理入口前缀。
     *
     * @param request WebFlux 请求
     * @param body 已读取的请求体
     * @param pathPrefixToStrip 需要从路径前部移除的代理前缀
     * @return 请求快照
     */
    public static QueuedHttpRequest from(ServerRequest request, byte[] body, String pathPrefixToStrip) {
        return new QueuedHttpRequest(
                request.method(),
                stripPathPrefix(request.uri(), pathPrefixToStrip),
                request.headers().asHttpHeaders(),
                body
        );
    }

    /**
     * 获取 HTTP 方法。
     *
     * @return HTTP 方法
     */
    public HttpMethod method() {
        return method;
    }

    /**
     * 获取转发目标相对 URI。
     *
     * @return 已剥离代理前缀的 URI
     */
    public URI uri() {
        return uri;
    }

    /**
     * 获取请求头快照。
     *
     * @return 请求头
     */
    public HttpHeaders headers() {
        return headers;
    }

    /**
     * 获取请求体字节。
     *
     * @return 请求体
     */
    public byte[] body() {
        return body;
    }

    /**
     * 从原始 URI 中移除代理入口前缀，并保留 query 参数。
     *
     * @param uri 原始请求 URI
     * @param pathPrefixToStrip 需要移除的路径前缀
     * @return 剥离前缀后的 URI
     */
    private static URI stripPathPrefix(URI uri, String pathPrefixToStrip) {
        if (pathPrefixToStrip == null || pathPrefixToStrip.isBlank()) {
            return uri;
        }

        String rawPath = uri.getRawPath();
        if (rawPath == null || !rawPath.startsWith(pathPrefixToStrip)) {
            return uri;
        }

        String strippedPath = rawPath.substring(pathPrefixToStrip.length());
        if (strippedPath.isBlank()) {
            strippedPath = "/";
        }

        StringBuilder value = new StringBuilder(strippedPath);
        if (uri.getRawQuery() != null && !uri.getRawQuery().isBlank()) {
            value.append('?').append(uri.getRawQuery());
        }
        return URI.create(value.toString());
    }
}
