package com.elex.service;

import com.elex.model.QueuedHttpRequest;
import com.elex.model.QueuedHttpResponse;
import java.util.concurrent.atomic.AtomicBoolean;

import java.util.concurrent.CompletableFuture;

/**
 * 队列中的单个 HTTP 转发任务。
 *
 * <p>保存请求快照和结果 future，入口线程通过 future 等待 worker 执行结果。</p>
 */
final class QueuedHttpTask {
    private final QueuedHttpRequest request;
    private final Runnable onFinish;
    private final CompletableFuture<QueuedHttpResponse> future = new CompletableFuture<>();
    private final AtomicBoolean finished = new AtomicBoolean(false);

    /**
     * 创建队列任务。
     *
     * @param request 请求快照
     */
    QueuedHttpTask(QueuedHttpRequest request, Runnable onFinish) {
        this.request = request;
        this.onFinish = onFinish == null ? () -> { } : onFinish;
    }

    /**
     * 获取待转发请求。
     *
     * @return 请求快照
     */
    QueuedHttpRequest request() {
        return request;
    }

    /**
     * 获取任务结果 future。
     *
     * @return 上游响应 future
     */
    CompletableFuture<QueuedHttpResponse> future() {
        return future;
    }

    /**
     * 判断调用方是否已经取消等待。
     *
     * @return true 表示任务已取消
     */
    boolean isCancelled() {
        return future.isCancelled();
    }

    /**
     * 取消任务，并释放占用的队列槽位。
     */
    void cancel() {
        try {
            future.cancel(true);
        } finally {
            finishOnce();
        }
    }

    /**
     * 标记任务成功完成。
     *
     * @param response 上游响应
     */
    void complete(QueuedHttpResponse response) {
        try {
            future.complete(response);
        } finally {
            finishOnce();
        }
    }

    /**
     * 标记任务执行失败。
     *
     * @param throwable 失败原因
     */
    void fail(Throwable throwable) {
        try {
            future.completeExceptionally(throwable);
        } finally {
            finishOnce();
        }
    }

    private void finishOnce() {
        if (finished.compareAndSet(false, true)) {
            onFinish.run();
        }
    }
}
