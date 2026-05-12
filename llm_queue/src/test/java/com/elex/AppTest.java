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
import java.util.Collections;
import java.util.List;
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
        queueRuleService.updateRules(List.of("/prompt"));
        ACTIVE_REQUESTS.set(0);
        MAX_ACTIVE_REQUESTS.set(0);
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
        registry.add("server.port", () -> "0");
    }

    @Test
    void requestsAreForwardedSerially() throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        List<CompletableFuture<HttpResponse<String>>> futures = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create("http://127.0.0.1:" + port + "/proxy/prompt"))
                    .POST(HttpRequest.BodyPublishers.ofString("prompt-" + i))
                    .build();
            futures.add(client.sendAsync(request, HttpResponse.BodyHandlers.ofString()));
        }

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).get();

        for (CompletableFuture<HttpResponse<String>> future : futures) {
            assertEquals(200, future.get().statusCode());
            assertTrue(future.get().body().startsWith("prompt-ok:prompt-"));
        }
        assertEquals(6, UPSTREAM_BODIES.size());
        assertEquals(1, MAX_ACTIVE_REQUESTS.get());
        assertEquals(0, queueService.queueSize());
    }

    @Test
    void nonPromptProxyRequestsAreForwardedDirectly() throws Exception {
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
        upstream.createContext("/prompt", exchange -> {
            int active = ACTIVE_REQUESTS.incrementAndGet();
            MAX_ACTIVE_REQUESTS.updateAndGet(previous -> Math.max(previous, active));
            try {
                sleepQuietly(80);
                String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                UPSTREAM_BODIES.add(body);
                byte[] response = ("prompt-ok:" + body).getBytes(StandardCharsets.UTF_8);
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
}
