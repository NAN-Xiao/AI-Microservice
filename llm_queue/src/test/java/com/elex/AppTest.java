package com.elex;

import com.elex.service.LlmQueueService;
import com.elex.service.QueueRuleService;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class AppTest {
    private static final AtomicInteger ACTIVE_REQUESTS = new AtomicInteger();
    private static final AtomicInteger MAX_ACTIVE_REQUESTS = new AtomicInteger();
    private static final AtomicInteger PROMOT_REQUESTS = new AtomicInteger();
    private static final AtomicInteger HISTORY_POLLS = new AtomicInteger();
    private static final Map<String, AtomicInteger> HISTORY_POLLS_BY_TASK = new ConcurrentHashMap<>();
    private static final List<String> UPSTREAM_BODIES = Collections.synchronizedList(new ArrayList<>());
    private static HttpServer upstream;
    private static ExecutorService upstreamExecutor;

    @LocalServerPort
    int port;

    @Autowired
    LlmQueueService queueService;

    @Autowired
    QueueRuleService queueRuleService;

    @BeforeEach
    void resetState() {
        System.clearProperty("llm.queue.config-file");
        queueRuleService.updateRules(List.of("/api/see-through/convert"));
        ACTIVE_REQUESTS.set(0);
        MAX_ACTIVE_REQUESTS.set(0);
        PROMOT_REQUESTS.set(0);
        HISTORY_POLLS.set(0);
        HISTORY_POLLS_BY_TASK.clear();
        UPSTREAM_BODIES.clear();
    }

    @AfterAll
    static void stopUpstream() {
        if (upstream != null) {
            upstream.stop(0);
        }
        if (upstreamExecutor != null) {
            upstreamExecutor.shutdownNow();
        }
    }

    @DynamicPropertySource
    static void registerProperties(DynamicPropertyRegistry registry) {
        ensureUpstreamStarted();
        registry.add("llm.queue.target-base-url", () -> "http://127.0.0.1:" + upstream.getAddress().getPort());
        registry.add("llm.queue.capacity", () -> "20");
        registry.add("llm.queue.request-timeout", () -> "10s");
        registry.add("llm.queue.upstream-timeout", () -> "5s");
        registry.add("llm.queue.history-poll-interval", () -> "100ms");
        registry.add("llm.queue.async-task-paths[0]", () -> "/promot");
        registry.add("llm.queue.async-task-paths[1]", () -> "/prompt");
        registry.add("llm.queue.history-path", () -> "/history");
        registry.add("llm.queue.max-in-memory-size", () -> String.valueOf(2 * 1024 * 1024));
        registry.add("server.port", () -> "0");
    }

    @Test
    void requestsAreForwardedSerially() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        List<CompletableFuture<HttpResponse<String>>> futures = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://127.0.0.1:" + port + "/proxy/api/see-through/convert"))
                    .POST(HttpRequest.BodyPublishers.ofString("convert-" + i))
                    .build();
            futures.add(client.sendAsync(request, HttpResponse.BodyHandlers.ofString()));
        }

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).get();

        for (CompletableFuture<HttpResponse<String>> future : futures) {
            assertEquals(200, future.get().statusCode());
            assertTrue(future.get().body().startsWith("convert-ok:convert-"));
        }
        assertEquals(6, UPSTREAM_BODIES.size());
        assertEquals(1, MAX_ACTIVE_REQUESTS.get());
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void nonQueuedProxyRequestsAreForwardedDirectly() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        List<CompletableFuture<HttpResponse<String>>> futures = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://127.0.0.1:" + port + "/proxy/upload/image"))
                    .POST(HttpRequest.BodyPublishers.ofString("upload-" + i))
                    .build();
            futures.add(client.sendAsync(request, HttpResponse.BodyHandlers.ofString()));
        }

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).get();

        for (CompletableFuture<HttpResponse<String>> future : futures) {
            assertEquals(200, future.get().statusCode());
            assertTrue(future.get().body().startsWith("upload-ok:upload-"));
        }
        assertEquals(6, UPSTREAM_BODIES.size());
        assertTrue(MAX_ACTIVE_REQUESTS.get() > 1);
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void promotRequestsWaitForHistoryBeforeNextTaskStarts() throws Exception {
        queueRuleService.updateRules(List.of("/promot"));
        HttpClient client = HttpClient.newHttpClient();
        List<CompletableFuture<HttpResponse<String>>> futures = new ArrayList<>();
        for (int i = 0; i < 2; i++) {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://127.0.0.1:" + port + "/proxy/promot"))
                    .POST(HttpRequest.BodyPublishers.ofString("promot-" + i))
                    .build();
            futures.add(client.sendAsync(request, HttpResponse.BodyHandlers.ofString()));
        }

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).get();

        for (CompletableFuture<HttpResponse<String>> future : futures) {
            assertEquals(200, future.get().statusCode());
            assertTrue(future.get().body().contains("prompt_id"));
        }
        assertEquals(2, UPSTREAM_BODIES.size());
        assertTrue(HISTORY_POLLS.get() >= 4);
        assertTrue(HISTORY_POLLS_BY_TASK.values().stream().allMatch(count -> count.get() >= 2));
        assertEquals(1, MAX_ACTIVE_REQUESTS.get());
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void proxyReturnsTargetServiceResponse() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + "/proxy/v1/created"))
                .POST(HttpRequest.BodyPublishers.ofString("create-request"))
                .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());

        assertEquals(201, response.statusCode());
        assertEquals("target-created", response.body());
        assertEquals("from-upstream", response.headers().firstValue("X-Upstream-Result").orElse(""));
        assertEquals(1, UPSTREAM_BODIES.size());
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void proxyForwardsLargeBinaryResponse() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + "/proxy/view?filename=result.psd"))
                .GET()
                .build();

        HttpResponse<byte[]> response = client.send(request, HttpResponse.BodyHandlers.ofByteArray());

        assertEquals(200, response.statusCode());
        assertEquals(1024 * 1024, response.body().length);
        assertTrue(Arrays.equals(largePayload(), response.body()));
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void healthDoesNotEnterQueue() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + "/health/"))
                .GET()
                .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());

        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"status\":\"UP\""));
        assertEquals(0, UPSTREAM_BODIES.size());
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void unmatchedPathDoesNotEnterQueue() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + "/v1/chat/completions"))
                .POST(HttpRequest.BodyPublishers.ofString("request"))
                .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());

        assertEquals(404, response.statusCode());
        assertEquals(0, UPSTREAM_BODIES.size());
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void adminReloadUpdatesQueueRulesFromLocalConfigFile() throws Exception {
        Path configFile = Files.createTempFile("llm-queue-test-", ".yml");
        Files.writeString(configFile, """
                llm:
                  queue:
                    queued-paths:
                      - /upload/image
                """, StandardCharsets.UTF_8);
        System.setProperty("llm.queue.config-file", configFile.toString());

        HttpClient client = HttpClient.newHttpClient();
        HttpRequest reloadRequest = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + port + "/admin/reload"))
                .POST(HttpRequest.BodyPublishers.noBody())
                .build();

        HttpResponse<String> reloadResponse = client.send(reloadRequest, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, reloadResponse.statusCode());
        assertTrue(reloadResponse.body().contains("/upload/image"));

        List<CompletableFuture<HttpResponse<String>>> futures = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://127.0.0.1:" + port + "/proxy/upload/image"))
                    .POST(HttpRequest.BodyPublishers.ofString("reloaded-upload-" + i))
                    .build();
            futures.add(client.sendAsync(request, HttpResponse.BodyHandlers.ofString()));
        }

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).get();

        for (CompletableFuture<HttpResponse<String>> future : futures) {
            assertEquals(200, future.get().statusCode());
            assertTrue(future.get().body().startsWith("upload-ok:reloaded-upload-"));
        }
        assertEquals(6, UPSTREAM_BODIES.size());
        assertEquals(1, MAX_ACTIVE_REQUESTS.get());
        assertEquals(0, queueService.queueSize());
    }

    private static void ensureUpstreamStarted() {
        if (upstream != null) {
            return;
        }
        try {
            upstream = HttpServer.create(new InetSocketAddress(0), 0);
        } catch (Exception e) {
            throw new IllegalStateException("启动测试上游服务失败", e);
        }
        upstream.createContext("/api/see-through/convert", exchange -> {
            int active = ACTIVE_REQUESTS.incrementAndGet();
            MAX_ACTIVE_REQUESTS.updateAndGet(previous -> Math.max(previous, active));
            try {
                sleepQuietly(80);
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                UPSTREAM_BODIES.add(body);
                byte[] response = ("convert-ok:" + body).getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200, response.length);
                try (OutputStream responseBody = exchange.getResponseBody()) {
                    responseBody.write(response);
                }
            } finally {
                ACTIVE_REQUESTS.decrementAndGet();
                exchange.close();
            }
        });
        upstream.createContext("/upload/image", exchange -> {
            int active = ACTIVE_REQUESTS.incrementAndGet();
            MAX_ACTIVE_REQUESTS.updateAndGet(previous -> Math.max(previous, active));
            try {
                sleepQuietly(80);
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                UPSTREAM_BODIES.add(body);
                byte[] response = ("upload-ok:" + body).getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200, response.length);
                try (OutputStream responseBody = exchange.getResponseBody()) {
                    responseBody.write(response);
                }
            } finally {
                ACTIVE_REQUESTS.decrementAndGet();
                exchange.close();
            }
        });
        upstream.createContext("/promot", exchange -> {
            int active = ACTIVE_REQUESTS.incrementAndGet();
            MAX_ACTIVE_REQUESTS.updateAndGet(previous -> Math.max(previous, active));
            try {
                int index = PROMOT_REQUESTS.incrementAndGet();
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                UPSTREAM_BODIES.add(body);
                byte[] response = ("{\"prompt_id\":\"task-" + index + "\"}").getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200, response.length);
                try (OutputStream responseBody = exchange.getResponseBody()) {
                    responseBody.write(response);
                }
            } finally {
                ACTIVE_REQUESTS.decrementAndGet();
                exchange.close();
            }
        });
        upstream.createContext("/history", exchange -> {
            int active = ACTIVE_REQUESTS.incrementAndGet();
            MAX_ACTIVE_REQUESTS.updateAndGet(previous -> Math.max(previous, active));
            try {
                int poll = HISTORY_POLLS.incrementAndGet();
                String path = exchange.getRequestURI().getPath();
                String taskId = path.substring("/history/".length());
                int taskPoll = HISTORY_POLLS_BY_TASK.computeIfAbsent(taskId, ignored -> new AtomicInteger())
                        .incrementAndGet();
                boolean completed = taskPoll >= 2;
                byte[] response = historyResponse(taskId, completed).getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, response.length);
                try (OutputStream responseBody = exchange.getResponseBody()) {
                    responseBody.write(response);
                }
            } finally {
                ACTIVE_REQUESTS.decrementAndGet();
                exchange.close();
            }
        });
        upstream.createContext("/v1/created", exchange -> {
            ACTIVE_REQUESTS.incrementAndGet();
            try {
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                UPSTREAM_BODIES.add(body);
                byte[] response = "target-created".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("X-Upstream-Result", "from-upstream");
                exchange.sendResponseHeaders(201, response.length);
                try (OutputStream responseBody = exchange.getResponseBody()) {
                    responseBody.write(response);
                }
            } finally {
                ACTIVE_REQUESTS.decrementAndGet();
                exchange.close();
            }
        });
        upstream.createContext("/view", exchange -> {
            byte[] response = largePayload();
            exchange.getResponseHeaders().set("Content-Type", "application/octet-stream");
            exchange.sendResponseHeaders(200, response.length);
            try (OutputStream responseBody = exchange.getResponseBody()) {
                responseBody.write(response);
            } finally {
                exchange.close();
            }
        });
        upstreamExecutor = Executors.newCachedThreadPool();
        upstream.setExecutor(upstreamExecutor);
        upstream.start();
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static byte[] largePayload() {
        byte[] payload = new byte[1024 * 1024];
        for (int i = 0; i < payload.length; i++) {
            payload[i] = (byte) (i % 251);
        }
        return payload;
    }

    private static String historyResponse(String taskId, boolean completed) {
        if (!completed) {
            return "{\"" + taskId + "\":{\"status\":{\"completed\":false,\"status_str\":\"running\"},\"outputs\":{}}}";
        }
        return "{\"" + taskId + "\":{\"status\":{\"completed\":true,\"status_str\":\"success\"},\"outputs\":{\"9\":{}}}}";
    }
}
