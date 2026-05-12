package com.elex.service;

import com.elex.config.LlmQueueProperties;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 入队规则判断服务。
 *
 * <p>规则来自配置项 {@code llm.queue.queued-paths}。
 * 服务启动时加载一次；调用 {@code /admin/reload} 后会从本地配置文件重新加载。</p>
 */
@Service
public class QueueRuleService {
    private final LlmQueueProperties properties;
    private final AtomicReference<List<String>> queuedPaths = new AtomicReference<>(List.of());

    /**
     * 创建入队规则服务。
     *
     * @param properties 队列配置
     */
    public QueueRuleService(LlmQueueProperties properties) {
        this.properties = properties;
    }

    /**
     * 初始化入队规则。
     */
    @PostConstruct
    void init() {
        updateRules(properties.getQueuedPaths());
    }

    /**
     * 判断目标路径是否需要进入串行队列。
     *
     * @param targetPath 已剥离代理前缀的目标路径
     * @return true 表示进入队列；false 表示直接转发
     */
    public boolean shouldQueue(String targetPath) {
        List<String> paths = queuedPaths.get();
        if (paths == null || paths.isEmpty()) {
            return false;
        }

        return paths.contains(normalizePath(targetPath));
    }

    /**
     * 更新内存中的入队规则。
     *
     * @param paths 新的目标路径列表
     * @return 更新后的有效规则
     */
    public List<String> updateRules(List<String> paths) {
        List<String> normalized = normalize(paths);
        queuedPaths.set(normalized);
        return normalized;
    }

    /**
     * 获取当前生效的入队规则。
     *
     * @return 当前目标路径列表
     */
    public List<String> currentRules() {
        return queuedPaths.get();
    }

    private static List<String> normalize(List<String> paths) {
        if (paths == null || paths.isEmpty()) {
            return List.of();
        }
        Set<String> normalized = new LinkedHashSet<>();
        for (String path : paths) {
            String normalizedPath = normalizePath(path);
            if (!normalizedPath.isBlank()) {
                normalized.add(normalizedPath);
            }
        }
        return new ArrayList<>(normalized);
    }

    /**
     * 规范化路径写法。
     *
     * <p>配置里允许省略前导斜杠或带末尾斜杠，最终按规范化路径匹配。</p>
     *
     * @param path 原始路径
     * @return 规范化后的路径
     */
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
}
