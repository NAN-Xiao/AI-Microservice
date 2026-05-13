package com.elex.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * llm_queue 的配置绑定对象。
 *
 * <p>配置前缀为 {@code llm.queue}，用于控制上游目标地址、队列容量、超时时间和入队路径。</p>
 */
@ConfigurationProperties(prefix = "llm.queue")
public class LlmQueueProperties {
    private String targetBaseUrl;
    private int capacity = 2;
    private Duration requestTimeout = Duration.ofMinutes(10);
    private Duration upstreamTimeout = Duration.ofMinutes(10);
    private Duration historyPollInterval = Duration.ofSeconds(1);
    private int maxInMemorySize = 100 * 1024 * 1024;
    private List<String> queuedPaths = new ArrayList<>(List.of("/prompt", "/promot", "/api/see-through/convert"));
    private List<String> asyncTaskPaths = new ArrayList<>(List.of("/promot", "/prompt"));
    private String historyPath = "/history";

    public String getTargetBaseUrl() {
        return targetBaseUrl;
    }

    public void setTargetBaseUrl(String targetBaseUrl) {
        this.targetBaseUrl = targetBaseUrl;
    }

    public int getCapacity() {
        return capacity;
    }

    public void setCapacity(int capacity) {
        this.capacity = capacity;
    }

    public Duration getRequestTimeout() {
        return requestTimeout;
    }

    public void setRequestTimeout(Duration requestTimeout) {
        this.requestTimeout = requestTimeout;
    }

    public Duration getUpstreamTimeout() {
        return upstreamTimeout;
    }

    public void setUpstreamTimeout(Duration upstreamTimeout) {
        this.upstreamTimeout = upstreamTimeout;
    }

    public Duration getHistoryPollInterval() {
        return historyPollInterval;
    }

    public void setHistoryPollInterval(Duration historyPollInterval) {
        this.historyPollInterval = historyPollInterval;
    }

    public int getMaxInMemorySize() {
        return maxInMemorySize;
    }

    public void setMaxInMemorySize(int maxInMemorySize) {
        this.maxInMemorySize = maxInMemorySize;
    }

    public List<String> getQueuedPaths() {
        return queuedPaths;
    }

    public void setQueuedPaths(List<String> queuedPaths) {
        this.queuedPaths = queuedPaths;
    }

    public List<String> getAsyncTaskPaths() {
        return asyncTaskPaths;
    }

    public void setAsyncTaskPaths(List<String> asyncTaskPaths) {
        this.asyncTaskPaths = asyncTaskPaths;
    }

    public String getHistoryPath() {
        return historyPath;
    }

    public void setHistoryPath(String historyPath) {
        this.historyPath = historyPath;
    }

    /**
     * 获取去掉末尾斜杠后的上游基础地址。
     *
     * <p>统一规范化后，转发器拼接路径时不会出现重复斜杠。</p>
     *
     * @return 规范化后的上游基础地址
     */
    public String normalizedTargetBaseUrl() {
        if (targetBaseUrl == null || targetBaseUrl.isBlank()) {
            throw new IllegalStateException("请配置 llm.queue.target-base-url");
        }
        String value = targetBaseUrl.trim();
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }
}
