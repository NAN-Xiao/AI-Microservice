package com.elex.service;

import com.elex.client.WebClientRequestForwarder;
import com.elex.config.LlmQueueProperties;
import com.elex.model.QueuedHttpRequest;
import com.elex.model.QueuedHttpResponse;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.TimeoutException;
import java.util.function.BooleanSupplier;

/**
 * promot/prompt 异步任务执行器。
 *
 * <p>这类接口的首次响应只表示任务已被上游接收，真正完成状态需要按返回 id 轮询 history。
 * 因此队列 worker 必须等 history 完成后，才能释放下一个队列任务。</p>
 */
@Service
public class PromptTaskExecutor {
    private static final Logger log = LoggerFactory.getLogger(PromptTaskExecutor.class);
    private static final int MAX_LOG_BODY_LENGTH = 4096;
    private static final Set<String> TASK_ID_FIELDS = Set.of("prompt_id", "id", "task_id");
    private static final Set<String> FAILED_STATUS = Set.of("failed", "failure", "error");
    private static final Set<String> COMPLETED_STATUS = Set.of("success", "succeeded", "completed", "complete", "done");

    private final WebClientRequestForwarder forwarder;
    private final LlmQueueProperties properties;
    private final ObjectMapper objectMapper;

    /**
     * 创建异步任务执行器。
     *
     * @param forwarder HTTP 转发器
     * @param properties 队列配置
     * @param objectMapper JSON 解析器
     */
    public PromptTaskExecutor(
            WebClientRequestForwarder forwarder,
            LlmQueueProperties properties,
            ObjectMapper objectMapper
    ) {
        this.forwarder = forwarder;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    /**
     * 判断请求是否需要按异步任务语义处理。
     *
     * @param request 请求快照
     * @return true 表示需要提取任务 id 并轮询 history
     */
    public boolean supports(QueuedHttpRequest request) {
        return normalizedAsyncTaskPaths().contains(normalizePath(request.uri().getRawPath()));
    }

    /**
     * 执行 promot/prompt 请求，并等待 history 判定完成。
     *
     * @param request 原始入队请求
     * @param shouldContinue 是否继续等待
     * @return 原始 promot/prompt 响应
     * @throws Exception 上游失败、任务失败或等待超时时抛出
     */
    public QueuedHttpResponse executeAndWait(QueuedHttpRequest request, BooleanSupplier shouldContinue) throws Exception {
        QueuedHttpResponse response = forwarder.forward(request);
        log.info(
                "async prompt response targetPath={} status={} body={}",
                request.uri().getRawPath(),
                response.statusCode(),
                responseBodyForLog(response)
        );
        if (!isSuccess(response)) {
            return response;
        }

        String taskId = extractTaskId(response);
        log.info("async prompt task accepted taskId={} targetPath={}", taskId, request.uri().getRawPath());
        waitUntilCompleted(request, taskId, shouldContinue);
        return response;
    }

    private void waitUntilCompleted(
            QueuedHttpRequest sourceRequest,
            String taskId,
            BooleanSupplier shouldContinue
    ) throws Exception {
        Instant deadline = Instant.now().plus(properties.getRequestTimeout());
        Duration pollInterval = validPollInterval();

        while (shouldContinue.getAsBoolean()) {
            if (Instant.now().isAfter(deadline)) {
                throw new TimeoutException("等待 history 完成超时: " + taskId);
            }

            QueuedHttpResponse historyResponse = forwarder.forward(historyRequest(sourceRequest, taskId));
            if (isSuccess(historyResponse) && isTaskCompleted(taskId, historyResponse)) {
                log.info("async prompt task completed taskId={}", taskId);
                return;
            }
            log.info(
                    "async prompt task still running taskId={} historyStatus={}",
                    taskId,
                    historyResponse.statusCode()
            );

            sleep(pollInterval);
        }

        throw new InterruptedException("任务等待已取消: " + taskId);
    }

    private QueuedHttpRequest historyRequest(QueuedHttpRequest sourceRequest, String taskId) {
        return QueuedHttpRequest.of(
                HttpMethod.GET,
                URI.create(normalizeHistoryPath() + "/" + encodePathSegment(taskId)),
                sourceRequest.headers(),
                new byte[0]
        );
    }

    private String extractTaskId(QueuedHttpResponse response) throws Exception {
        JsonNode root = objectMapper.readTree(response.body());
        for (String field : TASK_ID_FIELDS) {
            JsonNode value = root.path(field);
            if (value.isTextual() && !value.asText().isBlank()) {
                return value.asText();
            }
        }
        throw new IllegalStateException("promot 响应中缺少任务 id 字段，已尝试字段: " + TASK_ID_FIELDS);
    }

    private boolean isTaskCompleted(String taskId, QueuedHttpResponse response) throws Exception {
        JsonNode root = objectMapper.readTree(response.body());
        JsonNode taskNode = root.path(taskId);
        if (taskNode.isMissingNode() || taskNode.isNull()) {
            return false;
        }

        JsonNode statusNode = taskNode.path("status");
        if (statusNode.path("completed").asBoolean(false)) {
            return true;
        }

        String status = statusNode.path("status_str").asText("");
        if (status.isBlank()) {
            status = taskNode.path("status").asText("");
        }
        String normalizedStatus = status.toLowerCase(Locale.ROOT);
        if (FAILED_STATUS.contains(normalizedStatus)) {
            throw new IllegalStateException("上游任务执行失败: " + taskId + ", status=" + status);
        }
        if (COMPLETED_STATUS.contains(normalizedStatus)) {
            return true;
        }

        JsonNode outputs = taskNode.path("outputs");
        return outputs.isObject() && outputs.size() > 0;
    }

    private Set<String> normalizedAsyncTaskPaths() {
        List<String> paths = properties.getAsyncTaskPaths();
        Set<String> normalized = new LinkedHashSet<>();
        if (paths == null) {
            return normalized;
        }
        for (String path : paths) {
            String normalizedPath = normalizePath(path);
            if (!normalizedPath.isBlank()) {
                normalized.add(normalizedPath);
            }
        }
        return normalized;
    }

    private Duration validPollInterval() {
        Duration interval = properties.getHistoryPollInterval();
        if (interval == null || interval.isZero() || interval.isNegative()) {
            return Duration.ofSeconds(1);
        }
        return interval;
    }

    private String normalizeHistoryPath() {
        return normalizePath(properties.getHistoryPath());
    }

    private static boolean isSuccess(QueuedHttpResponse response) {
        return response.statusCode() >= 200 && response.statusCode() < 300;
    }

    private static String normalizePath(String path) {
        if (path == null || path.isBlank()) {
            return "";
        }
        String value = path.trim();
        if (!value.startsWith("/")) {
            value = "/" + value;
        }
        while (value.length() > 1 && value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    private static String encodePathSegment(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }

    private static String responseBodyForLog(QueuedHttpResponse response) {
        String body = new String(response.body(), StandardCharsets.UTF_8);
        if (body.length() <= MAX_LOG_BODY_LENGTH) {
            return body;
        }
        return body.substring(0, MAX_LOG_BODY_LENGTH) + "...(truncated)";
    }

    private static void sleep(Duration interval) throws InterruptedException {
        Thread.sleep(interval.toMillis());
    }
}
