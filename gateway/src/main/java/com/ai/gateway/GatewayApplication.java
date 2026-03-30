package com.ai.gateway;

import com.ai.gateway.config.GatewayAuthProperties;
import com.ai.gateway.config.GatewayCorsProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
/**###############################
 * 网关服务应用程序主入口
 *
 * 本类负责启动 Spring Boot 应用。依赖于各类@Configuration、@Component 注解的 Bean，
 * 自动加载和配置网关相关的过滤器（如 AccessLogFilter、AuthFilter）、跨域配置（CorsConfig）、
 * 错误处理器（GatewayErrorHandler）以及健康检查控制器（GatewayHealthController）等。
 *
 * 启动顺序：
 * 1. 加载配置（application.yml、环境变量等）
 * 2. 初始化 Spring 上下文和各相关 Bean
 * 3. 启动嵌入式 Web 服务器（如 Netty）
 * 4. 等待并响应外部请求
 *
 * 注意：主类被 @SpringBootApplication 注解标记，包含 @Configuration、@EnableAutoConfiguration，
 * 以及 @ComponentScan，会自动扫描本包及子包下所有标注的 Spring 组件。
 */

@SpringBootApplication
@EnableConfigurationProperties({GatewayAuthProperties.class, GatewayCorsProperties.class})
public class GatewayApplication {

    /**
     * 应用程序主入口方法
     * @param args 命令行参数
     */
    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
