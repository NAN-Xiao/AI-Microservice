package com.example.msgqueue.config;

import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.util.ArrayList;
import java.util.List;

@Validated
@ConfigurationProperties(prefix = "queue")
public class QueueProperties {

    @Min(1)
    private int maxSize = 200;

    @Min(1)
    private int workerCount = 1;

    @Min(0)
    private int workerDelayMs = 0;

    private List<String> longTaskPathPrefixes = new ArrayList<>(List.of("/report/generate"));

    public int getMaxSize() {
        return maxSize;
    }

    public void setMaxSize(int maxSize) {
        this.maxSize = maxSize;
    }

    public int getWorkerCount() {
        return workerCount;
    }

    public void setWorkerCount(int workerCount) {
        this.workerCount = workerCount;
    }

    public int getWorkerDelayMs() {
        return workerDelayMs;
    }

    public void setWorkerDelayMs(int workerDelayMs) {
        this.workerDelayMs = workerDelayMs;
    }

    public List<String> getLongTaskPathPrefixes() {
        return longTaskPathPrefixes;
    }

    public void setLongTaskPathPrefixes(List<String> longTaskPathPrefixes) {
        this.longTaskPathPrefixes = longTaskPathPrefixes == null ? new ArrayList<>() : new ArrayList<>(longTaskPathPrefixes);
    }
}
