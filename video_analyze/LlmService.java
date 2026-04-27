import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashSet;
import java.util.Set;
import java.util.logging.Logger;

/**
 * 对应 video_analyze/app/services/llm_service.py 的 Java 版本（JDK 11）。
 * 调用 OpenAI 兼容接口：POST {apiUrl}/chat/completions
 */
public class LlmService {
    private static final Logger LOG = Logger.getLogger(LlmService.class.getName());

    private static final int MAX_RETRIES = 2;
    private static final double RETRY_BACKOFF_SECONDS = 1.0;
    private static final Set<Integer> RETRYABLE_STATUS = new HashSet<Integer>();

    static {
        RETRYABLE_STATUS.add(500);
        RETRYABLE_STATUS.add(502);
        RETRYABLE_STATUS.add(503);
        RETRYABLE_STATUS.add(429);
    }

    private final HttpClient client;
    private final ObjectMapper mapper;
    private final String apiUrl;
    private final String apiKey;
    private final String model;
    private final Duration timeout;

    public LlmService(String apiUrl, String apiKey, String model, int timeoutSeconds) {
        this(HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build(),
                new ObjectMapper(),
                apiUrl,
                apiKey,
                model,
                timeoutSeconds);
    }

    public LlmService(HttpClient client,
                      ObjectMapper mapper,
                      String apiUrl,
                      String apiKey,
                      String model,
                      int timeoutSeconds) {
        this.client = client;
        this.mapper = mapper;
        this.apiUrl = trimRightSlash(apiUrl);
        this.apiKey = apiKey;
        this.model = model;
        this.timeout = Duration.ofSeconds(timeoutSeconds);
    }

    /**
     * 输入视频 URL + prompt，返回 LLM 文本结果。
     */
    public String analyze(String videoUrl, String prompt) throws Exception {
        Exception lastException = null;

        for (int attempt = 0; attempt <= MAX_RETRIES; attempt++) {
            try {
                if (attempt > 0) {
                    double waitSeconds = RETRY_BACKOFF_SECONDS * Math.pow(2, attempt - 1);
                    LOG.info(String.format("LLM 重试 %d/%d (等待 %.1fs): video_url=%s",
                            attempt, MAX_RETRIES, waitSeconds, videoUrl));
                    Thread.sleep((long) (waitSeconds * 1000));
                }

                LOG.info(String.format("调用 LLM: model=%s, video_url=%s", model, videoUrl));

                ObjectNode payload = buildPayload(videoUrl, prompt);
                HttpRequest request = HttpRequest.newBuilder()
                        .uri(URI.create(apiUrl + "/chat/completions"))
                        .timeout(timeout)
                        .header("Content-Type", "application/json")
                        .header("Authorization", "Bearer " + apiKey)
                        .POST(HttpRequest.BodyPublishers.ofString(payload.toString()))
                        .build();

                HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
                int status = response.statusCode();
                String body = response.body();

                if (status >= 400) {
                    LlmHttpException e = new LlmHttpException(status, body);
                    lastException = e;
                    if (RETRYABLE_STATUS.contains(status)) {
                        LOG.warning("LLM HTTP " + status + "，可重试");
                        continue;
                    }
                    throw e;
                }

                JsonNode result = mapper.readTree(body);
                return parseContent(result);

            } catch (LlmHttpException e) {
                lastException = e;
                if (!RETRYABLE_STATUS.contains(e.getStatusCode())) {
                    throw e;
                }

            } catch (IOException e) {
                lastException = e;
                LOG.warning("LLM 连接/超时异常: " + e.getClass().getSimpleName());

            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw e;

            } catch (IllegalArgumentException e) {
                // 响应解析错误不重试
                throw e;
            }
        }

        if (lastException != null) {
            throw lastException;
        }
        throw new IllegalStateException("LLM 调用失败：未知错误");
    }

    private ObjectNode buildPayload(String videoUrl, String prompt) {
        ObjectNode root = mapper.createObjectNode();
        root.put("model", model);

        ArrayNode messages = root.putArray("messages");
        ObjectNode userMsg = messages.addObject();
        userMsg.put("role", "user");

        ArrayNode content = userMsg.putArray("content");
        ObjectNode textPart = content.addObject();
        textPart.put("type", "text");
        textPart.put("text", prompt);

        ObjectNode videoPart = content.addObject();
        videoPart.put("type", "video_url");
        ObjectNode videoObj = videoPart.putObject("video_url");
        videoObj.put("url", videoUrl);

        return root;
    }

    private String parseContent(JsonNode result) {
        JsonNode choices = result.get("choices");
        if (choices == null || !choices.isArray() || choices.size() == 0) {
            throw new IllegalArgumentException("LLM 响应缺少 choices 字段: " + result.fieldNames().toString());
        }

        JsonNode first = choices.get(0);
        JsonNode message = first == null ? null : first.get("message");
        JsonNode content = message == null ? null : message.get("content");
        if (content == null) {
            throw new IllegalArgumentException("LLM 响应缺少 message.content");
        }

        if (content.isTextual()) {
            return content.asText();
        }

        if (content.isArray()) {
            StringBuilder sb = new StringBuilder();
            for (JsonNode part : content) {
                if (part != null
                        && part.isObject()
                        && "text".equals(part.path("type").asText())
                        && part.has("text")) {
                    String text = part.path("text").asText("");
                    if (!text.isEmpty()) {
                        if (sb.length() > 0) {
                            sb.append('\n');
                        }
                        sb.append(text);
                    }
                }
            }
            return sb.toString().trim();
        }

        throw new IllegalArgumentException("LLM 响应 content 类型异常: " + content.getNodeType());
    }

    private static String trimRightSlash(String s) {
        if (s == null) {
            return "";
        }
        String out = s.trim();
        while (out.endsWith("/")) {
            out = out.substring(0, out.length() - 1);
        }
        return out;
    }

    public static class LlmHttpException extends IOException {
        private final int statusCode;
        private final String responseBody;

        public LlmHttpException(int statusCode, String responseBody) {
            super("LLM 服务错误: HTTP " + statusCode);
            this.statusCode = statusCode;
            this.responseBody = responseBody;
        }

        public int getStatusCode() {
            return statusCode;
        }

        public String getResponseBody() {
            return responseBody;
        }
    }
}
