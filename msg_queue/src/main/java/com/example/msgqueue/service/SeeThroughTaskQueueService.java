package com.example.msgqueue.service;

import com.example.msgqueue.config.SeeThroughProperties;
import com.example.msgqueue.exception.QueueBusyException;
import com.example.msgqueue.exception.TaskCanceledException;
import com.example.msgqueue.model.SeeThroughQueueStatsResponse;
import com.example.msgqueue.model.SeeThroughResult;
import com.example.msgqueue.model.SeeThroughTask;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

@Service
public class SeeThroughTaskQueueService {

    private static final Logger log = LoggerFactory.getLogger(SeeThroughTaskQueueService.class);
    private static final long PENDING_CANCEL_TTL_SECONDS = 60L;

    private final SeeThroughProperties properties;
    private final SeeThroughClient seeThroughClient;
    private final LinkedBlockingQueue<SeeThroughTask> queue;
    private final ConcurrentMap<String, SeeThroughTask> tasks = new ConcurrentHashMap<>();
    private final ConcurrentMap<String, PendingCancel> pendingCancels = new ConcurrentHashMap<>();
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicLong processedCount = new AtomicLong(0);
    private final AtomicLong failedCount = new AtomicLong(0);
    private final AtomicLong canceledCount = new AtomicLong(0);
    private final AtomicReference<String> runningTaskId = new AtomicReference<>(null);

    private ExecutorService workerPool;

    public SeeThroughTaskQueueService(SeeThroughProperties properties, SeeThroughClient seeThroughClient) {
        this.properties = properties;
        this.seeThroughClient = seeThroughClient;
        this.queue = new LinkedBlockingQueue<>(properties.getMaxSize());
    }

    @PostConstruct
    public void start() {
        running.set(true);
        workerPool = Executors.newSingleThreadExecutor();
        workerPool.submit(() -> consumeLoop(1));
        log.info(
                "SeeThrough queue started: baseUrl={}, workerCount=1, maxSize={}, requestTimeoutSeconds={}",
                properties.getBaseUrl(),
                properties.getMaxSize(),
                properties.getRequestTimeoutSeconds()
        );
    }

    @PreDestroy
    public void shutdown() {
        running.set(false);
        if (workerPool != null) {
            workerPool.shutdownNow();
            try {
                workerPool.awaitTermination(5, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        log.info("SeeThrough queue stopped.");
    }

    public void submit(SeeThroughTask task) {
        cleanupExpiredPendingCancels();
        PendingCancel pendingCancel = pendingCancels.remove(task.taskId());
        if (pendingCancel != null) {
            task.cancel(pendingCancel.reason());
            task.resultFuture().completeExceptionally(new TaskCanceledException(task.cancelReason()));
            canceledCount.incrementAndGet();
            log.info("SeeThrough task canceled before queueing: taskId={} reason={}", task.taskId(), task.cancelReason());
            return;
        }

        tasks.put(task.taskId(), task);
        if (!queue.offer(task)) {
            tasks.remove(task.taskId(), task);
            throw new QueueBusyException();
        }
        log.info("SeeThrough task queued: taskId={} filename={} queueSize={}", task.taskId(), task.filename(), queue.size());
    }

    public SeeThroughResult waitForResult(SeeThroughTask task) throws InterruptedException, TimeoutException {
        try {
            return task.resultFuture().get(properties.getRequestTimeoutSeconds(), TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            cancel(task.taskId(), "任务等待超时");
            throw e;
        } catch (ExecutionException e) {
            Throwable cause = e.getCause();
            if (cause instanceof RuntimeException runtimeException) {
                throw runtimeException;
            }
            throw new IllegalStateException(cause);
        }
    }

    public SeeThroughResult submitAndWait(SeeThroughTask task) throws InterruptedException, TimeoutException {
        submit(task);
        return waitForResult(task);
    }

    public boolean cancel(String taskId, String reason) {
        if (taskId == null || taskId.isBlank()) {
            return false;
        }

        SeeThroughTask task = tasks.get(taskId.trim());
        if (task == null) {
            pendingCancels.put(taskId.trim(), new PendingCancel(reason, Instant.now()));
            cleanupExpiredPendingCancels();
            log.info("SeeThrough task cancel recorded before queue registration: taskId={} reason={}", taskId.trim(), reason);
            return true;
        }

        if (!task.cancel(reason)) {
            return true;
        }

        canceledCount.incrementAndGet();
        boolean removed = queue.remove(task);
        task.resultFuture().completeExceptionally(new TaskCanceledException(task.cancelReason()));
        if (removed) {
            tasks.remove(task.taskId(), task);
            log.info("SeeThrough task canceled before start: taskId={} reason={}", task.taskId(), task.cancelReason());
        } else {
            log.info("SeeThrough task marked canceled after start: taskId={} reason={}", task.taskId(), task.cancelReason());
        }
        return true;
    }

    private void cleanupExpiredPendingCancels() {
        Instant threshold = Instant.now().minusSeconds(PENDING_CANCEL_TTL_SECONDS);
        pendingCancels.entrySet().removeIf(entry -> entry.getValue().createdAt().isBefore(threshold));
    }

    public SeeThroughQueueStatsResponse stats() {
        return new SeeThroughQueueStatsResponse(
                queue.size(),
                properties.getMaxSize(),
                processedCount.get(),
                failedCount.get(),
                canceledCount.get(),
                runningTaskId.get()
        );
    }

    private void consumeLoop(int workerId) {
        while (running.get() && !Thread.currentThread().isInterrupted()) {
            try {
                SeeThroughTask task = queue.poll(1, TimeUnit.SECONDS);
                if (task == null) {
                    continue;
                }

                task.markStarted();
                runningTaskId.set(task.taskId());
                if (task.canceled()) {
                    tasks.remove(task.taskId(), task);
                    task.resultFuture().completeExceptionally(new TaskCanceledException(task.cancelReason()));
                    runningTaskId.set(null);
                    log.info("SeeThrough worker {} skipped canceled task: taskId={} filename={}", workerId, task.taskId(), task.filename());
                    continue;
                }

                log.info("SeeThrough worker {} started: taskId={} filename={}", workerId, task.taskId(), task.filename());
                try {
                    SeeThroughResult result = seeThroughClient.convert(task);
                    if (task.canceled()) {
                        task.resultFuture().completeExceptionally(new TaskCanceledException(task.cancelReason()));
                        log.info("SeeThrough worker {} discarded canceled result: taskId={} filename={}", workerId, task.taskId(), task.filename());
                    } else {
                        processedCount.incrementAndGet();
                        task.resultFuture().complete(result);
                        log.info("SeeThrough worker {} completed: taskId={} filename={}", workerId, task.taskId(), task.filename());
                    }
                } catch (Exception ex) {
                    failedCount.incrementAndGet();
                    task.resultFuture().completeExceptionally(ex);
                    log.warn("SeeThrough worker {} failed: taskId={} filename={} error={}",
                            workerId, task.taskId(), task.filename(), ex.getMessage());
                } finally {
                    tasks.remove(task.taskId(), task);
                    runningTaskId.set(null);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    private record PendingCancel(String reason, Instant createdAt) {
    }
}
