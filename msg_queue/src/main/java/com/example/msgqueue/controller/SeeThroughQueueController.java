package com.example.msgqueue.controller;

import com.example.msgqueue.model.SeeThroughQueueStatsResponse;
import com.example.msgqueue.model.SeeThroughResult;
import com.example.msgqueue.model.SeeThroughTask;
import com.example.msgqueue.service.SeeThroughClient;
import com.example.msgqueue.service.SeeThroughTaskQueueService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.context.request.async.DeferredResult;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

@RestController
public class SeeThroughQueueController {

    private static final long ASYNC_TIMEOUT_MS = 610_000L;

    private final SeeThroughTaskQueueService queueService;
    private final SeeThroughClient seeThroughClient;
    private final ExecutorService requestWaiterPool = Executors.newCachedThreadPool();

    public SeeThroughQueueController(SeeThroughTaskQueueService queueService, SeeThroughClient seeThroughClient) {
        this.queueService = queueService;
        this.seeThroughClient = seeThroughClient;
    }

    @PreDestroy
    public void shutdown() {
        requestWaiterPool.shutdownNow();
        try {
            requestWaiterPool.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    @GetMapping("/api/see-through/health")
    public ResponseEntity<String> health() {
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_JSON)
                .body(seeThroughClient.health());
    }

    @GetMapping({"/api/see-through", "/api/see-through/"})
    public ResponseEntity<Void> apiRoot() {
        return ResponseEntity.status(HttpStatus.FOUND)
                .header(HttpHeaders.LOCATION, "/api/see-through/ui")
                .build();
    }

    @GetMapping("/api/see-through/ui")
    public ResponseEntity<byte[]> ui(HttpServletRequest request) {
        ResponseEntity<byte[]> response = seeThroughClient.getRaw("/api/see-through/ui", request.getHeader(HttpHeaders.AUTHORIZATION));
        HttpHeaders headers = new HttpHeaders();
        copyProxyHeaders(response.getHeaders(), headers);
        return new ResponseEntity<>(response.getBody(), headers, response.getStatusCode());
    }

    @GetMapping("/api/see-through/queue/stats")
    public SeeThroughQueueStatsResponse stats() {
        return queueService.stats();
    }

    @PostMapping(path = "/api/see-through/cleanup", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> cleanup(
            @RequestBody Map<String, Object> payload,
            HttpServletRequest request
    ) {
        String token = String.valueOf(payload.getOrDefault("token", "")).trim();
        if (token.isBlank()) {
            return ResponseEntity.badRequest()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"code\":400,\"message\":\"缺少 cleanup token\"}");
        }
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_JSON)
                .body(seeThroughClient.cleanup(token, request.getHeader(HttpHeaders.AUTHORIZATION)));
    }

    @PostMapping(path = "/api/see-through/cancel", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, Object>> cancel(@RequestBody Map<String, Object> payload) {
        String taskId = String.valueOf(payload.getOrDefault("taskId", "")).trim();
        if (taskId.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of(
                    "code", 400,
                    "message", "缺少 taskId"
            ));
        }

        boolean canceled = queueService.cancel(taskId, "client cancel request");
        return ResponseEntity.ok(Map.of(
                "taskId", taskId,
                "canceled", canceled
        ));
    }

    @PostMapping(path = "/api/see-through/convert", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public DeferredResult<ResponseEntity<byte[]>> convert(
            @RequestPart("image") MultipartFile image,
            @RequestParam(value = "taskId", required = false) String requestedTaskId,
            HttpServletRequest request
    ) throws IOException {
        DeferredResult<ResponseEntity<byte[]>> deferredResult = new DeferredResult<>(ASYNC_TIMEOUT_MS);

        String contentType = image.getContentType();
        if (contentType == null || !contentType.startsWith("image/")) {
            deferredResult.setResult(ResponseEntity.badRequest()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(errorBody("仅支持图片文件，当前类型: " + contentType)));
            return deferredResult;
        }
        if (image.isEmpty()) {
            deferredResult.setResult(ResponseEntity.badRequest()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(errorBody("图片内容为空")));
            return deferredResult;
        }
        String filename = image.getOriginalFilename() == null || image.getOriginalFilename().isBlank()
                ? "input.png"
                : image.getOriginalFilename();
        String taskId = requestedTaskId == null || requestedTaskId.isBlank()
                ? UUID.randomUUID().toString()
                : requestedTaskId.trim();
        SeeThroughTask task = SeeThroughTask.of(
                taskId,
                filename,
                contentType,
                image.getBytes(),
                request.getHeader(HttpHeaders.AUTHORIZATION)
        );

        deferredResult.onTimeout(() -> {
            queueService.cancel(task.taskId(), "HTTP async request timeout");
            deferredResult.setErrorResult(new TimeoutException("任务等待超时"));
        });
        deferredResult.onError(error -> queueService.cancel(task.taskId(), "HTTP client disconnected"));
        deferredResult.onCompletion(() -> {
            if (!task.resultFuture().isDone()) {
                queueService.cancel(task.taskId(), "HTTP request completed before task result");
            }
        });

        queueService.submit(task);
        requestWaiterPool.submit(() -> {
            try {
                SeeThroughResult result = queueService.waitForResult(task);
                HttpHeaders headers = new HttpHeaders();
                headers.setContentType(MediaType.parseMediaType(result.contentType()));
                headers.setContentDisposition(ContentDisposition.attachment().filename(result.filename()).build());
                headers.set("X-Task-Id", task.taskId());
                if (result.cleanupToken() != null && !result.cleanupToken().isBlank()) {
                    headers.set("X-Cleanup-Token", result.cleanupToken());
                }
                for (String setCookie : result.setCookieHeaders()) {
                    headers.add(HttpHeaders.SET_COOKIE, setCookie);
                }

                deferredResult.setResult(new ResponseEntity<>(result.body(), headers, HttpStatus.OK));
            } catch (Exception ex) {
                deferredResult.setErrorResult(ex);
            }
        });

        return deferredResult;
    }

    private byte[] errorBody(String message) {
        return ("{\"code\":400,\"message\":\"" + escapeJson(message) + "\"}").getBytes(StandardCharsets.UTF_8);
    }

    private void copyProxyHeaders(HttpHeaders source, HttpHeaders target) {
        MediaType contentType = source.getContentType();
        if (contentType != null) {
            target.setContentType(contentType);
        }
        String contentDisposition = source.getFirst(HttpHeaders.CONTENT_DISPOSITION);
        if (contentDisposition != null && !contentDisposition.isBlank()) {
            target.set(HttpHeaders.CONTENT_DISPOSITION, contentDisposition);
        }
        String cacheControl = source.getFirst(HttpHeaders.CACHE_CONTROL);
        if (cacheControl != null && !cacheControl.isBlank()) {
            target.set(HttpHeaders.CACHE_CONTROL, cacheControl);
        }
    }

    private String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
