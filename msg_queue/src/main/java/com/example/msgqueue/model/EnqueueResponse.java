package com.example.msgqueue.model;

public record EnqueueResponse(
        String messageId,
        String status,
        int queueSize
) {
}

