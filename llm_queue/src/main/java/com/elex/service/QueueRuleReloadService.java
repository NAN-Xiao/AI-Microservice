package com.elex.service;

import com.elex.config.LlmQueueProperties;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.PropertySource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * 本地配置文件重载服务。
 *
 * <p>只读取并刷新 {@code llm.queue.queued-paths}，
 * 不重建队列，也不修改队列容量等启动期配置。</p>
 */
@Service
public class QueueRuleReloadService {
    private static final String QUEUED_PATHS_PREFIX = "llm.queue.queued-paths";
    private static final String ASYNC_TASK_PATHS_PREFIX = "llm.queue.async-task-paths";
    private static final String CONFIG_FILE_PROPERTY = "llm.queue.config-file";
    private static final String CONFIG_FILE_ENV = "LLM_QUEUE_CONFIG_FILE";

    private final LlmQueueProperties properties;
    private final QueueRuleService queueRuleService;

    /**
     * 创建本地配置重载服务。
     *
     * @param properties 队列配置
     * @param queueRuleService 入队规则服务
     */
    public QueueRuleReloadService(LlmQueueProperties properties, QueueRuleService queueRuleService) {
        this.properties = properties;
        this.queueRuleService = queueRuleService;
    }

    /**
     * 从本地 YAML 文件重新加载入队规则。
     *
     * @return 当前生效的规则
     * @throws IOException 配置文件读取失败时抛出
     */
    public List<String> reload() throws IOException {
        Resource resource = resolveConfigResource();
        List<PropertySource<?>> sources = loadYaml(resource);
        List<String> queuedPaths = readList(sources, QUEUED_PATHS_PREFIX);
        List<String> asyncTaskPaths = readList(sources, ASYNC_TASK_PATHS_PREFIX);
        properties.setQueuedPaths(queuedPaths);
        properties.setAsyncTaskPaths(asyncTaskPaths);
        return queueRuleService.updateRules(queuedPaths);
    }

    private Resource resolveConfigResource() {
        String configFile = resolveConfigFilePath();
        if (configFile != null && !configFile.isBlank()) {
            return new FileSystemResource(configFile);
        }
        return new ClassPathResource("application.yml");
    }

    private static String resolveConfigFilePath() {
        String propertyValue = System.getProperty(CONFIG_FILE_PROPERTY);
        if (propertyValue != null && !propertyValue.isBlank()) {
            return propertyValue;
        }
        String envValue = System.getenv(CONFIG_FILE_ENV);
        if (envValue != null && !envValue.isBlank()) {
            return envValue;
        }
        return "";
    }

    private static List<PropertySource<?>> loadYaml(Resource resource) throws IOException {
        if (!resource.exists()) {
            throw new IOException("配置文件不存在: " + resource.getDescription());
        }

        YamlPropertySourceLoader loader = new YamlPropertySourceLoader();
        return loader.load("llm-queue-reload", resource);
    }

    private static List<String> readList(List<PropertySource<?>> sources, String prefix) {
        List<String> values = new ArrayList<>();
        for (PropertySource<?> source : sources) {
            for (int i = 0; ; i++) {
                Object value = source.getProperty(prefix + "[" + i + "]");
                if (value == null) {
                    break;
                }
                values.add(String.valueOf(value));
            }
        }
        return values;
    }
}
