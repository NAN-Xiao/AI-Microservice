package com.example.msgqueue.service;

import com.example.msgqueue.config.QueueProperties;
import com.example.msgqueue.exception.QueueBusyException;
import com.example.msgqueue.model.EnqueueRequest;
import com.example.msgqueue.model.QueueMessage;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicReference;

@Service
public class MessageQueueService {

    private static final Logger log = LoggerFactory.getLogger(MessageQueueService.class);
    private static final String MESSAGE_BASE_PATH = "/messages";

    private final QueueProperties queueProperties;
    private final LinkedBlockingQueue<QueueMessage> queue;
    private final Set<String> longTaskPathPrefixSet;
    private final Semaphore consumePermit = new Semaphore(1, true);
    private final AtomicReference<String> runningMessageId = new AtomicReference<>(null);
    private final AtomicLong processedCount = new AtomicLong(0);
    private final AtomicLong failedCount = new AtomicLong(0);
    private final AtomicBoolean running = new AtomicBoolean(false);

    private ExecutorService workerPool;

    public MessageQueueService(QueueProperties queueProperties) {
        this.queueProperties = queueProperties;
        this.queue = new LinkedBlockingQueue<>(queueProperties.getMaxSize());
        this.longTaskPathPrefixSet = buildLongTaskPathPrefixSet(queueProperties);
    }

    @PostConstruct
    public void startConsumer() {
        running.set(true);
        workerPool = Executors.newFixedThreadPool(queueProperties.getWorkerCount());
        for (int i = 1; i <= queueProperties.getWorkerCount(); i++) {
            int workerId = i;
            workerPool.submit(() -> consumeLoop(workerId));
        }
        log.info(
                "Queue consumers started: workerCount={}, maxSize={}, workerDelayMs={}, longTaskPathPrefixes={}",
                queueProperties.getWorkerCount(),
                queueProperties.getMaxSize(),
                queueProperties.getWorkerDelayMs(),
                longTaskPathPrefixSet
        );
        if (queueProperties.getWorkerCount() > 1) {
            log.warn("workerCount > 1 is configured, but tasks are executed one by one due to task-state guard.");
        }
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
        log.info("Queue consumers stopped.");
    }

    public QueueMessage enqueue(EnqueueRequest request) {
        QueueMessage message = QueueMessage.of(request.getTopic(), request.getPayload());
        boolean offered = queue.offer(message);
        if (!offered) {
            throw new QueueBusyException();
        }
        return message;
    }

    public TaskRoute routeByPath(String requestPath) {
        String businessPath = extractBusinessPath(requestPath);
        if (isQueryPath(businessPath)) {
            return TaskRoute.DIRECT_QUERY;
        }
        if (matchesLongTaskPath(businessPath)) {
            return TaskRoute.QUEUE;
        }
        return TaskRoute.DIRECT_PROCESS;
    }

    public String processDirect(EnqueueRequest request, TaskRoute route) {
        String taskId = UUID.randomUUID().toString();
        log.info(
                "Directly processed taskId={} route={} topic={} payload={}",
                taskId,
                route,
                request.getTopic(),
                request.getPayload()
        );
        return taskId;
    }

    public int queueSize() {
        return queue.size();
    }

    public long processedCount() {
        return processedCount.get();
    }

    public long failedCount() {
        return failedCount.get();
    }

    public boolean hasRunningTask() {
        return runningMessageId.get() != null;
    }

    private void consumeLoop(int workerId) {
        while (running.get() && !Thread.currentThread().isInterrupted()) {
            try {
                // If a task is running, worker waits here until current task finishes.
                consumePermit.acquire();
                try {
                    QueueMessage message = queue.poll(1, TimeUnit.SECONDS);
                    if (message == null) {
                        continue;
                    }
                    runningMessageId.set(message.messageId());
                    consumeMessage(workerId, message);
                    processedCount.incrementAndGet();
                } finally {
                    runningMessageId.set(null);
                    consumePermit.release();
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } catch (Exception ex) {
                failedCount.incrementAndGet();
                log.error("Worker {} failed to consume message", workerId, ex);
            }
        }
    }

    private void consumeMessage(int workerId, QueueMessage message) throws InterruptedException {
        if (queueProperties.getWorkerDelayMs() > 0) {
            Thread.sleep(queueProperties.getWorkerDelayMs());
        }
        log.info(
                "Worker {} consumed messageId={} topic={} payload={}",
                workerId,
                message.messageId(),
                message.topic(),
                message.payload()
        );
    }

    private Set<String> buildLongTaskPathPrefixSet(QueueProperties properties) {
        Set<String> set = new HashSet<>();
        for (String pathPrefix : properties.getLongTaskPathPrefixes()) {
            if (pathPrefix == null || pathPrefix.isBlank()) {
                continue;
            }
            set.add(normalizePath(pathPrefix));
        }
        return Set.copyOf(set);
    }

    private String extractBusinessPath(String requestPath) {
        String normalizedPath = normalizePath(requestPath);
        if (normalizedPath.equals(MESSAGE_BASE_PATH)) {
            return "/";
        }
        if (normalizedPath.startsWith(MESSAGE_BASE_PATH + "/")) {
            return normalizedPath.substring(MESSAGE_BASE_PATH.length());
        }
        return normalizedPath;
    }

    private boolean matchesLongTaskPath(String businessPath) {
        for (String prefix : longTaskPathPrefixSet) {
            if (matchesPrefix(businessPath, prefix)) {
                return true;
            }
        }
        return false;
    }

    private boolean isQueryPath(String businessPath) {
        return matchesPrefix(businessPath, "/query");
    }

    private boolean matchesPrefix(String path, String prefix) {
        return path.equals(prefix) || path.startsWith(prefix + "/");
    }

    private String normalizePath(String path) {
        if (path == null || path.isBlank()) {
            return "/";
        }
        String normalized = path.trim().toLowerCase(Locale.ROOT);
        if (!normalized.startsWith("/")) {
            normalized = "/" + normalized;
        }
        while (normalized.length() > 1 && normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    public enum TaskRoute {
        QUEUE,
        DIRECT_QUERY,
        DIRECT_PROCESS
    }
}
