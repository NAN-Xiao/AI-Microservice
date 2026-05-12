package com.elex;

import com.elex.config.LlmQueueProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

/**
 * llm_queue 服务启动入口。
 *
 * <p>该服务作为 see_through 与上游 ComfyUI 之间的 HTTP 代理：
 * 只对需要串行执行的目标接口进入队列，其余接口直接转发。</p>
 */
@SpringBootApplication
@EnableConfigurationProperties(LlmQueueProperties.class)
public class LlmQueueApplication {
    /**
     * 启动 Spring Boot WebFlux 应用。
     *
     * @param args 命令行参数
     */
    public static void main(String[] args) {
        SpringApplication.run(LlmQueueApplication.class, args);
    }
}
