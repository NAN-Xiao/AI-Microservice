package com.example.msgqueue.model;

import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;

public class SeeThroughTask {

    private final String taskId;
    private final String filename;
    private final String contentType;
    private final byte[] imageBytes;
    private final String authorization;
    private final Instant createdAt;
    private final AtomicBoolean started = new AtomicBoolean(false);
    private final AtomicBoolean canceled = new AtomicBoolean(false);
    private final CompletableFuture<SeeThroughResult> resultFuture = new CompletableFuture<>();
    private volatile String cancelReason = "";

    private SeeThroughTask(String taskId, String filename, String contentType, byte[] imageBytes, String authorization) {
        this.taskId = taskId == null || taskId.isBlank() ? UUID.randomUUID().toString() : taskId.trim();
        this.filename = filename;
        this.contentType = contentType;
        this.imageBytes = imageBytes;
        this.authorization = authorization;
        this.createdAt = Instant.now();
    }

    public static SeeThroughTask of(String filename, String contentType, byte[] imageBytes, String authorization) {
        return new SeeThroughTask(null, filename, contentType, imageBytes, authorization);
    }

    public static SeeThroughTask of(String taskId, String filename, String contentType, byte[] imageBytes, String authorization) {
        return new SeeThroughTask(taskId, filename, contentType, imageBytes, authorization);
    }

    public String taskId() {
        return taskId;
    }

    public String filename() {
        return filename;
    }

    public String contentType() {
        return contentType;
    }

    public byte[] imageBytes() {
        return imageBytes;
    }

    public String authorization() {
        return authorization;
    }

    public Instant createdAt() {
        return createdAt;
    }

    public boolean started() {
        return started.get();
    }

    public void markStarted() {
        started.set(true);
    }

    public boolean canceled() {
        return canceled.get();
    }

    public boolean cancel(String reason) {
        boolean changed = canceled.compareAndSet(false, true);
        if (changed) {
            this.cancelReason = reason == null || reason.isBlank() ? "canceled" : reason;
        }
        return changed;
    }

    public String cancelReason() {
        return cancelReason;
    }

    public CompletableFuture<SeeThroughResult> resultFuture() {
        return resultFuture;
    }
}
