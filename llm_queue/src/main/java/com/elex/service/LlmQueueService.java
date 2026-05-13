package com.elex.service;

import com.elex.client.WebClientRequestForwarder;
import com.elex.config.LlmQueueProperties;
import com.elex.exception.QueueFullException;
import com.elex.model.QueuedHttpRequest;
import com.elex.model.QueuedHttpResponse;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Mono;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 串行队列业务服务。
 *
 * <p>内部维护一个有界阻塞队列和一个单独 worker 线程，
 * 所有进入该服务的请求都会按入队顺序逐个转发到上游。</p>
 */
@Service
public class LlmQueueService {
    private static final Logger log = LoggerFactory.getLogger(LlmQueueService.class);

    private final BlockingQueue<QueuedHttpTask> queue;
    private final WebClientRequestForwarder forwarder;
    private final PromptTaskExecutor promptTaskExecutor;
    private final LlmQueueProperties properties;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private Thread worker;

    /**
     * 创建队列服务。
     *
     * @param forwarder          实际执行 HTTP 转发的组件
     * @param promptTaskExecutor promot/prompt 异步任务执行器
     * @param properties         队列容量和超时配置
     */
    public LlmQueueService(
            WebClientRequestForwarder forwarder,
            PromptTaskExecutor promptTaskExecutor,
            LlmQueueProperties properties
    ) {
        if (properties.getCapacity() <= 0) {
            throw new IllegalArgumentException("llm.queue.capacity 必须大于 0");
        }
        this.queue = new ArrayBlockingQueue<>(properties.getCapacity());
        this.forwarder = forwarder;
        this.promptTaskExecutor = promptTaskExecutor;
        this.properties = properties;
    }

    /**
     * Spring 容器启动后启动后台 worker。
     */
    @PostConstruct
    void start() {
        if (!running.compareAndSet(false, true)) {
            return;
        }
        worker = new Thread(this::runLoop, "llm-queue-worker");
        worker.setDaemon(false);
        worker.start();
        log.info("llm queue worker started capacity={}", properties.getCapacity());
    }

    /**
     * Spring 容器关闭时停止 worker。
     */
    @PreDestroy
    void stop() {
        running.set(false);
        if (worker != null) {
            worker.interrupt();
        }
        log.info("llm queue worker stopping remainingQueueSize={}", queue.size());
    }

    /**
     * 提交请求到串行队列。
     *
     * @param request 待转发请求
     * @return 请求完成后的上游响应；队列满或超时时返回错误信号
     */
    public Mono<QueuedHttpResponse> enqueue(QueuedHttpRequest request) {
        QueuedHttpTask task = new QueuedHttpTask(request);
        if (!running.get() || !queue.offer(task)) {
            log.warn(
                    "queue enqueue rejected targetPath={} running={} queueSize={} capacity={}",
                    request.uri().getRawPath(),
                    running.get(),
                    queue.size(),
                    properties.getCapacity()
            );
            return Mono.error(new QueueFullException());
        }
        log.info(
                "queue enqueue success targetPath={} queueSize={} capacity={}",
                request.uri().getRawPath(),
                queue.size(),
                properties.getCapacity()
        );
        return Mono.fromFuture(task.future())
                .timeout(properties.getRequestTimeout())
                .doOnCancel(() -> {
                    task.future().cancel(true);
                    log.warn("queue request cancelled targetPath={} queueSize={}", request.uri().getRawPath(), queue.size());
                });
    }

    /**
     * 查询当前等待执行的任务数量。
     *
     * @return 队列中尚未被 worker 取出的任务数
     */
    public int queueSize() {
        return queue.size();
    }

    /**
     * 单 worker 消费循环。
     *
     * <p>这里是串行保证的核心：同一时间只有该线程会调用上游转发器。</p>
     */
    private void runLoop() {
        while (running.get() || !queue.isEmpty()) {
            try {
                QueuedHttpTask task = queue.take();
                if (task.future().isCancelled()) {
                    log.warn("queue task skipped because requester cancelled targetPath={} queueSize={}",
                            task.request().uri().getRawPath(),
                            queue.size());
                    continue;
                }
                try {
                    log.info("queue task started targetPath={} queueSize={}",
                            task.request().uri().getRawPath(),
                            queue.size());
                    task.complete(forwardQueuedTask(task));
                    log.info("queue task completed targetPath={} queueSize={}",
                            task.request().uri().getRawPath(),
                            queue.size());
                } catch (Exception e) {
                    log.warn("queue task failed targetPath={} queueSize={} error={}",
                            task.request().uri().getRawPath(),
                            queue.size(),
                            e.getMessage());
                    task.fail(e);
                }
            } catch (InterruptedException e) {
                if (!running.get()) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
    }

    private QueuedHttpResponse forwardQueuedTask(QueuedHttpTask task) throws Exception {
        if (promptTaskExecutor.supports(task.request())) {
            return promptTaskExecutor.executeAndWait(task.request(), () -> running.get() && !task.isCancelled());
        }
        return forwarder.forward(task.request());
    }
}
