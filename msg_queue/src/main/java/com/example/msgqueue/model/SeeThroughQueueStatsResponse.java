package com.example.msgqueue.model;

public record SeeThroughQueueStatsResponse(
        int queueSize,
        int maxSize,
        long processedCount,
        long failedCount,
        long canceledCount,
        String runningTaskId
) {
}
