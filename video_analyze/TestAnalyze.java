import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.stream.Collectors;

/**
 * Video Analyze API 测试（Java 版）
 * 对应 video_analyze/test_analyze.py 当前版本：
 * 1) 健康检查
 * 2) 参数校验
 * 3) 同步分析
 * 4) 10 并发异步任务 + 每 5 秒轮询并打印返回参数
 */
public class TestAnalyze {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final HttpClient CLIENT = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    private static final String BASE_URL = "http://10.1.6.76:9001";
    private static final String VIDEO_URL = "https://elex-apx-download.oss-cn-beijing.aliyuncs.com/material_sensortower/5a/5ae0beb8fa34103f.mp4";

    private static final int SYNC_TIMEOUT_SECONDS = 600;
    private static final int POLL_INTERVAL_SECONDS = 5;
    private static final int POLL_MAX_WAIT_SECONDS = 600;
    private static final int ASYNC_TASK_COUNT = 10;

    private static class ApiResp {
        final int httpStatus;
        final JsonNode json;
        final String raw;

        ApiResp(int httpStatus, JsonNode json, String raw) {
            this.httpStatus = httpStatus;
            this.json = json;
            this.raw = raw;
        }
    }

    private static class SubmitResult {
        final int idx;
        final boolean ok;
        final Integer httpStatus;
        final Integer code;
        final String message;
        final String taskId;

        SubmitResult(int idx, boolean ok, Integer httpStatus, Integer code, String message, String taskId) {
            this.idx = idx;
            this.ok = ok;
            this.httpStatus = httpStatus;
            this.code = code;
            this.message = message;
            this.taskId = taskId;
        }
    }

    private static void separator(String title) {
        System.out.println();
        System.out.println("============================================================");
        System.out.println("  " + title);
        System.out.println("============================================================");
    }

    private static String pretty(JsonNode node) {
        try {
            return MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(node);
        } catch (Exception e) {
            return String.valueOf(node);
        }
    }

