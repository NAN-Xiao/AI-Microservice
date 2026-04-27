package com.example.msgqueue.model;

public record QueueStatsResponse(
        int queueSize,
        long processedCount,
        long failedCount
) {
}

