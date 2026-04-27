package com.example.msgqueue.model;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public record QueueMessage(
        String messageId,
        String topic,
        Map<String, Object> payload,
        Instant createdAt
) {
    public static QueueMessage of(String topic, Map<String, Object> payload) {
        return new QueueMessage(UUID.randomUUID().toString(), topic, payload, Instant.now());
    }
}

