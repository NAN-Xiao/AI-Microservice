package com.elex.model;

import org.springframework.http.HttpHeaders;

/**
 * 上游 HTTP 响应快照。
 *
 * <p>用于在队列 worker 和 WebFlux 响应层之间传递状态码、响应头和响应体。</p>
 */
public final class QueuedHttpResponse {
    private final int statusCode;
    private final HttpHeaders headers;
    private final byte[] body;

    /**
     * 创建响应快照。
     *
     * @param statusCode 上游 HTTP 状态码
     * @param headers 上游响应头
     * @param body 上游响应体
     */
    public QueuedHttpResponse(int statusCode, HttpHeaders headers, byte[] body) {
        this.statusCode = statusCode;
        this.headers = headers;
        this.body = body;
    }

    /**
     * 获取上游 HTTP 状态码。
     *
     * @return HTTP 状态码
     */
    public int statusCode() {
        return statusCode;
    }

    /**
     * 获取上游响应头。
     *
     * @return 响应头
     */
    public HttpHeaders headers() {
        return headers;
    }

    /**
     * 获取上游响应体。
     *
     * @return 响应体字节
     */
    public byte[] body() {
        return body;
    }
}