    private static ApiResp getJson(String url, int timeoutSeconds) throws Exception {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(timeoutSeconds))
                .GET()
                .build();
        HttpResponse<String> resp = CLIENT.send(req, HttpResponse.BodyHandlers.ofString());
        JsonNode json = null;
        try {
            json = MAPPER.readTree(resp.body());
        } catch (Exception ignore) {
        }
        return new ApiResp(resp.statusCode(), json, resp.body());
    }

    private static ApiResp postJson(String url, JsonNode body, int timeoutSeconds) throws Exception {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(timeoutSeconds))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                .build();
        HttpResponse<String> resp = CLIENT.send(req, HttpResponse.BodyHandlers.ofString());
        JsonNode json = null;
        try {
            json = MAPPER.readTree(resp.body());
        } catch (Exception ignore) {
        }
        return new ApiResp(resp.statusCode(), json, resp.body());
    }

    // 3) 异步任务并发提交 + 轮询
    private static SubmitResult submitAsyncTask(String submitUrl, JsonNode payload, int idx) {
        try {
            ApiResp resp = postJson(submitUrl, payload, 30);
            if (resp.json == null) {
                return new SubmitResult(idx, false, resp.httpStatus, null, "非 JSON 响应", null);
            }
            Integer code = resp.json.path("code").isInt() ? resp.json.path("code").asInt() : null;
            String message = resp.json.path("message").asText(null);
            String taskId = resp.json.path("data").path("task_id").asText(null);
            boolean ok = resp.httpStatus == 200 && code != null && code == 200 && taskId != null && !taskId.isBlank();
            return new SubmitResult(idx, ok, resp.httpStatus, code, message, ok ? taskId : null);
        } catch (Exception e) {
            return new SubmitResult(idx, false, null, null, e.getMessage(), null);
        }
    }

    private static boolean testAsyncTask() {
        separator("3. 异步任务并发测试  POST /api/video-analyze/tasks × " + ASYNC_TASK_COUNT);
        String submitUrl = BASE_URL + "/api/video-analyze/tasks";
        ObjectNode payload = MAPPER.createObjectNode();
        payload.put("video_url", VIDEO_URL);

        System.out.println("并发提交任务数: " + ASYNC_TASK_COUNT);
        try {
            long submitStart = System.currentTimeMillis();
            ExecutorService pool = Executors.newFixedThreadPool(ASYNC_TASK_COUNT);

                   
            List<Callable<SubmitResult>> calls = new ArrayList<>();
            for (int i = 1; i <= ASYNC_TASK_COUNT; i++) {
                final int idx = i;
                calls.add(() -> submitAsyncTask(submitUrl, payload, idx));
            }

            List<Future<SubmitResult>> futures = pool.invokeAll(calls);
            pool.shutdown();

            List<SubmitResult> submitResults = new ArrayList<>();
            for (Future<SubmitResult> f : futures) {
                try {
                    submitResults.add(f.get());
                } catch (ExecutionException e) {
                    submitResults.add(new SubmitResult(-1, false, null, null, e.getMessage(), null));
                }
            }
            submitResults.sort((a, b) -> Integer.compare(a.idx, b.idx));

            double submitElapsed = (System.currentTimeMillis() - submitStart) / 1000.0;
            System.out.printf("提交完成，耗时: %.2fs%n", submitElapsed);
            for (SubmitResult r : submitResults) {
                String icon = r.ok ? "✅" : "❌";
                System.out.printf("  %s #%02d http=%s code=%s task_id=%s%n",
                        icon, r.idx, String.valueOf(r.httpStatus), String.valueOf(r.code), String.valueOf(r.taskId));
            }

            List<SubmitResult> failedSubmit = submitResults.stream()
                    .filter(x -> !x.ok)
                    .collect(Collectors.toList());
            if (!failedSubmit.isEmpty()) {
                System.out.printf("%n❌ 存在提交失败任务: %d/%d%n", failedSubmit.size(), ASYNC_TASK_COUNT);
                for (SubmitResult r : failedSubmit) {
                    System.out.printf("  - #%02d: %s%n", r.idx, r.message);
                }
                return false;
            }

            List<String> taskIds = submitResults.stream()
                    .map(r -> r.taskId)
                    .collect(Collectors.toList());
            System.out.printf("%n开始轮询 %d 个任务（间隔 %ds，最多等待 %ds）...%n%n",
                    taskIds.size(), POLL_INTERVAL_SECONDS, POLL_MAX_WAIT_SECONDS);

            Map<String, String> taskStatus = new LinkedHashMap<>();
            Map<String, JsonNode> taskResult = new LinkedHashMap<>();
            for (String tid : taskIds) {
                taskStatus.put(tid, "pending");
            }

            long pollStart = System.currentTimeMillis();
            while ((System.currentTimeMillis() - pollStart) / 1000.0 < POLL_MAX_WAIT_SECONDS) {
                long cycleStart = System.currentTimeMillis();
                double elapsed = (System.currentTimeMillis() - pollStart) / 1000.0;
                int done = 0;
                int failed = 0;

                for (String tid : taskIds) {
                    String current = taskStatus.get(tid);
                    if ("completed".equals(current) || "failed".equals(current)) {
                        if ("completed".equals(current)) {
                            done++;
                        } else {
                            failed++;
                        }
                        continue;
                    }

                    ApiResp resp = getJson(BASE_URL + "/api/video-analyze/tasks/" + tid, 10);
                    if (resp.json == null) {
                        System.out.printf("    返回参数 task_id=%s code=null message=非JSON status=unknown error_code=null error=%s duration_seconds=null%n",
                                tid, resp.raw);
                        continue;
                    }

                    JsonNode taskData = resp.json.path("data");
                    String status = taskData.path("status").asText("unknown");
                    taskStatus.put(tid, status);

                    System.out.printf(
                            "    返回参数 task_id=%s code=%s message=%s status=%s error_code=%s error=%s duration_seconds=%s%n",
                            tid,
                            safeText(resp.json.get("code")),
                            safeText(resp.json.get("message")),
                            safeText(taskData.get("status")),
                            safeText(taskData.get("error_code")),
                            safeText(taskData.get("error")),
                            safeText(taskData.get("duration_seconds"))
                    );

                    if ("completed".equals(status) || "failed".equals(status)) {
                        taskResult.put(tid, taskData);
                    }
                    if ("completed".equals(status)) {
                        done++;
                    } else if ("failed".equals(status)) {
                        failed++;
                    }
                }

                System.out.printf("  [%.1fs] completed=%d/%d failed=%d/%d%n",
                        elapsed, done, taskIds.size(), failed, taskIds.size());

                if (done + failed == taskIds.size()) {
                    System.out.println();
                    System.out.println("全部任务进入最终态。");
                    System.out.println("  完成: " + done);
                    System.out.println("  失败: " + failed);

                    if (failed > 0) {
                        System.out.println("❌ 异步任务并发测试失败（存在 failed）");
                        for (Map.Entry<String, JsonNode> e : taskResult.entrySet()) {
                            JsonNode data = e.getValue();
                            if ("failed".equals(data.path("status").asText())) {
                                System.out.printf("  - %s: %s%n", e.getKey(), data.path("error").asText(""));
                            }
                        }
                        return false;
                    }

                    String firstTid = taskIds.get(0);
                    JsonNode sample = taskResult.get(firstTid);
                    System.out.printf("%n样例任务结果（task_id=%s）:%n", firstTid);
                    System.out.println(pretty(sample.path("result")));
                    System.out.println("✅ 异步任务并发测试成功");
                    return true;
                }

                long spentMs = System.currentTimeMillis() - cycleStart;
                long sleepMs = Math.max(0, POLL_INTERVAL_SECONDS * 1000L - spentMs);
                Thread.sleep(sleepMs);
            }

            List<String> unfinished = taskIds.stream()
                    .filter(tid -> {
                        String s = taskStatus.get(tid);
                        return !"completed".equals(s) && !"failed".equals(s);
                    })
                    .collect(Collectors.toList());
            System.out.printf("❌ 轮询超时（等待 %ds），未完成任务数: %d%n", POLL_MAX_WAIT_SECONDS, unfinished.size());
            for (String tid : unfinished) {
                System.out.printf("  - %s: %s%n", tid, taskStatus.get(tid));
            }
            return false;
        } catch (Exception e) {
            System.out.println("❌ 异步任务异常: " + e.getMessage());
            return false;
        }
    }

    // 4) 参数校验
    private static boolean testValidation() {
        separator("4. 参数校验");
        String url = BASE_URL + "/api/video-analyze/analyze";
        List<Boolean> results = new ArrayList<>();

        // 4a. 空 URL
        System.out.println("\n--- 4a. 空 video_url ---");
        try {
            ObjectNode body = MAPPER.createObjectNode();
            body.put("video_url", "");
            ApiResp resp = postJson(url, body, 10);
            System.out.println("Status: " + resp.httpStatus);
            if (resp.json != null) {
                System.out.println(pretty(resp.json));
            } else {
                System.out.println(resp.raw);
            }
            if (resp.httpStatus == 422) {
                System.out.println("✅ 空 URL 校验通过（返回 422）");
                results.add(true);
            } else {
                System.out.println("⚠ 预期 422, 实际 " + resp.httpStatus);
                results.add(false);
            }
        } catch (Exception e) {
            System.out.println("❌ 异常: " + e.getMessage());
            results.add(false);
        }

        // 4b. 非 http(s) URL
        System.out.println("\n--- 4b. 非 http(s) URL ---");
        try {
            ObjectNode body = MAPPER.createObjectNode();
            body.put("video_url", "ftp://example.com/video.mp4");
            ApiResp resp = postJson(url, body, 10);
            System.out.println("Status: " + resp.httpStatus);
            if (resp.json != null) {
                System.out.println(pretty(resp.json));
            } else {
                System.out.println(resp.raw);
            }
            if (resp.httpStatus == 422) {
                System.out.println("✅ 非 http(s) URL 校验通过（返回 422）");
                results.add(true);
            } else {
                System.out.println("⚠ 预期 422, 实际 " + resp.httpStatus);
                results.add(false);
            }
        } catch (Exception e) {
            System.out.println("❌ 异常: " + e.getMessage());
            results.add(false);
        }

        // 4c. 缺少 video_url 字段
        System.out.println("\n--- 4c. 缺少 video_url ---");
        try {
            ObjectNode body = MAPPER.createObjectNode();
            ApiResp resp = postJson(url, body, 10);
            System.out.println("Status: " + resp.httpStatus);
            if (resp.json != null) {
                System.out.println(pretty(resp.json));
            } else {
                System.out.println(resp.raw);
            }
            if (resp.httpStatus == 422) {
                System.out.println("✅ 缺少字段校验通过（返回 422）");
                results.add(true);
            } else {
                System.out.println("⚠ 预期 422, 实际 " + resp.httpStatus);
                results.add(false);
            }
        } catch (Exception e) {
            System.out.println("❌ 异常: " + e.getMessage());
            results.add(false);
        }

        return results.stream().allMatch(Boolean::booleanValue);
    }

    private static String safeText(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) {
            return "null";
        }
        if (node.isTextual()) {
            return node.asText();
        }
        return node.toString();
    }

    public static void main(String[] args) {
        System.out.println("============================================================");
        System.out.println("  Video Analyze API 测试 (Java)");
        System.out.println("  Base URL: " + BASE_URL);
        System.out.println("  Video:    " + VIDEO_URL);
        System.out.println("============================================================");

        Map<String, Boolean> results = new LinkedHashMap<>();

        results.put("健康检查", testHealth());
        if (!results.get("健康检查")) {
            System.out.println("\n⛔ 服务不可用，跳过后续测试");
            System.exit(1);
            return;
        }

        results.put("参数校验", testValidation());
        results.put("同步分析", testSyncAnalyze());
        results.put("异步任务", testAsyncTask());

        separator("测试结果汇总");
        int passed = 0;
        for (Map.Entry<String, Boolean> e : results.entrySet()) {
            String icon = e.getValue() ? "✅" : "❌";
            System.out.printf("  %s  %s%n", icon, e.getKey());
            if (e.getValue()) {
                passed++;
            }
        }
        System.out.printf("%n  总计: %d/%d 通过%n", passed, results.size());
        System.exit(passed == results.size() ? 0 : 1);
    }
}
